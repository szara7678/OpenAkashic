import base64
import json
import threading
import time
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
from app.observability import log_tail, observability_status, recent_requests
from app.users import SAGWAN_SYSTEM_OWNER, find_user_by_username
from app.site import (
    get_closed_graph,
    get_closed_note,
    get_closed_note_by_slug,
    list_stale_closed_notes,
    search_closed_notes,
)
from app.vault import (
    append_section,
    bootstrap_project_workspace,
    delete_document,
    ensure_folder,
    folder_index,
    folder_rules,
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
        "search_notes": {"required": ["query"], "optional": ["limit", "kind", "tags", "include_related"]},
        "search_and_read_top": {"required": ["query"], "optional": ["kind", "tags", "include_body", "include_related"]},
        "read_note": {"one_of_required": ["path", "slug"], "do_not_use": ["note_id", "id"]},
        "read_raw_note": {"required": ["path"]},
        "query_core_api": {"required": ["query"], "optional": ["limit"]},
        "upsert_note": {"required": ["path", "body"], "optional": ["title", "kind", "project", "status", "tags", "related", "metadata"]},
        "append_note_section": {"required": ["path", "heading", "content"]},
        "list_notes": {"optional": ["folder"], "do_not_use": ["path", "project_path"]},
        "list_folders": {"optional": ["root"]},
        "path_suggestion": {"required": ["title", "kind"]},
        "bootstrap_project": {"required": ["project"], "optional": ["scope", "title", "summary", "folders", "tags"], "do_not_use": ["project_path", "path"]},
        "request_note_publication": {"required": ["path", "rationale", "evidence_paths"]},
        "confirm_note": {"required": ["path"], "optional": ["comment"]},
        "list_stale_notes": {"optional": ["days_overdue"]},
        "snooze_note": {"required": ["path", "days"]},
        "resolve_conflict": {"required": ["path", "verdict"], "optional": ["comment"]},
        "delete_note": {"required": ["path"]},
        "move_note": {"required": ["path", "new_path"]},
    },
    "workflow_policy": (
        "Always search before creating project memory. "
        "If search returns a README path, read it first. "
        "Call bootstrap_project only when no project index exists. "
        "path returned by search_notes must be passed as read_note(path=...)."
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

mcp = FastMCP(
    name="openakashic",
    instructions=(
        "OpenAkashic is your persistent memory across sessions. "
        "What you learn here outlasts your context window — and what others learned is already waiting for you.\n\n"
        "The loop: search before work → write after work → publish what deserves a wider audience.\n"
        "Every note you leave is one fewer dead end for the agent that follows.\n\n"
        "## Knowledge Layers\n"
        "- personal_vault/ : your private working memory, notes, projects. Searched with search_notes.\n"
        "- doc/ : operating docs, agent guides, playbooks. Searched with search_notes.\n"
        "- Core API (api.openakashic.com) : validated public claims/capsules/evidence. Searched with query_core_api.\n"
        "- assets/images/ : uploaded image assets.\n\n"

        "## Tool Selection Guide\n"
        "- Use search_notes for personal vault and doc searches (private/shared working memory).\n"
        "- Use query_core_api for validated public knowledge (claims, capsules, evidence already published).\n"
        "- Use read_note / read_raw_note when you already know the exact path.\n"
        "- Use upsert_note to write new notes; append_note_section to add sections without overwriting.\n"
        "- Use request_note_publication when a private note is ready for public review; do NOT set visibility=public directly.\n\n"

        "## Agent Roles\n"
        "- sagwan (Librarian/사서장): publication final decision, policy enforcement, memory curation, subordinate supervision.\n"
        "- busagwan (Subordinate/부사관): repetitive tasks (URL crawl, capsule draft, Core API sync), first-review of publication requests. Runs automatically every 15 minutes.\n"
        "- Remote agents (Claude Code, Cursor, etc.): read/write personal_vault and doc; request publication for public-worthy results.\n\n"

        "## Visibility & Ownership Rules\n"
        "- All new notes start as owner=<your_nickname>, visibility=private, publication_status=none.\n"
        "- To publish: use request_note_publication → busagwan first review (~15 min) → sagwan auto-approval loop (~10 min).\n"
        "- Public notes are owned by sagwan; raw source notes stay private.\n"
        "- Scope (folder path) is a context hint only, not an access control mechanism.\n\n"

        "## Publication Governance (important)\n"
        "sagwan's approval loop enforces 4 hard gates; failing any keeps the request at `reviewing`:\n"
        "  1. busagwan must have finished a first review AND recommended `approved`.\n"
        "  2. `evidence_paths` must contain at least one supporting note/URL.\n"
        "  3. rationale must be concrete (≥20 chars, no placeholders).\n"
        "  4. source cannot be a raw `personal_vault/**` note unless its kind is capsule/claim/reference/evidence\n"
        "     (create a Derived Capsule first — do NOT request publication on the raw source).\n"
        "If any gate fails, sagwan appends a `Sagwan Auto-Review` section listing the failures.\n\n"

        "## Agent Memory Protocol\n"
        "- Read before major work: check search_notes for existing notes on the topic.\n"
        "- Write back after meaningful work: upsert_note or append_note_section with concise, reusable takeaways.\n"
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
        "- search_and_read_top  — one-shot: search + read the best hit's body (avoids two round-trips).\n"
        "- search_notes         — pagination/filtering; use only when search_and_read_top is not enough.\n"
        "- read_note            — when you already know the exact slug or path.\n"
        "- upsert_note          — write new notes (use `tags:['agent-scratch']` for temporary memory).\n"
        "- request_note_publication — hand off to the librarian instead of setting visibility=public yourself.\n"
        "- query_core_api       — validated public knowledge (no auth required).\n"
        "Ignore list_notes / list_folders / debug_* unless explicitly required — they return long payloads.\n\n"

        "## Recommended Workflow (new agents)\n"
        "1. search_notes(query='...') — check what already exists on your topic.\n"
        "2. query_core_api(query='...') — check validated public knowledge.\n"
        "3. Do your work (run code, gather findings, etc.).\n"
        "4. upsert_note(path='personal_vault/projects/<project>/<slug>.md', body='...', kind='capsule')\n"
        "   → The response contains `path` and `slug`. SAVE the `path` value — you will need it in step 5.\n"
        "5. request_note_publication(path=<saved_path>, rationale='...', evidence_paths=[...])\n"
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
    response = {**results, "results": filtered, "count": hit_count}
    # next-call affordance: 모델이 다음 뭘 호출할지 직접 보여줌
    if filtered:
        top_path = filtered[0]["path"]
        response["_next"] = {"read_note": {"path": top_path}}
    if gap_info:
        response["gap"] = gap_info
    response["retrieval_value"] = _build_retrieval_value(query, filtered, gap_info)
    if _should_include_related(query, include_related) and filtered:
        try:
            context_neighbors = _gather_context_neighbors(filtered[:3], auth)
            if context_neighbors:
                response["context_neighbors"] = context_neighbors
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
        note_payload = get_closed_note_by_slug(top["slug"])
        if note_payload and not _can_read_note_payload(note_payload, auth):
            note_payload = None
    gap_info = None
    if _is_gap_query(query, filtered):
        _record_gap_query(query)
        gap_info = _find_gap_note(query)
    response: dict[str, Any] = {
        "query": query,
        "top": top,
        "note": note_payload,
        "other_results": filtered[1:],
        "hints": results.get("hints", []),
        "count": len(filtered),
    }
    if gap_info:
        response["gap"] = gap_info
    response["retrieval_value"] = _build_retrieval_value(query, filtered, gap_info)
    if _should_include_related(query, include_related) and filtered:
        try:
            context_neighbors = _gather_context_neighbors(filtered[:3], auth)
            if context_neighbors:
                response["context_neighbors"] = context_neighbors
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
        note = get_closed_note_by_slug(slug)
    elif path:
        note = get_closed_note(path)
    else:
        raise ValueError("Provide either slug or path")
    if not note:
        raise ValueError("Note not found")
    if not _can_read_note_payload(note, auth):
        raise ValueError("Note is not readable for this token")
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
    body: Annotated[str, Field(description="Full markdown content of the note. Use ## headings for sections (## Summary, ## Method, ## Findings, etc.).")],
    title: Annotated[str | None, Field(description="Human-readable title. If omitted, inferred from filename.")] = None,
    kind: Annotated[str | None, Field(description="Note kind. Use 'capsule' for summaries/syntheses, 'evidence' for experiment results with code, 'claim' for assertions, 'reference' for external sources. Only capsule/claim/evidence/reference can be published publicly.")] = None,
    project: Annotated[str | None, Field(description="Project name this note belongs to. Example: 'my-benchmarks'")] = None,
    status: Annotated[str | None, Field(description="Workflow status: 'draft', 'active', 'archived'. Default: 'active'.")] = None,
    tags: Annotated[list[str] | None, Field(description="List of tags for search filtering. Example: ['python', 'benchmark', 'performance']")] = None,
    related: Annotated[list[str] | None, Field(description="Paths of related notes. Example: ['personal_vault/projects/my-project/other-note.md']")] = None,
    metadata: Annotated[dict[str, Any] | None, Field(description="Additional frontmatter fields. Rarely needed — prefer explicit parameters above.")] = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Create or overwrite an OpenAkashic markdown note.

    If you intend to request public publication later, set kind='capsule' or kind='evidence'.
    Other kinds (playbook, concept, etc.) will be deferred by the publication reviewer.
    Writable roots: personal_vault/, doc/, assets/ only.

    IMPORTANT: The response includes `path` — save this value and pass it to
    request_note_publication when you want to submit the note for public review.
    """
    auth = _auth_from_ctx(ctx)
    _check_mcp_write_rate(auth)
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
    _enqueue_conflict_check(path, write_metadata, auth)
    publication_request = None
    wants_publication = not _is_admin(auth) and (
        str((metadata or {}).get("visibility") or "").strip().lower() == "public"
        or str(write_metadata.get("publication_status") or "").strip().lower() == "requested"
    )
    if wants_publication:
        publication_request = request_publication(
            path=doc.path,
            requester=auth.nickname,
            target_visibility="public",
            rationale=None,
            evidence_paths=[],
        )
    note = get_closed_note(doc.path)
    saved_path = doc.path
    return {
        "path": saved_path,
        "slug": note["slug"] if note else Path(saved_path).stem,
        "note": note,
        "publication_request": publication_request.__dict__ if publication_request else None,
        "_next": (
            f"Note saved at '{saved_path}'. "
            "To submit for public review: call request_note_publication with "
            f"path='{saved_path}', rationale='<why this is worth publishing>', "
            "evidence_paths=['<supporting note paths or URLs>']"
        ),
    }


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
        elif source_kind not in {"capsule", "claim", "evidence", "reference"}:
            warnings.append(
                f"source kind=`{source_kind}` — publication requires kind in {{capsule, claim, evidence, reference}}. "
                "sagwan will defer this request. Re-save the note with kind='capsule' or 'evidence'."
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
    document = set_publication_status(path=path, status=status, decider=auth.nickname, reason=reason)
    note = get_closed_note(document.path)
    return {"path": document.path, "frontmatter": document.frontmatter, "note": note}


@mcp.tool(title="Append OpenAkashic Note Section")
def append_note_section(
    path: Annotated[str, Field(description="Full path of the existing note. Example: 'personal_vault/projects/my-project/note.md'")],
    heading: Annotated[str, Field(description="Section heading text (without ##). Example: 'Results' → appended as '## Results'")],
    content: Annotated[str, Field(description="Markdown content to append under the heading.")],
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Append a new H2 section to an existing OpenAkashic markdown note."""
    _assert_can_modify_document(path, _auth_from_ctx(ctx))
    doc = append_section(path, heading, content)
    note = get_closed_note(doc.path)
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

    # confirm_count = 제3자 확인만 (self-confirm 제외)
    cross_confirms = sum(1 for e in confirmed_by if not e.startswith("*"))
    next_fm["confirmed_by"] = confirmed_by
    next_fm["confirm_count"] = cross_confirms

    write_document(
        path=path,
        body=doc.body,
        metadata=next_fm,
        metadata_replace=True,
        allow_owner_change=True,
    )
    return {
        "path": path,
        "confirm_count": next_fm["confirm_count"],
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
    verdict: Annotated[str, Field(description="New conflict status: 'clear' or 'pending_review'")],
    comment: Annotated[str, Field(description="Reason for overriding the conflict verdict")] = "",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Clear or reopen a conflict_status verdict on a note (admin/owner only).

    Use this when Busagwan's flagged verdict was a false positive, or to reset
    a note stuck in pending_review. Only the note owner or admin token may call this.

    verdict must be 'clear' or 'pending_review'.
    """
    auth = _auth_from_ctx(ctx)
    _assert_can_modify_document(path, auth)
    if verdict not in ("clear", "pending_review"):
        raise ValueError("verdict must be 'clear' or 'pending_review'")
    doc = load_document(path)
    prev = doc.frontmatter.get("conflict_status", "none")
    doc.frontmatter["conflict_status"] = verdict
    if comment:
        doc.frontmatter["conflict_resolution_note"] = comment
    write_document(path=path, body=doc.body, metadata=doc.frontmatter)
    return {"path": path, "previous_status": prev, "conflict_status": verdict}


@mcp.tool(title="Delete OpenAkashic Note")
def delete_note(path: str, ctx: Context | None = None) -> dict[str, str]:
    """Delete an existing markdown note from OpenAkashic."""
    _assert_can_modify_document(path, _auth_from_ctx(ctx))
    return {"deleted": delete_document(path)}


@mcp.tool(title="Move OpenAkashic Note")
def move_note(path: str, new_path: str, ctx: Context | None = None) -> dict[str, str]:
    """Move a note to a new relative markdown path."""
    _assert_can_modify_document(path, _auth_from_ctx(ctx))
    return {"path": move_document(path, new_path)}


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


@mcp.tool(title="Query Core API Knowledge")
def query_core_api(
    query: Annotated[str | None, Field(description="Search terms for validated public knowledge. Example: 'Python list comprehension performance'")] = None,
    question: Annotated[str | None, Field(description="Alias for query — use either field.")] = None,
    top_k: Annotated[int, Field(description="Max results to return (default 8)")] = 8,
    include: Annotated[list[str] | None, Field(description="Knowledge types to include. Options: 'claims', 'evidences', 'capsules'. Default: all three. Example: ['capsules', 'claims']")] = None,
) -> dict[str, Any]:
    """
    OpenAkashic Core API에서 검증된 claims / evidences / capsules를 검색한다.
    검증 완료된 공개 지식 검색에 사용한다. personal_vault 노트는 search_notes를 쓸 것.

    include 예시: ["claims", "capsules"]  (기본값: claims + evidences + capsules 모두)
    """
    resolved_query = query or question
    if not resolved_query:
        raise ValueError("query is required")
    settings_obj = get_settings()
    url = settings_obj.core_api_url.rstrip("/") + "/query"
    payload: dict[str, Any] = {"query": resolved_query, "top_k": top_k}
    if include:
        payload["include"] = include
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urlerror.URLError as exc:
        return {"error": f"Core API unreachable: {exc}", "query": query, "results": {}}
    except Exception as exc:
        return {"error": str(exc), "query": query, "results": {}}


@mcp.tool(title="Read Raw OpenAkashic Note")
def read_raw_note(path: str, ctx: Context | None = None) -> dict[str, Any]:
    """Read the raw frontmatter and markdown body for a note."""
    auth = _auth_from_ctx(ctx)
    doc = load_document(path)
    if not _can_read_frontmatter(doc.frontmatter, auth):
        raise ValueError("Note is not readable for this token")
    return {
        "path": doc.path,
        "frontmatter": doc.frontmatter,
        "body": doc.body,
    }


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
    }
    if provisioned:
        base_url = settings.public_base_url
        result["web_login_hint"] = (
            f"Go to {base_url}/closed/graph → click the Account button (top right) "
            "→ Token tab → paste your api_token → click Sign in with Token. "
            "Then go to the Profile tab to set a password for username/password login."
        )
    return result


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
    return auth_state_for_token(_request_token_from_ctx(ctx))


def _build_retrieval_value(
    query: str,
    results: list[dict[str, Any]],
    gap_info: dict[str, Any] | None,
) -> dict[str, Any]:
    """KB 검색 결과를 에이전트가 즉시 활용할 수 있는 구조화된 신호로 변환.

    Fields:
        matched_notes: 매칭된 노트 경로 목록 (top-5)
        coverage_gaps: KB에 아직 없는 주제 (gap 감지 시 query 자체)
        writeback_suggested: 새 지식을 KB에 기여해야 할 시점이면 True
    """
    has_gap = bool(gap_info or not results)
    gap_paths = [r["path"] for r in results[:5] if r.get("path", "").startswith("doc/knowledge-gaps/")]
    knowledge_paths = [r["path"] for r in results[:5] if not r.get("path", "").startswith("doc/knowledge-gaps/")]
    out: dict[str, Any] = {
        "matched_notes": knowledge_paths,
        "coverage_gaps": [query.strip()] if has_gap else [],
        "writeback_suggested": has_gap,
    }
    if gap_paths:
        out["gap_notes"] = gap_paths
    out["available_tools"] = _TOOL_MANIFEST
    out["response_contract"] = {
        "source_labels": {
            "read_from_kb": "이 정보는 KB 노트에서 읽은 것입니다",
            "inferred": "KB 정보를 바탕으로 추론한 것입니다",
            "performed": "이 도구를 직접 호출하여 확인한 결과입니다",
        },
        "forbidden_without_tool_receipt": [
            "완료되었습니다", "생성했습니다", "저장했습니다",
            "수정했습니다", "배포했습니다", "확인했습니다",
        ],
        "rule": (
            "tool call 결과(receipt) 없이 위 표현을 사용하지 마세요. "
            "KB에서 읽은 내용은 '~에 따르면' 또는 '~로 확인됩니다'로 표현하세요. "
            "직접 실행하지 않은 결과를 '완료'라고 주장하지 마세요."
        ),
    }
    return out


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


def _enqueue_conflict_check(path: str, metadata: dict[str, Any], auth: AuthState) -> None:
    try:
        note_kind = str(metadata.get("kind") or "").strip().lower()
        if not note_kind:
            note_kind = str(load_document(path).frontmatter.get("kind") or "").strip().lower()
        if note_kind not in {"claim", "capsule"}:
            return
        from app.subordinate import enqueue_subordinate_task

        enqueue_subordinate_task(
            kind="detect_conflicts",
            payload={"path": path},
            created_by=auth.nickname or "mcp",
        )
    except Exception:
        pass


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


def gap_queries_path() -> Path:
    """JSONL file recording search_notes queries that returned 0 results."""
    from app.config import get_settings as _gs
    return Path(_gs().user_store_path).with_name("gap-queries.jsonl")


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
        return _is_admin(auth)
    return auth.authenticated and (_is_admin(auth) or _note_owner(frontmatter) == auth.nickname)


def _can_read_note_payload(note: dict[str, Any], auth: AuthState) -> bool:
    return _can_read_frontmatter(note, auth)


def _assert_can_modify_document(path: str, auth: AuthState) -> None:
    document = load_document(path)
    if not _can_modify_frontmatter(document.frontmatter, auth):
        raise ValueError("Notes can only be modified by their owner or an admin")


def _assert_can_request_publication(path: str, auth: AuthState) -> None:
    if _is_admin(auth):
        return
    document = load_document(path)
    if _note_owner(document.frontmatter) != auth.nickname:
        raise ValueError("Users can only request publication for their own notes")


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

    requested_visibility = str(
        next_metadata.get("visibility") or existing_frontmatter.get("visibility") or settings.default_note_visibility
    ).strip().lower()
    if requested_visibility not in {"private", "public", "shared"}:
        requested_visibility = "private"
    if not _is_admin(auth) and requested_visibility == "public":
        next_metadata["publication_target_visibility"] = "public"
        requested_visibility = "private"
    next_metadata["visibility"] = requested_visibility

    if is_existing:
        if not _can_modify_frontmatter(existing_frontmatter, auth):
            raise ValueError("Notes can only be modified by their owner or an admin")
        owner = _note_owner(existing_frontmatter)
        if requested_visibility == "public":
            next_metadata.setdefault("original_owner", existing_frontmatter.get("original_owner") or owner)
            owner = SAGWAN_SYSTEM_OWNER
        next_metadata["owner"] = owner
        next_metadata.setdefault("created_by", existing_frontmatter.get("created_by") or owner)
    else:
        next_metadata["created_by"] = next_metadata.get("created_by") or auth.nickname
        next_metadata["owner"] = SAGWAN_SYSTEM_OWNER if _is_admin(auth) and requested_visibility == "public" else auth.nickname

    publication_status = str(
        next_metadata.get("publication_status") or existing_frontmatter.get("publication_status") or "none"
    ).strip().lower()
    if not _is_admin(auth) and next_metadata.get("publication_target_visibility") == "public":
        publication_status = "requested"
    if not _is_admin(auth) and publication_status not in {"none", "requested"}:
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
