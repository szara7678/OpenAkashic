from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import get_settings
from app.users import find_user_by_token, find_user_by_username, public_user_record


_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthState:
    authenticated: bool
    role: str
    token_label: str
    username: str
    nickname: str
    owner: str
    capabilities: list[str]
    display_name: str = ""


def _capabilities_for_role(role: str) -> list[str]:
    if role == "admin":
        return [
            "notes:read",
            "notes:write",
            "folders:write",
            "assets:write",
            "publication:request",
            "publication:manage",
            "users:manage",
            "librarian:chat",
            "librarian:admin",
        ]
    if role == "manager":
        return [
            "notes:read",
            "notes:write",
            "folders:write",
            "assets:write",
            "publication:request",
            "publication:manage",
            "librarian:chat",
            "librarian:admin",
        ]
    return [
        "notes:read",
        "notes:write",
        "folders:write",
        "assets:write",
        "publication:request",
    ]


def _matches(token: str | None) -> bool:
    expected = get_settings().bearer_token.strip()
    if not expected:
        return True
    return token == expected


def auth_state_for_token(token: str | None) -> AuthState:
    expected = get_settings().bearer_token.strip()
    master_user = find_user_by_username("aaron")
    master_nickname = str((master_user or {}).get("nickname") or "aaron")
    if not expected:
        return AuthState(
            authenticated=True,
            role="admin",
            token_label="open-mode",
            username="aaron",
            nickname=master_nickname,
            owner=master_nickname,
            capabilities=_capabilities_for_role("admin"),
            display_name=master_nickname,
        )
    if token and token == expected:
        return AuthState(
            authenticated=True,
            role="admin",
            token_label="master",
            username="aaron",
            nickname=master_nickname,
            owner=master_nickname,
            capabilities=_capabilities_for_role("admin"),
            display_name=master_nickname,
        )
    user = find_user_by_token(token)
    if user:
        profile = public_user_record(user)
        role = str(profile.get("role") or "user")
        username = str(profile.get("username") or "user")
        nickname = str(profile.get("nickname") or "user")
        return AuthState(
            authenticated=True,
            role=role,
            token_label="user",
            username=username,
            nickname=nickname,
            owner=nickname,
            capabilities=_capabilities_for_role(role),
            display_name=nickname,
        )
    return AuthState(
        authenticated=False,
        role="anonymous",
        token_label="anonymous",
        username="anonymous",
        nickname="anonymous",
        owner="anonymous",
        capabilities=[],
        display_name="Guest",
    )


def auth_state_dict(token: str | None) -> dict[str, object]:
    return asdict(auth_state_for_token(token))


def librarian_identity() -> AuthState:
    return AuthState(
        authenticated=True,
        role="manager",
        token_label="server-librarian",
        username="sagwan",
        nickname="sagwan",
        owner="sagwan",
        capabilities=_capabilities_for_role("manager"),
        display_name="sagwan",
    )


def librarian_identity_dict() -> dict[str, object]:
    return asdict(librarian_identity())


def require_agent_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthState:
    token = credentials.credentials if credentials else None
    auth_state = auth_state_for_token(token)
    if auth_state.authenticated:
        return auth_state
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid bearer token",
    )


def require_admin_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthState:
    token = credentials.credentials if credentials else None
    auth_state = auth_state_for_token(token)
    if auth_state.authenticated and auth_state.role == "admin":
        return auth_state
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid admin token",
    )


class BearerTokenASGI:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin1").lower(): value.decode("latin1")
            for key, value in scope.get("headers", [])
        }
        auth_header = headers.get("authorization", "")
        token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else None

        if auth_state_for_token(token).authenticated:
            await self.app(scope, receive, send)
            return

        response = JSONResponse(
            {"detail": "Missing or invalid bearer token"},
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"www-authenticate": "Bearer"},
        )
        await response(scope, receive, send)


def format_json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
