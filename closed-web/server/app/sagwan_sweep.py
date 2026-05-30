"""
sagwan_sweep.py — Stage Z (autonomous sweep) engine.

Codex review (2026-05-04 v7) decision: Z is **orchestration only, no execution**.
Existing stages already do narrow domain work; Z gathers a panorama and decides
whether to enqueue, escalate, annotate, or trigger Stage S as a deadlock breaker.

Action types (8):
    1. add_goal              — sagwan adds a goal to its own agenda
    2. add_concern           — sagwan flags a risk
    3. priority_enqueue      — urgent maintenance/conflict task at priority=2
    4. trigger_stage_s       — directly trigger operating-note edit (Stage S)
    5. improvement_request   — open a human-review note
    6. update_goal           — adjust an existing goal's status/priority/next_actions
    7. propose_oa_improvement — write a markdown draft to OpenAkashic proposals/
    8. no_op                 — explicit abstain with logged rationale (valid)

Hard caps (per 24h, Codex-tightened):
    add_goal                   ≤ 1
    add_concern                ≤ 2
    priority_enqueue           ≤ 3
    trigger_stage_s            bypasses 24h capacity
    improvement_request        ≤ 1
    update_goal                ≤ 3
    propose_oa_improvement     ≤ 2

Same-target cooldown: 24h on (action_kind, target_key) — prevents storm.

Safeguards against Codex's 4 extra risks:
    - prompt-injection: schema-validated JSON only; strip suspicious tokens
      ("ignore previous", "system:", control characters) from any text fields
    - self-justifying loops: dedup against open goals/concerns (same statement)
    - duplicate escalation storms: rate limit + cooldown + open-goal/concern dedup
    - private→public leakage: propose_oa_improvement starts with visibility=private
      and a `proposal-draft` tag mandatory; never auto-promotes to public

7-day no-action protection: if sweep has been silent ≥7d AND panorama shows
out-of-bounds metric, the LLM is *required* to emit at least concern or IR.
"""
from __future__ import annotations

import collections
import json
import logging
import os
import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import get_settings
from app.vault import append_section, list_note_paths, load_document, write_document

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SWEEP_LOG_PATH = "personal_vault/projects/ops/librarian/activity/sweep-log.md"
PROPOSALS_FOLDER = "personal_vault/projects/personal/openakashic/proposals"

# Per-kind 24h hard caps (Codex v7 tightened). trigger_stage_s is a deadlock
# breaker and bypasses this 24h capacity check.
ACTION_RATE_LIMITS_24H: dict[str, int] = {
    "add_goal": 1,
    "add_concern": 2,
    "priority_enqueue": 3,
    "trigger_stage_s": 9999,
    "improvement_request": 1,
    "update_goal": 3,
    "propose_oa_improvement": 2,
    "no_op": 9999,
}

SAME_TARGET_COOLDOWN_HOURS = 24
NO_ACTION_BREAK_DAYS = 7   # if 7d silent + panorama signals → must act

# Prompt-injection token list (rejected if found in any LLM-supplied text)
SUSPICIOUS_PATTERNS = [
    r"(?i)\bignore (previous|all|prior) (instructions|context)\b",
    r"(?i)\bsystem\s*:",
    r"(?i)\bdisregard\b.*\bprevious\b",
    r"‮",  # right-to-left override
    r"(?i)\bprompt\s*injection\b",
]


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


# ─── prompt-injection sanitizer ─────────────────────────────────────────────
def looks_injected(text: str) -> bool:
    if not text:
        return False
    return any(re.search(pat, text) for pat in SUSPICIOUS_PATTERNS)


def sanitize_text(text: str, max_len: int = 4000) -> str:
    """Strip control chars + truncate. Used for any text the LLM emits that
    will be persisted to vault notes."""
    if not text:
        return ""
    # remove most control chars except \n \t
    cleaned = "".join(ch for ch in text if ch == "\n" or ch == "\t" or 32 <= ord(ch) < 127 or ord(ch) >= 0xA0)
    return cleaned[:max_len]


# ─── panorama gathering ─────────────────────────────────────────────────────
def gather_panorama() -> dict[str, Any]:
    """Snapshot the operational state Z needs to decide on actions.
    No mutation. Pure read.
    """
    from app import sagwan_agenda, sagwan_self_edit, sagwan_tasks

    panorama: dict[str, Any] = {"ts": _now_iso()}

    # queue
    try:
        panorama["queue"] = sagwan_tasks.queue_stats()
    except Exception as exc:
        panorama["queue"] = {"error": str(exc)[:120]}

    # agenda + concerns + recent picks
    try:
        snap = sagwan_agenda.get_observability_snapshot()
        active_concerns = [c for c in (snap.get("active_concerns") or []) if _concern_still_active(c)]
        panorama["agenda_count"] = len(snap.get("current_agenda") or [])
        panorama["agenda_titles"] = [g.get("statement", "")[:80] for g in (snap.get("current_agenda") or [])][:5]
        panorama["concerns_count"] = len(active_concerns)
        panorama["why_this_next_recent"] = (snap.get("why_this_next") or [])[:3]
    except Exception as exc:
        panorama["agenda_error"] = str(exc)[:120]

    # vault graph density (read-only count)
    try:
        from app.sagwan_loop import _build_inbound_index  # late import to avoid cycle
        inbound = _build_inbound_index()
        total_notes = sum(1 for _ in list_note_paths())
        with_inbound = len(inbound)
        orphan_ratio = round(1 - (with_inbound / max(1, total_notes)), 3)
        panorama["vault"] = {
            "total_notes": total_notes,
            "with_inbound": with_inbound,
            "orphan_ratio": orphan_ratio,
            "total_inbound_edges": sum(inbound.values()),
        }
    except Exception as exc:
        panorama["vault_error"] = str(exc)[:120]

    # recent maintenance verdict distribution (last 24h)
    try:
        cutoff = _now_dt() - timedelta(hours=24)
        verdicts = collections.Counter()
        log_doc = load_document("personal_vault/projects/ops/librarian/activity/maintenance-log.md")
        for m in re.finditer(
            r"## (20\d{2}-\d{2}-\d{2}T[\d:]+Z) maintenance\s*\n- target: ([^\n]+)\n- verdict: (\w+)",
            log_doc.body or "",
        ):
            t = _parse_iso(m.group(1))
            if t and t >= cutoff:
                verdicts[m.group(3)] += 1
        panorama["maintenance_24h"] = dict(verdicts)
    except Exception as exc:
        panorama["maintenance_error"] = str(exc)[:120]

    # self-edit history
    try:
        panorama["self_edits_7d"] = sagwan_self_edit.get_self_edit_snapshot(lookback_hours=168)["total"]
    except Exception:
        panorama["self_edits_7d"] = 0

    # recent sweep actions
    try:
        panorama["sweep_recent"] = list_recent_sweep_entries(hours=24 * NO_ACTION_BREAK_DAYS)
    except Exception:
        panorama["sweep_recent"] = []

    return panorama


def _concern_still_active(concern: dict[str, Any]) -> bool:
    exp = _parse_iso(str(concern.get("expires_at") or ""))
    return exp is None or exp >= _now_dt()


# ─── sweep log ──────────────────────────────────────────────────────────────
def list_recent_sweep_entries(*, hours: int = 168) -> list[dict[str, Any]]:
    cutoff = _now_dt() - timedelta(hours=hours)
    out: list[dict[str, Any]] = []
    try:
        doc = load_document(SWEEP_LOG_PATH)
    except Exception:
        return out
    for m in re.finditer(
        r"## (20\d{2}-\d{2}-\d{2}T[\d:]+Z) sweep\s*\n([\s\S]+?)(?=\n## |\Z)",
        doc.body or "",
    ):
        ts = _parse_iso(m.group(1))
        if ts is None or ts < cutoff:
            continue
        block = m.group(2)
        actions = re.findall(r"^- action: (\w+)", block, re.MULTILINE)
        rationale_m = re.search(r"^- rationale: (.+?)(?=\n- |\Z)", block, re.MULTILINE | re.DOTALL)
        out.append({
            "ts": m.group(1),
            "actions": actions,
            "rationale": (rationale_m.group(1).strip() if rationale_m else "")[:200],
        })
    return out


def append_sweep_entry(*, panorama: dict[str, Any], actions: list[dict[str, Any]],
                       rationale: str) -> None:
    try:
        load_document(SWEEP_LOG_PATH)
    except Exception:
        write_document(
            path=SWEEP_LOG_PATH,
            body="## Summary\nSagwan autonomous sweep audit log.\n",
            title="Sagwan Sweep Log",
            kind="activity",
            project="ops/librarian",
            tags=["sagwan", "sweep", "audit"],
            allow_owner_change=True,
        )
    panorama_summary = {
        "queue": panorama.get("queue"),
        "vault": panorama.get("vault"),
        "agenda_count": panorama.get("agenda_count"),
        "concerns_count": panorama.get("concerns_count"),
        "maintenance_24h": panorama.get("maintenance_24h"),
        "self_edits_7d": panorama.get("self_edits_7d"),
    }
    body_lines = [
        f"- rationale: {sanitize_text(rationale, 400)}",
        f"- panorama: `{json.dumps(panorama_summary, ensure_ascii=False)[:500]}`",
        f"- action_count: {len(actions)}",
    ]
    for a in actions:
        body_lines.append(f"- action: {a.get('kind')}")
        body_lines.append(f"  - outcome: {a.get('outcome', '?')}")
        body_lines.append(f"  - target: {a.get('target_summary', '')[:120]}")
    append_section(SWEEP_LOG_PATH, f"{_now_iso()} sweep", "\n".join(body_lines))


# ─── rate limit + dedup ─────────────────────────────────────────────────────
def _count_action_24h(action_kind: str) -> int:
    cutoff = _now_dt() - timedelta(hours=24)
    n = 0
    for entry in list_recent_sweep_entries(hours=24):
        ts = _parse_iso(entry.get("ts"))
        if ts and ts >= cutoff:
            n += sum(1 for a in entry.get("actions", []) if a == action_kind)
    return n


def can_do_action(action_kind: str) -> tuple[bool, str]:
    """Check rate limit. Returns (allowed, reason_if_not)."""
    cap = ACTION_RATE_LIMITS_24H.get(action_kind, 0)
    if cap == 0:
        return False, f"unknown_action_kind: {action_kind}"
    if cap >= 9999:
        return True, "ok"
    used = _count_action_24h(action_kind)
    if used >= cap:
        return False, f"rate_limit_24h ({used}/{cap})"
    return True, "ok"


def same_target_recently_acted(action_kind: str, target_key: str, *, hours: int = SAME_TARGET_COOLDOWN_HOURS) -> bool:
    """Check (action_kind, target_key) in last `hours`."""
    if not target_key:
        return False
    cutoff = _now_dt() - timedelta(hours=hours)
    try:
        doc = load_document(SWEEP_LOG_PATH)
    except Exception:
        return False
    body = doc.body or ""
    # Look at sweep entries where action AND target match within window
    for m in re.finditer(
        r"## (20\d{2}-\d{2}-\d{2}T[\d:]+Z) sweep\s*\n([\s\S]+?)(?=\n## |\Z)",
        body,
    ):
        ts = _parse_iso(m.group(1))
        if ts is None or ts < cutoff:
            continue
        block = m.group(2)
        # actions are listed as `- action: KIND` followed by `  - target: SUMMARY`
        for am in re.finditer(r"^- action: (\w+)\s*\n((?:  - .+\n)+)", block, re.MULTILINE):
            kind = am.group(1)
            sub = am.group(2)
            if kind == action_kind and target_key in sub:
                return True
    return False


# ─── action dispatcher ──────────────────────────────────────────────────────
def execute_action(action: dict[str, Any], *, requested_by: str = "sagwan") -> dict[str, Any]:
    """Apply one action. Returns dict with at least {kind, outcome, target_summary}.
    Outcome is 'applied' / 'rejected' / 'queued'.
    """
    kind = str(action.get("kind") or "").strip()
    rationale = sanitize_text(str(action.get("rationale") or ""))

    if kind not in ACTION_RATE_LIMITS_24H:
        return {"kind": kind, "outcome": "rejected", "target_summary": "",
                "reason": "unknown_kind"}

    if kind == "no_op":
        return {"kind": "no_op", "outcome": "applied", "target_summary": "",
                "rationale_head": rationale[:120]}

    if kind != "trigger_stage_s":
        ok, why = can_do_action(kind)
        if not ok:
            return {"kind": kind, "outcome": "rejected", "target_summary": "",
                    "reason": why}

    # Reject prompt-injection in any user-emitted free text
    for fld in ("rationale", "statement", "text", "new_content", "title", "body"):
        v = action.get(fld)
        if isinstance(v, str) and looks_injected(v):
            return {"kind": kind, "outcome": "rejected", "target_summary": "",
                    "reason": f"prompt_injection_in_field:{fld}"}

    # ── per-kind dispatch ───────────────────────────────────────────────
    if kind == "add_goal":
        return _do_add_goal(action, rationale, requested_by)
    if kind == "add_concern":
        return _do_add_concern(action, rationale, requested_by)
    if kind == "priority_enqueue":
        return _do_priority_enqueue(action, rationale)
    if kind == "trigger_stage_s":
        return _do_trigger_stage_s(action, rationale)
    if kind == "improvement_request":
        return _do_improvement_request(action, rationale, requested_by)
    if kind == "update_goal":
        return _do_update_goal(action, rationale, requested_by)
    if kind == "propose_oa_improvement":
        return _do_propose_oa_improvement(action, rationale, requested_by)
    return {"kind": kind, "outcome": "rejected", "target_summary": "",
            "reason": "no_dispatcher"}


def _do_add_goal(action: dict[str, Any], rationale: str, requested_by: str) -> dict[str, Any]:
    from app import sagwan_agenda
    statement = sanitize_text(str(action.get("statement") or ""), 200)
    if not statement:
        return {"kind": "add_goal", "outcome": "rejected", "target_summary": "",
                "reason": "no_statement"}
    # dedup against open goals (same statement → don't duplicate)
    for g in sagwan_agenda.list_goals(status="active"):
        if g.get("statement") == statement:
            return {"kind": "add_goal", "outcome": "rejected", "target_summary": statement[:80],
                    "reason": "duplicate_open_goal"}
    if same_target_recently_acted("add_goal", statement[:60]):
        return {"kind": "add_goal", "outcome": "rejected", "target_summary": statement[:80],
                "reason": "same_target_cooldown"}
    goal = sagwan_agenda.add_goal(
        statement=statement,
        metric=sanitize_text(str(action.get("metric") or ""), 80),
        target=sanitize_text(str(action.get("target") or ""), 80),
        horizon_days=int(action.get("horizon_days") or 7),
        owner="sagwan",
        created_by=requested_by,
        next_actions=[sanitize_text(str(a), 200) for a in (action.get("next_actions") or [])][:5],
        notes=rationale,
        priority=int(action.get("priority") or 1),
    )
    return {"kind": "add_goal", "outcome": "applied",
            "target_summary": statement[:80],
            "goal_id": goal["id"]}


def _do_add_concern(action: dict[str, Any], rationale: str, requested_by: str) -> dict[str, Any]:
    from app import sagwan_agenda
    statement = sanitize_text(str(action.get("statement") or ""), 200)
    if not statement:
        return {"kind": "add_concern", "outcome": "rejected", "target_summary": "",
                "reason": "no_statement"}
    if same_target_recently_acted("add_concern", statement[:60]):
        return {"kind": "add_concern", "outcome": "rejected", "target_summary": statement[:80],
                "reason": "same_target_cooldown"}
    entry = sagwan_agenda.add_concern(
        statement=statement,
        severity=str(action.get("severity") or "medium").lower(),
        source=requested_by,
        tags=[sanitize_text(str(t), 40) for t in (action.get("tags") or [])][:6],
        related_paths=[str(p) for p in (action.get("related_paths") or []) if str(p).strip()][:6],
        ttl_hours=int(action.get("ttl_hours") or 72),
    )
    return {"kind": "add_concern", "outcome": "applied",
            "target_summary": statement[:80], "concern_id": entry.get("id", "")}


def _do_priority_enqueue(action: dict[str, Any], rationale: str) -> dict[str, Any]:
    from app import sagwan_tasks
    target_path = sanitize_text(str(action.get("target_path") or ""), 300)
    if not target_path:
        return {"kind": "priority_enqueue", "outcome": "rejected", "target_summary": "",
                "reason": "no_target_path"}
    task_kind = str(action.get("task_kind") or "check_capsule_maintenance")
    if task_kind not in sagwan_tasks.SAGWAN_TASK_KINDS:
        return {"kind": "priority_enqueue", "outcome": "rejected", "target_summary": target_path,
                "reason": f"unknown_task_kind:{task_kind}"}
    if same_target_recently_acted("priority_enqueue", target_path):
        return {"kind": "priority_enqueue", "outcome": "rejected", "target_summary": target_path,
                "reason": "same_target_cooldown"}
    try:
        doc = load_document(target_path)
    except Exception as exc:
        return {"kind": "priority_enqueue", "outcome": "rejected", "target_summary": target_path,
                "reason": f"load_failed:{exc}"[:120]}
    fm = dict(doc.frontmatter or {})
    res = sagwan_tasks.enqueue_task(
        kind=task_kind,
        payload={"path": target_path},
        resource_key=target_path,
        freshness_key=sagwan_tasks.compute_freshness_key(
            updated_at=str(fm.get("updated_at") or ""), body=doc.body),
        write_set=[target_path],
        priority=2,
        created_by="sagwan",
        reason=f"sweep_priority: {rationale[:60]}",
    )
    return {"kind": "priority_enqueue", "outcome": "applied" if res else "deduped",
            "target_summary": target_path, "task_id": (res or {}).get("id", "")}


def _do_trigger_stage_s(action: dict[str, Any], rationale: str) -> dict[str, Any]:
    """Directly invoke Stage S as the no-action breaker.

    This action intentionally bypasses the sweep 24h action-capacity check; Stage
    S still keeps its own model/self-edit safety gates.
    """
    try:
        from app import sagwan_loop  # late import: sagwan_loop imports this module
        out = sagwan_loop._curate_self_improve(force=True)
    except Exception as exc:
        return {"kind": "trigger_stage_s", "outcome": "rejected",
                "target_summary": "Stage S self-improve",
                "reason": f"stage_s_failed:{exc}"[:120]}
    return {"kind": "trigger_stage_s", "outcome": "applied",
            "target_summary": "Stage S self-improve",
            "stage_s_status": str((out or {}).get("status") or "")[:80]}


def _do_improvement_request(action: dict[str, Any], rationale: str, requested_by: str) -> dict[str, Any]:
    title = sanitize_text(str(action.get("title") or "Sagwan sweep request"), 120)
    body_text = sanitize_text(str(action.get("body") or rationale or "(no body)"), 4000)
    slug = re.sub(r"[^\w\-]+", "-", title).strip("-").lower()[:60] or uuid4().hex[:8]
    ts = _now_iso()
    path = f"personal_vault/meta/improvement-requests/sweep-{slug}-{ts.replace(':','').lower()}.md"
    if same_target_recently_acted("improvement_request", title[:60]):
        return {"kind": "improvement_request", "outcome": "rejected", "target_summary": title,
                "reason": "same_target_cooldown"}
    try:
        write_document(
            path=path,
            body="\n".join([
                "## Summary",
                title,
                "",
                "## Rationale",
                rationale or "(none)",
                "",
                "## Body",
                body_text,
            ]),
            title=title,
            kind="improvement-request",
            project="ops/librarian",
            tags=["sagwan", "sweep", "auto"],
            metadata={"status": "proposed", "owner": requested_by, "source": "sweep"},
            allow_owner_change=True,
        )
    except Exception as exc:
        return {"kind": "improvement_request", "outcome": "rejected", "target_summary": title,
                "reason": f"write_failed:{exc}"[:120]}
    return {"kind": "improvement_request", "outcome": "applied",
            "target_summary": title[:80], "request_path": path}


def _do_update_goal(action: dict[str, Any], rationale: str, requested_by: str) -> dict[str, Any]:
    from app import sagwan_agenda
    goal_id = str(action.get("goal_id") or "").strip()
    if not goal_id:
        return {"kind": "update_goal", "outcome": "rejected", "target_summary": "",
                "reason": "no_goal_id"}
    if same_target_recently_acted("update_goal", goal_id):
        return {"kind": "update_goal", "outcome": "rejected", "target_summary": goal_id,
                "reason": "same_target_cooldown"}
    patch: dict[str, Any] = {}
    if "status" in action:
        patch["status"] = str(action["status"])
    if "priority" in action:
        try: patch["priority"] = int(action["priority"])
        except: pass
    if "next_actions" in action:
        patch["next_actions"] = [sanitize_text(str(a), 200) for a in (action.get("next_actions") or [])][:5]
    if "notes" in action:
        patch["notes"] = sanitize_text(str(action["notes"]), 400)
    if not patch:
        return {"kind": "update_goal", "outcome": "rejected", "target_summary": goal_id,
                "reason": "empty_patch"}
    out = sagwan_agenda.update_goal(goal_id, by=requested_by, **patch)
    if out is None:
        return {"kind": "update_goal", "outcome": "rejected", "target_summary": goal_id,
                "reason": "goal_not_found"}
    return {"kind": "update_goal", "outcome": "applied",
            "target_summary": (out.get("statement") or "")[:80],
            "goal_id": goal_id, "patched_fields": list(patch.keys())}


def _do_propose_oa_improvement(action: dict[str, Any], rationale: str, requested_by: str) -> dict[str, Any]:
    """v7.1: write a markdown draft to OpenAkashic proposals subtree.
    Always visibility=private + tag `proposal-draft` (per Codex). Never auto-promotes.
    """
    title = sanitize_text(str(action.get("title") or ""), 120)
    body = sanitize_text(str(action.get("body") or ""), 6000)
    if not title or not body:
        return {"kind": "propose_oa_improvement", "outcome": "rejected", "target_summary": title,
                "reason": "no_title_or_body"}
    slug = re.sub(r"[^\w\-]+", "-", title).strip("-").lower()[:60] or uuid4().hex[:8]
    ts = _now_iso()
    path = f"{PROPOSALS_FOLDER}/sweep-{slug}-{ts.replace(':','').lower()}.md"
    if same_target_recently_acted("propose_oa_improvement", title[:60]):
        return {"kind": "propose_oa_improvement", "outcome": "rejected", "target_summary": title,
                "reason": "same_target_cooldown"}
    # Defense: private→public leakage. Reject if body has obvious secret patterns.
    secret_patterns = [r"sk-[a-zA-Z0-9]{16,}", r"BEGIN [A-Z ]+ PRIVATE KEY",
                       r"AKIA[A-Z0-9]{16}", r"ghp_[a-zA-Z0-9]{20,}"]
    for p in secret_patterns:
        if re.search(p, body):
            return {"kind": "propose_oa_improvement", "outcome": "rejected", "target_summary": title,
                    "reason": "potential_secret_in_body"}
    try:
        write_document(
            path=path,
            body="\n".join([
                "## Summary",
                title,
                "",
                "## Rationale",
                rationale or "(none)",
                "",
                "## Proposal",
                body,
                "",
                "## Reviewer Action",
                "이 제안은 사관(sagwan)이 자동 생성한 *draft* 입니다.",
                "사람 review 후 git/공개 surface에 반영하세요. 자동 promotion 없음.",
            ]),
            title=title,
            kind="reference",
            project="personal/openakashic",
            tags=["sagwan", "sweep", "proposal-draft", "openakashic-improvement"],
            metadata={
                "status": "draft",
                "owner": requested_by,
                "visibility": "private",          # never auto-public
                "publication_status": "none",
                "source": "sweep",
            },
            allow_owner_change=True,
        )
    except Exception as exc:
        return {"kind": "propose_oa_improvement", "outcome": "rejected", "target_summary": title,
                "reason": f"write_failed:{exc}"[:120]}
    return {"kind": "propose_oa_improvement", "outcome": "applied",
            "target_summary": title[:80], "draft_path": path}


# ─── observability ──────────────────────────────────────────────────────────
def get_sweep_snapshot(*, lookback_hours: int = 168) -> dict[str, Any]:
    entries = list_recent_sweep_entries(hours=lookback_hours)
    by_action: dict[str, int] = {}
    for e in entries:
        for a in e.get("actions", []):
            by_action[a] = by_action.get(a, 0) + 1
    return {
        "lookback_hours": lookback_hours,
        "sweeps": len(entries),
        "actions_by_kind": by_action,
        "recent": entries[:10],
    }


def days_since_last_action() -> int:
    """How many days since the last sweep that produced ≥1 non-no_op action."""
    entries = list_recent_sweep_entries(hours=24 * 30)
    for e in entries:
        non_noop = [a for a in e.get("actions", []) if a != "no_op"]
        if non_noop:
            ts = _parse_iso(e.get("ts"))
            if ts:
                return (_now_dt() - ts).days
    return 999  # never
