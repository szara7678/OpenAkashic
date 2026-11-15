"""Independent, fixture-specific verification; no third-party dependencies."""
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
from html.parser import HTMLParser

root = Path('/work')
with open('/task/input/cases.csv', newline='') as stream:
    cases = list(csv.DictReader(stream))
with (root / 'summary.csv').open(newline='') as stream:
    reader = csv.DictReader(stream)
    assert reader.fieldnames == ['service', 'branch', 'n_total', 'n_known', 'n_missing', 'n_success', 'success_rate']
    summary = list(reader)
expected = {
    ('assisted', 'East'): (14, 10, 4, 8, .8),
    ('assisted', 'West'): (56, 50, 6, 30, .6),
    ('assisted', 'ALL'): (70, 60, 10, 38, 38 / 60),
    ('standard', 'East'): (51, 50, 1, 36, .72),
    ('standard', 'West'): (19, 10, 9, 4, .4),
    ('standard', 'ALL'): (70, 60, 10, 40, 40 / 60),
}
assert len(cases) == 140 and len(summary) == 6
assert {(row['service'], row['branch']) for row in summary} == set(expected)
for row in summary:
    key = row['service'], row['branch']
    counts = tuple(int(row[column]) for column in ('n_total', 'n_known', 'n_missing', 'n_success'))
    assert counts == expected[key][:4]
    assert counts[0] == counts[1] + counts[2]
    assert 0 <= counts[3] <= counts[1]
    assert math.isclose(float(row['success_rate']), expected[key][4], abs_tol=1e-12)
comparison = json.loads((root / 'comparison.json').read_text())
assert set(comparison) == {'pooled_difference_pp', 'equal_branch_difference_pp'}
assert all(isinstance(value, (int, float)) for value in comparison.values())
assert math.isclose(comparison['pooled_difference_pp'], -10 / 3, abs_tol=1e-12)
assert math.isclose(comparison['equal_branch_difference_pp'], 14, abs_tol=1e-12)
assert comparison['pooled_difference_pp'] < 0 < comparison['equal_branch_difference_pp']

class AuditHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.external = []
        self.table_rows = 0
    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.table_rows += 1
        for name, value in attrs:
            if name in ('src', 'href') and value and not value.startswith('#'):
                self.external.append(value)

html = (root / 'report.html').read_text()
audit = AuditHTML()
audit.feed(html)
assert not audit.external and audit.table_rows == 7
assert 'http://' not in html and 'https://' not in html and '@import' not in html
assert 'Blank outcomes remain unknown' in html
with tempfile.TemporaryDirectory() as temporary:
    subprocess.run(['python', '/work/analysis.py', '--input', '/task/input/cases.csv', '--outdir', temporary], check=True, capture_output=True)
    for filename in ('summary.csv', 'comparison.json', 'report.html'):
        assert (root / filename).read_bytes() == (Path(temporary) / filename).read_bytes()
    malformed = Path(temporary) / 'bad.csv'
    for label, changed in (
        ('invalid outcome', [{**cases[0], 'resolved': '2'}, *cases[1:]]),
        ('duplicate ID', [cases[0], cases[0], *cases[2:]]),
        ('unknown branch', [{**cases[0], 'branch': 'North'}, *cases[1:]]),
    ):
        with malformed.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['case_id', 'branch', 'service', 'resolved'])
            writer.writeheader()
            writer.writerows(changed)
        result = subprocess.run(['python', '/work/analysis.py', '--input', str(malformed), '--outdir', temporary], capture_output=True)
        assert result.returncode != 0, label
print('PASS: exact schema, six groups, all counts/rates, conservation, numeric differences and reversal')
print('PASS: HTML seven table rows; no external resource attributes, URLs or CSS imports')
print('PASS: byte-identical reproduction for all three generated artifacts')
print('PASS: rejection of invalid outcome, duplicate ID and unexpected branch')
print('Input SHA-256:', hashlib.sha256(Path('/task/input/cases.csv').read_bytes()).hexdigest())
