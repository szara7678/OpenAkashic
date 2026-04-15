from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import threading
from pathlib import Path
import re
from typing import Any

from app.config import get_settings

_STORE_LOCK = threading.Lock()  # in-process mutex; fcntl adds inter-process safety


USER_ROLES = {"user", "manager", "admin"}
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")


def _admin_username() -> str:
    return str(get_settings().admin_username or "admin").strip() or "admin"


def _admin_nickname() -> str:
    return str(get_settings().admin_nickname or _admin_username()).strip() or _admin_username()


# The system reserves two usernames: the configured admin and the fixed "sagwan"
# agent account. These cannot be taken by regular signups.
def system_usernames() -> set[str]:
    return {_admin_username().casefold(), "sagwan"}


def system_nicknames() -> set[str]:
    return {_admin_username().casefold(), _admin_nickname().casefold(), "sagwan", "anonymous"}


# Backwards-compatible constants — evaluated at import time with defaults; the
# functions above should be preferred at runtime.
SYSTEM_USERNAMES = {"admin", "sagwan"}
SYSTEM_NICKNAMES = {"admin", "sagwan", "anonymous"}

# The owner of promoted public notes and ops artifacts is always "sagwan".
SAGWAN_SYSTEM_OWNER = "sagwan"


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
    admin_name = _admin_username()
    admin_nick = _admin_nickname()
    admin_key = admin_name.casefold()
    admin = by_username.get(admin_key)
    if not admin:
        users.append(_system_user_record(admin_name, nickname=admin_nick, role="admin", api_token=master_token or None))
    else:
        admin.setdefault("username", admin_name)
        admin["nickname"] = str(admin.get("nickname") or admin_nick)
        admin["role"] = "admin"
        admin["system"] = True
        admin["password_salt"] = f"system-{admin_key}-seed"
        admin["password_hash"] = _password_digest(master_password_seed, admin["password_salt"])
        if master_token:
            admin["api_token"] = master_token
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


def _lock_path() -> Path:
    return user_store_path().with_suffix(user_store_path().suffix + ".lock")


@contextmanager
def _file_lock(exclusive: bool):
    """Inter-process lock on a sidecar .lock file. In-process mutex held too."""
    with _STORE_LOCK:
        lock_path = _lock_path()
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _read_raw() -> dict[str, Any]:
    path = user_store_path()
    if not path.exists():
        return {"users": []}
    raw = path.read_text(encoding="utf-8").strip() or '{"users":[]}'
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid user store JSON: {path}") from exc


def _write_atomic(store: dict[str, Any]) -> None:
    path = user_store_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(store, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


_SEEDED = False


def _load_store() -> dict[str, Any]:
    """Read-only. Seeds system users once at first call, never writes on subsequent reads."""
    global _SEEDED
    with _file_lock(exclusive=not _SEEDED):
        parsed = _read_raw()
        users = [_migrate_user(item) for item in parsed.get("users", []) if isinstance(item, dict)]
        if not _SEEDED:
            users = _seed_system_users(users)
            _write_atomic({"users": users})
            _SEEDED = True
        return {"users": users}


def _mutate_store(mutator) -> dict[str, Any]:
    """Read-modify-write under an exclusive lock. `mutator(users)` returns new users list."""
    with _file_lock(exclusive=True):
        parsed = _read_raw()
        users = [_migrate_user(item) for item in parsed.get("users", []) if isinstance(item, dict)]
        users = _seed_system_users(users)
        users = mutator(users)
        _write_atomic({"users": users})
        return {"users": users}


def _save_store(store: dict[str, Any]) -> None:
    """Legacy callers expect a full-replace save. Keep it safe: atomic write under lock."""
    with _file_lock(exclusive=True):
        _write_atomic(store)


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
    normalized_username = _normalize_username(username)
    normalized_nickname = _normalize_nickname(nickname)
    normalized_role = _normalize_role(role)
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

    def _add(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if _username_exists(users, normalized_username):
            raise ValueError("Username already exists")
        if _nickname_exists(users, normalized_nickname):
            raise ValueError("Nickname already exists")
        users.append(record)
        return users

    _mutate_store(_add)
    return dict(record)


def update_user_profile(*, username: str, nickname: str | None = None) -> dict[str, Any]:
    normalized_username = username.strip().casefold()
    next_nickname = _normalize_nickname(nickname) if nickname is not None else None
    captured: dict[str, Any] = {}

    def _mut(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for user in users:
            if str(user.get("username") or "").casefold() != normalized_username:
                continue
            current_nickname = str(user.get("nickname") or user.get("username") or "")
            if next_nickname and next_nickname.casefold() != current_nickname.casefold():
                if _nickname_exists(users, next_nickname, excluding=current_nickname):
                    raise ValueError("Nickname already exists")
                if next_nickname.casefold() in {item.casefold() for item in SYSTEM_NICKNAMES} and not bool(user.get("system")):
                    raise ValueError("That nickname is reserved")
                user["nickname"] = next_nickname
            user["updated_at"] = _now_iso()
            captured.update(user)
            return users
        raise ValueError("User not found")

    _mutate_store(_mut)
    return dict(captured)


def rotate_user_token(*, username: str) -> dict[str, Any]:
    normalized_username = username.strip().casefold()
    captured: dict[str, Any] = {}

    def _mut(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for user in users:
            if str(user.get("username") or "").casefold() != normalized_username:
                continue
            if bool(user.get("system")) and str(user.get("username") or "").casefold() == _admin_username().casefold():
                raise ValueError("Master admin token is managed outside local rotation")
            user["api_token"] = _generate_token()
            user["updated_at"] = _now_iso()
            captured.update(user)
            return users
        raise ValueError("User not found")

    _mutate_store(_mut)
    return dict(captured)


def change_user_password(*, username: str, current_password: str, new_password: str) -> dict[str, Any]:
    normalized_username = username.strip().casefold()
    captured: dict[str, Any] = {}

    def _mut(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for user in users:
            if str(user.get("username") or "").casefold() != normalized_username:
                continue
            if not _verify_password(
                current_password,
                salt=str(user.get("password_salt") or ""),
                digest=str(user.get("password_hash") or ""),
            ):
                raise ValueError("Current password is incorrect")
            salt, digest = _make_password_fields(new_password)
            user["password_salt"] = salt
            user["password_hash"] = digest
            user["updated_at"] = _now_iso()
            captured.update(user)
            return users
        raise ValueError("User not found")

    _mutate_store(_mut)
    return dict(captured)


def update_user_role(*, username: str, role: str) -> dict[str, Any]:
    normalized_username = username.strip().casefold()
    normalized_role = _normalize_role(role)
    captured: dict[str, Any] = {}

    def _mut(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for user in users:
            if str(user.get("username") or "").casefold() != normalized_username:
                continue
            if bool(user.get("system")) and str(user.get("username") or "").casefold() == _admin_username().casefold():
                user["role"] = "admin"
            else:
                user["role"] = normalized_role
            user["updated_at"] = _now_iso()
            captured.update(user)
            return users
        raise ValueError("User not found")

    _mutate_store(_mut)
    return dict(captured)
