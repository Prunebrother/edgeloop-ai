# SPDX-License-Identifier: AGPL-3.0-only
import httpx,pytest
from fastapi.testclient import TestClient
from ai_observer.server import create_app
from companion_ai.event_intelligence import EventConfig
from companion_ai.storage import SettingsStore
from tests.ai.test_f25 import runtime
from tests.fork.test_observer import TOKEN,ORIGIN,auth,until
from tests.fork.grounding_cases import Clock,snapshot,frame

def test_config_persistence_presets_defaults_and_no_inference(tmp_path):
 wire=[];app=create_app(TOKEN,tmp_path,transport=runtime(wire))
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   auth(ws);ws.send_json({'version':1,'type':'configure_events','preset':'quiet'})
   info=until(ws,'character_state');assert info['events_saved'] and info['event_intelligence']['config']['preset']=='quiet'
   assert app.state.director.config.spontaneous_interval_seconds==300 and not wire
   c=EventConfig().model_dump();c['preset']='custom';c['detectors']['rapid_rise']['threshold_bpm']=18
   c['preferences']['evelyn']['physiology']=0
   ws.send_json({'version':1,'type':'configure_events','config':c});info=until(ws,'character_state')
   assert info['event_intelligence']['config']['detectors']['rapid_rise']['threshold_bpm']==18
   assert info['event_intelligence']['config']['preferences']['daisy']['physiology']==1
   assert SettingsStore(tmp_path).read('event-intelligence.json')['preset']=='custom'
   c['detectors']['rapid_rise']['significance']='critical'
   ws.send_json({'version':1,'type':'configure_events','config':c});until(ws,'protocol_error')
   assert app.state.speech.event_intelligence.config.detectors['rapid_rise'].significance=='major'
   ws.send_json({'version':1,'type':'configure_events','preset':'balanced'});until(ws,'character_state')
   assert not wire
 restored=create_app(TOKEN,tmp_path,transport=runtime(wire));assert restored.state.speech.event_intelligence.config.preset=='balanced'
 assert restored.state.speech.event_intelligence.config.detectors['rapid_rise'].threshold_bpm==15
 assert restored.state.models.config.thinking is False

def test_disabled_event_intelligence_and_preferences_cannot_suppress_original_safety(tmp_path):
 c=Clock();wire=[];app=create_app(TOKEN,tmp_path,clock=c.mono,transport=runtime(wire));app.state.observation.wall=c.wall
 s=snapshot(c)
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   ready=auth(ws);cfg=EventConfig(enabled=False).model_dump();cfg['preferences']['generic']['session']=0
   ws.send_json({'version':1,'type':'configure_events','config':cfg});until(ws,'character_state')
   def observe(seq,kinds):
    f=frame(s,seq,kinds);f['epoch']=ready['epoch'];ws.send_json(f)
    if seq==0:return until(ws,'observation_ack')
   observe(0,[]);c.tick(.3);s['details']['captured_at_ms']=int(c.wall()*1000);s['safety']['no_contact']=True
   observe(1,['no_contact']);speech=until(ws,'speech');assert speech['source']=='safety'
   assert not wire and app.state.observation.report['effective_max']==140
   assert app.state.speech.event_intelligence.history[-1]['event']['significance']=='critical'

def test_typing_is_strict_temporary_and_does_not_generate(tmp_path):
 c=Clock();wire=[];app=create_app(TOKEN,tmp_path,clock=c.mono,transport=runtime(wire))
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   auth(ws);ws.send_json({'version':1,'type':'conversation_activity','model':'qwen3:8b','typing':True})
   ws.send_json({'version':1,'type':'get_character_state','model':'qwen3:8b'});until(ws,'character_state')
   assert app.state.director.typing_until==c.mono()+6 and not wire
   c.tick(7);assert c.mono()>app.state.director.typing_until


def test_celeste_relevance_migrates_old_preferences_and_is_persisted(tmp_path):
 config=EventConfig().model_dump();config['preferences'].pop('celeste')
 old=EventConfig.model_validate(config)
 assert old.preferences['celeste']=={'physiology':1,'session':1,'configuration':1,'story':1}
 old.preferences['celeste']['physiology']=2
 assert old.relevance('celeste-narrative-v1:latest','physiology')==2
 assert old.relevance('celeste-narrative-v2:latest','physiology')==2
 assert old.relevance('evelyn-narrative-v1:latest','physiology')==1
 wire=[];app=create_app(TOKEN,tmp_path,transport=runtime(wire))
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   auth(ws);ws.send_json({'version':1,'type':'configure_events','config':old.model_dump()})
   info=until(ws,'character_state')
   assert info['event_intelligence']['config']['preferences']['celeste']['physiology']==2
 restored=create_app(TOKEN,tmp_path,transport=runtime(wire))
 assert restored.state.speech.event_intelligence.config.relevance('celeste-narrative-v2:latest','physiology')==2
 assert not wire
