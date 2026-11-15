"""Independent fixture checks and deterministic rerun; writes actual QA results."""
import csv
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path('/work')
source = Path('/task/input/cases.csv')
cases = list(csv.DictReader(source.open()))
assert len(cases) == 140
assert len({case['case_id'] for case in cases}) == 140
expected = {
    ('assisted', 'East'): (14, 10, 4, 8),
    ('assisted', 'West'): (56, 50, 6, 30),
    ('assisted', 'ALL'): (70, 60, 10, 38),
    ('standard', 'East'): (51, 50, 1, 36),
    ('standard', 'West'): (19, 10, 9, 4),
    ('standard', 'ALL'): (70, 60, 10, 40),
}
with (root / 'summary.csv').open() as stream:
    reader = csv.DictReader(stream)
    assert reader.fieldnames == ['service', 'branch', 'n_total', 'n_known', 'n_missing', 'n_success', 'success_rate']
    summary = list(reader)
assert len(summary) == 6
assert len({(row['service'], row['branch']) for row in summary}) == 6
for row in summary:
    key = row['service'], row['branch']
    counts = tuple(int(row[column]) for column in ('n_total', 'n_known', 'n_missing', 'n_success'))
    assert counts == expected[key]
    assert counts[0] == counts[1] + counts[2]
    assert abs(float(row['success_rate']) - float(Fraction(counts[3], counts[1]))) < 1e-12
    selected = [case for case in cases if case['service'] == key[0] and (key[1] == 'ALL' or case['branch'] == key[1])]
    assert len(selected) == counts[0]
    assert sum(case['resolved'] == '' for case in selected) == counts[2]
    assert sum(case['resolved'] == '1' for case in selected) == counts[3]
comparison = json.loads((root / 'comparison.json').read_text())
assert set(comparison) == {'pooled_difference_pp', 'equal_branch_difference_pp'}
assert all(isinstance(value, (float, int)) for value in comparison.values())
assert abs(comparison['pooled_difference_pp'] - float(Fraction(-10, 3))) < 1e-12
assert abs(comparison['equal_branch_difference_pp'] - 14) < 1e-12
assert comparison['pooled_difference_pp'] < 0 < comparison['equal_branch_difference_pp']
html = (root / 'report.html').read_text()
assert '<html lang="en">' in html and '<table>' in html
assert 'src=' not in html and 'href=' not in html
assert 'never failures' in html and 'observational' in html
with tempfile.TemporaryDirectory() as temporary:
    subprocess.run([sys.executable, str(root / 'analysis.py'), '--input', str(source), '--output-dir', temporary], check=True, capture_output=True)
    for name in ('summary.csv', 'comparison.json', 'report.html'):
        assert (Path(temporary) / name).read_bytes() == (root / name).read_bytes()
(root / 'QA.md').write_text('''# Executed QA

Commands: `python /work/analysis.py`; `python /work/verify.py`.

All assertions passed:
- Input: 140 rows, 140 distinct case IDs; analysis validates schema, domains and nonzero known denominators.
- CSV: exact seven-column schema, six unique service/branch rows; each row matches independent fixture counts and direct input recounts.
- Each row: total = known + missing; success rate = successes / known to tolerance 1e-12. Pooled rows reconcile to branch rows.
- Assisted counts (total, known, missing, success): East (14,10,4,8), West (56,50,6,30), ALL (70,60,10,38).
- Standard counts: East (51,50,1,36), West (19,10,9,4), ALL (70,60,10,40).
- JSON: exactly two numeric entries, pooled difference −10/3 pp and equal-branch difference +14 pp, each within 1e-12; direction reversal verified.
- HTML: English language marker and table present; no external `src` or `href` references; unknown-outcome and observational caveats present.
- A fresh subprocess rerun in a temporary directory produced byte-identical CSV, JSON and HTML. Temporary files cleaned automatically.

These checks establish arithmetic, schema and reproducibility for this fixture, not causality or unbiased outcome ascertainment. Rendering and visual QA are recorded separately below when performed.
''')
print('PASS: fixture counts, CSV schema, numeric differences, HTML checks, byte-identical rerun.')
