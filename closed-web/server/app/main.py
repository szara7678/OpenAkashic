from __future__ import annotations

import asyncio
import ipaddress
import json as _json
import logging as _logging
import os
import threading
import time
import urllib.request as _urlrequest
import urllib.error as _urlerror
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

# ── 인증 엔드포인트 rate limit ────────────────────────────────────────────────
# signup: IP당 1시간 내 10회
#   (2026-04-16) 3→10 상향 조정: 외부 에이전트 테스트/개발 시 IP 공유 환경에서
#   정상 사용도 차단됨. 대량 계정 생성은 hourly 10으로도 충분히 억제.
#   운영 안정화 후 재조정 필요 — 너무 낮으면 Docker 내부망 전체가 차단됨.
# login:  IP당 5분 내 10회 (브루트포스 방지)
_AUTH_RATE_LOCK = threading.Lock()
_SIGNUP_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_SIGNUP_WINDOW_SEC = 3600
_SIGNUP_LIMIT = 10
_LOGIN_WINDOW_SEC = 300
_LOGIN_LIMIT = 10
# note 생성/수정: 유저(nickname)당 1분 내 30회, 1시간 내 300회
_NOTE_WRITE_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_NOTE_WRITE_WINDOW_SEC = 60
_NOTE_WRITE_LIMIT = 30
_NOTE_WRITE_HOURLY: dict[str, list[float]] = defaultdict(list)
_NOTE_WRITE_HOURLY_WINDOW_SEC = 3600
_NOTE_WRITE_HOURLY_LIMIT = 300

# open_signup=True defense-in-depth: global /api/auth/provision cap per UTC day.
_PROVISION_DAILY_LOCK = threading.Lock()
_PROVISION_DAILY_COUNT = 0
_PROVISION_DAILY_DATE = ""  # UTC YYYY-MM-DD

# Per-username daily upload quota (reset at UTC midnight).
_PER_USER_LOCK = threading.Lock()
_UPLOAD_DAILY: dict[str, tuple[str, int, int]] = {}  # user -> (date, file_count, bytes)


def _peer_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_trusted_proxy(peer: str, trusted_cidrs: list[str]) -> bool:
    if not trusted_cidrs:
        return False
    try:
        peer_addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for cidr in trusted_cidrs:
        try:
            if peer_addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def _client_ip(request: Request) -> str:
    # Honor x-forwarded-for only when the immediate peer is a trusted proxy;
    # otherwise an attacker could spoof the header to bypass IP rate limits.
    settings = get_settings()
    peer = _peer_ip(request)
    xff = request.headers.get("x-forwarded-for", "")
    if xff and settings.trust_forwarded_for and _is_trusted_proxy(peer, settings.trusted_proxy_networks):
        return xff.split(",")[0].strip()
    return peer


def _check_rate_limit(attempts: dict[str, list[float]], ip: str, window: int, limit: int, msg: str) -> None:
    now = time.monotonic()
    with _AUTH_RATE_LOCK:
        attempts[ip] = [t for t in attempts[ip] if now - t < window]
        if len(attempts[ip]) >= limit:
            raise HTTPException(status_code=429, detail=msg)
        attempts[ip].append(now)


def _utc_date() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _check_provision_daily_cap(limit: int) -> None:
    global _PROVISION_DAILY_COUNT, _PROVISION_DAILY_DATE
    today = _utc_date()
    with _PROVISION_DAILY_LOCK:
        if _PROVISION_DAILY_DATE != today:
            _PROVISION_DAILY_DATE = today
            _PROVISION_DAILY_COUNT = 0
        if _PROVISION_DAILY_COUNT >= limit:
            raise HTTPException(
                status_code=429,
                detail="Daily provisioning cap reached — retry after UTC midnight",
            )
        _PROVISION_DAILY_COUNT += 1


def _check_upload_quota(auth: AuthState, size_bytes: int, file_limit: int, byte_limit: int) -> None:
    # Trusted roles are exempt — quotas exist to curb auto-provisioned agent abuse.
    if auth.role in {"admin", "manager"}:
        return
    username = auth.username
    if not username:
        return
    today = _utc_date()
    with _PER_USER_LOCK:
        date, files, total_bytes = _UPLOAD_DAILY.get(username, ("", 0, 0))
        if date != today:
            date, files, total_bytes = today, 0, 0
        if files >= file_limit:
            raise HTTPException(status_code=429, detail=f"upload daily file cap ({file_limit}) reached")
        if total_bytes + size_bytes > byte_limit:
            raise HTTPException(status_code=429, detail=f"upload daily byte cap ({byte_limit}) reached")
        _UPLOAD_DAILY[username] = (today, files + 1, total_bytes + size_bytes)

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
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
from app.guidance import openakashic_guidance_payload
from app.librarian import (
    ensure_librarian_workspace,
    librarian_chat,
    librarian_status,
    load_librarian_settings,
    save_librarian_settings,
)
from app.core_api_bridge import sync_published_note
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
from app.sagwan_loop import (
    load_sagwan_settings,
    pending_publication_request_count,
    run_sagwan_approval_cycle,
    run_sagwan_curation_cycle,
    save_sagwan_settings,
)
from app.subordinate import (
    enqueue_subordinate_task,
    list_subordinate_tasks,
    load_subordinate_settings,
    run_subordinate_cycle,
    save_subordinate_settings,
    subordinate_chat,
    subordinate_status,
)
from app.vault import (
    append_section,
    bootstrap_project_workspace,
    delete_document,
    folder_index,
    folder_rules,
    list_note_paths,
    list_publication_requests,
    load_document,
    move_document,
    move_folder,
    normalize_project_key,
    rename_actor_references,
    request_publication,
    read_asset_bytes,
    save_asset,
    save_image,
    set_publication_status,
    ensure_folder,
    suggest_note_path,
    write_document,
)
from app.users import (
    SAGWAN_SYSTEM_OWNER,
    authenticate_user,
    change_user_password,
    create_user,
    find_user_by_token,
    list_users,
    public_user_record,
    rotate_user_token,
    set_first_time_password,
    update_user_profile,
    update_user_role,
)


settings = get_settings()
configure_observability(settings.log_dir, settings.recent_request_limit)

api = FastAPI(
    title="OpenAkashic",
    version="0.2.0",
    description="Visibility-aware knowledge network, personal vault, publication workflow, and agent memory surface.",
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
    kind: str | None = Field(
        default=None,
        description="Use 'claim' for one reusable fact/warning/config discovery; use 'capsule' for a synthesis. Claims are public by default.",
    )
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
    current_note_path: str | None = None
    current_note_slug: str | None = None


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


class AuthSignupPayload(BaseModel):
    username: str = Field(min_length=3)
    nickname: str = Field(min_length=2)
    password: str = Field(min_length=8)
    password_confirm: str = Field(min_length=8)


class AuthLoginPayload(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=8)


class ProfileUpdatePayload(BaseModel):
    nickname: str = Field(min_length=2)


class PasswordChangePayload(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)
    new_password_confirm: str = Field(min_length=8)


class SetupPasswordPayload(BaseModel):
    new_password: str = Field(min_length=8)
    new_password_confirm: str = Field(min_length=8)


class UserRoleUpdatePayload(BaseModel):
    username: str = Field(min_length=1)
    role: str = Field(min_length=1)


class LibrarianSettingsPayload(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    reasoning_effort: str | None = None
    enabled_tools: list[str] | None = None


class SubordinateSettingsPayload(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    enabled: bool | None = None
    interval_sec: int | None = None
    max_tasks_per_run: int | None = None
    auto_review_publication_requests: bool | None = None
    auto_request_publication_for_capsules: bool | None = None
    enabled_task_types: list[str] | None = None


class SubordinateTaskPayload(BaseModel):
    kind: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    run_after: str | None = None


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


def _session_payload(token: str | None, *, include_agents: bool = True) -> dict[str, Any]:
    auth = auth_state_dict(token)
    user = find_user_by_token(token) if token else None
    payload: dict[str, Any] = {
        **auth,
        "public_base_url": settings.public_base_url,
        "provisioned": bool(user.get("provisioned")) if user else False,
        "guidance": openakashic_guidance_payload(public_base_url=settings.public_base_url),
    }
    is_admin = auth.get("role") == "admin" or "librarian:admin" in (auth.get("capabilities") or [])
    if include_agents:
        payload["librarian_identity"] = librarian_identity_dict()
        # Full agent configs only for admins — regular users don't need tool/memory details
        payload["librarian"] = librarian_status() if is_admin else None
        payload["subordinate"] = subordinate_status() if is_admin else None
    return payload


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


def _assert_can_read_note_payload(note: dict[str, Any], auth: AuthState) -> None:
    if not _can_read_frontmatter(note, auth):
        raise HTTPException(status_code=403, detail="Notes can only be opened by their owner or an admin")


def _assert_can_read_document(document_path: str, auth: AuthState) -> None:
    document = load_document(document_path)
    if not _can_read_frontmatter(document.frontmatter, auth):
        raise HTTPException(status_code=403, detail="Notes can only be opened by their owner or an admin")


def _assert_can_modify_document(document_path: str, auth: AuthState) -> dict[str, Any]:
    document = load_document(document_path)
    if not _can_modify_frontmatter(document.frontmatter, auth):
        raise HTTPException(status_code=403, detail="Notes can only be modified by their owner or an admin")
    return document.frontmatter


def _filter_readable_notes(notes: list[dict[str, Any]], auth: AuthState) -> list[dict[str, Any]]:
    return [note for note in notes if _can_read_frontmatter(note, auth)]


_PROTECTED_METADATA_FIELDS = frozenset({
    "core_api_id",
    "created_at",
    "updated_at",
    "synced_at",
    "sagwan_review",
    "sagwan_score",
    "sagwan_reviewed_at",
    "busagwan_crawled_at",
    "publication_id",
})


def _normalize_write_metadata(payload: NoteWriteRequest, auth: AuthState) -> dict[str, Any]:
    raw_metadata = dict(payload.metadata or {})
    # Strip protected system fields non-admins cannot set
    if not _is_admin(auth):
        for field in _PROTECTED_METADATA_FIELDS:
            raw_metadata.pop(field, None)
    metadata = raw_metadata
    existing_frontmatter: dict[str, Any] = {}
    is_existing = False
    try:
        existing_frontmatter = load_document(payload.path).frontmatter
        is_existing = True
    except (FileNotFoundError, ValueError):
        existing_frontmatter = {}
    resolved_kind = str(
        payload.kind or metadata.get("kind") or existing_frontmatter.get("kind") or "reference"
    ).strip().lower()
    explicit_visibility = "visibility" in metadata and str(metadata.get("visibility") or "").strip() != ""

    requested_visibility = str(
        metadata.get("visibility") or existing_frontmatter.get("visibility") or settings.default_note_visibility
    ).strip().lower().replace("-", "_")
    if resolved_kind == "claim" and not is_existing and not explicit_visibility:
        requested_visibility = "public"
    if requested_visibility not in {"private", "public", "shared"}:
        requested_visibility = "private"
    direct_public_claim = resolved_kind == "claim" and requested_visibility == "public"
    if not _is_admin(auth) and requested_visibility == "public" and not direct_public_claim:
        metadata["publication_target_visibility"] = "public"
        requested_visibility = "private"
    metadata["visibility"] = requested_visibility

    if is_existing:
        if not _can_modify_frontmatter(existing_frontmatter, auth):
            raise HTTPException(status_code=403, detail="Notes can only be modified by their owner or an admin")
        owner = _note_owner(existing_frontmatter)
        if requested_visibility == "public" and _is_admin(auth) and not direct_public_claim:
            metadata.setdefault("original_owner", existing_frontmatter.get("original_owner") or owner)
            owner = SAGWAN_SYSTEM_OWNER
        elif requested_visibility == "public" and not direct_public_claim:
            # non-admin: force private + publication request
            requested_visibility = "private"
            metadata["visibility"] = "private"
            metadata["publication_target_visibility"] = "public"
        metadata["owner"] = owner
    else:
        metadata["created_by"] = metadata.get("created_by") or auth.nickname
        if requested_visibility == "public" and _is_admin(auth) and not direct_public_claim:
            metadata["owner"] = SAGWAN_SYSTEM_OWNER
        else:
            metadata["owner"] = auth.nickname
            if requested_visibility == "public" and not direct_public_claim:
                # non-admin: force private + publication request
                requested_visibility = "private"
                metadata["visibility"] = "private"
                metadata["publication_target_visibility"] = "public"

    publication_status = str(
        metadata.get("publication_status") or existing_frontmatter.get("publication_status") or "none"
    ).strip().lower().replace("-", "_")
    if direct_public_claim:
        publication_status = "published"
        metadata.pop("publication_target_visibility", None)
    elif not _is_admin(auth) and metadata.get("publication_target_visibility") == "public":
        publication_status = "requested"
    if not _is_admin(auth) and not direct_public_claim and publication_status not in {"none", "requested"}:
        raise HTTPException(status_code=403, detail="Users can only set publication status to none or requested")
    metadata["publication_status"] = publication_status or "none"
    return metadata


def _assert_can_request_publication(path: str, auth: AuthState) -> None:
    document = load_document(path)
    owner = str(document.frontmatter.get("owner") or settings.default_note_owner).strip()
    if not _is_admin(auth) and owner != auth.nickname:
        raise HTTPException(status_code=403, detail="Users can only request publication for their own notes")
    if str(document.frontmatter.get("targets") or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Targeted claims (reviews) cannot be published. Reviews stay Closed-only by design — publish the underlying capsule instead.",
        )


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
    auth = _auth_from_request(request)
    return closed_note_html(route_prefix=_route_prefix(request), viewer_owner=auth.nickname, is_admin=_is_admin(auth))


@api.get("/closed", response_class=HTMLResponse)
def prefixed_root(request: Request) -> str:
    auth = _auth_from_request(request)
    return closed_note_html(route_prefix="/closed", viewer_owner=auth.nickname, is_admin=_is_admin(auth))


@api.get("/graph", response_class=HTMLResponse)
def graph_page(request: Request) -> str:
    auth = _auth_from_request(request)
    return closed_graph_html(route_prefix=_route_prefix(request), viewer_owner=auth.nickname, is_admin=_is_admin(auth))


@api.get("/closed/graph", response_class=HTMLResponse)
def prefixed_graph_page(request: Request) -> str:
    auth = _auth_from_request(request)
    return closed_graph_html(route_prefix="/closed", viewer_owner=auth.nickname, is_admin=_is_admin(auth))


@api.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    auth = _auth_from_request(request)
    prefix = _route_prefix(request)
    if not _is_admin(auth):
        return RedirectResponse(f"{prefix}/graph", status_code=303)
    return HTMLResponse(closed_debug_html(route_prefix=prefix))


@api.get("/closed/admin", response_class=HTMLResponse)
def prefixed_admin_page(request: Request):
    auth = _auth_from_request(request)
    if not _is_admin(auth):
        return RedirectResponse("/closed/graph", status_code=303)
    return HTMLResponse(closed_debug_html(route_prefix="/closed"))


@api.get("/debug", response_class=HTMLResponse)
def debug_page(request: Request):
    return admin_page(request)


@api.get("/closed/debug", response_class=HTMLResponse)
def prefixed_debug_page(request: Request):
    return prefixed_admin_page(request)


@api.get("/graph-data")
def graph_data(request: Request) -> dict[str, Any]:
    auth = _auth_from_request(request)
    return get_closed_graph(viewer_owner=auth.nickname, is_admin=_is_admin(auth))


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
    result = get_closed_note(path, route_prefix=_route_prefix(request), viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    if not result:
        raise HTTPException(status_code=404, detail="Note not found")
    _assert_can_read_note_payload(result, auth)
    return result


@api.get("/closed/note")
def prefixed_note(request: Request, path: str = Query(min_length=1)) -> dict[str, Any]:
    auth = _auth_from_request(request)
    result = get_closed_note(path, route_prefix="/closed", viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    if not result:
        raise HTTPException(status_code=404, detail="Note not found")
    _assert_can_read_note_payload(result, auth)
    return result


@api.get("/home")
def home(request: Request) -> dict[str, Any]:
    auth = _auth_from_request(request)
    result = get_closed_home_note(
        route_prefix=_route_prefix(request),
        viewer_owner=auth.nickname,
        is_admin=_is_admin(auth),
    )
    return result


@api.get("/closed/home")
def prefixed_home(request: Request) -> dict[str, Any]:
    auth = _auth_from_request(request)
    result = get_closed_home_note(
        route_prefix="/closed",
        viewer_owner=auth.nickname,
        is_admin=_is_admin(auth),
    )
    return result


@api.get("/notes/{slug}", response_class=HTMLResponse)
def note_page(request: Request, slug: str) -> str:
    auth = _auth_from_request(request)
    note_data = get_closed_note_by_slug(slug, route_prefix=_route_prefix(request), viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    if not note_data:
        raise HTTPException(status_code=404, detail="Note not found")
    _assert_can_read_note_payload(note_data, auth)
    return closed_note_html(
        note_slug=slug,
        route_prefix=_route_prefix(request),
        viewer_owner=auth.nickname,
        is_admin=_is_admin(auth),
    )


@api.get("/closed/notes/{slug}", response_class=HTMLResponse)
def prefixed_note_page(request: Request, slug: str) -> str:
    auth = _auth_from_request(request)
    note_data = get_closed_note_by_slug(slug, route_prefix="/closed", viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    if not note_data:
        raise HTTPException(status_code=404, detail="Note not found")
    _assert_can_read_note_payload(note_data, auth)
    return closed_note_html(note_slug=slug, route_prefix="/closed", viewer_owner=auth.nickname, is_admin=_is_admin(auth))


@api.get("/api/session")
def api_session(request: Request, include: str | None = Query(default=None)) -> dict[str, Any]:
    include_agents = include is None or "agents" in {part.strip() for part in include.split(",")}
    return _session_payload(_request_token(request), include_agents=include_agents)


@api.post("/api/auth/signup")
def api_auth_signup(request: Request, payload: AuthSignupPayload) -> dict[str, Any]:
    _check_rate_limit(
        _SIGNUP_ATTEMPTS,
        _client_ip(request),
        _SIGNUP_WINDOW_SEC,
        _SIGNUP_LIMIT,
        "Too many signup attempts — try again in 1 hour",
    )
    settings = get_settings()
    if not settings.open_signup:
        raise HTTPException(status_code=403, detail="Self-registration is disabled — contact an admin")
    # Signup also counts against the provision daily cap — same abuse surface.
    _check_provision_daily_cap(settings.provision_daily_cap)
    if payload.password != payload.password_confirm:
        raise HTTPException(status_code=400, detail="Password confirmation does not match")
    try:
        user = create_user(
            username=payload.username,
            nickname=payload.nickname,
            password=payload.password,
        )
    except ValueError as exc:
        raise _vault_http_error(exc) from exc
    token = str(user.get("api_token") or "")
    return {
        "token": token,
        "user": public_user_record(user),
        "session": _session_payload(token),
        "mcp_endpoint": f"{settings.public_base_url}/mcp/",
        "usage_hint": "Set Authorization header to 'Bearer <token>' when connecting to the MCP endpoint.",
        "guidance": openakashic_guidance_payload(public_base_url=settings.public_base_url),
    }


@api.post("/api/auth/provision")
def api_auth_provision(request: Request) -> dict[str, Any]:
    """Auto-provision an agent account — no username or password required.

    Generates a random `agent-XXXXXXXX` account and returns a ready-to-use token.
    Intended for automated agent onboarding: one HTTP call, no human interaction.

    Rate-limited to 5 provisions/hour/IP (shared with signup bucket).
    Returns the same token shape as /api/auth/signup.
    """
    import secrets as _secrets

    _check_rate_limit(
        _SIGNUP_ATTEMPTS,
        _client_ip(request),
        _SIGNUP_WINDOW_SEC,
        _SIGNUP_LIMIT,
        "Too many signup attempts — try again in 1 hour",
    )
    settings = get_settings()
    if not settings.open_signup:
        raise HTTPException(status_code=403, detail="Self-registration is disabled — contact an admin")
    _check_provision_daily_cap(settings.provision_daily_cap)
    # auto-generate credentials
    suffix = _secrets.token_hex(4)  # 8 hex chars
    username = f"agent-{suffix}"
    nickname = f"Agent {suffix.upper()}"
    password = _secrets.token_urlsafe(24)
    try:
        user = create_user(username=username, nickname=nickname, password=password, provisioned=True)
    except ValueError as exc:
        raise _vault_http_error(exc) from exc
    token = str(user.get("api_token") or "")
    mcp_url = f"{settings.public_base_url}/mcp/"
    mcp_block = {
        "mcpServers": {
            "openakashic": {
                "type": "http",
                "url": mcp_url,
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    }
    return {
        "token": token,
        "username": username,
        "provisioned": True,
        "mcp_endpoint": mcp_url,
        "mcp_config": mcp_block,
        "env": f"CLOSED_AKASHIC_TOKEN={token}",
        "guidance": openakashic_guidance_payload(public_base_url=settings.public_base_url),
        "next": (
            f"Account '{username}' created. "
            "Merge `mcp_config` into your MCP client settings "
            "(Claude Code: ~/.claude/settings.json | Cursor: .cursor/mcp.json | "
            "Codex: ~/.codex/config.toml [mcp_servers.openakashic] | "
            "Antigravity / others: see client docs). "
            f"MCP endpoint: {mcp_url}"
        ),
    }


@api.post("/api/auth/login")
def api_auth_login(request: Request, payload: AuthLoginPayload) -> dict[str, Any]:
    _check_rate_limit(
        _LOGIN_ATTEMPTS,
        _client_ip(request),
        _LOGIN_WINDOW_SEC,
        _LOGIN_LIMIT,
        "Too many login attempts — try again in 5 minutes",
    )
    user = authenticate_user(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid login credentials")
    token = str(user.get("api_token") or "")
    return {
        "token": token,
        "user": public_user_record(user),
        "session": _session_payload(token),
        "guidance": openakashic_guidance_payload(public_base_url=settings.public_base_url),
    }


@api.get("/api/profile")
def api_profile(auth: AuthState = Depends(require_agent_token)) -> dict[str, Any]:
    return {
        "profile": {
            "username": auth.username,
            "nickname": auth.nickname,
            "role": auth.role,
            "token_label": auth.token_label,
        }
    }


@api.post("/api/profile")
def api_update_profile(
    payload: ProfileUpdatePayload,
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    try:
        old_nickname = auth.nickname
        user = update_user_profile(
            username=auth.username,
            nickname=payload.nickname,
        )
        new_nickname = str(user.get("nickname") or old_nickname)
        migration = rename_actor_references(old_nickname, new_nickname)
    except ValueError as exc:
        raise _vault_http_error(exc) from exc
    return {"profile": public_user_record(user), "migration": migration}


@api.post("/api/profile/password")
def api_change_password(
    payload: PasswordChangePayload,
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    if payload.new_password != payload.new_password_confirm:
        raise HTTPException(status_code=400, detail="New password confirmation does not match")
    try:
        user = change_user_password(
            username=auth.username,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except ValueError as exc:
        raise _vault_http_error(exc) from exc
    token = str(user.get("api_token") or "")
    return {
        "profile": public_user_record(user),
        "token": token,
        "session": _session_payload(token),
    }


@api.post("/api/profile/setup-password")
def api_setup_password(
    payload: SetupPasswordPayload,
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    """Set a password for a provisioned account (no current password required).

    Only succeeds for accounts created via /api/auth/provision (provisioned=True).
    After success the account's provisioned flag is cleared and subsequent password
    changes go through /api/profile/password (which requires the current password).
    """
    if payload.new_password != payload.new_password_confirm:
        raise HTTPException(status_code=400, detail="Password confirmation does not match")
    try:
        user = set_first_time_password(username=auth.username, new_password=payload.new_password)
    except ValueError as exc:
        raise _vault_http_error(exc) from exc
    token = str(user.get("api_token") or "")
    return {
        "success": True,
        "profile": public_user_record(user),
        "session": _session_payload(token),
    }


@api.post("/api/profile/token")
def api_rotate_profile_token(auth: AuthState = Depends(require_agent_token)) -> dict[str, Any]:
    try:
        user = rotate_user_token(username=auth.username)
    except ValueError as exc:
        raise _vault_http_error(exc) from exc
    token = str(user.get("api_token") or "")
    return {
        "token": token,
        "profile": public_user_record(user),
        "session": _session_payload(token),
    }


@api.get("/api/admin/users")
def api_admin_users(auth: AuthState = Depends(require_admin_token)) -> dict[str, Any]:
    users = list_users()
    return {"users": users, "count": len(users), "viewer": auth.nickname}


@api.post("/api/admin/users/create")
def api_admin_create_user(
    payload: AuthSignupPayload,
    auth: AuthState = Depends(require_admin_token),
) -> dict[str, Any]:
    """Admin-only user creation — works regardless of open_signup setting."""
    if payload.password != payload.password_confirm:
        raise HTTPException(status_code=400, detail="Password confirmation does not match")
    try:
        user = create_user(
            username=payload.username,
            nickname=payload.nickname,
            password=payload.password,
        )
    except ValueError as exc:
        raise _vault_http_error(exc) from exc
    return {"user": public_user_record(user), "api_token": user.get("api_token"), "created_by": auth.nickname}


@api.post("/api/admin/users/role")
def api_admin_update_user_role(
    payload: UserRoleUpdatePayload,
    auth: AuthState = Depends(require_admin_token),
) -> dict[str, Any]:
    try:
        user = update_user_role(username=payload.username, role=payload.role)
    except ValueError as exc:
        raise _vault_http_error(exc) from exc
    return {
        "user": public_user_record(user),
        "updated_by": auth.nickname,
    }


@api.get("/api/admin/librarian")
def api_admin_librarian_settings(auth: AuthState = Depends(require_admin_token)) -> dict[str, Any]:
    return {
        "settings": load_librarian_settings(),
        "status": librarian_status(),
        "viewer": auth.nickname,
    }


@api.post("/api/admin/librarian")
def api_admin_update_librarian_settings(
    payload: LibrarianSettingsPayload,
    auth: AuthState = Depends(require_admin_token),
) -> dict[str, Any]:
    try:
        settings_doc = save_librarian_settings(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise _vault_http_error(exc) from exc
    return {
        "settings": settings_doc,
        "status": librarian_status(),
        "updated_by": auth.nickname,
    }


@api.get("/api/admin/subordinate")
def api_admin_subordinate_settings(auth: AuthState = Depends(require_admin_token)) -> dict[str, Any]:
    return {
        "settings": load_subordinate_settings(),
        "status": subordinate_status(),
        "viewer": auth.nickname,
    }


@api.post("/api/admin/subordinate")
def api_admin_update_subordinate_settings(
    payload: SubordinateSettingsPayload,
    auth: AuthState = Depends(require_admin_token),
) -> dict[str, Any]:
    settings_doc = save_subordinate_settings(payload.model_dump(exclude_none=True))
    return {
        "settings": settings_doc,
        "status": subordinate_status(),
        "updated_by": auth.nickname,
    }


@api.get("/api/admin/subordinate/tasks")
def api_admin_subordinate_tasks(
    status: str | None = Query(default=None),
    auth: AuthState = Depends(require_admin_token),
) -> dict[str, Any]:
    tasks = list_subordinate_tasks(status=status)
    return {"tasks": tasks, "count": len(tasks), "viewer": auth.nickname}


@api.post("/api/admin/subordinate/tasks")
def api_admin_enqueue_subordinate_task(
    payload: SubordinateTaskPayload,
    auth: AuthState = Depends(require_admin_token),
) -> dict[str, Any]:
    try:
        task = enqueue_subordinate_task(
            kind=payload.kind,
            payload=payload.payload,
            created_by=auth.nickname,
            run_after=payload.run_after,
        )
    except ValueError as exc:
        raise _vault_http_error(exc) from exc
    return {"task": task}


@api.post("/api/admin/subordinate/run")
def api_admin_run_subordinate(auth: AuthState = Depends(require_admin_token)) -> dict[str, Any]:
    return run_subordinate_cycle(reason=f"manual:{auth.nickname}")


@api.get("/api/admin/sagwan/settings")
def api_admin_get_sagwan_settings(auth: AuthState = Depends(require_admin_token)) -> dict[str, Any]:
    return load_sagwan_settings()


@api.put("/api/admin/sagwan/settings")
def api_admin_put_sagwan_settings(
    payload: dict[str, Any],
    auth: AuthState = Depends(require_admin_token),
) -> dict[str, Any]:
    return save_sagwan_settings(payload)


@api.post("/api/admin/sagwan/run")
def api_admin_run_sagwan(auth: AuthState = Depends(require_admin_token)) -> dict[str, Any]:
    return run_sagwan_approval_cycle(reason=f"manual:{auth.nickname}")


@api.post("/api/admin/sagwan/curate")
def api_admin_run_sagwan_curate(auth: AuthState = Depends(require_admin_token)) -> dict[str, Any]:
    return run_sagwan_curation_cycle(reason=f"manual:{auth.nickname}")


_IMPROVEMENT_REQUEST_PREFIX = "personal_vault/meta/improvement-requests/"
_IMPROVEMENT_PRIORITY_TAGS = {"low", "medium", "high"}
_IMPROVEMENT_KIND_TAGS = {"code", "knowledge", "policy", "data"}


def _extract_improvement_summary(body: str) -> str:
    import re as _re

    m = _re.search(r"^-\s*summary\s*:\s*(.+)$", body or "", _re.MULTILINE | _re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _improvement_item(path: str, doc: Any) -> dict[str, Any]:
    fm = dict(doc.frontmatter or {})
    tags = [str(t).lower() for t in (fm.get("tags") or []) if isinstance(t, str)]
    priority = next((t for t in tags if t in _IMPROVEMENT_PRIORITY_TAGS), "")
    kind = next((t for t in tags if t in _IMPROVEMENT_KIND_TAGS), "")
    slug = path.rsplit("/", 1)[-1].removesuffix(".md")
    return {
        "path": path,
        "slug": slug,
        "title": fm.get("title") or slug,
        "status": fm.get("status") or "proposed",
        "priority": priority,
        "kind": kind,
        "review_status": fm.get("review_status") or "pending_human_review",
        "created_at": fm.get("created_at") or "",
        "summary": _extract_improvement_summary(doc.body or ""),
    }


@api.get("/api/admin/sagwan/improvements")
def api_admin_list_improvements(
    status: str | None = Query(default=None),
    auth: AuthState = Depends(require_admin_token),
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for path in list_note_paths():
        if not path.startswith(_IMPROVEMENT_REQUEST_PREFIX):
            continue
        try:
            doc = load_document(path)
        except Exception:
            continue
        item = _improvement_item(path, doc)
        if status and item["status"] != status:
            continue
        items.append(item)
    items.sort(key=lambda it: it.get("created_at") or "", reverse=True)
    return {"items": items}


@api.get("/api/admin/sagwan/improvements/detail")
def api_admin_improvement_detail(
    path: str = Query(min_length=1),
    auth: AuthState = Depends(require_admin_token),
) -> dict[str, Any]:
    if not path.startswith(_IMPROVEMENT_REQUEST_PREFIX):
        raise HTTPException(status_code=400, detail="path must be under improvement-requests folder")
    try:
        doc = load_document(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="note not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    fm = dict(doc.frontmatter or {})
    tags = [str(t).lower() for t in (fm.get("tags") or []) if isinstance(t, str)]
    priority = next((t for t in tags if t in _IMPROVEMENT_PRIORITY_TAGS), "")
    category_kind = next((t for t in tags if t in _IMPROVEMENT_KIND_TAGS), "")
    fm["priority"] = priority
    if category_kind:
        fm["kind"] = category_kind
    return {"path": doc.path, "frontmatter": fm, "body": doc.body}


@api.post("/api/admin/core/resync")
def api_admin_core_resync(
    path: str | None = Query(default=None, description="specific note path; if omitted, rescans all published capsules/claims"),
    force: bool = Query(default=True),
    auth: AuthState = Depends(require_admin_token),
) -> dict[str, Any]:
    """Re-sync published notes to Core API. Admin only. Use after changing the sync logic
    (e.g. key_points parser) to regenerate Core API records for existing capsules.
    force=True (default) drops stored core_api_id and creates fresh records.
    """
    logger_ = _logging.getLogger(__name__)
    targets: list[str]
    if path:
        targets = [path]
    else:
        targets = []
        for rel in list_note_paths():
            try:
                fm = load_document(rel).frontmatter
            except Exception:
                continue
            if str(fm.get("publication_status") or "").lower() != "published":
                continue
            if str(fm.get("kind") or "").lower() not in {"capsule", "claim"}:
                continue
            targets.append(rel)

    synced: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for rel in targets:
        try:
            doc = load_document(rel)
            new_id = sync_published_note(doc.frontmatter, doc.body, rel, force=force)
            if not new_id:
                errors.append({"path": rel, "error": "sync returned None"})
                continue
            next_fm = dict(doc.frontmatter)
            next_fm["core_api_id"] = new_id
            try:
                write_document(path=rel, body=doc.body, metadata=next_fm, allow_owner_change=True)
            except Exception as exc:
                logger_.error("admin resync: failed to persist core_api_id for %s: %s", rel, exc)
                errors.append({"path": rel, "error": f"persist: {exc}"})
                continue
            synced.append({"path": rel, "core_api_id": new_id})
        except Exception as exc:
            errors.append({"path": rel, "error": str(exc)})
    return {"synced": synced, "errors": errors, "count": len(synced), "requested_by": auth.nickname}


@api.get("/api/core/search")
def api_core_search(
    q: str = Query(..., min_length=1),
    top_k: int = Query(default=8, ge=1, le=50),
    include: str | None = Query(default=None, description="comma-separated: claims,capsules,evidences"),
    compact: bool = Query(default=False),
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    """Agent-facing wrapper around the Core API /query endpoint.

    Use this for validated public knowledge (claims/capsules/evidences). For
    personal_vault / doc searches, use /api/notes?q=… instead.
    """
    settings_obj = get_settings()
    url = settings_obj.core_api_url.rstrip("/") + "/query"
    payload: dict[str, Any] = {"query": q, "top_k": top_k}
    if include:
        kinds = [part.strip() for part in include.split(",") if part.strip()]
        if kinds:
            payload["include"] = kinds
    try:
        req = _urlrequest.Request(
            url,
            data=_json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _urlrequest.urlopen(req, timeout=10) as resp:
            body = _json.loads(resp.read().decode("utf-8"))
    except _urlerror.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Core API unreachable: {exc}") from exc
    if compact:
        results = body.get("results") or {}
        body["results"] = {
            kind: [
                {k: item[k] for k in ("id", "title", "summary", "confidence") if k in item}
                for item in items
            ]
            for kind, items in results.items()
        }
    return body


_COMPACT_LIST_FIELDS = (
    "path",
    "slug",
    "title",
    "kind",
    "owner",
    "visibility",
    "publication_status",
    "claim_review_status",
    "claim_review_badge",
    "confirm_count",
    "dispute_count",
    "summary",
    "score",
)

_API_FACTUAL_QUERY_HINTS = {
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


def _compact_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: item[k] for k in _COMPACT_LIST_FIELDS if k in item} for item in items]


def _api_looks_like_factual_query(query: str | None) -> bool:
    lowered = str(query or "").strip().lower()
    if not lowered:
        return False
    if len(lowered.split()) >= 3:
        return True
    return any(token in lowered for token in _API_FACTUAL_QUERY_HINTS)


def _api_search_usage_hint(query: str | None, kind: str | None, results: list[dict[str, Any]]) -> dict[str, Any] | None:
    if kind in {"claim", "capsule"}:
        return None
    if not _api_looks_like_factual_query(query):
        return None
    hint: dict[str, Any] = {
        "message": (
            "For factual or conceptual questions, prefer the public Akashic query path first. "
            "This /api/notes endpoint is for OpenAkashic's private/shared working-memory layer."
        ),
        "recommended_request": {
            "endpoint": "https://api.openakashic.com/query",
            "payload": {
                "query": query,
                "mode": "compact",
                "include": ["capsules", "claims"],
            },
        },
        "write_hint": "If your result is one reusable fact, save it as kind='claim'. Use kind='capsule' only for a synthesis.",
    }
    if results:
        top = results[0]
        hint["note_scope"] = (
            f"Top hit `{top.get('title') or top.get('slug') or 'note'}` is from OpenAkashic's private/shared working-memory layer, "
            "not the validated public layer."
        )
    return hint


@api.get("/api/notes")
def api_list_notes(
    q: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    compact: bool = Query(default=False, description="strip to path/title/kind/summary/score"),
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    if q:
        results = search_closed_notes(q, limit=limit, kind=kind, tags=tags)
        readable = _filter_readable_notes(results.get("results", []), auth)
        if compact:
            readable = _compact_list(readable)
        response = {**results, "results": readable, "count": len(readable)}
        usage_hint = _api_search_usage_hint(q, kind, readable if isinstance(readable, list) else [])
        if usage_hint:
            response["usage_hint"] = usage_hint
        return response
    graph = get_closed_graph(viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    nodes = _filter_readable_notes(graph["nodes"], auth)
    if kind:
        nodes = [n for n in nodes if n.get("kind") == kind]
    if tags:
        tag_set = {t.strip().lower() for t in tags}
        nodes = [n for n in nodes if tag_set.issubset({t.lower() for t in (n.get("tags") or [])})]
    notes = nodes[:limit]
    if compact:
        notes = _compact_list(notes)
    return {
        "notes": notes,
        "count": min(len(nodes), limit),
    }


@api.get("/api/notes/{slug}")
def api_note_by_slug(
    slug: str,
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    result = get_closed_note_by_slug(slug, viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    if not result:
        raise HTTPException(status_code=404, detail="Note not found")
    _assert_can_read_note_payload(result, auth)
    return result


@api.get("/api/note")
def api_note_by_path(
    path: str = Query(min_length=1),
    compact: bool = Query(default=False, description="drop body_html, related_notes, backlinks"),
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    result = get_closed_note(path, viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    if not result:
        raise HTTPException(status_code=404, detail="Note not found")
    _assert_can_read_note_payload(result, auth)
    if compact:
        for k in ("body_html", "related_notes", "backlinks"):
            result.pop(k, None)
    return result


@api.get("/api/raw-note")
def api_raw_note(
    path: str = Query(min_length=1),
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    try:
        document = load_document(path)
        if not _can_read_frontmatter(document.frontmatter, auth):
            raise HTTPException(status_code=403, detail="Notes can only be opened by their owner or an admin")
    except (FileNotFoundError, ValueError) as exc:
        raise _vault_http_error(exc) from exc
    return {
        "path": document.path,
        "frontmatter": document.frontmatter,
        "body": document.body,
    }


@api.get("/api/graph")
def api_graph(auth: AuthState = Depends(require_agent_token)) -> dict[str, Any]:
    return get_closed_graph(viewer_owner=auth.nickname, is_admin=_is_admin(auth))


@api.get("/api/folders", dependencies=[Depends(require_agent_token)])
def api_folders() -> dict[str, Any]:
    return {
        "rules": folder_rules(),
        "existing": folder_index(),
    }


@api.get("/api/debug/status", dependencies=[Depends(require_admin_token)])
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


@api.get("/api/debug/recent-requests", dependencies=[Depends(require_admin_token)])
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


@api.get("/api/debug/log-tail", dependencies=[Depends(require_admin_token)])
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


def _check_note_write_rate(auth: AuthState) -> None:
    """Note write rate limit — admin 면제, 일반 유저 분당 30회 / 시간당 300회."""
    if auth.role == "admin":
        return
    key = auth.nickname or auth.username or "unknown"
    _check_rate_limit(
        _NOTE_WRITE_ATTEMPTS, key,
        _NOTE_WRITE_WINDOW_SEC, _NOTE_WRITE_LIMIT,
        "Too many note writes — slow down (limit: 30/min)",
    )
    _check_rate_limit(
        _NOTE_WRITE_HOURLY, key,
        _NOTE_WRITE_HOURLY_WINDOW_SEC, _NOTE_WRITE_HOURLY_LIMIT,
        "Too many note writes — try again later (limit: 300/hour)",
    )


@api.put("/api/note")
def api_upsert_note(
    payload: NoteWriteRequest,
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    _check_note_write_rate(auth)
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
        publication_request_data: dict[str, Any] | None = None
        core_api_id: str | None = None
        direct_public_claim = (
            str(document.frontmatter.get("kind") or "").strip().lower() == "claim"
            and str(document.frontmatter.get("visibility") or "").strip().lower() == "public"
            and not str(document.frontmatter.get("targets") or "").strip()
        )
        wants_publication = not _is_admin(auth) and (
            str((payload.metadata or {}).get("visibility") or "").strip().lower() == "public"
            or str(metadata.get("publication_status") or "").strip().lower() == "requested"
        ) and not str(document.frontmatter.get("targets") or "").strip()
        if direct_public_claim:
            core_api_id = sync_published_note(
                frontmatter=document.frontmatter,
                body=document.body,
                note_path=document.path,
            )
            if core_api_id and str(document.frontmatter.get("core_api_id") or "") != core_api_id:
                fm = dict(document.frontmatter)
                fm["core_api_id"] = core_api_id
                document = write_document(
                    path=document.path,
                    body=document.body,
                    metadata=fm,
                    allow_owner_change=True,
                )
        elif wants_publication:
            request = request_publication(
                path=document.path,
                requester=auth.nickname,
                target_visibility="public",
                rationale=None,
                evidence_paths=[],
            )
            publication_request_data = request.__dict__
    except (FileNotFoundError, ValueError) as exc:
        raise _vault_http_error(exc) from exc
    result = get_closed_note(document.path, viewer_owner=auth.nickname, is_admin=_is_admin(auth))
    warnings: list[str] = []
    requested_kind = (payload.kind or "").strip().lower()
    effective_kind = str(document.frontmatter.get("kind") or "").strip().lower()
    if requested_kind and effective_kind and requested_kind != effective_kind:
        warnings.append(f"kind '{requested_kind}' normalized to '{effective_kind}'")
    coaching: list[str] = []
    if not requested_kind:
        coaching.append("If this note is one reusable fact, warning, or config discovery, prefer kind='claim'.")
    elif requested_kind not in {"claim", "capsule"}:
        coaching.append("If this content should become public memory, prefer kind='claim' for an atomic fact or kind='capsule' for a synthesis.")
    if effective_kind == "claim":
        coaching.append("This claim is the fast public participation path. Add more atomic claims on the same topic before writing a capsule.")
    return {
        "path": document.path,
        "note": result,
        "publication_request": publication_request_data,
        "core_api_id": core_api_id,
        "warnings": warnings,
        "usage_hint": {
            "message": "Claim-first works best for broad agent participation.",
            "write_hint": "Use kind='claim' for one reusable fact/warning/config discovery. Use kind='capsule' for a synthesis.",
            "coaching": coaching,
        },
    }


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
    result = get_closed_note(document.path, viewer_owner=auth.nickname, is_admin=_is_admin(auth))
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
    warnings: list[str] = []
    if not (payload.rationale or "").strip():
        warnings.append("rationale is empty — reviewers rely on it to judge publication")
    elif len((payload.rationale or "").strip()) < 20:
        warnings.append("rationale is very short (<20 chars) — consider expanding")
    if not payload.evidence_paths:
        warnings.append("evidence_paths is empty — link supporting notes to strengthen the request")
    return {"request": request.__dict__, "warnings": warnings}


@api.get("/api/publication/requests")
def api_publication_requests(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    if not _can_manage_publication(auth):
        raise HTTPException(status_code=403, detail="Only admins or managers can list publication requests")
    all_requests = list_publication_requests(status=status)
    total = len(all_requests)
    paged = all_requests[offset : offset + limit]
    return {
        "requests": [item.__dict__ for item in paged],
        "total": total,
        "count": len(paged),
        "offset": offset,
        "limit": limit,
    }


@api.post("/api/publication/status")
def api_publication_status(
    payload: PublicationStatusPayload,
    auth: AuthState = Depends(require_admin_token),
) -> dict[str, Any]:
    try:
        source = load_document(payload.path)
        if str(source.frontmatter.get("targets") or "").strip():
            raise ValueError("Targeted claims (reviews) cannot be published. Reviews stay Closed-only by design — publish the underlying capsule instead.")
        document = set_publication_status(
            path=payload.path,
            status=payload.status,
            decider=auth.nickname,
            reason=payload.reason,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise _vault_http_error(exc) from exc
    core_api_id = None
    if payload.status == "published":
        core_api_id = sync_published_note(
            frontmatter=document.frontmatter,
            body=document.body,
            note_path=document.path,
        )
        if core_api_id:
            try:
                from app.vault import write_document
                fm = dict(document.frontmatter)
                fm["core_api_id"] = core_api_id
                document = write_document(
                    path=document.path,
                    body=document.body,
                    metadata=fm,
                    allow_owner_change=True,
                )
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error("publication/status: failed to persist core_api_id on %s: %s", document.path, exc)
    return {"path": document.path, "frontmatter": document.frontmatter, "core_api_id": core_api_id}


async def _read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    # Stream in chunks and bail early so an oversized upload never pins memory.
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"upload exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


@api.post("/api/assets/images")
async def api_upload_image(
    file: UploadFile = File(...),
    folder: str = Form(default="assets/images"),
    alt: str | None = Form(default=None),
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    from app.vault import MAX_IMAGE_BYTES
    content = await _read_upload_capped(file, MAX_IMAGE_BYTES)
    settings = get_settings()
    _check_upload_quota(
        auth,
        len(content),
        settings.per_token_upload_daily_files,
        settings.per_token_upload_daily_bytes,
    )
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


@api.post("/api/assets/files")
async def api_upload_file(
    file: UploadFile = File(...),
    folder: str = Form(default="assets/files"),
    label: str | None = Form(default=None),
    auth: AuthState = Depends(require_agent_token),
) -> dict[str, Any]:
    from app.vault import MAX_ASSET_BYTES
    content = await _read_upload_capped(file, MAX_ASSET_BYTES)
    settings = get_settings()
    _check_upload_quota(
        auth,
        len(content),
        settings.per_token_upload_daily_files,
        settings.per_token_upload_daily_bytes,
    )
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
    note_path = payload.current_note_path
    if not note_path and payload.current_note_slug:
        resolved = get_closed_note_by_slug(payload.current_note_slug)
        if resolved:
            note_path = resolved.get("path")
    return librarian_chat(
        payload.message,
        payload.thread,
        current_note_path=note_path,
    )


@api.post("/api/subordinate/chat", dependencies=[Depends(require_admin_token)])
async def api_subordinate_chat(payload: LibrarianChatRequest) -> StreamingResponse:
    """
    SSE 스트리밍으로 응답한다.
    gemma4:e4b 같은 대형 로컬 모델은 응답에 60초+ 걸릴 수 있어
    Cloudflare tunnel이 끊기므로, 5초마다 keep-alive(:)를 보내 연결을 유지한다.
    최종 데이터는 'event: result\ndata: <JSON>\n\n' 형식으로 전송된다.
    """
    import json as _json

    async def _stream():
        result_holder: list[dict[str, Any]] = []
        error_holder: list[str] = []

        async def _run():
            try:
                result_holder.append(
                    await asyncio.to_thread(subordinate_chat, payload.message, payload.thread)
                )
            except Exception as exc:
                error_holder.append(str(exc))

        task = asyncio.create_task(_run())
        while not task.done():
            yield ": keep-alive\n\n"
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            except asyncio.TimeoutError:
                pass

        if error_holder:
            yield f"event: error\ndata: {_json.dumps({'error': error_holder[0]}, ensure_ascii=False)}\n\n"
        else:
            yield f"event: result\ndata: {_json.dumps(result_holder[0], ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


_SAFE_INLINE_MIME = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "image/bmp", "image/tiff"})


def _serve_asset(path: str) -> FileResponse:
    target, mime_type = read_asset_bytes(path)
    disposition = "inline" if mime_type in _SAFE_INLINE_MIME else "attachment"
    resp = FileResponse(target, media_type=mime_type, content_disposition_type=disposition)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@api.get("/files/{path:path}")
def api_file(path: str) -> FileResponse:
    return _serve_asset(path)


@api.get("/closed/files/{path:path}")
def api_prefixed_file(path: str) -> FileResponse:
    return _serve_asset(path)


def _glama_connector_payload() -> dict[str, Any]:
    email = os.getenv("CLOSED_AKASHIC_GLAMA_MAINTAINER_EMAIL", "").strip()
    if not email:
        raise HTTPException(status_code=404, detail="Glama maintainer email not configured")
    return {
        "$schema": "https://glama.ai/mcp/schemas/connector.json",
        "maintainers": [
            {
                "email": email,
            }
        ],
    }


@api.api_route("/.well-known/glama.json", methods=["GET", "HEAD"])
def glama_well_known() -> dict[str, Any]:
    return _glama_connector_payload()


@api.api_route("/glama.json", methods=["GET", "HEAD"])
def glama_root() -> dict[str, Any]:
    # Expose the same payload at the root as a compatibility fallback for
    # registries/UIs that probe /glama.json directly.
    return _glama_connector_payload()


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/api/status")
def api_public_status() -> dict[str, Any]:
    """Public (unauthenticated) service status — shows signup availability and MCP endpoint."""
    base = settings.public_base_url
    return {
        "status": "ok",
        "signup_enabled": bool(get_settings().open_signup),
        "mcp_endpoint": f"{base}/mcp/",
        "provision_endpoint": f"{base}/api/auth/provision" if get_settings().open_signup else None,
        "api_base": f"{base}/api",
        "quickstart": (
            f"POST {base}/api/auth/provision  (no body) → get token → "
            f"add to MCP config at {base}/mcp/"
        ),
    }


mcp_mount = BearerTokenASGI(
    mcp.streamable_http_app()
)


@asynccontextmanager
async def lifespan(_: Starlette):
    # 부사관 이벤트 드리븐 워커: enqueue 시 즉시 깨어나고, heartbeat 로 간격 재확인.
    from app.subordinate import register_wake_event
    wake_event = asyncio.Event()
    register_wake_event(wake_event, asyncio.get_running_loop())

    async def subordinate_loop() -> None:
        while True:
            try:
                settings_doc = load_subordinate_settings()
                if settings_doc.get("enabled"):
                    reason = "wake" if wake_event.is_set() else "interval"
                    wake_event.clear()
                    await asyncio.to_thread(run_subordinate_cycle, reason=reason)
                else:
                    wake_event.clear()
                heartbeat = max(60, int(settings_doc.get("interval_sec") or 900))
                try:
                    await asyncio.wait_for(wake_event.wait(), timeout=heartbeat)
                except asyncio.TimeoutError:
                    pass  # heartbeat 도달 — 정상 재확인
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(120)

    async def sagwan_loop() -> None:
        # 사관(sagwan) 승인 루틴: interval 도달 OR 대기 요청 수가 batch_trigger 이상이면 실행.
        # 짧게 sleep 하면서 배치 조건을 체크한다.
        while True:
            try:
                s = load_sagwan_settings()
                if s.get("enabled"):
                    pending = await asyncio.to_thread(pending_publication_request_count)
                    if pending >= int(s.get("batch_trigger") or 3):
                        await asyncio.to_thread(run_sagwan_approval_cycle, reason="batch_trigger")
                    else:
                        await asyncio.to_thread(run_sagwan_approval_cycle, reason="interval")
                await asyncio.sleep(max(60, int(s.get("interval_sec") or 600)))
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(180)

    async def sagwan_curation_loop() -> None:
        # 사관 정제(큐레이션) 루틴: 기본 1시간마다 raw 노트 파생/재동기화 유도.
        while True:
            try:
                s = load_sagwan_settings()
                if s.get("enabled"):
                    await asyncio.to_thread(run_sagwan_curation_cycle, reason="interval")
                await asyncio.sleep(max(300, int(s.get("curation_interval_sec") or 3600)))
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(600)

    # Rate-limit / daily-cap counters live in-process. Multi-worker deployments
    # (uvicorn --workers N, or WEB_CONCURRENCY>1) would fragment the state and
    # silently scale every cap by N. Warn loudly so misconfig doesn't slip in.
    web_concurrency = int(os.environ.get("WEB_CONCURRENCY", "1") or "1")
    if web_concurrency > 1:
        _logging.getLogger("app.main").warning(
            "WEB_CONCURRENCY=%d: in-process rate-limit/provision-cap/upload-quota "
            "counters are per-worker. Effective caps = configured * workers. "
            "Run a single worker or move counters to a shared store before scaling.",
            web_concurrency,
        )

    worker_task = asyncio.create_task(subordinate_loop())
    sagwan_task = asyncio.create_task(sagwan_loop())
    curation_task = asyncio.create_task(sagwan_curation_loop())
    async with mcp.session_manager.run():
        try:
            yield
        finally:
            worker_task.cancel()
            sagwan_task.cancel()
            curation_task.cancel()
            for task in (worker_task, sagwan_task, curation_task):
                try:
                    await task
                except asyncio.CancelledError:
                    pass


_app = Starlette(
    routes=[
        Route(
            "/mcp",
            endpoint=lambda request: RedirectResponse(url="/mcp/", status_code=308),
            methods=["GET", "POST", "DELETE"],
        ),
        Route(
            "/closed/mcp",
            endpoint=lambda request: RedirectResponse(url="/closed/mcp/", status_code=308),
            methods=["GET", "POST", "DELETE"],
        ),
        Mount("/mcp", app=mcp_mount),
        Mount("/closed/mcp", app=mcp_mount),
        Mount("/", app=api),
    ],
    lifespan=lifespan,
)

app = RequestLogMiddleware(_app)
