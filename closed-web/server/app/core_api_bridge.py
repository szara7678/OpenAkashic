"""
core_api_bridge.py

published 상태가 된 kind=capsule / kind=claim 노트를 OpenAkashic Core API로
자동 동기화한다.

- kind=capsule → POST /capsules
- kind=claim   → POST /claims + POST /evidences (Evidence Links 섹션 기반)
- 이미 동기화된 노트는 frontmatter의 core_api_id 필드로 건너뛴다.
- 실패해도 vault 동작에 영향을 주지 않도록 모든 예외를 로깅 후 무시한다.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from app.config import get_settings

logger = logging.getLogger(__name__)

_SYNCABLE_KINDS = {"capsule", "claim"}

# confidence 필드는 노트에서 "high"/"medium"/"low" 같은 라벨 또는 float으로 올 수 있다.
# Core API 스키마는 [0, 1] float만 받으므로 라벨을 대표 숫자로 매핑한다.
_CONFIDENCE_LABELS = {
    "high": 0.9,
    "medium": 0.7,
    "med": 0.7,
    "moderate": 0.7,
    "low": 0.5,
    "unknown": 0.5,
}


def _coerce_confidence(value: Any, default: float = 0.75) -> float:
    """노트 frontmatter의 confidence(문자열/숫자)를 [0,1] float으로 정규화한다."""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return min(1.0, max(0.0, float(value)))
    label = str(value).strip().lower()
    if label in _CONFIDENCE_LABELS:
        return _CONFIDENCE_LABELS[label]
    try:
        return min(1.0, max(0.0, float(label)))
    except ValueError:
        return default


# ─── 섹션 파서 ────────────────────────────────────────────────────────────────
# 영어/한국어 혼용 heading을 폭넓게 수용한다. 섹션 후보는 우선순위 순.

_SUMMARY_HEADINGS = (
    "Summary", "요약", "개요", "TL;DR", "Overview", "Abstract", "Brief",
)
_KEY_POINT_HEADINGS = (
    "Key Points", "key_points", "Key Takeaways", "Outcome", "Practical Use",
    "Findings", "핵심", "핵심 포인트", "요점", "포인트", "결론", "Conclusion",
    "What We Learned", "Learnings", "Insights",
)
_CAUTION_HEADINGS = (
    "Caveats", "cautions", "Cautions", "Limitations", "Warnings",
    "주의", "주의사항", "한계", "제약", "Risks", "Risk",
)


def _extract_section(body: str, *headings: str) -> str:
    """마크다운 body에서 ## Heading 아래 내용을 추출한다. 여러 heading 후보를 순서대로 시도.
    ##, ###, #### 모두 매칭 (depth 무관)."""
    for heading in headings:
        pattern = re.compile(
            r"^#{2,4}\s+" + re.escape(heading) + r"\s*\n(.*?)(?=\n#{2,4}\s|\Z)",
            re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )
        match = pattern.search(body)
        if match:
            return match.group(1).strip()
    return ""


def _extract_summary_text(body: str) -> str:
    text = _extract_section(body, *_SUMMARY_HEADINGS)
    if text:
        return text
    # 첫 번째 의미있는 단락 (# 제외, 코드블록 제외)
    in_code = False
    for block in body.split("\n\n"):
        stripped = block.strip()
        if not stripped:
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("---"):
            continue
        return stripped
    return ""


def _extract_key_points_text(body: str) -> str:
    return _extract_section(body, *_KEY_POINT_HEADINGS)


def _extract_cautions_text(body: str) -> str:
    return _extract_section(body, *_CAUTION_HEADINGS)


def _extract_bullets(text: str) -> list[str]:
    """마크다운 bullet list를 문자열 리스트로 변환한다. 코드 블록 내부는 건너뛴다."""
    lines = []
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = re.match(r"^[-*+]\s+(.+)", stripped)
        if not match:
            continue
        cleaned = match.group(1).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _extract_sentences(text: str) -> list[str]:
    """텍스트를 문장 단위로 분리한다 (bullet도 포함)."""
    bullets = _extract_bullets(text)
    if bullets:
        return bullets
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    return sentences or ([text.strip()] if text.strip() else [])


def _extract_evidence_links(text: str) -> list[str]:
    """Evidence Links 섹션에서 URL 또는 경로를 추출한다."""
    uris: list[str] = []
    for line in text.splitlines():
        # markdown link [text](url) 또는 bare URL
        for match in re.finditer(r"\[.*?\]\(([^)]+)\)|https?://\S+|personal_vault/\S+|doc/\S+", line):
            uri = match.group(1) or match.group(0)
            if uri:
                uris.append(uri.strip())
    return uris


# ─── HTTP 헬퍼 ────────────────────────────────────────────────────────────────

def _core_api_post(path: str, body: dict[str, Any], write_key: str, base_url: str) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-OpenAkashic-Key": write_key,
        },
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _patch_claim_status(claim_id: str, write_key: str, base_url: str) -> None:
    url = base_url.rstrip("/") + f"/claims/{claim_id}/status"
    data = json.dumps({"status": "accepted"}).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-OpenAkashic-Key": write_key,
        },
        method="PATCH",
    )
    with urlrequest.urlopen(req, timeout=15) as resp:
        resp.read()


# ─── claim 자동 생성 헬퍼 ─────────────────────────────────────────────────────

def _note_evidence_uri(note_path: str, settings: Any) -> str:
    closed_public_base = (settings.public_base_url or "").rstrip("/")
    if closed_public_base:
        return f"{closed_public_base}/closed/note?path={urlparse.quote(note_path)}"
    return f"closed-akashic://{note_path}"


def _create_derived_claim(
    text: str,
    claim_role: str,
    confidence: float,
    tags: list[str],
    note_path: str,
    settings: Any,
) -> str | None:
    """캡슐에서 도출된 claim을 생성·accept 상태로 승격. evidence는 원본 노트 링크 1개."""
    try:
        claim_result = _core_api_post(
            "/claims",
            {
                "text": text,
                "status": "pending",
                "confidence": confidence,
                "source_weight": 0.8,
                "claim_role": claim_role,
                "metadata": {
                    "tags": tags,
                    "source_note": note_path,
                    "source": "closed_akashic_capsule_derived",
                },
            },
            settings.core_api_write_key,
            settings.core_api_url,
        )
        cid = str(claim_result.get("id") or "")
        if not cid:
            return None

        _core_api_post(
            "/evidences",
            {
                "claim_id": cid,
                "source_type": "closed_akashic_note",
                "source_uri": _note_evidence_uri(note_path, settings),
                "note": f"Derived from capsule {note_path}",
            },
            settings.core_api_write_key,
            settings.core_api_url,
        )

        _patch_claim_status(cid, settings.core_api_write_key, settings.core_api_url)
        return cid
    except Exception as exc:
        logger.warning("core_api_bridge: derived claim create failed (%s): %s", text[:60], exc)
        return None


# ─── kind=capsule 동기화 ──────────────────────────────────────────────────────

def _sync_capsule(frontmatter: dict[str, Any], body: str, note_path: str) -> str | None:
    """
    Core API에 capsule 레코드를 생성하고 ID를 반환한다.

    규칙:
    1. Summary / 요약 / 개요 / TL;DR 섹션(또는 첫 단락)을 summary[]로.
    2. Key Points / 핵심 / 요점 / Outcome / 결론 섹션의 bullet을 key_points[]로.
    3. Cautions / 주의 / 한계 / Limitations 섹션의 bullet을 cautions[]로.
    4. summary 첫 문장은 core claim, 나머지는 support claim으로 자동 생성.
    5. 각 key_point는 support claim, 각 caution은 caution claim으로 자동 생성.
    6. 생성된 claim ID들을 source_claim_ids + key_points[].claim_id / cautions[].claim_id에 채운다.
    """
    settings = get_settings()
    if not settings.core_api_write_key:
        logger.warning("core_api_bridge: OPENAKASHIC_CORE_WRITE_KEY not set, skipping capsule sync")
        return None

    title = str(frontmatter.get("title") or note_path).strip()
    confidence = _coerce_confidence(frontmatter.get("confidence"))
    tags = list(frontmatter.get("tags") or [])

    summary_text = _extract_summary_text(body)
    summary_sentences = _extract_sentences(summary_text) if summary_text else []
    if not summary_sentences:
        summary_sentences = [title]
    summary = summary_sentences[:5]

    key_points_raw = _extract_bullets(_extract_key_points_text(body))
    cautions_raw = _extract_bullets(_extract_cautions_text(body))

    # 1) Summary → claims (first=core, rest=support)
    source_claim_ids: list[str] = []
    for idx, text in enumerate(summary):
        role = "core" if idx == 0 else "support"
        cid = _create_derived_claim(text, role, confidence, tags, note_path, settings)
        if cid:
            source_claim_ids.append(cid)

    # 2) Key points → support claims (link back via claim_id)
    key_points: list[dict[str, Any]] = []
    for text in key_points_raw[:10]:
        cid = _create_derived_claim(text, "support", confidence, tags, note_path, settings)
        if cid:
            source_claim_ids.append(cid)
            key_points.append({"text": text, "claim_id": cid})
        else:
            key_points.append({"text": text})

    # 3) Cautions → caution claims
    cautions: list[dict[str, Any]] = []
    for text in cautions_raw[:10]:
        cid = _create_derived_claim(text, "caution", confidence, tags, note_path, settings)
        if cid:
            source_claim_ids.append(cid)
            cautions.append({"text": text, "claim_id": cid})
        else:
            cautions.append({"text": text})

    payload = {
        "title": title,
        "summary": summary,
        "key_points": key_points,
        "cautions": cautions,
        "source_claim_ids": source_claim_ids,
        "confidence": confidence,
        "metadata": {
            "tags": tags,
            "source_note": note_path,
            "source": "closed_akashic_publication",
            "parser_version": "2026-04-19",
        },
    }

    result = _core_api_post("/capsules", payload, settings.core_api_write_key, settings.core_api_url)
    capsule_id = str(result.get("id") or "")
    logger.info(
        "core_api_bridge: synced capsule %s → Core API %s (claims=%d key_points=%d cautions=%d)",
        note_path, capsule_id, len(source_claim_ids), len(key_points), len(cautions),
    )
    return capsule_id or None


# ─── kind=claim 동기화 ────────────────────────────────────────────────────────

def _sync_claim(frontmatter: dict[str, Any], body: str, note_path: str) -> str | None:
    """Core API에 claim 레코드를 생성하고 ID를 반환한다."""
    settings = get_settings()
    if not settings.core_api_write_key:
        logger.warning("core_api_bridge: OPENAKASHIC_CORE_WRITE_KEY not set, skipping claim sync")
        return None

    claim_text = _extract_section(body, "Claim", "주장", *_SUMMARY_HEADINGS)
    if not claim_text:
        claim_text = _extract_summary_text(body) or str(frontmatter.get("title") or note_path)

    # bullet list라면 첫 항목을 사용
    bullets = _extract_bullets(claim_text)
    text = bullets[0] if bullets else claim_text.splitlines()[0].strip()
    if not text:
        return None

    confidence = _coerce_confidence(frontmatter.get("confidence"))
    claim_role_raw = str(frontmatter.get("claim_role") or frontmatter.get("kind") or "support")
    valid_roles = {"core", "support", "caution", "conflict", "example"}
    claim_role = claim_role_raw if claim_role_raw in valid_roles else "support"
    tags = list(frontmatter.get("tags") or [])

    claim_payload = {
        "text": text,
        "status": "pending",
        "confidence": confidence,
        "source_weight": 0.8,
        "claim_role": claim_role,
        "metadata": {
            "tags": tags,
            "source_note": note_path,
            "source": "closed_akashic_publication",
        },
    }

    claim_result = _core_api_post("/claims", claim_payload, settings.core_api_write_key, settings.core_api_url)
    claim_id = str(claim_result.get("id") or "")
    if not claim_id:
        return None

    # Evidence Links 섹션에서 증거 첨부
    evidence_text = _extract_section(body, "Evidence Links", "Evidence", "Sources", "근거", "출처")
    evidence_uris = _extract_evidence_links(evidence_text)
    if not evidence_uris:
        # Evidence Links 섹션이 없으면 원본 노트의 closed_note_uri를 붙여둔다.
        evidence_uris = [_note_evidence_uri(note_path, settings)]

    for uri in evidence_uris[:5]:  # 최대 5개
        try:
            _core_api_post(
                "/evidences",
                {
                    "claim_id": claim_id,
                    "source_type": "closed_akashic_note",
                    "source_uri": uri,
                    "note": f"Published from {note_path}",
                },
                settings.core_api_write_key,
                settings.core_api_url,
            )
        except Exception as exc:
            logger.warning("core_api_bridge: evidence attach failed for %s: %s", uri, exc)

    # evidence 첨부 후 accepted로 승격
    try:
        _patch_claim_status(claim_id, settings.core_api_write_key, settings.core_api_url)
    except Exception as exc:
        logger.warning("core_api_bridge: claim status patch failed %s: %s", claim_id, exc)

    logger.info("core_api_bridge: synced claim %s → Core API %s", note_path, claim_id)
    return claim_id


# ─── 공개 인터페이스 ──────────────────────────────────────────────────────────

def sync_published_note(frontmatter: dict[str, Any], body: str, note_path: str, *, force: bool = False) -> str | None:
    """
    publication_status=published 된 노트를 Core API로 동기화한다.

    반환값: 생성된 Core API 레코드 ID (실패 또는 비대상이면 None)
    이 함수는 절대 예외를 올리지 않는다 — vault 동작을 방해하지 않도록.

    force=True면 frontmatter의 기존 core_api_id를 무시하고 새 레코드를 생성한다.
    (key_points 파서 버그 수정 이후 과거 캡슐을 재생성할 때 사용.)
    """
    kind = str(frontmatter.get("kind") or "").strip().lower()
    if kind not in _SYNCABLE_KINDS:
        return None

    # 이미 동기화된 경우 건너뜀 (force 지정 시 우회)
    if not force and frontmatter.get("core_api_id"):
        return str(frontmatter["core_api_id"])

    try:
        if kind == "capsule":
            return _sync_capsule(frontmatter, body, note_path)
        if kind == "claim":
            return _sync_claim(frontmatter, body, note_path)
    except urlerror.URLError as exc:
        logger.error("core_api_bridge: network error syncing %s: %s", note_path, exc)
    except Exception as exc:
        logger.error("core_api_bridge: unexpected error syncing %s: %s", note_path, exc)
    return None
