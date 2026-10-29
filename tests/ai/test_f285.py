# SPDX-License-Identifier: AGPL-3.0-only
"""Director-only regression: synthetic observations, no hardware or live inference."""
from pathlib import Path
import asyncio,json
from copy import deepcopy
import httpx,pytest
from fastapi.testclient import TestClient
from ai_observer.server import create_app
from ai_observer.protocol import Messages
from ai_observer.observation import ObserverDirector
from companion_ai.director import ConversationDirector,DirectorConfig,transition_occurrence
from companion_ai.conversation import ConversationService,ModelManager
from companion_ai.models import AIConfig,MemoryConfig
from companion_ai.storage import SettingsStore
from companion_ai.context import compose_messages
from companion_ai.context_compiler import ContextCompiler
from tests.fork.event_replay import Replay
from tests.ai.test_f25 import runtime
from tests.fork.test_observer import TOKEN,ORIGIN,auth,until

TEXTS=['A folded map offers a path through the garden.','The library keeps its unanswered riddle behind a painted screen.','An unexpected connection makes the discovery worth considering.','There is room for a different kind of question about what matters to us.','The promised atlas belongs at the centre of our next decision.','I wonder which unexplored direction you would choose for this conversation.']
class Adapter:
 config=AIConfig(model='nova-narrative-v1:latest');mode='ollama'
 def __init__(self):self.calls=[]
 async def reply(self,summary,prompt,history):
  self.calls.append((summary,prompt,history));return TEXTS[(len(self.calls)-1)%len(TEXTS)]

def rig(adapter=None,**settings):
 r=Replay();r.step(85,seconds=0);frames=[];a=adapter or Adapter()
 d=ObserverDirector(DirectorConfig.model_validate({'experimental_idle_enabled':True,'regenerate_once':False}|settings),clock=r.clock.mono)
 d.session_status=r.observation.status
 s=ConversationService(r.observation,frames.append,a,clock=r.clock.mono,director=d)
 return r,s,a,frames

def tick(r,seconds):
 for _ in range(seconds):r.step(85)

def seed(s):
 text='Imagine a fictional map mystery. I choose the garden. My preferred drink is tea.'
 s.narrative.accepted(text,'I will bring the atlas to our next meeting.',True)
 s.history.append({'role':'user','content':text,'origin':'real_user','narrative_epoch':s.narrative.state['epoch']})
 s.director.user(text)

def event(r,s,kind='edge',id='edge1',**extra):
 details={'event_id':id,'session_id':r.observation.session_id,'at_ms':int(r.clock.wall()*1000),'category':'authoritative',**extra}
 s.enqueue(kind,50,details);return details


def test_stable_identity_outlives_legacy_ttl_and_new_occurrence_is_eligible():
 r,s,_,_=rig();details=event(r,s);s.pending.clear();s.director.mark_event({'kind':'edge',**details},'acknowledged')
 tick(r,120);s.enqueue('edge',50,details)
 assert not s.pending and s.director.counts['duplicate_occurrences']==1
 event(r,s,id='edge2');assert len(s.pending)==1
 assert len(s.director.occurrences)<=1024


def test_transition_alias_and_reconnect_cannot_replay_edge_or_mode():
 r,s,_,_=rig();before=deepcopy(r.state);r.state['edges']+=1;r.step(85)
 occurrence=transition_occurrence('edge',before,r.state)
 event(r,s,occurrence=occurrence);s.pending.clear();r.observation.begin_epoch();r.step(85)
 event(r,s,id='new-envelope',occurrence=occurrence);assert not s.pending
 p=deepcopy(r.state);r.state['experience']='headplay';r.step(85)
 occurrence=transition_occurrence('experience_changed',p,r.state,42)
 event(r,s,'experience_changed','mode1',occurrence=occurrence,previous_experience=p['experience'],current_experience='headplay')
 s.pending.clear();event(r,s,'goal_changed','mode-alias',occurrence=occurrence)
 assert not s.pending and s.director.counts['duplicate_occurrences']==2
 # Returning to the same value later is a new occurrence, not text-equivalent replay.
 later=transition_occurrence('experience_changed',p,r.state,43)
 event(r,s,'experience_changed','later-mode',occurrence=later,previous_experience=p['experience'],current_experience='headplay')
 assert s.pending


async def test_mode_reacts_once_without_second_historical_event_in_prompt():
 wire=[];m=ModelManager(transport=runtime(wire,'[[expression:focused]]A new direction is selected.'))
 await m.select(AIConfig(model='nova-narrative-v1:latest'))
 r,s,_,frames=rig(m,experimental_idle_enabled=False);r.state['experience']='headplay';r.step(85)
 details=event(r,s,'experience_changed','mode1',previous_experience='classic',current_experience='headplay',current_goal='tease',previous_goal='tease')
 tick(r,3);s.pump();await s.task
 assert len(wire)==1 and wire[0][1]['think'] is False
 assert sum(f['type']=='speech' for f in frames)==1
 assert 'mode1' in s.director.acknowledged_ids()
 tick(r,120);s.enqueue('experience_changed',50,details);s.pump()
 assert len(wire)==1 and not s.pending
 assert s.director.occurrences
 s.reset_narrative();s.enqueue('experience_changed',50,details);assert not s.pending
 await s.close()


async def test_idle_without_event_varies_intents_and_respects_topic_cooldown():
 r,s,a,frames=rig(max_consecutive_unsolicited=4);seed(s)
 for _ in range(4):
  tick(r,51);s.pump();assert s.task;await s.task
 intents=list(s.director.memory['initiative_intents']);assert len(intents)==4 and len(set(intents))==4
 assert all('trigger_event' not in summary for summary,_,_ in a.calls)
 assert all(not summary['recent_events'] for summary,_,_ in a.calls)
 keys=list(s.director.memory['initiative_topics']);assert len(keys)==4
 assert all(summary['director_opportunity']['intent'] in intents for summary,_,_ in a.calls)
 assert not any(f['type']=='conversation_error' for f in frames)
 await s.close()


def test_recent_topic_suppresses_only_repeated_opportunity_and_event_does_not_wait_on_idle():
 r,s,_,_=rig();d=s.director;tick(r,51)
 d.memory['initiative_topics']['curiosity']=r.clock.mono()
 assert d.idle_candidate(None,[],r.observation.session_id,'RUNNING',True,False)[1]=='topic_cooldown'
 tick(r,181);op,_=d.idle_candidate(None,[],r.observation.session_id,'RUNNING',True,False);assert op['intent']=='character_curiosity'
 d.idle_dispatched(op);d.dispatched({'kind':'idle_initiative','narrative':True},'idle')
 # Idle is not a physiological/session-event cooldown and cannot starve a new event.
 assert d.opportunity({'kind':'edge','priority':50,'category':'authoritative'})[0]


async def test_direct_user_preempts_idle_and_quiet_is_cross_model_until_explicit_resume():
 gate=asyncio.Event()
 class Slow(Adapter):
  async def reply(self,*args):self.calls.append(args);await gate.wait();return 'A synthetic reply.'
 r,s,a,frames=rig(Slow());seed(s);tick(r,51);s.pump();idle=s.task;await asyncio.sleep(0)
 s.request('Give me a break.',user=True);await idle
 assert s.director.memory['quiet_requested'] and not s.pending
 assert not any(f['type']=='speech' for f in frames)
 tick(r,51);s.pump();assert len(a.calls)==1
 a.config=AIConfig(model='evelyn-narrative-v1:latest');s.activate_model();assert s.director.memory['quiet_requested']
 s.request('What is your name?',True);gate.set();await s.task
 assert s.director.memory['quiet_requested'] # direct chat is permitted, not automatic consent
 s.request('You can talk again.',True);await s.task;assert not s.director.memory['quiet_requested']
 await s.close()


async def test_new_major_event_preempts_idle_but_never_a_direct_user_turn():
 gate=asyncio.Event()
 class Slow(Adapter):
  async def reply(self,*args):self.calls.append(args);await gate.wait();return 'A valid fresh reply.'
 r,s,a,_=rig(Slow());seed(s);tick(r,51);s.pump();idle=s.task;await asyncio.sleep(0)
 event(r,s);await idle;assert idle.done()
 s.request('Answer me directly.',True);user=s.task;await asyncio.sleep(0)
 s.pump();assert s.task is user and s.pending
 gate.set();await user;await s.close()


async def test_stopped_session_drops_queued_and_inflight_initiative_direct_chat_on_pause_works():
 gate=asyncio.Event()
 class Slow(Adapter):
  async def reply(self,*args):await gate.wait();return 'A stale thought must not be displayed.'
 r,s,_,frames=rig(Slow());seed(s);tick(r,51);s.pump();await asyncio.sleep(0)
 r.step(85,status='IDLE');gate.set();await s.task
 assert not any(f['type']=='speech' for f in frames)
 event(r,s,'session_started');s.pump();assert not s.pending
 tick(r,60);s.pump();assert not any(f['type']=='speech' for f in frames)
 r.step(85,status='PAUSED');s.request('Can we still chat?',True);await s.task
 assert any(f['type']=='speech' and f['source']=='user' for f in frames)
 await s.close()


async def test_idle_context_memory_reference_is_source_backed_and_not_telemetry():
 wire=[];m=ModelManager(transport=runtime(wire,'[[expression:neutral]]A connection worth revisiting.'))
 await m.select(AIConfig(model='nova-narrative-v1:latest'))
 r,s,_,_=rig(m);seed(s);n=s.narrative.context();ref=next(f for f in n['facts'] if f['category']=='user_fact' and 'preferred drink' in f['text'])
 op={'intent':'memory_recall','topic_key':'memory:'+ref['id'],'reference_id':ref['id'],'session_id':r.observation.session_id}
 s.request('Director opportunity',False,event={'kind':'idle_initiative','narrative':True,'opportunity':op});await s.task
 payload=wire[-1][1];content=payload['messages'][-1]['content'];assert 'tea' in content and 'DIRECTOR OPPORTUNITY' in content
 assert 'Heart rate [hr]' not in content and 'BLE' not in content and '85 BPM' not in content
 assert ref['id'] in m.context_diagnostics['narrative_recall']['selected_fact_ids']
 assert payload['think'] is False and not payload.get('tools') and payload['options']['num_predict']==m.config.max_tokens
 await s.close()


async def test_memory_disabled_idle_does_not_include_old_fiction_or_other_character():
 wire=[];m=ModelManager(transport=runtime(wire,'[[expression:neutral]]A fresh conversational angle.'))
 await m.select(AIConfig(model='nova-narrative-v1:latest'))
 r,s,_,_=rig(m);seed(s);m.memory=MemoryConfig(enabled=False)
 tick(r,51);s.pump();await s.task
 data=json.dumps(wire[-1]);assert 'garden' not in data and 'atlas' not in data and 'preferred drink' not in data
 assert s.director.memory['initiative_intents'][-1]=='character_curiosity'
 await s.close()


def test_model_scoped_settings_authenticated_strict_and_migrated(tmp_path):
 wire=[];app=create_app(TOKEN,tmp_path,transport=runtime(wire))
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   auth(ws);ws.send_json({'version':1,'type':'configure_director','model':'qwen3:8b','proactive_enabled':True,'experimental_idle_enabled':True,'idle_interval_seconds':50.,'topic_cooldown_seconds':180.})
   saved=until(ws,'character_state');assert saved['director_saved'] and saved['director']['settings']['experimental_idle_enabled']
   assert not wire
   ws.send_json({'version':1,'type':'configure_director','model':'not-selected','proactive_enabled':False})
   assert until(ws,'character_menu_error')
 speech=app.state.speech;speech.adapter.config=AIConfig(model='nova-narrative-v1:latest');speech.activate_model()
 assert not speech.director.config.experimental_idle_enabled
 restored=create_app(TOKEN,tmp_path,transport=runtime(wire));assert restored.state.director.config.experimental_idle_enabled
 assert DirectorConfig.model_validate({'spontaneous_interval_seconds':120.}).idle_interval_seconds==50.
 assert not DirectorConfig().experimental_idle_enabled


@pytest.mark.parametrize('fields',[{'idle_interval_seconds':0},{'reaction_interval_seconds':90},{'topic_cooldown_seconds':-1},{'experimental_idle_enabled':'true'},{'hardware':'start'}])
def test_settings_cannot_add_control_or_invalid_timing(fields):
 with pytest.raises(ValueError):Messages.validate_python({'version':1,'type':'configure_director','proactive_enabled':True,**fields})


async def test_obsolete_selection_is_dropped_before_inference_and_snapshot_has_no_event():
 r,s,a,_=rig(experimental_idle_enabled=False)
 event(r,s,'experience_changed','old-mode',previous_experience='classic',current_experience='headplay')
 tick(r,3);s.pump();assert not s.pending and not a.calls
 # Merely refreshing accepted state does not schedule a new transition.
 tick(r,200);s.pump();assert not a.calls


async def test_measurement_epoch_reconnect_cancels_stale_event_scope():
 gate=asyncio.Event()
 class Late(Adapter):
  async def reply(self,*args):await gate.wait();return 'An obsolete edge acknowledgement.'
 r,s,_,frames=rig(Late(),experimental_idle_enabled=False)
 details=event(r,s,sequence=r.observation.sequence);s.pump();await asyncio.sleep(0)
 r.observation.begin_epoch();r.step(85,seconds=0);gate.set();await s.task
 assert not any(f['type']=='speech' for f in frames)
 await s.close()


async def test_provider_inference_remains_serialized_when_direct_user_interrupts_idle():
 gate=asyncio.Event();first=asyncio.Event();active=0;peak=0;wire=[]
 class Stream(httpx.AsyncByteStream):
  async def __aiter__(self):
   nonlocal active,peak
   active+=1;peak=max(peak,active);first.set()
   try:
    await gate.wait()
    yield (json.dumps({'message':{'content':'[[expression:neutral]]A direct answer.'},'done':True})+'\n').encode()
   finally:active-=1
 async def transport(req):
  if req.url.path=='/api/show':return httpx.Response(200,json={'system':'Fixture identity','capabilities':['completion','thinking']})
  if req.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
  wire.append(json.loads(req.content));return httpx.Response(200,stream=Stream())
 m=ModelManager(transport=httpx.MockTransport(transport));await m.select(AIConfig(model='qwen3:8b'))
 r,s,_,frames=rig(m);seed(s);tick(r,51);s.pump();old=s.task;await asyncio.wait_for(first.wait(),2)
 s.request('Answer this directly.',True);gate.set();await old;await s.task
 assert peak==1 and all(v['think'] is False and not v.get('tools') for v in wire)
 assert sum(f['type']=='speech' and f['source']=='event' for f in frames)==0
 assert sum(f['type']=='speech' and f['source']=='user' for f in frames)==1
 await s.close()


def test_initial_idle_wait_and_bounded_novelty_state():
 r,s,_,_=rig();d=s.director
 assert d.idle_candidate(None,[],r.observation.session_id,'RUNNING',True,False)[1]=='idle_interval'
 for i in range(80):
  d.idle_dispatched({'intent':'character_curiosity','topic_key':'synthetic-'+str(i),'session_id':r.observation.session_id})
 assert len(d.memory['initiative_topics'])==32 and len(d.memory['initiative_intents'])==12


async def test_benchmark_has_no_duplicate_ack_or_hardware_calls_and_varied_idle_intents():
 from tests.fork.director_session_benchmark import run_arm
 result=await run_arm(True)
 assert result['autonomous_messages']>0 and result['duplicate_accepted_event_ids']==0
 assert result['duplicate_events_suppressed']>=9 and result['errors']==0
 assert result['maximum_parallel_inference']==1 and result['thinking_off'] and result['output_budget_unchanged']
 assert not result['hardware_tools_exposed'] and not result['messages_after_stop']
 assert len(set(result['requested_trigger_categories'])&{'narrative_development','dialogue_follow_up','memory_recall','character_curiosity','contextual_observation'})==5


def test_unreadable_model_settings_preserve_file_and_use_defaults(tmp_path):
 path=tmp_path/'director-models.json';path.write_text('{broken')
 app=create_app(TOKEN,tmp_path,transport=runtime([]));s=app.state.speech
 assert s.director_settings_error and not s.director.config.experimental_idle_enabled
 with pytest.raises(ValueError):s.configure_director({'experimental_idle_enabled':True},s.responder()['model'])
 assert path.read_text()=='{broken'


@pytest.mark.parametrize('text',["Let's take a break.",'Please stay quiet.','Can we sit quietly?','I need a break.',"Don't respond until I ask."])
def test_explicit_quiet_requests_are_not_story_keywords(text):
 d=ConversationDirector();d.user(text);assert d.memory['quiet_requested'] and d.last_user_quiet_request
 d.user('A character decides to take a break.');assert not d.last_user_quiet_request
 d.user('Okay, you can talk again.');assert not d.memory['quiet_requested']


@pytest.mark.parametrize('text',['The detective asks us to take a break.', 'Mira said, "Please be quiet."','We could use silence as a clue in our story.'])
def test_fictional_quiet_is_not_an_autonomous_mute_command(text):
 d=ConversationDirector();d.user(text);assert not d.memory['quiet_requested']


@pytest.mark.parametrize('kind',['pause','session_resumed','milestone','rapid_rise','experience_changed'])
def test_event_identity_applies_to_all_meaningful_event_families(kind):
 d=ConversationDirector();payload={'session_id':'synthetic-session','event_id':'first','at_ms':1000}
 assert d.receive(kind,50,payload)
 assert not d.receive(kind,50,payload|{'sequence':999,'received_at_ms':10000})
 assert d.receive(kind,50,payload|{'event_id':'second','at_ms':1100})
 # Safety notices bypass model commentary deduplication and do not await inference.
 assert d.receive('signal_lost',100,payload,origin='safety_event')
 assert d.receive('signal_lost',100,payload,origin='safety_event')


def test_event_focus_excludes_old_history_but_explicit_user_history_remains_answerable():
 r,s,_,_=rig();r.state['experience']='headplay';r.step(85)
 summary=r.observation.summary();sid=r.observation.session_id
 old={'event_id':'old-goal','kind':'goal_changed','evidence':'The earlier goal switched to oracle.','session_id':sid,'sequence':1,'age_seconds':2.0}
 summary['canonical_session']['events']=[old]
 trigger={'kind':'experience_changed','event_id':'new-mode','session_id':sid,'previous_experience':'classic','current_experience':'headplay','evidence':'The selected experience changed to headplay.'}
 auto=summary|{'conversation_source':'event','trigger_event':trigger,'director':{'enabled':True,'acknowledged_event_ids':['old-goal']}}
 messages,_,d=ContextCompiler().compile(auto,'Observed application event',[],AIConfig())
 assert 'earlier goal' not in str(messages) and d['event_ids']==['new-mode']
 user=summary|{'conversation_source':'user','director':{'enabled':True,'acknowledged_event_ids':['old-goal']}}
 messages,_,d=ContextCompiler().compile(user,'Which goal changed earlier?',[],AIConfig())
 assert 'earlier goal' in str(messages) and 'already_acknowledged' in str(messages)


def test_checkpoint_reproduces_id_expiry_and_new_envelope_duplicate_defects():
 import subprocess,sys,types
 name='companion_ai._f285_checkpoint_director'
 module=types.ModuleType(name);module.__package__='companion_ai';sys.modules[name]=module
 source=(Path(__file__).resolve().parents[2]/'tests/fixtures/historical/director_before_occurrence_fix.py').read_text()
 exec(compile(source,'<f285-checkpoint-director>','exec'),module.__dict__)
 r,s,_,_=rig();old=module.ConversationDirector(clock=r.clock.mono);new=s.director
 first={'event_id':'original','session_id':r.observation.session_id,'at_ms':1000,'occurrence':{'family':'edge','counter':3}}
 assert old.receive('edge',50,first) and new.receive('edge',50,first)
 tick(r,91)
 assert old.receive('edge',50,first) and not new.receive('edge',50,first)
 alias=first|{'event_id':'new-envelope'}
 assert old.receive('edge',50,alias) and not new.receive('edge',50,alias)


async def test_idle_does_not_reprime_acknowledged_event_prose_but_user_history_is_intact():
 r,s,a,_=rig();seed(s)
 prose='The old transition invites the SAME-OLD-EVENT-ANGLE.'
 eid='old-selection';epoch=s.narrative.state['epoch']
 s.history.append({'role':'assistant','content':prose,'trigger_origin':'system_event','event_id':eid,'narrative_epoch':epoch})
 s.director.accepted(prose,False,{'kind':'experience_changed','event_id':eid});s.director.memory['event_responses'][-1]['narrative_epoch']=epoch
 s.narrative.state['developments'].append(prose)
 tick(r,51);s.pump();await s.task
 summary,prompt,history=a.calls[-1]
 assert prose not in str(history) and prose not in str(summary.get('narrative_context'))
 assert summary['idle_context_exclusions']['history_rows']>=1
 assert any(row['content']==prose for row in s.history)
 assert prose in s.narrative.state['developments'] # no deletion or storyline rewrite
 s.request('What did you say about that earlier transition?',True);await s.task
 assert prose in str(a.calls[-1][2])
 await s.close()


def test_idle_memory_candidate_uses_existing_significance_not_routine_detours():
 r,s,_,_=rig();s.narrative.accepted('A visitor leaves parcel number 12 on the table. My preferred drink is tea.','Understood.',True)
 tick(r,51);op,reason=s.director.idle_candidate(s.narrative.context(),[],r.observation.session_id,'RUNNING',True,True)
 source=next(f for f in s.narrative.state['facts'] if f['id']==op['reference_id'])
 assert op['intent']=='memory_recall' and 'preferred drink' in source['text']


def test_queued_user_behind_discovery_prevents_idle_scheduling(tmp_path):
 import threading,time
 from tests.fork.test_observer import frame,snapshot
 from tests.fork.grounding_cases import Clock
 entered=threading.Event();release=threading.Event();c=Clock();a=Adapter();a.config=AIConfig()
 async def transport(request):
  assert request.url.path=='/api/tags';entered.set()
  while not release.is_set():await asyncio.sleep(.005)
  return httpx.Response(200,json={'models':[{'name':'qwen3:8b'}]})
 app=create_app(TOKEN,tmp_path,adapter=a,transport=httpx.MockTransport(transport),clock=c.mono)
 app.state.director.config=DirectorConfig(experimental_idle_enabled=True,regenerate_once=False)
 try:
  with TestClient(app) as client:
   with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
    epoch=auth(ws)['epoch'];state=snapshot();state['devices']['toy_ready']=False
    ws.send_json(frame(epoch,state=state));assert until(ws,'observation_ack')['accepted']
    ws.send_json({'version':1,'type':'list_models'});assert entered.wait(1)
    ws.send_json({'version':1,'type':'chat','model':'qwen3:8b','text':'Answer this first.'})
    ws.send_json({'version':1,'type':'get_character_state','model':'qwen3:8b'});until(ws,'character_state')
    c.tick(51);ws.send_json(frame(epoch,1,state));assert until(ws,'observation_ack')['accepted']
    time.sleep(.35)
    assert not a.calls
    assert app.state.director.last_reason=='queued_user_or_model_work'
    release.set();speech=until(ws,'speech');assert speech['source']=='user'
    assert len(a.calls)==1 and a.calls[0][0]['conversation_source']=='user'
 finally:release.set()


def test_idle_source_filter_preserves_established_personal_facts_introduced_with_events():
 r,s,_,_=rig();text='I work as an archivist.';epoch=s.narrative.state['epoch']
 s.narrative.accepted('Observed application event',text,False,event='experience_changed')
 s.director.accepted(text,False,{'kind':'experience_changed','event_id':'old-mode'});s.director.memory['event_responses'][-1]['narrative_epoch']=epoch
 projection={'narrative_context':s.narrative.context()};s.idle_context(projection,[])
 assert any(f['text']==text and f['category']=='character_detail' for f in projection['narrative_context']['facts'])


async def test_validated_lifecycle_precedes_ordinary_events_without_general_cooldown_delay():
 r,s,a,_=rig(experimental_idle_enabled=False)
 s.last_event=s.director.last_spoken=s.director.last_event_dispatch=r.clock.mono()
 s.director.last_category['session']=r.clock.mono()
 event(r,s,'edge','earlier-edge');tick(r,1);event(r,s,'session_resumed','resume')
 s.pump();await s.task
 assert a.calls[-1][0]['trigger_event']['kind']=='session_resumed'
 assert any(row['kind']=='edge' for row in s.pending)
 await s.close()
