from pathlib import Path
import hashlib,tarfile,tempfile,subprocess,sys
root=Path(__file__).resolve().parent
archive=root/'evidence-bundle.tar.gz'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='62b2b166346da4c9f4bd63d1657c2f6565d42968f218bd5bb95aa552927196c6'
with tempfile.TemporaryDirectory(prefix='openakashic-evidence-') as target:
 with tarfile.open(archive) as tar:tar.extractall(target,filter='data')
 bundle=Path(target)/'evidence-bundle'
 subprocess.run([sys.executable,str(bundle/'verify_results.py')],cwd=bundle,check=True)
print('Published archive bytes and full nested evidence verification passed.')
