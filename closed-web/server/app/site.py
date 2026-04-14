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
from app.vault import file_href, list_note_paths


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


def get_closed_graph() -> dict[str, Any]:
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
            }
        )

    return {
        "nodes": sorted(nodes, key=lambda item: (-item["degree"], item["title"])),
        "links": edges,
        "meta": {
            "vault": "closed-akashic",
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


def get_closed_home_note(route_prefix: str = "") -> dict[str, Any]:
    notes = _load_notes()
    home = next((note for note in notes if note.path.lower() == "readme.md"), None)
    note = home or (notes[0] if notes else _empty_note())
    return _note_payload(note, notes, route_prefix)


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
            [note.title, note.summary, note.kind, note.project, " ".join(note.tags), note.body]
        ).lower()
        lexical_hit = bool(q and q in haystack)
        semantic_score = semantic_scores.get(note.slug, 0.0)
        if not lexical_hit and semantic_score <= 0:
            continue
        title_hit = 4 if q and q in note.title.lower() else 0
        tag_hit = 2 if q and any(q in tag.lower() for tag in note.tags) else 0
        lexical_score = title_hit + tag_hit + (haystack.count(q) if q else 0)
        score = float(lexical_score) + semantic_score * 6.0
        matches_by_slug[note.slug] = {
            "path": note.path,
            "slug": note.slug,
            "title": note.title,
            "kind": note.kind,
            "project": note.project,
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


def closed_note_html(note_slug: str | None = None, route_prefix: str = "") -> str:
    notes = _load_notes()
    route_prefix = _normalize_prefix(route_prefix)
    note = next((item for item in notes if item.slug == note_slug), None) if note_slug else None
    note = note or next((item for item in notes if item.path.lower() == "readme.md"), None)
    note = note or (notes[0] if notes else _empty_note())
    payload = _note_payload(note, notes, route_prefix)
    note_links = _explorer_html(notes, note.slug, route_prefix)
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
  <title>{html.escape(payload["title"])} | Closed Akashic</title>
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
      display: grid; gap: 16px; margin-bottom: 26px; padding-bottom: 22px;
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
  <div class="layout">
    <aside class="sidebar" id="workspace-sidebar" data-active-panel="explore">
      <div class="brand-wrap">
        <div>
          <p class="brand-kicker">Closed Akashic</p>
          <h1 class="brand">Living Notes</h1>
        </div>
      </div>
      <p class="sub">링크된 노트를 따라 기억을 쌓고 다시 꺼내 쓰는 개인 지식 창고.</p>
      <div class="sidebar-tabs" role="tablist" aria-label="Workspace sidebar">
        <button class="side-tab active" type="button" data-sidebar-tab="explore">Explore</button>
        <button class="side-tab" type="button" data-sidebar-tab="info">Info</button>
        <button class="side-tab" type="button" data-sidebar-tab="relations">Relations</button>
        <button class="side-tab" type="button" data-sidebar-tab="edit" data-admin-only hidden>Edit</button>
      </div>
      <section class="sidebar-panel" data-sidebar-panel="explore">
        <div class="search-wrap">
          <input class="search" id="note-filter" placeholder="노트 제목이나 태그 검색" />
          <div class="search-results" id="search-results"></div>
        </div>
        <div class="section-label">Explorer</div>
        <nav class="nav" id="note-nav">
          {note_links}
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
            <button class="action-button" id="edit-relations" type="button" data-admin-only hidden>Edit Related</button>
          </div>
        </section>
        {related_html}
        {backlinks_html}
      </section>
      <section class="sidebar-panel" data-sidebar-panel="edit" data-admin-only hidden>
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
              <input class="field-input" id="editor-owner" placeholder="personal" />
            </label>
            <label class="field">
              <span class="field-label">Visibility</span>
              <select class="field-select" id="editor-visibility">
                <option value="private">private</option>
                <option value="source_private">source_private</option>
                <option value="source_shared">source_shared</option>
                <option value="derived_internal">derived_internal</option>
                <option value="public_requested">public_requested</option>
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
              <span class="field-label">Scope</span>
              <select class="field-select" id="editor-scope">
                <option value="shared">shared</option>
                <option value="personal">personal</option>
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
      </section>
      <div class="sidebar-resizer" id="sidebar-resizer" role="separator" aria-orientation="vertical" aria-label="Resize sidebar" title="Drag to resize"></div>
    </aside>
    <main class="content">
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
            <span class="inline-hint" id="workspace-banner">마크다운 원문을 수정한 뒤 상단 헤더의 Save로 저장한다.</span>
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
    const input = document.getElementById('note-filter');
    const items = [...document.querySelectorAll('.nav-link')];
    const folders = [...document.querySelectorAll('.folder-group')];
    const searchBox = document.getElementById('search-results');
    const sidebarResizer = document.getElementById('sidebar-resizer');
    const pathSegments = [...document.querySelectorAll('.path-segment')];
    const sidebar = document.getElementById('workspace-sidebar');
    const leftToggle = document.getElementById('toggle-left-sidebar');
    const focusSearch = document.getElementById('focus-global-search');
    const sideTabs = [...document.querySelectorAll('[data-sidebar-tab]')];
    const editRelations = document.getElementById('edit-relations');
    const searchEndpoint = '{html.escape(_search_href(route_prefix))}';
    const sidebarWidthKey = 'closed-akashic-sidebar-width';
    const leftCollapsedKey = 'closed-akashic-left-collapsed';
    const sidebarTabKey = 'closed-akashic-sidebar-tab';
    let searchTimer = null;

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

    focusSearch?.addEventListener('click', () => {{
      setSidebarTab('explore');
      setLeftCollapsed(false);
      window.setTimeout(() => {{
        input?.focus();
        input?.select();
      }}, 80);
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
  </script>
  <script>
    {workspace_script}
  </script>
</body>
</html>"""


def closed_graph_html(route_prefix: str = "") -> str:
    route_prefix = _normalize_prefix(route_prefix)
    shared_styles = _shared_ui_styles()
    shared_header = _shared_header_html(route_prefix, "Graph")
    shared_shell = _shared_ui_shell(route_prefix)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="icon" href="data:," />
  <title>Closed Akashic Graph</title>
  <style>
    :root {{
      --bg: #f4f7fb;
      --panel: rgba(255, 255, 255, 0.86);
      --line: #d7e2ef;
      --ink: #172033;
      --muted: #5d6b82;
      --accent: #2563eb;
      --accent-2: #0f766e;
      --warm: #ea580c;
      --shadow: 0 20px 40px rgba(15, 23, 42, 0.10);
      --graph-hud-width: 420px;
      --graph-info-width: 360px;
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
    }}
    button, input {{ font: inherit; }}
    canvas {{ display: block; width: 100vw; height: calc(100svh - var(--closed-header-height)); cursor: grab; touch-action: none; }}
    canvas.grabbing {{ cursor: grabbing; }}
    .shell {{
      position: fixed; inset: calc(var(--closed-header-height) + 18px) 18px 18px;
      display: flex;
      align-items: flex-start;
      justify-content: flex-start;
      gap: 14px;
      pointer-events: none;
    }}
    .floating {{
      pointer-events: auto;
      min-width: 240px;
      max-width: min(560px, calc(100vw - 36px));
      max-height: calc(100svh - 86px);
      overflow: auto;
      resize: both;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      backdrop-filter: blur(12px);
      box-shadow: var(--shadow);
    }}
    .graph-menu {{ width: min(var(--graph-hud-width), calc(100vw - 36px)); }}
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
    .graph-menu[data-active-tab="search"] .graph-tab-panel[data-graph-panel="search"],
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
    .floating.minimized {{
      width: auto !important;
      min-width: 0;
      min-height: 0;
      max-width: calc(100vw - 36px);
      resize: none;
      overflow: visible;
    }}
    .floating.minimized .floating-inner {{ display: none; }}
    .floating.minimized .panel-bar {{ border-bottom: 0; padding: 8px; }}
    .floating.minimized .panel-label {{ max-width: 42vw; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
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
    @media (max-width: 980px) {{
      .shell {{
        inset: 64px 10px 10px;
        flex-direction: column;
        align-items: stretch;
        justify-content: flex-start;
      }}
      .floating {{
        width: min(100%, var(--graph-hud-width));
        max-width: 100%;
        max-height: 42svh;
        resize: vertical;
      }}
      .graph-menu {{ max-width: 100%; }}
      .floating-inner {{ padding: 0 14px 14px; }}
      .panel-bar {{ padding-left: 14px; }}
    }}
    @media (max-width: 560px) {{
      .shell {{ gap: 8px; }}
      .floating {{ min-width: 0; max-height: 38svh; }}
      .meta-grid {{ grid-template-columns: 1fr; }}
      .row, .actions {{ gap: 7px; }}
      .chip, .search {{ min-width: 0; max-width: 100%; }}
      .floating.minimized .panel-label {{ max-width: 62vw; }}
    }}
    {shared_styles}
  </style>
</head>
<body class="closed-with-header">
  {shared_header}
  <canvas id="graph"></canvas>
  <div class="shell">
    <section class="graph-menu floating" id="graph-menu" data-active-tab="search">
      <div class="panel-bar">
        <span class="panel-label">Graph workspace</span>
        <button class="panel-toggle" type="button" data-toggle-panel="graph-menu" aria-expanded="true">Hide</button>
      </div>
      <div class="graph-panel-tabs" role="tablist" aria-label="Graph panel tabs">
        <button class="graph-panel-tab active" type="button" data-graph-tab="search">Search</button>
        <button class="graph-panel-tab" type="button" data-graph-tab="selection">Selection</button>
        <button class="graph-panel-tab" type="button" data-graph-tab="display">Display</button>
      </div>
      <div class="floating-inner">
        <section class="graph-tab-panel" data-graph-panel="search">
          <p class="eyebrow">Closed Akashic</p>
          <h1>Graph View</h1>
          <p>노트 사이의 연결을 훑어보고, 반복되는 주제와 연결 밀도가 높은 중심 노트를 빠르게 찾는다.</p>
          <input class="search" id="graph-search" placeholder="노트, 태그, 경로 검색" />
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
          </div>
          <div class="tags" id="tags"></div>
          <div class="actions">
            <a class="button" id="open-link" href="{html.escape(_root_href(route_prefix))}">Open Note</a>
            <button class="button ghost" id="focus-link" type="button">Focus Selection</button>
          </div>
        </section>
        <section class="graph-tab-panel" data-graph-panel="display">
          <h2>Display</h2>
          <p>패널은 이 한 곳에서 접고 펼친다. 모바일에서는 세로 리사이즈로 그래프 공간을 더 확보할 수 있다.</p>
          <div class="legend">
            <span><i style="background:#2563eb"></i>concept</span>
            <span><i style="background:#0f766e"></i>playbook</span>
            <span><i style="background:#ea580c"></i>incident/decision</span>
          </div>
          <div class="row">
            <button class="chip" id="graph-focus-search" type="button">Focus Search</button>
            <button class="chip" id="graph-focus-selection" type="button">Focus Selection</button>
          </div>
        </section>
        <div class="actions" style="margin-top: 16px;">
          <button class="button ghost" id="graph-show-menu" type="button">Show Menu</button>
        </div>
      </div>
    </section>
  </div>
  {shared_shell}
  <script>
    const canvas = document.getElementById('graph');
    const ctx = canvas.getContext('2d');
    const searchInput = document.getElementById('graph-search');
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
      search: '',
      adjacency: new Map(),
      clusters: new Map(),
      activePointer: null,
    }};
    const panelStateKey = 'closed-akashic-graph-panels';
    const panelToggles = [...document.querySelectorAll('[data-toggle-panel]')];
    const graphMenu = document.getElementById('graph-menu');
    const graphTabs = [...document.querySelectorAll('[data-graph-tab]')];
    const graphFocusSearch = document.getElementById('graph-focus-search');
    const graphFocusSelection = document.getElementById('graph-focus-selection');

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
      if (node.kind === 'concept') return '#2563eb';
      if (node.kind === 'playbook' || node.kind === 'pattern') return '#0f766e';
      if (node.kind === 'incident' || node.kind === 'decision') return '#ea580c';
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
      for (const node of state.nodes) {{
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
      const searchBoost = state.search && matchesSearch(node) ? 2 : 0;
      return 7 + Math.min(14, node.degree * 1.7) + searchBoost;
    }}

    function matchesSearch(node) {{
      const haystack = `${{node.title}} ${{node.path}} ${{(node.tags || []).join(' ')}}`.toLowerCase();
      return state.search && haystack.includes(state.search);
    }}

    function relatedToActive(node) {{
      if (!state.selected) return false;
      if (state.selected.id === node.id) return true;
      return state.adjacency.get(state.selected.id)?.has(node.id);
    }}

    function stepPhysics() {{
      const centerX = (window.innerWidth / 2 - state.offsetX) / state.zoom;
      const centerY = (window.innerHeight / 2 - state.offsetY) / state.zoom;
      const lookup = new Map(state.nodes.map(node => [node.id, node]));

      for (let i = 0; i < state.nodes.length; i += 1) {{
        const a = state.nodes[i];
        if (a === state.draggingNode) continue;

        const cluster = state.clusters.get(clusterKey(a)) || {{ x: centerX, y: centerY }};
        a.vx += (cluster.x - a.x) * 0.0009;
        a.vy += (cluster.y - a.y) * 0.0009;
        a.vx += (centerX - a.x) * 0.00014;
        a.vy += (centerY - a.y) * 0.00014;

        for (let j = i + 1; j < state.nodes.length; j += 1) {{
          const b = state.nodes[j];
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

      for (const edge of state.links) {{
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

      for (const node of state.nodes) {{
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

      const lookup = new Map(state.nodes.map(node => [node.id, node]));
      ctx.save();
      ctx.translate(state.offsetX, state.offsetY);
      ctx.scale(state.zoom, state.zoom);

      for (const edge of state.links) {{
        const a = lookup.get(edge.source);
        const b = lookup.get(edge.target);
        if (!a || !b) continue;
        const active = state.selected && (edge.source === state.selected.id || edge.target === state.selected.id);
        const searchHit = state.search && (matchesSearch(a) || matchesSearch(b));
        ctx.strokeStyle = active ? 'rgba(37,99,235,.52)' : searchHit ? 'rgba(15,118,110,.34)' : 'rgba(100,116,139,.18)';
        ctx.lineWidth = active ? 1.5 / state.zoom : 1 / state.zoom;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }}

      for (const node of state.nodes) {{
        const active = state.selected && state.selected.id === node.id;
        const hovered = state.hover && state.hover.id === node.id;
        const related = relatedToActive(node);
        const searchHit = matchesSearch(node);
        const radius = nodeRadius(node) + (active ? 5 : hovered ? 2 : 0);
        const color = active ? '#0f766e' : nodeColor(node);
        ctx.beginPath();
        ctx.fillStyle = color;
        ctx.globalAlpha = active || related || hovered || searchHit || !state.search ? 0.96 : 0.42;
        ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
        ctx.fill();

        if (active || hovered || searchHit) {{
          ctx.beginPath();
          ctx.lineWidth = 2 / state.zoom;
          ctx.strokeStyle = 'rgba(255,255,255,.92)';
          ctx.arc(node.x, node.y, radius + 3, 0, Math.PI * 2);
          ctx.stroke();
        }}

        const label = active || hovered || related || searchHit || node.degree >= 4;
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
      document.getElementById('tags').innerHTML = (node.tags || []).map(tag => `<span class="tag">#${{tag}}</span>`).join('') || '<span class="tag">#untagged</span>';
      document.getElementById('open-link').href = `{html.escape(_notes_base(route_prefix))}/${{node.slug}}`;
    }}

    function readPanelState() {{
      try {{
        return JSON.parse(window.localStorage.getItem(panelStateKey) || '{{}}');
      }} catch (error) {{
        return {{}};
      }}
    }}

    function writePanelState(value) {{
      window.localStorage.setItem(panelStateKey, JSON.stringify(value));
    }}

    function applyPanelState() {{
      const saved = readPanelState();
      panelToggles.forEach((button) => {{
        const id = button.dataset.togglePanel;
        const panel = document.getElementById(id);
        const minimized = Boolean(saved[id]);
        panel?.classList.toggle('minimized', minimized);
        button.textContent = minimized ? 'Show' : 'Hide';
        button.setAttribute('aria-expanded', minimized ? 'false' : 'true');
      }});
    }}

    function setPanelMinimized(id, minimized) {{
      const saved = readPanelState();
      saved[id] = minimized;
      writePanelState(saved);
      applyPanelState();
    }}

    function togglePanel(id) {{
      const saved = readPanelState();
      setPanelMinimized(id, !saved[id]);
    }}

    function setGraphTab(tab) {{
      const next = ['search', 'selection', 'display'].includes(tab) ? tab : 'search';
      graphMenu?.setAttribute('data-active-tab', next);
      graphTabs.forEach((button) => button.classList.toggle('active', button.dataset.graphTab === next));
    }}

    function focusSelected() {{
      if (!state.selected) return;
      state.offsetX = window.innerWidth * 0.5 - state.selected.x * state.zoom;
      state.offsetY = window.innerHeight * 0.5 - state.selected.y * state.zoom;
    }}

    async function boot() {{
      resize();
      applyPanelState();
      const data = await fetch('{html.escape(_graph_data_href(route_prefix))}').then(res => res.json());
      state.nodes = data.nodes;
      state.links = data.links;
      buildAdjacency();
      document.getElementById('stats').textContent = `${{data.meta.note_count}} notes · ${{data.meta.link_count}} links`;
      state.offsetX = window.innerWidth * 0.12;
      state.offsetY = window.innerHeight * 0.08;
      init();
      if (state.nodes[0]) show(state.nodes[0]);
      tick();
    }}

    function tick() {{
      stepPhysics();
      render();
      requestAnimationFrame(tick);
    }}

    window.addEventListener('resize', resize);
    searchInput.addEventListener('input', () => {{
      state.search = searchInput.value.trim().toLowerCase();
    }});
    document.getElementById('focus-link').addEventListener('click', focusSelected);
    panelToggles.forEach((button) => {{
      button.addEventListener('click', () => togglePanel(button.dataset.togglePanel));
    }});
    graphTabs.forEach((button) => {{
      button.addEventListener('click', () => setGraphTab(button.dataset.graphTab || 'search'));
    }});
    graphFocusSearch?.addEventListener('click', () => {{
      setPanelMinimized('graph-menu', false);
      setGraphTab('search');
      window.setTimeout(() => searchInput.focus(), 80);
    }});
    graphFocusSelection?.addEventListener('click', () => {{
      setPanelMinimized('graph-menu', false);
      setGraphTab('selection');
      focusSelected();
    }});

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
      if (node) {{
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
    shared_header = _shared_header_html(route_prefix, "Debug")
    shared_shell = _shared_ui_shell(route_prefix)
    template = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="icon" href="data:," />
  <title>Closed Akashic Debug</title>
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
    body { padding: 28px clamp(16px, 3vw, 38px) 42px; }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    button, input, select { font: inherit; }
    .shell {
      width: min(1280px, 100%);
      margin: 0 auto;
      display: grid;
      gap: 18px;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: flex-start;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--line);
    }
    .eyebrow {
      margin: 0 0 8px;
      color: var(--accent-2);
      font-size: .74rem;
      font-weight: 800;
      letter-spacing: .08em;
      text-transform: uppercase;
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
      justify-content: flex-end;
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
    .grid {
      display: grid;
      grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }
    .grid.filters-collapsed {
      grid-template-columns: minmax(0, 1fr);
    }
    .grid.filters-collapsed .side {
      display: none;
    }
    .panel {
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
      border: 1px solid var(--line);
      border-radius: 8px;
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
    @media (max-width: 1040px) {
      .grid { grid-template-columns: 1fr; }
      .side { position: static; }
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .request { grid-template-columns: 110px 70px minmax(0, 1fr); }
      .request .duration { text-align: left; }
      .detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .payload-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 720px) {
      body { padding: 20px 14px 28px; }
      .topbar { display: grid; }
      .quicklinks, .actions { justify-content: flex-start; }
      .metrics, .filter-grid { grid-template-columns: 1fr; }
      .filter-grid .span-2 { grid-column: auto; }
      .request { grid-template-columns: 1fr; }
      .duration { text-align: left; }
      .detail-grid { grid-template-columns: 1fr; }
      .modal-shell { padding: 10px; place-items: stretch; }
      .modal { max-height: calc(100svh - 20px); }
      .modal-head, .modal-body { padding: 14px; }
    }
    __SHARED_STYLES__
  </style>
</head>
<body class="closed-with-header">
  __SHARED_HEADER__
  <main class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Closed Akashic</p>
        <h1>Debug Console</h1>
        <p class="lead">MCP, API, 페이지 요청을 한 화면에서 검색하고 시간순, 종류순, 상태순으로 좁혀 본다.</p>
      </div>
      <nav class="quicklinks">
        <button class="chip" id="toggle-debug-filters" type="button" aria-pressed="false">Filters</button>
      </nav>
    </header>

    <section class="grid" id="debug-grid">
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
          <div class="empty">토큰을 입력하면 최근 요청을 불러온다.</div>
        </div>
      </section>
    </section>
  </main>
  __SHARED_SHELL__
  <div class="modal-shell" id="request-modal" hidden>
    <div class="modal-backdrop" data-close-modal></div>
    <section class="modal" role="dialog" aria-modal="true" aria-labelledby="request-modal-title">
      <header class="modal-head">
        <div>
          <p class="eyebrow">Request detail</p>
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
        timer: null,
        loading: false,
        status: null,
        events: [],
      };
      const dom = {
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
        debugGrid: document.getElementById('debug-grid'),
        filtersToggle: document.getElementById('toggle-debug-filters'),
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

      async function fetchJson(path) {
        if (window.closedAkashicUI?.requestJson) {
          return window.closedAkashicUI.requestJson(path);
        }
        const response = await fetch(`${apiBase}${path}`, { mode: 'cors' });
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
      }

      async function refresh() {
        if (!token()) {
          setAuthText('토큰을 입력하면 디버그 데이터를 볼 수 있다.', 'warn');
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

      dom.refresh.addEventListener('click', refresh);
      dom.reset.addEventListener('click', resetFilters);
      dom.filtersToggle.addEventListener('click', () => {
        const collapsed = !dom.debugGrid.classList.contains('filters-collapsed');
        dom.debugGrid.classList.toggle('filters-collapsed', collapsed);
        dom.filtersToggle.setAttribute('aria-pressed', String(collapsed));
      });
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
      document.addEventListener('closed-akashic-auth-change', refresh);
      [dom.q, dom.kind, dom.method, dom.statusMin, dom.limit, dom.sort, dom.order, dom.requestId]
        .forEach((element) => element.addEventListener('input', scheduleRefresh));

      refresh();
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
        kind=str(frontmatter.get("kind") or "note"),
        project=str(frontmatter.get("project") or "closed-akashic"),
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
        title="Closed Akashic",
        kind="index",
        project="closed-akashic",
        status="empty",
        owner=get_settings().default_note_owner,
        visibility=get_settings().default_note_visibility,
        publication_status="none",
        tags=[],
        related=[],
        summary="아직 노트가 없습니다.",
        body="## Summary\nClosed Akashic vault is empty.",
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
    return f"{route_prefix}/debug" if route_prefix else "/debug"


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
    note_action_html = ""
    if note_actions:
        note_action_html = """
          <button class="global-pill is-primary" id="global-edit-note" type="button" data-admin-only data-edit-view="edit" hidden>Edit</button>
          <button class="global-pill is-primary" id="global-save-note" type="button" data-admin-only data-edit-view="save" hidden>Save</button>
          <button class="global-pill" id="global-cancel-note" type="button" data-admin-only data-edit-view="save" hidden>Cancel</button>
        """
    return f"""
    <header class="global-header">
      <div class="global-brand">
        <div class="global-brand-mark">OA</div>
        <div class="global-brand-copy">
          <div class="global-brand-title">OpenAkashic / Closed</div>
          <div class="global-brand-subtitle">{html.escape(page_label)}</div>
        </div>
      </div>
      <nav class="global-nav" aria-label="Primary">
        <a class="global-pill" href="{html.escape(_root_href(route_prefix))}">Home</a>
        <a class="global-pill" href="{html.escape(_graph_href(route_prefix))}">Graph</a>
        <a class="global-pill" href="{html.escape(_debug_href(route_prefix))}">Debug</a>
      </nav>
      <div class="global-actions">
        {note_action_html}
        <button class="global-pill global-auth-button" id="global-auth-trigger" type="button" data-tone="warn">Admin</button>
      </div>
    </header>
    """


def _shared_ui_shell(route_prefix: str) -> str:
    config = _json_script_text({"apiBase": ""})
    return f"""
    <div class="global-modal" id="global-auth-modal" hidden>
      <div class="global-modal-backdrop" data-close-auth-modal></div>
      <section class="global-modal-card" role="dialog" aria-modal="true" aria-labelledby="global-auth-title">
        <h2 id="global-auth-title">관리자 토큰</h2>
        <p>현재 브라우저에만 토큰을 저장하고, 관리자 권한이 확인되면 편집과 사서장 기능이 열린다.</p>
        <div class="global-modal-grid">
          <input class="global-token-input" id="global-token-input" type="password" placeholder="CLOSED_AKASHIC_TOKEN" autocomplete="off" />
        </div>
        <div class="global-modal-actions">
          <button class="global-pill is-primary" id="global-token-apply" type="button">Apply</button>
          <button class="global-pill" id="global-token-clear" type="button">Clear</button>
          <button class="global-pill" id="global-token-close" type="button">Close</button>
        </div>
        <div class="global-status" id="global-auth-status">토큰을 적용하면 이 브라우저에서만 관리자 상태가 유지된다.</div>
      </section>
    </div>
    <section class="librarian-fab" id="librarian-shell" data-admin-only hidden data-open="false">
      <div class="librarian-panel">
        <div class="librarian-head">
          <div class="librarian-head-row">
            <div>
              <p class="librarian-kicker">Librarian</p>
              <h2 class="librarian-title">사서장</h2>
              <p class="librarian-subtitle">관리자 상태에서만 보이는 운영 사서장이다. 명령을 내리거나 보고를 받을 수 있다.</p>
            </div>
            <button class="librarian-close" id="librarian-close" type="button" aria-label="Close librarian">×</button>
          </div>
        </div>
        <div class="librarian-messages" id="librarian-messages"></div>
        <div class="librarian-compose">
          <textarea class="librarian-textarea" id="librarian-input" placeholder="사서장에게 요청하거나 보고를 받아보세요."></textarea>
          <div class="librarian-compose-row" style="margin-top:10px;">
            <div class="librarian-tools" id="librarian-status">관리자 토큰이 활성화되면 사서장과 대화할 수 있다.</div>
            <button class="global-pill is-primary" id="librarian-send" type="button">Send</button>
          </div>
        </div>
      </div>
      <button class="librarian-launcher" id="librarian-launcher" type="button">사서장</button>
    </section>
    <script type="application/json" id="closed-global-config">{config}</script>
    <script>
      (() => {{
        const config = JSON.parse(document.getElementById('closed-global-config')?.textContent || '{{}}');
        const apiBase = String(config.apiBase || '').replace(/\\/$/, '');
        const tokenStorageKey = 'closed-akashic-token';
        const threadStorageKey = 'closed-akashic-librarian-thread';
        const state = {{
          session: {{ authenticated: false, role: 'anonymous', capabilities: [] }},
          thread: [],
        }};
        const dom = {{
          authTrigger: document.getElementById('global-auth-trigger'),
          authModal: document.getElementById('global-auth-modal'),
          authInput: document.getElementById('global-token-input'),
          authApply: document.getElementById('global-token-apply'),
          authClear: document.getElementById('global-token-clear'),
          authClose: document.getElementById('global-token-close'),
          authStatus: document.getElementById('global-auth-status'),
          authDismiss: [...document.querySelectorAll('[data-close-auth-modal]')],
          adminOnly: [...document.querySelectorAll('[data-admin-only]')],
          editButton: document.getElementById('global-edit-note'),
          saveButton: document.getElementById('global-save-note'),
          cancelButton: document.getElementById('global-cancel-note'),
          librarianShell: document.getElementById('librarian-shell'),
          librarianLauncher: document.getElementById('librarian-launcher'),
          librarianClose: document.getElementById('librarian-close'),
          librarianMessages: document.getElementById('librarian-messages'),
          librarianInput: document.getElementById('librarian-input'),
          librarianSend: document.getElementById('librarian-send'),
          librarianStatus: document.getElementById('librarian-status'),
        }};

        function token() {{
          return window.localStorage.getItem(tokenStorageKey) || '';
        }}

        function setAuthButton(session) {{
          if (!dom.authTrigger) return;
          const isAdmin = Boolean(session?.authenticated && session?.role === 'admin');
          dom.authTrigger.dataset.tone = isAdmin ? 'admin' : 'warn';
          dom.authTrigger.textContent = isAdmin ? 'Admin Active' : 'Admin';
        }}

        function setAdminVisible(visible) {{
          document.body.classList.toggle('is-admin', visible);
          dom.adminOnly.forEach((node) => {{
            node.hidden = !visible;
          }});
        }}

        function setAuthStatus(message) {{
          if (dom.authStatus) dom.authStatus.textContent = message;
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
              setAuthStatus(isAdmin ? '관리자 권한이 활성화되었다.' : '유효한 관리자 토큰이 아직 없다.');
            }}
            if (dom.librarianStatus) {{
              dom.librarianStatus.textContent = isAdmin
                ? `모델: ${{session?.librarian?.model || 'unknown'}}`
                : '관리자 토큰이 활성화되면 사서장과 대화할 수 있다.';
            }}
            dispatchAuthChange();
            return session;
          }} catch (error) {{
            state.session = {{ authenticated: false, role: 'anonymous', capabilities: [] }};
            setAdminVisible(false);
            setAuthButton(state.session);
            if (!silent) {{
              setAuthStatus(error.message || '토큰 확인에 실패했다.');
            }}
            dispatchAuthChange();
            return state.session;
          }}
        }}

        function openAuthModal() {{
          if (dom.authModal) dom.authModal.hidden = false;
          if (dom.authInput) {{
            dom.authInput.value = token();
            window.setTimeout(() => dom.authInput.focus(), 40);
          }}
        }}

        function closeAuthModal() {{
          if (dom.authModal) dom.authModal.hidden = true;
        }}

        async function applyToken() {{
          const value = dom.authInput?.value.trim() || '';
          if (!value) {{
            setAuthStatus('먼저 토큰을 넣어야 한다.');
            return;
          }}
          window.localStorage.setItem(tokenStorageKey, value);
          const session = await refreshSession();
          if (session?.authenticated && session?.role === 'admin') {{
            closeAuthModal();
          }}
        }}

        function clearToken() {{
          window.localStorage.removeItem(tokenStorageKey);
          if (dom.authInput) dom.authInput.value = '';
          refreshSession();
          setAuthStatus('토큰을 지웠다. 지금은 읽기 전용이다.');
        }}

        function loadThread() {{
          try {{
            const raw = window.localStorage.getItem(threadStorageKey);
            state.thread = raw ? JSON.parse(raw) : [];
          }} catch (error) {{
            state.thread = [];
          }}
        }}

        function saveThread() {{
          window.localStorage.setItem(threadStorageKey, JSON.stringify(state.thread.slice(-20)));
        }}

        function renderThread() {{
          if (!dom.librarianMessages) return;
          if (!state.thread.length) {{
            dom.librarianMessages.innerHTML = '<div class="librarian-message" data-role="assistant"><div class="librarian-message-meta">Librarian</div><div>관리자 토큰이 활성화되면 사서장에게 운영 명령이나 정리 요청을 보낼 수 있다.</div></div>';
            return;
          }}
          dom.librarianMessages.innerHTML = state.thread.map((item) => `
            <div class="librarian-message" data-role="${{item.role}}">
              <div class="librarian-message-meta">${{item.role === 'assistant' ? 'Librarian' : 'You'}}</div>
              <div>${{String(item.content || '').replace(/[&<>]/g, (ch) => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[ch]))}}</div>
            </div>
          `).join('');
          dom.librarianMessages.scrollTop = dom.librarianMessages.scrollHeight;
        }}

        function toggleLibrarian(open) {{
          if (!dom.librarianShell) return;
          dom.librarianShell.dataset.open = open ? 'true' : 'false';
          if (open) {{
            renderThread();
            window.setTimeout(() => dom.librarianInput?.focus(), 80);
          }}
        }}

        async function sendToLibrarian() {{
          if (!(state.session?.authenticated && state.session?.role === 'admin')) {{
            openAuthModal();
            return;
          }}
          const message = dom.librarianInput?.value.trim() || '';
          if (!message) return;
          state.thread.push({{ role: 'user', content: message }});
          dom.librarianInput.value = '';
          renderThread();
          if (dom.librarianStatus) dom.librarianStatus.textContent = '사서장이 답변을 준비하는 중이다.';
          try {{
            const data = await requestJson('/api/librarian/chat', {{
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
                : '사서장이 응답했다.';
            }}
          }} catch (error) {{
            state.thread.push({{ role: 'assistant', content: error.message || '사서장 요청에 실패했다.' }});
            renderThread();
            if (dom.librarianStatus) dom.librarianStatus.textContent = error.message || '사서장 요청 실패';
          }}
        }}

        dom.authTrigger?.addEventListener('click', openAuthModal);
        dom.authApply?.addEventListener('click', applyToken);
        dom.authClear?.addEventListener('click', clearToken);
        dom.authClose?.addEventListener('click', closeAuthModal);
        dom.authDismiss.forEach((node) => node.addEventListener('click', closeAuthModal));
        dom.authInput?.addEventListener('keydown', (event) => {{
          if (event.key === 'Enter') applyToken();
          if (event.key === 'Escape') closeAuthModal();
        }});
        dom.editButton?.addEventListener('click', () => document.dispatchEvent(new CustomEvent('closed-akashic-edit-request')));
        dom.saveButton?.addEventListener('click', () => document.dispatchEvent(new CustomEvent('closed-akashic-save-request')));
        dom.cancelButton?.addEventListener('click', () => document.dispatchEvent(new CustomEvent('closed-akashic-cancel-request')));
        dom.librarianLauncher?.addEventListener('click', () => toggleLibrarian(dom.librarianShell?.dataset.open !== 'true'));
        dom.librarianClose?.addEventListener('click', () => toggleLibrarian(false));
        dom.librarianSend?.addEventListener('click', sendToLibrarian);
        dom.librarianInput?.addEventListener('keydown', (event) => {{
          if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {{
            sendToLibrarian();
          }}
        }});

        loadThread();
        renderThread();
        if (token()) {{
          refreshSession({{ silent: true }});
        }} else {{
          setAdminVisible(false);
          setAuthButton(state.session);
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
    return """
    <div class="workspace-shell" id="workspace-shell">
      <div class="toast" id="workspace-toast" data-tone="success"></div>
      <datalist id="editor-kind-options">
        <option value="note"></option>
        <option value="index"></option>
        <option value="concept"></option>
        <option value="playbook"></option>
        <option value="architecture"></option>
        <option value="schema"></option>
        <option value="incident"></option>
        <option value="decision"></option>
        <option value="experiment"></option>
        <option value="reference"></option>
        <option value="workflow"></option>
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
    return """
    (() => {
      const noteData = JSON.parse(document.getElementById('closed-note-data')?.textContent || '{}');
      const state = {
        authorized: false,
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
        noteFolderOptions: document.getElementById('editor-folder-options'),
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
          setBanner('마크다운 원문을 수정한 뒤 상단 헤더의 Save로 저장한다.');
        }
      }

      async function openWorkspace(mode) {
        if (!state.authorized) {
          setSidebarPanel('edit');
          showToast('먼저 관리자 토큰을 적용해줘.', 'warn');
          window.closedAkashicUI?.openAuthModal?.();
          if (!state.authorized) return;
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
          showToast('먼저 관리자 토큰을 적용해줘.', 'warn');
          window.closedAkashicUI?.openAuthModal?.();
          return;
        }
        dom.folderPath?.focus();
      }

      function presetNewNote() {
        const inheritedProject = noteData.project && noteData.project !== 'closed-akashic' ? noteData.project : '';
        state.originalPath = '';
        dom.formTitle.value = '';
        dom.formSummary.value = '';
        dom.formKind.value = 'reference';
        dom.formProject.value = inheritedProject;
        dom.formStatus.value = 'active';
        dom.formOwner.value = 'personal';
        dom.formVisibility.value = 'private';
        dom.formPublicationStatus.value = 'none';
        dom.formScope.value = inheritedProject ? 'shared' : 'shared';
        dom.formFolder.value = '';
        dom.formPath.value = '';
        dom.formTags.value = '';
        dom.formRelated.value = '';
        dom.formBody.value = '## Summary\\n\\n';
        dom.folderPath.value = '';
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
          dom.formOwner.value = fm.owner || noteData.owner || 'personal';
          dom.formVisibility.value = fm.visibility || noteData.visibility || 'private';
          dom.formPublicationStatus.value = fm.publication_status || noteData.publication_status || 'none';
          dom.formScope.value = dom.formProject.value ? 'shared' : 'shared';
          dom.formFolder.value = '';
          dom.formPath.value = raw.path || noteData.path || '';
          dom.formTags.value = Array.isArray(fm.tags) ? fm.tags.join(', ') : (noteData.tags || []).join(', ');
          dom.formRelated.value = Array.isArray(fm.related) ? fm.related.join(', ') : (noteData.related || []).join(', ');
          dom.formBody.value = raw.body || noteData.body || '## Summary\\n\\n';
          dom.folderPath.value = '';
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
            owner: dom.formOwner.value.trim() || 'personal',
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
          setBanner('저장을 마쳤다.', 'success');
          showToast('노트를 저장했다.', 'success');
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

      document.addEventListener('closed-akashic-edit-request', () => openWorkspace('edit'));
      document.addEventListener('closed-akashic-save-request', () => {
        if (document.body.classList.contains('inline-editing')) saveNote();
      });
      document.addEventListener('closed-akashic-cancel-request', closeWorkspace);
      document.addEventListener('closed-akashic-auth-change', async (event) => {
        const session = event.detail || {};
        state.authorized = Boolean(session.authenticated && session.role === 'admin');
        if (state.authorized) {
          await refreshFolders();
          setBanner('마크다운 원문을 수정한 뒤 상단 헤더의 Save로 저장한다.');
        } else {
          closeWorkspace();
        }
      });

      const session = window.closedAkashicUI?.getSession?.();
      if (session?.authenticated && session?.role === 'admin') {
        state.authorized = true;
        refreshFolders();
      }
    })();
    """


def _rewrite_markdown_image(match: re.Match[str], route_prefix: str) -> str:
    alt = (match.group(1) or "").strip()
    src = (match.group(2) or "").strip()
    if not src or src.startswith(("http://", "https://", "data:", "/")):
        return match.group(0)
    if src.startswith("#"):
        return match.group(0)
    return f"![{alt}]({file_href(src, route_prefix)})"
