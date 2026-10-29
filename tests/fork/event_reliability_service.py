# SPDX-License-Identifier: AGPL-3.0-only
"""Isolated F2.5.1 browser fixture. No drivers; optional audited existing Ollama."""
import asyncio,json,os,tempfile,re
from pathlib import Path
import httpx,uvicorn
from ai_observer.server import create_app
from companion_ai.models import AIConfig
from companion_ai.storage import SettingsStore
LIVE=os.getenv('EDGELOOP_LIVE_ACCEPTANCE')=='1'
TOKEN='event-reliability-fixture-'+'x'*32
UI=int(os.getenv('EDGELOOP_FIXTURE_UI_PORT','8820'));PORT=int(os.getenv('EDGELOOP_FIXTURE_OBSERVER_PORT','8828'))
MODELS=['evelyn-lite-v1:latest','daisy-qwen35:latest']
class Audit(httpx.AsyncBaseTransport):
    def __init__(self):self.inner=httpx.AsyncHTTPTransport();self.requests=[]
    async def handle_async_request(self,request):
        if (request.url.host,request.url.port)!=('127.0.0.1',11435):raise ValueError('Only existing local 11435 allowed')
        body=json.loads(request.content) if request.content else {}
        if request.url.path=='/api/chat':
            assert body['think'] is False
            self.requests.append({'model':body['model'],'think':body['think'],'messages':body['messages']})
            if not LIVE:
                prompt=body['messages'][-1]['content']
                if 'APPLICATION EVENT / REVISION' in prompt:
                    trigger=json.loads(prompt.split('Observed application event (not a user request): ',1)[-1]) if 'Observed application event (not a user request): ' in prompt else {}
                    if 'SUPPORTING VERIFIED HISTORICAL EVENTS:\n' in prompt:
                        values=json.JSONDecoder().raw_decode(prompt.split('SUPPORTING VERIFIED HISTORICAL EVENTS:\n',1)[1])[0]
                        trigger=values[0] if values else {}
                        for key,label in [('experience','Selected experience'),('goal','Selected goal')]:
                            match=re.search(label+r' \['+key+r'\]:[^\n]*\[([a-z]+)\]',prompt)
                            if match:trigger['current_'+key]=match[1]
                    if trigger.get('kind')=='came_early':text='[[expression:comforting]]EdgeLoop accepted Came Early. Take your time.'
                    else:text='[[expression:focused]]You selected '+str(trigger.get('current_experience'))+' with goal '+str(trigger.get('current_goal'))+'.'
                elif 'long streaming' in prompt:
                    class Stream(httpx.AsyncByteStream):
                        async def __aiter__(self):
                            for s in ['[[expr','ession:con','cerned]]','Let us take this slowly.']:
                                yield (json.dumps({'message':{'content':s},'done':False})+'\n').encode();await asyncio.sleep(.2)
                            await asyncio.sleep(30)
                            yield b'{"done":true}\n'
                    return httpx.Response(200,stream=Stream())
                else:text='[[expression:playful]]A fresh thought for this conversation.'
                return httpx.Response(200,text=json.dumps({'message':{'content':text},'done':True,'done_reason':'stop'})+'\n')
        if not LIVE:
            if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':m} for m in MODELS]})
            if request.url.path=='/api/show':return httpx.Response(200,json={'system':'Native test character.','capabilities':['completion','thinking']})
            if request.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
            return httpx.Response(200,json={'done':True})
        return await self.inner.handle_async_request(request)
    async def aclose(self):pass
transport=Audit();data=tempfile.TemporaryDirectory(prefix='f251-events-');store=SettingsStore(data.name)
store.write('model-presets.json',{'ollama:'+m:AIConfig(model=m,max_tokens=384,idle_unload_seconds=60).model_dump() for m in MODELS})
app=create_app(TOKEN,data.name,transport=transport,ollama_url='http://127.0.0.1:11435',origins={f'http://127.0.0.1:{UI}'})
@app.get('/fixture/state')
async def status():
    # Synthetic test data only. Native SYSTEM text is deliberately omitted.
    return {'report':app.state.observation.report,'events':list(app.state.observation.events),'speech':app.state.speech.status(),
            'history':list(app.state.speech.history),'requests':[{'model':r['model'],'think':r['think'],'last_turn':r['messages'][-1]} for r in transport.requests],
            'metrics':list(app.state.models.metrics.samples),'live':LIVE,'read_only':app.state.models.tool_executor is None}
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=PORT,access_log=False)
