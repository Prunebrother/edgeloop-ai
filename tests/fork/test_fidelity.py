# SPDX-License-Identifier: AGPL-3.0-only
import json
import httpx
import pytest
from companion_ai.fidelity import violations, explicit_bpm, GroundingError
from companion_ai.conversation import ModelManager, ConversationService
from companion_ai.models import AIConfig
from tests.fork.grounding_cases import cases

BY_NAME={c.name:c for c in cases()}
@pytest.mark.parametrize('text,codes',[
    ('Your heart is currently beating at 98 BPM.',['unsupported_bpm','unmeasured_physiology_from_simulation_or_unknown','wrong_current_bpm']),
    ('I am guessing ninety-eight beats per minute.',['unsupported_bpm']),
    ('The Handy is still connected.',['unsupported_handy_connection']),
    ('The Handy is disconnected.',['unsupported_handy_connection']),
    ('The Handy is not connected.',['unsupported_handy_connection']),
    ('Your current BPM and the connection are unavailable.',[]),
    ('Is the Handy connected? I cannot tell.',[]),
    ('The Handy is not connected, according to the old conversation.',[]),
    ('The session is currently running.',['unsupported_session_status']),
])
def test_stale_facts_cannot_be_guessed_from_dialogue(text,codes):
    assert violations(text,BY_NAME['stale_connection'].observation.canonical())==codes

@pytest.mark.parametrize('text,expected',[
    ('The simulated reading is 98 BPM; the single maximum setting is 140 BPM.',[]),
    ('The current heart rate is 140 BPM.',['wrong_current_bpm']),
    ('Your current heart rate is 98 BPM.',['unmeasured_physiology_from_simulation_or_unknown']),
    ('The real sensor reports 98 BPM.',['wrong_hr_source']),
    ('The simulated reading is 28 BPM above the resting setting.',[]),
    ('Your pulse has been steadily climbing.',['unmeasured_physiology_from_simulation_or_unknown','unsupported_trend']),
    ('If your pulse has been climbing, this snapshot cannot establish that.',[]),
])
def test_measurements_thresholds_simulation_and_trend_are_distinguished(text,expected):
    assert violations(text,BY_NAME['active_simulated'].observation.canonical())==expected

def test_verified_historical_dialogue_can_be_acknowledged_without_presenting_it_as_live():
    c=BY_NAME['stale_connection'];text='You previously mentioned 98 BPM. Current readings are unavailable.'
    assert violations(text,c.observation.canonical(),c.history)==[]
    assert violations('Your current heart rate is 98 BPM, as we mentioned earlier.',c.observation.canonical(),c.history)
    assert explicit_bpm('Ninety-eight beats per minute and 140 BPM.')

@pytest.mark.parametrize('repair_succeeds',[True,False])
async def test_correction_is_bounded_replaces_stream_and_never_saves_false_facts(repair_succeeds):
    c=BY_NAME['stale_connection'];requests=[]
    def runtime(request):
        if request.url.path=='/api/show':return httpx.Response(200,json={'system':'EXACT CHARACTER','capabilities':['completion']})
        body=json.loads(request.content);requests.append(body)
        content='Current readings and connectivity are unavailable.' if len(requests)>1 and repair_succeeds else 'Your current heart rate is 98 BPM. The Handy is connected.'
        return httpx.Response(200,text=json.dumps({'message':{'content':content},'done':True,'done_reason':'stop'})+'\n')
    manager=ModelManager(transport=httpx.MockTransport(runtime));manager.current_summary=c.observation.summary
    await manager.start(AIConfig(thinking=False));messages=[]
    speech=ConversationService(c.observation,messages.append,manager)
    speech.request('Current BPM and connection?',user=True);await speech.task
    assert len(requests)==2
    assert all(body['messages'][0]['content'].startswith('EXACT CHARACTER\n\n') for body in requests)
    assert 'CORRECTION REQUIRED' in requests[1]['messages'][0]['content']
    assert len([m for m in messages if m['type']=='response_start'])==2
    assert [m for m in messages if m['type']=='response_start'][-1]['reason']=='grounding_retry'
    if repair_succeeds:
        assert speech.history[-1]['content']=='Current readings and connectivity are unavailable.'
        assert not any('98 BPM' in m['content'] for m in speech.history)
    else:
        assert not speech.history and not any(m['type']=='speech' for m in messages)
        assert 'conflicted' in next(m['detail'] for m in messages if m['type']=='conversation_error')
    await speech.close();await manager.stop()


@pytest.mark.parametrize('text,expected',[
    ('The Handy is moving.',['unverified_physical_motion']),
    ('The Handy is not moving.',['unverified_physical_motion']),
    ('I cannot tell whether the Handy is moving.',[]),
    ('The current edge counter is 9.',['wrong_edges']),
    ('The pause count is 9.',['wrong_pauses']),
    ('The elapsed time is 200 seconds.',['wrong_seconds']),
    ('I changed your intensity.',['read_only_control_claim']),
    ('The derived reading is 98 BPM.',[]),
])
def test_engine_settings_and_disconnection_never_establish_physical_actions(text,expected):
    assert violations(text,BY_NAME['active_simulated'].observation.canonical())==expected


def test_user_report_can_be_acknowledged_without_promoting_it_to_engine_measurement():
    current=BY_NAME['active_simulated'].observation.canonical()
    reported=[{'role':'user','content':'I measured 110 BPM myself.'}]
    assert violations('You said 110 BPM. The simulated EdgeLoop reading is 98 BPM.',current,reported)==[]
    assert violations('Your current heart rate is 110 BPM.',current,reported)


@pytest.mark.parametrize('text,expected',[
    ("I'd wager you're hovering between a resting 68 and a startled 82.",['unsupported_unitless_bpm']),
    ("I'd say you're probably a healthy, bouncing 72.",['unsupported_unitless_bpm']),
    ('The HR is unavailable; this is observation frame 72.',[]),
    ("I'm 72 years old. Current pulse data is unavailable.",[]),
    ('The last update was 72 seconds ago; no current pulse is available.',[]),
])
def test_missing_units_cannot_hide_a_guessed_pulse(text,expected):
    case=BY_NAME['stale_connection']
    assert violations(text,case.observation.canonical(),[{'role':'user','content':'What is my current BPM?'}])==expected


async def test_telemetry_expiring_during_generation_is_rechecked_before_acceptance():
    from tests.fork.grounding_cases import Clock,snapshot,frame
    from ai_observer.observation import BrowserObservation
    from ai_observer.protocol import Observation
    clock=Clock();observation=BrowserObservation(clock.mono,clock.wall)
    observation.accept(Observation.model_validate(frame(snapshot(clock))))
    requests=[]
    def runtime(request):
        if request.url.path=='/api/show':return httpx.Response(200,json={'system':'EXACT CHARACTER','capabilities':['completion']})
        requests.append(json.loads(request.content))
        if len(requests)==1:
            clock.tick(8)
            content='Your current heart rate is 98 BPM.'
        else:content='Current heart rate is unavailable.'
        return httpx.Response(200,text=json.dumps({'message':{'content':content},'done':True,'done_reason':'stop'})+'\n')
    manager=ModelManager(transport=httpx.MockTransport(runtime));manager.current_summary=observation.summary
    await manager.start(AIConfig(thinking=False))
    reply=await manager.reply(observation.summary(),'What is my current BPM?',[])
    assert reply=='Current heart rate is unavailable.' and len(requests)==2
    assert 'UNAVAILABLE / STALE' in requests[1]['messages'][-1]['content']
    await manager.stop()
