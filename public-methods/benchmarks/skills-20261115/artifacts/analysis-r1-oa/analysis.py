#!/usr/bin/env python3
"""Reproduce the Cedar descriptive comparison using Python's standard library."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

SERVICES = ('assisted', 'standard')
BRANCHES = ('East', 'West')
COLUMNS = ('service', 'branch', 'n_total', 'n_known', 'n_missing', 'n_success', 'success_rate')


def analyze(source, output):
    raw = source.read_bytes()
    with source.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ['case_id', 'branch', 'service', 'resolved']:
            raise ValueError('Unexpected input columns')
        cases = list(reader)
    identifiers = set()
    for case in cases:
        if not case['case_id'] or case['case_id'] in identifiers:
            raise ValueError('Missing or duplicate case ID')
        identifiers.add(case['case_id'])
        if case['service'] not in SERVICES or case['branch'] not in BRANCHES:
            raise ValueError('Unexpected service or branch')
        if case['resolved'] not in ('', '0', '1'):
            raise ValueError('Outcome must be blank, 0 or 1')
    summary = []
    for service in SERVICES:
        for branch in (*BRANCHES, 'ALL'):
            subset = [case for case in cases if case['service'] == service
                      and (branch == 'ALL' or case['branch'] == branch)]
            known = sum(case['resolved'] != '' for case in subset)
            successes = sum(case['resolved'] == '1' for case in subset)
            if not known:
                raise ValueError(f'No known outcomes for {service}/{branch}')
            summary.append(dict(zip(COLUMNS, (service, branch, len(subset), known,
                                             len(subset) - known, successes, successes / known))))
    lookup = {(row['service'], row['branch']): row for row in summary}
    equal_rates = {service: sum(lookup[service, branch]['success_rate'] for branch in BRANCHES) / 2
                   for service in SERVICES}
    comparison = {
        'pooled_difference_pp': 100 * (lookup['assisted', 'ALL']['success_rate'] - lookup['standard', 'ALL']['success_rate']),
        'equal_branch_difference_pp': 100 * (equal_rates['assisted'] - equal_rates['standard']),
    }
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'summary.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(summary)
    (output / 'comparison.json').write_text(json.dumps(comparison, indent=2) + '\n')
    table_rows = ''.join(
        f"<tr><th scope='row'>{row['service'].title()}</th><td>{row['branch']}</td>"
        f"<td>{row['n_total']}</td><td>{row['n_known']}</td>"
        f"<td>{row['n_missing']} ({row['n_missing']/row['n_total']:.1%})</td>"
        f"<td>{row['n_success']}</td><td>{row['success_rate']:.1%}</td></tr>" for row in summary)
    pooled = comparison['pooled_difference_pp']
    equal = comparison['equal_branch_difference_pp']
    report = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cedar pilot | Assisted vs standard</title>
<style>
:root {{color-scheme:light}} * {{box-sizing:border-box}} body {{margin:0;background:#f3f3ee;color:#202d33;font:17px/1.55 system-ui,sans-serif}}
main {{max-width:1050px;margin:36px auto;padding:36px;background:white;border-top:7px solid #28756b}}
h1 {{font-size:36px;line-height:1.15;margin:10px 0 20px}} h2 {{font-size:22px;margin:27px 0 10px}}
p {{margin:10px 0}} .eyebrow {{text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:700;color:#34645e}}
.cards {{display:flex;gap:18px;margin:22px 0}} .card {{flex:1;background:#eef4f2;padding:18px;border-left:4px solid #28756b}}
.value {{display:block;font-size:30px;font-weight:750}} .note {{font-size:14px;color:#49595f}}
table {{width:100%;border-collapse:collapse;font-size:14px}} th,td {{padding:10px 8px;text-align:right;border-bottom:1px solid #d9e1df}}
th:first-child,td:nth-child(2) {{text-align:left}} thead {{background:#edf2f0}} .table-wrap {{overflow-x:auto}}
footer {{margin-top:28px;padding-top:14px;border-top:1px solid #d9e1df;font-size:12px;overflow-wrap:anywhere}}
@media(max-width:650px) {{main {{margin:0;padding:22px}} .cards {{flex-direction:column}} h1 {{font-size:29px}}}}
@media print {{body {{background:white}} main {{margin:0;padding:15px;max-width:none}} .card,table {{break-inside:avoid}}}}
</style></head><body><main>
<div class="eyebrow">Cedar pilot / Operations evidence brief</div>
<h1>Assisted handling: better within branches, not in the pooled log</h1>
<p><strong>Bottom line:</strong> assisted has higher observed success rates in both East and West, but a lower pooled rate. The comparison changes direction when each branch gets equal weight. This is descriptive evidence, not proof that assisted handling causes better outcomes.</p>
<div class="cards"><section class="card"><strong>Pooled difference</strong><span class="value">{pooled:+.2f} pp</span>
Assisted 63.3% vs standard 66.7%<br><span class="note">38/60 vs 40/60 known outcomes</span></section>
<section class="card"><strong>Equal-branch difference</strong><span class="value">{equal:+.2f} pp</span>
Assisted {equal_rates['assisted']:.1%} vs standard {equal_rates['standard']:.1%}<br><span class="note">50% East + 50% West within each service</span></section></div>
<h2>What changes the answer?</h2>
<p>East: assisted 8/10 = 80.0%, standard 36/50 = 72.0% (<strong>+8.0 pp</strong>). West: assisted 30/50 = 60.0%, standard 4/10 = 40.0% (<strong>+20.0 pp</strong>). All four rates divide successes by known outcomes.</p>
<p>Among known outcomes, assisted is concentrated in lower-success West (50/60 = 83.3% of its known cases), while standard is concentrated in higher-success East (50/60 = 83.3% of its known cases). This mix produces a Simpson’s-paradox reversal: pooled assisted looks worse even though it looks better in each branch.</p>
<p>The equal-branch calculation is (80.0% + 60.0%)/2 = 70.0% for assisted and (72.0% + 40.0%)/2 = 56.0% for standard. Its 14.0 pp difference describes a hypothetical 50/50 branch mix, not the actual overall case mix or a causal effect. It adjusts only for branch.</p>
<h2>Counts and unknown outcomes</h2>
<p class="note">Success rate = successes / known outcomes. Unknown percentage = unknown / total cases in that row. ALL pools cases within a service; it is not the equal-branch average. pp means percentage points.</p>
<div class="table-wrap"><table><thead><tr><th scope="col">Service</th><th scope="col">Branch</th><th scope="col">Total</th><th scope="col">Known</th><th scope="col">Unknown (% total)</th><th scope="col">Successes</th><th scope="col">Success (% known)</th></tr></thead><tbody>{table_rows}</tbody></table></div>
<p>There are 20 unknown outcomes among 140 cases (14.3% of all cases). Each service has 10/70 unknown (14.3%), but missingness differs sharply by branch: assisted East 4/14 (28.6%) and West 6/56 (10.7%); standard East 1/51 (2.0%) and West 9/19 (47.4%). Equal service-level missingness does not remove this concern.</p>
<p>Blank outcomes remain unknown and are excluded from success-rate denominators, never coded as failures. If missing outcomes differ systematically from recorded ones, both comparisons may be biased.</p>
<h2>Decision and next step</h2>
<p>Do not declare a winner from this log alone. Assignment was not randomized; case difficulty, routing, staffing, timing or other unrecorded factors may differ even within a branch. One row per case does not establish independence across staff or repeated customers. These are point estimates for the observed log; no sampling-based confidence or significance claim is made.</p>
<p><strong>Next:</strong> recover unknown outcomes first, especially standard West, and audit routing and case difficulty by branch. If operationally feasible, run a prospective randomized comparison within each branch, with a fixed follow-up window, consistent outcome capture, and a prespecified weighting rule. Until then, use these results as a signal to investigate, not a basis for a causal rollout claim.</p>
<footer>Source: cases.csv · 140 case records · Descriptive, known-outcome analysis<br>Input SHA-256: {hashlib.sha256(raw).hexdigest()}<br>Reproduce: python /work/analysis.py --input /task/input/cases.csv --outdir /work</footer>
</main></body></html>'''
    (output / 'report.html').write_text(report, encoding='utf-8')
    print(json.dumps({'cases': len(cases), 'input_sha256': hashlib.sha256(raw).hexdigest(), **comparison}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('/task/input/cases.csv'))
    parser.add_argument('--outdir', type=Path, default=Path('/work'))
    args = parser.parse_args()
    analyze(args.input, args.outdir)
