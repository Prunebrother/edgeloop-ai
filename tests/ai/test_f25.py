# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import json
from copy import deepcopy
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from companion_ai.expressions import EXPRESSIONS, ExpressionStream, clean_dialogue
from companion_ai.models import AIConfig, MemoryConfig, SpeechPolicy
from companion_ai.llm import OllamaProvider, LLMRequest, ChatMessage, collect_reply, InferenceCompatibilityError
from companion_ai.conversation import ModelManager, ConversationService
from companion_ai.director import DirectorConfig
from companion_ai.storage import SettingsStore
from companion_ai.event_policy import significance
from ai_observer.server import create_app
from tests.ai.support import ObservationFixture

@pytest.mark.parametrize('expression', EXPRESSIONS)
def test_every_chunk_boundary(expression):
    text='[[expression:'+expression+']]Hello there.'
    for split in range(len(text)+1):
        seen=[];parser=ExpressionStream(seen.append)
        visible=parser.feed(text[:split])+parser.feed(text[split:])+parser.finish()
        assert visible=='Hello there.' and seen==[expression]
    parser=ExpressionStream()
    assert ''.join(parser.feed(c) for c in text)=='Hello there.'
    assert parser.expression==expression

@pytest.mark.parametrize('text,expected,expression',[
    ('A [','A [',None),
    ('A <','A <',None),
    ('Plain text [a] and [[ordinary]] brackets.','Plain text [a] and [[ordinary]] brackets.',None),
    ('[[tone:playful]]Hello','Hello',None),
    ('[[expression=happy]]Hello','Hello',None),
    ('[[ordinary','[[ordinary',None),
    ('[['+'prose '*100+']]','[['+'prose '*100+']]',None),
    ('[[happy:98]]Hello','Hello',None),
    ('[[expression:unknown]]Hello','Hello',None),
    ('[[expression:happy]][[expression:proud]]Hello','Hello','happy'),
    ('Hello [[expression:proud]]there','Hello there',None),
    ('[[expression:hap','',None),
    ('[[expr','',None),
    ('<think>PRIVATE [[expression:happy]]</think>[[expression:focused]]Hello','Hello','focused'),
    ('<think>PRIVATE','',None),
    ('[[expression:'+('x'*10000)+']]Hello','Hello',None),
    ('[[expression:bad\nHello','Hello',None),
])
def test_untrusted_bounded_envelope(text,expected,expression):
    parser=ExpressionStream();out=''
    for c in text:
        out+=parser.feed(c)
        assert len(parser.pending)<=13 and len(parser.envelope)<=64
    assert out+parser.finish()==expected and parser.expression==expression


def runtime(wire, content='[[expression:proud]]A clear answer.'):
    def handler(request):
        body=json.loads(request.content) if request.content else {}
        if request.url.path=='/api/show':return httpx.Response(200,json={'system':'Native character personality.','thinking':{'values':[True,False]},'capabilities':['completion','thinking']})
        if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':m} for m in ['evelyn-lite-v1:latest','evelyn-qwen35-stable:latest','daisy-qwen35:latest','brand-new:latest']]})
        if request.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
        wire.append((request.url.path,body))
        if request.url.path=='/api/generate':return httpx.Response(200,json={'done':True})
        rows=[{'message':{'thinking':'PRIVATE REASONING [[expression:concerned]]'},'done':False}]
        rows += [{'message':{'content':c},'done':False} for c in content]
        rows += [{'message':{},'done':True,'done_reason':'stop'}]
        return httpx.Response(200,text='\n'.join(map(json.dumps,rows))+'\n')
    return httpx.MockTransport(handler)

async def test_discovery_switch_restoration_event_and_generate_payloads(tmp_path):
    wire=[];store=SettingsStore(tmp_path)
    store.write('selection.json',{'config':{'thinking':True}})
    manager=ModelManager(transport=runtime(wire),store=store)
    assert manager.config.thinking is False
    messages=[];speech=ConversationService(ObservationFixture(),messages.append,manager)
    manager.memory=MemoryConfig(persist_between_sessions=True)
    models=await manager.provider().discover()
    for model in models:
        await manager.select(AIConfig(model=model['name']))
        speech.activate_model()
        speech.request('Hello',True);await speech.task
        result=next(m for m in reversed(messages) if m['type']=='speech')
        assert result['expression']=='proud' and result['text']=='A clear answer.'
        assert speech.history[-1]['expression']=='proud'
        assert '[[expression' not in json.dumps([m['content'] for m in speech.history])
        restored=ConversationService(ObservationFixture(),lambda m:None,manager)
        assert restored.history[-1]['content']=='A clear answer.'
        await restored.close()
    speech.busy_until=0;speech.policy=SpeechPolicy(min_interval_seconds=0.0,user_grace_seconds=0.0)
    speech.request('Observed application event: milestone',False);await speech.task
    assert messages[-1]['source']=='event'
    provider=manager.provider();await provider.unload(force=True)
    assert wire[-1][0]=='/api/generate'
    assert all(body['think'] is False for _,body in wire)
    for _,body in wire:
        if 'messages' in body:assert body['messages'][0]['content'].startswith('Native character personality.\n\n')
    assert 'PRIVATE' not in json.dumps(messages) and 'PRIVATE' not in json.dumps(list(speech.history))
    await speech.close()

async def test_compatibility_failure_never_retries():
    wire=[]
    def reject(request):
        if request.url.path=='/api/show':return httpx.Response(200,json={'thinking':{'values':[True]}})
        wire.append(json.loads(request.content));return httpx.Response(400,json={'error':'Unsupported think'})
    provider=OllamaProvider('required',transport=httpx.MockTransport(reject))
    with pytest.raises(InferenceCompatibilityError):await collect_reply(provider,LLMRequest(AIConfig(model='required'),(ChatMessage('user','Hi'),)))
    assert not wire
    provider=OllamaProvider('reject',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={}) if r.url.path=='/api/show' else httpx.Response(400,json={'error':'think not supported'})))
    with pytest.raises(InferenceCompatibilityError,match='no fallback'):await collect_reply(provider,LLMRequest(AIConfig(model='reject'),(ChatMessage('user','Hi'),)))

async def test_disable_explicit_expressions_still_removes_metadata():
    wire=[];seen=[];config=AIConfig(explicit_expressions=False)
    result=await collect_reply(OllamaProvider(config.model,transport=runtime(wire)),LLMRequest(config,(ChatMessage('user','Hi'),)),on_expression=seen.append)
    assert result=='A clear answer.' and not seen and wire[-1][1]['think'] is False

async def test_cancel_does_not_save_partial_metadata_or_dialogue():
    class Slow:
        streaming=True;stream_reset=True;config=AIConfig()
        async def reply(self,*args,on_chunk,on_expression,**kwargs):
            on_expression('happy');on_chunk('Unfinished')
            await asyncio.Event().wait()
    messages=[];speech=ConversationService(ObservationFixture(),messages.append,Slow())
    speech.request('Hi',True);await asyncio.sleep(0);speech.interrupt();await speech.task
    assert not speech.history and not any(m['type']=='speech' for m in messages)
    await speech.close()


def test_event_classification_uses_actual_contract_only():
    previous={'devices':{'ble':True},'status':'RUNNING'}
    current={'devices':{'ble':False},'status':'RUNNING'}
    for kind in ['edge','milestone','stop','session_started','session_resumed']:assert significance(kind,previous,current)==('major',50)
    for kind in ['signal_lost','no_contact','device_changed']:assert significance(kind,previous,current)==('critical',100)
    for kind in ['threshold_changed','mode_changed','made_up_goal_completion']:assert significance(kind,previous,current)==('routine',10)


def test_observer_reconnect_default_off_and_validated_event_payload(tmp_path):
    from tests.fork.test_observer import TOKEN, ORIGIN, snapshot, frame, auth, until
    wire=[];app=create_app(TOKEN,tmp_path,transport=runtime(wire))
    # Test the same scheduler with clocks/cooldowns removed, never production policy.
    app.state.director.config=DirectorConfig(spontaneous_interval_seconds=0.0,user_idle_before_spontaneous_seconds=0.0,category_cooldowns={})
    app.state.speech.policy=SpeechPolicy(min_interval_seconds=0.0,user_grace_seconds=0.0)
    browser=str(uuid4());state=snapshot();state['seconds']=299
    with TestClient(app) as client:
        with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
            ready=auth(ws,browser)
            ws.send_json({'version':1,'type':'select_model','selection':{'model':'brand-new:latest'}});assert until(ws,'model_selected')['thinking'] is False
            ws.send_json(frame(ready['epoch'],state=state));until(ws,'observation_ack')
            import time;time.sleep(.11)
            state['seconds']=300
            event={'id':str(uuid4()),'kind':'milestone','session_id':state['session_id']}
            ws.send_json(frame(ready['epoch'],1,state,[event]));until(ws,'observation_ack')
            result=until(ws,'speech');assert result['source']=='event' and result['expression']=='proud'
        with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
            ready=auth(ws,browser)
            ws.send_json({'version':1,'type':'select_model','selection':{'model':'brand-new:latest'}});assert until(ws,'model_selected')['thinking'] is False
            ws.send_json(frame(ready['epoch'],state=state,events=[event]));until(ws,'observation_ack')
            assert not app.state.speech.pending
            ws.send_json({'version':1,'type':'chat','model':'brand-new:latest','text':'Hello again'});until(ws,'speech')
    assert wire and all(b['think'] is False for _,b in wire)


def test_backend_inference_config_rejects_on_and_can_disable_expressions(tmp_path):
    from ai_observer.config import RuntimeConfig
    path=tmp_path/'ai.toml'
    path.write_text('[inference]\nthinking = true\n')
    with pytest.raises(ValueError,match='requires'):RuntimeConfig.load({'EDGELOOP_AI_CONFIG':str(path)})
    path.write_text('[inference]\nthinking = false\nexplicit_expressions = false\n')
    config=RuntimeConfig.load({'EDGELOOP_AI_CONFIG':str(path)})
    assert config.thinking is False and config.explicit_expressions is False


async def test_routine_events_cannot_queue_in_observer_and_busy_generation_is_not_interrupted(tmp_path):
    # Direct policy tests complement the full validated websocket milestone test.
    from companion_ai.director import ConversationDirector
    director=ConversationDirector(DirectorConfig(spontaneous_interval_seconds=0.0,user_idle_before_spontaneous_seconds=0.0,category_cooldowns={}))
    class Slow:
        mode='ollama';streaming=True;config=AIConfig()
        async def reply(self,*args,on_chunk=None):
            await asyncio.Event().wait()
    state=ObservationFixture();state.report['status']='RUNNING';state.session_id=state.report['session_id']
    speech=ConversationService(state,lambda _:None,Slow(),director=director)
    speech.policy=SpeechPolicy(min_interval_seconds=0.0,user_grace_seconds=0.0,interruption='interrupt')
    speech.request('Hello',True);await asyncio.sleep(0)
    active=speech.task
    speech.enqueue('milestone',50,{'session_id':state.session_id,'significance':'major'})
    speech.pump()
    assert speech.task is active and not active.cancelled() and speech.pending
    speech.adapter.config=AIConfig(model='different:latest');speech.activate_model()
    assert not speech.pending
    speech.interrupt();await active;await speech.close()


def test_routine_observer_updates_never_trigger_inference(tmp_path):
    from tests.fork.test_observer import TOKEN,ORIGIN,snapshot,frame,auth,until
    import time
    wire=[];app=create_app(TOKEN,tmp_path,transport=runtime(wire))
    with TestClient(app) as client:
        with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
            ready=auth(ws);state=snapshot()
            ws.send_json({'version':1,'type':'select_model','selection':{'model':'brand-new:latest'}});until(ws,'model_selected')
            ws.send_json(frame(ready['epoch'],state=state));until(ws,'observation_ack')
            time.sleep(.11);state['intensity']=80
            event={'id':str(uuid4()),'kind':'intensity_changed','session_id':state['session_id']}
            ws.send_json(frame(ready['epoch'],1,state,[event]));until(ws,'observation_ack')
            time.sleep(.3)
            assert not wire and not app.state.speech.pending
            assert app.state.director.recent_observations[-1]['kind']=='intensity_changed'


@pytest.mark.parametrize('text',[
    'The simulator is pushing your heart rate to 98 BPM.',
    "You're standing there while the simulator counts an edge.",
    'Your pulse is racing with the session.',
    "You're perfectly safe.",
])
def test_live_observed_physical_claims_are_not_established_by_simulation(text):
    from tests.fork.grounding_cases import cases
    from companion_ai.fidelity import violations
    canonical=next(c for c in cases() if c.name=='active_simulated').observation.canonical()
    assert violations(text,canonical)

@pytest.mark.parametrize('text',[
    'The simulated reading is 98 BPM.',
    'Your heart rate is simulated at 98 BPM.',
    'I cannot determine whether you are standing.',
    'The verified engine edge counter increased.',
])
def test_simulation_labels_uncertainty_and_engine_events_remain_valid(text):
    from tests.fork.grounding_cases import cases
    from companion_ai.fidelity import violations
    canonical=next(c for c in cases() if c.name=='active_simulated').observation.canonical()
    assert not violations(text,canonical)
