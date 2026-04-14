from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings


USER_ROLES = {"user", "admin", "manager"}
RESERVED_NICKNAMES = {"aaron", "sagwan", "anonymous"}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _store_path() -> Path:
    settings = get_settings()
    path = Path(settings.user_store_path).expanduser()
    legacy_root = Path("/server")
    if legacy_root in path.parents or path == legacy_root:
        path = Path(settings.closed_akashic_path).expanduser() / "server" / path.relative_to(legacy_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps({"users": []}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _load_store() -> dict[str, Any]:
    path = _store_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {"users": []}
    if not isinstance(data, dict):
        data = {"users": []}
    users = data.get("users")
    if not isinstance(users, list):
        data["users"] = []
    return data


def _save_store(data: dict[str, Any]) -> None:
    _store_path().write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_nickname(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_-]+", "-", value.strip()).strip("-").lower()
    if len(normalized) < 3:
        raise ValueError("Nickname must be at least 3 characters and use letters, numbers, hyphen, or underscore")
    return normalized


def _normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def _new_token() -> str:
    return "oak_" + secrets.token_urlsafe(24)


def public_user_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "nickname": str(record.get("nickname") or ""),
        "display_name": str(record.get("display_name") or record.get("nickname") or ""),
        "email": str(record.get("email") or ""),
        "role": str(record.get("role") or "user"),
        "created_at": str(record.get("created_at") or ""),
        "updated_at": str(record.get("updated_at") or ""),
    }


def find_user_by_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    store = _load_store()
    for record in store.get("users", []):
        if str(record.get("api_token") or "") == token:
            return dict(record)
    return None


def authenticate_user(identifier: str, password: str) -> dict[str, Any] | None:
    lookup = identifier.strip().lower()
    if not lookup or not password:
        return None
    store = _load_store()
    for record in store.get("users", []):
        if lookup not in {
            str(record.get("nickname") or "").lower(),
            str(record.get("email") or "").lower(),
        }:
            continue
        salt = str(record.get("password_salt") or "")
        password_hash = str(record.get("password_hash") or "")
        if salt and password_hash and _hash_password(password, salt) == password_hash:
            return dict(record)
    return None


def create_user(
    *,
    nickname: str,
    password: str,
    email: str | None = None,
    display_name: str | None = None,
    role: str = "user",
) -> dict[str, Any]:
    normalized_nickname = _normalize_nickname(nickname)
    if normalized_nickname in RESERVED_NICKNAMES:
        raise ValueError("Nickname is reserved")
    normalized_email = _normalize_email(email)
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    next_role = role if role in USER_ROLES else "user"
    store = _load_store()
    for record in store.get("users", []):
        if str(record.get("nickname") or "").lower() == normalized_nickname:
            raise ValueError("Nickname already exists")
        if normalized_email and str(record.get("email") or "").lower() == normalized_email:
            raise ValueError("Email already exists")
    salt = secrets.token_hex(8)
    now = _now_iso()
    record = {
        "nickname": normalized_nickname,
        "display_name": (display_name or normalized_nickname).strip() or normalized_nickname,
        "email": normalized_email,
        "role": next_role,
        "password_salt": salt,
        "password_hash": _hash_password(password, salt),
        "api_token": _new_token(),
        "created_at": now,
        "updated_at": now,
    }
    store.setdefault("users", []).append(record)
    _save_store(store)
    return dict(record)


def update_user_profile(
    *,
    nickname: str,
    display_name: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    normalized_email = _normalize_email(email)
    store = _load_store()
    target_index = -1
    for index, record in enumerate(store.get("users", [])):
        if str(record.get("nickname") or "") == nickname:
            target_index = index
            break
    if target_index == -1:
        raise ValueError("User not found")
    for index, record in enumerate(store.get("users", [])):
        if index == target_index or not normalized_email:
            continue
        if str(record.get("email") or "").lower() == normalized_email:
            raise ValueError("Email already exists")
    record = dict(store["users"][target_index])
    if display_name is not None:
        record["display_name"] = display_name.strip() or record["nickname"]
    if email is not None:
        record["email"] = normalized_email
    record["updated_at"] = _now_iso()
    store["users"][target_index] = record
    _save_store(store)
    return dict(record)


def rotate_user_token(*, nickname: str) -> dict[str, Any]:
    store = _load_store()
    for index, record in enumerate(store.get("users", [])):
        if str(record.get("nickname") or "") != nickname:
            continue
        next_record = dict(record)
        next_record["api_token"] = _new_token()
        next_record["updated_at"] = _now_iso()
        store["users"][index] = next_record
        _save_store(store)
        return dict(next_record)
    raise ValueError("User not found")
