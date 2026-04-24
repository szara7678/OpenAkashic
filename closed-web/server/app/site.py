from __future__ import annotations

import html
import json
import math
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import markdown

try:
    import nh3 as _nh3

    _ALLOWED_TAGS = {
        "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li", "dl", "dt", "dd",
        "table", "thead", "tbody", "tr", "th", "td",
        "blockquote", "pre", "code", "em", "strong", "del", "s",
        "a", "img", "sup", "sub", "span", "div",
        "details", "summary",
    }
    _ALLOWED_ATTRS: dict[str, set[str]] = {
        "a": {"href", "title", "class", "data-note-slug"},
        "img": {"src", "alt", "title", "width", "height", "class"},
        "code": {"class"},
        "pre": {"class"},
        "h2": {"id"},
        "h3": {"id"},
        "span": {"class"},
        "div": {"class"},
        "td": {"align"},
        "th": {"align"},
    }

    def _sanitize_html(raw_html: str) -> str:
        return _nh3.clean(raw_html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS)
except ImportError:
    import logging as _logging
    _logging.getLogger(__name__).warning("nh3 not installed — markdown output will NOT be sanitized (XSS risk)")

    def _sanitize_html(raw_html: str) -> str:  # type: ignore[misc]
        return raw_html

from app.config import get_settings
from app.fts_search import FTSDocument, lexical_rank
from app.semantic_search import SemanticDocument, semantic_rank
from app.vault import file_href, kind_catalog, kind_template_sections, list_note_paths, load_document, normalize_kind


WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]")
EMBED_LINK_PATTERN = re.compile(r"!\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]")
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

_NOTES_CACHE: list["ClosedNote"] | None = None
_NOTES_CACHE_AT = 0.0
_NOTES_CACHE_TTL = 30.0
_NOTES_CACHE_LOCK = threading.Lock()
_DECAY_TIER_DAYS = {
    "legal": 30,
    "product": 60,
    "general": 90,
}


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
    frontmatter: dict[str, Any] = field(default_factory=dict)
    confirm_count: int = 0
    dispute_count: int = 0
    neutral_count: int = 0
    claim_review_status: str = "unreviewed"
    original_owner: str = ""
    created_by: str = ""
    freshness_date: str = ""
    decay_tier: str = "general"
    snoozed_until: str = ""
    claim_id: str = ""
    targets: str | None = None
    stance: str = ""
    claim_review_lifecycle: str = ""
    self_authored: bool = False
    evidence_urls: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    topic: str = ""
    target_title_snapshot: str = ""


def _targeted_claim_lifecycle(frontmatter: dict[str, Any]) -> str:
    value = str(frontmatter.get("claim_review_lifecycle") or "").strip().lower()
    if value:
        return value
    legacy = str(frontmatter.get("review_status") or "").strip().lower()
    return legacy or "active"


def _viewer_can_open_note(note: ClosedNote, viewer_owner: str | None, is_admin: bool) -> bool:
    if note.visibility == "public":
        return True
    if is_admin:
        return True
    if note.visibility == "shared":
        return bool(viewer_owner)  # 인증된 사용자라면 누구든 읽기 가능
    owner = (viewer_owner or "").strip()
    return bool(owner and note.owner == owner)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


_CLAIM_REVIEW_STATES = {"unreviewed", "confirmed", "disputed", "superseded", "merged"}


def _effective_dispute_count(frontmatter: dict[str, Any], owner: str) -> int:
    if "disputed_by" not in frontmatter:
        return _as_int(frontmatter.get("dispute_count"))
    owner_value = str(owner or "").strip()
    return sum(1 for caller in _confirmation_callers(frontmatter.get("disputed_by")) if caller != owner_value)


def _normalize_claim_review_status(frontmatter: dict[str, Any], *, kind: str, confirm_count: int, dispute_count: int) -> str:
    raw = str(frontmatter.get("claim_review_status") or "").strip().lower()
    if raw in _CLAIM_REVIEW_STATES:
        return raw
    publication_status = str(frontmatter.get("publication_status") or "").strip().lower()
    if publication_status == "superseded":
        return "superseded"
    if publication_status == "needs_merge":
        return "merged"
    if dispute_count > 0:
        return "disputed"
    if kind == "claim" and confirm_count > 0:
        return "confirmed"
    return "unreviewed"


def _claim_trust_badge(status: str) -> str:
    mapping = {
        "confirmed": "Confirmed",
        "disputed": "Disputed",
        "superseded": "Superseded",
        "merged": "Merged",
        "unreviewed": "Unreviewed",
    }
    return mapping.get(status, "Unreviewed")


def _claim_trust_multiplier(status: str, confirm_count: int, dispute_count: int) -> float:
    base = {
        "unreviewed": 1.0,
        "confirmed": 1.08,
        "disputed": 0.74,
        "superseded": 0.35,
        "merged": 0.46,
    }.get(status, 1.0)
    confirm_boost = 1.0 + 0.05 * math.log(1 + max(0, confirm_count))
    dispute_penalty = 1.0 / (1.0 + 0.18 * max(0, dispute_count))
    if status in {"superseded", "merged"}:
        confirm_boost = 1.0
    return base * confirm_boost * dispute_penalty


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
    all_notes = _load_notes()
    notes = _filter_notes_for_viewer(all_notes, viewer_owner=viewer_owner, is_admin=is_admin)
    visible_slugs = {note.slug for note in notes}
    # 전체 인덱스(참조 해석용) — 비공개 노트도 조회 가능해야 "공개 노트가 비공개를 참조"를 식별할 수 있음
    all_by_title = {note.title.lower(): note for note in all_notes}
    all_by_slug = {note.slug.lower(): note for note in all_notes}

    restricted_notes: dict[str, ClosedNote] = {}
    inbound_count: dict[str, int] = {note.slug: 0 for note in notes}
    outbound_count: dict[str, int] = {note.slug: 0 for note in notes}
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for note in notes:
        for target_name in [*note.links, *note.related]:
            target = all_by_title.get(target_name.lower()) or all_by_slug.get(_slugify(target_name).lower())
            if not target or target.slug == note.slug:
                continue
            # 공개 노트가 참조하는 비공개 노트는 redacted 자리표시자 노드로 포함.
            # (렌더된 본문의 [[wikilink]]가 이미 제목을 노출하므로 엣지 자체는 숨기지 않고,
            #  대신 민감 필드는 서버에서 걸러서 전달)
            if target.slug not in visible_slugs:
                if not is_admin:
                    restricted_notes[target.slug] = target
                    inbound_count.setdefault(target.slug, 0)
                    outbound_count.setdefault(target.slug, 0)
                else:
                    continue
            edge = (note.slug, target.slug)
            if edge in seen:
                continue
            seen.add(edge)
            inbound_count[target.slug] = inbound_count.get(target.slug, 0) + 1
            outbound_count[note.slug] = outbound_count.get(note.slug, 0) + 1
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
                "claim_review_status": note.claim_review_status,
                "claim_review_badge": _claim_trust_badge(note.claim_review_status),
                "confirm_count": note.confirm_count,
                "dispute_count": note.dispute_count,
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

    for slug, note in restricted_notes.items():
        degree = inbound_count.get(slug, 0) + outbound_count.get(slug, 0)
        nodes.append(
            {
                "id": note.slug,
                "slug": note.slug,
                # 자리표시자: 제목은 공개 본문의 [[wikilink]]로 이미 노출되므로 노출하되
                # path/owner/project/summary/tags/status 등은 일체 숨김.
                "title": note.title,
                "kind": "restricted",
                "project": "",
                "status": "",
                "owner": "",
                "visibility": "private",
                "publication_status": "",
                "claim_review_status": "",
                "claim_review_badge": "",
                "confirm_count": 0,
                "dispute_count": 0,
                "tags": [],
                "summary": "",
                "path": "",
                "inbound": inbound_count.get(slug, 0),
                "outbound": outbound_count.get(slug, 0),
                "degree": degree,
                "size": 0,
                "can_open": False,
                "can_write": False,
                "restricted": True,
            }
        )

    return {
        "nodes": sorted(nodes, key=lambda item: (-item["degree"], item["title"])),
        "links": edges,
        "edges": edges,  # alias for graph-convention clients
        "meta": {
            "vault": "openakashic",
            "note_count": len(nodes),
            "link_count": len(edges),
            "edge_count": len(edges),  # alias for graph-convention clients
            "source": get_settings().closed_akashic_path,
        },
    }


def get_closed_note(
    path: str,
    route_prefix: str = "",
    *,
    viewer_owner: str | None = None,
    is_admin: bool = False,
) -> dict[str, Any] | None:
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
    visible_notes = _filter_notes_for_viewer(notes, viewer_owner=viewer_owner, is_admin=is_admin)
    return _note_payload(note, visible_notes or [note], route_prefix, viewer_owner=viewer_owner, is_admin=is_admin)


def get_closed_note_by_slug(
    slug: str,
    route_prefix: str = "",
    *,
    viewer_owner: str | None = None,
    is_admin: bool = False,
) -> dict[str, Any] | None:
    notes = _load_notes()
    note = next((item for item in notes if item.slug == slug), None)
    if not note:
        return None
    visible_notes = _filter_notes_for_viewer(notes, viewer_owner=viewer_owner, is_admin=is_admin)
    return _note_payload(note, visible_notes or [note], route_prefix, viewer_owner=viewer_owner, is_admin=is_admin)


def list_stale_closed_notes(days_overdue: int = 0) -> list[dict[str, Any]]:
    min_overdue = max(0, int(days_overdue or 0))
    today = date.today()
    stale: list[dict[str, Any]] = []
    for note in _load_notes():
        freshness = _parse_iso_date(note.freshness_date)
        if not freshness:
            continue
        snoozed_until = _parse_iso_date(note.snoozed_until)
        if snoozed_until and snoozed_until > today:
            continue
        tier = note.decay_tier if note.decay_tier in _DECAY_TIER_DAYS else "general"
        due_date = freshness.toordinal() + _DECAY_TIER_DAYS[tier]
        overdue = today.toordinal() - due_date
        if overdue < min_overdue:
            continue
        stale.append(
            {
                "path": note.path,
                "slug": note.slug,
                "title": note.title,
                "kind": note.kind,
                "project": note.project,
                "owner": note.owner,
                "visibility": note.visibility,
                "publication_status": note.publication_status,
                "freshness_date": note.freshness_date,
                "decay_tier": tier,
                "days_overdue": overdue,
                "snoozed_until": note.snoozed_until,
                "suggested_action": _stale_note_action(overdue),
            }
        )
    return sorted(stale, key=lambda item: (-int(item["days_overdue"]), str(item["title"])))


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
    return _note_payload(note, candidates, route_prefix, viewer_owner=viewer_owner, is_admin=is_admin)


def search_closed_notes(
    query: str,
    limit: int = 12,
    route_prefix: str = "",
    include_imported: bool = False,
    include_targeted_claims: bool = False,
    kind: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    q = query.strip().lower()
    q_tokens = [token for token in re.findall(r"[\w가-힣]+", q, flags=re.UNICODE) if len(token) >= 2]
    notes = _load_notes()
    # raw import 노트는 기본적으로 검색에서 제외 (include_imported=True 시 포함)
    if not include_imported:
        notes = [n for n in notes if "imported-doc" not in n.tags]
    # publication_request 스텁은 지식이 아닌 메타데이터 — 실제 source 노트의 rationale/evidence가
    # 본문에 포함돼 있어 source보다 상위 랭크되는 부작용을 일으킨다. 검색에서 제외한다.
    notes = [n for n in notes if not n.path.startswith("personal_vault/projects/ops/librarian/publication_requests/")]
    # knowledge-gaps 초안은 메타 운영 산출물이라 사용자-facing 검색 상단을 오염시키기 쉽다.
    notes = [n for n in notes if not n.path.startswith("doc/knowledge-gaps/")]
    include_targeted = bool(include_targeted_claims)
    if not include_targeted:
        notes = [n for n in notes if not (n.kind == "claim" and n.targets)]
    # kind 필터
    if kind:
        notes = [n for n in notes if n.kind == kind]
    # tags 필터 (모든 지정 태그를 포함하는 노트만)
    if tags:
        tag_set = {t.strip().lower() for t in tags}
        notes = [n for n in notes if tag_set.issubset({t.lower() for t in n.tags})]
    matches_by_slug: dict[str, dict[str, Any]] = {}
    lexical_scores = lexical_rank(
        query,
        [
            FTSDocument(
                path=note.path,
                slug=note.slug,
                title=note.title,
                summary=note.summary,
                kind=note.kind,
                project=note.project,
                owner=note.owner,
                tags=note.tags,
                body=note.body,
            )
            for note in notes
        ],
        limit=max(limit * 5, 32),
    )
    note_by_slug = {note.slug: note for note in notes}
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
        lexical_entry = lexical_scores.get(note.slug, {})
        lexical_hit = bool(lexical_entry) or bool(q and q in haystack)
        title_hit = 4 if q and q in note.title.lower() else 0
        path_hit = 3 if q and q in note.path.lower() else 0
        tag_hit = 2 if q and any(q in tag.lower() for tag in note.tags) else 0
        token_title_hit = sum(3 for token in q_tokens if token in note.title.lower())
        token_path_hit = sum(2 for token in q_tokens if token in note.path.lower())
        token_tag_hit = sum(1 for token in q_tokens if any(token in tag.lower() for tag in note.tags))
        lexical_boost = (
            title_hit
            + path_hit
            + tag_hit
            + token_title_hit
            + token_path_hit
            + token_tag_hit
            + (haystack.count(q) if q else 0)
        )
        lexical_score = float(lexical_entry.get("score") or 0.0) + float(lexical_boost)
        if lexical_score > 0:
            lexical_scores[note.slug] = {
                "score": lexical_score,
                "bm25": float(lexical_entry.get("bm25") or 0.0),
            }
    # Common queries should stay fast: run semantic reranking over the lexical pool first.
    # Only fall back to a global semantic pass when lexical recall is too thin.
    semantic_scores: dict[str, float] = {}
    if not lexical_scores:
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
        semantic_score = semantic_scores.get(note.slug, 0.0)
        lexical_entry = lexical_scores.get(note.slug, {})
        lexical_score = float(lexical_entry.get("score") or 0.0)
        if lexical_score <= 0 and semantic_score <= 0:
            continue
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
            "lexical_score": float(lexical_score),
            "lexical_bm25": round(float(lexical_entry.get("bm25") or 0.0), 6),
            "semantic_score": round(semantic_score, 4),
            "confirm_count": note.confirm_count,
            "dispute_count": note.dispute_count,
            "claim_review_status": note.claim_review_status,
            "claim_review_badge": _claim_trust_badge(note.claim_review_status),
        }
    # Reciprocal Rank Fusion (Cormack et al. 2009) — 이질적 점수(정수 lexical vs [0,1] semantic)를
    # 선형 결합하는 대신 rank 기반으로 합쳐 scale 의존성을 제거한다. k=60은 업계 표준.
    RRF_K = 60
    lexical_ranked = sorted(
        ((slug, float(payload.get("score") or 0.0)) for slug, payload in lexical_scores.items()),
        key=lambda kv: -kv[1],
    )
    semantic_ranked = sorted(
        ((slug, score) for slug, score in semantic_scores.items() if score > 0),
        key=lambda kv: -kv[1],
    )
    rrf_scores: dict[str, float] = {}
    for rank, (slug, _) in enumerate(lexical_ranked, start=1):
        rrf_scores[slug] = rrf_scores.get(slug, 0.0) + 1.0 / (RRF_K + rank)
    for rank, (slug, _) in enumerate(semantic_ranked, start=1):
        rrf_scores[slug] = rrf_scores.get(slug, 0.0) + 1.0 / (RRF_K + rank)
    for slug, entry in matches_by_slug.items():
        confirm_count = int(entry.get("confirm_count") or 0)
        dispute_count = int(entry.get("dispute_count") or 0)
        claim_review_status = str(entry.get("claim_review_status") or "unreviewed")
        trust_multiplier = _claim_trust_multiplier(claim_review_status, confirm_count, dispute_count)
        final_score = rrf_scores.get(slug, 0.0) * trust_multiplier
        entry["trust_multiplier"] = round(trust_multiplier, 6)
        entry["score"] = round(final_score, 6)
    results = sorted(matches_by_slug.values(), key=lambda item: (-item["score"], item["title"]))[:limit]
    # 결과가 얇을 때 semantic 점수가 조금이라도 있는 이웃 노트를 hint로 제공.
    # 작은 모델이 쿼리 문구를 잘못 고를 때 재검색 실마리를 잡을 수 있도록 한다.
    hints: list[dict[str, Any]] = []
    if len(results) < 3:
        matched_slugs = {item["slug"] for item in results}
        hint_candidates = sorted(
            (
                (slug, score)
                for slug, score in semantic_scores.items()
                if slug not in matched_slugs and score > 0
            ),
            key=lambda pair: -pair[1],
        )[:5]
        for slug, score in hint_candidates:
            note = note_by_slug.get(slug)
            if not note:
                continue
            hints.append({
                "path": note.path,
                "slug": note.slug,
                "title": note.title,
                "kind": note.kind,
                "summary": note.summary,
                "href": _note_href(note.slug, route_prefix),
                "semantic_score": round(score, 4),
            })
    return {
        "query": query,
        "results": results,
        "hints": hints,
        "meta": {
            "retrieval": "sqlite_fts5+semantic+rrf",
            "rrf_k": RRF_K,
            "semantic_model": get_settings().embedding_model,
            "semantic_provider": get_settings().embedding_provider,
            "lexical_backend": "sqlite_fts5",
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
    payload = _note_payload(
        note,
        visible_notes or [note],
        route_prefix,
        viewer_owner=viewer_owner,
        is_admin=is_admin,
    )
    note_links = _explorer_html(visible_notes, note.slug, route_prefix)
    path_breadcrumb = _path_breadcrumb_html(payload["path"])
    shared_styles = _shared_ui_styles()
    shared_header = _shared_header_html(route_prefix, payload["title"], note_actions=True)
    shared_shell = _shared_ui_shell(route_prefix)
    workspace_styles = _workspace_styles()
    workspace_overlay = _workspace_overlay_html()
    workspace_script = _workspace_script()
    explorer_empty = "Your vault is empty. Create your first note to get started." if not notes else "No notes available."

    related_html = _link_list_html(payload["related_notes"], "Related Notes", route_prefix, "No related notes found.")
    backlinks_html = _link_list_html(payload["backlinks"], "Backlinks", route_prefix, "No backlinks found.")
    review_path_href_map = {visible.path: _note_href(visible.slug, route_prefix) for visible in visible_notes}
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
      position: fixed;
      top: var(--closed-header-height, 58px);
      bottom: 0;
      left: calc(var(--closed-sidebar-width) - 6px);
      z-index: 30;
      width: 12px;
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
    /* ── mini graph widget ─────────────────────── */
    .mini-graph-widget {{
      position: fixed;
      top: calc(var(--closed-header-height, 58px) + 8px);
      right: 18px;
      width: min(300px, calc(100vw - 28px));
      border-radius: 14px;
      border: 1px solid var(--line-strong);
      background: rgba(248,250,252,.97);
      backdrop-filter: blur(18px);
      box-shadow: 0 20px 40px rgba(15,23,42,.12);
      z-index: 44;
      overflow: hidden;
      display: none;
      flex-direction: column;
    }}
    .mini-graph-widget.visible {{ display: flex; }}
    .mini-graph-header {{
      display: flex; align-items: center; justify-content: space-between;
      padding: 10px 14px 8px;
      border-bottom: 1px solid var(--line);
      font-size: .8rem; font-weight: 700; color: var(--muted);
      user-select: none;
    }}
    .mini-graph-header span {{ color: var(--ink); }}
    .mini-graph-close {{
      width: 22px; height: 22px; border-radius: 6px; border: none;
      background: transparent; color: var(--muted); cursor: pointer; font-size: 14px;
      display: inline-flex; align-items: center; justify-content: center;
      transition: background .14s;
    }}
    .mini-graph-close:hover {{ background: rgba(15,23,42,.07); color: var(--ink); }}
    .mini-graph-canvas-wrap {{ position: relative; height: 240px; }}
    .mini-graph-canvas {{ display: block; width: 100%; height: 100%; cursor: default; }}
    .mini-graph-footer {{
      padding: 6px 14px;
      font-size: .75rem; color: var(--muted);
      border-top: 1px solid var(--line);
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    /* ── note header & edit controls ──────────────── */
    .note-path-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-height: 30px;
    }}
    .note-edit-trigger {{
      display: inline-flex;
      align-items: center;
      height: 28px;
      padding: 0 12px;
      border-radius: 7px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.9);
      color: var(--muted);
      font: inherit;
      font-size: .79rem;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
      flex-shrink: 0;
      transition: background .15s, border-color .15s, color .15s;
    }}
    .note-edit-trigger:hover {{
      background: rgba(37,99,235,.07);
      border-color: rgba(37,99,235,.22);
      color: var(--accent);
    }}
    .note-edit-actions {{
      display: flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;
    }}
    .note-action-btn {{
      display: inline-flex;
      align-items: center;
      height: 28px;
      padding: 0 12px;
      border-radius: 7px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.9);
      color: var(--muted);
      font: inherit;
      font-size: .79rem;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
      transition: background .15s, border-color .15s, color .15s;
    }}
    .note-action-btn:hover {{ background: var(--panel); border-color: var(--line-strong); color: var(--ink); }}
    .note-action-btn.is-ghost {{ background: transparent; border-color: transparent; }}
    .note-action-btn.is-ghost:hover {{ background: rgba(15,23,42,.05); border-color: var(--line); }}
    .note-action-btn.is-primary {{ background: rgba(37,99,235,.09); border-color: rgba(37,99,235,.22); color: var(--accent); }}
    .note-action-btn.is-primary:hover {{ background: rgba(37,99,235,.15); }}
    .note-action-btn.is-danger {{ background: transparent; border-color: transparent; color: #b91c1c; }}
    .note-action-btn.is-danger:hover {{ background: rgba(220,38,38,.07); border-color: rgba(220,38,38,.2); }}
    /* edit-view button visibility */
    body.inline-editing .note-edit-trigger {{ display: none !important; }}
    body:not(.inline-editing) .note-edit-actions {{ display: none !important; }}
    /* mini graph floating button */
    .mini-graph-fab {{
      position: fixed;
      top: calc(var(--closed-header-height, 58px) + 10px);
      right: 18px;
      z-index: 45;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.94);
      backdrop-filter: blur(10px);
      color: var(--muted);
      font-size: 16px;
      cursor: pointer;
      box-shadow: 0 4px 12px rgba(15,23,42,.08);
      transition: background .16s, border-color .16s, color .16s, box-shadow .16s;
    }}
    .mini-graph-fab:hover, .mini-graph-fab.active {{
      background: rgba(37,99,235,.09);
      border-color: rgba(37,99,235,.24);
      color: var(--accent);
      box-shadow: 0 6px 16px rgba(37,99,235,.12);
    }}
    html[data-theme="dark"] .mini-graph-fab {{
      background: rgba(19, 26, 42, .95);
      border-color: var(--line);
      color: var(--muted);
    }}
    html[data-theme="dark"] .mini-graph-fab:hover,
    html[data-theme="dark"] .mini-graph-fab.active {{
      color: var(--ink);
      border-color: var(--line-strong);
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
    .search-row {{ display: flex; gap: 6px; align-items: stretch; }}
    .search-row .search {{ flex: 1; }}
    .search-btn {{
      flex: 0 0 auto; width: 42px; border-radius: 8px; border: 1px solid var(--line);
      background: rgba(255,255,255,.96); color: var(--ink); cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      transition: background .18s ease, border-color .18s ease;
    }}
    .search-btn:hover {{ background: rgba(37, 99, 235, .08); border-color: rgba(37, 99, 235, .42); }}
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
    .folder-group + .folder-group {{ margin-top: 6px; }}
    .folder-summary {{
      list-style: none;
      display: flex;
      align-items: center;
      gap: 8px;
      padding: max(6px, calc(10px - var(--depth, 0) * 1px)) 12px;
      min-width: 0;
      cursor: pointer;
      color: var(--ink);
      font-size: max(0.78rem, calc(0.84rem - var(--depth, 0) * 0.02rem));
      font-weight: 700;
      letter-spacing: 0;
      background: rgba(255,255,255,.68);
    }}
    .folder-summary span:last-child {{ min-width: 0; overflow-wrap: anywhere; }}
    .folder-summary::-webkit-details-marker {{ display: none; }}
    .folder-caret {{
      display: inline-flex;
      flex: 0 0 11px;
      width: 11px;
      justify-content: center;
      color: var(--muted);
      transition: transform .16s ease;
    }}
    .folder-group[open] > .folder-summary .folder-caret {{ transform: rotate(90deg); }}
    .folder-children {{
      display: flex;
      flex-direction: column;
      gap: 4px;
      margin-left: 8px;
      padding: 4px 4px 6px 8px;
      border-left: 1px solid rgba(197, 211, 229, .55);
    }}
    .nav-link {{
      display: block;
      padding: max(6px, calc(10px - var(--depth, 0) * 1px)) max(8px, calc(12px - var(--depth, 0) * 1px));
      border-radius: 8px; color: var(--ink);
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
    .nav-link small {{ display:none; color: var(--muted); font-size: 0.72rem; margin-top: 4px; overflow-wrap: anywhere; line-height: 1.35; }}
    .nav-link.active small,
    body.explorer-searching .nav-link small {{ display:block; }}
    .note-shell {{ max-width: 820px; margin: 0 auto; padding-top: 32px; }}
    [hidden] {{ display: none !important; }}
    .note-top {{
      display: grid; gap: 22px; margin-bottom: 28px; padding-bottom: 24px;
      border-bottom: 1px solid var(--line);
    }}
    .note-top .note-path-row {{ margin-bottom: 4px; }}
    .note-top .title {{ margin-top: 4px; }}
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
    .edit-view {{ display: none !important; }}
    body.inline-editing .read-view {{ display: none !important; }}
    body.inline-editing .edit-view {{ display: block !important; }}
    body.inline-editing .inline-editor {{ display: grid !important; }}
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
      gap: 14px;
    }}
    .editor-title-input, .editor-body-input {{
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
    .meta-collapsible {{ margin: 0; }}
    .meta-collapsible[open] > .meta-collapsible-summary {{ margin-bottom: 12px; }}
    .meta-collapsible-summary {{
      display: flex; align-items: center; justify-content: space-between; gap: 8px;
      margin: 0; padding: 4px 0; cursor: pointer; user-select: none;
      list-style: none;
    }}
    .meta-collapsible-summary::-webkit-details-marker {{ display: none; }}
    .meta-collapsible-summary::before {{
      content: "▸"; display: inline-block; margin-right: 6px; color: var(--muted);
      font-size: 0.7rem; transition: transform .18s ease;
    }}
    .meta-collapsible[open] > .meta-collapsible-summary::before {{ transform: rotate(90deg); }}
    .meta-count {{
      display: inline-flex; align-items: center; justify-content: center; min-width: 22px; height: 20px;
      padding: 0 7px; border-radius: 999px; background: rgba(37, 99, 235, .12); color: var(--accent);
      font-size: 0.7rem; font-weight: 700; letter-spacing: 0;
    }}
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
    .reviews-section {{ margin-top: 28px; padding-top: 24px; border-top: 1px solid var(--line); }}
    .reviews-toolbar {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; margin: 18px 0 16px; }}
    .review-tabs {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .review-tab {{
      appearance: none; border: 1px solid var(--line); background: rgba(255,255,255,.86); color: var(--muted);
      border-radius: 999px; padding: 8px 12px; font: inherit; font-size: .84rem; font-weight: 700; cursor: pointer;
    }}
    .review-tab.is-active {{ color: var(--ink); border-color: rgba(37, 99, 235, .28); background: rgba(37, 99, 235, .10); }}
    .review-sort {{ display: inline-flex; align-items: center; gap: 8px; color: var(--muted); font-size: .84rem; }}
    .review-sort select {{
      border: 1px solid var(--line); border-radius: 999px; background: rgba(255,255,255,.92);
      color: var(--ink); padding: 7px 10px; font: inherit;
    }}
    .review-list {{ display: grid; gap: 12px; }}
    .review-card {{
      padding: 14px; border-radius: 12px; border: 1px solid var(--line);
      background: rgba(255,255,255,.9); box-shadow: 0 10px 24px rgba(15, 23, 42, .05);
    }}
    .review-head {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }}
    .review-meta {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; color: var(--muted); font-size: .84rem; }}
    .review-stance {{
      display: inline-flex; align-items: center; height: 26px; padding: 0 10px; border-radius: 999px;
      font-size: .78rem; font-weight: 800; letter-spacing: .02em; text-transform: uppercase; border: 1px solid transparent;
    }}
    .review-stance.is-support {{ background: rgba(22, 163, 74, .12); color: #166534; border-color: rgba(22, 163, 74, .2); }}
    .review-stance.is-dispute {{ background: rgba(220, 38, 38, .12); color: #991b1b; border-color: rgba(220, 38, 38, .2); }}
    .review-stance.is-neutral {{ background: rgba(100, 116, 139, .12); color: #475569; border-color: rgba(100, 116, 139, .2); }}
    .review-self {{
      display: inline-flex; align-items: center; height: 22px; padding: 0 8px; border-radius: 999px;
      background: rgba(148, 163, 184, .16); color: var(--muted); font-size: .74rem; font-weight: 700;
    }}
    .review-rationale {{ margin: 0; color: var(--ink); line-height: 1.7; }}
    .review-evidence {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    .review-chip {{
      display: inline-flex; align-items: center; gap: 6px; min-height: 30px; padding: 0 10px;
      border-radius: 999px; border: 1px solid var(--line); background: rgba(244, 247, 251, .95);
      color: var(--ink); font-size: .78rem; font-weight: 600;
    }}
    a.review-chip:hover {{ text-decoration: none; border-color: var(--line-strong); background: #fff; }}
    .review-empty {{ padding: 14px; border: 1px dashed var(--line-strong); border-radius: 12px; color: var(--muted); background: rgba(255,255,255,.74); }}
    .missing-link {{ color: #b91c1c; font-weight: 600; }}
    .wiki-link {{ color: var(--accent); text-decoration: none; border-bottom: 1px dashed rgba(37, 99, 235, .4); }}
    .wiki-link:hover {{ border-bottom-style: solid; border-bottom-color: var(--accent); }}
    #wiki-preview {{
      position: fixed;
      max-width: 320px;
      padding: 12px 14px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, .98);
      box-shadow: 0 18px 32px rgba(15, 23, 42, .16);
      z-index: 85;
      pointer-events: none;
      opacity: 0;
      transform: translateY(4px);
      transition: opacity .12s ease, transform .12s ease;
      font-size: .82rem;
      line-height: 1.5;
    }}
    #wiki-preview.visible {{ opacity: 1; transform: translateY(0); }}
    #wiki-preview strong {{ display: block; color: var(--ink); font-size: .92rem; margin-bottom: 4px; }}
    #wiki-preview small {{ color: var(--muted); display: block; }}
    .meta-copy {{ color: var(--muted); font-size: .92rem; line-height: 1.65; }}
    @media (max-width: 1180px) {{
      .layout {{ grid-template-columns: var(--closed-sidebar-width) minmax(0, 1fr); }}
      body.left-collapsed .layout {{ grid-template-columns: minmax(0, 1fr); }}
      body.left-collapsed .sidebar {{ display: none; }}
    }}
    @media (max-width: 820px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .sidebar-resizer {{ display: none; }}
      .sidebar {{
        position: fixed;
        top: var(--closed-header-height);
        left: 0;
        right: 0;
        bottom: 0;
        z-index: 70;
        width: 100%;
        height: calc(100svh - var(--closed-header-height));
        overflow-y: auto;
        -webkit-overflow-scrolling: touch;
        overscroll-behavior: contain;
        border: 0;
        background: rgba(248, 250, 252, .97);
        padding: 20px 20px 32px;
        transform: translateX(0);
        transition: transform .24s ease;
      }}
      body.left-collapsed .sidebar {{
        display: block;
        transform: translateX(-100vw);
        opacity: 1;
        pointer-events: auto;
        overflow-y: auto;
        padding: 20px 20px 32px;
        border-right-color: var(--line);
      }}
      .sidebar-edge-toggle {{
        top: calc(var(--closed-header-height) + 10px);
        right: 10px;
        left: auto;
        z-index: 80;
      }}
      body.left-collapsed .sidebar-edge-toggle {{
        right: auto;
        left: 10px;
      }}
      .appbar {{
        margin-left: -14px;
        margin-right: -14px;
        padding-left: 14px;
        padding-right: 14px;
        align-items: flex-start;
      }}
      .appbar-title {{ max-width: 100%; order: 3; flex-basis: 100%; }}
      .top-button, .top-tab, .meta-tab, .side-tab, .note-action-btn {{ min-height: 38px; }}
      .article-wrap {{ padding: 22px 18px; }}
    }}
    {shared_styles}
    {workspace_styles}
  </style>
</head>
<body class="closed-with-header">
  <a class="skip-link" href="#main-content">Skip to content</a>
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
      <p class="sub">A personal knowledge store — follow linked notes to build and retrieve memory.</p>
      <div class="sidebar-tabs" role="tablist" aria-label="Workspace sidebar">
        <button class="side-tab active" type="button" role="tab" aria-selected="true" aria-controls="sidebar-panel-explore" data-sidebar-tab="explore">Explore</button>
        <button class="side-tab" type="button" role="tab" aria-selected="false" aria-controls="sidebar-panel-info" data-sidebar-tab="info">Info</button>
        <button class="side-tab" type="button" role="tab" aria-selected="false" aria-controls="sidebar-panel-relations" data-sidebar-tab="relations">Relations</button>
        <button class="side-tab" type="button" role="tab" aria-selected="false" aria-controls="sidebar-panel-edit" data-sidebar-tab="edit" data-note-write-control hidden>Edit</button>
      </div>
      <section class="sidebar-panel" id="sidebar-panel-explore" role="tabpanel" aria-labelledby="sidebar-tab-explore" data-sidebar-panel="explore">
        <div class="search-wrap">
          <div class="search-row">
            <input class="search" id="note-filter" placeholder="Search by title or tag" type="text" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" data-form-type="other" />
            <button class="search-btn" id="note-filter-submit" type="button" aria-label="Search">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="5.5" cy="5.5" r="4"/><line x1="8.5" y1="8.5" x2="13" y2="13"/></svg>
            </button>
          </div>
          <div class="search-results" id="search-results"></div>
        </div>
        <div class="section-label">Explorer</div>
        <nav class="nav" id="note-nav">
          {note_links or f'<p class="meta-copy">{html.escape(explorer_empty)}</p>'}
        </nav>
      </section>
      <section class="sidebar-panel" id="sidebar-panel-info" role="tabpanel" aria-labelledby="sidebar-tab-info" data-sidebar-panel="info">
        <section class="meta-section">
          <h3 class="meta-title">Note</h3>
          <div class="meta-grid">
            <div class="metric"><div class="meta-label">Kind</div><div class="meta-value">{html.escape(payload["kind"])}</div></div>
            <div class="metric"><div class="meta-label">Project</div><div class="meta-value">{html.escape(payload["project"])}</div></div>
            <div class="metric"><div class="meta-label">Status</div><div class="meta-value">{html.escape(payload["status"])}</div></div>
            <div class="metric"><div class="meta-label">Owner</div><div class="meta-value">{html.escape(payload["owner"])}</div></div>
            <div class="metric"><div class="meta-label">Visibility</div><div class="meta-value">{html.escape(payload["visibility"])}</div></div>
            <div class="metric"><div class="meta-label">Publication</div><div class="meta-value">{html.escape(payload["publication_status"])}</div></div>
            <div class="metric"><div class="meta-label">Trust</div><div class="meta-value">{html.escape(payload["claim_review_badge"])}</div></div>
            <div class="metric"><div class="meta-label">Signals</div><div class="meta-value">{int(payload["confirm_count"])} confirm / {int(payload["dispute_count"])} dispute</div></div>
          </div>
        </section>
        <section class="meta-section">
          <h3 class="meta-title">Tags</h3>
          <div class="tag-row">{tag_html or '<span class="tag">#untagged</span>'}</div>
        </section>
      </section>
      <section class="sidebar-panel" id="sidebar-panel-relations" role="tabpanel" aria-labelledby="sidebar-tab-relations" data-sidebar-panel="relations">
        <div class="toolbar-row" style="margin-bottom:12px;">
          <button class="action-button" id="edit-relations" type="button" data-note-write-control hidden>Edit Related</button>
        </div>
        {related_html}
        {backlinks_html}
      </section>
      <section class="sidebar-panel" id="sidebar-panel-edit" role="tabpanel" aria-labelledby="sidebar-tab-edit" data-sidebar-panel="edit" data-note-write-control hidden>
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
              <input class="field-input" id="editor-related" placeholder="related note titles, comma-separated" />
            </label>
          </div>
          <div class="workspace-card" style="margin-top:12px;">
            <div class="meta-title" style="margin:0;">Kind Guide</div>
            <div class="meta-copy" id="editor-kind-summary">Select a kind to see its recommended structure and folder.</div>
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
          <p class="meta-copy">Setting Visibility to `public` on your own document keeps the source private and auto-queues a publication request.</p>
        </section>
      </section>
    </aside>
    <div class="sidebar-resizer" id="sidebar-resizer" role="separator" aria-orientation="vertical" aria-label="Resize sidebar" title="Drag to resize. Use Arrow keys when focused." tabindex="0"></div>
    <main class="content">
      <button class="mini-graph-fab" id="mini-graph-toggle" type="button" title="Local Graph" aria-label="Local Graph">⬡</button>
      <div class="mini-graph-widget" id="mini-graph-widget" role="dialog" aria-label="Local Graph">
        <div class="mini-graph-header">
          <span id="mini-graph-label">Local Graph</span>
          <button class="mini-graph-close" id="mini-graph-close" type="button" aria-label="Close">✕</button>
        </div>
        <div class="mini-graph-canvas-wrap">
          <canvas class="mini-graph-canvas" id="mini-graph-canvas"></canvas>
        </div>
        <div class="mini-graph-footer" id="mini-graph-footer">Click a node to open the note.</div>
      </div>
      <div class="note-shell">
        <header class="note-top read-view">
          <div class="note-path-row">
            <div class="path" aria-label="Note path">{path_breadcrumb}</div>
            <button class="note-edit-trigger" id="global-edit-note" type="button" data-note-write-control data-edit-view="edit" hidden>Edit</button>
          </div>
          <h2 class="title" id="read-title" data-edit-target="title">{html.escape(payload["title"])}</h2>
          <p class="summary" id="read-summary" data-edit-target="summary">{html.escape(payload["summary"] or "")}</p>
        </header>
        <header class="note-top edit-view">
          <div class="note-path-row">
            <div class="path" aria-label="Note path">{path_breadcrumb}</div>
            <div class="note-edit-actions">
              <button class="note-action-btn is-ghost" id="global-cancel-note" type="button" data-note-write-control hidden>Cancel</button>
              <button class="note-action-btn is-danger" id="global-delete-note" type="button" data-note-write-control hidden>Delete</button>
              <button class="note-action-btn is-primary" id="global-save-note" type="button" data-note-write-control data-edit-view="save" hidden>Save</button>
            </div>
          </div>
          <textarea class="editor-title-input" id="editor-title" rows="1" placeholder="Untitled"></textarea>
        </header>
        <section class="article-wrap">
          <article class="markdown read-view" id="main-content" data-edit-target="body">{payload["body_html"]}</article>
          {(
              f'''
          <section class="reviews-section read-view" aria-labelledby="reviews-heading">
            <h3 id="reviews-heading">Reviews</h3>
            <div class="meta-grid">
              <div class="metric"><div class="meta-label">Support</div><div class="meta-value">{int(payload["support_count"])}</div></div>
              <div class="metric"><div class="meta-label">Dispute</div><div class="meta-value">{int(payload["dispute_count"])}</div></div>
              <div class="metric"><div class="meta-label">Neutral</div><div class="meta-value">{int(payload["neutral_count"])}</div></div>
              <div class="metric"><div class="meta-label">Visible Reviews</div><div class="meta-value">{len(payload["reviews"])}</div></div>
            </div>
            <div class="reviews-toolbar">
              <div class="review-tabs" id="review-tabs">
                <button class="review-tab is-active" type="button" data-review-filter="all">All</button>
                <button class="review-tab" type="button" data-review-filter="support">Support</button>
                <button class="review-tab" type="button" data-review-filter="dispute">Dispute</button>
                <button class="review-tab" type="button" data-review-filter="neutral">Neutral</button>
              </div>
              <label class="review-sort">Sort
                <select id="review-sort">
                  <option value="recent">Recent</option>
                  <option value="evidence">Evidence count</option>
                </select>
              </label>
            </div>
            <div class="review-list" id="review-list"></div>
          </section>
              '''
              if payload.get("is_review_target")
              else ""
          )}
          <section class="inline-editor edit-view">
            <textarea class="editor-body-input" id="editor-body" placeholder="## Summary&#10;&#10;## Body"></textarea>
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
    const reviewPathHrefMap = {json.dumps(review_path_href_map, ensure_ascii=False)};
    if (noteMeta?.slug && noteMeta?.status !== 'empty') {{
      window.closedAkashicUI?.recordRecentNote?.(noteMeta.slug);
    }}
    const input = document.getElementById('note-filter');
    if (input) input.value = '';
    const __collapsibleKey = (key) => `closed-akashic-collapsible-${{key}}`;
    document.querySelectorAll('details[data-collapsible-key]').forEach((el) => {{
      const key = el.dataset.collapsibleKey;
      if (!key) return;
      const stored = window.localStorage.getItem(__collapsibleKey(key));
      if (stored === '0') el.open = false;
      else if (stored === '1') el.open = true;
      el.addEventListener('toggle', () => {{
        window.localStorage.setItem(__collapsibleKey(key), el.open ? '1' : '0');
      }});
    }});

    (function initReviews() {{
      const container = document.getElementById('review-list');
      const tabs = [...document.querySelectorAll('[data-review-filter]')];
      const sortSelect = document.getElementById('review-sort');
      if (!container || !Array.isArray(noteMeta?.reviews)) return;
      let filter = 'all';

      function relTime(value) {{
        if (!value) return 'unknown time';
        const ts = Date.parse(value);
        if (!Number.isFinite(ts)) return String(value);
        const diff = Math.round((Date.now() - ts) / 1000);
        const abs = Math.abs(diff);
        if (abs < 60) return 'just now';
        if (abs < 3600) return `${{Math.floor(abs / 60)}}m ago`;
        if (abs < 86400) return `${{Math.floor(abs / 3600)}}h ago`;
        return `${{Math.floor(abs / 86400)}}d ago`;
      }}

      function escapeHtml(value) {{
        return String(value ?? '').replace(/[&<>\"']/g, (ch) => ({{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', \"'\": '&#39;' }})[ch] || ch);
      }}

      function renderEvidence(review) {{
        const urls = Array.isArray(review.evidence_urls) ? review.evidence_urls : [];
        const paths = Array.isArray(review.evidence_paths) ? review.evidence_paths : [];
        const chips = [];
        for (const url of urls) {{
          chips.push(`<a class="review-chip" href="${{escapeHtml(url)}}" target="_blank" rel="noreferrer noopener">URL</a>`);
        }}
        for (const path of paths) {{
          if (path === '(restricted)') {{
            chips.push('<span class="review-chip">(restricted)</span>');
            continue;
          }}
          const assetHref = String(path).startsWith('assets/') ? `${{String('{_normalize_prefix(route_prefix)}') || ''}}/files/${{encodeURI(path)}}` : '';
          const href = String(reviewPathHrefMap[path] || assetHref || '');
          if (href) {{
            chips.push(`<a class="review-chip" href="${{escapeHtml(href)}}">${{escapeHtml(path.split('/').slice(-1)[0] || path)}}</a>`);
          }} else {{
            chips.push(`<span class="review-chip">${{escapeHtml(path)}}</span>`);
          }}
        }}
        return chips.join('');
      }}

      function render() {{
        let reviews = [...noteMeta.reviews];
        if (filter !== 'all') reviews = reviews.filter((item) => String(item.stance || '') === filter);
        const sortValue = sortSelect?.value || 'recent';
        reviews.sort((a, b) => {{
          if (sortValue === 'evidence') {{
            const aCount = (a.evidence_urls?.length || 0) + (a.evidence_paths?.length || 0);
            const bCount = (b.evidence_urls?.length || 0) + (b.evidence_paths?.length || 0);
            if (bCount !== aCount) return bCount - aCount;
          }}
          return String(b.created_at || '').localeCompare(String(a.created_at || ''));
        }});
        if (!reviews.length) {{
          container.innerHTML = '<div class="review-empty">No visible reviews in this slice.</div>';
          return;
        }}
        container.innerHTML = reviews.map((review) => {{
          const stance = String(review.stance || 'neutral');
          const reviewHref = review.slug ? `${{String('{_normalize_prefix(route_prefix)}') || ''}}/notes/${{encodeURIComponent(review.slug)}}` : '';
          const owner = review.owner || review.claim_id || review.target_title_snapshot || 'review';
          return `
            <article class="review-card">
              <div class="review-head">
                <div class="review-meta">
                  <span class="review-stance is-${{escapeHtml(stance)}}">${{escapeHtml(stance)}}</span>
                  ${{review.self_authored ? '<span class="review-self">self</span>' : ''}}
                  <strong>${{reviewHref ? `<a href="${{escapeHtml(reviewHref)}}">${{escapeHtml(owner)}}</a>` : escapeHtml(owner)}}</strong>
                  <span>${{escapeHtml(relTime(review.created_at))}}</span>
                </div>
                <span class="meta-copy">${{escapeHtml(review.claim_review_lifecycle || 'active')}}</span>
              </div>
              <p class="review-rationale">${{escapeHtml(review.rationale_excerpt || '')}}</p>
              <div class="review-evidence">${{renderEvidence(review)}}</div>
            </article>
          `;
        }}).join('');
      }}

      tabs.forEach((tab) => {{
        tab.addEventListener('click', () => {{
          filter = tab.dataset.reviewFilter || 'all';
          tabs.forEach((item) => item.classList.toggle('is-active', item === tab));
          render();
        }});
      }});
      sortSelect?.addEventListener('change', render);
      render();
    }})();

    (function initWikiPreview() {{
      const links = document.querySelectorAll('.wiki-link[data-note-slug]');
      if (!links.length) return;
      let card = null;
      let registry = null;
      let pending = null;
      let hideTimer = null;
      function ensureCard() {{
        if (card) return card;
        card = document.createElement('div');
        card.id = 'wiki-preview';
        card.setAttribute('role', 'tooltip');
        document.body.appendChild(card);
        return card;
      }}
      async function loadRegistry() {{
        if (registry) return registry;
        if (pending) return pending;
        pending = fetch('{html.escape(_graph_data_href(route_prefix))}')
          .then((r) => r.ok ? r.json() : null)
          .then((data) => {{
            registry = new Map();
            (data?.nodes || []).forEach((n) => {{
              if (n.slug) registry.set(n.slug, {{ title: n.title, summary: n.summary || n.path || '', path: n.path }});
              if (n.id && n.id !== n.slug) registry.set(n.id, {{ title: n.title, summary: n.summary || n.path || '', path: n.path }});
            }});
            return registry;
          }})
          .catch(() => {{ registry = new Map(); return registry; }});
        return pending;
      }}
      function showCard(link, data) {{
        const el = ensureCard();
        el.innerHTML = `<strong></strong><small></small>`;
        el.querySelector('strong').textContent = data.title || link.textContent;
        el.querySelector('small').textContent = (data.summary || '').slice(0, 180);
        const rect = link.getBoundingClientRect();
        const top = Math.min(window.innerHeight - 140, rect.bottom + 8);
        const left = Math.max(12, Math.min(window.innerWidth - 340, rect.left));
        el.style.top = top + 'px';
        el.style.left = left + 'px';
        el.classList.add('visible');
      }}
      function hideCard() {{ if (card) card.classList.remove('visible'); }}
      links.forEach((link) => {{
        link.addEventListener('mouseenter', async () => {{
          window.clearTimeout(hideTimer);
          const slug = link.dataset.noteSlug;
          const reg = await loadRegistry();
          const data = reg.get(slug);
          if (data) showCard(link, data);
        }});
        link.addEventListener('mouseleave', () => {{
          hideTimer = window.setTimeout(hideCard, 120);
        }});
        link.addEventListener('focus', async () => {{
          const reg = await loadRegistry();
          const data = reg.get(link.dataset.noteSlug);
          if (data) showCard(link, data);
        }});
        link.addEventListener('blur', hideCard);
      }});
    }})();
    (function initHeadingAnchors() {{
      document.querySelectorAll('.heading-anchor').forEach((anchor) => {{
        anchor.addEventListener('click', async (event) => {{
          event.preventDefault();
          const href = anchor.getAttribute('href') || '';
          const absoluteUrl = new URL(href, window.location.href).href;
          let copied = false;
          try {{
            if (navigator.clipboard?.writeText) {{
              await navigator.clipboard.writeText(absoluteUrl);
              copied = true;
            }}
          }} catch (error) {{ /* fallback below */ }}
          if (!copied) {{
            const ta = document.createElement('textarea');
            ta.value = absoluteUrl;
            ta.setAttribute('readonly', '');
            ta.style.position = 'fixed';
            ta.style.top = '-1000px';
            document.body.appendChild(ta);
            ta.select();
            try {{ copied = document.execCommand('copy'); }} catch (e) {{ /* silent */ }}
            finally {{ document.body.removeChild(ta); }}
          }}
          if (copied) window.closedAkashicUI?.notify?.('Link copied', 'success');
          window.location.hash = href.replace(/^#/, '');
        }});
      }});
    }})();
    const items = [...document.querySelectorAll('#note-nav .nav-link')];
    const folders = [...document.querySelectorAll('#note-nav .folder-group')];
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

    function setExplorerSearching(active) {{
      document.body.classList.toggle('explorer-searching', active);
    }}

    function syncExplorerSearchState() {{
      setExplorerSearching(Boolean(document.activeElement === input || input?.value?.trim()));
    }}

    function highlightExplorerLink(item, query) {{
      const titleEl = item.querySelector('span');
      const pathEl = item.querySelector('small');
      const title = item.dataset.noteTitle || titleEl?.textContent || '';
      const path = item.dataset.notePath || pathEl?.textContent || '';
      window.closedAkashicUI?.highlightText?.(titleEl, title, query);
      window.closedAkashicUI?.highlightText?.(pathEl, path, query);
    }}

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
      if (window.matchMedia('(max-width: 820px)').matches) {{
        sidebar?.setAttribute('aria-hidden', collapsed ? 'true' : 'false');
      }}
    }}

    sidebar?.addEventListener('click', (e) => {{
      const link = e.target.closest('a[href]');
      if (link && window.matchMedia('(max-width: 820px)').matches) setLeftCollapsed(true);
    }});

    function setSidebarTab(tab, options = {{}}) {{
      const next = ['explore', 'info', 'relations', 'edit'].includes(tab) ? tab : 'explore';
      sidebar?.setAttribute('data-active-panel', next);
      sideTabs.forEach((button) => {{
        const isActive = button.dataset.sidebarTab === next;
        button.classList.toggle('active', isActive);
        button.setAttribute('aria-selected', String(isActive));
      }});
      window.localStorage.setItem(sidebarTabKey, next);
      if (options.openSidebar !== false) setLeftCollapsed(false);
    }}

    {{
      const _sc = window.localStorage.getItem(leftCollapsedKey);
      const _isMobile = window.matchMedia('(max-width: 820px)').matches;
      if (_sc === '1' || (_sc === null && _isMobile)) {{
        setLeftCollapsed(true);
      }}
    }}
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
    sidebarResizer?.addEventListener('keydown', (event) => {{
      const step = event.shiftKey ? 40 : 10;
      if (event.key === 'ArrowRight') {{
        event.preventDefault();
        const current = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--closed-sidebar-width')) || 280;
        const width = applySidebarWidth(current + step);
        window.localStorage.setItem(sidebarWidthKey, String(width));
      }} else if (event.key === 'ArrowLeft') {{
        event.preventDefault();
        const current = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--closed-sidebar-width')) || 280;
        const width = applySidebarWidth(current - step);
        window.localStorage.setItem(sidebarWidthKey, String(width));
      }}
    }});
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
      setSidebarTab('edit', {{ openSidebar: !window.matchMedia('(max-width: 820px)').matches }});
      window.setTimeout(() => document.getElementById('editor-related')?.focus(), 120);
    }});
    sideTabs.forEach((button) => {{
      button.addEventListener('click', () => setSidebarTab(button.dataset.sidebarTab || 'explore', {{ openSidebar: !window.matchMedia('(max-width: 820px)').matches }}));
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

    function fetchNoteSearchResults(q) {{
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(async () => {{
        try {{
          const res = await fetch(`${{searchEndpoint}}?q=${{encodeURIComponent(q)}}&limit=6`);
          if (!res.ok) throw new Error(res.status);
          const data = await res.json();
          searchBox.innerHTML = '';
          const results = data.results || [];
          if (results.length === 0) {{
            const empty = document.createElement('div');
            empty.className = 'search-result';
            empty.textContent = `Nothing matches "${{q}}" — try a different keyword.`;
            searchBox.appendChild(empty);
          }} else {{
            for (const item of results) {{
              const a = document.createElement('a');
              a.className = 'search-result';
              const href = String(item.href || '');
              if (href.startsWith('/') || href.startsWith('https://')) a.href = href;
              const strong = document.createElement('strong');
              strong.textContent = item.title || '';
              const badge = String(item.claim_review_badge || '');
              if (badge && badge !== 'Unreviewed') {{
                const badgeEl = document.createElement('span');
                badgeEl.style.marginLeft = '8px';
                badgeEl.style.fontSize = '.76rem';
                badgeEl.style.color = '#475569';
                badgeEl.textContent = `[${{badge}}]`;
                strong.appendChild(badgeEl);
              }}
              const small = document.createElement('small');
              const signals = `${{Number(item.confirm_count || 0)}}c/${{Number(item.dispute_count || 0)}}d`;
              small.textContent = `${{item.summary || item.path || ''}}${{item.kind === 'claim' ? ` · ${{badge || 'Unreviewed'}} · ${{signals}}` : ''}}`;
              a.appendChild(strong);
              a.appendChild(small);
              searchBox.appendChild(a);
            }}
          }}
          searchBox.classList.add('visible');
        }} catch (error) {{
          searchBox.innerHTML = '';
          const errEl = document.createElement('div');
          errEl.className = 'search-result';
          errEl.textContent = window._t?.('graph.search_error') ?? 'Search unavailable';
          searchBox.appendChild(errEl);
          searchBox.classList.add('visible');
        }}
      }}, 120);
    }}

    function runNoteSearch() {{
      const q = input?.value?.trim() || '';
      const ql = q.toLowerCase();
      for (const item of items) {{
        const hit = !ql || item.dataset.title.includes(ql);
        item.style.display = hit ? '' : 'none';
        highlightExplorerLink(item, q);
      }}
      for (const folder of folders) {{
        const descendants = [...folder.querySelectorAll('.nav-link')];
        const visible = descendants.some((item) => item.style.display !== 'none');
        folder.style.display = visible ? '' : 'none';
        if (ql && visible) folder.open = true;
      }}
      if (!q) {{
        window.clearTimeout(searchTimer);
        searchBox?.classList.remove('visible');
        if (searchBox) searchBox.innerHTML = '';
        return;
      }}
      fetchNoteSearchResults(q);
    }}

    input?.addEventListener('focus', syncExplorerSearchState);
    input?.addEventListener('blur', () => window.setTimeout(syncExplorerSearchState, 0));
    input?.addEventListener('input', syncExplorerSearchState);
    input?.addEventListener('keydown', (event) => {{ if (event.key === 'Enter') runNoteSearch(); }});
    document.getElementById('note-filter-submit')?.addEventListener('click', runNoteSearch);
    syncExplorerSearchState();

    document.addEventListener('click', (event) => {{
      const submitBtn = document.getElementById('note-filter-submit');
      if (!searchBox?.contains(event.target) && event.target !== input && event.target !== submitBtn) {{
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
  <script>
    /* ── mini local graph ───────────────────────────────────── */
    (() => {{
      const GRAPH_HREF = '{html.escape(_graph_data_href(route_prefix))}';
      const currentPath = (JSON.parse(document.getElementById('closed-note-data')?.textContent || '{{}}') || {{}}).path || '';
      const toggle   = document.getElementById('mini-graph-toggle');
      const widget   = document.getElementById('mini-graph-widget');
      const closeBtn = document.getElementById('mini-graph-close');
      const canvas   = document.getElementById('mini-graph-canvas');
      const footer   = document.getElementById('mini-graph-footer');
      const label    = document.getElementById('mini-graph-label');
      if (!toggle || !widget || !canvas) return;

      const KIND_COLOR = {{
        capsule: '#2563eb', claim: '#0f766e', playbook: '#7c3aed', architecture: '#9333ea',
        experiment: '#ea580c', evidence: '#ca8a04', reference: '#475569', policy: '#db2777',
        index: '#0284c7',
      }};

      const ctx = canvas.getContext('2d');
      let nodes = [], links = [], raf = null, hoveredNode = null;
      function isDark() {{ return document.documentElement.getAttribute('data-theme') === 'dark'; }}
      const SIM_STEPS = 80;

      function kindColor(kind) {{
        return KIND_COLOR[kind] || '#64748b';
      }}

      const NOTES_BASE = '{html.escape(_notes_base(route_prefix))}';

      function buildLocal(allNodes, allLinks, centerPath) {{
        const byPath = new Map(allNodes.map((n) => [n.path, n]));
        const bySlug = new Map(allNodes.map((n) => [n.slug || n.id, n]));
        const center = byPath.get(centerPath);
        if (!center) return {{ nodes: [], links: [] }};
        const centerSlug = center.slug || center.id;
        const neighborSlugs = new Set([centerSlug]);
        allLinks.forEach((l) => {{
          const src = l.source?.slug || l.source;
          const tgt = l.target?.slug || l.target;
          if (src === centerSlug) neighborSlugs.add(tgt);
          if (tgt === centerSlug) neighborSlugs.add(src);
        }});
        const count = neighborSlugs.size;
        let i = 0;
        const cw0 = canvas.clientWidth || 300, ch0 = canvas.clientHeight || 240;
        const cx0 = cw0 / 2, cy0 = ch0 / 2;
        const r0 = Math.min(cw0, ch0) * 0.32;
        const localNodes = [...neighborSlugs].slice(0, 24).map((slug) => bySlug.get(slug)).filter(Boolean).map((n) => {{
          const isCenter = (n.slug || n.id) === centerSlug;
          const angle = isCenter ? 0 : (i++ / (count - 1)) * Math.PI * 2;
          const radius = isCenter ? 0 : r0;
          return {{
            ...n,
            x: cx0 + (isCenter ? 0 : Math.cos(angle) * radius),
            y: cy0 + (isCenter ? 0 : Math.sin(angle) * radius * 0.8),
            vx: 0, vy: 0,
            href: `${{NOTES_BASE}}/${{n.slug || n.id}}`,
          }};
        }});
        const localSlugs = new Set(localNodes.map((n) => n.slug || n.id));
        const localLinks = allLinks.filter((l) => {{
          const src = l.source?.slug || l.source;
          const tgt = l.target?.slug || l.target;
          return localSlugs.has(src) && localSlugs.has(tgt);
        }});
        return {{ nodes: localNodes, links: localLinks }};
      }}

      function stepPhysics() {{
        const cw = canvas.clientWidth || 300, ch = canvas.clientHeight || 240;
        const k = 0.012, repel = 900, center = {{ x: cw / 2, y: ch / 2 }};
        nodes.forEach((a) => {{
          nodes.forEach((b) => {{
            if (a === b) return;
            const dx = a.x - b.x, dy = a.y - b.y;
            const dist = Math.max(Math.sqrt(dx*dx+dy*dy), 1);
            const force = repel / (dist * dist);
            a.vx += dx / dist * force; a.vy += dy / dist * force;
          }});
          a.vx += (center.x - a.x) * 0.004;
          a.vy += (center.y - a.y) * 0.004;
        }});
        links.forEach((l) => {{
          const src = l.source?.slug || l.source?.id || l.source;
          const tgt = l.target?.slug || l.target?.id || l.target;
          const s = nodes.find((n) => (n.slug || n.id) === src);
          const t = nodes.find((n) => (n.slug || n.id) === tgt);
          if (!s || !t) return;
          const dx = t.x - s.x, dy = t.y - s.y;
          const dist = Math.max(Math.sqrt(dx*dx+dy*dy), 1);
          const force = (dist - 70) * k;
          const fx = dx / dist * force, fy = dy / dist * force;
          s.vx += fx; s.vy += fy; t.vx -= fx; t.vy -= fy;
        }});
        nodes.forEach((n) => {{
          n.vx *= 0.72; n.vy *= 0.72;
          n.x += n.vx; n.y += n.vy;
          n.x = Math.max(14, Math.min(cw - 14, n.x));
          n.y = Math.max(14, Math.min(ch - 14, n.y));
        }});
      }}

      function draw() {{
        const dpr = window.devicePixelRatio || 1;
        const w = canvas.clientWidth, h = canvas.clientHeight;
        if (canvas.width !== w * dpr || canvas.height !== h * dpr) {{
          canvas.width = w * dpr; canvas.height = h * dpr;
          ctx.scale(dpr, dpr);
        }}
        ctx.clearRect(0, 0, w, h);
        ctx.strokeStyle = isDark() ? 'rgba(148,163,184,.22)' : 'rgba(148,163,184,.38)';
        ctx.lineWidth = 1;
        links.forEach((l) => {{
          const src = l.source?.slug || l.source?.id || l.source;
          const tgt = l.target?.slug || l.target?.id || l.target;
          const s = nodes.find((n) => (n.slug || n.id) === src);
          const t = nodes.find((n) => (n.slug || n.id) === tgt);
          if (!s || !t) return;
          ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.lineTo(t.x, t.y); ctx.stroke();
        }});
        const dark = isDark();
        nodes.forEach((n) => {{
          const isCenter = n.path === currentPath || n.href === window.location.pathname;
          const isHovered = n === hoveredNode;
          const restricted = !!n.restricted;
          const r = isCenter ? 9 : 6;
          const color = restricted ? '#94a3b8' : kindColor(n.kind);
          ctx.beginPath(); ctx.arc(n.x, n.y, r + (isHovered ? 2 : 0), 0, Math.PI * 2);
          ctx.fillStyle = isCenter ? color : (isHovered ? color : color + '99');
          ctx.fill();
          if (restricted) {{
            ctx.strokeStyle = dark ? '#94a3b8' : '#64748b';
            ctx.setLineDash([3, 2]);
            ctx.lineWidth = 1.2;
            ctx.beginPath(); ctx.arc(n.x, n.y, r + 2, 0, Math.PI * 2); ctx.stroke();
            ctx.setLineDash([]);
          }}
          if (isCenter || isHovered) {{
            ctx.strokeStyle = color; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.arc(n.x, n.y, r + 3, 0, Math.PI * 2); ctx.stroke();
            ctx.lineWidth = 1;
          }}
          const rawTitle = (n.title || n.path || '').slice(0, 22);
          const title = restricted ? `🔒 ${{rawTitle}}` : rawTitle;
          ctx.font = `${{isCenter ? 700 : 500}} 10px Inter, sans-serif`;
          ctx.fillStyle = dark
            ? (isCenter ? '#e6eaf3' : (isHovered ? '#e6eaf3' : '#94a3b8'))
            : (isCenter ? '#0f172a' : (isHovered ? '#0f172a' : '#475569'));
          ctx.globalAlpha = isCenter || isHovered ? 1 : 0.85;
          ctx.fillText(title, n.x + r + 4, n.y + 4);
          ctx.globalAlpha = 1;
        }});
      }}

      function nodeAt(mx, my) {{
        return nodes.find((n) => {{
          const dx = n.x - mx, dy = n.y - my;
          return dx*dx + dy*dy < 144;
        }}) || null;
      }}

      function startAnimation() {{
        let step = 0;
        function tick() {{
          if (step++ < SIM_STEPS) stepPhysics();
          draw();
          if (widget.classList.contains('visible')) raf = requestAnimationFrame(tick);
        }}
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(tick);
      }}

      canvas.addEventListener('mousemove', (e) => {{
        const rect = canvas.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        hoveredNode = nodeAt((e.clientX - rect.left), (e.clientY - rect.top));
        canvas.style.cursor = hoveredNode ? 'pointer' : 'default';
        if (hoveredNode) footer.textContent = hoveredNode.title || hoveredNode.path;
        else footer.textContent = window._t?.('mini.footer') ?? 'Click a node to open the note.';
      }});

      canvas.addEventListener('mouseleave', () => {{
        hoveredNode = null;
        canvas.style.cursor = 'default';
        footer.textContent = window._t?.('mini.footer') ?? 'Click a node to open the note.';
      }});

      canvas.addEventListener('click', (e) => {{
        const rect = canvas.getBoundingClientRect();
        const n = nodeAt(e.clientX - rect.left, e.clientY - rect.top);
        if (n && n.path !== currentPath && n.href) window.location.href = n.href;
      }});

      let loaded = false;
      async function loadAndShow() {{
        if (!loaded) {{
          try {{
            const data = await fetch(GRAPH_HREF).then((r) => r.json());
            const local = buildLocal(data.nodes || [], data.links || [], currentPath);
            nodes = local.nodes;
            links = local.links;
            const cnt = nodes.length - 1;
            if (label) label.textContent = window._lang === 'ko' ? `로컬 그래프 · ${{cnt}} 연결` : `Local Graph · ${{cnt}} connections`;
            loaded = true;
          }} catch (e) {{
            footer.textContent = window._t?.('mini.load_fail') ?? 'Failed to load graph data.';
            return;
          }}
        }}
        startAnimation();
      }}

      function openWidget() {{
        widget.classList.add('visible');
        toggle.classList.add('active');
        loadAndShow();
      }}

      function closeWidget() {{
        widget.classList.remove('visible');
        toggle.classList.remove('active');
        cancelAnimationFrame(raf);
      }}

      toggle.addEventListener('click', () => {{
        widget.classList.contains('visible') ? closeWidget() : openWidget();
      }});
      closeBtn.addEventListener('click', () => {{
        closeWidget();
        try {{ window.localStorage.setItem('closed-akashic-mini-graph', '0'); }} catch (e) {{ /* ignore */ }}
      }});

      // 모바일에서는 첫 방문 시 위젯이 본문 위를 가리지 않도록 기본 접힘
      const stored = window.localStorage.getItem('closed-akashic-mini-graph');
      const shouldOpen = stored === '1';
      if (shouldOpen) openWidget();
      toggle.addEventListener('click', () => {{
        window.localStorage.setItem('closed-akashic-mini-graph', widget.classList.contains('visible') ? '1' : '0');
      }});
    }})();
    /* ─────────────────────────────────────────────────────── */
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
    #graph-skeleton {{
      position: fixed;
      inset: var(--closed-header-height) 0 0 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 18px;
      pointer-events: none;
      background: linear-gradient(180deg, rgba(248, 250, 252, .6), rgba(241, 245, 249, .4));
      z-index: 20;
      transition: opacity .28s ease;
    }}
    #graph-skeleton[hidden] {{ display: none; }}
    #graph-skeleton.fading {{ opacity: 0; }}
    .skeleton-constellation {{
      position: relative;
      width: 220px;
      height: 140px;
    }}
    .sk-dot {{
      position: absolute;
      border-radius: 999px;
      background: rgba(37, 99, 235, .28);
      box-shadow: 0 0 0 0 rgba(37, 99, 235, .22);
      animation: sk-pulse 1.6s ease-in-out infinite;
    }}
    .sk-dot-a {{ width: 16px; height: 16px; left: 16px; top: 54px; animation-delay: 0s; }}
    .sk-dot-b {{ width: 22px; height: 22px; left: 88px; top: 12px; animation-delay: .2s; }}
    .sk-dot-c {{ width: 28px; height: 28px; left: 96px; top: 72px; background: rgba(15, 118, 110, .32); animation-delay: .4s; }}
    .sk-dot-d {{ width: 14px; height: 14px; left: 168px; top: 36px; background: rgba(234, 88, 12, .30); animation-delay: .6s; }}
    .sk-dot-e {{ width: 18px; height: 18px; left: 176px; top: 96px; background: rgba(124, 58, 237, .30); animation-delay: .8s; }}
    @keyframes sk-pulse {{
      0%, 100% {{ transform: scale(1); opacity: .55; }}
      50% {{ transform: scale(1.18); opacity: 1; }}
    }}
    .skeleton-label {{
      margin: 0;
      font-size: 13px;
      color: var(--muted);
      letter-spacing: .02em;
    }}
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
    .search-row {{ display: flex; gap: 6px; align-items: stretch; }}
    .search-row .search {{ flex: 1; }}
    .search-btn {{
      flex: 0 0 auto; width: 42px; border-radius: 8px; border: 1px solid var(--line);
      background: rgba(255,255,255,.96); color: var(--ink); cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      transition: background .18s ease, border-color .18s ease;
    }}
    .search-btn:hover {{ background: rgba(37, 99, 235, .08); border-color: rgba(37, 99, 235, .42); }}
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
    .folder-group + .folder-group {{ margin-top: 6px; }}
    .folder-summary {{
      list-style: none; display: flex; align-items: center; gap: 8px;
      padding: max(6px, calc(10px - var(--depth, 0) * 1px)) 12px; min-width: 0;
      cursor: pointer; color: var(--ink);
      font-size: max(0.78rem, calc(0.84rem - var(--depth, 0) * 0.02rem));
      font-weight: 700; background: rgba(255,255,255,.68);
    }}
    .folder-summary::-webkit-details-marker {{ display: none; }}
    .folder-caret {{ display: inline-flex; flex: 0 0 11px; width: 11px; justify-content: center; color: var(--muted); transition: transform .16s ease; }}
    .folder-group[open] > .folder-summary .folder-caret {{ transform: rotate(90deg); }}
    .folder-children {{ display: flex; flex-direction: column; gap: 4px; margin-left: 8px; padding: 4px 4px 6px 8px; border-left: 1px solid rgba(197, 211, 229, .55); }}
    .nav-link {{
      display: block;
      padding: max(6px, calc(10px - var(--depth, 0) * 1px)) max(8px, calc(12px - var(--depth, 0) * 1px));
      border-radius: 8px; color: var(--ink); border: 1px solid transparent;
      transition: background .18s ease, border-color .18s ease, transform .18s ease; min-width: 0;
    }}
    .nav-link:hover {{ background: rgba(255,255,255,.75); text-decoration: none; transform: translateX(2px); }}
    .nav-link.active {{ background: rgba(37, 99, 235, .08); border-color: rgba(37, 99, 235, .2); box-shadow: inset 3px 0 0 rgba(37, 99, 235, .85); }}
    .nav-link span {{ display: block; min-width: 0; overflow-wrap: anywhere; line-height: 1.34; }}
    .nav-link small {{ display:none; color: var(--muted); font-size: 0.72rem; margin-top: 4px; overflow-wrap: anywhere; line-height: 1.35; }}
    .nav-link.active small,
    body.explorer-searching .nav-link small {{ display:block; }}
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
    @media (max-width: 720px) {{
      .shell {{ width: 100vw; }}
      body.left-collapsed .shell {{ transform: translateX(-100vw); }}
      .graph-menu {{ width: 100%; }}
      .graph-panel-tab {{ min-height: 38px; }}
      .sidebar-edge-toggle {{
        top: calc(var(--closed-header-height) + 10px);
        right: 10px;
        left: auto;
      }}
      body.left-collapsed .sidebar-edge-toggle {{
        right: auto;
        left: 10px;
      }}
    }}
    @media (max-width: 560px) {{
      .meta-grid {{ grid-template-columns: 1fr; }}
      .filter-grid {{ grid-template-columns: 1fr; }}
      .row, .actions {{ gap: 7px; }}
      .chip, .search {{ min-width: 0; max-width: 100%; }}
      .graph-menu {{ width: 100%; }}
    }}
    {shared_styles}
  </style>
</head>
<body class="closed-with-header">
  <a class="skip-link" href="#main-content">Skip to content</a>
  {shared_header}
  <canvas id="graph" role="application" aria-label="Knowledge graph canvas. Use WASD to pan, Q and E to cycle neighbors, Escape to deselect, Enter to open selected note." tabindex="0"></canvas>
  <p class="sr-only" id="graph-keyboard-hint">WASD: pan. Q/E: previous/next neighbor. Esc: deselect. Enter: open note. Click a node to inspect it.</p>
  <div id="graph-skeleton" aria-hidden="true">
    <div class="skeleton-constellation">
      <span class="sk-dot sk-dot-a"></span>
      <span class="sk-dot sk-dot-b"></span>
      <span class="sk-dot sk-dot-c"></span>
      <span class="sk-dot sk-dot-d"></span>
      <span class="sk-dot sk-dot-e"></span>
    </div>
    <p class="skeleton-label" id="graph-skeleton-label">Loading graph…</p>
  </div>
  <button class="sidebar-edge-toggle" id="toggle-left-sidebar" type="button" aria-label="Toggle Sidebar" title="Toggle Sidebar">❮</button>
  <div class="shell" id="main-content">
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
          <p class="sub">All graph connections are preserved, but only notes you can open are listed here.</p>
          <div class="search-wrap">
            <div class="search-row">
              <input class="search" id="graph-note-filter" placeholder="Search accessible notes" type="text" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" data-form-type="other" />
              <button class="search-btn" id="graph-note-filter-submit" type="button" aria-label="Search">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="5.5" cy="5.5" r="4"/><line x1="8.5" y1="8.5" x2="13" y2="13"/></svg>
              </button>
            </div>
            <div class="search-results" id="graph-search-results"></div>
          </div>
          <div class="section-label">Explorer</div>
          <nav class="nav" id="graph-note-nav">
            {note_links or '<p class="panel-copy">No accessible notes.</p>'}
          </nav>
          <div class="row">
            <a class="chip" href="{html.escape(_graph_href(route_prefix))}">Reset View</a>
            <span class="chip stats" id="stats">loading…</span>
          </div>
        </section>
        <section class="graph-tab-panel" data-graph-panel="selection">
          <h2 id="title">Select a node</h2>
          <div class="meta" id="summary">Click a node to see neighbors and metadata. WASD to pan, scroll or pinch to zoom, Q/E to step through neighbors.</div>
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
            <div class="metric"><span>Trust</span><strong id="trust">-</strong></div>
          </div>
          <div class="tags" id="tags"></div>
          <div class="actions">
            <a class="button" id="open-link" href="{html.escape(_root_href(route_prefix))}" hidden>Open Note</a>
            <button class="button ghost" id="focus-link" type="button">Focus Selection</button>
          </div>
          <div class="selection-access" id="selection-access">Select a node to check access for the current session.</div>
        </section>
        <section class="graph-tab-panel" data-graph-panel="display">
          <h2>Display</h2>
          <p>The graph preserves all connections. Use filters below to focus on a subset of nodes.</p>
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
          <div class="filter-meta" id="graph-filter-meta">Filters apply across the full graph.</div>
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
    if (noteFilterInput) noteFilterInput.value = '';
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
      pinchPointers: new Map(), // id → {{clientX, clientY}}
      pinchDist: null,
      auth: {{ authenticated: false, role: 'anonymous', nickname: '' }},
      visibleNodeIds: new Set(),
      visibleLinks: [],
      filters: {{ kind: '', owner: '', query: '', path: '', minDegree: 0, maxDegree: '', minSize: 0, maxSize: '' }},
      pointerDownX: 0,
      pointerDownY: 0,
      pointerDidMove: false,
      pointerDownOnEmpty: false,
      lastNeighborId: null,
    }};
    window.__graphState = state;
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

    function setExplorerSearching(active) {{
      document.body.classList.toggle('explorer-searching', active);
    }}

    function syncExplorerSearchState() {{
      setExplorerSearching(Boolean(document.activeElement === noteFilterInput || noteFilterInput?.value?.trim()));
    }}

    function resize() {{
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth || window.innerWidth;
      const h = canvas.clientHeight || window.innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }}

    function canvasPoint(clientX, clientY) {{
      const rect = canvas.getBoundingClientRect();
      return {{ x: clientX - rect.left, y: clientY - rect.top }};
    }}

    function clusterKey(node) {{
      return (node.path || '').split('/')[0] || 'root';
    }}

    function nodeColor(node) {{
      if (node && node.restricted) return '#94a3b8';
      if (['architecture', 'dataset'].includes(node.kind)) return '#2563eb';
      if (['policy', 'playbook', 'profile'].includes(node.kind)) return '#0f766e';
      if (['evidence', 'experiment', 'publication_request'].includes(node.kind)) return '#ea580c';
      if (['claim', 'capsule', 'roadmap'].includes(node.kind)) return '#7c3aed';
      return '#334155';
    }}

    function nodeSaturation(node) {{
      // 활동/발행 상태에 따라 채도를 조절해 "새로운/정착된" 노트를 우선 눈에 띄게 한다.
      if (!node || node.restricted) return 1;
      const pub = String(node.publication_status || '').toLowerCase();
      const status = String(node.status || '').toLowerCase();
      if (pub === 'published' && status === 'active') return 1;
      if (pub === 'reviewing' || status === 'requested') return 0.72;
      if (!pub && !status) return 0.58;
      return 0.86;
    }}

    function _hexToRgb(hex) {{
      const m = /^#?([0-9a-fA-F]{{6}})$/.exec(hex || '');
      if (!m) return null;
      const n = parseInt(m[1], 16);
      return {{ r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }};
    }}

    function desaturate(hex, factor) {{
      const rgb = _hexToRgb(hex);
      if (!rgb) return hex;
      const f = Math.max(0, Math.min(1, factor));
      if (f >= 0.999) return hex;
      // 회색(luma) 쪽으로 f만큼 섞는다.
      const luma = 0.2126 * rgb.r + 0.7152 * rgb.g + 0.0722 * rgb.b;
      const r = Math.round(rgb.r * f + luma * (1 - f));
      const g = Math.round(rgb.g * f + luma * (1 - f));
      const b = Math.round(rgb.b * f + luma * (1 - f));
      return '#' + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('');
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

    // LOD: hide low-degree nodes when zoomed out; always keep selected/hover
    function lodVisibleNodes() {{
      const z = state.zoom;
      const minDeg = z < 0.12 ? 18 : z < 0.22 ? 10 : z < 0.38 ? 5 : z < 0.6 ? 2 : 0;
      if (minDeg === 0) return visibleNodes();
      const selId = state.selected?.id;
      const hovId = state.hover?.id;
      return visibleNodes().filter(n =>
        (n.degree || 0) >= minDeg || n.id === selId || n.id === hovId
      );
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
        document.getElementById('title').textContent = window._t?.('graph.select_node') ?? 'Select a node';
        document.getElementById('summary').textContent = window._t?.('graph.intro') ?? 'Select a note to see neighbors and metadata.';
      }}
      if (filterMeta) {{
        const n = nextNodes.length, m = state.visibleLinks.length;
        filterMeta.textContent = window._t
          ? (window._lang === 'ko' ? `${{n}}개 노드와 ${{m}}개 링크가 현재 필터에 맞는다.` : `${{n}} nodes and ${{m}} links match the current filter.`)
          : `${{n}} nodes · ${{m}} links`;
      }}
      syncSelectionAccess();
    }}

    function worldFromScreen(clientX, clientY) {{
      const p = canvasPoint(clientX, clientY);
      return {{
        x: (p.x - state.offsetX) / state.zoom,
        y: (p.y - state.offsetY) / state.zoom,
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
      // 실제 화면에 렌더되는 노드(LOD/필터 적용)만 클릭 대상으로 취급
      for (const node of lodVisibleNodes()) {{
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

    function relatedToHover(node) {{
      if (!state.hover) return false;
      if (state.hover.id === node.id) return true;
      return state.adjacency.get(state.hover.id)?.has(node.id);
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

    function isDark() {{
      return document.documentElement.getAttribute('data-theme') === 'dark';
    }}

    function drawGrid() {{
      const spacing = 52 * state.zoom;
      const startX = ((state.offsetX % spacing) + spacing) % spacing;
      const startY = ((state.offsetY % spacing) + spacing) % spacing;
      ctx.save();
      ctx.strokeStyle = isDark() ? 'rgba(148, 163, 184, 0.10)' : 'rgba(148, 163, 184, 0.16)';
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

      const z = state.zoom;
      const nodes = lodVisibleNodes();
      const lookup = new Map(nodes.map(node => [node.id, node]));
      ctx.save();
      ctx.translate(state.offsetX, state.offsetY);
      ctx.scale(z, z);

      const hoverId = state.hover?.id;
      const selectedId = state.selected?.id;
      const hasFocus = Boolean(hoverId || selectedId);

      for (const edge of state.visibleLinks) {{
        const a = lookup.get(edge.source);
        const b = lookup.get(edge.target);
        if (!a || !b) continue;
        const touchesHover = hoverId && (edge.source === hoverId || edge.target === hoverId);
        const touchesSelected = selectedId && (edge.source === selectedId || edge.target === selectedId);
        let stroke, width, alpha;
        if (touchesHover) {{
          stroke = 'rgba(234,88,12,.78)'; // 주황 계열: 호버 엣지 강조
          width = 2 / z;
          alpha = 1;
        }} else if (touchesSelected) {{
          stroke = 'rgba(37,99,235,.52)';
          width = 1.5 / z;
          alpha = 1;
        }} else {{
          stroke = 'rgba(100,116,139,.18)';
          width = 1 / z;
          alpha = hasFocus ? 0.2 : 1;
        }}
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = stroke;
        ctx.lineWidth = width;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }}
      ctx.globalAlpha = 1;

      // label degree threshold based on zoom; overlap-tracked in screen space
      const labelDegMin = z < 0.5 ? Infinity : z < 0.8 ? 8 : z < 1.2 ? 4 : z < 2.0 ? 1 : 0;
      const fontSize = Math.max(10, 12 / z);
      ctx.font = `600 ${{fontSize}}px Inter, system-ui, sans-serif`;
      const labelRects = [];

      function noOverlap(lx, ly, text) {{
        const w = ctx.measureText(text).width;
        const h = fontSize;
        const r = {{ x: lx, y: ly - h, w, h: h + 2 }};
        for (const q of labelRects) {{
          if (r.x < q.x + q.w && r.x + r.w > q.x && r.y < q.y + q.h && r.y + r.h > q.y) return false;
        }}
        labelRects.push(r);
        return true;
      }}

      for (const node of nodes) {{
        const active = state.selected && state.selected.id === node.id;
        const hovered = state.hover && state.hover.id === node.id;
        const hoverNeighbor = !hovered && relatedToHover(node);
        const related = relatedToActive(node);
        const radius = nodeRadius(node) + (hovered ? 6 : active ? 5 : hoverNeighbor ? 2 : 0);
        const color = hovered ? '#ea580c' : (active ? '#0f766e' : desaturate(nodeColor(node), nodeSaturation(node)));
        // hover 시 비이웃 노드는 흐리게, 이웃/활성은 선명하게
        const isFocal = active || hovered || hoverNeighbor || related;
        ctx.beginPath();
        ctx.fillStyle = color;
        ctx.globalAlpha = hasFocus ? (isFocal ? 1 : 0.2) : 1;
        ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
        ctx.fill();

        if (hovered) {{
          // 호버 글로우: 바깥쪽 주황 반투명 링 + 내부 흰 링 (대비)
          ctx.beginPath();
          ctx.lineWidth = 4 / z;
          ctx.strokeStyle = 'rgba(234,88,12,.32)';
          ctx.arc(node.x, node.y, radius + 7, 0, Math.PI * 2);
          ctx.stroke();
          ctx.beginPath();
          ctx.lineWidth = 2 / z;
          ctx.strokeStyle = 'rgba(255,255,255,.98)';
          ctx.arc(node.x, node.y, radius + 3, 0, Math.PI * 2);
          ctx.stroke();
        }} else if (active) {{
          ctx.beginPath();
          ctx.lineWidth = 2 / z;
          ctx.strokeStyle = 'rgba(255,255,255,.92)';
          ctx.arc(node.x, node.y, radius + 3, 0, Math.PI * 2);
          ctx.stroke();
        }}

        const wantLabel = active || hovered || hoverNeighbor || related || (node.degree || 0) >= labelDegMin;
        if (wantLabel) {{
          const lx = node.x + radius + 7;
          const ly = node.y + 4;
          const title = (node.title || '').slice(0, 32);
          // force-show for active/hovered/neighbors; skip on overlap for background nodes
          const forceShow = active || hovered || hoverNeighbor;
          if (forceShow || noOverlap(lx, ly, title)) {{
            ctx.globalAlpha = forceShow ? 1 : (hasFocus ? 0.38 : 0.9);
            ctx.fillStyle = hovered ? (isDark() ? '#fed7aa' : '#7c2d12') : (isDark() ? '#e6eaf3' : '#172033');
            ctx.font = `${{active || hovered ? 700 : 600}} ${{fontSize}}px Inter, system-ui, sans-serif`;
            ctx.fillText(title, lx, ly);
          }}
        }}
      }}
      ctx.restore();
      ctx.globalAlpha = 1;
    }}

    function show(node) {{
      state.selected = node;
      setGraphTab('selection', {{ openSidebar: !window.matchMedia('(max-width: 720px)').matches }});
      const restricted = !!node.restricted;
      const mask = restricted ? '🔒' : '-';
      document.getElementById('title').textContent = node.title || '-';
      document.getElementById('summary').textContent = restricted
        ? (window._t?.('graph.restricted_summary') ?? 'Referenced by a public note. Details hidden.')
        : (node.summary || (window._t?.('graph.summary_empty') ?? 'No summary'));
      document.getElementById('kind').textContent = restricted ? (window._t?.('graph.restricted') ?? 'Restricted') : (node.kind || '-');
      document.getElementById('degree').textContent = String(node.degree ?? 0);
      document.getElementById('project').textContent = restricted ? mask : (node.project || '-');
      document.getElementById('path').textContent = restricted ? mask : (node.path || '-');
      document.getElementById('size').textContent = restricted ? mask : `${{node.size || 0}} chars`;
      document.getElementById('owner').textContent = restricted ? mask : (node.owner || '-');
      document.getElementById('status').textContent = restricted ? mask : (node.status || '-');
      document.getElementById('visibility').textContent = node.visibility || '-';
      document.getElementById('publication').textContent = restricted ? mask : (node.publication_status || '-');
      document.getElementById('trust').textContent = restricted ? mask : (node.claim_review_badge || '-');
      document.getElementById('tags').innerHTML = restricted
        ? '<span class="tag">🔒 restricted</span>'
        : ((node.tags || []).map(tag => `<span class="tag">#${{tag}}</span>`).join('') || '<span class="tag">#untagged</span>');
      openLink.href = `{html.escape(_notes_base(route_prefix))}/${{node.slug}}`;
      syncSelectionAccess();
    }}

    function deselectNode() {{
      state.selected = null;
      const tf = (id, text) => {{ const el = document.getElementById(id); if (el) el.textContent = text; }};
      tf('title', window._t?.('graph.select_node') ?? 'Select a node');
      tf('summary', window._t?.('graph.intro') ?? 'Click a node to see neighbors and metadata. WASD to pan, scroll or pinch to zoom, Q/E to step through neighbors.');
      ['kind','degree','project','path','size','owner','status','visibility','publication','trust'].forEach((id) => tf(id, '-'));
      const tags = document.getElementById('tags');
      if (tags) tags.innerHTML = '';
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
        if (access) access.textContent = window._t?.('graph.no_selection') ?? 'Select a node to check access.';
        return;
      }}
      const allowed = canOpenNode(state.selected);
      openLink.hidden = !allowed;
      if (access) {{
        const t = window._t ?? ((k) => k);
        access.textContent = allowed
          ? (state.selected.visibility === 'public' ? t('graph.public_access') : t('graph.can_access'))
          : t('graph.no_access');
      }}
    }}

    function setLeftCollapsed(collapsed) {{
      document.body.classList.toggle('left-collapsed', collapsed);
      leftToggle?.setAttribute('aria-pressed', String(collapsed));
      window.localStorage.setItem(leftCollapsedKey, collapsed ? '1' : '0');
    }}

    function setGraphTab(tab, options = {{}}) {{
      const next = ['explore', 'selection', 'display'].includes(tab) ? tab : 'explore';
      graphMenu?.setAttribute('data-active-tab', next);
      graphTabs.forEach((button) => button.classList.toggle('active', button.dataset.graphTab === next));
      window.localStorage.setItem(graphTabKey, next);
      if (options.openSidebar !== false) setLeftCollapsed(false);
    }}

    function focusSelected() {{
      if (!state.selected) return;
      state.offsetX = window.innerWidth * 0.5 - state.selected.x * state.zoom;
      state.offsetY = window.innerHeight * 0.5 - state.selected.y * state.zoom;
    }}

    function hideGraphSkeleton() {{
      const sk = document.getElementById('graph-skeleton');
      if (!sk) return;
      sk.classList.add('fading');
      setTimeout(() => {{ sk.hidden = true; }}, 320);
    }}
    function showGraphSkeletonError(message) {{
      const label = document.getElementById('graph-skeleton-label');
      if (label) label.textContent = message || 'Could not load graph.';
    }}

    async function boot() {{
      resize();
      let data;
      try {{
        const response = await fetch('{html.escape(_graph_data_href(route_prefix))}');
        if (!response.ok) throw new Error('HTTP ' + response.status);
        data = await response.json();
      }} catch (err) {{
        showGraphSkeletonError('Could not load graph. Please refresh.');
        throw err;
      }}
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
      if (!window.matchMedia('(max-width: 720px)').matches && visibleNodes()[0]) show(visibleNodes()[0]);
      hideGraphSkeleton();
      tick();
    }}

    function tick() {{
      if (state.__panFromKeys) state.__panFromKeys();
      stepPhysics();
      render();
      requestAnimationFrame(tick);
    }}

    window.addEventListener('resize', resize);
    document.getElementById('focus-link').addEventListener('click', focusSelected);
    openLink?.addEventListener('click', () => {{
      window.localStorage.setItem(leftCollapsedKey, '1');
    }});
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
    {{
      const _gc = window.localStorage.getItem(leftCollapsedKey);
      if (_gc === '1' || (_gc === null && window.matchMedia('(max-width: 720px)').matches)) {{
        setLeftCollapsed(true);
      }}
    }}
    setGraphTab(window.localStorage.getItem(graphTabKey) || 'explore', {{ openSidebar: false }});
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
    async function runGraphSearch() {{
      const q = noteFilterInput.value.trim();
      const ql = q.toLowerCase();
      window.clearTimeout(searchTimer);
      for (const item of noteItems) {{
        const hit = !ql || item.dataset.title.includes(ql);
        item.style.display = hit ? '' : 'none';
        const titleEl = item.querySelector('span');
        const title = item.dataset.title || titleEl?.textContent || '';
        window.closedAkashicUI?.highlightText?.(titleEl, title, q);
      }}
      for (const folder of noteFolders) {{
        const descendants = [...folder.querySelectorAll('.nav-link')];
        const visible = descendants.some((item) => item.style.display !== 'none');
        folder.style.display = visible ? '' : 'none';
        if (ql && visible) folder.open = true;
      }}
      if (!q) {{
        searchBox?.classList.remove('visible');
        if (searchBox) searchBox.innerHTML = '';
        return;
      }}
      try {{
        const res = await fetch(`${{graphSearchEndpoint}}?q=${{encodeURIComponent(q)}}&limit=6`);
        if (!res.ok) throw new Error(res.status);
        const data = await res.json();
        if (searchBox) {{
          searchBox.innerHTML = '';
          const items = data.results || [];
          if (items.length === 0) {{
            const empty = document.createElement('div');
            empty.className = 'search-result';
            empty.textContent = `Nothing matches "${{q}}" — try a different keyword.`;
            searchBox.appendChild(empty);
          }} else {{
            for (const item of items) {{
              const a = document.createElement('a');
              a.className = 'search-result';
              const href = String(item.href || '');
              if (href.startsWith('/') || href.startsWith('https://')) a.href = href;
              const strong = document.createElement('strong');
              strong.textContent = item.title || '';
              const badge = String(item.claim_review_badge || '');
              if (badge && badge !== 'Unreviewed') {{
                const badgeEl = document.createElement('span');
                badgeEl.style.marginLeft = '8px';
                badgeEl.style.fontSize = '.76rem';
                badgeEl.style.color = '#475569';
                badgeEl.textContent = `[${{badge}}]`;
                strong.appendChild(badgeEl);
              }}
              const small = document.createElement('small');
              const signals = `${{Number(item.confirm_count || 0)}}c/${{Number(item.dispute_count || 0)}}d`;
              small.textContent = `${{item.summary || item.path || ''}}${{item.kind === 'claim' ? ` · ${{badge || 'Unreviewed'}} · ${{signals}}` : ''}}`;
              a.appendChild(strong);
              a.appendChild(small);
              searchBox.appendChild(a);
            }}
          }}
          searchBox.classList.add('visible');
        }}
      }} catch (error) {{
        if (searchBox) {{
          searchBox.innerHTML = '';
          const errEl = document.createElement('div');
          errEl.className = 'search-result';
          errEl.textContent = window._t?.('graph.search_error') ?? 'Search unavailable';
          searchBox.appendChild(errEl);
          searchBox.classList.add('visible');
        }}
      }}
    }}

    noteFilterInput?.addEventListener('focus', syncExplorerSearchState);
    noteFilterInput?.addEventListener('blur', () => window.setTimeout(syncExplorerSearchState, 0));
    noteFilterInput?.addEventListener('input', syncExplorerSearchState);
    noteFilterInput?.addEventListener('keydown', (event) => {{ if (event.key === 'Enter') runGraphSearch(); }});
    document.getElementById('graph-note-filter-submit')?.addEventListener('click', runGraphSearch);
    syncExplorerSearchState();

    document.addEventListener('click', (event) => {{
      const submitBtn = document.getElementById('graph-note-filter-submit');
      if (!searchBox?.contains(event.target) && event.target !== noteFilterInput && event.target !== submitBtn) {{
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

    function pinchDist(pp) {{
      const pts = [...pp.values()];
      if (pts.length < 2) return null;
      const dx = pts[0].clientX - pts[1].clientX;
      const dy = pts[0].clientY - pts[1].clientY;
      return Math.hypot(dx, dy);
    }}
    function pinchMid(pp) {{
      const pts = [...pp.values()];
      return {{ x: (pts[0].clientX + pts[1].clientX) / 2, y: (pts[0].clientY + pts[1].clientY) / 2 }};
    }}

    canvas.addEventListener('pointerdown', (event) => {{
      canvas.setPointerCapture(event.pointerId);
      state.pinchPointers.set(event.pointerId, {{ clientX: event.clientX, clientY: event.clientY }});
      if (state.pinchPointers.size === 2) {{
        // start pinch — cancel any drag/pan
        state.draggingNode = null;
        state.panning = false;
        state.pinchDist = pinchDist(state.pinchPointers);
        state.activePointer = null;
        return;
      }}
      const node = pick(event.clientX, event.clientY);
      state.activePointer = event.pointerId;
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      state.pointerDownX = event.clientX;
      state.pointerDownY = event.clientY;
      state.pointerDidMove = false;
      state.pointerDownOnEmpty = !node;
      if (node) {{
        state._wasAlreadySelected = node === state.selected;
        state.draggingNode = node;
        show(node);
      }} else {{
        state.panning = true;
        canvas.classList.add('grabbing');
      }}
    }});

    // 호버 전용: pointerdown 없이 움직이는 경우에도 호버 강조 동작
    canvas.addEventListener('pointermove', (event) => {{
      if (state.pinchPointers.has(event.pointerId)) return;
      if (state.activePointer !== null) return;
      const hit = pick(event.clientX, event.clientY);
      state.hover = hit;
      canvas.style.cursor = hit ? 'pointer' : 'grab';
    }});
    canvas.addEventListener('pointerleave', () => {{
      if (state.activePointer === null) {{
        state.hover = null;
        canvas.style.cursor = '';
      }}
    }});

    window.addEventListener('pointermove', (event) => {{
      if (!state.pinchPointers.has(event.pointerId)) return;
      state.pinchPointers.set(event.pointerId, {{ clientX: event.clientX, clientY: event.clientY }});

      // pinch zoom
      if (state.pinchPointers.size === 2 && state.pinchDist !== null) {{
        const newDist = pinchDist(state.pinchPointers);
        if (newDist > 0) {{
          const ratio = newDist / state.pinchDist;
          const mid = pinchMid(state.pinchPointers);
          const worldBefore = worldFromScreen(mid.x, mid.y);
          const anchor = canvasPoint(mid.x, mid.y);
          state.zoom = Math.min(10, Math.max(0.06, state.zoom * ratio));
          state.offsetX = anchor.x - worldBefore.x * state.zoom;
          state.offsetY = anchor.y - worldBefore.y * state.zoom;
          state.pinchDist = newDist;
        }}
        return;
      }}

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
        const dx = event.clientX - state.pointerDownX;
        const dy = event.clientY - state.pointerDownY;
        if (dx * dx + dy * dy > 16) state.pointerDidMove = true;
        state.offsetX += event.clientX - state.lastX;
        state.offsetY += event.clientY - state.lastY;
        state.lastX = event.clientX;
        state.lastY = event.clientY;
        return;
      }}
      state.hover = pick(event.clientX, event.clientY);
    }});

    function endPointer(event) {{
      state.pinchPointers.delete(event.pointerId);
      if (state.pinchPointers.size < 2) state.pinchDist = null;
      if (state.activePointer === event.pointerId) {{
        if (state.pointerDownOnEmpty && !state.pointerDidMove && state.selected) {{
          deselectNode();
        }}
        if (!state.pointerDownOnEmpty && !state.pointerDidMove && state._wasAlreadySelected) {{
          if (window.matchMedia('(max-width: 720px)').matches) setLeftCollapsed(false);
        }}
        state.draggingNode = null;
        state.panning = false;
        state.activePointer = null;
        state.pointerDownOnEmpty = false;
        state.pointerDidMove = false;
        canvas.classList.remove('grabbing');
      }}
      try {{ canvas.releasePointerCapture(event.pointerId); }} catch (_) {{}}
    }}
    window.addEventListener('pointerup', endPointer);
    window.addEventListener('pointercancel', endPointer);

    canvas.addEventListener('wheel', (event) => {{
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.10 : 0.91;
      const nextZoom = Math.min(10, Math.max(0.06, state.zoom * factor));
      const worldBefore = worldFromScreen(event.clientX, event.clientY);
      const anchor = canvasPoint(event.clientX, event.clientY);
      state.zoom = nextZoom;
      state.offsetX = anchor.x - worldBefore.x * state.zoom;
      state.offsetY = anchor.y - worldBefore.y * state.zoom;
    }}, {{ passive: false }});

    canvas.addEventListener('dblclick', (event) => {{
      const node = pick(event.clientX, event.clientY);
      if (node && canOpenNode(node)) {{
        window.location.href = `{html.escape(_notes_base(route_prefix))}/${{node.slug}}`;
      }}
    }});

    // WASD 뷰포트 이동, QE 이웃 순환, Esc 선택 해제, Enter 열기
    const panKeys = new Set();
    function isTypingTarget(target) {{
      if (!target) return false;
      const tag = target.tagName;
      return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
    }}
    function cycleNeighbor(dir) {{
      if (!state.selected) {{
        const first = visibleNodes()[0];
        if (first) {{ show(first); focusSelected(); }}
        return;
      }}
      const curId = state.selected.id;
      const set = state.adjacency.get(curId);
      if (!set || set.size === 0) return;
      const neighbors = [...set]
        .map((id) => state.nodes.find((n) => n.id === id))
        .filter(Boolean)
        .sort((a, b) => (a.title || '').localeCompare(b.title || '', 'ko'));
      if (neighbors.length === 0) return;
      const lastId = state.lastNeighborId;
      let idx = lastId ? neighbors.findIndex((n) => n.id === lastId) : -1;
      if (idx < 0) idx = dir > 0 ? -1 : 0;
      idx = (idx + dir + neighbors.length) % neighbors.length;
      const next = neighbors[idx];
      state.lastNeighborId = next.id;
      show(next);
      focusSelected();
    }}
    window.addEventListener('keydown', (event) => {{
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;
      const key = event.key.toLowerCase();
      if (['w','a','s','d'].includes(key)) {{
        panKeys.add(key);
        event.preventDefault();
        return;
      }}
      if (key === 'q') {{ cycleNeighbor(-1); event.preventDefault(); return; }}
      if (key === 'e') {{ cycleNeighbor(1); event.preventDefault(); return; }}
      if (key === 'escape') {{
        if (state.selected) {{ deselectNode(); state.lastNeighborId = null; event.preventDefault(); }}
        return;
      }}
      if (key === 'enter' && state.selected && canOpenNode(state.selected)) {{
        window.location.href = `{html.escape(_notes_base(route_prefix))}/${{state.selected.slug}}`;
        event.preventDefault();
      }}
    }});
    window.addEventListener('keyup', (event) => {{
      const key = event.key?.toLowerCase?.();
      if (key) panKeys.delete(key);
    }});
    window.addEventListener('blur', () => panKeys.clear());

    function panFromKeys() {{
      if (panKeys.size === 0) return;
      const step = 18;
      if (panKeys.has('w')) state.offsetY += step;
      if (panKeys.has('s')) state.offsetY -= step;
      if (panKeys.has('a')) state.offsetX += step;
      if (panKeys.has('d')) state.offsetX -= step;
    }}
    state.__panFromKeys = panFromKeys;

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
        <p class="sidebar-copy">Manage users, roles, debug requests, and agent runtime settings.</p>
      </div>
      <nav class="admin-nav" aria-label="Admin sections">
        <button class="admin-nav-button active" type="button" data-admin-nav="overview">Overview</button>
        <button class="admin-nav-button" type="button" data-admin-nav="publication">Publication</button>
        <button class="admin-nav-button" type="button" data-admin-nav="debug">Debug</button>
        <button class="admin-nav-button" type="button" data-admin-nav="users">Users</button>
        <button class="admin-nav-button" type="button" data-admin-nav="roles">Roles</button>
        <button class="admin-nav-button" type="button" data-admin-nav="sagwan">Sagwan</button>
        <button class="admin-nav-button" type="button" data-admin-nav="improvements">Improvements</button>
      </nav>
      <p class="footer-note">Without an admin token, only the overview is visible and management features remain locked.</p>
    </aside>
    <main class="admin-content">
      <div class="admin-page">
        <header class="page-head">
          <div>
            <p class="brand-kicker">OpenAkashic</p>
            <h1>Admin Console</h1>
            <p class="lead">Manage permissions, user accounts, agent settings, and request logs for this OpenAkashic instance.</p>
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
                  <div class="status-line" id="admin-session-status">Checking admin session…</div>
                </section>
                <section class="card">
                  <h2 class="card-title">Next Checks</h2>
                  <div class="locked-copy">
                    Public notes are readable by everyone; private notes are accessible to owner/admin only.
                    User tokens work for both web login and agent API/MCP.
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
                    <div class="locked-copy" id="overview-librarian">Loading agent settings…</div>
                  </section>
                  <section class="card">
                    <h2 class="card-title">Recent Requests</h2>
                    <div class="locked-copy" id="overview-debug">Loading recent requests…</div>
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
                  <p class="status-line" id="load-status">Adjusting filters reloads automatically.</p>
                </section>
                <p class="footer-note">Request bodies and bearer tokens are not stored. Token, access_token, and api_key query parameters are redacted before logging.</p>
              </aside>
              <section class="panel">
                <div class="metrics">
                  <div class="metric"><span>Shown</span><strong id="metric-shown">0</strong></div>
                  <div class="metric"><span>MCP</span><strong id="metric-mcp">0</strong></div>
                  <div class="metric"><span>Errors</span><strong id="metric-errors">0</strong></div>
                  <div class="metric"><span>Slowest</span><strong id="metric-slowest">0ms</strong></div>
                </div>
                <div class="list" id="request-list">
                  <div class="empty">Apply an admin token to load recent requests.</div>
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
                  <p class="status-line" id="users-status">Load users to search and review them here.</p>
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
                      <tr><td colspan="5" class="locked-copy">Admin token required.</td></tr>
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
                  <p class="status-line" id="roles-status">Only admins can change roles.</p>
                </section>
              </aside>
              <section class="panel">
                <div class="list">
                  <section class="card">
                    <h2 class="card-title">Current Roles</h2>
                    <div id="roles-summary" class="locked-copy">Load users first.</div>
                  </section>
                </div>
              </section>
            </div>
          </section>

          <section class="admin-panel" id="admin-panel-sagwan" hidden>
            <div class="overview-grid">
              <aside class="side">
                <section class="card">
                  <h2 class="card-title">Sagwan LLM</h2>
                  <div class="inline-form">
                    <label class="field">
                      <span>Provider</span>
                      <input class="input" id="librarian-provider" placeholder="claude-cli | codex-style | openai-compatible" />
                    </label>
                    <label class="field">
                      <span>Model</span>
                      <input class="input" id="librarian-model" placeholder="claude-sonnet-4-6" />
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
                    <button class="button primary" id="librarian-save" type="button">Save LLM</button>
                  </div>
                  <p class="status-line" id="librarian-save-status">Applies from the next call onward.</p>
                </section>
                <section class="card">
                  <h2 class="card-title">Schedule & Batching</h2>
                  <div class="inline-form">
                    <label class="checkbox"><input id="sagwan-enabled" type="checkbox" /> <span>loops enabled</span></label>
                    <label class="checkbox"><input id="sagwan-use-llm" type="checkbox" /> <span>LLM approval (off = rule-only)</span></label>
                    <label class="field">
                      <span>Approval interval (sec)</span>
                      <input class="input" id="sagwan-interval" type="number" min="60" step="60" />
                    </label>
                    <label class="field">
                      <span>Curation interval (sec)</span>
                      <input class="input" id="sagwan-curation-interval" type="number" min="300" step="60" />
                    </label>
                    <label class="checkbox"><input id="sagwan-research-enabled" type="checkbox" /> <span>research stage enabled</span></label>
                    <label class="field">
                      <span>Research interval (sec)</span>
                      <input class="input" id="sagwan-research-interval" type="number" min="1800" step="600" />
                    </label>
                    <label class="field">
                      <span>Research max fetches</span>
                      <input class="input" id="sagwan-research-max-fetches" type="number" min="1" max="6" step="1" />
                    </label>
                    <label class="field">
                      <span>Topic proposal interval (h)</span>
                      <input class="input" id="sagwan-topic-interval-hours" type="number" min="1" max="168" step="1" />
                    </label>
                    <label class="field">
                      <span>Meta curation interval (h)</span>
                      <input class="input" id="sagwan-meta-interval-hours" type="number" min="1" max="168" step="1" />
                    </label>
                    <label class="field">
                      <span>Batch trigger (pending ≥ N → run now)</span>
                      <input class="input" id="sagwan-batch-trigger" type="number" min="1" step="1" />
                    </label>
                    <label class="field">
                      <span>Approval max per cycle</span>
                      <input class="input" id="sagwan-approval-max" type="number" min="1" step="1" />
                    </label>
                  </div>
                  <div class="actions">
                    <button class="button primary" id="sagwan-save" type="button">Save Schedule</button>
                    <button class="button" id="sagwan-run-approval" type="button">Run Approval Now</button>
                    <button class="button" id="sagwan-run-curate" type="button">Run Curation Now</button>
                    <button class="button" id="sagwan-run-research" type="button">Run Research Now</button>
                  </div>
                  <p class="status-line" id="sagwan-save-status">Heartbeat still protects the loops; saved values apply from the next tick.</p>
                </section>
              </aside>
              <section class="panel">
                <div class="list">
                  <section class="card">
                    <h2 class="card-title">Enabled Tools</h2>
                    <div class="tool-grid" id="librarian-tools-grid">
                      <div class="locked-copy">Loading tool configuration…</div>
                    </div>
                  </section>
                  <section class="card">
                    <h2 class="card-title">Runtime Status</h2>
                    <div class="locked-copy" id="librarian-runtime-status">Loading agent status…</div>
                    <div class="locked-copy" id="sagwan-runtime-status">Loading schedule…</div>
                  </section>
                  <section class="card">
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                      <h2 class="card-title">Recent Curation Cycles</h2>
                      <button class="button" id="sagwan-activity-refresh" type="button">Refresh</button>
                    </div>
                    <div id="sagwan-activity-list" class="locked-copy">Loading curation cycles…</div>
                  </section>
                  <section class="card">
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                      <h2 class="card-title">Sagwan Capsules</h2>
                      <button class="button" id="sagwan-capsules-refresh" type="button">Refresh</button>
                    </div>
                    <div id="sagwan-capsules-list" class="list" style="display:grid;gap:10px;">
                      <div class="locked-copy">Loading capsules…</div>
                    </div>
                  </section>
                  <section class="card">
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                      <h2 class="card-title">Research Log</h2>
                      <button class="button" id="sagwan-research-refresh" type="button">Refresh</button>
                    </div>
                    <div id="sagwan-research-list" class="list" style="display:grid;gap:10px;">
                      <div class="locked-copy">Loading research log…</div>
                    </div>
                  </section>
                </div>
              </section>
            </div>
          </section>

          <section class="admin-panel" id="admin-panel-publication" hidden>
            <div class="page-head" style="margin-bottom:18px;">
              <div>
                <h1 style="font-size:2rem;">Publication Queue</h1>
                <p class="lead">Publication request queue. Approving syncs automatically to Core API.</p>
                <p class="status-line" id="pub-summary">Loading queue summary…</p>
              </div>
              <div class="actions">
                <select class="input" id="pub-status-filter" style="width:160px;">
                  <option value="">All statuses</option>
                  <option value="requested" selected>Requested</option>
                  <option value="reviewing">Reviewing</option>
                  <option value="rejected">Rejected</option>
                  <option value="published">Published</option>
                  <option value="needs_merge">Needs Merge</option>
                  <option value="needs_evidence">Needs Evidence</option>
                  <option value="superseded">Superseded</option>
                </select>
                <button class="button" id="pub-refresh" type="button">Refresh</button>
              </div>
            </div>
            <div id="pub-list" class="list" style="display:grid;gap:10px;">
              <p class="locked-copy">Loading after login…</p>
            </div>
            <div class="modal-shell" id="pub-modal" hidden>
              <div class="modal-backdrop" id="pub-modal-close"></div>
              <section class="modal" role="dialog" aria-modal="true">
                <header class="modal-head">
                  <div>
                    <p class="brand-kicker">Publication Request</p>
                    <h2 class="modal-title" id="pub-modal-title">-</h2>
                    <p class="status-line" id="pub-modal-path">-</p>
                  </div>
                  <button class="icon-button" id="pub-modal-x" type="button" aria-label="Close">×</button>
                </header>
                <div class="modal-body">
                  <div id="pub-modal-meta" style="margin-bottom:14px;font-size:.88rem;color:var(--muted);"></div>
                  <label class="field" style="margin-bottom:10px;">
                    <span>Reason (optional)</span>
                    <input class="input" id="pub-modal-reason" placeholder="Approve or rejection reason…" />
                  </label>
                  <div class="actions">
                    <button class="button primary" id="pub-approve" type="button">Approve</button>
                    <button class="button" id="pub-reject" type="button" style="color:var(--error);border-color:rgba(185,28,28,.22);">Reject</button>
                  </div>
                  <p class="status-line" id="pub-modal-status"></p>
                </div>
              </section>
            </div>
          </section>

          <section class="admin-panel" id="admin-panel-improvements" hidden>
            <div class="page-head" style="margin-bottom:18px;">
              <div>
                <h1 style="font-size:2rem;">Improvement Requests</h1>
                <p class="lead">Sagwan-generated self-improvement proposals (meta-curation output). Review before applying — Sagwan does not edit code directly.</p>
              </div>
              <div class="actions">
                <select class="input" id="imp-status-filter" style="width:160px;">
                  <option value="">All statuses</option>
                  <option value="proposed" selected>Proposed</option>
                  <option value="accepted">Accepted</option>
                  <option value="rejected">Rejected</option>
                  <option value="applied">Applied</option>
                </select>
                <button class="button" id="imp-refresh" type="button">Refresh</button>
              </div>
            </div>
            <div id="imp-list" class="list" style="display:grid;gap:10px;">
              <p class="locked-copy">Loading after login…</p>
            </div>
            <div class="modal-shell" id="imp-modal" hidden>
              <div class="modal-backdrop" id="imp-modal-close"></div>
              <section class="modal" role="dialog" aria-modal="true">
                <header class="modal-head">
                  <div>
                    <p class="brand-kicker">Improvement Request</p>
                    <h2 class="modal-title" id="imp-modal-title">-</h2>
                    <p class="status-line" id="imp-modal-path">-</p>
                  </div>
                  <button class="icon-button" id="imp-modal-x" type="button" aria-label="Close">×</button>
                </header>
                <div class="modal-body">
                  <div id="imp-modal-meta" style="margin-bottom:14px;font-size:.88rem;color:var(--muted);"></div>
                  <pre id="imp-modal-body" style="white-space:pre-wrap;font-size:.86rem;line-height:1.55;background:rgba(0,0,0,.03);padding:12px;border-radius:8px;max-height:50vh;overflow:auto;"></pre>
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
          <p class="status-line" id="request-modal-subtitle">Request and response details.</p>
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
        sagwanTimer: null,
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
          publication: document.getElementById('admin-panel-publication'),
          debug: document.getElementById('admin-panel-debug'),
          users: document.getElementById('admin-panel-users'),
          roles: document.getElementById('admin-panel-roles'),
          sagwan: document.getElementById('admin-panel-sagwan'),
          improvements: document.getElementById('admin-panel-improvements'),
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
        sagwanEnabled: document.getElementById('sagwan-enabled'),
        sagwanUseLlm: document.getElementById('sagwan-use-llm'),
        sagwanInterval: document.getElementById('sagwan-interval'),
        sagwanCurationInterval: document.getElementById('sagwan-curation-interval'),
        sagwanResearchEnabled: document.getElementById('sagwan-research-enabled'),
        sagwanResearchInterval: document.getElementById('sagwan-research-interval'),
        sagwanResearchMaxFetches: document.getElementById('sagwan-research-max-fetches'),
        sagwanTopicIntervalHours: document.getElementById('sagwan-topic-interval-hours'),
        sagwanMetaIntervalHours: document.getElementById('sagwan-meta-interval-hours'),
        sagwanBatchTrigger: document.getElementById('sagwan-batch-trigger'),
        sagwanApprovalMax: document.getElementById('sagwan-approval-max'),
        sagwanSave: document.getElementById('sagwan-save'),
        sagwanRunApproval: document.getElementById('sagwan-run-approval'),
        sagwanRunCurate: document.getElementById('sagwan-run-curate'),
        sagwanRunResearch: document.getElementById('sagwan-run-research'),
        sagwanSaveStatus: document.getElementById('sagwan-save-status'),
        sagwanRuntimeStatus: document.getElementById('sagwan-runtime-status'),
        sagwanActivityRefresh: document.getElementById('sagwan-activity-refresh'),
        sagwanActivityList: document.getElementById('sagwan-activity-list'),
        sagwanCapsulesRefresh: document.getElementById('sagwan-capsules-refresh'),
        sagwanCapsulesList: document.getElementById('sagwan-capsules-list'),
        sagwanResearchRefresh: document.getElementById('sagwan-research-refresh'),
        sagwanResearchList: document.getElementById('sagwan-research-list'),
        impStatusFilter: document.getElementById('imp-status-filter'),
        impRefresh: document.getElementById('imp-refresh'),
        impList: document.getElementById('imp-list'),
        impModal: document.getElementById('imp-modal'),
        impModalTitle: document.getElementById('imp-modal-title'),
        impModalPath: document.getElementById('imp-modal-path'),
        impModalMeta: document.getElementById('imp-modal-meta'),
        impModalBody: document.getElementById('imp-modal-body'),
        impModalClose: document.getElementById('imp-modal-close'),
        impModalX: document.getElementById('imp-modal-x'),
        pubStatusFilter: document.getElementById('pub-status-filter'),
        pubSummary: document.getElementById('pub-summary'),
        pubRefresh: document.getElementById('pub-refresh'),
        pubList: document.getElementById('pub-list'),
        pubModal: document.getElementById('pub-modal'),
        pubModalTitle: document.getElementById('pub-modal-title'),
        pubModalPath: document.getElementById('pub-modal-path'),
        pubModalMeta: document.getElementById('pub-modal-meta'),
        pubModalReason: document.getElementById('pub-modal-reason'),
        pubModalClose: document.getElementById('pub-modal-close'),
        pubModalX: document.getElementById('pub-modal-x'),
        pubApprove: document.getElementById('pub-approve'),
        pubReject: document.getElementById('pub-reject'),
        pubModalStatus: document.getElementById('pub-modal-status'),
      };
      let pubCurrentPath = null;

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

      function shortExternalLabel(url) {
        try {
          return new URL(String(url || '')).hostname || String(url || '');
        } catch (error) {
          return String(url || '');
        }
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
        state.panel = ['overview', 'publication', 'debug', 'users', 'roles', 'sagwan', 'improvements'].includes(next) ? next : 'overview';
        dom.navButtons.forEach((button) => {
          button.classList.toggle('active', button.dataset.adminNav === state.panel);
        });
        Object.entries(dom.panels).forEach(([key, panel]) => {
          if (!panel) return;
          panel.hidden = key !== state.panel;
        });
        if (state.panel === 'publication') loadPublicationRequests();
        if (state.panel === 'sagwan') {
          refreshSagwanSchedule();
          refreshSagwanActivityPanels();
          startSagwanAutoRefresh();
        } else {
          stopSagwanAutoRefresh();
        }
        if (state.panel === 'improvements') loadImprovementRequests();
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
          dom.list.innerHTML = '<div class="empty">' + (window._t?.('admin.debug_empty') ?? 'No matching requests.') + '</div>';
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
          setAuthText(window._t?.('admin.debug_locked') ?? 'Log in as admin to view debug requests.', 'warn');
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
          setAuthText(`Access failed: ${error.message}`, 'error');
          setLoadText('Check token or server log status.');
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
          dom.usersTableBody.innerHTML = `<tr><td colspan="5" class="locked-copy">${window._t?.('admin.no_users') ?? 'No users to show.'}</td></tr>`;
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
          dom.rolesSummary.textContent = `Total ${state.users.length} | admin ${adminCount} | manager ${managerCount} | user ${Math.max(0, state.users.length - adminCount - managerCount)}`;
        }
        if (dom.overviewUsers) dom.overviewUsers.textContent = String(state.users.length);
        if (dom.overviewAdmins) dom.overviewAdmins.textContent = String(adminCount);
        if (dom.overviewManagers) dom.overviewManagers.textContent = String(managerCount);
      }

      async function refreshUsers() {
        if (!isAdminSession()) {
          dom.usersStatus.textContent = window._t?.('admin.users_locked') ?? 'Log in as admin to view users.';
          dom.usersTableBody.innerHTML = `<tr><td colspan="5" class="locked-copy">${window._t?.('admin.users_need_admin') ?? 'Admin token required.'}</td></tr>`;
          return;
        }
        try {
          const data = await fetchJson('/api/admin/users');
          state.users = data.users || [];
          dom.usersStatus.textContent = `${state.users.length} user(s) loaded.`;
          renderUsers();
          syncRoleControls();
        } catch (error) {
          dom.usersStatus.textContent = error.message;
          dom.usersTableBody.innerHTML = `<tr><td colspan="5" class="locked-copy">${window._t?.('admin.users_failed') ?? 'Failed to load users.'}</td></tr>`;
        }
      }

      async function saveRole() {
        if (!isAdminSession()) {
          dom.rolesStatus.textContent = window._t?.('admin.roles_locked') ?? 'Log in as admin to change roles.';
          return;
        }
        try {
          const username = dom.roleUser?.value || '';
          const role = dom.roleValue?.value || 'user';
          if (!username) throw new Error(window._t?.('admin.select_user_first') ?? 'Select a user first.');
          await fetchJson('/api/admin/users/role', {
            method: 'POST',
            json: { username, role },
          });
          dom.rolesStatus.textContent = `Saved role ${role} for ${username}.`;
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
          if (dom.librarianRuntimeStatus) dom.librarianRuntimeStatus.textContent = window._t?.('admin.librarian_runtime_locked') ?? 'Log in as admin to view agent settings.';
          if (dom.overviewLibrarian) dom.overviewLibrarian.textContent = window._t?.('admin.librarian_locked') ?? 'Activate admin session to view agent runtime.';
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
          dom.librarianSaveStatus.textContent = window._t?.('admin.librarian_saving_locked') ?? 'Log in as admin to save agent settings.';
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
          dom.librarianSaveStatus.textContent = window._t?.('admin.librarian_saved') ?? 'Agent settings saved.';
          renderLibrarian(data.settings || {}, data.status || {});
        } catch (error) {
          dom.librarianSaveStatus.textContent = error.message;
        }
      }

      function renderSagwanSchedule(settings) {
        state.sagwan = { settings };
        if (dom.sagwanEnabled) dom.sagwanEnabled.checked = Boolean(settings.enabled);
        if (dom.sagwanUseLlm) dom.sagwanUseLlm.checked = Boolean(settings.use_llm);
        if (dom.sagwanInterval) dom.sagwanInterval.value = settings.interval_sec || 600;
        if (dom.sagwanCurationInterval) dom.sagwanCurationInterval.value = settings.curation_interval_sec || 1800;
        if (dom.sagwanResearchEnabled) dom.sagwanResearchEnabled.checked = Boolean(settings.research_enabled);
        if (dom.sagwanResearchInterval) dom.sagwanResearchInterval.value = settings.research_interval_sec || 7200;
        if (dom.sagwanResearchMaxFetches) dom.sagwanResearchMaxFetches.value = settings.research_max_fetches || 3;
        if (dom.sagwanTopicIntervalHours) dom.sagwanTopicIntervalHours.value = settings.topic_min_interval_hours || 12;
        if (dom.sagwanMetaIntervalHours) dom.sagwanMetaIntervalHours.value = settings.meta_min_interval_hours || 12;
        if (dom.sagwanBatchTrigger) dom.sagwanBatchTrigger.value = settings.batch_trigger || 3;
        if (dom.sagwanApprovalMax) dom.sagwanApprovalMax.value = settings.approval_max_per_cycle || 10;
        if (dom.sagwanRuntimeStatus) {
          dom.sagwanRuntimeStatus.textContent = `approval=${settings.interval_sec ?? '-'}s · curation=${settings.curation_interval_sec ?? '-'}s · research=${settings.research_interval_sec ?? '-'}s (enabled=${Boolean(settings.research_enabled)}, fetches≤${settings.research_max_fetches ?? '-'}) · topic_interval=${settings.topic_min_interval_hours ?? '-'}h · meta_interval=${settings.meta_min_interval_hours ?? '-'}h · batch_trigger=${settings.batch_trigger ?? '-'} · approval_max_per_cycle=${settings.approval_max_per_cycle ?? '-'} · enabled=${Boolean(settings.enabled)} · use_llm=${Boolean(settings.use_llm)}`;
        }
      }

      async function refreshSagwanSchedule() {
        if (!isAdminSession()) {
          if (dom.sagwanRuntimeStatus) dom.sagwanRuntimeStatus.textContent = 'Log in as admin to view Sagwan schedule.';
          return;
        }
        try {
          const data = await fetchJson('/api/admin/sagwan/settings');
          renderSagwanSchedule(data || {});
        } catch (error) {
          if (dom.sagwanRuntimeStatus) dom.sagwanRuntimeStatus.textContent = error.message;
        }
      }

      async function saveSagwanSchedule() {
        if (!isAdminSession()) {
          if (dom.sagwanSaveStatus) dom.sagwanSaveStatus.textContent = 'Log in as admin to save Sagwan schedule.';
          return;
        }
        try {
          const data = await fetchJson('/api/admin/sagwan/settings', {
            method: 'PUT',
            json: {
              enabled: Boolean(dom.sagwanEnabled?.checked),
              use_llm: Boolean(dom.sagwanUseLlm?.checked),
              interval_sec: Number(dom.sagwanInterval?.value || 600),
              curation_interval_sec: Number(dom.sagwanCurationInterval?.value || 1800),
              research_enabled: Boolean(dom.sagwanResearchEnabled?.checked),
              research_interval_sec: Number(dom.sagwanResearchInterval?.value || 7200),
              research_max_fetches: Number(dom.sagwanResearchMaxFetches?.value || 3),
              topic_min_interval_hours: Number(dom.sagwanTopicIntervalHours?.value || 12),
              meta_min_interval_hours: Number(dom.sagwanMetaIntervalHours?.value || 12),
              batch_trigger: Number(dom.sagwanBatchTrigger?.value || 3),
              approval_max_per_cycle: Number(dom.sagwanApprovalMax?.value || 10),
            },
          });
          if (dom.sagwanSaveStatus) dom.sagwanSaveStatus.textContent = 'Schedule saved. Applies from next tick.';
          renderSagwanSchedule(data || {});
        } catch (error) {
          if (dom.sagwanSaveStatus) dom.sagwanSaveStatus.textContent = error.message;
        }
      }

      async function runSagwanApproval() {
        if (!isAdminSession()) return;
        if (dom.sagwanSaveStatus) dom.sagwanSaveStatus.textContent = 'Running approval…';
        try {
          const data = await fetchJson('/api/admin/sagwan/run', { method: 'POST' });
          const processed = (data.processed || []).length;
          const deferred = data.deferred_for_next_cycle ?? 0;
          if (dom.sagwanSaveStatus) dom.sagwanSaveStatus.textContent = `Approval done: processed=${processed}, deferred=${deferred}.`;
        } catch (error) {
          if (dom.sagwanSaveStatus) dom.sagwanSaveStatus.textContent = error.message;
        }
      }

      async function runSagwanCurate() {
        if (!isAdminSession()) return;
        if (dom.sagwanSaveStatus) dom.sagwanSaveStatus.textContent = 'Running curation (may take a minute)…';
        try {
          const data = await fetchJson('/api/admin/sagwan/curate', { method: 'POST' });
          const topic = data.topic_proposals?.status || '-';
          const meta = data.meta_curation?.status || '-';
          const research = data.research_gaps?.status || '-';
          if (dom.sagwanSaveStatus) dom.sagwanSaveStatus.textContent = `Curation done: topic_proposals=${topic}, meta_curation=${meta}, research=${research}.`;
          refreshSagwanActivityPanels();
        } catch (error) {
          if (dom.sagwanSaveStatus) dom.sagwanSaveStatus.textContent = error.message;
        }
      }

      async function runSagwanResearch() {
        if (!isAdminSession()) return;
        if (dom.sagwanSaveStatus) dom.sagwanSaveStatus.textContent = 'Running research…';
        try {
          const data = await fetchJson('/api/admin/sagwan/research/run', { method: 'POST' });
          if (dom.sagwanSaveStatus) dom.sagwanSaveStatus.textContent = `Research ${data.status || 'done'} (${data.capsule_path || '-'})`;
          await loadSagwanResearch();
          await loadSagwanCapsules();
        } catch (error) {
          if (dom.sagwanSaveStatus) dom.sagwanSaveStatus.textContent = `Research run failed: ${error.message}`;
        }
      }

      function startSagwanAutoRefresh() {
        stopSagwanAutoRefresh();
        state.sagwanTimer = window.setInterval(() => {
          if (state.panel === 'sagwan') refreshSagwanActivityPanels();
        }, 60000);
      }

      function stopSagwanAutoRefresh() {
        if (state.sagwanTimer) {
          window.clearInterval(state.sagwanTimer);
          state.sagwanTimer = null;
        }
      }

      function renderSagwanActivity(events) {
        if (!dom.sagwanActivityList) return;
        if (!events.length) {
          dom.sagwanActivityList.innerHTML = '<div class="locked-copy">No curation cycle events yet.</div>';
          return;
        }
        dom.sagwanActivityList.innerHTML = `
          <div style="display:grid;gap:8px;">
            ${events.map((event) => `
              <div style="display:grid;grid-template-columns:160px 220px 1fr;gap:10px;font-size:.84rem;">
                <div>${escapeHtml(fmtTime(event.ts))}</div>
                <div style="font-weight:700;">${escapeHtml(event.subject || 'curation cycle')}</div>
                <div style="color:var(--muted);">${escapeHtml(event.outcome || '-')}</div>
              </div>
            `).join('')}
          </div>
        `;
      }

      async function loadSagwanActivity() {
        if (!dom.sagwanActivityList) return;
        if (!isAdminSession()) {
          dom.sagwanActivityList.innerHTML = '<div class="locked-copy">Log in as admin to view curation cycles.</div>';
          return;
        }
        try {
          const data = await fetchJson('/api/admin/sagwan/activity?limit=20');
          renderSagwanActivity(data.events || []);
        } catch (error) {
          dom.sagwanActivityList.innerHTML = `<div class="locked-copy">${escapeHtml(error.message)}</div>`;
        }
      }

      function renderSagwanCapsules(capsules) {
        if (!dom.sagwanCapsulesList) return;
        if (!capsules.length) {
          dom.sagwanCapsulesList.innerHTML = '<div class="locked-copy">No Sagwan capsules yet.</div>';
          return;
        }
        dom.sagwanCapsulesList.innerHTML = capsules.map((item) => {
          const title = escapeHtml(item.title || item.path);
          const href = item.href ? escapeHtml(item.href) : '';
          const titleHtml = href ? `<a href="${href}" style="font-weight:700;color:var(--text);text-decoration:none;">${title}</a>` : `<span style="font-weight:700;">${title}</span>`;
          const urls = Array.isArray(item.research_cited_urls) ? item.research_cited_urls : [];
          return `
            <div class="card" style="padding:14px 16px;display:grid;gap:6px;">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
                ${titleHtml}
                <span class="badge">${escapeHtml(item.publication_status || 'none')}</span>
              </div>
              <div style="font-size:.78rem;color:var(--muted);">${escapeHtml(item.generated_by || '-')} · ${escapeHtml((item.updated_at || item.created_at || '').slice(0, 16).replace('T', ' '))} UTC${item.research_gap_topic ? ` · topic=${escapeHtml(item.research_gap_topic)}` : ''}</div>
              <div style="font-size:.84rem;color:var(--muted);">${escapeHtml(item.body_excerpt || '(empty)')}</div>
              ${urls.length ? `<div style="display:flex;flex-wrap:wrap;gap:6px;">${urls.slice(0, 4).map((url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer" class="badge">${escapeHtml(shortExternalLabel(url))}</a>`).join('')}</div>` : ''}
            </div>
          `;
        }).join('');
      }

      async function loadSagwanCapsules() {
        if (!dom.sagwanCapsulesList) return;
        if (!isAdminSession()) {
          dom.sagwanCapsulesList.innerHTML = '<div class="locked-copy">Log in as admin to view Sagwan capsules.</div>';
          return;
        }
        try {
          const data = await fetchJson('/api/admin/sagwan/capsules?limit=30');
          renderSagwanCapsules(data.capsules || []);
        } catch (error) {
          dom.sagwanCapsulesList.innerHTML = `<div class="locked-copy">${escapeHtml(error.message)}</div>`;
        }
      }

      function renderSagwanResearch(entries) {
        if (!dom.sagwanResearchList) return;
        if (!entries.length) {
          dom.sagwanResearchList.innerHTML = '<div class="locked-copy">No research cycles yet.</div>';
          return;
        }
        dom.sagwanResearchList.innerHTML = entries.map((entry) => {
          const queries = Array.isArray(entry.queries) ? entry.queries : [];
          const cited = Array.isArray(entry.cited_urls) ? entry.cited_urls : [];
          const capsuleLink = entry.capsule_path
            ? `<div style="font-size:.8rem;color:var(--muted);">capsule: ${entry.capsule_href ? `<a href="${escapeHtml(entry.capsule_href)}">${escapeHtml(entry.capsule_path)}</a>` : escapeHtml(entry.capsule_path)}</div>`
            : '';
          return `
            <div class="card" style="padding:14px 16px;display:grid;gap:8px;">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                <span style="font-weight:700;">${escapeHtml(entry.topic || '(untitled topic)')}</span>
                <span style="font-size:.78rem;color:var(--muted);">${escapeHtml(fmtTime(entry.ts))}</span>
              </div>
              <div style="display:flex;flex-wrap:wrap;gap:6px;">${queries.map((query) => `<span class="badge">${escapeHtml(query)}</span>`).join('')}</div>
              <div style="font-size:.84rem;color:var(--muted);">${escapeHtml(entry.rationale || '-')}</div>
              <div style="display:flex;flex-wrap:wrap;gap:6px;">${cited.map((url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer" class="badge">${escapeHtml(shortExternalLabel(url))}</a>`).join('')}</div>
              ${capsuleLink}
              <div style="font-size:.78rem;color:var(--muted);">model=${escapeHtml(entry.model || '-')}</div>
            </div>
          `;
        }).join('');
      }

      async function loadSagwanResearch() {
        if (!dom.sagwanResearchList) return;
        if (!isAdminSession()) {
          dom.sagwanResearchList.innerHTML = '<div class="locked-copy">Log in as admin to view research history.</div>';
          return;
        }
        try {
          const data = await fetchJson('/api/admin/sagwan/research?limit=20');
          renderSagwanResearch(data.entries || []);
        } catch (error) {
          dom.sagwanResearchList.innerHTML = `<div class="locked-copy">${escapeHtml(error.message)}</div>`;
        }
      }

      async function refreshSagwanActivityPanels() {
        await Promise.all([loadSagwanActivity(), loadSagwanCapsules(), loadSagwanResearch()]);
      }

      // ── improvement requests ────────────────────
      async function loadImprovementRequests() {
        if (!dom.impList) return;
        if (!isAdminSession()) {
          dom.impList.innerHTML = `<p class="locked-copy">Log in as admin to view improvement requests.</p>`;
          return;
        }
        const status = dom.impStatusFilter?.value || '';
        try {
          const data = await fetchJson(`/api/admin/sagwan/improvements${status ? `?status=${encodeURIComponent(status)}` : ''}`);
          renderImprovementList(data.items || []);
        } catch (error) {
          dom.impList.innerHTML = `<p class="locked-copy">${escapeHtml(error.message)}</p>`;
        }
      }

      function renderImprovementList(items) {
        if (!dom.impList) return;
        if (!items.length) { dom.impList.innerHTML = `<p class="locked-copy">No improvement requests.</p>`; return; }
        const prioColor = { high: '#b91c1c', medium: '#c2410c', low: '#15803d' };
        dom.impList.innerHTML = items.map((it) => `
          <div class="card imp-row" data-imp-path="${escapeHtml(it.path)}" style="padding:14px 16px;cursor:pointer;display:grid;gap:4px;">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
              <span style="font-weight:700;font-size:.92rem;">${escapeHtml(it.title || it.slug || it.path)}</span>
              <span style="font-size:.74rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:${prioColor[it.priority] || 'var(--muted)'};flex-shrink:0;">${escapeHtml(it.priority || '-')} · ${escapeHtml(it.kind || '-')}</span>
            </div>
            <div style="font-size:.78rem;color:var(--muted);">${escapeHtml(it.status || 'proposed')} · ${escapeHtml((it.created_at || '').slice(0, 16).replace('T', ' '))} UTC · review=${escapeHtml(it.review_status || 'pending_human_review')}</div>
            ${it.summary ? `<div style="font-size:.82rem;color:var(--muted);">${escapeHtml(it.summary)}</div>` : ''}
          </div>`).join('');
        dom.impList.querySelectorAll('.imp-row').forEach((row) => {
          row.addEventListener('click', () => openImpModal(row.dataset.impPath));
        });
      }

      async function openImpModal(path) {
        if (!dom.impModal) return;
        if (dom.impModalTitle) dom.impModalTitle.textContent = path.split('/').pop() || path;
        if (dom.impModalPath) dom.impModalPath.textContent = path;
        if (dom.impModalMeta) dom.impModalMeta.textContent = 'Loading…';
        if (dom.impModalBody) dom.impModalBody.textContent = '';
        dom.impModal.hidden = false;
        try {
          const data = await fetchJson(`/api/admin/sagwan/improvements/detail?path=${encodeURIComponent(path)}`);
          const fm = data.frontmatter || {};
          const metaLines = [
            `kind: ${fm.kind || '-'}`,
            `status: ${fm.status || '-'}`,
            `priority: ${fm.priority || '-'}`,
            `review_status: ${fm.review_status || 'pending_human_review'}`,
            `created_at: ${fm.created_at || '-'}`,
            `owner: ${fm.owner || '-'}`,
          ];
          if (dom.impModalMeta) dom.impModalMeta.textContent = metaLines.join(' · ');
          if (dom.impModalBody) dom.impModalBody.textContent = data.body || '(empty)';
        } catch (error) {
          if (dom.impModalMeta) dom.impModalMeta.textContent = error.message;
        }
      }

      async function refreshAll() {
        const session = currentSession();
        dom.sessionStatus.textContent = session?.authenticated
          ? `${session.nickname || session.username} (${session.role}) session active.`
          : (window._t?.('admin.session_anon') ?? 'Anonymous. Log in as admin to unlock management features.');
        await Promise.all([refresh(), refreshUsers(), refreshLibrarian(), refreshSagwanSchedule(), refreshSagwanActivityPanels()]);
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
      dom.sagwanActivityRefresh?.addEventListener('click', loadSagwanActivity);
      dom.sagwanCapsulesRefresh?.addEventListener('click', loadSagwanCapsules);
      dom.sagwanResearchRefresh?.addEventListener('click', loadSagwanResearch);
      [dom.q, dom.kind, dom.method, dom.statusMin, dom.limit, dom.sort, dom.order, dom.requestId]
        .forEach((element) => element.addEventListener('input', scheduleRefresh));
      dom.userSearch?.addEventListener('input', renderUsers);
      dom.usersRefresh?.addEventListener('click', refreshUsers);
      dom.roleSave?.addEventListener('click', saveRole);
      dom.librarianSave?.addEventListener('click', saveLibrarian);
      dom.sagwanSave?.addEventListener('click', saveSagwanSchedule);
      dom.sagwanRunApproval?.addEventListener('click', runSagwanApproval);
      dom.sagwanRunCurate?.addEventListener('click', runSagwanCurate);
      dom.sagwanRunResearch?.addEventListener('click', runSagwanResearch);
      dom.impRefresh?.addEventListener('click', loadImprovementRequests);
      dom.impStatusFilter?.addEventListener('change', loadImprovementRequests);
      dom.impModalClose?.addEventListener('click', () => { if (dom.impModal) dom.impModal.hidden = true; });
      dom.impModalX?.addEventListener('click', () => { if (dom.impModal) dom.impModal.hidden = true; });

      // ── publication dashboard ────────────────────
      async function loadPublicationRequests() {
        const t = token();
        if (!t) {
          if (dom.pubList) dom.pubList.innerHTML = `<p class="locked-copy">${window._t?.('admin.pub_locked') ?? 'Login required.'}</p>`;
          if (dom.pubSummary) dom.pubSummary.textContent = window._t?.('admin.pub_locked') ?? 'Login required.';
          return;
        }
        const status = dom.pubStatusFilter?.value || '';
        const url = `${apiBase}/api/publication/requests?limit=200`;
        try {
          const res = await fetch(url, { headers: { Authorization: `Bearer ${t}` } });
          if (!res.ok) {
            dom.pubList.innerHTML = `<p class="locked-copy">${window._t?.('admin.pub_fetch_fail') ?? 'Failed to load. Check admin token.'}</p>`;
            if (dom.pubSummary) dom.pubSummary.textContent = window._t?.('admin.pub_fetch_fail') ?? 'Failed to load. Check admin token.';
            return;
          }
          const data = await res.json();
          const requests = data.requests || [];
          const counts = requests.reduce((acc, item) => {
            const key = String(item.status || 'unknown').toLowerCase();
            acc[key] = (acc[key] || 0) + 1;
            return acc;
          }, {});
          if (dom.pubSummary) {
            dom.pubSummary.textContent = [
              `total ${requests.length}`,
              `requested ${counts.requested || 0}`,
              `reviewing ${counts.reviewing || 0}`,
              `published ${counts.published || 0}`,
              `rejected ${counts.rejected || 0}`,
            ].join(' · ');
          }
          renderPublicationList(status ? requests.filter((item) => String(item.status || '').toLowerCase() === status) : requests);
        } catch (error) {
          if (dom.pubList) dom.pubList.innerHTML = `<p class="locked-copy">${escapeHtml(error.message)}</p>`;
          if (dom.pubSummary) dom.pubSummary.textContent = error.message;
        }
      }

      const pubRequestsIndex = {};

      function renderPublicationList(requests) {
        if (!dom.pubList) return;
        for (const key of Object.keys(pubRequestsIndex)) delete pubRequestsIndex[key];
        if (!requests.length) { dom.pubList.innerHTML = `<p class="locked-copy">${window._t?.('admin.pub_empty') ?? 'No requests.'}</p>`; return; }
        const statusColor = {
          requested: '#c2410c',
          reviewing: '#c2410c',
          approved: '#15803d',
          published: '#15803d',
          rejected: '#b91c1c',
          needs_merge: '#7c3aed',
          needs_evidence: '#0f766e',
          superseded: '#64748b',
        };
        dom.pubList.innerHTML = requests.map((r) => {
          pubRequestsIndex[r.path] = r;
          return `
          <div class="card pub-row" data-pub-path="${escapeHtml(r.path)}" data-pub-title="${escapeHtml(r.path)}" style="padding:14px 16px;cursor:pointer;display:grid;gap:4px;">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
              <span style="font-weight:700;font-size:.92rem;overflow-wrap:anywhere;">${escapeHtml(r.path)}</span>
              <span style="font-size:.74rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:${statusColor[r.status] || 'var(--muted)'};flex-shrink:0;">${escapeHtml(r.status)}</span>
            </div>
            <div style="font-size:.78rem;color:var(--muted);">Requester: ${escapeHtml(r.requester || '-')} · ${escapeHtml((r.requested_at || '').slice(0, 16).replace('T', ' '))} UTC</div>
            ${r.rationale ? `<div style="font-size:.82rem;color:var(--muted);">${escapeHtml(r.rationale)}</div>` : ''}
          </div>`;
        }).join('');
        dom.pubList.querySelectorAll('.pub-row').forEach((row) => {
          row.addEventListener('click', () => openPubModal(row.dataset.pubPath));
        });
      }

      function openPubModal(path) {
        pubCurrentPath = path;
        const item = pubRequestsIndex[path] || {};
        if (dom.pubModalTitle) dom.pubModalTitle.textContent = path.split('/').pop() || path;
        if (dom.pubModalPath) dom.pubModalPath.textContent = path;
        if (dom.pubModalReason) dom.pubModalReason.value = '';
        if (dom.pubModalStatus) dom.pubModalStatus.textContent = '';
        if (dom.pubModalMeta) {
          const evidence = Array.isArray(item.evidence_paths) ? item.evidence_paths : [];
          const parts = [];
          parts.push(`<div><strong>Status:</strong> ${escapeHtml(item.status || '-')}</div>`);
          parts.push(`<div><strong>Requester:</strong> ${escapeHtml(item.requester || '-')} · <strong>Requested:</strong> ${escapeHtml(item.requested_at || '-')}</div>`);
          if (item.decider) parts.push(`<div><strong>Decider:</strong> ${escapeHtml(item.decider)} · <strong>Decided:</strong> ${escapeHtml(item.decided_at || '-')}</div>`);
          if (item.rationale) parts.push(`<div style="margin-top:6px;"><strong>Rationale:</strong><br>${escapeHtml(item.rationale)}</div>`);
          if (item.decision_reason) parts.push(`<div style="margin-top:6px;"><strong>Decision reason:</strong><br>${escapeHtml(item.decision_reason)}</div>`);
          if (evidence.length) {
            parts.push(`<div style="margin-top:6px;"><strong>Evidence:</strong><ul style="margin:4px 0 0 18px;padding:0;">${evidence.map((e) => `<li>${escapeHtml(String(e))}</li>`).join('')}</ul></div>`);
          }
          dom.pubModalMeta.innerHTML = parts.join('');
        }
        if (dom.pubModal) dom.pubModal.hidden = false;
      }

      async function applyPublicationStatus(status) {
        if (!pubCurrentPath) return;
        const t = token();
        if (!t) { if (dom.pubModalStatus) dom.pubModalStatus.textContent = window._t?.('admin.pub_locked') ?? 'Login required.'; return; }
        const reason = dom.pubModalReason?.value?.trim() || '';
        try {
          const res = await fetch(`${apiBase}/api/publication/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${t}` },
            body: JSON.stringify({ path: pubCurrentPath, status, reason }),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || res.statusText);
          if (dom.pubModalStatus) dom.pubModalStatus.textContent = status === 'published' ? (window._t?.('admin.pub_approved') ?? `Approved. Core API ID: ${data.core_api_id || 'N/A'}`) : 'Done.';
          setTimeout(() => { if (dom.pubModal) dom.pubModal.hidden = true; loadPublicationRequests(); }, 1200);
        } catch (error) {
          if (dom.pubModalStatus) dom.pubModalStatus.textContent = error.message;
        }
      }

      dom.pubRefresh?.addEventListener('click', loadPublicationRequests);
      dom.pubStatusFilter?.addEventListener('change', loadPublicationRequests);
      dom.pubApprove?.addEventListener('click', () => applyPublicationStatus('published'));
      dom.pubReject?.addEventListener('click', () => applyPublicationStatus('rejected'));
      dom.pubModalClose?.addEventListener('click', () => { if (dom.pubModal) dom.pubModal.hidden = true; });
      dom.pubModalX?.addEventListener('click', () => { if (dom.pubModal) dom.pubModal.hidden = true; });
      document.addEventListener('closed-akashic-auth-change', () => { if (state.panel === 'publication') loadPublicationRequests(); });

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


def _viewer_can_open_path(path: str, viewer_owner: str | None, is_admin: bool) -> bool:
    safe_path = str(path or "").strip()
    if not safe_path:
        return False
    if safe_path.startswith("assets/"):
        return True
    try:
        document = load_document(safe_path)
    except Exception:
        return False
    visibility = str(document.frontmatter.get("visibility") or get_settings().default_note_visibility).strip().lower()
    if visibility == "public":
        return True
    if is_admin:
        return True
    if visibility == "shared":
        return bool(viewer_owner)
    owner = str(document.frontmatter.get("owner") or "").strip()
    return bool(viewer_owner and owner == viewer_owner)


def _note_payload(
    note: ClosedNote,
    notes: list[ClosedNote],
    route_prefix: str,
    *,
    viewer_owner: str | None = None,
    is_admin: bool = False,
) -> dict[str, Any]:
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

    reviews: list[dict[str, Any]] = []
    if note.kind in {"capsule", "claim"} and not note.targets:
        review_notes = _load_targeted_claims_for(note.path)
        review_notes = [review for review in review_notes if _viewer_can_open_note(review, viewer_owner, is_admin)]
        reviews = [
            {
                "claim_id": review.claim_id,
                "slug": review.slug,
                "path": review.path,
                "owner": review.owner,
                "stance": review.stance,
                "claim_review_lifecycle": review.claim_review_lifecycle,
                "self_authored": review.self_authored,
                "rationale_excerpt": review.body[:240],
                "evidence_urls": review.evidence_urls,
                "evidence_paths": [
                    p if _viewer_can_open_path(p, viewer_owner=viewer_owner, is_admin=is_admin) else "(restricted)"
                    for p in review.evidence_paths
                ],
                "created_at": review.frontmatter.get("created_at"),
                "target_title_snapshot": review.target_title_snapshot,
            }
            for review in review_notes[:100]
        ]

    return {
        "path": note.path,
        "slug": note.slug,
        "title": note.title,
        "kind": note.kind,
        "project": note.project,
        "status": note.status,
        "owner": note.owner,
        "original_owner": note.original_owner,
        "created_by": note.created_by,
        "visibility": note.visibility,
        "publication_status": note.publication_status,
        "claim_review_status": note.claim_review_status,
        "claim_review_badge": _claim_trust_badge(note.claim_review_status),
        "confirm_count": note.confirm_count,
        "support_count": note.confirm_count,
        "dispute_count": note.dispute_count,
        "neutral_count": note.neutral_count,
        "tags": note.tags,
        "related": note.related,
        "summary": note.summary,
        "body": note.body,
        "body_html": _render_markdown(note.body, lookup, route_prefix),
        "links": note.links,
        "claim_id": note.claim_id,
        "targets": note.targets,
        "stance": note.stance,
        "claim_review_lifecycle": note.claim_review_lifecycle,
        "self_authored": note.self_authored,
        "evidence_urls": note.evidence_urls,
        "evidence_paths": note.evidence_paths,
        "topic": note.topic,
        "target_title_snapshot": note.target_title_snapshot,
        "is_review_target": note.kind in {"capsule", "claim"} and not note.targets,
        "reviews": reviews,
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


def _link_list_html(
    items: list[dict[str, str]], title: str, route_prefix: str, empty_text: str | None = None
) -> str:
    route_prefix = _normalize_prefix(route_prefix)
    if not items:
        if not empty_text:
            return ""
        return (
            f'<section class="meta-section" data-meta-panel="links">'
            f'<h3 class="meta-title">{html.escape(title)}</h3>'
            f'<p class="meta-copy">{html.escape(empty_text)}</p>'
            f'</section>'
        )
    cards = "".join(
        f'<a class="note-card" href="{html.escape(item["href"])}"><strong>{html.escape(item["title"])}</strong><small>{html.escape(item["summary"] or "")}</small></a>'
        for item in items
    )
    slug = _slugify(title) or "links"
    count = len(items)
    return (
        f'<section class="meta-section" data-meta-panel="links">'
        f'<details class="meta-collapsible" data-collapsible-key="note-{slug}" open>'
        f'<summary class="meta-title meta-collapsible-summary">'
        f'<span>{html.escape(title)}</span>'
        f'<span class="meta-count" aria-label="{count} item{"s" if count != 1 else ""}">{count}</span>'
        f'</summary>'
        f'<div class="note-list">{cards}</div>'
        f'</details>'
        f'</section>'
    )


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
        href = _note_href(target.slug, route_prefix)
        return f'<a class="wiki-link" data-note-slug="{html.escape(target.slug)}" href="{html.escape(href)}">{html.escape(alias)}</a>'

    text = EMBED_LINK_PATTERN.sub(replace_embed, body)
    text = WIKI_LINK_PATTERN.sub(replace, text)
    text = MARKDOWN_IMAGE_PATTERN.sub(lambda match: _rewrite_markdown_image(match, route_prefix), text)
    raw_html = markdown.markdown(
        text,
        extensions=["extra", "fenced_code", "tables", "sane_lists"],
        output_format="html5",
    )
    return _inject_heading_anchors(_sanitize_html(raw_html))


def invalidate_notes_cache() -> None:
    global _NOTES_CACHE, _NOTES_CACHE_AT
    with _NOTES_CACHE_LOCK:
        _NOTES_CACHE = None
        _NOTES_CACHE_AT = 0.0


def _load_notes() -> list[ClosedNote]:
    global _NOTES_CACHE, _NOTES_CACHE_AT
    now = time.monotonic()
    with _NOTES_CACHE_LOCK:
        if _NOTES_CACHE is not None and now - _NOTES_CACHE_AT < _NOTES_CACHE_TTL:
            return _NOTES_CACHE
        root = Path(get_settings().closed_akashic_path).resolve()
        if not root.exists():
            _NOTES_CACHE = []
            _NOTES_CACHE_AT = time.monotonic()
            return _NOTES_CACHE
        notes = []
        for relative_path in list_note_paths():
            path = root / relative_path
            if path.is_file():
                notes.append(_parse_note(root, path))
        notes = _ensure_unique_slugs(notes)
        _NOTES_CACHE = notes
        _NOTES_CACHE_AT = time.monotonic()
        return _NOTES_CACHE


# TODO: path-based targeting is rename-fragile. move_document does not rewrite
# inbound references. Reviews orphan silently on rename until a later pass adds
# reference rewriting to the move flow.
def _load_targeted_claims_for(parent_path: str, *, include_consolidated: bool = False) -> list[ClosedNote]:
    notes = _load_notes()
    return sorted(
        [
            n for n in notes
            if n.kind == "claim"
            and n.targets == parent_path
            and (include_consolidated or n.claim_review_lifecycle != "consolidated")
        ],
        key=lambda n: str(n.frontmatter.get("created_at") or ""),
        reverse=True,
    )


def _parse_note(root: Path, path: Path) -> ClosedNote:
    raw = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw)
    rel_path = path.relative_to(root).as_posix()
    title = str(frontmatter.get("title") or path.stem)
    owner = str(frontmatter.get("owner") or get_settings().default_note_owner)
    kind = normalize_kind(str(frontmatter.get("kind") or "reference"))
    confirm_count = _effective_confirm_count(frontmatter, owner)
    dispute_count = _effective_dispute_count(frontmatter, owner)
    return ClosedNote(
        path=rel_path,
        slug=_slugify(path.stem),
        title=title,
        kind=kind,
        project=str(frontmatter.get("project") or "openakashic"),
        status=str(frontmatter.get("status") or "draft"),
        owner=owner,
        visibility=str(frontmatter.get("visibility") or get_settings().default_note_visibility),
        publication_status=str(frontmatter.get("publication_status") or "none"),
        tags=_as_list(frontmatter.get("tags")),
        related=_as_list(frontmatter.get("related")),
        summary=_extract_summary(body),
        body=body.strip(),
        links=sorted(set(match.group(1).strip() for match in WIKI_LINK_PATTERN.finditer(body))),
        frontmatter=frontmatter,
        confirm_count=confirm_count,
        dispute_count=dispute_count,
        neutral_count=_as_int(frontmatter.get("neutral_count")),
        claim_review_status=_normalize_claim_review_status(
            frontmatter,
            kind=kind,
            confirm_count=confirm_count,
            dispute_count=dispute_count,
        ),
        original_owner=str(frontmatter.get("original_owner") or frontmatter.get("owner") or get_settings().default_note_owner),
        created_by=str(frontmatter.get("created_by") or frontmatter.get("owner") or ""),
        freshness_date=str(frontmatter.get("freshness_date") or ""),
        decay_tier=str(frontmatter.get("decay_tier") or "general").strip().lower() or "general",
        snoozed_until=str(frontmatter.get("snoozed_until") or ""),
        claim_id=str(frontmatter.get("claim_id") or ""),
        targets=str(frontmatter.get("targets") or "").strip() or None,
        stance=str(frontmatter.get("stance") or ""),
        claim_review_lifecycle=_targeted_claim_lifecycle(frontmatter),
        self_authored=_as_bool(frontmatter.get("self_authored")),
        evidence_urls=_as_list(frontmatter.get("evidence_urls")),
        evidence_paths=_as_list(frontmatter.get("evidence_paths")),
        topic=str(frontmatter.get("topic") or ""),
        target_title_snapshot=str(frontmatter.get("target_title_snapshot") or ""),
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


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _parse_iso_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _confirmation_callers(value: Any) -> list[str]:
    callers: list[str] = []
    for item in _as_list(value):
        caller = ""
        if isinstance(item, dict):
            caller = str(item.get("by") or item.get("caller") or "").strip()
        else:
            raw = str(item).strip()
            if "|" in raw:
                caller = raw.split("|", 1)[0].strip()
            if not caller:
                match = re.search(r"['\"](?:by|caller)['\"]\s*:\s*['\"]([^'\"]+)['\"]", raw)
                caller = match.group(1).strip() if match else raw
        if caller and caller not in callers:
            callers.append(caller)
    return callers


def _effective_confirm_count(frontmatter: dict[str, Any], owner: str) -> int:
    if "confirmed_by" not in frontmatter:
        return _as_int(frontmatter.get("confirm_count"))
    owner_value = str(owner or "").strip()
    return sum(1 for caller in _confirmation_callers(frontmatter.get("confirmed_by")) if caller != owner_value)


def _stale_note_action(days_overdue: int) -> str:
    if days_overdue >= 30:
        return "Review the note and rewrite stale sections if the claim or source changed."
    if days_overdue > 0:
        return "Append a dated refresh section with current evidence, or snooze with snoozed_until if still valid."
    return "Review now; append a dated refresh section or confirm it after independent verification."


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


def _plain_text_from_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value or "")).strip()


def _inject_heading_anchors(rendered_html: str) -> str:
    seen_generated: dict[str, int] = {}

    def replace_heading(match: re.Match[str]) -> str:
        tag = match.group(1)
        attrs = match.group(2) or ""
        inner = match.group(3) or ""
        existing = re.search(r'\bid=(["\'])([^"\']+)\1', attrs)
        heading_id = (existing.group(2).strip() if existing else "") or _slugify(_plain_text_from_html(inner))
        if not existing:
            count = seen_generated.get(heading_id, 0)
            seen_generated[heading_id] = count + 1
            if count:
                heading_id = f"{heading_id}-{count + 1}"
            attrs = f'{attrs} id="{html.escape(heading_id, quote=True)}"'
        else:
            seen_generated[heading_id] = seen_generated.get(heading_id, 0) + 1
        anchor = f'<a class="heading-anchor" href="#{html.escape(heading_id, quote=True)}">#</a>'
        return f"<{tag}{attrs}>{inner}{anchor}</{tag}>"

    return re.sub(r"<(h[23])([^>]*)>(.*?)</\1>", replace_heading, rendered_html, flags=re.IGNORECASE | re.DOTALL)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣ぁ-んァ-ン一-龥]+", "-", value.strip()).strip("-").lower()
    return slug or "note"


def _empty_note() -> ClosedNote:
    empty_copy = "Your vault is empty. Create your first note to get started."
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
        summary=empty_copy,
        body=f"## Summary\n{empty_copy}",
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
            f'data-note-title="{html.escape(note.title)}" '
            f'data-note-path="{html.escape(note.path)}" '
            f'data-path="{html.escape(note.path)}" '
            f'href="{html.escape(_note_href(note.slug, route_prefix))}">'
            f'<span>{html.escape(note.title)}</span>'
            f"<small>{html.escape(note.path)}</small>"
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
    html, body { overscroll-behavior-y: contain; }
    html[data-theme="dark"] {
      color-scheme: dark;
      --bg: #0b1222;
      --surface: rgba(24, 31, 48, 0.88);
      --surface-strong: #182030;
      --panel: #13192a;
      --line: #2a3347;
      --line-strong: #38425a;
      --ink: #e6eaf3;
      --muted: #a8b1c5;
      --accent: #60a5fa;
      --accent-2: #2dd4bf;
      --code: #0a0f1e;
      --code-ink: #e6eaf3;
      --shadow: 0 18px 40px rgba(0, 0, 0, 0.38);
    }
    html[data-theme="dark"] body { background: var(--bg); color: var(--ink); }
    html[data-theme="dark"] .global-header {
      background: rgba(19, 25, 42, .88);
      border-bottom-color: var(--line);
    }
    html[data-theme="dark"] #command-palette .cmd-card {
      background: rgba(19, 25, 42, .98);
      border-color: var(--line);
    }
    html[data-theme="dark"] #command-palette .cmd-input {
      color: var(--ink);
      border-bottom-color: var(--line);
    }
    html[data-theme="dark"] #command-palette .cmd-item strong { color: var(--ink); }
    html[data-theme="dark"] #command-palette .cmd-item small { color: var(--muted); }
    html[data-theme="dark"] #command-palette .cmd-footer {
      background: rgba(11, 18, 34, .6);
      border-top-color: var(--line);
      color: var(--muted);
    }
    html[data-theme="dark"] #wiki-preview {
      background: rgba(19, 25, 42, .98);
      border-color: var(--line);
    }
    html[data-theme="dark"] #wiki-preview strong { color: var(--ink); }
    /* Auth modal card + inputs */
    html[data-theme="dark"] .global-modal-card {
      background: rgba(19, 26, 42, .98);
      border-color: var(--line);
    }
    html[data-theme="dark"] .global-modal-card h2 { color: var(--ink); }
    html[data-theme="dark"] .global-modal-card p { color: var(--muted); }
    html[data-theme="dark"] .auth-modal-close { color: var(--muted); border-color: var(--line); }
    html[data-theme="dark"] .auth-modal-close:hover { background: rgba(255, 255, 255, .08); color: var(--ink); }
    html[data-theme="dark"] .global-token-input {
      background: rgba(24, 31, 48, .92);
      border-color: var(--line);
      color: var(--ink);
    }
    html[data-theme="dark"] .global-token-input::placeholder { color: var(--muted); opacity: 1; }
    html[data-theme="dark"] .global-token-input:focus {
      border-color: rgba(96, 165, 250, .5);
      box-shadow: 0 0 0 4px rgba(96, 165, 250, .1);
    }
    html[data-theme="dark"] .global-token-input:disabled {
      background: rgba(11, 18, 34, .6);
      color: var(--muted);
    }
    html[data-theme="dark"] .auth-tabs {
      border-bottom-color: var(--line);
    }
    html[data-theme="dark"] .auth-tab {
      background: rgba(24, 31, 48, .82);
      border-color: var(--line);
      color: var(--muted);
    }
    html[data-theme="dark"] .auth-tab.active {
      background: rgba(96, 165, 250, .12);
      border-color: rgba(96, 165, 250, .25);
      color: var(--accent);
    }
    html[data-theme="dark"] .auth-field > span { color: var(--muted); }
    /* Workspace edit panel cards */
    html[data-theme="dark"] .workspace-card {
      background: rgba(24, 31, 48, .86);
      border-color: var(--line);
    }
    html[data-theme="dark"] .workspace-template {
      background: rgba(11, 18, 34, .7);
      color: var(--ink);
      border-color: var(--line);
    }
    html[data-theme="dark"] .field-input,
    html[data-theme="dark"] .editor-body-input,
    html[data-theme="dark"] .editor-title-input {
      background: rgba(24, 31, 48, .9);
      border-color: var(--line);
      color: var(--ink);
    }
    html[data-theme="dark"] .field-input::placeholder,
    html[data-theme="dark"] .editor-body-input::placeholder { color: var(--muted); opacity: 1; }
    html[data-theme="dark"] .field-label { color: var(--muted); }
    html[data-theme="dark"] .action-button {
      background: rgba(24, 31, 48, .9);
      border-color: var(--line);
      color: var(--ink);
    }
    html[data-theme="dark"] .action-button:hover { border-color: var(--accent); color: var(--accent); }
    /* Note meta/info sidebar */
    html[data-theme="dark"] .meta-value { color: var(--ink); }
    html[data-theme="dark"] .meta-label { color: var(--muted); }
    html[data-theme="dark"] .meta-grid .metric strong { color: var(--ink); }
    html[data-theme="dark"] .meta-grid .metric span { color: var(--muted); }
    html[data-theme="dark"] #graph-skeleton {
      background: linear-gradient(180deg, rgba(11, 18, 34, .7), rgba(11, 18, 34, .5));
    }
    .theme-toggle {
      display: inline-flex; align-items: center; justify-content: center;
      width: 34px; height: 34px; border-radius: 999px;
      border: 1px solid var(--line); background: rgba(255,255,255,.7);
      color: var(--muted); cursor: pointer; font-size: 15px;
      transition: background .18s ease, color .18s ease, border-color .18s ease;
    }
    .theme-toggle:hover { background: rgba(255,255,255,.95); color: var(--ink); }
    html[data-theme="dark"] .theme-toggle {
      background: rgba(24, 31, 48, .7);
      border-color: var(--line);
    }
    html[data-theme="dark"] .theme-toggle:hover { background: rgba(24, 31, 48, .95); color: var(--ink); }

    /* ─── Dark mode: component overrides ─────────────────────────────── */
    /* 모든 페이지에서 hardcode된 rgba(255,255,255,…) / rgba(248,250,252,…) 를 덮는다 */

    /* Note page sidebar */
    html[data-theme="dark"] .sidebar {
      background: rgba(19, 26, 42, 0.97);
      border-right-color: var(--line);
    }
    /* Sidebar edge toggle */
    html[data-theme="dark"] .sidebar-edge-toggle {
      background: rgba(19, 26, 42, 0.9);
      border-color: var(--line);
      color: var(--muted);
    }
    html[data-theme="dark"] .sidebar-edge-toggle:hover {
      background: rgba(24, 31, 48, 0.99);
      border-color: var(--line-strong);
      color: var(--ink);
    }
    /* Mini graph widget */
    html[data-theme="dark"] .mini-graph-widget {
      background: rgba(19, 26, 42, 0.97);
      border-color: var(--line-strong);
    }
    /* Note action buttons */
    html[data-theme="dark"] .note-edit-trigger,
    html[data-theme="dark"] .note-action-btn {
      background: rgba(24, 31, 48, 0.9);
      border-color: var(--line);
      color: var(--muted);
    }
    html[data-theme="dark"] .note-action-btn:hover,
    html[data-theme="dark"] .note-edit-trigger:hover { color: var(--ink); border-color: var(--line-strong); }
    html[data-theme="dark"] .note-action-btn.is-primary {
      background: var(--accent);
      color: #fff;
      border-color: transparent;
    }
    /* Search input + button (both pages) */
    html[data-theme="dark"] .search,
    html[data-theme="dark"] .filter-input {
      background: rgba(24, 31, 48, 0.9);
      color: var(--ink);
      border-color: var(--line);
    }
    html[data-theme="dark"] .search-btn {
      background: rgba(24, 31, 48, 0.9);
      color: var(--ink);
      border-color: var(--line);
    }
    html[data-theme="dark"] .search-btn:hover {
      background: rgba(37, 99, 235, 0.18);
      border-color: rgba(96, 165, 250, 0.4);
    }
    html[data-theme="dark"] .chip,
    html[data-theme="dark"] .chip-link {
      background: rgba(37, 48, 72, 0.92);
      color: var(--ink);
      border-color: var(--line-strong);
    }
    html[data-theme="dark"] .search::placeholder,
    html[data-theme="dark"] .filter-input::placeholder { color: var(--muted); opacity: 1; }
    /* Chip / path */
    html[data-theme="dark"] .chip:hover,
    html[data-theme="dark"] .chip-link:hover {
      background: rgba(37, 99, 235, 0.15);
      border-color: var(--accent);
      color: var(--accent);
    }
    /* Folder groups in nav */
    html[data-theme="dark"] .folder-group {
      background: rgba(19, 26, 42, 0.46);
    }
    html[data-theme="dark"] .folder-summary {
      background: rgba(24, 31, 48, 0.68);
      color: var(--ink);
    }
    html[data-theme="dark"] .folder-summary:hover { background: rgba(37, 99, 235, 0.12); }
    /* Nav links */
    html[data-theme="dark"] .nav-link:hover { background: rgba(255, 255, 255, 0.06); }
    html[data-theme="dark"] .nav-link.active { background: rgba(37, 99, 235, 0.15); }
    /* Path / breadcrumb area */
    html[data-theme="dark"] .path {
      background: rgba(24, 31, 48, 0.9);
    }
    /* Metric cards */
    html[data-theme="dark"] .metric {
      background: rgba(24, 31, 48, 0.94);
      border-color: var(--line);
    }
    /* Note cards (backlinks / related) */
    html[data-theme="dark"] .note-card {
      background: rgba(24, 31, 48, 0.86);
      border-color: var(--line);
      color: var(--ink);
    }
    html[data-theme="dark"] .note-card:hover {
      background: rgba(37, 99, 235, 0.10);
      border-color: rgba(96, 165, 250, 0.3);
    }
    html[data-theme="dark"] .note-card strong { color: var(--ink); }
    html[data-theme="dark"] .note-card small { color: var(--muted); }
    /* Meta section title */
    html[data-theme="dark"] .meta-title { color: var(--muted); }
    /* Tag pills */
    html[data-theme="dark"] .tag {
      background: rgba(45, 212, 191, 0.10);
      border-color: rgba(45, 212, 191, 0.22);
      color: var(--accent-2);
    }
    /* Search results dropdown */
    html[data-theme="dark"] .search-results {
      background: rgba(19, 26, 42, 0.98);
      border-color: var(--line);
    }
    html[data-theme="dark"] .search-result { color: var(--ink); }
    html[data-theme="dark"] .search-result:hover { background: rgba(255, 255, 255, 0.06); }
    html[data-theme="dark"] .search-result strong { color: var(--ink); }
    html[data-theme="dark"] .search-result small { color: var(--muted); }
    /* Graph page: main sidebar panel */
    html[data-theme="dark"] .graph-menu {
      background: rgba(19, 26, 42, 0.92);
      border-right-color: var(--line);
    }
    html[data-theme="dark"] .graph-panel-tabs {
      background: rgba(13, 19, 32, 0.88);
      border-bottom-color: var(--line);
    }
    html[data-theme="dark"] .panel-bar {
      background: rgba(19, 26, 42, 0.88);
      border-bottom-color: var(--line);
    }
    html[data-theme="dark"] .graph-panel-tab { color: var(--muted); }
    html[data-theme="dark"] .graph-panel-tab.active,
    html[data-theme="dark"] .graph-panel-tab:hover { color: var(--accent); background: rgba(37, 99, 235, 0.1); }
    /* Ghost button */
    html[data-theme="dark"] .button.ghost {
      background: rgba(24, 31, 48, 0.94);
      color: var(--ink);
      border-color: var(--line);
    }
    html[data-theme="dark"] .button.ghost:hover { border-color: var(--accent); color: var(--accent); }
    /* graph stats chip */
    html[data-theme="dark"] .chip.stats { color: var(--muted); }
    /* Filter meta text */
    html[data-theme="dark"] .filter-meta,
    html[data-theme="dark"] .sub,
    html[data-theme="dark"] .meta { color: var(--muted); }
    /* Section labels */
    html[data-theme="dark"] .section-label { color: var(--muted); }
    /* Selection access */
    html[data-theme="dark"] .selection-access { color: var(--muted); }
    /* Note main article area */
    html[data-theme="dark"] .content,
    html[data-theme="dark"] .article-wrap { background: transparent; color: var(--ink); }
    html[data-theme="dark"] .markdown { color: var(--ink); }
    html[data-theme="dark"] .markdown h1,
    html[data-theme="dark"] .markdown h2,
    html[data-theme="dark"] .markdown h3,
    html[data-theme="dark"] .markdown h4 { color: var(--ink); }
    html[data-theme="dark"] .markdown a { color: var(--accent); }
    html[data-theme="dark"] .markdown code {
      background: rgba(37, 99, 235, 0.12);
      color: var(--accent);
    }
    html[data-theme="dark"] .markdown pre,
    html[data-theme="dark"] .markdown pre code {
      background: rgba(11, 18, 34, 0.9);
      color: #e6eaf3;
    }
    html[data-theme="dark"] .markdown blockquote {
      border-left-color: var(--accent);
      color: var(--muted);
      background: rgba(37, 99, 235, 0.06);
    }
    html[data-theme="dark"] .markdown table th { background: rgba(37, 99, 235, 0.12); }
    html[data-theme="dark"] .markdown table td { border-color: var(--line); }
    html[data-theme="dark"] .markdown hr { border-color: var(--line); }
    /* Note header */
    html[data-theme="dark"] .note-header { background: transparent; }
    html[data-theme="dark"] .note-title { color: var(--ink); }
    html[data-theme="dark"] .breadcrumb,
    html[data-theme="dark"] .path-segment { color: var(--muted); }
    /* Workspace sidebar (note page) tabs */
    html[data-theme="dark"] .sidebar-tabs {
      background: rgba(19, 26, 42, .95);
      border-top-color: var(--line);
      border-bottom-color: var(--line);
    }
    html[data-theme="dark"] [data-sidebar-tab],
    html[data-theme="dark"] .meta-tab { color: var(--muted); }
    html[data-theme="dark"] [data-sidebar-tab].active,
    html[data-theme="dark"] .meta-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
    /* Top-level workspace area */
    html[data-theme="dark"] #workspace-sidebar {
      background: rgba(19, 26, 42, 0.92);
      border-right-color: var(--line);
    }
    /* Main area / page wrapper */
    html[data-theme="dark"] .main,
    html[data-theme="dark"] .page-wrap,
    html[data-theme="dark"] .closed-page { background: var(--bg); }

    body.closed-with-header {
      padding-top: var(--closed-header-height);
    }
    [data-admin-only][hidden] {
      display: none !important;
    }
    :focus-visible {
      outline: 2px solid rgba(37, 99, 235, .55);
      outline-offset: 2px;
      border-radius: 6px;
    }
    .skip-link {
      position: absolute;
      left: -9999px;
      top: 8px;
    }
    .skip-link:focus-visible {
      left: 8px;
      padding: 8px 12px;
      background: var(--accent);
      color: white;
      border-radius: 8px;
      z-index: 999;
      text-decoration: none;
    }
    .sr-only {
      position: absolute !important;
      width: 1px; height: 1px; padding: 0; margin: -1px;
      overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
    }
    .hl {
      background: rgba(37, 99, 235, .14);
      color: inherit;
      padding: 0 2px;
      border-radius: 3px;
    }
    html[data-theme="dark"] .hl {
      background: rgba(96, 165, 250, .22);
    }
    .markdown .heading-anchor {
      opacity: 0;
      font-size: .85em;
      color: var(--muted);
      margin-left: .4em;
      text-decoration: none;
      transition: opacity .16s ease;
    }
    .markdown h2:hover .heading-anchor,
    .markdown h3:hover .heading-anchor,
    .markdown h2:focus-within .heading-anchor,
    .markdown h3:focus-within .heading-anchor {
      opacity: 1;
    }
    @media (hover: none) {
      .markdown .heading-anchor { opacity: .3; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.001ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.001ms !important;
        scroll-behavior: auto !important;
      }
    }
    .global-toast {
      position: fixed;
      left: 50%;
      bottom: 22px;
      transform: translate(-50%, 18px);
      min-width: min(320px, calc(100vw - 32px));
      max-width: min(560px, calc(100vw - 32px));
      padding: 11px 16px;
      border-radius: 8px;
      border: 1px solid rgba(15, 23, 42, .08);
      background: rgba(15, 23, 42, .92);
      color: white;
      font-size: 13px;
      line-height: 1.45;
      box-shadow: 0 18px 36px rgba(15, 23, 42, .24);
      opacity: 0;
      pointer-events: none;
      transition: opacity .18s ease, transform .18s ease;
      z-index: 95;
    }
    .global-toast.visible {
      opacity: 1;
      transform: translate(-50%, 0);
    }
    .global-toast[data-tone="success"] { background: rgba(15, 118, 110, .96); }
    .global-toast[data-tone="warn"] { background: rgba(194, 65, 12, .96); }
    .global-toast[data-tone="error"] { background: rgba(185, 28, 28, .96); }
    #command-palette {
      position: fixed;
      inset: 0;
      z-index: 120;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding-top: 12vh;
      opacity: 0;
      pointer-events: none;
      transition: opacity .18s ease;
    }
    #command-palette.visible { opacity: 1; pointer-events: auto; }
    #command-palette[hidden] { display: none !important; }
    #command-palette .cmd-backdrop {
      position: absolute; inset: 0; background: rgba(15, 23, 42, .42);
      backdrop-filter: blur(4px);
    }
    #command-palette .cmd-card {
      position: relative;
      width: min(560px, calc(100vw - 32px));
      background: rgba(255, 255, 255, .99);
      border-radius: 14px;
      border: 1px solid rgba(15, 23, 42, .08);
      box-shadow: 0 24px 48px rgba(15, 23, 42, .24);
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }
    #command-palette .cmd-input {
      width: 100%;
      padding: 16px 18px;
      border: 0;
      border-bottom: 1px solid rgba(15, 23, 42, .08);
      font-size: 15px;
      outline: none;
      background: transparent;
    }
    #command-palette .cmd-list {
      max-height: 50vh;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
    }
    #command-palette .cmd-section {
      padding: 10px 18px 6px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .02em;
      text-transform: uppercase;
    }
    #command-palette .cmd-item {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 2px;
      padding: 10px 18px;
      border: 0;
      background: transparent;
      text-align: left;
      cursor: pointer;
      color: inherit;
    }
    #command-palette .cmd-item strong {
      font-size: 13.5px;
      font-weight: 600;
      color: rgba(15, 23, 42, 1);
    }
    #command-palette .cmd-item small {
      font-size: 11.5px;
      color: rgba(15, 23, 42, .52);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    #command-palette .cmd-item.active,
    #command-palette .cmd-item:hover {
      background: rgba(37, 99, 235, .09);
    }
    #command-palette .cmd-item.active strong { color: rgba(37, 99, 235, 1); }
    #command-palette .cmd-empty {
      padding: 22px 18px;
      color: rgba(15, 23, 42, .55);
      font-size: 13px;
    }
    #command-palette .cmd-footer {
      display: flex;
      justify-content: space-between;
      padding: 8px 18px;
      border-top: 1px solid rgba(15, 23, 42, .06);
      font-size: 11px;
      color: rgba(15, 23, 42, .5);
      background: rgba(248, 250, 252, .65);
    }
    .global-header {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      z-index: 90;
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: var(--closed-header-height);
      padding: 10px clamp(14px, 3vw, 28px);
      border-bottom: 1px solid rgba(215, 226, 239, .82);
      background: rgba(248, 250, 252, .86);
      backdrop-filter: blur(18px);
      box-shadow: 0 12px 32px rgba(15, 23, 42, .06);
    }
    .global-header .global-nav {
      flex: 1;
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
    .global-note-actions { display: none; }
    .global-pill[hidden] { display: none !important; }
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
    .global-pill.is-danger {
      background: rgba(220, 38, 38, .08);
      border-color: rgba(220, 38, 38, .18);
      color: #dc2626;
    }
    .global-pill.is-danger:hover {
      background: rgba(220, 38, 38, .14);
      border-color: rgba(220, 38, 38, .28);
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
      place-items: start center;
      padding: 18px;
      overflow-y: auto;
      overscroll-behavior: contain;
    }
    @media (min-height: 620px) {
      .global-modal { place-items: center; }
    }
    .global-modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, .32);
      backdrop-filter: blur(8px);
    }
    .global-modal-card {
      position: relative;
      width: min(480px, 100%);
      max-height: calc(100dvh - 36px);
      overflow-y: auto;
      overscroll-behavior: contain;
      padding: 22px;
      border-radius: 16px;
      border: 1px solid rgba(215, 226, 239, .9);
      background: rgba(248, 250, 252, .98);
      box-shadow: 0 28px 72px rgba(15, 23, 42, .24);
    }
    .auth-modal-close {
      position: absolute;
      top: 14px;
      right: 14px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: transparent;
      color: var(--muted);
      font-size: 1.2rem;
      cursor: pointer;
    }
    .auth-modal-close:hover {
      background: rgba(15, 23, 42, .06);
      color: var(--ink);
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
      width: min(560px, calc(100vw - 28px));
      height: min(78svh, 780px);
      min-width: 320px;
      min-height: 360px;
      max-width: calc(100vw - 28px);
      max-height: calc(100svh - 80px);
      display: grid;
      grid-template-rows: auto 1fr auto;
      overflow: hidden;
      resize: both;
      border-radius: 18px;
      border: 1px solid rgba(215, 226, 239, .92);
      background: rgba(250, 251, 253, .985);
      backdrop-filter: saturate(140%) blur(6px);
      box-shadow: 0 32px 80px rgba(15, 23, 42, .26);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", "Pretendard", "Apple SD Gothic Neo", Roboto, sans-serif;
      opacity: 0;
      transform: translateY(10px);
      pointer-events: none;
      transition: opacity .18s ease, transform .18s ease;
    }
    .librarian-panel::-webkit-resizer { background: transparent; }
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
      padding: 16px 18px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      background:
        radial-gradient(circle at top right, rgba(37,99,235,.06), transparent 30%),
        rgba(244,247,251,.72);
      scroll-behavior: smooth;
      font-size: .95rem;
    }
    .librarian-message {
      display: grid;
      gap: 6px;
      padding: 12px 15px;
      border-radius: 16px;
      border: 1px solid rgba(215, 226, 239, .72);
      background: rgba(255,255,255,.96);
      color: var(--ink);
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
      max-width: min(88%, 520px);
      box-shadow: 0 1px 2px rgba(15, 23, 42, .04);
    }
    .librarian-message[data-role="user"] {
      align-self: flex-end;
      border-color: rgba(37,99,235,.22);
      background: linear-gradient(180deg, rgba(37,99,235,.10), rgba(37,99,235,.06));
      border-bottom-right-radius: 6px;
    }
    .librarian-message[data-role="assistant"] {
      align-self: flex-start;
      border-color: rgba(15,118,110,.22);
      background: linear-gradient(180deg, rgba(240,253,250,.98), rgba(236,253,245,.88));
      border-bottom-left-radius: 6px;
    }
    .librarian-message code {
      font-family: "JetBrains Mono", "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: .88em;
      padding: 1px 5px;
      border-radius: 5px;
      background: rgba(15, 23, 42, .06);
    }
    .librarian-message pre {
      margin: 6px 0 0;
      padding: 10px 12px;
      border-radius: 10px;
      background: rgba(15, 23, 42, .88);
      color: #e2e8f0;
      font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
      font-size: .82rem;
      line-height: 1.55;
      overflow-x: auto;
    }
    .librarian-message-meta {
      color: var(--muted);
      font-size: .68rem;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
      opacity: .78;
    }
    .librarian-textarea {
      width: 100%;
      min-height: 72px;
      max-height: 240px;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.98);
      color: var(--ink);
      font: inherit;
      font-size: .94rem;
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
        gap: 6px;
        padding: 8px 12px;
      }
      .global-nav,
      .global-actions {
        justify-content: flex-start;
      }
      .global-nav { flex: 0 1 auto; gap: 4px; }
      .global-pill {
        min-height: 32px;
        padding: 0 8px;
        font-size: .78rem;
      }
    }
    @media (max-width: 560px) {
      .global-header { padding: 6px 12px; }
      .global-brand { gap: 6px; flex: 0 0 auto; }
      .global-brand-mark { width: 28px; height: 28px; font-size: .76rem; }
      .global-brand-subtitle { display: none; }
      .global-brand-title { font-size: .86rem; }
      .global-nav { flex: 1; gap: 2px; }
      .global-actions { flex: 0 0 auto; }
      .global-pill {
        min-height: 30px;
        padding: 0 7px;
        font-size: .74rem;
        border-radius: 8px;
      }
      .global-auth-button .auth-meta { display: none; }
    }
    """


def _shared_header_html(route_prefix: str, page_label: str, *, note_actions: bool = False) -> str:
    route_prefix = _normalize_prefix(route_prefix)
    note_action_html = ""
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
        <a class="global-pill" id="global-admin-link" href="{html.escape(_debug_href(route_prefix))}" hidden>Admin</a>
      </nav>{note_action_html}
      <div class="global-actions">
        <button class="theme-toggle" id="global-theme-toggle" type="button" aria-label="Toggle dark mode" title="Toggle dark mode">🌓</button>
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
    <script>
      (function applyTheme() {{
        try {{
          const stored = window.localStorage.getItem('closed-akashic-theme');
          const preferred = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
          const theme = stored || preferred;
          if (theme === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
        }} catch (e) {{}}
      }})();
    </script>
    <div class="global-modal" id="global-auth-modal" hidden>
      <div class="global-modal-backdrop" data-close-auth-modal></div>
      <section class="global-modal-card" role="dialog" aria-modal="true" aria-labelledby="global-auth-title">
        <button class="auth-modal-close" type="button" data-close-auth-modal aria-label="Close">&times;</button>
        <h2 id="global-auth-title">Account &amp; Profile</h2>
        <p id="global-auth-desc">Sign in with username and password. After login, manage your nickname and agent token here.</p>
        <div class="auth-tabs" id="global-auth-tabs" role="tablist" aria-label="Auth panels">
          <button class="auth-tab active" type="button" data-auth-panel="login">Login</button>
          <button class="auth-tab" type="button" data-auth-panel="signup">Sign Up</button>
          <button class="auth-tab" type="button" data-auth-panel="token" id="global-auth-tab-token">Token</button>
          <button class="auth-tab" type="button" data-auth-panel="profile">Profile</button>
          <button class="auth-tab" type="button" data-auth-panel="settings">Settings</button>
        </div>
        <section class="auth-panel" data-auth-panel-view="login">
          <div class="global-modal-grid">
            <label class="auth-field">
              <span>Username</span>
              <input class="global-token-input" id="global-login-username" type="text" placeholder="username" autocomplete="username" />
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
        <section class="auth-panel" data-auth-panel-view="token" hidden>
          <div class="global-modal-grid">
            <label class="auth-field">
              <span id="global-token-login-label">API Token</span>
              <input class="global-token-input" id="global-token-login-value" type="text" placeholder="paste your token here" autocomplete="off" spellcheck="false" />
            </label>
          </div>
          <p style="font-size:0.82em;margin:6px 0 0;opacity:0.65;" id="global-token-login-hint">Find your token: run <code>whoami</code> via MCP, or check your MCP client config (e.g. ~/.claude/settings.json).</p>
          <div class="global-modal-actions">
            <button class="global-pill is-primary" id="global-token-login-submit" type="button">Sign in with Token</button>
          </div>
        </section>
        <section class="auth-panel" data-auth-panel-view="signup" hidden>
          <div class="global-modal-grid">
            <label class="auth-field">
              <span>Username</span>
              <input class="global-token-input" id="global-signup-username" type="text" placeholder="username" autocomplete="username" />
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
          <div id="global-profile-setup-section" hidden>
            <p id="global-profile-setup-hint" style="font-size:0.82em;margin:14px 0 8px;opacity:0.7;">This account was provisioned automatically. Set a password to enable username/password login.</p>
            <div class="global-modal-grid">
              <label class="auth-field">
                <span id="global-profile-setup-password-new-label">New Password</span>
                <input class="global-token-input" id="global-profile-setup-password-new" type="password" autocomplete="new-password" />
              </label>
              <label class="auth-field">
                <span id="global-profile-setup-password-confirm-label">Confirm Password</span>
                <input class="global-token-input" id="global-profile-setup-password-confirm" type="password" autocomplete="new-password" />
              </label>
            </div>
            <div class="global-modal-actions">
              <button class="global-pill" id="global-profile-setup-password-submit" type="button">Set Password</button>
            </div>
          </div>
          <div id="global-profile-change-password-section">
            <div class="global-modal-grid" style="margin-top:14px;">
              <label class="auth-field">
                <span id="global-profile-password-current-label">Current Password</span>
                <input class="global-token-input" id="global-profile-password-current" type="password" autocomplete="current-password" />
              </label>
              <label class="auth-field">
                <span id="global-profile-password-new-label">New Password</span>
                <input class="global-token-input" id="global-profile-password-new" type="password" autocomplete="new-password" />
              </label>
              <label class="auth-field">
                <span id="global-profile-password-confirm-label">Confirm New Password</span>
                <input class="global-token-input" id="global-profile-password-confirm" type="password" autocomplete="new-password" />
              </label>
            </div>
            <div class="global-modal-actions">
              <button class="global-pill" id="global-profile-password-submit" type="button">Change Password</button>
            </div>
          </div>
        </section>
        <section class="auth-panel" data-auth-panel-view="settings" hidden>
          <div class="global-modal-grid">
            <label class="auth-field">
              <span id="settings-lang-label">Language</span>
              <select class="global-token-input" id="settings-lang-select">
                <option value="en">English</option>
                <option value="ko">한국어</option>
              </select>
            </label>
          </div>
        </section>
        <div class="global-modal-actions">
          <button class="global-pill" id="global-token-close" type="button">Close</button>
        </div>
        <div class="global-status" id="global-auth-status">Token is stored in this browser only.</div>
      </section>
    </div>
    <section class="librarian-fab" id="librarian-shell" data-admin-only hidden data-open="false">
      <div class="librarian-panel">
        <div class="librarian-head">
          <div class="librarian-head-row">
            <div>
              <p class="librarian-kicker">OpenAkashic Agents</p>
              <h2 class="librarian-title" id="agent-chat-title">Sagwan</h2>
              <p class="librarian-subtitle" id="agent-chat-subtitle">Issue directives or receive reports in admin mode.</p>
            </div>
            <button class="librarian-close" id="librarian-close" type="button" aria-label="Close librarian">×</button>
          </div>
        </div>
        <div class="librarian-messages" id="librarian-messages"></div>
        <div class="librarian-compose">
          <textarea class="librarian-textarea" id="librarian-input" placeholder="Send a command or request a report from the selected agent."></textarea>
          <div class="librarian-compose-row" style="margin-top:10px;">
            <div class="librarian-tools" id="librarian-status">Activate admin token to chat with agents.</div>
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
        // ── i18n ──────────────────────────────────────────────────────────────
        const LANG_STORAGE_KEY = 'oa-lang';
        const LANG_DICT = {{
          en: {{
            'auth.title': 'Account & Profile',
            'auth.desc': 'Sign in with username and password. After login, manage your nickname and agent token here.',
            'auth.status_default': 'Token is stored in this browser only.',
            'sagwan.label': 'Sagwan', 'sagwan.subtitle': 'Issue directives or receive reports in admin mode.',
            'sagwan.empty': 'Activate admin token to send commands to Sagwan.',
            'sagwan.waiting': 'Sagwan is preparing a response\u2026', 'sagwan.ready': 'Sagwan responded.', 'sagwan.failed': 'Sagwan request failed',
            'agent.status_locked': 'Activate admin token to chat with Sagwan.',
            'graph.select_node': 'Select a node',
            'graph.intro': 'Click a node to see neighbors and metadata. WASD to pan, scroll or pinch to zoom, Q/E to step through neighbors.',
            'graph.no_access': 'Your session cannot open this note. Only graph relations are visible.',
            'graph.can_access': 'Your session can open this note.',
            'graph.public_access': 'This is a public note \u2014 you can open it directly.',
            'graph.no_selection': 'Select a node to check access for the current session.',
            'graph.no_results': 'No results', 'graph.summary_empty': 'No summary',
            'mini.footer': 'Click a node to open the note.', 'mini.load_fail': 'Failed to load graph data.',
            'home.no_notes': 'No notes available.',
            'admin.session_checking': 'Checking admin session\u2026',
            'admin.session_anon': 'Anonymous. Log in as admin to unlock management features.',
            'admin.librarian_locked': 'Activate admin session to view agent runtime.',
            'admin.no_users': 'No users to show.', 'admin.users_failed': 'Failed to load users.',
            'admin.users_locked': 'Log in as admin to view users.', 'admin.users_need_admin': 'Admin token required.',
            'admin.roles_locked': 'Log in as admin to change roles.',
            'admin.select_user_first': 'Select a user first.',
            'admin.librarian_saving_locked': 'Log in as admin to save agent settings.', 'admin.librarian_saved': 'Agent settings saved.',
            'admin.librarian_runtime_locked': 'Log in as admin to view agent settings.',
            'admin.subordinate_saving_locked': 'Log in as admin to save Busagwan settings.', 'admin.subordinate_saved': 'Busagwan settings saved.',
            'admin.subordinate_runtime_locked': 'Log in as admin to view Busagwan settings.',
            'admin.subordinate_run_locked': 'Log in as admin to run Busagwan.',
            'admin.pub_locked': 'Login required.', 'admin.pub_fetch_fail': 'Failed to load. Check admin token.', 'admin.pub_empty': 'No requests.',
            'admin.pub_approved': 'Approved. Syncing to Core API\u2026',
            'admin.debug_locked': 'Log in as admin to view debug requests.', 'admin.debug_empty': 'No matching requests.',
            'edit.token_hint': 'Save token to edit title, body, metadata, images, and files inline.',
            'edit.edit_banner': 'Edit the Markdown source, then save with the Save button.',
            'edit.login_required': 'Please log in or set a token first.', 'edit.no_permission': 'Your session cannot edit this note.',
            'edit.load_fail': 'Failed to load folder info.',
            'auth.login_ok': 'Logged in. This token works for both web and agent access.',
            'auth.login_fields': 'Enter both username and password.',
            'auth.signup_fields': 'Username, nickname, password, and confirmation are all required.',
            'auth.signup_password_mismatch': 'Passwords do not match.',
            'auth.signup_ok': 'Account created and logged in. Copy your API token from the Profile tab.',
            'auth.profile_login_first': 'Please log in first.',
            'auth.token_rotated': 'New API token issued. Agent token updated.',
            'auth.token_copied': 'API token copied.', 'auth.token_copy_failed': 'Failed to copy token.',
            'auth.token_cleared': 'Token cleared. Read-only mode.', 'auth.token_verify_fail': 'Failed to verify token.',
            'auth.password_current': 'Current Password', 'auth.password_new': 'New Password', 'auth.password_confirm': 'Confirm New Password',
            'auth.password_change': 'Change Password',
            'auth.password_all_required': 'Enter your current password, new password, and confirmation.',
            'auth.password_mismatch': 'New password confirmation does not match.',
            'auth.password_changed': 'Password changed successfully.',
            'auth.login_failed': 'Login failed.', 'auth.signup_failed': 'Sign-up failed.',
            'auth.tab_token': 'Token',
            'auth.token_input': 'API Token',
            'auth.token_missing': 'Paste your API token first.',
            'auth.token_login_ok': 'Token accepted. Logged in.',
            'auth.setup_password_hint': 'This account was provisioned automatically. Set a password to enable username/password login.',
            'auth.setup_password_ok': 'Password set. You can now log in with your username and password.',
            'auth.setup_password_new_required': 'Enter new password and confirmation.',
            'auth.setup_password': 'Set Password',
            'settings.language': 'Language',
          }},
          ko: {{
            'auth.title': '\uacc4\uc815\uacfc \ud504\ub85c\ud544',
            'auth.desc': '\uc6f9\uc5d0\uc11c\ub294 \uc544\uc774\ub514\uc640 \ube44\ubc00\ubc88\ud638\ub85c \ub85c\uadf8\uc778\ud558\uace0, \ub85c\uadf8\uc778 \ub4a4\uc5d0\ub294 \ub2c9\ub124\uc784\uacfc \uc5d0\uc774\uc804\ud2b8\uc6a9 \ud1a0\ud070\uc744 \uc5ec\uae30\uc11c \uad00\ub9ac\ud55c\ub2e4.',
            'auth.status_default': '\ub85c\uadf8\uc778 \ub4a4 \ubc1c\uae09\ub41c \ud1a0\ud070\uc740 \uc774 \ube0c\ub77c\uc6b0\uc800\uc5d0\ub9cc \uc800\uc7a5\ub41c\ub2e4.',
            'sagwan.label': '\uc0ac\uad00', 'sagwan.subtitle': '\uad00\ub9ac\uc790 \uc0c1\ud0dc\uc5d0\uc11c \uc0ac\uad00\uc5d0\uac8c \uc6b4\uc601 \uba85\ub839\uc744 \ub0b4\ub9ac\uac70\ub098 \ubcf4\uace0\ub97c \ubc1b\uc744 \uc218 \uc788\ub2e4.',
            'sagwan.empty': '\uad00\ub9ac\uc790 \ud1a0\ud070\uc774 \ud65c\uc131\ud654\ub418\uba74 \uc0ac\uad00\uc5d0\uac8c \uc6b4\uc601 \uba85\ub839\uc774\ub098 \uc815\ub9ac \uc694\uccad\uc744 \ubcf4\ub0bc \uc218 \uc788\ub2e4.',
            'sagwan.waiting': '\uc0ac\uad00\uc774 \ub2f5\ubcc0\uc744 \uc900\ube44\ud558\ub294 \uc911\uc774\ub2e4.', 'sagwan.ready': '\uc0ac\uad00\uc774 \uc751\ub2f5\ud588\ub2e4.', 'sagwan.failed': '\uc0ac\uad00 \uc694\uccad \uc2e4\ud328',
            'agent.status_locked': '\uad00\ub9ac\uc790 \ud1a0\ud070\uc774 \ud65c\uc131\ud654\ub418\uba74 \uc0ac\uad00\uacfc \ub300\ud654\ud560 \uc218 \uc788\ub2e4.',
            'graph.select_node': '\ub178\ub4dc\ub97c \uc120\ud0dd\ud558\uc138\uc694',
            'graph.intro': '\uadf8\ub798\ud504\uc5d0\uc11c \ub178\ub4dc\ub97c \uace0\ub974\uba74 \uc5f0\uacb0\ub41c \uc774\uc6c3\uacfc \uba54\ud0c0 \uc815\ubcf4\ub97c \uac19\uc774 \ubcf4\uc5ec\uc900\ub2e4. WASD\ub85c \uc774\ub3d9, \ud720\uc774\ub098 \ud540\uce58\ub85c \ud655\ub300, Q/E\ub85c \uc774\uc6c3\uc744 \uc21c\ud68c\ud55c\ub2e4.',
            'graph.no_access': '\ud604\uc7ac \uc138\uc158\uc740 \uc774 \ub178\ud2b8\ub97c \uc5f4 \uc218 \uc5c6\ub2e4. \uadf8\ub798\ud504 \uad00\uacc4\ub9cc \ud655\uc778 \uac00\ub2a5\ud558\ub2e4.',
            'graph.can_access': '\ud604\uc7ac \uc138\uc158\uc740 \uc774 \ub178\ud2b8\ub97c \uc5f4 \uc218 \uc788\ub2e4.',
            'graph.public_access': '\uc774 \ub178\ud2b8\ub294 public \uacf5\uac1c \ubb38\uc11c\ub77c \ud604\uc7ac \uc138\uc158\uc73c\ub85c \ubc14\ub85c \uc5f4 \uc218 \uc788\ub2e4.',
            'graph.no_selection': '\ub178\ub4dc\ub97c \uace0\ub974\uba74 \ud604\uc7ac \uc138\uc158\uc5d0\uc11c \uc5f4 \uc218 \uc788\ub4f1\uc9c0 \ud568\uaed8 \ud45c\uc2dc\ud55c\ub2e4.',
            'graph.no_results': '\uac80\uc0c9 \uacb0\uacfc \uc5c6\uc74c', 'graph.summary_empty': '\uc694\uc57d \uc5c6\uc74c',
            'mini.footer': '\ub178\ub4dc\ub97c \ud074\ub9ad\ud558\uba74 \ud574\ub2f9 \ub178\ud2b8\ub85c \uc774\ub3d9\ud55c\ub2e4.', 'mini.load_fail': '\uadf8\ub798\ud504 \ub370\uc774\ud130\ub97c \ubd88\ub7ec\uc624\uc9c0 \ubabb\ud588\ub2e4.',
            'home.no_notes': '\uc9c0\uae08 \uc5f4 \uc218 \uc788\ub294 \ubb38\uc11c\uac00 \uc544\uc9c1 \uc5c6\ub2e4.',
            'admin.session_checking': '\uad00\ub9ac\uc790 \uc138\uc158\uc744 \ud655\uc778\ud558\ub294 \uc911\uc774\ub2e4.',
            'admin.session_anon': '\uc9c0\uae08\uc740 \uc775\uba85 \uc0c1\ud0dc\ub2e4. \uad00\ub9ac\uc790 \uacc4\uc815\uc73c\ub85c \ub85c\uadf8\uc778\ud558\uba74 \uad00\ub9ac \uae30\ub2a5\uc774 \uc5f4\ub9b0\ub2e4.',
            'admin.librarian_locked': '\uad00\ub9ac\uc790 \uc138\uc158\uc774 \ud65c\uc131\ud654\ub418\uba74 \uc0ac\uad00 \ub7f0\ud0c0\uc784\uc744 \ud655\uc778\ud560 \uc218 \uc788\ub2e4.',
            'admin.no_users': '\ud45c\uc2dc\ud560 \uc0ac\uc6a9\uc790\uac00 \uc5c6\ub2e4.', 'admin.users_failed': '\uc0ac\uc6a9\uc790 \ubaa9\ub85d\uc744 \ubd88\ub7ec\uc624\uc9c0 \ubabb\ud588\ub2e4.',
            'admin.users_locked': '\uad00\ub9ac\uc790 \ub85c\uadf8\uc778 \ub4a4 \uc0ac\uc6a9\uc790 \ubaa9\ub85d\uc744 \ubcfc \uc218 \uc788\ub2e4.', 'admin.users_need_admin': '\uad00\ub9ac\uc790 \ud1a0\ud070\uc774 \ud544\uc694\ud558\ub2e4.',
            'admin.roles_locked': '\uad00\ub9ac\uc790 \ub85c\uadf8\uc778 \ub4a4 \uc5ed\ud560\uc744 \ubc14\uafb8 \uc218 \uc788\ub2e4.',
            'admin.select_user_first': '\uba3c\uc800 \uc0ac\uc6a9\uc790\ub97c \uc120\ud0dd\ud574\uc918.',
            'admin.librarian_saving_locked': '\uad00\ub9ac\uc790 \ub85c\uadf8\uc778 \ub4a4 \uc0ac\uad00 \uc124\uc815\uc744 \uc800\uc7a5\ud560 \uc218 \uc788\ub2e4.', 'admin.librarian_saved': '\uc0ac\uad00 \uc124\uc815\uc744 \uc800\uc7a5\ud588\ub2e4.',
            'admin.librarian_runtime_locked': '\uad00\ub9ac\uc790 \ub85c\uadf8\uc778 \ub4a4 \uc0ac\uad00 \uc124\uc815\uc744 \ubcfc \uc218 \uc788\ub2e4.',
            'admin.subordinate_saving_locked': '\uad00\ub9ac\uc790 \ub85c\uadf8\uc778 \ub4a4 \ubd80\uc0ac\uad00 \uc124\uc815\uc744 \uc800\uc7a5\ud560 \uc218 \uc788\ub2e4.', 'admin.subordinate_saved': '\ubd80\uc0ac\uad00 \uc124\uc815\uc744 \uc800\uc7a5\ud588\ub2e4.',
            'admin.subordinate_runtime_locked': '\uad00\ub9ac\uc790 \ub85c\uadf8\uc778 \ub4a4 \ubd80\uc0ac\uad00 \uc124\uc815\uc744 \ubcfc \uc218 \uc788\ub2e4.',
            'admin.subordinate_run_locked': '\uad00\ub9ac\uc790 \ub85c\uadf8\uc778 \ub4a4 \ubd80\uc0ac\uad00\uc744 \uc2e4\ud589\ud560 \uc218 \uc788\ub2e4.',
            'admin.pub_locked': '\uad00\ub9ac\uc790 \ub85c\uadf8\uc778 \ud544\uc694', 'admin.pub_fetch_fail': '\ubd88\ub7ec\uc624\uae30 \uc2e4\ud328. \uad00\ub9ac\uc790 \ud1a0\ud070\uc778\uc9c0 \ud655\uc778\ud558\ub77c.', 'admin.pub_empty': '\uc694\uccad\uc774 \uc5c6\ub2e4.',
            'admin.pub_approved': '\uc2b9\uc778 \uc644\ub8cc. Core API \ub3d9\uae30\ud654 \uc911\u2026',
            'admin.debug_locked': '\uad00\ub9ac\uc790 \ub85c\uadf8\uc778 \ub4a4 \ub514\ubc84\uadf8 \uc694\uccad\uc744 \ubcfc \uc218 \uc788\ub2e4.', 'admin.debug_empty': '\uc870\uac74\uc5d0 \ub9de\ub294 \uc694\uccad\uc774 \uc5c6\ub2e4.',
            'edit.token_hint': '\ud1a0\ud070\uc744 \uc800\uc7a5\ud558\uba74 \uc81c\ubaa9, \ubcf8\ubb38, \uba54\ud0c0\ub370\uc774\ud130, \uc774\ubbf8\uc9c0\uc640 \ud30c\uc77c\uc744 \ud398\uc774\uc9c0 \uc548\uc5d0\uc11c \ubc14\ub85c \uc218\uc815\ud560 \uc218 \uc788\ub2e4.',
            'edit.edit_banner': '\ub9c8\ud06c\ub2e4\uc6b4 \uc6d0\ubb38\uc744 \uc218\uc815\ud55c \ub4a4 \uc6b0\uc0c1\ub2e8 Save\ub85c \uc800\uc7a5\ud55c\ub2e4.',
            'edit.login_required': '\uba3c\uc800 \ub85c\uadf8\uc778\ud558\uac70\ub098 \ud1a0\ud070\uc744 \uc801\uc6a9\ud574\uc918.', 'edit.no_permission': '\ud604\uc7ac \uc138\uc158\uc740 \uc774 \ub178\ud2b8\ub97c \uc218\uc815\ud560 \uc218 \uc5c6\ub2e4.',
            'edit.load_fail': '\ud3f4\ub354 \uc815\ubcf4\ub97c \ubd88\ub7ec\uc624\uc9c0 \ubabb\ud588\ub2e4.',
            'auth.login_ok': '\ub85c\uadf8\uc778\ud588\ub2e4. \uc774 \ud1a0\ud070\uc73c\ub85c \uc6f9\uacfc \uc5d0\uc774\uc804\ud2b8 \ub458 \ub2e4 \uc0ac\uc6a9\ud560 \uc218 \uc788\ub2e4.',
            'auth.login_fields': '\uc544\uc774\ub514\uc640 \ube44\ubc00\ubc88\ud638\ub97c \ubaa8\ub450 \uc785\ub825\ud574\uc918.',
            'auth.signup_fields': '\ud68c\uc6d0\uac00\uc785\uc5d0\ub294 \uc544\uc774\ub514, \ub2c9\ub124\uc784, \ube44\ubc00\ubc88\ud638, \ube44\ubc00\ubc88\ud638 \ud655\uc778\uc774 \ud544\uc694\ud558\ub2e4.',
            'auth.signup_password_mismatch': '\ube44\ubc00\ubc88\ud638 \ud655\uc778\uc774 \uc77c\uce58\ud558\uc9c0 \uc54a\ub294\ub2e4.',
            'auth.signup_ok': '\uacc4\uc815\uc744 \ub9cc\ub4e4\uace0 \ubc14\ub85c \ub85c\uadf8\uc778\ud588\ub2e4. \ud504\ub85c\ud544 \ud0ed\uc5d0\uc11c API \ud1a0\ud070\uc744 \ubcf5\uc0ac\ud560 \uc218 \uc788\ub2e4.',
            'auth.profile_login_first': '\uba3c\uc800 \ub85c\uadf8\uc778\ud574\uc918.',
            'auth.token_rotated': '\uc0c8 API \ud1a0\ud070\uc744 \ubc1c\uae09\ud588\ub2e4. \uc5d0\uc774\uc804\ud2b8\uac00 \uc4f8 \ud1a0\ud070\ub3c4 \ud568\uaed8 \ubc14\ub00c\uc5c8\ub2e4.',
            'auth.token_copied': '\ud604\uc7ac API \ud1a0\ud070\uc744 \ubcf5\uc0ac\ud588\ub2e4.', 'auth.token_copy_failed': '\ud1a0\ud070 \ubcf5\uc0ac\uc5d0 \uc2e4\ud328\ud588\ub2e4.',
            'auth.token_cleared': '\ud1a0\ud070\uc744 \uc9c0\uc6c0\ub2e4. \uc9c0\uae08\uc740 \uc77d\uae30 \uc804\uc6a9\uc774\ub2e4.', 'auth.token_verify_fail': '\ud1a0\ud070 \ud655\uc778\uc5d0 \uc2e4\ud328\ud588\ub2e4.',
            'auth.password_current': '\ud604\uc7ac \ube44\ubc00\ubc88\ud638', 'auth.password_new': '\uc0c8 \ube44\ubc00\ubc88\ud638', 'auth.password_confirm': '\uc0c8 \ube44\ubc00\ubc88\ud638 \ud655\uc778',
            'auth.password_change': '\ube44\ubc00\ubc88\ud638 \ubcc0\uacbd',
            'auth.password_all_required': '\ud604\uc7ac \ube44\ubc00\ubc88\ud638, \uc0c8 \ube44\ubc00\ubc88\ud638, \ud655\uc778\uc744 \ubaa8\ub450 \uc785\ub825\ud574\uc918.',
            'auth.password_mismatch': '\uc0c8 \ube44\ubc00\ubc88\ud638 \ud655\uc778\uc774 \uc77c\uce58\ud558\uc9c0 \uc54a\ub294\ub2e4.',
            'auth.password_changed': '\ube44\ubc00\ubc88\ud638\ub97c \ubcc0\uacbd\ud588\ub2e4.',
            'auth.login_failed': '\ub85c\uadf8\uc778 \uc2e4\ud328', 'auth.signup_failed': '\ud68c\uc6d0\uac00\uc785 \uc2e4\ud328',
            'auth.tab_token': '\ud1a0\ud070',
            'auth.token_input': 'API \ud1a0\ud070',
            'auth.token_missing': '\uba3c\uc800 API \ud1a0\ud070\uc744 \ube99\uc5ec\ub123\uc5b4\uc918.',
            'auth.token_login_ok': '\ud1a0\ud070 \ud655\uc778. \ub85c\uadf8\uc778\ub428.',
            'auth.setup_password_hint': '\uc774 \uacc4\uc815\uc740 \uc5d0\uc774\uc804\ud2b8\uac00 \uc790\ub3d9\uc73c\ub85c \ub9cc\ub4e4\uc5c8\ub2e4. \ube44\ubc00\ubc88\ud638\ub97c \uc124\uc815\ud558\uba74 \uc544\uc774\ub514/\ube44\ubc00\ubc88\ud638\ub85c\ub3c4 \ub85c\uadf8\uc778\ud560 \uc218 \uc788\ub2e4.',
            'auth.setup_password_ok': '\ube44\ubc00\ubc88\ud638\ub97c \uc124\uc815\ud588\ub2e4. \uc774\uc81c \uc544\uc774\ub514\uc640 \ube44\ubc00\ubc88\ud638\ub85c \ub85c\uadf8\uc778\ud560 \uc218 \uc788\ub2e4.',
            'auth.setup_password_new_required': '\uc0c8 \ube44\ubc00\ubc88\ud638\uc640 \ud655\uc778\uc744 \ubaa8\ub450 \uc785\ub825\ud574\uc918.',
            'auth.setup_password': '\ube44\ubc00\ubc88\ud638 \uc124\uc815',
            'settings.language': '\uc5b8\uc5b4',
          }},
        }};
        let _lang = window.localStorage.getItem(LANG_STORAGE_KEY) || 'en';
        function _t(key) {{
          const val = (LANG_DICT[_lang] || LANG_DICT.en)[key];
          return (val !== undefined) ? val : ((LANG_DICT.en)[key] ?? key);
        }}
        function _tf(key, ...args) {{
          const fn = (LANG_DICT[_lang] || LANG_DICT.en)[key] || (LANG_DICT.en)[key];
          return typeof fn === 'function' ? fn(...args) : (fn ?? key);
        }}
        function applyLang(lang) {{
          _lang = lang;
          window.localStorage.setItem(LANG_STORAGE_KEY, lang);
          const el = (id) => document.getElementById(id);
          const setText = (id, key) => {{ const e = el(id); if (e) e.textContent = _t(key); }};
          setText('global-auth-title', 'auth.title');
          const desc = el('global-auth-desc'); if (desc) desc.textContent = _t('auth.desc');
          const statusEl = el('global-auth-status'); if (statusEl && !statusEl.dataset.custom) statusEl.textContent = _t('auth.status_default');
          setText('agent-chat-title', 'sagwan.label');
          setText('agent-chat-subtitle', 'sagwan.subtitle');
          const ls = el('librarian-status'); if (ls && !ls.dataset.busy) ls.textContent = _t('agent.status_locked');
          const li = el('librarian-input'); if (li) li.placeholder = _t('agent.chat_placeholder') || li.placeholder;
          const langSel = el('settings-lang-select'); if (langSel) langSel.value = lang;
          const langLabel = el('settings-lang-label'); if (langLabel) langLabel.textContent = _t('settings.language');
          setText('global-profile-password-current-label', 'auth.password_current');
          setText('global-profile-password-new-label', 'auth.password_new');
          setText('global-profile-password-confirm-label', 'auth.password_confirm');
          const pwBtn = el('global-profile-password-submit'); if (pwBtn) pwBtn.textContent = _t('auth.password_change');
          setText('global-token-login-label', 'auth.token_input');
          const tabToken = el('global-auth-tab-token'); if (tabToken) tabToken.textContent = _t('auth.tab_token');
          setText('global-profile-setup-hint', 'auth.setup_password_hint');
          setText('global-profile-setup-password-new-label', 'auth.password_new');
          setText('global-profile-setup-password-confirm-label', 'auth.password_confirm');
          const setupBtn = el('global-profile-setup-password-submit'); if (setupBtn) setupBtn.textContent = _t('auth.setup_password');
          document.documentElement.lang = lang === 'ko' ? 'ko' : 'en';
        }}
        window._t = _t; window._tf = _tf;
        Object.defineProperty(window, '_lang', {{ get: () => _lang }});
        // ── end i18n ──────────────────────────────────────────────────────────
        const agents = {{
          sagwan: {{
            label: 'Sagwan',
            meta: 'Sagwan',
            endpoint: '/api/librarian/chat',
            get empty() {{ return _t('sagwan.empty'); }},
            get waiting() {{ return _t('sagwan.waiting'); }},
            get ready() {{ return _t('sagwan.ready'); }},
            get failed() {{ return _t('sagwan.failed'); }},
            get subtitle() {{ return _t('sagwan.subtitle'); }},
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
          profilePasswordCurrent: document.getElementById('global-profile-password-current'),
          profilePasswordNew: document.getElementById('global-profile-password-new'),
          profilePasswordConfirm: document.getElementById('global-profile-password-confirm'),
          profilePasswordSubmit: document.getElementById('global-profile-password-submit'),
          tokenLoginValue: document.getElementById('global-token-login-value'),
          tokenLoginSubmit: document.getElementById('global-token-login-submit'),
          profileSetupSection: document.getElementById('global-profile-setup-section'),
          profileChangePasswordSection: document.getElementById('global-profile-change-password-section'),
          profileSetupPasswordNew: document.getElementById('global-profile-setup-password-new'),
          profileSetupPasswordConfirm: document.getElementById('global-profile-setup-password-confirm'),
          profileSetupPasswordSubmit: document.getElementById('global-profile-setup-password-submit'),
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
          const allowed = ['login', 'token', 'signup', 'profile', 'settings'];
          const next = allowed.includes(panel) ? panel : (isAuthed ? 'profile' : 'login');
          dom.authTabs.forEach((button) => button.classList.toggle('active', button.dataset.authPanel === next));
          dom.authPanels.forEach((section) => {{
            section.hidden = section.dataset.authPanelView !== next;
          }});
          if (dom.authTabStrip) {{
            dom.authTabStrip.hidden = false;
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
          const isAdmin = Boolean(session?.authenticated && (session?.role === 'admin' || session?.role === 'manager'));
          const isUser = Boolean(session?.authenticated && !isAdmin);
          dom.authTrigger.dataset.tone = isAdmin ? 'admin' : isUser ? 'user' : 'warn';
          if (dom.authAvatar) dom.authAvatar.textContent = initialsFor(session);
          if (dom.authName) dom.authName.textContent = session?.nickname || 'Guest';
          if (dom.authRole) dom.authRole.textContent = session?.role || 'anonymous';
          // Show Admin nav link only to admin/manager
          const adminLink = document.getElementById('global-admin-link');
          if (adminLink) adminLink.hidden = !isAdmin;
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
          const provisioned = Boolean(session.provisioned);
          if (dom.profileSetupSection) dom.profileSetupSection.hidden = !provisioned;
          if (dom.profileChangePasswordSection) dom.profileChangePasswordSection.hidden = provisioned;
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
                  ? `${{session.nickname || session.username || 'user'}} connected (${{session.role}}).`
                  : 'No valid session or token.'
              );
            }}
            if (dom.librarianStatus) {{
              dom.librarianStatus.textContent = isAdmin
                ? `Model: ${{session?.librarian?.model || 'unknown'}}`
                : _t('agent.status_locked');
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
              setAuthStatus(error.message || _t('auth.token_verify_fail'));
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
          setAuthStatus(_t('auth.token_cleared'));
          reloadForAuthChange();
        }}

        async function login() {{
          const username = dom.loginUsername?.value.trim() || '';
          const password = dom.loginPassword?.value || '';
          if (!username || !password) {{
            setAuthStatus(_t('auth.login_fields'));
            return;
          }}
          try {{
            const data = await requestJson('/api/auth/login', {{
              method: 'POST',
              json: {{ username, password }},
            }});
            await applyIssuedToken(data.token || '');
            setAuthStatus(_t('auth.login_ok'));
            reloadForAuthChange();
          }} catch (error) {{
            setAuthStatus(error.message || _t('auth.login_failed'));
          }}
        }}

        async function loginWithToken() {{
          const value = (dom.tokenLoginValue?.value || '').trim();
          if (!value) {{
            setAuthStatus(_t('auth.token_missing'));
            return;
          }}
          await applyIssuedToken(value);
          if (state.session?.authenticated) {{
            setAuthStatus(_t('auth.token_login_ok'));
            if (state.session?.provisioned) {{
              sessionStorage.setItem('oa_open_profile', '1');
            }}
            reloadForAuthChange();
          }} else {{
            setAuthStatus(_t('auth.login_failed'));
          }}
        }}

        async function signup() {{
          const username = dom.signupUsername?.value.trim() || '';
          const nickname = dom.signupNickname?.value.trim() || '';
          const password = dom.signupPassword?.value || '';
          const password_confirm = dom.signupPasswordConfirm?.value || '';
          if (!username || !nickname || !password || !password_confirm) {{
            setAuthStatus(_t('auth.signup_fields'));
            return;
          }}
          if (password !== password_confirm) {{
            setAuthStatus(_t('auth.signup_password_mismatch'));
            return;
          }}
          try {{
            const data = await requestJson('/api/auth/signup', {{
              method: 'POST',
              json: {{ username, nickname, password, password_confirm }},
            }});
            await applyIssuedToken(data.token || '');
            setAuthStatus(_t('auth.signup_ok'));
            reloadForAuthChange();
          }} catch (error) {{
            setAuthStatus(error.message || _t('auth.signup_failed'));
          }}
        }}

        async function saveProfile() {{
          if (!state.session?.authenticated) {{
            setAuthStatus(_t('auth.profile_login_first'));
            return;
          }}
          try {{
            const data = await requestJson('/api/profile', {{
              method: 'POST',
              json: {{
                nickname: dom.profileNickname?.value.trim() || '',
              }},
            }});
            await refreshSession({{ silent: true }});
            syncProfileFields();
            setAuthStatus(`Profile saved: ${{data.profile?.nickname || state.session?.nickname || ''}}`);
          }} catch (error) {{
            setAuthStatus(error.message || 'Failed to save profile');
          }}
        }}

        async function rotateProfileToken() {{
          if (!state.session?.authenticated) {{
            setAuthStatus(_t('auth.profile_login_first'));
            return;
          }}
          try {{
            const data = await requestJson('/api/profile/token', {{
              method: 'POST',
            }});
            await applyIssuedToken(data.token || '');
            setAuthStatus(_t('auth.token_rotated'));
          }} catch (error) {{
            setAuthStatus(error.message || 'Failed to rotate token');
          }}
        }}

        async function changeProfilePassword() {{
          if (!state.session?.authenticated) {{
            setAuthStatus(_t('auth.profile_login_first'));
            return;
          }}
          const current = dom.profilePasswordCurrent?.value || '';
          const next = dom.profilePasswordNew?.value || '';
          const confirm = dom.profilePasswordConfirm?.value || '';
          if (!current || !next || !confirm) {{
            setAuthStatus(_t('auth.password_all_required'));
            return;
          }}
          if (next !== confirm) {{
            setAuthStatus(_t('auth.password_mismatch'));
            return;
          }}
          try {{
            await requestJson('/api/profile/password', {{
              method: 'POST',
              json: {{ current_password: current, new_password: next, new_password_confirm: confirm }},
            }});
            if (dom.profilePasswordCurrent) dom.profilePasswordCurrent.value = '';
            if (dom.profilePasswordNew) dom.profilePasswordNew.value = '';
            if (dom.profilePasswordConfirm) dom.profilePasswordConfirm.value = '';
            setAuthStatus(_t('auth.password_changed'));
          }} catch (error) {{
            setAuthStatus(error.message || 'Failed to change password');
          }}
        }}

        async function setupPassword() {{
          if (!state.session?.authenticated) {{
            setAuthStatus(_t('auth.profile_login_first'));
            return;
          }}
          const next = dom.profileSetupPasswordNew?.value || '';
          const confirm = dom.profileSetupPasswordConfirm?.value || '';
          if (!next || !confirm) {{
            setAuthStatus(_t('auth.setup_password_new_required'));
            return;
          }}
          if (next !== confirm) {{
            setAuthStatus(_t('auth.password_mismatch'));
            return;
          }}
          try {{
            await requestJson('/api/profile/setup-password', {{
              method: 'POST',
              json: {{ new_password: next, new_password_confirm: confirm }},
            }});
            if (dom.profileSetupPasswordNew) dom.profileSetupPasswordNew.value = '';
            if (dom.profileSetupPasswordConfirm) dom.profileSetupPasswordConfirm.value = '';
            if (state.session) state.session.provisioned = false;
            if (dom.profileSetupSection) dom.profileSetupSection.hidden = true;
            if (dom.profileChangePasswordSection) dom.profileChangePasswordSection.hidden = false;
            setAuthStatus(_t('auth.setup_password_ok'));
          }} catch (error) {{
            setAuthStatus(error.message || 'Failed to set password');
          }}
        }}

        async function copyProfileToken() {{
          const value = dom.profileToken?.value || token();
          if (!value) return;
          try {{
            await navigator.clipboard.writeText(value);
            setAuthStatus(_t('auth.token_copied'));
          }} catch (error) {{
            setAuthStatus(_t('auth.token_copy_failed'));
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

        function highlightText(target, text, query) {{
          if (!target) return;
          const source = String(text || '');
          const needle = String(query || '').trim();
          target.textContent = '';
          if (!needle) {{
            target.textContent = source;
            return;
          }}
          const haystack = source.toLowerCase();
          const lowerNeedle = needle.toLowerCase();
          const frag = document.createDocumentFragment();
          let cursor = 0;
          while (cursor < source.length) {{
            const next = haystack.indexOf(lowerNeedle, cursor);
            if (next === -1) {{
              frag.appendChild(document.createTextNode(source.slice(cursor)));
              break;
            }}
            if (next > cursor) {{
              frag.appendChild(document.createTextNode(source.slice(cursor, next)));
            }}
            const mark = document.createElement('mark');
            mark.className = 'hl';
            mark.textContent = source.slice(next, next + needle.length);
            frag.appendChild(mark);
            cursor = next + needle.length;
          }}
          target.appendChild(frag);
        }}

        const recentNotesKey = 'closed-akashic-recent-notes';
        function loadRecentNotes() {{
          try {{
            const raw = JSON.parse(window.localStorage.getItem(recentNotesKey) || '[]');
            return Array.isArray(raw) ? raw.filter((item) => typeof item === 'string' && item.trim()).slice(0, 6) : [];
          }} catch (error) {{
            return [];
          }}
        }}

        function recordRecentNote(slug) {{
          const value = String(slug || '').trim();
          if (!value) return;
          try {{
            const next = [value, ...loadRecentNotes().filter((item) => item !== value)].slice(0, 6);
            window.localStorage.setItem(recentNotesKey, JSON.stringify(next));
          }} catch (error) {{ /* quota/private mode: ignore */ }}
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
            dom.librarianStatus.textContent = _t('agent.status_locked');
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
          // 사관(사서장)에게만 현재 열람 중인 노트 slug를 자동 주입한다.
          const currentSlugMatch = window.location.pathname.match(/\\/notes\\/([^/?#]+)/);
          const currentNoteSlug = currentSlugMatch ? decodeURIComponent(currentSlugMatch[1]) : null;
          const chatPayload = {{
            message,
            thread: state.thread.slice(-12),
          }};
          if (currentNoteSlug) {{
            chatPayload.current_note_slug = currentNoteSlug;
          }}
          try {{
            const data = await requestJson(agent.endpoint, {{ method: 'POST', json: chatPayload }});
            state.thread.push({{ role: 'assistant', content: data.message || 'Empty response.' }});
            saveThread();
            renderThread();
            if (dom.librarianStatus) {{
              dom.librarianStatus.textContent = data.model
                ? `Model: ${{data.model}}`
                : agent.ready;
            }}
          }} catch (error) {{
            state.thread.push({{ role: 'assistant', content: error.message || agent.failed }});
            renderThread();
            if (dom.librarianStatus) dom.librarianStatus.textContent = error.message || agent.failed;
          }}
        }}

        dom.authTrigger?.addEventListener('click', openAuthModal);
        dom.authTabs.forEach((button) => button.addEventListener('click', () => setAuthPanel(button.dataset.authPanel || 'login')));
        dom.authClose?.addEventListener('click', closeAuthModal);
        dom.loginSubmit?.addEventListener('click', login);
        dom.tokenLoginSubmit?.addEventListener('click', loginWithToken);
        dom.tokenLoginValue?.addEventListener('keydown', (event) => {{ if (event.key === 'Enter') loginWithToken(); }});
        dom.signupSubmit?.addEventListener('click', signup);
        dom.profileSave?.addEventListener('click', saveProfile);
        dom.profileRotateToken?.addEventListener('click', rotateProfileToken);
        dom.profilePasswordSubmit?.addEventListener('click', changeProfilePassword);
        dom.profileSetupPasswordSubmit?.addEventListener('click', setupPassword);
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

        // language picker wiring
        const langSelect = document.getElementById('settings-lang-select');
        if (langSelect) {{
          langSelect.value = _lang;
          langSelect.addEventListener('change', () => applyLang(langSelect.value));
        }}
        // apply stored language on boot
        applyLang(_lang);

        setActiveAgent(activeAgent());
        if (token()) {{
          setStoredToken(token());
          refreshSession({{ silent: true }}).then((session) => {{
            if (sessionStorage.getItem('oa_open_profile') === '1') {{
              sessionStorage.removeItem('oa_open_profile');
              if (session?.authenticated) {{
                openAuthModal();
                setAuthPanel('profile');
              }}
            }}
          }});
        }} else {{
          setAdminVisible(false);
          setAuthButton(state.session);
          syncProfileFields();
          dispatchAuthChange();
        }}

        let __toastTimer = null;
        function __ensureToast() {{
          let el = document.getElementById('global-toast');
          if (!el) {{
            el = document.createElement('div');
            el.id = 'global-toast';
            el.className = 'global-toast';
            el.setAttribute('role', 'status');
            el.setAttribute('aria-live', 'polite');
            document.body.appendChild(el);
          }}
          return el;
        }}
        function notify(message, tone) {{
          if (!message) return;
          const toneName = ['success','warn','error','info'].includes(tone) ? tone : 'info';
          const el = __ensureToast();
          el.textContent = message;
          el.dataset.tone = toneName;
          el.classList.add('visible');
          window.clearTimeout(__toastTimer);
          const duration = toneName === 'error' ? 4200 : 2600;
          __toastTimer = window.setTimeout(() => el.classList.remove('visible'), duration);
        }}

        const themeToggleBtn = document.getElementById('global-theme-toggle');
        function setTheme(theme) {{
          if (theme === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
          else document.documentElement.removeAttribute('data-theme');
          try {{ window.localStorage.setItem('closed-akashic-theme', theme); }} catch (e) {{}}
        }}
        function toggleTheme() {{
          const current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
          setTheme(current === 'dark' ? 'light' : 'dark');
        }}
        themeToggleBtn?.addEventListener('click', toggleTheme);

        window.closedAkashicUI = {{
          getToken: token,
          getSession: () => state.session,
          refreshSession,
          apiFetch,
          requestJson,
          openAuthModal,
          closeAuthModal,
          setNoteWriteVisible,
          notify,
          highlightText,
          loadRecentNotes,
          recordRecentNote,
          setTheme,
          toggleTheme,
        }};
      }})();

      (function initCommandPalette() {{
        const graphDataUrl = '{html.escape(_graph_data_href(route_prefix))}';
        let modal = null;
        let input = null;
        let list = null;
        let registry = null;
        let pending = null;
        let selectedIndex = 0;
        let currentResults = [];

        function ensureModal() {{
          if (modal) return modal;
          modal = document.createElement('div');
          modal.id = 'command-palette';
          modal.hidden = true;
          modal.innerHTML = `
            <div class="cmd-backdrop" data-cmd-close></div>
            <div class="cmd-card" role="dialog" aria-modal="true" aria-label="Command palette">
              <input class="cmd-input" id="cmd-input" type="search" placeholder="Type to search notes…" autocomplete="off" />
              <div class="cmd-list" id="cmd-list" role="listbox"></div>
              <div class="cmd-footer"><span>↑↓ navigate</span><span>↵ open</span><span>Esc close</span></div>
            </div>`;
          document.body.appendChild(modal);
          input = modal.querySelector('#cmd-input');
          list = modal.querySelector('#cmd-list');
          modal.querySelector('[data-cmd-close]').addEventListener('click', closePalette);
          input.addEventListener('input', () => render(input.value));
          input.addEventListener('keydown', onInputKey);
          return modal;
        }}
        async function loadRegistry() {{
          if (registry) return registry;
          if (pending) return pending;
          pending = fetch(graphDataUrl).then((r) => r.ok ? r.json() : null).then((data) => {{
            registry = (data?.nodes || []).map((n) => ({{
              slug: n.slug || n.id,
              title: n.title || n.slug || n.id,
              summary: n.summary || n.path || '',
              path: n.path || '',
            }}));
            return registry;
          }}).catch(() => {{ registry = []; return registry; }});
          return pending;
        }}
        function score(item, q) {{
          const t = (item.title || '').toLowerCase();
          const p = (item.path || '').toLowerCase();
          if (t.startsWith(q)) return 3;
          if (t.includes(q)) return 2;
          if (p.includes(q)) return 1;
          return 0;
        }}
        function paletteButtons() {{
          return [...list.querySelectorAll('.cmd-item')];
        }}
        function createCommandItem(item, index, query) {{
          const button = document.createElement('button');
          button.className = `cmd-item${{index === 0 ? ' active' : ''}}`;
          button.dataset.cmdIndex = String(index);
          button.setAttribute('role', 'option');
          const strong = document.createElement('strong');
          const small = document.createElement('small');
          window.closedAkashicUI?.highlightText?.(strong, item.title || '', query);
          window.closedAkashicUI?.highlightText?.(small, item.path || '', query);
          button.appendChild(strong);
          button.appendChild(small);
          button.addEventListener('click', () => navigate(index));
          button.addEventListener('mouseenter', () => highlight(index));
          return button;
        }}
        function appendSection(label, items, query) {{
          if (!items.length) return;
          const header = document.createElement('div');
          header.className = 'cmd-section';
          header.textContent = label;
          list.appendChild(header);
          items.forEach((item) => {{
            list.appendChild(createCommandItem(item, currentResults.length, query));
            currentResults.push(item);
          }});
        }}
        function render(query) {{
          const q = String(query || '').trim();
          const ql = q.toLowerCase();
          const pool = registry || [];
          const recent = window.closedAkashicUI?.loadRecentNotes?.() || [];
          const bySlug = new Map(pool.map((item) => [item.slug, item]));
          list.replaceChildren();
          currentResults = [];
          selectedIndex = 0;
          if (!ql) {{
            const recentItems = recent.map((slug) => bySlug.get(slug)).filter(Boolean);
            const remaining = pool.filter((item) => !recent.includes(item.slug)).slice(0, 30);
            appendSection('Recent', recentItems, q);
            appendSection('All notes', remaining, q);
            if (currentResults.length) return;
            const empty = document.createElement('div');
            empty.className = 'cmd-empty';
            empty.textContent = 'Your vault is empty. Create your first note to get started.';
            list.appendChild(empty);
            return;
          }}
          const results = pool
            .map((item) => [score(item, ql), item])
            .filter(([value]) => value > 0)
            .sort((a, b) => b[0] - a[0])
            .map(([, item]) => item)
            .slice(0, 30);
          if (!results.length) {{
            const empty = document.createElement('div');
            empty.className = 'cmd-empty';
            empty.textContent = `Nothing matches "${{q}}" — try a different keyword.`;
            list.appendChild(empty);
            return;
          }}
          results.forEach((item) => {{
            list.appendChild(createCommandItem(item, currentResults.length, q));
            currentResults.push(item);
          }});
        }}
        function highlight(i) {{
          selectedIndex = i;
          paletteButtons().forEach((btn, j) => btn.classList.toggle('active', j === i));
        }}
        function navigate(i) {{
          const item = currentResults[i];
          if (!item) return;
          window.closedAkashicUI?.recordRecentNote?.(item.slug);
          closePalette();
          window.location.href = `{html.escape(_notes_base(route_prefix))}/${{encodeURIComponent(item.slug)}}`;
        }}
        function onInputKey(event) {{
          if (event.key === 'ArrowDown') {{ event.preventDefault(); if (currentResults.length) highlight((selectedIndex + 1) % currentResults.length); }}
          else if (event.key === 'ArrowUp') {{ event.preventDefault(); if (currentResults.length) highlight((selectedIndex - 1 + currentResults.length) % currentResults.length); }}
          else if (event.key === 'Enter') {{ event.preventDefault(); navigate(selectedIndex); }}
          else if (event.key === 'Escape') {{ event.preventDefault(); closePalette(); }}
        }}
        async function openPalette() {{
          ensureModal();
          modal.hidden = false;
          modal.classList.add('visible');
          input.value = '';
          input.focus();
          await loadRegistry();
          render('');
        }}
        function closePalette() {{
          if (!modal) return;
          modal.classList.remove('visible');
          modal.hidden = true;
        }}

        window.addEventListener('keydown', (event) => {{
          if ((event.metaKey || event.ctrlKey) && event.key && event.key.toLowerCase() === 'k') {{
            event.preventDefault();
            if (modal && modal.classList.contains('visible')) closePalette();
            else openPalette();
          }}
        }});
        if (window.closedAkashicUI) window.closedAkashicUI.openCommandPalette = openPalette;
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
        <p class="workspace-note" id="workspace-status">Save token to edit title, body, metadata, images, and files inline.</p>
        <button class="action-button subtle" id="workspace-clear">Clear Token</button>
        <p class="workspace-note">Token is stored in this browser only.</p>
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
        deleteButton: document.getElementById('global-delete-note'),
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
        if (window.closedAkashicUI?.notify) {
          window.closedAkashicUI.notify(message, tone);
          return;
        }
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
        if (!window.matchMedia('(max-width: 820px)').matches) {
          document.body.classList.remove('left-collapsed');
          window.localStorage.setItem('closed-akashic-left-collapsed', '0');
        }
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
          dom.kindSummary.textContent = `${spec.label}: ${spec.summary} Recommended folder: ${spec.folder}.`;
        }
        if (dom.kindTemplate) {
          dom.kindTemplate.textContent = buildKindTemplate(rawKind);
        }
      }

      async function requestJson(path, options = {}) {
        if (!window.closedAkashicUI?.requestJson) {
          throw new Error('Common admin UI is not ready yet.');
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
          showToast(error.message || (window._t?.('edit.load_fail') ?? 'Failed to load folder info.'), 'error');
        }
      }

      function setEditing(enabled) {
        document.body.classList.toggle('inline-editing', enabled);
        if (!enabled) {
          setBanner(window._t?.('edit.edit_banner') ?? 'Edit the Markdown source, then save with the Save button.');
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
          showToast(window._t?.('edit.login_required') ?? 'Please log in or set a token first.', 'warn');
          window.closedAkashicUI?.openAuthModal?.();
          return;
        }
        if (mode === 'edit' && !canWriteCurrent(session)) {
          showToast(window._t?.('edit.no_permission') ?? 'Your session cannot edit this note.', 'warn');
          return;
        }
        setSidebarPanel('edit');
        state.mode = mode;
        if (mode === 'new') {
          presetNewNote();
          if (dom.deleteButton) dom.deleteButton.style.visibility = 'hidden';
          setBanner('New note. Add a title and save to generate a path.');
        } else {
          if (dom.deleteButton) dom.deleteButton.style.visibility = '';
          await loadCurrentNote();
          setBanner('Title, summary, and body are editable inline.');
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
          showToast(window._t?.('edit.login_required') ?? 'Please log in or set a token first.', 'warn');
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
          setBanner('Loading current note...');
          const raw = await requestJson(`/api/raw-note?path=${encodeURIComponent(noteData.path)}`);
          const fm = raw.frontmatter || {};
          state.originalPath = raw.path || noteData.path;
          dom.formTitle.value = fm.title || noteData.title || '';
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
          setBanner('Changing the path will move the note before saving.');
        } catch (error) {
          setBanner(error.message || 'Failed to load current note.', 'error');
          showToast(error.message || 'Failed to load current note.', 'error');
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
          showToast('Add a title first.', 'warn');
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
          setBanner('Path filled in. Edit it if needed.', 'success');
        } catch (error) {
          showToast(error.message || 'Path suggestion failed.', 'error');
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
          body: dom.formBody.value.trimEnd() + '\\n',
        };
      }

      async function saveNote() {
        let path = dom.formPath.value.trim();
        if (!path) {
          await suggestPath();
          path = dom.formPath.value.trim();
        }
        if (!path) {
          showToast('A save path is required.', 'warn');
          dom.formPath.focus();
          return;
        }
        try {
          setBanner('Saving note...');
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
          setBanner(publicationRequested ? 'Saved and publication request submitted.' : 'Saved.', 'success');
          showToast(publicationRequested ? 'Saved and publication request submitted.' : 'Note saved.', 'success');
          const href = data.note?.href ? `${window.location.origin}${data.note.href}` : `${window.location.origin}/`;
          window.location.href = href;
        } catch (error) {
          setBanner(error.message || 'Save failed.', 'error');
          showToast(error.message || 'Save failed.', 'error');
        }
      }

      async function deleteNote() {
        if (state.mode !== 'edit' || !state.originalPath) return;
        if (!window.confirm('Delete this note?')) return;
        try {
          await requestJson('/api/note', {
            method: 'DELETE',
            json: { path: state.originalPath },
          });
          showToast('Note deleted.', 'success');
          window.location.href = `${window.location.origin}/`;
        } catch (error) {
          showToast(error.message || 'Delete failed.', 'error');
        }
      }

      async function createFolder() {
        const path = dom.folderPath.value.trim() || dom.formFolder.value.trim();
        if (!path) {
          showToast('Enter a folder path first.', 'warn');
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
          showToast('Folder created.', 'success');
          setBanner('Folder created. Use path suggestion to set the note path.', 'success');
        } catch (error) {
          showToast(error.message || 'Folder creation failed.', 'error');
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
          setBanner(window._t?.('edit.edit_banner') ?? 'Edit the Markdown source, then save with the Save button.');
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
