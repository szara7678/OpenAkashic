#!/usr/bin/env python3
"""Verify public hashes/accounting, optionally replay frozen checks. No models/auth."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys
R=Path(__file__).resolve().parent
def load(name):return json.loads((R/name).read_text())
def main():
 p=argparse.ArgumentParser();p.add_argument('--replay-checks',action='store_true');p.add_argument('--image',default='oa-practical-replay');args=p.parse_args()
 expected={}
 for line in (R/'SHA256SUMS').read_text().splitlines():
  digest,name=line.split('  ',1);target=(R/name).resolve()
  assert target.is_relative_to(R.resolve()),name
  assert hashlib.sha256(target.read_bytes()).hexdigest()==digest,name
  expected[name]=digest
 actual={str(x.relative_to(R)) for x in R.rglob('*') if x.is_file() and x.name!='SHA256SUMS' and '__pycache__' not in x.parts}
 assert actual==set(expected),{'unlisted':sorted(actual-set(expected)),'missing':sorted(set(expected)-actual)}
 runs=load('run-metrics.json');schedule=load('schedule.json');summary=load('summary.json');grades=load('blind-grades.json')
 assert len(runs)==len(schedule)==len(grades)==8
 assert {x['id'] for x in runs}=={x['id'] for x in schedule}
 assert len({x['anonymous'] for x in grades})==8
 grade_by_run={x['run_id']:x for x in grades}
 for row in runs:
  usage=row['provider_usage']
  if usage is not None:
   assert usage['input_tokens']+usage['output_tokens']==usage['total_tokens']
   assert 0<=usage['cached_input_tokens']<=usage['input_tokens']
  grade=grade_by_run[row['id']]
  expected_success=row['normal_CLI_completion'] and row['artifact_checker_passed'] and row['retrieval_compliant'] and all(grade[k]>=1 for k in ['correctness','evidence_fit','limitations','artifact_usability']) and not grade['material_unsupported_claim']
  assert row['full_task_success']==expected_success,row['id']
 for arm in ['web','oa']:
  rows=[x for x in runs if x['arm']==arm]
  assert len(rows)==4
  assert summary['arms'][arm]['quality_successes']==sum(x['full_task_success'] for x in rows)
 assert summary['overall_token_change_percent'] is None
 assert summary['arms']['oa']['provider_usage_all_attempts'] is None
 assert summary['arms']['web']['quality_successes']==2 and summary['arms']['oa']['quality_successes']==1
 assert load('method-snapshot-hashes.json')['method_count']==61
 assert load('source-validation-summary.json')['comparison_freeze_nonempty_quote_records']==75
 replay=[]
 if args.replay_checks:
  for row in runs:
   workspace=R/'candidates'/row['id']
   cmd=['docker','run','--rm','--network','none','--read-only','--user','65534:65534','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','1g','--cpus','1','--tmpfs','/tmp:rw,size=128m,mode=1777','-e','PYTHONDONTWRITEBYTECODE=1','-v',str(workspace)+':/work:ro','-v',str(R/'checker.py')+':/check.py:ro',args.image,'python','/check.py',row['task']]
   try:
    q=subprocess.run(cmd,capture_output=True,text=True,timeout=40)
    try:out=json.loads(q.stdout)
    except ValueError:out={'all_passed':False,'parse_error':True}
    entry={'id':row['id'],'exit_code':q.returncode,'checker':out,'matches_recorded_acceptance':bool(out.get('all_passed'))==row['artifact_checker_passed']}
   except subprocess.TimeoutExpired:entry={'id':row['id'],'replay_timeout':True,'matches_recorded_acceptance':False}
   replay.append(entry)
  assert all(x['matches_recorded_acceptance'] for x in replay),replay
 print(json.dumps({'hashes_verified':len(expected),'scheduled_attempts':8,'grades':8,'quality_successes':{'web':2,'oa':1},'all_provider_response_identities_verified':False,'all_cohort_token_change_percent':None,'replay':replay},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
