"""
sagwan_tasks.py — TaskStore for Sagwan v4 (independent agent task queue).

Distinct from subordinate-queue.json. The subordinate is a "no LLM judgment, pure
worker"; the sagwan queue carries LLM-judgment tasks with self-enqueue, agenda
linkage, freshness-aware dedup, lease/retry/dead-letter semantics.

Architectural intent (insu's design + Codex review, 2026-05-03):
- 사관 = role-bearing independent agent over OpenAkashic
- task entries are durable; in-memory state is only a cache
- self-enqueue allowed but bounded (whitelist + 4 safety knobs)
- freshness-key dedup so unchanged capsules are not re-checked
- multi-path mutations declare write_set and run with max_concurrent=1
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from app.config import get_settings

logger = logging.getLogger(__name__)

# ─── schema + constants ──────────────────────────────────────────────────────
SCHEMA_VERSION = 1

# Task kinds the sagwan worker will execute. Keep this list authoritative —
# enqueue() rejects anything not listed.
SAGWAN_TASK_KINDS = (
    "check_capsule_maintenance",
    "check_capsule_conflict",
    "research_gap",            # K: vault gap research → new capsule
    "meta_health",             # I: 24h system health report + improvement requests
    "consolidate_review",      # L: ≥3 reviews → uphold/revise/supersede
)

# Whitelist: which kinds are allowed to spawn which kinds via self-enqueue.
# An empty value means "no spawning allowed from this kind".
# K (research_gap) intentionally has NO entry — Codex review: "K is broad
# exploration; chain drift risk is high. Initial release: self-enqueue off."
SELF_ENQUEUE_WHITELIST: dict[str, set[str]] = {
    "check_capsule_maintenance": {"check_capsule_maintenance", "check_capsule_conflict"},
    "check_capsule_conflict": {"check_capsule_conflict"},
    "meta_health": set(),      # writes meta only; no follow-up enqueue
    "consolidate_review": {"check_capsule_maintenance"},  # may enqueue post-consolidation maintenance
    # research_gap: no self-enqueue allowed (intentional)
}

# Safety knobs (per Codex final review).
MAX_CHAIN_DEPTH = 3
MAX_CHILDREN_PER_TASK = 3
MAX_SELF_ENQUEUE_PER_CYCLE = 8
RECENTLY_TOUCHED_COOLDOWN_HOURS = 6  # don't self-enqueue same (kind, resource) inside this window

# Worker behavior.
LEASE_DURATION_SECONDS = 600          # task lease while running; reclaimed if stale
DEFAULT_MAX_RETRIES = 2               # retry transient failures
RETRY_BACKOFF_BASE_SECONDS = 60       # first retry +60s, second +120s, third +240s …
QUEUE_PENDING_LIMIT = 200             # refuse new enqueues beyond this
DONE_PRUNE_AFTER_DAYS = 7             # done/failed tasks older than this get garbage-collected
PAYLOAD_MAX_BYTES = 16_000            # reject overly large payloads


def _disabled_kinds() -> set[str]:
    """Per-kind kill-switch loaded from sagwan-settings.json each call (cheap)."""
    try:
        from app.sagwan_loop import load_sagwan_settings  # late import to avoid cycle
        s = load_sagwan_settings()
        items = s.get("task_queue_kinds_disabled") or []
        if isinstance(items, list):
            return {str(k).strip() for k in items if str(k).strip()}
    except Exception:
        pass
    return set()


# ─── path / persistence ──────────────────────────────────────────────────────
def sagwan_queue_path() -> Path:
    return Path(get_settings().user_store_path).with_name("sagwan-queue.json")


_QUEUE_LOCK = threading.RLock()
_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


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


def _load_queue() -> dict[str, Any]:
    p = sagwan_queue_path()
    if not p.exists():
        return {"schema_version": SCHEMA_VERSION, "tasks": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception as exc:
        logger.warning("sagwan_tasks: queue file unreadable, starting fresh: %s", exc)
        return {"schema_version": SCHEMA_VERSION, "tasks": []}
    if not isinstance(data, dict):
        return {"schema_version": SCHEMA_VERSION, "tasks": []}
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("tasks", [])
    if not isinstance(data["tasks"], list):
        data["tasks"] = []
    return data


def _save_queue(queue: dict[str, Any]) -> None:
    p = sagwan_queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


# ─── async wake event so the worker reacts to new enqueues immediately ─────
_WAKE_EVENT: asyncio.Event | None = None
_WAKE_LOOP: asyncio.AbstractEventLoop | None = None


def register_wake_event(event: asyncio.Event, loop: asyncio.AbstractEventLoop) -> None:
    global _WAKE_EVENT, _WAKE_LOOP
    _WAKE_EVENT = event
    _WAKE_LOOP = loop


def _trigger_wake() -> None:
    if _WAKE_EVENT is None or _WAKE_LOOP is None:
        return
    try:
        _WAKE_LOOP.call_soon_threadsafe(_WAKE_EVENT.set)
    except RuntimeError:
        pass


# ─── path lock (per-resource serialization) ────────────────────────────────
def acquire_path_locks(paths: Iterable[str]) -> list[threading.Lock]:
    """Acquire per-path write locks in deterministic order to prevent deadlocks.
    Returns the lock objects so the caller can release them in reverse order.
    """
    sorted_paths = sorted({p for p in paths if p})
    acquired: list[threading.Lock] = []
    for p in sorted_paths:
        with _PATH_LOCKS_GUARD:
            lock = _PATH_LOCKS.setdefault(p, threading.Lock())
        lock.acquire()
        acquired.append(lock)
    return acquired


def release_path_locks(locks: list[threading.Lock]) -> None:
    for lock in reversed(locks):
        try:
            lock.release()
        except RuntimeError:
            pass


# ─── helpers: dedup key + freshness ─────────────────────────────────────────
def compute_freshness_key(*, updated_at: str | None, body: str | None = None) -> str:
    """Caller passes either updated_at (preferred) or body content. Returns a stable
    short token used to dedup tasks targeting unchanged resources.
    """
    if updated_at:
        return updated_at.strip()
    if body is not None:
        return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return "?"


def _dedup_signature(task: dict[str, Any]) -> str:
    return "::".join([
        str(task.get("kind") or ""),
        str(task.get("resource_key") or ""),
        str(task.get("freshness_key") or ""),
    ])


# ─── enqueue ────────────────────────────────────────────────────────────────
def enqueue_task(
    *,
    kind: str,
    payload: dict[str, Any],
    resource_key: str,
    freshness_key: str,
    write_set: list[str] | None = None,
    priority: int = 0,
    created_by: str = "sagwan",
    reason: str = "scheduled",
    parent_task_id: str | None = None,
    root_task_id: str | None = None,
    chain_depth: int = 0,
    spawned_from: str | None = None,
    run_after: str | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict[str, Any] | None:
    """Enqueue a sagwan task. Returns the task dict or None if dedup'd / refused.

    Dedup: if a pending task with same (kind, resource_key, freshness_key) exists,
    do not enqueue and return that existing task instead.
    """
    if kind not in SAGWAN_TASK_KINDS:
        raise ValueError(f"Unknown sagwan task kind: {kind}")
    if kind in _disabled_kinds():
        # Silent skip — caller tries to enqueue but kind is disabled by setting.
        return None
    payload = dict(payload or {})
    payload_size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    if payload_size > PAYLOAD_MAX_BYTES:
        raise ValueError(f"Payload too large ({payload_size} > {PAYLOAD_MAX_BYTES} bytes)")
    write_set = sorted(set(write_set or [resource_key]))
    with _QUEUE_LOCK:
        queue = _load_queue()
        pending = [t for t in queue["tasks"] if t.get("status") == "pending"]
        if len(pending) >= QUEUE_PENDING_LIMIT:
            raise RuntimeError(f"Sagwan queue pending limit reached ({len(pending)}/{QUEUE_PENDING_LIMIT}).")
        sig = "::".join([kind, resource_key, freshness_key])
        for existing in queue["tasks"]:
            if existing.get("status") in ("pending", "running") and _dedup_signature(existing) == sig:
                return existing  # dedup hit
        task: dict[str, Any] = {
            "id": uuid4().hex,
            "schema_version": SCHEMA_VERSION,
            "kind": kind,
            "payload": payload,
            "resource_key": resource_key,
            "freshness_key": freshness_key,
            "write_set": write_set,
            "priority": int(priority),
            "status": "pending",
            "created_by": created_by,
            "reason": reason,
            "spawned_from": spawned_from,
            "root_task_id": root_task_id or "",
            "parent_task_id": parent_task_id or "",
            "chain_depth": int(chain_depth),
            "spawn_budget_used": 0,
            "created_at": _now_iso(),
            "run_after": run_after or _now_iso(),
            "started_at": "",
            "finished_at": "",
            "lease_expires_at": "",
            "retry_count": 0,
            "max_retries": int(max_retries),
            "decision_trace": [],
            "result_path": "",
            "last_error": "",
        }
        if not task["root_task_id"]:
            task["root_task_id"] = task["id"]
        queue["tasks"].append(task)
        _save_queue(queue)
    _trigger_wake()
    return task


# ─── self-enqueue with safeguards ───────────────────────────────────────────
def can_self_enqueue(parent_task: dict[str, Any], child_kind: str) -> tuple[bool, str]:
    """Return (allowed, reason). Reason is human-readable for decision_trace."""
    parent_kind = str(parent_task.get("kind") or "")
    allowed_kinds = SELF_ENQUEUE_WHITELIST.get(parent_kind, set())
    if child_kind not in allowed_kinds:
        return False, f"whitelist: {parent_kind} cannot spawn {child_kind}"
    if int(parent_task.get("chain_depth") or 0) + 1 > MAX_CHAIN_DEPTH:
        return False, f"chain_depth would exceed {MAX_CHAIN_DEPTH}"
    if int(parent_task.get("spawn_budget_used") or 0) + 1 > MAX_CHILDREN_PER_TASK:
        return False, f"would exceed {MAX_CHILDREN_PER_TASK} children/task"
    return True, "ok"


def recently_touched(kind: str, resource_key: str, *, hours: int = RECENTLY_TOUCHED_COOLDOWN_HOURS) -> bool:
    """True if a task with same (kind, resource_key) finished within the cooldown window."""
    cutoff = _now_dt() - timedelta(hours=hours)
    with _QUEUE_LOCK:
        queue = _load_queue()
    for t in queue["tasks"]:
        if t.get("kind") != kind or t.get("resource_key") != resource_key:
            continue
        if t.get("status") not in ("done", "failed"):
            continue
        finished = _parse_iso(t.get("finished_at"))
        if finished and finished >= cutoff:
            return True
    return False


def self_enqueue(
    parent_task: dict[str, Any],
    *,
    child_kind: str,
    payload: dict[str, Any],
    resource_key: str,
    freshness_key: str,
    write_set: list[str] | None = None,
    reason: str = "self-enqueue",
) -> dict[str, Any] | None:
    """Spawn a child task from inside a worker. Returns the child task or None
    if blocked by safeguards (in which case decision_trace explains why)."""
    ok, msg = can_self_enqueue(parent_task, child_kind)
    if not ok:
        parent_task.setdefault("decision_trace", []).append({
            "ts": _now_iso(),
            "event": "self_enqueue_blocked",
            "child_kind": child_kind,
            "resource": resource_key,
            "reason": msg,
        })
        return None
    if recently_touched(child_kind, resource_key):
        parent_task.setdefault("decision_trace", []).append({
            "ts": _now_iso(),
            "event": "self_enqueue_blocked",
            "child_kind": child_kind,
            "resource": resource_key,
            "reason": f"recently_touched (cooldown {RECENTLY_TOUCHED_COOLDOWN_HOURS}h)",
        })
        return None
    child = enqueue_task(
        kind=child_kind,
        payload=payload,
        resource_key=resource_key,
        freshness_key=freshness_key,
        write_set=write_set,
        created_by="sagwan",
        reason=reason,
        parent_task_id=str(parent_task.get("id") or ""),
        root_task_id=str(parent_task.get("root_task_id") or parent_task.get("id") or ""),
        chain_depth=int(parent_task.get("chain_depth") or 0) + 1,
        spawned_from=str(parent_task.get("kind") or ""),
    )
    if child:
        parent_task["spawn_budget_used"] = int(parent_task.get("spawn_budget_used") or 0) + 1
        parent_task.setdefault("decision_trace", []).append({
            "ts": _now_iso(),
            "event": "self_enqueue_ok",
            "child_id": child["id"],
            "child_kind": child_kind,
            "resource": resource_key,
        })
    return child


# ─── lease / claim / release ────────────────────────────────────────────────
def claim_next_task() -> dict[str, Any] | None:
    """Pick the next runnable task: pending OR running-with-expired-lease, ordered
    by (priority desc, run_after asc, created_at asc). Mark it running with a fresh
    lease. Returns the task or None.
    """
    now = _now_dt()
    disabled = _disabled_kinds()
    with _QUEUE_LOCK:
        queue = _load_queue()
        runnable: list[dict[str, Any]] = []
        for t in queue["tasks"]:
            status = t.get("status")
            if str(t.get("kind") or "") in disabled:
                continue       # skip disabled kinds even if queued
            if status == "pending":
                run_after = _parse_iso(t.get("run_after"))
                if run_after and run_after > now:
                    continue
                runnable.append(t)
            elif status == "running":
                lease = _parse_iso(t.get("lease_expires_at"))
                if lease is None or lease < now:
                    runnable.append(t)
        if not runnable:
            return None
        runnable.sort(key=lambda t: (
            -int(t.get("priority") or 0),
            t.get("run_after") or "",
            t.get("created_at") or "",
        ))
        chosen = runnable[0]
        chosen["status"] = "running"
        chosen["started_at"] = _now_iso()
        chosen["lease_expires_at"] = (_now_dt() + timedelta(seconds=LEASE_DURATION_SECONDS)).isoformat().replace("+00:00", "Z")
        _save_queue(queue)
        return dict(chosen)


def update_task(task_id: str, *, updates: dict[str, Any]) -> None:
    """Persist arbitrary updates to a task's record (worker mid-execution metadata)."""
    with _QUEUE_LOCK:
        queue = _load_queue()
        for t in queue["tasks"]:
            if t.get("id") == task_id:
                t.update(updates)
                break
        _save_queue(queue)


def complete_task(task_id: str, *, status: str, result_path: str = "", last_error: str = "",
                  decision_trace: list[dict[str, Any]] | None = None) -> None:
    """Mark a task done/failed/dead_letter. On 'failed' inside retry budget the
    queue automatically reclassifies as pending with backoff.
    """
    with _QUEUE_LOCK:
        queue = _load_queue()
        for t in queue["tasks"]:
            if t.get("id") != task_id:
                continue
            if status == "failed":
                retries = int(t.get("retry_count") or 0)
                if retries < int(t.get("max_retries") or DEFAULT_MAX_RETRIES):
                    backoff = RETRY_BACKOFF_BASE_SECONDS * (2 ** retries)
                    t["status"] = "pending"
                    t["retry_count"] = retries + 1
                    t["run_after"] = (_now_dt() + timedelta(seconds=backoff)).isoformat().replace("+00:00", "Z")
                    t["lease_expires_at"] = ""
                    t["last_error"] = last_error
                else:
                    t["status"] = "dead_letter"
                    t["last_error"] = last_error
                    t["finished_at"] = _now_iso()
            else:
                t["status"] = status
                t["finished_at"] = _now_iso()
                t["lease_expires_at"] = ""
                if result_path:
                    t["result_path"] = result_path
                if last_error:
                    t["last_error"] = last_error
            if decision_trace is not None:
                t["decision_trace"] = decision_trace
            break
        _save_queue(queue)


# ─── listing / introspection ────────────────────────────────────────────────
def list_tasks(*, status: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    with _QUEUE_LOCK:
        queue = _load_queue()
    tasks = list(queue.get("tasks") or [])
    if status:
        wanted = status.strip().lower()
        tasks = [t for t in tasks if str(t.get("status") or "").lower() == wanted]
    tasks.sort(key=lambda t: t.get("created_at") or "", reverse=True)
    if limit:
        tasks = tasks[:limit]
    return tasks


def queue_stats() -> dict[str, Any]:
    with _QUEUE_LOCK:
        queue = _load_queue()
    by_status: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    oldest_pending: str | None = None
    for t in queue["tasks"]:
        s = str(t.get("status") or "?")
        by_status[s] = by_status.get(s, 0) + 1
        k = str(t.get("kind") or "?")
        by_kind[k] = by_kind.get(k, 0) + 1
        if s == "pending":
            ts = t.get("created_at") or ""
            if oldest_pending is None or ts < oldest_pending:
                oldest_pending = ts
    return {
        "total": len(queue["tasks"]),
        "by_status": by_status,
        "by_kind": by_kind,
        "oldest_pending": oldest_pending,
    }


# ─── housekeeping ───────────────────────────────────────────────────────────
def prune_done(*, older_than_days: int = DONE_PRUNE_AFTER_DAYS) -> int:
    """Delete done/failed/dead_letter tasks older than threshold. Returns removed count."""
    cutoff = _now_dt() - timedelta(days=older_than_days)
    removed = 0
    with _QUEUE_LOCK:
        queue = _load_queue()
        survivors: list[dict[str, Any]] = []
        for t in queue["tasks"]:
            if t.get("status") in ("done", "failed", "dead_letter"):
                fin = _parse_iso(t.get("finished_at"))
                if fin and fin < cutoff:
                    removed += 1
                    continue
            survivors.append(t)
        if removed:
            queue["tasks"] = survivors
            _save_queue(queue)
    return removed
