"""Hidden deterministic evaluator. Run ONLY via isolated Docker wrapper."""
import copy, importlib.util, json, math, os, shutil, sqlite3, sys, tempfile, traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
RESULT=[]
def check(name, fn):
    try:fn();RESULT.append({'name':name,'pass':True})
    except Exception as e:RESULT.append({'name':name,'pass':False,'error':type(e).__name__+': '+str(e)[:700]})
def eq(a,b):
    assert a==b,(a,b)
def raises(kind,fn):
    try:fn()
    except kind:return
    raise AssertionError('expected '+kind.__name__)
def compare(a,b):
    if isinstance(b,dict):
        assert isinstance(a,dict);eq(set(a),set(b))
        for k in b:compare(a[k],b[k])
    elif isinstance(b,list):
        assert isinstance(a,list);eq(len(a),len(b))
        for x,y in zip(a,b):compare(x,y)
    elif isinstance(b,float):assert isinstance(a,(int,float)) and math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-9),(a,b)
    else:eq(a,b)

def sqlite_checks(m,root):
    source=root/'catalog.sqlite'; target=root/'review.sqlite'
    c=sqlite3.connect(source)
    c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA wal_autocheckpoint=0')
    c.executescript('CREATE TABLE parent(id INTEGER PRIMARY KEY,label TEXT); CREATE TABLE "item notes"(id INTEGER PRIMARY KEY,parent_id INTEGER REFERENCES parent(id),memo BLOB); CREATE TABLE bag(tag TEXT, quantity REAL); CREATE INDEX lookup_note ON "item notes"(parent_id); CREATE VIEW note_labels AS SELECT id,memo FROM "item notes";')
    c.executemany('INSERT INTO parent VALUES(?,?)',[(3,'blue'),(8,'cedar')])
    c.executemany('INSERT INTO "item notes" VALUES(?,?,?)',[(11,3,b'x\x00y'),(19,999,b'orphan')])
    c.executemany('INSERT INTO bag VALUES(?,?)',[('same',1.5),('same',1.5),(None,None)])
    c.commit()
    def logical(db):
        schema=db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' ORDER BY type,name").fetchall()
        tables=[r[1] for r in schema if r[0]=='table']
        data={t:sorted(db.execute('SELECT * FROM "'+t.replace('"','""')+'"').fetchall(),key=repr) for t in tables}
        return schema,data
    before=logical(c)
    holder={}
    def backup():
        holder['r']=m.backup_review(str(source),str(target))
        assert isinstance(holder['r'],dict)
        assert target.exists()
    check('committed-wal-copy-created',backup)
    def contents():
        with sqlite3.connect(target) as d:
            eq(logical(d),before)
            eq(d.execute('PRAGMA integrity_check').fetchall(),[('ok',)])
            eq(d.execute('SELECT * FROM note_labels ORDER BY id').fetchall(),[(11,b'x\x00y'),(19,b'orphan')])
        standalone=root/'standalone';standalone.mkdir()
        shutil.copyfile(target,standalone/'only-main.sqlite')
        with sqlite3.connect(standalone/'only-main.sqlite') as d:eq(d.execute('SELECT count(*) FROM "item notes"').fetchone(),(2,))
    check('schema-rows-and-independent-reopen',contents)
    def report():
        r=holder['r'];eq(r['integrity_ok'],True);eq(r['copy_matches'],True)
        eq(r['relation_valid'],False)
        eq(sorted(r['foreign_key_violations']),[['item notes',19,'parent',0]])
        eq(r['tables'],{'parent':2,'item notes':2,'bag':3})
        json.dumps(r,allow_nan=False)
    check('copy-and-foreign-key-validity-distinguished',report)
    def protect():
        existing=root/'existing.sqlite';existing.write_bytes(b'KEEP EXISTING TARGET')
        raises(FileExistsError,lambda:m.backup_review(str(source),str(existing)))
        eq(existing.read_bytes(),b'KEEP EXISTING TARGET')
    check('existing-target-preserved',protect)
    def absent():
        missing=root/'absent.sqlite'; dst=root/'absent-target.sqlite'
        raises(FileNotFoundError,lambda:m.backup_review(str(missing),str(dst)))
        assert not missing.exists() and not dst.exists()
    check('missing-source-not-created',absent)
    def unchanged():eq(logical(c),before)
    check('source-logical-state-preserved',unchanged)
    c.close()

def probe_checks(m,root):
    original={'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'render','labels':{'tier':'batch'}},
     'spec':{'replicas':3,'template':{'metadata':{'annotations':{'audit':'keep'}},'spec':{'containers':[
      {'name':'metrics','image':'metrics:1','ports':[{'containerPort':9090}]},
      {'name':'renderer','image':'render:4','env':[{'name':'MODE','value':'safe'}],'ports':[{'name':'health','containerPort':8087}],
       'readinessProbe':{'exec':{'command':['false']},'initialDelaySeconds':99},
       'livenessProbe':{'httpGet':{'path':'/ready','port':'health'}}}
     ]}}}}
    before=copy.deepcopy(original);hold={}
    def produce():hold['out']=m.configure_probes(original);assert isinstance(hold['out'],dict)
    check('configuration-produced',produce)
    def probes():
        c=hold['out']['spec']['template']['spec']['containers'][1]
        for kind,path,period,threshold in [('startup','/boot',5,32),('readiness','/ready',4,2),('liveness','/live',10,3)]:
            p=c[kind+'Probe'];eq(p.get('httpGet'),{'path':path,'port':'health'});eq(p.get('periodSeconds'),period);eq(p.get('failureThreshold'),threshold);eq(p.get('timeoutSeconds'),1)
            assert 'initialDelaySeconds' not in p and 'exec' not in p and 'tcpSocket' not in p and 'grpc' not in p
    check('three-purpose-probe-configuration',probes)
    def preserve():
        eq(original,before); out=copy.deepcopy(hold['out']);target=out['spec']['template']['spec']['containers'][1]
        for key in ('startupProbe','readinessProbe','livenessProbe'):target.pop(key,None)
        clean=copy.deepcopy(before);target=clean['spec']['template']['spec']['containers'][1]
        for key in ('startupProbe','readinessProbe','livenessProbe'):target.pop(key,None)
        eq(out,clean)
    check('input-sidecar-and-unrelated-fields-preserved',preserve)
    def effects():
        for kind,threshold,effect in [('startup',32,'restart_container'),('readiness',2,'remove_from_service'),('liveness',3,'restart_container')]:
            for n in (0,threshold-1,threshold,threshold+4):
                eq(m.probe_effect(kind,n,True),'no_action' if n<threshold else effect)
        for kind in ('readiness','liveness'):
            for n in (0,1,100):eq(m.probe_effect(kind,n,False),'gated')
        eq(m.probe_effect('startup',32,False),'restart_container')
    check('thresholds-gating-and-failure-effects',effects)
    def invalid():
        raises(ValueError,lambda:m.probe_effect('bogus',0,True));raises(ValueError,lambda:m.probe_effect('readiness',-1,True))
        missing=copy.deepcopy(before);missing['spec']['template']['spec']['containers']=[missing['spec']['template']['spec']['containers'][0]]
        raises(ValueError,lambda:m.configure_probes(missing))
    check('invalid-inputs-rejected',invalid)

def pandas_checks(m,root):
    df=pd.DataFrame({'desk':['east','east','east','west','west','empty'],'wait_minutes':[4.,None,10.,None,None,None],'charge':[None,20.,40.,5.,None,None]},index=[7,7,2,9,1,0])
    before=df.copy(deep=True);hold={}
    def compute():hold['r']=m.diagnose(df);json.dumps(hold['r'],allow_nan=False)
    check('json-compatible-result',compute)
    def missing():
        compare(hold['r']['columns'],{'wait_minutes':{'missing':4,'fraction':4/6},'charge':{'missing':3,'fraction':.5}})
        compare(hold['r']['patterns'],[
          {'wait_missing':False,'charge_missing':False,'rows':1},
          {'wait_missing':False,'charge_missing':True,'rows':1},
          {'wait_missing':True,'charge_missing':False,'rows':2},
          {'wait_missing':True,'charge_missing':True,'rows':2}])
    check('column-and-combination-missingness',missing)
    def policies():
        compare(hold['r']['policies'],{
        'observed':{'rows':6,'wait_mean':7.,'charge_mean':65/3},
        'complete_case':{'rows':1,'wait_mean':10.,'charge_mean':40.},
        'desk_median':{'rows':6,'wait_mean':7.,'charge_mean':20.}})
    check('policy-sample-counts-and-median-boundaries',policies)
    def unchanged():pd.testing.assert_frame_equal(df,before)
    check('source-index-dtypes-and-values-preserved',unchanged)
    def boundary():
        for frame in [pd.DataFrame({'desk':pd.Series(dtype=str),'wait_minutes':pd.Series(dtype=float),'charge':pd.Series(dtype=float)}),
         pd.DataFrame({'desk':['n','n'],'wait_minutes':[None,None],'charge':[None,None]},dtype=object)]:
            n=len(frame);r=m.diagnose(frame)
            compare(r['columns'],{c:{'missing':n,'fraction':1. if n else 0.} for c in ('wait_minutes','charge')})
            expected=[{'wait_missing':True,'charge_missing':True,'rows':n}] if n else []
            compare(r['patterns'],expected)
            compare(r['policies'],{p:{'rows':0 if p=='complete_case' else n,'wait_mean':None,'charge_mean':None} for p in ('observed','complete_case','desk_median')})
            json.dumps(r,allow_nan=False)
    check('empty-and-all-missing-are-null-not-zero',boundary)

def http_checks(m,root):
    now=datetime(2031,4,9,13,20,0,250000,tzinfo=timezone.utc)
    f=m.retry_after_seconds
    def digits():
        for v,w in [('0',0),(' 0037\t',37),('999999',999999)]:eq(f(v,now),w)
    check('nonnegative-ascii-delta-seconds',digits)
    def dates():
        eq(f('Wed, 09 Apr 2031 13:20:01 GMT',now),1)
        eq(f('Wed, 09 Apr 2031 13:21:01 GMT',now),61)
        eq(f('Wed, 09 Apr 2031 13:19:59 GMT',now),0)
    check('http-date-ceiling-and-expired-clamp',dates)
    def zones():
        local=now.astimezone(timezone(timedelta(hours=9)))
        eq(f('Wed, 09 Apr 2031 13:21:01 GMT',local),61)
    check('aware-nonutc-clock-converted',zones)
    def invalid():
        for v in (None,'',' ','-2','+2','1.5','１２','3 4','Wednesday, 09-Apr-31 13:20:01 GMT','Wed Apr  9 13:20:01 2031','Wed, 09 Apr 2031 13:20:01 UTC','Wed, 31 Feb 2031 13:20:01 GMT','Bad, 09 Apr 2031 13:20:01 GMT'):
            eq(f(v,now),None)
    check('unsupported-and-malformed-values-rejected',invalid)
    def naive():
        for v in (None,'2','Wed, 09 Apr 2031 13:21:01 GMT'):raises(ValueError,lambda:f(v,datetime(2031,4,9)))
    check('naive-clock-rejected-even-with-absent-header',naive)

def main():
    task,candidate=sys.argv[1:3]
    try:
        spec=importlib.util.spec_from_file_location('candidate_solution',str(Path(candidate)/'solution.py'))
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory(prefix='heldout-') as root:
            {'sqlite-backup-review':sqlite_checks,'probe-routing-review':probe_checks,'pandas-intake-diagnostic':pandas_checks,'http-retry-after':http_checks}[task](m,Path(root))
    except BaseException as e:
        RESULT.append({'name':'import-or-harness-execution','pass':False,'error':type(e).__name__+': '+str(e)[:700]})
    output={'schema':'heldout-check-v1','task':task,'checks':RESULT,'passed':sum(x['pass'] for x in RESULT),'total':len(RESULT),'all_pass':bool(RESULT) and all(x['pass'] for x in RESULT)}
    print(json.dumps(output,allow_nan=False))
    return 0 if output['all_pass'] else 1
if __name__=='__main__':sys.exit(main())
