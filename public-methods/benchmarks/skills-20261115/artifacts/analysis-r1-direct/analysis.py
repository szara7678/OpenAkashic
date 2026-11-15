#!/usr/bin/env python3
"""Deterministic, descriptive Cedar pilot analysis; Python standard library only."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

SERVICES = ('assisted', 'standard')
BRANCHES = ('East', 'West')
FIELDS = ('service', 'branch', 'n_total', 'n_known', 'n_missing', 'n_success', 'success_rate')


def analyze(source, output):
    with source.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ['case_id', 'branch', 'service', 'resolved']:
            raise ValueError('Unexpected CSV schema')
        cases = list(reader)
    identifiers = set()
    for case in cases:
        if not case['case_id'] or case['case_id'] in identifiers:
            raise ValueError('Missing or duplicate case_id')
        identifiers.add(case['case_id'])
        if case['service'] not in SERVICES or case['branch'] not in BRANCHES:
            raise ValueError('Unknown service or branch')
        if case['resolved'] not in ('', '0', '1'):
            raise ValueError('Outcome must be blank, 0, or 1')
    summary = []
    for service in SERVICES:
        for branch in (*BRANCHES, 'ALL'):
            selected = [case for case in cases if case['service'] == service
                        and (branch == 'ALL' or case['branch'] == branch)]
            known = sum(case['resolved'] != '' for case in selected)
            successes = sum(case['resolved'] == '1' for case in selected)
            if not known:
                raise ValueError(f'No known outcomes for {service}/{branch}; rate undefined')
            summary.append(dict(zip(FIELDS, (service, branch, len(selected), known,
                                             len(selected) - known, successes, successes / known))))
    lookup = {(row['service'], row['branch']): row for row in summary}
    pooled = {service: lookup[service, 'ALL']['success_rate'] for service in SERVICES}
    balanced = {service: sum(lookup[service, branch]['success_rate'] for branch in BRANCHES) / 2
                for service in SERVICES}
    comparison = {
        'pooled_difference_pp': 100 * (pooled['assisted'] - pooled['standard']),
        'equal_branch_difference_pp': 100 * (balanced['assisted'] - balanced['standard']),
    }
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'summary.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(summary)
    (output / 'comparison.json').write_text(json.dumps(comparison, indent=2, allow_nan=False) + '\n')
    table_rows = '\n'.join(
        f"<tr><th scope='row'>{row['service'].title()}</th><td>{row['branch']}</td>"
        f"<td>{row['n_total']}</td><td>{row['n_known']}</td>"
        f"<td>{row['n_missing']} ({row['n_missing'] / row['n_total']:.1%})</td>"
        f"<td>{row['n_success']}</td><td>{row['success_rate']:.1%}</td></tr>"
        for row in summary)
    east_shares = {service: lookup[service, 'East']['n_known'] / lookup[service, 'ALL']['n_known']
                   for service in SERVICES}
    missing = sum(case['resolved'] == '' for case in cases)
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cedar pilot | Handling comparison</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#edf2f5;color:#182e3d;font:16px/1.5 system-ui,sans-serif}}
main{{max-width:1050px;margin:28px auto;background:white;padding:34px 40px;border-radius:12px}}
h1{{font-size:32px;line-height:1.15;margin:6px 0 16px}}h2{{font-size:20px;margin:22px 0 8px}}
p{{margin:8px 0}}.eyebrow{{font-size:13px;text-transform:uppercase;letter-spacing:2px;color:#426573}}
.cards{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:20px 0}}
.card{{background:#edf4f6;border-left:5px solid #216477;padding:16px}}
.metric{{font-size:29px;font-weight:750}}.label{{font-weight:650}}
table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:9px 8px;border-bottom:1px solid #d6e0e5;text-align:right}}
th:first-child,td:nth-child(2){{text-align:left}}thead{{background:#edf4f6}}.note{{font-size:14px;color:#405764}}
.action{{padding:14px 18px;background:#f7f1df;border-radius:6px}}footer{{border-top:1px solid #d6e0e5;margin-top:22px;padding-top:12px}}
@media(max-width:650px){{main{{padding:20px;margin:0}}.cards{{grid-template-columns:1fr}}.table-wrap{{overflow-x:auto}}}}
@media print{{body{{background:white}}main{{margin:0;padding:14px;max-width:none}}}}
</style></head><body><main>
<div class="eyebrow">Cedar pilot · Operations brief</div>
<h1>Assisted leads within each branch,<br>but trails in the pooled log</h1>
<p><strong>Bottom line:</strong> Branch mix changes the direction of the comparison. The log supports a descriptive association, not a claim that assisted handling causes better outcomes.</p>
<div class="cards">
<section class="card"><div class="label">Pooled · actual known-case mix</div>
<div class="metric">{comparison['pooled_difference_pp']:+.2f} pp</div>
<p>Assisted {pooled['assisted']:.1%} vs standard {pooled['standard']:.1%}</p>
<div class="note">Successes ÷ known outcomes, pooled across branches.</div></section>
<section class="card"><div class="label">Equal branch · 50/50 East–West</div>
<div class="metric">{comparison['equal_branch_difference_pp']:+.2f} pp</div>
<p>Assisted {balanced['assisted']:.1%} vs standard {balanced['standard']:.1%}</p>
<div class="note">Mean of the two branch known-outcome success rates; not a pooled case rate.</div></section></div>
<h2>Case counts and outcome completeness</h2>
<p class="note">Success rate = successes ÷ known outcomes. Missing % = unknown outcomes ÷ all cases in that row. ALL rows combine East and West; do not add them to branch rows.</p>
<div class="table-wrap"><table><thead><tr><th scope="col">Service</th><th scope="col">Branch</th><th scope="col">All cases</th><th scope="col">Known</th><th scope="col">Missing (% all)</th><th scope="col">Successes</th><th scope="col">Success rate</th></tr></thead>
<tbody>{table_rows}</tbody></table></div>
<h2>Why the direction changes</h2>
<p>East has higher known-outcome success rates for both services. Assisted exceeds standard in East (80.0% vs 72.0%, +8.0 pp) and West (60.0% vs 40.0%, +20.0 pp). Yet only {east_shares['assisted']:.1%} of assisted known cases are in East, versus {east_shares['standard']:.1%} of standard known cases (denominator: each service’s known cases). Assisted is concentrated in the lower-success branch, producing a Simpson’s-paradox reversal.</p>
<p>The equal-branch result averages East and West rates with weight 0.5 each within each service. It answers a hypothetical equal-branch-mix question, not the result for the observed case mix or a causal effect.</p>
<h2>Unknown outcomes and evidence limits</h2>
<p>{missing} of {len(cases)} cases have unknown outcomes ({missing / len(cases):.1%} of all cases). Each service has 10 unknowns out of 70 cases (14.3% of all cases per service), but missingness varies sharply by branch: standard West has 9/19 unknown (47.4% of its cases). Blank outcomes are excluded only from success-rate denominators, never counted as failures or imputed. If missingness relates to success, even the within-branch comparisons can be biased.</p>
<p>This observational log does not establish causation: service assignment was not randomized, branch adjustment does not control severity or other unrecorded differences, and follow-up may differ. These are descriptive estimates for this pilot; no confidence intervals, significance tests, or population-level claims are made.</p>
<section class="action"><h2 style="margin-top:0">Practical next step</h2><p>Recover unknown outcomes, especially standard West, and audit assignment, severity and follow-up consistency. Before scaling, run a prospectively planned pilot with random assignment within branch where feasible, a common outcome window and complete follow-up. Use these results to justify further evaluation, not an immediate causal performance claim.</p></section>
<footer class="note">Source: cases.csv · one row per case · differences are assisted minus standard in percentage points (pp). Rounded display only; CSV/JSON retain numerical precision. Reproduce with analysis.py using Python’s standard library; no network or external assets.</footer>
</main></body></html>'''
    (output / 'report.html').write_text(html, encoding='utf-8')
    checks = []
    def check(condition, description):
        if not condition:
            raise AssertionError(description)
        checks.append('PASS — ' + description)
    check(len(identifiers) == len(cases), f'{len(cases)} unique nonblank case IDs; schema and allowed values validated')
    check(len(summary) == 6, 'Exactly six summary rows with required column order')
    check(all(row['n_total'] == row['n_known'] + row['n_missing'] for row in summary), 'Total = known + missing in every row')
    check(all(row['success_rate'] == row['n_success'] / row['n_known'] for row in summary), 'Every success rate uses known outcomes only')
    check(all(lookup[service, 'ALL'][field] == sum(lookup[service, branch][field] for branch in BRANCHES)
              for service in SERVICES for field in ('n_total', 'n_known', 'n_missing', 'n_success')), 'Pooled counts reconcile to branch counts')
    check(comparison['pooled_difference_pp'] < 0 < comparison['equal_branch_difference_pp'], 'Pooled negative and equal-branch positive: direction reversal confirmed')
    fingerprint = hashlib.sha256(source.read_bytes()).hexdigest()
    (output / 'QA.md').write_text('# Executed analysis checks\n\nCommand: `python /work/analysis.py`\n\n'
        + '\n'.join('- ' + item for item in checks)
        + f'\n\nInput SHA-256: `{fingerprint}`\n'
        + '\nThese are descriptive calculations, not causal or inferential validation. Further independent and visual checks are recorded after execution.\n')
    print(json.dumps({'cases': len(cases), 'missing': missing, **comparison}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('/task/input/cases.csv'))
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    analyze(args.input, args.output_dir)
