from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.db import close_pool, get_conn
from app.retrieval import query_memory
from app.schemas import (
    CapsuleCreate,
    ClaimCreate,
    ClaimStatusUpdate,
    EntityCreate,
    EvidenceCreate,
    QueryRequest,
)
from app.security import require_write_key
from app.utils import extract_mentions, json_ready, normalize_text

settings = get_settings()

app = FastAPI(
    title="OpenAkashic Core",
    version="0.1.0",
    description="Claim/evidence/capsule based public memory store for external agents.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
def shutdown() -> None:
    close_pool()


@app.get("/", response_model=None)
def root(request: Request):
    host = request.headers.get("host", "")
    if host.startswith("personal."):
        return RedirectResponse(url="https://knowledge.openakashic.com", status_code=307)
    return {
        "name": "OpenAkashic Core",
        "version": "0.1.0",
        "definition": "A public memory store that retrieves claim/evidence and returns structured capsules for agents.",
        "docs": "/docs",
        "health": "/health",
        "query": "POST /query",
        "mcp": "POST /mcp",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()
    return {"status": "ok"}


@app.post("/query")
def query(payload: QueryRequest) -> dict[str, Any]:
    return query_memory(payload)


@app.post("/claims", dependencies=[Depends(require_write_key)])
def create_claim(payload: ClaimCreate) -> dict[str, Any]:
    if payload.status == "accepted":
        raise HTTPException(
            status_code=409,
            detail="Create claims as pending, attach evidence, then PATCH /claims/{id}/status to accepted",
        )
    data = payload.model_dump(exclude={"mentions"})
    data["metadata"] = Jsonb(data["metadata"])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO claims (text, status, confidence, source_weight, claim_role, metadata)
                VALUES (%(text)s, %(status)s, %(confidence)s, %(source_weight)s, %(claim_role)s, %(metadata)s)
                RETURNING id, text, status, confidence::float AS confidence, source_weight::float AS source_weight,
                          claim_role, metadata, created_at, updated_at
                """,
                data,
            )
            claim = dict(cur.fetchone())
            mentions = payload.mentions or [
                {"mention_text": item, "role": "auto", "entity_id": None}
                for item in extract_mentions(payload.text)
            ]
            for mention in mentions:
                mention_text = mention["mention_text"] if isinstance(mention, dict) else mention.mention_text
                role = mention.get("role") if isinstance(mention, dict) else mention.role
                entity_id = mention.get("entity_id") if isinstance(mention, dict) else mention.entity_id
                cur.execute(
                    """
                    INSERT INTO claim_mentions (claim_id, mention_text, normalized_mention, role, entity_id)
                    VALUES (%(claim_id)s, %(mention_text)s, %(normalized_mention)s, %(role)s, %(entity_id)s)
                    ON CONFLICT (claim_id, normalized_mention) DO NOTHING
                    """,
                    {
                        "claim_id": claim["id"],
                        "mention_text": mention_text,
                        "normalized_mention": normalize_text(mention_text),
                        "role": role,
                        "entity_id": entity_id,
                    },
                )
        conn.commit()
    return json_ready(claim)


@app.get("/claims/{claim_id}")
def get_claim(claim_id: UUID) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, text, status, confidence::float AS confidence, source_weight::float AS source_weight,
                       claim_role, metadata, created_at, updated_at
                FROM claims
                WHERE id = %(id)s
                """,
                {"id": claim_id},
            )
            claim = cur.fetchone()
            if not claim:
                raise HTTPException(status_code=404, detail="Claim not found")
            claim = dict(claim)
            cur.execute(
                """
                SELECT id, mention_text, normalized_mention, role, entity_id, created_at
                FROM claim_mentions
                WHERE claim_id = %(id)s
                ORDER BY mention_text
                """,
                {"id": claim_id},
            )
            claim["mentions"] = [json_ready(dict(row)) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT id, source_type, source_uri, excerpt, hash, note, metadata, created_at
                FROM evidences
                WHERE claim_id = %(id)s
                ORDER BY created_at DESC
                """,
                {"id": claim_id},
            )
            claim["evidences"] = [json_ready(dict(row)) for row in cur.fetchall()]
    return json_ready(claim)


@app.patch("/claims/{claim_id}/status", dependencies=[Depends(require_write_key)])
def update_claim_status(claim_id: UUID, payload: ClaimStatusUpdate) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if payload.status == "accepted":
                cur.execute("SELECT count(*) AS count FROM evidences WHERE claim_id = %(id)s", {"id": claim_id})
                if cur.fetchone()["count"] < 1:
                    raise HTTPException(status_code=409, detail="Accepted claims require at least one evidence")
            cur.execute(
                """
                UPDATE claims
                SET status = %(status)s
                WHERE id = %(id)s
                RETURNING id, text, status, confidence::float AS confidence, source_weight::float AS source_weight,
                          claim_role, metadata, created_at, updated_at
                """,
                {"id": claim_id, "status": payload.status},
            )
            claim = cur.fetchone()
            if not claim:
                raise HTTPException(status_code=404, detail="Claim not found")
        conn.commit()
    return json_ready(dict(claim))


@app.post("/evidences", dependencies=[Depends(require_write_key)])
def create_evidence(payload: EvidenceCreate) -> dict[str, Any]:
    data = payload.model_dump()
    data["metadata"] = Jsonb(data["metadata"])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM claims WHERE id = %(claim_id)s", {"claim_id": payload.claim_id})
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Claim not found")
            cur.execute(
                """
                INSERT INTO evidences (claim_id, source_type, source_uri, excerpt, hash, note, metadata)
                VALUES (%(claim_id)s, %(source_type)s, %(source_uri)s, %(excerpt)s, %(hash)s, %(note)s, %(metadata)s)
                RETURNING id, claim_id, source_type, source_uri, excerpt, hash, note, metadata, created_at
                """,
                data,
            )
            evidence = dict(cur.fetchone())
        conn.commit()
    return json_ready(evidence)


@app.get("/evidences/{evidence_id}")
def get_evidence(evidence_id: UUID) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, claim_id, source_type, source_uri, excerpt, hash, note, metadata, created_at
                FROM evidences
                WHERE id = %(id)s
                """,
                {"id": evidence_id},
            )
            evidence = cur.fetchone()
            if not evidence:
                raise HTTPException(status_code=404, detail="Evidence not found")
    return json_ready(dict(evidence))


@app.post("/capsules", dependencies=[Depends(require_write_key)])
def create_capsule(payload: CapsuleCreate) -> dict[str, Any]:
    data = payload.model_dump()
    data["summary"] = Jsonb(data["summary"])
    data["key_points"] = Jsonb(data["key_points"])
    data["cautions"] = Jsonb(data["cautions"])
    data["metadata"] = Jsonb(data["metadata"])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO capsules (title, summary, key_points, cautions, source_claim_ids, confidence, metadata)
                VALUES (%(title)s, %(summary)s, %(key_points)s, %(cautions)s, %(source_claim_ids)s, %(confidence)s, %(metadata)s)
                RETURNING id, title, summary, key_points, cautions, source_claim_ids,
                          confidence::float AS confidence, metadata, created_at, updated_at
                """,
                data,
            )
            capsule = dict(cur.fetchone())
        conn.commit()
    return json_ready(capsule)


@app.get("/capsules/{capsule_id}")
def get_capsule(capsule_id: UUID) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, summary, key_points, cautions, source_claim_ids,
                       confidence::float AS confidence, metadata, created_at, updated_at
                FROM capsules
                WHERE id = %(id)s
                """,
                {"id": capsule_id},
            )
            capsule = cur.fetchone()
            if not capsule:
                raise HTTPException(status_code=404, detail="Capsule not found")
    return json_ready(dict(capsule))


@app.get("/mentions/search")
def search_mentions(q: str = Query(min_length=1), limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    nq = normalize_text(q)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT mention_text, normalized_mention, count(*)::int AS claim_count
                FROM claim_mentions
                WHERE normalized_mention ILIKE '%%' || %(q)s || '%%' OR similarity(normalized_mention, %(q)s) > 0.15
                GROUP BY mention_text, normalized_mention
                ORDER BY claim_count DESC, similarity(normalized_mention, %(q)s) DESC
                LIMIT %(limit)s
                """,
                {"q": nq, "limit": limit},
            )
            rows = [dict(row) for row in cur.fetchall()]
    return {"query": q, "mentions": rows}


@app.post("/entities", dependencies=[Depends(require_write_key)])
def create_entity(payload: EntityCreate) -> dict[str, Any]:
    data = payload.model_dump(exclude={"aliases"})
    data["metadata"] = Jsonb(data["metadata"])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO entities (entity_key, canonical_name, entity_type, status, metadata)
                VALUES (%(entity_key)s, %(canonical_name)s, %(entity_type)s, %(status)s, %(metadata)s)
                RETURNING id, entity_key, canonical_name, entity_type, status, metadata, created_at, updated_at
                """,
                data,
            )
            entity = dict(cur.fetchone())
            for alias in payload.aliases:
                cur.execute(
                    """
                    INSERT INTO entity_aliases (entity_id, alias, normalized_alias)
                    VALUES (%(entity_id)s, %(alias)s, %(normalized_alias)s)
                    ON CONFLICT (entity_id, normalized_alias) DO NOTHING
                    """,
                    {
                        "entity_id": entity["id"],
                        "alias": alias,
                        "normalized_alias": normalize_text(alias),
                    },
                )
        conn.commit()
    return json_ready(entity)


@app.get("/entities/search")
def search_entities(q: str = Query(min_length=1), limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    nq = normalize_text(q)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT e.id, e.entity_key, e.canonical_name, e.entity_type, e.status, e.metadata,
                       greatest(similarity(lower(e.canonical_name), %(q)s), coalesce(similarity(ea.normalized_alias, %(q)s), 0)) AS score
                FROM entities e
                LEFT JOIN entity_aliases ea ON ea.entity_id = e.id
                WHERE
                    lower(e.canonical_name) ILIKE '%%' || %(q)s || '%%'
                    OR ea.normalized_alias ILIKE '%%' || %(q)s || '%%'
                    OR similarity(lower(e.canonical_name), %(q)s) > 0.15
                    OR similarity(ea.normalized_alias, %(q)s) > 0.15
                ORDER BY score DESC
                LIMIT %(limit)s
                """,
                {"q": nq, "limit": limit},
            )
            rows = [json_ready(dict(row)) for row in cur.fetchall()]
    return {"query": q, "entities": rows}


@app.post("/mcp")
def mcp_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    method = payload.get("method")
    request_id = payload.get("id")
    params = payload.get("params") or {}

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "openakashic-core", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            result = {"tools": _mcp_tools()}
        elif method == "tools/call":
            result = _mcp_call_tool(params)
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
    except HTTPException as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": exc.status_code, "message": exc.detail}}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}

    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "openakashic.query",
            "description": "Search OpenAkashic claims/evidences/capsules with the common query schema.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 8},
                    "include": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["query"],
            },
        },
        {"name": "openakashic.get_claim", "description": "Get a claim by UUID.", "inputSchema": _id_schema("claim_id")},
        {"name": "openakashic.get_evidence", "description": "Get evidence by UUID.", "inputSchema": _id_schema("evidence_id")},
        {"name": "openakashic.get_capsule", "description": "Get a capsule by UUID.", "inputSchema": _id_schema("capsule_id")},
    ]


def _id_schema(name: str) -> dict[str, Any]:
    return {"type": "object", "properties": {name: {"type": "string", "format": "uuid"}}, "required": [name]}


def _mcp_call_tool(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name == "openakashic.query":
        result = query(QueryRequest(**arguments))
    elif name == "openakashic.get_claim":
        result = get_claim(UUID(arguments["claim_id"]))
    elif name == "openakashic.get_evidence":
        result = get_evidence(UUID(arguments["evidence_id"]))
    elif name == "openakashic.get_capsule":
        result = get_capsule(UUID(arguments["capsule_id"]))
    else:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {name}")
    return {"content": [{"type": "text", "text": str(result)}], "structuredContent": result}
