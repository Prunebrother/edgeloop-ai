# SPDX-License-Identifier: AGPL-3.0-only
from uuid import uuid4
from tests.fork.event_replay import Replay
from companion_ai.grounding import render_facts,render_event_facts
from companion_ai.context import compose_messages
from companion_ai.models import AIConfig

def test_start_pause_resume_stop_restart_source_counter_and_context():
 r=Replay();r.step(85,seconds=0,status='IDLE')
 r.step(85,status='RUNNING',reset=True,kinds=('session_started',))
 first=r.observation.session_id
 for _ in range(4):r.step(85)
 assert r.observation.canonical()['facts']['seconds']['value']==5
 r.step(85,status='PAUSED',kinds=('pause',));r.step(85,seconds=3)
 facts=r.observation.canonical()
 assert facts['facts']['seconds']['value']==5
 assert facts['facts']['status']['value']=='PAUSED'
 text=render_event_facts(facts)
 assert 'active running counter 5 seconds' in text and 'Latest validated event: pause, 3 seconds' in text
 assert 'paused duration are unavailable' in text
 r.step(85,status='RUNNING',kinds=('session_resumed',))
 assert r.observation.canonical()['facts']['seconds']['value']==6
 # The original engine zeroes its counter at stop, not a computed final duration.
 r.state['seconds']=0;r.step(85,status='IDLE',kinds=('stop',))
 assert r.observation.canonical()['facts']['seconds']['value']==0
 r.step(85,seconds=0,status='RUNNING',reset=True,kinds=('session_started',))
 assert r.observation.session_id!=first
 assert r.observation.canonical()['facts']['seconds']['value']==0
 assert not any(e['kind']=='pause' for e in r.observation.canonical()['events'])

def test_stale_timing_is_not_extrapolated_or_anchored_in_model_context():
 r=Replay();r.step(85,seconds=0);r.state['seconds']=47;r.step(85,seconds=0)
 r.clock.tick(8)
 facts=r.observation.canonical()
 assert not facts['facts']['seconds']['current']
 for render in (render_facts,render_event_facts):
  text=render(facts)
  assert 'counter unavailable / stale' in text
  assert '47 seconds' not in text and '55 seconds' not in text
 assert 'Latest validated event:' not in render_event_facts(facts)

def test_narrative_view_has_scoped_fresh_timing_without_persisted_updates():
 r=Replay();r.step(85,seconds=0)
 summary=r.observation.summary()|{'conversation_source':'user','narrative_context':{'premise':'A fictional mystery'}}
 history=[]
 messages,_=compose_messages(summary,'How long has this session been running?',history,AIConfig(model='evelyn-narrative-v1:latest'))
 text=messages[-1]['content']
 assert 'TIMING: active running counter 0 seconds' in text
 assert 'captured_at_ms' in text and r.observation.session_id in text
 assert 'Wall-clock session duration and paused duration are unavailable' in text
 assert not history


def test_explicit_wall_pause_and_wrong_counter_claims_are_rejected():
 from companion_ai.fidelity import violations
 r=Replay();r.step(85,seconds=0);r.state['seconds']=408;r.step(85,seconds=0,status='PAUSED')
 facts=r.observation.canonical()
 assert 'unsupported_wall_or_paused_duration' in violations('The session has been running nearly seven minutes in real time.',facts)
 assert 'unsupported_wall_or_paused_duration' in violations('The paused duration is 20 seconds.',facts)
 assert 'wrong_running_counter' in violations('The engine counter is 500 seconds.',facts)
 assert not violations('The active running counter is 408 seconds. Wall-clock and paused durations are unavailable.',facts)
 r.clock.tick(8)
 assert 'unavailable_session_timing' in violations('The engine clock is at 408 seconds.',r.observation.canonical())
