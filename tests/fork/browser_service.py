"""Isolated browser fixture: real observer classes, mocked local model transport."""
from pathlib import Path
import os
import asyncio
import json
import re
import tempfile
import httpx
import uvicorn
from fastapi import Request
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

SELECTION_LINES=['Got it, that choice is set.','Understood, the new setting is in place.','All right, I see the change.','Noted, we will go that way.',
    'Fine by me, the switch is made.','Okay, I have your new pick.','Changed, and I am ready when you are.','Your call, and it is in effect.',
    'There we are, the update is in.','Alright, that is what we will do.','Sounds good, the selection stands.','Very well, I have adjusted with you.']
SELECTION_REPLIES=[]
PLAYER_REQUESTS=[]
# AI Settings Control: queued model decisions, and what the observer asked and announced.
SETTINGS_PROPOSALS=[]
SETTINGS_DECISIONS=[]
SETTINGS_CARDS=[]
SETTINGS_REPLIES=[]

async def runtime(request):
    global last_thinking
    if request.url.path=='/api/tags' and ollama_down:raise httpx.ConnectError('fixture unavailable')
    if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':name} for name in json.loads((Path(__file__).resolve().parents[1]/'fixtures/character-models.json').read_text())]})
    if request.url.path=='/api/show':return httpx.Response(200,json={'system':'Exact fixture Modelfile identity','capabilities':['completion','thinking'],'thinking':{'values':[True,False]},'model_info':{'qwen35.context_length':8192}})
    if request.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
    body=json.loads(request.content)
    last_thinking=body.get('think')
    if 'messages' not in body:return httpx.Response(200,json={'done':True})
    current=body['messages'][-1]['content']
    if 'deciding, in character, whether to change one EdgeLoop session setting' in current:
        SETTINGS_DECISIONS.append({'content':current,'format':body.get('format') is not None})
        proposal=SETTINGS_PROPOSALS.pop(0) if SETTINGS_PROPOSALS else {'change':'none'}
        return httpx.Response(200,text=json.dumps({'message':{'content':json.dumps(proposal)},'done':True,'done_reason':'stop'})+'\n')
    context_all='\n'.join(m['content'] for m in body['messages'])
    if 'AI SETTINGS CONTROL' in context_all and 'USER MESSAGE (request, not session data)' in context_all:
        applied='in answer to this message (verified by EdgeLoop)' in context_all
        SETTINGS_REPLIES.append({'applied':applied,'content':context_all})
        line='Done. I changed it for you, just as you asked.' if applied else 'I tried, but EdgeLoop kept things as they are for now.'
        return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:playful]]'+line},'done':True,'done_reason':'stop'})+'\n')
    if 'Announce your own setting change' in context_all:
        SETTINGS_CARDS.append({'content':context_all,'retry':'Your last attempt needs another try' in current})
        return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:mischievous]]I changed that myself, because you were getting far too comfortable.'},'done':True,'done_reason':'stop'})+'\n')
    if 'Verified Player interaction:' in current:
        kind=re.search(r'Verified Player interaction: (\w+)',current)[1]
        PLAYER_REQUESTS.append({'kind':kind,'messages':body['messages'],'model':body['model'],'retry':'Your last attempt needs another try' in current})
        lines={'player_opened':'A shared viewing invitation leaves room for curiosity.',
               'video_selected':'That new selection has my attention; I am curious about your choice.',
               'video_started':'The shared viewing begins, and I look forward to discovering it together.'}
        if kind=='player_opened' and len([r for r in PLAYER_REQUESTS if r['kind']==kind])>1:lines[kind]='There is room for another shared discovery in that invitation.'
        if kind=='video_started' and 'Second' in current:lines[kind]='Another screen choice, another chance to discover something together.'
        return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:playful]]'+lines[kind]},'done':True,'done_reason':'stop'})+'\n')
    if 'Three-edge milestone. The three-edge objective is complete.' in body['messages'][-1]['content']:
        return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:proud]]Three edges, and that objective is complete. The session continues.'},'done':True,'done_reason':'stop'})+'\n')
    if 'APPLICATION EVENT / REVISION' in body['messages'][-1]['content'] and any(k in body['messages'][-1]['content'] for k in ('experience_changed','goal_changed')):
        # Distinct lines per selection, so consecutive acknowledgements are not dropped as repeats.
        SELECTION_REPLIES.append(SELECTION_LINES[len(SELECTION_REPLIES)%len(SELECTION_LINES)])
        return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:happy]]'+SELECTION_REPLIES[-1]},'done':True,'done_reason':'stop'})+'\n')
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
    app.state.director.config=DirectorConfig(user_idle_before_spontaneous_seconds=0.0) if mode=='fast' else DirectorConfig()
    app.state.speech.last_event=float('-inf');app.state.speech.busy_until=0
    return {'mode':mode}

@app.post('/fixture/settings-proposal')
async def settings_proposal(request: Request):
    SETTINGS_PROPOSALS.append(await request.json())
    # Decide on the next maintenance tick instead of waiting out the cadence.
    app.state.speech.settings.last_decision=-1e9
    return {'queued':len(SETTINGS_PROPOSALS)}

@app.delete('/fixture/settings-proposals')
async def clear_settings_proposals():
    SETTINGS_PROPOSALS.clear();return {'queued':0}

@app.get('/fixture/state')
async def observed():
    return {'state':app.state.observation.report,'director':dict(app.state.director.counts),'read_only':app.state.models.tool_executor is None,'thinking':app.state.models.config.thinking,'last_thinking':last_thinking,'player_requests':PLAYER_REQUESTS,'selection_replies':SELECTION_REPLIES,
            'settings_decisions':len(SETTINGS_DECISIONS),'settings_formatted':all(d['format'] for d in SETTINGS_DECISIONS),'settings_cards':SETTINGS_CARDS,'settings_replies':SETTINGS_REPLIES,'settings_proposals_left':len(SETTINGS_PROPOSALS)}
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=OBSERVER_PORT,access_log=False,ws_max_size=16384)
