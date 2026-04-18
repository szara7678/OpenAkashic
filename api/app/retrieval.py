from typing import Any

from app.db import get_conn
from app.schemas import QueryRequest
from app.utils import json_ready, normalize_text


_CAPSULE_MODE_FIELDS = {
    "compact": {"id", "title", "summary_head", "confidence", "score"},
    "standard": {
        "id",
        "title",
        "summary",
        "key_points",
        "cautions",
        "confidence",
        "source_claim_ids",
        "score",
    },
    "full": None,  # all columns
}

_CLAIM_MODE_FIELDS = {
    "compact": {"id", "text", "claim_role", "confidence", "score"},
    "standard": {
        "id",
        "text",
        "claim_role",
        "status",
        "confidence",
        "source_weight",
        "mentions",
        "score",
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


def query_memory(payload: QueryRequest) -> dict[str, Any]:
    include = {"evidences" if item == "evidence" else item for item in payload.include}
    normalized_query = normalize_text(payload.query)
    explicit_fields = set(payload.fields or [])
    with get_conn() as conn:
        claims = _search_claims(conn, payload, normalized_query)
        expanded = []
        if payload.options.expand_related_claims and claims:
            expanded = _expand_related_claims(conn, claims, payload)
        combined = _merge_ranked_claims(claims, expanded, payload.top_k)

        claim_ids = [claim["id"] for claim in combined]
        if payload.options.expand_mentions and claim_ids:
            _attach_mentions(conn, combined, claim_ids)

        evidences = _fetch_evidences(conn, claim_ids) if "evidences" in include and claim_ids else []
        capsules = _search_capsules(conn, payload, normalized_query, claim_ids) if "capsules" in include else []
        has_conflict = _has_conflict(conn, claim_ids) if claim_ids else False

    projected_claims = (
        [json_ready(_project_claim(item, payload.mode, explicit_fields)) for item in combined]
        if "claims" in include
        else []
    )
    projected_capsules = [
        json_ready(_project_capsule(item, payload.mode, explicit_fields)) for item in capsules
    ]

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
            "retrieval": "postgres_fts_trigram_mentions_links_capsules",
            "read_path": "db_search_rank_packaging_no_llm",
        },
    }


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
                cap.search_vector @@ q.tsq
                OR lower(cap.title) ILIKE '%%' || q.nq || '%%'
                OR similarity(lower(cap.title), q.nq) > 0.08
                OR cap.source_claim_ids && %(claim_ids)s::uuid[]
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
