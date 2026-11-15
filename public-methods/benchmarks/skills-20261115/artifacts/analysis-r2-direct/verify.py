"""Independent fixture and artifact checks; writes the actual QA result."""
import csv
import hashlib
import json
import math
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

root = Path('/work')
expected = {
    ('assisted', 'East'): (14, 10, 4, 8),
    ('assisted', 'West'): (56, 50, 6, 30),
    ('assisted', 'ALL'): (70, 60, 10, 38),
    ('standard', 'East'): (51, 50, 1, 36),
    ('standard', 'West'): (19, 10, 9, 4),
    ('standard', 'ALL'): (70, 60, 10, 40),
}
source = Path('/task/input/cases.csv')
before = hashlib.sha256(source.read_bytes()).hexdigest()
with (root / 'summary.csv').open() as handle:
    reader = csv.DictReader(handle)
    assert reader.fieldnames == ['service', 'branch', 'n_total', 'n_known', 'n_missing', 'n_success', 'success_rate']
    rows = list(reader)
assert len(rows) == 6
assert {(row['service'], row['branch']) for row in rows} == set(expected)
for row in rows:
    counts = tuple(int(row[column]) for column in ['n_total', 'n_known', 'n_missing', 'n_success'])
    assert counts == expected[row['service'], row['branch']]
    assert counts[0] == counts[1] + counts[2]
    assert math.isclose(float(row['success_rate']), counts[3] / counts[1], abs_tol=1e-12)
comparison = json.loads((root / 'comparison.json').read_text())
assert set(comparison) == {'pooled_difference_pp', 'equal_branch_difference_pp'}
for key, value in [('pooled_difference_pp', -10 / 3), ('equal_branch_difference_pp', 14)]:
    assert isinstance(comparison[key], (int, float))
    assert math.isclose(comparison[key], value, abs_tol=1e-12)
assert comparison['pooled_difference_pp'] < 0 < comparison['equal_branch_difference_pp']

class OfflineParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        assert tag not in ('script', 'iframe', 'link', 'img'), tag
        for name, value in attrs:
            assert name not in ('src', 'href'), (name, value)

report = (root / 'report.html').read_text()
OfflineParser().feed(report)
assert '<html lang="en">' in report and report.count('<tr') == 7
for text in ['−3.3', '+14.0', '47.4%', 'not randomized', 'none are imputed']:
    assert text.replace('−', '-') in report
with tempfile.TemporaryDirectory() as temporary:
    subprocess.run([sys.executable, str(root / 'analysis.py'), '--input', str(source), '--output-dir', temporary], check=True)
    for name in ['summary.csv', 'comparison.json', 'report.html']:
        assert (root / name).read_bytes() == (Path(temporary) / name).read_bytes(), name
assert hashlib.sha256(source.read_bytes()).hexdigest() == before
with (root / 'QA.md').open('a') as handle:
    handle.write('''\n## Independent verification\nExecuted `python /work/verify.py`: PASS.\n- Exact six-row schema, service/branch combinations, fixture counts, count identities, and all rate denominators passed.\n- Numeric JSON keys matched −10/3 and +14 pp within 1e-12; direction reversal passed.\n- HTML parsed; seven table rows including header, English language, expected numerical/caution text, and no external asset/script/link elements passed.\n- Re-ran analysis in a temporary directory: all three generated outputs were byte-identical.\n- Input SHA-256 unchanged across rerun: `''' + before + '''`.\n- These are artifact and fixture checks, not evidence of causal validity.\n''')
print('PASS: counts, schemas, numeric rates, direction reversal, offline HTML, deterministic rerun, unchanged source')
