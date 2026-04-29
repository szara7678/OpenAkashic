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
import re
import time
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
from app.librarian import (
    _invoke_claude_cli,
    _invoke_claude_cli_with_tools,
    _invoke_proxy_chat,
    load_librarian_settings,
)
from app.vault import (
    PUBLICATION_REQUEST_FOLDER,
    append_section,
    list_note_paths,
    list_publication_requests,
    load_document,
    set_publication_status,
    suggest_note_path,
    write_document,
)

logger = logging.getLogger(__name__)

_SAGWAN_STAGE_MODEL_DEFAULTS = {
    "research": "claude-cli:claude-sonnet-4-6",
    "maintenance": "claude-cli:claude-sonnet-4-6",
    "conflict": "proxy:gpt-5.4",
    "publication_judge": "proxy:gpt-5.4",
    "revalidate": "proxy:gpt-5.4",
    "distill": "proxy:gpt-5.4-mini",
    "topic_proposal": "proxy:gpt-5.4",
    "meta_curation": "proxy:gpt-5.4",
    "profile_update": "proxy:gpt-5.4",
}
_LLM_CALL_HISTORY: list[dict[str, Any]] = []

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
        "research_enabled": True,
        "research_interval_sec": 7200,   # 2시간
        "research_max_fetches": 3,
        "consolidate_enabled": True,
        "consolidate_interval_sec": 21600,  # 6시간
        "consolidate_min_reviews": 3,
        "bench_enabled": False,
        "bench_interval_sec": 604800,  # 1주
        "bench_model": "",
        "maintenance_enabled": True,
        "maintenance_interval_sec": 1800,
        "stage_models": dict(_SAGWAN_STAGE_MODEL_DEFAULTS),
        "llm_call_hourly_cap": 50,
        "llm_call_ceiling_action": "skip_stage",
        "distill_min_interval_sec": 21600,
        "distill_min_episodes": 5,
        "profile_update_min_interval_hours": 24,
        "topic_min_interval_hours": 12,
        "meta_min_interval_hours": 12,
    }


def _normalize_stage_models(raw: Any, defaults: dict[str, str]) -> dict[str, str]:
    merged = dict(defaults)
    if isinstance(raw, dict):
        for key, value in raw.items():
            stage = str(key or "").strip()
            chosen = str(value or "").strip()
            if stage and chosen and ":" in chosen:
                merged[stage] = chosen
    return merged


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
        "research_enabled": bool(raw.get("research_enabled", defaults["research_enabled"])),
        "research_interval_sec": min(
            86400,
            max(1800, int(raw.get("research_interval_sec") or defaults["research_interval_sec"])),
        ),
        "research_max_fetches": min(
            6,
            max(1, int(raw.get("research_max_fetches") or defaults["research_max_fetches"])),
        ),
        "maintenance_enabled": bool(raw.get("maintenance_enabled", defaults["maintenance_enabled"])),
        "maintenance_interval_sec": min(
            86400,
            max(1800, int(raw.get("maintenance_interval_sec") or defaults["maintenance_interval_sec"])),
        ),
        "stage_models": _normalize_stage_models(raw.get("stage_models"), defaults["stage_models"]),
        "llm_call_hourly_cap": min(
            500,
            max(1, int(raw.get("llm_call_hourly_cap") or defaults["llm_call_hourly_cap"])),
        ),
        "llm_call_ceiling_action": str(raw.get("llm_call_ceiling_action") or defaults["llm_call_ceiling_action"]).strip()
        or defaults["llm_call_ceiling_action"],
        "distill_min_interval_sec": min(
            86400,
            max(1800, int(raw.get("distill_min_interval_sec") or defaults["distill_min_interval_sec"])),
        ),
        "distill_min_episodes": min(
            50,
            max(1, int(raw.get("distill_min_episodes") or defaults["distill_min_episodes"])),
        ),
        "profile_update_min_interval_hours": min(
            168,
            max(1, int(raw.get("profile_update_min_interval_hours") or defaults["profile_update_min_interval_hours"])),
        ),
        "consolidate_enabled": bool(raw.get("consolidate_enabled", defaults["consolidate_enabled"])),
        "consolidate_interval_sec": min(
            86400,
            max(1800, int(raw.get("consolidate_interval_sec") or defaults["consolidate_interval_sec"])),
        ),
        "consolidate_min_reviews": min(
            20,
            max(2, int(raw.get("consolidate_min_reviews") or defaults["consolidate_min_reviews"])),
        ),
        "bench_enabled": bool(raw.get("bench_enabled", defaults["bench_enabled"])),
        "bench_interval_sec": min(
            2592000,
            max(86400, int(raw.get("bench_interval_sec") or defaults["bench_interval_sec"])),
        ),
        "bench_model": str(raw.get("bench_model") or defaults["bench_model"]).strip(),
        "topic_min_interval_hours": min(
            168,
            max(1, int(raw.get("topic_min_interval_hours") or defaults["topic_min_interval_hours"])),
        ),
        "meta_min_interval_hours": min(
            168,
            max(1, int(raw.get("meta_min_interval_hours") or defaults["meta_min_interval_hours"])),
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
        "research_enabled": bool(payload.get("research_enabled", current["research_enabled"])),
        "research_interval_sec": min(
            86400,
            max(1800, int(payload.get("research_interval_sec") or current["research_interval_sec"])),
        ),
        "research_max_fetches": min(
            6,
            max(1, int(payload.get("research_max_fetches") or current["research_max_fetches"])),
        ),
        "maintenance_enabled": bool(payload.get("maintenance_enabled", current["maintenance_enabled"])),
        "maintenance_interval_sec": min(
            86400,
            max(1800, int(payload.get("maintenance_interval_sec") or current["maintenance_interval_sec"])),
        ),
        "stage_models": _normalize_stage_models(payload.get("stage_models"), current["stage_models"]),
        "llm_call_hourly_cap": min(
            500,
            max(1, int(payload.get("llm_call_hourly_cap") or current["llm_call_hourly_cap"])),
        ),
        "llm_call_ceiling_action": str(payload.get("llm_call_ceiling_action") or current["llm_call_ceiling_action"]).strip()
        or current["llm_call_ceiling_action"],
        "distill_min_interval_sec": min(
            86400,
            max(1800, int(payload.get("distill_min_interval_sec") or current["distill_min_interval_sec"])),
        ),
        "distill_min_episodes": min(
            50,
            max(1, int(payload.get("distill_min_episodes") or current["distill_min_episodes"])),
        ),
        "profile_update_min_interval_hours": min(
            168,
            max(1, int(payload.get("profile_update_min_interval_hours") or current["profile_update_min_interval_hours"])),
        ),
        "consolidate_enabled": bool(payload.get("consolidate_enabled", current["consolidate_enabled"])),
        "consolidate_interval_sec": min(
            86400,
            max(1800, int(payload.get("consolidate_interval_sec") or current["consolidate_interval_sec"])),
        ),
        "consolidate_min_reviews": min(
            20,
            max(2, int(payload.get("consolidate_min_reviews") or current["consolidate_min_reviews"])),
        ),
        "bench_enabled": bool(payload.get("bench_enabled", current["bench_enabled"])),
        "bench_interval_sec": min(
            2592000,
            max(86400, int(payload.get("bench_interval_sec") or current["bench_interval_sec"])),
        ),
        "bench_model": str(payload.get("bench_model") or current["bench_model"]).strip(),
        "topic_min_interval_hours": min(
            168,
            max(1, int(payload.get("topic_min_interval_hours") or current["topic_min_interval_hours"])),
        ),
        "meta_min_interval_hours": min(
            168,
            max(1, int(payload.get("meta_min_interval_hours") or current["meta_min_interval_hours"])),
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


class StageRateLimitExceeded(RuntimeError):
    def __init__(self, stage: str) -> None:
        super().__init__(f"sagwan hourly LLM cap exceeded for stage={stage}")
        self.stage = stage


def _web_tools_list() -> list[str]:
    return [
        "WebSearch",
        "WebFetch",
        "Read",
        "mcp__openakashic__search_akashic",
        "mcp__openakashic__search_notes",
        "mcp__openakashic__read_note",
        "mcp__openakashic__read_raw_note",
        "mcp__openakashic__list_reviews",
    ]


def _record_llm_call(stage: str, backend: str, model: str, *, duration_s: float, response_text: str) -> None:
    _LLM_CALL_HISTORY.append(
        {
            "ts": _now_iso(),
            "stage": stage,
            "backend": backend,
            "model": model,
            "duration_s": round(float(duration_s), 3),
            "estimated_tokens": max(1, len(response_text or "") // 4),
        }
    )


def _recent_llm_calls(*, since: timedelta) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - since
    fresh: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for event in _LLM_CALL_HISTORY:
        event_dt = _parse_iso_datetime(str(event.get("ts") or ""))
        if event_dt is None:
            continue
        if event_dt >= cutoff - timedelta(hours=24):
            kept.append(event)
        if event_dt >= cutoff:
            fresh.append(event)
    if len(kept) != len(_LLM_CALL_HISTORY):
        _LLM_CALL_HISTORY[:] = kept
    return fresh


def _check_rate_limit(stage: str) -> None:
    settings = load_sagwan_settings()
    cap = int(settings.get("llm_call_hourly_cap") or 50)
    ceiling_action = str(settings.get("llm_call_ceiling_action") or "skip_stage").strip().lower()
    if ceiling_action not in {"skip_stage", "queue_to_next_cycle", "warn_only"}:
        ceiling_action = "skip_stage"
    current_hour_calls = len(_recent_llm_calls(since=timedelta(hours=1)))
    if current_hour_calls < cap:
        return
    if ceiling_action == "warn_only":
        logger.warning("sagwan llm cap exceeded but continuing: stage=%s cap=%d", stage, cap)
        return
    raise StageRateLimitExceeded(stage)


def _invoke_for_stage(stage: str, prompt: str, *, web_tools: bool = False, system: str | None = None) -> str:
    settings = load_sagwan_settings()
    stage_models = settings.get("stage_models") or {}
    default_choice = "claude-cli:claude-sonnet-4-6" if web_tools else "proxy:gpt-5.4"
    chosen = str(stage_models.get(stage) or default_choice).strip()
    if ":" not in chosen:
        chosen = default_choice
    backend, model = chosen.split(":", 1)
    backend = backend.strip()
    model = model.strip()
    _check_rate_limit(stage)
    started = time.monotonic()
    if backend == "claude-cli":
        result = _invoke_claude_cli_with_tools(prompt, model=model or None, tools=_web_tools_list() if web_tools else [])
    else:
        result = _invoke_proxy_chat(prompt, model=model or "gpt-5.4", system=system)
    _record_llm_call(stage, backend, model or "", duration_s=time.monotonic() - started, response_text=result)
    return result


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

def run_sagwan_research_cycle(*, reason: str = "manual", force: bool = False) -> dict[str, Any]:
    try:
        result = _curate_research_gaps(force=force)
        if reason:
            result = {**result, "reason": reason}
        return result
    except Exception as exc:
        logger.error("sagwan research cycle failed: %s", exc)
        return {"status": "error", "detail": str(exc), "reason": reason}


def run_sagwan_consolidation_cycle(*, reason: str = "manual", force: bool = False) -> dict[str, Any]:
    try:
        result = _curate_consolidate_reviews(force=force)
        if reason:
            result = {**result, "reason": reason}
        return result
    except Exception as exc:
        logger.error("sagwan consolidation cycle failed: %s", exc)
        return {"status": "error", "detail": str(exc), "reason": reason}


def _curate_run_bench(settings: dict[str, Any]) -> dict[str, Any]:
    from app.bench_scheduled import trigger_full_bench_run_async

    return trigger_full_bench_run_async(
        reason="scheduled:sagwan-curation",
        force=False,
        settings=settings,
        tasks_file="tasks.yaml",
        k=1,
        model=str(settings.get("bench_model") or "").strip() or None,
    )


def run_sagwan_curation_cycle(*, reason: str = "scheduled") -> dict[str, Any]:
    """
    사관의 정제(큐레이션) 루틴. 다음 단계를 수행한다:
    (B) core_api 재동기화 — published 인데 core_api_id 없음 → sync_to_core_api enqueue
    (C) 재검증 — published capsule/claim 오래된 순으로 사관 LLM 재검토
    (D) 레거시 피드 수급 — deprecated no-op
    (E) 캡슐 생성 — 사관 LLM 이 seed 노트에서 직접 capsule 본문 작성 (과거 draft_capsule 부사관 이관)
    (F) 충돌 판정 — 사관 LLM 이 의미 중복 후보를 판정 (과거 detect_conflicts 부사관 이관)
    (G) signal scans — stale/gap 스캔 태스크 enqueue
    (H) 연구 토픽 제안 — 주제만 제안/기록 (자동 crawl 없음)
    (K) gap-driven research — 사관이 WebSearch/WebFetch 로 직접 리서치 capsule 초안 생성
    (L) review consolidation — 누적 리뷰를 uphold/revise/supersede 로 정리
    """
    settings = load_sagwan_settings()

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
        k_research = _curate_research_gaps()
    except Exception as exc:
        logger.error("sagwan curation K (research gaps) failed: %s", exc)
        k_research = {"error": str(exc)}

    try:
        l_consolidate = _curate_consolidate_reviews()
    except Exception as exc:
        logger.error("sagwan curation L (consolidate reviews) failed: %s", exc)
        l_consolidate = {"error": str(exc)}

    try:
        m_maintenance = _curate_maintenance()
    except Exception as exc:
        logger.error("sagwan curation M (maintenance) failed: %s", exc)
        m_maintenance = {"error": str(exc)}

    if settings.get("bench_enabled"):
        try:
            m_bench = _curate_run_bench(settings)
        except Exception as exc:
            logger.error("sagwan curation bench trigger failed: %s", exc)
            m_bench = {"error": str(exc)}
    else:
        m_bench = {"status": "disabled"}

    try:
        distill = _maybe_distill_sagwan()
    except Exception as exc:
        logger.error("sagwan distill failed: %s", exc)
        distill = {"error": str(exc)}

    summary = {
        "status": "ok", "reason": reason,
        "derive_sync": a, "revalidate": c, "feeds": d,
        "capsule_gen": e, "conflict_detect": f_conflict, "signal_scans": g_signals,
        "topic_proposals": h_topics,
        "meta_curation": i_meta,
        "research_gaps": k_research,
        "consolidate_reviews": l_consolidate,
        "maintenance": m_maintenance,
        "bench": m_bench,
        "distill_sagwan": distill,
    }
    try:
        _write_llm_telemetry_cycle(summary)
    except Exception as exc:
        logger.warning("sagwan telemetry write failed: %s", exc)
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
                f"research_status={k_research.get('status', '?')} "
                f"research_capsule={k_research.get('capsule_path', '-')} "
                f"consolidate={l_consolidate.get('verdict', l_consolidate.get('status', '?'))} "
                f"maintenance={m_maintenance.get('verdict', m_maintenance.get('status', '?'))} "
                f"bench={m_bench.get('status', '?')} "
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
        targets = str(fm.get("targets") or "").strip()

        if pub_status == "published" and not targets and not fm.get("core_api_id") and kind in {"capsule", "claim"}:
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
    from app.mcp_server import _post_internal_review

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
    cycle_date = datetime.now(UTC).date().isoformat()

    for path in targets:
        checked += 1
        try:
            doc = load_document(path)
        except Exception:
            continue
        fm = dict(doc.frontmatter or {})
        prompt = _build_revalidation_prompt(path, fm, doc.body or "")
        try:
            raw = _invoke_for_stage("revalidate", prompt)
        except StageRateLimitExceeded:
            return {
                "status": "rate_limit_skipped",
                "checked": checked - 1,
                "revalidated": ok,
                "stale": stale,
                "refresh_enqueued": refresh,
                "results": results,
            }
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
        try:
            if verdict in {"stale", "refresh"}:
                _post_internal_review(
                    target=path,
                    stance="dispute",
                    rationale=(
                        f"Sagwan revalidation ({cycle_date} cycle) flagged this capsule as stale or inaccurate: "
                        f"{note[:1500]}"
                    ),
                    topic="sagwan-revalidation",
                )
            elif verdict == "ok":
                _post_internal_review(
                    target=path,
                    stance="support",
                    rationale=(
                        "Sagwan revalidation cycle confirmed this capsule still matches current sources. "
                        f"Sampled freshness date: {fm.get('freshness_date') or '(none)'}."
                    ),
                    topic="sagwan-revalidation",
                )
        except Exception as exc:
            logger.warning("sagwan revalidation: review_note posting failed for %s: %s", path, exc)
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
    """(D) legacy RSS/arXiv ingest path is deprecated and intentionally no-ops."""
    return {
        "status": "deprecated",
        "note": "replaced by _curate_research_gaps in stage K",
        "feeds": 0,
        "enqueued": 0,
    }


# ─── (E) 사관 주기적 캡슐 생성 ────────────────────────────────────────────────
# 설계: 사관이 최근 피드 수급 + 기존 지식을 묶어 *새 capsule 초안*을 직접 생성한다.
# 단, 자동 공개는 하지 않는다 — 생성된 capsule 은 visibility=private, status=none 으로
# 시작하고 사용자/부사관이 publication_request 를 내야 정상 flow 를 탄다. 자기가 만들고
# 자기가 승인하는 self-approval 은 _evaluate_gates 에서 source frontmatter 를 통해 차단.

_SAGWAN_CAPSULE_FOLDER = "personal_vault/projects/ops/librarian/capsules"
_SAGWAN_CAPSULE_CREATOR = "sagwan"
_CAPSULE_GEN_MAX_PER_CYCLE = 1  # 안전상 사이클당 1개만 생성
_RESEARCH_LOG_PATH = "personal_vault/projects/ops/librarian/activity/research-log.md"
_CONSOLIDATION_LOG_PATH = "personal_vault/projects/ops/librarian/activity/consolidation-log.md"
_MAINTENANCE_LOG_PATH = "personal_vault/projects/ops/librarian/activity/maintenance-log.md"
_LLM_TELEMETRY_LOG_PATH = "personal_vault/projects/ops/librarian/activity/llm-telemetry.md"
_MAINTENANCE_QUEUE_SIZE = 1
_LIBRARIAN_PREFIX = "personal_vault/projects/ops/librarian/"


def _parse_iso_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _extract_json_dict(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        payload = json.loads(raw[start:end + 1])
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _topic_slug(value: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", str(value or "").strip()).strip("-").lower()
    return slug[:60] or "research-gap"


def _inventory_knowledge_state() -> dict[str, Any]:
    now = datetime.now(UTC)
    clusters: dict[str, dict[str, Any]] = {}
    recent_gap_queries: list[dict[str, Any]] = []
    total_capsules = 0
    total_claims = 0

    for path in list_note_paths():
        try:
            doc = load_document(path)
        except Exception:
            continue
        fm = dict(doc.frontmatter or {})
        kind = str(fm.get("kind") or "").strip().lower()
        tags = [str(tag).strip() for tag in (fm.get("tags") or []) if str(tag).strip()]
        if kind == "capsule":
            total_capsules += 1
        elif kind == "claim":
            total_claims += 1

        if path.startswith("doc/knowledge-gaps/"):
            gap_query = str(fm.get("gap_query") or fm.get("title") or Path(path).stem).strip()
            recent_gap_queries.append(
                {
                    "query": gap_query,
                    "miss_count": int(fm.get("miss_count") or 0),
                    "last_queried": str(fm.get("last_queried") or fm.get("updated_at") or ""),
                    "path": path,
                }
            )

        if not tags:
            tags = ["untagged"]
        freshness_anchor = (
            _parse_iso_datetime(str(fm.get("freshness_date") or ""))
            or _parse_iso_datetime(str(fm.get("updated_at") or ""))
            or _parse_iso_datetime(str(fm.get("created_at") or ""))
        )
        age_days = None
        if freshness_anchor is not None:
            age_days = max(0.0, (now - freshness_anchor).total_seconds() / 86400.0)

        for tag in tags:
            cluster = clusters.setdefault(
                tag,
                {
                    "tag": tag,
                    "note_count": 0,
                    "capsule_count": 0,
                    "claim_count": 0,
                    "total_body_chars": 0,
                    "freshness_ages": [],
                },
            )
            cluster["note_count"] += 1
            cluster["total_body_chars"] += len(doc.body or "")
            if kind == "capsule":
                cluster["capsule_count"] += 1
            elif kind == "claim":
                cluster["claim_count"] += 1
            if age_days is not None:
                cluster["freshness_ages"].append(age_days)

    tag_clusters: list[dict[str, Any]] = []
    for item in clusters.values():
        note_count = max(1, int(item["note_count"]))
        ages = [float(age) for age in item.get("freshness_ages") or []]
        tag_clusters.append(
            {
                "tag": item["tag"],
                "note_count": int(item["note_count"]),
                "capsule_count": int(item["capsule_count"]),
                "claim_count": int(item["claim_count"]),
                "avg_body_chars": round(float(item["total_body_chars"]) / note_count, 1),
                "avg_freshness_age_days": round(sum(ages) / len(ages), 1) if ages else None,
            }
        )

    top_thin: list[dict[str, Any]] = []
    for cluster in tag_clusters:
        reasons: list[str] = []
        knowledge_count = int(cluster["capsule_count"]) + int(cluster["claim_count"])
        if knowledge_count == 0:
            reasons.append("no_capsules_or_claims")
        elif knowledge_count <= 2:
            reasons.append("few_capsules_or_claims")
        if float(cluster["avg_body_chars"] or 0) < 700:
            reasons.append("shallow_notes")
        age_days = cluster.get("avg_freshness_age_days")
        if age_days is not None and float(age_days) > 120:
            reasons.append("stale_cluster")
        if reasons:
            top_thin.append(
                {
                    "tag": cluster["tag"],
                    "reason": ", ".join(reasons),
                    "note_count": cluster["note_count"],
                    "capsule_count": cluster["capsule_count"],
                    "claim_count": cluster["claim_count"],
                    "avg_body_chars": cluster["avg_body_chars"],
                    "avg_freshness_age_days": age_days,
                }
            )

    tag_clusters.sort(
        key=lambda item: (
            int(item["capsule_count"]) + int(item["claim_count"]),
            int(item["note_count"]),
            float(item["avg_body_chars"] or 0),
        )
    )
    top_thin.sort(
        key=lambda item: (
            -len(str(item.get("reason") or "").split(",")),
            int(item.get("capsule_count") or 0) + int(item.get("claim_count") or 0),
            int(item.get("note_count") or 0),
        )
    )
    recent_gap_queries.sort(
        key=lambda item: (
            str(item.get("last_queried") or ""),
            int(item.get("miss_count") or 0),
        ),
        reverse=True,
    )

    return {
        "tag_clusters": tag_clusters[:30],
        "top_thin": top_thin[:10],
        "total_capsules": total_capsules,
        "total_claims": total_claims,
        "recent_gap_queries": recent_gap_queries[:10],
    }


def _build_gap_selection_prompt(
    inventory: dict[str, Any],
    memory_snippet: str,
) -> str:
    top_thin = inventory.get("top_thin") or []
    gap_queries = inventory.get("recent_gap_queries") or []
    inventory_block = json.dumps(
        {
            "total_capsules": inventory.get("total_capsules", 0),
            "total_claims": inventory.get("total_claims", 0),
            "top_thin": top_thin[:8],
            "recent_gap_queries": gap_queries[:8],
        },
        ensure_ascii=False,
        indent=2,
    )
    return "\n\n".join(
        [
            "너는 OpenAkashic 사관이다. 지식 인벤토리를 보고 지금 가장 얇고 가치 있는 연구 공백 하나를 고른다.",
            "선정 기준:",
            "- 이미 충분히 두꺼운 태그 군집은 피한다.",
            "- 최근 gap query 와 연결되거나, capsule/claim 이 부족하거나, 오래된 군집을 우선한다.",
            "- 검색 쿼리는 실제 웹 검색에 바로 쓸 수 있게 구체적으로 쓴다.",
            "- broad topic 금지. implementation / architecture / failure mode 같이 재사용 가능한 주제를 고른다.",
            "",
            "반드시 JSON 객체만 출력하라. 설명 금지.",
            '{"topic":"...","queries":["q1","q2","q3"],"rationale":"...","target_capsule_title":"..."}',
            "",
            "## 인벤토리",
            inventory_block,
            "",
            "## 최근 사관 기억",
            memory_snippet or "(없음)",
        ]
    )


def _parse_gap_selection(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None

    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    brace = re.search(r"(\{.*\})", text, re.DOTALL)
    if brace:
        candidates.append(brace.group(1).strip())

    parsed: dict[str, Any] | None = None
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            parsed = payload
            break

    if parsed is None:
        topic_match = re.search(r"topic\s*[:=]\s*(.+)", text, re.IGNORECASE)
        rationale_match = re.search(r"rationale\s*[:=]\s*(.+)", text, re.IGNORECASE)
        title_match = re.search(r"target_capsule_title\s*[:=]\s*(.+)", text, re.IGNORECASE)
        query_lines = re.findall(r"query(?:ies)?\s*[:=]\s*(.+)", text, re.IGNORECASE)
        parsed = {
            "topic": topic_match.group(1).strip().strip('"\'' ) if topic_match else "",
            "queries": query_lines,
            "rationale": rationale_match.group(1).strip().strip('"\'' ) if rationale_match else "",
            "target_capsule_title": title_match.group(1).strip().strip('"\'' ) if title_match else "",
        }

    topic = str(parsed.get("topic") or "").strip()
    raw_queries = parsed.get("queries")
    if isinstance(raw_queries, str):
        queries = [
            item.strip().strip('"\'' )
            for item in re.split(r"[,\n;]+", raw_queries)
            if item.strip()
        ]
    elif isinstance(raw_queries, list):
        queries = [str(item).strip().strip('"\'' ) for item in raw_queries if str(item).strip()]
    else:
        queries = []
    rationale = str(parsed.get("rationale") or "").strip()
    target_capsule_title = str(parsed.get("target_capsule_title") or "").strip()

    if not topic or not queries:
        return None
    cleaned_queries = list(dict.fromkeys(query for query in queries if len(query) >= 3))[:5]
    if not cleaned_queries:
        return None

    return {
        "topic": topic,
        "queries": cleaned_queries,
        "rationale": rationale[:500],
        "target_capsule_title": target_capsule_title[:200],
    }


def _build_research_prompt(gap: dict[str, Any], *, require_web_citations: bool = False) -> str:
    queries = gap.get("queries") or []
    max_fetches = int(gap.get("max_fetches") or 3)
    lines = [
        "너는 OpenAkashic 사관이다. 공개 웹을 조사해 private capsule 초안을 작성한다.",
        "반드시 WebSearch 를 먼저 사용하고, 검색 결과 중 신뢰 가능한 공개 URL만 고른다.",
        f"WebFetch 는 전체 합계 최대 {max_fetches}회까지만 사용한다. 그 이상 fetch 하지 마라.",
        "과장 금지. 확인되지 않은 내용은 Cautions 에 적어라.",
        "최종 출력은 마크다운 본문만 작성하고, 반드시 아래 섹션을 포함한다:",
        "## Summary",
        "## Key Points",
        "## Cautions",
        "## Sources",
        "Sources 섹션에는 사용한 각 URL을 bullet 로 명시하라.",
        "",
        f"## Topic\n{gap.get('topic')}",
        "",
        "## Search Queries",
        *[f"- {query}" for query in queries],
    ]
    if require_web_citations:
        lines[1:1] = [
            "이번 시도는 재검증이다. 반드시 WebSearch 와 WebFetch 를 실제로 호출해 웹 근거를 확보하라.",
            "웹에서 확인한 URL이 Sources 섹션에 1개도 없으면 이 답변은 거부된다.",
        ]
    if gap.get("rationale"):
        lines.extend(["", "## Why This Gap Matters", str(gap.get("rationale"))])
    return "\n".join(lines)


def _build_dedup_check_prompt(gap: dict[str, Any]) -> str:
    return "\n".join(
        [
            "너는 OpenAkashic 사관이다. 새 capsule을 쓰기 전 기존 지식과의 겹침을 검사한다.",
            "",
            "제안된 주제:",
            f"- topic: {gap.get('topic')}",
            f"- queries: {json.dumps(gap.get('queries') or [], ensure_ascii=False)}",
            f"- rationale: {str(gap.get('rationale') or '').strip() or '(none)'}",
            "",
            "제공된 도구:",
            "- mcp__openakashic__search_akashic(query: str) — 검증된 public capsule 검색",
            "- mcp__openakashic__search_notes(query: str) — 전체 vault 검색 (private 포함)",
            "- mcp__openakashic__read_note(path: str) — 특정 노트 본문 읽기",
            "",
            "판정 형식 (JSON 한 줄):",
            '- {"verdict":"proceed","rationale":"..."}',
            '- {"verdict":"skip","rationale":"...","existing_path":"..."}',
            '- {"verdict":"refine","new_topic":"...","new_queries":["...","..."],"rationale":"..."}',
            '- {"verdict":"supplement","extend_path":"...","rationale":"..."}',
            "",
            "총 도구 호출은 4-7회 이내로 제한하라. 최종 출력은 JSON만 작성한다.",
        ]
    )


def _parse_dedup_decision(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    fallback = {"verdict": "proceed", "rationale": ""}
    if not text:
        return fallback

    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    brace = re.search(r"(\{.*\})", text, re.DOTALL)
    if brace:
        candidates.append(brace.group(1).strip())

    payload: dict[str, Any] | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payload = parsed
            break

    if payload is None:
        verdict_match = re.search(r'"?verdict"?\s*[:=]\s*"?(proceed|skip|refine|supplement)"?', text, re.IGNORECASE)
        if not verdict_match:
            return fallback
        payload = {"verdict": verdict_match.group(1).lower()}

    verdict = str(payload.get("verdict") or "").strip().lower()
    if verdict not in {"proceed", "skip", "refine", "supplement"}:
        return fallback

    raw_new_queries = payload.get("new_queries")
    if isinstance(raw_new_queries, list):
        new_queries = [str(item).strip() for item in raw_new_queries if str(item).strip()]
    elif isinstance(raw_new_queries, str):
        new_queries = [item.strip() for item in re.split(r"[,\n;]+", raw_new_queries) if item.strip()]
    else:
        new_queries = []

    decision: dict[str, Any] = {
        "verdict": verdict,
        "rationale": str(payload.get("rationale") or "").strip()[:600],
    }
    if verdict == "skip":
        decision["existing_path"] = str(payload.get("existing_path") or "").strip()
    elif verdict == "supplement":
        decision["extend_path"] = str(payload.get("extend_path") or "").strip()
    elif verdict == "refine":
        decision["new_topic"] = str(payload.get("new_topic") or "").strip()
        decision["new_queries"] = list(dict.fromkeys(new_queries))[:5]
    return decision


def _extract_source_urls(capsule_body: str) -> list[str]:
    body = str(capsule_body or "")
    match = re.search(r"^##\s+Sources\s*$([\s\S]*)", body, re.IGNORECASE | re.MULTILINE)
    if not match:
        return []
    section = match.group(1)
    urls = re.findall(r"https?://[^\s)>\"'`]+", section)
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        cleaned = url.rstrip(".,;:!?`")
        if cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def _research_response_is_usable(raw_capsule: str) -> bool:
    text = str(raw_capsule or "")
    return len(text) >= 400 and "## Summary" in text and "## Sources" in text


def _ensure_research_log_document() -> None:
    try:
        load_document(_RESEARCH_LOG_PATH)
        return
    except Exception:
        pass
    write_document(
        path=_RESEARCH_LOG_PATH,
        title="Sagwan Research Log",
        kind="reference",
        project="ops/librarian",
        status="active",
        tags=["sagwan", "activity", "research-gap"],
        body="\n".join(
            [
                "## Summary",
                "Sagwan gap-driven research history. Frontmatter `last_run_at` is the stage-K cooldown anchor.",
            ]
        ),
        metadata={"visibility": "private", "publication_status": "none", "owner": "sagwan"},
        allow_owner_change=True,
    )


def _append_research_log_entry(
    *,
    topic: str,
    queries: list[str],
    rationale: str,
    cited_urls: list[str],
    capsule_path: str | None,
    model: str,
    max_fetches: int,
    status: str = "ok",
    existing_path: str | None = None,
    grounding: str | None = None,
    retry_count: int = 0,
) -> None:
    _ensure_research_log_document()
    ts = _now_iso()
    append_section(
        _RESEARCH_LOG_PATH,
        f"{ts} research-gap",
        "\n".join(
            [
                f"- topic: {topic}",
                f"- queries: {json.dumps(queries, ensure_ascii=False)}",
                f"- rationale: {rationale or '(none)'}",
                f"- model: {model or '-'}",
                f"- max_fetches: {max_fetches}",
                f"- status: {status}",
                f"- capsule_path: {capsule_path or '-'}",
                f"- existing_path: {existing_path or '-'}",
                f"- grounding: {grounding or '-'}",
                f"- retry_count: {retry_count}",
                f"- cited_urls: {json.dumps(cited_urls, ensure_ascii=False)}",
            ]
        ),
    )


def _touch_research_state(now_iso: str) -> None:
    _ensure_research_log_document()
    doc = load_document(_RESEARCH_LOG_PATH)
    next_frontmatter = dict(doc.frontmatter or {})
    next_frontmatter["last_run_at"] = now_iso
    write_document(
        path=_RESEARCH_LOG_PATH,
        body=doc.body,
        metadata=next_frontmatter,
        allow_owner_change=True,
    )


def _ensure_consolidation_log_document() -> None:
    try:
        load_document(_CONSOLIDATION_LOG_PATH)
        return
    except Exception:
        pass
    write_document(
        path=_CONSOLIDATION_LOG_PATH,
        title="Sagwan Consolidation Log",
        kind="reference",
        project="ops/librarian",
        status="active",
        tags=["sagwan", "activity", "review-consolidation"],
        body="\n".join(
            [
                "## Summary",
                "Sagwan review consolidation history. Frontmatter `last_run_at` is the stage-L cooldown anchor.",
            ]
        ),
        metadata={"visibility": "private", "publication_status": "none", "owner": "sagwan"},
        allow_owner_change=True,
    )


def _build_consolidation_prompt(*, capsule: Any, reviews: list[Any]) -> str:
    title = str(capsule.frontmatter.get("title") or capsule.path)
    kind = str(capsule.frontmatter.get("kind") or "capsule").strip().lower()
    review_blocks: list[str] = []
    for index, review in enumerate(reviews, start=1):
        review_blocks.append(
            "\n".join(
                [
                    f"### Review {index}",
                    f"- path: {review.path}",
                    f"- stance: {review.stance or 'neutral'}",
                    f"- owner: {review.owner or '-'}",
                    f"- topic: {review.topic or '-'}",
                    f"- rationale: {_review_rationale_text(review.body)}",
                    f"- evidence_urls: {json.dumps(review.evidence_urls or [], ensure_ascii=False)}",
                    f"- evidence_paths: {json.dumps(review.evidence_paths or [], ensure_ascii=False)}",
                ]
            )
        )
    return "\n\n".join(
        [
            "너는 OpenAkashic 사관이다. 부모 캡슐/클레임과 누적 리뷰를 읽고 통합 결론을 내린다.",
            "판단 규칙:",
            "- 리뷰가 대부분 support 이고 사실 반박이 없으면 uphold.",
            "- dispute 포인트가 타당하고 현재 본문에 흡수 가능하면 revise.",
            "- 문서가 근본적으로 틀렸거나 시대에 뒤처져 새 버전이 낫다면 supersede.",
            "- support/neutral 만 많다는 이유로 새 버전을 만들지 마라.",
            "- revise 또는 supersede 일 때만 NEW_TITLE / NEW_BODY 를 작성한다.",
            "- NEW_BODY 는 반드시 아래 섹션을 포함한다: ## Summary / ## Key Points / ## Cautions / ## Sources",
            "",
            "출력 형식:",
            "VERDICT: uphold | revise | supersede",
            "RATIONALE: <한국어 한두 문장>",
            "NEW_TITLE: <선택, revise|supersede일 때>",
            "NEW_BODY:",
            "## Summary",
            "...",
            "## Key Points",
            "...",
            "## Cautions",
            "...",
            "## Sources",
            "...",
            "",
            f"## Parent Note",
            f"path: {capsule.path}",
            f"title: {title}",
            f"kind: {kind}",
            "",
            "## Parent Body",
            str(capsule.body or "").strip() or "(empty)",
            "",
            "## Reviews",
            "\n\n".join(review_blocks) or "(no reviews)",
        ]
    )


def _parse_consolidation_decision(raw: str) -> dict[str, str] | None:
    text = str(raw or "").strip()
    if not text:
        return None

    verdict_match = re.search(r"^\s*VERDICT\s*:\s*(uphold|revise|supersede)\s*$", text, re.IGNORECASE | re.MULTILINE)
    if not verdict_match:
        return None
    verdict = verdict_match.group(1).strip().lower()

    rationale_match = re.search(
        r"^\s*RATIONALE\s*:\s*(.+?)(?=^\s*(?:NEW_TITLE|NEW_BODY|VERDICT)\s*:|\Z)",
        text,
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    new_title_match = re.search(
        r"^\s*NEW_TITLE\s*:\s*(.+?)(?=^\s*(?:NEW_BODY|RATIONALE|VERDICT)\s*:|\Z)",
        text,
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    new_body_match = re.search(r"^\s*NEW_BODY\s*:\s*(.*)\Z", text, re.IGNORECASE | re.MULTILINE | re.DOTALL)

    rationale = (rationale_match.group(1).strip() if rationale_match else "")[:2000]
    new_title = (new_title_match.group(1).strip() if new_title_match else "")[:240]
    new_body = new_body_match.group(1).strip() if new_body_match else ""

    return {
        "verdict": verdict,
        "rationale": rationale,
        "new_title": new_title,
        "new_body": new_body,
    }


def _mark_review_consolidated(review_path: str, *, cycle_id: str) -> None:
    review_doc = load_document(review_path)
    next_frontmatter = dict(review_doc.frontmatter or {})
    next_frontmatter["claim_review_lifecycle"] = "consolidated"
    next_frontmatter["claim_review_cycle_id"] = cycle_id
    next_frontmatter["claim_review_consolidated_at"] = _now_iso()
    write_document(
        path=review_path,
        body=review_doc.body,
        metadata=next_frontmatter,
        metadata_replace=False,
        allow_owner_change=True,
    )


def _mark_review_active(review_path: str) -> None:
    review_doc = load_document(review_path)
    next_frontmatter = dict(review_doc.frontmatter or {})
    next_frontmatter["claim_review_lifecycle"] = "active"
    next_frontmatter["claim_review_cycle_id"] = None
    next_frontmatter["claim_review_consolidated_at"] = None
    write_document(
        path=review_path,
        body=review_doc.body,
        metadata=next_frontmatter,
        metadata_replace=False,
        allow_owner_change=True,
    )


def _touch_parent_consolidation(parent_path: str, now_iso: str, verdict: str) -> None:
    parent_doc = load_document(parent_path)
    next_frontmatter = dict(parent_doc.frontmatter or {})
    next_frontmatter["last_consolidated_at"] = now_iso
    next_frontmatter["last_consolidation_verdict"] = verdict
    write_document(
        path=parent_path,
        body=parent_doc.body,
        metadata=next_frontmatter,
        metadata_replace=False,
        allow_owner_change=True,
    )


def _write_revised_capsule(old_doc: Any, new_body: str, now_iso: str) -> None:
    next_frontmatter = dict(old_doc.frontmatter or {})
    next_frontmatter["last_consolidated_at"] = now_iso
    next_frontmatter["last_consolidation_verdict"] = "revise"
    next_frontmatter["revision_count"] = int(next_frontmatter.get("revision_count") or 0) + 1
    write_document(
        path=old_doc.path,
        body=new_body,
        metadata=next_frontmatter,
        metadata_replace=False,
        allow_owner_change=True,
    )


def _write_superseding_capsule(*, old_doc: Any, new_title: str, new_body: str, now_iso: str) -> str:
    old_frontmatter = dict(old_doc.frontmatter or {})
    old_kind = str(old_frontmatter.get("kind") or "capsule").strip().lower() or "capsule"
    target_path = suggest_note_path(old_kind, new_title, _SAGWAN_CAPSULE_FOLDER, None, "ops/librarian")
    if target_path == old_doc.path:
        target_path = suggest_note_path(
            old_kind,
            f"{new_title} {now_iso[:10]}",
            _SAGWAN_CAPSULE_FOLDER,
            None,
            "ops/librarian",
        )
    try:
        load_document(target_path)
    except Exception:
        pass
    else:
        target_path = suggest_note_path(
            old_kind,
            f"{new_title} {now_iso[:10]}",
            _SAGWAN_CAPSULE_FOLDER,
            None,
            "ops/librarian",
        )

    related = [str(item) for item in (old_frontmatter.get("related") or []) if str(item).strip()]
    if old_doc.path not in related:
        related.append(old_doc.path)

    new_doc = write_document(
        path=target_path,
        title=new_title,
        kind=old_kind,
        project=str(old_frontmatter.get("project") or "ops/librarian"),
        status=str(old_frontmatter.get("status") or "active"),
        tags=[str(item) for item in (old_frontmatter.get("tags") or []) if str(item).strip()],
        related=related,
        body=new_body,
        metadata={
            "visibility": "private",
            "publication_status": "none",
            "owner": "sagwan",
            "generated_by": "sagwan",
            "supersedes": old_doc.path,
            "revision_count": 1,
            "last_consolidated_at": now_iso,
            "last_consolidation_verdict": "supersede",
        },
        allow_owner_change=True,
    )
    return new_doc.path


def _mark_parent_superseded_by(old_path: str, new_path: str, now_iso: str) -> None:
    old_doc = load_document(old_path)
    next_frontmatter = dict(old_doc.frontmatter or {})
    next_frontmatter["superseded_by"] = new_path
    next_frontmatter["claim_review_status"] = "superseded"
    next_frontmatter["last_consolidated_at"] = now_iso
    next_frontmatter["last_consolidation_verdict"] = "supersede"
    write_document(
        path=old_path,
        body=old_doc.body,
        metadata=next_frontmatter,
        metadata_replace=False,
        allow_owner_change=True,
    )


def _append_consolidation_log_entry(
    *,
    target: str,
    verdict: str,
    review_count: int,
    rationale: str,
    new_path: str | None,
    model: str,
) -> None:
    _ensure_consolidation_log_document()
    ts = _now_iso()
    lines = [
        f"- target: {target}",
        f"- verdict: {verdict}",
        f"- review_count: {review_count}",
        f"- rationale: {rationale or '(none)'}",
        f"- model: {model or '-'}",
    ]
    if new_path:
        lines.append(f"- new_path: {new_path}")
    append_section(
        _CONSOLIDATION_LOG_PATH,
        f"{ts} consolidate-reviews",
        "\n".join(lines),
    )


def _touch_consolidation_state(now_iso: str) -> None:
    _ensure_consolidation_log_document()
    doc = load_document(_CONSOLIDATION_LOG_PATH)
    next_frontmatter = dict(doc.frontmatter or {})
    next_frontmatter["last_run_at"] = now_iso
    write_document(
        path=_CONSOLIDATION_LOG_PATH,
        body=doc.body,
        metadata=next_frontmatter,
        allow_owner_change=True,
    )


def _review_rationale_text(body: str) -> str:
    text = str(body or "").strip()
    if text.startswith("## Rationale"):
        text = text[len("## Rationale"):].strip()
    return text[:2000]


def _curate_consolidate_reviews(force: bool = False) -> dict[str, Any]:
    from app.mcp_server import _recompute_parent_aggregate
    from app.site import _load_targeted_claims_for

    settings = load_sagwan_settings()
    if not settings.get("consolidate_enabled", True):
        return {"status": "disabled"}

    _ensure_consolidation_log_document()
    state_doc = load_document(_CONSOLIDATION_LOG_PATH)
    state = dict(state_doc.frontmatter or {})
    last_run_at = str(state.get("last_run_at") or "").strip()
    interval_sec = int(settings.get("consolidate_interval_sec") or 21600)
    if last_run_at and not force:
        last_dt = _parse_iso_datetime(last_run_at)
        if last_dt is not None:
            next_allowed = last_dt + timedelta(seconds=interval_sec)
            if datetime.now(UTC) < next_allowed:
                return {
                    "status": "cooldown",
                    "last_run_at": last_run_at,
                    "next_run_after": next_allowed.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                }

    min_reviews = int(settings.get("consolidate_min_reviews") or 3)
    candidates: list[dict[str, Any]] = []
    for path in list_note_paths():
        if not path.startswith("personal_vault/"):
            continue
        try:
            doc = load_document(path)
        except Exception:
            continue
        frontmatter = dict(doc.frontmatter or {})
        kind = str(frontmatter.get("kind") or "").strip().lower()
        if kind not in {"capsule", "claim"}:
            continue
        if str(frontmatter.get("targets") or "").strip():
            continue
        if str(frontmatter.get("claim_review_status") or "").strip().lower() in {"superseded", "merged"}:
            continue
        active_reviews = _load_targeted_claims_for(path)
        if len(active_reviews) < min_reviews:
            continue
        candidates.append(
            {
                "path": path,
                "doc": doc,
                "reviews": active_reviews,
                "last_consolidated_at": str(frontmatter.get("last_consolidated_at") or ""),
            }
        )

    if not candidates:
        return {"status": "no_candidates", "min_reviews": min_reviews}

    candidates.sort(key=lambda item: (item["last_consolidated_at"] or "", -len(item["reviews"])))
    picked = candidates[0]
    prompt = _build_consolidation_prompt(capsule=picked["doc"], reviews=picked["reviews"])
    try:
        raw = _invoke_for_stage("consolidate_reviews", prompt)
    except StageRateLimitExceeded:
        return {"status": "rate_limit_skipped", "target": picked["path"]}
    decision = _parse_consolidation_decision(raw)
    if not decision:
        return {"status": "llm_parse_error", "raw": raw[:500], "target": picked["path"]}

    verdict = decision["verdict"]
    now_iso = _now_iso()
    cycle_id = f"L-{now_iso}"
    new_path: str | None = None

    for review in picked["reviews"]:
        _mark_review_consolidated(review.path, cycle_id=cycle_id)

    if verdict == "uphold":
        _touch_parent_consolidation(picked["path"], now_iso, verdict)
    elif verdict == "revise":
        new_body = str(decision.get("new_body") or "")
        if len(new_body) < 400 or "## Summary" not in new_body:
            for review in picked["reviews"]:
                _mark_review_active(review.path)
            return {"status": "revise_too_weak", "raw": raw[:300], "target": picked["path"]}
        _write_revised_capsule(picked["doc"], new_body, now_iso)
    elif verdict == "supersede":
        new_body = str(decision.get("new_body") or "")
        if len(new_body) < 400 or "## Summary" not in new_body:
            for review in picked["reviews"]:
                _mark_review_active(review.path)
            return {"status": "supersede_too_weak", "raw": raw[:300], "target": picked["path"]}
        old_title = str(picked["doc"].frontmatter.get("title") or picked["path"])
        new_title = str(decision.get("new_title") or f"{old_title} (v2)")
        new_path = _write_superseding_capsule(
            old_doc=picked["doc"],
            new_title=new_title,
            new_body=new_body,
            now_iso=now_iso,
        )
        _mark_parent_superseded_by(picked["path"], new_path, now_iso)
    else:
        for review in picked["reviews"]:
            _mark_review_active(review.path)
        return {"status": "unknown_verdict", "verdict": verdict, "target": picked["path"]}

    _append_consolidation_log_entry(
        target=picked["path"],
        verdict=verdict,
        review_count=len(picked["reviews"]),
        rationale=str(decision.get("rationale") or ""),
        new_path=new_path,
        model="stage-routed",
    )
    _touch_consolidation_state(now_iso)
    _recompute_parent_aggregate(picked["path"])
    if new_path:
        _recompute_parent_aggregate(new_path)
    result = {
        "status": "ok",
        "verdict": verdict,
        "target": picked["path"],
        "review_count": len(picked["reviews"]),
        "rationale": str(decision.get("rationale") or ""),
    }
    if new_path:
        result["new_path"] = new_path
    return result


def _curate_research_gaps(force: bool = False) -> dict[str, Any]:
    settings = load_sagwan_settings()
    if not settings.get("research_enabled", True):
        return {"status": "disabled"}

    _ensure_research_log_document()
    state_doc = load_document(_RESEARCH_LOG_PATH)
    state = dict(state_doc.frontmatter or {})
    last_run_at = str(state.get("last_run_at") or "").strip()
    interval_sec = int(settings.get("research_interval_sec") or 14400)
    if last_run_at and not force:
        last_dt = _parse_iso_datetime(last_run_at)
        if last_dt is not None:
            next_allowed = last_dt + timedelta(seconds=interval_sec)
            if datetime.now(UTC) < next_allowed:
                return {
                    "status": "cooldown",
                    "last_run_at": last_run_at,
                    "next_run_after": next_allowed.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                }

    inventory = _inventory_knowledge_state()
    memory = before_task_context("sagwan", "research gap selection", current_note_path=None, total_chars=2400)
    memory_snippet = "\n\n".join(
        block for block in [memory.get("distilled", ""), recent_memory_tail("sagwan", max_sections=4, char_budget=1000)] if block
    )
    selection_prompt = _build_gap_selection_prompt(inventory, memory_snippet)
    try:
        raw_selection = _invoke_for_stage("research_selection", selection_prompt)
    except StageRateLimitExceeded:
        return {"status": "rate_limit_skipped"}
    gap = _parse_gap_selection(raw_selection)
    if not gap:
        return {"status": "llm_parse_error", "raw": raw_selection[:500]}

    dedup_raw = _invoke_claude_cli_with_tools(
        _build_dedup_check_prompt(gap),
        model="claude-sonnet-4-6",
        tools=[
            "mcp__openakashic__search_akashic",
            "mcp__openakashic__search_notes",
            "mcp__openakashic__read_note",
        ],
        timeout=180,
    )
    dedup_decision = _parse_dedup_decision(dedup_raw)
    if dedup_decision["verdict"] == "skip":
        now_iso = _now_iso()
        existing_path = str(dedup_decision.get("existing_path") or "").strip() or None
        rationale = str(dedup_decision.get("rationale") or "")
        _append_research_log_entry(
            topic=gap["topic"],
            queries=gap["queries"],
            rationale=rationale or str(gap.get("rationale") or ""),
            cited_urls=[],
            capsule_path=None,
            model=str(model or ""),
            max_fetches=int(settings.get("research_max_fetches") or 3),
            status="skipped_duplicate",
            existing_path=existing_path,
        )
        _touch_research_state(now_iso)
        return {
            "status": "skip_existing_coverage",
            "existing_path": existing_path,
            "rationale": rationale,
            "gap": gap,
        }
    if dedup_decision["verdict"] == "refine":
        prior_topic = str(gap.get("topic") or "").strip()
        new_topic = str(dedup_decision.get("new_topic") or "").strip()
        new_queries = [str(item).strip() for item in (dedup_decision.get("new_queries") or []) if str(item).strip()]
        if new_topic:
            gap["topic"] = new_topic
            current_title = str(gap.get("target_capsule_title") or "").strip()
            if not current_title or current_title == f"{prior_topic} Capsule":
                gap["target_capsule_title"] = f"{new_topic} Capsule"
        if new_queries:
            gap["queries"] = list(dict.fromkeys(new_queries))[:5]
    elif dedup_decision["verdict"] == "supplement":
        extend_path = str(dedup_decision.get("extend_path") or "").strip()
        if extend_path:
            gap["supplement_extend_path"] = extend_path

    gap["topic_slug"] = _topic_slug(gap["topic"])
    gap["max_fetches"] = int(settings.get("research_max_fetches") or 3)

    try:
        raw_capsule = _invoke_for_stage("research", _build_research_prompt(gap), web_tools=True)
    except StageRateLimitExceeded:
        return {"status": "rate_limit_skipped", "gap": gap}
    if not raw_capsule or raw_capsule.startswith("[CLI 오류"):
        return {"status": "llm_error", "detail": (raw_capsule or "")[:200], "gap": gap}

    final_capsule = raw_capsule
    cited_urls = _extract_source_urls(final_capsule)
    retry_attempted = False
    retry_count = 0
    grounding = "web_grounded"
    if not cited_urls and gap["max_fetches"] > 0:
        retry_attempted = True
        retry_count = 1
        try:
            retry_capsule = _invoke_for_stage("research", _build_research_prompt(gap, require_web_citations=True), web_tools=True)
        except StageRateLimitExceeded:
            retry_capsule = ""
        if retry_capsule and not retry_capsule.startswith("[CLI 오류") and _research_response_is_usable(retry_capsule):
            final_capsule = retry_capsule
            cited_urls = _extract_source_urls(final_capsule)
        if not cited_urls:
            grounding = "training_only"
    if not _research_response_is_usable(final_capsule):
        return {"status": "response_too_weak", "detail": final_capsule[:200], "gap": gap}
    capsule_title = str(gap.get("target_capsule_title") or "").strip() or f"{gap['topic']} Capsule"

    from app.subordinate import SUBORDINATE_IDENTITY

    publication_status = "none"
    publication_rationale = ""
    try:
        publication_raw = _invoke_for_stage(
            "publication_judge",
            _build_publication_judge_prompt(
                capsule_title=capsule_title,
                capsule_body=final_capsule,
                cited_urls=cited_urls,
                research_grounding=grounding,
            ),
        )
        publication_decision = _parse_publication_decision(publication_raw)
        publication_status = str(publication_decision.get("publication_status") or "none")
        publication_rationale = str(publication_decision.get("rationale") or "").strip()
    except StageRateLimitExceeded:
        publication_status = "none"
        publication_rationale = "hourly_llm_cap_exceeded"

    visibility = "public" if publication_status == "published" else "private"
    owner = "sagwan" if publication_status == "published" else SUBORDINATE_IDENTITY.get("nickname", "busagwan")

    suggested_path = suggest_note_path("capsule", capsule_title, _SAGWAN_CAPSULE_FOLDER, None, "ops/librarian")
    doc = write_document(
        path=suggested_path,
        title=capsule_title,
        kind="capsule",
        project="ops/librarian",
        status="draft",
        tags=["capsule", "sagwan-generated", "research-gap", gap["topic_slug"]],
        body=final_capsule,
        metadata={
            "visibility": visibility,
            "publication_status": publication_status,
            "owner": owner,
            "original_owner": SUBORDINATE_IDENTITY.get("nickname", "busagwan"),
            "created_by": _SAGWAN_CAPSULE_CREATOR,
            "generated_by": "sagwan-research",
            "research_gap_topic": gap["topic"],
            "research_queries": gap["queries"],
            "research_cited_urls": cited_urls,
            "research_grounding": grounding,
            "research_retry_count": retry_count,
            "research_supplement_to": str(gap.get("supplement_extend_path") or "").strip() or None,
            "publication_decided_by": "sagwan",
            "publication_decided_at": _now_iso(),
            "publication_decision_reason": publication_rationale,
            "evidence_urls": cited_urls,
            "evidence_paths": [],
        },
        allow_owner_change=True,
    )

    _append_research_log_entry(
        topic=gap["topic"],
        queries=gap["queries"],
        rationale=str(gap.get("rationale") or ""),
        cited_urls=cited_urls,
        capsule_path=doc.path,
        model="stage-routed",
        max_fetches=gap["max_fetches"],
        status="supplement" if gap.get("supplement_extend_path") else "ok",
        existing_path=str(gap.get("supplement_extend_path") or "").strip() or None,
        grounding=grounding,
        retry_count=retry_count,
    )
    now_iso = _now_iso()
    _touch_research_state(now_iso)

    return {
        "status": "ok",
        "gap_topic": gap["topic"],
        "queries": gap["queries"],
        "capsule_path": doc.path,
        "cited_urls": cited_urls,
        "research_grounding": grounding,
        "publication_status": publication_status,
        "publication_rationale": publication_rationale,
        "retry_attempted": retry_attempted,
        "research_supplement_to": str(gap.get("supplement_extend_path") or "").strip() or None,
        "inventory_summary": {
            "total_capsules": inventory.get("total_capsules", 0),
            "total_claims": inventory.get("total_claims", 0),
        },
    }


def _build_publication_judge_prompt(
    *,
    capsule_title: str,
    capsule_body: str,
    cited_urls: list[str],
    research_grounding: str,
) -> str:
    return f"""당신은 OpenAkashic 사관입니다. 방금 생성한 capsule을 검토하고 publication 단계를 결정합니다.

Capsule title: {capsule_title}
Capsule body (excerpt):
{capsule_body[:2000]}

Cited sources: {cited_urls}
Research grounding: {research_grounding}

사관 페르소나 규칙:
- 차분/규칙/근거/공개가능성/재사용성 우선
- 출처가 명확하고 일반화 가능한 사실이면 공개
- IchiMozzi/insu-server 같은 internal 환경 의존이 있으면 private 유지

다음 3가지 중 하나로 답하세요 (JSON):
{{"publication_status": "published", "rationale": "..."}}
{{"publication_status": "requested", "rationale": "..."}}
{{"publication_status": "none", "rationale": "..."}}
"""


def _parse_publication_decision(raw: str) -> dict[str, str]:
    payload = _extract_json_dict(raw)
    status = str(payload.get("publication_status") or "").strip().lower()
    if status not in {"published", "requested", "none"}:
        status = "none"
    return {
        "publication_status": status,
        "rationale": str(payload.get("rationale") or "").strip(),
    }


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


def _curate_detect_conflicts(*, max_per_cycle: int = 1) -> dict[str, Any]:
    """(F) 신규 capsule/claim 을 사관이 자율적으로 conflict/duplicate/clear 판정한다."""
    from app.mcp_server import _post_internal_review

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    candidates: list[Any] = []
    for path in list_note_paths():
        try:
            doc = load_document(path)
        except Exception:
            continue
        fm = dict(doc.frontmatter or {})
        kind = str(fm.get("kind") or "").strip().lower()
        if kind not in {"capsule", "claim"}:
            continue
        created_at = _parse_iso_datetime(str(fm.get("created_at") or fm.get("updated_at") or ""))
        if created_at is None or created_at < cutoff:
            continue
        if str(fm.get("conflict_check_at") or "").strip():
            continue
        if str(fm.get("targets") or "").strip():
            continue
        candidates.append(doc)

    if not candidates:
        return {"checked": 0, "flagged": 0, "status": "no_new_candidates"}

    candidates.sort(
        key=lambda doc: str(doc.frontmatter.get("created_at") or doc.frontmatter.get("updated_at") or ""),
        reverse=True,
    )
    candidate = candidates[0]
    try:
        raw = _invoke_for_stage("conflict", _build_conflict_check_prompt(candidate), web_tools=True)
    except StageRateLimitExceeded:
        return {"checked": 0, "flagged": 0, "status": "rate_limit_skipped"}
    decision = _parse_conflict_decision(raw)
    verdict = str(decision.get("verdict") or "clear")
    flagged = 0

    if verdict == "conflict" and decision.get("target_path"):
        flagged = 1
        _post_internal_review(
            target=str(decision["target_path"]),
            stance="dispute",
            rationale=str(decision.get("rationale") or "Sagwan autonomous conflict check flagged this note."),
            evidence_paths=[candidate.path],
            topic="sagwan-conflict-detect",
        )
    elif verdict == "duplicate" and decision.get("target_path"):
        flagged = 1
        _enqueue_maintenance(candidate.path, reason=f"duplicate_with_{decision['target_path']}")

    next_fm = dict(candidate.frontmatter or {})
    next_fm["conflict_check_at"] = _now_iso()
    next_fm["conflict_status"] = "flagged" if verdict in {"conflict", "duplicate"} else "clear"
    next_fm["conflict_check_verdict"] = verdict
    if decision.get("target_path"):
        next_fm["conflict_target_path"] = decision["target_path"]
    if decision.get("rationale"):
        next_fm["conflict_check_note"] = str(decision["rationale"])[:500]
    write_document(path=candidate.path, body=candidate.body, metadata=next_fm, allow_owner_change=True)
    return {"checked": 1, "flagged": flagged, "verdict": verdict, "status": "ok", "target": candidate.path}


def _build_conflict_check_prompt(doc: Any) -> str:
    fm = dict(doc.frontmatter or {})
    return "\n\n".join(
        [
            "너는 OpenAkashic 사관이다. 신규 note/capsule의 충돌·중복·정합성을 자율 점검한다.",
            "사용 가능한 도구:",
            "- mcp__openakashic__search_akashic",
            "- mcp__openakashic__search_notes",
            "- mcp__openakashic__read_note",
            "- mcp__openakashic__read_raw_note",
            "- mcp__openakashic__list_reviews",
            "- WebSearch",
            "- WebFetch",
            "",
            f"대상 path: {doc.path}",
            f"title: {fm.get('title') or doc.path}",
            f"kind: {fm.get('kind') or 'reference'}",
            f"created_at: {fm.get('created_at') or '(none)'}",
            f"tags: {fm.get('tags') or []}",
            "",
            "## Body",
            (doc.body or "")[:2500] or "(empty)",
            "",
            "작업:",
            "1. 관련/유사 문서를 vault와 public knowledge에서 찾는다.",
            "2. 명백한 모순이면 conflict, 거의 같은 내용이면 duplicate, 아니면 clear로 판정한다.",
            "3. 마지막에는 JSON만 출력한다.",
            '{"verdict":"clear|conflict|duplicate","target_path":"...", "rationale":"..."}',
        ]
    )


def _parse_conflict_decision(raw: str) -> dict[str, str]:
    payload = _extract_json_dict(raw)
    verdict = str(payload.get("verdict") or "").strip().lower()
    if verdict not in {"clear", "conflict", "duplicate"}:
        verdict = "clear"
    return {
        "verdict": verdict,
        "target_path": str(payload.get("target_path") or payload.get("merge_into") or "").strip(),
        "rationale": str(payload.get("rationale") or "").strip(),
    }


def _ensure_activity_log(path: str, *, title: str, tags: list[str]) -> None:
    try:
        load_document(path)
    except Exception:
        write_document(
            path=path,
            body="## Summary\nSagwan activity log.\n",
            metadata={
                "title": title,
                "kind": "activity",
                "project": "ops/librarian",
                "status": "active",
                "tags": tags,
                "visibility": "private",
                "owner": "sagwan",
            },
            allow_owner_change=True,
        )


def _enqueue_maintenance(path: str, *, reason: str) -> None:
    doc = load_document(path)
    fm = dict(doc.frontmatter or {})
    fm["maintenance_priority_reason"] = reason
    fm["maintenance_priority_at"] = _now_iso()
    write_document(path=path, body=doc.body, metadata=fm, allow_owner_change=True)


def _maintenance_system_owners() -> set[str]:
    return {"sagwan", "admin", "system", "busagwan", SAGWAN_DECIDER}


def _find_maintenance_candidate() -> Any | None:
    candidates: list[dict[str, Any]] = []
    for path in list_note_paths():
        if not path.startswith("personal_vault/"):
            continue
        try:
            doc = load_document(path)
        except Exception:
            continue
        fm = dict(doc.frontmatter or {})
        kind = str(fm.get("kind") or "").strip().lower()
        if kind not in {"capsule", "claim"}:
            continue
        if str(fm.get("targets") or "").strip():
            continue
        if str(fm.get("claim_review_status") or "").strip().lower() in {"superseded", "merged"}:
            continue
        if str(fm.get("status") or "").strip().lower() == "archived":
            continue
        last_at = str(fm.get("maintenance_priority_at") or fm.get("last_maintained_at") or fm.get("created_at") or "")
        candidates.append(
            {
                "doc": doc,
                "priority": 0 if fm.get("maintenance_priority_at") else 1,
                "last_at": last_at,
            }
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["priority"], item["last_at"]))
    return candidates[0]["doc"]


def _build_maintenance_prompt(doc: Any) -> str:
    fm = dict(doc.frontmatter or {})
    return "\n\n".join(
        [
            "너는 OpenAkashic 사관이다. 다음 capsule/claim을 자율 점검하라.",
            "사용 가능한 도구:",
            "- mcp__openakashic__search_akashic",
            "- mcp__openakashic__search_notes",
            "- mcp__openakashic__read_note",
            "- mcp__openakashic__read_raw_note",
            "- mcp__openakashic__list_reviews",
            "- WebSearch",
            "- WebFetch",
            "",
            f"path: {doc.path}",
            f"title: {fm.get('title') or doc.path}",
            f"created_at: {fm.get('created_at') or '(none)'}",
            f"last_maintained_at: {fm.get('last_maintained_at') or '없음'}",
            "",
            "## Body",
            (doc.body or "")[:3000] or "(empty)",
            "",
            "작업:",
            "1. 관련 문서 / 비슷한 문서 검색 (vault + public web)",
            "2. 정보 진위와 정합성 확인",
            "3. 5-way 판정: keep | revise | supersede | merge | archive",
            "도구 호출은 5~15회 이내를 목표로 한다.",
            '마지막에는 JSON만 출력: {"verdict":"keep|revise|supersede|merge|archive","rationale":"...","new_title":"...","new_body":"...","merge_into":"..."}',
        ]
    )


def _parse_maintenance_decision(raw: str) -> dict[str, str]:
    payload = _extract_json_dict(raw)
    verdict = str(payload.get("verdict") or "").strip().lower()
    if verdict not in {"keep", "revise", "supersede", "merge", "archive"}:
        verdict = "keep"
    return {
        "verdict": verdict,
        "rationale": str(payload.get("rationale") or "").strip(),
        "new_title": str(payload.get("new_title") or "").strip(),
        "new_body": str(payload.get("new_body") or "").strip(),
        "merge_into": str(payload.get("merge_into") or payload.get("target_path") or "").strip(),
    }


def _touch_maintenance_state(path: str, verdict: str, rationale: str) -> None:
    doc = load_document(path)
    fm = dict(doc.frontmatter or {})
    fm["last_maintained_at"] = _now_iso()
    fm["last_maintenance_verdict"] = verdict
    fm["last_maintenance_note"] = rationale[:500]
    fm.pop("maintenance_priority_reason", None)
    fm.pop("maintenance_priority_at", None)
    write_document(path=path, body=doc.body, metadata=fm, allow_owner_change=True)


def _write_maintenance_dispute(target_path: str, rationale: str) -> None:
    from app.mcp_server import _post_internal_review

    _post_internal_review(
        target=target_path,
        stance="dispute",
        rationale=rationale[:1800],
        topic="sagwan-maintenance-owner-guard",
    )


def _write_revised(candidate: Any, new_body: str, rationale: str) -> dict[str, Any]:
    owner = str(candidate.frontmatter.get("owner") or "").strip().lower()
    if owner and owner not in _maintenance_system_owners():
        _write_maintenance_dispute(
            candidate.path,
            f"Sagwan maintenance wanted to revise this note but owner guard blocked direct body edits: {rationale}",
        )
        _touch_maintenance_state(candidate.path, "revise_blocked_owner_guard", rationale)
        return {"status": "owner_guard_dispute"}
    fm = dict(candidate.frontmatter or {})
    fm["revision_count"] = int(fm.get("revision_count") or 0) + 1
    fm["last_maintained_at"] = _now_iso()
    fm["last_maintenance_verdict"] = "revise"
    fm["last_maintenance_note"] = rationale[:500]
    fm.pop("maintenance_priority_reason", None)
    fm.pop("maintenance_priority_at", None)
    write_document(path=candidate.path, body=new_body, metadata=fm, allow_owner_change=True)
    return {"status": "revised"}


def _write_superseding(candidate: Any, new_title: str, new_body: str, rationale: str) -> str:
    now_iso = _now_iso()
    new_path = _write_superseding_capsule(
        old_doc=candidate,
        new_title=new_title or f"{candidate.frontmatter.get('title') or candidate.path} (Superseded)",
        new_body=new_body,
        now_iso=now_iso,
    )
    _mark_parent_superseded_by(candidate.path, new_path, now_iso)
    _touch_maintenance_state(candidate.path, "supersede", rationale)
    return new_path


def _mark_parent_merged_into(old_path: str, target_path: str, rationale: str) -> None:
    old_doc = load_document(old_path)
    fm = dict(old_doc.frontmatter or {})
    fm["superseded_by"] = target_path
    fm["claim_review_status"] = "merged"
    fm["last_maintained_at"] = _now_iso()
    fm["last_maintenance_verdict"] = "merge"
    fm["last_maintenance_note"] = rationale[:500]
    fm.pop("maintenance_priority_reason", None)
    fm.pop("maintenance_priority_at", None)
    write_document(path=old_path, body=old_doc.body, metadata=fm, allow_owner_change=True)


def _archive_capsule(path: str, rationale: str) -> dict[str, Any]:
    if path.startswith(_LIBRARIAN_PREFIX):
        logger.warning("sagwan maintenance archive blocked for protected path: %s", path)
        return {"status": "guard_blocked"}
    doc = load_document(path)
    fm = dict(doc.frontmatter or {})
    fm["visibility"] = "private"
    fm["status"] = "archived"
    fm["last_maintained_at"] = _now_iso()
    fm["last_maintenance_verdict"] = "archive"
    fm["last_maintenance_note"] = rationale[:500]
    fm.pop("maintenance_priority_reason", None)
    fm.pop("maintenance_priority_at", None)
    write_document(path=path, body=doc.body, metadata=fm, allow_owner_change=True)
    return {"status": "archived"}


def _trim_maintenance_log(max_entries: int = 100) -> None:
    try:
        doc = load_document(_MAINTENANCE_LOG_PATH)
    except Exception:
        return
    matches = list(re.finditer(r"^##\s+", doc.body or "", re.MULTILINE))
    if len(matches) <= max_entries + 1:
        return
    summary_end = matches[1].start()
    keep_from = matches[-max_entries].start()
    archived_body = (doc.body[summary_end:keep_from]).strip()
    if archived_body:
        archive_path = _MAINTENANCE_LOG_PATH.replace(".md", "-archive.md")
        try:
            archive_doc = load_document(archive_path)
            archive_text = archive_doc.body.rstrip() + "\n\n" + archived_body + "\n"
            archive_fm = dict(archive_doc.frontmatter or {})
        except Exception:
            archive_text = "## Summary\nArchived maintenance entries.\n\n" + archived_body + "\n"
            archive_fm = {
                "title": "Sagwan Maintenance Archive",
                "kind": "activity",
                "project": "ops/librarian",
                "status": "active",
                "tags": ["sagwan", "activity", "maintenance", "archive"],
                "visibility": "private",
                "owner": "sagwan",
            }
        write_document(path=archive_path, body=archive_text, metadata=archive_fm, allow_owner_change=True)
    next_body = doc.body[:summary_end].rstrip() + "\n\n" + doc.body[keep_from:].lstrip()
    write_document(path=_MAINTENANCE_LOG_PATH, body=next_body, metadata=dict(doc.frontmatter or {}), allow_owner_change=True)


def _append_maintenance_log_entry(candidate_path: str, decision: dict[str, str]) -> None:
    _ensure_activity_log(
        _MAINTENANCE_LOG_PATH,
        title="Sagwan Maintenance Log",
        tags=["sagwan", "activity", "maintenance"],
    )
    append_section(
        _MAINTENANCE_LOG_PATH,
        f"{_now_iso()} maintenance",
        "\n".join(
            [
                f"- target: {candidate_path}",
                f"- verdict: {decision.get('verdict')}",
                f"- rationale: {str(decision.get('rationale') or '')[:800]}",
                f"- merge_into: {decision.get('merge_into') or '-'}",
                f"- new_title: {decision.get('new_title') or '-'}",
            ]
        ),
    )
    _trim_maintenance_log()


def _touch_maintenance_state_global(now_iso: str) -> None:
    _ensure_activity_log(
        _MAINTENANCE_LOG_PATH,
        title="Sagwan Maintenance Log",
        tags=["sagwan", "activity", "maintenance"],
    )
    doc = load_document(_MAINTENANCE_LOG_PATH)
    fm = dict(doc.frontmatter or {})
    fm["last_run_at"] = now_iso
    write_document(path=_MAINTENANCE_LOG_PATH, body=doc.body, metadata=fm, allow_owner_change=True)


def _curate_maintenance(force: bool = False) -> dict[str, Any]:
    settings = load_sagwan_settings()
    if not settings.get("maintenance_enabled", True):
        return {"status": "disabled"}
    _ensure_activity_log(
        _MAINTENANCE_LOG_PATH,
        title="Sagwan Maintenance Log",
        tags=["sagwan", "activity", "maintenance"],
    )
    state_doc = load_document(_MAINTENANCE_LOG_PATH)
    last_run_at = str(state_doc.frontmatter.get("last_run_at") or "").strip()
    interval_sec = int(settings.get("maintenance_interval_sec") or 1800)
    if last_run_at and not force:
        last_dt = _parse_iso_datetime(last_run_at)
        if last_dt is not None and datetime.now(UTC) < last_dt + timedelta(seconds=interval_sec):
            return {"status": "cooldown", "last_run_at": last_run_at}

    candidate = _find_maintenance_candidate()
    if candidate is None:
        return {"status": "no_candidates"}

    try:
        raw = _invoke_for_stage("maintenance", _build_maintenance_prompt(candidate), web_tools=True)
    except StageRateLimitExceeded:
        return {"status": "rate_limit_skipped"}
    decision = _parse_maintenance_decision(raw)
    verdict = decision["verdict"]
    result: dict[str, Any] = {"status": "ok", "target": candidate.path, "verdict": verdict}

    if verdict == "keep":
        _touch_maintenance_state(candidate.path, "keep", decision["rationale"])
    elif verdict == "revise":
        result.update(_write_revised(candidate, decision["new_body"] or candidate.body, decision["rationale"]))
    elif verdict == "supersede":
        result["new_path"] = _write_superseding(candidate, decision["new_title"], decision["new_body"] or candidate.body, decision["rationale"])
    elif verdict == "merge":
        _mark_parent_merged_into(candidate.path, decision["merge_into"], decision["rationale"])
    elif verdict == "archive":
        result.update(_archive_capsule(candidate.path, decision["rationale"]))

    _append_maintenance_log_entry(candidate.path, decision)
    _touch_maintenance_state_global(_now_iso())
    return result


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

    if "analyze_search_quality_signals" not in live_kinds:
        try:
            enqueue_subordinate_task(
                kind="analyze_search_quality_signals",
                payload={"max_new": 10},
                created_by="sagwan",
            )
            enqueued.append("analyze_search_quality_signals")
        except Exception as exc:
            logger.warning("signal scan: quality enqueue failed: %s", exc)

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
# 설계: 사관이 직접 관심 주제 3개를 제안해 activity 로그에 남긴다.
# 자동 crawl_url enqueue 는 폐기되었고, 실제 웹 조사는 stage K가 맡는다.
# 24시간에 한 번만 실행 (claude-cli 비용 절약).

_TOPIC_STATE_PATH = "personal_vault/projects/ops/librarian/activity/topic-proposals.md"
_TOPIC_MIN_INTERVAL_HOURS = 24


def _curate_propose_topics() -> dict[str, Any]:
    """(H) 사관이 직접 관심 주제를 선정하고 후속 stage K / 인간 검토용으로 기록한다."""
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

    min_interval_hours = _TOPIC_MIN_INTERVAL_HOURS
    try:
        settings = load_sagwan_settings()
        min_interval_hours = int(settings.get("topic_min_interval_hours") or _TOPIC_MIN_INTERVAL_HOURS)
    except Exception:
        min_interval_hours = _TOPIC_MIN_INTERVAL_HOURS

    last_run = str(state_fm.get("last_run_at") or "").strip()
    if last_run:
        try:
            last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
            if datetime.now(UTC) - last_dt < timedelta(hours=min_interval_hours):
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

    try:
        reply = _invoke_for_stage("topic_proposal", prompt)
    except StageRateLimitExceeded:
        return {"status": "rate_limit_skipped"}
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

    # 4) 주제만 기록한다. 자동 crawl_url enqueue 는 폐기되었고, 웹 조사는 stage K가 담당한다.
    total_enqueued = 0
    per_topic = [{"topic": q, "enqueued": 0, "mode": "proposal_only"} for q in topics]

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
        mark = item.get("error") or "recorded for stage K / human follow-up"
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
_CORE_SYNC_BLOCKED_REQUEST_PATH = f"{_IMPROVEMENT_REQUEST_FOLDER}/core-sync-blocked-notes.md"


def _collect_core_sync_blocked_notes(*, limit: int = 10) -> list[dict[str, str]]:
    blocked: list[dict[str, str]] = []
    for path in list_note_paths():
        try:
            doc = load_document(path)
        except Exception:
            continue
        fm = dict(doc.frontmatter or {})
        if not fm.get("core_sync_blocked"):
            continue
        blocked.append(
            {
                "path": path,
                "reason": str(fm.get("core_sync_last_failure_reason") or "sync_failed").strip() or "sync_failed",
                "last_failure_at": str(fm.get("core_sync_last_failure_at") or "").strip(),
            }
        )
        if len(blocked) >= limit:
            break
    return blocked


def _upsert_core_sync_blocked_request(blocked_notes: list[dict[str, str]]) -> str | None:
    if not blocked_notes:
        return None
    lines = [
        "## Summary",
        "Busagwan Core API sync has one or more notes blocked after repeated failures. Human investigation is required.",
        "",
        "## Blocked Notes",
    ]
    for item in blocked_notes:
        lines.append(
            f"- {item['path']} — {item['reason']}"
            + (f" (last_failure_at={item['last_failure_at']})" if item.get("last_failure_at") else "")
        )
    write_document(
        path=_CORE_SYNC_BLOCKED_REQUEST_PATH,
        body="\n".join(lines),
        metadata={
            "title": "Improvement Request: core sync blocked notes",
            "kind": "improvement-request",
            "project": "ops/librarian",
            "status": "proposed",
            "tags": ["meta", "improvement-request", "core-sync", "blocked", "sagwan-generated"],
            "visibility": "private",
            "owner": "sagwan",
            "review_status": "pending_human_review",
        },
        allow_owner_change=True,
    )
    return _CORE_SYNC_BLOCKED_REQUEST_PATH


def _count_new_memory_episodes(actor: str) -> int:
    from app.agent_memory import _distilled_path, _memory_path, _split_sections, _segment_ts

    try:
        mem_doc = load_document(_memory_path(actor))
    except Exception:
        return 0
    segments = _split_sections(mem_doc.body or "")
    if not segments:
        return 0
    last_distilled_at = ""
    try:
        distilled_doc = load_document(_distilled_path(actor))
        last_distilled_at = str(distilled_doc.frontmatter.get("last_distilled_at") or "")
    except Exception:
        pass
    if not last_distilled_at:
        return len(segments)
    return sum(1 for segment in segments if _segment_ts(segment) > last_distilled_at)


def _maybe_distill_sagwan() -> dict[str, Any]:
    settings = load_sagwan_settings()
    min_interval_sec = int(settings.get("distill_min_interval_sec") or 21600)
    min_episodes = int(settings.get("distill_min_episodes") or 5)
    last_distilled_at = ""
    try:
        distilled_doc = load_document("personal_vault/projects/ops/librarian/memory/Sagwan Distilled Memory.md")
        last_distilled_at = str(distilled_doc.frontmatter.get("last_distilled_at") or "")
    except Exception:
        pass
    if last_distilled_at:
        last_dt = _parse_iso_datetime(last_distilled_at)
        if last_dt is not None and datetime.now(UTC) < last_dt + timedelta(seconds=min_interval_sec):
            return {"status": "skip", "reason": "cooldown", "last_distilled_at": last_distilled_at}
    new_episodes = _count_new_memory_episodes("sagwan")
    if new_episodes < min_episodes:
        return {"status": "skip", "reason": "insufficient_new_episodes", "new_episodes": new_episodes}
    prompt_invoke = lambda prompt, *, model=None: _invoke_for_stage("distill", prompt)
    return distill_memory("sagwan", llm_invoke=prompt_invoke, force=True)


def _write_llm_telemetry_cycle(summary: dict[str, Any]) -> None:
    _ensure_activity_log(
        _LLM_TELEMETRY_LOG_PATH,
        title="Sagwan LLM Telemetry",
        tags=["sagwan", "activity", "llm-telemetry"],
    )
    hour_events = _recent_llm_calls(since=timedelta(hours=1))
    day_events = _recent_llm_calls(since=timedelta(days=1))
    counts: dict[str, dict[str, int]] = {}
    durations: dict[str, list[float]] = {}
    for event in hour_events:
        backend = str(event.get("backend") or "unknown")
        stage = str(event.get("stage") or "unknown")
        counts.setdefault(backend, {})
        counts[backend][stage] = counts[backend].get(stage, 0) + 1
        durations.setdefault(backend, []).append(float(event.get("duration_s") or 0.0))
    rate_limit_skipped = sum(
        1
        for item in summary.values()
        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "rate_limit_skipped"
    )
    append_section(
        _LLM_TELEMETRY_LOG_PATH,
        f"{_now_iso()} cycle",
        "\n".join(
            [
                f"- claude_cli_calls: {sum(counts.get('claude-cli', {}).values())}",
                f"- proxy_calls: {sum(counts.get('proxy', {}).values())}",
                f"- rate_limit_skipped: {rate_limit_skipped}",
                f"- stages: {json.dumps(counts, ensure_ascii=False)}",
            ]
        ),
    )
    day_counts: dict[str, dict[str, int]] = {}
    day_durations: dict[str, list[float]] = {}
    for event in day_events:
        backend = str(event.get("backend") or "unknown")
        stage = str(event.get("stage") or "unknown")
        day_counts.setdefault(backend, {})
        day_counts[backend][stage] = day_counts[backend].get(stage, 0) + 1
        day_durations.setdefault(backend, []).append(float(event.get("duration_s") or 0.0))
    day_key = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00Z")
    rollup_lines = [
        f"- claude_cli_calls: {sum(day_counts.get('claude-cli', {}).values())} ({', '.join(f'{k}: {v}' for k, v in sorted(day_counts.get('claude-cli', {}).items())) or 'none'})",
        f"- proxy_calls: {sum(day_counts.get('proxy', {}).values())} ({', '.join(f'{k}: {v}' for k, v in sorted(day_counts.get('proxy', {}).items())) or 'none'})",
        f"- avg_response_time_s: claude_cli={round(sum(day_durations.get('claude-cli', [0.0])) / max(1, len(day_durations.get('claude-cli', []))), 2)}"
        f", proxy={round(sum(day_durations.get('proxy', [0.0])) / max(1, len(day_durations.get('proxy', []))), 2)}",
        f"- rate_limit_skipped: {rate_limit_skipped}",
    ]
    doc = load_document(_LLM_TELEMETRY_LOG_PATH)
    body = doc.body or "## Summary\nSagwan LLM telemetry.\n"
    rollup_heading = f"## {day_key} daily-rollup"
    rollup_block = rollup_heading + "\n" + "\n".join(rollup_lines)
    if rollup_heading in body:
        body = re.sub(
            rf"^##\s+{re.escape(day_key)} daily-rollup\s*\n.*?(?=^##\s+|\Z)",
            rollup_block + "\n",
            body,
            flags=re.MULTILINE | re.DOTALL,
        )
    else:
        body = body.rstrip() + "\n\n" + rollup_block + "\n"
    write_document(path=_LLM_TELEMETRY_LOG_PATH, body=body, metadata=dict(doc.frontmatter or {}), allow_owner_change=True)


def _maybe_update_librarian_profile(state_fm: dict[str, Any]) -> dict[str, Any]:
    settings = load_sagwan_settings()
    min_hours = int(settings.get("profile_update_min_interval_hours") or 24)
    last_run = str(state_fm.get("last_profile_update_at") or "").strip()
    if last_run:
        last_dt = _parse_iso_datetime(last_run)
        if last_dt is not None and datetime.now(UTC) < last_dt + timedelta(hours=min_hours):
            return {"status": "cooldown"}
    try:
        profile_doc = load_document("personal_vault/projects/ops/librarian/profile/Librarian Profile.md")
    except Exception:
        return {"status": "missing_profile"}
    prompt = "\n\n".join(
        [
            "현재 자기 페르소나 (Librarian Profile.md)와 새 권한/역할이 일치하는가? 새 도구 / 변경된 정책 반영이 필요한지 판단하라.",
            "필요 없으면 JSON만 출력: {\"needs_update\": false, \"rationale\": \"...\"}",
            "필요하면 JSON만 출력: {\"needs_update\": true, \"rationale\": \"...\", \"body\": \"## Summary ...\"}",
            "",
            "## Current Profile",
            profile_doc.body or "",
        ]
    )
    try:
        raw = _invoke_for_stage("profile_update", prompt)
    except StageRateLimitExceeded:
        return {"status": "rate_limit_skipped"}
    payload = _extract_json_dict(raw)
    if not payload or not bool(payload.get("needs_update")):
        return {"status": "no_change", "rationale": str(payload.get("rationale") or "").strip()}
    body = str(payload.get("body") or "").strip()
    if "## Summary" not in body:
        return {"status": "invalid_body"}
    fm = dict(profile_doc.frontmatter or {})
    fm["updated_at"] = _now_iso()
    write_document(path=profile_doc.path, body=body, metadata=fm, allow_owner_change=True)
    return {"status": "updated", "rationale": str(payload.get("rationale") or "").strip()}


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
    min_interval_hours = _META_MIN_INTERVAL_HOURS
    try:
        settings = load_sagwan_settings()
        min_interval_hours = int(settings.get("meta_min_interval_hours") or _META_MIN_INTERVAL_HOURS)
    except Exception:
        min_interval_hours = _META_MIN_INTERVAL_HOURS
    last_run = str(state_fm.get("last_run_at") or "").strip()
    if last_run:
        try:
            last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
            if datetime.now(UTC) - last_dt < timedelta(hours=min_interval_hours):
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
    blocked_core_sync = _collect_core_sync_blocked_notes(limit=10)
    blocked_core_sync_block = "\n".join(
        [
            f"- {item['path']}: {item['reason']}"
            + (f" @ {item['last_failure_at']}" if item.get("last_failure_at") else "")
            for item in blocked_core_sync
        ]
    ) or "(없음)"

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
        f"## Blocked core sync notes\n{blocked_core_sync_block}",
        "",
        ctx["combined"] or "",
        "",
        "형식을 반드시 지켜라. 불필요한 서두 금지.",
    ])

    try:
        reply = _invoke_for_stage("meta_curation", prompt)
    except StageRateLimitExceeded:
        return {"status": "rate_limit_skipped"}
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
    blocked_request_path = _upsert_core_sync_blocked_request(blocked_core_sync)
    if blocked_request_path:
        requests_created.append(Path(blocked_request_path).stem)
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

    profile_update = _maybe_update_librarian_profile(state_fm)

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
                "last_profile_update_at": now_iso if profile_update.get("status") != "cooldown" else state_fm.get("last_profile_update_at"),
            },
            allow_owner_change=True,
        )
    except Exception as exc:
        logger.warning("meta curation: state write failed: %s", exc)

    return {
        "status": "ok",
        "health_path": health_path,
        "requests_created": requests_created,
        "profile_update": profile_update,
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
