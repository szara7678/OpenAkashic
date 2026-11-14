#!/usr/bin/env python3
"""Verify archived public artifact bytes only; never execute the fixture."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
manifest=json.loads((ROOT/'manifest.json').read_text())
for name,expected in manifest['files_sha256'].items():
    path=(ROOT/name).resolve()
    if ROOT not in path.parents:raise SystemExit('unsafe manifest path')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise SystemExit('artifact hash mismatch: '+name)
for folder,version in [('v2-original',2),('v3-corrected',3)]:
    report=json.loads((ROOT/folder/'report.json').read_text())
    if report['method']['version']!=version:raise SystemExit('method version mismatch')
    if not all(report['checks'].values()):raise SystemExit('archived fixture check failed')
    if not report['temporary_fixture_removed']:raise SystemExit('archived fixture cleanup unconfirmed')
print(json.dumps({'verified_files':len(manifest['files_sha256']),'archived_runs':2,
                  'fixture_executed_by_verifier':False,'API_or_model_calls':0},sort_keys=True))
