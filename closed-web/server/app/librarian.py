from __future__ import annotations

from datetime import UTC, datetime
import json
import os
import re
from pathlib import Path
import subprocess
from typing import Any

from app.auth import librarian_identity_dict
from app.config import get_settings
from app.site import get_closed_note, search_closed_notes
from app.users import SAGWAN_SYSTEM_OWNER
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
# 부사관 메모리 — 사서장이 부사관 경험을 참조하기 위해 읽는다
SUBORDINATE_MEMORY_PATH = "personal_vault/projects/ops/librarian/memory/Subordinate Working Memory.md"

LIBRARIAN_TOOL_NAMES = (
    "exec_command",
    "search_notes",
    "read_note",
    "append_note_section",
    "upsert_note",
    "request_publication",
    "list_publication_requests",
    "set_publication_status",
    "enqueue_task",
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


def librarian_chat(
    message: str,
    thread: list[dict[str, str]] | None = None,
    *,
    current_note_path: str | None = None,
) -> dict[str, Any]:
    ensure_librarian_workspace()
    relevant_notes = _relevant_context(message, current_note_path=current_note_path)
    settings = get_settings()
    runtime = load_librarian_settings()
    provider = runtime["provider"].strip().lower()

    if provider == "claude-cli":
        import shutil
        if shutil.which("claude"):
            # 호스트/컨테이너에 claude binary가 있으면 subprocess ReAct 루프 사용
            try:
                response = _run_claude_cli_librarian(message, thread or [], relevant_notes)
            except Exception as exc:
                failure = f"사서장 CLI 호출 중 오류가 발생했다: {exc}"
                _remember_interaction(message, failure, [])
                return {
                    "message": failure,
                    "status": "error",
                    "tool_events": [],
                    "context_notes": relevant_notes,
                    "model": "claude-cli",
                }
            _remember_interaction(message, response["message"], response["tool_events"])
            return {
                **response,
                "context_notes": relevant_notes,
                "model": "claude-cli",
                "status": "ok",
            }
        elif settings.has_librarian_api_key:
            # binary 없이 ANTHROPIC_API_KEY가 있으면 OpenAI compat(Anthropic) 폴백
            try:
                response = _run_openai_librarian(message, thread or [], relevant_notes)
            except Exception as exc:
                failure = f"사서장 Anthropic API 호출 중 오류가 발생했다: {exc}"
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
        else:
            fallback = (
                "사서장 claude-cli 런타임이 준비되지 않았다. "
                "컨테이너에 claude binary가 없고 ANTHROPIC_API_KEY도 설정되지 않았다. "
                "env 파일에 ANTHROPIC_API_KEY를 추가하거나 컨테이너에 claude CLI를 설치하라."
            )
            _remember_interaction(message, fallback, [])
            return {
                "message": fallback,
                "status": "needs_claude_cli_or_api_key",
                "tool_events": [],
                "context_notes": relevant_notes,
                "model": runtime["model"],
            }

    if provider != "openai-compatible":
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


def _invoke_claude_cli(prompt: str, model: str | None = None) -> str:
    """claude -p CLI를 subprocess로 호출해 응답 텍스트를 반환한다."""
    try:
        cmd = ["claude", "-p", "--tools", "", "--output-format", "text"]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ},
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return f"[CLI 오류 {result.returncode}] {result.stderr.strip()[:400]}"
    except FileNotFoundError:
        return "[CLI 오류] claude 명령어를 찾을 수 없다. PATH를 확인하라."
    except subprocess.TimeoutExpired:
        return "[CLI 오류] 응답 시간 초과 (120초)"
    except Exception as exc:
        return f"[CLI 오류] {exc}"


def _cli_tool_definitions(enabled_tools: list[str] | None = None) -> str:
    """사관이 사용할 수 있는 도구 목록과 호출 형식을 반환한다."""
    allowed = set(enabled_tools or LIBRARIAN_TOOL_NAMES)
    signatures = {
        "exec_command": "exec_command(command: str, cwd?: str, timeout_sec?: int) — 서버 명령 실행",
        "search_notes": "search_notes(query: str, limit?: int) — 노트 검색",
        "read_note": "read_note(path: str) — 노트 읽기",
        "append_note_section": "append_note_section(path: str, heading: str, content: str) — 노트에 섹션 추가",
        "upsert_note": "upsert_note(path: str, body: str, title?: str, kind?: str, project?: str) — 노트 생성/수정",
        "request_publication": "request_publication(path: str, requester?: str, rationale?: str, evidence_paths?: list) — 공개 신청",
        "list_publication_requests": "list_publication_requests(status?: str) — 공개 신청 목록",
        "set_publication_status": "set_publication_status(path: str, status: str, reason?: str) — 공개 상태 변경 (status: requested|reviewing|approved|rejected|published)",
        "enqueue_task": 'enqueue_task(kind: str, payload: dict) — 부사관 태스크 큐에 추가. kind: crawl_url|draft_capsule|draft_claim|sync_to_core_api|analyze_search_gaps. crawl_url payload: {"url": "...", "folder": "..."}, draft_capsule payload: {"source_path": "..."}, draft_claim payload: {"source_path": "..."}, sync_to_core_api payload: {"limit": 10}, analyze_search_gaps payload: {"max_new": 10}',
    }
    lines = [
        "## 사용 가능한 도구",
        *[f"- {sig}" for name, sig in signatures.items() if name in allowed],
        "",
        "도구가 필요하면 다음 형식으로 한 번에 하나씩 출력하라:",
        "<<TOOL_CALL>>",
        '{"name": "도구이름", "arguments": {"key": "value"}}',
        "<</TOOL_CALL>>",
        "",
        "최종 답변은 반드시 다음 형식으로 출력하라:",
        "<<FINAL>>",
        "답변 내용",
        "<</FINAL>>",
    ]
    return "\n".join(lines)


def _build_cli_prompt(
    instructions: str,
    tool_defs: str,
    history: str,
    message: str,
    tool_exchange: str,
) -> str:
    """단일 claude -p 호출용 프롬프트를 조립한다."""
    parts = [instructions, tool_defs]
    if history:
        parts.append(f"## 대화 이력\n{history}")
    parts.append(f"## 현재 요청\n사용자: {message}")
    if tool_exchange:
        parts.append(f"## 도구 실행 내역\n{tool_exchange}")
    parts.append(
        "위 내용을 바탕으로 처리하라.\n"
        "절대 지켜야 할 규칙:\n"
        "1. 너는 vault 파일시스템에 직접 접근할 수 없다. 파일 읽기/쓰기/검색/실행은 반드시 위에 명시된 도구를 <<TOOL_CALL>> JSON으로 호출해야 한다.\n"
        "2. 파일 작성/수정이 요청됐다면 반드시 upsert_note 또는 append_note_section 도구를 실제로 호출해라. 호출 없이 '작성됐습니다'라고 말하지 마라(거짓말 금지).\n"
        "3. '파일이 없다', '권한이 없다' 같은 추측으로 포기하지 마라. 먼저 도구를 실제로 호출해 확인하라.\n"
        "4. 한 번에 하나의 <<TOOL_CALL>>만 출력하라. 결과는 다음 턴에 `## 도구 실행 내역`으로 주어진다.\n"
        "5. 도구 호출과 최종 답변을 동시에 출력하지 마라. 모든 필요한 도구 호출이 끝난 뒤에만 <<FINAL>>을 작성하라."
    )
    return "\n\n".join(parts)


def _run_claude_cli_librarian(
    message: str,
    thread: list[dict[str, str]],
    relevant_notes: list[dict[str, Any]],
) -> dict[str, Any]:
    """claude -p CLI를 이용한 ReAct 루프로 사관 응답을 생성한다."""
    runtime = load_librarian_settings()
    instructions = _librarian_instructions(relevant_notes)
    tool_defs = _cli_tool_definitions(runtime["enabled_tools"])
    history = "\n".join(
        f"{'사용자' if item.get('role') == 'user' else '사서장'}: {item.get('content', '')[:600]}"
        for item in (thread or [])[-12:]
        if item.get("role") in {"user", "assistant"} and item.get("content", "").strip()
    )

    tool_events: list[dict[str, Any]] = []
    tool_exchange = ""

    for _iteration in range(14):
        prompt = _build_cli_prompt(instructions, tool_defs, history, message, tool_exchange)
        reply = _invoke_claude_cli(prompt, runtime.get("model") or None)

        if not reply or reply.startswith("[CLI 오류]"):
            return {"message": reply or "사서장이 응답을 만들지 못했다.", "tool_events": tool_events}

        # 도구 호출 파싱 — 먼저 마커 형식, 없으면 JSON 블록 탐지(백업)
        tool_payload: str | None = None
        tool_match = re.search(r"<<TOOL_CALL>>\s*(.*?)\s*<</TOOL_CALL>>", reply, re.DOTALL)
        if tool_match:
            tool_payload = tool_match.group(1).strip()
        else:
            # 마커 없이 raw JSON으로 온 경우 fenced code 또는 단독 JSON 추출
            fenced = re.search(r"```(?:json)?\s*(\{.*?\"name\".*?\})\s*```", reply, re.DOTALL)
            if fenced:
                tool_payload = fenced.group(1).strip()
            else:
                brace = re.search(r"(\{[^{}]*\"name\"\s*:\s*\"[a-z_]+\"\s*,\s*\"arguments\"\s*:\s*\{.*?\}\s*\})", reply, re.DOTALL)
                if brace:
                    tool_payload = brace.group(1).strip()
        if tool_payload:
            name = ""
            args: dict[str, Any] = {}
            try:
                call = json.loads(tool_payload)
                name = str(call.get("name", ""))
                args = dict(call.get("arguments", {}))
            except Exception as exc:
                tool_events.append({"name": "_parse_error", "arguments": {"payload": tool_payload[:400]}, "result": {"error": str(exc)}})
                tool_exchange += f"\n### _parse_error\n오류: {exc}\n"
                continue
            if name:
                try:
                    result = _run_tool(name, args)
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                tool_events.append({"name": name, "arguments": args, "result": result})
                tool_exchange += (
                    f"\n### {name}\n"
                    f"인자: {json.dumps(args, ensure_ascii=False)[:400]}\n"
                    f"결과: {json.dumps(result, ensure_ascii=False)[:1500]}\n"
                )
                continue

        # 최종 답변 추출
        final_match = re.search(r"<<FINAL>>\s*(.*?)\s*<</FINAL>>", reply, re.DOTALL)
        text = (
            final_match.group(1).strip()
            if final_match
            else re.sub(r"<</?(?:TOOL_CALL|FINAL)>>", "", reply).strip()
        )
        return {"message": text or "사서장이 응답을 만들지 못했다.", "tool_events": tool_events}

    return {"message": "사서장이 최대 반복 횟수(14)에 도달했다.", "tool_events": tool_events}


def _run_openai_librarian(
    message: str,
    thread: list[dict[str, str]],
    relevant_notes: list[dict[str, Any]],
) -> dict[str, Any]:
    from openai import OpenAI

    settings = get_settings()
    runtime = load_librarian_settings()
    # claude-cli provider → Anthropic OpenAI-compat endpoint 사용
    effective_base_url = runtime["base_url"] or settings.librarian_effective_base_url or None
    client = OpenAI(
        api_key=settings.librarian_api_key,
        base_url=effective_base_url,
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
    subordinate_memory = _read_note_safely(SUBORDINATE_MEMORY_PATH)
    notes_block = "\n\n".join(
        [
            f"[{item['title']}] {item['path']}\nSummary: {item['summary']}"
            for item in relevant_notes[:6]
        ]
    )
    return "\n\n".join(
        [
            "너는 OpenAkashic의 사서장(sagwan)이다.",
            "역할: 공개 승격 최종 결정, 정책 일관성 유지, 운영 메모리 축적, 부사관(busagwan) 감독 및 태스크 위임.",
            "private/source/shared/public 레이어를 섞지 말고, 공개 가능한 것만 승격 후보로 다뤄라.",
            "새 개인 문서는 visibility=private으로 시작하고, 공개는 request_publication → 부사관 1차 리뷰 → 사서장 최종 결정 순서를 지킨다.",
            "scope는 폴더/맥락 선택일 뿐 권한 모델이 아니다.",
            "공개 결과는 raw source가 아니라 fact/evidence summary/capsule/know-how 형태여야 한다.",
            "반복 작업(URL 크롤링, capsule 초안, Core API 동기화)은 enqueue_task로 부사관에게 위임하라.",
            "답변은 짧고 실무적으로. 도구가 필요하면 사용하라. 중요 판단은 append_note_section으로 Working Memory에 남겨라.",
            f"## Profile\n{profile}",
            f"## Policy\n{policy}",
            f"## Librarian Working Memory\n{memory}",
            f"## Subordinate (busagwan) Working Memory\n{subordinate_memory or '아직 없음'}",
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
        {
            "type": "function",
            "name": "enqueue_task",
            "description": (
                "Queue a background task for the subordinate agent (busagwan). "
                "Use for repetitive or long-running work: crawling URLs, drafting capsules, syncing to Core API, or processing knowledge gaps. "
                "kind=crawl_url: payload requires 'url'; optional 'folder', 'project'. "
                "kind=draft_capsule: payload requires 'source_path'. "
                "kind=draft_claim: payload requires 'source_path' — extracts atomic factual claims (measurements, experiments, observations) and creates kind=claim notes. "
                "kind=sync_to_core_api: payload optionally has 'limit' (default 10). "
                "kind=analyze_search_gaps: payload optionally has 'max_new' (default 10) — processes gap-queries.jsonl and creates candidate gap notes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["crawl_url", "draft_capsule", "draft_claim", "sync_to_core_api", "analyze_search_gaps"],
                    },
                    "payload": {"type": "object"},
                    "run_after": {"type": "string", "description": "ISO8601 datetime to delay execution"},
                },
                "required": ["kind", "payload"],
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
            metadata={"owner": SAGWAN_SYSTEM_OWNER, "created_by": SAGWAN_SYSTEM_OWNER},
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
    if name == "enqueue_task":
        from app.subordinate import enqueue_subordinate_task
        task = enqueue_subordinate_task(
            kind=arguments["kind"],
            payload=dict(arguments.get("payload") or {}),
            created_by="sagwan",
            run_after=arguments.get("run_after"),
        )
        return {"queued": True, "task_id": task["id"], "kind": task["kind"], "status": task["status"]}
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


def _relevant_context(
    message: str,
    *,
    current_note_path: str | None = None,
) -> list[dict[str, Any]]:
    preferred_paths = [
        LIBRARIAN_README_PATH,
        LIBRARIAN_PROFILE_PATH,
        LIBRARIAN_POLICY_PATH,
        LIBRARIAN_MEMORY_PATH,
        SUBORDINATE_MEMORY_PATH,   # 부사관 경험 교차 공유
        OPENAKASHIC_REVIEW_PATH,
    ]
    by_path: dict[str, dict[str, Any]] = {}

    # 사용자가 현재 열람 중인 노트를 최우선 컨텍스트로 포함한다.
    # (UI에서 채팅 시 명시적으로 전달. preferred_paths 뒤에 merge 하지 않고 앞에 두어 잘림 없이 보존.)
    current_ctx: dict[str, Any] | None = None
    if current_note_path:
        note = get_closed_note(current_note_path)
        if note:
            current_ctx = {**_note_context(note), "is_current_note": True}
            by_path[current_note_path] = current_ctx

    for path in preferred_paths:
        if path in by_path:
            continue
        note = get_closed_note(path)
        if note:
            by_path[path] = _note_context(note)

    results = search_closed_notes(message, limit=8).get("results", [])
    for item in results:
        note = get_closed_note(item["path"])
        if not note:
            continue
        by_path.setdefault(note["path"], _note_context(note))

    ordered = list(by_path.values())[:10]
    # 현재 노트는 맨 앞 고정 (검색/preferred 순서에 밀리지 않도록)
    if current_ctx and ordered and ordered[0] is not current_ctx:
        ordered = [current_ctx] + [item for item in ordered if item is not current_ctx]
        ordered = ordered[:10]
    return ordered


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
