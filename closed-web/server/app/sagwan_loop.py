"""
sagwan_loop.py

사관(sagwan, chief librarian)의 승인/정제 루틴.

설계 이념:
- 사관은 LLM(기본: claude-cli) 로 **지능형 최종 판단**을 내린다.
  규칙 기반 거버넌스 게이트는 *pre-filter* 로만 쓴다 (값싼 필터 + 근거 부재 차단).
  게이트를 통과한 후보만 LLM 에게 물어 approve/defer 를 받는다.
- 부사관(busagwan, gemma) 의 1차 리뷰가 입력 신호.
- 루틴은 *배치* 로 동작한다: 주기(기본 10분) OR 대기 요청 수(기본 3건) 도달 시 실행.
- 이 모듈은 `personal_vault/**` 원본 노트를 직접 공개하지 않는다 — 반드시 `kind` 가
  capsule/claim/reference 또는 경로가 `doc/` 이어야 한다.
- 별도 curation cycle 도 제공한다: 원본→capsule 파생 유도, stale 동기화 정리.
"""
from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any

from app.agent_memory import (
    after_task,
    before_task_context,
    distill_memory,
    gather_context,
    recent_memory_tail,
    remember,
    render_context_snippet,
)
from app.config import get_settings
from app.librarian import _invoke_claude_cli, load_librarian_settings
from app.vault import (
    PUBLICATION_REQUEST_FOLDER,
    append_section,
    list_publication_requests,
    load_document,
    set_publication_status,
)

logger = logging.getLogger(__name__)

SAGWAN_DECIDER = "sagwan"
# 공개 승격이 가능한 source note 의 kind. personal_vault/knowledge/** 내부는
# kind 가 capsule 이어야만 허용 (순수 학습/메모 원본 유출 방지).
_ALLOWED_PUBLIC_KINDS = {"capsule", "claim"}
_ALLOWED_PUBLIC_PATH_PREFIXES = ("doc/",)
# 원본 학습 노트가 쌓이는 영역. 이 아래의 노트는 kind=capsule 이 아니면 공개 불가.
_RAW_SOURCE_PREFIXES = ("personal_vault/knowledge/",)
_MIN_RATIONALE_CHARS = 20
# LLM 에 보내는 본문/이유 스니펫 상한 (토큰 낭비 방지)
_LLM_BODY_SNIPPET = 1600
_LLM_RATIONALE_SNIPPET = 600


def sagwan_settings_path() -> Path:
    return Path(get_settings().user_store_path).with_name("sagwan-settings.json")


def _default_sagwan_settings() -> dict[str, Any]:
    return {
        "enabled": True,
        "interval_sec": 600,       # 10분 주기
        "batch_trigger": 3,        # 대기 요청이 N건 이상이면 즉시 실행
        "require_subordinate_review": True,
        "use_llm": True,           # LLM 최종 판단 사용
        "curation_interval_sec": 3600,  # 1시간마다 정제 루틴
    }


def load_sagwan_settings() -> dict[str, Any]:
    defaults = _default_sagwan_settings()
    path = sagwan_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(defaults, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        raw = {}
    return {
        "enabled": bool(raw.get("enabled", defaults["enabled"])),
        "interval_sec": max(60, int(raw.get("interval_sec") or defaults["interval_sec"])),
        "batch_trigger": max(1, int(raw.get("batch_trigger") or defaults["batch_trigger"])),
        "require_subordinate_review": bool(
            raw.get("require_subordinate_review", defaults["require_subordinate_review"])
        ),
        "use_llm": bool(raw.get("use_llm", defaults["use_llm"])),
        "curation_interval_sec": max(
            300, int(raw.get("curation_interval_sec") or defaults["curation_interval_sec"])
        ),
    }


def save_sagwan_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_sagwan_settings()
    next_settings = {
        "enabled": bool(payload.get("enabled", current["enabled"])),
        "interval_sec": max(60, int(payload.get("interval_sec") or current["interval_sec"])),
        "batch_trigger": max(1, int(payload.get("batch_trigger") or current["batch_trigger"])),
        "require_subordinate_review": bool(
            payload.get("require_subordinate_review", current["require_subordinate_review"])
        ),
        "use_llm": bool(payload.get("use_llm", current["use_llm"])),
        "curation_interval_sec": max(
            300,
            int(payload.get("curation_interval_sec") or current["curation_interval_sec"]),
        ),
    }
    path = sagwan_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(next_settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return next_settings


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now_iso_minus_hours(hours: int) -> str:
    from datetime import timedelta
    t = datetime.now(UTC) - timedelta(hours=hours)
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _evaluate_gates(request_doc: Any, source_doc: Any, *, require_subordinate_review: bool) -> tuple[bool, list[str]]:
    """거버넌스 게이트(pre-filter). 모두 통과해야 LLM 판단으로 진행."""
    failures: list[str] = []
    fm = request_doc.frontmatter
    source_fm = source_doc.frontmatter if source_doc else {}

    # 1. 부사관 1차 리뷰가 있어야 한다 (AI 판단 입력)
    if require_subordinate_review:
        recommendation = str(fm.get("subordinate_recommendation") or "").strip().lower()
        reviewed_at = str(fm.get("subordinate_reviewed_at") or "").strip()
        if not reviewed_at:
            failures.append("subordinate review missing (busagwan hasn't reviewed yet)")
        elif recommendation != "approved":
            failures.append(f"subordinate recommendation is `{recommendation or 'none'}`, not `approved`")

    # 2. evidence_paths — soft signal only (no hard block).
    # Evidence notes are NEVER published; they stay at their original visibility.
    # Sagwan sees only the paths/URLs, not the contents of private notes.
    # Absence of evidence is allowed: Sagwan applies stricter self-completeness
    # criteria to evidence-free capsules instead of blocking outright.
    # (removed hard gate: callers should not need to expose internal work to publish)

    # 3. 원본 직접 공개 차단. 정책:
    #    - doc/** : 공개 운영 문서 영역, 허용
    #    - personal_vault/knowledge/** : 순수 학습/메모 원본, kind=capsule 만 허용
    #    - 그 외 personal_vault/** : kind in {capsule, claim} 허용
    if source_doc:
        source_path = source_doc.path
        source_kind = str(source_fm.get("kind") or "").strip().lower()
        if source_path.startswith(_ALLOWED_PUBLIC_PATH_PREFIXES):
            pass  # doc/** 는 공개 문서 영역
        elif source_path.startswith(_RAW_SOURCE_PREFIXES):
            if source_kind != "capsule":
                failures.append(
                    f"source `{source_path}` is raw learning/memo material under "
                    "`personal_vault/knowledge/` — only kind=capsule can be published from here, "
                    "derive a capsule first"
                )
        else:
            if source_kind not in _ALLOWED_PUBLIC_KINDS:
                failures.append(
                    f"source `{source_path}` has kind=`{source_kind}` — publication requires "
                    "kind in {capsule, claim}"
                )

    # 4. self-approval 차단: 사관이 생성한 capsule 은 사람이 검토해야 승격 가능
    if source_doc:
        generated_by = str(source_fm.get("generated_by") or "").lower()
        if generated_by == "sagwan":
            failures.append(
                f"source `{source_doc.path}` was generated by sagwan itself — "
                "human review required before auto-approval"
            )

    # 5. rationale 최소 길이
    rationale = str(source_fm.get("publication_rationale") or "").strip()
    # rationale 은 request body 의 "## Rationale" 섹션에도 있을 수 있다 — 본문으로 fallback
    if not rationale:
        body = getattr(request_doc, "body", "") or ""
        if "## Rationale" in body:
            after = body.split("## Rationale", 1)[1]
            rationale = after.split("##", 1)[0].strip() if "##" in after else after.strip()
    if len(rationale) < _MIN_RATIONALE_CHARS or rationale.lower().startswith("no rationale"):
        failures.append(f"rationale too short (<{_MIN_RATIONALE_CHARS} chars) or placeholder")

    return (not failures), failures


def _extract_rationale(request_doc: Any, source_doc: Any) -> str:
    """rationale 텍스트 추출 (source frontmatter 또는 request body)."""
    src_fm = source_doc.frontmatter if source_doc else {}
    r = str(src_fm.get("publication_rationale") or "").strip()
    if r:
        return r
    body = getattr(request_doc, "body", "") or ""
    if "## Rationale" in body:
        after = body.split("## Rationale", 1)[1]
        return after.split("##", 1)[0].strip() if "##" in after else after.strip()
    return ""


def _build_sagwan_prompt(request_doc: Any, source_doc: Any) -> str:
    """사관 LLM 에게 보낼 결정 프롬프트."""
    fm = request_doc.frontmatter
    src_fm = source_doc.frontmatter if source_doc else {}
    source_path = source_doc.path if source_doc else str(fm.get("source_path") or "?")
    source_kind = str(src_fm.get("kind") or "").lower()
    title = str(src_fm.get("title") or fm.get("title") or source_path)
    tags = list(src_fm.get("tags") or [])
    confidence = src_fm.get("confidence")
    evidence = [str(e) for e in (fm.get("evidence_paths") or []) if str(e).strip()]
    subordinate = str(fm.get("subordinate_recommendation") or "").lower()
    sub_reason = str(fm.get("subordinate_review_summary") or fm.get("subordinate_review_reason") or "").strip()
    rationale = _extract_rationale(request_doc, source_doc)[:_LLM_RATIONALE_SNIPPET]
    body_snippet = (getattr(source_doc, "body", "") or "")[:_LLM_BODY_SNIPPET]

    # 사관 3계층 메모리 컨텍스트 (distilled + episodic tail + related notes)
    query = f"{title} {' '.join(str(t) for t in tags[:3])}"
    ctx = before_task_context("sagwan", query, current_note_path=source_path)
    ctx_snippet = ctx["combined"]

    return "\n".join([
        "너는 OpenAkashic 의 사관(chief librarian)이다. 공개 승격 요청의 최종 판단을 내린다.",
        "규칙 게이트는 이미 통과된 상태다. 너는 품질과 맥락을 본다.",
        "",
        "판단 기준:",
        "- 공개되어도 되는 내용인가? (개인 식별, 미공개 계약/보안 정보 없는가)",
        "- evidence_paths 가 있으면: 근거가 주장을 실제로 뒷받침하는가?",
        "- evidence_paths 가 없으면: 본문만으로 자기완결적인가? 이 경우 완성도 기준을 더 높게 적용.",
        "  (내부 작업물 비공개는 정당한 선택이다 — evidence 없음을 결점으로 보지 마라.)",
        "- capsule 이라면 독립적으로 읽히고 재사용 가능한가? claim 이라면 단일한 주장이 명확한가?",
        "- 완성도가 낮거나 초안 티가 나면 defer 한다.",
        "",
        f"## 요청 메타",
        f"- source_path: `{source_path}`",
        f"- kind: `{source_kind}`",
        f"- title: {title}",
        f"- tags: {tags}",
        f"- confidence: {confidence}",
        (
            f"- evidence_paths ({len(evidence)}): {evidence[:8]}"
            if evidence
            else "- evidence_paths: 없음 (제공자가 내부 자료 비공개 선택 — 본문 자기완결성으로 판단)"
        ),
        f"- 부사관 추천: {subordinate}",
        f"- 부사관 메모: {sub_reason[:400] if sub_reason else '(없음)'}",
        "",
        "## Rationale",
        rationale or "(없음)",
        "",
        "## Source body (앞 1600자)",
        body_snippet or "(빈 문서)",
        "",
        ctx_snippet or "",
        "",
        "반드시 다음 형식으로만 답하라. 다른 설명 금지.",
        "DECISION: approve | defer",
        "REASON: <한 문장 — 한국어, 80자 이하>",
    ])


def _parse_sagwan_response(text: str) -> tuple[str, str]:
    """LLM 응답에서 (decision, reason) 추출. 파싱 실패 시 defer."""
    decision = "defer"
    reason = ""
    for line in (text or "").splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith("decision:"):
            value = stripped.split(":", 1)[1].strip().lower()
            if value.startswith("approve"):
                decision = "approve"
            elif value.startswith("defer"):
                decision = "defer"
        elif low.startswith("reason:"):
            reason = stripped.split(":", 1)[1].strip()
    if not reason:
        reason = (text or "").strip().splitlines()[0][:200] if text else "no reason parsed"
    return decision, reason


def _ask_sagwan_llm(request_doc: Any, source_doc: Any) -> tuple[str, str, str]:
    """사관 LLM 호출. (decision, reason, raw_response) 반환. CLI 오류 시 decision=defer."""
    prompt = _build_sagwan_prompt(request_doc, source_doc)
    model = (load_librarian_settings() or {}).get("model") or None
    raw = _invoke_claude_cli(prompt, model=model)
    if raw.startswith("[CLI 오류"):
        logger.warning("sagwan_loop: LLM 호출 실패 — %s", raw)
        return "defer", raw, raw
    decision, reason = _parse_sagwan_response(raw)
    return decision, reason, raw


def run_sagwan_approval_cycle(*, reason: str = "manual") -> dict[str, Any]:
    """대기 중인 publication request 를 일괄 검토하고 게이트+LLM 통과 시 published 로 승격한다."""
    settings = load_sagwan_settings()
    if not settings["enabled"]:
        return {"status": "disabled", "reason": reason, "processed": []}

    pending: list[Any] = []
    for candidate in list_publication_requests():
        # list_publication_requests 는 frontmatter.status (kind-level) 를 우선 읽어 publication_status
        # 와 엇갈릴 수 있다 — 요청 노트 자체의 publication_status 로 다시 확인한다.
        try:
            req_fm = load_document(candidate.path).frontmatter
        except Exception:
            continue
        pub_status = str(req_fm.get("publication_status") or "").lower()
        if pub_status not in {"requested", "reviewing"}:
            continue
        pending.append(candidate)

    processed: list[dict[str, Any]] = []
    for item in pending:
        try:
            request_doc = load_document(item.path)
            source_path = str(request_doc.frontmatter.get("source_path") or "")
            source_doc = None
            if source_path:
                try:
                    source_doc = load_document(source_path)
                except Exception:
                    processed.append({
                        "path": item.path,
                        "decision": "deferred",
                        "failures": [f"source note `{source_path}` missing — cannot verify"],
                    })
                    continue
            passed, failures = _evaluate_gates(
                request_doc,
                source_doc,
                require_subordinate_review=settings["require_subordinate_review"],
            )
            if not passed:
                _record_defer(request_doc, item.path, failures, llm_reason=None)
                processed.append({"path": item.path, "decision": "deferred", "failures": failures})
                continue

            # 게이트 통과 — LLM 최종 판단
            if settings["use_llm"]:
                decision, llm_reason, _raw = _ask_sagwan_llm(request_doc, source_doc)
            else:
                decision, llm_reason = "approve", "LLM disabled; gates-only approval"

            if decision == "approve":
                set_publication_status(
                    path=item.path,
                    status="published",
                    decider=SAGWAN_DECIDER,
                    reason=f"sagwan LLM approved: {llm_reason[:160]}",
                )
                append_section(
                    item.path,
                    f"Sagwan Final Decision {_now_iso()}",
                    "\n".join([
                        f"- decider: `{SAGWAN_DECIDER}`",
                        "- decision: `published`",
                        "- gates: all passed",
                        f"- llm_reason: {llm_reason}",
                    ]),
                )
                try:
                    remember(
                        "sagwan",
                        subject=f"published {source_path or item.path}",
                        outcome=f"approve — {llm_reason}",
                        kind="publication_approval",
                    )
                except Exception as exc:
                    logger.warning("sagwan memory append failed: %s", exc)
                processed.append({
                    "path": item.path,
                    "decision": "published",
                    "source": source_path,
                    "llm_reason": llm_reason,
                })
                logger.info("sagwan_loop: published %s (source=%s, reason=%s)",
                            item.path, source_path, llm_reason[:120])
            else:
                _record_defer(request_doc, item.path, failures=[], llm_reason=llm_reason)
                try:
                    remember(
                        "sagwan",
                        subject=f"deferred {source_path or item.path}",
                        outcome=f"defer — {llm_reason}",
                        kind="publication_defer",
                    )
                except Exception as exc:
                    logger.warning("sagwan memory append failed: %s", exc)
                processed.append({
                    "path": item.path,
                    "decision": "deferred",
                    "llm_reason": llm_reason,
                })
        except Exception as exc:
            logger.error("sagwan_loop: error on %s: %s", item.path, exc)
            processed.append({"path": item.path, "decision": "error", "error": str(exc)})

    published = sum(1 for p in processed if p.get("decision") == "published")
    return {
        "status": "ok",
        "reason": reason,
        "pending_count": len(pending),
        "published_count": published,
        "deferred_count": sum(1 for p in processed if p.get("decision") == "deferred"),
        "processed": processed,
    }
    # 매 배치 종료 후 장기 기억 정제 시도 (임계치 미달이면 자동 skip)
    try:
        after_task("sagwan", llm_invoke=_invoke_claude_cli)
    except Exception as exc:
        logger.debug("sagwan after_task distill skipped: %s", exc)


def _record_defer(request_doc: Any, path: str, failures: list[str], *, llm_reason: str | None) -> None:
    """reviewing 상태 유지 + 사관 메모 append + 재-append 방지 플래그 기록."""
    already_noted = str(request_doc.frontmatter.get("sagwan_auto_review_at") or "").strip()
    if already_noted and not llm_reason:
        # 이미 같은 이유로 한 번 기록했다 — 중복 기록 방지
        return
    lines = [
        f"- decider: `{SAGWAN_DECIDER}`",
        "- decision: `deferred` (held at reviewing)",
    ]
    if failures:
        lines.append("- gate_failures:")
        lines.extend(f"  - {msg}" for msg in failures)
    if llm_reason:
        lines.append(f"- llm_reason: {llm_reason}")
    lines.append("")
    lines.append("수정 후 재검토를 원하면 사관 메모를 초기화하거나 새 요청을 제출하세요.")

    append_section(path, f"Sagwan Auto-Review {_now_iso()}", "\n".join(lines))

    from app.vault import write_document
    next_fm = dict(request_doc.frontmatter)
    next_fm["sagwan_auto_review_at"] = _now_iso()
    if failures:
        next_fm["sagwan_auto_review_failures"] = failures
    if llm_reason:
        next_fm["sagwan_llm_reason"] = llm_reason
    write_document(path=path, body=request_doc.body, metadata=next_fm, allow_owner_change=True)


def pending_publication_request_count() -> int:
    """batch_trigger 비교용: 대기 상태 요청 수."""
    count = 0
    for item in list_publication_requests():
        try:
            fm = load_document(item.path).frontmatter
        except Exception:
            continue
        pub_status = str(fm.get("publication_status") or "").lower()
        if pub_status in {"requested", "reviewing"}:
            count += 1
    return count


# ─── 정제/큐레이션 루틴 ────────────────────────────────────────────────────────

def run_sagwan_curation_cycle(*, reason: str = "scheduled") -> dict[str, Any]:
    """
    사관의 정제(큐레이션) 루틴. 세 종류의 작업을 수행한다:
    (A) 원본 파생 유도 — knowledge/** raw 노트 → 부사관 draft_capsule enqueue
    (B) core_api 재동기화 — published 인데 core_api_id 없음 → sync_to_core_api enqueue
    (C) 재검증 — published capsule/claim/reference 오래된 순으로 사관 LLM 재검토
    (D) 피드 수급 — sources.json 정의된 RSS/arXiv 피드에서 새 항목 → crawl_url enqueue
    """
    try:
        a = _curate_derive_and_sync()
    except Exception as exc:
        logger.error("sagwan curation A/B failed: %s", exc)
        a = {"error": str(exc)}

    try:
        c = _curate_revalidate_published()
    except Exception as exc:
        logger.error("sagwan curation C (revalidate) failed: %s", exc)
        c = {"error": str(exc)}

    try:
        d = _curate_ingest_feeds()
    except Exception as exc:
        logger.error("sagwan curation D (feeds) failed: %s", exc)
        d = {"error": str(exc)}

    try:
        e = _curate_generate_capsules()
    except Exception as exc:
        logger.error("sagwan curation E (capsule gen) failed: %s", exc)
        e = {"error": str(exc)}

    try:
        f = distill_memory("sagwan", llm_invoke=_invoke_claude_cli)
    except Exception as exc:
        logger.error("sagwan distill failed: %s", exc)
        f = {"error": str(exc)}
    try:
        g = distill_memory("busagwan", llm_invoke=_invoke_claude_cli)
    except Exception as exc:
        logger.error("busagwan distill failed: %s", exc)
        g = {"error": str(exc)}

    summary = {
        "status": "ok", "reason": reason,
        "derive_sync": a, "revalidate": c, "feeds": d,
        "capsule_gen": e, "distill_sagwan": f, "distill_busagwan": g,
    }
    try:
        remember(
            "sagwan",
            subject=f"curation cycle ({reason})",
            outcome=(
                f"drafts={a.get('drafts_enqueued', 0)} "
                f"sync={a.get('sync_enqueued', False)} "
                f"revalidated={c.get('revalidated', 0)}/{c.get('checked', 0)} "
                f"feeds_enqueued={d.get('enqueued', 0)} "
                f"capsules_generated={e.get('generated', 0)} "
                f"distill_sagwan={f.get('status')} distill_busagwan={g.get('status')}"
            ),
            kind="curation",
        )
    except Exception as exc:
        logger.warning("sagwan curation memory append failed: %s", exc)
    logger.info("sagwan_loop curation: %s", summary)
    return summary


def _curate_derive_and_sync() -> dict[str, Any]:
    """(A) knowledge/** raw 노트 → draft_capsule, (B) stale published → sync_to_core_api."""
    from app.vault import list_note_paths, write_document
    from app.subordinate import enqueue_subordinate_task

    drafts_enqueued = 0
    stale_published_count = 0
    scanned = 0
    max_drafts = 3

    for path in list_note_paths():
        scanned += 1
        try:
            doc = load_document(path)
        except Exception:
            continue
        fm = doc.frontmatter or {}
        kind = str(fm.get("kind") or "").lower()
        pub_status = str(fm.get("publication_status") or "").lower()

        if pub_status == "published" and not fm.get("core_api_id") and kind in {"capsule", "claim", "reference"}:
            stale_published_count += 1

        if (
            path.startswith("personal_vault/knowledge/")
            and kind != "capsule"
            and drafts_enqueued < max_drafts
            and not fm.get("sagwan_capsule_draft_requested_at")
        ):
            body = getattr(doc, "body", "") or ""
            if len(body) >= 200:
                try:
                    enqueue_subordinate_task(
                        kind="draft_capsule",
                        payload={"source_path": path},
                        created_by="sagwan",
                    )
                    drafts_enqueued += 1
                    next_fm = dict(fm)
                    next_fm["sagwan_capsule_draft_requested_at"] = _now_iso()
                    write_document(path=path, body=body, metadata=next_fm, allow_owner_change=True)
                except Exception as exc:
                    logger.warning("sagwan curation: draft enqueue failed for %s: %s", path, exc)

    sync_enqueued = False
    if stale_published_count > 0:
        try:
            enqueue_subordinate_task(
                kind="sync_to_core_api",
                payload={"limit": max(5, min(stale_published_count, 20))},
                created_by="sagwan",
            )
            sync_enqueued = True
        except Exception as exc:
            logger.warning("sagwan curation: sync enqueue failed: %s", exc)

    return {
        "scanned": scanned,
        "drafts_enqueued": drafts_enqueued,
        "stale_published": stale_published_count,
        "sync_enqueued": sync_enqueued,
    }


def _validation_anchor(fm: dict[str, Any]) -> str:
    """재검증 기준 날짜 anchor. last_validated_at > updated > created."""
    for key in ("last_validated_at", "updated", "created"):
        v = str(fm.get(key) or "").strip()
        if v:
            return v
    return ""


def _curate_revalidate_published(*, max_per_cycle: int = 5) -> dict[str, Any]:
    """(C) published capsule/claim/reference 를 오래된 순으로 LLM 재검증."""
    from app.vault import list_note_paths, write_document

    candidates: list[tuple[str, str]] = []
    for path in list_note_paths():
        try:
            doc = load_document(path)
        except Exception:
            continue
        fm = doc.frontmatter or {}
        if str(fm.get("publication_status") or "").lower() != "published":
            continue
        if str(fm.get("kind") or "").lower() not in {"capsule", "claim", "reference"}:
            continue
        # 최근 재검증된 것은 24h 동안 재검증 대상에서 제외 (무한 루프 방지)
        last_v = str(fm.get("last_validated_at") or "")
        if last_v and last_v > _now_iso_minus_hours(24):
            continue
        candidates.append((_validation_anchor(fm), path))

    candidates.sort(key=lambda t: t[0])
    targets = [p for _, p in candidates[:max_per_cycle]]

    checked = 0
    ok = 0
    stale = 0
    refresh = 0
    results: list[dict[str, Any]] = []
    model = (load_librarian_settings() or {}).get("model") or None

    for path in targets:
        checked += 1
        try:
            doc = load_document(path)
        except Exception:
            continue
        fm = dict(doc.frontmatter or {})
        prompt = _build_revalidation_prompt(path, fm, doc.body or "")
        raw = _invoke_claude_cli(prompt, model=model)
        verdict, note = _parse_revalidation_response(raw)
        fm["last_validated_at"] = _now_iso()
        fm["sagwan_validation_count"] = int(fm.get("sagwan_validation_count") or 0) + 1
        fm["sagwan_last_validation_verdict"] = verdict
        fm["sagwan_last_validation_note"] = note[:300]
        if verdict == "stale":
            fm["stale"] = True
            fm["stale_reason"] = note[:300]
            stale += 1
        elif verdict == "refresh":
            refresh += 1
            try:
                from app.subordinate import enqueue_subordinate_task
                enqueue_subordinate_task(
                    kind="draft_capsule",
                    payload={"source_path": path},
                    created_by="sagwan",
                )
            except Exception as exc:
                logger.warning("sagwan curation: refresh enqueue failed %s: %s", path, exc)
        else:
            ok += 1
            if "stale" in fm:
                fm["stale"] = False
        try:
            write_document(path=path, body=doc.body, metadata=fm, allow_owner_change=True)
        except Exception as exc:
            logger.warning("sagwan curation: write_document failed for %s: %s", path, exc)
        append_section(
            path,
            f"Sagwan Revalidation {_now_iso()}",
            "\n".join([f"- verdict: `{verdict}`", f"- note: {note[:400]}"]),
        )
        results.append({"path": path, "verdict": verdict, "note": note[:160]})

    return {
        "candidates": len(candidates),
        "checked": checked,
        "revalidated": ok,
        "stale": stale,
        "refresh_enqueued": refresh,
        "results": results,
    }


def _build_revalidation_prompt(path: str, fm: dict[str, Any], body: str) -> str:
    title = str(fm.get("title") or path)
    kind = str(fm.get("kind") or "")
    tags = list(fm.get("tags") or [])
    anchor = _validation_anchor(fm) or "(unknown)"
    return "\n".join([
        "너는 OpenAkashic 의 사관이다. 이미 공개된 노트가 지금도 유효한지 짧게 재검증한다.",
        "판단 기준:",
        "- 주장/수치/링크/권장안이 여전히 사실인가?",
        "- 기술 내용은 최근 practice 에 뒤처졌는가?",
        "- 오탈자/모순 없이 여전히 재사용 가능한가?",
        "",
        f"노트: `{path}`",
        f"title: {title}",
        f"kind: {kind}, tags: {tags}",
        f"이전 검증 시각: {anchor}",
        "",
        "## Body (앞 1600자)",
        body[:1600] or "(빈 문서)",
        "",
        "정확히 다음 형식으로만 답하라.",
        "VERDICT: ok | stale | refresh",
        "NOTE: <한 문장 근거, 한국어, 80자 이하>",
        "",
        "의미:",
        "- ok: 변경 불필요",
        "- stale: 정보가 낡았지만 업데이트 여력 없음 (stale 플래그만)",
        "- refresh: 부사관에게 새 capsule 초안을 맡길 가치 있음",
    ])


def _parse_revalidation_response(text: str) -> tuple[str, str]:
    verdict = "ok"
    note = ""
    for line in (text or "").splitlines():
        s = line.strip()
        low = s.lower()
        if low.startswith("verdict:"):
            v = s.split(":", 1)[1].strip().lower()
            if v.startswith("stale"):
                verdict = "stale"
            elif v.startswith("refresh"):
                verdict = "refresh"
            else:
                verdict = "ok"
        elif low.startswith("note:"):
            note = s.split(":", 1)[1].strip()
    if text.startswith("[CLI 오류"):
        # LLM 실패 시 ok 로 유지하지 않고 검증 미실시로 남겨둔다
        return "ok", f"LLM unavailable: {text[:120]}"
    if not note:
        note = (text or "").strip().splitlines()[0][:160] if text else ""
    return verdict, note


def _sources_file() -> Path:
    return Path(get_settings().user_store_path).with_name("agent-sources.json")


def _load_sources() -> list[dict[str, Any]]:
    """agent-sources.json 의 피드 정의 로드. 없으면 빈 리스트."""
    path = _sources_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("sources") or []
    return [item for item in data if isinstance(item, dict) and item.get("url")]


def _parse_feed_items(raw_xml: str, max_items: int) -> list[tuple[str, str]]:
    """RSS/Atom XML에서 (title, link) 쌍을 추출한다. xml.etree 우선, 실패 시 regex fallback."""
    import xml.etree.ElementTree as ET
    import re as _re

    items: list[tuple[str, str]] = []

    # ElementTree 파싱 시도 (CDATA, namespace 포함 feed 에 강함)
    try:
        root = ET.fromstring(raw_xml)
        # Atom namespace 처리
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        # RSS 2.0 <item>
        for item in root.iter("item"):
            t_el = item.find("title")
            l_el = item.find("link")
            title = (t_el.text or "").strip() if t_el is not None else ""
            link = (l_el.text or "").strip() if l_el is not None else ""
            if title and link:
                items.append((title[:200], link))
            if len(items) >= max_items:
                return items
        # Atom <entry>
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            t_el = entry.find("{http://www.w3.org/2005/Atom}title")
            l_el = entry.find("{http://www.w3.org/2005/Atom}link")
            title = (t_el.text or "").strip() if t_el is not None else ""
            link = l_el.get("href", "").strip() if l_el is not None else ""
            if title and link:
                items.append((title[:200], link))
            if len(items) >= max_items:
                return items
        if items:
            return items
    except ET.ParseError:
        pass  # fallback to regex

    # regex fallback (깨진 XML, HTML entities 섞인 피드 대응)
    for match in _re.finditer(
        r"<(?:item|entry)\b[^>]*>(.*?)</(?:item|entry)>",
        raw_xml,
        flags=_re.IGNORECASE | _re.DOTALL,
    ):
        chunk = match.group(1)
        tm = _re.search(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", chunk, flags=_re.IGNORECASE | _re.DOTALL)
        lm = _re.search(r"<link[^>]*href=\"([^\"]+)\"", chunk, flags=_re.IGNORECASE)
        if not lm:
            lm = _re.search(r"<link[^>]*>(.*?)</link>", chunk, flags=_re.IGNORECASE | _re.DOTALL)
        title = _re.sub(r"<.*?>", "", (tm.group(1) if tm else "")).strip()
        link = (lm.group(1) if lm else "").strip()
        if title and link:
            items.append((title[:200], link))
        if len(items) >= max_items:
            break
    return items


def _curate_ingest_feeds(*, max_per_feed: int = 3, max_total: int = 5) -> dict[str, Any]:
    """(D) sources.json 에서 새 항목 fetch → 중복 체크 → crawl_url 태스크 enqueue."""
    from urllib import error as urlerror
    from urllib import request as urlrequest

    from app.site import search_closed_notes
    from app.subordinate import enqueue_subordinate_task

    sources = _load_sources()
    if not sources:
        return {"enabled": False, "enqueued": 0, "feeds": 0}

    enqueued = 0
    feeds_processed = 0
    skipped_duplicate = 0
    errors: list[str] = []

    for feed in sources:
        if enqueued >= max_total:
            break
        feeds_processed += 1
        url = str(feed.get("url") or "")
        folder = str(feed.get("folder") or "personal_vault/feeds")
        tags = list(feed.get("tags") or [])
        try:
            req = urlrequest.Request(url, headers={"User-Agent": "OpenAkashic-Sagwan/1.0"})
            with urlrequest.urlopen(req, timeout=15) as resp:
                raw_xml = resp.read().decode("utf-8", errors="replace")
            items = _parse_feed_items(raw_xml, max_items=max_per_feed)
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            errors.append(f"{url}: {exc}")
            continue
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue

        for title, link in items:
            if enqueued >= max_total:
                break
            try:
                hits = search_closed_notes(title, limit=3).get("results", [])
                t_low = title.lower()
                if hits and any(
                    t_low in (h.get("title") or "").lower()
                    or (h.get("title") or "").lower() in t_low
                    for h in hits
                ):
                    skipped_duplicate += 1
                    continue
            except Exception:
                pass
            try:
                enqueue_subordinate_task(
                    kind="crawl_url",
                    payload={"url": link, "folder": folder, "tags": tags, "title_hint": title},
                    created_by="sagwan",
                )
                enqueued += 1
            except RuntimeError as exc:
                # 큐 상한 초과 — 이번 사이클 feed 수급 중단
                errors.append(f"queue_limit: {exc}")
                break
            except Exception as exc:
                errors.append(f"enqueue {link}: {exc}")

    return {
        "enabled": True,
        "feeds": feeds_processed,
        "enqueued": enqueued,
        "skipped_duplicate": skipped_duplicate,
        "errors": errors[:5],
    }


# ─── (E) 사관 주기적 캡슐 생성 ────────────────────────────────────────────────
# 설계: 사관이 최근 피드 수급 + 기존 지식을 묶어 *새 capsule 초안*을 직접 생성한다.
# 단, 자동 공개는 하지 않는다 — 생성된 capsule 은 visibility=private, status=none 으로
# 시작하고 사용자/부사관이 publication_request 를 내야 정상 flow 를 탄다. 자기가 만들고
# 자기가 승인하는 self-approval 은 _evaluate_gates 에서 source frontmatter 를 통해 차단.

_SAGWAN_CAPSULE_FOLDER = "personal_vault/projects/ops/librarian/capsules"
_SAGWAN_CAPSULE_CREATOR = "sagwan"
_CAPSULE_GEN_MAX_PER_CYCLE = 1  # 안전상 사이클당 1개만 생성


def _curate_generate_capsules() -> dict[str, Any]:
    """(E) 최근 크롤된 feed 노트 + 관련 기존 지식을 묶어 사관이 capsule 초안을 직접 작성한다.
    비용 통제를 위해 사이클당 최대 1개만 생성. 생성된 capsule 은 private/none 으로 시작.
    """
    from app.site import search_closed_notes
    from app.vault import list_note_paths, write_document
    from app.subordinate import SUBORDINATE_IDENTITY

    # 1) 최근 크롤된 feed 노트 중 capsule 파생이 아직 없는 것 하나 고름
    candidate_seed = _find_capsule_seed()
    if not candidate_seed:
        return {"generated": 0, "reason": "no_seed_found"}

    seed_path, seed_doc = candidate_seed
    seed_title = str(seed_doc.frontmatter.get("title") or seed_path)
    seed_tags = list(seed_doc.frontmatter.get("tags") or [])

    # 2) 관련 기존 지식 수집 (semantic + lexical 하이브리드는 search_closed_notes 가 처리)
    query = f"{seed_title} {' '.join(str(t) for t in seed_tags[:4])}"
    related_paths: list[tuple[str, str]] = []  # (path, excerpt)
    try:
        results = search_closed_notes(query, limit=6).get("results", [])
        for r in results:
            p = r.get("path") or ""
            if p == seed_path:
                continue
            try:
                d = load_document(p)
                related_paths.append((p, (d.body or "")[:1200]))
            except Exception:
                continue
            if len(related_paths) >= 4:
                break
    except Exception as exc:
        logger.warning("sagwan capsule gen: search failed: %s", exc)

    # 3) 사관 3계층 메모리 컨텍스트
    ctx = before_task_context("sagwan", query, current_note_path=seed_path)

    prompt = _build_capsule_gen_prompt(
        seed_title=seed_title,
        seed_body=(seed_doc.body or "")[:2000],
        related=related_paths,
        memory_snippet=ctx["combined"],
    )

    model = (load_librarian_settings() or {}).get("model") or None
    raw = _invoke_claude_cli(prompt, model=model)
    if not raw or raw.startswith("[CLI 오류"):
        return {"generated": 0, "reason": "llm_error", "detail": raw[:200]}

    # 4) Claim: LLM 응답은 ## Summary / ## Key Points / ## Cautions / ## Sources 포함 마크다운
    #    안전장치: 응답이 너무 짧거나 섹션이 없으면 중단
    if len(raw) < 300 or "## Summary" not in raw:
        return {"generated": 0, "reason": "response_too_weak", "detail": raw[:200]}

    capsule_title = f"{seed_title} Capsule"
    from app.vault import suggest_note_path
    suggested = suggest_note_path("capsule", capsule_title, _SAGWAN_CAPSULE_FOLDER, None, "ops/librarian")
    tags_out = list(dict.fromkeys(["capsule", "sagwan-generated", *seed_tags[:4]]))
    evidence_paths = [seed_path] + [p for p, _ in related_paths[:3]]

    try:
        doc = write_document(
            path=suggested,
            title=capsule_title,
            kind="capsule",
            project="ops/librarian",
            status="draft",
            tags=tags_out,
            related=[seed_title] + [p for p, _ in related_paths[:3]],
            body=raw,
            metadata={
                "visibility": "private",
                "publication_status": "none",
                "owner": SUBORDINATE_IDENTITY.get("nickname", "busagwan"),  # system-owned, not sagwan itself
                "created_by": _SAGWAN_CAPSULE_CREATOR,
                "generated_by": _SAGWAN_CAPSULE_CREATOR,
                "seed_path": seed_path,
                "evidence_paths": evidence_paths,
                "publication_rationale": f"Auto-synthesized by sagwan from seed={seed_path} + {len(related_paths)} related notes. Review before requesting publication.",
            },
            allow_owner_change=True,
        )
    except Exception as exc:
        logger.error("sagwan capsule gen: write failed: %s", exc)
        return {"generated": 0, "reason": "write_failed", "detail": str(exc)}

    # 씨앗 노트에 파생 플래그
    try:
        from app.vault import write_document as _wd
        next_fm = dict(seed_doc.frontmatter)
        next_fm["sagwan_capsule_generated_at"] = _now_iso()
        next_fm["sagwan_generated_capsule_path"] = doc.path
        _wd(path=seed_path, body=seed_doc.body, metadata=next_fm, allow_owner_change=True)
    except Exception:
        pass

    try:
        remember(
            "sagwan",
            subject=f"generated capsule from seed {seed_path}",
            outcome=f"wrote {doc.path}; related={len(related_paths)}",
            kind="capsule_gen",
        )
    except Exception:
        pass
    logger.info("sagwan capsule gen: wrote %s from seed=%s (related=%d)",
                doc.path, seed_path, len(related_paths))
    return {"generated": 1, "path": doc.path, "seed": seed_path, "related": len(related_paths)}


def _find_capsule_seed() -> tuple[str, Any] | None:
    """사관 캡슐 생성 씨앗 후보 탐색.
    우선순위:
      1) personal_vault/feeds/** 하의 노트 중 sagwan_capsule_generated_at 없는 것
      2) personal_vault/knowledge/** 의 raw 노트 (fallback)
    성능: feeds/ 만 스캔하다가 찾으면 즉시 반환 — knowledge/ 는 feeds 가 없을 때만 스캔.
    """
    from app.vault import list_note_paths

    # 1) feeds 우선 탐색
    for path in list_note_paths():
        if not path.startswith("personal_vault/feeds/"):
            continue
        try:
            doc = load_document(path)
        except Exception:
            continue
        fm = doc.frontmatter or {}
        if fm.get("sagwan_capsule_generated_at"):
            continue
        if str(fm.get("kind") or "").lower() == "capsule":
            continue
        if len(doc.body or "") < 400:
            continue
        return path, doc  # 찾으면 즉시 반환

    # 2) knowledge/ fallback (feeds 가 비어있거나 모두 처리된 경우)
    for path in list_note_paths():
        if not path.startswith("personal_vault/knowledge/"):
            continue
        try:
            doc = load_document(path)
        except Exception:
            continue
        fm = doc.frontmatter or {}
        if fm.get("sagwan_capsule_generated_at"):
            continue
        if str(fm.get("kind") or "").lower() == "capsule":
            continue
        if len(doc.body or "") < 400:
            continue
        return path, doc

    return None


def _build_capsule_gen_prompt(*, seed_title: str, seed_body: str,
                               related: list[tuple[str, str]], memory_snippet: str) -> str:
    related_block = "\n\n".join(
        [f"### {p}\n{excerpt[:900]}" for p, excerpt in related[:4]]
    ) or "(관련 노트 없음)"
    return "\n".join([
        "너는 OpenAkashic 의 사관이다. 아래 씨앗 노트와 관련 지식들을 종합해서",
        "*공개 후보가 될 수 있는 capsule 초안*을 마크다운으로 작성하라.",
        "",
        "준칙:",
        "- 과장 금지. 근거 있는 것만 주장.",
        "- 씨앗이 외부 피드이면 소스 링크를 Sources 섹션에 명시.",
        "- Key Points 는 '- ' bullet, 각 80자 이하.",
        "- 최소 섹션: Summary, Key Points, Cautions, Sources.",
        "- 내부 개인정보/비공개 정책 언급 금지.",
        "",
        memory_snippet or "(메모리 없음)",
        "",
        "## 씨앗 노트",
        f"title: {seed_title}",
        seed_body or "(빈 문서)",
        "",
        "## 관련 지식 발췌",
        related_block,
        "",
        "출력은 마크다운 본문만. Frontmatter 금지. YAML 금지. '## Summary' 로 시작하라.",
    ])

