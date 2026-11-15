"""Independent fixture-specific verification; run after analysis.py."""
import csv
import hashlib
import json
import math
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
fields = ['service', 'branch', 'n_total', 'n_known', 'n_missing', 'n_success', 'success_rate']
expected = {
    ('assisted', 'East'): (14, 10, 4, 8),
    ('assisted', 'West'): (56, 50, 6, 30),
    ('assisted', 'ALL'): (70, 60, 10, 38),
    ('standard', 'East'): (51, 50, 1, 36),
    ('standard', 'West'): (19, 10, 9, 4),
    ('standard', 'ALL'): (70, 60, 10, 40),
}
with (ROOT / 'summary.csv').open(newline='') as stream:
    reader = csv.DictReader(stream)
    assert reader.fieldnames == fields
    rows = list(reader)
assert len(rows) == 6
assert {(row['service'], row['branch']) for row in rows} == set(expected)
for row in rows:
    total, known, missing, success = expected[row['service'], row['branch']]
    assert [int(row[field]) for field in fields[2:6]] == [total, known, missing, success]
    assert math.isclose(float(row['success_rate']), success / known, abs_tol=1e-12)
comparison = json.loads((ROOT / 'comparison.json').read_text())
assert set(comparison) == {'pooled_difference_pp', 'equal_branch_difference_pp'}
assert all(type(value) in (int, float) and math.isfinite(value) for value in comparison.values())
assert math.isclose(comparison['pooled_difference_pp'], -10 / 3, abs_tol=1e-12)
assert math.isclose(comparison['equal_branch_difference_pp'], 14, abs_tol=1e-12)

class OfflineParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        assert tag not in ('script', 'iframe', 'link', 'img')
        assert all(key not in ('src', 'href') for key, value in attrs)

html = (ROOT / 'report.html').read_text()
OfflineParser().feed(html)
assert '<html lang="en">' in html and html.count('<tbody>') == 1
assert 'never counted as failures or imputed' in html
assert 'not establish causation' in html
assert '−' not in json.dumps(comparison)
artifacts = ['summary.csv', 'comparison.json', 'report.html']
with tempfile.TemporaryDirectory() as directory:
    subprocess.run([sys.executable, str(ROOT / 'analysis.py'), '--output-dir', directory],
                   check=True, capture_output=True, text=True)
    for name in artifacts:
        assert (ROOT / name).read_bytes() == (Path(directory) / name).read_bytes(), name
    invalid = Path(directory) / 'invalid.csv'
    original = Path('/task/input/cases.csv').read_text()
    invalid.write_text(original.replace('C001,East,assisted,1', 'C001,East,assisted,unknown', 1))
    result = subprocess.run([sys.executable, str(ROOT / 'analysis.py'), '--input', str(invalid),
                             '--output-dir', str(Path(directory) / 'bad')], capture_output=True, text=True)
    assert result.returncode != 0 and 'Outcome must be blank, 0, or 1' in result.stderr
print('PASS: exact six-row schema and fixture counts; known-outcome rates; both numerical differences;')
print('offline HTML structure and caveat text; byte-identical rerun of three deliverables; invalid outcome rejected.')
print('summary.csv SHA-256:', hashlib.sha256((ROOT / 'summary.csv').read_bytes()).hexdigest())
