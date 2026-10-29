"""AGPL-3.0-only. Read-only inspection of an existing Ollama; never starts/stops it."""
import argparse,json,os
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from .config import RuntimeConfig,validate_ollama_url

def local_model_directories(url,proc=Path('/proc')):
    expected=urlsplit(url).port or 80
    matches=[]
    if not proc.is_dir():return matches
    for process in proc.iterdir():
        if not process.name.isdigit():continue
        try:
            command=(process/'cmdline').read_bytes().split(b'\0')
            if len(command)<2 or Path(os.fsdecode(command[0])).name!='ollama' or command[1]!=b'serve':continue
            env=dict(item.split('=',1) for item in (process/'environ').read_text().split('\0') if '=' in item)
            host=env.get('OLLAMA_HOST','127.0.0.1:11434')
            origin=urlsplit(host if '://' in host else 'http://'+host)
            if (origin.port or 11434)!=expected:continue
            matches.append({'pid':int(process.name),'model_directory':env.get('OLLAMA_MODELS','not explicitly set; inspect this process owner’s default ~/.ollama/models')})
        except (OSError,ValueError):continue
    return matches

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url');args=parser.parse_args()
    try:url=validate_ollama_url(args.url) if args.url else RuntimeConfig.load().ollama_url
    except (ValueError,OSError) as exc:parser.error(str(exc))
    report={'ollama_url':url,'process_model_directories':local_model_directories(url)}
    try:
        with httpx.Client(base_url=url,timeout=5,trust_env=False) as client:
            response=client.get('/api/tags');response.raise_for_status();report['models']=[m['name'] for m in response.json().get('models',[])]
            response=client.get('/api/version');response.raise_for_status();report['version']=response.json().get('version')
        report['available']=True
    except (httpx.HTTPError,ValueError,KeyError):report.update(available=False,error='No usable Ollama API at the configured origin. Start the existing server manually; no fallback or automatic startup occurred.')
    print(json.dumps(report,indent=2))
    if not report['available']:raise SystemExit(1)

if __name__=='__main__':main()
