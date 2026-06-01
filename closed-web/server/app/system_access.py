from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from app.vault import vault_root


WORKSPACE_ROOT = Path("/workspace")
AUDIT_LOG_RELATIVE_PATH = Path("personal_vault/projects/ops/librarian/activity/system-access-log.md")
MAX_SHELL_TIMEOUT_SECS = 600

SYSTEM_TOOL_DEFS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "run_shell",
        "description": "Run a shell command in /workspace and return stdout, stderr, and exit_code.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_secs": {"type": "integer", "default": 60},
            },
            "required": ["command"],
        },
    },
    {
        "type": "function",
        "name": "read_workspace_file",
        "description": "Read a UTF-8 text file inside /workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "type": "function",
        "name": "write_workspace_file",
        "description": "Write UTF-8 text to a file inside /workspace, creating parent directories.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "type": "function",
        "name": "list_workspace_dir",
        "description": "List a directory inside /workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "/workspace"},
            },
        },
    },
]

SYSTEM_TOOL_NAMES = {str(tool["name"]) for tool in SYSTEM_TOOL_DEFS}


def _workspace_root() -> Path:
    return WORKSPACE_ROOT.resolve(strict=False)


def _resolve_workspace_path(raw_path: str | None) -> Path:
    root = _workspace_root()
    value = str(raw_path or "").strip()
    if not value:
        value = str(root)
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    if os.path.commonpath([str(root), str(resolved)]) != str(root):
        raise ValueError("path must stay inside /workspace")
    return resolved


def _sanitize_args(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in tool_args.items():
        if key == "content":
            text = str(value)
            sanitized[key] = {"chars": len(text), "preview": text[:80]}
        else:
            sanitized[key] = value
    if tool_name == "run_shell" and "command" in sanitized:
        sanitized["command"] = str(sanitized["command"])[:500]
    return sanitized


def _append_audit_log(tool_name: str, tool_args: dict[str, Any], result: str) -> None:
    log_path = vault_root() / AUDIT_LOG_RELATIVE_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    sanitized_args = json.dumps(_sanitize_args(tool_name, tool_args), ensure_ascii=False, sort_keys=True)
    result_summary = str(result).replace("\n", "\\n")[:200]
    entry = f"## {timestamp} {tool_name}\n- args: {sanitized_args}\n- result_summary: {result_summary}\n"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def _run_shell(tool_args: dict[str, Any]) -> str:
    command = str(tool_args.get("command") or "")
    if not command.strip():
        return json.dumps({"error": "command required", "exit_code": 2}, ensure_ascii=False)
    try:
        timeout = int(tool_args.get("timeout_secs") or 60)
    except (TypeError, ValueError):
        timeout = 60
    timeout = max(1, min(timeout, MAX_SHELL_TIMEOUT_SECS))
    try:
        completed = subprocess.run(
            command,
            cwd=str(_workspace_root()),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return json.dumps(
            {
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "exit_code": completed.returncode,
            },
            ensure_ascii=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return json.dumps(
            {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": -1,
                "error": f"command timed out after {timeout}s",
            },
            ensure_ascii=False,
        )


def _read_workspace_file(tool_args: dict[str, Any]) -> str:
    path = _resolve_workspace_path(str(tool_args.get("path") or ""))
    if not path.is_file():
        return json.dumps({"error": "file not found", "path": str(path)}, ensure_ascii=False)
    return path.read_text(encoding="utf-8")


def _write_workspace_file(tool_args: dict[str, Any]) -> str:
    path = _resolve_workspace_path(str(tool_args.get("path") or ""))
    content = str(tool_args.get("content") or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return json.dumps({"status": "ok", "path": str(path), "bytes": len(content.encode("utf-8"))}, ensure_ascii=False)


def _list_workspace_dir(tool_args: dict[str, Any]) -> str:
    path = _resolve_workspace_path(str(tool_args.get("path") or str(_workspace_root())))
    if not path.is_dir():
        return json.dumps({"error": "directory not found", "path": str(path)}, ensure_ascii=False)
    entries = []
    with os.scandir(path) as iterator:
        for entry in iterator:
            try:
                stat = entry.stat(follow_symlinks=False)
                size = stat.st_size
            except OSError:
                size = None
            entries.append(
                {
                    "name": entry.name,
                    "path": str(Path(entry.path)),
                    "type": "dir" if entry.is_dir(follow_symlinks=False) else "file",
                    "size": size,
                }
            )
    entries.sort(key=lambda item: (item["type"] != "dir", item["name"]))
    return json.dumps({"path": str(path), "entries": entries}, ensure_ascii=False)


def execute_system_tool(tool_name: str, tool_args: dict[str, Any]) -> str:
    args = dict(tool_args or {})
    try:
        if tool_name == "run_shell":
            result = _run_shell(args)
        elif tool_name == "read_workspace_file":
            result = _read_workspace_file(args)
        elif tool_name == "write_workspace_file":
            result = _write_workspace_file(args)
        elif tool_name == "list_workspace_dir":
            result = _list_workspace_dir(args)
        else:
            result = json.dumps({"error": f"unknown system tool {tool_name}"}, ensure_ascii=False)
    except Exception as exc:
        result = json.dumps({"error": str(exc)}, ensure_ascii=False)
    _append_audit_log(tool_name, args, result)
    return result
