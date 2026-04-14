from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest
from uuid import uuid4

from app.config import get_settings
from app.site import get_closed_note, search_closed_notes
from app.vault import (
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
SUBORDINATE_TASK_TYPES = ("crawl_url", "draft_capsule")


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
        "model": "gemma4:e4b",
        "enabled": True,
        "interval_sec": 900,
        "max_tasks_per_run": 2,
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
    prompt = _subordinate_prompt(message, relevant, thread or [])
    reply = _ollama_generate(prompt)
    _remember_subordinate_note(message, reply, task_kind="chat")
    return {
        "message": reply,
        "status": "ok",
        "context_notes": relevant,
        "model": load_subordinate_settings()["model"],
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
    queue = _load_queue()
    task = {
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
        processed.extend(_run_publication_first_reviews(limit=settings["max_tasks_per_run"]))

    if len(processed) >= settings["max_tasks_per_run"]:
        return {"status": "ok", "reason": reason, "processed": processed}

    queue = _load_queue()
    now = datetime.now(UTC)
    for task in queue["tasks"]:
        if len(processed) >= settings["max_tasks_per_run"]:
            break
        if task.get("status") != "pending":
            continue
        if task.get("kind") not in settings["enabled_task_types"]:
            continue
        run_after = _parse_iso(str(task.get("run_after") or task.get("created_at") or _now_iso()))
        if run_after > now:
            continue
        task["status"] = "running"
        task["started_at"] = _now_iso()
        _save_queue(queue)
        try:
            result_path = _run_task(task, settings)
            task["status"] = "done"
            task["finished_at"] = _now_iso()
            task["result_path"] = result_path or ""
            task["last_error"] = ""
        except Exception as exc:
            task["status"] = "failed"
            task["finished_at"] = _now_iso()
            task["last_error"] = str(exc)
        processed.append(dict(task))
        _save_queue(queue)

    return {"status": "ok", "reason": reason, "processed": processed}


def _run_publication_first_reviews(*, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for request in list_publication_requests(status="requested"):
        if len(results) >= limit:
            break
        document = load_document(request.path)
        if str(document.frontmatter.get("subordinate_reviewed_at") or "").strip():
            continue
        result = _review_publication_request(request.path)
        results.append(result)
    return results


def _run_task(task: dict[str, Any], settings: dict[str, Any]) -> str:
    kind = str(task.get("kind") or "")
    payload = dict(task.get("payload") or {})
    if kind == "crawl_url":
        return _crawl_url_to_note(payload.get("url") or "", folder=payload.get("folder"), project=payload.get("project"))
    if kind == "draft_capsule":
        result = _draft_capsule(payload.get("source_path") or "", auto_request=settings["auto_request_publication_for_capsules"])
        return str(result.get("path") or "")
    raise ValueError(f"Unsupported subordinate task: {kind}")


def _review_publication_request(path: str) -> dict[str, Any]:
    request_doc = load_document(path)
    source_path = str(request_doc.frontmatter.get("source_path") or "")
    source_doc = load_document(source_path) if source_path else None
    evidence_paths = request_doc.frontmatter.get("evidence_paths") or []
    evidence_notes: list[str] = []
    for item in evidence_paths[:4]:
        try:
            evidence_doc = load_document(str(item))
            evidence_notes.append(f"- {evidence_doc.frontmatter.get('title') or evidence_doc.path}: {evidence_doc.body[:280]}")
        except Exception:
            evidence_notes.append(f"- {item}")
    prompt = "\n\n".join(
        [
            "너는 OpenAkashic의 부사관이다. publication request의 1차 리뷰를 아주 짧고 실무적으로 작성한다.",
            "반드시 근거 부족 여부와 추천 다음 상태를 적는다. 가능한 상태는 reviewing, approved, rejected 중 하나다.",
            f"Request note title: {request_doc.frontmatter.get('title') or request_doc.path}",
            f"Request body:\n{request_doc.body[:2000]}",
            f"Source note:\n{(source_doc.body[:2500] if source_doc else '없음')}",
            "Evidence:\n" + ("\n".join(evidence_notes) if evidence_notes else "- none"),
            "출력 형식:\nRecommendation: <status>\nReason:\n- ...\n- ...\nReview Summary:\n...",
        ]
    )
    reply = _ollama_generate(prompt)
    recommendation_match = re.search(r"Recommendation:\s*(\w+)", reply, flags=re.IGNORECASE)
    recommendation = (recommendation_match.group(1).strip().lower() if recommendation_match else "reviewing")
    if recommendation not in {"reviewing", "approved", "rejected"}:
        recommendation = "reviewing"
    append_section(
        path,
        f"Subordinate First Review {_now_iso()}",
        "\n".join(
            [
                f"- reviewer: `{SUBORDINATE_IDENTITY['nickname']}`",
                f"- recommendation: `{recommendation}`",
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
            "owner": "sagwan",
            "visibility": "private",
            "publication_status": "none",
            "created_by": SUBORDINATE_IDENTITY["nickname"],
        },
        allow_owner_change=True,
    )
    request_data = None
    if auto_request:
        request_data = request_publication(
            path=doc.path,
            requester=SUBORDINATE_IDENTITY["nickname"],
            rationale="Auto-requested from subordinate capsule draft",
            evidence_paths=[source.path],
        ).__dict__
    _remember_subordinate_note(source_path, f"Created capsule draft at {doc.path}", task_kind="draft_capsule")
    return {"path": doc.path, "request": request_data}


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
            "owner": "sagwan",
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
    path = subordinate_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        queue = {"tasks": []}
        path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return queue
    try:
        return json.loads(path.read_text(encoding="utf-8") or '{"tasks":[]}')
    except json.JSONDecodeError:
        return {"tasks": []}


def _save_queue(queue: dict[str, Any]) -> None:
    path = subordinate_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _relevant_context(message: str) -> list[dict[str, Any]]:
    paths = [SUBORDINATE_PROFILE_PATH, SUBORDINATE_PLAYBOOK_PATH, SUBORDINATE_MEMORY_PATH]
    notes: dict[str, dict[str, Any]] = {}
    for path in paths:
        note = get_closed_note(path)
        if note:
            notes[path] = {
                "path": note["path"],
                "title": note["title"],
                "summary": note["summary"],
                "body": note["body"],
            }
    for item in search_closed_notes(message, limit=8).get("results", []):
        note = get_closed_note(item["path"])
        if note:
            notes.setdefault(
                note["path"],
                {"path": note["path"], "title": note["title"], "summary": note["summary"], "body": note["body"]},
            )
    return list(notes.values())[:8]


def _remember_subordinate_note(subject: str, result: str, *, task_kind: str) -> None:
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
            "owner": "sagwan",
            "visibility": "private",
            "publication_status": "none",
            "created_by": SUBORDINATE_IDENTITY["nickname"],
        },
        allow_owner_change=True,
    )
