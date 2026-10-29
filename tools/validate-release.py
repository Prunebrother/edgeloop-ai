#!/usr/bin/env python3
"""AGPL-3.0-only. Conservative source-integrity/privacy checks; no uploads or services.
Pattern scanning cannot prove absence of every secret or identity. Review is required.
"""
from pathlib import Path
from hashlib import sha256
import json
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
IGNORED={'.git','.venv','node_modules','__pycache__','.pytest_cache'}

def validate():
    manifest=json.loads((ROOT/'MANIFEST.json').read_text())
    errors=[]
    included=manifest['included']
    found=set()
    patterns={
        'absolute home path':rb'/(?:home|Users)/[A-Za-z0-9_.-]+/',
        'private key':rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        'credential token':rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})',
        'device MAC':rb'(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b',
    }
    for p in ROOT.rglob('*'):
        parts=p.relative_to(ROOT).parts
        if any(x in IGNORED or x.endswith('.egg-info') for x in parts):continue
        n=str(p.relative_to(ROOT))
        if p.is_symlink():errors.append((n,'symlink not allowed'));continue
        if not p.is_file() or n=='MANIFEST.json':continue
        found.add(n);b=p.read_bytes()
        expected=included.get(n)
        if expected is None or sha256(b).hexdigest()!=expected['sha256']:errors.append((n,'missing or changed manifest entry'))
        if p.suffix in {'.db','.sqlite','.sqlite3','.jsonl','.gguf','.safetensors','.pyc','.log','.dump'} or any(x in {'.ai-data','Character_Art'} for x in parts):errors.append((n,'private/generated/unlicensed file category'))
        if n.startswith('.env') and n!='.env.example':errors.append((n,'environment file'))
        for category,pattern in patterns.items():
            if re.search(pattern,b):errors.append((n,category))
    for n in set(included)-found:errors.append((n,'missing packaged file'))
    if (ROOT/'.git').is_dir():
        def git(*a):return subprocess.run(['git','--no-optional-locks','-C',str(ROOT),*a],capture_output=True,text=True,check=True).stdout
        if git('remote'):errors.append(('.git','remote configured; review publication approval'))
        refs=git('for-each-ref','--format=%(objectname)').splitlines()
        if refs:
            metadata=git('log','--all','--format=%an <%ae>%n%cn <%ce>%n%B')
            for category,pattern in patterns.items():
                if re.search(pattern,metadata.encode()):errors.append(('.git',category))
            # Current release has no commits. Future commits require explicit identity review.
            errors.append(('.git','history now exists: manually review author/committer identities and every historical blob'))
    return {'passed':not errors,'packaged_files':len(included),'errors':[{'path':n,'category':c} for n,c in errors],
            'limits':'Pattern and hash checks only. Does not certify licensing, arbitrary secrets, human identities, or physical safety.'}

if __name__=='__main__':
    try:result=validate()
    except (OSError,ValueError,subprocess.CalledProcessError) as exc:
        print(json.dumps({'passed':False,'error_type':type(exc).__name__}));sys.exit(1)
    print(json.dumps(result,indent=2));sys.exit(0 if result['passed'] else 1)
