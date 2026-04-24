#!/usr/bin/env python3
"""OpenAkashicBench v0.5 — A/B task runner.

동일 task를 두 조건으로 실행해서 OpenAkashic의 실제 가치를 측정한다:
  - baseline: MCP/skills 없음. 모델 파라메트릭 지식만으로 답.
  - standard: DDG + ephemeral note store 를 흉내 낸 simulated agent tools.
  - openakashic: MCP 도구 노출 (2-turn: plan+tool_calls → receipts → final).
  - cli_baseline: 실제 CLI agent (Claude/Codex), 기본 도구만 사용, OpenAkashic MCP 없음.
  - cli_openakashic: 실제 CLI agent (Claude/Codex), 기본 도구 + OpenAkashic MCP 사용.

Usage:
  python3 runner.py --task-id domain_jlpt_gen --model claude-haiku-4-5 \
    --condition baseline --k 1
  python3 runner.py --all --model claude-haiku-4-5 --condition openakashic --k 3
  python3 runner.py --all --model claude-haiku-4-5 --condition all5 --cli-harness claude --k 3
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import tomllib
import traceback
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

try:
    import yaml
except ImportError:
    print("pip install pyyaml", file=sys.stderr)
    raise

from standard_tools import LocalNoteStore, TOOL_MANIFEST_TEXT as STD_TOOL_MANIFEST_TEXT
from standard_tools import dispatch as std_dispatch

BENCH_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)
CLAUDE_BASELINE_MCP_CONFIG = BENCH_DIR / "mcp-baseline.json"
CLAUDE_OPENAKASHIC_MCP_CONFIG = BENCH_DIR / "mcp-openakashic.json"

LLM_PROXY_URL = "http://127.0.0.1:18796/v1/chat/completions"
LLM_PROXY_KEY = "claude-code-local"
MCP_URL = "https://knowledge.openakashic.com/mcp/"
CLI_TIMEOUT_SEC = 900


def _mcp_token() -> str:
    settings_path = Path.home() / ".claude" / "settings.json"
    data = json.loads(settings_path.read_text())
    return data["mcpServers"]["openakashic"]["headers"]["Authorization"]


# ── 조건별 시스템 프롬프트 ─────────────────────────────────────────────────

BASELINE_SYSTEM = """당신은 사용자 질문에 답하는 어시스턴트입니다.
외부 도구나 데이터베이스 없이 당신이 알고 있는 일반 지식만으로 답변하세요.

다음 JSON 형식으로만 응답 (마크다운 블록 없이 raw JSON):

{"answer": "<사용자에게 보여줄 답변>"}

규칙:
- 모르면 "모른다" 또는 "확실하지 않다"고 명시하세요.
- 추측을 사실처럼 단정하지 마세요.
"""

STD_SYSTEM_TURN1 = f"""당신은 기본 에이전트 도구를 가진 어시스턴트입니다.
이 task는 2단계로 진행됩니다. 지금은 **1단계(계획 + 도구 호출)**.
runner가 tool_calls를 실행하고 2단계에서 receipt를 보여줍니다.

{STD_TOOL_MANIFEST_TEXT}

다음 JSON 형식으로만 응답 (마크다운 블록 없이 raw JSON):

{{
  "plan": "<1-2문장 계획>",
  "tool_calls": [{{"tool": "<도구명>", "arguments": {{<키-값>}}}}]
}}

규칙:
- tool_calls는 실행 순서대로. 필요 없으면 빈 배열.
- 정보가 필요하면 web_search 로 외부 검색을, 저장이 필요하면 notes_write 를 사용.
- **도구는 증강 수단일 뿐**: 도구가 도움이 되지 않더라도 파라메트릭 지식으로 답할 수 있으면 그렇게 해야 합니다. 파라메트릭 지식으로 충분한 일반 상식 질문이면 tool_calls=[]도 OK.
- answer는 아직 작성하지 마세요 (2단계에서).
"""

STD_SYSTEM_TURN2 = f"""당신은 기본 에이전트 도구를 가진 어시스턴트입니다.
**2단계(최종 응답)**. 1단계 tool_calls receipt가 user 메시지로 전달됩니다.

{STD_TOOL_MANIFEST_TEXT}

다음 JSON 형식으로만 응답 (마크다운 블록 없이 raw JSON):

{{"answer": "<사용자에게 보여줄 답변>"}}

규칙:
- receipt에 없는 내용을 "저장했다"/"완료했다"로 주장하지 마세요.
- receipt에 error가 있으면 실패를 명시하세요.
- web_search 결과를 인용할 때 URL을 함께 명시.
- **필수 — tool 결과 공백/무관 대응**: receipt가 비거나 무관하면 "정보를 찾을 수 없습니다" / "확인할 수 없습니다" / "정보 부재" 형태의 **답변 회피는 절대 금지**. Baseline 조건의 에이전트처럼 당신의 일반 지식·공개 표준·합리적 추론으로 최대한 구체적으로 답하세요. 틀려도 "모른다"보다 낫습니다 — 단, hallucination_traps은 피하세요.
- **창작·생성 요청**은 retrieve 없이도 파라메트릭 지식만으로 초안을 만드는 것이 정답입니다.
- **온보딩·설명·triage 요청**은 일반적 업계 best practice + 합리적 기본값으로 구체적 답을 구성하세요.
"""

OAK_SYSTEM_TURN1 = """당신은 OpenAkashic MCP 서버에 연결된 에이전트입니다.
이 task는 2단계입니다. 지금은 **1단계(계획 + 도구 호출)**.
runner가 당신의 tool_calls를 실제 MCP에 실행하고, 2단계에서 receipt를 다시 보여줍니다.

다음 JSON 형식으로만 응답 (마크다운 블록 없이 raw JSON):

{
  "plan": "<1-2문장 계획>",
  "tool_calls": [{"tool": "<도구명>", "arguments": {<키-값>}}]
}

규칙:
- tool_calls는 실행 순서대로. 필요 없으면 빈 배열.
- 사용 가능한 MCP 도구: search_notes, search_and_read_top, read_note, read_raw_note,
  search_akashic, upsert_note, append_note_section, list_notes, list_folders,
  path_suggestion, bootstrap_project, request_note_publication, confirm_note,
  list_stale_notes, snooze_note, resolve_conflict, delete_note, move_note.
- 사실 조회/온보딩은 search_and_read_top(query=...)을 1순위 — 한 번에 상위 노트 본문까지 반환.
- **쓰기/저장/기억 요청**("기억해줘", "저장해", "메모", "remember", "save", "store")은 반드시 upsert_note(path, body, title)로 실제 저장 호출을 포함해야 합니다. "기억했다고 치자"는 실패입니다.
- bootstrap_project는 프로젝트 인덱스가 전혀 없을 때만. 온보딩은 search_and_read_top부터 시작.
- 파라메트릭 지식으로 충분한 일반 상식(공개 URL·프로토콜 설명·MCP/HTTP 같은 표준) 질문이면 tool_calls는 []로 두고 2단계에서 지식만으로 답해도 됩니다.
- 경로 규칙: 모든 노트 경로는 personal_vault/ 또는 doc/ 로 시작해야 합니다.
- final answer는 아직 작성하지 마세요 (2단계에서).
"""

OAK_SYSTEM_TURN2 = """당신은 OpenAkashic MCP 서버에 연결된 에이전트입니다.
**2단계(최종 응답)**. 1단계의 tool_calls receipt가 user 메시지로 전달됩니다.
이를 바탕으로 사용자에게 보여줄 최종 답변을 작성하세요.

다음 JSON 형식으로만 응답 (마크다운 블록 없이 raw JSON):

{"answer": "<사용자에게 보여줄 답변>"}

규칙:
- receipt에 없는 내용을 "저장했다"/"완료했다"/"확인했다"로 주장하지 마세요.
- receipt에 error가 있으면 실패를 명시하세요.
- 노트 내용을 인용할 때 "출처: <path>" 형식을 사용하세요.
- receipt 내용을 근거로 삼아 사용자 질문에 직접 답하세요 — receipt를 나열·요약하지 말고 그 안의 사실을 사용해 답 문장을 만드세요. (예: "X 컨테이너는 insu-server-backend-prod-1이다", "N4 문제는 ~형식이다")
- **tool_calls가 비어 있으면** 당신이 1단계에서 의도적으로 "파라메트릭 지식으로 충분"이라고 판단한 것입니다. receipt 부재를 변명으로 삼지 말고, 당신의 일반 지식으로 질문에 답하세요 (예: 공개된 프로토콜·URL·개념 설명 등).
- receipt에 실제 사실이 들어 있으면 그 구체 값(경로, 명령어, 숫자, 이름)을 그대로 인용해 답에 포함하세요. "자세한 내용은 노트를 보세요" 같은 회피 금지.
- **생성·창작 요청(문제 만들어줘, 예시 작성, 초안 써줘 등)에서는 retrieve한 노트를 spec/template으로 활용해 실제 산출물을 생성하세요.** 형식 설명·요약만 반환하면 task 실패. 노트의 예시를 그대로 복붙하지 말고, 형식·규칙을 따라 새 산출물을 만드세요.
"""


# ── 데이터 구조 ────────────────────────────────────────────────────────────

@dataclass
class ToolCallReceipt:
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class RunRecord:
    task_id: str
    condition: str
    model: str
    attempt: int
    started_at: str
    finished_at: str
    duration_ms: float = 0.0
    plan: str = ""
    tool_calls: list[ToolCallReceipt] = field(default_factory=list)
    answer: str = ""
    raw_model_output_turn1: str = ""
    raw_model_output_turn2: str = ""
    cli_harness: str | None = None
    cli_model: str | None = None
    error: str | None = None
    format_violation: bool = False


# ── 인프라 호출 ────────────────────────────────────────────────────────────

def load_tasks(filename: str = "tasks.yaml") -> list[dict[str, Any]]:
    p = BENCH_DIR / filename
    with open(p, encoding="utf-8") as fp:
        data = yaml.safe_load(fp)
    return data.get("tasks", [])


def _ensure_bench_mcp_configs() -> tuple[Path, Path]:
    CLAUDE_BASELINE_MCP_CONFIG.write_text(
        json.dumps({"mcpServers": {}}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    bearer_header = "<TOKEN_FROM_SETTINGS>"
    try:
        bearer_header = _mcp_token()
    except Exception:
        pass

    CLAUDE_OPENAKASHIC_MCP_CONFIG.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "openakashic": {
                        "type": "http",
                        "url": MCP_URL,
                        "headers": {"Authorization": bearer_header},
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return CLAUDE_BASELINE_MCP_CONFIG, CLAUDE_OPENAKASHIC_MCP_CONFIG


def mcp_call(tool: str, arguments: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }).encode()
    req = urllib.request.Request(
        MCP_URL,
        data=payload,
        headers={
            "Authorization": _mcp_token(),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "Mozilla/5.0 (compatible; OpenAkashicBench/0.5)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = json.loads(r.read())
    result = raw.get("result", {})
    if "structuredContent" in result:
        return result["structuredContent"]
    content = result.get("content", [{}])
    text = content[0].get("text", "{}") if content else "{}"
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw_text": text}


def llm_call(model: str, messages: list[dict[str, str]], timeout: int = 300,
             max_tokens: int = 3000) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_tokens,
        "stream": True,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        LLM_PROXY_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {LLM_PROXY_KEY}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    chunks: list[str] = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw_line in r:
            line = raw_line.decode(errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            choice = (obj.get("choices") or [{}])[0]
            delta = choice.get("delta", {})
            piece = delta.get("content")
            if piece:
                chunks.append(piece)
    return "".join(chunks).strip()


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            pass
    return {"answer": text.strip(), "_format_violation": True}


def _bench_turn1_addendum(condition: str) -> str:
    base = """You are running inside a one-shot benchmark harness.
Use available built-in tools (and MCP if connected) when helpful, but return only the final user-facing answer text.
Do not describe your internal tool steps unless the task itself asks for them.
If tools return nothing useful, still answer concretely using public knowledge and reasonable inference instead of refusing.
Never claim that you saved, confirmed, or checked something unless a tool actually did it.
If you cite a source from OpenAkashic, include the real note path or capsule id you actually used.
"""
    if condition == "cli_openakashic":
        return base + (
            "When a task asks you to remember, save, or store something, use the OpenAkashic MCP server to do the actual write.\n"
        )
    return base


def _extract_cli_answer(text: str) -> str:
    cleaned = text.strip()
    patterns = [
        r"(?is)(?:^|\n)final answer\s*:\s*(.+)$",
        r"(?is)(?:^|\n)answer\s*:\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return match.group(1).strip()
    return cleaned


def _run_subprocess(cmd: list[str], *, timeout: int = CLI_TIMEOUT_SEC) -> tuple[str, str, int]:
    proc = subprocess.run(
        cmd,
        cwd=BENCH_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.stdout, proc.stderr, proc.returncode


def _codex_plugin_disable_overrides() -> list[str]:
    config_path = Path.home() / ".codex" / "config.toml"
    if not config_path.exists():
        return []
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    plugin_table = config.get("plugins", {})
    overrides: list[str] = []
    for plugin_name in plugin_table.keys():
        overrides.extend(["-c", f'plugins."{plugin_name}".enabled=false'])
    return overrides


def _claude_cli_command(model: str, condition: str, prompt_body: str) -> list[str]:
    baseline_cfg, open_cfg = _ensure_bench_mcp_configs()
    config_path = baseline_cfg if condition == "cli_baseline" else open_cfg
    return [
        "claude",
        "-p",
        "--model",
        model,
        "--tools",
        "default",
        "--permission-mode",
        "bypassPermissions",
        "--mcp-config",
        str(config_path),
        "--strict-mcp-config",
        "--output-format",
        "text",
        "--append-system-prompt",
        _bench_turn1_addendum(condition),
        prompt_body,
    ]


def _codex_cli_command(model: str, condition: str, prompt_body: str,
                       output_last_message_path: str | None = None) -> list[str]:
    bench_prompt = _bench_turn1_addendum(condition).strip() + "\n\nUser task:\n" + prompt_body
    cmd = [
        "codex",
        "exec",
        "--color",
        "never",
        "--sandbox",
        "read-only",
        "--dangerously-bypass-approvals-and-sandbox",
        "-C",
        str(BENCH_DIR),
        "-m",
        model,
        "-c",
        'model_reasoning_effort="medium"',
        "-c",
        "mcp_servers={}",
    ]
    cmd.extend(_codex_plugin_disable_overrides())
    if condition == "cli_openakashic":
        cmd.extend([
            "-c",
            f'mcp_servers.openakashic.url="{MCP_URL}"',
            "-c",
            'mcp_servers.openakashic.bearer_token_env_var="CLOSED_AKASHIC_TOKEN"',
        ])
    if output_last_message_path:
        cmd.extend(["-o", output_last_message_path])
    cmd.append(bench_prompt)
    return cmd


def run_cli_agent(task: dict[str, Any], model: str, condition: str, cli_harness: str,
                  record: RunRecord) -> None:
    prompt_body = task["prompt"].strip()
    output_last_message_path: str | None = None
    if cli_harness == "claude":
        cmd = _claude_cli_command(model, condition, prompt_body)
    elif cli_harness == "codex":
        with NamedTemporaryFile(prefix="bench-codex-last-", suffix=".txt", delete=False) as fp:
            output_last_message_path = fp.name
        cmd = _codex_cli_command(model, condition, prompt_body, output_last_message_path)
    else:
        raise ValueError(f"unknown cli harness: {cli_harness}")

    t0 = time.time()
    try:
        stdout, stderr, returncode = _run_subprocess(cmd)
    except subprocess.TimeoutExpired as exc:
        record.duration_ms = round((time.time() - t0) * 1000, 1)
        partial_stdout = (exc.stdout or "").strip() if isinstance(exc.stdout, str) else ""
        record.raw_model_output_turn1 = partial_stdout
        record.answer = _extract_cli_answer(partial_stdout) if partial_stdout else ""
        record.error = f"TimeoutExpired: CLI agent exceeded {CLI_TIMEOUT_SEC}s"
        return

    record.duration_ms = round((time.time() - t0) * 1000, 1)
    record.raw_model_output_turn1 = stdout.strip()
    final_answer = ""
    if output_last_message_path:
        last_message_path = Path(output_last_message_path)
        if last_message_path.exists():
            final_answer = last_message_path.read_text(encoding="utf-8").strip()
            last_message_path.unlink(missing_ok=True)
    record.answer = final_answer or _extract_cli_answer(stdout)
    record.cli_harness = cli_harness
    record.cli_model = model
    record.format_violation = False
    if returncode != 0:
        stderr_tail = stderr.strip()[-1000:]
        record.error = f"CLIExitError({returncode}): {stderr_tail or 'no stderr'}"


def _summarize_receipt(receipt: ToolCallReceipt, max_chars: int = 1500) -> dict[str, Any]:
    result = receipt.result
    if isinstance(result, dict):
        preview = json.dumps(result, ensure_ascii=False)
    else:
        preview = str(result) if result is not None else ""
    if len(preview) > max_chars:
        preview = preview[:max_chars] + f"... <truncated {len(preview) - max_chars} chars>"
    return {
        "tool": receipt.tool,
        "arguments": receipt.arguments,
        "error": receipt.error,
        "result": preview,
        "duration_ms": receipt.duration_ms,
    }


# ── 조건별 실행 ────────────────────────────────────────────────────────────

def run_baseline(task: dict[str, Any], model: str, record: RunRecord) -> None:
    messages = [
        {"role": "system", "content": BASELINE_SYSTEM},
        {"role": "user", "content": task["prompt"].strip()},
    ]
    raw = llm_call(model, messages)
    record.raw_model_output_turn1 = raw
    parsed = extract_json(raw)
    record.format_violation = bool(parsed.get("_format_violation", False))
    record.answer = str(parsed.get("answer", "")).strip()
    if not record.answer:
        record.answer = raw.strip()


def run_standard(task: dict[str, Any], model: str, record: RunRecord) -> None:
    user_prompt = task["prompt"].strip()
    notes = LocalNoteStore()

    turn1 = [
        {"role": "system", "content": STD_SYSTEM_TURN1},
        {"role": "user", "content": user_prompt},
    ]
    raw1 = llm_call(model, turn1)
    record.raw_model_output_turn1 = raw1
    parsed1 = extract_json(raw1)
    record.format_violation = bool(parsed1.get("_format_violation", False))
    record.plan = str(parsed1.get("plan", ""))
    tool_calls = parsed1.get("tool_calls") or []

    for call in tool_calls:
        tname = str(call.get("tool", ""))
        targs = call.get("arguments") or {}
        receipt = ToolCallReceipt(tool=tname, arguments=targs)
        t0 = time.time()
        try:
            receipt.result = std_dispatch(tname, targs, notes)
        except Exception as exc:
            receipt.error = f"{type(exc).__name__}: {exc}"
        receipt.duration_ms = round((time.time() - t0) * 1000, 1)
        record.tool_calls.append(receipt)

    assistant_turn1 = json.dumps({
        "plan": record.plan,
        "tool_calls": [{"tool": c.get("tool"), "arguments": c.get("arguments") or {}}
                       for c in tool_calls],
    }, ensure_ascii=False)
    receipts_payload = {
        "tool_receipts": [_summarize_receipt(r) for r in record.tool_calls],
    }
    if record.tool_calls:
        turn2_user = (
            "아래는 tool_calls의 실행 receipt입니다. 이를 바탕으로 answer JSON을 작성하세요.\n\n"
            + json.dumps(receipts_payload, ensure_ascii=False, indent=2)
        )
    else:
        turn2_user = (
            "1단계에서 당신은 tool_calls를 호출하지 않기로 결정했습니다 (파라메트릭 지식으로 충분).\n"
            "원 질문은 다음과 같습니다:\n---\n" + user_prompt + "\n---\n"
            "위 질문에 당신이 아는 사실(파라메트릭 지식)로 직접 답변하는 answer JSON을 작성하세요. "
            "되묻거나 인사하지 말고, 질문에 구체적으로 답하세요."
        )
    turn2 = [
        {"role": "system", "content": STD_SYSTEM_TURN2},
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": assistant_turn1},
        {"role": "user", "content": turn2_user},
    ]
    raw2 = llm_call(model, turn2)
    record.raw_model_output_turn2 = raw2
    parsed2 = extract_json(raw2)
    record.answer = str(parsed2.get("answer", "")).strip()
    if not record.answer:
        record.answer = raw2.strip()


def run_openakashic(task: dict[str, Any], model: str, record: RunRecord) -> None:
    user_prompt = task["prompt"].strip()

    turn1 = [
        {"role": "system", "content": OAK_SYSTEM_TURN1},
        {"role": "user", "content": user_prompt},
    ]
    raw1 = llm_call(model, turn1)
    record.raw_model_output_turn1 = raw1
    parsed1 = extract_json(raw1)
    record.format_violation = bool(parsed1.get("_format_violation", False))
    record.plan = str(parsed1.get("plan", ""))
    tool_calls = parsed1.get("tool_calls") or []

    for call in tool_calls:
        tname = str(call.get("tool", ""))
        targs = call.get("arguments") or {}
        receipt = ToolCallReceipt(tool=tname, arguments=targs)
        t0 = time.time()
        try:
            receipt.result = mcp_call(tname, targs)
        except Exception as exc:
            receipt.error = f"{type(exc).__name__}: {exc}"
        receipt.duration_ms = round((time.time() - t0) * 1000, 1)
        record.tool_calls.append(receipt)

    assistant_turn1 = json.dumps({
        "plan": record.plan,
        "tool_calls": [{"tool": c.get("tool"), "arguments": c.get("arguments") or {}}
                       for c in tool_calls],
    }, ensure_ascii=False)
    receipts_payload = {
        "tool_receipts": [_summarize_receipt(r) for r in record.tool_calls],
    }
    if record.tool_calls:
        turn2_user = (
            "원 질문(다시 보여드림):\n---\n" + user_prompt + "\n---\n\n"
            "아래는 당신이 요청한 tool_calls의 실제 실행 receipt입니다. "
            "**원 질문에 답하기 위한 근거 자료**로 활용하세요. "
            "원 질문이 '생성·작성·만들어줘' 형식이면 receipt의 spec/예시를 참고해 **실제 산출물을 생성**하고, "
            "원 질문이 '뭐가 있어?·어떻게 해?·확인해줘' 형식이면 receipt의 사실을 인용해 **답하세요**.\n\n"
            + json.dumps(receipts_payload, ensure_ascii=False, indent=2)
        )
    else:
        turn2_user = (
            "1단계에서 당신은 tool_calls를 호출하지 않기로 결정했습니다 (파라메트릭 지식으로 충분).\n"
            "원 질문은 다음과 같습니다:\n---\n"
            + user_prompt + "\n---\n"
            "위 질문에 당신이 아는 사실(파라메트릭 지식)로 직접 답변하는 answer JSON을 작성하세요. "
            "되묻거나 인사하지 말고, 질문에 구체적으로 답하세요."
        )
    turn2 = [
        {"role": "system", "content": OAK_SYSTEM_TURN2},
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": assistant_turn1},
        {"role": "user", "content": turn2_user},
    ]
    raw2 = llm_call(model, turn2)
    record.raw_model_output_turn2 = raw2
    parsed2 = extract_json(raw2)
    record.answer = str(parsed2.get("answer", "")).strip()
    if not record.answer:
        record.answer = raw2.strip()


def run_task(task: dict[str, Any], model: str, condition: str, attempt: int,
             cli_harness: str = "claude") -> RunRecord:
    from datetime import UTC, datetime as dt
    t0 = time.time()
    started = dt.now(UTC).replace(microsecond=0).isoformat()
    record = RunRecord(
        task_id=task["id"],
        condition=condition,
        model=model,
        attempt=attempt,
        started_at=started,
        finished_at=started,
    )
    try:
        if condition == "baseline":
            run_baseline(task, model, record)
        elif condition == "standard":
            run_standard(task, model, record)
        elif condition == "openakashic":
            run_openakashic(task, model, record)
        elif condition in {"cli_baseline", "cli_openakashic"}:
            run_cli_agent(task, model, condition, cli_harness, record)
        else:
            raise ValueError(f"unknown condition: {condition}")
    except Exception as exc:
        record.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[:500]}"
    from datetime import UTC, datetime as dt
    record.finished_at = dt.now(UTC).replace(microsecond=0).isoformat()
    if not record.duration_ms:
        record.duration_ms = round((time.time() - t0) * 1000, 1)
    return record


def record_to_dict(rec: RunRecord) -> dict[str, Any]:
    return asdict(rec)


def save_results(records: list[RunRecord], model: str, condition: str,
                 cli_harness: str | None = None) -> Path:
    from datetime import UTC, datetime as dt
    stamp = dt.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_model = model.replace('.', '_').replace('/', '_')
    prefix = f"run-{condition}-"
    if cli_harness:
        prefix += f"{cli_harness}-"
    out_path = RESULTS_DIR / f"{prefix}{safe_model}-{stamp}.json"
    payload = {
        "model": model,
        "condition": condition,
        "cli_harness": cli_harness,
        "cli_model": model if cli_harness else None,
        "timestamp": stamp,
        "records": [record_to_dict(r) for r in records],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", help="Run a single task by id")
    parser.add_argument("--all", action="store_true", help="Run all tasks")
    parser.add_argument("--model", required=True, help="Model id")
    parser.add_argument("--condition", required=True,
                        choices=[
                            "baseline",
                            "standard",
                            "openakashic",
                            "cli_baseline",
                            "cli_openakashic",
                            "all3",
                            "all5",
                        ],
                        help="Which condition(s) to run")
    parser.add_argument("--cli-harness", default="claude",
                        choices=["claude", "codex"],
                        help="CLI harness for cli_* conditions")
    parser.add_argument("--tasks-file", default="tasks.yaml")
    parser.add_argument("--k", type=int, default=1, help="Repetitions per task")
    args = parser.parse_args()

    _ensure_bench_mcp_configs()

    all_tasks = load_tasks(args.tasks_file)
    if args.task_id:
        tasks = [t for t in all_tasks if t["id"] == args.task_id]
        if not tasks:
            print(f"task not found: {args.task_id}")
            return 1
    elif args.all:
        tasks = all_tasks
    else:
        print("specify --task-id or --all")
        return 1

    if args.condition == "all3":
        conditions = ["baseline", "standard", "openakashic"]
    elif args.condition == "all5":
        conditions = ["baseline", "standard", "openakashic", "cli_baseline", "cli_openakashic"]
    else:
        conditions = [args.condition]
    out_paths: list[Path] = []
    for cond in conditions:
        records: list[RunRecord] = []
        for task in tasks:
            for attempt in range(1, args.k + 1):
                print(f"[{cond}][{task['id']}] attempt {attempt}/{args.k} ({args.model})")
                rec = run_task(task, args.model, cond, attempt, cli_harness=args.cli_harness)
                records.append(rec)
                if rec.error:
                    print(f"  ERR: {rec.error[:120]}")
                else:
                    print(f"  answer[:120]: {rec.answer[:120].replace(chr(10),' ')}")
                    if rec.tool_calls:
                        print(f"  tools: {[t.tool for t in rec.tool_calls]}")
        harness = args.cli_harness if cond.startswith("cli_") else None
        out = save_results(records, args.model, cond, cli_harness=harness)
        out_paths.append(out)
        print(f"\nSaved [{cond}]: {out}")
        print(f"Records: {len(records)}\n")

    print("All outputs:")
    for p in out_paths:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
