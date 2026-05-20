"""
sagwan_self_edit.py — Stage S engine for sagwan to edit its own operating notes.

Design (insu, 2026-05-04):
    Sagwan reads its own logs/distilled memory, judges room for improvement,
    and DIRECTLY edits the markdown notes that drive its behavior. Those notes
    are already injected into prompts via `before_task_context`, so the next
    cycle automatically picks up the change.

Codex review (2026-05-04 §5) flagged the real risk as "write authority
explosion" — not what to fix, but how far the agent can reach. This module
enforces the safety nets:

    - subtree allowlist: only `personal_vault/projects/ops/librarian/` subtree
    - one file, one section per call
    - diff size cap (≤ MAX_DIFF_BYTES per edit)
    - rollback log: every successful edit appends a record with the prior body
      so a human (or sagwan itself in a future cycle) can revert
    - per-target-class rate limit (Profile rare, Policy medium, Playbook frequent)
    - structural validation: protected sections cannot be deleted
    - risk_level=medium|high → improvement-request only (never direct write)
    - Profile.md / Policy.md whole-body replace is forbidden — section patch only

The actual LLM call lives in `_curate_self_improve` (sagwan_loop). This module
is the durable safety layer it goes through.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from app.vault import load_document, write_document, append_section

logger = logging.getLogger(__name__)

# ─── Constants & target-class policies ──────────────────────────────────────
SUBTREE_ALLOWLIST = "personal_vault/projects/ops/librarian/"

MAX_DIFF_BYTES = 4_000     # any single edit's new_content cap
MAX_SAME_TARGET_PER_24H = 1  # rate limit per exact path

ROLLBACK_LOG_PATH = "personal_vault/projects/ops/librarian/activity/self-edit-history.md"

# Target classes — different update semantics per Codex.
TARGET_CLASSES = {
    "profile": {
        "path_marker": "/profile/",
        "cooldown_hours": 24,
        "allow_full_body_replace": False,         # section-only
        "required_sections": ("## Summary", "## Persona"),  # cannot disappear
        "max_edits_per_class_per_24h": 1,
    },
    "policy": {
        "path_marker": "/policy/",
        "cooldown_hours": 12,
        "allow_full_body_replace": False,
        "required_sections": ("## Summary",),
        "max_edits_per_class_per_24h": 2,
    },
    "playbooks": {
        "path_marker": "/playbooks/",
        "cooldown_hours": 4,
        "allow_full_body_replace": True,         # playbooks can be rewritten
        "required_sections": (),                  # no protected sections
        "max_edits_per_class_per_24h": 4,
    },
    "readme": {
        "path_marker": "/README.md",
        "cooldown_hours": 24,
        "allow_full_body_replace": False,
        "required_sections": (),
        "max_edits_per_class_per_24h": 1,
    },
}

# Risk levels — only `low` is eligible for direct write.
DIRECT_WRITE_ALLOWED_RISK = {"low"}

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


# ─── target classification ──────────────────────────────────────────────────
def classify_target(path: str) -> str | None:
    """Return target class name (key in TARGET_CLASSES) or None if path is
    outside the allowlist or unrecognized."""
    if not path or not path.startswith(SUBTREE_ALLOWLIST):
        return None
    for cls_name, cfg in TARGET_CLASSES.items():
        marker = cfg["path_marker"]
        if marker in path:
            return cls_name
    # Reject paths inside the librarian subtree but not under a known marker
    # (e.g., capsules/, memory/, activity/) — those aren't operating notes.
    return None


# ─── recent-edit tracking (rate limit) ──────────────────────────────────────
def _recent_edits(*, hours: int = 24) -> list[dict[str, Any]]:
    """Read self-edit-history.md and parse recent entries within window."""
    cutoff = _now_dt() - timedelta(hours=hours)
    out: list[dict[str, Any]] = []
    try:
        doc = load_document(ROLLBACK_LOG_PATH)
    except Exception:
        return out
    body = doc.body or ""
    for m in re.finditer(
        r"^## (20\d{2}-\d{2}-\d{2}T[\d:]+Z) self-edit\s*\n([\s\S]+?)(?=\n## |\Z)",
        body,
        re.MULTILINE,
    ):
        ts_raw = m.group(1)
        ts = _parse_iso(ts_raw)
        if ts is None or ts < cutoff:
            continue
        block = m.group(2)
        target = re.search(r"^- target_path: `?([^`\n]+)`?", block, re.MULTILINE)
        target_class = re.search(r"^- target_class: (\w+)", block, re.MULTILINE)
        section = re.search(r"^- section: `?([^`\n]*)`?", block, re.MULTILINE)
        out.append({
            "ts": ts_raw,
            "target_path": target.group(1).strip() if target else "",
            "target_class": target_class.group(1) if target_class else "",
            "section": section.group(1).strip() if section else "",
        })
    return out


# ─── public engine: apply or queue an edit ──────────────────────────────────
def attempt_self_edit(
    *,
    target_path: str,
    section: str | None,
    new_content: str,
    rationale: str,
    risk_level: str,
    full_body_replace: bool = False,
    requested_by: str = "sagwan",
) -> dict[str, Any]:
    """Single entry point. Returns a dict with status:
       - "applied"               — direct write completed, edit appended to rollback log
       - "queued_for_review"     — converted to improvement-request note
       - "rejected"              — safety net blocked it (with reason)
    Validates everything before any write.
    """
    risk_level = (risk_level or "").lower().strip() or "high"
    target_path = (target_path or "").strip()

    # ── allowlist + classification ──
    cls = classify_target(target_path)
    if cls is None:
        return _reject(target_path, "outside_allowlist_or_unknown_class",
                       rationale=rationale, risk_level=risk_level)
    cfg = TARGET_CLASSES[cls]

    # ── existence check ──
    try:
        doc = load_document(target_path)
    except Exception as exc:
        return _reject(target_path, f"target_not_found: {exc}",
                       rationale=rationale, risk_level=risk_level)
    prior_body = doc.body or ""

    # ── full-body replace guard ──
    if full_body_replace and not cfg["allow_full_body_replace"]:
        return _reject(target_path, f"full_body_replace_forbidden_for_{cls}",
                       rationale=rationale, risk_level=risk_level)

    # ── diff size cap ──
    if len(new_content.encode("utf-8")) > MAX_DIFF_BYTES:
        return _reject(target_path, f"new_content_too_large (>{MAX_DIFF_BYTES} bytes)",
                       rationale=rationale, risk_level=risk_level)

    # ── compute the would-be new body (without writing yet) ──
    if full_body_replace:
        next_body = new_content
    else:
        if not section or not section.strip():
            return _reject(target_path, "section_required_when_not_full_body_replace",
                           rationale=rationale, risk_level=risk_level)
        next_body = _replace_or_append_section(prior_body, section.strip(), new_content)

    # ── structural validation ──
    for required in cfg["required_sections"]:
        if required not in next_body:
            return _reject(target_path, f"would_remove_required_section: {required}",
                           rationale=rationale, risk_level=risk_level)

    # ── risk-level gate: medium/high go to improvement-request ──
    if risk_level not in DIRECT_WRITE_ALLOWED_RISK:
        return _queue_improvement_request(
            target_path=target_path,
            target_class=cls,
            section=section,
            new_content=new_content,
            rationale=rationale,
            risk_level=risk_level,
            full_body_replace=full_body_replace,
            requested_by=requested_by,
        )

    # ── rate limit: per-path 1 / 24h, per-class N / 24h ──
    with _LOCK:
        recents = _recent_edits(hours=24)
        same_path = sum(1 for r in recents if r.get("target_path") == target_path)
        if same_path >= MAX_SAME_TARGET_PER_24H:
            return _reject(target_path, f"rate_limit_per_path (>{MAX_SAME_TARGET_PER_24H}/24h)",
                           rationale=rationale, risk_level=risk_level)
        same_class = sum(1 for r in recents if r.get("target_class") == cls)
        if same_class >= cfg["max_edits_per_class_per_24h"]:
            return _reject(target_path, f"rate_limit_per_class_{cls} (>{cfg['max_edits_per_class_per_24h']}/24h)",
                           rationale=rationale, risk_level=risk_level)

        # ── apply (direct write) ──
        try:
            fm = dict(doc.frontmatter or {})
            fm["updated_at"] = _now_iso()
            write_document(path=target_path, body=next_body, metadata=fm,
                           allow_owner_change=True, metadata_replace=True)
        except Exception as exc:
            logger.warning("self_edit: write failed %s: %s", target_path, exc)
            return _reject(target_path, f"write_failed: {exc}",
                           rationale=rationale, risk_level=risk_level)

        # ── rollback log append ──
        try:
            _append_rollback_entry(
                target_path=target_path,
                target_class=cls,
                section=section,
                rationale=rationale,
                prior_body=prior_body,
                requested_by=requested_by,
            )
        except Exception as exc:
            logger.warning("self_edit: rollback log append failed: %s", exc)

    return {
        "status": "applied",
        "target_path": target_path,
        "target_class": cls,
        "section": section,
        "risk_level": risk_level,
    }


# ─── helpers ────────────────────────────────────────────────────────────────
def _replace_or_append_section(body: str, section_heading: str, new_section_content: str) -> str:
    """If `section_heading` (e.g. '## Persona') exists, replace its block.
    Otherwise append `\n\n{section_heading}\n{new_section_content}\n` at end.
    Section block = heading + content until next `^## ` line or EOF.
    """
    heading = section_heading.strip()
    pattern = re.compile(
        r"(^" + re.escape(heading) + r"\s*\n)([\s\S]*?)(?=^## |\Z)",
        re.MULTILINE,
    )
    m = pattern.search(body)
    if m:
        # Replace the body content (preserve heading itself)
        before = body[: m.start()]
        after = body[m.end():]
        return f"{before}{heading}\n{new_section_content.strip()}\n\n{after}".rstrip() + "\n"
    # Append
    base = (body or "").rstrip()
    return f"{base}\n\n{heading}\n{new_section_content.strip()}\n"


def _reject(target_path: str, reason: str, *, rationale: str, risk_level: str) -> dict[str, Any]:
    logger.info("self_edit: rejected %s — %s", target_path, reason)
    return {
        "status": "rejected",
        "target_path": target_path,
        "reason": reason,
        "rationale_head": (rationale or "")[:160],
        "risk_level": risk_level,
    }


def _queue_improvement_request(
    *,
    target_path: str,
    target_class: str,
    section: str | None,
    new_content: str,
    rationale: str,
    risk_level: str,
    full_body_replace: bool,
    requested_by: str,
) -> dict[str, Any]:
    """Convert a medium/high risk edit into an improvement-request note for
    human review. Reuses the existing improvement-requests folder."""
    slug = re.sub(r"[^\w\-]+", "-", target_path).strip("-").lower()[:80]
    ts = _now_iso()
    req_path = f"personal_vault/meta/improvement-requests/self-edit-{slug}-{ts.replace(':', '').lower()}.md"
    body = "\n".join([
        "## Summary",
        f"Sagwan self-improvement proposal blocked by safety gate (risk={risk_level}).",
        "",
        "## Target",
        f"- target_path: `{target_path}`",
        f"- target_class: {target_class}",
        f"- section: `{section or '(full body replace)'}`",
        f"- full_body_replace: {full_body_replace}",
        "",
        "## Rationale",
        rationale.strip() or "(no rationale)",
        "",
        "## Proposed New Content",
        "```markdown",
        new_content.strip()[:MAX_DIFF_BYTES],
        "```",
        "",
        "## Reviewer Action",
        "- Review and either apply manually OR delete this request to dismiss.",
    ])
    try:
        write_document(
            path=req_path,
            body=body,
            title=f"Self-edit proposal: {target_path}",
            kind="improvement-request",
            project="ops/librarian",
            tags=["sagwan", "self-edit", target_class, f"risk-{risk_level}"],
            metadata={
                "status": "proposed",
                "owner": requested_by,
                "self_edit_target": target_path,
                "self_edit_class": target_class,
                "self_edit_section": section or "",
                "self_edit_risk": risk_level,
            },
            allow_owner_change=True,
        )
    except Exception as exc:
        logger.warning("self_edit: improvement-request write failed: %s", exc)
        return _reject(target_path, f"queue_write_failed: {exc}",
                       rationale=rationale, risk_level=risk_level)
    return {
        "status": "queued_for_review",
        "target_path": target_path,
        "target_class": target_class,
        "request_path": req_path,
        "risk_level": risk_level,
    }


def _append_rollback_entry(
    *,
    target_path: str,
    target_class: str,
    section: str | None,
    rationale: str,
    prior_body: str,
    requested_by: str,
) -> None:
    """Append a self-edit log entry that contains enough info to roll back
    (prior body fenced inline). Bounded so the log file doesn't explode."""
    ts = _now_iso()
    section_label = section or "(full body)"
    prior_excerpt = prior_body[:MAX_DIFF_BYTES]  # cap inline backup
    entry = "\n".join([
        f"- target_path: `{target_path}`",
        f"- target_class: {target_class}",
        f"- section: `{section_label}`",
        f"- requested_by: {requested_by}",
        f"- rationale: {rationale.strip()[:400]}",
        "",
        "<details><summary>prior body (rollback source)</summary>",
        "",
        "```markdown",
        prior_excerpt,
        "```",
        "</details>",
    ])
    # Ensure activity log exists, then append.
    try:
        load_document(ROLLBACK_LOG_PATH)
    except Exception:
        write_document(
            path=ROLLBACK_LOG_PATH,
            body="## Summary\nSagwan self-edit history (audit + rollback).\n",
            title="Sagwan Self-Edit History",
            kind="activity",
            project="ops/librarian",
            tags=["sagwan", "self-edit", "audit"],
            allow_owner_change=True,
        )
    append_section(ROLLBACK_LOG_PATH, f"{ts} self-edit", entry)


# ─── observability snapshot for admin endpoint ──────────────────────────────
def get_self_edit_snapshot(*, lookback_hours: int = 168) -> dict[str, Any]:
    recents = _recent_edits(hours=lookback_hours)
    by_class: dict[str, int] = {}
    for r in recents:
        c = r.get("target_class", "?")
        by_class[c] = by_class.get(c, 0) + 1
    return {
        "lookback_hours": lookback_hours,
        "total": len(recents),
        "by_class": by_class,
        "recent": recents[:20],
    }
