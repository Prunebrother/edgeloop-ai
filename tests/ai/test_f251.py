# SPDX-License-Identifier: AGPL-3.0-only
import asyncio,json
from copy import deepcopy
from uuid import uuid4
import httpx,pytest
from fastapi.testclient import TestClient
from ai_observer.observation import BrowserObservation,ObserverDirector
from ai_observer.protocol import Observation
from ai_observer.server import create_app
from companion_ai.conversation import ConversationService,ModelManager
from companion_ai.models import AIConfig,SpeechPolicy
from companion_ai.director import ConversationDirector,DirectorConfig
from companion_ai.context import compose_messages
from companion_ai.fidelity import violations
from tests.fork.grounding_cases import Clock,snapshot,frame,cases
from tests.ai.test_f25 import runtime


def observation():
    c=Clock();o=BrowserObservation(c.mono,c.wall);s=snapshot(c)
    s['details'].update(learning_release_count=0,settle_outcome=None)
    assert o.accept(Observation.model_validate(frame(s)))
    return c,o,s


def change(c,o,s,kind,**updates):
    c.tick(.3);s=deepcopy(s);s.update(updates);s['details']['captured_at_ms']=int(c.wall()*1000)
    f=Observation.model_validate(frame(s,o.sequence+1,[kind]));assert o.accept(f)
    return s,f

@pytest.mark.parametrize('kind,key,current',[('experience_changed','experience','headplay'),('goal_changed','goal','oracle')])
def test_selected_setting_requires_actual_transition_even_idle(kind,key,current):
    c,o,s=observation();s['status']='IDLE';s['details']['warmup_active']=False
    o.report=deepcopy(s)
    s,f=change(c,o,s,kind,**{key:current})
    assert f.events[0].id in o.accepted_event_ids
    assert current in o.events[-1]['evidence']
    # Snapshot repetition and fabricated kinds cannot create a second change.
    s,f=change(c,o,s,kind)
    assert not o.accepted_event_ids

@pytest.mark.parametrize('status,ending,count,mode,accepted',[
    ('RUNNING','premature_release',1,'classic',True),
    ('PAUSED','premature_release',1,'classic',True),
    ('RUNNING',None,1,'classic',True), # zero-duration settle; result IDLE below
    ('IDLE','premature_release',1,'classic',False),
    ('RUNNING','premature_release',0,'classic',False), # refused dialog, no engine write
    ('RUNNING',None,1,'survival',False),
    ('RUNNING',None,1,'calibrate',False),
])
def test_came_early_proof_requires_accepted_engine_write_and_ending(status,ending,count,mode,accepted):
    c,o,s=observation();s.update(status=status,active_mode=mode);s['details']['warmup_active']=status=='RUNNING';o.report=deepcopy(s)
    result=deepcopy(s);result['details'].update(learning_release_count=count,settle_outcome=ending,warmup_active=False)
    result['status']='RUNNING' if ending else 'IDLE'
    result,f=change(c,o,result,'came_early')
    assert bool(o.accepted_event_ids) is accepted
    if accepted:
        assert 'engine accepted premature release' in o.events[-1]['evidence']
        result,duplicate=change(c,o,result,'came_early')
        assert not o.accepted_event_ids

async def test_selection_burst_coalesces_final_state_and_bypasses_spontaneous_cooldowns():
    c,o,s=observation();s['status']='IDLE';o.report=s
    calls=[]
    class Adapter:
        mode='ollama';config=AIConfig()
        async def reply(self,summary,prompt,history):calls.append((summary,prompt));return 'A different approach to explore.'
    director=ObserverDirector(clock=c.mono)
    director.last_spoken=c.mono();director.memory['last_user']=c.mono()-3
    speech=ConversationService(o,lambda _:None,Adapter(),clock=c.mono,director=director)
    for current in ['headplay','milker','ruin']:
        previous=o.report['experience'];o.report=dict(o.report,experience=current)
        speech.enqueue('experience_changed',50,{'previous_experience':previous,'current_experience':current,'previous_goal':'tease','current_goal':'tease'})
        speech.pump();assert not speech.task
        c.tick(.3)
    o.report=dict(o.report,goal='oracle')
    speech.enqueue('goal_changed',50,{'previous_experience':'ruin','current_experience':'ruin','previous_goal':'tease','current_goal':'oracle'})
    assert len(speech.pending)==1
    c.tick(2.1);speech.pump();await speech.task
    assert len(calls)==1
    data=json.loads(calls[0][1].split(': ',1)[1])
    assert data['previous_experience']=='classic' and data['current_experience']=='ruin' and data['current_goal']=='oracle'
    assert calls[0][0]['canonical_session']['facts']['experience']['value']=='ruin'
    assert not speech.pending
    speech.pump();assert len(calls)==1
    await speech.close()

async def test_return_to_original_selection_is_silent():
    c,o,s=observation();speech=ConversationService(o,lambda _:None,clock=c.mono,director=ConversationDirector(clock=c.mono))
    for before,after in [('classic','headplay'),('headplay','classic')]:
        speech.enqueue('experience_changed',50,{'previous_experience':before,'current_experience':after,'previous_goal':'tease','current_goal':'tease'})
    assert not speech.pending and speech.director.last_reason=='selection_returned_to_original'
    await speech.close()

async def test_verified_action_uses_fresh_application_turn_and_thinking_off():
    wire=[];manager=ModelManager(transport=runtime(wire,'[[expression:concerned]]A new direction, then.'))
    await manager.select(AIConfig(model='daisy-qwen35:latest'))
    c,o,s=observation();s['status']='IDLE';s['details']['warmup_active']=False;o.report=s
    messages=[];speech=ConversationService(o,messages.append,manager,clock=c.mono,director=ConversationDirector(clock=c.mono))
    speech.history.append({'role':'assistant','content':'Earlier wording.'})
    s['experience']='headplay'
    speech.enqueue('experience_changed',50,{'previous_experience':'classic','current_experience':'headplay','previous_goal':'tease','current_goal':'tease'})
    c.tick(2.1);speech.pump();await speech.task
    body=wire[-1][1]
    assert body['think'] is False and body['messages'][-1]['role']=='user'
    assert 'APPLICATION EVENT' in body['messages'][-1]['content'] and 'headplay' in body['messages'][-1]['content']
    assert messages[-1]['expression']=='concerned'
    assert not any(m['role']=='user' for m in speech.history)
    assert all('[[' not in m['content'] for m in speech.history)
    await speech.close()


def test_event_transport_turn_is_not_a_user_quotation_or_saved_history():
    messages,_=compose_messages({'conversation_source':'event'},'Verified mode change',[{'role':'assistant','content':'Old reply'}],AIConfig())
    assert messages[-1]['origin']=='system_event' and 'APPLICATION EVENT' in messages[-1]['content']
    assert messages[-2]['role']=='assistant'

@pytest.mark.parametrize('text',[
    'The Handy is physically active.', 'The Handy is disconnected and sitting idle.',
    "The Handy isn't moving.",
])
def test_disconnected_projection_does_not_establish_physical_motion(text):
    canonical=next(c for c in cases() if c.name=='hardware_disconnected_active').observation.canonical()
    assert 'unverified_physical_motion' in violations(text,canonical)


def test_selection_acknowledgement_can_repeat_structure_but_not_an_exact_response():
    director=ConversationDirector()
    director.accepted('You selected headplay with goal tease.',False)
    prompt='Observed application event (not a user request): '+json.dumps({'kind':'goal_changed','previous_goal':'tease','current_goal':'oracle'})
    score=director.assess('You selected headplay with goal oracle.',False,prompt)
    assert score['verified_selection_ack'] and not score['excessive']
    score=director.assess('You selected headplay with goal tease.',False,prompt)
    assert score['excessive']

async def test_deliberate_event_does_not_reinject_old_unsolicited_prose_but_preserves_memory():
    c,o,s=observation();received=[]
    class Adapter:
        config=AIConfig();mode='ollama'
        async def reply(self,summary,prompt,history):received.extend(history);return 'A fresh acknowledgement.'
    speech=ConversationService(o,lambda _:None,Adapter(),clock=c.mono,director=ObserverDirector(clock=c.mono))
    speech.history.extend([{'role':'user','content':'My name is Alex.'},
        {'role':'assistant','content':'Good morning, Alex.','trigger_origin':'real_user'},
        {'role':'assistant','content':'OLD UNSOLICITED OPERATIONAL STORY','trigger_origin':'system_event'}])
    o.report['experience']='headplay' # Fresh transition must still match the current selection.
    speech.enqueue('experience_changed',50,{'previous_experience':'classic','current_experience':'headplay','previous_goal':'tease','current_goal':'tease'})
    c.tick(2.1);speech.pump();await speech.task
    assert any(m['content']=='My name is Alex.' for m in received)
    assert not any('OLD UNSOLICITED' in m['content'] for m in received)
    assert any('OLD UNSOLICITED' in m['content'] for m in speech.history)
    await speech.close()


def test_came_early_is_not_an_early_arrival():
    from companion_ai.fidelity import event_violations
    assert event_violations('You showed up early!',{'kind':'came_early'})
    assert not event_violations('Take your time after that premature release.',{'kind':'came_early'})
    assert not event_violations('You arrived early.',{'kind':'goal_changed'})


def test_normal_ending_stop_preserves_proven_came_early_generation(tmp_path):
    import threading
    from tests.fork.test_observer import TOKEN,ORIGIN,auth,until
    release=threading.Event()
    class Delayed(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"message":{"content":"[[expression:comforting]]"},"done":false}\n'
            while not release.is_set():await asyncio.sleep(.01)
            yield b'{"message":{"content":"Take your time."},"done":true,"done_reason":"stop"}\n'
    def handler(request):
        if request.url.path=='/api/show':return httpx.Response(200,json={'system':'Native identity.','capabilities':['completion']})
        if request.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
        body=json.loads(request.content);assert body['think'] is False
        return httpx.Response(200,stream=Delayed())
    c=Clock();app=create_app(TOKEN,tmp_path,clock=c.mono,transport=httpx.MockTransport(handler));app.state.observation.wall=c.wall
    s=snapshot(c);s['details'].update(learning_release_count=0,settle_outcome=None)
    with TestClient(app) as client:
        with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
            ready=auth(ws)
            ws.send_json({'version':1,'type':'select_model','selection':{'model':'evelyn-lite-v1:latest'}});until(ws,'model_selected')
            def send(seq,kinds):
                f=frame(s,seq,kinds);f['epoch']=ready['epoch'];ws.send_json(f)
            send(0,[]);until(ws,'observation_ack')
            c.tick(.3);s['details'].update(captured_at_ms=int(c.wall()*1000),learning_release_count=1,settle_outcome='premature_release')
            send(1,['came_early']);until(ws,'observation_ack');start=until(ws,'response_start')
            c.tick(.3);s.update(status='IDLE',seconds=0,edges=0);s['details'].update(captured_at_ms=int(c.wall()*1000),settle_outcome=None,warmup_active=False,warmup_remaining_seconds=None,pauses=0)
            send(2,['stop']);ack=until(ws,'observation_ack')
            assert ack['events'][0]['kind']=='stop' and ack['events'][0]['preserve_reaction'] is True
            release.set();speech=until(ws,'speech')
            assert speech['id']==start['id'] and speech['expression']=='comforting' and speech['text']=='Take your time.'
            assert app.state.observation.report['status']=='IDLE'

async def test_selection_changed_during_generation_cannot_publish_or_save_an_obsolete_reaction():
    c,o,s=observation();s['experience']='headplay';o.report=s;gate=asyncio.Event();messages=[]
    class Slow:
        mode='ollama';config=AIConfig();streaming=True;stream_reset=True
        async def reply(self,summary,prompt,history,on_chunk=None,on_expression=None,**kwargs):
            await gate.wait();on_expression('happy');on_chunk('Head Play is selected.');return 'Head Play is selected.'
    speech=ConversationService(o,messages.append,Slow(),clock=c.mono,director=ObserverDirector(clock=c.mono))
    speech.enqueue('experience_changed',50,{'previous_experience':'classic','current_experience':'headplay','previous_goal':'tease','current_goal':'tease'})
    c.tick(2.1);speech.pump();await asyncio.sleep(0)
    o.report=dict(o.report,experience='ruin');gate.set();await speech.task
    assert not speech.history and not any(m['type'] in {'speech','response_expression'} for m in messages)
    assert messages[-1]['reason']=='selection_superseded'
    await speech.close()
