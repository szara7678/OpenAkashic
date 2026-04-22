"""
sagwan_loop.py

사관(sagwan, chief librarian)의 승인/정제 루틴.

설계 이념:
- 사관은 LLM(기본: claude-cli) 로 **지능형 최종 판단**을 내린다.
  규칙 기반 거버넌스 게이트는 *pre-filter* 로만 쓴다 (값싼 필터 + 근거 부재 차단).
  게이트를 통과한 후보만 LLM 에게 물어 approve/defer 를 받는다.
- 루틴은 *배치* 로 동작한다: 주기(기본 10분) OR 대기 요청 수(기본 3건) 도달 시 실행.
- 이 모듈은 `personal_vault/**` 원본 노트를 직접 공개하지 않는다 — 반드시 `kind` 가
  capsule/claim 또는 경로가 `doc/` 이어야 한다.
- 별도 curation cycle 도 제공한다: 원본→capsule 파생 유도, stale 동기화 정리.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    list_note_paths,
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
        "approval_max_per_cycle": 10,  # 한 사이클에서 처리할 승인 요청 상한 (컨텍스트 보호)
        # 사관이 단독 LLM 판정자 — 부사관 1차 리뷰는 폐지되었다.
        "require_subordinate_review": False,
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
        "approval_max_per_cycle": max(
            1, int(raw.get("approval_max_per_cycle") or defaults["approval_max_per_cycle"])
        ),
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
        "approval_max_per_cycle": max(
            1,
            int(payload.get("approval_max_per_cycle") or current["approval_max_per_cycle"]),
        ),
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

    max_per_cycle = int(settings.get("approval_max_per_cycle") or 10)
    batch = pending[:max_per_cycle]
    deferred_for_next_cycle = max(0, len(pending) - len(batch))
    processed: list[dict[str, Any]] = []
    for item in batch:
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

    # 매 배치 종료 후 장기 기억 정제 시도 (임계치 미달이면 자동 skip)
    try:
        after_task("sagwan", llm_invoke=_invoke_claude_cli)
    except Exception as exc:
        logger.debug("sagwan after_task distill skipped: %s", exc)

    published = sum(1 for p in processed if p.get("decision") == "published")
    return {
        "status": "ok",
        "reason": reason,
        "pending_count": len(pending),
        "batch_size": len(batch),
        "deferred_for_next_cycle": deferred_for_next_cycle,
        "published_count": published,
        "deferred_count": sum(1 for p in processed if p.get("decision") == "deferred"),
        "processed": processed,
    }


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
    사관의 정제(큐레이션) 루틴. 다음 단계를 수행한다:
    (B) core_api 재동기화 — published 인데 core_api_id 없음 → sync_to_core_api enqueue
    (C) 재검증 — published capsule/claim 오래된 순으로 사관 LLM 재검토
    (D) 피드 수급 — sources.json 정의된 RSS/arXiv 피드에서 새 항목 → crawl_url enqueue
    (E) 캡슐 생성 — 사관 LLM 이 seed 노트에서 직접 capsule 본문 작성 (과거 draft_capsule 부사관 이관)
    (F) 충돌 판정 — 사관 LLM 이 의미 중복 후보를 판정 (과거 detect_conflicts 부사관 이관)
    (G) signal scans — stale/gap 스캔 태스크 enqueue
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
        f_conflict = _curate_detect_conflicts()
    except Exception as exc:
        logger.error("sagwan curation F (conflict detect) failed: %s", exc)
        f_conflict = {"error": str(exc)}

    try:
        g_signals = _curate_enqueue_signal_scans()
    except Exception as exc:
        logger.error("sagwan curation G (signal scans) failed: %s", exc)
        g_signals = {"error": str(exc)}

    try:
        h_topics = _curate_propose_topics()
    except Exception as exc:
        logger.error("sagwan curation H (topic proposals) failed: %s", exc)
        h_topics = {"error": str(exc)}

    try:
        i_meta = _curate_system_health()
    except Exception as exc:
        logger.error("sagwan curation I (meta) failed: %s", exc)
        i_meta = {"error": str(exc)}

    try:
        distill = distill_memory("sagwan", llm_invoke=_invoke_claude_cli)
    except Exception as exc:
        logger.error("sagwan distill failed: %s", exc)
        distill = {"error": str(exc)}

    summary = {
        "status": "ok", "reason": reason,
        "derive_sync": a, "revalidate": c, "feeds": d,
        "capsule_gen": e, "conflict_detect": f_conflict, "signal_scans": g_signals,
        "topic_proposals": h_topics,
        "meta_curation": i_meta,
        "distill_sagwan": distill,
    }
    try:
        remember(
            "sagwan",
            subject=f"curation cycle ({reason})",
            outcome=(
                f"sync={a.get('sync_enqueued', False)} "
                f"revalidated={c.get('revalidated', 0)}/{c.get('checked', 0)} "
                f"feeds_enqueued={d.get('enqueued', 0)} "
                f"capsules_generated={e.get('generated', 0)} "
                f"conflicts_checked={f_conflict.get('checked', 0)} "
                f"conflicts_flagged={f_conflict.get('flagged', 0)} "
                f"signals_enqueued={g_signals.get('enqueued', 0)} "
                f"topics_status={h_topics.get('status', '?')} "
                f"meta_status={i_meta.get('status', '?')} "
                f"distill_sagwan={distill.get('status')}"
            ),
            kind="curation",
        )
    except Exception as exc:
        logger.warning("sagwan curation memory append failed: %s", exc)
    logger.info("sagwan_loop curation: %s", summary)
    return summary


def _curate_derive_and_sync() -> dict[str, Any]:
    """(B) stale published → sync_to_core_api 워커 태스크 큐잉.

    과거에는 (A) raw note → draft_capsule 를 부사관에게 enqueue 했으나,
    캡슐 생성은 사관이 직접 수행(_curate_generate_capsules, E 단계)으로 이관되어
    이 함수에서는 core_api 동기화 큐잉만 담당한다.
    """
    from app.subordinate import enqueue_subordinate_task

    stale_published_count = 0
    scanned = 0

    for path in list_note_paths():
        scanned += 1
        try:
            doc = load_document(path)
        except Exception:
            continue
        fm = doc.frontmatter or {}
        kind = str(fm.get("kind") or "").lower()
        pub_status = str(fm.get("publication_status") or "").lower()

        if pub_status == "published" and not fm.get("core_api_id") and kind in {"capsule", "claim"}:
            stale_published_count += 1

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
        "drafts_enqueued": 0,  # 사관이 _curate_generate_capsules 에서 직접 생성
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
    """(C) published capsule/claim 를 오래된 순으로 LLM 재검증."""
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
        if str(fm.get("kind") or "").lower() not in {"capsule", "claim"}:
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
            # Busagwan draft_capsule 태스크는 폐기됨(사관으로 이관). 재생성은 후속 curation 단계 또는
            # 사람의 결정에 맡기고, 여기서는 플래그만 남긴다.
            fm["needs_refresh"] = True
            fm["refresh_requested_at"] = _now_iso()
            fm["refresh_reason"] = note[:300]
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


def _curate_detect_conflicts(*, max_per_cycle: int = 3) -> dict[str, Any]:
    """(F) 최근 갱신된 public-bound 캡슐에 대해 의미 중복 후보를 찾고 사관 LLM 으로
    실제 충돌 여부를 판정한다.  부사관에서 이관된 기능이다.

    정책:
    - 대상: kind ∈ {capsule, claim} 이고 publication_status != "rejected" 인 노트 중
      conflict_status 가 비어있거나 "pending_review" 인 것 top-N (updated desc).
    - 후보 수집: semantic_rank 상위 5개 중 score ≥ 0.86 (또는 ≥ 0.74 + 같은 project/tag).
    - 판정: claude-cli 가 CONFLICT | CLEAR 결정.  실패 시 pending_review 로 남김.
    """
    from app.site import SemanticDocument, semantic_rank

    scanned = 0
    checked = 0
    flagged = 0
    errors = 0

    # 대상 노트 수집
    candidates: list[tuple[str, Any]] = []
    for path in list_note_paths():
        try:
            doc = load_document(path)
        except Exception:
            continue
        fm = doc.frontmatter or {}
        kind = str(fm.get("kind") or "").lower()
        if kind not in {"capsule", "claim"}:
            continue
        pub_status = str(fm.get("publication_status") or "").lower()
        if pub_status == "rejected":
            continue
        conflict_status = str(fm.get("conflict_status") or "").lower()
        if conflict_status in {"clear", "flagged"}:
            continue  # 이미 판정됨 (재판정은 별도 trigger)
        candidates.append((path, doc))

    scanned = len(candidates)
    # updated desc 정렬
    def _updated_key(item: tuple[str, Any]) -> str:
        fm = item[1].frontmatter or {}
        return str(fm.get("updated_at") or fm.get("updated") or fm.get("created") or "")
    candidates.sort(key=_updated_key, reverse=True)

    # 전체 vault 로 SemanticDocument 한번만 구성 (비용 절감)
    all_documents: list[SemanticDocument] = []
    doc_by_path: dict[str, Any] = {}
    for p in list_note_paths():
        try:
            d = load_document(p)
        except Exception:
            continue
        fm = d.frontmatter or {}
        all_documents.append(SemanticDocument(
            key=d.path, path=d.path,
            title=str(fm.get("title") or d.path),
            kind=str(fm.get("kind") or "reference"),
            project=str(fm.get("project") or "openakashic"),
            status=str(fm.get("status") or "active"),
            summary=str(fm.get("summary") or ""),
            body=d.body,
        ))
        doc_by_path[d.path] = d

    for source_path, source in candidates[:max_per_cycle]:
        checked += 1
        source_fm = source.frontmatter or {}
        query = "\n".join([
            str(source_fm.get("title") or source_path),
            str(source_fm.get("kind") or ""),
            " ".join(str(t) for t in (source_fm.get("tags") or [])),
            source.body,
        ])
        source_tags = set(str(t) for t in (source_fm.get("tags") or []))
        source_project = str(source_fm.get("project") or "")

        conflict_candidates: list[dict[str, Any]] = []
        for cand_key, score in semantic_rank(query, all_documents, limit=8)[:5]:
            if cand_key == source_path:
                continue
            cand = doc_by_path.get(cand_key)
            if not cand:
                continue
            if score >= 0.86:
                conflict_candidates.append({"path": cand_key, "score": round(float(score), 4)})
            elif score >= 0.74:
                cand_fm = cand.frontmatter or {}
                cand_tags = set(str(t) for t in (cand_fm.get("tags") or []))
                cand_project = str(cand_fm.get("project") or "")
                if (source_tags & cand_tags) or (source_project and source_project == cand_project):
                    conflict_candidates.append({"path": cand_key, "score": round(float(score), 4)})

        next_fm = dict(source_fm)
        if not conflict_candidates:
            next_fm["conflict_candidates"] = []
            next_fm["conflict_status"] = "clear"
            try:
                from app.vault import write_document as _wd
                _wd(path=source_path, body=source.body, metadata=next_fm, allow_owner_change=True)
            except Exception as exc:
                logger.warning("conflict detect: write clear failed for %s: %s", source_path, exc)
                errors += 1
            continue

        # LLM 판정
        snippet_block = "\n---\n".join(
            f"Path: {cc['path']} (score={cc['score']})\n{doc_by_path[cc['path']].body[:600]}"
            for cc in conflict_candidates[:3] if cc['path'] in doc_by_path
        )
        prompt = "\n\n".join([
            "너는 OpenAkashic 사관이다. 소스 노트와 후보들이 실제로 모순되는지 판정한다.",
            f"소스 ({source_path}):\n{source.body[:1500]}",
            f"후보:\n{snippet_block}",
            "같은 주제라는 이유만으로 충돌이 아니다. 서로 다른 주장이어야 충돌이다.",
            "출력:\nVerdict: <CONFLICT|CLEAR>\nReason:\n- ...",
        ])
        model = (load_librarian_settings() or {}).get("model") or None
        reply = _invoke_claude_cli(prompt, model=model)
        import re as _re
        # Verdict 라인은 **bold** 마크업이 섞일 수 있으므로 별표/공백을 관대하게 처리
        # 허용 예: "Verdict: CLEAR", "**Verdict: CLEAR**", "**Verdict:** CLEAR", "Verdict: **CLEAR**"
        m = _re.search(
            r"^[\s\*#>\-]*Verdict:[\s\*`_]*(CONFLICT|CLEAR)\b",
            reply,
            _re.MULTILINE | _re.IGNORECASE,
        )
        if not m or reply.startswith("[CLI 오류"):
            logger.warning(
                "conflict detect: verdict parse failed for %s. reply[:400]=%r",
                source_path,
                (reply or "")[:400],
            )
            next_fm["conflict_candidates"] = conflict_candidates
            next_fm["conflict_status"] = "pending_review"
            errors += 1
        elif m.group(1).upper() == "CONFLICT":
            next_fm["conflict_candidates"] = conflict_candidates
            next_fm["conflict_status"] = "flagged"
            flagged += 1
        else:
            next_fm["conflict_candidates"] = conflict_candidates
            next_fm["conflict_status"] = "clear"

        try:
            from app.vault import write_document as _wd
            _wd(path=source_path, body=source.body, metadata=next_fm, allow_owner_change=True)
        except Exception as exc:
            logger.warning("conflict detect: write verdict failed for %s: %s", source_path, exc)
            errors += 1

    return {"scanned": scanned, "checked": checked, "flagged": flagged, "errors": errors}


def _curate_enqueue_signal_scans() -> dict[str, Any]:
    """(G) 순수-코드 신호 감지 태스크들을 주기적으로 워커(부사관) 큐에 넣는다.
    이 태스크들은 LLM 을 쓰지 않는 집계/시간 산술이므로 워커 실행이 적합하다.
    """
    from app.subordinate import enqueue_subordinate_task, list_subordinate_tasks

    # 동일 태스크가 pending/running 상태로 이미 있으면 중복 큐잉 방지
    live_kinds = {
        str(t.get("kind") or "")
        for t in list_subordinate_tasks()
        if str(t.get("status") or "") in {"pending", "running"}
    }

    enqueued: list[str] = []

    if "analyze_search_gaps" not in live_kinds:
        try:
            enqueue_subordinate_task(
                kind="analyze_search_gaps",
                payload={"max_new": 10},
                created_by="sagwan",
            )
            enqueued.append("analyze_search_gaps")
        except Exception as exc:
            logger.warning("signal scan: gap enqueue failed: %s", exc)

    if "scan_stale_private_notes" not in live_kinds:
        # owner=aaron 기본 — 필요 시 known owners 확장
        try:
            enqueue_subordinate_task(
                kind="scan_stale_private_notes",
                payload={"owner": "aaron", "dry_run": False},
                created_by="sagwan",
            )
            enqueued.append("scan_stale_private_notes:aaron")
        except Exception as exc:
            logger.warning("signal scan: stale enqueue failed: %s", exc)

    return {"enqueued": len(enqueued), "kinds": enqueued}


# ─── (H) 사관 주제 자율 선정 ─────────────────────────────────────────────────
# 설계: 고정 피드(arxiv cs.CL, HN)만으로는 관심 영역 확장 불가. 사관이 직접 관심 주제
# 3개를 제안하고, 각 주제를 arxiv/Google News 검색 URL 로 변환해 피드 수급과 동일한
# 방식으로 크롤을 enqueue 한다. 24시간에 한 번만 실행 (claude-cli 비용 절약).

_TOPIC_STATE_PATH = "personal_vault/projects/ops/librarian/activity/topic-proposals.md"
_TOPIC_MIN_INTERVAL_HOURS = 24


def _curate_propose_topics() -> dict[str, Any]:
    """(H) 사관이 직접 관심 주제를 선정하고 arxiv/Google News 검색 피드로 크롤 enqueue."""
    from app.vault import write_document, load_document as _ld

    # 1) 쿨다운 확인
    state_fm: dict[str, Any] = {}
    state_body = ""
    try:
        state_doc = _ld(_TOPIC_STATE_PATH)
        state_fm = dict(state_doc.frontmatter or {})
        state_body = state_doc.body or ""
    except Exception:
        pass

    last_run = str(state_fm.get("last_run_at") or "").strip()
    if last_run:
        try:
            last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
            if datetime.now(UTC) - last_dt < timedelta(hours=_TOPIC_MIN_INTERVAL_HOURS):
                return {"status": "cooldown", "next_run_after": last_run}
        except Exception:
            pass

    # 2) 컨텍스트 수집: 최근 gap 쿼리 + distilled 메모리
    gap_summary = ""
    try:
        from app.vault import list_note_paths
        for p in list_note_paths():
            if p.startswith("doc/knowledge-gaps/") and p.endswith(".md"):
                try:
                    d = _ld(p)
                    gap_summary += f"- {d.frontmatter.get('title','?')}\n"
                except Exception:
                    continue
                if gap_summary.count("\n") >= 10:
                    break
    except Exception:
        pass

    ctx = before_task_context("sagwan", "research topic proposal", current_note_path=None)

    # 3) LLM 에게 주제 제안 요청
    prompt = "\n\n".join([
        "너는 OpenAkashic 사관이다. 다음 24시간 동안 수집할 연구 주제 3개를 제안한다.",
        "선정 기준:",
        "- 최근 gap queries 와 사관 기억(특히 반복적으로 언급된 영역)에 닿을 것",
        "- 너무 광범위하지 말 것 (예: 'AI' X, 'retrieval-augmented generation for code X')",
        "- 서로 겹치지 않을 것",
        "",
        f"## 최근 gap queries\n{gap_summary or '(없음)'}",
        "",
        ctx["combined"] or "",
        "",
        "출력 형식 (엄격):",
        "TOPIC 1: <5-12 단어의 영어 검색 쿼리>",
        "TOPIC 2: <...>",
        "TOPIC 3: <...>",
    ])

    model = (load_librarian_settings() or {}).get("model") or None
    reply = _invoke_claude_cli(prompt, model=model)
    if not reply or reply.startswith("[CLI 오류"):
        return {"status": "llm_error", "detail": (reply or "")[:200]}

    import re as _re
    topics: list[str] = []
    for m in _re.finditer(r"^\s*TOPIC\s*\d+\s*:\s*(.+?)\s*$", reply, _re.MULTILINE | _re.IGNORECASE):
        q = m.group(1).strip().strip("`*_\"'")
        if 3 <= len(q) <= 200:
            topics.append(q)
    topics = topics[:3]
    if not topics:
        return {"status": "parse_error", "detail": reply[:200]}

    # 4) 각 주제를 arxiv 검색 피드로 변환 → 아이템 파싱 → crawl_url enqueue
    from urllib import error as urlerror
    from urllib import parse as urlparse_
    from urllib import request as urlrequest
    from app.site import search_closed_notes
    from app.subordinate import enqueue_subordinate_task

    total_enqueued = 0
    per_topic: list[dict[str, Any]] = []
    for q in topics:
        qs = urlparse_.quote_plus(q)
        feed_url = (
            f"http://export.arxiv.org/api/query?search_query=all:{qs}"
            "&sortBy=submittedDate&sortOrder=descending&max_results=3"
        )
        items: list[tuple[str, str]] = []
        try:
            req = urlrequest.Request(feed_url, headers={"User-Agent": "OpenAkashic-Sagwan/1.0"})
            with urlrequest.urlopen(req, timeout=15) as resp:
                raw_xml = resp.read().decode("utf-8", errors="replace")
            items = _parse_feed_items(raw_xml, max_items=3)
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            per_topic.append({"topic": q, "error": str(exc), "enqueued": 0})
            continue
        except Exception as exc:
            per_topic.append({"topic": q, "error": str(exc), "enqueued": 0})
            continue

        enq = 0
        for title, link in items:
            try:
                hits = search_closed_notes(title, limit=3).get("results", [])
                t_low = title.lower()
                if hits and any(
                    t_low in (h.get("title") or "").lower()
                    or (h.get("title") or "").lower() in t_low
                    for h in hits
                ):
                    continue
            except Exception:
                pass
            try:
                enqueue_subordinate_task(
                    kind="crawl_url",
                    payload={
                        "url": link,
                        "folder": "personal_vault/feeds",
                        "tags": ["sagwan-topic-proposal"],
                        "title_hint": title,
                    },
                    created_by="sagwan",
                )
                enq += 1
                total_enqueued += 1
            except Exception as exc:
                per_topic.append({"topic": q, "error": f"enqueue {link}: {exc}", "enqueued": enq})
                break
        per_topic.append({"topic": q, "enqueued": enq})

    # 5) state 업데이트
    now_iso = _now_iso()
    state_fm_next = {
        **state_fm,
        "title": "Sagwan Topic Proposals (Activity Log)",
        "kind": "activity",
        "project": "ops/librarian",
        "status": "active",
        "tags": ["sagwan", "activity", "topic-proposal"],
        "visibility": "private",
        "owner": "sagwan",
        "last_run_at": now_iso,
    }
    new_body = (state_body or "## 최근 주제 제안\n\n").rstrip() + "\n\n"
    new_body += f"### {now_iso}\n"
    for item in per_topic:
        mark = item.get("error") or f"enqueued={item.get('enqueued', 0)}"
        new_body += f"- **{item['topic']}** — {mark}\n"
    try:
        write_document(path=_TOPIC_STATE_PATH, body=new_body, metadata=state_fm_next, allow_owner_change=True)
    except Exception as exc:
        logger.warning("topic proposals: state write failed: %s", exc)

    return {
        "status": "ok",
        "topics": topics,
        "enqueued": total_enqueued,
        "per_topic": per_topic,
    }


# ─── (I) 사관 메타 큐레이션 + 자율 개선 요청 ────────────────────────────────
# 설계: 매 24시간마다 운영 데이터(실패한 busagwan 태스크, 반복 gap, 충돌 pending_review,
# 최근 distilled 메모리)를 분석해 시스템/지식 개선점을 claude-cli 로 도출한다.
# 산출물은 2종류:
#   1) 시스템 헬스 리포트: personal_vault/meta/system-health/YYYY-MM-DD.md
#   2) 개선 요청 노트:    personal_vault/meta/improvement-requests/<slug>.md
#      - status=proposed. 실제 코드 수정은 사람(insu)이 리뷰 후 적용.
#      - 사관은 직접 코드 파일을 수정하지 않는다 (안전 경계).

_META_STATE_PATH = "personal_vault/projects/ops/librarian/activity/meta-curation.md"
_META_MIN_INTERVAL_HOURS = 24
_SYSTEM_HEALTH_FOLDER = "personal_vault/meta/system-health"
_IMPROVEMENT_REQUEST_FOLDER = "personal_vault/meta/improvement-requests"


def _curate_system_health() -> dict[str, Any]:
    """(I) 24시간 1회. 운영 데이터 분석 → 헬스 리포트 + 개선 요청 노트 작성."""
    from app.vault import write_document, load_document as _ld
    from app.subordinate import list_subordinate_tasks

    # 1) 쿨다운
    state_fm: dict[str, Any] = {}
    try:
        state_doc = _ld(_META_STATE_PATH)
        state_fm = dict(state_doc.frontmatter or {})
    except Exception:
        pass
    last_run = str(state_fm.get("last_run_at") or "").strip()
    if last_run:
        try:
            last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
            if datetime.now(UTC) - last_dt < timedelta(hours=_META_MIN_INTERVAL_HOURS):
                return {"status": "cooldown", "next_run_after": last_run}
        except Exception:
            pass

    # 2) 운영 시그널 수집
    tasks = list_subordinate_tasks()
    failed_recent = [t for t in tasks if t.get("status") == "failed"][-20:]
    failure_sample = "\n".join(
        f"- {t.get('kind')} @ {t.get('finished_at') or t.get('created_at')}: {(t.get('last_error') or '')[:150]}"
        for t in failed_recent[-10:]
    ) or "(없음)"

    pending_conflicts: list[str] = []
    try:
        from app.vault import list_note_paths
        for p in list_note_paths():
            try:
                d = _ld(p)
            except Exception:
                continue
            fm = d.frontmatter or {}
            if fm.get("conflict_status") in {"pending_review", "flagged"}:
                pending_conflicts.append(f"- {p} [{fm.get('conflict_status')}]")
            if len(pending_conflicts) >= 10:
                break
    except Exception:
        pass
    conflicts_sample = "\n".join(pending_conflicts) or "(없음)"

    gap_sample: list[str] = []
    try:
        from app.vault import list_note_paths as _lnp
        for p in _lnp():
            if p.startswith("doc/knowledge-gaps/") and p.endswith(".md"):
                try:
                    d = _ld(p)
                    gap_sample.append(f"- {d.frontmatter.get('title','?')}")
                except Exception:
                    continue
                if len(gap_sample) >= 10:
                    break
    except Exception:
        pass
    gap_block = "\n".join(gap_sample) or "(없음)"

    ctx = before_task_context("sagwan", "system health meta-curation", current_note_path=None)

    # 3) LLM 분석
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    prompt = "\n\n".join([
        "너는 OpenAkashic 사관이다. 지난 24시간 운영 데이터를 보고 시스템/지식 개선점을 도출한다.",
        "결과는 두 부분:",
        "A) 한 줄 헬스 요약 (## HEALTH 섹션)",
        "B) 0~3개의 개선 요청 (## IMPROVEMENTS 섹션, 각 항목은 다음 형식):",
        "",
        "### <짧은 영문 slug (파일명용, 3-6 단어 kebab-case)>",
        "- kind: `code` | `knowledge` | `policy` | `data`",
        "- priority: `low` | `medium` | `high`",
        "- summary: <한 문장 한국어>",
        "- rationale: <2-4 문장. 위 운영 데이터의 어떤 패턴을 근거로 제안하는지 명시>",
        "- proposal: <구체적 변경안. code 면 수정 대상 파일/함수까지. 직접 코드는 쓰지 말 것.>",
        "- risk: <적용 시 예상 위험 1-2 문장>",
        "",
        f"## 최근 실패 태스크 샘플\n{failure_sample}",
        "",
        f"## 미해결 충돌 샘플\n{conflicts_sample}",
        "",
        f"## 최근 gap queries\n{gap_block}",
        "",
        ctx["combined"] or "",
        "",
        "형식을 반드시 지켜라. 불필요한 서두 금지.",
    ])

    model = (load_librarian_settings() or {}).get("model") or None
    reply = _invoke_claude_cli(prompt, model=model)
    if not reply or reply.startswith("[CLI 오류"):
        return {"status": "llm_error", "detail": (reply or "")[:200]}

    # 4) 헬스 리포트 저장
    health_path = f"{_SYSTEM_HEALTH_FOLDER}/{today}.md"
    try:
        write_document(
            path=health_path,
            body=reply,
            metadata={
                "title": f"System Health {today}",
                "kind": "activity",
                "project": "ops/librarian",
                "status": "active",
                "tags": ["meta", "system-health", "sagwan-generated"],
                "visibility": "private",
                "owner": "sagwan",
                "created_at": _now_iso(),
            },
            allow_owner_change=True,
        )
    except Exception as exc:
        logger.warning("meta curation: health write failed: %s", exc)

    # 5) 개선 요청 파싱 후 각각 별도 노트로 저장
    import re as _re
    section_match = _re.search(r"##\s*IMPROVEMENTS\s*\n(.*)", reply, _re.DOTALL | _re.IGNORECASE)
    requests_created: list[str] = []
    if section_match:
        body_section = section_match.group(1)
        # 각 ### <slug> 블록 추출
        for m in _re.finditer(
            r"^###\s+([a-z0-9][a-z0-9\-]{2,80})\s*\n(.*?)(?=^###\s+|\Z)",
            body_section,
            _re.MULTILINE | _re.DOTALL | _re.IGNORECASE,
        ):
            slug = m.group(1).strip().lower()
            block = m.group(2).strip()
            # 중복 slug 방지: 이미 존재하면 skip
            req_path = f"{_IMPROVEMENT_REQUEST_FOLDER}/{slug}.md"
            try:
                _ld(req_path)
                continue  # 이미 있음
            except Exception:
                pass
            # priority/kind 추출 (간단 파싱)
            kind_m = _re.search(r"kind:\s*`?(\w+)`?", block)
            prio_m = _re.search(r"priority:\s*`?(\w+)`?", block)
            try:
                write_document(
                    path=req_path,
                    body=block,
                    metadata={
                        "title": f"Improvement Request: {slug}",
                        "kind": "improvement-request",
                        "project": "ops/librarian",
                        "status": "proposed",
                        "tags": [
                            "meta",
                            "improvement-request",
                            "sagwan-generated",
                            (kind_m.group(1) if kind_m else "unknown"),
                            (prio_m.group(1) if prio_m else "unknown"),
                        ],
                        "visibility": "private",
                        "owner": "sagwan",
                        "created_at": _now_iso(),
                        "review_status": "pending_human_review",
                    },
                    allow_owner_change=True,
                )
                requests_created.append(slug)
            except Exception as exc:
                logger.warning("meta curation: request write failed for %s: %s", slug, exc)

    # 6) state 업데이트
    now_iso = _now_iso()
    try:
        write_document(
            path=_META_STATE_PATH,
            body=f"최근 실행: {now_iso}\n생성된 개선 요청: {len(requests_created)}건\n"
            + ("- " + "\n- ".join(requests_created) if requests_created else "(없음)"),
            metadata={
                **state_fm,
                "title": "Meta Curation Activity Log",
                "kind": "activity",
                "project": "ops/librarian",
                "status": "active",
                "tags": ["sagwan", "activity", "meta-curation"],
                "visibility": "private",
                "owner": "sagwan",
                "last_run_at": now_iso,
            },
            allow_owner_change=True,
        )
    except Exception as exc:
        logger.warning("meta curation: state write failed: %s", exc)

    return {
        "status": "ok",
        "health_path": health_path,
        "requests_created": requests_created,
    }


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
