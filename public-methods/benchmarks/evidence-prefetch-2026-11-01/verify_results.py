#!/usr/bin/env python3
from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parent
for line in (root/'SHA256SUMS').read_text().splitlines():
 h,name=line.split('  ',1);p=(root/name).resolve();assert p.is_relative_to(root.resolve());assert hashlib.sha256(p.read_bytes()).hexdigest()==h,name
count=0
for phase,expected in [('development',27),('validation',18)]:
 s=json.loads((root/phase/'summary.json').read_text());a=json.loads((root/phase/'answers-and-checks.json').read_text());assert len(s['runs'])==len(a['runs'])==expected
 receipts=json.loads((root/phase/'provider-receipts.json').read_text())['runs'];byrun={r['id']:r for r in s['runs']};assert len(receipts)==expected
 for record in receipts:
  run=byrun[record['run']];events=record['receipts'];assert len(events)==run['model_calls']
  sums=dict(input_tokens=0,output_tokens=0,total_tokens=0,cached_input_tokens=0)
  for event in events:
   u=event.get('usage');assert isinstance(u,dict),record['run']
   assert all(type(u.get(k)) is int and u[k]>=0 for k in ('input_tokens','output_tokens','total_tokens'))
   assert u['input_tokens']+u['output_tokens']==u['total_tokens'],record['run']
   cached=u.get('input_tokens_details',{}).get('cached_tokens',0);assert type(cached) is int and 0<=cached<=u['input_tokens']
   for k in ('input_tokens','output_tokens','total_tokens'):sums[k]+=u[k]
   sums['cached_input_tokens']+=cached
  assert all(sums[k]==run[k] for k in sums),record['run']
 assert sum(x['total_tokens'] for x in s['runs'])==s['experiment_candidate_tokens']
 for arm,t in s['totals'].items():
  runs=[r for r in s['runs'] if r['arm']==arm];assert len(runs)==9
  assert sum(r['full_success'] for r in runs)==t['full_successes']
  assert sum(r['total_tokens'] for r in runs)==t['total_tokens']
  assert sum(r['decisions_correct'] for r in runs)==t['decisions_correct']
 for comparison,c in s['comparisons'].items():
  arm=comparison.split('_vs_direct')[0];t=s['totals'][arm];d=s['totals']['direct'];quality=t['full_successes']>=8 and t['full_successes']>=d['full_successes']
  assert c['quality_gate_passed']==quality
  assert c['primary_token_gate_passed']==bool(quality and c['tokens_per_success_reduction']>=.30)
 count+=expected
assert count==45
print('Verified all exported hashes, 45-run summaries, and every provider receipt token/cache arithmetic.')
