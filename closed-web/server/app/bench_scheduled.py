from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, date, datetime
import json
import logging
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any

from app.librarian import load_librarian_settings
from app.users import SAGWAN_SYSTEM_OWNER
from app.vault import list_note_paths, load_document, write_document

logger = logging.getLogger(__name__)

_HISTORY_PREFIX = "personal_vault/projects/ops/bench/history/"
_RUN_LOCK = threading.Lock()
_RUN_ACTIVE = False


def _server_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _bench_dir() -> Path:
    return _server_dir() / "bench"


def _results_dir() -> Path:
    return _bench_dir() / "results"


def _safe_model(model: str) -> str:
    return model.replace(".", "_").replace("/", "_")


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _now_iso() -> str:
    return _now_utc().isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _history_note_path(target_date: date | None = None) -> str:
    day = target_date or _now_utc().date()
    return f"{_HISTORY_PREFIX}{day.isoformat()}.md"


def _latest_bench_history_entry() -> dict[str, Any] | None:
    entries: list[dict[str, Any]] = []
    for path in list_note_paths():
        if not path.startswith(_HISTORY_PREFIX) or not path.endswith(".md"):
            continue
        try:
            doc = load_document(path)
        except Exception:
            continue
        fm = doc.frontmatter or {}
        ts = (
            str(fm.get("run_finished_at") or "")
            or str(fm.get("run_started_at") or "")
            or str(fm.get("updated_at") or "")
            or str(fm.get("date") or "")
        )
        entries.append({"path": path, "frontmatter": fm, "ts": ts})
    if not entries:
        return None
    entries.sort(key=lambda item: item["ts"], reverse=True)
    return entries[0]


def _bench_cooldown_status(*, settings: dict[str, Any], force: bool) -> dict[str, Any]:
    if _is_running():
        return {"status": "running", "detail": "bench run already in progress"}
    if force:
        return {"status": "ready"}
    if not settings.get("bench_enabled", False):
        return {"status": "disabled", "detail": "bench_enabled is false"}
    latest = _latest_bench_history_entry()
    if not latest:
        return {"status": "ready"}
    last_run = _parse_iso(latest["frontmatter"].get("run_finished_at") or latest["frontmatter"].get("updated_at"))
    if not last_run:
        return {"status": "ready"}
    interval_sec = int(settings.get("bench_interval_sec") or 604800)
    elapsed = (_now_utc() - last_run).total_seconds()
    if elapsed < interval_sec:
        return {
            "status": "cooldown",
            "detail": "bench interval has not elapsed yet",
            "last_run_at": last_run.isoformat().replace("+00:00", "Z"),
            "remaining_sec": max(0, int(interval_sec - elapsed)),
            "last_path": latest["path"],
        }
    return {"status": "ready"}


def _judge_pass_ratio(judged_payload: dict[str, Any]) -> tuple[float, int]:
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for judgment in judged_payload.get("judgments", []):
        task_id = str(judgment.get("task_id") or "").strip()
        if task_id:
            by_task[task_id].append(judgment)
    if not by_task:
        return 0.0, 0
    passed = sum(1 for judgments in by_task.values() if any(j.get("verdict") == "pass" for j in judgments))
    return passed / len(by_task), len(by_task)


def _find_newest_result(prefix: str, *, started_at: float) -> Path:
    candidates = [path for path in _results_dir().glob(f"{prefix}*.json") if path.stat().st_mtime >= started_at]
    if not candidates:
        candidates = list(_results_dir().glob(f"{prefix}*.json"))
    if not candidates:
        raise FileNotFoundError(f"no result file found for prefix={prefix}")
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def _run_command(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    logger.info("bench command: %s", " ".join(args))
    return subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True)


def _resolve_model(override: str | None = None) -> str:
    if override and override.strip():
        return override.strip()
    librarian_settings = load_librarian_settings()
    model = str(librarian_settings.get("model") or "").strip()
    if model:
        return model
    raise RuntimeError("No bench model configured and librarian model is empty")


def _build_note_body(
    *,
    report_markdown: str,
    reason: str,
    model: str,
    judge_model: str,
    tasks_file: str,
    run_files: dict[str, Path],
    judged_files: dict[str, Path],
) -> str:
    lines = [
        "## Run Metadata",
        f"- reason: {reason}",
        f"- model: {model}",
        f"- judge_model: {judge_model}",
        f"- tasks_file: {tasks_file}",
        "- run_files:",
    ]
    for condition in ("baseline", "standard", "openakashic"):
        lines.append(f"  - {condition}: {run_files[condition].name}")
    lines.append("- judged_files:")
    for condition in ("baseline", "standard", "openakashic"):
        lines.append(f"  - {condition}: {judged_files[condition].name}")
    lines.append("")
    lines.append(report_markdown.rstrip())
    lines.append("")
    return "\n".join(lines)


def _is_running() -> bool:
    with _RUN_LOCK:
        return _RUN_ACTIVE


def _set_running(value: bool) -> None:
    global _RUN_ACTIVE
    with _RUN_LOCK:
        _RUN_ACTIVE = value


def run_full_bench_and_record(
    *,
    reason: str,
    force: bool = False,
    settings: dict[str, Any] | None = None,
    tasks_file: str = "tasks.yaml",
    k: int = 1,
    model: str | None = None,
    judge_model: str = "gpt-5.4",
) -> dict[str, Any]:
    current_settings = dict(settings or {})
    cooldown = _bench_cooldown_status(settings=current_settings, force=force)
    if cooldown["status"] != "ready":
        return cooldown
    if _is_running():
        return {"status": "running", "detail": "bench run already in progress"}

    resolved_model = _resolve_model(model or current_settings.get("bench_model"))
    safe_model = _safe_model(resolved_model)
    started_dt = _now_utc()
    started_iso = started_dt.isoformat().replace("+00:00", "Z")
    run_files: dict[str, Path] = {}
    judged_files: dict[str, Path] = {}
    per_condition: dict[str, float] = {}
    task_count = 0

    with _RUN_LOCK:
        global _RUN_ACTIVE
        if _RUN_ACTIVE:
            return {"status": "running", "detail": "bench run already in progress"}
        _RUN_ACTIVE = True
    try:
        for condition in ("baseline", "standard", "openakashic"):
            started_marker = datetime.now().timestamp()
            _run_command(
                [
                    sys.executable,
                    "runner.py",
                    "--all",
                    "--model",
                    resolved_model,
                    "--condition",
                    condition,
                    "--k",
                    str(k),
                    "--tasks-file",
                    tasks_file,
                ],
                cwd=_bench_dir(),
            )
            run_path = _find_newest_result(
                f"run-{condition}-{safe_model}-",
                started_at=started_marker,
            )
            run_files[condition] = run_path

            _run_command(
                [
                    sys.executable,
                    "judge.py",
                    "--run",
                    str(run_path),
                    "--judge-model",
                    judge_model,
                ],
                cwd=_bench_dir(),
            )
            judged_path = run_path.with_name(f"{run_path.stem}-judged.json")
            judged_files[condition] = judged_path
            judged_payload = json.loads(judged_path.read_text(encoding="utf-8"))
            pass_ratio, judged_task_count = _judge_pass_ratio(judged_payload)
            per_condition[condition] = pass_ratio
            task_count = max(task_count, judged_task_count)

        report_stamp = started_dt.strftime("%Y%m%dT%H%M%SZ")
        report_out = _results_dir() / f"report-{safe_model}-scheduled-{report_stamp}.md"
        _run_command(
            [
                sys.executable,
                "report.py",
                "--judged",
                str(judged_files["baseline"]),
                str(judged_files["standard"]),
                str(judged_files["openakashic"]),
                "--out",
                str(report_out),
            ],
            cwd=_bench_dir(),
        )
        report_markdown = report_out.read_text(encoding="utf-8")
        finished_iso = _now_iso()
        note_path = _history_note_path(started_dt.date())
        write_document(
            path=note_path,
            title=f"OpenAkashicBench History — {started_dt.date().isoformat()}",
            kind="reference",
            project="ops",
            tags=["bench", "ops", "history", "metrics"],
            body=_build_note_body(
                report_markdown=report_markdown,
                reason=reason,
                model=resolved_model,
                judge_model=judge_model,
                tasks_file=tasks_file,
                run_files=run_files,
                judged_files=judged_files,
            ),
            metadata={
                "owner": SAGWAN_SYSTEM_OWNER,
                "created_by": "bench-scheduled",
                "date": started_dt.date().isoformat(),
                "model": resolved_model,
                "judge_model": judge_model,
                "tasks_file": tasks_file,
                "task_count": task_count,
                "pass_at_k_baseline": round(per_condition.get("baseline", 0.0), 4),
                "pass_at_k_standard": round(per_condition.get("standard", 0.0), 4),
                "pass_at_k_openakashic": round(per_condition.get("openakashic", 0.0), 4),
                "run_started_at": started_iso,
                "run_finished_at": finished_iso,
                "run_reason": reason,
            },
            allow_owner_change=True,
        )
        return {
            "status": "ok",
            "path": note_path,
            "model": resolved_model,
            "judge_model": judge_model,
            "tasks_file": tasks_file,
            "task_count": task_count,
            "pass_at_k_baseline": round(per_condition.get("baseline", 0.0), 4),
            "pass_at_k_standard": round(per_condition.get("standard", 0.0), 4),
            "pass_at_k_openakashic": round(per_condition.get("openakashic", 0.0), 4),
            "run_started_at": started_iso,
            "run_finished_at": finished_iso,
            "reason": reason,
        }
    finally:
        _set_running(False)


def trigger_full_bench_run_async(
    *,
    reason: str,
    force: bool = False,
    settings: dict[str, Any] | None = None,
    tasks_file: str = "tasks.yaml",
    k: int = 1,
    model: str | None = None,
    judge_model: str = "gpt-5.4",
) -> dict[str, Any]:
    current_settings = dict(settings or {})
    cooldown = _bench_cooldown_status(settings=current_settings, force=force)
    if cooldown["status"] != "ready":
        return cooldown
    try:
        resolved_model = _resolve_model(model or current_settings.get("bench_model"))
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}

    def _runner() -> None:
        try:
            run_full_bench_and_record(
                reason=reason,
                force=True,
                settings=current_settings,
                tasks_file=tasks_file,
                k=k,
                model=resolved_model,
                judge_model=judge_model,
            )
        except Exception as exc:
            logger.error("bench run failed: %s", exc, exc_info=True)

    thread = threading.Thread(target=_runner, daemon=True, name="openakashic-bench")
    thread.start()
    return {
        "status": "started",
        "async": True,
        "reason": reason,
        "tasks_file": tasks_file,
        "model": resolved_model,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reason", default="manual:cli")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--tasks-file", default="tasks.yaml")
    parser.add_argument("--k", type=int, default=1)
    parser.add_argument("--model", default="")
    parser.add_argument("--judge-model", default="gpt-5.4")
    args = parser.parse_args()
    result = run_full_bench_and_record(
        reason=args.reason,
        force=args.force,
        tasks_file=args.tasks_file,
        k=args.k,
        model=args.model or None,
        judge_model=args.judge_model,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"ok", "disabled", "cooldown", "running"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
