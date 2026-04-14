from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.auth import format_json_text
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
    name="closed-akashic",
    instructions=(
        "Closed Akashic is the user's long-lived private memory store. "
        "Remote agents should use this MCP server as the central memory layer instead of local agent-knowledge clones. "
        "Read before major work, prefer existing notes, and write back concise linked notes after meaningful work. "
        "Use doc/ for operating docs, personal_vault/ for graph-linked working memory, and assets/images/ for uploaded images. "
        "New notes default to owner=aaron and visibility=private. "
        "Scope is only a folder/context hint; access is controlled by owner, visibility, and publication_status. "
        "Do not publish raw source directly; use request_publication for explicit public promotion review."
    ),
    host="0.0.0.0",
    streamable_http_path="/",
    stateless_http=True,
    json_response=True,
)


@mcp.resource("closed-akashic://index")
def closed_akashic_index() -> str:
    return format_json_text(
        {
            "base_url": settings.public_base_url,
            "paths": list_note_paths(),
            "writable_roots": settings.writable_root_list,
        }
    )


@mcp.resource("closed-akashic://graph")
def closed_akashic_graph() -> str:
    return format_json_text(get_closed_graph())


@mcp.resource("closed-akashic://agent-bootstrap")
def closed_akashic_agent_bootstrap() -> str:
    return format_json_text(
        {
            "base_url": settings.public_base_url,
            "mcp_url": f"{settings.public_base_url}/mcp",
            "api_base": f"{settings.public_base_url}/api",
            "auth_env_var": "CLOSED_AKASHIC_TOKEN",
            "read_first": [
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


@mcp.resource("closed-akashic://notes/{slug}")
def closed_akashic_note_resource(slug: str) -> str:
    note = get_closed_note_by_slug(slug)
    if not note:
        return format_json_text({"error": f"Note not found: {slug}"})
    return format_json_text(note)


@mcp.tool(title="Search Closed Akashic")
def search_notes(query: str, limit: int = 8) -> dict[str, Any]:
    """Search the Closed Akashic vault by note title, tags, summary, and body."""
    return search_closed_notes(query, limit=limit)


@mcp.tool(title="Read Closed Note")
def read_note(slug: str | None = None, path: str | None = None) -> dict[str, Any]:
    """Read a note by slug or relative markdown path."""
    if slug:
        note = get_closed_note_by_slug(slug)
    elif path:
        note = get_closed_note(path)
    else:
        raise ValueError("Provide either slug or path")
    if not note:
        raise ValueError("Note not found")
    return note


@mcp.tool(title="List Closed Notes")
def list_notes(folder: str | None = None) -> dict[str, Any]:
    """List markdown note paths in Closed Akashic, optionally filtered by top-level folder."""
    notes = list_note_paths()
    if folder:
        prefix = folder.strip("/").rstrip("/") + "/"
        notes = [path for path in notes if path.startswith(prefix)]
    return {"notes": notes, "count": len(notes)}


@mcp.tool(title="List Closed Folders")
def list_folders() -> dict[str, Any]:
    """List the organized folder map used for Closed Akashic notes and assets."""
    return {
        "rules": folder_rules(),
        "existing": folder_index(),
    }


@mcp.tool(title="Debug Recent Closed Requests")
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
    """Inspect and filter recent Closed Akashic API/MCP requests without exposing bearer tokens."""
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


@mcp.tool(title="Tail Closed Request Log")
def debug_log_tail(limit: int = 100) -> dict[str, Any]:
    """Tail the persistent Closed Akashic request JSONL log."""
    return {
        "lines": log_tail(limit=limit),
        "observability": observability_status(),
    }


@mcp.tool(title="Suggest Closed Note Path")
def path_suggestion(
    title: str,
    kind: str | None = None,
    folder: str | None = None,
    scope: str | None = None,
    project: str | None = None,
) -> dict[str, str]:
    """Suggest a note path based on note kind and the Closed Akashic folder rules."""
    return {"path": suggest_note_path(kind, title, folder, scope, project)}


@mcp.tool(title="Bootstrap Closed Project")
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


@mcp.tool(title="Upsert Closed Note")
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
) -> dict[str, Any]:
    """Create or overwrite a Closed Akashic markdown note."""
    write_metadata = dict(metadata or {})
    write_metadata.pop("owner", None)
    write_metadata.setdefault("created_by", "aaron")
    visibility = str(write_metadata.get("visibility") or settings.default_note_visibility).strip().lower()
    if visibility == "public":
        write_metadata["owner"] = "sagwan"
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
    note = get_closed_note(doc.path)
    return {
        "path": doc.path,
        "slug": note["slug"] if note else Path(doc.path).stem,
        "note": note,
    }


@mcp.tool(title="Request Closed Note Publication")
def request_note_publication(
    path: str,
    requester: str | None = None,
    target_visibility: str = "public",
    rationale: str | None = None,
    evidence_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Request librarian review for public publication. Source remains private by default."""
    request = request_publication(
        path=path,
        requester=requester,
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


@mcp.tool(title="Append Closed Note Section")
def append_note_section(path: str, heading: str, content: str) -> dict[str, Any]:
    """Append a new H2 section to an existing Closed Akashic markdown note."""
    doc = append_section(path, heading, content)
    note = get_closed_note(doc.path)
    return {
        "path": doc.path,
        "note": note,
    }


@mcp.tool(title="Delete Closed Note")
def delete_note(path: str) -> dict[str, str]:
    """Delete an existing markdown note from Closed Akashic."""
    return {"deleted": delete_document(path)}


@mcp.tool(title="Move Closed Note")
def move_note(path: str, new_path: str) -> dict[str, str]:
    """Move a note to a new relative markdown path."""
    return {"path": move_document(path, new_path)}


@mcp.tool(title="Create Closed Folder")
def create_folder(path: str) -> dict[str, str]:
    """Create a folder inside an allowed Closed Akashic root."""
    return {"path": ensure_folder(path)}


@mcp.tool(title="Move Closed Folder")
def rename_folder(path: str, new_path: str) -> dict[str, str]:
    """Move or rename a folder inside an allowed Closed Akashic root."""
    return {"path": move_folder(path, new_path)}


@mcp.tool(title="Upload Closed Image")
def upload_image(
    filename: str,
    content_base64: str,
    folder: str = "assets/images",
    alt: str | None = None,
) -> dict[str, Any]:
    """Upload an image into Closed Akashic assets and return embeddable markdown."""
    content = base64.b64decode(content_base64)
    asset = save_image(filename=filename, content=content, folder=folder, alt=alt)
    return {
        "path": asset.path,
        "url": asset.url,
        "markdown": asset.markdown,
        "mime_type": asset.mime_type,
        "size": asset.size,
    }


@mcp.tool(title="Read Raw Closed Note")
def read_raw_note(path: str) -> dict[str, Any]:
    """Read the raw frontmatter and markdown body for a note."""
    doc = load_document(path)
    return {
        "path": doc.path,
        "frontmatter": doc.frontmatter,
        "body": doc.body,
    }
