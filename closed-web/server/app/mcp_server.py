from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from app.auth import AuthState, auth_state_for_token, format_json_text
from app.config import get_settings
from app.observability import log_tail, observability_status, recent_requests
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
        "OpenAkashic is a visibility-aware knowledge network for private working memory, public evidence, reusable capsules, and agent memory. "
        "Remote agents should use this MCP server as the central memory and contribution layer instead of local agent-knowledge clones. "
        "Read before major work, prefer existing notes, and write back concise linked notes after meaningful work. "
        "Use doc/ for operating docs, personal_vault/ for graph-linked working memory, and assets/images/ for uploaded images. "
        "New notes default to the current token owner's nickname and visibility=private. "
        "Scope is only a folder/context hint; access is controlled by owner, visibility, and publication_status. "
        "Do not publish raw source directly; use request_note_publication for explicit Busagwan first review and Sagwan/admin final review. "
        "The historical closed-akashic MCP name, URI aliases, and CLOSED_AKASHIC_TOKEN env var may remain for compatibility, but user-facing behavior is OpenAkashic."
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
def search_notes(query: str, limit: int = 8, ctx: Context | None = None) -> dict[str, Any]:
    """Search OpenAkashic by note title, tags, summary, and body."""
    auth = _auth_from_ctx(ctx)
    results = search_closed_notes(query, limit=limit)
    filtered = [item for item in results.get("results", []) if _can_read_note_payload(item, auth)]
    return {**results, "results": filtered, "count": len(filtered)}


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
) -> dict[str, Any]:
    """Inspect and filter recent OpenAkashic API/MCP requests without exposing bearer tokens."""
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
def debug_log_tail(limit: int = 100) -> dict[str, Any]:
    """Tail the persistent OpenAkashic request JSONL log."""
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
    evidence_paths: list[str] | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Request librarian review for public publication. Source remains private by default."""
    auth = _auth_from_ctx(ctx)
    _assert_can_request_publication(path, auth)
    request = request_publication(
        path=path,
        requester=requester if _is_admin(auth) else auth.nickname,
        target_visibility=target_visibility,
        rationale=rationale,
        evidence_paths=evidence_paths,
    )
    return {"request": request.__dict__}


@mcp.tool(title="List Publication Requests")
def list_note_publication_requests(status: str | None = None) -> dict[str, Any]:
    """List librarian publication requests."""
    requests = list_publication_requests(status=status)
    return {
        "requests": [item.__dict__ for item in requests],
        "count": len(requests),
    }


@mcp.tool(title="Set Publication Status")
def set_note_publication_status(path: str, status: str, reason: str | None = None) -> dict[str, Any]:
    """Admin/librarian-only publication decision helper. published also sets visibility=public."""
    document = set_publication_status(path=path, status=status, decider="sagwan", reason=reason)
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
            owner = "sagwan"
        next_metadata["owner"] = owner
        next_metadata.setdefault("created_by", existing_frontmatter.get("created_by") or owner)
    else:
        next_metadata["created_by"] = next_metadata.get("created_by") or auth.nickname
        next_metadata["owner"] = "sagwan" if _is_admin(auth) and requested_visibility == "public" else auth.nickname

    publication_status = str(
        next_metadata.get("publication_status") or existing_frontmatter.get("publication_status") or "none"
    ).strip().lower()
    if not _is_admin(auth) and next_metadata.get("publication_target_visibility") == "public":
        publication_status = "requested"
    if not _is_admin(auth) and publication_status not in {"none", "requested"}:
        raise ValueError("Users can only set publication status to none or requested")
    next_metadata["publication_status"] = publication_status or "none"
    return next_metadata
