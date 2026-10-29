# SPDX-License-Identifier: AGPL-3.0-only
import asyncio,json
import httpx,pytest
from fastapi.testclient import TestClient
from ai_observer.server import create_app
from ai_observer.protocol import Messages
from companion_ai.conversation import ConversationService,ModelManager
from companion_ai.models import AIConfig,MemoryConfig
from companion_ai.narrative import NarrativeMemory,NarrativeConfig
from companion_ai.storage import SettingsStore
from companion_ai.director import DirectorConfig
from tests.ai.test_f251 import observation
from tests.ai.test_f25 import runtime
from tests.fork.test_observer import TOKEN,ORIGIN,auth,until

def test_authenticated_director_settings_are_strict_persisted_and_inference_free(tmp_path):
    wire=[];app=create_app(TOKEN,tmp_path,transport=runtime(wire))
    with TestClient(app) as client:
        with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
            auth(ws)
            ws.send_json({'version':1,'type':'get_character_state','model':'qwen3:8b'})
            state=until(ws,'character_state');assert state['director']['proactive_enabled']
            ws.send_json({'version':1,'type':'configure_director','proactive_enabled':False})
            state=until(ws,'character_state');assert state['director_saved'] and not state['director']['proactive_enabled']
            assert SettingsStore(tmp_path).read('director.json')['spontaneous_enabled'] is False
            ws.send_json({'version':1,'type':'configure_director','proactive_enabled':'false'})
            assert until(ws,'protocol_error')
            assert not app.state.director.config.spontaneous_enabled and not wire
            ws.send_json({'version':1,'type':'reset_narrative','model':'other:latest'})
            assert until(ws,'character_menu_error')['model']=='other:latest'
    restored=create_app(TOKEN,tmp_path,transport=runtime(wire))
    assert restored.state.director.config.spontaneous_enabled is False
    assert restored.state.models.config.thinking is False and not wire

@pytest.mark.parametrize('message',[
 {'type':'configure_director','proactive_enabled':False,'hardware':'stop'},
 {'type':'configure_director','proactive_enabled':0},
 {'type':'get_character_state','model':'evelyn:latest','raw':True},
 {'type':'reset_narrative','model':'evelyn:latest','clear_transcript':True},
])
def test_menus_expose_no_extra_controls(message):
    with pytest.raises(ValueError):Messages.validate_python({'version':1,**message})

async def test_reset_epoch_excludes_old_inference_and_retains_transcript_and_session(tmp_path):
    c,o,s=observation();wire=[];store=SettingsStore(tmp_path);m=ModelManager(transport=runtime(wire,'[[expression:focused]]A fresh page.'),store=store)
    m.memory=MemoryConfig(persist_between_sessions=True);await m.select(AIConfig(model='evelyn-narrative-v1:latest'))
    messages=[];speech=ConversationService(o,messages.append,m,clock=c.mono)
    speech.request('Imagine an abandoned blue envelope story.',user=True);await speech.task
    old=speech.narrative.state['epoch'];transcript=list(speech.history);canonical=o.canonical()
    speech.director.memory['questions'].append('old mystery?');speech.director.memory['event_responses'].append({'role':'assistant','content':'The abandoned blue envelope returns.'})
    speech.enqueue('experience_changed',50,{'current_experience':'headplay'})
    speech.reset_narrative();assert speech.narrative.state['epoch']!=old and list(speech.history)==transcript
    assert not speech.pending and not speech.director.memory['questions'] and not speech.director.memory['event_responses']
    assert o.canonical()==canonical
    speech.request('Imagine a garden scene instead.',user=True);await speech.task
    payload=wire[-1][1];assert payload['think'] is False
    assert not any('abandoned blue envelope' in x['content'] for x in payload['messages'])
    assert any('abandoned blue envelope' in x['content'] for x in speech.history)
    assert speech.history[-1]['narrative_epoch']==speech.narrative.state['epoch']
    # Default narrative persistence is OFF; the explicit reset boundary still
    # survives restart alongside independently persisted conversation history.
    restored_wire=[];other=ModelManager(transport=runtime(restored_wire,'[[expression:happy]]A garden path.'),store=store);other.config=m.config
    restored=ConversationService(o,lambda _:None,other,clock=c.mono)
    assert restored.narrative.state['context_boundary']
    assert restored.narrative.state['epoch']==speech.narrative.state['epoch']
    assert restored.narrative.context()['premise'] is None
    await other.select(m.config)
    restored.request('Continue the fresh garden scene.',user=True);await restored.task
    assert not any('abandoned blue envelope' in message['content'] for message in restored_wire[-1][1]['messages'])
    await restored.close();await speech.close()

async def test_stubborn_inflight_generation_cannot_restore_reset_story():
    c,o,s=observation();started=asyncio.Event();release=asyncio.Event();messages=[]
    class Slow:
        config=AIConfig(model='evelyn:latest')
        async def reply(self,*args,**kw):
            started.set()
            try:await release.wait()
            except asyncio.CancelledError:pass
            return 'The old blue envelope returns.'
    speech=ConversationService(o,messages.append,Slow(),clock=c.mono)
    speech.request('Imagine an old blue envelope.',user=True);await started.wait()
    old=speech.narrative.state['epoch'];speech.reset_narrative();release.set();await speech.task
    assert speech.narrative.state['epoch']!=old and not speech.history
    assert not any(m['type']=='speech' for m in messages)
    assert speech.narrative.context()['premise'] is None
    await speech.close()

def test_reset_is_model_specific_and_boundary_survives_new_session(tmp_path):
    n=NarrativeMemory(store=SettingsStore(tmp_path));n.activate('evelyn','one');n.accepted('Imagine a blue envelope.','A clue waits.',True)
    n.activate('daisy','one');n.accepted('Imagine a violet letter.','A farm mystery.',True);daisy=n.context()
    n.activate('evelyn','one');n.reset();epoch=n.state['epoch'];n.activate('daisy','one');assert n.context()==daisy
    n.activate('evelyn','two');assert n.state['context_boundary'] and n.state['epoch']==epoch and not n.context()['premise']

def test_read_only_state_reports_real_cooldown_and_same_session_event():
    c,o,s=observation();speech=ConversationService(o,lambda _:None,clock=c.mono)
    speech.director.config=DirectorConfig();speech.director.last_spoken=c.mono()
    speech.last_validated_event={'kind':'goal_changed','significance':'major','session_id':o.session_id,'received':c.mono()}
    info=speech.character_state();assert info['director']['cooldown_seconds']==120
    assert info['director']['last_event']['kind']=='goal_changed'
    c.tick(5);assert speech.character_state()['director']['cooldown_seconds']==115
    speech.last_validated_event['session_id']='old';assert speech.character_state()['director']['last_event'] is None


def test_menu_recent_event_comes_from_validated_transition_without_inference(tmp_path):
    from tests.fork.grounding_cases import Clock,snapshot,frame
    c=Clock();wire=[];app=create_app(TOKEN,tmp_path,clock=c.mono,transport=runtime(wire));app.state.observation.wall=c.wall;s=snapshot(c)
    with TestClient(app) as client:
        with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
            ready=auth(ws)
            ws.send_json({'version':1,'type':'configure_director','proactive_enabled':False});until(ws,'character_state')
            def observe(sequence):
                f=frame(s,sequence,['goal_changed']);f['epoch']=ready['epoch'];ws.send_json(f);return until(ws,'observation_ack')
            observe(0);assert app.state.speech.character_state()['director']['last_event'] is None
            c.tick(.3);s['goal']='oracle';s['details']['captured_at_ms']=int(c.wall()*1000)
            assert not observe(1)['rejected_events']
            ws.send_json({'version':1,'type':'get_character_state','model':'qwen3:8b'})
            event=until(ws,'character_state')['director']['last_event'];assert event['kind']=='goal_changed' and event['significance']=='major'
            assert not wire and app.state.observation.report['goal']=='oracle'
            assert not app.state.speech.pending
            ws.send_json({'version':1,'type':'configure_director','proactive_enabled':True});until(ws,'character_state')
            c.tick(3);app.state.speech.pump();assert not wire and not app.state.speech.task
