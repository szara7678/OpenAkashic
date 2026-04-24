#!/usr/bin/env python3
"""OpenAkashicBench — A/B comparison report.

Reads two or more *-judged.json files (one per condition) and produces a
side-by-side markdown comparing baseline vs openakashic per task.

Usage:
  python3 report.py --judged results/run-baseline-...-judged.json \
                              results/run-openakashic-...-judged.json \
                    --out results/report-haiku-v05.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


KNOWN_CONDITION_ORDER = [
    "cli_baseline",
    "cli_openakashic",
    "baseline",
    "standard",
    "openakashic",
]


def load_judged(paths: list[Path]) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in paths]


def aggregate_by_task_condition(bundles: list[dict[str, Any]]
                                ) -> dict[str, dict[str, Any]]:
    """Group judgments by (task_id, condition) → list of attempts."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for b in bundles:
        cond = b.get("condition") or "unknown"
        for j in b.get("judgments", []):
            buckets[(j["task_id"], cond)].append(j)

    out: dict[str, dict[str, Any]] = {}
    for (tid, cond), judgs in buckets.items():
        k = len(judgs)
        passes = sum(1 for j in judgs if j["verdict"] == "pass")
        hit_rates = [j.get("score", {}).get("hit_rate", 0.0) for j in judgs]
        traps = [j.get("score", {}).get("traps_hit_count", 0) for j in judgs]
        out.setdefault(tid, {})[cond] = {
            "k": k,
            "passes": passes,
            "pass_at_k": 1 if passes >= 1 else 0,
            "pass_pow_k": 1 if passes == k else 0,
            "mean_hit_rate": sum(hit_rates) / len(hit_rates) if hit_rates else 0.0,
            "total_traps_hit": sum(traps),
            "missed": [j.get("missed", []) for j in judgs],
            "traps_detail": [j.get("traps_hit", []) for j in judgs],
            "reasons": [j.get("reason", "") for j in judgs],
        }
    return out


def render_markdown(bundles: list[dict[str, Any]],
                    per_task: dict[str, dict[str, Any]]) -> str:
    model = bundles[0].get("model", "unknown")
    raw_conditions = {b.get("condition") for b in bundles if b.get("condition")}
    conditions = [c for c in KNOWN_CONDITION_ORDER if c in raw_conditions]
    conditions += sorted(raw_conditions - set(conditions))
    cli_harnesses = sorted({b.get("cli_harness") for b in bundles if b.get("cli_harness")})

    lines: list[str] = [
        f"# OpenAkashicBench — A/B Report",
        "",
        f"**Model**: `{model}`  ",
        f"**Conditions compared**: {', '.join(conditions)}  ",
        f"**CLI harnesses**: {', '.join(cli_harnesses) if cli_harnesses else 'n/a'}  ",
        f"**Tasks**: {len(per_task)}",
        "",
    ]

    lines.append("## Summary (pass@k by condition)")
    lines.append("")
    lines.append("| task | " + " | ".join(f"{c} pass@k" for c in conditions) +
                 " | " + " | ".join(f"{c} hit rate" for c in conditions) +
                 " | " + " | ".join(f"{c} traps" for c in conditions) + " |")
    lines.append("|" + "---|" * (1 + 3 * len(conditions)))
    for tid in sorted(per_task.keys()):
        row = [tid]
        for c in conditions:
            d = per_task[tid].get(c)
            row.append(str(d["pass_at_k"]) if d else "—")
        for c in conditions:
            d = per_task[tid].get(c)
            row.append(f"{d['mean_hit_rate']:.2f}" if d else "—")
        for c in conditions:
            d = per_task[tid].get(c)
            row.append(str(d["total_traps_hit"]) if d else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    def _pair_lift(left: str, right: str, label: str) -> None:
        if left not in conditions or right not in conditions:
            return
        lines.append(f"### {label}: {right} vs {left}")
        lines.append("")
        lines.append(
            f"| task | {left} pass@k | {right} pass@k | Δ pass@k | "
            f"{left} hit | {right} hit | Δ hit | "
            f"{left} traps | {right} traps | trap reduction |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        tot_l_p = tot_r_p = 0
        tot_l_h = tot_r_h = 0.0
        tot_l_t = tot_r_t = 0
        counted = 0
        for tid in sorted(per_task.keys()):
            L = per_task[tid].get(left)
            R = per_task[tid].get(right)
            if not (L and R):
                continue
            trap_reduction = L["total_traps_hit"] - R["total_traps_hit"]
            lines.append(
                f"| {tid} | {L['pass_at_k']} | {R['pass_at_k']} | {R['pass_at_k']-L['pass_at_k']:+d} | "
                f"{L['mean_hit_rate']:.2f} | {R['mean_hit_rate']:.2f} | "
                f"{R['mean_hit_rate']-L['mean_hit_rate']:+.2f} | "
                f"{L['total_traps_hit']} | {R['total_traps_hit']} | "
                f"{trap_reduction:+d} |"
            )
            tot_l_p += L["pass_at_k"]
            tot_r_p += R["pass_at_k"]
            tot_l_h += L['mean_hit_rate']; tot_r_h += R['mean_hit_rate']
            tot_l_t += L['total_traps_hit']; tot_r_t += R['total_traps_hit']
            counted += 1
        if counted:
            lines.append(
                f"| **mean** | **{tot_l_p/counted:.2f}** | **{tot_r_p/counted:.2f}** | "
                f"**{(tot_r_p-tot_l_p)/counted:+.2f}** | "
                f"**{tot_l_h/counted:.2f}** | **{tot_r_h/counted:.2f}** | "
                f"**{(tot_r_h-tot_l_h)/counted:+.2f}** | **{tot_l_t}** | **{tot_r_t}** | "
                f"**{tot_l_t-tot_r_t:+d}** |"
            )
        lines.append("")

    if "cli_baseline" in conditions or "cli_openakashic" in conditions:
        lines.append("## CLI conditions")
        lines.append("")
        _pair_lift("cli_baseline", "cli_openakashic", "Primary benchmark")

    simulated_present = any(c in conditions for c in ("baseline", "standard", "openakashic"))
    if simulated_present:
        lines.append("## Simulated conditions")
        lines.append("")
        _pair_lift("baseline", "standard", "기본 에이전트 도구가 주는 이득")
        _pair_lift("standard", "openakashic", "OpenAkashic 고유 가치")
        _pair_lift("baseline", "openakashic", "전체 lift")

    lines.append("## Per-task detail")
    lines.append("")
    for tid in sorted(per_task.keys()):
        lines.append(f"### {tid}")
        lines.append("")
        for c in conditions:
            d = per_task[tid].get(c)
            if not d:
                lines.append(f"- **{c}**: (not run)")
                continue
            lines.append(f"- **{c}** (k={d['k']}): passes {d['passes']}/{d['k']}, "
                         f"hit_rate mean {d['mean_hit_rate']:.2f}, traps_hit {d['total_traps_hit']}")
            for reason in d["reasons"]:
                if reason:
                    lines.append(f"  - {reason}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judged", nargs="+", required=True)
    parser.add_argument("--out", help="markdown output path")
    args = parser.parse_args()

    paths = [Path(p).resolve() for p in args.judged]
    bundles = load_judged(paths)
    per_task = aggregate_by_task_condition(bundles)
    md = render_markdown(bundles, per_task)
    if args.out:
        Path(args.out).write_text(md)
        print(f"Saved: {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
