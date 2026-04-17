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

_SYNCABLE_KINDS = {"capsule", "claim", "reference", "evidence"}

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

def _extract_section(body: str, *headings: str) -> str:
    """마크다운 body에서 ## Heading 아래 내용을 추출한다. 여러 heading 후보를 순서대로 시도."""
    for heading in headings:
        pattern = re.compile(
            r"^##\s+" + re.escape(heading) + r"\s*\n(.*?)(?=\n##\s|\Z)",
            re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )
        match = pattern.search(body)
        if match:
            return match.group(1).strip()
    return ""


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
                cleaned = uri.strip()
                # path traversal 방지: 로컬 경로에 '..' 포함 시 무시
                if not cleaned.startswith("http") and ".." in cleaned:
                    continue
                uris.append(cleaned)
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


# ─── kind=capsule 동기화 ──────────────────────────────────────────────────────

def _sync_capsule(frontmatter: dict[str, Any], body: str, note_path: str) -> str | None:
    """Core API에 capsule 레코드를 생성하고 ID를 반환한다."""
    settings = get_settings()
    if not settings.core_api_write_key:
        logger.warning("core_api_bridge: OPENAKASHIC_CORE_WRITE_KEY not set, skipping capsule sync")
        return None

    title = str(frontmatter.get("title") or note_path).strip()
    confidence = _coerce_confidence(frontmatter.get("confidence"))
    tags = list(frontmatter.get("tags") or [])

    summary_text = _extract_section(body, "Summary")
    summary = _extract_sentences(summary_text) if summary_text else [title]

    outcome_text = _extract_section(body, "Outcome", "key_points", "Key Points", "Practical Use")
    key_points = [{"text": t} for t in _extract_bullets(outcome_text)] if outcome_text else []

    caveats_text = _extract_section(body, "Caveats", "cautions", "Cautions")
    cautions = [{"text": t} for t in _extract_bullets(caveats_text)] if caveats_text else []

    payload = {
        "title": title,
        "summary": summary,
        "key_points": key_points,
        "cautions": cautions,
        "source_claim_ids": [],
        "confidence": confidence,
        "metadata": {
            "tags": tags,
            "source_note": note_path,
            "source": "closed_akashic_publication",
        },
    }

    result = _core_api_post("/capsules", payload, settings.core_api_write_key, settings.core_api_url)
    capsule_id = str(result.get("id") or "")
    logger.info("core_api_bridge: synced capsule %s → Core API %s", note_path, capsule_id)
    return capsule_id or None


# ─── kind=claim 동기화 ────────────────────────────────────────────────────────

def _sync_claim(frontmatter: dict[str, Any], body: str, note_path: str) -> str | None:
    """Core API에 claim 레코드를 생성하고 ID를 반환한다."""
    settings = get_settings()
    if not settings.core_api_write_key:
        logger.warning("core_api_bridge: OPENAKASHIC_CORE_WRITE_KEY not set, skipping claim sync")
        return None

    claim_text = _extract_section(body, "Claim", "Summary")
    if not claim_text:
        # body 전체 첫 문단을 claim text로 사용
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip() and not p.startswith("#")]
        claim_text = paragraphs[0] if paragraphs else str(frontmatter.get("title") or note_path)

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
    evidence_text = _extract_section(body, "Evidence Links", "Evidence", "Sources")
    evidence_uris = _extract_evidence_links(evidence_text)
    if not evidence_uris:
        # Evidence Links 섹션이 없으면 원본 노트의 closed_note_uri를 붙여둔다.
        # Core API는 이 URI를 참조만 하고 fetch하지 않으므로 공개 열람 경로가 맞다.
        closed_public_base = (settings.public_base_url or "").rstrip("/")
        if closed_public_base:
            evidence_uris = [f"{closed_public_base}/closed/note?path={urlparse.quote(note_path)}"]
        else:
            evidence_uris = [f"closed-akashic://{note_path}"]

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
        if kind in {"capsule", "reference"}:
            return _sync_capsule(frontmatter, body, note_path)
        if kind == "claim":
            return _sync_claim(frontmatter, body, note_path)
    except urlerror.URLError as exc:
        logger.error("core_api_bridge: network error syncing %s: %s", note_path, exc)
    except Exception as exc:
        logger.error("core_api_bridge: unexpected error syncing %s: %s", note_path, exc)
    return None
