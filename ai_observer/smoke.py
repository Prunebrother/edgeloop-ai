"""AGPL-3.0-only. Explicit real-Ollama observer smoke; synthetic observations, no hardware."""
import argparse,hashlib,json,secrets,tempfile,threading,time
from pathlib import Path
from uuid import uuid4
import httpx
from fastapi.testclient import TestClient
from .config import RuntimeConfig,validate_ollama_url
from .server import create_app
from companion_ai.models import AIConfig
from companion_ai.storage import SettingsStore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url');parser.add_argument('--models',nargs='+',default=['evelyn-lite-v1:latest'])
    parser.add_argument('--thinking',choices=['off','on'],default='off')
    parser.add_argument('--max-tokens',type=int,default=128);parser.add_argument('--timeout',type=float,default=90)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():parser.error('Output already exists; choose another path to preserve evidence')
    url=validate_ollama_url(args.url) if args.url else RuntimeConfig.load().ollama_url
    config=AIConfig(thinking=args.thinking=='on',max_tokens=args.max_tokens,timeout_seconds=args.timeout)
    report={'ollama_url':url,'thinking':config.thinking,'hardware':'none; synthetic IDLE observation only','models':[],'passed':False}
    try:
        with httpx.Client(base_url=url,timeout=5,trust_env=False) as runtime:
            tags=runtime.get('/api/tags');tags.raise_for_status();report['installed_models']=[m['name'] for m in tags.json()['models']]
        report['available']=True
        with tempfile.TemporaryDirectory(prefix='edgeloop-f22-smoke-') as directory:
            store=SettingsStore(directory)
            for model in args.models:store.write('model-presets.json',store.read('model-presets.json',{})|{'ollama:'+model:config.model_copy(update={'model':model}).model_dump()})
            token=secrets.token_urlsafe(32);app=create_app(token,directory,ollama_url=url)
            with TestClient(app) as client:
                with client.websocket_connect('/observe',headers={'Origin':'http://127.0.0.1:8770'}) as ws:
                    ws.send_json({'version':1,'type':'auth','token':token,'browser_id':str(uuid4())})
                    ready=ws.receive_json();epoch=ready['epoch'];sequence=0;stop=threading.Event();lock=threading.Lock()
                    snapshot={'session_id':str(uuid4()),'status':'IDLE','seconds':0,'experience':'classic','active_mode':'classic','goal':'tease','hr':98,'effective_max':140,'pullback':140,'trend':'unknown','edges':0,'intensity':100,
                        'movement':{'primary':0,'secondary':0,'stroke_min':0,'stroke_max':100},'devices':{'simulated_hr':True,'hr_ready':True,'toy_ready':False,'ble':False,'handy':False,'intiface':False,'tcode':False,'vacuglide':False},'safety':{'signal':'ok','no_contact':False,'watchdog_paused':False,'fault':'device_unready'}}
                    def send(message):
                        with lock:ws.send_json(message)
                    def heartbeat():
                        nonlocal sequence
                        while not stop.is_set():
                            try:
                                send({'version':1,'type':'observation','epoch':epoch,'sequence':sequence,'snapshot':snapshot,'events':[]});sequence+=1
                            except Exception as exc:
                                if not stop.is_set():report['heartbeat_error']=type(exc).__name__
                                return
                            stop.wait(1.05)
                    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
                    def until(kind):
                        while True:
                            message=ws.receive_json()
                            if message['type'] in {'ai_error','conversation_error','protocol_error'}:raise ValueError(message.get('detail','AI error'))
                            if message['type']==kind:return message
                    try:
                        send({'version':1,'type':'list_models'});listed=until('models')
                        assert listed['ollama_url']==url
                        for model in args.models:
                            if model not in report['installed_models']:raise ValueError('Requested model is not installed: '+model)
                            send({'version':1,'type':'select_model','selection':{'model':model},'thinking':config.thinking})
                            selected=until('model_selected');assert selected['model']==model and selected['thinking']==config.thinking
                            system=app.state.models.model_metadata.get('system','');entry={'model':model,'embedded_system_sha256':hashlib.sha256(system.encode()).hexdigest(),'embedded_system_characters':len(system)}
                            started=time.monotonic();send({'version':1,'type':'chat','model':model,'text':'Briefly state the reported BPM, whether it is simulated, and whether the session is running or idle.'})
                            deltas=[]
                            while True:
                                message=ws.receive_json()
                                if message['type']=='response_delta':deltas.append(message['text'])
                                if message['type'] in {'conversation_error','ai_error','protocol_error'}:raise ValueError(message.get('detail','AI error'))
                                if message['type']=='speech' and message.get('source')=='user':
                                    entry.update(reply=message['text'],streamed_chunks=len(deltas),seconds=round(time.monotonic()-started,3),metrics=app.state.models.metrics.samples[-1])
                                    break
                            assert deltas and entry['reply'] and app.state.observation.report['status']=='IDLE' and app.state.observation.report['seconds']==0
                            entry['reported_telemetry_facts']=all(term in entry['reply'].lower() for term in ['98','simulat','idle'])
                            report['models'].append(entry)
                            print('Completed '+model+'; visible chunks='+str(len(deltas)),flush=True)
                        if len(args.models)>1:
                            send({'version':1,'type':'select_model','selection':{'model':args.models[0]},'thinking':config.thinking})
                            restored=until('model_selected');assert any(m['role']=='assistant' for m in restored['history']);report['model_memory_restored']=True
                        report['heartbeat_messages']=sequence;report['passed']=True
                    finally:stop.set();thread.join(timeout=2)
    except (httpx.HTTPError,ValueError,AssertionError,KeyError,TimeoutError) as exc:
        report['error']=str(exc);report.setdefault('available',False)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    if not report['passed']:raise SystemExit(1)

if __name__=='__main__':main()
