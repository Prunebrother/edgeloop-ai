# SPDX-License-Identifier: AGPL-3.0-only
from copy import deepcopy
import json
import httpx
import pytest
from ai_observer.protocol import Observation
from ai_observer.observation import BrowserObservation
from companion_ai.grounding import SessionFacts, render_facts
from companion_ai.context import compose_messages
from companion_ai.models import AIConfig, MemoryConfig
from companion_ai.conversation import ModelManager
from tests.fork.grounding_cases import Clock, snapshot, frame, cases

@pytest.mark.parametrize('case',cases(),ids=lambda c:c.name)
def test_twenty_scenarios_have_valid_single_current_contract(case):
    canonical=SessionFacts.model_validate(case.summary()['canonical_session'])
    messages,_=compose_messages(case.summary(),case.prompt,case.history,AIConfig(max_tokens=256),MemoryConfig(max_messages=64))
    system=messages[0]['content'];assert sum(m['content'].count('CURRENT SESSION —') for m in messages)==1
    assert 'CURRENT SESSION —' in messages[-1]['content']
    assert '"reported_state"' not in system and '"state":' not in system
    assert canonical.facts['physical_motion'].known is False
    assert canonical.facts['physical_motion'].value is None
    assert all(m['role'] in {'system','assistant','user'} for m in messages)
    if case.name=='malformed_rejected':assert case.rejected_messages==1

@pytest.mark.parametrize('name,value,kind,unit',[
    ('hr',98,'derived','BPM'),('resting_bpm',70,'setting','BPM'),('single_max_bpm',140,'setting','BPM'),
    ('dual_max_bpm',125,'setting','BPM'),('effective_max',140,'derived','BPM'),('seconds',42,'status','seconds'),
    ('intensity',100,'setting','percent'),('edges',2,'status','count'),('pauses',1,'status','count'),('primary',20,'engine_value','percent')])
def test_field_values_units_kind_source_and_freshness(name,value,kind,unit):
    case=cases()[1];fact=case.observation.canonical()['facts'][name]
    assert fact['value']==value and fact['kind']==kind and fact['unit']==unit
    assert fact['known'] and fact['current'] and fact['source'] and fact['observed_at_ms'] is not None

def test_source_isolation_and_no_sensor_defaults_or_old_ble_current():
    c=Clock();o=BrowserObservation(c.mono,c.wall);s=snapshot(c);s['devices'].update(simulated_hr=False,ble=True)
    assert o.accept(Observation.model_validate(frame(s))) and o.hr==98
    c.tick(5.01)
    assert not o.hr_current() and o.hr is None
    # A fresh transport frame cannot freshen an old physiological sample.
    s['details']['captured_at_ms']=int(c.wall()*1000)
    assert o.accept(Observation.model_validate(frame(s,1)))
    assert o.fresh() and o.hr is None
    assert '98 BPM' not in render_facts(o.canonical())

@pytest.mark.parametrize('mutate',[
    lambda s:s['devices'].update(hr_ready=False),
    lambda s:s['devices'].update(simulated_hr=False,ble=False),
    lambda s:s['details'].update(hr_recorded_at_ms=s['details']['captured_at_ms']+1),
    lambda s:s.update(status='PAUSED'),
    lambda s:s['devices'].update(toy_ready=True),
    lambda s:s['details'].update(secret_control='stop'),
    lambda s:s.update(hr=0),
])
def test_contradictory_or_malformed_projection_is_rejected(mutate):
    s=snapshot(Clock());mutate(s)
    with pytest.raises(ValueError):Observation.model_validate(frame(s))

def test_expired_capture_cannot_be_replayed_as_live_and_future_is_rejected():
    c=Clock();o=BrowserObservation(c.mono,c.wall);s=snapshot(c);c.tick(6)
    assert o.accept(Observation.model_validate(frame(s))) and not o.fresh()
    assert all(not f['current'] for f in o.canonical()['facts'].values())
    s['details']['captured_at_ms']=int(c.wall()*1000)+2000
    assert not o.accept(Observation.model_validate(frame(s,1)))

def test_repeated_snapshots_are_not_samples_and_reconnect_resets_evidence():
    c=Clock();o=BrowserObservation(c.mono,c.wall);s=snapshot(c)
    for i in range(12):
        c.tick(.2);s['details']['captured_at_ms']=int(c.wall()*1000);o.accept(Observation.model_validate(frame(s,i)))
    assert len(o.samples)<=1 and o.trend=='unknown'
    o.begin_epoch();assert not o.samples and not o.events and not o.fresh()

def test_trend_requires_timestamped_monotonic_evidence_and_source_continuity():
    by_name={c.name:c for c in cases()}
    assert by_name['rising_evidence'].observation.trend=='rising'
    assert by_name['fluctuating_not_trend'].observation.trend=='unknown'
    case=by_name['rising_evidence'];o=case.observation;c=Clock();c.elapsed=4;s=snapshot(c,hr=100)
    assert o.accept(Observation.model_validate(frame(s,5))) # BLE -> simulator
    assert o.trend=='unknown' and len(o.samples)<=1

def test_event_dedup_order_bounds_and_no_generated_dialogue_as_events():
    c=Clock();o=BrowserObservation(c.mono,c.wall);s=snapshot(c);o.accept(Observation.model_validate(frame(s)))
    for i in range(1,45):
        c.tick(.2);s=snapshot(c,edges=2+i)
        message=Observation.model_validate(frame(s,i,['edge']))
        assert o.accept(message)
    assert len(o.events)==32 and len(o.seen_events)<=256
    events=o.canonical()['events'];assert len(events)==6
    assert [e['sequence'] for e in events]==sorted(e['sequence'] for e in events)
    before=len(o.events);c.tick(.2);s['details']['captured_at_ms']=int(c.wall()*1000)
    same=message.model_dump();same['sequence']=45;same['snapshot']=s
    assert o.accept(Observation.model_validate(same)) and len(o.events)==before
    assert all(e['source']=='original_edgeloop_observed_change' for e in events)
    fake=frame(s,46,['edge']);fake['events'][0]['id']=str(__import__('uuid').uuid4())
    assert o.accept(Observation.model_validate(fake)) and len(o.events)==before # Counter did not increase.

def test_current_status_setting_change_and_session_reset_do_not_invent_pulse_or_events():
    values={c.name:c for c in cases()}
    for name in ['threshold_changed_not_pulse','intensity_changed']:
        f=values[name].observation.canonical()['facts'];assert f['hr']['value']==98 and f['trend']['value'] is None
    r=values['restart_counters'].observation.canonical()
    assert r['facts']['edges']['value']==0 and r['facts']['seconds']['value']==0 and not r['events']
    assert values['stopped'].observation.canonical()['events'][0]['kind']=='stop'

def test_long_history_trims_inference_but_never_stores_a_snapshot_or_loses_current_facts():
    case=cases()[-1];copy=deepcopy(case.history)
    messages,warnings=compose_messages(case.summary(),case.prompt,case.history,AIConfig(max_tokens=256),MemoryConfig(max_messages=64))
    assert case.history==copy and warnings
    assert messages[-1]['content'].count('CURRENT SESSION —')==1
    assert 'Heart rate [hr]: 98 BPM' in messages[-1]['content']
    assert messages[-1]['content'].endswith(case.prompt)

async def test_latest_snapshot_is_refreshed_after_provider_wait_before_chat_wire():
    clock=Clock();o=BrowserObservation(clock.mono,clock.wall);s=snapshot(clock);o.accept(Observation.model_validate(frame(s)))
    wire=[]
    def runtime(request):
        if request.url.path=='/api/show':
            clock.tick();new=snapshot(clock,hr=102);o.accept(Observation.model_validate(frame(new,1)))
            return httpx.Response(200,json={'system':'UNCHANGED CHARACTER','capabilities':['completion']})
        body=json.loads(request.content);wire.append(body)
        return httpx.Response(200,text=json.dumps({'message':{'content':'Simulated 102 BPM.'},'done':True,'done_reason':'stop'})+'\n')
    manager=ModelManager(transport=httpx.MockTransport(runtime));manager.current_summary=o.summary
    await manager.start(AIConfig(thinking=False));old=o.summary()
    answer=await manager.reply(old,'Current BPM?',[])
    assert answer=='Simulated 102 BPM.' and wire[0]['messages'][0]['content'].startswith('UNCHANGED CHARACTER\n\n')
    assert 'Heart rate [hr]: 102 BPM' in wire[0]['messages'][-1]['content']
    assert 'Heart rate [hr]: 98 BPM' not in wire[0]['messages'][-1]['content']
    await manager.stop()


def test_watchdog_reset_cannot_turn_a_nonlive_reading_into_current_telemetry():
    c=Clock();o=BrowserObservation(c.mono,c.wall);s=snapshot(c)
    s['devices'].update(simulated_hr=False,ble=True)
    s['details']['hr_live']=False  # Original watchdog verdict, not the cleared display badge.
    assert o.accept(Observation.model_validate(frame(s)))
    assert not o.hr_current() and o.hr is None
    assert o.canonical()['facts']['hr']['current'] is False


def test_expired_measurements_do_not_reenter_from_assistant_memory_but_personal_history_remains():
    case=next(c for c in cases() if c.name=='stale_connection')
    original=case.history+[{'role':'user','content':'My name is Alex.'},{'role':'assistant','content':'Good to see you, Alex.'}]
    stored=deepcopy(original)
    messages,warnings=compose_messages(case.summary(),case.prompt,original,AIConfig(max_tokens=256))
    assert original==stored and warnings
    assert not any('98 BPM' in m['content'] for m in messages)
    assert any('Alex' in m['content'] for m in messages)
    assert 'CURRENT SESSION —' in messages[-1]['content']


def test_model_sees_actual_trend_evidence_window_not_the_session_elapsed_counter():
    examples={c.name:c for c in cases()}
    rising=render_facts(examples['rising_evidence'].observation.canonical())
    mixed=render_facts(examples['fluctuating_not_trend'].observation.canonical())
    assert '4 distinct timestamped samples spanning 3 seconds' in rising
    assert '42 seconds' in rising  # Distinctly labelled session clock.
    assert 'mixed samples; no consistent direction' in mixed


def test_current_session_question_uses_no_old_dialogue_as_measurement_history_even_when_fresh():
    case=cases()[-1];stored=deepcopy(case.history)
    messages,warnings=compose_messages(case.summary(),case.prompt,case.history,AIConfig(max_tokens=512),MemoryConfig(max_messages=64))
    assert case.history==stored and warnings
    assert not any('130 BPM' in m['content'] for m in messages)
    assert 'Heart rate [hr]: 98 BPM' in messages[-1]['content']
    # Explicit questions about prior dialogue still retain the conversation.
    past,_=compose_messages(case.summary(),'What did I say about my BPM earlier?',case.history,AIConfig(max_tokens=512),MemoryConfig(max_messages=64))
    assert any('130 BPM' in m['content'] for m in past[:-1])


def test_model_data_distinguishes_heart_sensor_from_stimulation_transports():
    text=render_facts(cases()[1].observation.canonical())
    assert 'BLE heart-rate sensor connection' in text
    assert 'Handy stimulation-device connection (not an HR sensor)' in text
    assert 'Intiface stimulation transport connection' in text


def test_disconnection_scenario_contains_an_observed_connection_transition():
    from tests.fork.grounding_cases import cases
    case=next(c for c in cases() if c.name=='hardware_disconnected_active')
    snapshot=case.observation.canonical()
    assert snapshot['facts']['status']['value']=='RUNNING'
    assert snapshot['facts']['handy']['value'] is False
    assert any(e['kind']=='device_changed' for e in snapshot['events'])
    assert snapshot['facts']['primary']['value']>0
    assert snapshot['facts']['physical_motion']['known'] is False
