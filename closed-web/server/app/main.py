from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from app.auth import (
    AuthState,
    BearerTokenASGI,
    auth_state_dict,
    librarian_identity_dict,
    require_admin_token,
    require_agent_token,
)
from app.config import get_settings
from app.librarian import ensure_librarian_workspace, librarian_chat, librarian_status
from app.mcp_server import mcp
from app.observability import (
    RequestLogMiddleware,
    configure_observability,
    log_tail,
    observability_status,
    recent_requests,
)
from app.site import (
    closed_debug_html,
    closed_graph_html,
    closed_note_html,
    get_closed_graph,
    get_closed_home_note,
    get_closed_note,
    get_closed_note_by_slug,
    search_closed_notes,
)
from app.vault import (
    append_section,
    bootstrap_project_workspace,
    delete_document,
    folder_index,
    folder_rules,
    list_publication_requests,
    load_document,
    move_document,
    move_folder,
    normalize_project_key,
    request_publication,
    read_asset_bytes,
    save_asset,
    save_image,
    set_publication_status,
    ensure_folder,
    suggest_note_path,
    write_document,
)


settings = get_settings()
configure_observability(settings.log_dir, settings.recent_request_limit)

api = FastAPI(
    title="Closed Akashic",
    version="0.2.0",
    description="Private published knowledge base and agent memory surface for the Closed Akashic repository.",
)

api.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NoteWriteRequest(BaseModel):
    path: str = Field(min_length=1)
    body: str = Field(min_length=1)
    title: str | None = None
    kind: str | None = None
    project: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    related: list[str] | None = None
    metadata: dict[str, Any] | None = None


class NoteAppendRequest(BaseModel):
    path: str = Field(min_length=1)
    heading: str = Field(min_length=1)
    content: str = Field(min_length=1)


class NoteDeleteRequest(BaseModel):
    path: str = Field(min_length=1)


class NoteMoveRequest(BaseModel):
    path: str = Field(min_length=1)
    new_path: str = Field(min_length=1)


class FolderRequest(BaseModel):
    path: str = Field(min_length=1)


class FolderMoveRequest(BaseModel):
    path: str = Field(min_length=1)
    new_path: str = Field(min_length=1)


class ProjectBootstrapRequest(BaseModel):
    project: str = Field(min_length=1)
    scope: str | None = None
    title: str | None = None
    summary: str | None = None
    canonical_docs: list[str] | None = None
    folders: list[str] | None = None
    tags: list[str] | None = None
    related: list[str] | None = None


class LibrarianChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread: list[dict[str, str]] = Field(default_factory=list)


class PublicationRequestPayload(BaseModel):
    path: str = Field(min_length=1)
    requester: str | None = None
    target_visibility: str = "public"
    rationale: str | None = None
    evidence_paths: list[str] = Field(default_factory=list)


class PublicationStatusPayload(BaseModel):
    path: str = Field(min_length=1)
    status: str = Field(min_length=1)
    reason: str | None = None


def _route_prefix(request: Request) -> str:
    host = request.headers.get("host", "")
    return "/closed" if host.startswith("openakashic.com") else ""


def _project_key(project: str, scope: str | None = None) -> str:
    return normalize_project_key(project, scope)


def _request_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        return token or None
    cookie_token = request.cookies.get("closed_akashic_token", "").strip()
    if cookie_token:
        return cookie_token
    return None


def _auth_from_request(request: Request) -> AuthState:
    from app.auth import auth_state_for_token

    return auth_state_for_token(_request_token(request))


def _is_admin(auth: AuthState) -> bool:
    return auth.role == "admin" or "librarian:admin" in auth.capabilities


def _can_manage_publication(auth: AuthState) -> bool:
    return _is_admin(auth) or "publication:manage" in auth.capabilities


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


def _assert_can_read_note_payload(note: dict[str, Any], auth: AuthState) -> None:
    if not _can_read_frontmatter(note, auth):
        raise HTTPException(status_code=403, detail="Private notes can only be read by their owner or an admin")


def _assert_can_read_document(document_path: str, auth: AuthState) -> None:
    document = load_document(document_path)
    if not _can_read_frontmatter(document.frontmatter, auth):
        raise HTTPException(status_code=403, detail="Private notes can only be read by their owner or an admin")


def _assert_can_modify_document(document_path: str, auth: AuthState) -> dict[str, Any]:
    document = load_document(document_path)
    if not _can_modify_frontmatter(document.frontmatter, auth):
        raise HTTPException(status_code=403, detail="Notes can only be modified by their owner or an admin")
    return document.frontmatter


def _filter_readable_notes(notes: list[dict[str, Any]], auth: AuthState) -> list[dict[str, Any]]:
    return [note for note in notes if _can_read_frontmatter(note, auth)]


def _normalize_write_metadata(payload: NoteWriteRequest, auth: AuthState) -> dict[str, Any]:
    metadata = dict(payload.metadata or {})
    existing_frontmatter: dict[str, Any] = {}
    is_existing = False
    try:
        existing_frontmatter = load_document(payload.path).frontmatter
        is_existing = True
    except (FileNotFoundError, ValueError):
        existing_frontmatter = {}

    requested_visibility = str(
        metadata.get("visibility") or existing_frontmatter.get("visibility") or settings.default_note_visibility
    ).strip().lower().replace("-", "_")
    if requested_visibility not in {"private", "public"}:
        requested_visibility = "private"
    if not _is_admin(auth) and requested_visibility != "private":
        raise HTTPException(status_code=403, detail="Only admins can make a note public")
    metadata["visibility"] = requested_visibility

    if is_existing:
        if not _can_modify_frontmatter(existing_frontmatter, auth):
            raise HTTPException(status_code=403, detail="Notes can only be modified by their owner or an admin")
        owner = _note_owner(existing_frontmatter)
        if requested_visibility == "public":
            metadata.setdefault("original_owner", existing_frontmatter.get("original_owner") or owner)
            owner = "sagwan"
        metadata["owner"] = owner
    else:
        metadata["created_by"] = metadata.get("created_by") or auth.nickname
        metadata["owner"] = "sagwan" if requested_visibility == "public" else auth.nickname

    publication_status = str(
        metadata.get("publication_status") or existing_frontmatter.get("publication_status") or "none"
    ).strip().lower().replace("-", "_")
    if not _is_admin(auth) and publication_status not in {"none", "requested"}:
        raise HTTPException(status_code=403, detail="Users can only set publication status to none or requested")
    metadata["publication_status"] = publication_status
    return metadata


def _assert_can_request_publication(path: str, auth: AuthState) -> None:
    if _is_admin(auth):
        return
    document = load_document(path)
    owner = str(document.frontmatter.get("owner") or settings.default_note_owner).strip()
    if owner != auth.nickname:
        raise HTTPException(status_code=403, detail="Users can only request publication for their own notes")


def _vault_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, FileExistsError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=exc.__class__.__name__)


@api.get("/", response_class=HTMLResponse)
def root(request: Request) -> str:
    return closed_note_html(route_prefix=_route_prefix(request))


@api.get("/closed", response_class=HTMLResponse)
def prefixed_root() -> str:
    return closed_note_html(route_prefix="/closed")


@api.get("/graph", response_class=HTMLResponse)
def graph_page(request: Request) -> str:
    return closed_graph_html(route_prefix=_route_prefix(request))


@api.get("/closed/graph", response_class=HTMLResponse)
def prefixed_graph_page() -> str:
    return closed_graph_html(route_prefix="/closed")


@api.get("/debug", response_class=HTMLResponse)
def debug_page(request: Request) -> str:
    return closed_debug_html(route_prefix=_route_prefix(request))


@api.get("/closed/debug", response_class=HTMLResponse)
def prefixed_debug_page() -> str:
    return closed_debug_html(route_prefix="/closed")


@api.get("/graph-data")
def graph_data(request: Request) -> dict[str, Any]:
    auth = _auth_from_request(request)
    graph = get_closed_graph()
    readable_paths = {note["path"] for note in _filter_readable_notes(graph["nodes"], auth)}
    return {
        **graph,
        "nodes": [node for node in graph["nodes"] if node["path"] in readable_paths],
        "links": [
            link for link in graph["links"]
            if link.get("source") in readable_paths and link.get("target") in readable_paths
        ],
    }


@api.get("/closed/graph-data")
def prefixed_graph_data(request: Request) -> dict[str, Any]:
    return graph_data(request)


@api.get("/search")
def search(
    request: Request,
    q: str = Query(min_length=1),
    limit: int = Query(default=12, ge=1, le=50),
) -> dict[str, Any]:
    auth = _auth_from_request(request)
    results = search_closed_notes(q, limit, route_prefix=_route_prefix(request))
    readable = _filter_readable_notes(results.get("results", []), auth)
    return {**results, "results": readable, "count": len(readable)}


@api.get("/closed/search")
def prefixed_search(
    request: Request,
    q: str = Query(min_length=1),
    limit: int = Query(default=12, ge=1, le=50),
) -> dict[str, Any]:
    auth = _auth_from_request(request)
    results = search_closed_notes(q, limit, route_prefix="/closed")
    readable = _filter_readable_notes(results.get("results", []), auth)
    return {**results, "results": readable, "count": len(readable)}


@api.get("/note")
def note(request: Request, path: str = Query(min_length=1)) -> dict[str, Any]:
    auth = _auth_from_request(request)
    result = get_closed_note(path, route_prefix=_route_prefix(request))
    if not result:
        raise HTTPException(status_code=404, detail="Note not found")
    _assert_can_read_note_payload(result, auth)
    return result


@api.get("/closed/note")
def prefixed_note(request: Request, path: str = Query(min_length=1)) -> dict[str, Any]:
    auth = _auth_from_request(request)
    result = get_closed_note(path, route_prefix="/closed")
    if not result:
        raise HTTPException(status_code=404, detail="Note not found")
    _assert_can_read_note_payload(result, auth)
    return result


@api.get("/home")
def home(request: Request) -> dict[str, Any]:
    return get_closed_home_note(route_prefix=_route_prefix(request))


@api.get("/closed/home")
def prefixed_home() -> dict[str, Any]:
    return get_closed_home_note(route_prefix="/closed")


@api.get("/notes/{slug}", response_class=HTMLResponse)
def note_page(request: Request, slug: str) -> str:
    auth = _auth_from_request(request)
    note_data = get_closed_note_by_slug(slug, route_prefix=_route_prefix(request))
    if not note_data:
        raise HTTPException(status_code=404, detail="Note not found")
    _assert_can_read_note_payload(note_data, auth)
    return closed_note_html(note_slug=slug, route_prefix=_route_prefix(request))


@api.get("/closed/notes/{slug}", response_class=HTMLResponse)
def prefixed_note_page(request: Request, slug: str) -> str:
    auth = _auth_from_request(request)
    note_data = get_closed_note_by_slug(slug, route_prefix="/closed")
    if not note_data:
        raise HTTPException(status_code=404, detail="Note not found")
    _assert_can_read_note_payload(note_data, auth)
    return closed_note_html(note_slug=slug, route_prefix="/closed")


@api.get("/api/session")
def api_session(request: Request) -> dict[str, Any]:
    auth = auth_state_dict(_request_token(request))
    return {
        **auth,
        "public_base_url": settings.public_base_url,
        "librarian_identity": librarian_identity_dict(),
        "librarian": librarian_status() if auth["authenticated"] else None,
    }


@api.get("/api/notes")
def api_list_notes(
    q: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    if q:
        results = search_closed_notes(q, limit=limit)
        readable = _filter_readable_notes(results.get("results", []), auth)
        return {**results, "results": readable, "count": len(readable)}
    graph = get_closed_graph()
    nodes = _filter_readable_notes(graph["nodes"], auth)
    return {
        "notes": nodes[:limit],
        "count": len(nodes),
    }


@api.get("/api/notes/{slug}")
def api_note_by_slug(
    slug: str,
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    result = get_closed_note_by_slug(slug)
    if not result:
        raise HTTPException(status_code=404, detail="Note not found")
    _assert_can_read_note_payload(result, auth)
    return result


@api.get("/api/note")
def api_note_by_path(
    path: str = Query(min_length=1),
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    result = get_closed_note(path)
    if not result:
        raise HTTPException(status_code=404, detail="Note not found")
    _assert_can_read_note_payload(result, auth)
    return result


@api.get("/api/raw-note")
def api_raw_note(
    path: str = Query(min_length=1),
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    try:
        document = load_document(path)
        if not _can_read_frontmatter(document.frontmatter, auth):
            raise HTTPException(status_code=403, detail="Private notes can only be read by their owner or an admin")
    except (FileNotFoundError, ValueError) as exc:
        raise _vault_http_error(exc) from exc
    return {
        "path": document.path,
        "frontmatter": document.frontmatter,
        "body": document.body,
    }


@api.get("/api/graph")
def api_graph(auth: AuthState = Depends(require_agent_token)) -> dict[str, Any]:
    graph = get_closed_graph()
    readable_paths = {note["path"] for note in _filter_readable_notes(graph["nodes"], auth)}
    return {
        **graph,
        "nodes": [node for node in graph["nodes"] if node["path"] in readable_paths],
        "links": [
            link for link in graph["links"]
            if link.get("source") in readable_paths and link.get("target") in readable_paths
        ],
    }


@api.get("/api/folders", dependencies=[Depends(require_agent_token)])
def api_folders() -> dict[str, Any]:
    return {
        "rules": folder_rules(),
        "existing": folder_index(),
    }


@api.get("/api/debug/status", dependencies=[Depends(require_agent_token)])
def api_debug_status() -> dict[str, Any]:
    return {
        "status": "ok",
        "mcp_endpoint": f"{settings.public_base_url}/mcp/",
        "api_base": f"{settings.public_base_url}/api",
        "token_required": bool(settings.bearer_token.strip()),
        "writable_roots": settings.writable_root_list,
        "librarian": librarian_status(),
        "observability": observability_status(),
    }


@api.get("/api/debug/recent-requests", dependencies=[Depends(require_agent_token)])
def api_debug_recent_requests(
    limit: int = Query(default=50, ge=1, le=500),
    path_prefix: str | None = Query(default=None),
    status_min: int | None = Query(default=None, ge=100, le=599),
    request_id: str | None = Query(default=None),
    method: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    q: str | None = Query(default=None),
    sort_by: str = Query(default="time"),
    order: str = Query(default="desc"),
) -> dict[str, Any]:
    events = recent_requests(
        limit=limit,
        path_prefix=path_prefix,
        status_min=status_min,
        request_id=request_id,
        method=method,
        kind=kind,
        q=q,
        sort_by=sort_by,
        order=order,
    )
    return {
        "events": events,
        "count": len(events),
        "observability": observability_status(),
    }


@api.get("/api/debug/log-tail", dependencies=[Depends(require_agent_token)])
def api_debug_log_tail(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    lines = log_tail(limit=limit)
    return {
        "lines": lines,
        "count": len(lines),
        "observability": observability_status(),
    }


@api.get("/api/path-suggestion", dependencies=[Depends(require_agent_token)])
def api_path_suggestion(
    title: str = Query(min_length=1),
    kind: str | None = Query(default=None),
    folder: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    project: str | None = Query(default=None),
) -> dict[str, str]:
    return {"path": suggest_note_path(kind, title, folder, scope, project)}


@api.put("/api/note")
def api_upsert_note(
    payload: NoteWriteRequest,
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    try:
        metadata = _normalize_write_metadata(payload, auth)
        document = write_document(
            path=payload.path,
            body=payload.body,
            title=payload.title,
            kind=payload.kind,
            project=payload.project,
            status=payload.status,
            tags=payload.tags,
            related=payload.related,
            metadata=metadata,
            allow_owner_change=metadata.get("owner") == "sagwan" and metadata.get("visibility") == "public",
        )
    except (FileNotFoundError, ValueError) as exc:
        raise _vault_http_error(exc) from exc
    result = get_closed_note(document.path)
    return {"path": document.path, "note": result}


@api.post("/api/note/append")
def api_append_note(
    payload: NoteAppendRequest,
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    try:
        _assert_can_modify_document(payload.path, auth)
        document = append_section(payload.path, payload.heading, payload.content)
    except (FileNotFoundError, ValueError) as exc:
        raise _vault_http_error(exc) from exc
    result = get_closed_note(document.path)
    return {"path": document.path, "note": result}


@api.api_route("/api/note", methods=["DELETE"])
async def api_delete_note(
    request: Request,
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    payload = NoteDeleteRequest(**(await request.json()))
    try:
        _assert_can_modify_document(payload.path, auth)
        deleted = delete_document(payload.path)
    except (FileNotFoundError, ValueError) as exc:
        raise _vault_http_error(exc) from exc
    return {"deleted": deleted}


@api.post("/api/note/move")
def api_move_note(
    payload: NoteMoveRequest,
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, str]:
    try:
        _assert_can_modify_document(payload.path, auth)
        moved = move_document(payload.path, payload.new_path)
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        raise _vault_http_error(exc) from exc
    return {"path": moved}


@api.post("/api/folder", dependencies=[Depends(require_agent_token)])
def api_create_folder(payload: FolderRequest) -> dict[str, str]:
    try:
        return {"path": ensure_folder(payload.path)}
    except ValueError as exc:
        raise _vault_http_error(exc) from exc


@api.post("/api/folder/move", dependencies=[Depends(require_agent_token)])
def api_move_folder(payload: FolderMoveRequest) -> dict[str, str]:
    try:
        return {"path": move_folder(payload.path, payload.new_path)}
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        raise _vault_http_error(exc) from exc


@api.post("/api/project/bootstrap", dependencies=[Depends(require_agent_token)])
def api_bootstrap_project(payload: ProjectBootstrapRequest) -> dict[str, Any]:
    return bootstrap_project_workspace(
        project=_project_key(payload.project, payload.scope),
        title=payload.title,
        summary=payload.summary,
        canonical_docs=payload.canonical_docs,
        folders=payload.folders,
        tags=payload.tags,
        related=payload.related,
    )


@api.post("/api/publication/request")
def api_request_publication(
    payload: PublicationRequestPayload,
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    try:
        _assert_can_request_publication(payload.path, auth)
        request = request_publication(
            path=payload.path,
            requester=payload.requester if _is_admin(auth) else auth.nickname,
            target_visibility=payload.target_visibility,
            rationale=payload.rationale,
            evidence_paths=payload.evidence_paths,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise _vault_http_error(exc) from exc
    return {"request": request.__dict__}


@api.get("/api/publication/requests")
def api_publication_requests(
    status: str | None = Query(default=None),
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    if not _can_manage_publication(auth):
        raise HTTPException(status_code=403, detail="Only admins or managers can list publication requests")
    requests = list_publication_requests(status=status)
    return {
        "requests": [item.__dict__ for item in requests],
        "count": len(requests),
    }


@api.post("/api/publication/status")
def api_publication_status(
    payload: PublicationStatusPayload,
    auth: AuthState = Depends(require_admin_token),
) -> dict[str, Any]:
    try:
        document = set_publication_status(
            path=payload.path,
            status=payload.status,
            decider=auth.nickname,
            reason=payload.reason,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise _vault_http_error(exc) from exc
    return {"path": document.path, "frontmatter": document.frontmatter}


@api.post("/api/assets/images", dependencies=[Depends(require_agent_token)])
async def api_upload_image(
    file: UploadFile = File(...),
    folder: str = Form(default="assets/images"),
    alt: str | None = Form(default=None),
) -> dict[str, Any]:
    content = await file.read()
    try:
        asset = save_image(
            filename=file.filename or "image.png",
            content=content,
            folder=folder,
            alt=alt,
        )
    except ValueError as exc:
        raise _vault_http_error(exc) from exc
    return {
        "path": asset.path,
        "url": asset.url,
        "markdown": asset.markdown,
        "mime_type": asset.mime_type,
        "size": asset.size,
    }


@api.post("/api/assets/files", dependencies=[Depends(require_agent_token)])
async def api_upload_file(
    file: UploadFile = File(...),
    folder: str = Form(default="assets/files"),
    label: str | None = Form(default=None),
) -> dict[str, Any]:
    content = await file.read()
    try:
        asset = save_asset(
            filename=file.filename or "file",
            content=content,
            folder=folder,
            label=label,
        )
    except ValueError as exc:
        raise _vault_http_error(exc) from exc
    return {
        "path": asset.path,
        "url": asset.url,
        "markdown": asset.markdown,
        "mime_type": asset.mime_type,
        "size": asset.size,
    }


@api.get("/api/librarian/status", dependencies=[Depends(require_admin_token)])
def api_librarian_status() -> dict[str, Any]:
    ensure_librarian_workspace()
    return librarian_status()


@api.post("/api/librarian/chat", dependencies=[Depends(require_admin_token)])
def api_librarian_chat(payload: LibrarianChatRequest) -> dict[str, Any]:
    ensure_librarian_workspace()
    return librarian_chat(payload.message, payload.thread)


@api.get("/files/{path:path}")
def api_file(path: str) -> FileResponse:
    target, mime_type = read_asset_bytes(path)
    return FileResponse(target, media_type=mime_type, content_disposition_type="inline")


@api.get("/closed/files/{path:path}")
def api_prefixed_file(path: str) -> FileResponse:
    target, mime_type = read_asset_bytes(path)
    return FileResponse(target, media_type=mime_type, content_disposition_type="inline")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


mcp_mount = BearerTokenASGI(
    mcp.streamable_http_app()
)


@asynccontextmanager
async def lifespan(_: Starlette):
    async with mcp.session_manager.run():
        yield


_app = Starlette(
    routes=[
        Route(
            "/mcp",
            endpoint=lambda request: RedirectResponse(url="/mcp/", status_code=307),
            methods=["GET", "POST", "DELETE"],
        ),
        Route(
            "/closed/mcp",
            endpoint=lambda request: RedirectResponse(url="/closed/mcp/", status_code=307),
            methods=["GET", "POST", "DELETE"],
        ),
        Mount("/mcp", app=mcp_mount),
        Mount("/closed/mcp", app=mcp_mount),
        Mount("/", app=api),
    ],
    lifespan=lifespan,
)

app = RequestLogMiddleware(_app)
