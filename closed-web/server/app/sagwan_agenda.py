"""
sagwan_agenda.py — Persistent Goal/Agenda register for Sagwan v4.

Codex final review (2026-05-03) flagged this as a must-have to lift sagwan from
"role-persistent reactive agent" to "strategy-owning autonomous steward":

> 단순 memory가 아니라 별도 durable state여야 합니다.
> goal_id / statement / metric / target / horizon / owner=sagwan / status /
>   last_reviewed_at / next_actions
> 이게 있어야 "이번 주는 ichimozzi 영역 집중" 같은 multi-task 전략이 생깁니다.

Stored as a flat JSON list. Edited via this module only — sagwan can append/update
through dedicated functions; humans can edit via admin endpoints.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import get_settings

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

GOAL_STATUSES = {"active", "paused", "achieved", "abandoned"}
DEFAULT_HORIZON_DAYS = 7

# Active agenda surface: how many goals to inject into prompts at once.
MAX_ACTIVE_FOR_PROMPT = 3


def sagwan_agenda_path() -> Path:
    return Path(get_settings().user_store_path).with_name("sagwan-agenda.json")


_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now_dt() -> datetime:
    return datetime.now(UTC)


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return None


def _load() -> dict[str, Any]:
    p = sagwan_agenda_path()
    if not p.exists():
        return {"schema_version": SCHEMA_VERSION, "goals": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception as exc:
        logger.warning("sagwan_agenda: file unreadable, starting fresh: %s", exc)
        return {"schema_version": SCHEMA_VERSION, "goals": []}
    if not isinstance(data, dict):
        return {"schema_version": SCHEMA_VERSION, "goals": []}
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("goals", [])
    if not isinstance(data["goals"], list):
        data["goals"] = []
    return data


def _save(data: dict[str, Any]) -> None:
    p = sagwan_agenda_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


# ─── CRUD ────────────────────────────────────────────────────────────────────
def add_goal(
    *,
    statement: str,
    metric: str = "",
    target: str = "",
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    owner: str = "sagwan",
    created_by: str = "sagwan",
    next_actions: list[str] | None = None,
    notes: str = "",
    priority: int = 0,
) -> dict[str, Any]:
    """Create a goal. Both sagwan and humans use this — `created_by` differentiates."""
    statement = (statement or "").strip()
    if not statement:
        raise ValueError("statement required")
    horizon_days = max(1, int(horizon_days))
    deadline = _now_dt() + timedelta(days=horizon_days)
    goal: dict[str, Any] = {
        "id": uuid4().hex,
        "statement": statement,
        "metric": (metric or "").strip(),
        "target": (target or "").strip(),
        "owner": owner,
        "status": "active",
        "priority": int(priority),
        "horizon_days": horizon_days,
        "deadline": deadline.isoformat().replace("+00:00", "Z"),
        "created_by": created_by,
        "created_at": _now_iso(),
        "last_reviewed_at": "",
        "next_actions": list(next_actions or []),
        "history": [{"ts": _now_iso(), "event": "created", "by": created_by, "note": notes}],
        "notes": notes,
    }
    with _LOCK:
        data = _load()
        data["goals"].append(goal)
        _save(data)
    return goal


def update_goal(goal_id: str, *, by: str = "sagwan", **patch: Any) -> dict[str, Any] | None:
    """Apply a patch to a goal. Whitelisted fields only. Records a history entry."""
    allowed = {"statement", "metric", "target", "horizon_days", "deadline", "status",
               "priority", "owner", "next_actions", "notes"}
    with _LOCK:
        data = _load()
        for g in data["goals"]:
            if g.get("id") != goal_id:
                continue
            changed: dict[str, Any] = {}
            for k, v in patch.items():
                if k not in allowed:
                    continue
                if g.get(k) != v:
                    g[k] = v
                    changed[k] = v
            if changed:
                g.setdefault("history", []).append({
                    "ts": _now_iso(),
                    "event": "updated",
                    "by": by,
                    "fields": list(changed.keys()),
                })
                _save(data)
            return dict(g)
    return None


def review_goal(goal_id: str, *, by: str = "sagwan", note: str = "") -> dict[str, Any] | None:
    with _LOCK:
        data = _load()
        for g in data["goals"]:
            if g.get("id") != goal_id:
                continue
            g["last_reviewed_at"] = _now_iso()
            g.setdefault("history", []).append({
                "ts": g["last_reviewed_at"],
                "event": "reviewed",
                "by": by,
                "note": note,
            })
            _save(data)
            return dict(g)
    return None


def list_goals(*, status: str | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        data = _load()
    goals = list(data["goals"])
    if status:
        goals = [g for g in goals if str(g.get("status") or "").lower() == status.strip().lower()]
    goals.sort(key=lambda g: (-int(g.get("priority") or 0), g.get("deadline") or ""))
    return goals


def get_goal(goal_id: str) -> dict[str, Any] | None:
    with _LOCK:
        data = _load()
    for g in data["goals"]:
        if g.get("id") == goal_id:
            return dict(g)
    return None


def archive_expired(*, mark_status: str = "abandoned") -> int:
    """Auto-mark active goals whose deadline has passed (and which haven't been
    reviewed since deadline). Sagwan can override by re-activating with new horizon.
    Returns how many were archived.
    """
    if mark_status not in {"abandoned", "achieved", "paused"}:
        mark_status = "abandoned"
    now = _now_dt()
    archived = 0
    with _LOCK:
        data = _load()
        for g in data["goals"]:
            if g.get("status") != "active":
                continue
            deadline = _parse_iso(g.get("deadline"))
            if deadline and deadline < now:
                g["status"] = mark_status
                g.setdefault("history", []).append({
                    "ts": _now_iso(),
                    "event": "auto_archived",
                    "by": "system",
                    "note": f"deadline {g.get('deadline')} passed",
                })
                archived += 1
        if archived:
            _save(data)
    return archived


# ─── prompt-side helpers ─────────────────────────────────────────────────────
def render_active_agenda(*, max_goals: int = MAX_ACTIVE_FOR_PROMPT) -> str:
    """Compact agenda block for injection into sagwan prompts."""
    active = [g for g in list_goals(status="active")][:max_goals]
    if not active:
        return ""
    lines = ["## Sagwan Agenda (현재 활성 목표 — 너의 장기 책임)"]
    for g in active:
        deadline = g.get("deadline") or "(없음)"
        metric = g.get("metric") or "(미정)"
        target = g.get("target") or "(미정)"
        nexts = g.get("next_actions") or []
        lines.append(f"- **{g['statement']}**")
        lines.append(f"  - metric={metric}  target={target}  deadline={deadline}")
        if nexts:
            lines.append(f"  - next_actions: {', '.join(str(a) for a in nexts[:3])}")
    lines.append("판단 시 위 목표가 영향받는다면 명시적으로 반영하라. 무관하면 무시해도 된다.")
    return "\n".join(lines)


def get_active_goal_ids() -> list[str]:
    return [g["id"] for g in list_goals(status="active")]


# ─── Observability triple ──────────────────────────────────────────────────
# Codex final review: surface sagwan's "current state" without anthropomorphism.
# Three durable fields:
#   - current_agenda  : top 1-3 active goals (already covered by list_goals(active))
#   - active_concerns : freshly-flagged risks the agent wants insu to know about
#   - why_this_next   : record of "why X was picked for the next task" — populated
#                       by the bootstrap selector and consumed by admin / sagwan
#                       prompt itself (so agent sees its own reasoning trail).
#
# Stored alongside goals in the same file so a single read serves the whole UI.

_OBSERVABILITY_FIELDS = ("active_concerns", "why_this_next")


def _ensure_observability(data: dict[str, Any]) -> dict[str, Any]:
    for f in _OBSERVABILITY_FIELDS:
        data.setdefault(f, [])
        if not isinstance(data[f], list):
            data[f] = []
    return data


def add_concern(*, statement: str, severity: str = "medium", source: str = "sagwan",
                tags: list[str] | None = None, related_paths: list[str] | None = None,
                ttl_hours: int = 72) -> dict[str, Any]:
    """Add an active concern entry. severity ∈ {low, medium, high, critical}.
    Auto-expires via prune_concerns() after ttl_hours unless re-asserted.
    """
    statement = (statement or "").strip()
    if not statement:
        raise ValueError("statement required")
    if severity not in {"low", "medium", "high", "critical"}:
        severity = "medium"
    expires_at = (_now_dt() + timedelta(hours=max(1, int(ttl_hours)))).isoformat().replace("+00:00", "Z")
    entry = {
        "id": uuid4().hex[:12],
        "statement": statement,
        "severity": severity,
        "source": source,
        "tags": list(tags or []),
        "related_paths": list(related_paths or []),
        "created_at": _now_iso(),
        "expires_at": expires_at,
    }
    with _LOCK:
        data = _ensure_observability(_load())
        # Dedup by statement (idempotent re-assert refreshes expiry)
        for existing in data["active_concerns"]:
            if existing.get("statement") == statement:
                existing.update({
                    "severity": severity,
                    "expires_at": expires_at,
                    "source": source,
                    "tags": entry["tags"] or existing.get("tags") or [],
                    "related_paths": entry["related_paths"] or existing.get("related_paths") or [],
                })
                _save(data)
                return dict(existing)
        data["active_concerns"].append(entry)
        _save(data)
    return entry


def prune_concerns() -> int:
    """Drop expired concerns. Returns removed count."""
    now = _now_dt()
    removed = 0
    with _LOCK:
        data = _ensure_observability(_load())
        survivors = []
        for c in data["active_concerns"]:
            exp = _parse_iso(c.get("expires_at"))
            if exp and exp < now:
                removed += 1
                continue
            survivors.append(c)
        if removed:
            data["active_concerns"] = survivors
            _save(data)
    return removed


def list_concerns() -> list[dict[str, Any]]:
    """Active concerns ordered by severity desc, then most-recent first."""
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    with _LOCK:
        data = _ensure_observability(_load())
    items = list(data["active_concerns"])
    items.sort(key=lambda c: (sev_order.get(c.get("severity", "medium"), 2),
                              c.get("created_at") or "" * -1), reverse=False)
    return items


def record_why_this_next(*, picked_path: str, kind: str, rank_tuple: list[Any] | tuple[Any, ...],
                         signals: dict[str, Any] | None = None,
                         max_history: int = 30) -> None:
    """Record the rationale for the most recent bootstrap pick. The list is
    bounded to the last `max_history` selections so it stays readable.
    """
    entry = {
        "ts": _now_iso(),
        "picked_path": picked_path,
        "kind": kind,
        "rank_tuple": [str(x) for x in (rank_tuple or [])],
        "signals": signals or {},
    }
    with _LOCK:
        data = _ensure_observability(_load())
        data["why_this_next"].insert(0, entry)
        data["why_this_next"] = data["why_this_next"][:max_history]
        _save(data)


def list_why_this_next(*, limit: int = 10) -> list[dict[str, Any]]:
    with _LOCK:
        data = _ensure_observability(_load())
    return list(data["why_this_next"][:limit])


def render_concerns_block(*, max_items: int = 5) -> str:
    items = list_concerns()[:max_items]
    if not items:
        return ""
    lines = ["## Sagwan Active Concerns (현재 우려/리스크)"]
    for c in items:
        sev = c.get("severity", "medium")
        statement = c.get("statement", "")
        rel = c.get("related_paths") or []
        line = f"- [{sev}] {statement}"
        if rel:
            line += f"  (paths: {', '.join(str(p) for p in rel[:3])})"
        lines.append(line)
    return "\n".join(lines)


def get_observability_snapshot() -> dict[str, Any]:
    """One-shot read for admin UI: agenda + concerns + recent picks."""
    return {
        "current_agenda": list_goals(status="active")[:MAX_ACTIVE_FOR_PROMPT],
        "active_concerns": list_concerns()[:10],
        "why_this_next": list_why_this_next(limit=10),
    }


# ─── ranking influence ──────────────────────────────────────────────────────
_GENERIC_PROJECT_TOKENS = frozenset({
    # Path scaffolding — these appear in many project labels and almost any goal
    # statement, so matching on them produces false-positive bonus.
    "shared", "reference", "knowledge", "vault", "personal", "projects",
    "project", "note", "notes", "doc", "docs", "meta", "ops", "company",
    "general", "misc",
})


def project_focus_bonus(project: str) -> float:
    """Return a bonus score for a project label if any active goal mentions it.
    Returns 0.0 if no relevant goal. Bigger = higher priority.
    Used by maintenance candidate ranking to bias toward goal-relevant work.

    Matches by token, not full substring: project "personal/ichimozzi" should
    match a goal statement that says "ichimozzi" without requiring the full
    scope prefix. Tokens of length < 3 are ignored to avoid noise hits.

    Generic scaffolding tokens (shared, reference, knowledge, etc.) are
    excluded so goal text like "cross-reference 인용" does NOT accidentally
    boost every shared/reference note. The match must hit a project-specific
    token (e.g. "ichimozzi", "arc-fleet", "openakashic").
    """
    if not project:
        return 0.0
    proj_tokens = {
        tok for tok in project.lower().replace("/", " ").replace("-", " ").split()
        if len(tok) >= 3 and tok not in _GENERIC_PROJECT_TOKENS
    }
    if not proj_tokens:
        return 0.0
    bonus = 0.0
    for g in list_goals(status="active"):
        statement = (g.get("statement") or "").lower()
        next_actions = " ".join(g.get("next_actions") or []).lower()
        haystack = statement + " " + next_actions
        if any(tok in haystack for tok in proj_tokens):
            bonus += float(int(g.get("priority") or 0) + 1)
    return bonus
