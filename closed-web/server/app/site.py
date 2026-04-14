from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import markdown

from app.config import get_settings
from app.semantic_search import SemanticDocument, semantic_rank
from app.vault import file_href, kind_catalog, kind_template_sections, list_note_paths, normalize_kind


WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]")
EMBED_LINK_PATTERN = re.compile(r"!\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]")
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


@dataclass
class ClosedNote:
    path: str
    slug: str
    title: str
    kind: str
    project: str
    status: str
    owner: str
    visibility: str
    publication_status: str
    tags: list[str]
    related: list[str]
    summary: str
    body: str
    links: list[str]


def _viewer_can_open_note(note: ClosedNote, viewer_owner: str | None, is_admin: bool) -> bool:
    if note.visibility == "public":
        return True
    if is_admin:
        return True
    owner = (viewer_owner or "").strip()
    return bool(owner and note.owner == owner)


def _filter_notes_for_viewer(
    notes: list[ClosedNote],
    *,
    viewer_owner: str | None = None,
    is_admin: bool = False,
) -> list[ClosedNote]:
    if is_admin:
        return notes
    return [note for note in notes if _viewer_can_open_note(note, viewer_owner, is_admin)]


def get_closed_graph(
    *,
    viewer_owner: str | None = None,
    is_admin: bool = False,
) -> dict[str, Any]:
    notes = _load_notes()
    by_title = {note.title.lower(): note for note in notes}
    by_slug = {note.slug.lower(): note for note in notes}
    inbound_count = {note.slug: 0 for note in notes}
    outbound_count = {note.slug: len(note.links) + len(note.related) for note in notes}
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for note in notes:
        for target_name in [*note.links, *note.related]:
            target = by_title.get(target_name.lower()) or by_slug.get(_slugify(target_name).lower())
            if not target or target.slug == note.slug:
                continue
            edge = (note.slug, target.slug)
            if edge in seen:
                continue
            seen.add(edge)
            inbound_count[target.slug] += 1
            edges.append({"source": note.slug, "target": target.slug, "type": "wiki"})

    nodes = []
    for note in notes:
        degree = inbound_count[note.slug] + outbound_count[note.slug]
        nodes.append(
            {
                "id": note.slug,
                "slug": note.slug,
                "path": note.path,
                "title": note.title,
                "kind": note.kind,
                "project": note.project,
                "status": note.status,
                "owner": note.owner,
                "visibility": note.visibility,
                "publication_status": note.publication_status,
                "tags": note.tags,
                "summary": note.summary,
                "inbound": inbound_count[note.slug],
                "outbound": outbound_count[note.slug],
                "degree": degree,
                "size": len(note.body),
                "can_open": _viewer_can_open_note(note, viewer_owner, is_admin),
                "can_write": bool(
                    is_admin or (note.visibility != "public" and viewer_owner and note.owner == viewer_owner)
                ),
            }
        )

    return {
        "nodes": sorted(nodes, key=lambda item: (-item["degree"], item["title"])),
        "links": edges,
        "meta": {
            "vault": "openakashic",
            "note_count": len(nodes),
            "link_count": len(edges),
            "source": get_settings().closed_akashic_path,
        },
    }


def get_closed_note(path: str, route_prefix: str = "") -> dict[str, Any] | None:
    safe_path = Path(path)
    if safe_path.is_absolute() or ".." in safe_path.parts:
        return None
    root = Path(get_settings().closed_akashic_path).resolve()
    target = (root / safe_path).resolve()
    if root not in target.parents and target != root:
        return None
    if not target.exists() or target.suffix.lower() != ".md":
        return None
    notes = _load_notes()
    note = next((item for item in notes if item.path == target.relative_to(root).as_posix()), None)
    if not note:
        return None
    return _note_payload(note, notes, route_prefix)


def get_closed_note_by_slug(slug: str, route_prefix: str = "") -> dict[str, Any] | None:
    notes = _load_notes()
    note = next((item for item in notes if item.slug == slug), None)
    if not note:
        return None
    return _note_payload(note, notes, route_prefix)


def get_closed_home_note(
    route_prefix: str = "",
    *,
    viewer_owner: str | None = None,
    is_admin: bool = False,
) -> dict[str, Any]:
    notes = _load_notes()
    visible_notes = _filter_notes_for_viewer(notes, viewer_owner=viewer_owner, is_admin=is_admin)
    candidates = visible_notes
    home = next((note for note in candidates if note.path.lower() == "readme.md"), None)
    note = home or (candidates[0] if candidates else _empty_note())
    return _note_payload(note, candidates, route_prefix)


def search_closed_notes(query: str, limit: int = 12, route_prefix: str = "") -> dict[str, Any]:
    q = query.strip().lower()
    notes = _load_notes()
    matches_by_slug: dict[str, dict[str, Any]] = {}
    semantic_scores = {
        key: score
        for key, score in semantic_rank(
            query,
            [
                SemanticDocument(
                    key=note.slug,
                    path=note.path,
                    title=note.title,
                    kind=note.kind,
                    project=note.project,
                    status=note.status,
                    summary=note.summary,
                    body=note.body,
                )
                for note in notes
            ],
            limit=max(limit * 3, limit),
        )
    }
    for note in notes:
        haystack = " ".join(
            [
                note.title,
                note.summary,
                note.kind,
                note.project,
                note.path,
                note.owner,
                " ".join(note.tags),
                note.body,
            ]
        ).lower()
        lexical_hit = bool(q and q in haystack)
        semantic_score = semantic_scores.get(note.slug, 0.0)
        if not lexical_hit and semantic_score <= 0:
            continue
        title_hit = 4 if q and q in note.title.lower() else 0
        path_hit = 3 if q and q in note.path.lower() else 0
        tag_hit = 2 if q and any(q in tag.lower() for tag in note.tags) else 0
        lexical_score = title_hit + path_hit + tag_hit + (haystack.count(q) if q else 0)
        score = float(lexical_score) + semantic_score * 6.0
        matches_by_slug[note.slug] = {
            "path": note.path,
            "slug": note.slug,
            "title": note.title,
            "kind": note.kind,
            "project": note.project,
            "owner": note.owner,
            "visibility": note.visibility,
            "publication_status": note.publication_status,
            "tags": note.tags,
            "summary": note.summary,
            "href": _note_href(note.slug, route_prefix),
            "score": score,
            "semantic_score": round(semantic_score, 4),
        }
    return {
        "query": query,
        "results": sorted(matches_by_slug.values(), key=lambda item: (-item["score"], item["title"]))[:limit],
        "meta": {
            "retrieval": "lexical+semantic",
            "semantic_model": get_settings().embedding_model,
            "semantic_provider": get_settings().embedding_provider,
        },
    }


def closed_note_html(
    note_slug: str | None = None,
    route_prefix: str = "",
    *,
    viewer_owner: str | None = None,
    is_admin: bool = False,
) -> str:
    notes = _load_notes()
    visible_notes = _filter_notes_for_viewer(notes, viewer_owner=viewer_owner, is_admin=is_admin)
    route_prefix = _normalize_prefix(route_prefix)
    note = next((item for item in notes if item.slug == note_slug), None) if note_slug else None
    home_candidates = visible_notes
    note = note or next((item for item in home_candidates if item.path.lower() == "readme.md"), None)
    note = note or (home_candidates[0] if home_candidates else _empty_note())
    payload = _note_payload(note, visible_notes or [note], route_prefix)
    note_links = _explorer_html(visible_notes, note.slug, route_prefix)
    path_breadcrumb = _path_breadcrumb_html(payload["path"])
    shared_styles = _shared_ui_styles()
    shared_header = _shared_header_html(route_prefix, payload["title"], note_actions=True)
    shared_shell = _shared_ui_shell(route_prefix)
    workspace_styles = _workspace_styles()
    workspace_overlay = _workspace_overlay_html()
    workspace_script = _workspace_script()

    related_html = _link_list_html(payload["related_notes"], "연결된 노트", route_prefix)
    backlinks_html = _link_list_html(payload["backlinks"], "백링크", route_prefix)
    tag_html = "".join(f'<span class="tag">#{html.escape(tag)}</span>' for tag in payload["tags"])
    note_json = _json_script_text(payload)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="icon" href="data:," />
  <title>{html.escape(payload["title"])} | OpenAkashic</title>
  <style>
    :root {{
      --bg: #f4f7fb;
      --surface: rgba(255, 255, 255, 0.88);
      --surface-strong: #ffffff;
      --panel: #eef3f9;
      --line: #d7e2ef;
      --line-strong: #c5d3e5;
      --ink: #172033;
      --muted: #5d6b82;
      --accent: #2563eb;
      --accent-2: #0f766e;
      --code: #0f172a;
      --code-ink: #e5edf8;
      --shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
      --closed-sidebar-width: 340px;
    }}
    * {{ box-sizing: border-box; }}
    * {{
      scrollbar-width: thin;
      scrollbar-color: rgba(148, 163, 184, .72) transparent;
    }}
    *::-webkit-scrollbar {{ width: 10px; height: 10px; }}
    *::-webkit-scrollbar-thumb {{
      background: rgba(148, 163, 184, .68);
      border-radius: 999px;
      border: 2px solid transparent;
      background-clip: padding-box;
    }}
    *::-webkit-scrollbar-track {{ background: transparent; }}
    html, body {{ margin: 0; min-height: 100%; background:
      radial-gradient(circle at top left, rgba(37, 99, 235, 0.08), transparent 26%),
      radial-gradient(circle at top right, rgba(15, 118, 110, 0.07), transparent 22%),
      var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .layout {{
      display: grid;
      grid-template-columns: var(--closed-sidebar-width) minmax(0, 1fr);
      min-height: 100svh;
      transition: grid-template-columns .22s ease;
    }}
    body.left-collapsed .layout {{ grid-template-columns: 0 minmax(0, 1fr); }}
    .sidebar-edge-toggle {{
      position: fixed;
      top: calc(var(--closed-header-height) + 18px);
      left: calc(var(--closed-sidebar-width) - 18px);
      z-index: 60;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.96);
      color: var(--muted);
      box-shadow: 0 10px 24px rgba(15, 23, 42, .08);
      cursor: pointer;
      transition: left .22s ease, transform .18s ease, background .18s ease, border-color .18s ease;
    }}
    body.left-collapsed .sidebar-edge-toggle {{
      left: 10px;
      transform: rotate(180deg);
    }}
    .sidebar-edge-toggle:hover {{
      background: rgba(255,255,255,.99);
      border-color: var(--line-strong);
      color: var(--ink);
    }}
    .sidebar {{
      position: sticky;
      top: var(--closed-header-height);
      align-self: start;
      height: calc(100svh - var(--closed-header-height));
      overflow: auto;
      padding: 28px 24px;
      backdrop-filter: blur(14px);
      background: rgba(248, 250, 252, 0.82);
      transition: opacity .2s ease, padding .2s ease, border-color .2s ease, transform .2s ease;
    }}
    .sidebar {{ border-right: 1px solid var(--line); padding-right: 28px; }}
    body.left-collapsed .sidebar {{
      opacity: 0;
      pointer-events: none;
      overflow: hidden;
      padding-left: 0;
      padding-right: 0;
      border-right-color: transparent;
    }}
    .sidebar-resizer {{
      position: absolute;
      top: 0;
      right: 0;
      z-index: 30;
      width: 12px;
      height: 100%;
      cursor: col-resize;
      touch-action: none;
    }}
    .sidebar-resizer::after {{
      content: "";
      position: absolute;
      top: 22px;
      bottom: 22px;
      left: 5px;
      width: 2px;
      border-radius: 999px;
      background: transparent;
      transition: background .18s ease, box-shadow .18s ease;
    }}
    .sidebar-resizer:hover::after,
    .sidebar-resizer.active::after {{
      background: rgba(37, 99, 235, .34);
      box-shadow: 0 0 0 4px rgba(37, 99, 235, .08);
    }}
    body.sidebar-resizing {{
      cursor: col-resize;
      user-select: none;
    }}
    body.left-collapsed .sidebar-resizer {{ display: none; }}
    .content {{ min-width: 0; padding: 0 clamp(18px, 4vw, 48px) 56px; }}
    .page-actions {{
      position: sticky;
      top: calc(var(--closed-header-height) + 10px);
      z-index: 42;
      display: flex;
      justify-content: flex-end;
      margin: 0 0 18px;
      pointer-events: none;
    }}
    .page-actions-row {{
      display: inline-flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 8px;
      border-radius: 10px;
      border: 1px solid rgba(215, 226, 239, .82);
      background: rgba(248, 250, 252, .92);
      backdrop-filter: blur(14px);
      box-shadow: 0 12px 28px rgba(15, 23, 42, .08);
      pointer-events: auto;
    }}
    .appbar {{
      position: sticky;
      top: 0;
      z-index: 45;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 58px;
      margin: 0 calc(clamp(18px, 4vw, 48px) * -1) 22px;
      padding: 10px clamp(18px, 4vw, 48px);
      border-bottom: 1px solid rgba(215, 226, 239, .76);
      background: rgba(248, 250, 252, .82);
      backdrop-filter: blur(16px);
    }}
    .appbar-group, .appbar-tabs {{
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      flex-wrap: wrap;
    }}
    .top-button, .top-tab, .meta-tab, .side-tab {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0 10px;
      border-radius: 8px;
      border: 1px solid transparent;
      background: transparent;
      color: var(--muted);
      font: inherit;
      font-size: .83rem;
      font-weight: 700;
      cursor: pointer;
      transition: background .16s ease, border-color .16s ease, color .16s ease;
    }}
    .top-button:hover, .top-tab:hover, .meta-tab:hover, .side-tab:hover {{
      background: rgba(255,255,255,.86);
      border-color: var(--line);
      color: var(--ink);
      text-decoration: none;
    }}
    .top-button[aria-pressed="true"], .top-tab.active, .meta-tab.active, .side-tab.active {{
      background: rgba(37, 99, 235, .08);
      border-color: rgba(37, 99, 235, .18);
      color: var(--accent);
    }}
    .appbar-title {{ min-width: 0; color: var(--ink); font-size: .9rem; font-weight: 760; }}
    .sidebar-tabs {{
      position: sticky;
      top: -28px;
      z-index: 25;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 6px;
      margin: 18px -24px 18px;
      padding: 12px 24px;
      border-top: 1px solid rgba(215, 226, 239, .72);
      border-bottom: 1px solid rgba(215, 226, 239, .72);
      background: rgba(248, 250, 252, .92);
      backdrop-filter: blur(14px);
    }}
    .side-tab {{ min-width: 0; padding: 0 6px; font-size: .76rem; }}
    .sidebar-panel {{ display: none; }}
    .sidebar[data-active-panel="explore"] .sidebar-panel[data-sidebar-panel="explore"],
    .sidebar[data-active-panel="info"] .sidebar-panel[data-sidebar-panel="info"],
    .sidebar[data-active-panel="relations"] .sidebar-panel[data-sidebar-panel="relations"],
    .sidebar[data-active-panel="edit"] .sidebar-panel[data-sidebar-panel="edit"] {{
      display: block;
    }}
    .brand-wrap {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 18px; }}
    .brand {{ margin: 0; font-size: 1.85rem; line-height: 1.05; font-weight: 780; letter-spacing: 0; }}
    .brand-kicker {{ margin: 0 0 6px; color: var(--accent-2); font-size: 0.76rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }}
    .sub {{ margin: 0; color: var(--muted); font-size: 0.94rem; line-height: 1.6; }}
    .quicklinks {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 18px 0 16px; }}
    .chip-link {{
      display: inline-flex; align-items: center; height: 34px; padding: 0 12px;
      border-radius: 8px; background: rgba(255,255,255,.9); border: 1px solid var(--line);
      color: var(--ink); font-size: 0.82rem; font-weight: 600;
    }}
    .search-wrap {{ position: relative; margin-bottom: 18px; }}
    .search {{
      width: 100%; height: 42px; border-radius: 8px; border: 1px solid var(--line);
      background: rgba(255,255,255,.96); color: var(--ink); padding: 0 14px; font: inherit;
      outline: none; transition: border-color .2s ease, box-shadow .2s ease;
    }}
    .search:focus {{ border-color: rgba(37, 99, 235, .42); box-shadow: 0 0 0 4px rgba(37, 99, 235, .08); }}
    .search-results {{
      position: absolute; top: calc(100% + 8px); left: 0; right: 0; z-index: 20;
      display: none; padding: 8px; border-radius: 8px; background: var(--surface-strong);
      border: 1px solid var(--line); box-shadow: var(--shadow);
    }}
    .search-results.visible {{ display: block; }}
    .search-result {{
      display: block; padding: 10px 12px; border-radius: 8px; color: var(--ink);
    }}
    .search-result:hover {{ background: var(--panel); text-decoration: none; }}
    .search-result small {{ display: block; margin-top: 4px; color: var(--muted); }}
    .section-label {{
      margin: 18px 0 10px; color: var(--muted); font-size: 0.72rem; font-weight: 800;
      letter-spacing: .08em; text-transform: uppercase;
    }}
    .nav {{ display: flex; flex-direction: column; gap: 6px; padding-right: 2px; }}
    .folder-group {{
      margin-left: calc(var(--depth, 0) * 2px);
      border: 1px solid rgba(215, 226, 239, .66);
      border-radius: 8px;
      background: rgba(255,255,255,.46);
      overflow: visible;
    }}
    .folder-group + .folder-group {{ margin-top: 8px; }}
    .folder-summary {{
      list-style: none;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 12px;
      min-width: 0;
      cursor: pointer;
      color: var(--ink);
      font-size: 0.84rem;
      font-weight: 700;
      letter-spacing: 0;
      background: rgba(255,255,255,.68);
    }}
    .folder-summary span:last-child {{ min-width: 0; overflow-wrap: anywhere; }}
    .folder-summary::-webkit-details-marker {{ display: none; }}
    .folder-caret {{
      display: inline-flex;
      flex: 0 0 12px;
      width: 12px;
      justify-content: center;
      color: var(--muted);
      transition: transform .16s ease;
    }}
    .folder-group[open] > .folder-summary .folder-caret {{ transform: rotate(90deg); }}
    .folder-children {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-left: 14px;
      padding: 6px 6px 8px 10px;
      border-left: 1px solid rgba(197, 211, 229, .66);
    }}
    .nav-link {{
      display: block; padding: 10px 12px; border-radius: 8px; color: var(--ink);
      border: 1px solid transparent; transition: background .18s ease, border-color .18s ease, transform .18s ease;
      min-width: 0;
    }}
    .nav-link:hover {{ background: rgba(255,255,255,.75); text-decoration: none; transform: translateX(2px); }}
    .nav-link.active {{
      background: rgba(37, 99, 235, .08);
      border-color: rgba(37, 99, 235, .2);
      box-shadow: inset 3px 0 0 rgba(37, 99, 235, .85);
    }}
    .nav-link.path-highlight,
    .folder-group.path-highlight > .folder-summary {{
      background: rgba(15, 118, 110, .11);
      border-color: rgba(15, 118, 110, .28);
      box-shadow: inset 3px 0 0 rgba(15, 118, 110, .88), 0 8px 18px rgba(15, 23, 42, .06);
    }}
    .folder-group.path-highlight > .folder-summary {{
      color: var(--accent-2);
    }}
    .nav-link span {{ display: block; min-width: 0; overflow-wrap: anywhere; line-height: 1.34; }}
    .nav-link small {{ display:block; color: var(--muted); font-size: 0.72rem; margin-top: 4px; overflow-wrap: anywhere; line-height: 1.35; }}
    .note-shell {{ max-width: 820px; margin: 0 auto; }}
    .note-top {{
      display: grid; gap: 22px; margin-bottom: 26px; padding-bottom: 22px;
      border-bottom: 1px solid var(--line);
    }}
    .path {{
      display: inline-flex; align-items: center; flex-wrap: wrap; gap: 4px; width: fit-content; max-width: 100%;
      min-height: 30px; padding: 3px 8px; border-radius: 8px; background: rgba(255,255,255,.92);
      border: 1px solid var(--line); color: var(--muted); font-size: 0.78rem;
    }}
    .path-segment {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      max-width: 100%;
      padding: 0 6px;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--muted);
      font: inherit;
      cursor: pointer;
      overflow-wrap: anywhere;
      text-align: left;
    }}
    .path-segment:hover {{
      background: rgba(37, 99, 235, .08);
      color: var(--accent);
    }}
    .path-segment[data-kind="file"] {{
      color: var(--ink);
      font-weight: 700;
    }}
    .path-separator {{
      color: rgba(93, 107, 130, .58);
      user-select: none;
    }}
    .title {{ margin: 0; font-size: clamp(2.25rem, 4vw, 3.6rem); line-height: .98; font-weight: 800; letter-spacing: 0; }}
    .summary {{ margin: 0; max-width: 62ch; color: var(--muted); font-size: 1.02rem; line-height: 1.72; }}
    .article-wrap {{ padding: 0; }}
    .read-view {{ display: block; }}
    .edit-view {{ display: none; }}
    body.inline-editing .read-view {{ display: none; }}
    body.inline-editing .edit-view {{ display: block; }}
    .editable-read {{
      border-radius: 8px;
      cursor: text;
      transition: background .16s ease, box-shadow .16s ease;
    }}
    .editable-read:hover {{
      background: rgba(37, 99, 235, .04);
      box-shadow: 0 0 0 8px rgba(37, 99, 235, .04);
    }}
    .inline-editor {{
      display: grid;
      gap: 14px;
    }}
    .editor-title-input, .editor-summary-input, .editor-body-input {{
      width: 100%;
      border: 0;
      outline: none;
      background: transparent;
      color: var(--ink);
      font: inherit;
    }}
    .editor-title-input {{
      min-height: 1.2em;
      font-size: clamp(2.25rem, 4vw, 3.6rem);
      line-height: 1.02;
      font-weight: 800;
      letter-spacing: 0;
      resize: none;
    }}
    .editor-summary-input {{
      min-height: 82px;
      max-width: 62ch;
      color: var(--muted);
      font-size: 1.02rem;
      line-height: 1.72;
      resize: vertical;
    }}
    .editor-body-input {{
      min-height: min(60svh, 720px);
      padding: 18px 0 40px;
      color: var(--ink);
      line-height: 1.72;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: .96rem;
    }}
    .inline-toolbar {{
      position: sticky;
      top: 58px;
      z-index: 35;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      padding: 10px 0;
      border-bottom: 1px solid rgba(215, 226, 239, .76);
      background: rgba(244, 247, 251, .88);
      backdrop-filter: blur(14px);
    }}
    .inline-hint {{
      color: var(--muted);
      font-size: .82rem;
      line-height: 1.45;
    }}
    .markdown {{ line-height: 1.82; font-size: 1rem; color: var(--ink); }}
    .markdown * {{ max-width: 100%; }}
    .markdown h1, .markdown h2, .markdown h3, .markdown h4 {{ letter-spacing: 0; color: #0f172a; }}
    .markdown h2 {{ margin-top: 2.4rem; margin-bottom: .8rem; font-size: 1.7rem; }}
    .markdown h3 {{ margin-top: 2rem; margin-bottom: .7rem; font-size: 1.28rem; }}
    .markdown h4 {{ margin-top: 1.7rem; margin-bottom: .55rem; font-size: 1.05rem; }}
    .markdown p {{ margin: 0 0 1rem; overflow-wrap: anywhere; }}
    .markdown ul, .markdown ol {{ margin: 0 0 1rem 1.3rem; padding: 0; }}
    .markdown li {{ margin-bottom: .55rem; }}
    .markdown blockquote {{
      margin: 1rem 0; padding: .2rem 0 .2rem 1rem; border-left: 3px solid rgba(15, 118, 110, .35);
      color: var(--muted);
    }}
    .markdown a {{
      color: var(--accent); text-decoration-thickness: .08em; text-underline-offset: .16em;
    }}
    .markdown code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      background: rgba(15, 23, 42, .06); border-radius: 6px; padding: 2px 6px; font-size: .92em;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .markdown pre {{
      overflow: auto; padding: 16px 18px; background: var(--code); color: var(--code-ink);
      border-radius: 8px; border: 1px solid rgba(15, 23, 42, .16);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .markdown pre code {{ border: 0; padding: 0; background: transparent; color: inherit; }}
    .markdown hr {{ border: 0; border-top: 1px solid var(--line); margin: 2rem 0; }}
    .markdown table {{ display: block; width: 100%; overflow-x: auto; border-collapse: collapse; margin: 1.2rem 0; font-size: .95rem; }}
    .markdown th, .markdown td {{ padding: .72rem .8rem; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    .markdown img, .markdown .note-image {{
      display: block; max-width: 100%; height: auto; margin: 1rem 0; border-radius: 8px;
      border: 1px solid var(--line); box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
      background: white;
    }}
    .meta-section + .meta-section {{ margin-top: 28px; }}
    .meta-header {{
      position: sticky;
      top: -28px;
      z-index: 3;
      display: grid;
      gap: 10px;
      margin: -28px -24px 20px;
      padding: 18px 24px 14px;
      border-bottom: 1px solid rgba(215, 226, 239, .78);
      background: rgba(248, 250, 252, .90);
      backdrop-filter: blur(14px);
    }}
    .meta-tabs {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .meta[data-active-panel="info"] .meta-section[data-meta-panel]:not([data-meta-panel="info"]),
    .meta[data-active-panel="links"] .meta-section[data-meta-panel]:not([data-meta-panel="links"]),
    .meta[data-active-panel="edit"] .meta-section[data-meta-panel]:not([data-meta-panel="edit"]) {{
      display: none;
    }}
    .meta-title {{ margin: 0 0 12px; color: var(--muted); font-size: 0.72rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    .meta-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    .metric {{ padding: 12px; border-radius: 8px; background: rgba(255,255,255,.85); border: 1px solid var(--line); }}
    .meta-label {{ color: var(--muted); font-size: 0.72rem; margin-bottom: 6px; }}
    .meta-value {{ font-size: 0.98rem; font-weight: 700; overflow-wrap: anywhere; word-break: break-word; }}
    .tag-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .tag {{
      display: inline-flex; align-items: center; height: 30px; padding: 0 10px; border-radius: 999px;
      background: rgba(15, 118, 110, .08); border: 1px solid rgba(15, 118, 110, .18); color: var(--accent-2); font-size: .77rem; font-weight: 600;
    }}
    .note-list {{ display: flex; flex-direction: column; gap: 8px; }}
    .note-card {{
      display: block; padding: 12px; border-radius: 8px; color: var(--ink); background: rgba(255,255,255,.86);
      border: 1px solid var(--line); transition: transform .18s ease, border-color .18s ease, background .18s ease;
    }}
    .note-card:hover {{ text-decoration: none; transform: translateY(-1px); border-color: var(--line-strong); background: var(--surface-strong); }}
    .note-card strong {{ display: block; line-height: 1.35; overflow-wrap: anywhere; }}
    .note-card small {{ display: block; margin-top: 6px; color: var(--muted); line-height: 1.55; overflow-wrap: anywhere; }}
    .missing-link {{ color: #b91c1c; font-weight: 600; }}
    .meta-copy {{ color: var(--muted); font-size: .92rem; line-height: 1.65; }}
    @media (max-width: 1180px) {{
      .layout {{ grid-template-columns: var(--closed-sidebar-width) minmax(0, 1fr); }}
      body.left-collapsed .layout {{ grid-template-columns: minmax(0, 1fr); }}
      body.left-collapsed .sidebar {{ display: none; }}
    }}
    @media (max-width: 820px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .sidebar {{ position: static; height: auto; border: 0; border-bottom: 1px solid var(--line); }}
      .sidebar {{ padding-right: 24px; }}
      .sidebar-resizer {{ display: none; }}
      body.left-collapsed .sidebar {{ display: none; }}
      .sidebar-edge-toggle {{ top: calc(var(--closed-header-height) + 10px); left: 10px; }}
      .content {{ padding-top: 0; }}
      .appbar {{
        margin-left: -14px;
        margin-right: -14px;
        padding-left: 14px;
        padding-right: 14px;
        align-items: flex-start;
      }}
      .appbar-title {{ max-width: 100%; order: 3; flex-basis: 100%; }}
      .article-wrap {{ padding: 22px 18px; }}
    }}
    {shared_styles}
    {workspace_styles}
  </style>
</head>
<body class="closed-with-header">
  {shared_header}
  <button class="sidebar-edge-toggle" id="toggle-left-sidebar" type="button" aria-label="Toggle Sidebar" title="Toggle Sidebar">❮</button>
  <div class="layout">
    <aside class="sidebar" id="workspace-sidebar" data-active-panel="explore">
      <div class="brand-wrap">
        <div>
          <p class="brand-kicker">OpenAkashic</p>
          <h1 class="brand">Living Notes</h1>
        </div>
      </div>
      <p class="sub">링크된 노트를 따라 기억을 쌓고 다시 꺼내 쓰는 개인 지식 창고.</p>
      <div class="sidebar-tabs" role="tablist" aria-label="Workspace sidebar">
        <button class="side-tab active" type="button" data-sidebar-tab="explore">Explore</button>
        <button class="side-tab" type="button" data-sidebar-tab="info">Info</button>
        <button class="side-tab" type="button" data-sidebar-tab="relations">Relations</button>
        <button class="side-tab" type="button" data-sidebar-tab="edit" data-note-write-control hidden>Edit</button>
      </div>
      <section class="sidebar-panel" data-sidebar-panel="explore">
        <div class="search-wrap">
          <input class="search" id="note-filter" placeholder="노트 제목이나 태그 검색" />
          <div class="search-results" id="search-results"></div>
        </div>
        <div class="section-label">Explorer</div>
        <nav class="nav" id="note-nav">
          {note_links or '<p class="meta-copy">지금 열 수 있는 문서가 아직 없다.</p>'}
        </nav>
      </section>
      <section class="sidebar-panel" data-sidebar-panel="info">
        <section class="meta-section">
          <h3 class="meta-title">Note</h3>
          <div class="meta-grid">
            <div class="metric"><div class="meta-label">Kind</div><div class="meta-value">{html.escape(payload["kind"])}</div></div>
            <div class="metric"><div class="meta-label">Project</div><div class="meta-value">{html.escape(payload["project"])}</div></div>
            <div class="metric"><div class="meta-label">Status</div><div class="meta-value">{html.escape(payload["status"])}</div></div>
            <div class="metric"><div class="meta-label">Owner</div><div class="meta-value">{html.escape(payload["owner"])}</div></div>
            <div class="metric"><div class="meta-label">Visibility</div><div class="meta-value">{html.escape(payload["visibility"])}</div></div>
            <div class="metric"><div class="meta-label">Publication</div><div class="meta-value">{html.escape(payload["publication_status"])}</div></div>
          </div>
        </section>
        <section class="meta-section">
          <h3 class="meta-title">Tags</h3>
          <div class="tag-row">{tag_html or '<span class="tag">#untagged</span>'}</div>
        </section>
        <section class="meta-section">
          <h3 class="meta-title">Reuse</h3>
          <p class="meta-copy">맞는 컨테이너면 덧붙이고, 아니면 작은 노트로 나눠 링크를 보강한다.</p>
        </section>
      </section>
      <section class="sidebar-panel" data-sidebar-panel="relations">
        <section class="meta-section">
          <h3 class="meta-title">Relations</h3>
          <p class="meta-copy">관련 페이지는 Edit 탭의 Related 필드에 제목을 넣어 연결한다.</p>
          <div class="toolbar-row" style="margin-top:12px;">
            <button class="action-button" id="edit-relations" type="button" data-note-write-control hidden>Edit Related</button>
          </div>
        </section>
        {related_html}
        {backlinks_html}
      </section>
      <section class="sidebar-panel" data-sidebar-panel="edit" data-note-write-control hidden>
        <section class="meta-section">
          <h3 class="meta-title">Page Settings</h3>
          <div class="workspace-grid">
            <label class="field">
              <span class="field-label">Kind</span>
              <input class="field-input" id="editor-kind" list="editor-kind-options" placeholder="playbook" />
            </label>
            <label class="field">
              <span class="field-label">Project</span>
              <input class="field-input" id="editor-project" placeholder="personal/openakashic" />
            </label>
            <label class="field">
              <span class="field-label">Status</span>
              <input class="field-input" id="editor-status" list="editor-status-options" placeholder="active" />
            </label>
            <label class="field">
              <span class="field-label">Owner</span>
              <input class="field-input" id="editor-owner" placeholder="auto" disabled />
            </label>
            <label class="field">
              <span class="field-label">Visibility</span>
              <select class="field-select" id="editor-visibility">
                <option value="private">private</option>
                <option value="public">public</option>
              </select>
            </label>
            <label class="field">
              <span class="field-label">Publication</span>
              <select class="field-select" id="editor-publication-status">
                <option value="none">none</option>
                <option value="requested">requested</option>
                <option value="reviewing">reviewing</option>
                <option value="approved">approved</option>
                <option value="rejected">rejected</option>
                <option value="published">published</option>
              </select>
            </label>
            <label class="field">
              <span class="field-label">Folder Scope</span>
              <select class="field-select" id="editor-scope">
                <option value="personal">personal</option>
                <option value="shared">shared</option>
              </select>
            </label>
            <label class="field span-2">
              <span class="field-label">Folder Override</span>
              <input class="field-input" id="editor-folder" list="editor-folder-options" placeholder="personal_vault/shared/reference" />
            </label>
            <label class="field span-2">
              <span class="field-label">Path</span>
              <div class="toolbar-row">
                <input class="field-input" id="editor-path" placeholder="personal_vault/projects/personal/openakashic/reference/..." />
                <button class="action-button" id="editor-suggest" type="button">Suggest</button>
              </div>
            </label>
            <label class="field span-2">
              <span class="field-label">Tags</span>
              <input class="field-input" id="editor-tags" placeholder="agent, mcp, workflow" />
            </label>
            <label class="field span-2">
              <span class="field-label">Related</span>
              <input class="field-input" id="editor-related" placeholder="관련 노트 제목을 콤마로 구분" />
            </label>
          </div>
          <div class="workspace-card" style="margin-top:12px;">
            <div class="meta-title" style="margin:0;">Kind Guide</div>
            <div class="meta-copy" id="editor-kind-summary">kind를 고르면 권장 구조와 위치를 바로 보여준다.</div>
            <pre class="workspace-template" id="editor-kind-template">## Summary</pre>
          </div>
        </section>
        <section class="meta-section">
          <h3 class="meta-title">Folders</h3>
          <label class="field">
            <span class="field-label">Folder Path</span>
            <input class="field-input" id="workspace-folder-path" list="editor-folder-options" placeholder="personal_vault/projects/personal/example/reference" />
          </label>
          <div class="toolbar-row" style="margin-top:10px;">
            <button class="action-button" id="workspace-create-folder" type="button">Create Folder</button>
          </div>
        </section>
        <section class="meta-section">
          <h3 class="meta-title">Save</h3>
          <div class="toolbar-row">
            <button class="action-button" id="workspace-save" type="button">Save Changes</button>
          </div>
          <p class="meta-copy">본인 문서에서 Visibility를 `public`으로 두고 저장하면 원문은 private로 유지되고 publication 요청이 자동으로 올라간다.</p>
        </section>
      </section>
      <div class="sidebar-resizer" id="sidebar-resizer" role="separator" aria-orientation="vertical" aria-label="Resize sidebar" title="Drag to resize"></div>
    </aside>
    <main class="content">
      <div class="page-actions">
        <div class="page-actions-row">
          <button class="global-pill is-primary" id="global-edit-note" type="button" data-note-write-control data-edit-view="edit" hidden>Edit</button>
          <button class="global-pill is-primary" id="global-save-note" type="button" data-note-write-control data-edit-view="save" hidden>Save</button>
          <button class="global-pill" id="global-cancel-note" type="button" data-note-write-control data-edit-view="save" hidden>Cancel</button>
        </div>
      </div>
      <div class="note-shell">
        <header class="note-top read-view">
          <div class="path" aria-label="Note path">{path_breadcrumb}</div>
          <h2 class="title" id="read-title" data-edit-target="title">{html.escape(payload["title"])}</h2>
          <p class="summary" id="read-summary" data-edit-target="summary">{html.escape(payload["summary"] or "요약이 아직 없습니다.")}</p>
        </header>
        <header class="note-top edit-view">
          <div class="path" aria-label="Note path">{path_breadcrumb}</div>
          <textarea class="editor-title-input" id="editor-title" rows="1" placeholder="Untitled"></textarea>
          <textarea class="editor-summary-input" id="editor-summary" placeholder="요약을 적으면 Summary 섹션으로 저장된다."></textarea>
        </header>
        <section class="article-wrap">
          <article class="markdown read-view" id="read-content" data-edit-target="body">{payload["body_html"]}</article>
          <section class="inline-editor edit-view">
            <span class="inline-hint" id="workspace-banner">마크다운 원문을 수정한 뒤 우상단 Save로 저장한다.</span>
            <textarea class="editor-body-input" id="editor-body" placeholder="## Summary"></textarea>
            <div class="workspace-actions">
              <button class="action-button subtle" id="editor-delete" type="button">Delete Note</button>
            </div>
          </section>
        </section>
      </div>
    </main>
  </div>
  {shared_shell}
  {workspace_overlay}
  <script type="application/json" id="closed-note-data">{note_json}</script>
  <script>
    const noteMeta = JSON.parse(document.getElementById('closed-note-data')?.textContent || '{{}}');
    const input = document.getElementById('note-filter');
    const items = [...document.querySelectorAll('.nav-link')];
    const folders = [...document.querySelectorAll('.folder-group')];
    const searchBox = document.getElementById('search-results');
    const sidebarResizer = document.getElementById('sidebar-resizer');
    const pathSegments = [...document.querySelectorAll('.path-segment')];
    const sidebar = document.getElementById('workspace-sidebar');
    const leftToggle = document.getElementById('toggle-left-sidebar');
    const sideTabs = [...document.querySelectorAll('[data-sidebar-tab]')];
    const editRelations = document.getElementById('edit-relations');
    const searchEndpoint = '{html.escape(_search_href(route_prefix))}';
    const sidebarWidthKey = 'closed-akashic-sidebar-width';
    const leftCollapsedKey = 'closed-akashic-left-collapsed';
    const sidebarTabKey = 'closed-akashic-sidebar-tab';
    let searchTimer = null;

    function canWriteCurrentNote(session) {{
      if (!session?.authenticated) return false;
      if (session.role === 'admin') return true;
      return noteMeta.visibility !== 'public' && session.nickname === noteMeta.owner;
    }}

    function syncNoteWriteControls(session) {{
      const allowed = canWriteCurrentNote(session);
      window.closedAkashicUI?.setNoteWriteVisible?.(allowed);
      if (!allowed && sidebar?.getAttribute('data-active-panel') === 'edit') {{
        setSidebarTab('explore', {{ openSidebar: false }});
      }}
    }}

    function setLeftCollapsed(collapsed) {{
      document.body.classList.toggle('left-collapsed', collapsed);
      leftToggle?.setAttribute('aria-pressed', String(collapsed));
      window.localStorage.setItem(leftCollapsedKey, collapsed ? '1' : '0');
    }}

    function setSidebarTab(tab, options = {{}}) {{
      const next = ['explore', 'info', 'relations', 'edit'].includes(tab) ? tab : 'explore';
      sidebar?.setAttribute('data-active-panel', next);
      sideTabs.forEach((button) => button.classList.toggle('active', button.dataset.sidebarTab === next));
      window.localStorage.setItem(sidebarTabKey, next);
      if (options.openSidebar !== false) setLeftCollapsed(false);
    }}

    if (window.localStorage.getItem(leftCollapsedKey) === '1') setLeftCollapsed(true);
    setSidebarTab(window.localStorage.getItem(sidebarTabKey) || 'explore', {{ openSidebar: false }});

    function clampSidebarWidth(value) {{
      const viewport = window.innerWidth || 1280;
      const max = Math.max(320, Math.min(620, viewport - 640));
      return Math.min(max, Math.max(280, value));
    }}

    function applySidebarWidth(value) {{
      const next = clampSidebarWidth(value);
      document.documentElement.style.setProperty('--closed-sidebar-width', `${{next}}px`);
      return next;
    }}

    const savedSidebarWidth = Number(window.localStorage.getItem(sidebarWidthKey));
    if (Number.isFinite(savedSidebarWidth) && savedSidebarWidth > 0) {{
      applySidebarWidth(savedSidebarWidth);
    }}

    sidebarResizer?.addEventListener('pointerdown', (event) => {{
      if (window.matchMedia('(max-width: 820px)').matches) return;
      event.preventDefault();
      sidebarResizer.setPointerCapture(event.pointerId);
      sidebarResizer.classList.add('active');
      document.body.classList.add('sidebar-resizing');
    }});

    sidebarResizer?.addEventListener('pointermove', (event) => {{
      if (!sidebarResizer.classList.contains('active')) return;
      const width = applySidebarWidth(event.clientX);
      window.localStorage.setItem(sidebarWidthKey, String(width));
    }});

    function stopSidebarResize(event) {{
      if (!sidebarResizer?.classList.contains('active')) return;
      sidebarResizer.classList.remove('active');
      document.body.classList.remove('sidebar-resizing');
      if (event?.pointerId !== undefined) {{
        try {{ sidebarResizer.releasePointerCapture(event.pointerId); }} catch (error) {{}}
      }}
    }}

    sidebarResizer?.addEventListener('pointerup', stopSidebarResize);
    sidebarResizer?.addEventListener('pointercancel', stopSidebarResize);
    window.addEventListener('resize', () => {{
      const current = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--closed-sidebar-width'));
      if (Number.isFinite(current)) {{
        const width = applySidebarWidth(current);
        window.localStorage.setItem(sidebarWidthKey, String(width));
      }}
    }});

    leftToggle?.addEventListener('click', () => {{
      setLeftCollapsed(!document.body.classList.contains('left-collapsed'));
    }});

    editRelations?.addEventListener('click', () => {{
      setSidebarTab('edit');
      window.setTimeout(() => document.getElementById('editor-related')?.focus(), 120);
    }});
    sideTabs.forEach((button) => {{
      button.addEventListener('click', () => setSidebarTab(button.dataset.sidebarTab || 'explore'));
    }});

    function escapeSelectorValue(value) {{
      if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(value);
      return String(value).replace(/["\\\\]/g, '\\\\$&');
    }}

    function clearPathHighlights() {{
      document.querySelectorAll('.path-highlight').forEach((element) => element.classList.remove('path-highlight'));
    }}

    function revealExplorerPath(kind, path) {{
      const selector = kind === 'file'
        ? `.nav-link[data-path="${{escapeSelectorValue(path)}}"]`
        : `.folder-group[data-path="${{escapeSelectorValue(path)}}"]`;
      const target = document.querySelector(selector);
      if (!target) return;

      clearPathHighlights();
      let cursor = target.parentElement;
      while (cursor) {{
        if (cursor.matches?.('.folder-group')) cursor.open = true;
        cursor = cursor.parentElement;
      }}
      if (target.matches('.folder-group')) target.open = true;
      target.classList.add('path-highlight');
      target.scrollIntoView({{ block: 'center', inline: 'nearest', behavior: 'smooth' }});
      window.setTimeout(() => target.classList.remove('path-highlight'), 1800);
    }}

    pathSegments.forEach((segment) => {{
      segment.addEventListener('click', () => {{
        const path = segment.dataset.path || '';
        const kind = segment.dataset.kind || 'folder';
        if (path) revealExplorerPath(kind, path);
      }});
    }});

    input?.addEventListener('input', () => {{
      const q = input.value.trim().toLowerCase();
      for (const item of items) {{
        const hit = !q || item.dataset.title.includes(q);
        item.style.display = hit ? '' : 'none';
      }}
      for (const folder of folders) {{
        const descendants = [...folder.querySelectorAll('.nav-link')];
        const visible = descendants.some((item) => item.style.display !== 'none');
        folder.style.display = visible ? '' : 'none';
        if (q && visible) folder.open = true;
      }}

      window.clearTimeout(searchTimer);
      if (!q) {{
        searchBox?.classList.remove('visible');
        searchBox.innerHTML = '';
        return;
      }}

      searchTimer = window.setTimeout(async () => {{
        try {{
          const res = await fetch(`${{searchEndpoint}}?q=${{encodeURIComponent(q)}}&limit=6`);
          const data = await res.json();
          const results = (data.results || []).map((item) => `
            <a class="search-result" href="${{item.href}}">
              <strong>${{item.title}}</strong>
              <small>${{item.summary || item.path || ''}}</small>
            </a>
          `).join('');
          searchBox.innerHTML = results || '<div class="search-result"><strong>검색 결과 없음</strong></div>';
          searchBox.classList.add('visible');
        }} catch (error) {{
          searchBox.classList.remove('visible');
        }}
      }}, 160);
    }});

    document.addEventListener('click', (event) => {{
      if (!searchBox?.contains(event.target) && event.target !== input) {{
        searchBox?.classList.remove('visible');
      }}
    }});
    document.addEventListener('closed-akashic-auth-change', (event) => {{
      syncNoteWriteControls(event.detail || {{ authenticated: false, role: 'anonymous', nickname: '' }});
    }});
    syncNoteWriteControls(window.closedAkashicUI?.getSession?.() || {{ authenticated: false, role: 'anonymous', nickname: '' }});
  </script>
  <script>
    {workspace_script}
  </script>
</body>
</html>"""


def closed_graph_html(
    route_prefix: str = "",
    *,
    viewer_owner: str | None = None,
    is_admin: bool = False,
) -> str:
    route_prefix = _normalize_prefix(route_prefix)
    visible_notes = _filter_notes_for_viewer(_load_notes(), viewer_owner=viewer_owner, is_admin=is_admin)
    note_links = _explorer_html(visible_notes, "", route_prefix)
    kind_options_html = "\n".join(
        f'        <option value="{html.escape(item["kind"])}"></option>'
        for item in kind_catalog()
    )
    shared_styles = _shared_ui_styles()
    shared_header = _shared_header_html(route_prefix, "Graph")
    shared_shell = _shared_ui_shell(route_prefix)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="icon" href="data:," />
  <title>OpenAkashic Graph</title>
  <style>
    :root {{
      --bg: #f4f7fb;
      --panel: rgba(255, 255, 255, 0.86);
      --line: #d7e2ef;
      --line-strong: #c5d3e5;
      --ink: #172033;
      --muted: #5d6b82;
      --accent: #2563eb;
      --accent-2: #0f766e;
      --warm: #ea580c;
      --shadow: 0 20px 40px rgba(15, 23, 42, 0.10);
      --closed-sidebar-width: 360px;
    }}
    * {{ box-sizing: border-box; }}
    * {{
      scrollbar-width: thin;
      scrollbar-color: rgba(148, 163, 184, .72) transparent;
    }}
    *::-webkit-scrollbar {{ width: 10px; height: 10px; }}
    *::-webkit-scrollbar-thumb {{
      background: rgba(148, 163, 184, .68);
      border-radius: 999px;
      border: 2px solid transparent;
      background-clip: padding-box;
    }}
    *::-webkit-scrollbar-track {{ background: transparent; }}
    body {{
      margin: 0;
      background:
        linear-gradient(180deg, rgba(37,99,235,.06), transparent 24%),
        radial-gradient(circle at top right, rgba(15,118,110,.08), transparent 22%),
        var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      overflow: hidden;
      transition: background .22s ease;
    }}
    button, input {{ font: inherit; }}
    canvas {{
      display: block;
      width: 100vw;
      height: calc(100svh - var(--closed-header-height));
      cursor: grab;
      touch-action: none;
      transition: transform .24s ease;
    }}
    canvas.grabbing {{ cursor: grabbing; }}
    .shell {{
      position: fixed;
      inset: var(--closed-header-height) auto 0 0;
      width: var(--closed-sidebar-width);
      pointer-events: auto;
      transform: translateX(0);
      transition: transform .24s ease;
      z-index: 30;
    }}
    body.left-collapsed .shell {{
      transform: translateX(calc(var(--closed-sidebar-width) * -1));
    }}
    .sidebar-edge-toggle {{
      position: fixed;
      top: calc(var(--closed-header-height) + 18px);
      left: calc(var(--closed-sidebar-width) - 18px);
      z-index: 60;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.96);
      color: var(--muted);
      box-shadow: 0 10px 24px rgba(15, 23, 42, .08);
      cursor: pointer;
      transition: left .22s ease, transform .18s ease, background .18s ease, border-color .18s ease;
    }}
    body.left-collapsed .sidebar-edge-toggle {{
      left: 10px;
      transform: rotate(180deg);
    }}
    .sidebar-edge-toggle:hover {{
      background: rgba(255,255,255,.99);
      border-color: var(--line-strong);
      color: var(--ink);
    }}
    .graph-menu {{
      width: 100%;
      height: 100%;
      overflow: auto;
      border-right: 1px solid var(--line);
      background: rgba(248, 250, 252, .90);
      backdrop-filter: blur(16px);
      box-shadow: 20px 0 40px rgba(15, 23, 42, 0.06);
    }}
    .graph-panel-tabs {{
      display: flex;
      gap: 6px;
      padding: 10px 12px 0;
      background: rgba(248, 250, 252, .88);
    }}
    .graph-panel-tab {{
      min-height: 32px;
      padding: 0 10px;
      border: 1px solid transparent;
      border-radius: 8px;
      background: transparent;
      color: var(--muted);
      font: inherit;
      font-size: .78rem;
      font-weight: 800;
      cursor: pointer;
    }}
    .graph-panel-tab.active {{
      background: rgba(37, 99, 235, .08);
      border-color: rgba(37, 99, 235, .18);
      color: var(--accent);
    }}
    .graph-tab-panel {{ display: none; }}
    .graph-menu[data-active-tab="explore"] .graph-tab-panel[data-graph-panel="explore"],
    .graph-menu[data-active-tab="selection"] .graph-tab-panel[data-graph-panel="selection"],
    .graph-menu[data-active-tab="display"] .graph-tab-panel[data-graph-panel="display"] {{
      display: block;
    }}
    .floating-inner {{ padding: 0 18px 18px; }}
    .panel-bar {{
      position: sticky;
      top: 0;
      z-index: 2;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-height: 44px;
      padding: 8px 10px 8px 18px;
      border-bottom: 1px solid rgba(215, 226, 239, .84);
      background: rgba(248, 250, 252, .88);
      backdrop-filter: blur(10px);
    }}
    .panel-label {{
      min-width: 0;
      color: var(--muted);
      font-size: .76rem;
      font-weight: 800;
      letter-spacing: .06em;
      text-transform: uppercase;
      overflow-wrap: anywhere;
    }}
    .panel-toggle {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 34px;
      height: 30px;
      padding: 0 9px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.96);
      color: var(--ink);
      cursor: pointer;
      font-size: .78rem;
      font-weight: 800;
    }}
    .eyebrow {{ margin: 0 0 8px; color: var(--accent-2); font-size: .74rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(1.8rem, 3vw, 2.4rem); line-height: 1.04; letter-spacing: 0; }}
    p {{ margin: 0; color: var(--muted); font-size: .95rem; line-height: 1.62; overflow-wrap: anywhere; }}
    .row {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }}
    .chip, .search {{
      display: inline-flex; align-items: center; height: 36px; padding: 0 12px; border-radius: 8px;
      border: 1px solid var(--line); background: rgba(255,255,255,.94); color: var(--ink); font: inherit;
    }}
    .search {{ width: 100%; outline: none; margin-top: 12px; }}
    .stats {{ color: var(--muted); font-size: .84rem; }}
    .panel h2 {{ margin: 0 0 8px; font-size: 1.5rem; line-height: 1.1; letter-spacing: 0; overflow-wrap: anywhere; }}
    .meta {{ color: var(--muted); font-size: .9rem; line-height: 1.65; margin-bottom: 14px; overflow-wrap: anywhere; }}
    .meta-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 12px 0 16px; }}
    .metric {{ min-width: 0; padding: 10px; border: 1px solid var(--line); border-radius: 8px; background: rgba(255,255,255,.94); }}
    .metric span {{ display: block; color: var(--muted); font-size: .72rem; margin-bottom: 5px; text-transform: uppercase; letter-spacing: .06em; }}
    .metric strong {{
      display: block;
      min-width: 0;
      overflow-wrap: anywhere;
      word-break: break-word;
      line-height: 1.35;
      white-space: pre-wrap;
    }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 18px; }}
    .tag {{
      display: inline-flex; align-items: center; height: 28px; padding: 0 10px; border-radius: 999px;
      background: rgba(15,118,110,.08); border: 1px solid rgba(15,118,110,.16); color: var(--accent-2); font-size: .75rem; font-weight: 600;
    }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .button {{
      display: inline-flex; align-items: center; justify-content: center; height: 38px; padding: 0 14px;
      border-radius: 8px; background: var(--accent); color: white; font-weight: 700; border: 0;
    }}
    .ghost {{
      background: rgba(255,255,255,.94); color: var(--ink); border: 1px solid var(--line);
    }}
    .legend {{ margin-top: 14px; display: flex; gap: 12px; flex-wrap: wrap; color: var(--muted); font-size: .78rem; }}
    .legend i {{ display: inline-block; width: 10px; height: 10px; border-radius: 999px; margin-right: 6px; vertical-align: middle; }}
    .brand-wrap {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 18px; }}
    .brand-kicker {{ margin: 0 0 6px; color: var(--accent-2); font-size: 0.76rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }}
    .brand {{ margin: 0; font-size: 1.85rem; line-height: 1.05; font-weight: 780; letter-spacing: 0; }}
    .sub {{ margin: 0; color: var(--muted); font-size: 0.94rem; line-height: 1.6; }}
    .search-wrap {{ position: relative; margin-bottom: 18px; }}
    .search-results {{
      position: absolute; top: calc(100% + 8px); left: 0; right: 0; z-index: 20;
      display: none; padding: 8px; border-radius: 8px; background: #fff;
      border: 1px solid var(--line); box-shadow: var(--shadow);
    }}
    .search-results.visible {{ display: block; }}
    .search-result {{
      display: block; padding: 10px 12px; border-radius: 8px; color: var(--ink);
    }}
    .search-result:hover {{ background: rgba(255,255,255,.86); text-decoration: none; }}
    .search-result small {{ display: block; margin-top: 4px; color: var(--muted); }}
    .section-label {{
      margin: 18px 0 10px; color: var(--muted); font-size: 0.72rem; font-weight: 800;
      letter-spacing: .08em; text-transform: uppercase;
    }}
    .nav {{ display: flex; flex-direction: column; gap: 6px; padding-right: 2px; }}
    .folder-group {{
      margin-left: calc(var(--depth, 0) * 2px);
      border: 1px solid rgba(215, 226, 239, .66);
      border-radius: 8px;
      background: rgba(255,255,255,.46);
      overflow: visible;
    }}
    .folder-group + .folder-group {{ margin-top: 8px; }}
    .folder-summary {{
      list-style: none; display: flex; align-items: center; gap: 10px; padding: 10px 12px; min-width: 0;
      cursor: pointer; color: var(--ink); font-size: 0.84rem; font-weight: 700; background: rgba(255,255,255,.68);
    }}
    .folder-summary::-webkit-details-marker {{ display: none; }}
    .folder-caret {{ display: inline-flex; flex: 0 0 12px; width: 12px; justify-content: center; color: var(--muted); transition: transform .16s ease; }}
    .folder-group[open] > .folder-summary .folder-caret {{ transform: rotate(90deg); }}
    .folder-children {{ display: flex; flex-direction: column; gap: 6px; margin-left: 14px; padding: 6px 6px 8px 10px; border-left: 1px solid rgba(197, 211, 229, .66); }}
    .nav-link {{
      display: block; padding: 10px 12px; border-radius: 8px; color: var(--ink); border: 1px solid transparent;
      transition: background .18s ease, border-color .18s ease, transform .18s ease; min-width: 0;
    }}
    .nav-link:hover {{ background: rgba(255,255,255,.75); text-decoration: none; transform: translateX(2px); }}
    .nav-link.active {{ background: rgba(37, 99, 235, .08); border-color: rgba(37, 99, 235, .2); box-shadow: inset 3px 0 0 rgba(37, 99, 235, .85); }}
    .nav-link span {{ display: block; min-width: 0; overflow-wrap: anywhere; line-height: 1.34; }}
    .nav-link small {{ display:block; color: var(--muted); font-size: 0.72rem; margin-top: 4px; overflow-wrap: anywhere; line-height: 1.35; }}
    .panel-copy {{ color: var(--muted); font-size: .88rem; line-height: 1.6; }}
    .selection-access {{ margin-top: 10px; color: var(--muted); font-size: .84rem; line-height: 1.55; }}
    .filter-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }}
    .filter-field {{
      display: grid;
      gap: 6px;
      min-width: 0;
    }}
    .filter-field span {{
      color: var(--muted);
      font-size: .72rem;
      font-weight: 800;
      letter-spacing: .06em;
      text-transform: uppercase;
    }}
    .filter-input {{
      width: 100%;
      min-width: 0;
      height: 38px;
      padding: 0 12px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.96);
      color: var(--ink);
      outline: none;
    }}
    .filter-meta {{
      margin-top: 12px;
      color: var(--muted);
      font-size: .84rem;
      line-height: 1.55;
    }}
    @media (max-width: 980px) {{
      .shell {{
        inset: var(--closed-header-height) auto 0 0;
      }}
      .graph-menu {{ width: min(100vw, 92vw); }}
      .sidebar-edge-toggle {{ top: calc(var(--closed-header-height) + 10px); left: 10px; }}
    }}
    @media (max-width: 560px) {{
      .meta-grid {{ grid-template-columns: 1fr; }}
      .filter-grid {{ grid-template-columns: 1fr; }}
      .row, .actions {{ gap: 7px; }}
      .chip, .search {{ min-width: 0; max-width: 100%; }}
      .graph-menu {{ width: min(100vw, 100%); }}
    }}
    {shared_styles}
  </style>
</head>
<body class="closed-with-header">
  {shared_header}
  <canvas id="graph"></canvas>
  <button class="sidebar-edge-toggle" id="toggle-left-sidebar" type="button" aria-label="Toggle Sidebar" title="Toggle Sidebar">❮</button>
  <div class="shell">
    <section class="graph-menu floating" id="graph-menu" data-active-tab="explore">
      <div class="panel-bar">
        <div class="brand-wrap" style="margin:0; width:100%;">
          <div>
            <p class="brand-kicker">OpenAkashic</p>
            <h1 class="brand">Graph Inspector</h1>
          </div>
        </div>
      </div>
      <div class="graph-panel-tabs" role="tablist" aria-label="Graph panel tabs">
        <button class="graph-panel-tab active" type="button" data-graph-tab="explore">Explore</button>
        <button class="graph-panel-tab" type="button" data-graph-tab="selection">Selection</button>
        <button class="graph-panel-tab" type="button" data-graph-tab="display">Display</button>
      </div>
      <div class="floating-inner">
        <section class="graph-tab-panel" data-graph-panel="explore">
          <p class="sub">그래프 전체 관계는 유지하되, 여기서는 현재 권한으로 열 수 있는 문서만 탐색하고 검색한다.</p>
          <div class="search-wrap">
            <input class="search" id="graph-note-filter" placeholder="열 수 있는 노트 제목이나 태그 검색" />
            <div class="search-results" id="graph-search-results"></div>
          </div>
          <div class="section-label">Explorer</div>
          <nav class="nav" id="graph-note-nav">
            {note_links or '<p class="panel-copy">현재 권한으로 열 수 있는 문서가 없다.</p>'}
          </nav>
          <div class="row">
            <a class="chip" href="{html.escape(_graph_href(route_prefix))}">Reset View</a>
            <span class="chip stats" id="stats">loading…</span>
          </div>
        </section>
        <section class="graph-tab-panel" data-graph-panel="selection">
          <h2 id="title">노드를 선택하세요</h2>
          <div class="meta" id="summary">그래프에서 노트를 고르면 연결된 이웃과 메타 정보를 같이 보여준다. 드래그로 이동하고 휠로 확대할 수 있다.</div>
          <div class="meta-grid">
            <div class="metric"><span>Kind</span><strong id="kind">-</strong></div>
            <div class="metric"><span>Degree</span><strong id="degree">-</strong></div>
            <div class="metric"><span>Project</span><strong id="project">-</strong></div>
            <div class="metric"><span>Path</span><strong id="path">-</strong></div>
            <div class="metric"><span>Size</span><strong id="size">-</strong></div>
            <div class="metric"><span>Owner</span><strong id="owner">-</strong></div>
            <div class="metric"><span>Status</span><strong id="status">-</strong></div>
            <div class="metric"><span>Visibility</span><strong id="visibility">-</strong></div>
            <div class="metric"><span>Publication</span><strong id="publication">-</strong></div>
          </div>
          <div class="tags" id="tags"></div>
          <div class="actions">
            <a class="button" id="open-link" href="{html.escape(_root_href(route_prefix))}" hidden>Open Note</a>
            <button class="button ghost" id="focus-link" type="button">Focus Selection</button>
          </div>
          <div class="selection-access" id="selection-access">현재 세션으로 노트를 열 수 있는지 여기에서 확인한다.</div>
        </section>
        <section class="graph-tab-panel" data-graph-panel="display">
          <h2>Display</h2>
          <p>그래프 자체는 전체 연결을 유지하면서도, 여기서는 원하는 조건의 노드 집합만 골라 시각화할 수 있다.</p>
          <div class="legend">
            <span><i style="background:#2563eb"></i>architecture/dataset</span>
            <span><i style="background:#0f766e"></i>policy/playbook/profile</span>
            <span><i style="background:#ea580c"></i>evidence/experiment/request</span>
            <span><i style="background:#7c3aed"></i>claim/capsule/roadmap</span>
          </div>
          <datalist id="graph-kind-options">
{kind_options_html}
          </datalist>
          <datalist id="graph-owner-options"></datalist>
          <div class="filter-grid">
            <label class="filter-field">
              <span>Kind</span>
              <input class="filter-input" id="graph-filter-kind" list="graph-kind-options" placeholder="all" />
            </label>
            <label class="filter-field">
              <span>Owner</span>
              <input class="filter-input" id="graph-filter-owner" list="graph-owner-options" placeholder="all" />
            </label>
            <label class="filter-field">
              <span>Name Or Word</span>
              <input class="filter-input" id="graph-filter-query" placeholder="title, tag, path, summary" />
            </label>
            <label class="filter-field">
              <span>Path Contains</span>
              <input class="filter-input" id="graph-filter-path" placeholder="projects/personal/openakashic" />
            </label>
            <label class="filter-field">
              <span>Min Degree</span>
              <input class="filter-input" id="graph-filter-min-degree" type="number" min="0" step="1" value="0" />
            </label>
            <label class="filter-field">
              <span>Max Degree</span>
              <input class="filter-input" id="graph-filter-max-degree" type="number" min="0" step="1" placeholder="auto" />
            </label>
            <label class="filter-field">
              <span>Min Size</span>
              <input class="filter-input" id="graph-filter-min-size" type="number" min="0" step="50" value="0" />
            </label>
            <label class="filter-field">
              <span>Max Size</span>
              <input class="filter-input" id="graph-filter-max-size" type="number" min="0" step="50" placeholder="auto" />
            </label>
          </div>
          <div class="filter-meta" id="graph-filter-meta">전체 그래프를 기준으로 필터를 적용한다.</div>
          <div class="row">
            <button class="chip" id="graph-focus-search" type="button">Focus Explore</button>
            <button class="chip" id="graph-focus-selection" type="button">Focus Selection</button>
            <button class="chip" id="graph-filter-reset" type="button">Reset Filters</button>
          </div>
        </section>
      </div>
    </section>
  </div>
  {shared_shell}
  <script>
    const canvas = document.getElementById('graph');
    const ctx = canvas.getContext('2d');
    const noteFilterInput = document.getElementById('graph-note-filter');
    const noteItems = [...document.querySelectorAll('#graph-note-nav .nav-link')];
    const noteFolders = [...document.querySelectorAll('#graph-note-nav .folder-group')];
    const searchBox = document.getElementById('graph-search-results');
    const graphSearchEndpoint = '{html.escape(_search_href(route_prefix))}';
    const state = {{
      nodes: [],
      links: [],
      selected: null,
      hover: null,
      zoom: 1,
      offsetX: 0,
      offsetY: 0,
      draggingNode: null,
      panning: false,
      lastX: 0,
      lastY: 0,
      adjacency: new Map(),
      clusters: new Map(),
      activePointer: null,
      auth: {{ authenticated: false, role: 'anonymous', nickname: '' }},
      visibleNodeIds: new Set(),
      visibleLinks: [],
      filters: {{ kind: '', owner: '', query: '', path: '', minDegree: 0, maxDegree: '', minSize: 0, maxSize: '' }},
    }};
    const leftCollapsedKey = 'closed-akashic-left-collapsed';
    const graphTabKey = 'closed-akashic-graph-tab';
    const graphMenu = document.getElementById('graph-menu');
    const graphTabs = [...document.querySelectorAll('[data-graph-tab]')];
    const graphFocusSearch = document.getElementById('graph-focus-search');
    const graphFocusSelection = document.getElementById('graph-focus-selection');
    const leftToggle = document.getElementById('toggle-left-sidebar');
    const openLink = document.getElementById('open-link');
    const ownerOptions = document.getElementById('graph-owner-options');
    const filterKind = document.getElementById('graph-filter-kind');
    const filterOwner = document.getElementById('graph-filter-owner');
    const filterQuery = document.getElementById('graph-filter-query');
    const filterPath = document.getElementById('graph-filter-path');
    const filterMinDegree = document.getElementById('graph-filter-min-degree');
    const filterMaxDegree = document.getElementById('graph-filter-max-degree');
    const filterMinSize = document.getElementById('graph-filter-min-size');
    const filterMaxSize = document.getElementById('graph-filter-max-size');
    const filterMeta = document.getElementById('graph-filter-meta');
    const filterReset = document.getElementById('graph-filter-reset');
    let searchTimer = null;

    function resize() {{
      const dpr = window.devicePixelRatio || 1;
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }}

    function clusterKey(node) {{
      return (node.path || '').split('/')[0] || 'root';
    }}

    function nodeColor(node) {{
      if (['architecture', 'dataset'].includes(node.kind)) return '#2563eb';
      if (['policy', 'playbook', 'profile'].includes(node.kind)) return '#0f766e';
      if (['evidence', 'experiment', 'publication_request'].includes(node.kind)) return '#ea580c';
      if (['claim', 'capsule', 'roadmap'].includes(node.kind)) return '#7c3aed';
      return '#334155';
    }}

    function init() {{
      const keys = [...new Set(state.nodes.map(clusterKey))];
      const cx = window.innerWidth / 2;
      const cy = window.innerHeight / 2;
      keys.forEach((key, i) => {{
        const angle = (i / Math.max(keys.length, 1)) * Math.PI * 2;
        state.clusters.set(key, {{
          x: cx + Math.cos(angle) * Math.min(260, window.innerWidth * 0.24),
          y: cy + Math.sin(angle) * Math.min(190, window.innerHeight * 0.22),
        }});
      }});

      state.nodes.forEach((node, i) => {{
        const anchor = state.clusters.get(clusterKey(node)) || {{ x: cx, y: cy }};
        const angle = (i * 0.75) % (Math.PI * 2);
        const radius = 26 + (i % 9) * 14;
        node.x = anchor.x + Math.cos(angle) * radius;
        node.y = anchor.y + Math.sin(angle) * radius;
        node.vx = 0;
        node.vy = 0;
      }});
    }}

    function buildAdjacency() {{
      const map = new Map();
      state.nodes.forEach(node => map.set(node.id, new Set()));
      state.links.forEach(link => {{
        map.get(link.source)?.add(link.target);
        map.get(link.target)?.add(link.source);
      }});
      state.adjacency = map;
    }}

    function matchesGraphFilters(node) {{
      const kind = String(state.filters.kind || '').trim().toLowerCase();
      const owner = String(state.filters.owner || '').trim().toLowerCase();
      const query = String(state.filters.query || '').trim().toLowerCase();
      const pathQuery = String(state.filters.path || '').trim().toLowerCase();
      const minDegree = Number(state.filters.minDegree || 0) || 0;
      const maxDegree = state.filters.maxDegree === '' ? Number.POSITIVE_INFINITY : Number(state.filters.maxDegree || 0);
      const minSize = Number(state.filters.minSize || 0) || 0;
      const maxSize = state.filters.maxSize === '' ? Number.POSITIVE_INFINITY : Number(state.filters.maxSize || 0);
      const haystack = [node.title, node.summary, node.path, node.project, node.kind, ...(node.tags || [])]
        .join(' ')
        .toLowerCase();
      if (kind && node.kind !== kind) return false;
      if (owner && String(node.owner || '').toLowerCase() !== owner) return false;
      if (query && !haystack.includes(query)) return false;
      if (pathQuery && !String(node.path || '').toLowerCase().includes(pathQuery)) return false;
      if ((node.degree || 0) < minDegree) return false;
      if ((node.degree || 0) > maxDegree) return false;
      if ((node.size || 0) < minSize) return false;
      if ((node.size || 0) > maxSize) return false;
      return true;
    }}

    function visibleNodes() {{
      return state.nodes.filter((node) => state.visibleNodeIds.has(node.id));
    }}

    function rebuildVisibleGraph() {{
      const nextNodes = state.nodes.filter(matchesGraphFilters);
      state.visibleNodeIds = new Set(nextNodes.map((node) => node.id));
      state.visibleLinks = state.links.filter((link) => state.visibleNodeIds.has(link.source) && state.visibleNodeIds.has(link.target));
      const nextAdjacency = new Map(nextNodes.map((node) => [node.id, new Set()]));
      state.visibleLinks.forEach((link) => {{
        nextAdjacency.get(link.source)?.add(link.target);
        nextAdjacency.get(link.target)?.add(link.source);
      }});
      state.adjacency = nextAdjacency;
      if (state.selected && !state.visibleNodeIds.has(state.selected.id)) {{
        state.selected = null;
        document.getElementById('title').textContent = '노드를 선택하세요';
        document.getElementById('summary').textContent = '그래프에서 노트를 고르면 연결된 이웃과 메타 정보를 같이 보여준다. 드래그로 이동하고 휠로 확대할 수 있다.';
      }}
      if (filterMeta) {{
        filterMeta.textContent = nextNodes.length + '개 노드와 ' + state.visibleLinks.length + '개 링크가 현재 필터에 맞는다.';
      }}
      syncSelectionAccess();
    }}

    function worldFromScreen(clientX, clientY) {{
      return {{
        x: (clientX - state.offsetX) / state.zoom,
        y: (clientY - state.offsetY) / state.zoom,
      }};
    }}

    function screenFromWorld(x, y) {{
      return {{
        x: x * state.zoom + state.offsetX,
        y: y * state.zoom + state.offsetY,
      }};
    }}

    function pick(clientX, clientY) {{
      const point = worldFromScreen(clientX, clientY);
      let best = null;
      let bestDist = Infinity;
      for (const node of visibleNodes()) {{
        const r = nodeRadius(node) + 4;
        const d = Math.hypot(node.x - point.x, node.y - point.y);
        if (d < r && d < bestDist) {{
          best = node;
          bestDist = d;
        }}
      }}
      return best;
    }}

    function nodeRadius(node) {{
      return 7 + Math.min(14, node.degree * 1.7);
    }}

    function relatedToActive(node) {{
      if (!state.selected) return false;
      if (state.selected.id === node.id) return true;
      return state.adjacency.get(state.selected.id)?.has(node.id);
    }}

    function stepPhysics() {{
      const centerX = (window.innerWidth / 2 - state.offsetX) / state.zoom;
      const centerY = (window.innerHeight / 2 - state.offsetY) / state.zoom;
      const nodes = visibleNodes();
      const lookup = new Map(nodes.map(node => [node.id, node]));

      for (let i = 0; i < nodes.length; i += 1) {{
        const a = nodes[i];
        if (a === state.draggingNode) continue;

        const cluster = state.clusters.get(clusterKey(a)) || {{ x: centerX, y: centerY }};
        a.vx += (cluster.x - a.x) * 0.0009;
        a.vy += (cluster.y - a.y) * 0.0009;
        a.vx += (centerX - a.x) * 0.00014;
        a.vy += (centerY - a.y) * 0.00014;

        for (let j = i + 1; j < nodes.length; j += 1) {{
          const b = nodes[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const dist = Math.max(18, Math.hypot(dx, dy));
          const force = 220 / (dist * dist);
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          if (a !== state.draggingNode) {{ a.vx += fx; a.vy += fy; }}
          if (b !== state.draggingNode) {{ b.vx -= fx; b.vy -= fy; }}
        }}
      }}

      for (const edge of state.visibleLinks) {{
        const a = lookup.get(edge.source);
        const b = lookup.get(edge.target);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.max(1, Math.hypot(dx, dy));
        const desired = 78 + Math.min(80, (a.degree + b.degree) * 2.6);
        const force = (dist - desired) * 0.0016;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        if (a !== state.draggingNode) {{ a.vx += fx; a.vy += fy; }}
        if (b !== state.draggingNode) {{ b.vx -= fx; b.vy -= fy; }}
      }}

      for (const node of nodes) {{
        if (node === state.draggingNode) continue;
        node.vx *= 0.92;
        node.vy *= 0.92;
        node.x += node.vx;
        node.y += node.vy;
      }}
    }}

    function drawGrid() {{
      const spacing = 52 * state.zoom;
      const startX = ((state.offsetX % spacing) + spacing) % spacing;
      const startY = ((state.offsetY % spacing) + spacing) % spacing;
      ctx.save();
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.16)';
      ctx.lineWidth = 1;
      for (let x = startX; x < window.innerWidth; x += spacing) {{
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, window.innerHeight);
        ctx.stroke();
      }}
      for (let y = startY; y < window.innerHeight; y += spacing) {{
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(window.innerWidth, y);
        ctx.stroke();
      }}
      ctx.restore();
    }}

    function render() {{
      ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
      drawGrid();

      const nodes = visibleNodes();
      const lookup = new Map(nodes.map(node => [node.id, node]));
      ctx.save();
      ctx.translate(state.offsetX, state.offsetY);
      ctx.scale(state.zoom, state.zoom);

      for (const edge of state.visibleLinks) {{
        const a = lookup.get(edge.source);
        const b = lookup.get(edge.target);
        if (!a || !b) continue;
        const active = state.selected && (edge.source === state.selected.id || edge.target === state.selected.id);
        ctx.strokeStyle = active ? 'rgba(37,99,235,.52)' : 'rgba(100,116,139,.18)';
        ctx.lineWidth = active ? 1.5 / state.zoom : 1 / state.zoom;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }}

      for (const node of nodes) {{
        const active = state.selected && state.selected.id === node.id;
        const hovered = state.hover && state.hover.id === node.id;
        const related = relatedToActive(node);
        const radius = nodeRadius(node) + (active ? 5 : hovered ? 2 : 0);
        const color = active ? '#0f766e' : nodeColor(node);
        ctx.beginPath();
        ctx.fillStyle = color;
        ctx.globalAlpha = active || related || hovered ? 0.96 : 0.7;
        ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
        ctx.fill();

        if (active || hovered) {{
          ctx.beginPath();
          ctx.lineWidth = 2 / state.zoom;
          ctx.strokeStyle = 'rgba(255,255,255,.92)';
          ctx.arc(node.x, node.y, radius + 3, 0, Math.PI * 2);
          ctx.stroke();
        }}

        const label = active || hovered || related || node.degree >= 4;
        if (label) {{
          ctx.globalAlpha = active || hovered ? 1 : 0.82;
          ctx.fillStyle = '#172033';
          ctx.font = `${{active ? 700 : 600}} ${{Math.max(11, 12 / state.zoom)}}px Inter, system-ui, sans-serif`;
          ctx.fillText(node.title, node.x + radius + 7, node.y + 4);
        }}
      }}
      ctx.restore();
    }}

    function show(node) {{
      state.selected = node;
      setGraphTab('selection');
      document.getElementById('title').textContent = node.title;
      document.getElementById('summary').textContent = node.summary || '요약 없음';
      document.getElementById('kind').textContent = node.kind || '-';
      document.getElementById('degree').textContent = String(node.degree ?? 0);
      document.getElementById('project').textContent = node.project || '-';
      document.getElementById('path').textContent = node.path || '-';
      document.getElementById('size').textContent = `${{node.size || 0}} chars`;
      document.getElementById('owner').textContent = node.owner || '-';
      document.getElementById('status').textContent = node.status || '-';
      document.getElementById('visibility').textContent = node.visibility || '-';
      document.getElementById('publication').textContent = node.publication_status || '-';
      document.getElementById('tags').innerHTML = (node.tags || []).map(tag => `<span class="tag">#${{tag}}</span>`).join('') || '<span class="tag">#untagged</span>';
      openLink.href = `{html.escape(_notes_base(route_prefix))}/${{node.slug}}`;
      syncSelectionAccess();
    }}

    function canOpenNode(node) {{
      if (!node) return false;
      return Boolean(node.can_open);
    }}

    function syncSelectionAccess() {{
      const access = document.getElementById('selection-access');
      if (!state.selected) {{
        openLink.hidden = true;
        if (access) access.textContent = '노드를 고르면 현재 세션에서 열 수 있는지 함께 표시한다.';
        return;
      }}
      const allowed = canOpenNode(state.selected);
      openLink.hidden = !allowed;
      if (access) {{
        access.textContent = allowed
          ? (state.selected.visibility === 'public'
              ? '이 노트는 public 공개 문서라 현재 세션으로 바로 열 수 있다.'
              : '현재 세션은 이 노트를 열 수 있다.')
          : '현재 세션은 이 노트를 열 수 없다. 그래프 관계만 확인 가능하다.';
      }}
    }}

    function setLeftCollapsed(collapsed) {{
      document.body.classList.toggle('left-collapsed', collapsed);
      leftToggle?.setAttribute('aria-pressed', String(collapsed));
      window.localStorage.setItem(leftCollapsedKey, collapsed ? '1' : '0');
    }}

    function setGraphTab(tab) {{
      const next = ['explore', 'selection', 'display'].includes(tab) ? tab : 'explore';
      graphMenu?.setAttribute('data-active-tab', next);
      graphTabs.forEach((button) => button.classList.toggle('active', button.dataset.graphTab === next));
      window.localStorage.setItem(graphTabKey, next);
      setLeftCollapsed(false);
    }}

    function focusSelected() {{
      if (!state.selected) return;
      state.offsetX = window.innerWidth * 0.5 - state.selected.x * state.zoom;
      state.offsetY = window.innerHeight * 0.5 - state.selected.y * state.zoom;
    }}

    async function boot() {{
      resize();
      const data = await fetch('{html.escape(_graph_data_href(route_prefix))}').then(res => res.json());
      state.nodes = data.nodes;
      state.links = data.links;
      if (ownerOptions) {{
        ownerOptions.innerHTML = [...new Set(state.nodes.map((node) => String(node.owner || '').trim()).filter(Boolean))]
          .sort((a, b) => a.localeCompare(b))
          .map((owner) => `<option value="${{owner}}"></option>`)
          .join('');
      }}
      document.getElementById('stats').textContent = `${{data.meta.note_count}} notes · ${{data.meta.link_count}} links`;
      state.offsetX = window.innerWidth * 0.12;
      state.offsetY = window.innerHeight * 0.08;
      init();
      rebuildVisibleGraph();
      if (visibleNodes()[0]) show(visibleNodes()[0]);
      tick();
    }}

    function tick() {{
      stepPhysics();
      render();
      requestAnimationFrame(tick);
    }}

    window.addEventListener('resize', resize);
    document.getElementById('focus-link').addEventListener('click', focusSelected);
    graphTabs.forEach((button) => {{
      button.addEventListener('click', () => setGraphTab(button.dataset.graphTab || 'explore'));
    }});
    graphFocusSearch?.addEventListener('click', () => {{
      setGraphTab('explore');
      window.setTimeout(() => noteFilterInput?.focus(), 80);
    }});
    graphFocusSelection?.addEventListener('click', () => {{
      setGraphTab('selection');
      focusSelected();
    }});
    if (window.localStorage.getItem(leftCollapsedKey) === '1') setLeftCollapsed(true);
    setGraphTab(window.localStorage.getItem(graphTabKey) || 'explore');
    leftToggle?.addEventListener('click', () => setLeftCollapsed(!document.body.classList.contains('left-collapsed')));
    const filterInputs = [filterKind, filterOwner, filterQuery, filterPath, filterMinDegree, filterMaxDegree, filterMinSize, filterMaxSize];
    filterInputs.forEach((field) => field?.addEventListener('input', () => {{
      state.filters.kind = String(filterKind?.value || '').trim().toLowerCase();
      state.filters.owner = String(filterOwner?.value || '').trim().toLowerCase();
      state.filters.query = String(filterQuery?.value || '').trim();
      state.filters.path = String(filterPath?.value || '').trim();
      state.filters.minDegree = String(filterMinDegree?.value || '0').trim();
      state.filters.maxDegree = String(filterMaxDegree?.value || '').trim();
      state.filters.minSize = String(filterMinSize?.value || '0').trim();
      state.filters.maxSize = String(filterMaxSize?.value || '').trim();
      rebuildVisibleGraph();
    }}));
    filterReset?.addEventListener('click', () => {{
      if (filterKind) filterKind.value = '';
      if (filterOwner) filterOwner.value = '';
      if (filterQuery) filterQuery.value = '';
      if (filterPath) filterPath.value = '';
      if (filterMinDegree) filterMinDegree.value = '0';
      if (filterMaxDegree) filterMaxDegree.value = '';
      if (filterMinSize) filterMinSize.value = '0';
      if (filterMaxSize) filterMaxSize.value = '';
      state.filters = {{ kind: '', owner: '', query: '', path: '', minDegree: 0, maxDegree: '', minSize: 0, maxSize: '' }};
      rebuildVisibleGraph();
    }});
    noteFilterInput?.addEventListener('input', () => {{
      const q = noteFilterInput.value.trim().toLowerCase();
      for (const item of noteItems) {{
        const hit = !q || item.dataset.title.includes(q);
        item.style.display = hit ? '' : 'none';
      }}
      for (const folder of noteFolders) {{
        const descendants = [...folder.querySelectorAll('.nav-link')];
        const visible = descendants.some((item) => item.style.display !== 'none');
        folder.style.display = visible ? '' : 'none';
        if (q && visible) folder.open = true;
      }}
      window.clearTimeout(searchTimer);
      if (!q) {{
        searchBox?.classList.remove('visible');
        if (searchBox) searchBox.innerHTML = '';
        return;
      }}
      searchTimer = window.setTimeout(async () => {{
        try {{
          const res = await fetch(`${{graphSearchEndpoint}}?q=${{encodeURIComponent(q)}}&limit=6`);
          const data = await res.json();
          const results = (data.results || []).map((item) => `
            <a class="search-result" href="${{item.href}}">
              <strong>${{item.title}}</strong>
              <small>${{item.summary || item.path || ''}}</small>
            </a>
          `).join('');
          if (searchBox) {{
            searchBox.innerHTML = results || '<div class="search-result"><strong>검색 결과 없음</strong></div>';
            searchBox.classList.add('visible');
          }}
        }} catch (error) {{
          searchBox?.classList.remove('visible');
        }}
      }}, 160);
    }});
    document.addEventListener('click', (event) => {{
      if (!searchBox?.contains(event.target) && event.target !== noteFilterInput) {{
        searchBox?.classList.remove('visible');
      }}
    }});
    document.addEventListener('closed-akashic-auth-change', (event) => {{
      state.auth = event.detail || {{ authenticated: false, role: 'anonymous', nickname: '' }};
      syncSelectionAccess();
    }});
    const initialSession = window.closedAkashicUI?.getSession?.();
    if (initialSession) {{
      state.auth = initialSession;
    }}

    canvas.addEventListener('pointerdown', (event) => {{
      const node = pick(event.clientX, event.clientY);
      state.activePointer = event.pointerId;
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      canvas.setPointerCapture(event.pointerId);
      if (node) {{
        state.draggingNode = node;
        show(node);
      }} else {{
        state.panning = true;
        canvas.classList.add('grabbing');
      }}
    }});

    window.addEventListener('pointermove', (event) => {{
      if (state.activePointer !== null && event.pointerId !== state.activePointer) return;
      if (state.draggingNode) {{
        const point = worldFromScreen(event.clientX, event.clientY);
        state.draggingNode.x = point.x;
        state.draggingNode.y = point.y;
        state.draggingNode.vx = 0;
        state.draggingNode.vy = 0;
        return;
      }}
      if (state.panning) {{
        state.offsetX += event.clientX - state.lastX;
        state.offsetY += event.clientY - state.lastY;
        state.lastX = event.clientX;
        state.lastY = event.clientY;
        return;
      }}
      state.hover = pick(event.clientX, event.clientY);
    }});

    window.addEventListener('pointerup', (event) => {{
      if (state.activePointer !== null && event.pointerId !== state.activePointer) return;
      state.draggingNode = null;
      state.panning = false;
      state.activePointer = null;
      canvas.classList.remove('grabbing');
      try {{ canvas.releasePointerCapture(event.pointerId); }} catch (error) {{}}
    }});

    window.addEventListener('pointercancel', (event) => {{
      if (state.activePointer !== null && event.pointerId !== state.activePointer) return;
      state.draggingNode = null;
      state.panning = false;
      state.activePointer = null;
      canvas.classList.remove('grabbing');
      try {{ canvas.releasePointerCapture(event.pointerId); }} catch (error) {{}}
    }});

    canvas.addEventListener('wheel', (event) => {{
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.08 : 0.92;
      const nextZoom = Math.min(2.4, Math.max(0.42, state.zoom * factor));
      const worldBefore = worldFromScreen(event.clientX, event.clientY);
      state.zoom = nextZoom;
      state.offsetX = event.clientX - worldBefore.x * state.zoom;
      state.offsetY = event.clientY - worldBefore.y * state.zoom;
    }}, {{ passive: false }});

    canvas.addEventListener('dblclick', (event) => {{
      const node = pick(event.clientX, event.clientY);
      if (node && canOpenNode(node)) {{
        window.location.href = `{html.escape(_notes_base(route_prefix))}/${{node.slug}}`;
      }}
    }});

    boot();
  </script>
</body>
</html>"""


def closed_debug_html(route_prefix: str = "") -> str:
    route_prefix = _normalize_prefix(route_prefix)
    api_base_json = json.dumps("", ensure_ascii=False)
    shared_styles = _shared_ui_styles()
    shared_header = _shared_header_html(route_prefix, "Admin")
    shared_shell = _shared_ui_shell(route_prefix)
    template = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="icon" href="data:," />
  <title>OpenAkashic Admin</title>
  <style>
    :root {
      --bg: #f4f7fb;
      --surface: rgba(255, 255, 255, .88);
      --surface-strong: #ffffff;
      --panel: #eef3f9;
      --line: #d7e2ef;
      --line-strong: #c5d3e5;
      --ink: #172033;
      --muted: #5d6b82;
      --accent: #2563eb;
      --accent-2: #0f766e;
      --warn: #c2410c;
      --error: #b91c1c;
      --shadow: 0 18px 40px rgba(15, 23, 42, .08);
    }
    * { box-sizing: border-box; }
    * {
      scrollbar-width: thin;
      scrollbar-color: rgba(148, 163, 184, .72) transparent;
    }
    *::-webkit-scrollbar { width: 10px; height: 10px; }
    *::-webkit-scrollbar-thumb {
      background: rgba(148, 163, 184, .68);
      border-radius: 999px;
      border: 2px solid transparent;
      background-clip: padding-box;
    }
    *::-webkit-scrollbar-track { background: transparent; }
    html, body {
      margin: 0;
      min-height: 100%;
      background:
        linear-gradient(180deg, rgba(37, 99, 235, .055), transparent 26%),
        radial-gradient(circle at top right, rgba(15, 118, 110, .07), transparent 22%),
        var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .admin-layout {
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr);
      min-height: calc(100svh - var(--closed-header-height));
    }
    .admin-sidebar {
      position: sticky;
      top: var(--closed-header-height);
      align-self: start;
      display: grid;
      gap: 14px;
      height: calc(100svh - var(--closed-header-height));
      padding: 28px 20px;
      border-right: 1px solid var(--line);
      background: rgba(248, 250, 252, .84);
      backdrop-filter: blur(14px);
    }
    .admin-content {
      min-width: 0;
      padding: 28px clamp(16px, 3vw, 38px) 42px;
    }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    button, input, select { font: inherit; }
    .brand-kicker {
      margin: 0 0 6px;
      color: var(--accent-2);
      font-size: .74rem;
      font-weight: 800;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .sidebar-title {
      margin: 0;
      font-size: 1.7rem;
      line-height: 1;
    }
    .sidebar-copy {
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
      font-size: .92rem;
    }
    .admin-nav {
      display: grid;
      gap: 8px;
    }
    .admin-nav-button {
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 42px;
      padding: 0 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(255, 255, 255, .88);
      color: var(--ink);
      font-weight: 700;
      cursor: pointer;
      text-align: left;
      transition: background .16s ease, border-color .16s ease, transform .16s ease;
    }
    .admin-nav-button:hover {
      background: rgba(255,255,255,.98);
      border-color: var(--line-strong);
      transform: translateX(2px);
    }
    .admin-nav-button.active {
      background: rgba(37, 99, 235, .09);
      border-color: rgba(37, 99, 235, .22);
      color: var(--accent);
      box-shadow: inset 3px 0 0 rgba(37, 99, 235, .88);
    }
    .admin-page {
      display: flex;
      flex-direction: column;
      gap: 18px;
    }
    .page-head {
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: flex-start;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--line);
    }
    h1 {
      margin: 0;
      font-size: clamp(2.2rem, 4vw, 4.1rem);
      line-height: .98;
      letter-spacing: 0;
    }
    .lead {
      margin: 12px 0 0;
      max-width: 68ch;
      color: var(--muted);
      font-size: 1rem;
      line-height: 1.72;
    }
    .quicklinks, .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-start;
    }
    .chip, .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 36px;
      padding: 0 12px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, .94);
      color: var(--ink);
      font-size: .86rem;
      font-weight: 700;
      cursor: pointer;
    }
    .button.primary {
      background: var(--ink);
      border-color: var(--ink);
      color: white;
    }
    .button:disabled {
      opacity: .48;
      cursor: not-allowed;
    }
    .panel-shell {
      display: grid;
      gap: 18px;
    }
    .admin-panel[hidden] {
      display: none;
    }
    .overview-grid, .debug-grid {
      display: grid;
      gap: 18px;
      grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
      align-items: start;
    }
    .panel, .card {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }
    .side {
      position: sticky;
      top: 18px;
      display: grid;
      gap: 14px;
    }
    .card {
      padding: 16px;
      background: rgba(255, 255, 255, .84);
    }
    .card-title {
      margin: 0 0 12px;
      color: var(--muted);
      font-size: .72rem;
      font-weight: 800;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .field {
      display: grid;
      gap: 7px;
      margin-bottom: 12px;
    }
    .field:last-child { margin-bottom: 0; }
    label {
      color: var(--muted);
      font-size: .74rem;
      font-weight: 800;
      letter-spacing: .06em;
      text-transform: uppercase;
    }
    .input, .select {
      width: 100%;
      min-height: 40px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, .98);
      color: var(--ink);
      padding: 0 12px;
      outline: none;
    }
    .input:focus, .select:focus {
      border-color: rgba(37, 99, 235, .42);
      box-shadow: 0 0 0 4px rgba(37, 99, 235, .08);
    }
    .filter-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .filter-grid .span-2 { grid-column: 1 / -1; }
    .status-line {
      margin: 10px 0 0;
      color: var(--muted);
      font-size: .86rem;
      line-height: 1.6;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      padding: 14px;
    }
    .metric {
      min-height: 92px;
      padding: 14px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, .88);
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: .72rem;
      font-weight: 800;
      letter-spacing: .06em;
      text-transform: uppercase;
    }
    .metric strong {
      display: block;
      margin-top: 10px;
      font-size: 1.75rem;
      line-height: 1;
      letter-spacing: 0;
    }
    .list {
      display: grid;
      gap: 10px;
      padding: 14px;
      border-top: 1px solid var(--line);
    }
    .request {
      display: grid;
      grid-template-columns: 140px 78px minmax(0, 1fr) 96px 86px;
      gap: 12px;
      align-items: start;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, .82);
      color: inherit;
      cursor: pointer;
      text-align: left;
    }
    .request:hover {
      border-color: var(--line-strong);
      background: var(--surface-strong);
    }
    .request:focus-visible {
      outline: none;
      border-color: rgba(37, 99, 235, .44);
      box-shadow: 0 0 0 4px rgba(37, 99, 235, .10);
    }
    .time {
      color: var(--muted);
      font-size: .8rem;
      line-height: 1.45;
    }
    .path {
      min-width: 0;
      font-weight: 760;
      line-height: 1.35;
      word-break: break-word;
    }
    .details {
      margin-top: 7px;
      color: var(--muted);
      font-size: .78rem;
      line-height: 1.5;
      word-break: break-word;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      width: fit-content;
      min-height: 28px;
      padding: 0 9px;
      border-radius: 999px;
      border: 1px solid rgba(37, 99, 235, .16);
      background: rgba(37, 99, 235, .08);
      color: var(--accent);
      font-size: .76rem;
      font-weight: 800;
      text-transform: uppercase;
    }
    .badge.kind-mcp, .badge.ok {
      border-color: rgba(15, 118, 110, .18);
      background: rgba(15, 118, 110, .09);
      color: var(--accent-2);
    }
    .badge.kind-debug {
      border-color: rgba(37, 99, 235, .16);
      background: rgba(37, 99, 235, .08);
      color: var(--accent);
    }
    .badge.kind-asset, .badge.warn {
      border-color: rgba(234, 88, 12, .18);
      background: rgba(234, 88, 12, .10);
      color: var(--warn);
    }
    .badge.error {
      border-color: rgba(185, 28, 28, .20);
      background: rgba(220, 38, 38, .10);
      color: var(--error);
    }
    .duration {
      color: var(--ink);
      font-weight: 800;
      text-align: right;
    }
    .empty {
      padding: 36px 18px;
      color: var(--muted);
      text-align: center;
      line-height: 1.7;
    }
    .footer-note {
      color: var(--muted);
      font-size: .84rem;
      line-height: 1.62;
    }
    .modal-shell[hidden] { display: none; }
    .modal-shell {
      position: fixed;
      inset: 0;
      z-index: 80;
      display: grid;
      place-items: center;
      padding: 18px;
    }
    .modal-backdrop {
      position: absolute;
      inset: 0;
      background: rgba(15, 23, 42, .28);
      backdrop-filter: blur(7px);
    }
    .modal {
      position: relative;
      width: min(1040px, 100%);
      max-height: min(860px, calc(100svh - 36px));
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(248, 250, 252, .98);
      box-shadow: 0 24px 70px rgba(15, 23, 42, .24);
    }
    .modal-head {
      position: sticky;
      top: 0;
      z-index: 2;
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 14px;
      padding: 18px;
      border-bottom: 1px solid var(--line);
      background: rgba(248, 250, 252, .96);
      backdrop-filter: blur(10px);
    }
    .modal-title {
      margin: 0;
      font-size: 1.34rem;
      line-height: 1.18;
      overflow-wrap: anywhere;
    }
    .icon-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 38px;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,.96);
      color: var(--ink);
      font: inherit;
      font-size: 1.18rem;
      cursor: pointer;
    }
    .modal-body {
      display: grid;
      gap: 14px;
      padding: 18px;
    }
    .detail-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .detail-box {
      min-width: 0;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,.82);
    }
    .detail-box span {
      display: block;
      margin-bottom: 7px;
      color: var(--muted);
      font-size: .72rem;
      font-weight: 800;
      letter-spacing: .06em;
      text-transform: uppercase;
    }
    .detail-box strong {
      display: block;
      min-width: 0;
      overflow-wrap: anywhere;
      line-height: 1.35;
    }
    .payload-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    .payload-card {
      min-width: 0;
      display: grid;
      gap: 10px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, .84);
    }
    .payload-card h3 {
      margin: 0;
      font-size: .9rem;
      color: var(--muted);
      letter-spacing: .06em;
      text-transform: uppercase;
    }
    .pretext {
      max-width: 100%;
      max-height: 340px;
      overflow: auto;
      margin: 0;
      padding: 12px;
      border-radius: 8px;
      border: 1px solid rgba(197, 211, 229, .76);
      background: rgba(15, 23, 42, .045);
      color: #0f172a;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: .82rem;
      line-height: 1.55;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    .data-table {
      width: 100%;
      border-collapse: collapse;
      background: rgba(255,255,255,.78);
      border-radius: 12px;
      overflow: hidden;
    }
    .data-table th, .data-table td {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: .92rem;
    }
    .data-table th {
      color: var(--muted);
      font-size: .74rem;
      text-transform: uppercase;
      letter-spacing: .06em;
    }
    .inline-form {
      display: grid;
      gap: 12px;
    }
    .tool-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .checkbox {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: rgba(255,255,255,.88);
    }
    .toolbar-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .locked-copy {
      color: var(--muted);
      line-height: 1.7;
      font-size: .94rem;
    }
    @media (max-width: 1040px) {
      .admin-layout { grid-template-columns: 1fr; }
      .admin-sidebar {
        position: static;
        height: auto;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }
      .overview-grid, .debug-grid { grid-template-columns: 1fr; }
      .side { position: static; }
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .request { grid-template-columns: 110px 70px minmax(0, 1fr); }
      .request .duration { text-align: left; }
      .detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .payload-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 720px) {
      .admin-content { padding: 20px 14px 28px; }
      .page-head { display: grid; }
      .quicklinks, .actions { justify-content: flex-start; }
      .metrics, .filter-grid { grid-template-columns: 1fr; }
      .filter-grid .span-2 { grid-column: auto; }
      .request { grid-template-columns: 1fr; }
      .duration { text-align: left; }
      .detail-grid { grid-template-columns: 1fr; }
      .tool-grid { grid-template-columns: 1fr; }
      .modal-shell { padding: 10px; place-items: stretch; }
      .modal { max-height: calc(100svh - 20px); }
      .modal-head, .modal-body { padding: 14px; }
    }
    __SHARED_STYLES__
  </style>
</head>
<body class="closed-with-header">
  __SHARED_HEADER__
  <div class="admin-layout">
    <aside class="admin-sidebar">
      <div>
        <p class="brand-kicker">OpenAkashic</p>
        <h1 class="sidebar-title">Admin</h1>
        <p class="sidebar-copy">사용자, 역할, 디버그 요청, 사관 런타임 설정을 한 곳에서 관리한다.</p>
      </div>
      <nav class="admin-nav" aria-label="Admin sections">
        <button class="admin-nav-button active" type="button" data-admin-nav="overview">Overview</button>
        <button class="admin-nav-button" type="button" data-admin-nav="debug">Debug</button>
        <button class="admin-nav-button" type="button" data-admin-nav="users">Users</button>
        <button class="admin-nav-button" type="button" data-admin-nav="roles">Roles</button>
        <button class="admin-nav-button" type="button" data-admin-nav="sagwan">Sagwan</button>
        <button class="admin-nav-button" type="button" data-admin-nav="busagwan">Busagwan</button>
      </nav>
      <p class="footer-note">관리자 토큰이 없으면 이 페이지는 개요만 보이고, 관리 기능은 잠금 상태로 남는다.</p>
    </aside>
    <main class="admin-content">
      <div class="admin-page">
        <header class="page-head">
          <div>
            <p class="brand-kicker">OpenAkashic</p>
            <h1>Admin Console</h1>
            <p class="lead">권한 모델, 사용자 계정, 사관/부사관 에이전트 설정, 요청 로그를 현재 OpenAkashic 구조에 맞춰 관리한다.</p>
          </div>
          <nav class="quicklinks">
            <button class="chip" id="admin-refresh-all" type="button">Refresh</button>
          </nav>
        </header>

        <section class="panel-shell">
          <section class="admin-panel" id="admin-panel-overview">
            <div class="overview-grid">
              <aside class="side">
                <section class="card">
                  <h2 class="card-title">Session</h2>
                  <div class="status-line" id="admin-session-status">관리자 세션을 확인하는 중이다.</div>
                </section>
                <section class="card">
                  <h2 class="card-title">Next Checks</h2>
                  <div class="locked-copy">
                    public 문서는 모두가 읽을 수 있고 private 문서는 owner/admin만 다룰 수 있다.
                    사용자 토큰은 웹 로그인과 에이전트 API/MCP 모두에서 재사용한다.
                  </div>
                </section>
              </aside>
              <section class="panel">
                <div class="metrics">
                  <div class="metric"><span>Users</span><strong id="metric-users">0</strong></div>
                  <div class="metric"><span>Admins</span><strong id="metric-admins">0</strong></div>
                  <div class="metric"><span>Managers</span><strong id="metric-managers">0</strong></div>
                  <div class="metric"><span>Librarian Tools</span><strong id="metric-tools">0</strong></div>
                </div>
                <div class="list">
                  <section class="card">
                    <h2 class="card-title">Librarian Runtime</h2>
                    <div class="locked-copy" id="overview-librarian">사관 설정을 불러오는 중이다.</div>
                  </section>
                  <section class="card">
                    <h2 class="card-title">Recent Requests</h2>
                    <div class="locked-copy" id="overview-debug">최근 요청 상태를 불러오는 중이다.</div>
                  </section>
                </div>
              </section>
            </div>
          </section>

          <section class="admin-panel" id="admin-panel-debug" hidden>
            <div class="debug-grid">
              <aside class="side">
                <section class="card">
                  <h2 class="card-title">Filters</h2>
                  <div class="filter-grid">
            <div class="field span-2">
              <label for="filter-q">Search</label>
              <input class="input" id="filter-q" placeholder="path, request id, user agent, cf-ray" />
            </div>
            <div class="field">
              <label for="filter-kind">Type</label>
              <select class="select" id="filter-kind">
                <option value="">All</option>
                <option value="mcp">MCP</option>
                <option value="api">API</option>
                <option value="debug">Debug</option>
                <option value="page">Page</option>
                <option value="asset">Asset</option>
                <option value="health">Health</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div class="field">
              <label for="filter-method">Method</label>
              <select class="select" id="filter-method">
                <option value="">All</option>
                <option value="GET">GET</option>
                <option value="POST">POST</option>
                <option value="PUT">PUT</option>
                <option value="DELETE">DELETE</option>
              </select>
            </div>
            <div class="field">
              <label for="filter-status">Status</label>
              <select class="select" id="filter-status">
                <option value="">All</option>
                <option value="300">300+</option>
                <option value="400">400+</option>
                <option value="500">500+</option>
              </select>
            </div>
            <div class="field">
              <label for="filter-limit">Limit</label>
              <select class="select" id="filter-limit">
                <option value="25">25</option>
                <option value="50" selected>50</option>
                <option value="100">100</option>
                <option value="250">250</option>
                <option value="500">500</option>
              </select>
            </div>
            <div class="field">
              <label for="filter-sort">Sort</label>
              <select class="select" id="filter-sort">
                <option value="time">Time</option>
                <option value="kind">Type</option>
                <option value="status">Status</option>
                <option value="method">Method</option>
                <option value="duration">Duration</option>
              </select>
            </div>
            <div class="field">
              <label for="filter-order">Order</label>
              <select class="select" id="filter-order">
                <option value="desc">Newest / High</option>
                <option value="asc">Oldest / Low</option>
              </select>
            </div>
            <div class="field span-2">
              <label for="filter-request-id">Request ID</label>
              <input class="input" id="filter-request-id" placeholder="remote-mcp-test-..." />
            </div>
          </div>
                  <div class="actions">
                    <button class="button primary" id="refresh" type="button">Refresh</button>
                    <button class="button" id="reset" type="button">Reset</button>
                  </div>
                  <p class="status-line" id="load-status">필터를 조정하면 자동으로 다시 불러온다.</p>
                </section>
                <p class="footer-note">요청 본문과 bearer token은 저장하지 않는다. 쿼리 문자열의 token, access_token, api_key 값은 로그에 남기기 전에 가린다.</p>
              </aside>
              <section class="panel">
                <div class="metrics">
                  <div class="metric"><span>Shown</span><strong id="metric-shown">0</strong></div>
                  <div class="metric"><span>MCP</span><strong id="metric-mcp">0</strong></div>
                  <div class="metric"><span>Errors</span><strong id="metric-errors">0</strong></div>
                  <div class="metric"><span>Slowest</span><strong id="metric-slowest">0ms</strong></div>
                </div>
                <div class="list" id="request-list">
                  <div class="empty">관리자 토큰을 적용하면 최근 요청을 불러온다.</div>
                </div>
              </section>
            </div>
          </section>

          <section class="admin-panel" id="admin-panel-users" hidden>
            <section class="panel">
              <div class="list">
                <section class="card">
                  <h2 class="card-title">User Management</h2>
                  <div class="toolbar-row">
                    <input class="input" id="user-search" placeholder="username or nickname" />
                    <button class="button" id="users-refresh" type="button">Refresh Users</button>
                  </div>
                  <p class="status-line" id="users-status">사용자 목록을 불러오면 여기서 검색하고 확인할 수 있다.</p>
                </section>
                <div style="overflow:auto;">
                  <table class="data-table">
                    <thead>
                      <tr>
                        <th>Username</th>
                        <th>Nickname</th>
                        <th>Role</th>
                        <th>System</th>
                        <th>Updated</th>
                      </tr>
                    </thead>
                    <tbody id="users-table-body">
                      <tr><td colspan="5" class="locked-copy">관리자 토큰이 필요하다.</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          </section>

          <section class="admin-panel" id="admin-panel-roles" hidden>
            <div class="overview-grid">
              <aside class="side">
                <section class="card">
                  <h2 class="card-title">Role Update</h2>
                  <div class="inline-form">
                    <label class="field">
                      <span>Username</span>
                      <select class="select" id="role-user"></select>
                    </label>
                    <label class="field">
                      <span>Role</span>
                      <select class="select" id="role-value">
                        <option value="user">user</option>
                        <option value="manager">manager</option>
                        <option value="admin">admin</option>
                      </select>
                    </label>
                  </div>
                  <div class="actions">
                    <button class="button primary" id="role-save" type="button">Save Role</button>
                  </div>
                  <p class="status-line" id="roles-status">관리자만 역할을 바꿀 수 있다.</p>
                </section>
              </aside>
              <section class="panel">
                <div class="list">
                  <section class="card">
                    <h2 class="card-title">Current Roles</h2>
                    <div id="roles-summary" class="locked-copy">사용자 목록을 먼저 불러온다.</div>
                  </section>
                </div>
              </section>
            </div>
          </section>

          <section class="admin-panel" id="admin-panel-sagwan" hidden>
            <div class="overview-grid">
              <aside class="side">
                <section class="card">
                  <h2 class="card-title">Sagwan Settings</h2>
                  <div class="inline-form">
                    <label class="field">
                      <span>Provider</span>
                      <input class="input" id="librarian-provider" placeholder="codex-style or openai-compatible" />
                    </label>
                    <label class="field">
                      <span>Model</span>
                      <input class="input" id="librarian-model" placeholder="openai-codex/gpt-5.4" />
                    </label>
                    <label class="field">
                      <span>Base URL</span>
                      <input class="input" id="librarian-base-url" placeholder="optional" />
                    </label>
                    <label class="field">
                      <span>Reasoning</span>
                      <input class="input" id="librarian-reasoning" placeholder="medium" />
                    </label>
                  </div>
                  <div class="actions">
                    <button class="button primary" id="librarian-save" type="button">Save Settings</button>
                  </div>
                  <p class="status-line" id="librarian-save-status">사관 런타임 설정을 저장하면 다음 호출부터 적용된다.</p>
                </section>
              </aside>
              <section class="panel">
                <div class="list">
                  <section class="card">
                    <h2 class="card-title">Enabled Tools</h2>
                    <div class="tool-grid" id="librarian-tools-grid">
                      <div class="locked-copy">도구 구성을 불러오는 중이다.</div>
                    </div>
                  </section>
                  <section class="card">
                    <h2 class="card-title">Runtime Status</h2>
                    <div class="locked-copy" id="librarian-runtime-status">사관 상태를 불러오는 중이다.</div>
                  </section>
                </div>
              </section>
            </div>
          </section>

          <section class="admin-panel" id="admin-panel-busagwan" hidden>
            <div class="overview-grid">
              <aside class="side">
                <section class="card">
                  <h2 class="card-title">Busagwan Settings</h2>
                  <div class="inline-form">
                    <label class="field">
                      <span>Provider</span>
                      <input class="input" id="subordinate-provider" placeholder="ollama" />
                    </label>
                    <label class="field">
                      <span>Base URL</span>
                      <input class="input" id="subordinate-base-url" placeholder="http://127.0.0.1:11434" />
                    </label>
                    <label class="field">
                      <span>Model</span>
                      <input class="input" id="subordinate-model" placeholder="gemma4:e4b" />
                    </label>
                    <label class="field">
                      <span>Interval Sec</span>
                      <input class="input" id="subordinate-interval" type="number" min="60" step="60" />
                    </label>
                    <label class="field">
                      <span>Max Tasks Per Run</span>
                      <input class="input" id="subordinate-max-tasks" type="number" min="1" max="8" step="1" />
                    </label>
                  </div>
                  <div class="toolbar-row">
                    <label class="checkbox"><input id="subordinate-enabled" type="checkbox" /> <span>enabled</span></label>
                    <label class="checkbox"><input id="subordinate-auto-review" type="checkbox" /> <span>auto review publication</span></label>
                    <label class="checkbox"><input id="subordinate-auto-capsule-request" type="checkbox" /> <span>auto request capsule</span></label>
                  </div>
                  <div class="actions">
                    <button class="button primary" id="subordinate-save" type="button">Save Settings</button>
                    <button class="button" id="subordinate-run" type="button">Run Once</button>
                  </div>
                  <p class="status-line" id="subordinate-save-status">부사관 반복 작업 설정을 저장하고 수동 실행할 수 있다.</p>
                </section>
              </aside>
              <section class="panel">
                <div class="list">
                  <section class="card">
                    <h2 class="card-title">Runtime Status</h2>
                    <div class="locked-copy" id="subordinate-runtime-status">부사관 상태를 불러오는 중이다.</div>
                  </section>
                  <section class="card">
                    <h2 class="card-title">Queue</h2>
                    <div class="locked-copy" id="subordinate-queue-status">큐를 불러오는 중이다.</div>
                  </section>
                </div>
              </section>
            </div>
          </section>
        </section>
      </div>
    </main>
  </div>
  __SHARED_SHELL__
  <div class="modal-shell" id="request-modal" hidden>
    <div class="modal-backdrop" data-close-modal></div>
    <section class="modal" role="dialog" aria-modal="true" aria-labelledby="request-modal-title">
      <header class="modal-head">
        <div>
          <p class="brand-kicker">Request detail</p>
          <h2 class="modal-title" id="request-modal-title">Request</h2>
          <p class="status-line" id="request-modal-subtitle">요청과 응답 상세를 확인한다.</p>
        </div>
        <button class="icon-button" id="request-modal-close" type="button" aria-label="Close request detail">×</button>
      </header>
      <div class="modal-body" id="request-modal-body"></div>
    </section>
  </div>

  <script>
    (() => {
      const apiBase = __API_BASE_JSON__;
      const state = {
        panel: 'overview',
        timer: null,
        loading: false,
        status: null,
        events: [],
        users: [],
        librarian: null,
        subordinate: null,
      };
      const dom = {
        navButtons: [...document.querySelectorAll('[data-admin-nav]')],
        panels: {
          overview: document.getElementById('admin-panel-overview'),
          debug: document.getElementById('admin-panel-debug'),
          users: document.getElementById('admin-panel-users'),
          roles: document.getElementById('admin-panel-roles'),
          sagwan: document.getElementById('admin-panel-sagwan'),
          busagwan: document.getElementById('admin-panel-busagwan'),
        },
        refreshAll: document.getElementById('admin-refresh-all'),
        sessionStatus: document.getElementById('admin-session-status'),
        overviewLibrarian: document.getElementById('overview-librarian'),
        overviewDebug: document.getElementById('overview-debug'),
        overviewUsers: document.getElementById('metric-users'),
        overviewAdmins: document.getElementById('metric-admins'),
        overviewManagers: document.getElementById('metric-managers'),
        overviewTools: document.getElementById('metric-tools'),
        q: document.getElementById('filter-q'),
        kind: document.getElementById('filter-kind'),
        method: document.getElementById('filter-method'),
        statusMin: document.getElementById('filter-status'),
        limit: document.getElementById('filter-limit'),
        sort: document.getElementById('filter-sort'),
        order: document.getElementById('filter-order'),
        requestId: document.getElementById('filter-request-id'),
        refresh: document.getElementById('refresh'),
        reset: document.getElementById('reset'),
        loadStatus: document.getElementById('load-status'),
        list: document.getElementById('request-list'),
        shown: document.getElementById('metric-shown'),
        mcp: document.getElementById('metric-mcp'),
        errors: document.getElementById('metric-errors'),
        slowest: document.getElementById('metric-slowest'),
        modal: document.getElementById('request-modal'),
        modalTitle: document.getElementById('request-modal-title'),
        modalSubtitle: document.getElementById('request-modal-subtitle'),
        modalBody: document.getElementById('request-modal-body'),
        modalClose: document.getElementById('request-modal-close'),
        userSearch: document.getElementById('user-search'),
        usersRefresh: document.getElementById('users-refresh'),
        usersStatus: document.getElementById('users-status'),
        usersTableBody: document.getElementById('users-table-body'),
        roleUser: document.getElementById('role-user'),
        roleValue: document.getElementById('role-value'),
        roleSave: document.getElementById('role-save'),
        rolesStatus: document.getElementById('roles-status'),
        rolesSummary: document.getElementById('roles-summary'),
        librarianProvider: document.getElementById('librarian-provider'),
        librarianModel: document.getElementById('librarian-model'),
        librarianBaseUrl: document.getElementById('librarian-base-url'),
        librarianReasoning: document.getElementById('librarian-reasoning'),
        librarianToolsGrid: document.getElementById('librarian-tools-grid'),
        librarianSave: document.getElementById('librarian-save'),
        librarianSaveStatus: document.getElementById('librarian-save-status'),
        librarianRuntimeStatus: document.getElementById('librarian-runtime-status'),
        subordinateProvider: document.getElementById('subordinate-provider'),
        subordinateBaseUrl: document.getElementById('subordinate-base-url'),
        subordinateModel: document.getElementById('subordinate-model'),
        subordinateInterval: document.getElementById('subordinate-interval'),
        subordinateMaxTasks: document.getElementById('subordinate-max-tasks'),
        subordinateEnabled: document.getElementById('subordinate-enabled'),
        subordinateAutoReview: document.getElementById('subordinate-auto-review'),
        subordinateAutoCapsuleRequest: document.getElementById('subordinate-auto-capsule-request'),
        subordinateSave: document.getElementById('subordinate-save'),
        subordinateRun: document.getElementById('subordinate-run'),
        subordinateSaveStatus: document.getElementById('subordinate-save-status'),
        subordinateRuntimeStatus: document.getElementById('subordinate-runtime-status'),
        subordinateQueueStatus: document.getElementById('subordinate-queue-status'),
      };

      function token() {
        return window.closedAkashicUI?.getToken?.() || '';
      }

      function setAuthText(message, tone = 'muted') {
        dom.loadStatus.textContent = message;
        dom.loadStatus.dataset.tone = tone;
      }

      function setLoadText(message) {
        dom.loadStatus.textContent = message;
      }

      function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, (char) => (
          {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]
        ));
      }

      function stringify(value) {
        if (value === undefined || value === null || value === '') return '-';
        if (typeof value === 'string') return value || '-';
        try {
          return JSON.stringify(value, null, 2);
        } catch (error) {
          return String(value);
        }
      }

      function fmtTime(value) {
        if (!value) return '-';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return value;
        return date.toLocaleString('ko-KR', {
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        });
      }

      function statusTone(status) {
        const code = Number(status || 0);
        if (code >= 500) return 'error';
        if (code >= 400) return 'error';
        if (code >= 300) return 'warn';
        return 'ok';
      }

      function params() {
        const query = new URLSearchParams();
        query.set('limit', dom.limit.value || '50');
        query.set('sort_by', dom.sort.value || 'time');
        query.set('order', dom.order.value || 'desc');
        if (dom.q.value.trim()) query.set('q', dom.q.value.trim());
        if (dom.kind.value) query.set('kind', dom.kind.value);
        if (dom.method.value) query.set('method', dom.method.value);
        if (dom.statusMin.value) query.set('status_min', dom.statusMin.value);
        if (dom.requestId.value.trim()) query.set('request_id', dom.requestId.value.trim());
        return query;
      }

      function currentSession() {
        return window.closedAkashicUI?.getSession?.() || { authenticated: false, role: 'anonymous' };
      }

      function isAdminSession() {
        return Boolean(currentSession()?.authenticated && currentSession()?.role === 'admin');
      }

      function setPanel(next) {
        state.panel = ['overview', 'debug', 'users', 'roles', 'sagwan', 'busagwan'].includes(next) ? next : 'overview';
        dom.navButtons.forEach((button) => {
          button.classList.toggle('active', button.dataset.adminNav === state.panel);
        });
        Object.entries(dom.panels).forEach(([key, panel]) => {
          if (!panel) return;
          panel.hidden = key !== state.panel;
        });
      }

      async function fetchJson(path, options = {}) {
        if (window.closedAkashicUI?.requestJson) {
          return window.closedAkashicUI.requestJson(path, options);
        }
        const request = { mode: 'cors', method: options.method || 'GET', headers: options.headers || {} };
        if (options.json !== undefined) {
          request.headers = { ...request.headers, 'Content-Type': 'application/json' };
          request.body = JSON.stringify(options.json);
        }
        const response = await fetch(`${apiBase}${path}`, request);
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`.trim());
        return response.json();
      }

      function renderMetrics(events) {
        const mcpCount = events.filter((event) => event.kind === 'mcp').length;
        const errorCount = events.filter((event) => Number(event.status || 0) >= 400).length;
        const slowest = events.reduce((max, event) => Math.max(max, Number(event.duration_ms || 0)), 0);
        dom.shown.textContent = String(events.length);
        dom.mcp.textContent = String(mcpCount);
        dom.errors.textContent = String(errorCount);
        dom.slowest.textContent = `${Math.round(slowest)}ms`;
      }

      function renderList(events) {
        if (!events.length) {
          dom.list.innerHTML = '<div class="empty">조건에 맞는 요청이 없다.</div>';
          return;
        }
        dom.list.innerHTML = events.map((event, index) => {
          const kind = escapeHtml(event.kind || 'other');
          const query = event.query ? `?${event.query}` : '';
          const detailParts = [
            event.request_id ? `id ${event.request_id}` : '',
            event.client ? `client ${event.client}` : '',
            event.cf_ray ? `cf ${event.cf_ray}` : '',
            event.error ? `error ${event.error}` : '',
          ].filter(Boolean);
          const agent = event.user_agent ? `<div class="details">${escapeHtml(event.user_agent)}</div>` : '';
          return `
            <article class="request" data-index="${index}" role="button" tabindex="0" aria-label="Open request detail">
              <div class="time">${escapeHtml(fmtTime(event.ts))}</div>
              <div><span class="badge kind-${kind}">${kind}</span></div>
              <div class="path">
                ${escapeHtml(event.method || '')} ${escapeHtml(event.path || '')}${escapeHtml(query)}
                <div class="details">${escapeHtml(detailParts.join(' · ') || 'no request metadata')}</div>
                ${agent}
              </div>
              <div><span class="badge ${statusTone(event.status)}">${escapeHtml(event.status || '-')}</span></div>
              <div class="duration">${escapeHtml(event.duration_ms ?? 0)}ms</div>
            </article>
          `;
        }).join('');
      }

      function bodyText(snapshot) {
        if (!snapshot) return '-';
        const parts = [];
        if (snapshot.content_type) parts.push(`content-type: ${snapshot.content_type}`);
        parts.push(`captured-bytes: ${snapshot.size ?? 0}${snapshot.truncated ? ' (truncated)' : ''}`);
        if (snapshot.skipped) parts.push('body skipped');
        if (snapshot.text) parts.push('', snapshot.text);
        return parts.join('\\n');
      }

      function detailBox(label, value) {
        return `<div class="detail-box"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
      }

      function payloadCard(title, value) {
        return `
          <section class="payload-card">
            <h3>${escapeHtml(title)}</h3>
            <pre class="pretext">${escapeHtml(value)}</pre>
          </section>
        `;
      }

      function openRequestDetail(event) {
        const query = event.query ? `?${event.query}` : '';
        const title = `${event.method || ''} ${event.path || ''}${query}`.trim() || 'Request';
        dom.modalTitle.textContent = title;
        dom.modalSubtitle.textContent = `${event.request_id || '-'} · ${fmtTime(event.ts)} · ${event.duration_ms ?? 0}ms`;
        dom.modalBody.innerHTML = `
          <div class="detail-grid">
            ${detailBox('Status', event.status || '-')}
            ${detailBox('Type', event.kind || 'other')}
            ${detailBox('Client', event.client || '-')}
            ${detailBox('CF-Ray', event.cf_ray || '-')}
            ${detailBox('Host', event.host || '-')}
            ${detailBox('Referer', event.referer || '-')}
            ${detailBox('Bytes', event.response_bytes ?? 0)}
            ${detailBox('Error', event.error || '-')}
          </div>
          <div class="payload-grid">
            ${payloadCard('Request headers', stringify(event.request?.headers))}
            ${payloadCard('Response headers', stringify(event.response?.headers))}
            ${payloadCard('Request body', bodyText(event.request?.body))}
            ${payloadCard('Response body', bodyText(event.response?.body))}
          </div>
          ${payloadCard('User agent', event.user_agent || '-')}
        `;
        dom.modal.hidden = false;
      }

      function closeRequestDetail() {
        dom.modal.hidden = true;
      }

      function renderStatus(status) {
        state.status = status;
        const obs = status?.observability || {};
        const logState = obs.log_file_exists ? 'request log ready' : 'request log not found';
        setAuthText(`Unlocked. ${logState}. recent buffer ${obs.recent_count ?? 0}/${obs.recent_capacity ?? '-'}.`, 'ok');
        if (dom.overviewDebug) {
          dom.overviewDebug.textContent = `request log ${logState}, recent buffer ${obs.recent_count ?? 0}/${obs.recent_capacity ?? '-'}.`;
        }
      }

      async function refresh() {
        if (!isAdminSession()) {
          setAuthText('관리자 로그인 뒤 디버그 요청을 볼 수 있다.', 'warn');
          setLoadText('Locked.');
          renderMetrics([]);
          renderList([]);
          return;
        }
        if (state.loading) return;
        state.loading = true;
        dom.refresh.disabled = true;
        setLoadText('Loading recent requests...');
        try {
          const [status, recent] = await Promise.all([
            fetchJson('/api/debug/status'),
            fetchJson(`/api/debug/recent-requests?${params().toString()}`),
          ]);
          state.events = recent.events || [];
          renderStatus(status);
          renderMetrics(state.events);
          renderList(state.events);
          setLoadText(`Updated ${fmtTime(new Date().toISOString())}.`);
        } catch (error) {
          setAuthText(`접근 실패: ${error.message}`, 'error');
          setLoadText('토큰이나 서버 로그 상태를 확인한다.');
          renderMetrics([]);
          renderList([]);
        } finally {
          state.loading = false;
          dom.refresh.disabled = false;
        }
      }

      function scheduleRefresh() {
        window.clearTimeout(state.timer);
        state.timer = window.setTimeout(refresh, 180);
      }

      function resetFilters() {
        dom.q.value = '';
        dom.kind.value = '';
        dom.method.value = '';
        dom.statusMin.value = '';
        dom.limit.value = '50';
        dom.sort.value = 'time';
        dom.order.value = 'desc';
        dom.requestId.value = '';
        refresh();
      }

      function renderUsers() {
        const q = String(dom.userSearch?.value || '').trim().toLowerCase();
        const rows = state.users.filter((user) => {
          const haystack = [user.username, user.nickname, user.role].join(' ').toLowerCase();
          return !q || haystack.includes(q);
        });
        if (!rows.length) {
          dom.usersTableBody.innerHTML = '<tr><td colspan="5" class="locked-copy">표시할 사용자가 없다.</td></tr>';
          return;
        }
        dom.usersTableBody.innerHTML = rows.map((user) => `
          <tr>
            <td>${escapeHtml(user.username)}</td>
            <td>${escapeHtml(user.nickname)}</td>
            <td><span class="badge">${escapeHtml(user.role)}</span></td>
            <td>${user.system ? 'yes' : 'no'}</td>
            <td>${escapeHtml(fmtTime(user.updated_at))}</td>
          </tr>
        `).join('');
      }

      function syncRoleControls() {
        const options = state.users.map((user) => `<option value="${escapeHtml(user.username)}">${escapeHtml(user.username)} (${escapeHtml(user.nickname)})</option>`).join('');
        if (dom.roleUser) dom.roleUser.innerHTML = options;
        const adminCount = state.users.filter((user) => user.role === 'admin').length;
        const managerCount = state.users.filter((user) => user.role === 'manager').length;
        if (dom.rolesSummary) {
          dom.rolesSummary.textContent = `전체 ${state.users.length}명, admin ${adminCount}명, manager ${managerCount}명, user ${Math.max(0, state.users.length - adminCount - managerCount)}명`;
        }
        if (dom.overviewUsers) dom.overviewUsers.textContent = String(state.users.length);
        if (dom.overviewAdmins) dom.overviewAdmins.textContent = String(adminCount);
        if (dom.overviewManagers) dom.overviewManagers.textContent = String(managerCount);
      }

      async function refreshUsers() {
        if (!isAdminSession()) {
          dom.usersStatus.textContent = '관리자 로그인 뒤 사용자 목록을 볼 수 있다.';
          dom.usersTableBody.innerHTML = '<tr><td colspan="5" class="locked-copy">관리자 토큰이 필요하다.</td></tr>';
          return;
        }
        try {
          const data = await fetchJson('/api/admin/users');
          state.users = data.users || [];
          dom.usersStatus.textContent = `${state.users.length}명의 사용자를 불러왔다.`;
          renderUsers();
          syncRoleControls();
        } catch (error) {
          dom.usersStatus.textContent = error.message;
          dom.usersTableBody.innerHTML = '<tr><td colspan="5" class="locked-copy">사용자 목록을 불러오지 못했다.</td></tr>';
        }
      }

      async function saveRole() {
        if (!isAdminSession()) {
          dom.rolesStatus.textContent = '관리자 로그인 뒤 역할을 바꿀 수 있다.';
          return;
        }
        try {
          const username = dom.roleUser?.value || '';
          const role = dom.roleValue?.value || 'user';
          if (!username) throw new Error('먼저 사용자를 선택해줘.');
          await fetchJson('/api/admin/users/role', {
            method: 'POST',
            json: { username, role },
          });
          dom.rolesStatus.textContent = `${username} 역할을 ${role}로 저장했다.`;
          await refreshUsers();
        } catch (error) {
          dom.rolesStatus.textContent = error.message;
        }
      }

      function selectedLibrarianTools() {
        return [...document.querySelectorAll('[data-librarian-tool]')].filter((input) => input.checked).map((input) => input.value);
      }

      function renderLibrarian(settings, status) {
        state.librarian = { settings, status };
        if (dom.librarianProvider) dom.librarianProvider.value = settings.provider || '';
        if (dom.librarianModel) dom.librarianModel.value = settings.model || '';
        if (dom.librarianBaseUrl) dom.librarianBaseUrl.value = settings.base_url || '';
        if (dom.librarianReasoning) dom.librarianReasoning.value = settings.reasoning_effort || '';
        const availableTools = status?.available_tools || [];
        dom.librarianToolsGrid.innerHTML = availableTools.map((tool) => `
          <label class="checkbox">
            <input type="checkbox" data-librarian-tool value="${escapeHtml(tool)}" ${settings.enabled_tools?.includes(tool) ? 'checked' : ''} />
            <span>${escapeHtml(tool)}</span>
          </label>
        `).join('');
        if (dom.librarianRuntimeStatus) {
          dom.librarianRuntimeStatus.textContent = `provider=${status.provider || '-'} · model=${status.model || '-'} · tools=${(status.tools || []).join(', ') || '-'}`;
        }
        if (dom.overviewLibrarian) {
          dom.overviewLibrarian.textContent = `provider=${status.provider || '-'} · model=${status.model || '-'} · tools=${(status.tools || []).join(', ') || '-'}`;
        }
        if (dom.overviewTools) {
          dom.overviewTools.textContent = String((status.tools || []).length);
        }
      }

      async function refreshLibrarian() {
        if (!isAdminSession()) {
          if (dom.librarianRuntimeStatus) dom.librarianRuntimeStatus.textContent = '관리자 로그인 뒤 사관 설정을 볼 수 있다.';
          if (dom.overviewLibrarian) dom.overviewLibrarian.textContent = '관리자 세션이 활성화되면 사관 런타임을 확인할 수 있다.';
          return;
        }
        try {
          const data = await fetchJson('/api/admin/librarian');
          renderLibrarian(data.settings || {}, data.status || {});
        } catch (error) {
          if (dom.librarianRuntimeStatus) dom.librarianRuntimeStatus.textContent = error.message;
        }
      }

      async function saveLibrarian() {
        if (!isAdminSession()) {
          dom.librarianSaveStatus.textContent = '관리자 로그인 뒤 사관 설정을 저장할 수 있다.';
          return;
        }
        try {
          const data = await fetchJson('/api/admin/librarian', {
            method: 'POST',
            json: {
              provider: dom.librarianProvider?.value.trim() || '',
              model: dom.librarianModel?.value.trim() || '',
              base_url: dom.librarianBaseUrl?.value.trim() || '',
              reasoning_effort: dom.librarianReasoning?.value.trim() || '',
              enabled_tools: selectedLibrarianTools(),
            },
          });
          dom.librarianSaveStatus.textContent = '사관 설정을 저장했다.';
          renderLibrarian(data.settings || {}, data.status || {});
        } catch (error) {
          dom.librarianSaveStatus.textContent = error.message;
        }
      }

      function renderSubordinate(settings, status) {
        state.subordinate = { settings, status };
        if (dom.subordinateProvider) dom.subordinateProvider.value = settings.provider || '';
        if (dom.subordinateBaseUrl) dom.subordinateBaseUrl.value = settings.base_url || '';
        if (dom.subordinateModel) dom.subordinateModel.value = settings.model || '';
        if (dom.subordinateInterval) dom.subordinateInterval.value = settings.interval_sec || 900;
        if (dom.subordinateMaxTasks) dom.subordinateMaxTasks.value = settings.max_tasks_per_run || 2;
        if (dom.subordinateEnabled) dom.subordinateEnabled.checked = Boolean(settings.enabled);
        if (dom.subordinateAutoReview) dom.subordinateAutoReview.checked = Boolean(settings.auto_review_publication_requests);
        if (dom.subordinateAutoCapsuleRequest) dom.subordinateAutoCapsuleRequest.checked = Boolean(settings.auto_request_publication_for_capsules);
        const queue = status?.queue || {};
        if (dom.subordinateRuntimeStatus) {
          dom.subordinateRuntimeStatus.textContent = `provider=${settings.provider || '-'} · model=${settings.model || '-'} · interval=${settings.interval_sec || '-'}s`;
        }
        if (dom.subordinateQueueStatus) {
          dom.subordinateQueueStatus.textContent = `pending=${queue.pending ?? 0} · running=${queue.running ?? 0} · done=${queue.done ?? 0} · failed=${queue.failed ?? 0}`;
        }
      }

      async function refreshSubordinate() {
        if (!isAdminSession()) {
          if (dom.subordinateRuntimeStatus) dom.subordinateRuntimeStatus.textContent = '관리자 로그인 뒤 부사관 설정을 볼 수 있다.';
          if (dom.subordinateQueueStatus) dom.subordinateQueueStatus.textContent = '관리자 세션이 활성화되면 큐를 확인할 수 있다.';
          return;
        }
        try {
          const data = await fetchJson('/api/admin/subordinate');
          renderSubordinate(data.settings || {}, data.status || {});
        } catch (error) {
          if (dom.subordinateRuntimeStatus) dom.subordinateRuntimeStatus.textContent = error.message;
        }
      }

      async function saveSubordinate() {
        if (!isAdminSession()) {
          dom.subordinateSaveStatus.textContent = '관리자 로그인 뒤 부사관 설정을 저장할 수 있다.';
          return;
        }
        try {
          const data = await fetchJson('/api/admin/subordinate', {
            method: 'POST',
            json: {
              provider: dom.subordinateProvider?.value.trim() || '',
              base_url: dom.subordinateBaseUrl?.value.trim() || '',
              model: dom.subordinateModel?.value.trim() || '',
              enabled: Boolean(dom.subordinateEnabled?.checked),
              interval_sec: Number(dom.subordinateInterval?.value || 900),
              max_tasks_per_run: Number(dom.subordinateMaxTasks?.value || 2),
              auto_review_publication_requests: Boolean(dom.subordinateAutoReview?.checked),
              auto_request_publication_for_capsules: Boolean(dom.subordinateAutoCapsuleRequest?.checked),
            },
          });
          dom.subordinateSaveStatus.textContent = '부사관 설정을 저장했다.';
          renderSubordinate(data.settings || {}, data.status || {});
        } catch (error) {
          dom.subordinateSaveStatus.textContent = error.message;
        }
      }

      async function runSubordinate() {
        if (!isAdminSession()) {
          dom.subordinateSaveStatus.textContent = '관리자 로그인 뒤 부사관을 실행할 수 있다.';
          return;
        }
        try {
          const data = await fetchJson('/api/admin/subordinate/run', { method: 'POST' });
          dom.subordinateSaveStatus.textContent = `수동 실행 완료: ${(data.processed || []).length}개 처리`;
          await refreshSubordinate();
        } catch (error) {
          dom.subordinateSaveStatus.textContent = error.message;
        }
      }

      async function refreshAll() {
        const session = currentSession();
        dom.sessionStatus.textContent = session?.authenticated
          ? `${session.nickname || session.username} (${session.role}) 세션이 연결되어 있다.`
          : '지금은 익명 상태다. 관리자 계정으로 로그인하면 관리 기능이 열린다.';
        await Promise.all([refresh(), refreshUsers(), refreshLibrarian(), refreshSubordinate()]);
      }

      dom.refresh.addEventListener('click', refresh);
      dom.reset.addEventListener('click', resetFilters);
      dom.navButtons.forEach((button) => button.addEventListener('click', () => setPanel(button.dataset.adminNav || 'overview')));
      dom.refreshAll?.addEventListener('click', refreshAll);
      dom.list.addEventListener('click', (event) => {
        const item = event.target.closest('.request');
        if (!item) return;
        const index = Number(item.dataset.index);
        if (Number.isInteger(index) && state.events[index]) openRequestDetail(state.events[index]);
      });
      dom.list.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        const item = event.target.closest('.request');
        if (!item) return;
        event.preventDefault();
        const index = Number(item.dataset.index);
        if (Number.isInteger(index) && state.events[index]) openRequestDetail(state.events[index]);
      });
      dom.modalClose.addEventListener('click', closeRequestDetail);
      document.querySelectorAll('[data-close-modal]').forEach((element) => {
        element.addEventListener('click', closeRequestDetail);
      });
      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !dom.modal.hidden) closeRequestDetail();
      });
      document.addEventListener('closed-akashic-auth-change', refreshAll);
      [dom.q, dom.kind, dom.method, dom.statusMin, dom.limit, dom.sort, dom.order, dom.requestId]
        .forEach((element) => element.addEventListener('input', scheduleRefresh));
      dom.userSearch?.addEventListener('input', renderUsers);
      dom.usersRefresh?.addEventListener('click', refreshUsers);
      dom.roleSave?.addEventListener('click', saveRole);
      dom.librarianSave?.addEventListener('click', saveLibrarian);
      dom.subordinateSave?.addEventListener('click', saveSubordinate);
      dom.subordinateRun?.addEventListener('click', runSubordinate);

      setPanel('overview');
      refreshAll();
    })();
  </script>
</body>
</html>"""
    return (
        template.replace("__SHARED_STYLES__", shared_styles)
        .replace("__SHARED_HEADER__", shared_header)
        .replace("__SHARED_SHELL__", shared_shell)
        .replace("__API_BASE_JSON__", api_base_json)
    )


def _explorer_html(notes: list[ClosedNote], current_slug: str, route_prefix: str) -> str:
    tree = _build_explorer_tree(notes)
    return _render_explorer_nodes(tree, current_slug, route_prefix, depth=0, prefix=())


def _note_payload(note: ClosedNote, notes: list[ClosedNote], route_prefix: str) -> dict[str, Any]:
    route_prefix = _normalize_prefix(route_prefix)
    lookup = _note_lookup(notes)
    related_notes = []
    for related in note.related:
        target = _resolve_note_reference(related, lookup)
        if target:
            related_notes.append(_note_link_payload(target, route_prefix))

    backlinks = []
    for other in notes:
        if other.slug == note.slug:
            continue
        referenced = False
        for target_name in [*other.links, *other.related]:
            target = _resolve_note_reference(target_name, lookup)
            if target and target.slug == note.slug:
                referenced = True
                break
        if referenced:
            backlinks.append(_note_link_payload(other, route_prefix))

    return {
        "path": note.path,
        "slug": note.slug,
        "title": note.title,
        "kind": note.kind,
        "project": note.project,
        "status": note.status,
        "owner": note.owner,
        "visibility": note.visibility,
        "publication_status": note.publication_status,
        "tags": note.tags,
        "related": note.related,
        "summary": note.summary,
        "body": note.body,
        "body_html": _render_markdown(note.body, lookup, route_prefix),
        "links": note.links,
        "related_notes": related_notes,
        "backlinks": sorted(backlinks, key=lambda item: item["title"]),
        "outbound": len(note.links) + len(note.related),
        "href": _note_href(note.slug, route_prefix),
    }


def _note_link_payload(note: ClosedNote, route_prefix: str) -> dict[str, str]:
    return {
        "slug": note.slug,
        "title": note.title,
        "summary": note.summary,
        "href": _note_href(note.slug, route_prefix),
    }


def _link_list_html(items: list[dict[str, str]], title: str, route_prefix: str) -> str:
    route_prefix = _normalize_prefix(route_prefix)
    if not items:
        return ""
    cards = "".join(
        f'<a class="note-card" href="{html.escape(item["href"])}"><strong>{html.escape(item["title"])}</strong><small>{html.escape(item["summary"] or "")}</small></a>'
        for item in items
    )
    return f'<section class="meta-section" data-meta-panel="links"><h3 class="meta-title">{html.escape(title)}</h3><div class="note-list">{cards}</div></section>'


def _note_lookup(notes: list[ClosedNote]) -> dict[str, ClosedNote]:
    lookup: dict[str, ClosedNote] = {}
    for note in notes:
        lookup[note.slug.lower()] = note
        lookup[note.title.lower()] = note
        lookup[note.path.lower()] = note
        lookup[Path(note.path).stem.lower()] = note
    return lookup


def _resolve_note_reference(value: str, lookup: dict[str, ClosedNote]) -> ClosedNote | None:
    return lookup.get(value.lower()) or lookup.get(_slugify(value).lower())


def _render_markdown(body: str, lookup: dict[str, ClosedNote], route_prefix: str) -> str:
    route_prefix = _normalize_prefix(route_prefix)

    def replace_embed(match: re.Match[str]) -> str:
        raw_target = (match.group(1) or "").strip()
        alt = (match.group(2) or "").strip() or Path(raw_target).stem or "image"
        suffix = Path(raw_target).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}:
            src = file_href(raw_target, route_prefix)
            return f'<img class="note-image" src="{html.escape(src)}" alt="{html.escape(alt)}" loading="lazy" />'
        target = _resolve_note_reference(raw_target, lookup)
        if not target:
            return f'<span class="missing-link">{html.escape(alt)}</span>'
        return f'[{alt}]({_note_href(target.slug, route_prefix)})'

    def replace(match: re.Match[str]) -> str:
        target_name = (match.group(1) or "").strip()
        alias = (match.group(3) or "").strip() or target_name
        target = _resolve_note_reference(target_name, lookup)
        if not target:
            return f'<span class="missing-link">{html.escape(alias)}</span>'
        return f'[{alias}]({_note_href(target.slug, route_prefix)})'

    text = EMBED_LINK_PATTERN.sub(replace_embed, body)
    text = WIKI_LINK_PATTERN.sub(replace, text)
    text = MARKDOWN_IMAGE_PATTERN.sub(lambda match: _rewrite_markdown_image(match, route_prefix), text)
    return markdown.markdown(
        text,
        extensions=["extra", "fenced_code", "tables", "sane_lists"],
        output_format="html5",
    )


def _load_notes() -> list[ClosedNote]:
    root = Path(get_settings().closed_akashic_path).resolve()
    if not root.exists():
        return []
    notes = []
    for relative_path in list_note_paths():
        path = root / relative_path
        if path.is_file():
            notes.append(_parse_note(root, path))
    return _ensure_unique_slugs(notes)


def _parse_note(root: Path, path: Path) -> ClosedNote:
    raw = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw)
    rel_path = path.relative_to(root).as_posix()
    title = str(frontmatter.get("title") or path.stem)
    return ClosedNote(
        path=rel_path,
        slug=_slugify(path.stem),
        title=title,
        kind=normalize_kind(str(frontmatter.get("kind") or "reference")),
        project=str(frontmatter.get("project") or "openakashic"),
        status=str(frontmatter.get("status") or "draft"),
        owner=str(frontmatter.get("owner") or get_settings().default_note_owner),
        visibility=str(frontmatter.get("visibility") or get_settings().default_note_visibility),
        publication_status=str(frontmatter.get("publication_status") or "none"),
        tags=_as_list(frontmatter.get("tags")),
        related=_as_list(frontmatter.get("related")),
        summary=_extract_summary(body),
        body=body.strip(),
        links=sorted(set(match.group(1).strip() for match in WIKI_LINK_PATTERN.finditer(body))),
    )


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---\n"):
        return {}, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw
    return _parse_yamlish(parts[1]), parts[2]


def _parse_yamlish(value: str) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for line in value.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            output[key.strip()] = [item.strip().strip("\"'") for item in raw[1:-1].split(",") if item.strip()]
        else:
            output[key.strip()] = raw.strip("\"'")
    return output


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _extract_summary(body: str) -> str:
    marker = "## Summary"
    if marker not in body:
        first = next((line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")), "")
        return _summary_text(first)[:220]
    after = body.split(marker, 1)[1]
    lines = []
    for line in after.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if stripped:
            lines.append(stripped)
    return _summary_text(" ".join(lines))[:260]


def _summary_text(value: str) -> str:
    cleaned = MARKDOWN_IMAGE_PATTERN.sub(lambda match: (match.group(1) or "").strip(), value)
    cleaned = EMBED_LINK_PATTERN.sub("", cleaned)
    cleaned = WIKI_LINK_PATTERN.sub(lambda match: (match.group(3) or match.group(1) or "").strip(), cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"[#>*_~]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣ぁ-んァ-ン一-龥]+", "-", value.strip()).strip("-").lower()
    return slug or "note"


def _empty_note() -> ClosedNote:
    return ClosedNote(
        path="README.md",
        slug="readme",
        title="OpenAkashic",
        kind="index",
        project="openakashic",
        status="empty",
        owner=get_settings().default_note_owner,
        visibility=get_settings().default_note_visibility,
        publication_status="none",
        tags=[],
        related=[],
        summary="아직 노트가 없습니다.",
        body="## Summary\nOpenAkashic vault is empty.",
        links=[],
    )


def _ensure_unique_slugs(notes: list[ClosedNote]) -> list[ClosedNote]:
    seen: dict[str, int] = {}
    for note in notes:
        key = note.slug
        if key not in seen:
            seen[key] = 1
            continue
        seen[key] += 1
        note.slug = _slugify(Path(note.path).with_suffix("").as_posix())
    return notes


def _normalize_prefix(route_prefix: str) -> str:
    value = route_prefix.strip()
    if not value:
        return ""
    return "/" + value.strip("/")


def _root_href(route_prefix: str) -> str:
    route_prefix = _normalize_prefix(route_prefix)
    return route_prefix or "/"


def _graph_href(route_prefix: str) -> str:
    route_prefix = _normalize_prefix(route_prefix)
    return f"{route_prefix}/graph" if route_prefix else "/graph"


def _debug_href(route_prefix: str) -> str:
    route_prefix = _normalize_prefix(route_prefix)
    return f"{route_prefix}/admin" if route_prefix else "/admin"


def _graph_data_href(route_prefix: str) -> str:
    route_prefix = _normalize_prefix(route_prefix)
    return f"{route_prefix}/graph-data" if route_prefix else "/graph-data"


def _search_href(route_prefix: str) -> str:
    route_prefix = _normalize_prefix(route_prefix)
    return f"{route_prefix}/search" if route_prefix else "/search"


def _notes_base(route_prefix: str) -> str:
    route_prefix = _normalize_prefix(route_prefix)
    return f"{route_prefix}/notes" if route_prefix else "/notes"


def _note_href(slug: str, route_prefix: str) -> str:
    return f"{_notes_base(route_prefix)}/{slug}"


def _build_explorer_tree(notes: list[ClosedNote]) -> dict[str, Any]:
    root: dict[str, Any] = {"folders": {}, "notes": []}
    ordered = sorted(notes, key=lambda item: (item.path.lower() != "readme.md", item.path.lower()))
    for note in ordered:
        parts = list(Path(note.path).parts)
        cursor = root
        for folder in parts[:-1]:
            cursor = cursor["folders"].setdefault(folder, {"folders": {}, "notes": []})
        cursor["notes"].append(note)
    return root


def _render_explorer_nodes(
    tree: dict[str, Any],
    current_slug: str,
    route_prefix: str,
    depth: int,
    prefix: tuple[str, ...],
) -> str:
    blocks: list[str] = []

    for note in tree["notes"]:
        blocks.append(
            f'<a class="nav-link{" active" if note.slug == current_slug else ""}" '
            f'data-title="{html.escape((note.title + " " + note.path).lower())}" '
            f'data-path="{html.escape(note.path)}" '
            f'href="{html.escape(_note_href(note.slug, route_prefix))}">'
            f'<span>{html.escape(note.title)}</span>'
            f'<small style="display:block;color:var(--muted);font-size:11px;margin-top:3px;">{html.escape(note.path)}</small>'
            f"</a>"
        )

    for folder, subtree in sorted(tree["folders"].items(), key=lambda item: item[0].lower()):
        folder_path = "/".join((*prefix, folder))
        body = _render_explorer_nodes(subtree, current_slug, route_prefix, depth + 1, (*prefix, folder))
        if not body:
            continue
        open_attr = " open" if _tree_contains_slug(subtree, current_slug) else ""
        label = _folder_label(folder)
        blocks.append(
            f'<details class="folder-group" data-folder="{html.escape(folder.lower())}" data-path="{html.escape(folder_path)}" style="--depth:{depth};"{open_attr}>'
            f'<summary class="folder-summary"><span class="folder-caret">▸</span><span>{html.escape(label)}</span></summary>'
            f'<div class="folder-children">{body}</div>'
            f"</details>"
        )

    return "".join(blocks)


def _path_breadcrumb_html(path: str) -> str:
    parts = [part for part in Path(path).parts if part]
    if not parts:
        return ""
    segments: list[str] = []
    for index, part in enumerate(parts):
        item_path = "/".join(parts[: index + 1])
        kind = "file" if index == len(parts) - 1 else "folder"
        if index:
            segments.append('<span class="path-separator">/</span>')
        segments.append(
            f'<button class="path-segment" type="button" data-kind="{kind}" data-path="{html.escape(item_path)}">'
            f"{html.escape(part)}"
            "</button>"
        )
    return "".join(segments)


def _tree_contains_slug(tree: dict[str, Any], slug: str) -> bool:
    for note in tree["notes"]:
        if note.slug == slug:
            return True
    return any(_tree_contains_slug(subtree, slug) for subtree in tree["folders"].values())


def _folder_label(folder: str) -> str:
    aliases = {
        "doc": "Docs",
        "general": "General",
        "agents": "Agents",
        "reference": "Reference",
        "personal_vault": "Vault",
        "shared": "Shared",
        "personal": "Personal",
        "projects": "Projects",
        "company": "Company",
        "openakashic": "OpenAkashic",
        "ichimozzi": "IchiMozzi",
        "playbooks": "Playbooks",
        "schemas": "Schemas",
        "concepts": "Concepts",
        "architecture": "Architecture",
    }
    if folder in aliases:
        return aliases[folder]
    return folder.replace("_", " ").replace("-", " ").title()


def _json_script_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def _shared_ui_styles() -> str:
    return """
    :root {
      --closed-header-height: 66px;
    }
    body.closed-with-header {
      padding-top: var(--closed-header-height);
    }
    [data-admin-only][hidden] {
      display: none !important;
    }
    .global-header {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      z-index: 90;
      display: grid;
      grid-template-columns: auto 1fr auto;
      align-items: center;
      gap: 14px;
      min-height: var(--closed-header-height);
      padding: 10px clamp(14px, 3vw, 28px);
      border-bottom: 1px solid rgba(215, 226, 239, .82);
      background: rgba(248, 250, 252, .86);
      backdrop-filter: blur(18px);
      box-shadow: 0 12px 32px rgba(15, 23, 42, .06);
    }
    .global-brand {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
      color: var(--ink);
      font-weight: 800;
      letter-spacing: -.01em;
    }
    .global-brand-mark {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border-radius: 10px;
      background: linear-gradient(135deg, rgba(37,99,235,.16), rgba(15,118,110,.16));
      color: var(--accent);
      font-size: .85rem;
      font-weight: 900;
    }
    .global-brand-copy {
      display: grid;
      gap: 2px;
      min-width: 0;
    }
    .global-brand-title {
      font-size: .92rem;
      line-height: 1;
    }
    .global-brand-subtitle {
      color: var(--muted);
      font-size: .72rem;
      line-height: 1;
      letter-spacing: .06em;
      text-transform: uppercase;
    }
    .global-nav {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      flex-wrap: wrap;
    }
    .global-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      min-width: 0;
      flex-wrap: wrap;
    }
    .global-pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 36px;
      padding: 0 12px;
      border-radius: 10px;
      border: 1px solid transparent;
      background: transparent;
      color: var(--muted);
      font: inherit;
      font-size: .83rem;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
      transition: background .16s ease, border-color .16s ease, color .16s ease, transform .16s ease;
    }
    .global-pill:hover {
      background: rgba(255,255,255,.92);
      border-color: var(--line);
      color: var(--ink);
      text-decoration: none;
      transform: translateY(-1px);
    }
    .global-pill.is-primary {
      background: rgba(37, 99, 235, .10);
      border-color: rgba(37, 99, 235, .18);
      color: var(--accent);
    }
    body.inline-editing .global-pill[data-edit-view="edit"] {
      display: none !important;
    }
    body:not(.inline-editing) .global-pill[data-edit-view="save"] {
      display: none !important;
    }
    .global-auth-button[data-tone="admin"] {
      background: rgba(15,118,110,.10);
      border-color: rgba(15,118,110,.22);
      color: var(--accent-2);
    }
    .global-auth-button[data-tone="warn"] {
      background: rgba(234,88,12,.10);
      border-color: rgba(234,88,12,.20);
      color: #c2410c;
    }
    .global-auth-button[data-tone="user"] {
      background: rgba(37,99,235,.10);
      border-color: rgba(37,99,235,.20);
      color: var(--accent);
    }
    .auth-identity {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }
    .auth-avatar {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 30px;
      height: 30px;
      border-radius: 999px;
      background: rgba(37,99,235,.14);
      color: var(--accent);
      font-size: .78rem;
      font-weight: 900;
      flex: 0 0 30px;
    }
    .auth-meta {
      display: grid;
      gap: 2px;
      min-width: 0;
      text-align: left;
    }
    .auth-meta strong,
    .auth-meta small {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      line-height: 1.1;
    }
    .auth-meta small {
      color: var(--muted);
      font-size: .68rem;
      font-weight: 700;
      letter-spacing: .04em;
      text-transform: uppercase;
    }
    .global-modal[hidden] {
      display: none;
    }
    .global-modal {
      position: fixed;
      inset: 0;
      z-index: 120;
      display: grid;
      place-items: center;
      padding: 18px;
    }
    .global-modal-backdrop {
      position: absolute;
      inset: 0;
      background: rgba(15, 23, 42, .32);
      backdrop-filter: blur(8px);
    }
    .global-modal-card {
      position: relative;
      width: min(480px, 100%);
      padding: 22px;
      border-radius: 16px;
      border: 1px solid rgba(215, 226, 239, .9);
      background: rgba(248, 250, 252, .98);
      box-shadow: 0 28px 72px rgba(15, 23, 42, .24);
    }
    .global-modal-card h2 {
      margin: 0 0 8px;
      font-size: 1.3rem;
      line-height: 1.1;
    }
    .global-modal-card p {
      margin: 0 0 16px;
      color: var(--muted);
      line-height: 1.62;
    }
    .global-modal-grid {
      display: grid;
      gap: 10px;
    }
    .auth-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 16px;
    }
    .auth-tab {
      min-height: 34px;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid transparent;
      background: rgba(255,255,255,.82);
      color: var(--muted);
      font: inherit;
      font-size: .78rem;
      font-weight: 800;
      cursor: pointer;
    }
    .auth-tab.active {
      background: rgba(37,99,235,.10);
      border-color: rgba(37,99,235,.18);
      color: var(--accent);
    }
    .auth-panel[hidden] {
      display: none;
    }
    .auth-field {
      display: grid;
      gap: 6px;
    }
    .auth-field span {
      color: var(--muted);
      font-size: .72rem;
      font-weight: 800;
      letter-spacing: .06em;
      text-transform: uppercase;
    }
    .auth-token-row {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .auth-token-row .global-token-input {
      flex: 1 1 220px;
    }
    .global-token-input {
      width: 100%;
      min-height: 44px;
      padding: 0 14px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.98);
      color: var(--ink);
      font: inherit;
      outline: none;
    }
    .global-token-input:focus {
      border-color: rgba(37, 99, 235, .42);
      box-shadow: 0 0 0 4px rgba(37, 99, 235, .08);
    }
    .global-modal-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 14px;
    }
    .global-status {
      margin-top: 12px;
      color: var(--muted);
      font-size: .86rem;
      line-height: 1.55;
    }
    .librarian-fab[data-open="true"] .librarian-panel {
      opacity: 1;
      transform: translateY(0);
      pointer-events: auto;
    }
    .librarian-fab {
      position: fixed;
      right: clamp(16px, 3vw, 26px);
      bottom: clamp(16px, 3vw, 26px);
      z-index: 95;
    }
    .librarian-launcher {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      min-height: 50px;
      padding: 0 16px;
      border-radius: 999px;
      border: 1px solid rgba(15,118,110,.22);
      background: rgba(15,118,110,.94);
      color: white;
      font: inherit;
      font-size: .88rem;
      font-weight: 800;
      cursor: pointer;
      box-shadow: 0 18px 34px rgba(15, 23, 42, .18);
    }
    .librarian-panel {
      position: absolute;
      right: 0;
      bottom: calc(100% + 12px);
      width: min(420px, calc(100vw - 28px));
      max-height: min(72svh, 720px);
      display: grid;
      grid-template-rows: auto 1fr auto;
      overflow: hidden;
      border-radius: 18px;
      border: 1px solid rgba(215, 226, 239, .92);
      background: rgba(248, 250, 252, .98);
      box-shadow: 0 32px 80px rgba(15, 23, 42, .26);
      opacity: 0;
      transform: translateY(10px);
      pointer-events: none;
      transition: opacity .18s ease, transform .18s ease;
    }
    .librarian-head,
    .librarian-compose {
      padding: 14px 16px;
      border-bottom: 1px solid rgba(215, 226, 239, .8);
      background: rgba(248, 250, 252, .96);
    }
    .librarian-compose {
      border-top: 1px solid rgba(215, 226, 239, .8);
      border-bottom: 0;
    }
    .librarian-head-row,
    .librarian-compose-row {
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: space-between;
    }
    .agent-chat-tabs {
      display: flex;
      gap: 8px;
      margin-top: 12px;
    }
    .agent-chat-tab {
      min-height: 32px;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid rgba(215, 226, 239, .9);
      background: rgba(255,255,255,.86);
      color: var(--muted);
      font: inherit;
      font-size: .78rem;
      font-weight: 800;
      cursor: pointer;
    }
    .agent-chat-tab.active {
      background: rgba(37,99,235,.10);
      border-color: rgba(37,99,235,.20);
      color: var(--accent);
    }
    .librarian-kicker {
      margin: 0 0 4px;
      color: var(--accent-2);
      font-size: .72rem;
      font-weight: 800;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .librarian-title {
      margin: 0;
      font-size: 1.02rem;
      line-height: 1.2;
    }
    .librarian-subtitle {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: .84rem;
      line-height: 1.55;
    }
    .librarian-close {
      width: 34px;
      height: 34px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.96);
      color: var(--ink);
      font: inherit;
      cursor: pointer;
    }
    .librarian-messages {
      overflow: auto;
      padding: 14px 16px;
      display: grid;
      gap: 10px;
      background:
        radial-gradient(circle at top right, rgba(37,99,235,.06), transparent 30%),
        rgba(244,247,251,.72);
    }
    .librarian-message {
      display: grid;
      gap: 6px;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid rgba(215, 226, 239, .72);
      background: rgba(255,255,255,.92);
      color: var(--ink);
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .librarian-message[data-role="assistant"] {
      border-color: rgba(15,118,110,.18);
      background: rgba(240,253,250,.92);
    }
    .librarian-message-meta {
      color: var(--muted);
      font-size: .72rem;
      font-weight: 800;
      letter-spacing: .06em;
      text-transform: uppercase;
    }
    .librarian-textarea {
      width: 100%;
      min-height: 96px;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.98);
      color: var(--ink);
      font: inherit;
      line-height: 1.55;
      resize: vertical;
      outline: none;
    }
    .librarian-textarea:focus {
      border-color: rgba(37, 99, 235, .42);
      box-shadow: 0 0 0 4px rgba(37, 99, 235, .08);
    }
    .librarian-tools {
      color: var(--muted);
      font-size: .78rem;
      line-height: 1.5;
    }
    @media (max-width: 900px) {
      .global-header {
        grid-template-columns: 1fr;
        align-items: start;
      }
      .global-nav,
      .global-actions {
        justify-content: flex-start;
      }
    }
    """


def _shared_header_html(route_prefix: str, page_label: str, *, note_actions: bool = False) -> str:
    route_prefix = _normalize_prefix(route_prefix)
    return f"""
    <header class="global-header">
      <div class="global-brand">
        <div class="global-brand-mark">OA</div>
        <div class="global-brand-copy">
          <div class="global-brand-title">OpenAkashic</div>
          <div class="global-brand-subtitle">{html.escape(page_label)}</div>
        </div>
      </div>
      <nav class="global-nav" aria-label="Primary">
        <a class="global-pill" href="{html.escape(_root_href(route_prefix))}">Home</a>
        <a class="global-pill" href="{html.escape(_graph_href(route_prefix))}">Graph</a>
        <a class="global-pill" href="{html.escape(_debug_href(route_prefix))}">Admin</a>
      </nav>
      <div class="global-actions">
        <button class="global-pill global-auth-button" id="global-auth-trigger" type="button" data-tone="warn">
          <span class="auth-identity">
            <span class="auth-avatar" id="global-auth-avatar">G</span>
            <span class="auth-meta">
              <strong id="global-auth-name">Guest</strong>
              <small id="global-auth-role">anonymous</small>
            </span>
          </span>
        </button>
      </div>
    </header>
    """


def _shared_ui_shell(route_prefix: str) -> str:
    config = _json_script_text({"apiBase": ""})
    return f"""
    <div class="global-modal" id="global-auth-modal" hidden>
      <div class="global-modal-backdrop" data-close-auth-modal></div>
      <section class="global-modal-card" role="dialog" aria-modal="true" aria-labelledby="global-auth-title">
        <h2 id="global-auth-title">계정과 프로필</h2>
        <p>웹에서는 아이디와 비밀번호로 로그인하고, 로그인 뒤에는 닉네임과 에이전트용 토큰을 여기서 관리한다.</p>
        <div class="auth-tabs" id="global-auth-tabs" role="tablist" aria-label="Auth panels">
          <button class="auth-tab active" type="button" data-auth-panel="login">Login</button>
          <button class="auth-tab" type="button" data-auth-panel="signup">Sign Up</button>
          <button class="auth-tab" type="button" data-auth-panel="profile">Profile</button>
        </div>
        <section class="auth-panel" data-auth-panel-view="login">
          <div class="global-modal-grid">
            <label class="auth-field">
              <span>Username</span>
              <input class="global-token-input" id="global-login-username" type="text" placeholder="your-id" autocomplete="username" />
            </label>
            <label class="auth-field">
              <span>Password</span>
              <input class="global-token-input" id="global-login-password" type="password" placeholder="password" autocomplete="current-password" />
            </label>
          </div>
          <div class="global-modal-actions">
            <button class="global-pill is-primary" id="global-login-submit" type="button">Login</button>
          </div>
        </section>
        <section class="auth-panel" data-auth-panel-view="signup" hidden>
          <div class="global-modal-grid">
            <label class="auth-field">
              <span>Username</span>
              <input class="global-token-input" id="global-signup-username" type="text" placeholder="unique-id" autocomplete="username" />
            </label>
            <label class="auth-field">
              <span>Nickname</span>
              <input class="global-token-input" id="global-signup-nickname" type="text" placeholder="shown name" />
            </label>
            <label class="auth-field">
              <span>Password</span>
              <input class="global-token-input" id="global-signup-password" type="password" placeholder="at least 8 characters" autocomplete="new-password" />
            </label>
            <label class="auth-field">
              <span>Confirm Password</span>
              <input class="global-token-input" id="global-signup-password-confirm" type="password" placeholder="repeat password" autocomplete="new-password" />
            </label>
          </div>
          <div class="global-modal-actions">
            <button class="global-pill is-primary" id="global-signup-submit" type="button">Create Account</button>
          </div>
        </section>
        <section class="auth-panel" data-auth-panel-view="profile" hidden>
          <div class="global-modal-grid">
            <label class="auth-field">
              <span>Username</span>
              <input class="global-token-input" id="global-profile-username" type="text" disabled />
            </label>
            <label class="auth-field">
              <span>Nickname</span>
              <input class="global-token-input" id="global-profile-nickname" type="text" placeholder="shown name" />
            </label>
            <label class="auth-field">
              <span>Role</span>
              <input class="global-token-input" id="global-profile-role" type="text" disabled />
            </label>
            <label class="auth-field">
              <span>Agent API Token</span>
              <div class="auth-token-row">
                <input class="global-token-input" id="global-profile-token" type="text" readonly />
                <button class="global-pill" id="global-profile-token-copy" type="button">Copy</button>
              </div>
            </label>
          </div>
          <div class="global-modal-actions">
            <button class="global-pill is-primary" id="global-profile-save" type="button">Save</button>
            <button class="global-pill" id="global-profile-rotate-token" type="button">Rotate Token</button>
            <button class="global-pill" id="global-profile-logout" type="button">Logout</button>
          </div>
        </section>
        <div class="global-modal-actions">
          <button class="global-pill" id="global-token-close" type="button">Close</button>
        </div>
        <div class="global-status" id="global-auth-status">로그인 뒤 발급된 토큰은 이 브라우저에만 저장된다.</div>
      </section>
    </div>
    <section class="librarian-fab" id="librarian-shell" data-admin-only hidden data-open="false">
      <div class="librarian-panel">
        <div class="librarian-head">
          <div class="librarian-head-row">
            <div>
              <p class="librarian-kicker">OpenAkashic Agents</p>
              <h2 class="librarian-title" id="agent-chat-title">사관</h2>
              <p class="librarian-subtitle" id="agent-chat-subtitle">관리자 상태에서 사관에게 운영 명령을 내리거나 보고를 받을 수 있다.</p>
            </div>
            <button class="librarian-close" id="librarian-close" type="button" aria-label="Close librarian">×</button>
          </div>
          <div class="agent-chat-tabs" role="tablist" aria-label="Agent chat tabs">
            <button class="agent-chat-tab active" type="button" data-agent-tab="sagwan">사관</button>
            <button class="agent-chat-tab" type="button" data-agent-tab="busagwan">부사관</button>
          </div>
        </div>
        <div class="librarian-messages" id="librarian-messages"></div>
        <div class="librarian-compose">
          <textarea class="librarian-textarea" id="librarian-input" placeholder="선택한 에이전트에게 요청하거나 보고를 받아보세요."></textarea>
          <div class="librarian-compose-row" style="margin-top:10px;">
            <div class="librarian-tools" id="librarian-status">관리자 토큰이 활성화되면 사관/부사관과 대화할 수 있다.</div>
            <button class="global-pill is-primary" id="librarian-send" type="button">Send</button>
          </div>
        </div>
      </div>
      <button class="librarian-launcher" id="librarian-launcher" type="button">Chat</button>
    </section>
    <script type="application/json" id="closed-global-config">{config}</script>
    <script>
      (() => {{
        const config = JSON.parse(document.getElementById('closed-global-config')?.textContent || '{{}}');
        const apiBase = String(config.apiBase || '').replace(/\\/$/, '');
        const tokenStorageKey = 'closed-akashic-token';
        const activeAgentStorageKey = 'openakashic-active-agent';
        const agents = {{
          sagwan: {{
            label: '사관',
            meta: 'Sagwan',
            endpoint: '/api/librarian/chat',
            empty: '관리자 토큰이 활성화되면 사관에게 운영 명령이나 정리 요청을 보낼 수 있다.',
            waiting: '사관이 답변을 준비하는 중이다.',
            ready: '사관이 응답했다.',
            failed: '사관 요청 실패',
            subtitle: '관리자 상태에서 사관에게 운영 명령을 내리거나 보고를 받을 수 있다.',
          }},
          busagwan: {{
            label: '부사관',
            meta: 'Busagwan',
            endpoint: '/api/subordinate/chat',
            empty: '부사관은 반복 작업, 1차 리뷰, 크롤링 요약, capsule 초안을 돕는다.',
            waiting: '부사관이 답변을 준비하는 중이다.',
            ready: '부사관이 응답했다.',
            failed: '부사관 요청 실패',
            subtitle: '부사관은 반복 정리와 publication 1차 검토를 맡는 보조 에이전트다.',
          }},
        }};
        const state = {{
          session: {{ authenticated: false, role: 'anonymous', capabilities: [] }},
          activeAgent: window.localStorage.getItem(activeAgentStorageKey) || 'sagwan',
          thread: [],
        }};
        const dom = {{
          authTrigger: document.getElementById('global-auth-trigger'),
          authAvatar: document.getElementById('global-auth-avatar'),
          authName: document.getElementById('global-auth-name'),
          authRole: document.getElementById('global-auth-role'),
          authModal: document.getElementById('global-auth-modal'),
          authTabStrip: document.getElementById('global-auth-tabs'),
          authTabs: [...document.querySelectorAll('[data-auth-panel]')],
          authPanels: [...document.querySelectorAll('[data-auth-panel-view]')],
          authClose: document.getElementById('global-token-close'),
          authStatus: document.getElementById('global-auth-status'),
          authDismiss: [...document.querySelectorAll('[data-close-auth-modal]')],
          loginUsername: document.getElementById('global-login-username'),
          loginPassword: document.getElementById('global-login-password'),
          loginSubmit: document.getElementById('global-login-submit'),
          signupUsername: document.getElementById('global-signup-username'),
          signupNickname: document.getElementById('global-signup-nickname'),
          signupPassword: document.getElementById('global-signup-password'),
          signupPasswordConfirm: document.getElementById('global-signup-password-confirm'),
          signupSubmit: document.getElementById('global-signup-submit'),
          profileUsername: document.getElementById('global-profile-username'),
          profileNickname: document.getElementById('global-profile-nickname'),
          profileRole: document.getElementById('global-profile-role'),
          profileToken: document.getElementById('global-profile-token'),
          profileTokenCopy: document.getElementById('global-profile-token-copy'),
          profileSave: document.getElementById('global-profile-save'),
          profileRotateToken: document.getElementById('global-profile-rotate-token'),
          profileLogout: document.getElementById('global-profile-logout'),
          adminOnly: [...document.querySelectorAll('[data-admin-only]')],
          noteWriteControls: [...document.querySelectorAll('[data-note-write-control]')],
          editButton: document.getElementById('global-edit-note'),
          saveButton: document.getElementById('global-save-note'),
          cancelButton: document.getElementById('global-cancel-note'),
          librarianShell: document.getElementById('librarian-shell'),
          librarianLauncher: document.getElementById('librarian-launcher'),
          librarianClose: document.getElementById('librarian-close'),
          agentTitle: document.getElementById('agent-chat-title'),
          agentSubtitle: document.getElementById('agent-chat-subtitle'),
          agentTabs: [...document.querySelectorAll('[data-agent-tab]')],
          librarianMessages: document.getElementById('librarian-messages'),
          librarianInput: document.getElementById('librarian-input'),
          librarianSend: document.getElementById('librarian-send'),
          librarianStatus: document.getElementById('librarian-status'),
        }};

        function token() {{
          return window.localStorage.getItem(tokenStorageKey) || '';
        }}

        function setStoredToken(value) {{
          if (value) {{
            window.localStorage.setItem(tokenStorageKey, value);
          }} else {{
            window.localStorage.removeItem(tokenStorageKey);
          }}
          syncTokenCookie(value);
          if (dom.profileToken) dom.profileToken.value = value;
        }}

        function initialsFor(session) {{
          const label = String(session?.nickname || session?.username || 'G').trim();
          return (label[0] || 'G').toUpperCase();
        }}

        function setAuthPanel(panel) {{
          const isAuthed = Boolean(state.session?.authenticated);
          const next = isAuthed ? 'profile' : (['login', 'signup'].includes(panel) ? panel : 'login');
          dom.authTabs.forEach((button) => button.classList.toggle('active', button.dataset.authPanel === next));
          dom.authPanels.forEach((section) => {{
            section.hidden = section.dataset.authPanelView !== next;
          }});
          if (dom.authTabStrip) {{
            dom.authTabStrip.hidden = isAuthed;
          }}
        }}

        function syncTokenCookie(value) {{
          if (value) {{
            document.cookie = `closed_akashic_token=${{encodeURIComponent(value)}}; path=/; SameSite=Lax; max-age=2592000`;
          }} else {{
            document.cookie = 'closed_akashic_token=; path=/; SameSite=Lax; max-age=0';
          }}
        }}

        function setAuthButton(session) {{
          if (!dom.authTrigger) return;
          const isAdmin = Boolean(session?.authenticated && session?.role === 'admin');
          const isUser = Boolean(session?.authenticated && session?.role !== 'admin');
          dom.authTrigger.dataset.tone = isAdmin ? 'admin' : isUser ? 'user' : 'warn';
          if (dom.authAvatar) dom.authAvatar.textContent = initialsFor(session);
          if (dom.authName) dom.authName.textContent = session?.nickname || 'Guest';
          if (dom.authRole) dom.authRole.textContent = session?.role || 'anonymous';
        }}

        function setAdminVisible(visible) {{
          document.body.classList.toggle('is-admin', visible);
          dom.adminOnly.forEach((node) => {{
            node.hidden = !visible;
          }});
        }}

        function setNoteWriteVisible(visible) {{
          dom.noteWriteControls.forEach((node) => {{
            node.hidden = !visible;
          }});
        }}

        function setAuthStatus(message) {{
          if (dom.authStatus) dom.authStatus.textContent = message;
        }}

        function reloadForAuthChange() {{
          window.setTimeout(() => window.location.reload(), 140);
        }}

        function syncProfileFields() {{
          const session = state.session || {{}};
          if (dom.profileUsername) dom.profileUsername.value = session.username || '';
          if (dom.profileNickname) dom.profileNickname.value = session.nickname || '';
          if (dom.profileRole) dom.profileRole.value = session.role || 'anonymous';
          if (dom.profileToken) dom.profileToken.value = token();
        }}

        async function apiFetch(path, options = {{}}) {{
          const headers = new Headers(options.headers || {{}});
          const storedToken = token();
          if (storedToken) {{
            headers.set('Authorization', `Bearer ${{storedToken}}`);
          }}
          const request = {{
            method: options.method || 'GET',
            headers,
            body: options.body,
            mode: 'cors',
          }};
          if (options.json !== undefined) {{
            headers.set('Content-Type', 'application/json');
            request.body = JSON.stringify(options.json);
          }}
          return fetch(`${{apiBase}}${{path}}`, request);
        }}

        async function requestJson(path, options = {{}}) {{
          const response = await apiFetch(path, options);
          const data = await response.json().catch(() => ({{ detail: `${{response.status}} ${{response.statusText}}` }}));
          if (!response.ok) {{
            throw new Error(data.detail || data.error || `${{response.status}} ${{response.statusText}}`);
          }}
          return data;
        }}

        function dispatchAuthChange() {{
          document.dispatchEvent(new CustomEvent('closed-akashic-auth-change', {{ detail: state.session }}));
        }}

        async function refreshSession({{ silent = false }} = {{}}) {{
          try {{
            const session = await requestJson('/api/session');
            state.session = session;
            const isAdmin = Boolean(session?.authenticated && session?.role === 'admin');
            setAdminVisible(isAdmin);
            setAuthButton(session);
            if (!silent) {{
              setAuthStatus(
                session?.authenticated
                  ? `${{session.nickname || session.username || 'user'}} 계정으로 연결되었다.`
                  : '유효한 로그인 세션이나 토큰이 아직 없다.'
              );
            }}
            if (dom.librarianStatus) {{
              dom.librarianStatus.textContent = isAdmin
                ? `모델: ${{session?.librarian?.model || 'unknown'}}`
                : '관리자 토큰이 활성화되면 사관/부사관과 대화할 수 있다.';
            }}
            syncProfileFields();
            dispatchAuthChange();
            return session;
          }} catch (error) {{
            state.session = {{ authenticated: false, role: 'anonymous', capabilities: [] }};
            setAdminVisible(false);
            setAuthButton(state.session);
            syncProfileFields();
            if (!silent) {{
              setAuthStatus(error.message || '토큰 확인에 실패했다.');
            }}
            dispatchAuthChange();
            return state.session;
          }}
        }}

        function openAuthModal() {{
          if (dom.authModal) dom.authModal.hidden = false;
          setAuthPanel(state.session?.authenticated ? 'profile' : 'login');
          syncProfileFields();
          window.setTimeout(() => {{
            if (state.session?.authenticated) {{
              dom.profileNickname?.focus();
            }} else {{
              dom.loginUsername?.focus();
            }}
          }}, 40);
        }}

        async function applyIssuedToken(value) {{
          setStoredToken(value);
          const session = await refreshSession();
          if (session?.authenticated) {{
            setAuthPanel('profile');
          }}
        }}

        function closeAuthModal() {{
          if (dom.authModal) dom.authModal.hidden = true;
        }}

        function clearToken() {{
          setStoredToken('');
          refreshSession();
          setAuthStatus('토큰을 지웠다. 지금은 읽기 전용이다.');
          reloadForAuthChange();
        }}

        async function login() {{
          const username = dom.loginUsername?.value.trim() || '';
          const password = dom.loginPassword?.value || '';
          if (!username || !password) {{
            setAuthStatus('아이디와 비밀번호를 모두 입력해줘.');
            return;
          }}
          const data = await requestJson('/api/auth/login', {{
            method: 'POST',
            json: {{ username, password }},
          }});
          await applyIssuedToken(data.token || '');
          setAuthStatus('로그인했다. 이 토큰으로 웹과 에이전트 둘 다 사용할 수 있다.');
          reloadForAuthChange();
        }}

        async function signup() {{
          const username = dom.signupUsername?.value.trim() || '';
          const nickname = dom.signupNickname?.value.trim() || '';
          const password = dom.signupPassword?.value || '';
          const password_confirm = dom.signupPasswordConfirm?.value || '';
          if (!username || !nickname || !password || !password_confirm) {{
            setAuthStatus('회원가입에는 아이디, 닉네임, 비밀번호, 비밀번호 확인이 필요하다.');
            return;
          }}
          if (password !== password_confirm) {{
            setAuthStatus('비밀번호 확인이 일치하지 않는다.');
            return;
          }}
          const data = await requestJson('/api/auth/signup', {{
            method: 'POST',
            json: {{ username, nickname, password, password_confirm }},
          }});
          await applyIssuedToken(data.token || '');
          setAuthStatus('계정을 만들고 바로 로그인했다. 프로필 탭에서 API 토큰을 복사할 수 있다.');
          reloadForAuthChange();
        }}

        async function saveProfile() {{
          if (!state.session?.authenticated) {{
            setAuthStatus('먼저 로그인해줘.');
            return;
          }}
          const data = await requestJson('/api/profile', {{
            method: 'POST',
            json: {{
              nickname: dom.profileNickname?.value.trim() || '',
            }},
          }});
          await refreshSession({{ silent: true }});
          syncProfileFields();
          setAuthStatus(`프로필을 저장했다: ${{data.profile?.nickname || state.session?.nickname || ''}}`);
        }}

        async function rotateProfileToken() {{
          if (!state.session?.authenticated) {{
            setAuthStatus('먼저 로그인해줘.');
            return;
          }}
          const data = await requestJson('/api/profile/token', {{
            method: 'POST',
          }});
          await applyIssuedToken(data.token || '');
          setAuthStatus('새 API 토큰을 발급했다. 에이전트가 쓸 토큰도 함께 바뀌었다.');
        }}

        async function copyProfileToken() {{
          const value = dom.profileToken?.value || token();
          if (!value) return;
          try {{
            await navigator.clipboard.writeText(value);
            setAuthStatus('현재 API 토큰을 복사했다.');
          }} catch (error) {{
            setAuthStatus('토큰 복사에 실패했다.');
          }}
        }}

        function activeAgent() {{
          return agents[state.activeAgent] ? state.activeAgent : 'sagwan';
        }}

        function threadStorageKey() {{
          return `openakashic-agent-thread-${{activeAgent()}}`;
        }}

        function escapeHtml(value) {{
          return String(value || '').replace(/[&<>]/g, (ch) => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[ch]));
        }}

        function loadThread() {{
          try {{
            const raw = window.localStorage.getItem(threadStorageKey());
            state.thread = raw ? JSON.parse(raw) : [];
          }} catch (error) {{
            state.thread = [];
          }}
        }}

        function saveThread() {{
          window.localStorage.setItem(threadStorageKey(), JSON.stringify(state.thread.slice(-20)));
        }}

        function renderThread() {{
          if (!dom.librarianMessages) return;
          const agent = agents[activeAgent()];
          if (!state.thread.length) {{
            dom.librarianMessages.innerHTML = `<div class="librarian-message" data-role="assistant"><div class="librarian-message-meta">${{agent.meta}}</div><div>${{agent.empty}}</div></div>`;
            return;
          }}
          dom.librarianMessages.innerHTML = state.thread.map((item) => `
            <div class="librarian-message" data-role="${{item.role}}">
              <div class="librarian-message-meta">${{item.role === 'assistant' ? agent.meta : 'You'}}</div>
              <div>${{escapeHtml(item.content)}}</div>
            </div>
          `).join('');
          dom.librarianMessages.scrollTop = dom.librarianMessages.scrollHeight;
        }}

        function setActiveAgent(agentKey) {{
          if (!agents[agentKey]) agentKey = 'sagwan';
          state.activeAgent = agentKey;
          window.localStorage.setItem(activeAgentStorageKey, agentKey);
          const agent = agents[agentKey];
          dom.agentTabs.forEach((button) => button.classList.toggle('active', button.dataset.agentTab === agentKey));
          if (dom.agentTitle) dom.agentTitle.textContent = agent.label;
          if (dom.agentSubtitle) dom.agentSubtitle.textContent = agent.subtitle;
          if (dom.librarianStatus && !(state.session?.authenticated && state.session?.role === 'admin')) {{
            dom.librarianStatus.textContent = '관리자 토큰이 활성화되면 사관/부사관과 대화할 수 있다.';
          }}
          loadThread();
          renderThread();
        }}

        function toggleLibrarian(open) {{
          if (!dom.librarianShell) return;
          dom.librarianShell.dataset.open = open ? 'true' : 'false';
          if (open) {{
            setActiveAgent(activeAgent());
            renderThread();
            window.setTimeout(() => dom.librarianInput?.focus(), 80);
          }}
        }}

        async function sendToLibrarian() {{
          if (!(state.session?.authenticated && state.session?.role === 'admin')) {{
            openAuthModal();
            return;
          }}
          const agent = agents[activeAgent()];
          const message = dom.librarianInput?.value.trim() || '';
          if (!message) return;
          state.thread.push({{ role: 'user', content: message }});
          dom.librarianInput.value = '';
          renderThread();
          if (dom.librarianStatus) dom.librarianStatus.textContent = agent.waiting;
          try {{
            const data = await requestJson(agent.endpoint, {{
              method: 'POST',
              json: {{
                message,
                thread: state.thread.slice(-12),
              }},
            }});
            state.thread.push({{ role: 'assistant', content: data.message || '응답이 비어 있다.' }});
            saveThread();
            renderThread();
            if (dom.librarianStatus) {{
              dom.librarianStatus.textContent = data.model
                ? `모델: ${{data.model}}`
                : agent.ready;
            }}
          }} catch (error) {{
            state.thread.push({{ role: 'assistant', content: error.message || `${{agent.label}} 요청에 실패했다.` }});
            renderThread();
            if (dom.librarianStatus) dom.librarianStatus.textContent = error.message || agent.failed;
          }}
        }}

        dom.authTrigger?.addEventListener('click', openAuthModal);
        dom.authTabs.forEach((button) => button.addEventListener('click', () => setAuthPanel(button.dataset.authPanel || 'login')));
        dom.authClose?.addEventListener('click', closeAuthModal);
        dom.loginSubmit?.addEventListener('click', login);
        dom.signupSubmit?.addEventListener('click', signup);
        dom.profileSave?.addEventListener('click', saveProfile);
        dom.profileRotateToken?.addEventListener('click', rotateProfileToken);
        dom.profileTokenCopy?.addEventListener('click', copyProfileToken);
        dom.profileLogout?.addEventListener('click', () => {{
          clearToken();
          closeAuthModal();
        }});
        dom.authDismiss.forEach((node) => node.addEventListener('click', closeAuthModal));
        dom.loginPassword?.addEventListener('keydown', (event) => {{
          if (event.key === 'Enter') login();
        }});
        dom.loginUsername?.addEventListener('keydown', (event) => {{
          if (event.key === 'Enter') login();
        }});
        dom.signupPasswordConfirm?.addEventListener('keydown', (event) => {{
          if (event.key === 'Enter') signup();
        }});
        dom.editButton?.addEventListener('click', () => document.dispatchEvent(new CustomEvent('closed-akashic-edit-request')));
        dom.saveButton?.addEventListener('click', () => document.dispatchEvent(new CustomEvent('closed-akashic-save-request')));
        dom.cancelButton?.addEventListener('click', () => document.dispatchEvent(new CustomEvent('closed-akashic-cancel-request')));
        dom.librarianLauncher?.addEventListener('click', () => toggleLibrarian(dom.librarianShell?.dataset.open !== 'true'));
        dom.librarianClose?.addEventListener('click', () => toggleLibrarian(false));
        dom.agentTabs.forEach((button) => button.addEventListener('click', () => setActiveAgent(button.dataset.agentTab || 'sagwan')));
        dom.librarianSend?.addEventListener('click', sendToLibrarian);
        dom.librarianInput?.addEventListener('keydown', (event) => {{
          if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {{
            sendToLibrarian();
          }}
        }});

        setActiveAgent(activeAgent());
        if (token()) {{
          setStoredToken(token());
          refreshSession({{ silent: true }});
        }} else {{
          setAdminVisible(false);
          setAuthButton(state.session);
          syncProfileFields();
          dispatchAuthChange();
        }}

        window.closedAkashicUI = {{
          getToken: token,
          getSession: () => state.session,
          refreshSession,
          apiFetch,
          requestJson,
          openAuthModal,
          closeAuthModal,
          setNoteWriteVisible,
        }};
      }})();
    </script>
    """


def _workspace_styles() -> str:
    return """
    body.inline-editing .editable-read { cursor: default; }
    .workspace-card {
      display: grid;
      gap: 12px;
      padding: 14px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.86);
    }
    .workspace-note {
      margin: 0;
      color: var(--muted);
      font-size: .82rem;
      line-height: 1.55;
    }
    .workspace-template {
      margin: 0;
      padding: 12px 14px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: rgba(15, 23, 42, .04);
      color: var(--ink);
      white-space: pre-wrap;
      font: 500 .82rem/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    .toolbar-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .field {
      display: grid;
      gap: 6px;
    }
    .field-label {
      color: var(--muted);
      font-size: .72rem;
      font-weight: 700;
      letter-spacing: .06em;
      text-transform: uppercase;
    }
    .field-input, .field-select, .field-textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,.98);
      color: var(--ink);
      font: inherit;
    }
    .field-input, .field-select {
      min-height: 40px;
      padding: 0 12px;
    }
    .field-textarea {
      min-height: 320px;
      padding: 12px;
      resize: vertical;
      line-height: 1.65;
    }
    .action-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 38px;
      padding: 0 12px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.96);
      color: var(--ink);
      font: inherit;
      font-size: .86rem;
      font-weight: 600;
      cursor: pointer;
      transition: transform .18s ease, border-color .18s ease, background .18s ease;
    }
    .action-button:hover {
      transform: translateY(-1px);
      border-color: var(--line-strong);
      background: var(--surface-strong);
    }
    .action-button:disabled {
      opacity: .45;
      cursor: not-allowed;
      transform: none;
    }
    .action-button.primary {
      background: var(--ink);
      border-color: var(--ink);
      color: white;
    }
    .action-button.primary:hover {
      background: #0f172a;
      border-color: #0f172a;
    }
    .action-button.subtle {
      background: transparent;
    }
    .status-chip {
      display: inline-flex;
      align-items: center;
      width: fit-content;
      min-height: 28px;
      padding: 0 10px;
      border-radius: 999px;
      background: rgba(37, 99, 235, .08);
      color: var(--accent);
      font-size: .77rem;
      font-weight: 700;
    }
    .status-chip[data-tone="warn"] {
      background: rgba(234, 88, 12, .10);
      color: #c2410c;
    }
    .status-chip[data-tone="error"] {
      background: rgba(220, 38, 38, .10);
      color: #b91c1c;
    }
    .status-chip[data-tone="success"] {
      background: rgba(15, 118, 110, .12);
      color: var(--accent-2);
    }
    .workspace-shell {
      position: static;
    }
    .workspace-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }
    .workspace-title {
      margin: 0;
      font-size: 1.7rem;
      line-height: 1.04;
      letter-spacing: 0;
    }
    .icon-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 38px;
      height: 38px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.96);
      color: var(--ink);
      font: inherit;
      font-size: 1.2rem;
      cursor: pointer;
    }
    .workspace-banner {
      min-height: 28px;
      margin: 0 0 14px;
      color: var(--muted);
      font-size: .88rem;
      line-height: 1.55;
    }
    .workspace-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    .workspace-grid .field.span-2 {
      grid-column: 1 / -1;
    }
    .field-help {
      color: var(--muted);
      font-size: .79rem;
      line-height: 1.55;
    }
    .tool-group {
      margin: 0;
      padding: 14px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.78);
    }
    .tool-summary {
      cursor: pointer;
      font-weight: 700;
      color: var(--ink);
      list-style: none;
    }
    .tool-summary::-webkit-details-marker { display: none; }
    .tool-body {
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }
    .workspace-actions {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 10px;
      margin-top: 18px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }
    .workspace-actions .toolbar-row:last-child {
      justify-content: flex-end;
      margin-left: auto;
    }
    .toast {
      position: fixed;
      left: 50%;
      bottom: 22px;
      transform: translate(-50%, 18px);
      min-width: min(560px, calc(100vw - 32px));
      max-width: min(720px, calc(100vw - 32px));
      padding: 12px 14px;
      border-radius: 8px;
      border: 1px solid rgba(15, 23, 42, .08);
      background: rgba(15, 23, 42, .92);
      color: white;
      box-shadow: 0 18px 36px rgba(15, 23, 42, .24);
      opacity: 0;
      pointer-events: none;
      transition: opacity .18s ease, transform .18s ease;
      z-index: 70;
    }
    .toast.visible {
      opacity: 1;
      transform: translate(-50%, 0);
    }
    .toast[data-tone="success"] {
      background: rgba(15, 118, 110, .95);
    }
    .toast[data-tone="warn"] {
      background: rgba(194, 65, 12, .95);
    }
    .toast[data-tone="error"] {
      background: rgba(185, 28, 28, .95);
    }
    @media (max-width: 820px) {
      .workspace-drawer {
        width: 100vw;
        padding: 22px 16px 18px;
      }
      .workspace-grid {
        grid-template-columns: 1fr;
      }
    }
    """


def _workspace_controls_html() -> str:
    return """
    <section class="meta-section">
      <h3 class="meta-title">Write Access</h3>
      <div class="workspace-card">
        <div class="field">
          <label class="field-label" for="workspace-token">Master Token</label>
          <div class="toolbar-row">
            <input class="field-input" id="workspace-token" type="password" placeholder="CLOSED_AKASHIC_TOKEN" autocomplete="off" />
            <button class="action-button" id="workspace-unlock">Unlock</button>
          </div>
        </div>
        <div class="status-chip" id="workspace-auth-chip" data-tone="warn">Read only</div>
        <p class="workspace-note" id="workspace-status">토큰을 저장하면 제목, 본문, 메타데이터, 이미지와 파일을 페이지 안에서 바로 수정할 수 있다.</p>
        <button class="action-button subtle" id="workspace-clear">Clear Token</button>
        <p class="workspace-note">토큰은 현재 브라우저의 localStorage에만 저장된다.</p>
      </div>
    </section>
    """


def _workspace_overlay_html() -> str:
    kind_options = "\n".join(
        f'        <option value="{html.escape(item["kind"])}"></option>'
        for item in kind_catalog()
    )
    return f"""
    <div class="workspace-shell" id="workspace-shell">
      <div class="toast" id="workspace-toast" data-tone="success"></div>
      <datalist id="editor-kind-options">
{kind_options}
      </datalist>
      <datalist id="editor-status-options">
        <option value="active"></option>
        <option value="draft"></option>
        <option value="archived"></option>
      </datalist>
      <datalist id="editor-folder-options"></datalist>
      <datalist id="editor-asset-folder-options"></datalist>
    </div>
    """


def _workspace_script() -> str:
    kind_specs = {
        item["kind"]: {
            "label": item["label"],
            "summary": item["summary"],
            "folder": item["folder"],
            "sections": kind_template_sections(item["kind"]),
        }
        for item in kind_catalog()
    }
    kind_specs_json = json.dumps(kind_specs, ensure_ascii=False)
    template = """
    (() => {
      const noteData = JSON.parse(document.getElementById('closed-note-data')?.textContent || '{}');
      const kindSpecs = __KIND_SPECS_JSON__;
      const state = {
        authorized: false,
        currentWritable: false,
        mode: 'edit',
        originalPath: noteData.path || '',
        noteFolders: [],
      };

      const dom = {
        sidebar: document.getElementById('workspace-sidebar'),
        sideTabs: [...document.querySelectorAll('[data-sidebar-tab]')],
        banner: document.getElementById('workspace-banner'),
        formTitle: document.getElementById('editor-title'),
        formSummary: document.getElementById('editor-summary'),
        formKind: document.getElementById('editor-kind'),
        formProject: document.getElementById('editor-project'),
        formStatus: document.getElementById('editor-status'),
        formOwner: document.getElementById('editor-owner'),
        formVisibility: document.getElementById('editor-visibility'),
        formPublicationStatus: document.getElementById('editor-publication-status'),
        formScope: document.getElementById('editor-scope'),
        formFolder: document.getElementById('editor-folder'),
        formPath: document.getElementById('editor-path'),
        formTags: document.getElementById('editor-tags'),
        formRelated: document.getElementById('editor-related'),
        formBody: document.getElementById('editor-body'),
        suggestButton: document.getElementById('editor-suggest'),
        deleteButton: document.getElementById('editor-delete'),
        folderPath: document.getElementById('workspace-folder-path'),
        createFolderButton: document.getElementById('workspace-create-folder'),
        saveButton: document.getElementById('workspace-save'),
        noteFolderOptions: document.getElementById('editor-folder-options'),
        kindSummary: document.getElementById('editor-kind-summary'),
        kindTemplate: document.getElementById('editor-kind-template'),
        toast: document.getElementById('workspace-toast'),
      };

      let toastTimer = null;

      function showToast(message, tone = 'success') {
        if (!dom.toast) return;
        dom.toast.textContent = message;
        dom.toast.dataset.tone = tone;
        dom.toast.classList.add('visible');
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => dom.toast.classList.remove('visible'), 2600);
      }

      function setBanner(message, tone = 'muted') {
        if (!dom.banner) return;
        dom.banner.textContent = message;
        dom.banner.dataset.tone = tone;
      }

      function setSidebarPanel(panel) {
        const next = ['explore', 'info', 'relations', 'edit'].includes(panel) ? panel : 'explore';
        dom.sidebar?.setAttribute('data-active-panel', next);
        dom.sideTabs.forEach((button) => button.classList.toggle('active', button.dataset.sidebarTab === next));
        window.localStorage.setItem('closed-akashic-sidebar-tab', next);
        document.body.classList.remove('left-collapsed');
        window.localStorage.setItem('closed-akashic-left-collapsed', '0');
      }

      function escapeAttr(value) {
        return String(value || '').replace(/[&<>\"]/g, (char) => (
          {'&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;'}[char]
        ));
      }

      function parseList(value) {
        return value
          .split(/[\\n,]/)
          .map((item) => item.trim())
          .filter(Boolean);
      }

      function renderOptions(target, values) {
        if (!target) return;
        target.innerHTML = [...new Set(values)].sort((a, b) => a.localeCompare(b)).map(
          (item) => `<option value=\"${escapeAttr(item)}\"></option>`
        ).join('');
      }

      function buildKindTemplate(kind) {
        const spec = kindSpecs[kind] || kindSpecs.reference;
        const body = (spec.sections || []).map((section) => `## ${section}\\n`).join('\\n');
        return body.trim() || '## Summary';
      }

      function updateKindGuide() {
        const rawKind = String(dom.formKind?.value || '').trim().toLowerCase().replace(/-/g, '_');
        const spec = kindSpecs[rawKind] || kindSpecs.reference;
        if (dom.kindSummary) {
          dom.kindSummary.textContent = `${spec.label}: ${spec.summary} 권장 폴더는 ${spec.folder} 계열이다.`;
        }
        if (dom.kindTemplate) {
          dom.kindTemplate.textContent = buildKindTemplate(rawKind);
        }
      }

      async function requestJson(path, options = {}) {
        if (!window.closedAkashicUI?.requestJson) {
          throw new Error('공통 관리자 UI가 아직 준비되지 않았다.');
        }
        return window.closedAkashicUI.requestJson(path, options);
      }

      async function refreshFolders() {
        try {
          const data = await requestJson('/api/folders');
          state.noteFolders = Object.entries(data.existing || {})
            .flatMap(([root, folders]) => root === 'assets' ? [] : folders);
          renderOptions(dom.noteFolderOptions, state.noteFolders);
        } catch (error) {
          showToast(error.message || '폴더 정보를 불러오지 못했다.', 'error');
        }
      }

      function setEditing(enabled) {
        document.body.classList.toggle('inline-editing', enabled);
        if (!enabled) {
          setBanner('마크다운 원문을 수정한 뒤 우상단 Save로 저장한다.');
        }
      }

      function canWriteCurrent(session) {
        if (!session?.authenticated) return false;
        if (session.role === 'admin') return true;
        return noteData.visibility !== 'public' && session.nickname === noteData.owner;
      }

      async function openWorkspace(mode) {
        const session = window.closedAkashicUI?.getSession?.() || {};
        if (!session?.authenticated) {
          setSidebarPanel('edit');
          showToast('먼저 로그인하거나 토큰을 적용해줘.', 'warn');
          window.closedAkashicUI?.openAuthModal?.();
          return;
        }
        if (mode === 'edit' && !canWriteCurrent(session)) {
          showToast('현재 세션은 이 노트를 수정할 수 없다.', 'warn');
          return;
        }
        setSidebarPanel('edit');
        state.mode = mode;
        if (mode === 'new') {
          presetNewNote();
          dom.deleteButton.hidden = true;
          setBanner('새 페이지를 작성 중이다. 제목을 적고 저장하면 경로를 추천한다.');
        } else {
          dom.deleteButton.hidden = false;
          await loadCurrentNote();
          setBanner('제목, 요약, 본문을 페이지 안에서 바로 수정할 수 있다.');
        }
        setEditing(true);
        window.setTimeout(() => {
          (mode === 'new' ? dom.formTitle : dom.formBody)?.focus();
        }, 80);
      }

      function closeWorkspace() {
        setEditing(false);
      }

      function openFolderTools() {
        setSidebarPanel('edit');
        if (!state.authorized) {
          showToast('먼저 로그인하거나 토큰을 적용해줘.', 'warn');
          window.closedAkashicUI?.openAuthModal?.();
          return;
        }
        dom.folderPath?.focus();
      }

      function presetNewNote() {
        const inheritedProject = noteData.project && !['closed-akashic', 'openakashic'].includes(noteData.project) ? noteData.project : '';
        const session = window.closedAkashicUI?.getSession?.() || {};
        state.originalPath = '';
        dom.formTitle.value = '';
        dom.formSummary.value = '';
        dom.formKind.value = 'reference';
        dom.formProject.value = inheritedProject;
        dom.formStatus.value = 'active';
        dom.formOwner.value = session.nickname || noteData.owner || 'aaron';
        dom.formVisibility.value = 'private';
        dom.formPublicationStatus.value = 'none';
        dom.formScope.value = inheritedProject ? 'shared' : 'shared';
        dom.formFolder.value = '';
        dom.formPath.value = '';
        dom.formTags.value = '';
        dom.formRelated.value = '';
        dom.formBody.value = buildKindTemplate(dom.formKind.value) + '\\n';
        dom.folderPath.value = '';
        updateKindGuide();
      }

      async function loadCurrentNote() {
        try {
          setBanner('현재 노트를 불러오는 중이다.');
          const raw = await requestJson(`/api/raw-note?path=${encodeURIComponent(noteData.path)}`);
          const fm = raw.frontmatter || {};
          state.originalPath = raw.path || noteData.path;
          dom.formTitle.value = fm.title || noteData.title || '';
          dom.formSummary.value = noteData.summary || '';
          dom.formKind.value = fm.kind || noteData.kind || '';
          dom.formProject.value = fm.project || noteData.project || '';
          dom.formStatus.value = fm.status || noteData.status || 'active';
          dom.formOwner.value = fm.owner || noteData.owner || 'aaron';
          dom.formVisibility.value = fm.visibility || noteData.visibility || 'private';
          dom.formPublicationStatus.value = fm.publication_status || noteData.publication_status || 'none';
          dom.formScope.value = (raw.path || noteData.path || '').startsWith('personal_vault/personal/') ? 'personal' : 'shared';
          dom.formFolder.value = '';
          dom.formPath.value = raw.path || noteData.path || '';
          dom.formTags.value = Array.isArray(fm.tags) ? fm.tags.join(', ') : (noteData.tags || []).join(', ');
          dom.formRelated.value = Array.isArray(fm.related) ? fm.related.join(', ') : (noteData.related || []).join(', ');
          dom.formBody.value = raw.body || noteData.body || '## Summary\\n\\n';
          dom.folderPath.value = '';
          updateKindGuide();
          setBanner('경로를 바꾸고 저장하면 기존 노트를 move한 뒤 내용을 저장한다.');
        } catch (error) {
          setBanner(error.message || '현재 노트를 불러오지 못했다.', 'error');
          showToast(error.message || '현재 노트를 불러오지 못했다.', 'error');
        }
      }

      function applySummaryToBody(body, summary) {
        const nextSummary = summary.trim();
        const cleanBody = body.trim();
        if (!nextSummary) {
          return cleanBody ? `${cleanBody}\\n` : '## Summary\\n\\n';
        }
        const lines = cleanBody.split('\\n');
        const index = lines.findIndex((line) => line.trim().toLowerCase() === '## summary');
        if (index === -1) {
          return `## Summary\\n${nextSummary}\\n\\n${cleanBody}\\n`;
        }
        let end = lines.length;
        for (let i = index + 1; i < lines.length; i += 1) {
          if (/^##\\s+/.test(lines[i]) && lines[i].trim().toLowerCase() !== '## summary') {
            end = i;
            break;
          }
        }
        const before = lines.slice(0, index);
        const after = lines.slice(end);
        return [...before, '## Summary', nextSummary, '', ...after].join('\\n').replace(/\\n{3,}/g, '\\n\\n').trim() + '\\n';
      }

      async function suggestPath() {
        const title = dom.formTitle.value.trim();
        if (!title) {
          showToast('먼저 제목을 적어줘.', 'warn');
          dom.formTitle.focus();
          return;
        }
        const params = new URLSearchParams({ title });
        if (dom.formKind.value.trim()) params.set('kind', dom.formKind.value.trim());
        if (dom.formFolder.value.trim()) params.set('folder', dom.formFolder.value.trim());
        if (dom.formProject.value.trim()) params.set('project', dom.formProject.value.trim());
        else if (dom.formScope.value.trim()) params.set('scope', dom.formScope.value.trim());
        try {
          const data = await requestJson(`/api/path-suggestion?${params.toString()}`);
          dom.formPath.value = data.path || '';
          setBanner('추천 경로를 채웠다. 필요하면 직접 바꿔도 된다.', 'success');
        } catch (error) {
          showToast(error.message || '경로 추천에 실패했다.', 'error');
        }
      }

      function notePayload(path) {
        return {
          path,
          title: dom.formTitle.value.trim() || null,
          kind: dom.formKind.value.trim() || null,
          project: dom.formProject.value.trim() || null,
          status: dom.formStatus.value.trim() || null,
          tags: parseList(dom.formTags.value),
          related: parseList(dom.formRelated.value),
          metadata: {
            visibility: dom.formVisibility.value.trim() || 'private',
            publication_status: dom.formPublicationStatus.value.trim() || 'none',
          },
          body: applySummaryToBody(dom.formBody.value, dom.formSummary.value),
        };
      }

      async function saveNote() {
        let path = dom.formPath.value.trim();
        if (!path) {
          await suggestPath();
          path = dom.formPath.value.trim();
        }
        if (!path) {
          showToast('저장 경로가 필요하다.', 'warn');
          dom.formPath.focus();
          return;
        }
        try {
          setBanner('노트를 저장하는 중이다.');
          if (state.mode === 'edit' && state.originalPath && state.originalPath !== path) {
            await requestJson('/api/note/move', {
              method: 'POST',
              json: { path: state.originalPath, new_path: path },
            });
            state.originalPath = path;
          }
          const data = await requestJson('/api/note', {
            method: 'PUT',
            json: notePayload(path),
          });
          const publicationRequested = Boolean(data.publication_request);
          setBanner(publicationRequested ? '저장과 함께 publication 요청을 보냈다.' : '저장을 마쳤다.', 'success');
          showToast(publicationRequested ? '저장 후 publication 요청을 보냈다.' : '노트를 저장했다.', 'success');
          const href = data.note?.href ? `${window.location.origin}${data.note.href}` : `${window.location.origin}/`;
          window.location.href = href;
        } catch (error) {
          setBanner(error.message || '저장에 실패했다.', 'error');
          showToast(error.message || '저장에 실패했다.', 'error');
        }
      }

      async function deleteNote() {
        if (state.mode !== 'edit' || !state.originalPath) return;
        if (!window.confirm('이 노트를 삭제할까?')) return;
        try {
          await requestJson('/api/note', {
            method: 'DELETE',
            json: { path: state.originalPath },
          });
          showToast('노트를 삭제했다.', 'success');
          window.location.href = `${window.location.origin}/`;
        } catch (error) {
          showToast(error.message || '삭제에 실패했다.', 'error');
        }
      }

      async function createFolder() {
        const path = dom.folderPath.value.trim() || dom.formFolder.value.trim();
        if (!path) {
          showToast('먼저 폴더 경로를 적어줘.', 'warn');
          dom.folderPath.focus();
          return;
        }
        try {
          const data = await requestJson('/api/folder', {
            method: 'POST',
            json: { path },
          });
          dom.formFolder.value = data.path;
          dom.folderPath.value = data.path;
          await refreshFolders();
          showToast('폴더를 만들었다.', 'success');
          setBanner('폴더를 만든 뒤에는 path suggestion으로 노트 경로를 잡으면 된다.', 'success');
        } catch (error) {
          showToast(error.message || '폴더 생성에 실패했다.', 'error');
        }
      }

      document.addEventListener('keydown', (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's' && document.body.classList.contains('inline-editing')) {
          event.preventDefault();
          saveNote();
        }
        if (event.key === 'Escape' && document.body.classList.contains('inline-editing')) {
          closeWorkspace();
        }
      });
      dom.suggestButton?.addEventListener('click', suggestPath);
      dom.deleteButton?.addEventListener('click', deleteNote);
      dom.createFolderButton?.addEventListener('click', createFolder);
      dom.saveButton?.addEventListener('click', saveNote);
      dom.formKind?.addEventListener('input', updateKindGuide);
      dom.formKind?.addEventListener('change', updateKindGuide);

      document.addEventListener('closed-akashic-edit-request', () => openWorkspace('edit'));
      document.addEventListener('closed-akashic-save-request', () => {
        if (document.body.classList.contains('inline-editing')) saveNote();
      });
      document.addEventListener('closed-akashic-cancel-request', closeWorkspace);
      document.addEventListener('closed-akashic-auth-change', async (event) => {
        const session = event.detail || {};
        state.authorized = Boolean(session.authenticated);
        state.currentWritable = canWriteCurrent(session);
        if (state.authorized) {
          await refreshFolders();
          setBanner('마크다운 원문을 수정한 뒤 우상단 Save로 저장한다.');
        } else {
          closeWorkspace();
        }
      });

      const session = window.closedAkashicUI?.getSession?.();
      if (session?.authenticated) {
        state.authorized = true;
        state.currentWritable = canWriteCurrent(session);
        refreshFolders();
      }
      updateKindGuide();
    })();
    """
    return template.replace("__KIND_SPECS_JSON__", kind_specs_json)


def _rewrite_markdown_image(match: re.Match[str], route_prefix: str) -> str:
    alt = (match.group(1) or "").strip()
    src = (match.group(2) or "").strip()
    if not src or src.startswith(("http://", "https://", "data:", "/")):
        return match.group(0)
    if src.startswith("#"):
        return match.group(0)
    return f"![{alt}]({file_href(src, route_prefix)})"
