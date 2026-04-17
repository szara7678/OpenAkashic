from __future__ import annotations

from datetime import UTC, datetime, timedelta
import fcntl
import json
import logging

logger = logging.getLogger(__name__)
from pathlib import Path
import re
import threading
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest
from uuid import uuid4

# 큐 파일 동시 접근 방지 — 단일 프로세스 내 스레드 직렬화
_QUEUE_LOCK = threading.Lock()
# 큐 pending 태스크 상한 (초과 시 신규 enqueue 거부)
_QUEUE_PENDING_LIMIT = 150
# done/failed 태스크 보존 기간 (일)
_QUEUE_PRUNE_DAYS = 7

from app.config import get_settings
from app.core_api_bridge import sync_published_note
from app.site import SemanticDocument, get_closed_note, search_closed_notes, semantic_rank
from app.users import SAGWAN_SYSTEM_OWNER
from app.vault import (
    list_note_paths,
    append_section,
    ensure_folder,
    list_publication_requests,
    load_document,
    request_publication,
    set_publication_status,
    suggest_note_path,
    write_document,
)


SUBORDINATE_IDENTITY = {
    "username": "busagwan",
    "nickname": "busagwan",
    "display_name": "busagwan",
    "role": "admin",
    "token_label": "server-subordinate",
}
SUBORDINATE_PROFILE_PATH = "personal_vault/projects/ops/librarian/profile/Subordinate Profile.md"
SUBORDINATE_PLAYBOOK_PATH = "personal_vault/projects/ops/librarian/playbooks/Subordinate Task Playbook.md"
SUBORDINATE_MEMORY_PATH = "personal_vault/projects/ops/librarian/memory/Subordinate Working Memory.md"
# 사서장 메모리 — 부사관이 사서장 판단 이력을 참조하기 위해 읽는다
LIBRARIAN_MEMORY_PATH = "personal_vault/projects/ops/librarian/memory/Working Memory.md"
SUBORDINATE_TASK_TYPES = (
    "crawl_url",
    "draft_capsule",
    "draft_claim",
    "sync_to_core_api",
    "analyze_search_gaps",
    "detect_conflicts",
    "scan_stale_private_notes",
)


def subordinate_settings_path() -> Path:
    return Path(get_settings().user_store_path).with_name("subordinate-settings.json")


def subordinate_queue_path() -> Path:
    return Path(get_settings().user_store_path).with_name("subordinate-queue.json")


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_subordinate_settings() -> dict[str, Any]:
    settings = get_settings()
    return {
        "provider": "ollama",
        "base_url": settings.ollama_base_url,
        # 부사관 기본 모델은 gemma4:e4b로 고정한다. 특별한 사유(장애/tool 지원 이슈) 없이
        # 바꾸지 말 것 — 운영상 합의된 디폴트다.
        "model": "gemma4:e4b",
        "enabled": True,
        "interval_sec": 900,
        "max_tasks_per_run": 3,
        "auto_review_publication_requests": True,
        "auto_request_publication_for_capsules": False,
        "enabled_task_types": list(SUBORDINATE_TASK_TYPES),
    }


def load_subordinate_settings() -> dict[str, Any]:
    defaults = _default_subordinate_settings()
    path = subordinate_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(defaults, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        raw = {}
    return {
        "provider": str(raw.get("provider") or defaults["provider"]).strip() or defaults["provider"],
        "base_url": str(raw.get("base_url") or defaults["base_url"]).strip() or defaults["base_url"],
        "model": str(raw.get("model") or defaults["model"]).strip() or defaults["model"],
        "enabled": bool(raw.get("enabled", defaults["enabled"])),
        "interval_sec": max(60, int(raw.get("interval_sec") or defaults["interval_sec"])),
        "max_tasks_per_run": max(1, min(8, int(raw.get("max_tasks_per_run") or defaults["max_tasks_per_run"]))),
        "auto_review_publication_requests": bool(
            raw.get("auto_review_publication_requests", defaults["auto_review_publication_requests"])
        ),
        "auto_request_publication_for_capsules": bool(
            raw.get("auto_request_publication_for_capsules", defaults["auto_request_publication_for_capsules"])
        ),
        "enabled_task_types": [
            item for item in raw.get("enabled_task_types", defaults["enabled_task_types"]) if item in SUBORDINATE_TASK_TYPES
        ]
        or list(defaults["enabled_task_types"]),
    }


def save_subordinate_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_subordinate_settings()
    next_settings = {
        "provider": str(payload.get("provider") or current["provider"]).strip() or current["provider"],
        "base_url": str(payload.get("base_url") or current["base_url"]).strip() or current["base_url"],
        "model": str(payload.get("model") or current["model"]).strip() or current["model"],
        "enabled": bool(payload.get("enabled", current["enabled"])),
        "interval_sec": max(60, int(payload.get("interval_sec") or current["interval_sec"])),
        "max_tasks_per_run": max(1, min(8, int(payload.get("max_tasks_per_run") or current["max_tasks_per_run"]))),
        "auto_review_publication_requests": bool(
            payload.get("auto_review_publication_requests", current["auto_review_publication_requests"])
        ),
        "auto_request_publication_for_capsules": bool(
            payload.get("auto_request_publication_for_capsules", current["auto_request_publication_for_capsules"])
        ),
        "enabled_task_types": [
            item for item in payload.get("enabled_task_types", current["enabled_task_types"]) if item in SUBORDINATE_TASK_TYPES
        ]
        or list(current["enabled_task_types"]),
    }
    path = subordinate_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(next_settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return next_settings


def ensure_subordinate_workspace() -> None:
    _ensure_seed_note(
        SUBORDINATE_PROFILE_PATH,
        title="Subordinate Profile",
        kind="profile",
        body="\n".join(
            [
                "## Summary",
                "부사관은 반복 작업, 문서 크롤링 후 정리, publication 1차 검토, capsule 초안 생성을 맡는 보조 운영 에이전트다.",
                "",
                "## Role",
                "- 사관이 시킨 정리 작업을 분할 수행한다.",
                "- 공개 요청을 읽고 1차 리뷰를 작성한다.",
                "- URL과 문서 내용을 요약해 reference/evidence 초안을 만든다.",
                "- 실행 권한은 관리자 급이지만 `exec`는 사용하지 않는다.",
                "",
                "## Capabilities",
                "- read/search note",
                "- append/upsert note",
                "- request/set publication status",
                "- local ollama model generation",
                "",
                "## Constraints",
                "- 임의의 시스템 명령 실행 금지",
                "- 근거가 부족하면 승인을 확정하지 말고 `reviewing` 또는 보강 요청으로 남긴다.",
                "- 공개 결과는 raw source 복제가 아니라 capsule/claim/evidence 요약 중심으로 남긴다.",
            ]
        ),
    )
    _ensure_seed_note(
        SUBORDINATE_PLAYBOOK_PATH,
        title="Subordinate Task Playbook",
        kind="playbook",
        body="\n".join(
            [
                "## Summary",
                "부사관의 반복 작업 원칙과 태스크 종류를 정리한다.",
                "",
                "## When To Use",
                "- publication 요청이 쌓였을 때",
                "- URL이나 문서 크롤링 후 reference/evidence 초안을 만들 때",
                "- source note를 바탕으로 capsule 초안을 뽑을 때",
                "",
                "## Steps",
                "1. 관련 source/evidence/publication request를 읽는다.",
                "2. 근거와 요약을 정리해 1차 리뷰 또는 초안을 만든다.",
                "3. 필요한 경우 publication 상태를 `reviewing`으로 올린다.",
                "4. 사관이 검토하기 쉬운 짧은 섹션과 링크 위주로 남긴다.",
                "",
                "## Checks",
                "- 근거 링크가 있는가",
                "- private를 바로 public로 새지 않았는가",
                "- capsule이 실용 결과 중심인가",
            ]
        ),
    )
    _ensure_seed_note(
        SUBORDINATE_MEMORY_PATH,
        title="Subordinate Working Memory",
        kind="reference",
        body="\n".join(
            [
                "## Summary",
                "부사관이 반복 작업에서 재사용할 짧은 기준과 결과 메모를 쌓는다.",
                "",
                "## Reuse",
                "길고 모호한 로그보다 작업 종류별 판단 기준과 자주 쓰는 출력 패턴을 남긴다.",
            ]
        ),
    )


def subordinate_status() -> dict[str, Any]:
    ensure_subordinate_workspace()
    settings = load_subordinate_settings()
    queue = _load_queue()
    return {
        "name": "Subordinate",
        "identity": SUBORDINATE_IDENTITY,
        "settings": settings,
        "queue": {
            "pending": len([item for item in queue["tasks"] if item.get("status") == "pending"]),
            "running": len([item for item in queue["tasks"] if item.get("status") == "running"]),
            "done": len([item for item in queue["tasks"] if item.get("status") == "done"]),
            "failed": len([item for item in queue["tasks"] if item.get("status") == "failed"]),
        },
        "memory_paths": {
            "profile": SUBORDINATE_PROFILE_PATH,
            "playbook": SUBORDINATE_PLAYBOOK_PATH,
            "working_memory": SUBORDINATE_MEMORY_PATH,
        },
    }


def subordinate_chat(message: str, thread: list[dict[str, str]] | None = None) -> dict[str, Any]:
    ensure_subordinate_workspace()
    relevant = _relevant_context(message)
    settings = load_subordinate_settings()
    result = _ollama_tool_loop(message, relevant, thread or [], settings)
    reply = result["message"]
    _remember_subordinate_note(message, reply, task_kind="chat")
    return {
        "message": reply,
        "status": "ok",
        "tool_events": result.get("tool_events", []),
        "context_notes": relevant,
        "model": settings["model"],
    }


def enqueue_subordinate_task(
    *,
    kind: str,
    payload: dict[str, Any],
    created_by: str = "sagwan",
    run_after: str | None = None,
) -> dict[str, Any]:
    if kind not in SUBORDINATE_TASK_TYPES:
        raise ValueError(f"Unsupported subordinate task: {kind}")
    with _QUEUE_LOCK:
        queue = _load_queue()
        pending = sum(1 for t in queue["tasks"] if t.get("status") == "pending")
        if pending >= _QUEUE_PENDING_LIMIT:
            raise RuntimeError(
                f"Queue pending limit reached ({pending}/{_QUEUE_PENDING_LIMIT}). "
                "Busagwan is falling behind — check ollama GPU or raise limit."
            )
        # 동일 kind+payload 의 pending 태스크가 이미 있으면 중복 enqueue 방지
        dedup_key = _task_dedup_key(kind, payload)
        if dedup_key:
            for existing in queue["tasks"]:
                if existing.get("status") == "pending" and existing.get("kind") == kind:
                    if _task_dedup_key(kind, existing.get("payload") or {}) == dedup_key:
                        return existing  # 이미 큐에 있음 — 그대로 반환
        task: dict[str, Any] = {
            "id": uuid4().hex,
            "kind": kind,
            "payload": payload,
            "status": "pending",
            "created_by": created_by,
            "created_at": _now_iso(),
            "run_after": run_after or _now_iso(),
            "started_at": "",
            "finished_at": "",
            "last_error": "",
            "result_path": "",
        }
        queue["tasks"].append(task)
        _save_queue(queue)
    return task


def list_subordinate_tasks(status: str | None = None) -> list[dict[str, Any]]:
    with _QUEUE_LOCK:
        queue = _load_queue()
    if not status:
        return queue["tasks"]
    needle = status.strip().lower()
    return [task for task in queue["tasks"] if str(task.get("status") or "").lower() == needle]


def run_subordinate_cycle(*, reason: str = "manual") -> dict[str, Any]:
    ensure_subordinate_workspace()
    settings = load_subordinate_settings()
    if not settings["enabled"]:
        return {"status": "disabled", "reason": "Subordinate worker is disabled", "processed": []}

    processed: list[dict[str, Any]] = []
    if settings["auto_review_publication_requests"]:
        # publication review 는 최대 2개로 제한 — 큐 작업 슬롯 항상 최소 1개 확보
        pub_limit = min(2, settings["max_tasks_per_run"])
        processed.extend(_run_publication_first_reviews(limit=pub_limit))

    if len(processed) >= settings["max_tasks_per_run"]:
        return {"status": "ok", "reason": reason, "processed": processed}

    now = datetime.now(UTC)
    while len(processed) < settings["max_tasks_per_run"]:
        # 1) 락 안에서: pending 태스크 하나 claim (running 으로 전환) + prune
        claimed: dict[str, Any] | None = None
        with _QUEUE_LOCK:
            queue = _load_queue()
            _prune_done_tasks(queue)
            for task in queue["tasks"]:
                if task.get("status") != "pending":
                    continue
                if task.get("kind") not in settings["enabled_task_types"]:
                    continue
                run_after_str = str(task.get("run_after") or task.get("created_at") or _now_iso())
                if _parse_iso(run_after_str) > now:
                    continue
                task["status"] = "running"
                task["started_at"] = _now_iso()
                claimed = dict(task)  # snapshot
                break
            if claimed:
                _save_queue(queue)

        if claimed is None:
            break  # 처리할 태스크 없음

        # 2) 락 밖에서: 실제 태스크 실행 (gemma 호출 등 오래 걸릴 수 있음)
        try:
            result_path = _run_task(claimed, settings)
            final_status, final_error = "done", ""
        except Exception as exc:
            result_path, final_status, final_error = "", "failed", str(exc)

        # 3) 락 안에서: 결과 기록
        with _QUEUE_LOCK:
            queue = _load_queue()
            for t in queue["tasks"]:
                if t.get("id") == claimed["id"]:
                    t["status"] = final_status
                    t["finished_at"] = _now_iso()
                    t["result_path"] = result_path or ""
                    t["last_error"] = final_error
                    break
            _save_queue(queue)

        processed.append({**claimed, "status": final_status, "last_error": final_error})

        # 태스크 완료마다 장기 기억 정제 시도 (임계치 미달이면 자동 skip)
        try:
            from app.agent_memory import after_task as _after_task

            def _ollama_invoke(prompt: str, *, model: str | None = None) -> str:
                return _ollama_generate(prompt)

            _after_task("busagwan", llm_invoke=_ollama_invoke)
        except Exception:
            pass  # distill 실패는 치명적이지 않음

    return {"status": "ok", "reason": reason, "processed": processed}


def _run_publication_first_reviews(*, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    # "requested" → 아직 미리뷰 / "reviewing" 중 recommendation이 미확정(reviewing)인 항목도 재시도
    candidates = list(list_publication_requests(status="requested")) + list(
        list_publication_requests(status="reviewing")
    )
    seen: set[str] = set()
    for request in candidates:
        if len(results) >= limit:
            break
        if request.path in seen:
            continue
        seen.add(request.path)
        try:
            document = load_document(request.path)
        except Exception as exc:
            logger.warning("_run_publication_first_reviews: skipping missing note %s: %s", request.path, exc)
            continue
        recommendation = str(document.frontmatter.get("subordinate_recommendation") or "").strip().lower()
        # 이미 확정/에스컬레이션된 항목은 건너뜀
        if recommendation in {"approved", "rejected", "escalated"}:
            continue
        try:
            result = _review_publication_request(request.path)
            results.append(result)
        except Exception as exc:
            logger.warning("_run_publication_first_reviews: review failed for %s: %s", request.path, exc)
    return results


def _run_task(task: dict[str, Any], settings: dict[str, Any]) -> str:
    kind = str(task.get("kind") or "")
    payload = dict(task.get("payload") or {})
    if kind == "crawl_url":
        return _crawl_url_to_note(payload.get("url") or "", folder=payload.get("folder"), project=payload.get("project"))
    if kind == "draft_capsule":
        result = _draft_capsule(payload.get("source_path") or "", auto_request=settings["auto_request_publication_for_capsules"])
        return str(result.get("path") or "")
    if kind == "draft_claim":
        results = _draft_claim(payload.get("source_path") or "", auto_request=settings.get("auto_request_publication_for_capsules", False))
        return str([r.get("path") for r in results])
    if kind == "sync_to_core_api":
        return _sync_published_notes_to_core_api(limit=int(payload.get("limit") or 10))
    if kind == "analyze_search_gaps":
        return _analyze_search_gaps(max_new=int(payload.get("max_new") or 10))
    if kind == "detect_conflicts":
        return _detect_conflicts(payload.get("path") or "")
    if kind == "scan_stale_private_notes":
        return _scan_stale_private_notes(
            owner=str(payload.get("owner") or ""),
            dry_run=bool(payload.get("dry_run") or False),
        )
    raise ValueError(f"Unsupported subordinate task: {kind}")


def _detect_conflicts(path: str) -> str:
    note_path = path.strip()
    if not note_path:
        raise ValueError("detect_conflicts requires path")
    source = load_document(note_path)
    source_fm = source.frontmatter
    source_owner = str(source_fm.get("owner") or "").strip()
    query = "\n".join(
        [
            str(source_fm.get("title") or Path(source.path).stem),
            str(source_fm.get("kind") or ""),
            str(source_fm.get("project") or ""),
            " ".join(str(tag) for tag in source_fm.get("tags") or []),
            source.body,
        ]
    ).strip()

    documents: list[SemanticDocument] = []
    document_by_path: dict[str, Any] = {}
    for candidate_path in list_note_paths():
        try:
            candidate = load_document(candidate_path)
        except Exception:
            continue
        candidate_fm = candidate.frontmatter
        documents.append(
            SemanticDocument(
                key=candidate.path,
                path=candidate.path,
                title=str(candidate_fm.get("title") or Path(candidate.path).stem),
                kind=str(candidate_fm.get("kind") or "reference"),
                project=str(candidate_fm.get("project") or "openakashic"),
                status=str(candidate_fm.get("status") or "active"),
                summary=str(candidate_fm.get("summary") or ""),
                body=candidate.body,
            )
        )
        document_by_path[candidate.path] = candidate

    # 2단계 threshold: >=0.86 무조건 / 0.74-0.86은 같은 project 또는 tag 겹칠 때만
    source_tags = set(str(t) for t in (source_fm.get("tags") or []))
    source_project = str(source_fm.get("project") or "")
    conflict_candidates: list[dict[str, Any]] = []
    checked = 0
    for candidate_key, semantic_score in semantic_rank(query, documents, limit=8):
        candidate = document_by_path.get(candidate_key)
        if not candidate:
            continue
        if candidate.path == source.path:
            continue
        checked += 1
        if checked > 5:
            break
        if semantic_score >= 0.86:
            conflict_candidates.append(
                {"path": candidate.path, "score": round(float(semantic_score), 4)}
            )
        elif semantic_score >= 0.74:
            cand_fm = candidate.frontmatter
            cand_tags = set(str(t) for t in (cand_fm.get("tags") or []))
            cand_project = str(cand_fm.get("project") or "")
            has_tag_overlap = bool(source_tags & cand_tags)
            same_project = source_project and source_project == cand_project
            if has_tag_overlap or same_project:
                conflict_candidates.append(
                    {"path": candidate.path, "score": round(float(semantic_score), 4)}
                )

    next_frontmatter = dict(source.frontmatter)
    if not conflict_candidates:
        next_frontmatter["conflict_candidates"] = []
        next_frontmatter["conflict_status"] = "clear"
        write_document(path=source.path, body=source.body, metadata=next_frontmatter)
        return f"No conflict candidates detected for {source.path}"

    # LLM으로 실제 충돌 여부 판단 — semantic 유사도만으로는 관련 노트와 모순 노트를 구별 불가.
    candidate_snippets = []
    for cc in conflict_candidates[:3]:
        cand_doc = document_by_path.get(cc["path"])
        if cand_doc:
            snippet = (
                f"Path: {cc['path']} (score={cc['score']})\n"
                f"{cand_doc.body[:600]}"
            )
            candidate_snippets.append(snippet)

    prompt = "\n\n".join(
        [
            "너는 OpenAkashic의 부사관이다. 소스 노트와 후보 노트들이 실제로 모순·충돌하는지 판단한다.",
            f"소스 노트 ({source.path}):\n{source.body[:1500]}",
            "유사도 높은 후보 노트들:\n" + "\n---\n".join(candidate_snippets),
            (
                "이 후보들이 소스 노트와 같은 사실에 대해 서로 다른 주장을 하는지 판단하라. "
                "단순히 같은 주제라면 충돌이 아니다. 서로 다른 주장이어야 충돌이다."
            ),
            "출력 형식:\nVerdict: <CONFLICT|CLEAR>\nReason:\n- ...",
        ]
    )
    reply = _ollama_generate(prompt)

    verdict_match = re.search(
        r'^\s*Verdict:\s*(CONFLICT|CLEAR)\b', reply, re.MULTILINE | re.IGNORECASE
    )
    if _is_llm_failure(reply) or not verdict_match:
        # LLM 실패 또는 Verdict 줄 파싱 불가 → pending_review (재시도 대기)
        next_frontmatter["conflict_candidates"] = conflict_candidates
        next_frontmatter["conflict_status"] = "pending_review"
        summary = (
            f"LLM evaluation failed or malformed for {source.path}; "
            f"{len(conflict_candidates)} candidate(s) pending manual review"
        )
    elif verdict_match.group(1).upper() == "CONFLICT":
        next_frontmatter["conflict_candidates"] = conflict_candidates
        next_frontmatter["conflict_status"] = "flagged"
        summary = f"Confirmed conflict in {source.path}: {len(conflict_candidates)} candidate(s)"
    else:
        # CLEAR
        next_frontmatter["conflict_candidates"] = conflict_candidates
        next_frontmatter["conflict_status"] = "clear"
        summary = (
            f"No genuine conflict in {source.path} despite {len(conflict_candidates)} similar note(s)"
        )

    write_document(path=source.path, body=source.body, metadata=next_frontmatter)
    return summary


def _scan_stale_private_notes(owner: str, *, dry_run: bool = False) -> str:
    """오너의 private 노트 중 freshness_date가 decay_tier 임계일을 넘은 것을 찾아 요약 노트로 기록.

    dry_run=True이면 파일을 쓰지 않고 탐지 결과만 반환.
    """
    from app.site import list_stale_closed_notes as _stale_fn
    from datetime import UTC as _UTC, datetime as _dt

    if not owner:
        return "scan_stale_private_notes requires owner"

    all_stale = _stale_fn(days_overdue=0)
    # 해당 오너의 private / shared 노트만 필터
    owner_stale = [
        item for item in all_stale
        if str(item.get("owner") or "") == owner
        and str(item.get("visibility") or "private") in {"private", "shared"}
    ]

    if not owner_stale:
        return f"No stale notes found for owner '{owner}'"

    lines = [
        f"# Stale Note Scan — {owner} — {_dt.now(_UTC).date().isoformat()}",
        "",
        f"Found **{len(owner_stale)}** note(s) past their freshness threshold.",
        "",
        "| Title | Days Overdue | Decay Tier | Action |",
        "|---|---|---|---|",
    ]
    for item in owner_stale[:50]:  # 최대 50개로 제한
        title = str(item.get("title") or item.get("path") or "?")[:60]
        lines.append(
            f"| [{title}]({item.get('path','')}) "
            f"| {item.get('days_overdue', 0)} "
            f"| {item.get('decay_tier','general')} "
            f"| {item.get('suggested_action','')} |"
        )

    summary_body = "\n".join(lines)
    result_summary = f"Found {len(owner_stale)} stale note(s) for owner '{owner}'"

    if dry_run:
        return result_summary

    today_str = _dt.now(_UTC).date().isoformat()
    safe_owner = re.sub(r"[^\w\-]", "_", owner)
    result_path = f"personal_vault/projects/personal/{safe_owner}/stale_scans/stale-scan-{today_str}.md"
    try:
        write_document(
            path=result_path,
            body=summary_body,
            title=f"Stale Note Scan {today_str}",
            kind="reference",
            metadata={"owner": owner, "visibility": "private", "generated_by": "busagwan"},
        )
        return f"{result_summary} — summary written to {result_path}"
    except Exception as exc:
        return f"{result_summary} — failed to write summary: {exc}"


_MAX_REVIEW_ATTEMPTS = 3


def _is_llm_failure(reply: str) -> bool:
    """ollama 응답이 에러인지 판별."""
    return reply.startswith("부사관") and ("실패" in reply or "응답을 만들지 못했다" in reply)


def _verify_evidence_paths(evidence_paths: list[str]) -> list[str]:
    """evidence_paths 접근 가능 여부 확인. URL은 HEAD 요청, vault path는 load 시도."""
    issues: list[str] = []
    for item in evidence_paths[:4]:
        item_str = str(item).strip()
        if not item_str:
            continue
        if item_str.startswith("http://") or item_str.startswith("https://"):
            try:
                req = urlrequest.Request(item_str, method="HEAD", headers={
                    "User-Agent": "OpenAkashic-Subordinate/1.0 (+https://knowledge.openakashic.com)",
                })
                with urlrequest.urlopen(req, timeout=10) as resp:
                    if resp.status >= 400:
                        issues.append(f"URL unreachable ({resp.status}): {item_str}")
            except Exception as exc:
                issues.append(f"URL unreachable: {item_str} — {exc}")
        else:
            try:
                load_document(item_str)
            except Exception:
                issues.append(f"evidence note not found: {item_str}")
    return issues


def _review_publication_request(path: str) -> dict[str, Any]:
    request_doc = load_document(path)
    fm = request_doc.frontmatter

    # ── 재시도 카운터 확인 ──
    attempt = int(fm.get("subordinate_review_attempts") or 0)
    if attempt >= _MAX_REVIEW_ATTEMPTS:
        # 이미 최대 시도 — escalated 상태여야 함. 중복 처리 방지.
        return {"kind": "review_publication_request", "path": path, "recommendation": "escalated"}

    source_path = str(fm.get("source_path") or "")
    try:
        source_doc = load_document(source_path) if source_path else None
    except Exception:
        source_doc = None

    # ── evidence 접근 가능 여부 검증 ──
    evidence_paths = fm.get("evidence_paths") or []
    evidence_issues = _verify_evidence_paths(evidence_paths)

    evidence_notes: list[str] = []
    for item in evidence_paths[:4]:
        try:
            evidence_doc = load_document(str(item))
            evidence_notes.append(f"- {evidence_doc.frontmatter.get('title') or evidence_doc.path}: {evidence_doc.body[:280]}")
        except Exception:
            evidence_notes.append(f"- {item}")

    try:
        from app.agent_memory import before_task_context as _before_ctx
        title_str = str(fm.get('title') or '')
        ctx = _before_ctx("busagwan", title_str, current_note_path=source_path or None)
        mem_block = ctx.get("combined") or ""
    except Exception:
        mem_block = ""

    evidence_issue_block = ""
    if evidence_issues:
        evidence_issue_block = "## Evidence Verification Issues\n" + "\n".join(f"- {i}" for i in evidence_issues)

    prompt = "\n\n".join(
        [
            "너는 OpenAkashic의 부사관이다. publication request의 1차 리뷰를 아주 짧고 실무적으로 작성한다.",
            "반드시 approved 또는 rejected 중 하나를 결정해야 한다. 애매하면 approved로 통과시키고 사관이 최종 판단한다.",
            "evidence URL이 접근 불가하면 rejected 한다.",
            f"Request note title: {fm.get('title') or request_doc.path}",
            f"Request body:\n{request_doc.body[:2000]}",
            f"Source note:\n{(source_doc.body[:2500] if source_doc else '없음')}",
            "Evidence:\n" + ("\n".join(evidence_notes) if evidence_notes else "- none"),
            evidence_issue_block or "",
            mem_block or "## 메모리 (비어있음)",
            "출력 형식:\nRecommendation: <approved|rejected>\nReason:\n- ...\n- ...\nReview Summary:\n...",
        ]
    )
    reply = _ollama_generate(prompt)
    attempt += 1

    # ── LLM 실패 → 재시도 대기 or escalation ──
    if _is_llm_failure(reply):
        next_fm = dict(fm)
        next_fm["subordinate_review_attempts"] = attempt
        next_fm["subordinate_last_attempt_at"] = _now_iso()
        if attempt >= _MAX_REVIEW_ATTEMPTS:
            # 최대 재시도 초과 → 사관에게 에스컬레이션
            next_fm["subordinate_recommendation"] = "escalated"
            set_publication_status(
                path=path, status="escalated",
                decider=SUBORDINATE_IDENTITY["nickname"],
                reason=f"부사관 LLM {attempt}회 실패 — 사관 수동 리뷰 필요: {reply[:200]}",
            )
            append_section(
                path,
                f"Subordinate Review Failed {_now_iso()}",
                f"- LLM 호출 {attempt}회 실패. 사관에게 에스컬레이션.\n- 마지막 오류: {reply[:300]}",
            )
            write_document(path=path, body=request_doc.body, metadata=next_fm, allow_owner_change=True)
            return {"kind": "review_publication_request", "path": path, "recommendation": "escalated"}
        else:
            # 재시도 대기 — 상태/추천은 변경하지 않음, 다음 사이클에서 재시도
            write_document(path=path, body=request_doc.body, metadata=next_fm, allow_owner_change=True)
            logger.info("_review_publication_request: LLM failed (attempt %d/%d), will retry: %s",
                        attempt, _MAX_REVIEW_ATTEMPTS, path)
            return {"kind": "review_publication_request", "path": path, "recommendation": "retry_pending",
                    "attempt": attempt}

    # ── 정상 LLM 응답 파싱 ──
    recommendation_match = re.search(r"Recommendation:\s*(\w+)", reply, flags=re.IGNORECASE)
    recommendation = (recommendation_match.group(1).strip().lower() if recommendation_match else "approved")
    if recommendation not in {"approved", "rejected"}:
        recommendation = "approved"  # 정상 응답인데 형식만 안 맞으면 사관에게 위임

    append_section(
        path,
        f"Subordinate First Review {_now_iso()}",
        "\n".join(
            [
                f"- reviewer: `{SUBORDINATE_IDENTITY['nickname']}`",
                f"- recommendation: `{recommendation}`",
                *(f"- evidence issue: {i}" for i in evidence_issues),
                "",
                reply.strip(),
            ]
        ),
    )
    updated = set_publication_status(
        path=path,
        status=recommendation if recommendation != "approved" else "reviewing",
        decider=SUBORDINATE_IDENTITY["nickname"],
        reason=reply[:500],
    )
    next_frontmatter = dict(updated.frontmatter)
    next_frontmatter["subordinate_reviewed_at"] = _now_iso()
    next_frontmatter["subordinate_reviewed_by"] = SUBORDINATE_IDENTITY["nickname"]
    next_frontmatter["subordinate_recommendation"] = recommendation
    next_frontmatter["subordinate_review_attempts"] = attempt
    write_document(path=path, body=updated.body, metadata=next_frontmatter, allow_owner_change=True)
    _remember_subordinate_note(path, reply, task_kind="review_publication_request")
    return {"kind": "review_publication_request", "path": path, "recommendation": recommendation}


def _draft_capsule(source_path: str, *, auto_request: bool) -> dict[str, Any]:
    if not source_path:
        raise ValueError("source_path is required")
    source = load_document(source_path)
    title = str(source.frontmatter.get("title") or Path(source.path).stem)
    prompt = "\n\n".join(
        [
            "너는 OpenAkashic의 부사관이다. 아래 source note를 바탕으로 public-facing capsule 초안을 만든다.",
            "과도한 주장보다 실전 결과, evidence link placeholder, caveat를 짧게 정리한다.",
            f"Source title: {title}",
            f"Source body:\n{source.body[:4000]}",
            "출력은 마크다운 본문만 작성하고, 최소 섹션은 Summary, Outcome, Evidence Links, Practical Use, Reuse 를 포함한다.",
        ]
    )
    body = _ollama_generate(prompt)
    project = str(source.frontmatter.get("project") or "ops/librarian")
    folder = str(Path(source.path).parent)
    capsule_title = f"{title} Capsule"
    suggested = suggest_note_path("capsule", capsule_title, folder, None, project)
    doc = write_document(
        path=suggested,
        title=capsule_title,
        kind="capsule",
        project=project,
        status="draft",
        tags=["capsule", "subordinate", "draft"],
        related=[title],
        body=body,
        metadata={
            "owner": SAGWAN_SYSTEM_OWNER,
            "visibility": "private",
            "publication_status": "none",
            "created_by": SUBORDINATE_IDENTITY["nickname"],
            "generated_by": SUBORDINATE_IDENTITY["nickname"],
            "original_owner": str(source.frontmatter.get("owner") or ""),
            "seed_path": source_path,
        },
        allow_owner_change=True,
    )
    request_data = None
    if auto_request:
        request_data = request_publication(
            path=doc.path,
            requester=SUBORDINATE_IDENTITY["nickname"],
            rationale=f"Auto-requested from subordinate capsule draft (source: {source_path})",
            evidence_paths=[source.path],
        ).__dict__
    _remember_subordinate_note(source_path, f"Created capsule draft at {doc.path}", task_kind="draft_capsule")
    return {"path": doc.path, "request": request_data}


def _draft_claim(source_path: str, *, auto_request: bool) -> list[dict[str, Any]]:
    """소스 노트에서 원자적(atomic) 사실 주장(claim)을 추출해 kind=claim 노트를 생성한다.

    claim의 설계 철학:
    - 하나의 노트 = 하나의 주장.  측정/실험/관찰 결과에서 가장 잘 나온다.
    - 주장은 falsifiable 해야 하고, Scope/Caveats 가 명시되어야 한다.
    - busagwan이 소스 본문에서 최대 _MAX_CLAIMS_PER_SOURCE 개의 원자 주장을 추출한다.
    """
    _MAX_CLAIMS_PER_SOURCE = 3

    if not source_path:
        raise ValueError("source_path is required")
    source = load_document(source_path)
    source_title = str(source.frontmatter.get("title") or Path(source.path).stem)
    project = str(source.frontmatter.get("project") or "ops/librarian")

    prompt = "\n\n".join([
        "너는 OpenAkashic의 부사관이다. 아래 source note에서 공개 가능한 원자적 사실 주장(atomic claim)을 추출한다.",
        "규칙:",
        f"- 최대 {_MAX_CLAIMS_PER_SOURCE}개의 claim만 추출한다.",
        "- 각 claim은 단일하고 검증 가능(falsifiable)한 주장 하나만 담는다.",
        "- 측정값·비교·실험 결과·정량적 관찰이 있는 경우 우선한다.",
        "- 각 claim은 JSON 오브젝트로 출력한다. 형식은 아래와 같다:",
        '  {"title": "...", "claim": "...", "scope": "...", "caveats": "..."}',
        "- JSON 오브젝트 목록을 JSON 배열로 반환한다. 다른 텍스트는 출력하지 않는다.",
        f"Source title: {source_title}",
        f"Source body:\n{source.body[:4000]}",
    ])

    raw = _ollama_generate(prompt)

    # JSON 파싱 — ollama가 마크다운 코드블록으로 감쌀 수도 있으므로 양쪽을 시도
    claims_data: list[dict] = []
    for candidate in (raw, raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                claims_data = [c for c in parsed if isinstance(c, dict) and c.get("claim")]
                break
        except (json.JSONDecodeError, ValueError):
            continue

    if not claims_data:
        logger.warning("_draft_claim: no valid claims extracted from %s — raw:\n%s", source_path, raw[:400])
        return []

    created: list[dict[str, Any]] = []
    for claim_obj in claims_data[:_MAX_CLAIMS_PER_SOURCE]:
        claim_title = str(claim_obj.get("title") or f"[Claim] {source_title}")
        claim_text = str(claim_obj.get("claim") or "")
        scope_text = str(claim_obj.get("scope") or "이 소스 맥락에 한함")
        caveats_text = str(claim_obj.get("caveats") or "없음")

        body = "\n\n".join([
            "## Summary",
            claim_text,
            "## Claim",
            claim_text,
            "## Evidence Links",
            f"- [[{source_title}]]({source_path})",
            "## Scope",
            scope_text,
            "## Caveats",
            caveats_text,
        ])

        folder = str(Path(source_path).parent)
        suggested = suggest_note_path("claim", claim_title, folder, None, project)
        try:
            doc = write_document(
                path=suggested,
                title=claim_title,
                kind="claim",
                project=project,
                status="draft",
                tags=["claim", "subordinate", "draft"],
                related=[source_title],
                body=body,
                metadata={
                    "owner": SAGWAN_SYSTEM_OWNER,
                    "visibility": "private",
                    "publication_status": "none",
                    "created_by": SUBORDINATE_IDENTITY["nickname"],
                    "generated_by": SUBORDINATE_IDENTITY["nickname"],
                    "original_owner": str(source.frontmatter.get("owner") or ""),
                    "claim_source": source_path,
                    "seed_path": source_path,
                },
                allow_owner_change=True,
            )
        except Exception as exc:
            logger.warning("_draft_claim: failed to write claim note: %s", exc)
            continue

        request_data = None
        if auto_request:
            try:
                request_data = request_publication(
                    path=doc.path,
                    requester=SUBORDINATE_IDENTITY["nickname"],
                    rationale="Auto-requested from subordinate claim draft",
                    evidence_paths=[source_path],
                ).__dict__
            except Exception as exc:
                logger.warning("_draft_claim: pub request failed: %s", exc)

        created.append({"path": doc.path, "request": request_data})

    _remember_subordinate_note(
        source_path,
        f"Created {len(created)} claim draft(s): {[c['path'] for c in created]}",
        task_kind="draft_claim",
    )
    return created


def _sync_published_notes_to_core_api(*, limit: int = 10) -> str:
    """
    publication_status=published이고 core_api_id가 없는 kind=capsule/claim 노트를
    Core API로 동기화한다. Busagwan 주기 태스크에서 호출.
    """
    from app.vault import list_note_paths, load_document, write_document

    synced = []
    errors = []
    count = 0
    for note_path in list_note_paths():
        if count >= limit:
            break
        try:
            doc = load_document(note_path)
        except Exception:
            continue
        fm = doc.frontmatter
        if str(fm.get("publication_status") or "").lower() != "published":
            continue
        if str(fm.get("kind") or "").lower() not in {"capsule", "claim", "reference", "evidence"}:
            continue
        if fm.get("core_api_id"):
            continue
        core_api_id = sync_published_note(frontmatter=fm, body=doc.body, note_path=note_path)
        count += 1
        if core_api_id:
            next_fm = dict(fm)
            next_fm["core_api_id"] = core_api_id
            try:
                write_document(path=note_path, body=doc.body, metadata=next_fm, allow_owner_change=True)
                synced.append(note_path)
            except Exception as exc:
                logger.error("sync_to_core_api: failed to persist core_api_id for %s: %s", note_path, exc)
                errors.append(note_path)
        else:
            errors.append(note_path)
    result_summary = f"sync_to_core_api: {len(synced)} synced, {len(errors)} failed"
    _remember_subordinate_note("sync_to_core_api", result_summary, task_kind="sync_to_core_api")
    return result_summary


def _gap_slug(query: str) -> str:
    """GAP 노트 슬러그 — 한글/CJK 보존, 6자리 해시 접미사로 절단 충돌 방지."""
    import hashlib as _hl
    slug = re.sub(r"[^0-9a-zA-Z가-힣ぁ-んァ-ン一-龥]+", "-", query.strip()).strip("-").lower()
    slug = slug[:50] or "query"
    suffix = _hl.md5(query.lower().strip().encode()).hexdigest()[:6]
    return f"{slug}-{suffix}"


def _analyze_search_gaps(*, max_new: int = 10) -> str:
    """
    gap-queries.jsonl에서 검색 결과가 없었던 쿼리를 읽어
    doc/knowledge-gaps/ 폴더에 gap 노트를 생성하거나 miss_count를 갱신한다.
    처리한 항목만 JSONL에서 제거(rotate) — 미처리 항목은 다음 사이클로 이월.

    수정 이력:
    - GAP_FOLDER: personal_vault/... → doc/knowledge-gaps (shared, 모든 에이전트 검색 가능)
    - 슬러그: ASCII only → 한글/CJK 보존 + 해시 접미사로 충돌 방지
    - miss_count: 기존 노트 miss_count 갱신 (신규 생성만 하던 것 개선)
    - leftover: processed_norms 기반 — max_new 초과 쿼리가 사라지던 버그 수정
    """
    from app.mcp_server import gap_queries_path

    gap_file = gap_queries_path()
    if not gap_file.exists():
        return "analyze_search_gaps: gap-queries.jsonl not found — nothing to process"

    # 1. 파일 읽기
    with gap_file.open("r", encoding="utf-8") as fh:
        raw_lines = fh.readlines()

    if not raw_lines:
        return "analyze_search_gaps: no gap queries recorded yet"

    # parse + 빈도 카운트 (case-insensitive, strip)
    seen_queries: dict[str, tuple[str, int]] = {}  # normalized → (original, count)
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            q = str(entry.get("query") or "").strip()
            if q:
                norm = q.lower()
                prev_orig, prev_cnt = seen_queries.get(norm, (q, 0))
                seen_queries[norm] = (prev_orig, prev_cnt + 1)
        except json.JSONDecodeError:
            continue

    if not seen_queries:
        gap_file.write_text("", encoding="utf-8")
        return "analyze_search_gaps: no valid queries found"

    # 2. gap 노트 생성 또는 miss_count 갱신
    GAP_FOLDER = "doc/knowledge-gaps"
    existing_paths = set(list_note_paths())
    new_created: list[str] = []
    updated: list[str] = []
    processed_norms: set[str] = set()

    for norm_q, (original_q, miss_count) in list(seen_queries.items()):
        if len(new_created) >= max_new:
            break  # 미처리 쿼리는 JSONL에 남겨 다음 사이클로 이월

        slug = _gap_slug(original_q)
        note_path = f"{GAP_FOLDER}/{slug}.md"

        if note_path in existing_paths:
            # 기존 노트: miss_count + last_queried 갱신
            processed_norms.add(norm_q)
            try:
                existing_doc = load_document(note_path)
                new_count = int(existing_doc.frontmatter.get("miss_count") or 0) + miss_count
                next_fm = dict(existing_doc.frontmatter)
                next_fm["miss_count"] = new_count
                next_fm["last_queried"] = _now_iso()
                write_document(
                    path=note_path,
                    body=existing_doc.body,
                    metadata=next_fm,
                    metadata_replace=True,
                    allow_owner_change=True,
                )
                updated.append(note_path)
            except Exception as exc:
                logger.warning("analyze_search_gaps: failed to update gap note %s: %s", note_path, exc)
            continue

        # 신규 노트 생성
        body = "\n".join([
            "## Summary",
            f"에이전트가 `{original_q}` 쿼리로 검색했으나 관련 노트가 없었습니다.",
            "",
            "## Gap Details",
            f"- **Query:** `{original_q}`",
            f"- **Detected by:** analyze_search_gaps ({_now_iso()})",
            "",
            "## Suggested Action",
            "이 주제에 대한 capsule 또는 reference 노트 작성을 검토하세요.",
            "- 관련 자료 수집 후 `upsert_note` (kind=reference) 로 evidence note 작성",
            "- 요약 synthesis 후 `upsert_note` (kind=capsule) 작성",
            "- `request_note_publication` 으로 공개 요청",
        ])
        try:
            write_document(
                path=note_path,
                title=f"[Gap] {original_q[:80]}",
                kind="request",
                project="openakashic",
                status="draft",
                tags=["gap", "knowledge-gap", "subordinate"],
                related=[],
                body=body,
                metadata={
                    "owner": SAGWAN_SYSTEM_OWNER,
                    "visibility": "shared",
                    "publication_status": "none",
                    "created_by": SUBORDINATE_IDENTITY["nickname"],
                    "gap_query": original_q,
                    "miss_count": miss_count,
                    "last_queried": _now_iso(),
                },
                allow_owner_change=True,
            )
            new_created.append(note_path)
            processed_norms.add(norm_q)
            existing_paths.add(note_path)
        except Exception as exc:
            logger.warning("analyze_search_gaps: failed to create gap note %s: %s", note_path, exc)

    # 3. 처리된 쿼리만 JSONL에서 제거 (미처리 쿼리는 다음 사이클로 이월)
    leftover_lines = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            q = str(entry.get("query") or "").strip()
            if q.lower() not in processed_norms:
                leftover_lines.append(line)
        except json.JSONDecodeError:
            pass  # 손상된 줄 폐기

    gap_file.write_text("\n".join(leftover_lines) + ("\n" if leftover_lines else ""), encoding="utf-8")

    summary = (
        f"analyze_search_gaps: {len(new_created)} new, {len(updated)} updated"
        f" — {len(seen_queries)} unique queries, {len(leftover_lines)} deferred to next cycle"
    )
    _remember_subordinate_note("analyze_search_gaps", summary, task_kind="analyze_search_gaps")
    return summary


def _crawl_url_to_note(url: str, *, folder: str | None = None, project: str | None = None) -> str:
    if not url:
        raise ValueError("url is required")
    html_text = _fetch_url_text(url)
    title = _extract_html_title(html_text) or url
    summary_prompt = "\n\n".join(
        [
            "너는 OpenAkashic의 부사관이다. 아래 웹 문서를 참고용 reference/evidence 초안으로 정리한다.",
            "과장 없이 핵심 요약, source, practical reuse 포인트를 짧게 정리한다.",
            f"URL: {url}",
            f"Raw text excerpt:\n{_strip_html(html_text)[:5000]}",
            "출력은 마크다운 본문만 작성하고 Summary, Source, Reference, Reuse 섹션을 포함한다.",
        ]
    )
    body = _ollama_generate(summary_prompt)
    note_title = f"{title} Reference"
    target_path = suggest_note_path("reference", note_title, folder, "shared", project or "reference")
    doc = write_document(
        path=target_path,
        title=note_title,
        kind="reference",
        project=project or "reference",
        status="active",
        tags=["external", "subordinate", "reference"],
        related=[],
        body=body + f"\n\n## Source\n- url: `{url}`\n",
        metadata={
            "owner": SAGWAN_SYSTEM_OWNER,
            "visibility": "private",
            "publication_status": "none",
            "created_by": SUBORDINATE_IDENTITY["nickname"],
        },
        allow_owner_change=True,
    )
    _remember_subordinate_note(url, f"Crawled source into {doc.path}", task_kind="crawl_url")
    return doc.path


def _fetch_url_text(url: str) -> str:
    req = urlrequest.Request(
        url,
        headers={
            "User-Agent": "OpenAkashic-Subordinate/1.0 (+https://knowledge.openakashic.com)",
            "Accept-Language": "ko,en;q=0.9,ja;q=0.8",
        },
    )
    with urlrequest.urlopen(req, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _extract_html_title(raw: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _strip_html(raw: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def _subordinate_prompt(message: str, relevant: list[dict[str, Any]], thread: list[dict[str, str]]) -> str:
    prior = "\n".join(f"{item.get('role','user')}: {item.get('content','')}" for item in thread[-8:])
    context = "\n\n".join(
        f"[{item['title']}] {item['path']}\nSummary: {item['summary']}\nBody: {item['body'][:1200]}"
        for item in relevant[:6]
    )
    return "\n\n".join(
        [
            "너는 OpenAkashic의 부사관이다.",
            "반복 작업, 1차 검토, 문서 정리, 크롤링 결과 요약, capsule 초안 작성에 특화된 관리자급 보조 에이전트다.",
            "하지만 exec 같은 시스템 명령은 쓰지 않고, 아카식 지식 도구와 로컬 ollama 모델만 사용한다.",
            "답변은 짧고 구조적이며, 가능하면 다음 액션이나 제안 태스크를 함께 제시한다.",
            f"## Prior Thread\n{prior or '없음'}",
            f"## Relevant Notes\n{context or '없음'}",
            f"## User Message\n{message}",
        ]
    )


def _subordinate_tool_definitions() -> list[dict[str, Any]]:
    """부사관이 tool-loop에서 사용할 수 있는 도구 스키마 목록."""
    return [
        {
            "type": "function",
            "function": {
                "name": "search_notes",
                "description": "Search OpenAkashic notes by keyword.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_note",
                "description": "Read a note by its vault path.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "append_note_section",
                "description": "Append a new H2 section to an existing note.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "heading": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "heading", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "upsert_note",
                "description": "Create or overwrite a note.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "body": {"type": "string"},
                        "title": {"type": "string"},
                        "kind": {"type": "string"},
                        "project": {"type": "string"},
                    },
                    "required": ["path", "body"],
                },
            },
        },
    ]


def _run_subordinate_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """부사관 tool-loop에서 실제 도구를 실행한다."""
    if name == "search_notes":
        return search_closed_notes(arguments.get("query", ""), limit=int(arguments.get("limit", 6)))
    if name == "read_note":
        note = get_closed_note(arguments.get("path", ""))
        return note or {"error": "Note not found"}
    if name == "append_note_section":
        doc = append_section(arguments["path"], arguments["heading"], arguments["content"])
        return {"path": doc.path, "title": doc.frontmatter.get("title")}
    if name == "upsert_note":
        doc = write_document(
            path=arguments["path"],
            body=arguments["body"],
            title=arguments.get("title"),
            kind=arguments.get("kind"),
            project=arguments.get("project"),
            metadata={"owner": SAGWAN_SYSTEM_OWNER, "created_by": SUBORDINATE_IDENTITY["nickname"]},
        )
        return {"path": doc.path, "title": doc.frontmatter.get("title")}
    return {"error": f"Unknown tool: {name}"}


def _ollama_tool_loop(
    message: str,
    relevant: list[dict[str, Any]],
    thread: list[dict[str, str]],
    settings: dict[str, Any],
    max_turns: int = 4,
) -> dict[str, Any]:
    """
    Ollama /api/chat + tool_calls를 이용한 부사관 tool-loop.
    모델이 tool calling을 지원하지 않거나 tools 응답이 없으면 단순 generate로 폴백한다.
    """
    if settings["provider"].strip().lower() != "ollama":
        return {"message": "부사관 provider가 ollama로 설정되지 않아 응답을 만들지 못했다.", "tool_events": []}

    system_prompt = _subordinate_prompt(message, relevant, thread)
    tool_events: list[dict[str, Any]] = []
    tool_defs = _subordinate_tool_definitions()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]

    base_url = settings["base_url"].rstrip("/")
    chat_url = f"{base_url}/api/chat"

    for _turn in range(max_turns):
        payload = json.dumps(
            {
                "model": settings["model"],
                "messages": messages,
                "tools": tool_defs,
                "stream": False,
                "options": {"temperature": 0.15, "num_predict": 512, "num_ctx": 4096},
            }
        ).encode("utf-8")
        req = urlrequest.Request(
            chat_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=180) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urlerror.URLError as exc:
            return {"message": f"부사관 모델 호출에 실패했다: {exc}", "tool_events": tool_events}

        msg = data.get("message") or {}
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            # 최종 응답 또는 tool calling 미지원
            # gemma4 계열은 실제 답변을 "thinking" 필드에 넣고 "content"를 비우기도 한다.
            text = str(msg.get("content") or msg.get("thinking") or "").strip()
            if not text:
                text = "부사관이 응답을 만들지 못했다."
            return {"message": text, "tool_events": tool_events}

        # 도구 호출 처리
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})
        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            try:
                result = _run_subordinate_tool(name, dict(args))
            except Exception as exc:
                result = {"error": f"{type(exc).__name__}: {exc}"}
            tool_events.append({"name": name, "arguments": args, "result": result})
            messages.append({
                "role": "tool",
                "content": json.dumps(result, ensure_ascii=False),
            })

    # 최대 반복 도달 — 마지막 메시지 반환 (gemma4 thinking 필드 포함)
    last_content = ""
    for m in reversed(messages):
        if m.get("role") == "assistant":
            last_content = str(m.get("content") or m.get("thinking") or "").strip()
            if last_content:
                break
    return {"message": last_content or "부사관이 최대 반복(4)에 도달했다.", "tool_events": tool_events}


def _ollama_generate(prompt: str) -> str:
    settings = load_subordinate_settings()
    if settings["provider"].strip().lower() != "ollama":
        return "부사관 provider가 ollama로 설정되지 않아 응답을 만들지 못했다."
    payload = json.dumps(
        {
            "model": settings["model"],
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        }
    ).encode("utf-8")
    req = urlrequest.Request(
        urlparse.urljoin(settings["base_url"].rstrip("/") + "/", "api/generate"),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urlerror.URLError as exc:
        return f"부사관 로컬 모델 호출에 실패했다: {exc}"
    return str(data.get("response") or "").strip() or "부사관이 응답을 만들지 못했다."


def _load_queue() -> dict[str, Any]:
    """큐 파일을 읽는다. 호출자는 반드시 _QUEUE_LOCK 을 보유한 상태여야 한다."""
    path = subordinate_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        queue: dict[str, Any] = {"tasks": []}
        path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return queue
    try:
        return json.loads(path.read_text(encoding="utf-8") or '{"tasks":[]}')
    except json.JSONDecodeError:
        return {"tasks": []}


def _save_queue(queue: dict[str, Any]) -> None:
    """큐 파일을 원자적으로 쓴다. 호출자는 반드시 _QUEUE_LOCK 을 보유한 상태여야 한다.
    fcntl.flock 으로 다른 프로세스(컨테이너 외부 접근 등)도 차단."""
    path = subordinate_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as fp:
        fcntl.flock(fp, fcntl.LOCK_EX)
        try:
            fp.seek(0)
            fp.truncate()
            fp.write((json.dumps(queue, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            fp.flush()
        finally:
            fcntl.flock(fp, fcntl.LOCK_UN)


def _task_dedup_key(kind: str, payload: dict[str, Any]) -> str | None:
    """kind 별 중복 판별 키. None 이면 dedup 하지 않음."""
    if kind == "crawl_url":
        return str(payload.get("url") or "").strip()
    if kind == "draft_capsule":
        return str(payload.get("source_path") or "").strip()
    return None  # sync_to_core_api 등은 중복 허용


def _prune_done_tasks(queue: dict[str, Any]) -> int:
    """_QUEUE_PRUNE_DAYS 보다 오래된 done/failed 태스크를 큐에서 제거. 제거 수 반환."""
    cutoff = (datetime.now(UTC) - timedelta(days=_QUEUE_PRUNE_DAYS)).isoformat().replace("+00:00", "Z")
    before = len(queue["tasks"])
    queue["tasks"] = [
        t for t in queue["tasks"]
        if not (
            t.get("status") in {"done", "failed"}
            and str(t.get("finished_at") or "") < cutoff
        )
    ]
    return before - len(queue["tasks"])


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _relevant_context(message: str) -> list[dict[str, Any]]:
    # 자신의 메모리 + 사서장 메모리(교차 공유) + 쿼리 검색 결과
    paths = [
        SUBORDINATE_PROFILE_PATH,
        SUBORDINATE_PLAYBOOK_PATH,
        SUBORDINATE_MEMORY_PATH,
        LIBRARIAN_MEMORY_PATH,  # 사서장 판단 이력 참조
    ]
    notes: dict[str, dict[str, Any]] = {}
    for path in paths:
        note = get_closed_note(path)
        if note:
            notes[path] = {
                "path": note["path"],
                "title": note["title"],
                "summary": note["summary"],
                "body": note["body"][:600],
            }
    for item in search_closed_notes(message, limit=3).get("results", []):
        note = get_closed_note(item["path"])
        if note:
            notes.setdefault(
                note["path"],
                {"path": note["path"], "title": note["title"], "summary": note["summary"], "body": note["body"][:600]},
            )
    return list(notes.values())[:5]


def _remember_subordinate_note(subject: str, result: str, *, task_kind: str) -> None:
    try:
        from app.agent_memory import remember as _agent_remember
        _agent_remember("busagwan", subject=subject, outcome=result, kind=task_kind)
    except Exception as exc:
        logger.warning("busagwan agent_memory.remember failed, falling back: %s", exc)
        append_section(
            SUBORDINATE_MEMORY_PATH,
            f"{_now_iso()} {task_kind}",
            "\n".join(
                [
                    f"- subject: {subject[:300]}",
                    f"- takeaway: {result[:900]}",
                ]
            ),
        )


def _ensure_seed_note(path: str, *, title: str, kind: str, body: str) -> None:
    try:
        load_document(path)
        return
    except Exception:
        pass
    ensure_folder(str(Path(path).parent))
    write_document(
        path=path,
        title=title,
        kind=kind,
        project="ops/librarian",
        status="active",
        tags=["librarian", "subordinate", "agent"],
        related=["Librarian Profile", "Librarian Policy"],
        body=body,
        metadata={
            "owner": SAGWAN_SYSTEM_OWNER,
            "visibility": "private",
            "publication_status": "none",
            "created_by": SUBORDINATE_IDENTITY["nickname"],
        },
        allow_owner_change=True,
    )
