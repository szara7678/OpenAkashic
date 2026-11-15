#!/usr/bin/env python3
"""Deterministic, standard-library-only analysis of the Cedar case log."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path

SERVICES = ('assisted', 'standard')
BRANCHES = ('East', 'West')
COLUMNS = ('service', 'branch', 'n_total', 'n_known', 'n_missing', 'n_success', 'success_rate')


def analyze(source, destination):
    raw = source.read_bytes()
    with source.open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ['case_id', 'branch', 'service', 'resolved']:
            raise ValueError('Unexpected input schema')
        cases = list(reader)
    identifiers = set()
    for case in cases:
        if set(case) != set(reader.fieldnames) or any(value is None for value in case.values()):
            raise ValueError('Nonrectangular input')
        if not case['case_id'] or case['case_id'] in identifiers:
            raise ValueError('Missing or duplicate case identifier')
        identifiers.add(case['case_id'])
        if case['branch'] not in BRANCHES or case['service'] not in SERVICES:
            raise ValueError('Unexpected branch or service')
        if case['resolved'] not in ('', '0', '1'):
            raise ValueError('Outcome must be blank, 0, or 1')
    summary = []
    for service in SERVICES:
        for branch in (*BRANCHES, 'ALL'):
            subset = [case for case in cases if case['service'] == service
                      and (branch == 'ALL' or case['branch'] == branch)]
            known = sum(case['resolved'] != '' for case in subset)
            success = sum(case['resolved'] == '1' for case in subset)
            if not known:
                raise ValueError(f'No known outcomes for {service}/{branch}')
            summary.append(dict(zip(COLUMNS, (service, branch, len(subset), known,
                                               len(subset) - known, success, success / known))))
    lookup = {(row['service'], row['branch']): row for row in summary}
    balanced = {service: sum(lookup[service, branch]['success_rate'] for branch in BRANCHES) / 2
                for service in SERVICES}
    pooled = {service: lookup[service, 'ALL']['success_rate'] for service in SERVICES}
    comparison = {
        'pooled_difference_pp': 100 * (pooled['assisted'] - pooled['standard']),
        'equal_branch_difference_pp': 100 * (balanced['assisted'] - balanced['standard']),
    }
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / 'summary.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(summary)
    (destination / 'comparison.json').write_text(json.dumps(comparison, indent=2, allow_nan=False) + '\n')
    table_rows = []
    for row in summary:
        style = ' class="pooled"' if row['branch'] == 'ALL' else ''
        table_rows.append(f'<tr{style}><th scope="row">{html.escape(row["service"].title())}</th>'
                          f'<td>{row["branch"]}</td><td>{row["n_total"]}</td>'
                          f'<td>{row["n_known"]}</td><td>{row["n_success"]}</td>'
                          f'<td>{row["success_rate"]:.1%}</td>'
                          f'<td>{row["n_missing"]} / {row["n_total"]} ({row["n_missing"] / row["n_total"]:.1%})</td></tr>')
    east_difference = 100 * (lookup['assisted', 'East']['success_rate'] - lookup['standard', 'East']['success_rate'])
    west_difference = 100 * (lookup['assisted', 'West']['success_rate'] - lookup['standard', 'West']['success_rate'])
    report = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cedar pilot | Assisted vs standard handling</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#edf2f4;color:#172e3b;font:16px/1.5 system-ui,sans-serif}}
main{{max-width:1050px;margin:30px auto;background:white;padding:32px 40px;border-top:7px solid #16776c;border-radius:8px}}
.eyebrow{{text-transform:uppercase;letter-spacing:.13em;font-size:12px;font-weight:700;color:#16776c}}
h1{{font-size:31px;line-height:1.2;margin:8px 0 16px}}h2{{font-size:20px;margin:25px 0 8px}}p{{margin:8px 0}}
.cards{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:22px 0}}.card{{padding:16px 20px;background:#f0f6f6;border-radius:6px}}
.card strong{{display:block;font-size:30px;line-height:1.3}}.card span{{font-weight:650}}.muted,footer{{color:#49616e;font-size:13px}}
table{{width:100%;border-collapse:collapse;font-size:14px;margin:12px 0}}th,td{{padding:9px 8px;text-align:right;border-bottom:1px solid #d9e3e7}}
th:first-child,td:nth-child(2){{text-align:left}}thead{{background:#eaf1f4}}.pooled{{background:#f3f7f8}}.note{{border-left:4px solid #d3a044;padding:10px 15px;background:#fff8eb}}
footer{{margin-top:24px;border-top:1px solid #d9e3e7;padding-top:12px;overflow-wrap:anywhere}}
@media(max-width:720px){{main{{padding:20px;margin:10px}}.cards{{grid-template-columns:1fr}}.table-wrap{{overflow-x:auto}}}}
@media print{{body{{background:white}}main{{margin:0;padding:10px;border:0}}.card,table{{break-inside:avoid}}}}
</style></head><body><main>
<div class="eyebrow">Cedar pilot · Operations evidence brief</div>
<h1>Assisted handling looks better within branches,<br>but worse in the pooled log</h1>
<p><b>Decision:</b> Do not use the pooled ranking alone to choose a service. Assisted handling has higher observed success in both branches; this is an association, not evidence that assistance caused improvement.</p>
<div class="cards"><section class="card"><span>Pooled difference</span><strong>{comparison['pooled_difference_pp']:+.1f} pp</strong>
<p>Assisted {pooled['assisted']:.1%} vs standard {pooled['standard']:.1%}</p><div class="muted">Successes ÷ known outcomes for each service, across both branches.</div></section>
<section class="card"><span>Equal-branch difference</span><strong>{comparison['equal_branch_difference_pp']:+.1f} pp</strong>
<p>Assisted {balanced['assisted']:.1%} vs standard {balanced['standard']:.1%}</p><div class="muted">Mean of East and West success rates within each service; each branch gets 50% weight.</div></section></div>
<h2>What changes the direction?</h2>
<p>Among known outcomes, assisted exceeds standard in East by {east_difference:.1f} percentage points (80.0% vs 72.0%) and in West by {west_difference:.1f} points (60.0% vs 40.0%). Yet assisted has 50 of its 60 known outcomes in West, where success is lower for both services; standard has 50 of its 60 in East. This mix produces a Simpson’s-paradox reversal in the pooled comparison.</p>
<p>Equal-branch rates are (80.0% + 60.0%) / 2 = 70.0% for assisted and (72.0% + 40.0%) / 2 = 56.0% for standard. This is a hypothetical 50/50 branch mix, not the actual case-weighted performance or full case-mix adjustment.</p>
<h2>Outcome counts and denominators</h2>
<p class="muted">Success rate = successes / known outcomes. Missing percentage = unknown outcomes / all cases in that row. ALL rows pool branches and repeat the same cases; do not add them to branch rows. Displayed percentages are rounded to one decimal.</p>
<div class="table-wrap"><table><thead><tr><th scope="col">Service</th><th scope="col">Branch</th><th scope="col">All cases</th><th scope="col">Known</th><th scope="col">Successes</th><th scope="col">Success rate</th><th scope="col">Missing / all</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table></div>
<h2>Unknown is not failure</h2>
<p>All {len(cases)} cases are included in the counts. There are 20 unknown outcomes (20/140 = 14.3% of all cases): 10/70 = 14.3% in each service. Equal overall missingness hides different branch patterns, notably standard West with 9/19 = 47.4% unknown. If outcome recording is related to success, both the pooled and equal-branch estimates may be biased. Blank outcomes are excluded only from success-rate denominators; none are imputed.</p>
<h2>What the log can—and cannot—support</h2>
<p>This observational log is not randomized. Branch weighting addresses only branch mix, not severity, routing, staff, timing, or other unrecorded differences. Outcome definitions and follow-up windows are not supplied beyond the resolved flag (1 = success, 0 = failure, blank = unknown). Small known-outcome cells and missing data limit stability and generalization; these descriptive differences do not establish causation or statistical significance.</p>
<p class="note"><b>Practical next step:</b> Audit and recover unknown outcomes, prioritizing standard West, using a consistent outcome definition and follow-up window. Track success and missingness by branch. Before wider rollout, run a prospective, branch-stratified randomized pilot if feasible, with consistent case eligibility and severity capture.</p>
<footer>Method: complete local log, one row per case; no row sampling, no imputation, no external resources. Differences are assisted minus standard; pp = percentage points. Source: cases.csv · SHA-256: {hashlib.sha256(raw).hexdigest()}. Reproduce with analysis.py; see README.md and QA.md for checks and limitations.</footer>
</main></body></html>'''
    (destination / 'report.html').write_text(report, encoding='utf-8')
    print(json.dumps({'cases': len(cases), 'summary_rows': len(summary), **comparison}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('/task/input/cases.csv'))
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent)
    options = parser.parse_args()
    analyze(options.input, options.output_dir)
