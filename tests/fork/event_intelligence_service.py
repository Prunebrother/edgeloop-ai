# SPDX-License-Identifier: AGPL-3.0-only
"""Isolated authenticated replay fixture. No engine or hardware connections."""
import asyncio,json,tempfile,os
from copy import deepcopy
from uuid import uuid4
import httpx,uvicorn
from ai_observer.server import create_app
from tests.fork.grounding_cases import Clock,snapshot,frame
TOKEN='f27-browser-fixture-'+'x'*32
clock=Clock();sequence=0;state=snapshot(clock,seconds=0);state['details'].update(warmup_active=False,learning_release_count=0,settle_outcome=None)
wire=[]
MODELS=['evelyn-narrative-v1:latest','daisy-narrative-v1:latest']
async def transport(request):
 body=json.loads(request.content) if request.content else {}
 if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':m} for m in MODELS]})
 if request.url.path=='/api/show':return httpx.Response(200,json={'system':'Native synthetic test identity.','capabilities':['completion','thinking']})
 if request.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
 if request.url.path=='/api/chat':
  assert body['think'] is False;wire.append(body)
  prompt=body['messages'][-1]['content'];marker='DERIVED TELEMETRY OBSERVATION (historical source evidence, not a safety event; no physiological cause or emotion established):\n'
  if 'DERIVED TELEMETRY OBSERVATION (' in prompt:
   block=prompt.split('DERIVED TELEMETRY OBSERVATION (',1)[1].split('\n',1)[1];e=json.JSONDecoder().raw_decode(block)[0];e=e[0] if isinstance(e,list) else e;expression='focused' if body['model'].startswith('evelyn') else 'playful'
   dialogue=f"The simulator endpoint medians changed by {e['change_bpm']:g} BPM over {e['window_seconds']:g} seconds. We can keep that observation as a clue; no cause is established."
  else:expression='happy';dialogue='A sealed envelope waits beside the garden path. We can return to that mystery later.'
  class Stream(httpx.AsyncByteStream):
   async def __aiter__(self):
    for text in ['[[expr','ession:'+expression+']] ',*[word+' ' for word in dialogue.split(' ')]]:
     yield (json.dumps({'message':{'content':text},'done':False})+'\n').encode();await asyncio.sleep(.08)
    yield b'{"done":true,"done_reason":"stop"}\n'
  return httpx.Response(200,stream=Stream())
 return httpx.Response(200,json={'done':True})
app=create_app(TOKEN,tempfile.mkdtemp(prefix='f27-browser-'),transport=httpx.MockTransport(transport),clock=clock.mono,origins={'http://127.0.0.1:8860'})
app.state.observation.wall=clock.wall
@app.post('/fixture/step/{bpm}')
async def step(bpm:int,reset:bool=False):
 global sequence,state
 clock.tick(200 if reset else 1)
 if reset:state['session_id']=str(uuid4());state['seconds']=0
 state['hr']=bpm;state['seconds']+=1;state['details'].update(captured_at_ms=int(clock.wall()*1000),hr_recorded_at_ms=int(clock.wall()*1000))
 result=frame(deepcopy(state),sequence);sequence+=1;return result
@app.get('/fixture/state')
async def inspect():
 return {'view':app.state.speech.character_state(),'requests':wire,'history':list(app.state.speech.history),'report':app.state.observation.report}
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=8868,access_log=False)
