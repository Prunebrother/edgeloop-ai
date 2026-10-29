# SPDX-License-Identifier: AGPL-3.0-only
"""Isolated synthetic UI fixture for A/B/C. No hardware imports, production data or models changed."""
import os,sys,types,subprocess,json,tempfile,time,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
ARM=os.environ.get('EDGELOOP_MEMORY_ARM','B');LIVE=os.environ.get('EDGELOOP_LIVE_ACCEPTANCE')=='1'
if ARM=='A':
    # Freeze the real checkpoint extraction/storage/retrieval/compiler, not a reimplementation.
    for name in ('narrative_facts','narrative','context_compiler'):
        full='companion_ai.'+name;module=types.ModuleType(full);module.__package__='companion_ai';sys.modules[full]=module
        exec(compile((ROOT/'tests/fixtures/historical/curation'/(name+'.py')).read_text(),'<f284-'+name+'>','exec'),module.__dict__)
    sys.modules['companion_ai.narrative_facts'].recall_violations=lambda *a:[]
import httpx,uvicorn
from ai_observer.server import create_app
from companion_ai.storage import SettingsStore
from companion_ai.memory_curator import CuratorConfig
from tests.fork.memory_inference_audit import InferenceAudit
MODELS=['evelyn-narrative-v1:latest','daisy-narrative-v1:latest','celeste-narrative-v2:latest']
HOBBIES={'evelyn':'tending an overgrown succulent','daisy':'pressing wildflowers','celeste':'restoring fountain pens'}
PORT=int(os.environ['EDGELOOP_FIXTURE_OBSERVER_PORT']);UI=int(os.environ['EDGELOOP_FIXTURE_UI_PORT'])
TOKEN=os.environ['EDGELOOP_FIXTURE_TOKEN']
OLLAMA_TIMEOUT_MS=float(os.environ.get('EDGELOOP_FIXTURE_OLLAMA_TIMEOUT_MS','120000'))
if not 1<=OLLAMA_TIMEOUT_MS<=300000:raise ValueError('Fixture Ollama timeout must be 1..300000 ms')
directory=tempfile.TemporaryDirectory(prefix='edgeloop-memory-browser-');store=SettingsStore(directory.name)
store.write('narrative-config.json',{'enabled':True,'persist_between_sessions':True})
store.write('memory-config.json',{'enabled':True,'persist_between_sessions':True})
# Test-local presets only; give the audited HTTP request time to report its own deadline.
store.write('model-presets.json',{'ollama:'+model:{'timeout_seconds':min(300,max(1,OLLAMA_TIMEOUT_MS/1000+1))} for model in MODELS})
class Clock:
    offset=0
    def __call__(self):return time.monotonic()+self.offset
clock=Clock()
class Audit(httpx.AsyncBaseTransport):
    def __init__(self):self.inner=httpx.AsyncHTTPTransport();self.records=[]
    async def handle_async_request(self,request):
        if (request.url.host,request.url.port)!=('127.0.0.1',11435):raise ValueError('Only existing loopback Ollama')
        body=json.loads(request.content) if request.content else {};path=request.url.path
        if path=='/api/chat':
            assert body['think'] is False
            curator='MEMORY CURATION TASK' in body['messages'][0]['content']
            record={'request':len(self.records)+1,'model':body['model'],'curator':curator,'think':False,'input_characters':sum(len(m['content']) for m in body['messages'])}
            self.records.append(record)
            inference=InferenceAudit(record,OLLAMA_TIMEOUT_MS)
            if not LIVE:
                prompt=body['messages'][-1]['content'];character=body['model'].split('-')[0];hobby=HOBBIES[character]
                if curator:
                    payload=json.loads(prompt);items=payload['memories'];chosen=sorted(items,key=lambda r:('ORCHID' in r['text'] or 'hobby' in r['text'] or 'succulent' in r['text']),reverse=True)[:6]
                    text=json.dumps({'proposals':[{'source_ref':r['id'],'quote':r['text'],'category':r['category'],'importance':5,'action':'retain','justification':'Sourced character detail or clue'} for r in chosen]})
                else:
                    query=prompt.split('USER MESSAGE (request, not session data):\n')[-1]
                    if 'Establish our scene' in query:text=f'[[expression:focused]]My hobby is {hobby}.'
                    elif 'identifier' in query:
                        identifiers=re.findall(r'ORCHID-\d+',prompt);text='[[expression:focused]]'+(identifiers[0] if identifiers else 'I cannot recall that identifier.')
                    elif 'hobby' in query:text='[[expression:happy]]'+('My hobby is '+hobby+'.' if hobby in prompt else 'I cannot recall that detail.')
                    else:text='[[expression:focused]]A curtain moves in the quiet room.'
                record.update(prompt_eval_count=sum(len(m['content']) for m in body['messages'])//4,eval_count=20,done_reason='stop')
                inference.finish('completed')
                return httpx.Response(200,text=json.dumps({'message':{'content':text},'done':True,'done_reason':'stop','prompt_eval_count':record['prompt_eval_count'],'eval_count':20})+'\n')
            return await inference.forward(self.inner,request)
        if not LIVE:
            if path=='/api/ps':return httpx.Response(200,json={'models':[]})
            if path=='/api/tags':return httpx.Response(200,json={'models':[{'name':m} for m in MODELS]})
            if path=='/api/show':
                model=body['model'].removesuffix(':latest');native=re.search(r'SYSTEM\s+"""(.*?)"""',(ROOT/'characters/models'/model/'Modelfile').read_text(),re.S)[1]
                return httpx.Response(200,json={'system':native,'capabilities':['completion','thinking']})
            if path=='/api/generate':return httpx.Response(200,json={'done':True})
        return await self.inner.handle_async_request(request)
audit=Audit();app=create_app(TOKEN,directory.name,origins={f'http://127.0.0.1:{UI}'},transport=audit,clock=clock,ollama_url='http://127.0.0.1:11435')
app.state.speech.curator.configure(CuratorConfig(enabled=False,interval_turns=8))
@app.get('/fixture/audit')
async def audit_state():
    s=app.state.speech;manager=app.state.models
    from companion_ai.narrative_facts import extract
    history=list(s.history);last_user=next((r['content'] for r in reversed(history) if r['role']=='user'),'');last_reply=next((r['content'] for r in reversed(history) if r['role']=='assistant'),'')
    candidates=extract(last_reply[:4096],'assistant',s.narrative.scope,s.narrative.state['epoch'],last_user[:2000]) if last_reply else []
    extraction={'method':'bounded replay of this arm extractor; candidate IDs are not persisted fact IDs','source_characters':len(last_reply),'source_truncated':len(last_reply)>4096,'candidates':[{k:r[k] for k in ('text','value','slot','category','speaker')} for r in candidates[:16]]}
    return {'last_extraction':extraction,'arm':ARM,'live':LIVE,'state':s.character_state(),'requests':audit.records,'metrics':list(manager.metrics.samples),'history':[{'role':r['role'],'content':r['content']} for r in s.history]}
@app.post('/fixture/advance')
async def advance():clock.offset+=6.1;return {'advanced':True}
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=PORT,access_log=False)
