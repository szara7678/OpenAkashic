#!/usr/bin/env python3
"""Parse sagwan maintenance log → editorial-feed.json for read.openakashic.com.

Source: closed-web/personal_vault/projects/ops/librarian/activity/maintenance-log.md
Output: apps/openakashic/web/read/editorial-feed.json (50 most recent entries)
Restriction: only entries targeting librarian capsules (public-relevant editorial work).
Run via cron (e.g., hourly).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(
    "/home/insu/insu_server/apps/openakashic/closed-web/personal_vault/"
    "projects/ops/librarian/activity/maintenance-log.md"
)
OUT_PATH = Path("/home/insu/insu_server/apps/openakashic/web/read/editorial-feed.json")
MAX_ENTRIES = 50
TARGET_PREFIX = "personal_vault/projects/ops/librarian/capsules/"

# secret patterns (mirrors sagwan v9 privacy guard intent — defense in depth)
SECRET_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{30,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}", re.IGNORECASE),
    re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
]

ENTRY_HEADER = re.compile(r"^## (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+(\w+)\s*$", re.M)


def parse_entries(text: str) -> list[dict]:
    matches = list(ENTRY_HEADER.finditer(text))
    out: list[dict] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        entry: dict[str, str] = {"timestamp": m.group(1), "stage": m.group(2)}
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            kv = line[2:].split(":", 1)
            if len(kv) != 2:
                continue
            entry[kv[0].strip()] = kv[1].strip()
        out.append(entry)
    return out


def has_secret(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS)


def sanitize(entry: dict) -> dict:
    cleaned: dict[str, str | None] = {
        "timestamp": entry.get("timestamp"),
        "stage": entry.get("stage", "maintenance"),
        "target": entry.get("target", ""),
        "verdict": entry.get("verdict", ""),
        "merge_into": entry.get("merge_into") if entry.get("merge_into") not in (None, "-") else None,
        "new_title": entry.get("new_title") if entry.get("new_title") not in (None, "-") else None,
    }
    rationale = entry.get("rationale", "")
    if rationale:
        if has_secret(rationale):
            rationale = "[redacted — secret pattern detected]"
        else:
            # truncate, preserve readable portion
            if len(rationale) > 600:
                rationale = rationale[:600].rstrip() + "…"
    cleaned["rationale"] = rationale or None

    target = cleaned.get("target") or ""
    if target.startswith(TARGET_PREFIX):
        cleaned["target_path"] = target
        cleaned["target_name"] = (
            target[len(TARGET_PREFIX):].rsplit("/", 1)[-1].replace(".md", "")
        )
    return cleaned


def main() -> int:
    text = LOG_PATH.read_text(encoding="utf-8")
    entries = parse_entries(text)
    # only entries targeting librarian capsules (public-editorial scope)
    entries = [e for e in entries if (e.get("target") or "").startswith(TARGET_PREFIX)]
    # newest first
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    entries = entries[:MAX_ENTRIES]
    entries = [sanitize(e) for e in entries]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "sagwan maintenance-log",
        "entry_count": len(entries),
        "entries": entries,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build_feed] wrote {len(entries)} entries → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
