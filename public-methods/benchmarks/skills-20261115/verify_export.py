#!/usr/bin/env python3
"""Verify public bytes and optionally recheck in offline Docker only."""
import argparse,hashlib,json,pathlib,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify():
 manifest=json.loads((ROOT/"MANIFEST.json").read_text())
 for name,record in manifest["files"].items():
  p=ROOT/name
  if p.is_symlink() or not p.is_file() or sha(p)!=record["sha256"]:raise ValueError("Manifest mismatch: "+name)
 for record in json.loads((ROOT/"artifact-provenance.json").read_text())["artifacts"]:
  if sha(ROOT/record["path"])!=record["original_sha256"]:raise ValueError("Original artifact bytes changed")
 return manifest
def replay(image):
 result=[]
 for row in json.loads((ROOT/"protocol/schedule.json").read_text()):
  task=ROOT/"tasks"/row["task"];artifact=ROOT/"artifacts"/row["id"]
  cmd=["docker","run","--rm","--network","none","--read-only","--user","65534:65534","--cap-drop","ALL","--security-opt","no-new-privileges","--memory","2g","--cpus","1","--pids-limit","256","--tmpfs","/tmp:rw,nosuid,size=512m,mode=1777","--tmpfs","/work:rw,nosuid,size=512m,mode=1777","-e","HOME=/tmp","-e","PYTHONDONTWRITEBYTECODE=1","-v",str(ROOT)+":/benchmark:ro","-v",str(task)+":/task:ro","-v",str(artifact)+":/candidate:ro",image,"python","-c","import shutil,subprocess;shutil.copytree('/candidate','/work/candidate');raise SystemExit(subprocess.call(['python','/benchmark/check.py','--task','"+row["task"]+"','--input','/task/input','--output','/work/candidate']))"]
  p=subprocess.run(cmd,capture_output=True,text=True,timeout=80)
  try:actual=json.loads(p.stdout)
  except ValueError:actual={"ok":False,"replay_error":p.stderr[-1000:]}
  expected=json.loads((ROOT/"checks"/(row["id"]+".json")).read_text())["report"]
  matched=isinstance(expected,dict) and actual.get("ok")==expected.get("ok")
  result.append({"run_id":row["id"],"archived_checker_ok":expected.get("ok") if isinstance(expected,dict) else None,"replayed_checker_ok":actual.get("ok"),"same_bounded_outcome":matched,"exit_code":p.returncode})
 return result
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--replay-checks",action="store_true");p.add_argument("--image");a=p.parse_args()
 try:
  m=verify();out={"manifest_verified":True,"files":len(m["files"]),"candidate_code_executed_on_host":False}
  if a.replay_checks:
   if not a.image:raise ValueError("--image required")
   out["rechecks"]=replay(a.image);out["all_archived_outcomes_preserved"]=all(x["same_bounded_outcome"] for x in out["rechecks"])
  print(json.dumps(out,indent=2));sys.exit(0 if out.get("all_archived_outcomes_preserved",True) else 1)
 except Exception as e:print(type(e).__name__+": "+str(e),file=sys.stderr);sys.exit(1)
