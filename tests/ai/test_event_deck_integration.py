# SPDX-License-Identifier: AGPL-3.0-only
"""Phase 1B: the deck behind pump(). Virtual time, mocked inference, no hardware."""
import asyncio,json,re,time
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from ai_observer.observation import ObserverDirector
from ai_observer.server import create_app
from companion_ai.conversation import ConversationService,ModelManager
from companion_ai.director import DirectorConfig
from companion_ai.event_deck import Card,DeckDefinition,DeckSettings,Eligibility,Sequence,SequenceTrigger,load_definition,scope_key
from companion_ai.event_intelligence import EventConfig
from companion_ai.grounding import SessionFacts
from companion_ai.models import AIConfig
from companion_ai.storage import SettingsStore
from tests.ai.test_f25 import runtime
from tests.fork.event_replay import Replay
from tests.fork.grounding_cases import Clock,snapshot as detailed_snapshot
from tests.fork.test_observer import TOKEN,ORIGIN,auth,frame,snapshot,until

MODEL='nova-narrative-v1:latest'
RESULT={'active_running_seconds':600,'last_verified_running_ticks':600,'edges':4,'experience':'classic','goal':'tease','termination':'manual_stop','completion_status':'unknown','completion_source':None,'completeness':'final_counter_captured'}
TEXTS=['A folded map offers a path through the garden.','The library keeps its riddle behind a painted screen.','An unexpected connection makes the discovery worth considering.','There is room for a different question about what matters.','The promised atlas belongs at the centre of the next decision.','I wonder which unexplored direction you would choose.','Copper kettles sing differently on rainy mornings.','Old lighthouses keep better secrets than most archives.','Nobody warned me that orchids hold grudges this long.','A careful experiment can still surprise its author.','Winter markets smell of cloves and unfinished plans.','Every good notebook hides one page it regrets.']

def card(id,kind='normal',**values):return Card(id=id,kind=kind,intent=values.pop('intent','comment'),brief='Brief '+id,**values)
def mission(id='m1',**trigger):return Sequence(id=id,lane='mission',trigger=SequenceTrigger(**(trigger or {'event_kinds':['edge']})),steps=[card(id+'-a','mission')])
def story(id='s1'):return Sequence(id=id,lane='narrative',trigger=SequenceTrigger(event_kinds=['edge']),steps=[card(id+'-a','narrative',memory='story')])
def definition(sequences=()):
 return DeckDefinition(session_start=[card('start','session_start')],session_end=[card('end','session_end')],normal=[card(f'n{i}') for i in range(4)],sequences=list(sequences))

class Adapter:
 mode='ollama'
 def __init__(self,texts=None):
  self.config=AIConfig(model=MODEL);self.calls=[];self.texts=texts;self.active=0;self.peak=0
 async def reply(self,summary,prompt,history):
  self.calls.append((summary,prompt,history));self.active+=1;self.peak=max(self.peak,self.active)
  await asyncio.sleep(0);self.active-=1
  source=self.texts if self.texts is not None else TEXTS
  return source[(len(self.calls)-1)%len(source)]

def rig(sequences=(),deck=True,adapter=None,**settings):
 r=Replay();r.state['devices'].update(toy_ready=True,handy=True);r.state['safety']['fault']='none';r.step(85,seconds=0)
 frames=[];a=adapter or Adapter()
 d=ObserverDirector(DirectorConfig(regenerate_once=False),clock=r.clock.mono);d.session_status=r.observation.status
 s=ConversationService(r.observation,frames.append,a,clock=r.clock.mono,director=d)
 if deck:
  s.deck_settings=DeckSettings(enabled=True,**settings);s.deck_definition=definition(sequences)
 return r,s,a,frames

def tick(r,seconds):
 for _ in range(int(seconds)):r.step(85)

def advance(r,seconds):
 """Exact fractional time, with the observations production would have received."""
 whole=int(seconds)
 tick(r,whole)
 if seconds-whole>0:r.step(85,seconds=seconds-whole)

def poll_until_turn(r,s,limit=400):
 """maintenance() cadence: returns once a new turn has started; never loops unbounded."""
 for _ in range(limit):
  advance(r,.25);s.pump()
  if s.task and not s.task.done():return
 pytest.fail('No turn started: '+str(s.director.last_reason))

async def turn(s):
 s.pump();task=s.task;assert task
 await task
 return s.adapter.calls[-1][0]

async def settle(r,s):
 """Let the estimated output time and the countdown pass."""
 tick(r,max(0,s.busy_until-r.clock.mono())+s.deck_settings.countdown_seconds+1)

def speeches(frames):return [f for f in frames if f['type']=='speech']
def lanes(a):return [c[0].get('deck_card',{}).get('lane') for c in a.calls]
def finish(r,s,kind='session_ended'):
 r.step(85,status='IDLE')
 s.enqueue(kind,70,{'event_id':'end:'+r.observation.session_id,'session_id':r.observation.session_id,'category':'authoritative','at_ms':int(r.clock.wall()*1000),'session_result':RESULT,'evidence':'Session ended.'})


# Flag off: no proactive scheduler. Conversation continues; nothing is unsolicited.

@pytest.mark.usefixtures('deck_off')
async def test_disabled_deck_means_no_unsolicited_dialogue_but_conversation_continues():
 r,s,a,frames=rig(deck=False)
 assert s.deck() is None and DeckSettings().enabled is False
 tick(r,40);s.pump();assert s.task is None and not a.calls
 assert s.request('Are you there?',user=True)['accepted'];await s.task
 assert 'deck_card' not in a.calls[0][0] and 'event_deck' not in s.character_state() and speeches(frames)[-1]['source']=='user'

async def test_disabled_deck_records_session_start_as_context_only_and_keeps_the_floor():
 r,s,a,_=rig(deck=False)
 s.enqueue('session_started',50,{'event_id':'e1','session_id':r.observation.session_id})
 assert s.pending==[] and s.recent_events[-1]['kind']=='session_started'
 s.pending.clear();s.last_event=r.clock.mono()
 assert s.request('Legacy turn',user=False,event={'kind':'idle_initiative','priority':0,'at':0,'narrative':True})=={'accepted':False,'reason':'frequency_policy'}

@pytest.mark.usefixtures('deck_off')
def test_disabled_deck_never_reads_the_definition_file(monkeypatch):
 r,s,_,_=rig(deck=False)
 monkeypatch.setattr('companion_ai.conversation.load_definition',lambda raw:pytest.fail('definition read while disabled'))
 assert s.deck() is None
 s.deck_event('edge','occ')

@pytest.mark.usefixtures('deck_off')
async def test_disabled_deck_finish_is_recorded_but_not_spoken():
 r,s,a,_=rig(deck=False);finish(r,s);s.pump()
 assert s.pending==[] and s.task is None and not a.calls
 assert s.recent_events[-1]['kind']=='session_ended' and 'session_result' not in s.recent_events[-1]


# Flag on: scheduling

async def test_opening_plays_first_without_a_countdown_then_normal_cards_replace_idle():
 r,s,a,frames=rig()
 first=await turn(s)
 assert first['deck_card']['lane']=='session_start'
 for _ in range(3):
  await settle(r,s);await turn(s)
 assert lanes(a)==['session_start','normal','normal','normal']
 assert not any(c[0].get('director_opportunity',{}).get('topic_key','card:').split(':')[0]!='card' for c in a.calls)
 assert s.active_event_kind=='deck_card'
 assert len(speeches(frames))==4

async def test_countdown_runs_from_estimated_output_end_with_no_45_second_floor():
 r,s,a,_=rig(countdown_seconds=10)
 await turn(s);end=s.busy_until
 tick(r,end-r.clock.mono()+9);s.pump();assert len(a.calls)==1
 assert s.director.last_reason=='deck:countdown'
 tick(r,2);s.pump();await s.task
 assert len(a.calls)==2 and r.clock.mono()-end<45

async def test_only_card_requests_are_exempt_from_the_floor():
 r,s,a,_=rig()
 await turn(s);await asyncio.sleep(0)
 s.last_event=r.clock.mono();s.busy_until=0
 assert s.request('Other unsolicited turn',user=False,event={'kind':'idle_initiative','priority':0,'at':0,'narrative':True})['reason']=='frequency_policy'

async def test_card_turns_do_not_reset_the_floor_or_starve_event_reactions():
 r,s,a,_=rig();before=s.last_event
 await turn(s)
 assert s.last_event==before

async def test_one_inference_at_a_time_and_output_must_be_free():
 r,s,a,_=rig()
 s.pump();task=s.task
 s.pump();s.pump()
 assert s.task is task
 await task
 assert a.peak==1 and len(a.calls)==1
 s.pump();assert len(a.calls)==1 and s.director.last_reason=='deck:output_busy'

async def test_card_prompt_is_labelled_and_compiled_as_scheduling_data_with_no_tools():
 r=Replay();r.state['devices'].update(toy_ready=True,handy=True);r.state['safety']['fault']='none';r.step(85,seconds=0)
 wire=[];m=ModelManager(transport=runtime(wire,'[[expression:focused]]Rain has its own rhythm.'));await m.select(AIConfig(model=MODEL));m.current_summary=r.observation.summary
 d=ObserverDirector(DirectorConfig(regenerate_once=False),clock=r.clock.mono);frames=[]
 s=ConversationService(r.observation,frames.append,m,clock=r.clock.mono,director=d)
 s.deck_settings=DeckSettings(enabled=True);s.deck_definition=definition()
 s.pump();await s.task
 body=next(b for path,b in reversed(wire) if path=='/api/chat');system,last=body['messages'][0]['content'],body['messages'][-1]
 assert 'Brief start' in last['content'] and last['content'].count('Brief start')==1 and 'This is not a message from them' in last['content']
 assert not re.search(r'DIRECTOR OPPORTUNITY|APPLICATION EVENT|PRIMARY FOCUS|play_id|card_id|"lane"',last['content'])
 assert last['role']=='user' and '{' not in last['content']
 assert 'CURRENT SESSION' in system and body['think'] is False and not body.get('tools')
 assert speeches(frames)[0]['text']=='Rain has its own rhythm.'

async def test_shipped_definition_validates_and_loads_when_enabled():
 raw=json.loads((Path(__file__).resolve().parents[2]/'config/event-deck.json').read_text())
 loaded,error=load_definition(raw);assert error is None and loaded.normal
 assert all(c.memory=='none' for c in loaded.normal)
 r,s,a,_=rig();s.deck_definition=None
 assert s.deck() is not None and (await turn(s))['deck_card']['card_id']=='opening'


# Priority

async def test_mission_outranks_narrative_and_normal_and_skips_the_countdown():
 r,s,a,_=rig(sequences=[story(),mission()])
 await turn(s)
 s.narrative.state['initiative_allowed']=True
 tick(r,s.busy_until-r.clock.mono()+1)
 s.deck_event('edge','occ-1')
 assert (await turn(s))['deck_card']['lane']=='mission'
 tick(r,s.busy_until-r.clock.mono()+5)
 assert (await turn(s))['deck_card']['lane']=='narrative'

async def test_triggered_card_waits_for_output_and_user_then_restarts_the_countdown():
 r,s,a,_=rig(sequences=[mission()],countdown_seconds=10)
 await turn(s)
 s.deck_event('edge','occ-1')
 s.pump();assert len(a.calls)==1 and s.director.last_reason=='deck:output_busy'
 tick(r,s.busy_until-r.clock.mono()+1)
 s.director.typing_until=r.clock.mono()+5
 s.pump();assert len(a.calls)==1 and s.director.last_reason=='deck:user_active'
 s.director.typing_until=0
 assert (await turn(s))['deck_card']['lane']=='mission'
 tick(r,s.busy_until-r.clock.mono()+9);s.pump();assert len(a.calls)==2 and s.director.last_reason=='deck:countdown'

async def test_user_turn_preempts_a_card_and_the_card_is_not_consumed():
 r,s,a,_=rig()
 await turn(s);await settle(r,s)
 s.pump();task=s.task;assert s.active_event_kind=='deck_card'
 played=s.deck().snapshot()['played']
 s.request('A direct question.',user=True);user_task=s.task
 await asyncio.gather(task,user_task,return_exceptions=True)
 await asyncio.sleep(0)
 assert s.deck().snapshot()['played']==played and s.deck().snapshot()['counts']['cancelled']==1


# Closing

async def test_closing_cancels_pending_commentary_and_is_the_first_new_reaction():
 r,s,a,frames=rig(sequences=[mission()])
 await turn(s)
 s.deck_event('edge','occ-1')
 s.enqueue('edge',50,{'event_id':'e1','session_id':r.observation.session_id,'at_ms':int(r.clock.wall()*1000),'category':'authoritative'})
 tick(r,s.busy_until-r.clock.mono()+1);finish(r,s)
 assert s.pending==[] and s.deck().snapshot()['active_sequences']==[]
 summary=await turn(s)
 assert summary['deck_card']['lane']=='session_end' and summary['trigger_event']['session_result']==RESULT
 s.pump();assert len(a.calls)==2 and s.director.last_reason=='deck:session_closed'

async def test_closing_cancels_a_card_already_generating():
 r,s,a,_=rig()
 await turn(s);await settle(r,s)
 s.pump();task=s.task;play_kind=s.active_event_kind;assert play_kind=='deck_card'
 finish(r,s)
 await asyncio.gather(task,return_exceptions=True);await asyncio.sleep(0)
 assert s.deck().snapshot()['played']==0
 tick(r,3);await turn(s)
 assert lanes(a)[-1]=='session_end'

async def test_repeated_completion_signals_produce_one_closing():
 r,s,a,frames=rig()
 await turn(s);tick(r,s.busy_until-r.clock.mono()+1)
 finish(r,s)
 details={'event_id':'other','session_id':r.observation.session_id,'session_result':RESULT|{'edges':99}}
 s.enqueue('session_ended',70,details);s.enqueue('completion_accepted',70,details)
 summary=await turn(s);assert summary['trigger_event']['session_result']['edges']==4
 s.enqueue('session_ended',70,details)
 for _ in range(5):
  tick(r,40);s.pump()
 assert s.task.done() and lanes(a).count('session_end')==1 and len(speeches(frames))==2

async def test_closing_never_overlaps_output_or_a_safety_notice():
 r,s,a,frames=rig()
 await turn(s)
 s.busy_until=r.clock.mono()+20;s.busy_from_user=True
 finish(r,s)
 s.pump();assert len(a.calls)==1 and s.director.last_reason=='deck:output_busy'
 s.busy_until=0;s.safety('stop')
 assert speeches(frames)[-1]['source']=='safety'
 s.pump();assert len(a.calls)==1 and s.director.last_reason=='deck:output_busy'
 tick(r,3);await turn(s)
 assert lanes(a)[-1]=='session_end' and speeches(frames)[-1]['interrupt'] is False

async def test_closing_gets_no_journal_and_does_not_touch_story_memory():
 r,s,a,_=rig()
 await turn(s);tick(r,s.busy_until-r.clock.mono()+1)
 before=json.dumps(s.narrative.state['facts']),list(s.narrative.state['developments'])
 finish(r,s);summary=await turn(s)
 assert 'journal_context' not in summary and 'journal_lookup' not in summary and 'nova_aggregate' not in summary
 assert (json.dumps(s.narrative.state['facts']),s.narrative.state['developments'])==before

async def test_a_failing_closing_stops_after_its_bounded_retries_and_the_drop_is_recorded():
 class Failing(Adapter):
  async def reply(self,*args):
   self.calls.append(args);raise ValueError('inference down')
 r,s,a,frames=rig(adapter=Failing())
 s.deck().next_play(s.deck_context(r.clock.mono()),r.clock.mono())
 s.deck()._active=None;s.deck()._start_done=True
 finish(r,s);await turn(s);await asyncio.sleep(0)
 assert len(a.calls)==1 and s.deck().closing_pending
 for _ in range(3):
  tick(r,10);r.step(85,status='IDLE');s.pump()
  if s.task and not s.task.done():await turn(s);await asyncio.sleep(0)
 assert len(a.calls)==2 and not s.deck().closing_pending and s.deck().closing_outcome=='failed'
 assert [d['outcome'] for d in s.director.decisions if d['reason']=='deck_closing_dropped']==['failed']


# Lifecycle through the real harness

async def test_silence_does_not_consume_and_the_deck_moves_on():
 r,s,a,_=rig(adapter=Adapter(['[SILENCE]']))
 await turn(s);await asyncio.sleep(0)
 deck=s.deck();assert deck.snapshot()['counts']['suppressed']==1 and deck.snapshot()['start_done'] is False
 tick(r,3);await turn(s);await asyncio.sleep(0)
 assert deck.snapshot()['start_outcome']=='attempts_exhausted'
 tick(r,3);assert (await turn(s))['deck_card']['lane']=='normal'

async def test_generation_failure_is_recorded_as_failed():
 class Failing(Adapter):
  async def reply(self,*args):
   self.calls.append(args);raise ValueError('inference down')
 r,s,a,frames=rig(adapter=Failing())
 await turn(s);await asyncio.sleep(0)
 assert s.deck().snapshot()['counts']['failed']==1 and s.deck_open=={}

async def test_refused_request_is_deferred_not_consumed():
 r,s,a,_=rig();s.policy=s.policy.model_copy(update={'event_responses':True});s.closed=False
 s.request=lambda *args,**kwargs:{'accepted':False,'reason':'busy'}
 s.pump()
 assert s.deck().snapshot()['counts']['deferred']==1 and s.deck().snapshot()['start_done'] is False

async def test_task_cancelled_before_its_first_step_still_settles():
 r,s,a,_=rig()
 s.pump();s.task.cancel()
 await asyncio.gather(s.task,return_exceptions=True);await asyncio.sleep(0)
 assert not a.calls and s.deck().snapshot()['counts']['cancelled']==1 and s.deck_open=={}

async def test_publication_is_delivery_and_generated_alone_is_not():
 seen=[];r,s,a,_=rig()
 original=s.publish
 def publish(message):
  if message['type']=='response_delta':seen.append(s.deck().snapshot()['counts'].get('generated',0),)
  if message['type']=='speech':seen.append(s.deck().snapshot()['counts'].get('delivered',0))
  original(message)
 s.publish=publish
 await turn(s);await asyncio.sleep(0)
 assert seen==[1,0] and s.deck().snapshot()['counts']['delivered']==1


# Unsolicited limit

async def test_limit_holds_normal_cards_but_not_opening_or_missions_which_do_not_count():
 r,s,a,_=rig(sequences=[mission()],mission_spacing_seconds=0)
 s.director.config=s.director.config.model_copy(update={'unlimited_unsolicited':False,'max_consecutive_unsolicited':1})
 assert (await turn(s))['deck_card']['lane']=='session_start'
 assert s.director.memory['consecutive_unsolicited']==0
 await settle(r,s)
 assert (await turn(s))['deck_card']['lane']=='normal'
 assert s.director.memory['consecutive_unsolicited']==1
 await settle(r,s);s.pump();assert len(a.calls)==2 and s.director.last_reason=='deck:unsolicited_limit'
 s.deck_event('edge','occ-1')
 assert (await turn(s))['deck_card']['lane']=='mission'
 assert s.director.memory['consecutive_unsolicited']==1


async def test_unlimited_ignores_the_cap_and_is_the_default():
 r,s,a,_=rig()
 assert s.director.config.unlimited_unsolicited
 s.director.config=s.director.config.model_copy(update={'max_consecutive_unsolicited':1})
 assert (await turn(s))['deck_card']['lane']=='session_start'
 await settle(r,s)
 for count in (1,2,3):
  assert (await turn(s))['deck_card']['lane']=='normal'
  assert s.director.memory['consecutive_unsolicited']==count
  await settle(r,s)


# Controls

async def test_proactive_off_suppresses_cards_but_keeps_a_user_ended_closing():
 r,s,a,frames=rig(sequences=[mission()])
 s.director.config=s.director.config.model_copy(update={'spontaneous_enabled':False})
 s.deck_event('edge','occ-1');s.pump();assert not a.calls
 finish(r,s);summary=await turn(s)
 assert summary['deck_card']['lane']=='session_end' and speeches(frames)

async def test_quiet_blocks_cards_and_the_closing():
 r,s,a,_=rig()
 s.director.memory['quiet_requested']=True
 s.pump();assert not a.calls and s.director.last_reason=='deck:user_requested_quiet'
 finish(r,s);s.pump();assert not a.calls

async def test_event_intelligence_off_keeps_normal_draws_and_counter_missions_only():
 r,s,a,_=rig(sequences=[mission('event-m'),mission('counter-m',min_edges=1),story()])
 s.deck()._counter_baseline={'edges':0,'seconds':0}
 s.event_intelligence.configure(EventConfig(enabled=False))
 s.deck_event('edge','occ-1')
 assert (await turn(s))['deck_card']['lane']=='session_start'
 tick(r,s.busy_until-r.clock.mono()+1)
 summary=await turn(s);assert summary['deck_card']['card_id']=='counter-m-a'
 await settle(r,s);assert (await turn(s))['deck_card']['lane']=='normal'
 assert s.deck().snapshot()['active_sequences']==[]

@pytest.mark.parametrize('safety,reason',[({'no_contact':True,'fault':'no_contact'},'protective_state'),({'watchdog_paused':True},'protective_state'),({'signal':'stale','fault':'signal_lost'},'protective_state'),({'signal':'stale'},'signal_unavailable'),({'signal':'holding'},'signal_unavailable'),({'fault':'device_unready'},'device_disconnected')])
async def test_safety_states_block_every_card(safety,reason):
 r,s,a,_=rig(sequences=[mission()])
 s.deck().next_play(s.deck_context(r.clock.mono()),r.clock.mono());s.deck()._active=None
 r.state['safety'].update(safety);r.step(85)
 s.deck_event('edge','occ-1');s.pump()
 assert not a.calls and reason in s.director.last_reason

async def test_session_without_sensor_gets_cards_and_a_lost_sensor_stops_them():
 r,s,a,_=rig()
 r.step(source='unavailable')
 assert (await turn(s))['deck_card']['lane']=='session_start'
 r2,s2,a2,_=rig()
 await turn(s2);tick(r2,20)
 r2.step(source='unavailable');s2.pump()
 assert len(a2.calls)==1 and s2.director.last_reason=='deck:sensor_disconnected'

async def test_paused_session_gets_no_cards():
 r,s,a,_=rig();r.step(85,status='PAUSED');s.pump()
 assert not a.calls and s.director.last_reason=='deck:session_inactive'


# Memory and isolation

async def test_routine_card_reaches_the_transcript_but_never_story_memory():
 r,s,a,_=rig()
 await turn(s)
 assert s.history[-1]['content']==TEXTS[0] and s.history[-1]['origin']=='assistant_dialogue'
 assert s.narrative.state['facts']==[] and s.narrative.state['developments']==[] and s.narrative.state['event_references']==[]

async def test_narrative_card_does_progress_story_memory():
 r,s,a,_=rig(sequences=[story()])
 await turn(s);s.narrative.state['initiative_allowed']=True;tick(r,s.busy_until-r.clock.mono()+1)
 s.deck_event('edge','occ-1')
 summary=await turn(s);assert summary['deck_card']['memory']=='story'
 assert s.narrative.state['developments'] and all(f['model_scope']==s.active_model_id for f in s.narrative.state['facts'])

@pytest.mark.usefixtures('deck_off')
async def test_decks_and_transcripts_are_isolated_by_exact_model():
 r,s,a,_=rig()
 await turn(s);first=s.deck();scope=s.active_model_id
 a.config=AIConfig(model='evelyn-narrative-v1:latest');s.activate_model()
 s.deck_settings=DeckSettings(enabled=True);s.deck_identity='evelyn'
 second=s.deck();assert second is not first and second.scope!=scope
 assert second.snapshot()['start_done'] is False and first.snapshot()['start_done'] is True
 assert not s.history
 a.config=AIConfig(model=MODEL);s.activate_model();s.deck_settings=DeckSettings(enabled=True);s.deck_identity='generic'
 assert s.deck() is first and len(s.history)==1

async def test_character_cards_only_reach_their_own_companion():
 custom=definition();custom=custom.model_copy(update={'normal':[card('evelyn-only',audience='evelyn')]})
 r,s,a,_=rig();s.deck_definition=custom;s.deck_identity='nova'
 await turn(s);await settle(r,s)
 s.pump();assert len(a.calls)==1 and s.director.last_reason=='deck:deck_exhausted'


# Settings file

def enable(root,scope,**values):
 SettingsStore(root).write('deck-settings.json',{'schema_version':1,'models':{scope_key(scope):{'enabled':True}|values}})

class Stored(Adapter):
 def __init__(self,root):
  super().__init__();self.store=SettingsStore(root)

def stored_service(root):
 clock=Replay().clock;a=Stored(root);r=Replay()
 return ConversationService(r.observation,lambda m:None,a,clock=r.clock.mono,director=ObserverDirector(DirectorConfig(),clock=r.clock.mono)),a

def test_settings_file_defaults_are_on_and_scope_is_exact(tmp_path):
 s,a=stored_service(tmp_path);nova=s.active_model_id
 assert s.deck_settings==DeckSettings() and s.deck_settings.enabled and not (tmp_path/'deck-settings.json').exists()
 enable(tmp_path,nova,enabled=False)
 s2,_=stored_service(tmp_path);assert not s2.deck_settings.enabled
 a.config=AIConfig(model='evelyn-narrative-v1:latest');s.activate_model();assert s.deck_settings.enabled  # off for Nova only
 enable(tmp_path,nova,countdown_seconds=25)
 s3,_=stored_service(tmp_path);assert s3.deck_settings.enabled and s3.deck_settings.countdown_seconds==25 and s3.deck_identity=='nova'

def test_corrupt_settings_fail_closed_and_are_preserved(tmp_path):
 path=tmp_path/'deck-settings.json';path.write_text('{not json');s,_=stored_service(tmp_path)
 assert not s.deck_settings.enabled and s.deck_error and path.read_text()=='{not json'
 assert s.character_state()['event_deck_fault']['unsolicited_commentary']=='disabled'
 s.pump();assert s.task is None and s.director.last_reason=='deck_fault'
 enable(tmp_path,s.active_model_id)
 restarted,_=stored_service(tmp_path);assert restarted.deck_error is None and restarted.deck_settings.enabled

def test_saved_director_settings_are_untouched_and_gain_no_deck_fields(tmp_path):
 SettingsStore(tmp_path).write('director.json',{'experimental_idle_enabled':False,'idle_interval_seconds':75.})
 before=(tmp_path/'director.json').read_bytes()
 app=create_app(TOKEN,tmp_path)
 assert (tmp_path/'director.json').read_bytes()==before
 assert not {k for k in DirectorConfig.model_fields if 'deck' in k} and app.state.speech.deck() is None


# Through the real observer

class Served(Stored):
 def __init__(self,root):
  super().__init__(root);self.config=AIConfig(model=MODEL)

def wait_for_lane(ws,speech,lane,limit=200):
 for _ in range(limit):
  message=ws.receive_json()
  if message['type']=='conversation_error':pytest.fail(str(message))
  if message['type']=='speech' and message.get('source')=='event':return message
 pytest.fail('No card speech for '+lane)

def test_enabled_observer_plays_the_opening_from_a_real_observation(tmp_path):
 a=Served(tmp_path)
 enable(tmp_path,'ollama:local:'+MODEL)
 app=create_app(TOKEN,tmp_path,adapter=a)
 speech=app.state.speech;assert speech.deck_settings.enabled
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   epoch=auth(ws)['epoch'];state=snapshot()
   ws.send_json(frame(epoch,state=state));assert until(ws,'observation_ack')['accepted']
   assert wait_for_lane(ws,speech,'session_start')['text']==TEXTS[0]
 assert a.calls[0][0]['deck_card']['card_id']=='opening'

@pytest.mark.usefixtures('deck_off')
def test_observer_with_no_settings_file_never_creates_a_deck(tmp_path):
 a=Served(tmp_path);app=create_app(TOKEN,tmp_path,adapter=a)
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   epoch=auth(ws)['epoch'];ws.send_json(frame(epoch,state=snapshot()));assert until(ws,'observation_ack')['accepted']
 assert app.state.speech.deck() is None and not (tmp_path/'deck-settings.json').exists()
 assert all('deck_card' not in c[0] for c in a.calls)

def send(ws,epoch,sequence,state,kind=None):
 events=[{'id':str(uuid4()),'kind':kind,'session_id':state['session_id'],'at_ms':state['details']['captured_at_ms']}] if kind else []
 state['details']['captured_at_ms']=int(time.time()*1000)
 ws.send_json(frame(epoch,sequence,state,events));assert until(ws,'observation_ack')['accepted']

def running_state(seconds=321):
 state=detailed_snapshot(Clock());state.update(status='RUNNING',seconds=seconds,edges=7,experience='headplay',goal='tease',active_mode='headplay')
 state['details'].update(hr_recorded_at_ms=None,warmup_active=False,captured_at_ms=int(time.time()*1000))
 state['hr']=None;state['devices'].update(hr_ready=False,simulated_hr=False,toy_ready=True,handy=True);state['safety']['fault']='none'
 return state

def wait_calls(a,count,seconds=5):
 end=time.monotonic()+seconds
 while len(a.calls)<count and time.monotonic()<end:time.sleep(.02)

def test_real_stop_produces_the_authoritative_closing_after_the_safety_notice(tmp_path):
 a=Served(tmp_path);enable(tmp_path,'ollama:local:'+MODEL);app=create_app(TOKEN,tmp_path,adapter=a);speech=app.state.speech
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   epoch=auth(ws)['epoch'];state=running_state()
   speech.last_event=speech.clock();speech.director.last_spoken=speech.clock()
   send(ws,epoch,0,state)
   state['status']='IDLE';state['details']['terminal_outcome']='manual_stop'
   send(ws,epoch,1,state,'stop')
   wait_calls(a,1)
   state['seconds']=state['edges']=0;send(ws,epoch,2,state,'stop');time.sleep(.35)
 closings=[c[0] for c in a.calls if c[0].get('deck_card',{}).get('lane')=='session_end']
 assert len(closings)==1 and len(a.calls)==1
 result=closings[0]['trigger_event']['session_result']
 assert result['edges']==7 and result['active_running_seconds']==321 and result['termination']=='manual_stop'

def test_real_safety_stop_produces_no_closing(tmp_path):
 a=Served(tmp_path);enable(tmp_path,'ollama:local:'+MODEL);app=create_app(TOKEN,tmp_path,adapter=a)
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   epoch=auth(ws)['epoch'];state=running_state()
   send(ws,epoch,0,state)
   state['status']='IDLE';state['details']['terminal_outcome']='safety_stop'
   send(ws,epoch,1,state,'stop');time.sleep(2.6)
 assert not [c for c in a.calls if c[0].get('deck_card',{}).get('lane')=='session_end']

def test_real_edge_event_reaches_the_deck_through_the_observer(tmp_path):
 a=Served(tmp_path);enable(tmp_path,'ollama:local:'+MODEL);app=create_app(TOKEN,tmp_path,adapter=a);speech=app.state.speech
 speech.deck_definition=definition([mission()])
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   epoch=auth(ws)['epoch'];state=running_state()
   send(ws,epoch,0,state)
   time.sleep(.12);state['edges']+=1;send(ws,epoch,1,state,'edge')  # Non-urgent frames are rate limited.
   wait_calls(a,1)
 assert a.calls[0][0]['deck_card']['card_id']=='m1-a'


# Faults stay inside the deck

def broken(*args,**kwargs):raise RuntimeError('deck bug')

async def test_a_deck_fault_in_pump_stops_unsolicited_dialogue_without_legacy_fallback():
 r,s,a,frames=rig();deck=s.deck();deck.next_play=broken
 s.pump()
 assert s.deck() is None and 'RuntimeError' in s.deck_error
 status=s.character_state()['event_deck_fault']
 assert status=={'error':s.deck_error,'unsolicited_commentary':'disabled','user_conversation':'available'}
 assert [f for f in frames if f.get('director_decision')=='deck_fault'][0]['event_deck_fault']==status
 for _ in range(8):
  tick(r,40);s.pump()
 assert not a.calls and s.director.last_reason=='deck_fault' and s.task is None

async def test_a_deck_fault_during_closing_does_not_escape():
 r,s,a,_=rig();await turn(s);tick(r,s.busy_until-r.clock.mono()+1);finish(r,s)
 s.deck().next_play=broken
 s.pump()
 assert s.deck_error and len(a.calls)==1

def test_a_deck_fault_on_a_verified_event_or_ending_does_not_escape():
 r,s,_,_=rig();s.deck().verified_event=broken
 s.deck_event('edge','occ-1')
 assert s.deck_error
 r,s,_,_=rig();s.deck().finish_session=broken;finish(r,s)
 assert s.deck_error and s.pending==[]

def test_a_changed_identity_fails_closed_instead_of_raising():
 r,s,_,_=rig();assert s.deck()
 s.deck_identity='evelyn'
 assert s.deck() is None and s.deck_error

def test_a_deck_fault_cannot_block_the_safety_notice_in_the_real_observer(tmp_path):
 a=Served(tmp_path);enable(tmp_path,'ollama:local:'+MODEL);app=create_app(TOKEN,tmp_path,adapter=a);speech=app.state.speech
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   epoch=auth(ws)['epoch'];state=running_state()
   send(ws,epoch,0,state)
   speech.deck().verified_event=broken;speech.deck().finish_session=broken
   state['status']='IDLE';state['details']['terminal_outcome']='safety_stop'
   event=[{'id':str(uuid4()),'kind':'stop','session_id':state['session_id'],'at_ms':int(time.time()*1000)}]
   state['details']['captured_at_ms']=int(time.time()*1000)
   ws.send_json(frame(epoch,1,state,event))
   notice=None
   for _ in range(60):
    message=ws.receive_json()
    if message['type']=='speech' and message.get('source')=='safety':notice=message;break
   assert notice and notice['interrupt'] is True


# Remaining policy coverage

async def test_muting_holds_the_closing_without_spending_its_attempts():
 r,s,a,frames=rig();await turn(s);tick(r,s.busy_until-r.clock.mono()+1)
 s.policy=s.policy.model_copy(update={'enabled':False})
 finish(r,s)
 for _ in range(6):
  tick(r,1);s.pump()
 assert len(a.calls)==1 and s.deck().closing_pending and s.director.last_reason=='closed_or_speech_disabled'
 assert s.deck().snapshot()['counts'].get('deferred',0)==0
 s.policy=s.policy.model_copy(update={'enabled':True})
 assert (await turn(s))['deck_card']['lane']=='session_end'

async def test_closing_compiles_through_the_real_model_path_with_final_facts():
 r=Replay();r.state['devices'].update(toy_ready=True,handy=True);r.state['safety']['fault']='none';r.step(85,seconds=0)
 wire=[];m=ModelManager(transport=runtime(wire,'[[expression:proud]]That was a good session.'));await m.select(AIConfig(model=MODEL));m.current_summary=r.observation.summary
 d=ObserverDirector(DirectorConfig(regenerate_once=False),clock=r.clock.mono);frames=[]
 s=ConversationService(r.observation,frames.append,m,clock=r.clock.mono,director=d)
 s.deck_settings=DeckSettings(enabled=True);s.deck_definition=definition()
 finish(r,s);s.pump();await s.task
 text=json.dumps(next(b for path,b in reversed(wire) if path=='/api/chat')['messages'])
 assert 'This session: 4 edges in 10 minutes.' in text
 assert speeches(frames) and speeches(frames)[-1]['text']=='That was a good session.'


# Gaps found by fault injection

def test_turning_the_director_off_also_turns_the_deck_off():
 r,s,_,_=rig();assert s.deck()
 s.director.config=s.director.config.model_copy(update={'enabled':False})
 assert s.deck() is None

async def test_a_card_is_not_held_by_the_legacy_floor():
 r,s,a,_=rig();s.last_event=r.clock.mono()
 assert (await turn(s))['deck_card']['lane']=='session_start'

async def test_a_held_closing_keeps_later_events_from_being_dispatched():
 r,s,a,_=rig();await turn(s);s.busy_until=r.clock.mono()+20;s.busy_from_user=True;finish(r,s)
 session=r.observation.session_id
 s.pending.append({'kind':'experience_changed','at':r.clock.mono(),'priority':50,'event_id':'late','session_id':session,'source_status':'IDLE','observer_epoch':getattr(r.observation,'connection_epoch',None)})
 s.pump()
 assert len(a.calls)==1 and s.director.last_reason=='deck:output_busy'

async def test_an_event_the_director_declines_does_not_stop_the_normal_draw():
 r,s,a,_=rig();await turn(s);await settle(r,s)
 r.state['experience']='headplay';r.step(85)
 s.enqueue('experience_changed',50,{'event_id':'sel1','session_id':r.observation.session_id,'previous_experience':'classic','current_experience':'headplay','previous_goal':'tease','current_goal':'tease','category':'authoritative'})
 s.director.last_reaction=r.clock.mono();s.policy=s.policy.model_copy(update={'user_grace_seconds':0.,'min_interval_seconds':0.})
 assert [e['kind'] for e in s.pending]==['experience_changed']
 assert (await turn(s))['deck_card']['lane']=='normal'

async def test_the_opening_card_replaces_the_session_started_reaction():
 r,s,a,_=rig()
 s.enqueue('session_started',50,{'event_id':'e1','session_id':r.observation.session_id})
 assert s.pending==[]
 assert (await turn(s))['deck_card']['card_id']=='start'

async def test_closing_interrupts_a_running_card_immediately():
 r,s,a,_=rig();await turn(s);await settle(r,s)
 s.pump();task=s.task;finish(r,s)
 assert task.cancelling()==1
 await asyncio.gather(task,return_exceptions=True)

async def test_closing_does_not_cancel_again_after_a_safety_notice():
 r,s,a,frames=rig();await turn(s);await settle(r,s)
 s.pump();task=s.task
 s.safety('stop');notice=len(frames);finish(r,s)
 assert task.cancelling()==1
 assert not [f for f in frames[notice:] if f['type']=='speech_cancel']
 await asyncio.gather(task,return_exceptions=True)

async def test_the_curator_waits_for_an_outstanding_closing():
 r,s,a,_=rig();await turn(s);tick(r,s.busy_until-r.clock.mono()+1);finish(r,s)
 a.curate_memory=lambda *args:pytest.fail('curator started');s.curator.due=lambda narrative:pytest.fail('curator consulted')
 s.last_user=r.clock.mono()-60
 s.maybe_curate()
 assert s.deck().closing_pending

async def test_repetition_suppresses_the_card_rather_than_consuming_it():
 r,s,a,_=rig(adapter=Adapter(['The same line about the same lighthouse keeper and his lamp.']))
 await turn(s);await asyncio.sleep(0);await settle(r,s)
 await turn(s);await asyncio.sleep(0)
 counts=s.deck().snapshot()['counts'];assert counts['suppressed']==1 and counts['delivered']==1

async def test_a_cancelled_turn_settles_as_cancelled_in_every_path():
 r,s,a,_=rig();await turn(s);await settle(r,s)
 s.pump();task=s.task;await asyncio.sleep(0);s.interrupt()
 await asyncio.gather(task,return_exceptions=True);await asyncio.sleep(0)
 assert s.deck().snapshot()['counts']['cancelled']==1 and s.deck_open=={}

async def test_card_speech_never_interrupts_even_under_the_interrupt_policy():
 r,s,a,frames=rig();s.policy=s.policy.model_copy(update={'interruption':'interrupt'})
 await turn(s)
 assert speeches(frames)[-1]['interrupt'] is False

async def test_proactive_off_silences_an_ending_the_user_did_not_cause():
 r,s,a,_=rig();await turn(s);tick(r,s.busy_until-r.clock.mono()+1)
 s.director.config=s.director.config.model_copy(update={'spontaneous_enabled':False})
 r.step(85,status='IDLE')
 s.enqueue('session_ended',70,{'event_id':'end','session_id':r.observation.session_id,'session_result':RESULT|{'termination':'other_stop'}})
 s.pump();assert len(a.calls)==1 and s.director.last_reason=='deck:proactive_disabled'

async def test_narrative_cards_wait_until_the_story_is_welcome():
 guarded=Sequence(id='s1',lane='narrative',trigger=SequenceTrigger(event_kinds=['edge']),steps=[card('s1-a','narrative',memory='story',eligibility=Eligibility(requires_story_welcome=True))])
 r,s,a,_=rig(sequences=[guarded]);await turn(s);await settle(r,s)
 assert s.narrative.state['initiative_allowed'] is False
 s.deck_event('edge','occ-1')
 assert (await turn(s))['deck_card']['lane']=='normal'

def test_a_narrative_reset_reaches_the_deck():
 r,s,_,_=rig(sequences=[story()]);deck=s.deck();s.deck_event('edge','occ-1')
 assert deck.snapshot()['active_sequences']==['s1']
 s.narrative.state['epoch']='new-epoch'
 assert s.deck() is deck and deck.epoch=='new-epoch' and deck.snapshot()['active_sequences']==[]


# Hardening: closing

async def test_commentary_still_playing_is_cancelled_so_the_closing_follows_at_once():
 r,s,a,frames=rig();await turn(s);assert s.busy_until>r.clock.mono()
 generation=s.generation;finish(r,s)
 assert s.generation==generation+1 and [f for f in frames if f['type']=='speech_cancel'] and s.busy_until==0
 tick(r,1)
 assert (await turn(s))['deck_card']['lane']=='session_end'

async def test_a_users_reply_still_playing_is_never_cancelled_by_the_closing():
 r,s,a,frames=rig();s.request('A direct question.',user=True);await s.task
 s.busy_until=end=r.clock.mono()+20
 cancels=[f for f in frames if f['type']=='speech_cancel']
 tick(r,3);finish(r,s)
 assert s.busy_until==end and [f for f in frames if f['type']=='speech_cancel']==cancels
 s.pump();assert len(a.calls)==1 and s.director.last_reason=='deck:output_busy'

async def test_output_held_for_longer_than_the_ttl_does_not_lose_the_closing():
 r,s,a,_=rig();await turn(s);tick(r,s.busy_until-r.clock.mono()+1)
 finish(r,s);s.busy_until=r.clock.mono()+120;s.busy_from_user=True
 for _ in range(100):
  tick(r,1);s.pump()
 assert len(a.calls)==1 and s.deck().closing_pending and s.director.last_reason=='deck:output_busy'
 tick(r,21)
 assert (await turn(s))['deck_card']['lane']=='session_end'

async def test_a_long_pause_in_polling_does_not_lose_the_closing():
 """maintenance() skips pump() entirely while a user turn holds the model lock."""
 r,s,a,_=rig();await turn(s);tick(r,s.busy_until-r.clock.mono()+1);finish(r,s)
 tick(r,180)
 assert (await turn(s))['deck_card']['lane']=='session_end'

async def test_a_user_conversation_holds_the_closing_without_spending_the_ttl():
 r,s,a,_=rig();await turn(s);tick(r,s.busy_until-r.clock.mono()+1);finish(r,s)
 for _ in range(80):
  tick(r,1);s.director.typing_until=r.clock.mono()+5;s.pump()
 assert len(a.calls)==1 and s.deck().closing_pending and s.director.last_reason=='deck:user_active'

async def test_an_endless_hold_ends_at_the_limit_and_is_recorded_not_silent():
 r,s,a,_=rig();await turn(s);tick(r,s.busy_until-r.clock.mono()+1);finish(r,s)
 s.busy_until=r.clock.mono()+1000;s.busy_from_user=True
 tick(r,301);s.pump()
 assert not s.deck().closing_pending and s.deck().closing_outcome=='hold_limit_reached'
 assert any(d['reason']=='deck_closing_dropped' and d['outcome']=='hold_limit_reached' for d in s.director.decisions)
 assert len(a.calls)==1

@pytest.mark.parametrize('block',['quiet','mute','disconnect','protective'])
async def test_safety_mute_and_disconnect_holds_still_spend_the_ttl(block):
 r,s,a,_=rig();await turn(s);tick(r,s.busy_until-r.clock.mono()+1);finish(r,s)
 if block=='quiet':s.director.memory['quiet_requested']=True
 if block=='mute':s.policy=s.policy.model_copy(update={'enabled':False})
 if block=='disconnect':r.state['safety']['fault']='device_unready';r.state['devices'].update(toy_ready=False,handy=False)
 if block=='protective':r.state['safety'].update(no_contact=True,fault='no_contact')
 for _ in range(58):
  tick(r,1);s.pump()
 assert s.deck().closing_pending and len(a.calls)==1
 for _ in range(4):
  tick(r,1);s.pump()
 assert not s.deck().closing_pending and s.deck().closing_outcome=='expired' and len(a.calls)==1
 assert any(d['reason']=='deck_closing_dropped' for d in s.director.decisions)

async def test_closing_reports_the_final_snapshot_even_after_counters_reset():
 r=Replay();r.state['devices'].update(toy_ready=True,handy=True);r.state['safety']['fault']='none';r.step(85,seconds=0)
 wire=[];m=ModelManager(transport=runtime(wire,'That was a good session.'));await m.select(AIConfig(model=MODEL));m.current_summary=r.observation.summary
 d=ObserverDirector(DirectorConfig(regenerate_once=False),clock=r.clock.mono)
 s=ConversationService(r.observation,lambda f:None,m,clock=r.clock.mono,director=d)
 s.deck_settings=DeckSettings(enabled=True);s.deck_definition=definition()
 finish(r,s)
 r.state['seconds']=r.state['edges']=0;r.step(85,seconds=1,status='IDLE')
 s.pump();await s.task
 result=s.deck_closing_event[1]['session_result']
 text='\n'.join(m['content'] for m in next(b for path,b in reversed(wire) if path=='/api/chat')['messages'])
 assert result['edges']==4 and result['active_running_seconds']==600
 assert 'This session: 4 edges in 10 minutes.' in text and '0 edges' not in text


# Hardening: one voice for each occurrence

@pytest.mark.parametrize('kind',['edge','milestone','session_resumed','completion_accepted','hr_rising'])
async def test_legacy_reactions_become_context_while_the_deck_is_on(kind):
 r,s,a,_=rig()
 s.enqueue(kind,50,{'event_id':'e1','session_id':r.observation.session_id,'category':'authoritative','at_ms':int(r.clock.wall()*1000)})
 assert s.pending==[] and s.recent_events[-1]['kind']==kind
 assert (await turn(s))['deck_card']['lane']=='session_start'
 assert not [c for c in a.calls if c[0].get('trigger_event',{}).get('kind')==kind]

async def test_one_edge_gets_the_mission_card_and_no_reaction_with_detection_preserved():
 r,s,a,_=rig(sequences=[mission()],mission_spacing_seconds=0)
 decisions=[];s.event_intelligence.decision=lambda event_id,*args:decisions.append((event_id,args[0]))
 await turn(s);tick(r,s.busy_until-r.clock.mono()+1)
 details={'event_id':'occ-1','session_id':r.observation.session_id,'category':'authoritative','at_ms':int(r.clock.wall()*1000)}
 s.deck_event('edge','occ-1');s.enqueue('edge',50,details);s.enqueue('edge',50,details)
 assert ('occ-1','context_only:deck_owned') in decisions and ('occ-1','discarded:duplicate') in decisions
 assert (await turn(s))['deck_card']['lane']=='mission'
 await settle(r,s);assert (await turn(s))['deck_card']['lane']=='normal'
 assert lanes(a)==['session_start','mission','normal']

async def test_derived_detector_events_can_trigger_cards_but_never_legacy_speech():
 r,s,a,_=rig(sequences=[mission('hr-m',event_kinds=['rapid_rise'])])
 await turn(s);tick(r,s.busy_until-r.clock.mono()+1)
 s.enqueue('rapid_rise',45,{'event_id':'d1','session_id':r.observation.session_id,'category':'derived','narrative_epoch':s.narrative.state['epoch']})
 assert s.pending==[]
 assert (await turn(s))['deck_card']['card_id']=='hr-m-a'

async def test_acknowledging_the_users_selection_survives_unless_a_card_covers_it():
 selection={'event_id':'sel','previous_experience':'classic','current_experience':'headplay','previous_goal':'tease','current_goal':'tease','category':'authoritative'}
 r,s,a,_=rig();s.enqueue('experience_changed',50,selection|{'session_id':r.observation.session_id})
 assert [e['kind'] for e in s.pending]==['experience_changed']
 r,s,a,_=rig(sequences=[mission(event_kinds=['experience_changed'])]);s.enqueue('experience_changed',50,selection|{'session_id':r.observation.session_id})
 assert s.pending==[] and s.deck().snapshot()['active_sequences']==['m1']

@pytest.mark.usefixtures('deck_off')
async def test_flag_off_records_events_without_reactions():
 r,s,a,_=rig(deck=False)
 s.enqueue('edge',50,{'event_id':'e1','session_id':r.observation.session_id,'category':'authoritative','at_ms':int(r.clock.wall()*1000)})
 assert s.pending==[] and s.recent_events[-1]['kind']=='edge'
 s.pump();assert s.task is None and not a.calls


# Hardening: faults

async def test_a_fault_keeps_user_conversation_and_safety_notices():
 r,s,a,frames=rig();s.deck().next_play=broken;s.pump();assert s.deck_error
 assert s.request('Are you there?',user=True)['accepted'];await s.task
 assert speeches(frames)[-1]['source']=='user' and len(a.calls)==1
 s.safety('stop');assert speeches(frames)[-1]['source']=='safety'

async def test_a_fault_stops_a_running_card_and_queued_or_future_reactions():
 r,s,a,frames=rig();await turn(s);await settle(r,s)
 s.pump();task=s.task
 s.deck_fail('Event deck disabled after an internal error: RuntimeError')
 assert task.cancelling()==1 and s.request('unsolicited',user=False)=={'accepted':False,'reason':'deck_fault'}
 await asyncio.gather(task,return_exceptions=True)
 details={'event_id':'sel','session_id':r.observation.session_id,'category':'authoritative','previous_experience':'classic','current_experience':'headplay','previous_goal':'tease','current_goal':'tease'}
 s.enqueue('experience_changed',50,details);s.enqueue('session_ended',70,details|{'event_id':'end','session_result':RESULT})
 assert s.pending==[] and s.recent_events[-1]['kind']=='session_ended' and 'session_result' not in s.recent_events[-1]

@pytest.mark.usefixtures('deck_off')
async def test_a_fault_is_per_model_and_outlasts_reactivation():
 r,s,a,_=rig();s.deck().next_play=broken;s.pump();assert s.deck_error
 a.config=AIConfig(model='evelyn-narrative-v1:latest');s.activate_model()
 assert s.deck_error is None and s.deck() is None
 tick(r,40);s.pump();assert s.task is None
 a.config=AIConfig(model=MODEL);s.activate_model();assert s.deck_error
 tick(r,60);count=len(a.calls);s.pump();assert len(a.calls)==count

async def test_a_missing_definition_is_a_fault_not_a_fallback(monkeypatch):
 r,s,a,_=rig();s.deck_definition=None
 monkeypatch.setattr('companion_ai.conversation.load_definition',lambda raw:(None,'bad definition'))
 tick(r,40);s.pump()
 assert s.deck_error=='bad definition' and s.task is None and not a.calls

async def test_a_fault_while_settling_never_breaks_a_finished_user_turn():
 r,s,a,frames=rig();s.deck().response_completed=broken
 s.request('Hello.',user=True);await s.task
 assert speeches(frames)[-1]['source']=='user' and not [f for f in frames if f['type']=='conversation_error'] and s.deck_error

async def test_turning_the_director_off_is_a_choice_but_a_fault_still_blocks():
 r,s,a,_=rig();s.deck().next_play=broken;s.pump()
 s.director.config=s.director.config.model_copy(update={'enabled':False})
 tick(r,60);s.pump();assert s.task is None


# Hardening: timing

@pytest.mark.parametrize('countdown',[0,3,10,25])
async def test_the_countdown_is_exact_from_estimated_output_end_and_configurable(countdown):
 r,s,a,_=rig(countdown_seconds=countdown)
 await turn(s);end=s.busy_until
 hold=max(0,end+countdown-r.clock.mono())
 if hold>=.5:
  advance(r,hold-.25);s.pump();assert len(a.calls)==1
  advance(r,.25)
 else:advance(r,hold)
 assert s.deck_context(r.clock.mono()).output_busy is False
 s.pump();assert s.active_source=='event' and not s.task.done(),s.director.last_reason
 await s.task;assert len(a.calls)==2

def test_the_default_countdown_is_ten_seconds():
 assert DeckSettings().countdown_seconds==10

async def test_ordinary_cadence_never_meets_the_hold_without_a_user_turn():
 r,s,a,_=rig();gaps=[];await turn(s)
 for _ in range(8):
  end=s.busy_until
  poll_until_turn(r,s)
  assert not any(d['reason']=='deck:active_conversation' for d in s.director.decisions)
  gaps.append(r.clock.mono()-end);await s.task;await asyncio.sleep(0)
 assert all(10<=gap<=10.25 for gap in gaps),gaps

async def test_after_a_user_turn_the_hold_runs_alongside_the_countdown_and_is_not_added():
 r,s,a,_=rig();await turn(s);await settle(r,s)
 s.request('A short question.',user=True);asked=r.clock.mono();await s.task
 assert s.deck_context(r.clock.mono()).conversation_active
 while r.clock.mono()-asked<29.75:
  advance(r,.25);s.pump();assert not (s.task and not s.task.done() and s.active_source=='event')
 advance(r,.5);s.pump()
 assert s.active_event_kind=='deck_card' and s.active_source=='event' and r.clock.mono()-asked<=30.25
 await s.task

async def test_a_long_user_reply_ends_later_than_the_hold_and_the_countdown_governs():
 r,s,a,_=rig(adapter=Adapter([' '.join(f'word{i}' for i in range(100))]));await turn(s);await settle(r,s)
 s.request('Tell me more.',user=True);asked=r.clock.mono();await s.task;end=s.busy_until
 assert end+10-asked>30
 advance(r,end+9.75-r.clock.mono());s.pump();assert not (s.task and not s.task.done())
 advance(r,.25);s.pump();assert s.active_source=='event'
 await s.task

async def test_the_hold_is_the_directors_existing_setting_and_can_be_shortened():
 assert DirectorConfig().user_idle_before_spontaneous_seconds==30
 r,s,a,_=rig();s.director.config=s.director.config.model_copy(update={'user_idle_before_spontaneous_seconds':0.})
 await turn(s);await settle(r,s);s.request('Hi.',user=True);await s.task
 assert not s.deck_context(r.clock.mono()).conversation_active

async def test_the_hold_never_delays_opening_mission_or_closing():
 r,s,a,_=rig(sequences=[mission()]);s.director.memory['last_user']=r.clock.mono()
 assert (await turn(s))['deck_card']['lane']=='session_start'
 tick(r,s.busy_until-r.clock.mono()+1);s.director.memory['last_user']=r.clock.mono()
 s.deck_event('edge','occ-1');assert (await turn(s))['deck_card']['lane']=='mission'
 tick(r,s.busy_until-r.clock.mono()+1);s.director.memory['last_user']=r.clock.mono();finish(r,s)
 assert (await turn(s))['deck_card']['lane']=='session_end'

async def test_a_silent_model_with_a_zero_countdown_cannot_retry_on_every_poll():
 r,s,a,_=rig(adapter=Adapter(['[SILENCE]']),countdown_seconds=0)
 s.deck()._start_done=True
 await turn(s);await asyncio.sleep(0)
 for _ in range(7):
  advance(r,.25);s.pump()
 assert len(a.calls)==1 and s.director.last_reason=='deck:retry_wait'


# Gaps found by the second round of fault injection

SELECTION={'event_id':'sel','previous_experience':'classic','current_experience':'headplay','previous_goal':'tease','current_goal':'tease','category':'authoritative'}

async def test_a_queued_selection_reaction_is_discarded_when_the_session_ends():
 r,s,a,_=rig();await turn(s);tick(r,s.busy_until-r.clock.mono()+1)
 s.enqueue('experience_changed',50,SELECTION|{'session_id':r.observation.session_id})
 assert [e['kind'] for e in s.pending]==['experience_changed']
 finish(r,s)
 assert s.pending==[]

async def test_a_fault_discards_a_queued_selection_reaction():
 r,s,a,_=rig()
 s.enqueue('experience_changed',50,SELECTION|{'session_id':r.observation.session_id})
 assert s.pending
 s.deck_fail('Event deck disabled after an internal error: RuntimeError')
 assert s.pending==[]

async def test_commentary_playing_beneath_a_safety_notice_does_not_cut_the_notice():
 r,s,a,frames=rig();await turn(s);tick(r,s.busy_until-r.clock.mono()+1)
 s.deck_hold_until=r.clock.mono()+2;s.busy_until=r.clock.mono()+5;s.busy_from_user=False
 finish(r,s)
 assert s.busy_until==0 and not [f for f in frames if f['type']=='speech_cancel']

@pytest.mark.parametrize('closing',[False,True])
async def test_a_fault_stops_that_poll_and_is_reported_once(closing):
 r,s,a,frames=rig()
 if closing:
  await turn(s);tick(r,s.busy_until-r.clock.mono()+1);finish(r,s)
 s.deck().next_play=broken
 s.pump();s.pump()
 assert len([f for f in frames if f.get('event_deck_fault')])==1

async def test_a_fault_during_a_lifecycle_update_never_escapes_the_turn():
 r,s,a,frames=rig();deck=s.deck();original=deck.transition
 def failing(play_id,status,now,reason=None):
  if status=='generated':raise RuntimeError('deck bug')
  return original(play_id,status,now,reason)
 deck.transition=failing
 s.pump();outcome=await asyncio.gather(s.task,return_exceptions=True)
 assert not isinstance(outcome[0],RuntimeError) and 'RuntimeError' in s.deck_error
 assert not [f for f in frames if f['type']=='conversation_error']

def test_events_that_never_reach_enqueue_still_reach_the_deck_through_the_observer(tmp_path):
 """A pause goes straight to a safety notice, so only the server hook can tell the deck."""
 a=Served(tmp_path);enable(tmp_path,'ollama:local:'+MODEL);app=create_app(TOKEN,tmp_path,adapter=a);speech=app.state.speech
 speech.deck_definition=definition([mission('paused-m',event_kinds=['pause'])])
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   epoch=auth(ws)['epoch'];state=running_state()
   send(ws,epoch,0,state)
   state['status']='PAUSED';time.sleep(.12);send(ws,epoch,1,state,'pause')
   assert speech.deck().snapshot()['active_sequences']==['paused-m']

async def test_a_ready_mission_goes_before_a_ready_selection_reaction():
 r,s,a,_=rig(sequences=[mission()]);await turn(s);tick(r,s.busy_until-r.clock.mono()+1)
 r.state['experience']='headplay';r.step(85)
 s.enqueue('experience_changed',50,SELECTION|{'session_id':r.observation.session_id})
 s.deck_event('edge','occ-1')
 # Ready for real: settled and out of cooldown, so the Director would dispatch it right now.
 s.pending[0]['not_before']=0;s.director.last_reaction=float('-inf')
 assert (await turn(s))['deck_card']['lane']=='mission'
 assert [e['kind'] for e in s.pending]==['experience_changed']
 tick(r,s.busy_until-r.clock.mono()+5);s.director.last_reaction=float('-inf')
 assert (await turn(s))['trigger_event']['kind']=='experience_changed'
