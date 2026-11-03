# SPDX-License-Identifier: AGPL-3.0-only
import asyncio,json
import pytest
from companion_ai.conversation import ConversationService,ModelManager
from companion_ai.models import AIConfig
from companion_ai.director import DirectorConfig
from companion_ai.event_intelligence import EventConfig
from ai_observer.observation import ObserverDirector
from tests.fork.event_replay import Replay
from tests.ai.test_f25 import runtime

async def service(config=None,text='[[expression:focused]]The simulator shows a measured increase. No cause is established.'):
 r=Replay(config);wire=[];m=ModelManager(transport=runtime(wire,text));await m.select(AIConfig(model='evelyn-narrative-v1:latest'));m.current_summary=r.observation.summary
 d=ObserverDirector(DirectorConfig(regenerate_once=False),clock=r.clock.mono)
 frames=[];s=ConversationService(r.observation,frames.append,m,clock=r.clock.mono,director=d);s.event_intelligence=r.detector
 for i in range(21):s.process_derived(r.step(85+i,seconds=0 if i==0 else 1))
 return r,s,wire,frames

@pytest.mark.usefixtures('deck_off')
async def test_derived_evidence_is_context_only_and_grounds_a_user_question_with_thinking_off():
 # With no deck there is no unsolicited physiology commentary; the evidence still answers the user.
 r,s,wire,frames=await service()
 assert not s.pending and s.event_intelligence.history[-1]['decision']=='context_only:no_card_dealer'
 s.director.session_status='RUNNING';s.pump();assert s.task is None and not wire
 assert s.request('What is my current heart rate in BPM?',user=True)['accepted'];await s.task
 assert len(wire)==1 and wire[0][1]['think'] is False
 assert 'DERIVED TELEMETRY OBSERVATION' in wire[0][1]['messages'][-1]['content']
 assert 'PRIVATE REASONING' not in json.dumps(list(s.history))
 await s.close()

@pytest.mark.usefixtures('deck_off')
async def test_derived_events_stay_silent_while_typing_and_after_a_storyline_reset():
 r,s,wire,frames=await service();s.director.typing_until=r.clock.mono()+6;s.pump()
 assert not s.task and s.event_intelligence.history[-1]['decision']=='context_only:no_card_dealer'
 old=list(s.history);s.reset_narrative();assert not s.pending and list(s.history)==old
 s.pump();assert not wire
 await s.close()

@pytest.mark.parametrize('mode',['routine','irrelevant','disabled'])
@pytest.mark.usefixtures('deck_off')
async def test_context_only_or_disabled_never_generates(mode):
 c=EventConfig()
 if mode=='routine':c.detectors['rapid_rise'].significance='routine'
 elif mode=='irrelevant':c.preferences['evelyn']['physiology']=0
 elif mode=='disabled':c.enabled=False
 r,s,wire,frames=await service(c);s.pump();assert not s.task and not wire
 if mode!='disabled':assert 'context_only' in s.event_intelligence.history[-1]['decision']
 await s.close()

@pytest.mark.usefixtures('deck_off')
async def test_configuration_session_and_model_changes_never_replay_events():
 r,s,wire,frames=await service();s.configure_events(EventConfig());assert not s.pending
 assert s.event_intelligence.history[-1]['decision']=='context_only:no_card_dealer'
 await s.close()
 r,s,wire,frames=await service();r.step(120,reset=True);s.pump();assert not s.pending and not wire
 await s.close()
 r,s,wire,frames=await service();s.adapter.config=AIConfig(model='daisy-narrative-v1:latest');s.activate_model()
 s.pump();assert not s.pending and not wire
 await s.close()

async def test_proactive_disabled_retains_diagnostic_without_pending_replay():
 r,s,wire,frames=await service();s.pending.clear();s.director.config.spontaneous_enabled=False
 s.enqueue('rapid_rise',45,{'event_id':s.event_intelligence.history[-1]['event']['id'],'category':'derived'})
 s.pump();assert not s.pending and not wire and 'context_only' in s.event_intelligence.history[-1]['decision']
 await s.close()


def test_derived_events_cannot_be_recast_as_feelings_or_personal_simulator_pulse():
 from companion_ai.fidelity import event_violations
 trigger={'category':'derived','observation':{'simulated':True,'change_bpm':18}}
 for text in ["That spike in your heart rate suggests you're feeling the envelope's weight.","The drop in your numbers suggests you're getting nervous.","Your heart decided to take a vacation.","A frantic 115 became a calm 97.","The simulator is whispering your excitement.","That sustained elevation reading must mean you are itching to tear open the envelope.","This simulated spike is proof that you are feeling eager.","The simulated BPM fell. Does this sudden calm mean a walk around the barn?"]:
  assert event_violations(text,trigger)
 assert not event_violations('The simulator endpoint medians increased by 18 BPM. No cause is established.',trigger)
 assert event_violations('The simulator increased by 27 BPM.',trigger)==['incorrect_derived_change']


@pytest.mark.usefixtures('deck_off')
async def test_an_ungrounded_derived_claim_never_reaches_the_model_without_the_deck():
 r,s,wire,frames=await service(text="[[expression:happy]]The simulator is whispering your excitement.")
 s.director.session_status='RUNNING';s.pump()
 assert s.task is None and not wire and not s.history and not any(f['type']=='speech' for f in frames)
 await s.close()


async def test_overlapping_results_coalesce_into_one_context_only_record():
 from companion_ai.event_intelligence import DerivedEvent
 r,s,wire,frames=await service()
 events=[]
 for i in range(21,40):events.extend(r.step(110))
 # Replay supplies actual rise and elevation evidence, then schedules a single slot.
 both=[DerivedEvent.model_validate(row['event']) for row in r.detector.history if row['event']['category']=='derived']
 assert {'rapid_rise','sustained_elevation'}<={e.kind for e in both}
 s.process_derived(both)
 # Coalescing still picks one result; with no deck it is recorded, not queued for speech.
 assert not s.pending and any(row['decision'].startswith('coalesced:') for row in r.detector.history)
 s.last_user=r.clock.mono();s.pump()
 record=next(row for row in r.detector.history if row['event']['kind']=='rapid_rise')
 assert record['decision'] in {'context_only:no_card_dealer','discarded:duplicate'}
 assert not wire
 await s.close()
