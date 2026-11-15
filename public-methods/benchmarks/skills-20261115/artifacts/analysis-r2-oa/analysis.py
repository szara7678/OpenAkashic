#!/usr/bin/env python3
"""Reproduce Cedar's descriptive comparisons using only the Python standard library."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

SERVICES = ('assisted', 'standard')
BRANCHES = ('East', 'West')
COLUMNS = ('service', 'branch', 'n_total', 'n_known', 'n_missing', 'n_success', 'success_rate')


def analyze(input_path, output_dir):
    with input_path.open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ['case_id', 'branch', 'service', 'resolved']:
            raise ValueError('Expected columns: case_id,branch,service,resolved')
        cases = list(reader)
    seen = set()
    for case in cases:
        if (not case['case_id'] or case['case_id'] in seen
                or case['service'] not in SERVICES or case['branch'] not in BRANCHES
                or case['resolved'] not in ('', '0', '1') or None in case):
            raise ValueError(f'Invalid or duplicate case: {case!r}')
        seen.add(case['case_id'])
    summary = []
    for service in SERVICES:
        for branch in (*BRANCHES, 'ALL'):
            selected = [case for case in cases if case['service'] == service
                        and (branch == 'ALL' or case['branch'] == branch)]
            known = sum(case['resolved'] != '' for case in selected)
            success = sum(case['resolved'] == '1' for case in selected)
            if not known:
                raise ValueError(f'No known outcomes for {service}/{branch}; rate undefined')
            summary.append(dict(zip(COLUMNS, (service, branch, len(selected), known,
                                               len(selected) - known, success, success / known))))
    lookup = {(row['service'], row['branch']): row for row in summary}
    equal = {service: sum(lookup[service, branch]['success_rate'] for branch in BRANCHES) / 2
             for service in SERVICES}
    comparison = {
        'pooled_difference_pp': 100 * (lookup['assisted', 'ALL']['success_rate']
                                       - lookup['standard', 'ALL']['success_rate']),
        'equal_branch_difference_pp': 100 * (equal['assisted'] - equal['standard']),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / 'summary.csv').open('w', newline='', encoding='utf-8') as destination:
        writer = csv.DictWriter(destination, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(summary)
    (output_dir / 'comparison.json').write_text(json.dumps(comparison, indent=2, allow_nan=False) + '\n')

    def percent(value):
        return f'{value:.1%}'

    table_rows = ''.join(
        f"<tr><th scope='row'>{row['service'].title()} · {row['branch']}</th>"
        f"<td>{row['n_total']}</td><td>{row['n_known']}</td><td>{row['n_missing']} "
        f"({percent(row['n_missing'] / row['n_total'])})</td>"
        f"<td>{row['n_success']} / {row['n_known']}</td><td>{percent(row['success_rate'])}</td></tr>"
        for row in summary)
    all_assisted, all_standard = (lookup[service, 'ALL'] for service in SERVICES)
    mix = {service: lookup[service, 'East']['n_known'] / lookup[service, 'ALL']['n_known']
           for service in SERVICES}
    branch_differences = {branch: 100 * (lookup['assisted', branch]['success_rate']
                                        - lookup['standard', branch]['success_rate']) for branch in BRANCHES}
    reversal = comparison['pooled_difference_pp'] * comparison['equal_branch_difference_pp'] < 0
    headline = ('The apparent winner changes when branch mix is balanced.' if reversal
                else 'Branch balance changes the size of the comparison, not its direction.')
    digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cedar pilot — handling comparison</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f4ef;color:#19352e;font:16px/1.55 system-ui,sans-serif}}
main{{max-width:1020px;margin:auto;padding:35px 32px}}.eyebrow{{font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase}}
h1{{font-size:34px;line-height:1.15;max-width:800px;margin:12px 0 18px}}h2{{font-size:21px;margin:24px 0 8px}}p{{margin:8px 0 14px}}
.cards{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:22px 0}}.card{{background:white;border-top:4px solid #357c68;padding:18px 22px}}
.value{{font-size:34px;font-weight:750}}.label{{font-size:14px}}.card p{{margin:4px 0}}.note{{background:#e3ebe3;padding:16px 20px;border-left:4px solid #357c68}}
table{{width:100%;border-collapse:collapse;font-size:14px;background:white}}th,td{{padding:10px 9px;border-bottom:1px solid #d9dfd8;text-align:right}}th:first-child{{text-align:left}}thead{{background:#e3ebe3}}
caption{{text-align:left;margin:0 0 9px;font-size:14px}}footer{{font-size:12px;color:#435b54;border-top:1px solid #bccac1;margin-top:25px;padding-top:13px;overflow-wrap:anywhere}}
@media(max-width:650px){{main{{padding:24px 15px}}h1{{font-size:28px}}.cards{{grid-template-columns:1fr}}.table-wrap{{overflow-x:auto}}}}
@media print{{body{{background:white}}main{{padding:0}}.card,table,.note{{break-inside:avoid}}}}
</style></head><body><main>
<div class="eyebrow">Cedar pilot / Operations evidence brief</div>
<h1>{headline}</h1>
<p><strong>Bottom line:</strong> This observational log does not establish that assisted handling causes better outcomes.
Among recorded outcomes, assisted handling has a higher success rate in both branches, despite a lower pooled rate.</p>
<div class="cards"><section class="card"><div class="label">POOLED · observed branch mix</div>
<div class="value">{comparison['pooled_difference_pp']:+.2f} pp</div>
<p>Assisted {percent(all_assisted['success_rate'])} vs standard {percent(all_standard['success_rate'])}</p>
<div class="label">Each rate = successes ÷ known outcomes across both branches.</div></section>
<section class="card"><div class="label">EQUAL BRANCH · 50% East / 50% West</div>
<div class="value">{comparison['equal_branch_difference_pp']:+.2f} pp</div>
<p>Assisted {percent(equal['assisted'])} vs standard {percent(equal['standard'])}</p>
<div class="label">Each rate = average of the two branch known-outcome success rates.</div></section></div>
<p class="label">All differences are assisted minus standard, in percentage points (pp). Displayed rates are rounded; calculations use full precision.</p>
<h2>Why the direction changes</h2>
<p>Assisted leads by {branch_differences['East']:.1f} pp in East and {branch_differences['West']:.1f} pp in West.
But East, the higher-success branch, represents only {percent(mix['assisted'])} of assisted known outcomes,
versus {percent(mix['standard'])} of standard known outcomes. Pooling therefore gives standard much more weight in East.
This is a Simpson’s-paradox reversal, not contradictory arithmetic.</p>
<p>The equal-branch comparison uses (East rate + West rate) ÷ 2 within each service, then subtracts standard from assisted.
It describes a hypothetical evenly weighted branch mix, not the observed case mix or an adjusted causal effect.</p>
<h2>Counts, denominators and unknown outcomes</h2>
<div class="table-wrap"><table><caption>Success percentages use known outcomes only. Missing percentages use all cases in that row. ALL rows pool both branches; do not add them to branch rows.</caption>
<thead><tr><th scope="col">Service · branch</th><th scope="col">All cases</th><th scope="col">Known</th><th scope="col">Missing (% all)</th><th scope="col">Success / known</th><th scope="col">Success rate</th></tr></thead>
<tbody>{table_rows}</tbody></table></div>
<p>There are {len(cases)} cases. Each service has {all_assisted['n_total']} cases and {all_assisted['n_missing']} unknown outcomes
({percent(all_assisted['n_missing']/all_assisted['n_total'])} of its cases). Equal overall missingness hides different branch patterns:
unknown outcomes are concentrated differently across services. Blank outcomes remain unknown, never failures;
they stay in total and missing counts but are excluded from success-rate denominators. If missingness relates to outcome or handling,
even these known-outcome comparisons may be biased.</p>
<h2>Decision and next step</h2>
<div class="note"><strong>Do not declare a causal winner or roll out based on the pooled result.</strong>
Reconcile the unknown outcomes and audit branch-specific recording practices. Then run a prospective pilot with random assignment
within each branch, if feasible, a common follow-up window, and prespecified success and missingness tracking.</div>
<p>This is a descriptive observational comparison, not a randomized experiment. Branch balancing addresses only branch mix;
severity, eligibility, timing and selection into handling may still differ. No confidence intervals or significance tests are presented:
sampling, dependence and missingness assumptions are not established. The log alone does not show whether differences are reliable
beyond these cases or caused by the handling method.</p>
<footer>Source: cases.csv · One row per case · resolved=1 success, resolved=0 non-success, blank unknown.<br>
Reproduce: python /work/analysis.py · No external assets or requests.<br>Input SHA-256: {digest}</footer>
</main></body></html>'''
    (output_dir / 'report.html').write_text(html, encoding='utf-8')
    print(json.dumps({'n_cases': len(cases), **comparison}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('/task/input/cases.csv'))
    parser.add_argument('--output-dir', type=Path, default=Path('/work'))
    arguments = parser.parse_args()
    analyze(arguments.input, arguments.output_dir)
