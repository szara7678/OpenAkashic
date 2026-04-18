"""Standard baseline tools: web_search + notes_read/notes_write.

These emulate what a typical non-MCP agent gets: web search and a basic
local note store. Intentionally minimal — not a vault, just a JSON dict
scoped to the current bench run.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None


def _ddg_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    if DDGS is None:
        return [{"error": "duckduckgo-search not installed"}]
    try:
        hits = list(DDGS().text(query, max_results=max_results))
    except Exception as exc:
        return [{"error": f"{type(exc).__name__}: {exc}"}]
    return [{"title": h.get("title", ""), "url": h.get("href", ""),
             "snippet": h.get("body", "")} for h in hits]


def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    override = os.environ.get("WEB_SEARCH_API_KEY", "").strip()
    if override:
        return {"results": [], "note": "WEB_SEARCH_API_KEY provided but no adapter impl; "
                "falling back to DDG", "adapter": "ddg"}
    return {"results": _ddg_search(query, max_results), "adapter": "ddg"}


class LocalNoteStore:
    """Per-run ephemeral note store. A standard agent's 'notebook'."""

    def __init__(self, path: Path | None = None):
        if path is None:
            fd, fp = tempfile.mkstemp(prefix="bench-std-notes-", suffix=".json")
            os.close(fd)
            path = Path(fp)
        self.path = path
        if not self.path.exists():
            self.path.write_text("{}")

    def _load(self) -> dict[str, str]:
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return {}

    def _save(self, data: dict[str, str]) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def read(self, key: str) -> dict[str, Any]:
        data = self._load()
        if key not in data:
            return {"error": f"no note at key {key!r}",
                    "available_keys": list(data.keys())}
        return {"key": key, "body": data[key]}

    def write(self, key: str, body: str) -> dict[str, Any]:
        data = self._load()
        existed = key in data
        data[key] = body
        self._save(data)
        return {"key": key, "updated": existed, "bytes": len(body.encode())}

    def list_keys(self) -> dict[str, Any]:
        return {"keys": list(self._load().keys())}


def dispatch(tool: str, arguments: dict[str, Any],
             notes: LocalNoteStore) -> dict[str, Any]:
    if tool == "web_search":
        q = str(arguments.get("query", "")).strip()
        n = int(arguments.get("max_results", 5))
        return web_search(q, n)
    if tool == "notes_write":
        return notes.write(str(arguments.get("key", "")),
                           str(arguments.get("body", "")))
    if tool == "notes_read":
        return notes.read(str(arguments.get("key", "")))
    if tool == "notes_list":
        return notes.list_keys()
    return {"error": f"unknown tool: {tool}",
            "available": ["web_search", "notes_write", "notes_read", "notes_list"]}


TOOL_MANIFEST_TEXT = """사용 가능한 도구:
- web_search(query: str, max_results: int=5) — DuckDuckGo 기반 일반 웹 검색
- notes_write(key: str, body: str) — 로컬 메모장에 기록 (key를 식별자로)
- notes_read(key: str) — notes_write로 저장한 내용 회수
- notes_list() — 현재까지 저장한 notes의 key 목록"""
