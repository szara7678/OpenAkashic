from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
import re
from typing import Any

from app.config import get_settings


USER_ROLES = {"user", "manager", "admin"}
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")
SYSTEM_USERNAMES = {"aaron", "sagwan"}
SYSTEM_NICKNAMES = {"aaron", "sagwan", "anonymous"}


def user_store_path() -> Path:
    path = Path(get_settings().user_store_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_username(value: str) -> str:
    username = value.strip()
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("Username must be 3-32 chars using letters, numbers, dot, dash, or underscore")
    return username


def _normalize_nickname(value: str) -> str:
    nickname = re.sub(r"\s+", " ", value.strip())
    if len(nickname) < 2:
        raise ValueError("Nickname must be at least 2 characters")
    if len(nickname) > 48:
        raise ValueError("Nickname must be 48 characters or fewer")
    return nickname


def _normalize_role(value: str) -> str:
    role = value.strip().lower()
    if role not in USER_ROLES:
        raise ValueError(f"Unsupported role: {value}")
    return role


def _password_digest(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 240_000).hex()


def _make_password_fields(password: str) -> tuple[str, str]:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    salt = secrets.token_hex(16)
    return salt, _password_digest(password, salt)


def _verify_password(password: str, *, salt: str, digest: str) -> bool:
    if not salt or not digest:
        return False
    return hmac.compare_digest(_password_digest(password, salt), digest)


def _generate_token() -> str:
    return secrets.token_hex(32)


def _username_exists(users: list[dict[str, Any]], username: str, *, excluding: str | None = None) -> bool:
    needle = username.casefold()
    skip = (excluding or "").casefold()
    return any(str(user.get("username") or "").casefold() == needle and needle != skip for user in users)


def _nickname_exists(users: list[dict[str, Any]], nickname: str, *, excluding: str | None = None) -> bool:
    needle = nickname.casefold()
    skip = (excluding or "").casefold()
    return any(str(user.get("nickname") or "").casefold() == needle and needle != skip for user in users)


def _default_password_seed() -> str:
    token = get_settings().bearer_token.strip()
    return token or "openakashic-bootstrap-password"


def _system_user_record(username: str, *, nickname: str, role: str, api_token: str | None = None) -> dict[str, Any]:
    created_at = "2026-04-14T00:00:00Z"
    salt = f"system-{username}-seed"
    password_seed = _default_password_seed()
    return {
        "username": username,
        "nickname": nickname,
        "role": role,
        "password_salt": salt,
        "password_hash": _password_digest(password_seed, salt),
        "api_token": api_token or _generate_token(),
        "system": True,
        "created_at": created_at,
        "updated_at": created_at,
    }


def _seed_system_users(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_username = {str(user.get("username") or "").casefold(): user for user in users}
    master_token = get_settings().bearer_token.strip()
    master_password_seed = _default_password_seed()
    aaron = by_username.get("aaron")
    if not aaron:
        users.append(_system_user_record("aaron", nickname="aaron", role="admin", api_token=master_token or None))
    else:
        aaron.setdefault("username", "aaron")
        aaron["nickname"] = str(aaron.get("nickname") or "aaron")
        aaron["role"] = "admin"
        aaron["system"] = True
        aaron["password_salt"] = "system-aaron-seed"
        aaron["password_hash"] = _password_digest(master_password_seed, aaron["password_salt"])
        if master_token:
            aaron["api_token"] = master_token
    sagwan = by_username.get("sagwan")
    if not sagwan:
        users.append(_system_user_record("sagwan", nickname="sagwan", role="manager"))
    else:
        sagwan.setdefault("username", "sagwan")
        sagwan["nickname"] = str(sagwan.get("nickname") or "sagwan")
        sagwan["role"] = str(sagwan.get("role") or "manager")
        sagwan["system"] = True
        sagwan["password_salt"] = "system-sagwan-seed"
        sagwan["password_hash"] = _password_digest(master_password_seed, sagwan["password_salt"])
        sagwan.setdefault("api_token", _generate_token())
    return users


def _migrate_user(record: dict[str, Any]) -> dict[str, Any]:
    username = str(record.get("username") or record.get("nickname") or record.get("display_name") or "").strip()
    if not username:
        raise ValueError("User record is missing username")
    username = username if USERNAME_PATTERN.fullmatch(username) else re.sub(r"[^A-Za-z0-9._-]+", "-", username).strip("-")
    username = username or f"user-{secrets.token_hex(4)}"
    if not USERNAME_PATTERN.fullmatch(username):
        username = f"user-{secrets.token_hex(4)}"

    nickname = str(record.get("nickname") or record.get("display_name") or username).strip()
    nickname = nickname or username

    role = str(record.get("role") or "user").strip().lower()
    if role not in USER_ROLES:
        role = "user"

    created_at = str(record.get("created_at") or _now_iso())
    updated_at = str(record.get("updated_at") or created_at)
    api_token = str(record.get("api_token") or _generate_token())
    password_salt = str(record.get("password_salt") or "")
    password_hash = str(record.get("password_hash") or "")
    if not password_salt or not password_hash:
        bootstrap_seed = _default_password_seed()
        password_salt = f"migrated-{username}"
        password_hash = _password_digest(bootstrap_seed, password_salt)

    return {
        "username": username,
        "nickname": nickname,
        "role": role,
        "password_salt": password_salt,
        "password_hash": password_hash,
        "api_token": api_token,
        "system": bool(record.get("system")),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _load_store() -> dict[str, Any]:
    path = user_store_path()
    if not path.exists():
        store = {"users": []}
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    raw = path.read_text(encoding="utf-8").strip() or '{"users":[]}'
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid user store JSON: {path}") from exc
    users = [_migrate_user(item) for item in parsed.get("users", []) if isinstance(item, dict)]
    users = _seed_system_users(users)
    store = {"users": users}
    _save_store(store)
    return store


def _save_store(store: dict[str, Any]) -> None:
    path = user_store_path()
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def public_user_record(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": str(user.get("username") or ""),
        "nickname": str(user.get("nickname") or ""),
        "role": str(user.get("role") or "user"),
        "system": bool(user.get("system")),
        "created_at": str(user.get("created_at") or ""),
        "updated_at": str(user.get("updated_at") or ""),
    }


def list_users() -> list[dict[str, Any]]:
    return [public_user_record(user) for user in sorted(_load_store()["users"], key=lambda item: str(item.get("username") or ""))]


def find_user_by_username(username: str) -> dict[str, Any] | None:
    needle = username.strip().casefold()
    for user in _load_store()["users"]:
        if str(user.get("username") or "").casefold() == needle:
            return dict(user)
    return None


def find_user_by_token(token: str | None) -> dict[str, Any] | None:
    needle = (token or "").strip()
    if not needle:
        return None
    for user in _load_store()["users"]:
        if str(user.get("api_token") or "") == needle:
            return dict(user)
    return None


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    user = find_user_by_username(username)
    if not user:
        return None
    if _verify_password(password, salt=str(user.get("password_salt") or ""), digest=str(user.get("password_hash") or "")):
        return user
    return None


def create_user(*, username: str, nickname: str, password: str, role: str = "user") -> dict[str, Any]:
    store = _load_store()
    normalized_username = _normalize_username(username)
    normalized_nickname = _normalize_nickname(nickname)
    normalized_role = _normalize_role(role)
    if _username_exists(store["users"], normalized_username):
        raise ValueError("Username already exists")
    if _nickname_exists(store["users"], normalized_nickname):
        raise ValueError("Nickname already exists")
    if normalized_username.casefold() in {item.casefold() for item in SYSTEM_USERNAMES}:
        raise ValueError("That username is reserved")
    if normalized_nickname.casefold() in {item.casefold() for item in SYSTEM_NICKNAMES}:
        raise ValueError("That nickname is reserved")
    salt, digest = _make_password_fields(password)
    now = _now_iso()
    record = {
        "username": normalized_username,
        "nickname": normalized_nickname,
        "role": normalized_role,
        "password_salt": salt,
        "password_hash": digest,
        "api_token": _generate_token(),
        "system": False,
        "created_at": now,
        "updated_at": now,
    }
    store["users"].append(record)
    _save_store(store)
    return dict(record)


def update_user_profile(*, username: str, nickname: str | None = None) -> dict[str, Any]:
    store = _load_store()
    normalized_username = username.strip().casefold()
    next_nickname = _normalize_nickname(nickname) if nickname is not None else None
    updated: dict[str, Any] | None = None
    for user in store["users"]:
        if str(user.get("username") or "").casefold() != normalized_username:
            continue
        current_nickname = str(user.get("nickname") or user.get("username") or "")
        if next_nickname and next_nickname.casefold() != current_nickname.casefold():
            if _nickname_exists(store["users"], next_nickname, excluding=current_nickname):
                raise ValueError("Nickname already exists")
            if next_nickname.casefold() in {item.casefold() for item in SYSTEM_NICKNAMES} and not bool(user.get("system")):
                raise ValueError("That nickname is reserved")
            user["nickname"] = next_nickname
        user["updated_at"] = _now_iso()
        updated = dict(user)
        break
    if not updated:
        raise ValueError("User not found")
    _save_store(store)
    return updated


def rotate_user_token(*, username: str) -> dict[str, Any]:
    store = _load_store()
    normalized_username = username.strip().casefold()
    updated: dict[str, Any] | None = None
    for user in store["users"]:
        if str(user.get("username") or "").casefold() != normalized_username:
            continue
        if bool(user.get("system")) and str(user.get("username") or "").casefold() == "aaron":
            raise ValueError("Master admin token is managed outside local rotation")
        user["api_token"] = _generate_token()
        user["updated_at"] = _now_iso()
        updated = dict(user)
        break
    if not updated:
        raise ValueError("User not found")
    _save_store(store)
    return updated


def update_user_role(*, username: str, role: str) -> dict[str, Any]:
    store = _load_store()
    normalized_username = username.strip().casefold()
    normalized_role = _normalize_role(role)
    updated: dict[str, Any] | None = None
    for user in store["users"]:
        if str(user.get("username") or "").casefold() != normalized_username:
            continue
        if bool(user.get("system")) and str(user.get("username") or "") == "aaron":
            user["role"] = "admin"
        else:
            user["role"] = normalized_role
        user["updated_at"] = _now_iso()
        updated = dict(user)
        break
    if not updated:
        raise ValueError("User not found")
    _save_store(store)
    return updated
