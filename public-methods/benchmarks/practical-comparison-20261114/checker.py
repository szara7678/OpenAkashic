import importlib.util,sys,json,pathlib,tempfile,sqlite3,threading,time,http.server,socketserver
ROOT=pathlib.Path('/work');TASK=sys.argv[1];checks=[]
def check(name,fn):
 try:fn();checks.append({'name':name,'passed':True})
 except Exception as e:checks.append({'name':name,'passed':False,'error_type':type(e).__name__,'message':str(e)[:400]})
def equal(a,b):assert a==b,(a,b)
def raises(kind,fn):
 try:fn()
 except kind as e:return e
 raise AssertionError('expected exception')
def load():
 spec=importlib.util.spec_from_file_location('solution',ROOT/'solution.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
try:
 if TASK=='sqlite-wal-backup':
  m=load()
  def wal():
   with tempfile.TemporaryDirectory() as d:
    a=pathlib.Path(d)/'source.sqlite';b=pathlib.Path(d)/'backup.sqlite';c=sqlite3.connect(a);c.execute('pragma journal_mode=wal');c.execute('pragma wal_autocheckpoint=0');c.execute('create table events(id integer primary key, body text)');c.executemany('insert into events(body) values(?)',[(f'item-{i}',) for i in range(600)]);c.commit();assert pathlib.Path(str(a)+'-wal').stat().st_size>0
    m.backup_database(str(a),str(b));out=sqlite3.connect(b);equal(out.execute('select count(*) from events').fetchone()[0],600);equal(out.execute('pragma integrity_check').fetchone()[0],'ok');out.close();equal(c.execute('select count(*) from events').fetchone()[0],600);c.close()
  def existing():
   with tempfile.TemporaryDirectory() as d:
    a=pathlib.Path(d)/'a';b=pathlib.Path(d)/'b';sqlite3.connect(a).close();b.write_bytes(b'KEEP');raises(FileExistsError,lambda:m.backup_database(a,b));equal(b.read_bytes(),b'KEEP')
  def same():
   with tempfile.TemporaryDirectory() as d:
    a=pathlib.Path(d)/'a';c=sqlite3.connect(a);c.execute('create table x(a)');c.commit();c.close();raises((ValueError,FileExistsError),lambda:m.backup_database(a,a));equal(sqlite3.connect(a).execute('pragma integrity_check').fetchone()[0],'ok')
  def cleanup():
   with tempfile.TemporaryDirectory() as d:
    a=pathlib.Path(d)/'missing'/'source';b=pathlib.Path(d)/'b'
    try:m.backup_database(a,b)
    except Exception:pass
    else:raise AssertionError('missing source did not fail')
    assert not b.exists()
  def corrupt_cleanup():
   with tempfile.TemporaryDirectory() as d:
    a=pathlib.Path(d)/'corrupt';b=pathlib.Path(d)/'backup';a.write_bytes(b'not a SQLite database'*100)
    try:m.backup_database(a,b)
    except Exception:pass
    else:raise AssertionError('corrupt source did not fail')
    assert not b.exists()
  for n,f in [('corrupt source and partial destination cleanup',corrupt_cleanup),('WAL committed rows and integrity',wal),('existing destination preserved',existing),('same source rejected',same),('failure cleanup',cleanup)]:check(n,f)
 elif TASK=='pandas-missingness':
  import pandas as pd,numpy as np
  m=load()
  def types():
   df=pd.DataFrame({'ints':pd.Series([1,pd.NA,3],dtype='Int64'),'bools':pd.Series([True,pd.NA,False],dtype='boolean'),'strings':pd.Series(['NaN',pd.NA,''],dtype='string'),'dates':pd.to_datetime(['2020-01-01',None,'2020-02-01']),'obj':[None,float('nan'),'None']});copy=df.copy(deep=True);r=m.summarize_missing(df);equal(list(r.columns),['column','missing_count','total_rows','missing_fraction']);equal(r['column'].tolist(),list(df.columns));equal(r['missing_count'].tolist(),[1,1,1,1,2]);equal(r['total_rows'].tolist(),[3]*5);assert np.allclose(r['missing_fraction'],[1/3]*4+[2/3]);pd.testing.assert_frame_equal(df,copy);assert pd.api.types.is_integer_dtype(r['missing_count']);assert pd.api.types.is_integer_dtype(r['total_rows'])
  def empty():
   r=m.summarize_missing(pd.DataFrame(columns=['a','b']));equal(r['missing_fraction'].tolist(),[0.0,0.0]);equal(r['missing_count'].tolist(),[0,0])
  def duplicates():
   r=m.summarize_missing(pd.DataFrame([[None,1],[None,None]],columns=['x','x']));equal(r['column'].tolist(),['x','x']);equal(r['missing_count'].tolist(),[2,1])
  def zero_columns():
   r=m.summarize_missing(pd.DataFrame());equal(list(r.columns),['column','missing_count','total_rows','missing_fraction']);equal(len(r),0)
  for n,f in [('zero columns fixed schema',zero_columns),('nullable types and source preservation',types),('empty denominator',empty),('duplicate labels',duplicates)]:check(n,f)
 elif TASK=='kubernetes-probes':
  import yaml
  d=yaml.safe_load((ROOT/'deployment.yaml').read_text());s=d['spec'];c=s['template']['spec']['containers'][0]
  def identity():
   equal(d['apiVersion'],'apps/v1');equal(d['kind'],'Deployment');equal(d['metadata']['name'],'public-reader');equal(s['replicas'],2);equal(c['name'],'reader');equal(c['image'],'registry.example.invalid/public-reader:1.0');assert any(p.get('containerPort')==8080 for p in c.get('ports',[]));assert s['selector']['matchLabels'];assert all(s['template']['metadata']['labels'].get(k)==v for k,v in s['selector']['matchLabels'].items())
  def probes():
   for k,path in [('startupProbe','/startup'),('readinessProbe','/ready'),('livenessProbe','/live')]:
    p=c[k];equal(p['httpGet']['path'],path);equal(p['httpGet']['port'],8080);assert p['timeoutSeconds']>0 and p['periodSeconds']>0
   p=c['startupProbe'];assert 150<=p['periodSeconds']*p['failureThreshold']<=180
  def resources():
   def q(v):
    v=str(v)
    for k,f in [('Gi',1024**3),('Mi',1024**2),('Ki',1024),('m',.001)]:
     if v.endswith(k):return float(v[:-len(k)])*f
    return float(v)
   r=c['resources']
   for k in ['cpu','memory']:assert 0<q(r['requests'][k])<=q(r['limits'][k])
  for n,f in [('deployment identity and selector',identity),('probe semantics and startup budget',probes),('positive resource requests and bounded limits',resources)]:check(n,f)
 elif TASK=='http-json-client':
  m=load();hits=[]
  class H(http.server.BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    hits.append(self.path)
    if self.path=='/slow':time.sleep(.3)
    code,body={'/null':(200,b'null'),'/false':(200,b'false'),'/empty':(200,b'[]'),'/bad':(200,b'{invalid'),'/utf8':(200,b'\xff'),'/fail':(503,b'x'*500)}.get(self.path,(200,b'{"ok":true}'))
    self.send_response(code);self.end_headers()
    try:self.wfile.write(body)
    except BrokenPipeError:pass
  class S(socketserver.ThreadingMixIn,http.server.HTTPServer):daemon_threads=True
  server=S(('127.0.0.1',0),H);threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(server.server_port)
  def valid():equal(m.fetch_json(base+'/null'),None);equal(m.fetch_json(base+'/false'),False);equal(m.fetch_json(base+'/empty'),[])
  def invalid():
   for path in ['/bad','/utf8']:assert raises(m.InvalidJSON,lambda:m.fetch_json(base+path)).__cause__ is not None
  def failure():
   old=len(hits);e=raises(m.HTTPFailure,lambda:m.fetch_json(base+'/fail'));equal(e.status,503);assert len(e.body)<=200;equal(len(hits)-old,1);assert e.__cause__ is not None
  def timeout():assert raises(m.TransportFailure,lambda:m.fetch_json(base+'/slow',timeout=.03)).__cause__ is not None
  for n,f in [('falsey JSON values',valid),('invalid JSON encoding and exception cause',invalid),('HTTP failure precedence and no retries',failure),('timeout classification and cause',timeout)]:check(n,f)
  server.shutdown()
 else:raise ValueError(TASK)
except Exception as e:checks.append({'name':'load artifact','passed':False,'error_type':type(e).__name__,'message':str(e)[:400]})
print(json.dumps({'task':TASK,'all_passed':bool(checks) and all(x['passed'] for x in checks),'checks':checks}));sys.exit(0 if checks and all(x['passed'] for x in checks) else 1)
