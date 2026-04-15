from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib import error as urlerror

from mcp.server.fastmcp import Context, FastMCP

from app.auth import AuthState, auth_state_for_token, format_json_text
from app.config import get_settings
from app.observability import log_tail, observability_status, recent_requests
from app.users import SAGWAN_SYSTEM_OWNER
from app.site import (
    get_closed_graph,
    get_closed_note,
    get_closed_note_by_slug,
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

mcp = FastMCP(
    name="openakashic",
    instructions=(
        "OpenAkashic is a visibility-aware knowledge network and agent memory surface.\n\n"

        "## Knowledge Layers\n"
        "- personal_vault/ : private working memory, notes, projects. Searched with search_notes.\n"
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
        "  4. source cannot be a raw `personal_vault/**` note unless its kind is capsule/claim/reference\n"
        "     (create a Derived Capsule first — do NOT request publication on the raw source).\n"
        "If any gate fails, sagwan appends a `Sagwan Auto-Review` section listing the failures.\n\n"

        "## Agent Memory Protocol\n"
        "- Read before major work: check search_notes for existing notes on the topic.\n"
        "- Write back after meaningful work: upsert_note or append_note_section with concise, reusable takeaways.\n"
        "- Prefer linking related notes via the 'related' field rather than duplicating content.\n"
        "- For bootstrap: use bootstrap_project to initialize a new project workspace with standard folders.\n\n"

        "## Small-Model / Low-Context Profile\n"
        "If your context window is tight or you run a small model (≤8B), prefer this minimal toolset:\n"
        "- search_and_read_top  — one-shot: search + read the best hit's body (avoids two round-trips).\n"
        "- search_notes         — pagination/filtering; use only when search_and_read_top is not enough.\n"
        "- read_note            — when you already know the exact slug or path.\n"
        "- upsert_note          — write new notes (use `tags:['agent-scratch']` for temporary memory).\n"
        "- request_note_publication — hand off to the librarian instead of setting visibility=public yourself.\n"
        "- query_core_api       — validated public knowledge (no auth required).\n"
        "Ignore list_notes / list_folders / debug_* unless explicitly required — they return long payloads.\n\n"

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
    query: str,
    limit: int = 8,
    kind: str | None = None,
    tags: list[str] | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Search OpenAkashic by note title, tags, summary, and body.

    Optional filters:
    - kind: restrict to a specific note kind (e.g. "capsule", "playbook", "claim")
    - tags: list of tags — only notes containing ALL specified tags are returned
    """
    auth = _auth_from_ctx(ctx)
    results = search_closed_notes(query, limit=limit, kind=kind, tags=tags)
    filtered = [item for item in results.get("results", []) if _can_read_note_payload(item, auth)]
    return {**results, "results": filtered, "count": len(filtered)}


@mcp.tool(title="Search And Read Top OpenAkashic Note")
def search_and_read_top(
    query: str,
    kind: str | None = None,
    tags: list[str] | None = None,
    include_body: bool = True,
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
    return {
        "query": query,
        "top": top,
        "note": note_payload,
        "other_results": filtered[1:],
        "hints": results.get("hints", []),
        "count": len(filtered),
    }


@mcp.tool(title="Read OpenAkashic Note")
def read_note(slug: str | None = None, path: str | None = None, ctx: Context | None = None) -> dict[str, Any]:
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
    title: str,
    kind: str | None = None,
    folder: str | None = None,
    scope: str | None = None,
    project: str | None = None,
) -> dict[str, str]:
    """Suggest a note path based on note kind and the OpenAkashic folder rules."""
    return {"path": suggest_note_path(kind, title, folder, scope, project)}


@mcp.tool(title="Bootstrap OpenAkashic Project")
def bootstrap_project(
    project: str,
    scope: str | None = None,
    title: str | None = None,
    summary: str | None = None,
    canonical_docs: list[str] | None = None,
    folders: list[str] | None = None,
    tags: list[str] | None = None,
    related: list[str] | None = None,
) -> dict[str, Any]:
    """Create or verify a project workspace with README index and optional agent-defined subfolders."""
    return bootstrap_project_workspace(
        project=normalize_project_key(project, scope),
        title=title,
        summary=summary,
        canonical_docs=canonical_docs,
        folders=folders,
        tags=tags,
        related=related,
    )


@mcp.tool(title="Upsert OpenAkashic Note")
def upsert_note(
    path: str,
    body: str,
    title: str | None = None,
    kind: str | None = None,
    project: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
    related: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Create or overwrite an OpenAkashic markdown note."""
    auth = _auth_from_ctx(ctx)
    write_metadata = _normalize_write_metadata(path=path, metadata=metadata or {}, auth=auth)
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
    return {
        "path": doc.path,
        "slug": note["slug"] if note else Path(doc.path).stem,
        "note": note,
        "publication_request": publication_request.__dict__ if publication_request else None,
    }


@mcp.tool(title="Request OpenAkashic Note Publication")
def request_note_publication(
    path: str,
    requester: str | None = None,
    target_visibility: str = "public",
    rationale: str | None = None,
    reason: str | None = None,
    evidence_paths: list[str] | None = None,
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
                "sagwan will defer this request."
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
def append_note_section(path: str, heading: str, content: str, ctx: Context | None = None) -> dict[str, Any]:
    """Append a new H2 section to an existing OpenAkashic markdown note."""
    _assert_can_modify_document(path, _auth_from_ctx(ctx))
    doc = append_section(path, heading, content)
    note = get_closed_note(doc.path)
    return {
        "path": doc.path,
        "note": note,
    }


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
    query: str,
    top_k: int = 8,
    include: list[str] | None = None,
) -> dict[str, Any]:
    """
    OpenAkashic Core API에서 검증된 claims / evidences / capsules를 검색한다.
    검증 완료된 공개 지식 검색에 사용한다. personal_vault 노트는 search_notes를 쓸 것.

    include 예시: ["claims", "capsules"]  (기본값: claims + evidences + capsules 모두)
    """
    settings_obj = get_settings()
    url = settings_obj.core_api_url.rstrip("/") + "/query"
    payload: dict[str, Any] = {"query": query, "top_k": top_k}
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


def _is_admin(auth: AuthState) -> bool:
    return auth.role == "admin"


def _note_visibility(frontmatter: dict[str, Any]) -> str:
    visibility = str(frontmatter.get("visibility") or settings.default_note_visibility).strip().lower()
    return visibility if visibility in {"private", "public"} else "private"


def _note_owner(frontmatter: dict[str, Any]) -> str:
    return str(frontmatter.get("owner") or settings.default_note_owner).strip() or settings.default_note_owner


def _can_read_frontmatter(frontmatter: dict[str, Any], auth: AuthState) -> bool:
    if _note_visibility(frontmatter) == "public":
        return True
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


def _normalize_write_metadata(*, path: str, metadata: dict[str, Any], auth: AuthState) -> dict[str, Any]:
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
    if requested_visibility not in {"private", "public"}:
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
    return next_metadata
