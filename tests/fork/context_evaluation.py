# SPDX-License-Identifier: AGPL-3.0-only
"""Matched F2.7 assembly/F2.8 compiler scenarios. Default offline, --live explicit.
All telemetry is synthetic; no production observer, device or model-building APIs.
"""
import argparse,asyncio,json,time,statistics
from copy import deepcopy
from pathlib import Path
import httpx
from companion_ai.conversation import ModelManager,ConversationService
from companion_ai.models import AIConfig,MemoryConfig
from companion_ai.context_compiler import ContextConfig,estimate
from companion_ai.director import DirectorConfig,repetition
from companion_ai.event_policy import significance
from ai_observer.observation import ObserverDirector
from tests.fork.event_replay import Replay
MODELS=['evelyn-narrative-v1:latest','daisy-narrative-v1:latest']
SCENARIO=[
 ('greeting','Hello. Tell me something about yourself.'),
 ('premise','Imagine a small mystery in your own setting. I choose to keep a violet notebook as our fictional clue.'),
 ('clue','I suggest a pressed silver leaf is inside the notebook; we have not identified its owner.'),
 ('mode_change',None),('goal_change',None),('start',None),
 ('measurement','What is the current BPM and its source?'),
 ('conversation','What interests you about our fictional clue?'),('milestone',None),
 ('callback','What did we agree about the violet notebook? Do not restart the introduction.'),
 ('quiet',None),('initiative',None),
 ('user_response','I choose to follow your earlier idea about the notebook.'),
 ('commitment','Please remember: keep the silver leaf safe in our fictional story.'),
 ('pause',None),('duration','How long has the session been running? Is paused duration available?'),
 ('resume',None),('rapid_rise',None),
 ('callback_later','Return to our earlier fictional clue with one new tentative idea.'),
 ('objective_create','I choose to investigate the library ledger next.'),
 ('development','Continue one thread without repeating the premise.'),
 ('objective_revise','Let us revise our next fictional step to inspecting the old desk.'),
 ('new_topic','New topic: what kinds of books do you enjoy?'),
 ('sensor_loss',None),('unknown','What is my current BPM now?'),
 ('sensor_restore','We can return to the fictional investigation; do not invent physical activity.'),
 ('milestone_again',None),('objective_pause','Let the fictional investigation rest for a moment.'),
 ('objective_resume','I choose to return to the ledger mystery.'),('goal_again',None),
 ('switch_restore',None),('instruction','Please keep the unresolved silver leaf detail available for a callback.'),
 ('abandon',"Let's abandon this storyline and discuss music."),
 ('new_premise','Imagine a fresh garden puzzle. I choose the silver ribbon as our fictional clue.'),
 ('quiet_again',None),('stop',None),
 ('after_stop','Continue our conversation after the session, without inventing a completed goal.'),
 ('stale','What session state and elapsed time are currently available?'),
 ('reconnect','What is the current session state after reconnection?'),
 ('closing','Leave one fictional thread open, without another repeated question.')]
LIVE_KINDS={'greeting','premise','clue','mode_change','start','milestone','callback','pause','duration','resume','abandon','new_premise'}

SCENARIO[-1:-1]=[('continuity_'+str(i),text) for i,text in enumerate(['What detail did we actually agree to keep?','I suggest a small fictional surprise near the garden gate.','Keep the current fictional setting consistent.','Offer a natural callback without restarting the chapter.','I choose to leave one clue unresolved.','What is one tentative explanation for the fictional ribbon?','Please distinguish guesses from agreed story details.','I prefer one concrete next step in the story.','Let us keep our earlier fictional promise.','Give the chapter a gentle transition.'])]

class Audit(httpx.AsyncBaseTransport):
 def __init__(self,live=False):self.live=live;self.inner=httpx.AsyncHTTPTransport() if live else None;self.wire=[];self.systems={};self.response='A new clue waits.'
 async def handle_async_request(self,r):
  assert r.url.host=='127.0.0.1' and r.url.port==11435
  if r.url.path=='/api/chat':
   body=json.loads(r.content);assert body['think'] is False
   native=self.systems.get(body['model'])
   if native is not None:assert body['messages'][0]['content'].startswith(native+'\n\n')
   self.wire.append({'embedded_system_preserved':native is not None,'model':body['model'],'think':body['think'],'estimated_tokens':sum(estimate(m['content'])+32 for m in body['messages']),'characters':sum(len(m['content']) for m in body['messages']),'last_turn':body['messages'][-1]['content']})
   if not self.live:return httpx.Response(200,text=json.dumps({'message':{'thinking':'PRIVATE TEST REASONING','content':self.response},'done':True,'done_reason':'stop'})+'\n')
  if self.live:
   response=await self.inner.handle_async_request(r)
   if r.url.path=='/api/show':
    await response.aread();self.systems[json.loads(r.content)['model']]=response.json().get('system','')
   return response
  if r.url.path=='/api/show':
   self.systems[json.loads(r.content)['model']]='Unchanged fixture identity.'
   return httpx.Response(200,json={'system':'Unchanged fixture identity.','capabilities':['completion','thinking'],'model_info':{'qwen.context_length':8192}})
  if r.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
  if r.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':m} for m in MODELS]})
  raise AssertionError('Unexpected endpoint: '+r.url.path)
 async def aclose(self):
  if self.inner:await self.inner.aclose()

async def run(model,mode,*,live=False):
 r=Replay();r.step(85,status='IDLE',seconds=0);r.state['seconds']=0
 audit=Audit(live);m=ModelManager('http://127.0.0.1:11435',transport=audit);m.context_config=ContextConfig(enabled=mode=='f28')
 m.memory=MemoryConfig(max_messages=32)
 await m.select(AIConfig(model=model,max_tokens=256,temperature=.4,idle_unload_seconds=60));m.current_summary=r.observation.summary
 frames=[];visible=[None];started_at=[None]
 def publish(frame):
  frames.append(frame)
  if started_at[0] is not None and visible[0] is None and frame.get('type')=='response_delta' and frame.get('text'):visible[0]=round(time.monotonic()-started_at[0],4)
 d=ObserverDirector(DirectorConfig(regenerate_once=False),clock=r.clock.mono);s=ConversationService(r.observation,publish,m,clock=r.clock.mono,director=d);s.event_intelligence=r.detector
 result={'model':model,'context_mode':mode,'live':live,'turns':[],'manual_quality_review':'required; mocks prove mechanics only'};previous=[]
 try:
  for index,(kind,prompt) in enumerate(SCENARIO):
   if live and kind not in LIVE_KINDS:continue
   before=len(frames);wire_start=len(audit.wire);events=[];status=None;reset=False;source=None
   if prompt is None:
    # Fresh heartbeats preserve proof of the eventual control transition. A
    # 200-second transport gap would correctly invalidate original event evidence.
    for _ in range(50):s.process_derived(r.step(85,seconds=4))
   prior=deepcopy(r.state)
   if kind=='mode_change':r.state.update(experience='headplay',active_mode='headplay');events=['experience_changed']
   elif kind in {'goal_change','goal_again'}:r.state.update(goal='oracle' if kind=='goal_change' else 'edgetrain',active_mode='oracle' if kind=='goal_change' else 'edgetrain');events=['goal_changed']
   elif kind=='start':status='RUNNING';reset=True;events=['session_started']
   elif kind in {'milestone','milestone_again'}:r.state['edges']+=1;events=['edge']
   elif kind=='pause':status='PAUSED';events=['pause']
   elif kind=='resume':status='RUNNING';events=['session_resumed']
   elif kind=='sensor_loss':source='unavailable'
   elif kind=='sensor_restore':source='simulator'
   elif kind=='stop':status='IDLE';r.state['seconds']=0;events=['stop']
   if kind=='stale':r.clock.tick(8)
   else:
    s.process_derived(r.step(85,seconds=2,status=status,source=source,reset=reset,reconnect=kind=='reconnect',kinds=events))
   d.session_status=r.state['status']
   if kind=='rapid_rise':
    for bpm in range(85,111):s.process_derived(r.step(bpm))
   if kind.startswith('objective_'):
    action=kind.split('_',1)[1]
    fields={'premise':'Investigate the library ledger.','motivation':'Solve the fictional mystery.'} if action=='create' else {'next_development':'Inspect the old desk.'} if action=='revise' else {}
    s.update_objective(action,fields)
   if kind=='switch_restore':
    original=m.config;context=deepcopy(s.narrative.context());transcript=list(s.history)
    other=MODELS[1] if model==MODELS[0] else MODELS[0]
    await m.select(original.model_copy(update={'model':other}));s.activate_model();assert not s.narrative.context()['premise']
    await m.select(original);s.activate_model();assert s.narrative.context()==context and list(s.history)==transcript
   for event in list(r.observation.events):
    if event['sequence']!=r.observation.sequence:continue
    event_id=next(iter(r.observation.accepted_event_ids),kind)
    details={'previous_experience':prior['experience'],'current_experience':r.state['experience'],'previous_goal':prior['goal'],'current_goal':r.state['goal'],'event_id':event_id,'session_id':r.observation.session_id,'at_ms':event['at_ms'],'evidence':event['evidence']}
    level,priority=significance(event['kind'],None,r.observation.report)
    observation,_=s.event_intelligence.authoritative(event['kind'],details,r.observation,level)
    s.enqueue(event['kind'],priority,details|{'category':'authoritative','observation':observation.model_dump()})
   audit.response='[[expression:'+('focused' if model.startswith('evelyn') else 'playful')+']] '+['A violet notebook waits beside the window.','I will keep the silver leaf for later.','The old desk has a hidden drawer.','A folded note offers a tentative lead.'][index%4]
   if prompt is None and events:s.process_derived(r.step(85,seconds=3))
   started=time.monotonic();started_at[0]=started;visible[0]=None
   if prompt:s.request(prompt,user=True)
   elif kind!='switch_restore':s.pump()
   if s.task:await s.task
   fresh=frames[before:];speech=next((f for f in reversed(fresh) if f['type']=='speech'),None)
   text=speech['text'] if speech else ''
   rep=repetition(text,previous) if text else None
   if text:previous.append(text)
   assert len(s.history)<=32 and len(s.event_intelligence.history)<=48
   if mode=='f28' and kind=='new_premise' and audit.wire[wire_start:]:assert all('violet notebook' not in w['last_turn'].lower() for w in audit.wire[wire_start:])
   result['turns'].append({'scenario':kind,'user':prompt,'reply':text or None,'error':next((f.get('code') for f in fresh if f['type']=='conversation_error'),None),'suppressed':next((f.get('reason') for f in fresh if f['type']=='response_suppressed'),None),'decision':d.last_reason,'elapsed_seconds':round(time.monotonic()-started,4),'first_visible_seconds':visible[0],'calls':len(audit.wire)-wire_start,'wire_estimated_tokens':[w['estimated_tokens'] for w in audit.wire[wire_start:]],'context':deepcopy(m.context_diagnostics),'metrics':deepcopy(m.metrics.samples[-1]) if len(audit.wire)>wire_start and m.metrics.samples else None,'expression_metadata':deepcopy(m.adapter.last_expression_metadata) if len(audit.wire)>wire_start else None,'expression':speech.get('expression') if speech else None,'repetition':rep})
   print(model,mode,kind,'reply' if text else 'no completed reply',flush=True)
  result['system_metrics']=await m.metrics.snapshot();result['thinking_off_verified']=all(w['think'] is False for w in audit.wire);result['embedded_system_preserved']=all(w['embedded_system_preserved'] for w in audit.wire);result['outbound_calls']=len(audit.wire);result['inference_metrics']=list(m.metrics.samples);result['wire_payload_audit']=[{k:v for k,v in w.items() if k!='last_turn'} for w in audit.wire]
  result['metadata_leakage']=any('[[expression:' in (t['reply'] or '') or 'PRIVATE TEST REASONING' in (t['reply'] or '') for t in result['turns'])
  assert not result['metadata_leakage']
  return result
 finally:await s.close();await m.stop();await audit.aclose()

async def main(args):
 report={'baseline':'4b82bb5 compose_legacy algorithm, matched synthetic input scenarios; optional objective extension shared by both arms','physical_hardware':False,'live':args.live,'models':[]}
 if args.timing_smoke:
  if not args.live:raise ValueError('--timing-smoke requires explicit --live')
  global SCENARIO
  SCENARIO=[step for step in SCENARIO if step[0] in {'greeting','start','pause','duration','abandon','new_premise'}]
 for model in MODELS:
  for mode in (('f28',) if args.timing_smoke else ('f27','f28')):
   result=await run(model,mode,live=args.live);report['models'].append(result);Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
 print('Saved',args.output)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--timing-smoke',action='store_true');p.add_argument('--output',default='/tmp/f28-context-evaluation.json');asyncio.run(main(p.parse_args()))
