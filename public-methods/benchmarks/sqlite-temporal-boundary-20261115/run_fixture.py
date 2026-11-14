#!/usr/bin/env python3
"""Run the unchanged synthetic fixture in a new external workspace."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
CODE_SHA256='dc524e82a5c2bee004236071cd17b0af8b63c2c4dd008fa96e522638ad0a9f27'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',type=int,choices=(2,3),required=True)
    parser.add_argument('--output',type=Path,required=True,help='new workspace outside the pack and any containing Git checkout')
    args=parser.parse_args()
    target=args.output.resolve()
    if target.exists():parser.error('output must not already exist')
    if target==HERE or HERE in target.parents:parser.error('keep generated runs outside the immutable pack')
    for ancestor in HERE.parents:
        if (ancestor/'.git').exists() and (target==ancestor or ancestor in target.parents):
            parser.error('keep generated runs outside the containing Git checkout')
    code=HERE/'v2-original/exercise-source.py'
    snapshot=HERE/('v2-original' if args.version==2 else 'v3-corrected')/'method-snapshot.json'
    if hashlib.sha256(code.read_bytes()).hexdigest()!=CODE_SHA256:
        raise SystemExit('original exercise code hash mismatch')
    target.mkdir(parents=True,exist_ok=False)
    local_code=target/'sqlite_boundary_exercise.py'
    local_snapshot=target/'method-snapshot.json'
    shutil.copyfile(code,local_code)
    shutil.copyfile(snapshot,local_snapshot)
    command=[sys.executable,str(local_code),'--method-snapshot',str(local_snapshot),
             '--method-version',str(args.version),'--output',str(target/'boundary-runs/fixture')]
    return subprocess.run(command,check=False).returncode

if __name__=='__main__':raise SystemExit(main())
