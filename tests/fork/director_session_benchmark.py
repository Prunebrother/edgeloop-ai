# SPDX-License-Identifier: AGPL-3.0-only
"""900-second virtual observer session, real scheduler/compiler, mocked Ollama only.
Run: python -m tests.fork.director_session_benchmark --output /tmp/f285-session.json
This measures orchestration, not personality or live-model narrative quality.
"""
import argparse,asyncio,json,re,statistics,time
from collections import Counter
from copy import deepcopy
from pathlib import Path
import httpx
from companion_ai.conversation import ConversationService,ModelManager
from companion_ai.director import DirectorConfig,transition_occurrence
from companion_ai.models import AIConfig
from ai_observer.observation import ObserverDirector
from tests.fork.event_replay import Replay

REPLIES=[
 'The atlas leaves an unresolved choice between a familiar road and an untested path. We can let that choice matter before deciding what follows.',
 'A small detail from our conversation deserves another look: the reason behind a preference can be more revealing than the preference itself.',
 'Returning to an established promise gives the next scene a useful direction. It can develop through a decision rather than another description of the surroundings.',
 'I have an unrelated curiosity: which ordinary discovery has ever persuaded you to reconsider something you thought was settled?',
 'There is an interesting contrast between what the scene makes obvious and what its characters still need to discover. That gap offers room for a meaningful development.',
 'A useful connection is waiting between an earlier decision and an unfinished task. We can explore its consequences without changing the facts already established.',
 'The folded map may invite an investigation of a different route. Choosing whether to share that discovery could give the scene a new direction.',
 'Some conversations become more interesting when a comfortable assumption meets a carefully chosen challenge. I wonder which idea you would enjoy testing in fiction.',
 'An unresolved question can remain open while something else develops. The next choice need not supply a tidy explanation of everything that came before.',
 'The promised return of an object gives us a concrete point of continuity. What changes next can come from the people involved, rather than rewriting the promise.',
 'A pause in dialogue can make space for a fresh perspective. There is no need to turn it into another account of the equipment or an old application transition.',
 'A discovery becomes consequential when someone must decide what to do with it. That provides a different direction from simply describing its appearance again.'
]

async def run_arm(experimental):
 r=Replay();r.step(85,seconds=0);started_at=r.clock.mono();frames=[];wire=[];requests={};starts=[];s=None;last_reply='';count=0;active=0;peak=0
 def publish(message):
  frames.append(message|{'virtual_at':r.clock.mono()-started_at})
  if message['type']=='response_start':starts.append(message['id'])
 async def transport(request):
  nonlocal count,last_reply,active,peak
  if request.url.path=='/api/show':return httpx.Response(200,json={'system':'Synthetic fixture identity. No character/persona evaluation.','capabilities':['completion','thinking'],'thinking':{'values':[True,False]},'model_info':{'qwen35.context_length':8192}})
  if request.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
  assert request.url.path=='/api/chat','Unexpected provider operation: '+request.url.path
  body=json.loads(request.content);wire.append({'think':body['think'],'tools':bool(body.get('tools')),'num_predict':body['options']['num_predict']})
  active+=1;peak=max(peak,active);await asyncio.sleep(0)
  # Intentionally repeat one in nine candidates: suppression is a measured outcome.
  text=last_reply if count and count%9==0 else REPLIES[count%len(REPLIES)]
  last_reply=text;count+=1;active-=1
  return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:neutral]]'+text},'done':True})+'\n')
 class Manager(ModelManager):
  async def reply(self,summary,prompt,history,**options):
   request_id=starts[-1]
   op=summary.get('director_opportunity') or {};trigger=summary.get('trigger_event') or {}
   requests[request_id]={'trigger':op.get('intent') or trigger.get('kind') or ('legacy_narrative' if summary.get('narrative_initiative') else 'direct_user'),'topic':op.get('topic_key'),'event_id':trigger.get('event_id'),'sequence':trigger.get('sequence'),'source':summary.get('conversation_source'),'at':r.clock.mono()-started_at}
   result=await super().reply(summary,prompt,history,**options)
   requests[request_id]['estimated_prompt_tokens']=self.context_diagnostics.get('estimated_prompt_tokens')
   return result
 m=Manager(transport=httpx.MockTransport(transport));await m.select(AIConfig(model='qwen3:8b'))
 d=ObserverDirector(DirectorConfig(experimental_idle_enabled=experimental,regenerate_once=False,max_consecutive_unsolicited=4),clock=r.clock.mono)
 s=ConversationService(r.observation,publish,m,clock=r.clock.mono,director=d)
 d.session_status='RUNNING';saved=[];t0=time.perf_counter();stop_at=840
 async def settle():
  if s.task and not s.task.done():await s.task
 def emit(kind,id,before):
  occurrence=transition_occurrence(kind,before,r.state,int(r.clock.wall()*1000))
  details={'event_id':id,'session_id':r.observation.session_id,'at_ms':int(r.clock.wall()*1000),'sequence':r.observation.sequence,'category':'authoritative','occurrence':occurrence,'significance':'major'}
  if kind in {'experience_changed','goal_changed'}:details|={'previous_experience':before['experience'],'current_experience':r.state['experience'],'previous_goal':before['goal'],'current_goal':r.state['goal']}
  s.enqueue(kind,50,details);saved.append((kind,details))
 for second in range(901):
  before=deepcopy(r.state)
  if second in {110,260,440,620}:r.state['edges']+=1
  if second in {160,400,580}:r.state['experience']={160:'headplay',400:'milker',580:'headplay'}[second]
  status='PAUSED' if 310<=second<325 else 'IDLE' if second>=stop_at else 'RUNNING'
  r.step(85,seconds=0 if second==0 else 1,status=status);d.session_status=status
  if second in {0,150,450,600,750}:
   s.request('Imagine a fictional atlas mystery. I choose the garden. My preferred drink is tea. Let us consider another route.' if second==0 else 'Continue our conversation about a different choice in the atlas story.',True);await settle()
  if second==220:s.request('Give me a break.',True);await settle()
  if second==250:s.request('You can talk again. We can return to our fictional map.',True);await settle()
  if second in {110,260,440,620}:emit('edge','edge-'+str(r.state['edges']),before)
  if second in {160,400,580}:emit('experience_changed','mode-'+str(second),before)
  if second==300:emit('milestone','five-minutes',before)
  if second==310:s.safety('pause')
  if second==325:emit('session_resumed','resumed',before)
  # Delayed exact and new-envelope replays of the same occurrence.
  if second in {211,360,530,700} and saved:
   kind,details=saved[0];s.enqueue(kind,50,details)
   s.enqueue(kind,50,details|{'event_id':'backfill-'+str(second),'sequence':r.observation.sequence})
  if second==500:
   r.observation.begin_epoch();r.step(85,seconds=0)
   if saved:s.enqueue(saved[0][0],50,saved[0][1])
  if second==stop_at:s.safety('stop')
  s.pump();await settle()
 await s.close()
 autonomous=[f for f in frames if f['type']=='speech' and f.get('source')=='event'];times=[f['virtual_at'] for f in autonomous];spacing=[b-a for a,b in zip(times,times[1:])]
 accepted=[requests[f['id']] for f in autonomous];ids=[v['event_id'] for v in accepted if v['event_id']]
 counts=Counter(v['trigger'] for v in accepted);decisions=Counter(v['reason'] for v in d.decisions)
 return {'experimental_idle':experimental,'virtual_seconds':900,'stopped_at':stop_at,'autonomous_messages':len(autonomous),'trigger_categories':dict(counts),'requested_trigger_categories':dict(Counter(v['trigger'] for v in requests.values() if v['source']=='event')),'duplicate_accepted_event_ids':len(ids)-len(set(ids)),'duplicate_events_suppressed':d.counts['duplicate_occurrences'],'topic_candidates_suppressed':d.counts['topic_candidates_suppressed'],'repetitive_candidates_suppressed':d.counts['responses_suppressed'],'repetition_frequency':d.counts['responses_suppressed']/max(1,sum(1 for v in requests.values() if v['source']=='event')),'average_response_spacing_seconds':round(statistics.mean(spacing),2) if spacing else None,'spacing_seconds':[round(v,2) for v in spacing],'errors':sum(f['type']=='conversation_error' for f in frames),'queue_expired_or_scope':d.counts['queue_expired_or_scope'],'recent_decision_counts':dict(decisions),'deferral_reason_transitions':{k.split(':',1)[1]:v for k,v in d.counts.items() if k.startswith('deferral_transitions:')},'director_counts':dict(d.counts),'provider_calls':len(wire),'maximum_parallel_inference':peak,'thinking_off':all(not v['think'] for v in wire),'hardware_tools_exposed':any(v['tools'] for v in wire),'output_budget_unchanged':all(v['num_predict']==2048 for v in wire),'messages_after_stop':sum(f['virtual_at']>=stop_at for f in autonomous),'accepted_turns':accepted,'cpu_wall_seconds':round(time.perf_counter()-t0,3),'kind':'real scheduler/context compilation; synthetic responses, not live-model novelty quality'}

async def evaluate():return {'baseline':'current scheduler with experimental idle off','experimental':'same scheduler with experimental idle on','arms':[await run_arm(False),await run_arm(True)]}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();result=asyncio.run(evaluate());Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='arms'}|{'arms':[{k:v for k,v in row.items() if k not in {'accepted_turns','director_counts','recent_decision_counts','spacing_seconds'}} for row in result['arms']]}))
