"""Isolated browser fixture: real observer classes, mocked local model transport."""
from pathlib import Path
import os
import asyncio
import json
import re
import tempfile
import httpx
import uvicorn
from ai_observer.server import create_app

UI_PORT=int(os.getenv('EDGELOOP_FIXTURE_UI_PORT','8770'))
OBSERVER_PORT=int(os.getenv('EDGELOOP_FIXTURE_OBSERVER_PORT','8768'))
last_thinking=None
ollama_down=False
TOKEN='browser-fixture-token-'+('x'*32)
class Stream(httpx.AsyncByteStream):
    async def __aiter__(self):
        for content in ['[[expr','ession:mis','chievous]]']:
            yield (json.dumps({'message':{'content':content},'done':False})+'\n').encode()
            await asyncio.sleep(.05)
        await asyncio.sleep(.3)
        for i in range(120):
            yield (json.dumps({'message':{'content':'A streamed companion message, with room to read and reflect. '*3},'done':False})+'\n').encode()
            await asyncio.sleep(.04)
        yield b'{"message":{"content":""},"done":true}\n'

async def runtime(request):
    global last_thinking
    if request.url.path=='/api/tags' and ollama_down:raise httpx.ConnectError('fixture unavailable')
    if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':name} for name in json.loads((Path(__file__).resolve().parents[1]/'fixtures/character-models.json').read_text())]})
    if request.url.path=='/api/show':return httpx.Response(200,json={'system':'Exact fixture Modelfile identity','capabilities':['completion','thinking'],'thinking':{'values':[True,False]},'model_info':{'qwen35.context_length':8192}})
    if request.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
    body=json.loads(request.content)
    last_thinking=body.get('think')
    if 'messages' not in body:return httpx.Response(200,json={'done':True})
    if 'APPLICATION EVENT / REVISION' in body['messages'][-1]['content']:
        return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:proud]]Five minutes are recorded in this simulated session.'},'done':True,'done_reason':'stop'})+'\n')
    prompt=body['messages'][-1].get('content','').split('USER MESSAGE (request, not session data):\n')[-1]
    if prompt=='portrait playful test':return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:playful]]Welcome back, you cheeky rascal.'},'done':True,'done_reason':'stop'})+'\n')
    if prompt=='portrait flirty tone test':return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:flirty]]Come a little closer, darling.'},'done':True,'done_reason':'stop'})+'\n')
    if prompt=='portrait concerned test':return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:concerned]]I am here to listen.'},'done':True,'done_reason':'stop'})+'\n')
    if prompt=='long streaming response':return httpx.Response(200,stream=Stream())
    if prompt=='grounding conflict test':return httpx.Response(200,text=json.dumps({'message':{'content':'Your current heart rate is 210 BPM.'},'done':True,'done_reason':'stop'})+'\n')
    if prompt=='thinking cutoff test':
        retry=body['options']['num_predict']>2048
        return httpx.Response(200,text=json.dumps({'message':{'content':'Finished after reasoning.' if retry else 'UNFINISHED_DRAFT'},'done':True,'done_reason':'stop' if retry else 'length'})+'\n')
    context='\n'.join(m['content'] for m in body['messages']);match=re.search(r'(?:\"hr\":|Heart rate \[hr\]: )(\d+)',context)
    hr=match[1] if match else 'unknown'
    return httpx.Response(200,text=json.dumps({'message':{'content':body['model']+' reports '+hr+' BPM (simulated).'},'done':True})+'\n')
app=create_app(TOKEN,tempfile.mkdtemp(prefix='fork-browser-fixture-'),transport=httpx.MockTransport(runtime),origins={f'http://127.0.0.1:{UI_PORT}'})
@app.post('/fixture/ollama-down')
async def disconnect_ollama():
    global ollama_down
    ollama_down=True
    return {'ok':True}

@app.post('/fixture/event-policy/{mode}')
async def event_policy(mode: str):
    from companion_ai.models import SpeechPolicy
    from companion_ai.director import DirectorConfig
    app.state.speech.policy=SpeechPolicy(min_interval_seconds=0.0,user_grace_seconds=0.0) if mode=='fast' else SpeechPolicy()
    app.state.director.config=DirectorConfig(spontaneous_interval_seconds=0.0,user_idle_before_spontaneous_seconds=0.0,category_cooldowns={},topic_protection_seconds=0.0) if mode=='fast' else DirectorConfig()
    app.state.speech.last_event=float('-inf');app.state.speech.busy_until=0
    return {'mode':mode}

@app.get('/fixture/state')
async def observed():
    return {'state':app.state.observation.report,'director':dict(app.state.director.counts),'read_only':app.state.models.tool_executor is None,'thinking':app.state.models.config.thinking,'last_thinking':last_thinking}
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=OBSERVER_PORT,access_log=False,ws_max_size=16384)
