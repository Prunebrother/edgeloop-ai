# SPDX-License-Identifier: AGPL-3.0-only
"""Deterministic Event Deck session: real scheduler, deck and compiler; mocked Ollama only.
Run: python -m tests.fork.deck_session_benchmark --output /tmp/deck-session.json [--arm off]
Measures orchestration at the production 250-ms poll, not prose quality or live latency.
The off arm imports nothing from the deck, so it also runs against pre-deck commits.
"""
import argparse,asyncio,json,re,tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
import httpx
from ai_observer.observation import ObserverDirector
from companion_ai.conversation import ConversationService,ModelManager
from companion_ai.director import DirectorConfig,transition_occurrence
from companion_ai.models import AIConfig
from companion_ai.storage import SettingsStore
from tests.fork.event_replay import Replay

BASE='http://127.0.0.1:11435'
NOVA='nova-narrative-v1:latest'
EVELYN='evelyn:latest'
STOP=720
TICK=.25
SUBJECTS=['copper kettle','winter market','folded chart','paper lantern','quiet orchard','stone bridge','glass atrium','cedar cabinet','tidal cavern','velvet curtain','brass compass','mossy stairway','amber window']
PREDICATES=['hides a stubborn little riddle','suggests a stranger way forward','keeps surprising careful visitors','deserves another patient look','changes meaning after sundown','rewards unhurried curiosity','invites one more honest question','remembers older unfinished plans','makes ordinary errands feel odd','turns a small habit into adventure','argues against tidy explanations','prefers conversation over ceremony','offers a gentler kind of mischief','quietly outlasts every fashion','gives familiar choices sharper edges','asks who benefits from certainty','treats patience like a craft']

def reply(index):
 return f'The {SUBJECTS[index%len(SUBJECTS)]} {PREDICATES[index%len(PREDICATES)]}.'

def fixture_definition():
 from companion_ai.event_deck import Card,DeckDefinition,Eligibility,Sequence,SequenceTrigger
 card=lambda id,kind='normal',**values:Card(id=id,kind=kind,intent='comment',brief='Benchmark brief '+id,**values)
 return DeckDefinition(session_start=[card('opening','session_start')],session_end=[card('closing','session_end')],
  normal=[card(f'routine-{i}') for i in range(4)]+[card('only-nova',audience='nova'),card('only-evelyn',audience='evelyn')],
  sequences=[Sequence(id='edge-milestone',lane='mission',trigger=SequenceTrigger(event_kinds=['edge']),steps=[card('edge-card','mission')]),
   Sequence(id='ten-minutes',lane='mission',trigger=SequenceTrigger(min_seconds=600),steps=[card('ten-minute-card','mission')]),
   Sequence(id='story-beat',lane='narrative',trigger=SequenceTrigger(event_kinds=['edge']),steps=[card('story-card','narrative',memory='story',eligibility=Eligibility(requires_story_welcome=True))])])

class Rig:
 def __init__(self,root,deck,model=NOVA):
  self.deck=deck;self.root=root;self.r=Replay();self.r.state['devices'].update(toy_ready=True,handy=True);self.r.state['safety']['fault']='none'
  self.r.step(85,seconds=0);self.start=self.r.clock.mono();self.frames=[];self.turns=[];self.speech=[];self.bodies=[];self.count=0;self.active=0;self.peak=0;self.starts=[];self.s=None
  self.store=SettingsStore(root)
  # Both arms write an explicit per-model setting; the 'off' arm does not rely on the default.
  self.enable(model,deck);self.enable(EVELYN,deck)
 def enable(self,model,on=True):
  from companion_ai.event_deck import scope_key
  path=self.root/'deck-settings.json';saved=json.loads(path.read_text()) if path.exists() else {'schema_version':1,'models':{}}
  saved['models'][scope_key('ollama:'+BASE+':'+model)]={'enabled':on,'countdown_seconds':10.}
  self.store.write('deck-settings.json',saved)
 def at(self):return round(self.r.clock.mono()-self.start,2)
 def publish(self,message):
  self.frames.append(message)
  if message['type']=='response_start':self.starts.append(message['id'])
  if message['type']=='speech':self.speech.append({'id':message['id'],'source':message['source'],'text':message['text'],'at':self.at(),'status':self.r.observation.status,'output_end':round(self.s.busy_until-self.start,2) if message['source']!='safety' else None})
 async def transport(self,request):
  if request.url.path=='/api/show':return httpx.Response(200,json={'system':'Synthetic fixture identity. No character evaluation.','capabilities':['completion','thinking'],'thinking':{'values':[True,False]},'model_info':{'qwen35.context_length':8192}})
  if request.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
  assert request.url.path=='/api/chat','Unexpected provider operation: '+request.url.path
  body=json.loads(request.content);self.bodies.append(body);self.active+=1;self.peak=max(self.peak,self.active)
  try:
   for _ in range(3):await asyncio.sleep(0)
   text=reply(self.count);self.count+=1
   return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:neutral]]'+text},'done':True})+'\n')
  finally:self.active-=1
 async def build(self,model=NOVA):
  rig=self
  class Manager(ModelManager):
   async def reply(self,summary,prompt,history,**options):
    card=summary.get('deck_card') or {};trigger=summary.get('trigger_event') or {};op=summary.get('director_opportunity') or {}
    rig.turns.append({'id':rig.starts[-1] if rig.starts else None,'at':rig.at(),'model':self.config.model,'source':summary.get('conversation_source'),'lane':card.get('lane'),'card':card.get('card_id'),
     'trigger':trigger.get('kind') or op.get('intent') or ('legacy_narrative' if summary.get('narrative_initiative') else None),'status':rig.r.observation.status,'session_result':trigger.get('session_result')})
    return await super().reply(summary,prompt,history,**options)
  self.m=Manager(base_url=BASE,transport=httpx.MockTransport(self.transport),store=self.store);await self.m.select(AIConfig(model=model))
  self.d=ObserverDirector(DirectorConfig(regenerate_once=False),clock=self.r.clock.mono)
  self.s=ConversationService(self.r.observation,self.publish,self.m,clock=self.r.clock.mono,director=self.d)
  if self.deck:self.s.deck_definition=fixture_definition()
  self.d.session_status='RUNNING'
 def emit(self,kind,id,before,priority=50,**extra):
  r=self.r;details={'event_id':id,'session_id':r.observation.session_id,'at_ms':int(r.clock.wall()*1000),'sequence':r.observation.sequence,'category':'authoritative','significance':'major','occurrence':transition_occurrence(kind,before,r.state,int(r.clock.wall()*1000))}|extra
  if self.deck:self.s.deck_event(kind,id)
  self.s.enqueue(kind,priority,details);return details
 async def poll(self):
  self.s.pump()
  if self.s.task and not self.s.task.done():await self.s.task
  await asyncio.sleep(0)
 def advance(self,status=None,whole=False):
  r=self.r
  if whole and r.state['status']=='RUNNING':r.state['seconds']+=1
  r.step(85,seconds=TICK,status=status)

async def run_session(root,deck):
 rig=Rig(root,deck);await rig.build();r,s=rig.r,None;s=rig.s
 result=None;preempt=False;preempted=False;user_at=[];blocked=[];signal_at=None;cancelled_at_stop=0
 for tick in range(int(900/TICK)+1):
  second=tick*TICK;whole=second==int(second);second=int(second) if whole else second
  before=deepcopy(r.state)
  status='IDLE' if second>=STOP else 'PAUSED' if 350<=second<365 else 'RUNNING'
  if second==200 or second==320:r.state['edges']+=1
  if second==450:r.state['experience']='headplay'
  if second in {400,430}:r.state['safety'].update(no_contact=second==400,fault='no_contact' if second==400 else 'none')
  if second==STOP:
   result={'active_running_seconds':r.state['seconds'],'last_verified_running_ticks':r.state['seconds'],'edges':r.state['edges'],'experience':r.state['experience'],'goal':r.state['goal'],'termination':'manual_stop','completion_status':'unknown','completion_source':None,'completeness':'final_counter_captured','orgasms':0}
  if second==STOP+1:r.state['seconds']=r.state['edges']=0
  rig.advance(status,whole)
  rig.d.session_status=r.state['status']
  if whole:
   if second==0:rig.emit('session_started','started',before)
   if second==120:preempt=True
   if second==640:s.request('Continue our conversation about a different choice in the atlas story.',True);user_at.append(rig.at());await s.task
   if second==200:rig.emit('edge','edge-1',before)
   if second in {205,260}:
    rig.emit('edge','edge-1',before);rig.emit('edge','edge-1-backfill-'+str(second),before)
   if second==300:rig.emit('milestone','five-minutes',before)
   if second==320:rig.emit('edge','edge-2',before)
   if second==350:s.safety('pause')
   if second==365:rig.emit('session_resumed','resumed',before)
   if second==400:s.safety('no_contact')
   if second==450:rig.emit('experience_changed','mode',before,previous_experience='classic',current_experience='headplay',previous_goal=before['goal'],current_goal=before['goal'])
   if second==500:r.observation.begin_epoch();r.step(85,seconds=0)
   if second==STOP:
    s.safety('stop')
    cancels=sum(f['type']=='speech_cancel' for f in rig.frames)
    signal=lambda kind,id,data:s.enqueue(kind,70,{'event_id':id,'session_id':r.observation.session_id,'at_ms':int(r.clock.wall()*1000),'sequence':r.observation.sequence,'category':'authoritative','evidence':'Session ended.','session_result':data})
    signal('session_ended','session-ended',result);cancelled_at_stop=sum(f['type']=='speech_cancel' for f in rig.frames)-cancels
    signal('session_ended','session-ended',result)
   if second==STOP+2:signal('completion_accepted','late-completion',result|{'edges':999})
  s.pump()
  if s.task and not s.task.done():
   # Adversarial: polls and a user turn arrive while a card is still generating.
   s.pump();s.pump()
   if preempt and s.active_source=='event':
    await asyncio.sleep(0)
    s.request('Imagine a fictional atlas mystery. I choose the garden. Let us consider another route.',True);user_at.append(rig.at());preempt=False;preempted=True
   await s.task
  await asyncio.sleep(0)
 await s.close()
 return rig,result,{'user_at':user_at,'preempted':preempted,'cancelled_at_stop':cancelled_at_stop}

def summarize(rig,result,info,deck):
 turns=rig.turns;delivered={f['id'] for f in rig.speech}
 for turn in turns:turn['delivered']=turn['id'] in delivered
 events=[t for t in turns if t['source']=='event'];done=[t for t in events if t['delivered']]
 lanes=[t['lane'] for t in done];speech=[f for f in rig.speech if f['source']=='event']
 after=[t for t in events if t['at']>=STOP and t['delivered']]
 closings=[t for t in after if t['lane']=='session_end' or t['trigger'] in {'session_ended','completion_accepted'}]
 result_seen=[t['session_result'] for t in closings]
 out={'arm':'on' if deck else 'off','virtual_seconds':900,'stopped_at':STOP,'provider_calls':len(rig.bodies),'maximum_parallel_inference':rig.peak,
  'delivered_unsolicited':len(done),'delivered_by_trigger':dict(Counter(t['trigger'] or t['lane'] for t in done)),
  'first_unsolicited':(done[0]['lane'] or done[0]['trigger']) if done else None,
  'commentary_after_stop':len(after)-len(closings),'closing_reactions':len(closings),'closing_used_final_snapshot':bool(closings) and all(v==result for v in result_seen),
  'closing_seconds_after_stop':round(closings[0]['at']-STOP,2) if closings else None,'obsolete_output_cancelled_at_stop':info['cancelled_at_stop'],
  'speech_while_paused':sum(f['status']=='PAUSED' for f in speech),'speech_during_protective_state':sum(400<=f['at']<430 for f in speech),
  'errors':sum(f['type']=='conversation_error' for f in rig.frames),'thinking_off':all(not b['think'] for b in rig.bodies),'hardware_tools_exposed':any(bool(b.get('tools')) for b in rig.bodies),
  'user_preempted_a_generating_turn':info['preempted'],'repetitive_candidates_suppressed':rig.d.counts['responses_suppressed'],'duplicate_occurrences_suppressed':rig.d.counts['duplicate_occurrences'],
  'turn_log':[{k:t[k] for k in ('at','source','lane','card','trigger','delivered')} for t in turns]}
 out['legacy_idle_turns']=sum(t['lane'] is None and t['trigger'] not in {None,'edge','milestone','session_started','session_resumed','experience_changed','session_ended','completion_accepted'} for t in events)
 out['legacy_reactions_by_kind']=dict(Counter(t['trigger'] for t in done if t['lane'] is None and t['trigger'] in {'edge','milestone','session_started','session_resumed','experience_changed'}))
 if deck:
  missions=Counter(t['card'] for t in done if t['lane']=='mission')
  out['mission_deliveries']=dict(missions);out['duplicate_milestones']=sum(v-1 for v in missions.values())
  edge=next((i for i,t in enumerate(done) if t['card']=='edge-card'),None)
  out['after_edge_order']=[t['lane'] for t in done[edge:edge+3]] if edge is not None else []
  out['after_edge_seconds']=[t['at'] for t in done[edge:edge+3]] if edge is not None else []
  out['opening_deliveries']=lanes.count('session_start');out['normal_deliveries']=lanes.count('normal')
  out.update(cadence(rig,info))
 return out

def cadence(rig,info):
 """Gap from estimated output end to the next normal card, when nothing else could hold it."""
 quiet,held=[],[]
 spoken=[f for f in rig.speech if f['source'] in {'event','user'}]
 for turn in rig.turns:
  if turn['lane']!='normal' or not turn['delivered']:continue  # A preempted card never spoke.
  # Virtual time stands still during inference, so a turn's own speech shares its timestamp.
  prior=[f for f in spoken if f['at']<=turn['at'] and f['id']!=turn['id']]
  if not prior:continue
  gap=round(turn['at']-prior[-1]['output_end'],2)
  users=[u for u in info['user_at'] if u<=turn['at']]
  hold_end=users[-1]+30 if users else float('-inf')
  # Pause, protective state and the safety notice are deliberate blocks, not cadence.
  blocked=any(lo<=prior[-1]['output_end']+10<=hi or lo<=turn['at']<=hi for lo,hi in ((350,366),(400,431),(500,501)))
  (held if blocked or prior[-1]['output_end']+10<hold_end else quiet).append(gap)
 return {'countdown_seconds':10.,'quiet_gaps':quiet,'quiet_gaps_outside_tolerance':[g for g in quiet if not 10<=g<=10.25],'held_gaps':held,
  'normal_within_hold_after_user':sum(1 for t in rig.turns if t['lane']=='normal' and t['delivered'] and any(0<=t['at']-u<30 for u in info['user_at']))}

async def run_isolation(root):
 """Two exact models share one session; dialogue, decks and Story Memory must stay apart."""
 rig=Rig(root,True);await rig.build();r,s=rig.r,rig.s
 async def run(start,end,actions=None):
  for tick in range(int(start/TICK),int(end/TICK)):
   second=tick*TICK;before=deepcopy(r.state)
   if second==100:r.state['edges']+=1
   rig.advance(None,second==int(second))
   if second==60:
    s.request('Imagine a fictional atlas mystery. I choose the garden. Let us consider another route.',True);await s.task
   if second==100:rig.emit('edge','edge-1',before)
   await rig.poll()
 await run(0,200)
 nova_deck=s.deck();nova_scope=s.active_model_id
 memory_after_nova=json.dumps(s.narrative.state,sort_keys=True,default=list)
 nova_history=[m['content'] for m in s.history]
 nova_turns=list(rig.turns)
 delivered={f['id']:f['text'] for f in rig.speech}
 routine=[delivered[t['id']] for t in nova_turns if t['lane'] in {'normal','session_start'} and t['id'] in delivered]
 story=[delivered[t['id']] for t in nova_turns if t['lane']=='narrative' and t['id'] in delivered]
 nova_said=[f['text'] for f in rig.speech]
 calls_before=len(rig.bodies);turns_before=len(rig.turns)
 await rig.m.select(AIConfig(model=EVELYN));s.activate_model()
 history_on_switch=len(s.history);memory_on_switch=json.dumps(s.narrative.state,sort_keys=True,default=list)
 await run(200,320)
 evelyn_deck=s.deck();evelyn_turns=rig.turns[turns_before:]
 evelyn_bodies=rig.bodies[calls_before:]
 text=json.dumps([b['messages'] for b in evelyn_bodies])
 evelyn_said=[f['text'] for f in rig.speech if f['text'] not in nova_said]
 await rig.m.select(AIConfig(model=NOVA));s.activate_model()
 back=[m['content'] for m in s.history]
 memory_back=json.dumps(s.narrative.state,sort_keys=True,default=list)
 result={'distinct_decks':nova_deck is not evelyn_deck and evelyn_deck.scope!=nova_scope,'same_deck_on_return':s.deck() is nova_deck,
  'nova_identity':nova_deck.identity,'evelyn_identity':evelyn_deck.identity,
  'evelyn_turns':sum(t['source']=='event' for t in evelyn_turns),'models_seen_after_switch':sorted({b['model'] for b in evelyn_bodies}),
  'evelyn_saw_nova_cards':sum(t['card']=='only-nova' for t in evelyn_turns),'nova_saw_evelyn_cards':sum(t['card']=='only-evelyn' for t in rig.turns[:turns_before]),
  'nova_dialogue_in_evelyn_prompts':sum(line in text for line in nova_said),
  'history_on_switch':history_on_switch,'nova_history_restored':back==nova_history and bool(back),
  'evelyn_dialogue_in_nova_history':sum(line in ' '.join(back) for line in evelyn_said),
  'nova_story_on_switch':sum(line in memory_on_switch for line in nova_said),
  'routine_cards_in_nova_story_memory':sum(line in memory_after_nova for line in routine),'routine_cards_measured':len(routine),
  'story_cards_delivered':len(story),'story_cards_in_nova_story_memory':sum(line in memory_after_nova for line in story),
  'nova_story_memory_restored':memory_back==memory_after_nova,'maximum_parallel_inference':rig.peak}
 await s.close()
 return result

async def evaluate(arm='both'):
 result={'kind':'real scheduler, deck and compiler at the 250-ms poll; synthetic replies, not prose quality or playback timing'}
 for name in (('off',) if arm=='off' else ('off','on')):
  with tempfile.TemporaryDirectory() as folder:
   deck=name=='on';rig,final,info=await run_session(Path(folder),deck)
   result[name]=summarize(rig,final,info,deck)
 if arm!='off':
  with tempfile.TemporaryDirectory() as folder:result['isolation']=await run_isolation(Path(folder))
 return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--arm',choices=['both','off'],default='both');a=p.parse_args()
 data=asyncio.run(evaluate(a.arm));Path(a.output).write_text(json.dumps(data,indent=2)+'\n')
 print(json.dumps({k:({m:n for m,n in v.items() if m!='turn_log'} if isinstance(v,dict) else v) for k,v in data.items()},indent=1))
