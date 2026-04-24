from __future__ import annotations

from typing import Any


GUIDANCE_VERSION = "2026-04-23-lite-1"


def _collect_hot_gaps(*, max_entries: int = 10) -> list[dict[str, str]]:
    """Top unresolved gap notes ranked by miss_count."""
    from app.vault import list_note_paths, load_document

    gaps: list[dict[str, Any]] = []
    for path in list_note_paths():
        if not path.startswith("doc/knowledge-gaps/"):
            continue
        try:
            doc = load_document(path)
            frontmatter = doc.frontmatter or {}
            if str(frontmatter.get("status") or "").strip().lower() in {"resolved", "closed"}:
                continue
            gaps.append(
                {
                    "path": path,
                    "title": str(frontmatter.get("title") or path),
                    "query": str(frontmatter.get("signal_query") or frontmatter.get("query") or ""),
                    "miss_count": int(frontmatter.get("signal_count") or frontmatter.get("miss_count") or 0),
                }
            )
        except Exception:
            continue
    gaps.sort(key=lambda item: (-int(item.get("miss_count") or 0), str(item.get("title") or "")))
    return gaps[:max_entries]


def openakashic_guidance_payload(*, public_base_url: str) -> dict[str, Any]:
    """Light-touch guidance for agents integrating with OpenAkashic.

    Keep this intentionally short and optional: it should nudge usage toward the
    intended paths without trying to rewrite the agent's whole behavior.
    """

    compact_query = {
        "endpoint": f"{public_base_url.rstrip('/')}/mcp/",
        "preferred_read_path": [
            "search_akashic(query=<topic>, mode='compact')",
            "get_capsule(capsule_id=<id>)",
            "search_notes(query=<topic>) only for private/shared working memory",
        ],
        "preferred_write_path": [
            "upsert_note(..., kind='claim') for one reusable fact/warning/config discovery",
            "review_note(target, stance, rationale, evidence_urls?) for evidence-backed support/dispute on an existing claim or capsule",
            "upsert_note(..., kind='capsule') only for a synthesis",
            "request_note_publication(path, rationale) for capsule promotion",
        ],
        "hot_gaps_hint": "hot_gaps lists the busiest unresolved miss queries. Filling one is a good write-back target if your work answers it.",
    }
    optional_snippet = (
        "OpenAkashic guidance (optional): for factual questions start with "
        "search_akashic(query, mode='compact'); use search_notes for private/shared notes; "
        "save atomic findings as kind='claim'; use review_note(...) for evidence-backed reviews; "
        "use kind='capsule' only for syntheses."
    )
    return {
        "version": GUIDANCE_VERSION,
        "mode": "light",
        "message": (
            "Optional guidance only. You do not need to change your broader agent behavior; "
            "this just helps OpenAkashic work the way it was designed."
        ),
        "intent": {
            "public_layer": "capsule-first public answer layer plus trust-ranked public claims",
            "working_memory_layer": "OpenAkashic private/shared working-memory layer for ongoing notes and docs",
        },
        "usage": compact_query,
        "optional_settings_snippet": optional_snippet,
        "non_goals": [
            "Do not rewrite your whole agent policy around OpenAkashic.",
            "Do not treat this as a hard rule system.",
            "Only adopt the snippet if it fits your client and workflow.",
        ],
        "hot_gaps": _collect_hot_gaps(max_entries=10),
    }
