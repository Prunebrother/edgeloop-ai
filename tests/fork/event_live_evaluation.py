# SPDX-License-Identifier: AGPL-3.0-only
"""Limited paired event evaluation on existing 11435; never modifies models."""
import argparse,asyncio,json,time
from pathlib import Path
import httpx
from companion_ai.conversation import ConversationService,ModelManager
from companion_ai.models import AIConfig
from companion_ai.director import DirectorConfig
from ai_observer.observation import ObserverDirector
from tests.fork.event_replay import Replay
MODELS=['evelyn-narrative-v1:latest','daisy-narrative-v1:latest']
class Audit(httpx.AsyncBaseTransport):
 def __init__(self):self.inner=httpx.AsyncHTTPTransport();self.wire=[]
 async def handle_async_request(self,r):
  assert r.url.host=='127.0.0.1' and r.url.port==11435
  if r.url.path=='/api/chat':
   b=json.loads(r.content);assert b['think'] is False;self.wire.append({'model':b['model'],'think':b['think'],'last_turn':b['messages'][-1]['content'],'input_characters':sum(len(m['content']) for m in b['messages'])})
  return await self.inner.handle_async_request(r)
 async def aclose(self):pass
async def main(args):
 if not args.live:raise SystemExit('Explicit --live required')
 audit=Audit();result={'endpoint':'http://127.0.0.1:11435','physical_hardware':False,'models':[],'policy':'Identical three episodes, 200 simulated seconds apart; narrative initiative disabled for paired event comparison. Existing Director cooldowns active.'}
 try:
  for name in MODELS:
   r=Replay();r.step(85,seconds=0);m=ModelManager(result['endpoint'],transport=audit);await m.select(AIConfig(model=name,max_tokens=320,temperature=.6,idle_unload_seconds=60,timeout_seconds=120.0));m.current_summary=r.observation.summary
   d=ObserverDirector(DirectorConfig(narrative_initiative_enabled=False),clock=r.clock.mono);d.session_status='RUNNING';frames=[];s=ConversationService(r.observation,frames.append,m,clock=r.clock.mono,director=d);s.event_intelligence=r.detector
   model={'model':name,'responses':[]};result['models'].append(model)
   async def record(label,prompt=None):
    start=len(frames);requests=len(audit.wire);begin=time.monotonic()
    if prompt:s.request(prompt,user=True)
    else:s.pump()
    if s.task:await s.task
    fresh=frames[start:];reply=next((f for f in reversed(fresh) if f['type']=='speech'),None)
    if reply or any(f['type']=='conversation_error' for f in fresh):
     model['responses'].append({'scenario':label,'reply':reply,'error':next((f for f in fresh if f['type']=='conversation_error'),None),'elapsed_seconds':round(time.monotonic()-begin,3),'metadata':m.adapter.last_expression_metadata,'requests':audit.wire[requests:],'metrics':list(m.metrics.samples)[-1:]});print(name,label,'reply' if reply else 'ERROR',flush=True)
     Path(args.output).write_text(json.dumps(result,indent=2))
   await record('opening','Imagine a small mystery together. I choose to keep a sealed blue envelope as our fictional clue. Continue in your own setting; do not invent bodily observations.')
   for label,values in [('rapid_rise',[85+i for i in range(26)]),('rapid_fall',[115-i for i in range(26)]),('sustained_elevation',[100]*40)]:
    if label=='sustained_elevation':await record('user_checkin','I am still following our fictional clue. Continue when there is a relevant observation, without guessing its cause.')
    s.process_derived(r.step(values[0],seconds=200))
    for value in values:
     s.process_derived(r.step(value));await record(label)
   model['events']=s.event_intelligence.snapshot();model['history']=list(s.history);model['narrative']=s.narrative.context();model['system_metrics']=await m.metrics.snapshot();await s.close()
  result['thinking_off_verified']=all(w['think'] is False for w in audit.wire);result['requests']=len(audit.wire)
 finally:
  await audit.inner.aclose();Path(args.output).write_text(json.dumps(result,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--output',default='/tmp/f27-live.json');asyncio.run(main(p.parse_args()))
