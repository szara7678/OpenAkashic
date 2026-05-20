import logging
from typing import Any

from app.config import get_settings
from app.db import get_conn
from app.embeddings import EmbeddingError, embed_one
from app.schemas import QueryRequest
from app.utils import json_ready, normalize_text

logger = logging.getLogger("openakashic.retrieval")


_CAPSULE_MODE_FIELDS = {
    "compact": {
        "id",
        "title",
        "summary_head",
        "confidence",
        "score",
        "semantic_score",
        "rrf_score",
        "related_capsules",
        "related_capsule_ids",
    },
    "standard": {
        "id",
        "title",
        "summary",
        "key_points",
        "cautions",
        "confidence",
        "source_claim_ids",
        "score",
        "semantic_score",
        "rrf_score",
        "related_capsules",
        "related_capsule_ids",
    },
    "full": None,  # all columns
}

_CLAIM_MODE_FIELDS = {
    "compact": {"id", "text", "claim_role", "confidence", "score", "claim_review_status", "semantic_score", "rrf_score"},
    "standard": {
        "id",
        "text",
        "claim_role",
        "status",
        "confidence",
        "source_weight",
        "claim_review_status",
        "confirm_count",
        "dispute_count",
        "mentions",
        "score",
        "semantic_score",
        "rrf_score",
    },
    "full": None,
}


def _project_capsule(row: dict[str, Any], mode: str, explicit_fields: set[str]) -> dict[str, Any]:
    projected = dict(row)
    if "summary" in projected and isinstance(projected["summary"], list):
        projected["summary_head"] = projected["summary"][0] if projected["summary"] else ""
    allowed = _CAPSULE_MODE_FIELDS.get(mode)
    if explicit_fields:
        allowed = explicit_fields | {"id", "title", "score"}
    if allowed is None:
        return projected
    return {k: v for k, v in projected.items() if k in allowed}


def _project_claim(row: dict[str, Any], mode: str, explicit_fields: set[str]) -> dict[str, Any]:
    projected = dict(row)
    allowed = _CLAIM_MODE_FIELDS.get(mode)
    if explicit_fields:
        allowed = explicit_fields | {"id", "text", "score"}
    if allowed is None:
        return projected
    return {k: v for k, v in projected.items() if k in allowed}


def _rrf_merge(
    lex_ranked: list[dict[str, Any]],
    sem_ranked: list[dict[str, Any]],
    *,
    id_key: str,
    top_k: int,
    rrf_k: int,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion over two ordered lists keyed by `id_key`.

    Each input is already sorted (lex by score desc, sem by cosine desc).
    Returns merged list sorted by rrf_score desc, trimmed to top_k. The
    surviving row keeps fields from whichever list provided it first; if
    both, lexical wins for the base row but semantic_score is preserved.
    """
    by_id: dict[Any, dict[str, Any]] = {}
    lex_rank: dict[Any, int] = {}
    sem_rank: dict[Any, int] = {}
    for idx, row in enumerate(lex_ranked):
        key = row[id_key]
        by_id[key] = dict(row)
        lex_rank[key] = idx
    for idx, row in enumerate(sem_ranked):
        key = row[id_key]
        if key not in by_id:
            by_id[key] = dict(row)
        else:
            # carry semantic_score onto existing row
            if "semantic_score" in row and "semantic_score" not in by_id[key]:
                by_id[key]["semantic_score"] = row["semantic_score"]
        sem_rank[key] = idx
    fused: list[tuple[float, dict[str, Any]]] = []
    big = 10_000
    for key, row in by_id.items():
        lr = lex_rank.get(key, big)
        sr = sem_rank.get(key, big)
        rrf = 1.0 / (rrf_k + lr) + 1.0 / (rrf_k + sr)
        row["rrf_score"] = round(float(rrf), 6)
        if "semantic_score" not in row:
            # if only lexical, leave 0.0
            row["semantic_score"] = 0.0
        fused.append((rrf, row))
    fused.sort(key=lambda p: -p[0])
    return [r for _s, r in fused[:top_k]]


def _include_related_capsules(payload: QueryRequest) -> bool:
    return bool(
        getattr(payload, "include_related_capsules", False)
        or getattr(payload.options, "include_related_capsules", False)
    )


def query_memory(payload: QueryRequest) -> dict[str, Any]:
    include = {"evidences" if item == "evidence" else item for item in payload.include}
    normalized_query = normalize_text(payload.query)
    explicit_fields = set(payload.fields or [])
    settings = get_settings()
    rrf_k = max(1, int(settings.rrf_k or 60))
    retrieval_mode = settings.retrieval_mode

    # Embed the query once for both claim + capsule semantic passes.
    query_vec: list[float] | None = None
    try:
        query_vec = embed_one(payload.query, is_query=True)
    except EmbeddingError as exc:
        logger.warning("query embedding failed (falling back to lexical-only): %s", exc)

    embedding_only = retrieval_mode == "embedding" and query_vec is not None
    lexical_fallback = retrieval_mode == "embedding" and query_vec is None

    with get_conn() as conn:
        if embedding_only:
            fused_claims = sorted(
                _search_claims_semantic(conn, payload, query_vec),
                key=lambda row: row.get("score") or 0.0,
                reverse=True,
            )[: payload.top_k]
        else:
            lex_claims = _search_claims(conn, payload, normalized_query)
            sem_claims: list[dict[str, Any]] = []
            if query_vec is not None and "claims" in include:
                sem_claims = _search_claims_semantic(conn, payload, query_vec)
            fused_claims = _rrf_merge(
                lex_claims, sem_claims, id_key="id",
                top_k=max(payload.top_k * 2, payload.top_k), rrf_k=rrf_k,
            )

        expanded = []
        if payload.options.expand_related_claims and fused_claims:
            expanded = _expand_related_claims(conn, fused_claims, payload)
        combined = _merge_ranked_claims(fused_claims, expanded, payload.top_k)

        claim_ids = [claim["id"] for claim in combined]
        if payload.options.expand_mentions and claim_ids:
            _attach_mentions(conn, combined, claim_ids)

        evidences = _fetch_evidences(conn, claim_ids) if "evidences" in include and claim_ids else []

        capsules: list[dict[str, Any]] = []
        if "capsules" in include:
            if embedding_only:
                capsules = sorted(
                    _search_capsules_semantic(conn, payload, query_vec),
                    key=lambda row: row.get("score") or 0.0,
                    reverse=True,
                )[: min(payload.top_k, 8)]
            else:
                lex_caps = _search_capsules(conn, payload, normalized_query, claim_ids)
                sem_caps: list[dict[str, Any]] = []
                if query_vec is not None:
                    sem_caps = _search_capsules_semantic(conn, payload, query_vec)
                capsules = _rrf_merge(
                    lex_caps, sem_caps, id_key="id",
                    top_k=min(payload.top_k, 8), rrf_k=rrf_k,
                )
            if _include_related_capsules(payload) and capsules:
                _attach_related_capsules(conn, capsules)

        has_conflict = _has_conflict(conn, claim_ids) if claim_ids else False

    projected_claims = (
        [json_ready(_project_claim(item, payload.mode, explicit_fields)) for item in combined]
        if "claims" in include
        else []
    )
    projected_capsules = [
        json_ready(_project_capsule(item, payload.mode, explicit_fields)) for item in capsules
    ]
    if embedding_only:
        retrieval = "pgvector_hnsw_embedding_only"
    elif lexical_fallback:
        retrieval = "postgres_fts_lexical_fallback"
    else:
        retrieval = "postgres_fts+pgvector_hnsw+rrf" if query_vec is not None else "postgres_fts_lexical_only"

    return {
        "query": payload.query,
        "results": {
            "claims": projected_claims,
            "evidences": [json_ready(item) for item in evidences],
            "capsules": projected_capsules,
        },
        "meta": {
            "has_conflict": has_conflict,
            "mode": payload.mode,
            "retrieval": retrieval,
            "semantic_model": settings.embedding_model if query_vec is not None else None,
            "rrf_k": rrf_k if query_vec is not None and not embedding_only else None,
            "read_path": "db_search_rank_packaging_no_llm",
        },
    }


def _search_claims_semantic(
    conn, payload: QueryRequest, query_vec: list[float]
) -> list[dict[str, Any]]:
    statuses = payload.filters.status or ["accepted"]
    limit = max(payload.top_k * 3, payload.top_k)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                c.id,
                c.text,
                c.status,
                c.confidence::float AS confidence,
                c.source_weight::float AS source_weight,
                c.claim_role,
                c.metadata,
                coalesce(c.metadata->>'claim_review_status', 'unreviewed') AS claim_review_status,
                greatest(coalesce((c.metadata->>'confirm_count')::int, 0), 0) AS confirm_count,
                greatest(coalesce((c.metadata->>'dispute_count')::int, 0), 0) AS dispute_count,
                c.created_at,
                c.updated_at,
                (1 - (c.embedding <=> %(qv)s::vector))::float AS semantic_score,
                (1 - (c.embedding <=> %(qv)s::vector))::float AS score
            FROM claims c
            WHERE c.embedding IS NOT NULL
              AND c.status = ANY(%(statuses)s)
            ORDER BY c.embedding <=> %(qv)s::vector
            LIMIT %(limit)s
            """,
            {"qv": query_vec, "statuses": statuses, "limit": limit},
        )
        return [dict(row) for row in cur.fetchall()]


def _search_capsules_semantic(
    conn, payload: QueryRequest, query_vec: list[float]
) -> list[dict[str, Any]]:
    limit = max(payload.top_k * 2, 8)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                cap.id,
                cap.title,
                cap.summary,
                cap.key_points,
                cap.cautions,
                cap.source_claim_ids,
                cap.confidence::float AS confidence,
                cap.metadata,
                coalesce(cap.metadata->'related_capsule_ids', '[]'::jsonb) AS related_capsule_ids,
                cap.created_at,
                cap.updated_at,
                (1 - (cap.embedding <=> %(qv)s::vector))::float AS semantic_score,
                (1 - (cap.embedding <=> %(qv)s::vector))::float AS score
            FROM capsules cap
            WHERE cap.embedding IS NOT NULL
              AND COALESCE(cap.metadata->>'dedup_decision','') <> 'supersede'
            ORDER BY cap.embedding <=> %(qv)s::vector
            LIMIT %(limit)s
            """,
            {"qv": query_vec, "limit": limit},
        )
        return [dict(row) for row in cur.fetchall()]


def _search_claims(conn, payload: QueryRequest, normalized_query: str) -> list[dict[str, Any]]:
    statuses = payload.filters.status or ["accepted"]
    limit = max(payload.top_k * 3, payload.top_k)
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH q AS (
                SELECT
                    plainto_tsquery('simple', %(query)s) AS tsq,
                    %(normalized_query)s::text AS nq
            ),
            mention_hits AS (
                SELECT
                    cm.claim_id,
                    max(
                        CASE
                            WHEN cm.normalized_mention = q.nq THEN 0.35
                            WHEN cm.normalized_mention ILIKE '%%' || q.nq || '%%' THEN 0.25
                            ELSE greatest(similarity(cm.normalized_mention, q.nq), 0) * 0.20
                        END
                    ) AS mention_boost
                FROM claim_mentions cm
                CROSS JOIN q
                WHERE
                    cm.normalized_mention = q.nq
                    OR cm.normalized_mention ILIKE '%%' || q.nq || '%%'
                    OR similarity(cm.normalized_mention, q.nq) > 0.15
                GROUP BY cm.claim_id
            )
            SELECT
                c.id,
                c.text,
                c.status,
                c.confidence::float AS confidence,
                    c.source_weight::float AS source_weight,
                    c.claim_role,
                    c.metadata,
                    coalesce(c.metadata->>'claim_review_status', 'unreviewed') AS claim_review_status,
                    greatest(coalesce((c.metadata->>'confirm_count')::int, 0), 0) AS confirm_count,
                    greatest(coalesce((c.metadata->>'dispute_count')::int, 0), 0) AS dispute_count,
                    c.created_at,
                    c.updated_at,
                    (
                        ts_rank_cd(c.search_vector, q.tsq) * 0.55
                        + greatest(similarity(lower(c.text), q.nq), 0) * 0.35
                    + CASE WHEN lower(c.text) ILIKE '%%' || q.nq || '%%' THEN 0.25 ELSE 0 END
                    + coalesce(mh.mention_boost, 0)
                    + c.confidence * 0.08
                    + c.source_weight * 0.07
                    + CASE c.claim_role
                        WHEN 'core' THEN 0.10
                        WHEN 'support' THEN 0.04
                        WHEN 'caution' THEN 0.02
                        ELSE 0
                      END
                    + CASE coalesce(c.metadata->>'claim_review_status', 'unreviewed')
                        WHEN 'confirmed' THEN 0.14
                        WHEN 'disputed' THEN -0.18
                        WHEN 'superseded' THEN -0.42
                        WHEN 'merged' THEN -0.30
                        ELSE 0
                      END
                    + LEAST(greatest(coalesce((c.metadata->>'confirm_count')::int, 0), 0), 12) * 0.015
                    - LEAST(greatest(coalesce((c.metadata->>'dispute_count')::int, 0), 0), 12) * 0.035
                )::float AS score
            FROM claims c
            CROSS JOIN q
            LEFT JOIN mention_hits mh ON mh.claim_id = c.id
            WHERE
                c.status = ANY(%(statuses)s)
                AND (
                    c.search_vector @@ q.tsq
                    OR lower(c.text) ILIKE '%%' || q.nq || '%%'
                    OR similarity(lower(c.text), q.nq) > 0.08
                    OR mh.claim_id IS NOT NULL
                )
            ORDER BY score DESC, c.updated_at DESC
            LIMIT %(limit)s
            """,
            {
                "query": payload.query,
                "normalized_query": normalized_query,
                "statuses": statuses,
                "limit": limit,
            },
        )
        return [dict(row) for row in cur.fetchall()]


def _expand_related_claims(conn, claims: list[dict[str, Any]], payload: QueryRequest) -> list[dict[str, Any]]:
    claim_ids = [claim["id"] for claim in claims[: payload.top_k]]
    if not claim_ids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH linked AS (
                SELECT to_claim_id AS claim_id, link_type FROM claim_links WHERE from_claim_id = ANY(%(claim_ids)s)
                UNION ALL
                SELECT from_claim_id AS claim_id, link_type FROM claim_links WHERE to_claim_id = ANY(%(claim_ids)s)
            )
            SELECT
                c.id,
                c.text,
                c.status,
                c.confidence::float AS confidence,
                c.source_weight::float AS source_weight,
                c.claim_role,
                c.metadata,
                c.created_at,
                c.updated_at,
                (
                    c.confidence * 0.18
                    + c.source_weight * 0.10
                    + CASE max(linked.link_type)
                        WHEN 'supports' THEN 0.28
                        WHEN 'related' THEN 0.20
                        WHEN 'conflicts' THEN 0.18
                        WHEN 'supersedes' THEN 0.18
                        ELSE 0.12
                      END
                    + CASE c.claim_role
                        WHEN 'core' THEN 0.08
                        WHEN 'caution' THEN 0.06
                        ELSE 0.03
                      END
                )::float AS score
            FROM linked
            JOIN claims c ON c.id = linked.claim_id
            WHERE c.status = ANY(%(statuses)s) AND c.id <> ALL(%(claim_ids)s)
            GROUP BY c.id
            ORDER BY score DESC, c.updated_at DESC
            LIMIT %(limit)s
            """,
            {"claim_ids": claim_ids, "statuses": payload.filters.status, "limit": payload.top_k},
        )
        return [dict(row) for row in cur.fetchall()]


def _merge_ranked_claims(
    primary: list[dict[str, Any]], expanded: list[dict[str, Any]], top_k: int
) -> list[dict[str, Any]]:
    by_id: dict[Any, dict[str, Any]] = {}
    for claim in [*primary, *expanded]:
        existing = by_id.get(claim["id"])
        if existing is None or claim["score"] > existing["score"]:
            by_id[claim["id"]] = claim
    return sorted(by_id.values(), key=lambda item: item["score"], reverse=True)[:top_k]


def _attach_mentions(conn, claims: list[dict[str, Any]], claim_ids: list[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT claim_id, mention_text, normalized_mention, role, entity_id
            FROM claim_mentions
            WHERE claim_id = ANY(%(claim_ids)s)
            ORDER BY mention_text
            """,
            {"claim_ids": claim_ids},
        )
        mentions_by_claim: dict[Any, list[dict[str, Any]]] = {}
        for row in cur.fetchall():
            row = dict(row)
            mentions_by_claim.setdefault(row.pop("claim_id"), []).append(json_ready(row))
    for claim in claims:
        claim["mentions"] = mentions_by_claim.get(claim["id"], [])


def _fetch_evidences(conn, claim_ids: list[Any]) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, claim_id, source_type, source_uri, excerpt, hash, note, metadata, created_at
            FROM evidences
            WHERE claim_id = ANY(%(claim_ids)s)
            ORDER BY created_at DESC
            """,
            {"claim_ids": claim_ids},
        )
        return [dict(row) for row in cur.fetchall()]


def _search_capsules(
    conn, payload: QueryRequest, normalized_query: str, claim_ids: list[Any]
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH q AS (
                SELECT plainto_tsquery('simple', %(query)s) AS tsq, %(normalized_query)s::text AS nq
            )
            SELECT
                cap.id,
                cap.title,
                cap.summary,
                cap.key_points,
                cap.cautions,
                cap.source_claim_ids,
                cap.confidence::float AS confidence,
                cap.metadata,
                coalesce(cap.metadata->'related_capsule_ids', '[]'::jsonb) AS related_capsule_ids,
                cap.created_at,
                cap.updated_at,
                (
                    ts_rank_cd(cap.search_vector, q.tsq) * 0.45
                    + greatest(similarity(lower(cap.title), q.nq), 0) * 0.30
                    + CASE WHEN lower(cap.title) ILIKE '%%' || q.nq || '%%' THEN 0.20 ELSE 0 END
                    + CASE WHEN cap.source_claim_ids && %(claim_ids)s::uuid[] THEN 0.35 ELSE 0 END
                    + cap.confidence * 0.10
                )::float AS score
            FROM capsules cap
            CROSS JOIN q
            WHERE
                COALESCE(cap.metadata->>'dedup_decision','') <> 'supersede'
                AND (
                cap.search_vector @@ q.tsq
                OR lower(cap.title) ILIKE '%%' || q.nq || '%%'
                OR similarity(lower(cap.title), q.nq) > 0.08
                OR cap.source_claim_ids && %(claim_ids)s::uuid[]
                )
            ORDER BY score DESC, cap.updated_at DESC
            LIMIT %(limit)s
            """,
            {
                "query": payload.query,
                "normalized_query": normalized_query,
                "claim_ids": claim_ids,
                "limit": min(payload.top_k, 8),
            },
        )
        return [dict(row) for row in cur.fetchall()]


def _attach_related_capsules(conn, capsules: list[dict[str, Any]]) -> None:
    result_ids = [capsule["id"] for capsule in capsules]
    result_id_set = set(result_ids)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, embedding::text AS embedding
            FROM capsules
            WHERE id = ANY(%(result_ids)s::uuid[]) AND embedding IS NOT NULL
            """,
            {"result_ids": result_ids},
        )
        embeddings_by_id = {row["id"]: row["embedding"] for row in cur.fetchall()}
        for capsule in capsules:
            capsule["related_capsules"] = []
            embedding = embeddings_by_id.get(capsule["id"])
            if not embedding:
                continue
            cur.execute(
                """
                SELECT
                    id,
                    title,
                    (1 - (embedding <=> %(embedding)s::vector))::float AS cosine
                FROM capsules
                WHERE embedding IS NOT NULL
                  AND id != %(id)s
                  AND NOT (id = ANY(%(result_ids)s::uuid[]))
                ORDER BY embedding <=> %(embedding)s::vector
                LIMIT 4
                """,
                {"id": capsule["id"], "embedding": embedding, "result_ids": result_ids},
            )
            related = []
            seen_ids = set()
            for row in cur.fetchall():
                row = dict(row)
                if row["id"] in result_id_set or row["id"] == capsule["id"] or row["id"] in seen_ids:
                    continue
                if row["cosine"] is None or float(row["cosine"]) < 0.55:
                    continue
                seen_ids.add(row["id"])
                related.append(
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "cosine": float(row["cosine"]),
                    }
                )
                if len(related) >= 3:
                    break
            capsule["related_capsules"] = related


def _has_conflict(conn, claim_ids: list[Any]) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM claim_links
                WHERE link_type = 'conflicts'
                  AND (from_claim_id = ANY(%(claim_ids)s) OR to_claim_id = ANY(%(claim_ids)s))
            ) AS has_conflict
            """,
            {"claim_ids": claim_ids},
        )
        row = cur.fetchone()
        return bool(row and row["has_conflict"])
