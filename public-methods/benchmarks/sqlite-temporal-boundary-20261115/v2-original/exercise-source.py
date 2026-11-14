#!/usr/bin/env python3
"""Operator-only SQLite temporal-boundary fixture; run after the benchmark closes.

No API, model, network, production database, or candidate-grader calls. The
caller supplies an exact public method snapshot. Every run uses a new directory
and temporary synthetic databases. Results are observed, never pre-filled.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parent
ALLOWED_RUN_ROOT=ROOT/'boundary-runs'
METHOD_ID='method_5af91cc7219a4130a3a2cf2d7630b031'
LATER_VALUE='later-commit-after-four-pages'
HISTORICAL_V2_CLAIM='온라인 백업은 백업 시작 시점의 스냅샷이므로 백업 후 원본 변경을 포함하지 않는다.'
FEEDBACK={'outcomes','opinions','feedback_counts'}

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def file_sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write_json(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def now():return datetime.now(timezone.utc).isoformat()

def load_method(path,method_id,version):
    data=json.loads(path.read_text())
    if isinstance(data,dict) and isinstance(data.get('full_methods'),list):
        matches=[m for m in data['full_methods'] if m.get('id')==method_id and m.get('version')==version]
        if len(matches)!=1:raise ValueError('Exact method ID/version must occur once in the supplied public catalog')
        data=matches[0]
    required={'id','version','title','situation','goal','constraints','steps','success_criteria','limitations'}
    if not isinstance(data,dict) or not required<=data.keys():raise ValueError('A complete method snapshot is required')
    if data['id']!=method_id or data['version']!=version:raise ValueError('Method snapshot ID/version mismatch')
    return {key:value for key,value in data.items() if key not in FEEDBACK}

def read_database(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as con:
        integrity=con.execute('PRAGMA integrity_check').fetchall()
        foreign_keys=con.execute('PRAGMA foreign_key_check').fetchall()
        schema=con.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        rows=con.execute('SELECT id,value,payload FROM observations ORDER BY id').fetchall()
        return {'integrity':integrity,'foreign_key_violations':foreign_keys,'schema':schema,'rows':rows,
                'page_count':con.execute('PRAGMA page_count').fetchone()[0]}

def cleanup_observation(path):
    try:
        if path is None or not path.exists():
            return {'removed':True,'remaining_files':[],'fixture_databases_retained':False}
        files=sorted(str(file.relative_to(path)) for file in path.rglob('*') if file.is_file())
        return {'removed':False,'remaining_files':files,
                'fixture_databases_retained':any('.sqlite3' in name for name in files)}
    except OSError as exc:
        return {'removed':None,'remaining_files':None,'fixture_databases_retained':None,
                'inspection_error_type':type(exc).__name__}

def run(args):
    source_snapshot=args.method_snapshot.resolve(strict=True)
    method=load_method(source_snapshot,args.method_id,args.method_version)
    target=args.output.resolve()
    allowed=ALLOWED_RUN_ROOT.resolve()
    if target==allowed or allowed not in target.parents:
        raise ValueError('Output must be a new child directory inside the external boundary-runs folder')
    if target.exists():raise FileExistsError('Refusing to reuse or overwrite a prior run directory')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.mkdir(exist_ok=False)
    shutil.copyfile(Path(__file__),target/'exercise-source.py')
    write_json(target/'method-snapshot.json',method)
    report={'schema':'openakashic-sqlite-temporal-boundary-v1','started_at':now(),
        'scope':'Separate operator synthetic fixture, not an LLM-quality benchmark or production recovery.',
        'method':{'id':method['id'],'version':method['version'],'snapshot_sha256':digest(method),
                  'supplied_snapshot_file_sha256':file_sha(source_snapshot)},
        'claim_under_test':{'historical_method_version':2,'exact_text':HISTORICAL_V2_CLAIM,
            'present_in_loaded_snapshot':HISTORICAL_V2_CLAIM in method['limitations'],
            'loaded_revised_method_semantic_agreement':None,
            'boundary':'The counterexample flag targets this historical v2 sentence. Loaded v3 wording requires separate owner review and is not automatically called false.'},
        'runtime':{'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'platform':platform.platform()},
        'fixture':{'row_count':512,'payload_characters_per_row':3000,'requested_page_size':4096,
                   'journal_mode':'WAL','backup_pages_per_step':1,'inject_after_copied_pages':4,
                   'intentional_update':'one other connection commits a value change for id=1'},
        'observations':None,'checks':None,'counterexample_observed':None,'state':'running',
        'production_or_API_or_model_writes':0}
    progress=[]
    fixture_dir=None
    try:
        with tempfile.TemporaryDirectory(prefix='synthetic-fixture-',dir=target) as temporary:
            fixture_dir=Path(temporary).resolve()
            if target not in fixture_dir.parents:raise RuntimeError('Temporary fixture escaped the new run directory')
            source=fixture_dir/'source.sqlite3';destination=fixture_dir/'new-backup.sqlite3'
            with closing(sqlite3.connect(source,isolation_level=None)) as writer:
                writer.execute('PRAGMA page_size=4096')
                journal=writer.execute('PRAGMA journal_mode=WAL').fetchone()[0]
                if journal.lower()!='wal':raise RuntimeError('Synthetic WAL setup failed')
                writer.execute('PRAGMA wal_autocheckpoint=0')
                writer.execute('CREATE TABLE observations(id INTEGER PRIMARY KEY,value TEXT NOT NULL,payload TEXT NOT NULL)')
                writer.execute('BEGIN')
                writer.executemany('INSERT INTO observations VALUES(?,?,?)',
                    [(i,f'initial-{i}',f'payload-{i:04d}-'+'x'*3000) for i in range(1,513)])
                writer.commit()
                before=read_database(source)
                if before['page_count']<8:raise RuntimeError('Fixture must span at least eight pages')
                if source.resolve()==destination.resolve():raise RuntimeError('Source and destination must differ')
                fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                os.close(fd)
                injection={'committed':False,'callback_index':None,'copied_this_pass':None,'changed_rows':None,'committed_at':None}
                deadline=time.monotonic()+30.0

                def callback(status,remaining,total):
                    if time.monotonic()>deadline:raise TimeoutError('Bounded synthetic backup exceeded 30 seconds')
                    copied=total-remaining
                    event={'callback_index':len(progress)+1,'status':status,'remaining':remaining,
                           'total':total,'copied_this_pass':copied,'late_commit_already_done':injection['committed']}
                    progress.append(event)
                    if not injection['committed'] and copied>=4 and remaining>0:
                        writer.execute('BEGIN IMMEDIATE')
                        changed=writer.execute('UPDATE observations SET value=? WHERE id=1',(LATER_VALUE,)).rowcount
                        writer.commit()
                        injection.update({'committed':True,'callback_index':event['callback_index'],
                            'copied_this_pass':copied,'changed_rows':changed,'committed_at':now()})

                # No explicit read transaction pins the source snapshot. Another
                # connection commits once, between incremental backup steps.
                with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True,isolation_level=None)) as src:
                    with closing(sqlite3.connect(destination)) as dst:
                        src.backup(dst,pages=1,progress=callback,sleep=0.001)
                after=read_database(source)
            # All write/backup connections are closed before independent reopen.
            backed_up=read_database(destination)
            isolated_dir=fixture_dir/'isolated';isolated_dir.mkdir()
            isolated=isolated_dir/'standalone.sqlite3'
            with destination.open('rb') as inp,isolated.open('xb') as out:
                shutil.copyfileobj(inp,out)
            standalone=read_database(isolated)
            expected=list(before['rows'])
            if injection['committed']:
                expected[0]=(expected[0][0],LATER_VALUE,expected[0][2])
            remaining_increases=[{'from_callback':a['callback_index'],'to_callback':b['callback_index'],
                                  'from_remaining':a['remaining'],'to_remaining':b['remaining']}
                for a,b in zip(progress,progress[1:]) if b['remaining']>a['remaining']]
            late_in_destination=bool(backed_up['rows'] and backed_up['rows'][0][1]==LATER_VALUE)
            source_only_expected_write=after['schema']==before['schema'] and after['rows']==expected
            checks={
                'fixture_spans_at_least_eight_pages':before['page_count']>=8,
                'source_and_destination_are_distinct':source.resolve()!=destination.resolve(),
                'destination_was_created_exclusively':True,
                'intentional_other_connection_commit_after_exactly_four_pages':injection['committed'] and injection['changed_rows']==1 and injection['copied_this_pass']==4,
                'source_logical_state_changed_only_by_intentional_fixture_update':source_only_expected_write,
                'source_reopen_integrity_ok':after['integrity']==[('ok',)],
                'destination_reopen_integrity_ok':backed_up['integrity']==[('ok',)],
                'destination_schema_equals_source':backed_up['schema']==after['schema'],
                'destination_all_ordered_rows_match_one_expected_committed_state':backed_up['rows']==before['rows'] or backed_up['rows']==after['rows'],
                'standalone_main_file_integrity_ok':standalone['integrity']==[('ok',)],
                'standalone_schema_and_all_ordered_rows_equal_destination':standalone['schema']==backed_up['schema'] and standalone['rows']==backed_up['rows'],
                'foreign_key_check_executed_no_violations':not after['foreign_key_violations'] and not backed_up['foreign_key_violations'],
            }
            base_valid=all(checks.values())
            counterexample=bool(base_valid and injection['committed'] and injection['changed_rows']==1 and late_in_destination)
            report['checks']=checks
            report['observations']={
                'injection':injection,'progress_callbacks':len(progress),'remaining_increases':remaining_increases,
                'restart_signal_observed':bool(remaining_increases),
                'later_commit_in_destination':late_in_destination,
                'all_ordered_destination_rows_equal_final_source':backed_up['rows']==after['rows'],
                'all_ordered_standalone_rows_equal_final_source':standalone['rows']==after['rows'],
                'row_counts':{'before':len(before['rows']),'final_source':len(after['rows']),'destination':len(backed_up['rows'])},
                'ordered_row_sha256':{'before':digest(before['rows']),'final_source':digest(after['rows']),
                                      'destination':digest(backed_up['rows']),'standalone':digest(standalone['rows'])},
                'schema_sha256':{'before':digest(before['schema']),'final_source':digest(after['schema']),
                                 'destination':digest(backed_up['schema'])},
                'closed_database_sha256':{'source':file_sha(source),'destination':file_sha(destination),'standalone':file_sha(isolated)},
                'foreign_key_scope':'No foreign-key relationships exist in this one-table fixture; empty checks do not validate complex FK recovery.'}
            report['counterexample_observed']=counterexample
            report['state']=('bounded_observations_for_revised_method_review' if base_valid and method['version']>2 else
                             'counterexample_observed_in_bounded_fixture' if counterexample else
                             'counterexample_not_observed_no_failure_link_supported' if base_valid else 'fixture_validation_failed')
            report['conclusion_boundary']=('A later committed change appears in a valid backup. This contradicts the quoted historical v2 start-time claim for this configuration; it does not claim the loaded revised method is false.'
                if counterexample else 'Do not manufacture a counterexample or correction edge. Preserve the actual observations and any limits.')
    except Exception as exc:
        report['state']='fixture_error_after_observations_preserved' if report['observations'] is not None else 'fixture_error_counterexample_not_established'
        report['error']={'type':type(exc).__name__,'message':str(exc)}
    finally:
        cleanup=cleanup_observation(fixture_dir)
        report['cleanup_observation']=cleanup
        report['temporary_fixture_removed']=cleanup['removed']
        report['finished_at']=now()
        write_json(target/'progress.json',progress)
        write_json(target/'report.json',report)
        write_json(target/'artifact-manifest.json',{
            'schema':'openakashic-sqlite-boundary-artifacts-v1','run_state':report['state'],
            'method_id':method['id'],'method_version':method['version'],'method_snapshot_sha256':digest(method),
            'files_sha256':{name:file_sha(target/name) for name in ('exercise-source.py','method-snapshot.json','progress.json','report.json')},
            'fixture_databases_retained':cleanup['fixture_databases_retained'],
            'temporary_fixture_removed':report['temporary_fixture_removed']})
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--method-snapshot',type=Path,required=True,help='exact public method JSON or frozen public catalog; read only')
    parser.add_argument('--method-id',default=METHOD_ID)
    parser.add_argument('--method-version',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True,help='new child of outcome-recording/boundary-runs')
    arguments=parser.parse_args()
    result=run(arguments)
    print(json.dumps({'state':result['state'],'method':result['method'],'counterexample_observed':result['counterexample_observed'],
                      'temporary_fixture_removed':result['temporary_fixture_removed']},sort_keys=True))
    sys.exit(0 if result['state'] in ('counterexample_observed_in_bounded_fixture','counterexample_not_observed_no_failure_link_supported','bounded_observations_for_revised_method_review') else 2)
