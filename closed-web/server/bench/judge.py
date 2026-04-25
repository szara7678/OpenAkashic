#!/usr/bin/env python3
"""OpenAkashicBench — outcome-based judge.

Reads a runner output and asks GPT-5.4 (via local proxy) to score each answer
against expected_outcome checkpoints and hallucination_traps. Works for both
baseline and openakashic condition outputs.

Usage:
  python3 judge.py --run results/run-baseline-claude-haiku-4-5-<stamp>.json
  python3 judge.py --run <path> --judge-model gpt-5.4
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("pip install pyyaml", file=sys.stderr)
    raise

BENCH_DIR = Path(__file__).resolve().parent
DEFAULT_TASK_FILES = [
    BENCH_DIR / "tasks-v0.7.yaml",
    BENCH_DIR / "tasks-private.yaml",
    BENCH_DIR / "tasks-public.yaml",
    BENCH_DIR / "tasks.yaml",
]

LLM_PROXY_URL = "http://127.0.0.1:18796/v1/chat/completions"
LLM_PROXY_KEY = "claude-code-local"

JUDGE_SYSTEM = """당신은 OpenAkashicBench 채점관입니다.
각 task는 사용자에게 답변해야 할 자연스러운 질문이고, 정답 체크포인트와 할루시네이션
트랩 목록이 주어집니다. 모델의 answer를 보고 다음을 판정하세요.

판정 대상:
1) expected_outcome 각 항목이 answer에 포함되었는가 → hits 리스트 (항목 문자열을 task에 적힌 그대로 표기)
2) hallucination_traps 중 answer에 등장한 것 → traps_hit 리스트
3) 최종 verdict:
   - expected_outcome 이 {"core": [...], "bonus": [...]} 구조면 core 전부 hit + traps_hit 없음 → pass
   - expected_outcome 이 평면 리스트면 80% 이상 hit + traps_hit 없음 → pass
   - 그 외는 fail

판정 원칙:
- answer가 정확히 그 문구를 써야 하는 건 아님. 의미적으로 같으면 hit.
- 할루시네이션 트랩은 strict — 언급되면 fail.
- openakashic 조건이면 tool_calls receipt를 참고해 "인용한 경로가 실제 receipt에 등장하는가"도 확인.
- Python 쪽에서도 verdict를 다시 계산하므로, hits/traps 분류를 가장 중요하게 신중히 하라.

반드시 다음 JSON 형식으로만 응답 (마크다운 블록 없이 raw JSON):

{
  "verdict": "pass" | "fail",
  "hits": ["<충족한 expected_outcome 항목 원문>", ...],
  "missed": ["<미충족 expected_outcome 항목 원문>", ...],
  "traps_hit": ["<answer에 등장한 hallucination_trap 원문>", ...],
  "groundedness_note": "<1-2문장: 답변이 근거에 기반했는지, 환각인지>",
  "reason": "<2-3문장 종합 판정 근거>"
}
"""


def normalize_expected_outcome(task: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    expected = task.get("expected_outcome", [])
    if isinstance(expected, dict):
        core = list(expected.get("core") or [])
        bonus = list(expected.get("bonus") or [])
        return core, bonus, core + bonus
    flat = list(expected or [])
    return [], [], flat


def score_verdict(task: dict[str, Any], hits: list[str], traps_hit: list[str]) -> tuple[str, dict[str, float | int]]:
    core, bonus, flat = normalize_expected_outcome(task)
    hit_set = set(hits)
    core_hits = sum(1 for item in core if item in hit_set)
    bonus_hits = sum(1 for item in bonus if item in hit_set)
    total_hits = sum(1 for item in flat if item in hit_set)

    if traps_hit:
        verdict = "fail"
    elif core:
        verdict = "pass" if core_hits == len(core) else "fail"
    else:
        verdict = "pass" if flat and (total_hits / len(flat)) >= 0.8 else "fail"

    score = {
        "hit_rate": (total_hits / len(flat)) if flat else 0.0,
        "expected_total": len(flat),
        "hits_count": total_hits,
        "core_hit_rate": (core_hits / len(core)) if core else 0.0,
        "core_total": len(core),
        "core_hits": core_hits,
        "bonus_hit_rate": (bonus_hits / len(bonus)) if bonus else 0.0,
        "bonus_total": len(bonus),
        "bonus_hits": bonus_hits,
        "traps_hit_count": len(traps_hit),
    }
    return verdict, score


def llm_call(model: str, system: str, user: str, timeout: int = 180) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_completion_tokens": 3000,
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
    last_err: Exception | None = None
    for attempt in range(5):
        chunks: list[str] = []
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
        except urllib.request.HTTPError as e:
            body = e.read().decode(errors="replace")[:500]
            last_err = RuntimeError(f"proxy HTTP {e.code}: {body}")
            time.sleep(2 ** attempt)
            continue
        except urllib.error.URLError as e:
            last_err = RuntimeError(f"URLError: {e}")
            time.sleep(2 ** attempt)
            continue
        with r:
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
        result = "".join(chunks).strip()
        if result:
            return result
        last_err = RuntimeError(f"proxy returned empty stream for model={model}")
        time.sleep(2 ** attempt)
    raise last_err or RuntimeError("judge proxy call failed after 5 attempts")


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
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found: {text[:200]}")
    return json.loads(cleaned[start:end + 1])


def load_tasks(task_files: list[Path]) -> dict[str, dict[str, Any]]:
    tasks: dict[str, dict[str, Any]] = {}
    for task_file in task_files:
        if not task_file.exists():
            continue
        with open(task_file, encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
        for task in data.get("tasks", []):
            tasks.setdefault(task["id"], task)
    return tasks


def build_user_payload(task: dict[str, Any], record: dict[str, Any]) -> str:
    core, bonus, flat = normalize_expected_outcome(task)
    trimmed_calls = []
    for call in record.get("tool_calls", []):
        result = call.get("result")
        if isinstance(result, dict):
            result_preview = json.dumps(result, ensure_ascii=False)[:800]
        else:
            result_preview = str(result)[:800]
        trimmed_calls.append({
            "tool": call.get("tool"),
            "arguments": call.get("arguments"),
            "error": call.get("error"),
            "result_preview": result_preview,
        })
    payload = {
        "task": {
            "id": task["id"],
            "prompt": task["prompt"].strip(),
            "expected_outcome": task.get("expected_outcome", []),
            "expected_outcome_flat": flat,
            "scoring_mode": "core_bonus" if core else "legacy_80pct",
            "hallucination_traps": task.get("hallucination_traps", []),
            "rubric": task.get("rubric", "").strip(),
        },
        "run": {
            "condition": record.get("condition", "unknown"),
            "plan": record.get("plan", ""),
            "tool_calls": trimmed_calls,
            "answer": record.get("answer", ""),
            "error": record.get("error"),
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def judge_record(task: dict[str, Any], record: dict[str, Any], judge_model: str) -> dict[str, Any]:
    user_payload = build_user_payload(task, record)
    try:
        raw = llm_call(judge_model, JUDGE_SYSTEM, user_payload)
        parsed = extract_json(raw)
    except Exception as exc:
        return {
            "task_id": task["id"],
            "condition": record.get("condition"),
            "attempt": record.get("attempt"),
            "verdict": "error",
            "hits": [], "missed": [], "traps_hit": [],
            "groundedness_note": "",
            "reason": f"judge error: {type(exc).__name__}: {exc}",
        }
    hits = parsed.get("hits") or []
    traps_hit = parsed.get("traps_hit") or []
    core, bonus, flat = normalize_expected_outcome(task)
    canonical_missed = [item for item in flat if item not in set(hits)]
    verdict, score = score_verdict(task, hits, traps_hit)
    return {
        "task_id": task["id"],
        "condition": record.get("condition"),
        "attempt": record.get("attempt"),
        "verdict": verdict,
        "hits": hits,
        "missed": canonical_missed,
        "traps_hit": traps_hit,
        "groundedness_note": parsed.get("groundedness_note", ""),
        "reason": parsed.get("reason", ""),
        "score": score,
        "scoring_mode": "core_bonus" if core else "legacy_80pct",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="runner output JSON file")
    parser.add_argument("--judge-model", default="claude-sonnet-4-6")
    parser.add_argument(
        "--tasks-file",
        action="append",
        help="optional additional task YAML file(s); checked before default task files",
    )
    parser.add_argument("--out", help="output path (default: alongside run file)")
    args = parser.parse_args()

    run_path = Path(args.run)
    if not run_path.is_absolute():
        run_path = (Path.cwd() / run_path).resolve()
    run_data = json.loads(run_path.read_text())
    task_files = [Path(p).resolve() for p in (args.tasks_file or [])]
    task_files.extend(DEFAULT_TASK_FILES)
    tasks = load_tasks(task_files)

    judgments: list[dict[str, Any]] = []
    for idx, rec in enumerate(run_data.get("records", []), 1):
        tid = rec.get("task_id")
        task = tasks.get(tid)
        if not task:
            judgments.append({
                "task_id": tid, "condition": rec.get("condition"),
                "attempt": rec.get("attempt"),
                "verdict": "error",
                "hits": [], "missed": [], "traps_hit": [],
                "groundedness_note": "",
                "reason": f"task {tid} not found in tasks.yaml",
            })
            continue
        print(f"[{idx}/{len(run_data['records'])}] judging {tid} "
              f"(attempt {rec.get('attempt')}, {rec.get('condition')})")
        verdict = judge_record(task, rec, args.judge_model)
        judgments.append(verdict)
        mark = "✓" if verdict["verdict"] == "pass" else "✗"
        score = verdict.get("score", {})
        if score.get("core_total"):
            print(
                f"  {mark} {verdict['verdict']} — core {score.get('core_hits', 0)}/{score.get('core_total', 0)}, "
                f"bonus {score.get('bonus_hits', 0)}/{score.get('bonus_total', 0)}, "
                f"traps {len(verdict['traps_hit'])}"
            )
        else:
            print(
                f"  {mark} {verdict['verdict']} — hits {score.get('hits_count', 0)}/{score.get('expected_total', 0)}, "
                f"traps {len(verdict['traps_hit'])}"
            )

    out_path = Path(args.out) if args.out else run_path.with_name(run_path.stem + "-judged.json")
    out_path.write_text(json.dumps({
        "run_file": str(run_path),
        "judge_model": args.judge_model,
        "model": run_data.get("model"),
        "condition": run_data.get("condition"),
        "judgments": judgments,
    }, ensure_ascii=False, indent=2))
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
