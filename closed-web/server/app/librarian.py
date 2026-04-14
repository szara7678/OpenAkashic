from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
from typing import Any

from app.auth import librarian_identity_dict
from app.config import get_settings
from app.site import get_closed_note, search_closed_notes
from app.vault import (
    append_section,
    bootstrap_project_workspace,
    ensure_folder,
    list_publication_requests,
    load_document,
    request_publication,
    resolve_note_path,
    set_publication_status,
    write_document,
)


LIBRARIAN_PROFILE_PATH = "personal_vault/projects/ops/librarian/profile/Librarian Profile.md"
LIBRARIAN_POLICY_PATH = "personal_vault/projects/ops/librarian/policy/Librarian Policy.md"
LIBRARIAN_MEMORY_PATH = "personal_vault/projects/ops/librarian/memory/Working Memory.md"
LIBRARIAN_README_PATH = "personal_vault/projects/ops/librarian/README.md"
OPENAKASHIC_REVIEW_PATH = (
    "personal_vault/projects/personal/openakashic/reference/closed-akashic-user-scope-review.md"
)
LIBRARIAN_TOOL_NAMES = (
    "exec_command",
    "search_notes",
    "read_note",
    "append_note_section",
    "upsert_note",
    "request_publication",
    "list_publication_requests",
    "set_publication_status",
)


def librarian_settings_path() -> Path:
    return Path(get_settings().user_store_path).with_name("librarian-settings.json")


def _default_librarian_settings() -> dict[str, Any]:
    settings = get_settings()
    return {
        "provider": settings.librarian_provider,
        "model": settings.librarian_model,
        "base_url": settings.librarian_base_url,
        "reasoning_effort": settings.librarian_reasoning_effort,
        "enabled_tools": list(LIBRARIAN_TOOL_NAMES),
    }


def load_librarian_settings() -> dict[str, Any]:
    defaults = _default_librarian_settings()
    path = librarian_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(defaults, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        raw = {}
    enabled_tools = [
        tool_name
        for tool_name in raw.get("enabled_tools", defaults["enabled_tools"])
        if tool_name in LIBRARIAN_TOOL_NAMES
    ]
    return {
        "provider": str(raw.get("provider") or defaults["provider"]).strip() or defaults["provider"],
        "model": str(raw.get("model") or defaults["model"]).strip() or defaults["model"],
        "base_url": str(raw.get("base_url") or defaults["base_url"]).strip(),
        "reasoning_effort": str(raw.get("reasoning_effort") or defaults["reasoning_effort"]).strip()
        or defaults["reasoning_effort"],
        "enabled_tools": enabled_tools or list(defaults["enabled_tools"]),
    }


def save_librarian_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_librarian_settings()
    next_settings = {
        "provider": str(payload.get("provider") or current["provider"]).strip() or current["provider"],
        "model": str(payload.get("model") or current["model"]).strip() or current["model"],
        "base_url": str(payload.get("base_url") or current["base_url"]).strip(),
        "reasoning_effort": str(payload.get("reasoning_effort") or current["reasoning_effort"]).strip()
        or current["reasoning_effort"],
        "enabled_tools": [
            tool_name
            for tool_name in payload.get("enabled_tools", current["enabled_tools"])
            if tool_name in LIBRARIAN_TOOL_NAMES
        ],
    }
    if not next_settings["enabled_tools"]:
        raise ValueError("At least one librarian tool must stay enabled")
    path = librarian_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(next_settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return next_settings


def ensure_librarian_workspace() -> dict[str, Any]:
    project_key = get_settings().librarian_project.strip() or "ops/librarian"
    result = bootstrap_project_workspace(
        project=project_key,
        title="Librarian",
        summary="사서장 에이전트의 운영 정책, 기억, 플레이북, 활동 로그를 관리하는 작업 공간이다.",
        folders=["profile", "policy", "playbooks", "memory", "activity", "reference"],
        tags=["project", "ops", "librarian", "agent"],
        related=["Agent Guide", "Distributed Agent Memory Contract"],
    )
    _ensure_seed_note(
        LIBRARIAN_PROFILE_PATH,
        title="Librarian Profile",
        kind="reference",
        body="\n".join(
            [
                "## Summary",
                "사서장은 OpenAkashic의 공유/공개 승격, 정리, 연결, 정책 적용을 담당한다.",
                "",
                "## Persona",
                "- 차분하고 규칙을 지키는 운영 사서장",
                "- 공개 가능성과 근거, 재사용성을 최우선으로 본다.",
                "- 사용자의 private 작업 영역은 존중하고, shared/public 레이어만 엄격하게 관리한다.",
                "",
                "## Tools",
                "- exec_command",
                "- search_notes",
                "- read_note",
                "- append_note_section",
                "- upsert_note",
                "",
                "## Reuse",
                "새로운 정책이나 반복되는 판단 기준이 생기면 이 프로필과 플레이북을 갱신한다.",
            ]
        ),
    )
    _ensure_seed_note(
        LIBRARIAN_POLICY_PATH,
        title="Librarian Policy",
        kind="playbook",
        body="\n".join(
            [
                "## Summary",
                "사서장은 private 원문과 public 산출물을 섞지 않고, 공개 승격과 구조 정리만 수행한다.",
                "",
                "## Policy",
                "- private 원문은 사용자가 자유롭게 관리한다.",
                "- public 쓰기는 정책과 권한 검토 뒤에만 수행한다.",
                "- scope는 폴더/맥락 힌트이며 접근 권한이 아니다.",
                "- 모든 새 개인 문서는 현재 토큰 소유자 owner, visibility=private, publication_status=none으로 시작한다.",
                "- public으로 승격된 문서는 owner=sagwan, visibility=public, publication_status=published 관리 문서가 된다.",
                "- 공개는 원문을 직접 공개하지 않고 publication request queue를 통해 capsule/result/evidence summary로 승격한다.",
                "- 근거 없는 공개 승격은 금지한다.",
                "- 장기 메모리는 요약과 재사용 포인트만 남기고 장황한 로그는 줄인다.",
                "",
                "## Reuse",
                "승격 기준, 링크 정책, 권한 정책이 바뀌면 이 문서를 기준 정책으로 갱신한다.",
            ]
        ),
    )
    _ensure_seed_note(
        LIBRARIAN_MEMORY_PATH,
        title="Working Memory",
        kind="reference",
        body="\n".join(
            [
                "## Summary",
                "사서장이 반복 작업에 재사용할 운영 메모와 주의점을 짧게 축적하는 메모다.",
                "",
                "## Reuse",
                "매번 모든 대화를 저장하지 말고, 다음 판단에 실제 도움이 되는 기준과 링크만 남긴다.",
            ]
        ),
    )
    return result


def librarian_status() -> dict[str, Any]:
    ensure_librarian_workspace()
    settings = get_settings()
    runtime = load_librarian_settings()
    return {
        "name": "Librarian",
        "identity": librarian_identity_dict(),
        "project": settings.librarian_project,
        "provider": runtime["provider"],
        "model": runtime["model"],
        "base_url": runtime["base_url"],
        "reasoning_effort": runtime["reasoning_effort"],
        "has_librarian_api_key": settings.has_librarian_api_key,
        "tools": [tool["name"] for tool in _tool_registry(runtime["enabled_tools"])],
        "available_tools": list(LIBRARIAN_TOOL_NAMES),
        "memory_paths": {
            "profile": LIBRARIAN_PROFILE_PATH,
            "policy": LIBRARIAN_POLICY_PATH,
            "working_memory": LIBRARIAN_MEMORY_PATH,
        },
    }


def librarian_chat(message: str, thread: list[dict[str, str]] | None = None) -> dict[str, Any]:
    ensure_librarian_workspace()
    relevant_notes = _relevant_context(message)
    settings = get_settings()
    runtime = load_librarian_settings()
    if runtime["provider"].strip().lower() != "openai-compatible":
        fallback = _codex_style_fallback(message, relevant_notes)
        _remember_interaction(message, fallback, [])
        return {
            "message": fallback,
            "status": "codex_style_runtime_pending",
            "tool_events": [],
            "context_notes": relevant_notes,
            "model": runtime["model"],
        }
    if not settings.has_librarian_api_key:
        fallback = (
            "사서장용 모델 호출 키가 아직 서버 환경에 없어 "
            f"`{runtime['model']}` 호출은 하지 못했다. "
            "대신 관련 노트와 정책 구조는 준비되어 있다."
        )
        _remember_interaction(message, fallback, [])
        return {
            "message": fallback,
            "status": "needs_librarian_api_key",
            "tool_events": [],
            "context_notes": relevant_notes,
            "model": runtime["model"],
        }

    try:
        response = _run_openai_librarian(message, thread or [], relevant_notes)
    except Exception as exc:
        failure = f"사서장 호출 중 오류가 발생했다: {exc}"
        _remember_interaction(message, failure, [])
        return {
            "message": failure,
            "status": "error",
            "tool_events": [],
            "context_notes": relevant_notes,
            "model": runtime["model"],
        }

    _remember_interaction(message, response["message"], response["tool_events"])
    return {
        **response,
        "context_notes": relevant_notes,
        "model": runtime["model"],
        "status": "ok",
    }


def _run_openai_librarian(
    message: str,
    thread: list[dict[str, str]],
    relevant_notes: list[dict[str, Any]],
) -> dict[str, Any]:
    from openai import OpenAI

    settings = get_settings()
    runtime = load_librarian_settings()
    client = OpenAI(
        api_key=settings.librarian_api_key,
        base_url=runtime["base_url"] or None,
    )
    instructions = _librarian_instructions(relevant_notes)
    messages = [{"role": "system", "content": instructions}, *_thread_to_messages(thread)]
    messages.append({"role": "user", "content": message})
    tool_events: list[dict[str, Any]] = []

    for _ in range(6):
        response = client.chat.completions.create(
            model=runtime["model"],
            messages=messages,
            tools=_tool_registry(runtime["enabled_tools"]),
            tool_choice="auto",
        )
        choice = response.choices[0].message
        tool_calls = list(choice.tool_calls or [])
        if not tool_calls:
            break
        messages.append(
            {
                "role": "assistant",
                "content": choice.content or "",
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                    for tool_call in tool_calls
                ],
            }
        )
        for tool_call in tool_calls:
            args = json.loads(tool_call.function.arguments or "{}")
            result = _run_tool(tool_call.function.name, args)
            tool_events.append(
                {
                    "name": tool_call.function.name,
                    "arguments": args,
                    "result": result,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    text = ""
    if "response" in locals():
        final_message = response.choices[0].message
        if isinstance(final_message.content, str):
            text = final_message.content.strip()
        elif final_message.content:
            parts = []
            for part in final_message.content:
                piece = getattr(part, "text", None)
                if piece:
                    parts.append(piece)
            text = "\n".join(parts).strip()
    if not text:
        text = "사서장이 응답을 만들지 못했다."
    return {"message": text, "tool_events": tool_events}


def _codex_style_fallback(message: str, relevant_notes: list[dict[str, Any]]) -> str:
    """Return a useful response while the dedicated Codex-style runtime is wired."""
    runtime = load_librarian_settings()
    notes = "\n".join(
        f"- {item['title']} ({item['path']})" for item in relevant_notes[:4]
    )
    if not notes:
        notes = "- 관련 노트를 아직 찾지 못했다."
    return "\n".join(
        [
            "사서장 런타임은 지금 OpenClaw를 직접 호출하지 않고, 그 구조를 참고한 Codex-style 운용 모드로 설정되어 있다.",
            f"참고 모델 라벨: `{runtime['model']}`",
            "",
            "현재 단계에서는 웹 권한, 메모리 작업공간, 관련 노트 검색, 공개신청 queue를 제공하고, 실제 장기 실행 에이전트 루프는 별도 런타임으로 연결해야 한다.",
            "",
            "관련 컨텍스트:",
            notes,
            "",
            f"요청 기록: {message.strip()[:240]}",
        ]
    )


def _librarian_instructions(relevant_notes: list[dict[str, Any]]) -> str:
    profile = _read_note_safely(LIBRARIAN_PROFILE_PATH)
    policy = _read_note_safely(LIBRARIAN_POLICY_PATH)
    memory = _read_note_safely(LIBRARIAN_MEMORY_PATH)
    notes_block = "\n\n".join(
        [
            f"[{item['title']}] {item['path']}\nSummary: {item['summary']}"
            for item in relevant_notes[:6]
        ]
    )
    return "\n\n".join(
        [
            "너는 OpenAkashic의 사서장이다.",
            "역할은 공개 승격, 링크 정리, 정책 일관성 유지, 메모리 축적, 운영 보고다.",
            "private/source/shared/public 레이어를 섞지 말고, 공개 가능한 것만 승격 후보로 다뤄라.",
            "새 개인 문서는 현재 토큰 소유자 owner, visibility=private 보관이고, 공개는 request_publication으로만 신청한다.",
            "scope는 폴더/맥락 선택일 뿐 권한 모델이 아니다.",
            "공개 결과는 raw source가 아니라 fact/evidence summary/capsule/know-how 형태여야 한다.",
            "답변은 짧고 실무적으로 하고, 필요하면 도구를 사용하라.",
            "중요한 운영 판단이나 재사용 가치가 높은 정보는 memory_write 제안 형태로 드러내라.",
            f"## Profile\n{profile}",
            f"## Policy\n{policy}",
            f"## Working Memory\n{memory}",
            f"## Relevant Notes\n{notes_block or '없음'}",
        ]
    )


def _thread_to_messages(thread: list[dict[str, str]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in thread[-12:]:
        role = item.get("role", "user")
        text = item.get("content", "").strip()
        if role not in {"user", "assistant"} or not text:
            continue
        messages.append({"role": role, "content": text})
    return messages


def _tool_registry(enabled_tools: list[str] | None = None) -> list[dict[str, Any]]:
    allowed = set(enabled_tools or LIBRARIAN_TOOL_NAMES)
    catalog = [
        {
            "type": "function",
            "name": "exec_command",
            "description": "Run a short shell command on the server for inspection or maintenance work.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                    "timeout_sec": {"type": "integer", "minimum": 1, "maximum": 60},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "search_notes",
            "description": "Search OpenAkashic notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 12},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "read_note",
            "description": "Read a note by path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "append_note_section",
            "description": "Append a section to a note.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "heading": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "heading", "content"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
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
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "request_publication",
            "description": "Create a librarian review request for public publication while keeping the source private.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "requester": {"type": "string"},
                    "target_visibility": {"type": "string", "enum": ["public"]},
                    "rationale": {"type": "string"},
                    "evidence_paths": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "list_publication_requests",
            "description": "List librarian publication requests.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "set_publication_status",
            "description": "Record a librarian/admin publication decision. Setting published also makes the source visibility public.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["requested", "reviewing", "approved", "rejected", "published"],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["path", "status"],
                "additionalProperties": False,
            },
        },
    ]
    return [item for item in catalog if item["name"] in allowed]


def _run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "exec_command":
        return _tool_exec_command(arguments)
    if name == "search_notes":
        return search_closed_notes(arguments.get("query", ""), limit=int(arguments.get("limit", 6)))
    if name == "read_note":
        note = get_closed_note(arguments.get("path", ""))
        return note or {"error": "Note not found"}
    if name == "append_note_section":
        doc = append_section(
            arguments["path"],
            arguments["heading"],
            arguments["content"],
        )
        return {"path": doc.path, "title": doc.frontmatter.get("title")}
    if name == "upsert_note":
        doc = write_document(
            path=arguments["path"],
            body=arguments["body"],
            title=arguments.get("title"),
            kind=arguments.get("kind"),
            project=arguments.get("project"),
            metadata={"owner": "sagwan", "created_by": "sagwan"},
        )
        return {"path": doc.path, "title": doc.frontmatter.get("title")}
    if name == "request_publication":
        request = request_publication(
            path=arguments["path"],
            requester=arguments.get("requester"),
            target_visibility=arguments.get("target_visibility", "public"),
            rationale=arguments.get("rationale"),
            evidence_paths=arguments.get("evidence_paths") or [],
        )
        return request.__dict__
    if name == "list_publication_requests":
        requests = list_publication_requests(arguments.get("status"))
        return {"requests": [item.__dict__ for item in requests], "count": len(requests)}
    if name == "set_publication_status":
        doc = set_publication_status(
            path=arguments["path"],
            status=arguments["status"],
            decider="sagwan",
            reason=arguments.get("reason"),
        )
        return {"path": doc.path, "frontmatter": doc.frontmatter}
    return {"error": f"Unknown tool: {name}"}


def _tool_exec_command(arguments: dict[str, Any]) -> dict[str, Any]:
    command = str(arguments.get("command", "")).strip()
    cwd = str(arguments.get("cwd", "")).strip() or get_settings().closed_akashic_path
    timeout_sec = max(1, min(int(arguments.get("timeout_sec", 15)), 60))
    if not command:
        return {"error": "command is required"}
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except Exception as exc:
        return {"error": str(exc)}
    return {
        "command": command,
        "cwd": cwd,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def _relevant_context(message: str) -> list[dict[str, Any]]:
    preferred_paths = [
        LIBRARIAN_README_PATH,
        LIBRARIAN_PROFILE_PATH,
        LIBRARIAN_POLICY_PATH,
        LIBRARIAN_MEMORY_PATH,
        OPENAKASHIC_REVIEW_PATH,
    ]
    by_path: dict[str, dict[str, Any]] = {}

    for path in preferred_paths:
        note = get_closed_note(path)
        if note:
            by_path[path] = _note_context(note)

    results = search_closed_notes(message, limit=8).get("results", [])
    for item in results:
        note = get_closed_note(item["path"])
        if not note:
            continue
        by_path.setdefault(note["path"], _note_context(note))

    return list(by_path.values())[:8]


def _note_context(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": note["path"],
        "title": note["title"],
        "summary": note["summary"],
        "body": note["body"][:2000],
    }


def _remember_interaction(message: str, reply: str, tool_events: list[dict[str, Any]]) -> None:
    ensure_librarian_workspace()
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    daily_path = f"personal_vault/projects/ops/librarian/activity/{timestamp[:10]}.md"
    _ensure_seed_note(
        daily_path,
        title=f"Librarian Activity {timestamp[:10]}",
        kind="reference",
        body="\n".join(
            [
                "## Summary",
                "사서장의 일일 활동 로그다.",
                "",
                "## Reuse",
                "반복되는 정책과 유용한 판단은 별도 memory/playbook 문서로 옮긴다.",
            ]
        ),
    )
    tool_lines = []
    for event in tool_events[:8]:
        tool_lines.append(f"- `{event['name']}`: {json.dumps(event['arguments'], ensure_ascii=False)}")
    content = "\n".join(
        [
            f"- time: `{timestamp}`",
            f"- request: {message}",
            "",
            "### Reply",
            reply,
            "",
            "### Tool Events",
            *(tool_lines or ["- none"]),
        ]
    )
    append_section(daily_path, f"{timestamp} Interaction", content)
    if reply.strip():
        append_section(
            LIBRARIAN_MEMORY_PATH,
            f"{timestamp} Reusable Note",
            "\n".join(
                [
                    f"- request: {message[:240]}",
                    f"- takeaway: {reply[:800]}",
                ]
            ),
        )


def _ensure_seed_note(path: str, *, title: str, kind: str, body: str) -> None:
    try:
        resolve_note_path(path, must_exist=True)
        return
    except FileNotFoundError:
        pass
    parent = str(Path(path).parent)
    ensure_folder(parent)
    write_document(
        path=path,
        title=title,
        kind=kind,
        project="ops/librarian",
        status="active",
        tags=["librarian", "agent"],
        related=["Agent Guide", "Distributed Agent Memory Contract"],
        body=body,
    )


def _read_note_safely(path: str) -> str:
    try:
        return load_document(path).body
    except Exception:
        return ""
