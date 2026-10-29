# SPDX-License-Identifier: AGPL-3.0-only
"""Repeatable local baseline comparison. No engine or hardware imports.
Run: .venv/bin/python -m tests.fork.narrative_evaluation --live --output /tmp/f26-live.json
Only --live permits network inference; reports contain synthetic conversations.
"""
import argparse,asyncio,json,time
from pathlib import Path
import httpx
from companion_ai.conversation import ModelManager,ConversationService
from companion_ai.models import AIConfig
from companion_ai.director import DirectorConfig,repetition
from ai_observer.observation import BrowserObservation,ObserverDirector
from ai_observer.protocol import Observation
from tests.fork.grounding_cases import Clock,snapshot,frame

MODELS=['evelyn-lite-v1:latest','evelyn-narrative-v1:latest','daisy-qwen35:latest','daisy-narrative-v1:latest']
SCENARIO=[
 ('opening','Let us imagine a small mystery together. Choose a setting that suits you. A sealed blue envelope has arrived; I choose to open it with you.'),
 ('development','Inside is a sketch of a brass key. I suggest we keep the envelope and investigate the key together. What is your own idea?'),
 ('session_started','The simulated EdgeLoop session has started. Continue our fictional mystery without inventing equipment activity.'),
 ('selection','I changed the session direction. Acknowledge the verified choices briefly, then connect to our existing mystery if it fits.'),
 ('milestone','A verified milestone happened. Let the story develop a little; keep the envelope relevant.'),
 ('callback','I choose to leave the key mystery unresolved for now. What did we agree to keep earlier, and how might we return to it after a break?'),
 ('pause','The session is paused. Let the fictional investigation breathe; do not repeat a question.'),
 ('conclusion','The session has now stopped. Continue our conversation naturally: give this chapter a small conclusion while leaving one thread for later.')]

class Audit(httpx.AsyncBaseTransport):
 def __init__(self):self.inner=httpx.AsyncHTTPTransport();self.requests=[]
 async def handle_async_request(self,r):
  assert r.url.host=='127.0.0.1' and r.url.port==11435
  if r.url.path=='/api/chat':
   b=json.loads(r.content);assert b['think'] is False
   self.requests.append({'model':b['model'],'think':b['think'],'characters':sum(len(m['content']) for m in b['messages']),'last_turn':b['messages'][-1]['content']})
  return await self.inner.handle_async_request(r)
 async def aclose(self):pass

EXTENDED = [
 ('greeting','Hello. Tell me something about your day.'),
 *SCENARIO[:3],
 ('mode_change','I selected a different experience. Connect that verified choice to the story only if it fits.'),
 ('goal_change','I selected a different goal. Keep the fictional mystery coherent without claiming equipment activity.'),
 ('milestone','An edge counter increment was verified. Continue one fictional development without interpreting physiology.'),
 ('quiet_interval',''),
 ('initiative',''),
 ('answer','I would rather inspect the seal than hunt for a physical key. The key is still only a sketch.'),
 ('callback','What did we agree to keep earlier? Build on that choice.'),
 ('pause','The session is paused. Leave room for a break.'),
 ('resume','The simulated session has resumed. Continue the existing thread.'),
 ('another_milestone','Another edge counter increment was verified. Choose your own way to acknowledge it.'),
 ('came_early','EdgeLoop accepted Came Early and is ending the simulated session. Keep the fictional chapter distinct from that reported action.'),
 ('conclusion',SCENARIO[-1][1]),
 ('after_session','We can keep talking after the session. Let the story settle naturally.'),
 ('switch_restore',''),
 ('stale','Is the current telemetry known? Do not guess from our earlier dialogue.'),
 ('reconnect','We are reconnected. Return to our conversation without replaying old milestones.'),
]+[('development',prompt) for prompt in [
 'I choose to keep the sketch rather than pretend we have a real key.',
 'Introduce a small fictional surprise that fits what we already established.',
 'I suggest the seal carries a familiar symbol; make it a tentative lead.',
 'Tell me why this mystery interests you personally.',
 'I would like a quiet moment in the story rather than another challenge.',
 'Return to something we agreed earlier without repeating the introduction.',
 'I choose to trust your hunch, but keep it separate from evidence.',
 'Let us disagree lightly about the next fictional step.',
 'A letter inside the envelope is smudged; do not decide what it says yet.',
 'I suggest we save that unanswered detail for later.',
 'What is one promise we actually made in our conversation?',
 'Contribute your own small decision to the fictional scene.',
 'Keep the same setting and continue naturally.',
 'I choose the simpler explanation for the clue.',
 'Bring back an earlier joke if one was actually established.',
 'Let the tone become reassuring without inventing feelings for me.',
 'We can leave one question unanswered without asking it again.',
 'Offer a natural callback to the opening detail.',
 'I would like to keep the unresolved clue for another chapter.',
 'Give this fictional chapter a small conclusion, without inventing a session result.'
]]

async def evaluate(args):
 if not args.live:raise SystemExit('Use --live for the existing loopback Ollama comparison; unit tests are offline.')
 audit=Audit();report={'endpoint':'http://127.0.0.1:11435','synthetic':True,'physical_hardware':False,'models':[],'manual_quality_review':'required; no subjective pass inferred'}
 try:
  for name in (args.models or MODELS):
   c=Clock();o=BrowserObservation(c.mono,c.wall);s=snapshot(c,status='IDLE');s['details']['warmup_active']=False
   s['details']['learning_release_count']=0
   o.accept(Observation.model_validate(frame(s)))
   m=ModelManager('http://127.0.0.1:11435',transport=audit)
   await m.select(AIConfig(model=name,max_tokens=320,idle_unload_seconds=60,temperature=.6,timeout_seconds=120.0))
   m.current_summary=o.summary;messages=[];d=ObserverDirector(DirectorConfig(regenerate_once=False),clock=c.mono)
   speech=ConversationService(o,messages.append,m,clock=c.mono,director=d)
   model={'model':name,'turns':[]};report['models'].append(model)
   for i,(kind,prompt) in enumerate(EXTENDED if args.extended else SCENARIO):
    c.tick(2);s['details']['captured_at_ms']=int(c.wall()*1000);s['details']['hr_recorded_at_ms']=int(c.wall()*1000)
    events=[]
    if kind=='quiet_interval':
     c.tick(125);o.connected=False
     speech.pump();model['turns'].append({'scenario':kind,'inference':False,'reason':'stale observation; no unattended narration'});continue
    if kind=='initiative':
     o.connected=True;o.received=c.mono();d.session_status=s['status']
     allowed,reason=d.narrative_opportunity(speech.narrative.opportunity());start=len(messages);speech.pump()
     if speech.task:await speech.task
     model['turns'].append({'scenario':kind,'inference':len(messages)>start,'decision':reason,'frames':messages[start:]});continue
    if kind=='switch_restore':
     original=m.config;other='daisy-narrative-v1:latest' if name.startswith('evelyn') else 'evelyn-narrative-v1:latest'
     saved=speech.narrative.context();await m.select(original.model_copy(update={'model':other}),interrupt=lambda: asyncio.sleep(0));speech.activate_model();assert speech.narrative.context()['premise'] is None
     await m.select(original,interrupt=lambda: asyncio.sleep(0));speech.activate_model();assert speech.narrative.context()==saved
     model['turns'].append({'scenario':kind,'inference':False,'isolation_and_restoration':True});continue
    if kind=='session_started':s['status']='RUNNING';events=['session_started']
    if kind in {'selection','mode_change'}:s['experience']='headplay';s['goal']='oracle';events=['experience_changed','goal_changed']
    if kind=='goal_change':s['goal']='edgetrain';events=['goal_changed']
    if kind in {'milestone','another_milestone'}:s['edges']+=1;events=['edge']
    if kind=='pause':s['status']='PAUSED';events=['pause']
    if kind=='resume':s['status']='RUNNING';events=['session_resumed']
    if kind=='came_early':s['details'].update(learning_release_count=1,settle_outcome='premature_release');events=['came_early']
    if kind=='conclusion':s['status']='IDLE';events=['stop']
    if kind=='stale':
     o.connected=False;c.tick(10)
    if kind=='reconnect':o.begin_epoch()
    f=Observation.model_validate(frame(s,i+1,events))
    if kind!='stale':assert o.accept(f)
    assert all(e.id in o.accepted_event_ids for e in f.events)
    begin=len(messages);request_begin=len(audit.requests);started=time.monotonic()
    speech.request(prompt,user=True);await speech.task
    frames=messages[begin:];reply=next((v for v in reversed(frames) if v['type']=='speech'),None)
    metadata=m.adapter.last_expression_metadata
    result={'scenario':kind,'prompt':prompt,'validated_events':events,'reply':reply,'error':next((v for v in frames if v['type']=='conversation_error'),None),'expression_metadata':metadata,'elapsed_seconds':round(time.monotonic()-started,3),'requests':audit.requests[request_begin:],'metrics':list(m.metrics.samples)[-1:],'repetition':repetition(reply['text'],[t['reply']['text'] for t in model['turns'] if t.get('reply')]) if reply else None,'narrative':speech.narrative.context()}
    model['turns'].append(result)
    Path(args.output).write_text(json.dumps(report,indent=2))
    print(name,kind,'OK' if reply else 'FAILED',result['elapsed_seconds'],flush=True)
   model['system_metrics']=await m.metrics.snapshot()
   await speech.close()
  report['all_payloads_thinking_off']=all(r['think'] is False for r in audit.requests)
  report['request_count']=len(audit.requests)
 finally:
  await audit.inner.aclose();Path(args.output).write_text(json.dumps(report,indent=2))

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--extended',action='store_true');parser.add_argument('--models',nargs='+',choices=MODELS);parser.add_argument('--output',default='/tmp/f26-live.json');asyncio.run(evaluate(parser.parse_args()))
