from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import re
import time
from typing import Any
from uuid import uuid4

from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import PROJECT_ROOT


_events: deque[dict[str, Any]] = deque(maxlen=500)
_log_file: Path | None = None
_logger = logging.getLogger("closed_akashic.access")
_BODY_CAPTURE_LIMIT = 65536
_BODY_PREVIEW_LIMIT = 20000
_SENSITIVE_KEYS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "api_key",
    "token",
    "access_token",
    "refresh_token",
    "bearer",
    "password",
    "secret",
}


def configure_observability(log_dir: str, recent_limit: int = 500) -> None:
    global _events, _log_file

    if _events.maxlen != recent_limit:
        _events = deque(_events, maxlen=recent_limit)

    target_dir = Path(log_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        target_dir = PROJECT_ROOT / "server" / "logs"
        target_dir.mkdir(parents=True, exist_ok=True)
    _log_file = target_dir / "requests.jsonl"

    _logger.setLevel(logging.INFO)
    _logger.propagate = False

    if not any(getattr(handler, "_closed_akashic_file", False) for handler in _logger.handlers):
        file_handler = logging.FileHandler(_log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        file_handler._closed_akashic_file = True  # type: ignore[attr-defined]
        _logger.addHandler(file_handler)

    if not any(getattr(handler, "_closed_akashic_stream", False) for handler in _logger.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter("%(message)s"))
        stream_handler._closed_akashic_stream = True  # type: ignore[attr-defined]
        _logger.addHandler(stream_handler)


class RequestLogMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = time.perf_counter()
        headers = _headers(scope)
        request_id = headers.get("x-request-id") or f"req_{uuid4().hex[:16]}"
        status_code = 500
        response_bytes = 0
        response_headers: dict[str, str] = {}
        request_body = bytearray()
        response_body = bytearray()
        request_body_truncated = False
        response_body_truncated = False
        error: str | None = None

        async def receive_wrapper() -> dict[str, Any]:
            nonlocal request_body_truncated
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body") or b""
                if body and len(request_body) < _BODY_CAPTURE_LIMIT:
                    remaining = _BODY_CAPTURE_LIMIT - len(request_body)
                    request_body.extend(body[:remaining])
                    if len(body) > remaining:
                        request_body_truncated = True
                elif body:
                    request_body_truncated = True
            return message

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code, response_bytes, response_headers, response_body_truncated
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                raw_headers = list(message.get("headers", []))
                response_headers = _headers_from_raw(raw_headers)
                raw_headers.append((b"x-request-id", request_id.encode("latin1")))
                message["headers"] = raw_headers
            elif message["type"] == "http.response.body":
                body = message.get("body") or b""
                response_bytes += len(body)
                if body and len(response_body) < _BODY_CAPTURE_LIMIT:
                    remaining = _BODY_CAPTURE_LIMIT - len(response_body)
                    response_body.extend(body[:remaining])
                    if len(body) > remaining:
                        response_body_truncated = True
                elif body:
                    response_body_truncated = True
            await send(message)

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        except Exception as exc:
            error = exc.__class__.__name__
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            path = str(scope.get("path", ""))
            response_body_snapshot = _body_snapshot(
                bytes(response_body),
                response_headers.get("content-type", ""),
                truncated=response_body_truncated,
            )
            if _is_recursive_debug_response(path):
                response_body_snapshot = _omitted_body_snapshot(
                    bytes(response_body),
                    response_headers.get("content-type", ""),
                    "Response body omitted for debug-log endpoints to avoid recursive log growth.",
                )
            event = {
                "ts": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "request_id": request_id,
                "method": scope.get("method", ""),
                "path": path,
                "kind": _kind_for_path(path),
                "query": _safe_query(scope.get("query_string", b"")),
                "status": status_code,
                "duration_ms": elapsed_ms,
                "response_bytes": response_bytes,
                "client": _client(scope, headers),
                "host": headers.get("host", ""),
                "user_agent": headers.get("user-agent", "")[:180],
                "referer": headers.get("referer", "")[:180],
                "cf_ray": headers.get("cf-ray", ""),
                "error": error,
                "request": {
                    "headers": _safe_headers(headers),
                    "body": _body_snapshot(
                        bytes(request_body),
                        headers.get("content-type", ""),
                        truncated=request_body_truncated,
                    ),
                },
                "response": {
                    "headers": _safe_headers(response_headers),
                    "body": response_body_snapshot,
                },
            }
            record_request(event)


def record_request(event: dict[str, Any]) -> None:
    _events.append(event)
    _logger.info(json.dumps(event, ensure_ascii=False, separators=(",", ":")))


_tool_events: deque[dict[str, Any]] = deque(maxlen=1000)


def log_tool_event(
    tool_name: str,
    *,
    user: str | None = None,
    request_id: str | None = None,
    args_summary: dict[str, Any] | None = None,
    notes_read: list[str] | None = None,
    notes_written: list[str] | None = None,
    receipt_present: bool = True,
    error: str | None = None,
    duration_ms: float | None = None,
) -> None:
    event = {
        "ts": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "tool": tool_name,
        "user": user or "",
        "request_id": request_id or "",
        "args_summary": args_summary or {},
        "notes_read": notes_read or [],
        "notes_written": notes_written or [],
        "receipt_present": bool(receipt_present),
        "error": error,
        "duration_ms": duration_ms,
    }
    _tool_events.append(event)
    _logger.info(json.dumps({"event": "tool_call", **event}, ensure_ascii=False, separators=(",", ":")))


def recent_tool_events(
    *,
    limit: int = 100,
    tool: str | None = None,
    user: str | None = None,
    errors_only: bool = False,
) -> list[dict[str, Any]]:
    items = list(_tool_events)
    if tool:
        items = [event for event in items if str(event.get("tool", "")) == tool]
    if user:
        items = [event for event in items if str(event.get("user", "")) == user]
    if errors_only:
        items = [event for event in items if event.get("error")]
    items = sorted(items, key=lambda event: str(event.get("ts", "")), reverse=True)
    return items[:limit]


def recent_requests(
    *,
    limit: int = 50,
    path_prefix: str | None = None,
    status_min: int | None = None,
    request_id: str | None = None,
    method: str | None = None,
    kind: str | None = None,
    q: str | None = None,
    sort_by: str = "time",
    order: str = "desc",
) -> list[dict[str, Any]]:
    items = list(_events)
    if path_prefix:
        items = [event for event in items if str(event.get("path", "")).startswith(path_prefix)]
    if status_min is not None:
        items = [event for event in items if int(event.get("status", 0)) >= status_min]
    if request_id:
        items = [event for event in items if event.get("request_id") == request_id]
    if method:
        method_key = method.upper()
        items = [event for event in items if str(event.get("method", "")).upper() == method_key]
    if kind:
        kind_key = kind.lower()
        items = [event for event in items if str(event.get("kind", "")).lower() == kind_key]
    if q:
        needle = q.lower()
        items = [
            event for event in items
            if needle in " ".join(
                str(event.get(key, ""))
                for key in ("request_id", "method", "path", "kind", "query", "status", "client", "user_agent", "cf_ray", "error")
            ).lower()
        ]

    sort_key = sort_by.lower()
    reverse = order.lower() != "asc"
    if sort_key == "status":
        items = sorted(items, key=lambda event: int(event.get("status", 0)), reverse=reverse)
    elif sort_key == "kind":
        items = sorted(items, key=lambda event: (str(event.get("kind", "")), str(event.get("ts", ""))), reverse=reverse)
    elif sort_key == "method":
        items = sorted(items, key=lambda event: (str(event.get("method", "")), str(event.get("ts", ""))), reverse=reverse)
    elif sort_key == "duration":
        items = sorted(items, key=lambda event: float(event.get("duration_ms", 0)), reverse=reverse)
    else:
        items = sorted(items, key=lambda event: str(event.get("ts", "")), reverse=reverse)

    return items[:limit]


def log_tail(limit: int = 100) -> list[str]:
    if not _log_file or not _log_file.exists():
        return []
    lines = _log_file.read_text(encoding="utf-8").splitlines()
    return lines[-limit:]


def observability_status() -> dict[str, Any]:
    return {
        "recent_count": len(_events),
        "recent_capacity": _events.maxlen,
        "log_file": str(_log_file) if _log_file else None,
        "log_file_exists": bool(_log_file and _log_file.exists()),
    }


def _headers(scope: Scope) -> dict[str, str]:
    return _headers_from_raw(scope.get("headers", []))


def _headers_from_raw(raw_headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    return {
        key.decode("latin1").lower(): value.decode("latin1", errors="replace")
        for key, value in raw_headers
    }


def _client(scope: Scope, headers: dict[str, str]) -> str:
    forwarded = headers.get("cf-connecting-ip") or headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    if isinstance(client, tuple) and client:
        return str(client[0])
    return ""


def _safe_query(raw: bytes) -> str:
    query = raw.decode("latin1", errors="replace")
    if not query:
        return ""
    redacted_parts = []
    for part in query.split("&"):
        key = part.split("=", 1)[0].lower()
        if key in {"token", "access_token", "authorization", "bearer", "api_key", "key"}:
            redacted_parts.append(f"{part.split('=', 1)[0]}=REDACTED")
        else:
            redacted_parts.append(part[:240])
    return "&".join(redacted_parts)[:800]


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in _SENSITIVE_KEYS or any(token in lowered for token in ("token", "secret", "password")):
            safe[key] = "REDACTED"
        else:
            safe[key] = value[:500]
    return safe


def _body_snapshot(body: bytes, content_type: str, *, truncated: bool) -> dict[str, Any]:
    media_type = content_type.split(";", 1)[0].strip().lower()
    snapshot: dict[str, Any] = {
        "content_type": content_type,
        "size": len(body),
        "truncated": truncated,
        "skipped": False,
        "text": "",
    }
    if not body:
        return snapshot
    if _is_binary_or_upload(media_type):
        snapshot["skipped"] = True
        snapshot["text"] = f"Body omitted for {media_type or 'binary'} content."
        return snapshot

    text = body.decode("utf-8", errors="replace")
    if media_type.endswith("/json") or media_type in {"application/json", "application/problem+json"}:
        try:
            parsed = json.loads(text)
            text = json.dumps(_redact_value(parsed), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            text = _redact_text(text)
    else:
        text = _redact_text(text)

    if len(text) > _BODY_PREVIEW_LIMIT:
        text = text[:_BODY_PREVIEW_LIMIT]
        snapshot["truncated"] = True
    snapshot["text"] = text
    return snapshot


def _omitted_body_snapshot(body: bytes, content_type: str, reason: str) -> dict[str, Any]:
    return {
        "content_type": content_type,
        "size": len(body),
        "truncated": False,
        "skipped": True,
        "text": reason,
    }


def _is_recursive_debug_response(path: str) -> bool:
    return path.startswith("/api/debug/recent-requests") or path.startswith("/api/debug/log-tail")


def _is_binary_or_upload(media_type: str) -> bool:
    if not media_type:
        return False
    return (
        media_type.startswith("image/")
        or media_type.startswith("audio/")
        or media_type.startswith("video/")
        or media_type in {"application/octet-stream", "application/pdf", "multipart/form-data"}
    )


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _SENSITIVE_KEYS or any(token in lowered for token in ("token", "secret", "password", "authorization")):
                output[str(key)] = "REDACTED"
            else:
                output[str(key)] = _redact_value(item)
        return output
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _redact_text(value: str) -> str:
    value = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s\r\n]+", r"\1REDACTED", value)
    value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1REDACTED", value)
    value = re.sub(
        r"(?i)\b(token|access_token|refresh_token|api_key|password|secret)=([^&\s]+)",
        lambda match: f"{match.group(1)}=REDACTED",
        value,
    )
    return value


def _kind_for_path(path: str) -> str:
    if path.startswith("/mcp") or path.startswith("/closed/mcp"):
        return "mcp"
    if path.startswith("/api/debug"):
        return "debug"
    if path.startswith("/api"):
        return "api"
    if path.startswith("/files") or path.startswith("/closed/files"):
        return "asset"
    if path in {"/health", "/closed/health"}:
        return "health"
    if path.startswith("/notes") or path.startswith("/closed/notes") or path in {"/", "/closed", "/graph", "/closed/graph", "/debug", "/closed/debug"}:
        return "page"
    return "other"
