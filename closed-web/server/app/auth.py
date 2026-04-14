from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import get_settings


_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthState:
    authenticated: bool
    role: str
    token_label: str
    nickname: str
    owner: str
    capabilities: list[str]


def _matches(token: str | None) -> bool:
    expected = get_settings().bearer_token.strip()
    if not expected:
        return True
    return token == expected


def auth_state_for_token(token: str | None) -> AuthState:
    expected = get_settings().bearer_token.strip()
    if not expected:
        return AuthState(
            authenticated=True,
            role="admin",
            token_label="open-mode",
            nickname="aaron",
            owner="aaron",
            capabilities=[
                "notes:read",
                "notes:write",
                "folders:write",
                "assets:write",
                "publication:request",
                "publication:manage",
                "users:manage",
                "librarian:chat",
                "librarian:admin",
            ],
        )
    if token and token == expected:
        return AuthState(
            authenticated=True,
            role="admin",
            token_label="master",
            nickname="aaron",
            owner="aaron",
            capabilities=[
                "notes:read",
                "notes:write",
                "folders:write",
                "assets:write",
                "publication:request",
                "publication:manage",
                "users:manage",
                "librarian:chat",
                "librarian:admin",
            ],
        )
    return AuthState(
        authenticated=False,
        role="anonymous",
        token_label="anonymous",
        nickname="anonymous",
        owner="anonymous",
        capabilities=[],
    )


def auth_state_dict(token: str | None) -> dict[str, object]:
    return asdict(auth_state_for_token(token))


def librarian_identity() -> AuthState:
    return AuthState(
        authenticated=True,
        role="manager",
        token_label="server-librarian",
        nickname="saguan",
        owner="saguan",
        capabilities=[
            "notes:read",
            "notes:write",
            "folders:write",
            "assets:write",
            "publication:request",
            "publication:manage",
            "librarian:chat",
            "librarian:admin",
        ],
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

        if _matches(token):
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
