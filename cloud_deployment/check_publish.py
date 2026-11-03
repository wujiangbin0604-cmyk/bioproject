"""Inspect the staged release without printing secret values or binary content."""
import json
import re
import subprocess
from pathlib import Path

def main():
    git=['git','-c',f'safe.directory={Path(__file__).resolve().parents[1].as_posix()}']
    files=list(filter(None,subprocess.check_output(git+['diff','--cached','--name-only','-z']).decode().split('\0')))
    pattern=re.compile(rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{32,}|AKIA[A-Z0-9]{16}')
    findings=[];binary=[];total=0
    for path in files:
        content=subprocess.check_output(git+['show',':'+path])
        total+=len(content)
        if pattern.search(content):
            findings.append(path)
        if b'\x00' in content:
            binary.append({'path':path,'bytes':len(content)})
    unexpected=[p for p in files if any(v in p for v in ['.vendor','node_modules','experiment_runs/','model_registry/','/matrix.npy','/raw/'])]
    print(json.dumps({'files':len(files),'bytes':total,'secret_pattern_files':findings,'binary_files':binary,'unexpected_runtime_paths':unexpected},ensure_ascii=False,indent=2))
    if findings or unexpected:
        raise SystemExit(1)

if __name__=='__main__':
    main()
