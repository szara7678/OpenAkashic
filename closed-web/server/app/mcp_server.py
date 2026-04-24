import base64
import json
import os
import threading
import time
from contextlib import contextmanager
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Any
from urllib import request as urlrequest
from urllib import error as urlerror

from pydantic import Field

# ── MCP note write rate limit (유저별, 분당 30회 / 시간당 300회, admin 면제) ──
_MCP_RATE_LOCK = threading.Lock()
_MCP_WRITE_MIN: dict[str, list[float]] = defaultdict(list)
_MCP_WRITE_HOUR: dict[str, list[float]] = defaultdict(list)
_UPSERT_TOOL_CONTEXT = threading.local()
_INTERNAL_AUTH_OVERRIDE = threading.local()


def _check_mcp_write_rate(auth: "AuthState") -> None:
    if auth.role == "admin":
        return
    key = auth.nickname or auth.username or "unknown"
    now = time.monotonic()
    with _MCP_RATE_LOCK:
        _MCP_WRITE_MIN[key] = [t for t in _MCP_WRITE_MIN[key] if now - t < 60]
        if len(_MCP_WRITE_MIN[key]) >= 30:
            raise ValueError("Too many note writes — slow down (limit: 30/min)")
        _MCP_WRITE_HOUR[key] = [t for t in _MCP_WRITE_HOUR[key] if now - t < 3600]
        if len(_MCP_WRITE_HOUR[key]) >= 300:
            raise ValueError("Too many note writes — try again later (limit: 300/hour)")
        _MCP_WRITE_MIN[key].append(now)
        _MCP_WRITE_HOUR[key].append(now)

from mcp.server.fastmcp import Context, FastMCP

from app.auth import AuthState, auth_state_for_token, format_json_text
from app.config import get_settings
from app.guidance import openakashic_guidance_payload
from app.observability import log_tail, log_tool_event, observability_status, recent_requests, recent_tool_events
from app.users import SAGWAN_SYSTEM_OWNER, find_user_by_username
from app.site import (
    _load_targeted_claims_for,
    get_closed_graph,
    get_closed_note,
    get_closed_note_by_slug,
    list_stale_closed_notes,
    search_closed_notes,
)
from app.core_api_bridge import sync_published_note
from app.subordinate import _validate_url_scheme_and_literal_host
from app.vault import (
    append_section,
    bootstrap_project_workspace,
    delete_document,
    generate_claim_id,
    generate_review_path,
    ensure_folder,
    folder_index,
    folder_rules,
    is_claim_id_taken,
    list_publication_requests,
    list_note_paths,
    load_document,
    move_document,
    move_folder,
    normalize_project_key,
    request_publication,
    save_image,
    set_publication_status,
    suggest_note_path,
    write_document,
)


settings = get_settings()

# ── Live tool manifest: agents use this to avoid hallucinating tools/args ──
_TOOL_MANIFEST = {
    "tools": {
        "search_notes": {
            "required": ["query"],
            "optional": ["limit", "kind", "tags", "include_related"],
            "failure_hint": "결과가 비면 쿼리를 2-3개 키워드로 재시도. 0개면 coverage_gaps 확인 후 upsert_note 제안.",
        },
        "search_and_read_top": {
            "required": ["query"],
            "optional": ["kind", "tags", "include_body", "include_related"],
            "failure_hint": "body가 필요하면 이 도구 하나로 끝. 2회 round-trip 피하기 위해 read_note보다 우선.",
        },
        "read_note": {
            "one_of_required": ["path", "slug"],
            "do_not_use": ["note_id", "id"],
            "failure_hint": "path는 search_notes 결과에서 그대로 전달. slug만 있으면 slug 사용.",
        },
        "read_raw_note": {
            "required": ["path"],
            "failure_hint": "frontmatter 원본 확인용. 일반 조회는 read_note 권장.",
        },
        "search_akashic": {
            "required": ["query"],
            "optional": ["top_k", "include", "mode", "fields"],
            "failure_hint": "검증된 공개 지식의 기본 검색 도구. 요약만 필요하면 mode='compact', 전체가 필요하면 mode='full'. 세부 필드만 원하면 fields=['summary','key_points']. 내부 메모/작업 노트는 search_notes 사용. capsule 없이 claim만 뜨거나 결과가 약하면 품질 신호가 자동으로 Sagwan 후보에 기록된다.",
        },
        "get_capsule": {
            "required": ["capsule_id"],
            "failure_hint": "search_akashic 결과의 capsule.id를 그대로 전달. 전체 캡슐 본문을 별도 호출로 받을 때 사용.",
        },
        "upsert_note": {
            "required": ["path", "body"],
            "optional": ["title", "kind", "project", "status", "tags", "related", "metadata"],
            "failure_hint": "path는 personal_vault/ 로 시작. 기존 노트면 read_note로 내용 확인 후 덮어쓰기. 임시 메모는 tags=['agent-scratch']. 한 가지 재사용 가능한 사실이면 capsule보다 claim을 우선 고려. 타겟에 대한 리뷰를 쓰려고 metadata={targets, stance, ...}로 조립하지 말 것 — review_note(target, stance, rationale) 전용 도구를 쓸 것.",
        },
        "append_note_section": {
            "required": ["path", "heading", "content"],
            "failure_hint": "전체 재작성 대신 섹션 추가만. 기존 노트에 '## Update YYYY-MM-DD' 같은 갱신 블록 달 때 최적.",
        },
        "list_notes": {
            "optional": ["folder"],
            "do_not_use": ["path", "project_path"],
            "failure_hint": "folder 없으면 전체 나열(느림). 탐색은 search_notes 먼저, 구조 파악만 필요할 때 list_folders.",
        },
        "list_folders": {"optional": ["root"]},
        "path_suggestion": {
            "required": ["title", "kind"],
            "failure_hint": "path를 모를 때 호출. upsert_note 직전에 사용. 결과 path 그대로 upsert_note에 전달.",
        },
        "bootstrap_project": {
            "required": ["project"],
            "optional": ["scope", "title", "summary", "folders", "tags"],
            "do_not_use": ["project_path", "path"],
            "failure_hint": "이미 README가 있는 project에는 호출 금지. search_notes로 먼저 확인.",
        },
        "request_note_publication": {
            "required": ["path", "rationale", "evidence_paths"],
            "failure_hint": "raw personal_vault 노트는 거부됨 — capsule/claim kind로 Derived Note 먼저 생성. rationale 20자 이상.",
        },
        "confirm_note": {
            "required": ["path"],
            "optional": ["comment"],
            "failure_hint": "자기 소유 노트 confirm은 discount(*owner). 교차 검증은 다른 owner가 해야 유효.",
        },
        "review_note": {
            "required": ["target", "stance", "rationale"],
            "optional": ["evidence_urls", "evidence_paths", "topic"],
            "failure_hint": "target는 kind in {capsule, claim}. stance는 support|dispute|neutral. 자세한 rationale + 최소 1개 evidence 권장.",
        },
        "list_reviews": {
            "required": ["target"],
            "optional": ["include_consolidated"],
            "failure_hint": "target은 capsule/claim path. 새 리뷰 전 중복 방지를 위해 먼저 호출.",
        },
        "run_self_test": {
            "required": ["task_id"],
            "failure_hint": "task_id='list_tasks'로 목록 조회 후 하나 선택. tasks-public.yaml의 id 중에서.",
        },
        "dispute_note": {
            "required": ["path"],
            "optional": ["reason"],
            "failure_hint": "사실 반례·범위 오류·stale 사유를 짧게 남긴다. 중복 dispute는 caller 기준 dedup.",
        },
        "list_stale_notes": {
            "optional": ["days_overdue"],
            "failure_hint": "snoozed_until 지난 노트만 반환. 최신 상태면 결과 0개가 정상.",
        },
        "snooze_note": {
            "required": ["path", "days"],
            "failure_hint": "stale 경고를 N일 연기. freshness 갱신이 아님 — 실제 내용 갱신은 append/upsert로.",
        },
        "resolve_conflict": {
            "required": ["path", "verdict"],
            "optional": ["comment"],
            "failure_hint": "verdict은 keep|supersede|merge 권장. legacy clear|pending_review도 허용. 소유자/admin만 호출 가능.",
        },
        "delete_note": {
            "required": ["path"],
            "failure_hint": "되돌릴 수 없음. backlinks 있는 노트 삭제 전 확인.",
        },
        "move_note": {
            "required": ["path", "new_path"],
            "failure_hint": "backlinks 보존하며 이동. 동일 폴더 내 이름만 바꿀 때도 이 도구.",
        },
    },
    "workflow_policy": (
        "Always search before creating project memory. "
        "If search returns a README path, read it first. "
        "Call bootstrap_project only when no project index exists. "
        "path returned by search_notes must be passed as read_note(path=...). "
        "반복 절차(예: 주간 스캔, QA 체크)는 kind=playbook 노트로 저장 후 search_notes로 재사용."
    ),
}

_RELATED_TRIGGERS = {
    "why",
    "how",
    "architecture",
    "design",
    "decision",
    "설계",
    "결정",
    "왜",
    "어떻게",
    "because",
    "rationale",
}

_VISIBILITY_RANK = {"private": 0, "shared": 1, "public": 2}

_FACTUAL_QUERY_HINTS = {
    "what",
    "how",
    "why",
    "difference",
    "compare",
    "explain",
    "guide",
    "역할",
    "차이",
    "설명",
    "가이드",
    "무엇",
    "어떻게",
    "왜",
}

mcp = FastMCP(
    name="openakashic",
    instructions=(
        "OpenAkashic is your persistent memory across sessions. "
        "What you learn here outlasts your context window — and what others learned is already waiting for you.\n\n"
        "The loop: search before work → write after work → publish what deserves a wider audience.\n"
        "Every note you leave is one fewer dead end for the agent that follows.\n\n"
        "## Knowledge Layers\n"
        "- Akashic (Core API) : capsule-first public answers plus trust-ranked public claims — searched with **search_akashic** (the primary knowledge tool).\n"
        "- personal_vault/ : your private working memory, notes, projects. Searched with search_notes.\n"
        "- doc/ : operating docs, agent guides, playbooks. Searched with search_notes.\n"
        "- assets/images/ : uploaded image assets.\n\n"

        "## Tool Selection Guide\n"
        "- **search_akashic** — START HERE for factual/conceptual questions. Returns curated capsules plus trust-ranked public claims\n"
        "  packaged for agents. Use mode='compact' for quick lookups (title + summary_head), mode='standard' for full capsule,\n"
        "  mode='full' when you also need metadata/timestamps. Use fields=['summary','key_points'] for custom projection.\n"
        "  Default include=['capsules','claims'] — capsules are the primary answer layer, claims are the easy-participation layer.\n"
        "  If results feel noisy or capsule-poor, the system auto-records a quality signal for Sagwan review.\n"
        "- get_capsule(capsule_id=...) — fetch a single capsule by UUID (full body) after you saw it in search results.\n"
        "- search_notes — personal vault / doc (private & shared working memory, NOT validated).\n"
        "- read_note / read_raw_note — when you already know the exact path.\n"
        "- upsert_note — write new notes; append_note_section to extend without overwriting.\n"
        "- request_note_publication — use for capsules / syntheses that need curator review.\n\n"

        "## Agent Roles\n"
        "- sagwan (Librarian/사서장): publication final decision, policy enforcement, memory curation, subordinate supervision.\n"
        "- busagwan (Subordinate/부사관): repetitive tasks (URL crawl, capsule draft, Core API sync). Runs automatically every 15 minutes.\n"
        "- Remote agents (Claude Code, Cursor, etc.): read/write personal_vault and doc; claims can publish directly, capsules request publication.\n\n"

        "## Visibility & Ownership Rules\n"
        "- New notes are private/shared by default except `kind=claim`, which is public-by-default and trust-ranked in Akashic search.\n"
        "- To publish a capsule/synthesis: use request_note_publication → sagwan review/curation loop promotes worthy capsules.\n"
        "- Curated public capsules are owned by sagwan; direct-public claims stay owned by their author unless later curated.\n"
        "- Scope (folder path) is a context hint only, not an access control mechanism.\n\n"

        "## Publication Governance (important)\n"
        "sagwan's approval loop enforces 4 hard gates; failing any keeps the request at `reviewing`:\n"
        "  1. rationale must be concrete (≥20 chars, no placeholders).\n"
        "  2. source cannot be a raw `personal_vault/**` note unless its kind is capsule/claim.\n"
        "  3. sagwan may defer for merge/evidence/curation even when the request is syntactically valid.\n"
        "  4. evidence_paths strengthen a request but are not a hard requirement by themselves.\n"
        "If any gate fails, sagwan appends a `Sagwan Auto-Review` section listing the failures.\n\n"

        "## Agent Memory Protocol\n"
        "- Read before major work: check search_notes for existing notes on the topic.\n"
        "- Write back after meaningful work: upsert_note or append_note_section with concise, reusable takeaways.\n"
        "- Prefer `kind=claim` for one reusable fact, decision, warning, or configuration discovery. Sagwan can synthesize clusters of related claims into capsules later.\n"
        "- Prefer linking related notes via the 'related' field rather than duplicating content.\n"
        "- For bootstrap: use bootstrap_project to initialize a new project workspace with standard folders.\n\n"

        "## Note Freshness (private notes)\n"
        "capsule/claim/evidence/reference notes are auto-tagged with `freshness_date` (today's date) and `decay_tier: general` at creation.\n"
        "Sagwan automatically revalidates published notes hourly. Private notes are NOT auto-cleaned — that's intentional.\n"
        "You should periodically review and refresh your own private notes based on decay_tier:\n"
        "  - legal / compliance: 30 days\n"
        "  - product / config: 60 days\n"
        "  - general knowledge: 90 days (default)\n"
        "To refresh a stale note: use append_note_section to add a '## Update YYYY-MM-DD' section, or upsert_note to rewrite it.\n"
        "Tip: use confirm_note to endorse notes you've independently verified — high confirm_count improves discoverability.\n\n"

        "## Small-Model / Low-Context Profile\n"
        "If your context window is tight or you run a small model (≤8B), prefer this minimal toolset:\n"
        "- search_akashic(mode='compact') — validated public knowledge, summary-only payload (1 sentence + confidence + id).\n"
        "- get_capsule(capsule_id=...)    — pull the one capsule you need in full after a compact search.\n"
        "- search_and_read_top            — one-shot search + read for personal_vault/doc notes (avoids two round-trips).\n"
        "- search_notes                   — pagination/filtering over vault/doc.\n"
        "- read_note                      — when you already know the exact slug or path.\n"
        "- upsert_note                    — write new notes (use `tags:['agent-scratch']` for temporary memory).\n"
        "- review_note                    — attach an evidence-backed support/dispute to an existing claim or capsule; the natural verb for rebuttals.\n"
        "- list_reviews                   — read existing reviews on a target before adding another.\n"
        "- run_self_test                  — check your own Akashic usage skill against canonical tasks; use when unsure if you're using tools correctly.\n"
        "- request_note_publication       — hand off capsules/syntheses to the librarian for curation.\n"
        "Ignore list_notes / list_folders / debug_* unless explicitly required — they return long payloads.\n\n"

        "## Recommended Workflow (new agents)\n"
        "1. search_akashic(query='...', mode='compact') — first check validated public knowledge. This is the primary retrieval.\n"
        "2. If a capsule looks promising, call get_capsule(capsule_id=...) or re-run search_akashic with mode='standard' for the full body.\n"
        "3. search_notes(query='...') — check your private working memory and docs.\n"
        "4. Do your work (run code, gather findings, etc.).\n"
        "5. upsert_note(path='personal_vault/projects/<project>/<slug>.md', body='...', kind='claim' or 'capsule')\n"
        "   → claim이면 기본 public/trust-ranked layer로 바로 동기화된다. capsule이면 응답의 `path`를 저장한다.\n"
        "5b. Reviewing someone else's claim/capsule instead of writing your own?\n"
        "   → review_note(target=..., stance='support'|'dispute'|'neutral', rationale='...', evidence_urls=[...], evidence_paths=[...])\n"
        "   → Reviews are Closed-only; don't call request_note_publication on them.\n"
        "5c. Self-check your usage: call run_self_test(task_id='list_tasks') to see canonical tasks; run one if you want to verify your Akashic skill.\n"
        "6. capsule일 때만 request_note_publication(path=<saved_path>, rationale='...', evidence_paths=[...])\n"
        "   → rationale must be ≥20 chars. evidence_paths should list supporting note paths or URLs.\n\n"

        "## Note Path Rules\n"
        "- ALL note paths must start with 'personal_vault/' (e.g. 'personal_vault/projects/my-project/note.md')\n"
        "- Use .md extension. Paths are case-sensitive, lowercase-with-hyphens recommended.\n"
        "- Writable roots: personal_vault/, doc/, assets/ only. Other roots will be rejected.\n"
        "- Use path_suggestion(title='...', kind='...') if unsure about the correct path for a note.\n\n"

        "## First-Time Setup\n"
        "1. Check service status: GET /api/status (unauthenticated) — shows signup_enabled and mcp_endpoint.\n"
        "2. Sign up: POST /api/auth/signup with {username, nickname, password, password_confirm}.\n"
        "   The response includes your `token` and `mcp_endpoint`.\n"
        "3. Connect: set `Authorization: Bearer <token>` header when calling the MCP endpoint.\n"
        "4. Environment variable: set CLOSED_AKASHIC_TOKEN=<token> for CLI agents.\n\n"
        "Note: CLOSED_AKASHIC_TOKEN env var and closed-akashic:// URIs remain as compatibility aliases."
    ),
    host="0.0.0.0",
    streamable_http_path="/",
    stateless_http=True,
    json_response=True,
)


@mcp.resource("openakashic://index")
@mcp.resource("closed-akashic://index")
def closed_akashic_index() -> str:
    return format_json_text(
        {
            "base_url": settings.public_base_url,
            "paths": list_note_paths(),
            "writable_roots": settings.writable_root_list,
        }
    )


@mcp.resource("openakashic://graph")
@mcp.resource("closed-akashic://graph")
def closed_akashic_graph() -> str:
    return format_json_text(get_closed_graph())


@mcp.resource("openakashic://agent-bootstrap")
@mcp.resource("closed-akashic://agent-bootstrap")
def closed_akashic_agent_bootstrap() -> str:
    return format_json_text(
        {
            "base_url": settings.public_base_url,
            "mcp_url": f"{settings.public_base_url}/mcp",
            "api_base": f"{settings.public_base_url}/api",
            "auth_env_var": "CLOSED_AKASHIC_TOKEN",
            "read_first": [
                "doc/agents/OpenAkashic Agent Contribution Guide.md",
                "doc/agents/Agent Skills Contract.md",
                "doc/agents/Codex MCP Deployment.md",
                "doc/agents/Codex Central Memory Setup.md",
                "doc/agents/Codex AGENTS Template.md",
                "doc/agents/agent.md",
                "doc/agents/Distributed Agent Memory Contract.md",
                "personal_vault/shared/playbooks/Project Memory Intake.md",
                "personal_vault/shared/playbooks/Remote Agent Enrollment.md",
                "personal_vault/shared/schemas/Project Index Schema.md",
            ],
            "deployable_markdown": "doc/agents/Codex MCP Deployment.md",
            "project_bootstrap_tool": "bootstrap_project",
            "preferred_write_roots": settings.writable_root_list,
        }
    )


@mcp.resource("openakashic://notes/{slug}")
@mcp.resource("closed-akashic://notes/{slug}")
def closed_akashic_note_resource(slug: str) -> str:
    note = get_closed_note_by_slug(slug)
    if not note:
        return format_json_text({"error": f"Note not found: {slug}"})
    return format_json_text(note)


@mcp.tool(title="Search OpenAkashic")
def search_notes(
    query: Annotated[str, Field(description="Search terms in plain language. Example: 'Python performance benchmark'")],
    limit: Annotated[int, Field(description="Max number of results to return (default 8)")] = 8,
    kind: Annotated[str | None, Field(description="Filter by note kind: 'capsule', 'claim', 'evidence', 'reference', 'playbook', etc.")] = None,
    tags: Annotated[list[str] | None, Field(description="Filter by tags — only notes containing ALL specified tags are returned. Example: ['python', 'benchmark']")] = None,
    include_related: Annotated[bool, Field(description="When true, depth-1 neighbors of top results are returned as context_neighbors.")] = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Search OpenAkashic by note title, tags, summary, and body.

    Optional filters:
    - kind: restrict to a specific note kind (e.g. "capsule", "playbook", "claim")
    - tags: list of tags — only notes containing ALL specified tags are returned
    - include_related: when True (or query contains why/how/architecture/decision/설계/결정),
      depth-1 neighbors of top results are returned as context_neighbors.
    """
    auth = _auth_from_ctx(ctx)
    results = search_closed_notes(query, limit=limit, kind=kind, tags=tags)
    filtered = [item for item in results.get("results", []) if _can_read_note_payload(item, auth)]
    hit_count = len(filtered)
    gap_info = None
    if _is_gap_query(query, filtered):
        _record_gap_query(query)
        gap_info = _find_gap_note(query)
    # retrieval_value를 맨 앞에 — 하위 에이전트가 응답을 잘라도(truncate) 코칭 필드가 살아남도록.
    response: dict[str, Any] = {
        "retrieval_value": _build_retrieval_value(query, filtered, gap_info),
    }
    usage_hint = _search_notes_usage_hint(query=query, kind=kind, results=filtered, gap_info=gap_info)
    if usage_hint:
        response["usage_hint"] = usage_hint
    top_path = str(filtered[0].get("path") or "") if filtered else ""
    response["_next"] = _build_search_notes_next(filtered, gap_info)
    if top_path:
        response["next_call"] = {"read_note": {"path": top_path}}
    if gap_info:
        response["gap"] = gap_info
    response["count"] = hit_count
    response["results"] = filtered
    for k, v in results.items():
        if k not in response and k != "results":
            response[k] = v
    if _should_include_related(query, include_related) and filtered:
        try:
            context_neighbors = _gather_context_neighbors(filtered[:3], auth)
            if context_neighbors:
                response["context_neighbors"] = context_neighbors
        except Exception:
            pass
    try:
        log_tool_event(
            "search_notes",
            user=auth.nickname or auth.username,
            args_summary={"query": query[:120], "limit": limit, "kind": kind, "tags": tags},
            notes_read=[r.get("path", "") for r in filtered[:5] if r.get("path")],
        )
    except Exception:
        pass
    return response


@mcp.tool(title="Search And Read Top OpenAkashic Note")
def search_and_read_top(
    query: Annotated[str, Field(description="Search terms in plain language. Returns the top matching note's full body in one call.")],
    kind: Annotated[str | None, Field(description="Filter by note kind: 'capsule', 'claim', 'evidence', etc.")] = None,
    tags: Annotated[list[str] | None, Field(description="Filter by tags — all specified tags must be present")] = None,
    include_body: Annotated[bool, Field(description="Include the full markdown body of the top result (default true)")] = True,
    include_related: Annotated[bool, Field(description="When true, depth-1 neighbors of top results are returned as context_neighbors.")] = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """One-shot search + read for small/low-context agents.

    Runs search_notes, then reads the highest-scoring readable hit and returns its
    full body inline. Saves a round-trip compared to search → read_note.
    Falls back to semantic `hints` when there is no direct match.
    """
    auth = _auth_from_ctx(ctx)
    results = search_closed_notes(query, limit=5, kind=kind, tags=tags)
    filtered = [item for item in results.get("results", []) if _can_read_note_payload(item, auth)]
    top = filtered[0] if filtered else None
    note_payload = None
    if top and include_body:
        note_payload = get_closed_note_by_slug(top["slug"], viewer_owner=auth.nickname, is_admin=_is_admin(auth))
        if note_payload and not _can_read_note_payload(note_payload, auth):
            note_payload = None
    gap_info = None
    if _is_gap_query(query, filtered):
        _record_gap_query(query)
        gap_info = _find_gap_note(query)
    # 순서 전략: directive → note_body_preview → retrieval_value → meta → full note
    # bench runner가 receipt를 1500자로 자르므로, 가장 중요한 행동 지침과 노트 본문을 앞에 배치.
    response: dict[str, Any] = {
        "directive": "노트 본문의 사실을 인용해 질문에 직접 답하세요. 경로 나열·도구명 반복 금지. 부족하면 read_note 추가 호출.",
    }
    usage_hint = _search_notes_usage_hint(query=query, kind=kind, results=filtered, gap_info=gap_info)
    if usage_hint:
        response["usage_hint"] = usage_hint
    if note_payload and note_payload.get("body"):
        response["note_body_preview"] = note_payload["body"][:1200]
    response["retrieval_value"] = _build_retrieval_value(query, filtered, gap_info)
    response["query"] = query
    response["top"] = top
    response["other_results"] = filtered[1:]
    response["hints"] = results.get("hints", [])
    response["count"] = len(filtered)
    if gap_info:
        response["gap"] = gap_info
    response["note"] = note_payload
    if _should_include_related(query, include_related) and filtered:
        try:
            context_neighbors = _gather_context_neighbors(filtered[:3], auth)
            if context_neighbors:
                response["context_neighbors"] = context_neighbors
        except Exception:
            pass
    try:
        read_paths: list[str] = []
        if top and top.get("path"):
            read_paths.append(top["path"])
        log_tool_event(
            "search_and_read_top",
            user=auth.nickname or auth.username,
            args_summary={"query": query[:120], "kind": kind, "tags": tags, "include_body": include_body},
            notes_read=read_paths,
        )
    except Exception:
        pass
    return response


@mcp.tool(title="Read OpenAkashic Note")
def read_note(
    slug: Annotated[str | None, Field(description="Note slug (short identifier from search results, e.g. 'my-findings'). Use this OR path, not both.")] = None,
    path: Annotated[str | None, Field(description="Full note path starting with 'personal_vault/' (e.g. 'personal_vault/projects/my-project/my-findings.md'). Use this OR slug.")] = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Read a note by slug or relative markdown path."""
    auth = _auth_from_ctx(ctx)
    if slug:
        note = get_closed_note_by_slug(slug, viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    elif path:
        note = get_closed_note(path, viewer_owner=auth.nickname, is_admin=_is_admin(auth))
        if not note and not path.endswith(".md"):
            # upsert_note auto-normalizes paths to append .md; mirror that for read_note.
            note = get_closed_note(path + ".md", viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    else:
        raise ValueError("Provide either slug or path")
    if not note:
        raise ValueError("Note not found")
    if not _can_read_note_payload(note, auth):
        raise ValueError("Note is not readable for this token")
    note_frontmatter = load_document(note["path"]).frontmatter if note.get("path") else {}
    next_hint = _build_read_note_next(note, note_frontmatter=note_frontmatter)
    if next_hint:
        note["_next"] = next_hint
    try:
        log_tool_event(
            "read_note",
            user=auth.nickname or auth.username,
            args_summary={"slug": slug, "path": path},
            notes_read=[note.get("path", "") or path or ""],
        )
    except Exception:
        pass
    return note


@mcp.tool(title="List OpenAkashic Notes")
def list_notes(folder: str | None = None, ctx: Context | None = None) -> dict[str, Any]:
    """List markdown note paths in OpenAkashic, optionally filtered by top-level folder."""
    auth = _auth_from_ctx(ctx)
    notes: list[str] = []
    prefix = folder.strip("/").rstrip("/") + "/" if folder else ""
    for note_path in list_note_paths():
        if prefix and not note_path.startswith(prefix):
            continue
        try:
            document = load_document(note_path)
        except Exception:
            continue
        if _can_read_frontmatter(document.frontmatter, auth):
            notes.append(note_path)
    return {"notes": notes, "count": len(notes)}


@mcp.tool(title="List OpenAkashic Folders")
def list_folders() -> dict[str, Any]:
    """List the organized folder map used for OpenAkashic notes and assets."""
    return {
        "rules": folder_rules(),
        "existing": folder_index(),
    }


@mcp.tool(title="Debug Recent OpenAkashic Requests")
def debug_recent_requests(
    limit: int = 50,
    path_prefix: str | None = None,
    status_min: int | None = None,
    request_id: str | None = None,
    method: str | None = None,
    kind: str | None = None,
    q: str | None = None,
    sort_by: str = "time",
    order: str = "desc",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Inspect and filter recent OpenAkashic API/MCP requests without exposing bearer tokens."""
    auth = _auth_from_ctx(ctx)
    if not _is_admin(auth):
        raise ValueError("Only admins can access request logs")
    return {
        "events": recent_requests(
            limit=limit,
            path_prefix=path_prefix,
            status_min=status_min,
            request_id=request_id,
            method=method,
            kind=kind,
            q=q,
            sort_by=sort_by,
            order=order,
        ),
        "observability": observability_status(),
    }


@mcp.tool(title="Tail OpenAkashic Request Log")
def debug_log_tail(limit: int = 100, ctx: Context | None = None) -> dict[str, Any]:
    """Tail the persistent OpenAkashic request JSONL log."""
    auth = _auth_from_ctx(ctx)
    if not _is_admin(auth):
        raise ValueError("Only admins can access request logs")
    return {
        "lines": log_tail(limit=limit),
        "observability": observability_status(),
    }


@mcp.tool(title="Debug Recent OpenAkashic Tool Calls")
def debug_tool_trace(
    limit: int = 100,
    tool: str | None = None,
    user: str | None = None,
    errors_only: bool = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Return recent MCP tool-call trace events (tool name, user, notes read/written)."""
    auth = _auth_from_ctx(ctx)
    if not _is_admin(auth):
        raise ValueError("Only admins can access tool trace")
    return {
        "events": recent_tool_events(limit=limit, tool=tool, user=user, errors_only=errors_only),
    }


@mcp.tool(title="Suggest OpenAkashic Note Path")
def path_suggestion(
    title: Annotated[str, Field(description="Human-readable note title. Example: 'Python JSON Benchmark Results'")],
    kind: Annotated[str | None, Field(description="Note kind: 'capsule', 'evidence', 'claim', 'reference', 'playbook', etc. Affects which folder is suggested.")] = None,
    folder: Annotated[str | None, Field(description="Override folder. If omitted, inferred from kind.")] = None,
    scope: Annotated[str | None, Field(description="Scope hint: 'personal', 'shared', 'ops', etc.")] = None,
    project: Annotated[str | None, Field(description="Project name. Used to build path like 'personal_vault/projects/<project>/<slug>.md'")] = None,
) -> dict[str, str]:
    """Suggest a note path based on note kind and the OpenAkashic folder rules.

    Use this tool when unsure what path to pass to upsert_note.
    Returns a path string ready to use directly in upsert_note.
    """
    return {"path": suggest_note_path(kind, title, folder, scope, project)}


@mcp.tool(title="Bootstrap OpenAkashic Project")
def bootstrap_project(
    project: str | None = None,
    project_key: str | None = None,  # alias — some agents emit this instead of `project`
    scope: str | None = None,
    title: str | None = None,
    summary: str | None = None,
    description: str | None = None,  # alias for summary
    canonical_docs: list[str] | None = None,
    folders: list[str] | None = None,
    tags: list[str] | None = None,
    related: list[str] | None = None,
) -> dict[str, Any]:
    """Create or verify a project workspace with README index and optional agent-defined subfolders."""
    resolved_project = project or project_key
    if not resolved_project:
        raise ValueError("project is required")
    resolved_summary = summary or description
    return bootstrap_project_workspace(
        project=normalize_project_key(resolved_project, scope),
        title=title,
        summary=resolved_summary,
        canonical_docs=canonical_docs,
        folders=folders,
        tags=tags,
        related=related,
    )


@mcp.tool(title="Upsert OpenAkashic Note")
def upsert_note(
    path: Annotated[str, Field(description="Note file path. MUST start with 'personal_vault/' and end with '.md'. Example: 'personal_vault/projects/my-project/findings.md'. Use path_suggestion tool if unsure.")],
    body: Annotated[str | None, Field(description="Full markdown content of the note (preferred field name). Use ## headings. Alias: pass as 'content' if preferred — both are accepted.")] = None,
    content: Annotated[str | None, Field(description="Alias for 'body'. Use either 'body' or 'content' — whichever you prefer. Same type/format as body.")] = None,
    title: Annotated[str | None, Field(description="Human-readable title. If omitted, inferred from filename.")] = None,
    kind: Annotated[str | None, Field(description="Note kind. Use 'capsule' for summaries/syntheses, 'claim' for assertions, 'evidence' for experiment results with code, 'reference' for external sources. Only capsule/claim are promoted to public OpenAkashic knowledge.")] = None,
    project: Annotated[str | None, Field(description="Project name this note belongs to. Example: 'my-benchmarks'")] = None,
    status: Annotated[str | None, Field(description="Workflow status: 'draft', 'active', 'archived'. Default: 'active'.")] = None,
    tags: Annotated[list[str] | None, Field(description="List of tags for search filtering. Example: ['python', 'benchmark', 'performance']")] = None,
    related: Annotated[list[str] | None, Field(description="Paths of related notes. Example: ['personal_vault/projects/my-project/other-note.md']")] = None,
    metadata: Annotated[dict[str, Any] | None, Field(description="Additional frontmatter fields. Rarely needed — prefer explicit parameters above.")] = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Create or overwrite an OpenAkashic markdown note.

    kind='claim' notes are public by default and become trust-ranked Core API claims.
    Prefer claim for atomic reusable findings; Sagwan can later turn multiple related claims into a capsule.
    kind='capsule' notes stay private until you request publication review.
    Other kinds (playbook, concept, etc.) remain Closed-only working memory.
    Writable roots: personal_vault/, doc/, assets/ only.

    IMPORTANT: The response includes `path` — save this value and pass it to
    request_note_publication when you want to submit a capsule/synthesis for public review.
    """
    body = body or content  # content는 body의 alias — 어느 쪽으로 호출해도 동작
    if not body:
        return {"error": "body (또는 content) 파라미터가 필수입니다. 노트 내용을 전달하세요."}
    auth = _auth_from_ctx(ctx)
    _check_mcp_write_rate(auth)
    existing_frontmatter: dict[str, Any] = {}
    try:
        existing_frontmatter = load_document(path).frontmatter
    except Exception:
        existing_frontmatter = {}
    write_metadata = _normalize_write_metadata(path=path, metadata=metadata or {}, auth=auth, kind=kind)
    doc = write_document(
        path=path,
        body=body,
        title=title,
        kind=kind,
        project=project,
        status=status,
        tags=tags,
        related=related,
        metadata=write_metadata,
    )
    publication_request = None
    core_api_id = None
    old_target = str(existing_frontmatter.get("targets") or "").strip() or None
    new_target = str(doc.frontmatter.get("targets") or "").strip() or None
    old_stance = str(existing_frontmatter.get("stance") or "").strip().lower()
    new_stance = str(doc.frontmatter.get("stance") or "").strip().lower()
    old_review_lifecycle = _targeted_claim_lifecycle_value(existing_frontmatter)
    new_review_lifecycle = _targeted_claim_lifecycle_value(doc.frontmatter)
    targeted_claim_written_directly = (
        str(doc.frontmatter.get("kind") or "").strip().lower() == "claim"
        and bool(str(doc.frontmatter.get("targets") or "").strip())
        and not getattr(_UPSERT_TOOL_CONTEXT, "invoked_via_review_tool", False)
    )
    direct_public_claim = (
        str(doc.frontmatter.get("kind") or "").strip().lower() == "claim"
        and str(doc.frontmatter.get("visibility") or "").strip().lower() == "public"
        and not str(doc.frontmatter.get("targets") or "").strip()
    )
    wants_publication = not _is_admin(auth) and (
        str((metadata or {}).get("visibility") or "").strip().lower() == "public"
        or str(write_metadata.get("publication_status") or "").strip().lower() == "requested"
    ) and not str(doc.frontmatter.get("targets") or "").strip()
    if direct_public_claim:
        core_api_id = sync_published_note(
            frontmatter=doc.frontmatter,
            body=doc.body,
            note_path=doc.path,
        )
        if core_api_id and str(doc.frontmatter.get("core_api_id") or "") != core_api_id:
            next_fm = dict(doc.frontmatter)
            next_fm["core_api_id"] = core_api_id
            doc = write_document(
                path=doc.path,
                body=doc.body,
                metadata=next_fm,
                allow_owner_change=True,
            )
    elif wants_publication:
        publication_request = request_publication(
            path=doc.path,
            requester=auth.nickname,
            target_visibility="public",
            rationale=None,
            evidence_paths=[],
        )
    if str(doc.frontmatter.get("kind") or "").strip().lower() == "claim":
        recompute_targets: list[str] = []
        if old_target and old_target != new_target:
            recompute_targets.append(old_target)
        if new_target and new_target not in recompute_targets:
            if new_review_lifecycle != "consolidated":
                recompute_targets.append(new_target)
            elif old_target == new_target:
                recompute_targets.append(new_target)
        elif old_target and old_target == new_target and (old_stance != new_stance or old_review_lifecycle != new_review_lifecycle):
            recompute_targets.append(old_target)
        for target_path in recompute_targets:
            _recompute_parent_aggregate(target_path)
    note = get_closed_note(doc.path, viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    saved_path = doc.path
    try:
        log_tool_event(
            "upsert_note",
            user=auth.nickname or auth.username,
            args_summary={"path": saved_path, "kind": kind, "title": title},
            notes_written=[saved_path],
        )
    except Exception:
        pass
    return {
        "path": saved_path,
        "slug": note["slug"] if note else Path(saved_path).stem,
        "note": note,
        "publication_request": publication_request.__dict__ if publication_request else None,
        "core_api_id": core_api_id,
        "claim_id": str(doc.frontmatter.get("claim_id") or "") if str(doc.frontmatter.get("kind") or "").strip().lower() == "claim" else None,
        "is_targeted": bool(str(doc.frontmatter.get("targets") or "").strip()) if str(doc.frontmatter.get("kind") or "").strip().lower() == "claim" else False,
        "_next": (
            f"Note saved at '{saved_path}'. "
            + (
                f"Public claim synced to Core API as '{core_api_id}'. Search with search_akashic(query=...). "
                "If you discover more atomic facts on the same topic, keep adding claims — Sagwan can later synthesize them into a capsule."
                if direct_public_claim and core_api_id
                else "If this is a single reusable fact, consider saving it as kind='claim'. "
                     "For a synthesis/capsule, call request_note_publication with "
                     f"path='{saved_path}', rationale='<why this is worth publishing>', "
                     "evidence_paths=['<supporting note paths or URLs>']"
            )
            + (
                " For future reviews prefer the dedicated review_note(target, stance, rationale, evidence_urls?) tool — it sets the correct path and defaults."
                if targeted_claim_written_directly
                else ""
            )
        ),
    }


def _review_note_impl(
    *,
    auth: AuthState,
    target: str,
    stance: str,
    rationale: str,
    evidence_urls: list[str] | None = None,
    evidence_paths: list[str] | None = None,
    topic: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    if not target.startswith("personal_vault/") or not target.endswith(".md"):
        raise ValueError("target must be a personal_vault/*.md path")
    target_doc = load_document(target)
    if not _can_read_frontmatter(target_doc.frontmatter, auth):
        raise ValueError("Target note is not readable for this token")
    target_kind = str(target_doc.frontmatter.get("kind") or "").strip().lower()
    if target_kind not in {"capsule", "claim"}:
        raise ValueError(
            f"review target must be a kind='capsule' or kind='claim' note (got kind={target_kind!r})."
        )
    normalized_stance = str(stance or "").strip().lower()
    if normalized_stance not in {"support", "dispute", "neutral"}:
        raise ValueError("stance must be one of support|dispute|neutral")
    rationale_text = str(rationale or "").strip()
    if not 20 <= len(rationale_text) <= 2000:
        raise ValueError("rationale must be 20-2000 chars")

    review_path = generate_review_path()
    prior_review_flag = getattr(_UPSERT_TOOL_CONTEXT, "invoked_via_review_tool", False)
    _UPSERT_TOOL_CONTEXT.invoked_via_review_tool = True
    try:
        with _auth_override(auth):
            review = upsert_note(
                path=review_path,
                body=f"## Rationale\n{rationale_text}",
                kind="claim",
                metadata={
                    "targets": target,
                    "stance": normalized_stance,
                    "claim_review_lifecycle": "active",
                    "evidence_urls": evidence_urls or [],
                    "evidence_paths": evidence_paths or [],
                    "topic": (str(topic or "").strip() or None),
                },
                ctx=ctx,
            )
    finally:
        if prior_review_flag:
            _UPSERT_TOOL_CONTEXT.invoked_via_review_tool = prior_review_flag
        else:
            try:
                delattr(_UPSERT_TOOL_CONTEXT, "invoked_via_review_tool")
            except AttributeError:
                pass
    parent_doc = load_document(target)
    parent_aggregate = {
        "confirm_count": int(parent_doc.frontmatter.get("confirm_count") or 0),
        "dispute_count": int(parent_doc.frontmatter.get("dispute_count") or 0),
        "neutral_count": int(parent_doc.frontmatter.get("neutral_count") or 0),
    }
    evidence_count = len(evidence_urls or []) + len(evidence_paths or [])
    try:
        log_tool_event(
            "review_note",
            user=auth.nickname or auth.username,
            args_summary={
                "target": target,
                "stance": normalized_stance,
                "topic": (str(topic or "").strip() or None),
                "evidence_count": evidence_count,
            },
            notes_read=[target],
            notes_written=[review["path"]],
        )
    except Exception:
        pass
    return {
        "path": review["path"],
        "claim_id": review.get("claim_id"),
        "stance": normalized_stance,
        "targets": target,
        "rationale_chars": len(rationale_text),
        "evidence_count": evidence_count,
        "parent_aggregate": parent_aggregate,
    }


def _post_internal_review(
    *,
    target: str,
    stance: str,
    rationale: str,
    evidence_urls: list[str] | None = None,
    evidence_paths: list[str] | None = None,
    topic: str | None = None,
) -> dict[str, Any]:
    normalized_topic = str(topic or "").strip() or None
    for review in _load_targeted_claims_for(target):
        if str(review.owner or "").strip() != SAGWAN_SYSTEM_OWNER:
            continue
        if normalized_topic and str(review.topic or "").strip() != normalized_topic:
            continue
        return {
            "status": "skipped_duplicate",
            "path": review.path,
            "target": target,
            "topic": normalized_topic,
        }

    admin_auth = AuthState(
        authenticated=True,
        role="admin",
        token_label="server-sagwan",
        username=SAGWAN_SYSTEM_OWNER,
        nickname=SAGWAN_SYSTEM_OWNER,
        owner=SAGWAN_SYSTEM_OWNER,
        capabilities=auth_state_for_token(settings.bearer_token.strip() or None).capabilities,
        display_name=SAGWAN_SYSTEM_OWNER,
    )
    result = _review_note_impl(
        auth=admin_auth,
        target=target,
        stance=stance,
        rationale=rationale,
        evidence_urls=evidence_urls,
        evidence_paths=evidence_paths,
        topic=normalized_topic,
        ctx=None,
    )
    return {"status": "created", **result}


@mcp.tool(title="Review OpenAkashic Claim or Capsule")
def review_note(
    target: Annotated[str, Field(description="Path of the capsule or claim you are reviewing. Must be under personal_vault/ and kind in {capsule, claim}. Example: 'personal_vault/projects/my-project/findings.md'")],
    stance: Annotated[str, Field(description="'support' if you back the target, 'dispute' if you contradict it, 'neutral' for a note-level comment.")],
    rationale: Annotated[str, Field(description="Short plain-text explanation (20-2000 chars). Markdown OK. This becomes the body of your review note.")],
    evidence_urls: Annotated[list[str] | None, Field(description="External URLs backing your stance. Max 10. Each URL is validated for storage hygiene (SSRF-safe); never fetched automatically.")] = None,
    evidence_paths: Annotated[list[str] | None, Field(description="Paths to supporting vault notes. Max 10. Must live under personal_vault/, doc/, or assets/.")] = None,
    topic: Annotated[str | None, Field(description="Optional one-line topic tag for clustering.")] = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Attach a review to an existing capsule or claim.

    Reviews appear on the parent's page, feed the trust score, and are visible
    to every agent reading that parent. You can review a review — it becomes a
    counter-claim threaded on the original targeted claim.

    Prefer this over `dispute_note`/`confirm_note` when you have rationale + evidence —
    those are one-click signals only.
    Prefer this over `upsert_note(kind='claim', metadata={...})` because this tool sets
    the correct defaults and path for you.
    """
    auth = _auth_from_ctx(ctx)
    return _review_note_impl(
        auth=auth,
        target=target,
        stance=stance,
        rationale=rationale,
        evidence_urls=evidence_urls,
        evidence_paths=evidence_paths,
        topic=topic,
        ctx=ctx,
    )


@mcp.tool(title="Request OpenAkashic Note Publication")
def request_note_publication(
    path: Annotated[str, Field(description="Exact path of the note to publish. Use the `path` value returned by upsert_note — do not guess or reconstruct it. Example: 'personal_vault/projects/my-project/findings.md'")],
    requester: Annotated[str | None, Field(description="Your username. If omitted, inferred from your auth token.")] = None,
    target_visibility: Annotated[str, Field(description="Target visibility after approval. Use 'public' (default).")] = "public",
    rationale: Annotated[str | None, Field(description="Why this note is worth making public (≥20 chars). Be specific — vague rationale causes rejection. Example: 'Benchmark results with reproducible code showing 1.14x speedup of list comprehensions vs for-loops on 1M elements.'")] = None,
    reason: Annotated[str | None, Field(description="Alias for rationale — use either field.")] = None,
    evidence_paths: Annotated[list[str] | None, Field(description="Paths or URLs supporting this note's claims. Example: ['personal_vault/projects/my-project/evidence.md', 'https://docs.python.org/3/library/timeit.html']. Required for approval.")] = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Request librarian review for public publication. Source remains private by default.

    Provide `rationale` (or `reason` alias) explaining WHY the note is publication-worthy,
    plus `evidence_paths` linking supporting notes. Weak requests (empty rationale or
    evidence) are accepted but returned with `warnings` so the caller can improve them.
    """
    auth = _auth_from_ctx(ctx)
    _assert_can_request_publication(path, auth)
    effective_rationale = (rationale or reason or "").strip() or None
    request = request_publication(
        path=path,
        requester=requester if _is_admin(auth) else auth.nickname,
        target_visibility=target_visibility,
        rationale=effective_rationale,
        evidence_paths=evidence_paths,
    )
    warnings: list[str] = []
    if not effective_rationale:
        warnings.append("rationale is empty — reviewers rely on it to judge publication")
    elif len(effective_rationale) < 20:
        warnings.append("rationale is very short (<20 chars) — consider expanding")
    if not (evidence_paths or []):
        warnings.append("evidence_paths is empty — link supporting notes to strengthen the request")
    # 거버넌스 게이트 미리 안내 — 사관 승인 루프가 아래 조건 중 하나라도 어기면 deferred 처리한다.
    try:
        source_doc = load_document(path)
        source_kind = str(source_doc.frontmatter.get("kind") or "").strip().lower()
        if path.startswith("doc/"):
            pass
        elif path.startswith("personal_vault/knowledge/") and source_kind != "capsule":
            warnings.append(
                f"source `{path}` is under `personal_vault/knowledge/` — "
                "only kind=capsule can be published from here. Derive a capsule first."
            )
        elif source_kind not in {"capsule", "claim"}:
            warnings.append(
                f"source kind=`{source_kind}` — publication requires kind in {{capsule, claim}}. "
                "sagwan will defer this request. Re-save the note with kind='capsule' or 'claim'."
            )
    except Exception:
        pass
    return {"request": request.__dict__, "warnings": warnings}


@mcp.tool(title="List Publication Requests")
def list_note_publication_requests(status: str | None = None) -> dict[str, Any]:
    """List librarian publication requests."""
    requests = list_publication_requests(status=status)
    return {
        "requests": [item.__dict__ for item in requests],
        "count": len(requests),
    }


@mcp.tool(title="Set Publication Status")
def set_note_publication_status(path: str, status: str, reason: str | None = None, ctx: Context | None = None) -> dict[str, Any]:
    """Admin/librarian-only publication decision helper. published also sets visibility=public."""
    auth = _auth_from_ctx(ctx)
    if not _is_admin(auth):
        raise ValueError("Only admins can set publication status directly")
    source_doc = load_document(path)
    if str(source_doc.frontmatter.get("targets") or "").strip():
        raise ValueError("Targeted claims (reviews) cannot be published. Reviews stay Closed-only by design — publish the underlying capsule instead.")
    document = set_publication_status(path=path, status=status, decider=auth.nickname, reason=reason)
    note = get_closed_note(document.path, viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    return {"path": document.path, "frontmatter": document.frontmatter, "note": note}


@mcp.tool(title="Append OpenAkashic Note Section")
def append_note_section(
    path: Annotated[str, Field(description="Full path of the existing note. Example: 'personal_vault/projects/my-project/note.md'")],
    heading: Annotated[str, Field(description="Section heading text (without ##). Example: 'Results' → appended as '## Results'")],
    content: Annotated[str, Field(description="Markdown content to append under the heading.")],
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Append a new H2 section to an existing OpenAkashic markdown note."""
    auth = _auth_from_ctx(ctx)
    _assert_can_modify_document(path, auth)
    doc = append_section(path, heading, content)
    note = get_closed_note(doc.path, viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    try:
        log_tool_event(
            "append_note_section",
            user=auth.nickname or auth.username,
            args_summary={"path": doc.path, "heading": heading[:80]},
            notes_written=[doc.path],
        )
    except Exception:
        pass
    return {
        "path": doc.path,
        "note": note,
    }


@mcp.tool(title="Confirm OpenAkashic Note")
def confirm_note(
    path: Annotated[str, Field(description="Full path of the note to endorse. Example: 'personal_vault/projects/my-project/findings.md'")],
    comment: Annotated[str | None, Field(description="Optional reason for confirming (e.g. 'reproduced result', 'verified in production'). Stored alongside your nickname and timestamp.")] = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Endorse a note as correct or useful. Lightweight — no LLM call, no write rate limit.

    Appends a timestamped entry to `confirmed_by` and increments `confirm_count` in the
    note's frontmatter. Any authenticated agent that can read the note may confirm it —
    including public notes owned by sagwan.

    Use this when you've independently verified a claim, reproduced a result, or found
    a note's guidance genuinely useful in practice. High confirm_count helps surface
    high-signal notes in search.
    """
    auth = _auth_from_ctx(ctx)
    if not auth.authenticated:
        raise ValueError("Authentication required to confirm a note")
    doc = load_document(path)
    if not _can_read_frontmatter(doc.frontmatter, auth):
        raise ValueError("Note is not readable for this token")

    caller = auth.nickname or auth.username or "unknown"
    from datetime import UTC as _UTC, datetime as _dt
    now = _dt.now(_UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    next_fm = dict(doc.frontmatter)
    # confirmed_by는 "nickname|timestamp" 또는 "*nickname|timestamp" (self-confirm) 형식 문자열 목록.
    # render_document의 inline list 직렬화가 dict를 지원하지 않아 문자열 형식 사용.
    confirmed_by: list[str] = [str(e) for e in (next_fm.get("confirmed_by") or [])]

    # ── Anti-gaming: dedup per caller ────────────────────────────────────────
    def _entry_caller(e: str) -> str:
        return e.lstrip("*").split("|")[0].strip()

    if any(_entry_caller(e) == caller for e in confirmed_by):
        return {
            "path": path,
            "confirm_count": int(next_fm.get("confirm_count") or 0),
            "confirmed_by": confirmed_by,
            "status": "already_confirmed",
        }

    # ── Same-owner discount ───────────────────────────────────────────────────
    note_owner = _note_owner(doc.frontmatter)
    is_self_confirm = bool(note_owner and caller == note_owner)

    # 형식: "*nickname|timestamp|comment" (self-confirm) or "nickname|timestamp|comment"
    parts = [("*" if is_self_confirm else "") + caller, now]
    if comment:
        parts.append(comment.strip()[:200].replace("|", "/"))
    entry = "|".join(parts)
    confirmed_by.append(entry)

    next_fm["confirmed_by"] = confirmed_by

    write_document(
        path=path,
        body=doc.body,
        metadata=next_fm,
        metadata_replace=True,
        allow_owner_change=True,
    )
    recomputed = _recompute_parent_aggregate(path)
    return {
        "path": path,
        "confirm_count": recomputed.get("confirm_count", int(next_fm.get("confirm_count") or 0)),
        "confirmed_by": confirmed_by,
        "self_confirm": is_self_confirm,
    }


@mcp.tool(title="List Stale OpenAkashic Notes")
def list_stale_notes(
    days_overdue: Annotated[int, Field(description="Only return notes at least this many days past their decay threshold (0 = any overdue note)")] = 0,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Return notes whose freshness_date has passed the decay_tier threshold.

    decay_tier thresholds: legal=30d, product=60d, general=90d (default).
    Notes with `snoozed_until` set to a future date are skipped.
    Only returns notes readable by the calling token.

    Suggested actions per note:
    - days_overdue > 30: rewrite stale sections
    - 1-30: append a dated refresh section, or snooze if still valid
    - 0: review and confirm_note if still accurate
    """
    auth = _auth_from_ctx(ctx)
    if not auth.authenticated:
        raise ValueError("Authentication required")
    all_stale = list_stale_closed_notes(days_overdue=days_overdue)
    visible = [item for item in all_stale if _can_read_note_payload(item, auth)]
    return {"stale_notes": visible, "count": len(visible), "days_overdue_threshold": days_overdue}


@mcp.tool(title="Dispute OpenAkashic Note")
def dispute_note(
    path: Annotated[str, Field(description="Full path of the note to dispute. Example: 'personal_vault/projects/my-project/findings.md'")],
    reason: Annotated[str | None, Field(description="Optional short reason for disputing (e.g. 'stale after deploy', 'counterexample in prod'). Stored alongside your nickname and timestamp.")] = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Record a dispute signal on a note after independent review.

    This is the counterweight to confirm_note. It appends a timestamped entry to
    `disputed_by`, increments `dispute_count`, and marks `claim_review_status`
    as `disputed` unless the note has already been marked `superseded` or `merged`.
    """
    auth = _auth_from_ctx(ctx)
    if not auth.authenticated:
        raise ValueError("Authentication required to dispute a note")
    doc = load_document(path)
    if not _can_read_frontmatter(doc.frontmatter, auth):
        raise ValueError("Note is not readable for this token")

    caller = auth.nickname or auth.username or "unknown"
    from datetime import UTC as _UTC, datetime as _dt
    now = _dt.now(_UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    next_fm = dict(doc.frontmatter)
    disputed_by: list[str] = [str(e) for e in (next_fm.get("disputed_by") or [])]

    def _entry_caller(e: str) -> str:
        return e.lstrip("*").split("|")[0].strip()

    if any(_entry_caller(e) == caller for e in disputed_by):
        return {
            "path": path,
            "dispute_count": int(next_fm.get("dispute_count") or 0),
            "disputed_by": disputed_by,
            "status": "already_disputed",
        }

    parts = [caller, now]
    if reason:
        parts.append(reason.strip()[:200].replace("|", "/"))
    disputed_by.append("|".join(parts))
    next_fm["disputed_by"] = disputed_by
    current_status = str(next_fm.get("claim_review_status") or "").strip().lower()
    if current_status not in {"superseded", "merged"}:
        next_fm["claim_review_status"] = "disputed"
    next_fm["claim_review_updated_at"] = now
    next_fm["claim_review_updated_by"] = caller
    if reason:
        next_fm["claim_review_note"] = reason.strip()

    write_document(
        path=path,
        body=doc.body,
        metadata=next_fm,
        metadata_replace=True,
        allow_owner_change=True,
    )
    recomputed = _recompute_parent_aggregate(path)
    return {
        "path": path,
        "dispute_count": recomputed.get("dispute_count", int(next_fm.get("dispute_count") or 0)),
        "disputed_by": disputed_by,
        "claim_review_status": next_fm.get("claim_review_status") or "disputed",
    }


@mcp.tool(title="List Reviews on OpenAkashic Note")
def list_reviews(
    target: Annotated[str, Field(description="Capsule/claim path whose reviews you want to read.")],
    include_consolidated: Annotated[bool, Field(description="Include reviews already merged by Sagwan. Default False.")] = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Return all reviews attached to a target, sorted by recency. Use before writing a new review to avoid duplication."""
    auth = _auth_from_ctx(ctx)
    if not target.startswith("personal_vault/") or not target.endswith(".md"):
        raise ValueError("target must be a personal_vault/*.md path")
    target_doc = load_document(target)
    if not _can_read_frontmatter(target_doc.frontmatter, auth):
        raise ValueError("Target note is not readable for this token")
    target_kind = str(target_doc.frontmatter.get("kind") or "").strip().lower()
    if target_kind not in {"capsule", "claim"}:
        raise ValueError(
            f"target must be a kind='capsule' or kind='claim' note (got kind={target_kind!r})."
        )
    visible_reviews = [
        review for review in _load_targeted_claims_for(target, include_consolidated=include_consolidated)
        if _can_read_frontmatter(review.frontmatter, auth)
    ]
    try:
        log_tool_event(
            "list_reviews",
            user=auth.nickname or auth.username,
            args_summary={"target": target, "include_consolidated": include_consolidated},
            notes_read=[target, *[review.path for review in visible_reviews[:20]]],
        )
    except Exception:
        pass
    result = {
        "target": target,
        "count": len(visible_reviews),
        "reviews": [
            {
                "claim_id": review.claim_id,
                "path": review.path,
                "stance": review.stance,
                "owner": review.owner,
                "self_authored": review.self_authored,
                "rationale_excerpt": _review_rationale_excerpt(review.body),
                "evidence_urls": review.evidence_urls,
                "evidence_paths": review.evidence_paths,
                "created_at": review.frontmatter.get("created_at"),
                "claim_review_lifecycle": review.claim_review_lifecycle,
            }
            for review in visible_reviews
        ],
    }
    next_hint = _build_list_reviews_next(len(visible_reviews))
    if next_hint:
        result["_next"] = next_hint
    return result


@mcp.tool(title="Snooze OpenAkashic Stale Reminder")
def snooze_note(
    path: Annotated[str, Field(description="Note path to snooze")],
    days: Annotated[int, Field(description="Days to snooze the stale reminder (1-365)", ge=1, le=365)],
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Snooze the stale-decay reminder for a note by setting snoozed_until.

    The note will not appear in list_stale_notes until the snooze period ends.
    Use this when a note is still accurate but hasn't been formally refreshed.
    Does NOT modify the note body — only updates the snoozed_until frontmatter field.
    """
    from datetime import UTC as _UTC, datetime as _dt, timedelta
    auth = _auth_from_ctx(ctx)
    _assert_can_modify_document(path, auth)
    doc = load_document(path)
    until_dt = (_dt.now(_UTC) + timedelta(days=days)).date().isoformat()
    doc.frontmatter["snoozed_until"] = until_dt
    write_document(path=path, body=doc.body, metadata=doc.frontmatter)
    return {"path": path, "snoozed_until": until_dt, "days": days}


@mcp.tool(title="Resolve OpenAkashic Conflict")
def resolve_conflict(
    path: Annotated[str, Field(description="Note path whose conflict_status to resolve")],
    verdict: Annotated[str, Field(description="Conflict verdict: keep|supersede|merge (legacy: clear|pending_review)")],
    comment: Annotated[str, Field(description="Reason for overriding the conflict verdict")] = "",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Resolve a conflict on a note and propagate the claim trust state.

    Recommended verdicts:
    - keep: reviewed and retained
    - supersede: this claim should remain searchable but demoted
    - merge: this claim has been folded into another container

    Legacy verdicts `clear` and `pending_review` are still accepted.
    Only the note owner or admin token may call this.
    """
    auth = _auth_from_ctx(ctx)
    _assert_can_modify_document(path, auth)
    normalized = str(verdict or "").strip().lower()
    if normalized not in ("keep", "supersede", "merge", "clear", "pending_review"):
        raise ValueError("verdict must be keep, supersede, merge, clear, or pending_review")
    doc = load_document(path)
    prev_conflict = str(doc.frontmatter.get("conflict_status", "none"))
    prev_claim_status = str(doc.frontmatter.get("claim_review_status") or "unreviewed")
    if normalized in {"keep", "clear"}:
        doc.frontmatter["conflict_status"] = "clear"
        doc.frontmatter["claim_review_status"] = "confirmed"
    elif normalized == "pending_review":
        doc.frontmatter["conflict_status"] = "pending_review"
        if str(doc.frontmatter.get("claim_review_status") or "").strip().lower() not in {"superseded", "merged", "disputed"}:
            doc.frontmatter["claim_review_status"] = "unreviewed"
    elif normalized == "supersede":
        doc.frontmatter["conflict_status"] = "clear"
        doc.frontmatter["claim_review_status"] = "superseded"
    elif normalized == "merge":
        doc.frontmatter["conflict_status"] = "clear"
        doc.frontmatter["claim_review_status"] = "merged"
    from datetime import UTC as _UTC, datetime as _dt
    now = _dt.now(_UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    doc.frontmatter["claim_review_updated_at"] = now
    doc.frontmatter["claim_review_updated_by"] = auth.nickname or auth.username or "unknown"
    if comment:
        doc.frontmatter["conflict_resolution_note"] = comment
        doc.frontmatter["claim_review_note"] = comment
    write_document(path=path, body=doc.body, metadata=doc.frontmatter)
    return {
        "path": path,
        "previous_status": prev_conflict,
        "previous_claim_review_status": prev_claim_status,
        "conflict_status": doc.frontmatter["conflict_status"],
        "claim_review_status": doc.frontmatter["claim_review_status"],
    }


@mcp.tool(title="Delete OpenAkashic Note")
def delete_note(path: str, ctx: Context | None = None) -> dict[str, str]:
    """Delete an existing markdown note from OpenAkashic."""
    auth = _auth_from_ctx(ctx)
    _assert_can_modify_document(path, auth)
    deleted = delete_document(path)
    try:
        log_tool_event(
            "delete_note",
            user=auth.nickname or auth.username,
            args_summary={"path": path},
            notes_written=[path],
        )
    except Exception:
        pass
    return {"deleted": deleted}


@mcp.tool(title="Move OpenAkashic Note")
def move_note(path: str, new_path: str, ctx: Context | None = None) -> dict[str, str]:
    """Move a note to a new relative markdown path."""
    auth = _auth_from_ctx(ctx)
    _assert_can_modify_document(path, auth)
    resolved = move_document(path, new_path)
    try:
        log_tool_event(
            "move_note",
            user=auth.nickname or auth.username,
            args_summary={"path": path, "new_path": new_path},
            notes_written=[path, resolved],
        )
    except Exception:
        pass
    return {"path": resolved}


@mcp.tool(title="Create OpenAkashic Folder")
def create_folder(path: str, ctx: Context | None = None) -> dict[str, str]:
    """Create a folder inside an allowed OpenAkashic root."""
    _auth_from_ctx(ctx)
    return {"path": ensure_folder(path)}


@mcp.tool(title="Move OpenAkashic Folder")
def rename_folder(path: str, new_path: str, ctx: Context | None = None) -> dict[str, str]:
    """Move or rename a folder inside an allowed OpenAkashic root."""
    _auth_from_ctx(ctx)
    return {"path": move_folder(path, new_path)}


@mcp.tool(title="Upload OpenAkashic Image")
def upload_image(
    filename: str,
    content_base64: str,
    folder: str = "assets/images",
    alt: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Upload an image into OpenAkashic assets and return embeddable markdown."""
    _auth_from_ctx(ctx)
    content = base64.b64decode(content_base64)
    asset = save_image(filename=filename, content=content, folder=folder, alt=alt)
    return {
        "path": asset.path,
        "url": asset.url,
        "markdown": asset.markdown,
        "mime_type": asset.mime_type,
        "size": asset.size,
    }


@mcp.tool(title="Search Akashic (validated public knowledge)")
def search_akashic(
    query: Annotated[str | None, Field(description="Search terms for validated public knowledge. Example: 'Python list comprehension performance'")] = None,
    question: Annotated[str | None, Field(description="Alias for query — use either field.")] = None,
    top_k: Annotated[int, Field(description="Max results to return (default 8)")] = 8,
    include: Annotated[list[str] | None, Field(description="Knowledge types to include. Options: 'capsules', 'claims', 'evidences'. Default: ['capsules','claims']. Add 'evidences' when you need source links.")] = None,
    mode: Annotated[str, Field(description="Projection mode: 'compact' (id+title+summary_head+confidence — smallest payload for SLMs), 'standard' (+ summary+key_points+cautions+source_claim_ids — default), 'full' (+ metadata/timestamps).")] = "standard",
    fields: Annotated[list[str] | None, Field(description="Explicit field allowlist for capsules/claims (overrides mode). Example: ['summary','key_points']. id/title/text/score are always included.")] = None,
) -> dict[str, Any]:
    """
    Search the Akashic Core API — the primary retrieval path for validated public knowledge.

    Returns agent-friendly capsules (summary + key_points + cautions) packaged from claim/evidence data.
    Use this FIRST for factual/conceptual questions. For your own working notes use search_notes.

    - mode='compact' → 1-sentence summary per capsule (smallest, best for small models)
    - mode='standard' → full capsule without metadata (default)
    - mode='full' → everything including metadata and timestamps
    - fields=['summary','key_points'] → custom projection overriding mode
    """
    resolved_query = query or question
    if not resolved_query:
        raise ValueError("query is required")
    settings_obj = get_settings()
    url = settings_obj.core_api_url.rstrip("/") + "/query"
    payload: dict[str, Any] = {"query": resolved_query, "top_k": top_k, "mode": mode}
    if include:
        payload["include"] = include
    if fields:
        payload["fields"] = fields
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            response = json.loads(resp.read().decode("utf-8"))
        _annotate_public_search_results(response)
        if _public_result_count(response) == 0:
            _record_gap_query(resolved_query)
        reasons = _detect_akashic_quality_issues(
            query=resolved_query,
            response=response,
            include=include,
        )
        if reasons:
            _record_search_quality_signal(
                tool="search_akashic",
                query=resolved_query,
                reasons=reasons,
                include=include,
                mode=mode,
                response=response,
            )
            try:
                from app.subordinate import enqueue_subordinate_task

                enqueue_subordinate_task(
                    kind="analyze_search_quality_signals",
                    payload={"max_new": 10},
                    created_by="signal-monitor",
                )
            except Exception:
                pass
        try:
            log_tool_event(
                "search_akashic",
                user="anonymous",
                args_summary={
                    "query": resolved_query[:120],
                    "top_k": top_k,
                    "include": include or ["capsules", "claims"],
                    "mode": mode,
                    "quality_reasons": reasons,
                },
            )
        except Exception:
            pass
        if reasons:
            response["_quality_signal"] = {
                "recorded": True,
                "reasons": reasons,
                "message": "Low-quality Akashic search signal recorded for Sagwan review.",
            }
        next_hint = _build_search_akashic_next(response)
        if next_hint:
            response["_next"] = next_hint
        return response
    except urlerror.URLError as exc:
        response = {"error": f"Core API unreachable: {exc}", "query": resolved_query, "results": {}}
        _record_search_quality_signal(
            tool="search_akashic",
            query=resolved_query,
            reasons=["core_api_error"],
            include=include,
            mode=mode,
            response=response,
        )
        try:
            from app.subordinate import enqueue_subordinate_task

            enqueue_subordinate_task(
                kind="analyze_search_quality_signals",
                payload={"max_new": 10},
                created_by="signal-monitor",
            )
        except Exception:
            pass
        return response
    except Exception as exc:
        response = {"error": str(exc), "query": resolved_query, "results": {}}
        _record_search_quality_signal(
            tool="search_akashic",
            query=resolved_query,
            reasons=["core_api_error"],
            include=include,
            mode=mode,
            response=response,
        )
        try:
            from app.subordinate import enqueue_subordinate_task

            enqueue_subordinate_task(
                kind="analyze_search_quality_signals",
                payload={"max_new": 10},
                created_by="signal-monitor",
            )
        except Exception:
            pass
        return response


@mcp.tool(title="Get Akashic Capsule (full body by id)")
def get_capsule(
    capsule_id: Annotated[str, Field(description="Capsule UUID from a search_akashic result. Example: '00000000-0000-0000-0000-000000000301'")],
) -> dict[str, Any]:
    """
    Fetch a single capsule by UUID with full body (title, summary, key_points, cautions, source_claim_ids, metadata).
    Use after a compact search_akashic call to drill into one capsule without re-searching.
    """
    if not capsule_id:
        raise ValueError("capsule_id is required")
    settings_obj = get_settings()
    url = settings_obj.core_api_url.rstrip("/") + f"/capsules/{capsule_id}"
    try:
        with urlrequest.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        if exc.code == 404:
            return {"error": "Capsule not found", "capsule_id": capsule_id}
        return {"error": f"Core API error {exc.code}: {exc.reason}", "capsule_id": capsule_id}
    except urlerror.URLError as exc:
        return {"error": f"Core API unreachable: {exc}", "capsule_id": capsule_id}
    except Exception as exc:
        return {"error": str(exc), "capsule_id": capsule_id}


@mcp.tool(title="Read Raw OpenAkashic Note")
def read_raw_note(path: str, ctx: Context | None = None) -> dict[str, Any]:
    """Read the raw frontmatter and markdown body for a note."""
    auth = _auth_from_ctx(ctx)
    doc = load_document(path)
    if not _can_read_frontmatter(doc.frontmatter, auth):
        raise ValueError("Note is not readable for this token")
    try:
        log_tool_event(
            "read_raw_note",
            user=auth.nickname or auth.username,
            args_summary={"path": path},
            notes_read=[doc.path],
        )
    except Exception:
        pass
    result = {
        "path": doc.path,
        "frontmatter": doc.frontmatter,
        "body": doc.body,
    }
    note = get_closed_note(doc.path, viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    if note:
        next_hint = _build_read_note_next(note, note_frontmatter=doc.frontmatter)
        if next_hint:
            result["_next"] = next_hint
    return result


@mcp.tool(title="Who Am I (OpenAkashic Profile)")
def whoami(ctx: Context | None = None) -> dict[str, Any]:
    """Return your username, nickname, role, and API token.

    Useful when you need to:
    - Find your token to log into the web UI (paste it in Account → Token tab)
    - Verify which account you're connected as
    - Check if your account is provisioned (no password set yet)
    """
    auth = _auth_from_ctx(ctx)
    if not auth.authenticated:
        return {
            "authenticated": False,
            "message": "Not authenticated. Set a valid Bearer token in your MCP config.",
        }
    token = _request_token_from_ctx(ctx)
    user = find_user_by_username(auth.username)
    provisioned = bool(user.get("provisioned")) if user else False
    result: dict[str, Any] = {
        "authenticated": True,
        "username": auth.username,
        "nickname": auth.nickname,
        "role": auth.role,
        "api_token": token or "",
        "provisioned": provisioned,
        "guidance": openakashic_guidance_payload(public_base_url=settings.public_base_url),
    }
    if provisioned:
        base_url = settings.public_base_url
        result["web_login_hint"] = (
            f"Go to {base_url}/closed/graph → click the Account button (top right) "
            "→ Token tab → paste your api_token → click Sign in with Token. "
            "Then go to the Profile tab to set a password for username/password login."
        )
    return result


@mcp.tool(title="Get OpenAkashic Guidance")
def get_openakashic_guidance() -> dict[str, Any]:
    """Return a short, optional usage guide for agents integrating with OpenAkashic.

    This is intentionally lightweight: it nudges toward the intended read/write
    paths without trying to replace the agent's broader standing instructions.
    """

    return openakashic_guidance_payload(public_base_url=settings.public_base_url)


@mcp.tool(title="Self-test Your OpenAkashic Usage Skill")
def run_self_test(
    task_id: Annotated[
        str,
        Field(
            description=(
                "Task ID from OpenAkashicBench public subset. Example: 'review_workflow', "
                "'list_reviews_first', 'consolidation_awareness', 'version_lineage', "
                "'citation_integrity'. Full list: run_self_test(task_id='list_tasks')."
            )
        ),
    ],
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Return one canonical bench task so the calling agent can self-test its Akashic usage skill.

    The task returns: prompt, expected_outcome (what a correct answer covers),
    hallucination_traps (what NOT to say), and rubric (judging notes).

    The agent then answers the prompt using its normal tool usage, and compares
    its answer against expected_outcome. This is self-assessment — no server-side
    judgment happens here. The judge script at closed-web/server/bench/judge.py
    can be run manually by an admin to score actual responses.
    """
    import yaml

    _auth_from_ctx(ctx)
    bench_root_candidates = [
        Path(__file__).resolve().parent.parent / "bench",
        Path(__file__).resolve().parent.parent.parent / "server" / "bench",
        Path(__file__).resolve().parent.parent.parent / "bench",
        # Container deployment: server/app is bind-mounted at /app/app, and the
        # rest of closed-web (including bench/) lives at /vault/closed/.
        Path("/vault/closed/server/bench"),
    ]
    env_dir = os.environ.get("CLOSED_AKASHIC_BENCH_DIR")
    if env_dir:
        bench_root_candidates.insert(0, Path(env_dir))

    tasks_file: Path | None = None
    for bench_dir in bench_root_candidates:
        public_candidate = bench_dir / "tasks-public.yaml"
        fallback_candidate = bench_dir / "tasks.yaml"
        if public_candidate.exists():
            tasks_file = public_candidate
            break
        if fallback_candidate.exists():
            tasks_file = fallback_candidate
            break

    if tasks_file is None:
        return {"error": "benchmark tasks not available on this instance"}

    raw = yaml.safe_load(tasks_file.read_text(encoding="utf-8")) or {}
    tasks = raw.get("tasks", [])

    if task_id == "list_tasks":
        return {
            "tasks": [{"id": t["id"], "summary": str(t.get("rubric") or "")[:160]} for t in tasks if t.get("id")],
            "usage": "call run_self_test(task_id=<pick one>) for full task.",
        }

    task = next((t for t in tasks if t.get("id") == task_id), None)
    if not task:
        return {
            "error": f"task_id '{task_id}' not found",
            "available": [t["id"] for t in tasks if t.get("id")][:20],
        }

    return {
        "id": task["id"],
        "prompt": task["prompt"],
        "expected_outcome": task.get("expected_outcome", []),
        "hallucination_traps": task.get("hallucination_traps", []),
        "rubric": task.get("rubric", ""),
        "_next": (
            "Answer the prompt above using your normal MCP tool usage. Compare your answer against "
            "expected_outcome; any hallucination_traps hit is a fail. Admin can score your run via bench/judge.py."
        ),
    }


def _request_token_from_ctx(ctx: Context | None) -> str | None:
    if not ctx:
        return settings.bearer_token.strip() or None
    request = getattr(getattr(ctx, "request_context", None), "request", None)
    headers = getattr(request, "headers", None)
    if not headers:
        return settings.bearer_token.strip() or None
    auth_header = headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip() or None
    return settings.bearer_token.strip() or None


def _auth_from_ctx(ctx: Context | None) -> AuthState:
    override = getattr(_INTERNAL_AUTH_OVERRIDE, "auth", None)
    if override is not None:
        return override
    return auth_state_for_token(_request_token_from_ctx(ctx))


@contextmanager
def _auth_override(auth: AuthState):
    previous = getattr(_INTERNAL_AUTH_OVERRIDE, "auth", None)
    _INTERNAL_AUTH_OVERRIDE.auth = auth
    try:
        yield
    finally:
        if previous is None:
            try:
                delattr(_INTERNAL_AUTH_OVERRIDE, "auth")
            except AttributeError:
                pass
        else:
            _INTERNAL_AUTH_OVERRIDE.auth = previous


_WRITEBACK_KEYWORDS = (
    "기록해", "저장해", "작성해", "정리해", "추가해", "남겨", "적어",
    "write", "save", "store", "log this", "기록하자", "정리하자",
)
_SYNTHESIS_KEYWORDS = (
    "비교", "차이", "분석", "대비", "장단점", "vs", "versus",
    "compare", "difference", "analyze", "trade-off", "tradeoff",
)


def _detect_intent(query: str) -> str:
    """Heuristic query-intent classifier. LLM 호출 없이 키워드 매칭만."""
    lowered = query.lower().strip()
    if not lowered:
        return "unknown"
    if any(kw in lowered for kw in _WRITEBACK_KEYWORDS):
        return "writeback"
    if any(kw in lowered for kw in _SYNTHESIS_KEYWORDS):
        return "synthesis"
    return "fact_lookup"


def _build_retrieval_value(
    query: str,
    results: list[dict[str, Any]],
    gap_info: dict[str, Any] | None,
) -> dict[str, Any]:
    """아카식 노트 검색 결과를 에이전트가 즉시 활용할 수 있는 구조화된 신호로 변환.

    Intent 기반 조립 (fact_lookup / synthesis / writeback / unknown) — 의도에 따라
    포함 필드를 달리 해서 토큰 낭비와 중요 정보 희석을 동시에 줄인다.
    """
    intent = _detect_intent(query)
    has_gap = bool(gap_info or not results)
    gap_paths = [r["path"] for r in results[:5] if r.get("path", "").startswith("doc/knowledge-gaps/")]
    knowledge_paths = [r["path"] for r in results[:5] if not r.get("path", "").startswith("doc/knowledge-gaps/")]

    # synthesis_directive를 맨 앞에 — compact하게 유지해서 note_body가 1500자 안에 들어오도록.
    out: dict[str, Any] = {
        "directive": "경로 나열 금지. 노트 내용을 읽어 질문에 직접 답하세요. 부족하면 read_note 추가 호출.",
        "intent": intent,
        "matched_notes": knowledge_paths[:3],  # 상위 3개로 제한
    }

    # writeback 의도: 어떤 경로에 쓸지가 중요. 관련 노트가 있으면 upsert 전 참고하라는 신호.
    if intent == "writeback":
        out["writeback_suggested"] = True
        out["writeback_hint"] = (
            "기존 관련 노트가 있으면 append_note_section으로 이어붙이는 것을 먼저 고려. "
            "새 경로가 필요하면 path_suggestion을 호출 후 upsert_note."
        )
        if knowledge_paths:
            out["related_for_writeback"] = knowledge_paths[:3]
    # synthesis 의도: 여러 노트 교차 분석. 커버리지 갭이 특히 중요.
    elif intent == "synthesis":
        out["coverage_gaps"] = [query.strip()] if has_gap else []
        out["writeback_suggested"] = has_gap
        if gap_paths:
            out["gap_notes"] = gap_paths
        out["synthesis_hint"] = (
            "여러 matched_notes를 교차 참조해서 답할 것. 근거가 부족하면 답 대신 coverage_gap을 명시하고 writeback을 제안."
        )
    # fact_lookup 의도: 단일 노트 읽기로 답 가능. gap이 있으면 가볍게 표시.
    else:  # fact_lookup / unknown
        if has_gap:
            out["coverage_gaps"] = [query.strip()]
            out["writeback_suggested"] = True
            if gap_paths:
                out["gap_notes"] = gap_paths
        else:
            out["writeback_suggested"] = False

    out["read_note_hint"] = "본문이 필요하면 read_note(path=<path>) 추가 호출. 쓰기는 upsert_note(path, body, title)."
    return out


def _looks_like_factual_query(query: str) -> bool:
    lowered = (query or "").strip().lower()
    if not lowered:
        return False
    if len(lowered.split()) >= 3:
        return True
    return any(token in lowered for token in _FACTUAL_QUERY_HINTS)


def _search_notes_usage_hint(
    *,
    query: str,
    kind: str | None,
    results: list[dict[str, Any]],
    gap_info: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if kind in {"claim", "capsule"}:
        return None
    if not _looks_like_factual_query(query):
        return None
    hint: dict[str, Any] = {
        "message": (
            "For factual or conceptual questions, start with search_akashic(query=..., mode='compact'). "
            "search_notes is best for OpenAkashic's private/shared working-memory layer."
        ),
        "recommended_search": {
            "tool": "search_akashic",
            "query": query,
            "mode": "compact",
            "include": ["capsules", "claims"],
        },
        "write_hint": (
            "If you discover one reusable fact, warning, or config finding, save it as kind='claim'. "
            "Use capsule for a synthesis."
        ),
    }
    if gap_info:
        hint["gap_followup"] = (
            "This looks like a coverage gap. After solving it, publish the atomic finding as a claim first."
        )
    elif results:
        top = results[0]
        hint["note_scope"] = (
            f"Top hit `{top.get('title') or top.get('slug') or 'note'}` came from OpenAkashic's private/shared working-memory layer, "
            "not the validated public layer."
        )
    return hint


def _should_include_related(query: str, include_related: bool) -> bool:
    if include_related:
        return True
    lowered = query.lower()
    return any(keyword in lowered for keyword in _RELATED_TRIGGERS)


def _gather_context_neighbors(results: list[dict[str, Any]], auth: AuthState) -> list[dict[str, Any]]:
    result_slugs = {str(result.get("slug") or "") for result in results}
    seen: set[str] = set()
    neighbors: list[dict[str, Any]] = []
    for result in results[:3]:
        if len(neighbors) >= 8:
            break
        slug = str(result.get("slug") or "").strip()
        if not slug:
            continue
        try:
            source_payload = get_closed_note_by_slug(slug)
        except Exception:
            continue
        if not source_payload:
            continue
        source_path = str(source_payload.get("path") or result.get("path") or "")
        for related in source_payload.get("related_notes") or []:
            if len(neighbors) >= 8:
                break
            related_slug = str((related or {}).get("slug") or "").strip()
            if not related_slug or related_slug in result_slugs or related_slug in seen:
                continue
            try:
                neighbor = get_closed_note_by_slug(related_slug)
            except Exception:
                continue
            if not neighbor or not _can_read_note_payload(neighbor, auth):
                continue
            seen.add(related_slug)
            neighbors.append(
                {
                    "slug": str(neighbor.get("slug") or related_slug),
                    "title": str(neighbor.get("title") or (related or {}).get("title") or related_slug),
                    "path": str(neighbor.get("path") or ""),
                    "kind": str(neighbor.get("kind") or ""),
                    "summary": str(neighbor.get("summary") or ""),
                    "source_note_path": source_path,
                }
            )
    return neighbors


# ── Gap query detection & logger ─────────────────────────────────────────────

# nomic-embed-text 기준 calibration (2026-04-15):
#   실제 hit 클러스터: semantic ≥ 0.72
#   진짜 gap 클러스터: semantic ≤ 0.58
#   threshold 0.70 + cliff 0.06 조합 — lexical override 우선
_GAP_SEM_STRONG = 0.70      # 이 이상이면 확실한 hit → 절대 gap 아님
_GAP_SEM_FLOOR = 0.62       # 이 미만이면 top-1이 무엇이든 gap (약한 매칭)
_GAP_BASELINE_CLIFF = 0.10  # 중간대(0.62~0.70)에서 top-1과 top-5 격차 하한


def _is_gap_query(query: str, results: list[dict[str, Any]]) -> bool:
    """검색 결과가 실질적으로 부족한지 판단.

    gap 조건 (lexical_score 모두 0 이어야 후보):
    - top semantic ≥ 0.70: 강한 매칭 → gap 아님
    - top semantic < 0.62: 약한 매칭 → gap
    - 0.62 ≤ top < 0.70: top-1이 baseline(top-5) 대비 0.10 이상 확실히 튀어야 hit
      (하나의 fluke 매칭이 중간 점수로 top-1에 오르는 False-not-gap 방지)
    """
    if not query or not results:
        return bool(not results)
    if any(float(r.get("lexical_score") or 0) > 0 for r in results):
        return False
    sem_scores = sorted(
        [float(r.get("semantic_score") or 0) for r in results], reverse=True
    )
    top_sem = sem_scores[0] if sem_scores else 0.0
    if top_sem >= _GAP_SEM_STRONG:
        return False
    if top_sem < _GAP_SEM_FLOOR:
        return True
    baseline = sem_scores[4] if len(sem_scores) >= 5 else sem_scores[-1]
    return (top_sem - baseline) < _GAP_BASELINE_CLIFF


_GAP_LOCK = __import__("threading").Lock()
_SEARCH_QUALITY_LOCK = __import__("threading").Lock()
_AKASHIC_LOW_CAPSULE_SCORE = 0.24
_AKASHIC_LOW_CLAIM_SCORE = 0.22


def gap_queries_path() -> Path:
    """JSONL file recording search_notes queries that returned 0 results."""
    from app.config import get_settings as _gs
    return Path(_gs().user_store_path).with_name("gap-queries.jsonl")


def search_quality_signals_path() -> Path:
    """JSONL file recording low-quality search_akashic responses for curator review."""
    from app.config import get_settings as _gs

    return Path(_gs().user_store_path).with_name("search-quality-signals.jsonl")


def _record_gap_query(query: str) -> None:
    """Append a zero-hit search query to the gap query log (fire-and-forget)."""
    import json as _json
    from datetime import UTC as _UTC, datetime as _dt
    line = _json.dumps({"ts": _dt.now(_UTC).isoformat().replace("+00:00", "Z"), "query": query.strip()}, ensure_ascii=False)
    try:
        path = gap_queries_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _GAP_LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        pass  # never break search on logging failure


def _score_of(item: dict[str, Any] | None) -> float:
    if not item:
        return 0.0
    try:
        return float(item.get("score") or 0.0)
    except Exception:
        return 0.0


def _claim_review_status_of(item: dict[str, Any] | None) -> str:
    if not item:
        return "unreviewed"
    return str(item.get("claim_review_status") or "unreviewed").strip().lower() or "unreviewed"


def _summarize_public_result(item: dict[str, Any] | None) -> dict[str, Any]:
    if not item:
        return {}
    payload: dict[str, Any] = {}
    for key in (
        "id",
        "title",
        "text",
        "summary_head",
        "confidence",
        "claim_role",
        "claim_review_status",
        "confirm_count",
        "dispute_count",
        "score",
    ):
        value = item.get(key)
        if value is not None:
            payload[key] = value
    return payload


def _trust_hint_from_counts(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    status = str(item.get("claim_review_status") or "").strip().lower()
    confirm_count = int(item.get("confirm_count") or 0)
    dispute_count = int(item.get("dispute_count") or 0)
    if status == "superseded":
        return "⚠ superseded"
    if status == "merged":
        return "merged"
    if dispute_count > confirm_count and dispute_count > 0:
        return f"⚠ disputed ({dispute_count}d / {confirm_count}c)"
    if confirm_count >= 2:
        return f"✓ confirmed ({confirm_count}c)"
    return ""


def _result_lineage_path(item: dict[str, Any] | None, key: str) -> str:
    if not item:
        return ""
    direct = str(item.get(key) or "").strip()
    if direct:
        return direct
    alt_map = {
        "superseded_by": ("superseded_by_path", "superseded_by_note_path"),
        "supersedes": ("supersedes_path", "supersedes_note_path"),
    }
    for alt in alt_map.get(key, ()):
        value = str(item.get(alt) or "").strip()
        if value:
            return value
    return ""


def _top_public_result(response: dict[str, Any]) -> dict[str, Any] | None:
    results = dict(response.get("results") or {})
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    order = 0
    for kind in ("capsules", "claims", "evidences"):
        for item in results.get(kind) or []:
            if not isinstance(item, dict):
                continue
            ranked.append((_score_of(item), order, item))
            order += 1
    if not ranked:
        return None
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return ranked[0][2]


def _public_result_count(response: dict[str, Any]) -> int:
    results = dict(response.get("results") or {})
    total = 0
    for kind in ("capsules", "claims", "evidences"):
        items = results.get(kind) or []
        if isinstance(items, list):
            total += len(items)
    return total


def _annotate_public_search_results(response: dict[str, Any]) -> None:
    results = dict(response.get("results") or {})
    for kind in ("capsules", "claims", "evidences"):
        items = results.get(kind) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                item["trust_hint"] = _trust_hint_from_counts(item)


def _build_search_akashic_next(response: dict[str, Any]) -> str:
    if _public_result_count(response) == 0:
        return (
            "No capsule found. Gap auto-logged. If you solve this, upsert_note(kind='claim', ...) "
            "will fill the gap for future agents."
        )
    top = _top_public_result(response)
    if not top:
        return ""
    confirm_count = int(top.get("confirm_count") or 0)
    dispute_count = int(top.get("dispute_count") or 0)
    superseded_by_path = _result_lineage_path(top, "superseded_by")
    if superseded_by_path:
        return f"Top result is superseded. See newer version at {superseded_by_path} via read_note."
    if dispute_count > confirm_count:
        return (
            f"⚠ Top result has more disputes than confirms ({dispute_count}d / {confirm_count}c). "
            "Check list_reviews before trusting."
        )
    if confirm_count == 0 and dispute_count == 0:
        return (
            "Top result has no reviews yet. If you use it and verify, confirm_note(path). "
            "If you find it wrong, review_note(target, stance='dispute', rationale, evidence_urls)."
        )
    return ""


def _build_search_notes_next(results: list[dict[str, Any]], gap_info: dict[str, Any] | None) -> str:
    if not results:
        return (
            "No note found. Gap auto-logged. If you solve this, upsert_note(kind='claim', ...) "
            "will fill the gap for future agents."
        )
    top = results[0]
    confirm_count = int(top.get("confirm_count") or 0)
    dispute_count = int(top.get("dispute_count") or 0)
    superseded_by_path = _result_lineage_path(top, "superseded_by")
    if superseded_by_path:
        return f"Top result is superseded. See newer version at {superseded_by_path} via read_note."
    if dispute_count > confirm_count:
        return (
            f"⚠ Top result has more disputes than confirms ({dispute_count}d / {confirm_count}c). "
            "Check list_reviews before trusting."
        )
    if str(top.get("kind") or "").strip().lower() in {"claim", "capsule"} and confirm_count == 0 and dispute_count == 0:
        return (
            "Top result has no reviews yet. If you use it and verify, confirm_note(path). "
            "If you find it wrong, review_note(target, stance='dispute', rationale, evidence_urls)."
        )
    top_path = str(top.get("path") or "").strip()
    if top_path:
        return f"Read the top note in full with read_note(path='{top_path}')."
    if gap_info:
        return str(gap_info.get("message") or "")
    return ""


def _build_read_note_next(note: dict[str, Any], *, note_frontmatter: dict[str, Any]) -> str:
    kind = str(note.get("kind") or "").strip().lower()
    parts: list[str] = []
    if kind in {"capsule", "claim"} and not str(note.get("targets") or "").strip():
        parts.append(
            "Agree with this note? confirm_note(path). Disagree with rationale + evidence? "
            f"review_note(target={note.get('path')!r}, stance='dispute', rationale, evidence_urls)."
        )
    superseded_by_path = _result_lineage_path(note, "superseded_by")
    if superseded_by_path:
        parts.append(f"This note is superseded. Read {superseded_by_path} for current version.")
    supersedes_path = _result_lineage_path(note, "supersedes")
    if supersedes_path:
        revision_count = int(note_frontmatter.get("revision_count") or 0)
        revision_label = revision_count if revision_count > 0 else 1
        parts.append(
            f"This is a successor note (revision_count={revision_label}). Previous version at {supersedes_path} if needed for history."
        )
    return " ".join(part for part in parts if part)


def _build_list_reviews_next(count: int) -> str:
    if count == 0:
        return "No active reviews. If you have rationale+evidence about this target, review_note() would be the first signal."
    if count >= 3:
        return "Sagwan's stage L (consolidation) may fire on next cycle (6h cooldown). Watch /api/admin/sagwan/consolidations for verdict."
    return ""


def _detect_akashic_quality_issues(
    *,
    query: str,
    response: dict[str, Any],
    include: list[str] | None,
) -> list[str]:
    include_set = {str(item).strip().lower() for item in (include or ["capsules", "claims"]) if item}
    include_set = {"evidences" if item == "evidence" else item for item in include_set}
    if not {"capsules", "claims"} & include_set:
        return []

    if response.get("error"):
        return ["core_api_error"]

    results = dict(response.get("results") or {})
    claims = [item for item in (results.get("claims") or []) if isinstance(item, dict)]
    capsules = [item for item in (results.get("capsules") or []) if isinstance(item, dict)]
    reasons: list[str] = []

    if not claims and not capsules:
        return ["no_public_results"]

    top_capsule_score = _score_of(capsules[0] if capsules else None)
    top_claim_score = _score_of(claims[0] if claims else None)

    if "capsules" in include_set:
        if not capsules:
            reasons.append("no_capsule_hits")
        elif top_capsule_score < _AKASHIC_LOW_CAPSULE_SCORE:
            reasons.append("weak_capsule_match")

    if "claims" in include_set:
        if claims and not capsules:
            reasons.append("claim_only_results")
        if claims and top_claim_score < _AKASHIC_LOW_CLAIM_SCORE:
            reasons.append("weak_claim_match")

    if claims and not capsules:
        claim_statuses = [_claim_review_status_of(item) for item in claims[:3]]
        if claim_statuses and all(status == "unreviewed" for status in claim_statuses):
            reasons.append("claim_only_unreviewed")

    meta = dict(response.get("meta") or {})
    if bool(meta.get("has_conflict")):
        reasons.append("conflict_in_top_claims")

    deduped: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if reason not in seen:
            deduped.append(reason)
            seen.add(reason)
    return deduped


def _record_search_quality_signal(
    *,
    tool: str,
    query: str,
    reasons: list[str],
    include: list[str] | None,
    mode: str,
    response: dict[str, Any],
) -> None:
    import json as _json
    from datetime import UTC as _UTC, datetime as _dt

    results = dict(response.get("results") or {})
    claims = [item for item in (results.get("claims") or []) if isinstance(item, dict)]
    capsules = [item for item in (results.get("capsules") or []) if isinstance(item, dict)]
    line = _json.dumps(
        {
            "ts": _dt.now(_UTC).isoformat().replace("+00:00", "Z"),
            "tool": tool,
            "query": query.strip(),
            "reasons": reasons,
            "mode": mode,
            "include": include or ["capsules", "claims"],
            "meta": {
                "retrieval": str((response.get("meta") or {}).get("retrieval") or ""),
                "has_conflict": bool((response.get("meta") or {}).get("has_conflict")),
            },
            "counts": {
                "claims": len(claims),
                "capsules": len(capsules),
            },
            "top_claim": _summarize_public_result(claims[0] if claims else None),
            "top_capsule": _summarize_public_result(capsules[0] if capsules else None),
        },
        ensure_ascii=False,
    )
    try:
        path = search_quality_signals_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _SEARCH_QUALITY_LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        pass


def _find_gap_note(query: str) -> dict[str, Any] | None:
    """Return an existing doc/knowledge-gaps note for this query, if present."""
    try:
        from app.subordinate import _gap_slug

        slug = _gap_slug(query)
        gap_path = f"doc/knowledge-gaps/{slug}.md"
        doc = load_document(gap_path)
        miss_count = int(doc.frontmatter.get("miss_count") or 1)
        return {
            "path": gap_path,
            "miss_count": miss_count,
            "last_queried": str(doc.frontmatter.get("last_queried") or ""),
            "message": (
                f"This topic has been searched {miss_count} time(s) with no good result. "
                "If you solve this, upsert_note to doc/knowledge-gaps/ or your personal_vault "
                "and request_note_publication — it will help every future agent."
            ),
        }
    except Exception:
        return None


def _is_admin(auth: AuthState) -> bool:
    return auth.role == "admin"


def _note_visibility(frontmatter: dict[str, Any]) -> str:
    visibility = str(frontmatter.get("visibility") or settings.default_note_visibility).strip().lower()
    return visibility if visibility in {"private", "public", "shared"} else "private"


def _note_owner(frontmatter: dict[str, Any]) -> str:
    return str(frontmatter.get("owner") or settings.default_note_owner).strip() or settings.default_note_owner


def _can_read_frontmatter(frontmatter: dict[str, Any], auth: AuthState) -> bool:
    visibility = _note_visibility(frontmatter)
    if visibility == "public":
        return True
    if visibility == "shared":
        return auth.authenticated
    return auth.authenticated and (_is_admin(auth) or _note_owner(frontmatter) == auth.nickname)


def _can_modify_frontmatter(frontmatter: dict[str, Any], auth: AuthState) -> bool:
    if _note_visibility(frontmatter) == "public":
        if str(frontmatter.get("kind") or "").strip().lower() == "claim":
            return auth.authenticated and (_is_admin(auth) or _note_owner(frontmatter) == auth.nickname)
        return _is_admin(auth)
    return auth.authenticated and (_is_admin(auth) or _note_owner(frontmatter) == auth.nickname)


def _can_read_note_payload(note: dict[str, Any], auth: AuthState) -> bool:
    return _can_read_frontmatter(note, auth)


def _assert_can_modify_document(path: str, auth: AuthState) -> None:
    document = load_document(path)
    if not _can_modify_frontmatter(document.frontmatter, auth):
        raise ValueError("Notes can only be modified by their owner or an admin")


def _assert_can_request_publication(path: str, auth: AuthState) -> None:
    document = load_document(path)
    if not _is_admin(auth) and _note_owner(document.frontmatter) != auth.nickname:
        raise ValueError("Users can only request publication for their own notes")
    if str(document.frontmatter.get("targets") or "").strip():
        raise ValueError("Targeted claims (reviews) cannot be published. Reviews stay Closed-only by design — publish the underlying capsule instead.")


def _as_boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _dedupe_str_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in values:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _confirmation_callers(value: Any) -> list[str]:
    callers: list[str] = []
    raw_items = value if isinstance(value, list) else ([value] if value is not None else [])
    for item in raw_items:
        raw = str(item).strip()
        if not raw:
            continue
        caller = raw.lstrip("*").split("|", 1)[0].strip()
        if caller and caller not in callers:
            callers.append(caller)
    return callers


def _effective_confirm_count(frontmatter: dict[str, Any]) -> int:
    owner_value = _note_owner(frontmatter)
    return sum(1 for caller in _confirmation_callers(frontmatter.get("confirmed_by")) if caller != owner_value)


def _effective_dispute_count(frontmatter: dict[str, Any]) -> int:
    owner_value = _note_owner(frontmatter)
    return sum(1 for caller in _confirmation_callers(frontmatter.get("disputed_by")) if caller != owner_value)


def _targeted_claim_lifecycle_value(frontmatter: dict[str, Any]) -> str:
    value = str(frontmatter.get("claim_review_lifecycle") or "").strip().lower()
    if value:
        return value
    legacy = str(frontmatter.get("review_status") or "").strip().lower()
    return legacy or "active"


def _review_rationale_excerpt(body: str, *, limit: int = 240) -> str:
    text = (body or "").strip()
    if text.startswith("## Rationale"):
        text = text[len("## Rationale"):].strip()
    return text[:limit]


def migrate_targeted_claim_review_lifecycle_field() -> dict[str, int]:
    migrated = 0
    skipped = 0
    for path in list_note_paths():
        if not path.startswith("personal_vault/"):
            continue
        try:
            document = load_document(path)
        except Exception:
            continue
        frontmatter = dict(document.frontmatter or {})
        if str(frontmatter.get("kind") or "").strip().lower() != "claim":
            continue
        if not str(frontmatter.get("targets") or "").strip():
            continue
        if "review_status" not in frontmatter or "claim_review_lifecycle" in frontmatter:
            skipped += 1
            continue
        frontmatter["claim_review_lifecycle"] = frontmatter.pop("review_status")
        write_document(
            path=document.path,
            body=document.body,
            metadata=frontmatter,
            allow_owner_change=True,
        )
        migrated += 1
    return {"migrated": migrated, "skipped": skipped}


def _recompute_parent_aggregate(parent_path: str) -> dict[str, int]:
    parent_doc = load_document(parent_path)
    rich_support = 0
    rich_dispute = 0
    rich_neutral = 0
    for note_path in list_note_paths():
        if not note_path.startswith("personal_vault/"):
            continue
        try:
            child_doc = load_document(note_path)
        except Exception:
            continue
        frontmatter = child_doc.frontmatter
        if str(frontmatter.get("kind") or "").strip().lower() != "claim":
            continue
        if str(frontmatter.get("targets") or "").strip() != parent_path:
            continue
        if _targeted_claim_lifecycle_value(frontmatter) == "consolidated":
            continue
        if _as_boolish(frontmatter.get("self_authored")):
            continue
        stance = str(frontmatter.get("stance") or "").strip().lower()
        if stance == "support":
            rich_support += 1
        elif stance == "dispute":
            rich_dispute += 1
        elif stance == "neutral":
            rich_neutral += 1

    next_metadata = {
        "confirm_count": _effective_confirm_count(parent_doc.frontmatter) + rich_support,
        "dispute_count": _effective_dispute_count(parent_doc.frontmatter) + rich_dispute,
        "neutral_count": rich_neutral,
    }
    write_document(
        path=parent_path,
        body=parent_doc.body,
        metadata=next_metadata,
        metadata_replace=False,
        allow_owner_change=True,
    )
    return next_metadata


def _normalize_write_metadata(*, path: str, metadata: dict[str, Any], auth: AuthState, kind: str | None = None) -> dict[str, Any]:
    next_metadata = dict(metadata)
    next_metadata.pop("owner", None)
    existing_frontmatter: dict[str, Any] = {}
    is_existing = False
    try:
        existing_frontmatter = load_document(path).frontmatter
        is_existing = True
    except Exception:
        existing_frontmatter = {}
    resolved_kind = str(kind or next_metadata.get("kind") or existing_frontmatter.get("kind") or "reference").strip().lower()
    explicit_visibility = "visibility" in next_metadata and str(next_metadata.get("visibility") or "").strip() != ""
    effective_targets = next_metadata.get("targets") if "targets" in next_metadata else existing_frontmatter.get("targets")
    effective_targets = str(effective_targets or "").strip() or None

    requested_visibility = str(
        next_metadata.get("visibility") or existing_frontmatter.get("visibility") or settings.default_note_visibility
    ).strip().lower()
    if resolved_kind == "claim" and not is_existing and not explicit_visibility:
        requested_visibility = "public"
    if requested_visibility not in {"private", "public", "shared"}:
        requested_visibility = "private"
    if resolved_kind == "claim":
        if existing_frontmatter.get("claim_id"):
            next_metadata["claim_id"] = existing_frontmatter.get("claim_id")
        else:
            allocated = None
            for _ in range(3):
                candidate = generate_claim_id()
                if not is_claim_id_taken(candidate):
                    allocated = candidate
                    break
            if not allocated:
                raise ValueError("could not allocate unique claim_id")
            next_metadata["claim_id"] = allocated

        targeted_only_fields = (
            "stance",
            "claim_review_lifecycle",
            "target_title_snapshot",
            "self_authored",
            "evidence_urls",
            "evidence_paths",
        )
        if not effective_targets:
            if any(
                field in next_metadata and next_metadata.get(field) not in (None, "", [])
                for field in targeted_only_fields
            ):
                raise ValueError(
                    "targets is required for stance/claim_review_lifecycle/target_title_snapshot/self_authored/evidence_urls/evidence_paths — atomic claims must omit these."
                )
            if "targets" in next_metadata:
                next_metadata["targets"] = None
                next_metadata["stance"] = None
                next_metadata["claim_review_lifecycle"] = None
                next_metadata["self_authored"] = None
                next_metadata["target_title_snapshot"] = None
                next_metadata["evidence_urls"] = None
                next_metadata["evidence_paths"] = None
        else:
            if not effective_targets.startswith("personal_vault/") or not effective_targets.endswith(".md"):
                raise ValueError("targets must be a personal_vault/*.md path")
            try:
                target_doc = load_document(effective_targets)
            except Exception as exc:
                raise ValueError(f"targets note not found: {effective_targets}") from exc
            target_kind = str(target_doc.frontmatter.get("kind") or "").strip().lower()
            if target_kind not in {"capsule", "claim"}:
                raise ValueError(
                    f"targets must be a kind=capsule or kind=claim note (got kind={target_kind!r}). "
                    "Reviews can only attach to published knowledge notes."
                )
            seen_targets: set[str] = set()
            cursor = effective_targets
            depth = 0
            while cursor:
                if cursor in seen_targets or cursor == path:
                    raise ValueError("targets cycle detected or depth>8")
                seen_targets.add(cursor)
                depth += 1
                if depth > 8:
                    raise ValueError("targets cycle detected or depth>8")
                try:
                    cursor_doc = load_document(cursor)
                except Exception:
                    break
                cursor = str(cursor_doc.frontmatter.get("targets") or "").strip() or None

            effective_stance = next_metadata.get("stance") if "stance" in next_metadata else existing_frontmatter.get("stance")
            effective_stance = str(effective_stance or "").strip().lower()
            if effective_stance not in {"support", "dispute", "neutral"}:
                raise ValueError("stance is required and must be one of support|dispute|neutral when targets is set")
            next_metadata["targets"] = effective_targets
            next_metadata["stance"] = effective_stance

            effective_lifecycle = (
                next_metadata.get("claim_review_lifecycle")
                if "claim_review_lifecycle" in next_metadata
                else existing_frontmatter.get("claim_review_lifecycle")
            )
            if effective_lifecycle in (None, "") and "review_status" in existing_frontmatter:
                effective_lifecycle = existing_frontmatter.get("review_status")
            effective_lifecycle = str(effective_lifecycle or "active").strip().lower()
            if effective_lifecycle not in {"active", "consolidated", "orphaned"}:
                raise ValueError("claim_review_lifecycle must be one of active|consolidated|orphaned")
            next_metadata.pop("review_status", None)
            next_metadata["claim_review_lifecycle"] = effective_lifecycle
            next_metadata["self_authored"] = (_note_owner(target_doc.frontmatter) == auth.nickname)
            next_metadata["target_title_snapshot"] = str(
                target_doc.frontmatter.get("title") or Path(effective_targets).stem
            )
            target_visibility = str(target_doc.frontmatter.get("visibility") or "private").strip().lower()
            target_visibility = target_visibility if target_visibility in _VISIBILITY_RANK else "private"
            if _is_admin(auth) and explicit_visibility:
                pass
            elif not explicit_visibility:
                requested_visibility = target_visibility
            else:
                requested_rank = _VISIBILITY_RANK.get(requested_visibility, 0)
                target_rank = _VISIBILITY_RANK.get(target_visibility, 0)
                if requested_rank > target_rank:
                    requested_visibility = target_visibility

        if "evidence_urls" in next_metadata and next_metadata.get("evidence_urls") not in (None, ""):
            raw_urls = next_metadata.get("evidence_urls")
            if not isinstance(raw_urls, list):
                raise ValueError("evidence_urls must be a list of strings")
            if len(raw_urls) > 10:
                raise ValueError("evidence_urls supports at most 10 items")
            cleaned_urls: list[str] = []
            for raw_url in raw_urls:
                if not isinstance(raw_url, str):
                    raise ValueError("evidence_urls must be a list of strings")
                url = raw_url.strip()
                if not url:
                    continue
                if len(url) > 500:
                    raise ValueError("evidence_urls entries must be <= 500 chars")
                # SSRF posture: validate stored URLs only. These links are never auto-fetched here.
                _validate_url_scheme_and_literal_host(url)
                cleaned_urls.append(url)
            next_metadata["evidence_urls"] = _dedupe_str_list(cleaned_urls)

        if "evidence_paths" in next_metadata and next_metadata.get("evidence_paths") not in (None, ""):
            raw_paths = next_metadata.get("evidence_paths")
            if not isinstance(raw_paths, list):
                raise ValueError("evidence_paths must be a list of strings")
            if len(raw_paths) > 10:
                raise ValueError("evidence_paths supports at most 10 items")
            cleaned_paths: list[str] = []
            for raw_path in raw_paths:
                if not isinstance(raw_path, str):
                    raise ValueError("evidence_paths must be a list of strings")
                evidence_path = raw_path.strip()
                if not evidence_path:
                    continue
                if evidence_path.startswith("assets/"):
                    cleaned_paths.append(evidence_path)
                    continue
                if not (
                    (evidence_path.startswith("personal_vault/") or evidence_path.startswith("doc/"))
                    and evidence_path.endswith(".md")
                ):
                    raise ValueError("evidence_paths must stay under personal_vault/|doc/|assets/")
                cleaned_paths.append(evidence_path)
            next_metadata["evidence_paths"] = _dedupe_str_list(cleaned_paths)

    direct_public_claim = resolved_kind == "claim" and requested_visibility == "public" and not effective_targets
    if not _is_admin(auth) and requested_visibility == "public" and not direct_public_claim and not effective_targets:
        next_metadata["publication_target_visibility"] = "public"
        requested_visibility = "private"
    next_metadata["visibility"] = requested_visibility

    if is_existing:
        if not _can_modify_frontmatter(existing_frontmatter, auth):
            raise ValueError("Notes can only be modified by their owner or an admin")
        owner = _note_owner(existing_frontmatter)
        if requested_visibility == "public" and not direct_public_claim and not effective_targets:
            next_metadata.setdefault("original_owner", existing_frontmatter.get("original_owner") or owner)
            owner = SAGWAN_SYSTEM_OWNER
        next_metadata["owner"] = owner
        next_metadata.setdefault("created_by", existing_frontmatter.get("created_by") or owner)
    else:
        next_metadata["created_by"] = next_metadata.get("created_by") or auth.nickname
        if requested_visibility == "public" and _is_admin(auth) and not direct_public_claim and not effective_targets:
            next_metadata["owner"] = SAGWAN_SYSTEM_OWNER
        else:
            next_metadata["owner"] = auth.nickname

    publication_status = str(
        next_metadata.get("publication_status") or existing_frontmatter.get("publication_status") or "none"
    ).strip().lower()
    if direct_public_claim:
        publication_status = "published"
        next_metadata.pop("publication_target_visibility", None)
    elif not _is_admin(auth) and next_metadata.get("publication_target_visibility") == "public":
        publication_status = "requested"
    if not _is_admin(auth) and not direct_public_claim and publication_status not in {"none", "requested"}:
        raise ValueError("Users can only set publication status to none or requested")
    next_metadata["publication_status"] = publication_status or "none"

    # 신규 구조화 노트에 freshness 메타 자동 주입 (capsule/claim/evidence/reference)
    # 기존 노트 업데이트 시에는 건드리지 않아 에이전트가 직접 갱신하도록 유도한다.
    if not is_existing:
        _FRESHNESS_KINDS = {"capsule", "claim", "evidence", "reference"}
        resolved_kind = (kind or str(next_metadata.get("kind") or "")).strip().lower()
        if resolved_kind in _FRESHNESS_KINDS:
            if not next_metadata.get("freshness_date"):
                from datetime import UTC as _UTC, datetime as _dt
                next_metadata["freshness_date"] = _dt.now(_UTC).date().isoformat()
            next_metadata.setdefault("decay_tier", "general")

    return next_metadata
