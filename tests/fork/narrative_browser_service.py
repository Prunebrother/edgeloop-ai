# SPDX-License-Identifier: AGPL-3.0-only
"""Isolated fixture extending the existing mocked event transport."""
import uvicorn,json,httpx,re
from pathlib import Path
from tests.fork import event_reliability_service as f
assert not f.LIVE, 'Narrative browser fixture never performs live inference'
class NarrativeAudit(f.Audit):
    async def handle_async_request(self,request):
        if request.url.path=='/api/show':
            model=json.loads(request.content)['model'].removesuffix(':latest')
            if model in {'evelyn-narrative-v1','daisy-narrative-v1','celeste-narrative-v2'}:
                native=re.search(r'SYSTEM\s+"""(.*?)"""',(Path(__file__).resolve().parents[2]/'characters/models'/model/'Modelfile').read_text(),re.S)[1]
                return httpx.Response(200,json={'system':native,'capabilities':['completion','thinking']})
        if request.url.path=='/api/chat':
            body=json.loads(request.content);prompt=body['messages'][-1]['content'].split('USER MESSAGE (request, not session data):\n')[-1]
            if 'long streaming' not in prompt:
                assert body['think'] is False
                self.requests.append({'model':body['model'],'think':body['think'],'messages':body['messages']})
                if 'Glasshouse page says:' in prompt:text='[[expression:focused]]I collect vintage, slightly dented teapots.'
                elif 'What did the page say?' in prompt and 'The truth was hidden in plain sight.' in body['messages'][-1]['content']:text='[[expression:focused]]The page said: "The truth was hidden in plain sight."'
                elif 'fresh garden' in prompt:text='[[expression:happy]]A new garden path winds between the apple trees.'
                elif 'brass key' in prompt:text='[[expression:focused]]I will keep the brass key for later; a violet seal points toward the garden.'
                elif 'Cloverfield' in prompt:text="[[expression:playful]]A violet letter waits on Cloverfield's porch. The orchard can keep its secrets a little longer."
                else:text='[[expression:focused]]A blue envelope waits beside the telescope. Shall we inspect its seal?'
                return httpx.Response(200,text=json.dumps({'message':{'content':text},'done':True,'done_reason':'stop'})+'\n')
        return await super().handle_async_request(request)
f.transport=NarrativeAudit();f.app.state.models.transport=f.transport
f.MODELS.extend(['evelyn-narrative-v1:latest','daisy-narrative-v1:latest','celeste-narrative-v2:latest'])
@f.app.get('/fixture/narrative')
async def narrative():
    return {'context':f.app.state.speech.narrative.context(),'history':list(f.app.state.speech.history),'requests':f.transport.requests,'thinking':f.app.state.models.config.thinking}
@f.app.get('/fixture/context')
async def context_state():return f.app.state.speech.character_state()

if __name__=='__main__':uvicorn.run(f.app,host='127.0.0.1',port=f.PORT,access_log=False)
