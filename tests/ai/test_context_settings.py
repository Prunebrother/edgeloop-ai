# SPDX-License-Identifier: AGPL-3.0-only
from fastapi.testclient import TestClient
from ai_observer.server import create_app
from companion_ai.context_compiler import ContextConfig
from tests.ai.test_f25 import runtime
from tests.fork.test_observer import TOKEN,ORIGIN,auth,until


def test_persistent_backend_budgets_and_explicit_fallback_never_generate(tmp_path):
 wire=[];app=create_app(TOKEN,tmp_path,transport=runtime(wire))
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   auth(ws);cfg=ContextConfig(enabled=False,history_tokens=500).model_dump()
   ws.send_json({'version':1,'type':'configure_context','config':cfg})
   until(ws,'character_state')
   assert app.state.models.context_config.enabled is False and not wire
   cfg['history_tokens']=-1
   ws.send_json({'version':1,'type':'configure_context','config':cfg});until(ws,'protocol_error')
   assert app.state.models.context_config.history_tokens==500
 restored=create_app(TOKEN,tmp_path,transport=runtime(wire))
 assert not restored.state.models.context_config.enabled
 assert restored.state.models.config.thinking is False


def test_objective_protocol_is_authenticated_model_scoped_and_inference_free(tmp_path):
 wire=[];app=create_app(TOKEN,tmp_path,transport=runtime(wire))
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   auth(ws);model=app.state.models.config.model
   ws.send_json({'version':1,'type':'update_objective','model':model,'action':'create','fields':{'premise':'Find the violet notebook.'}})
   state=until(ws,'character_state');assert state['narrative']['objective']['status']=='active'
   assert not wire
   ws.send_json({'version':1,'type':'update_objective','model':'wrong:latest','action':'complete'})
   until(ws,'character_menu_error');assert app.state.speech.narrative.state['objective']['status']=='active'
   ws.send_json({'version':1,'type':'update_objective','model':model,'action':'abandon'})
   state=until(ws,'character_state');assert state['narrative']['objective']['status']=='abandoned'
   assert app.state.speech.narrative.state['context_boundary']
   assert app.state.observation.report is None and not wire


def test_invalid_context_file_preserves_file_and_reports_baseline_fallback(tmp_path):
 from companion_ai.storage import SettingsStore
 store=SettingsStore(tmp_path);store.write('context-intelligence.json',{'schema_version':99})
 app=create_app(TOKEN,tmp_path)
 assert not app.state.models.context_config.enabled
 assert app.state.models.context_config_error and store.read('context-intelligence.json')['schema_version']==99
 app.state.models.configure_context(ContextConfig())
 assert app.state.models.context_config.enabled and app.state.models.context_config_error is None


def test_abandonment_drops_chat_queued_behind_discovery_before_old_story_can_restart(tmp_path):
 import asyncio,threading,httpx
 from companion_ai.models import AIConfig
 entered=threading.Event();release=threading.Event();wire=[]
 mock=runtime(wire,'[[expression:focused]]A fresh garden path waits.')
 async def transport(request):
  if request.url.path=='/api/tags':
   entered.set()
   while not release.is_set():await asyncio.sleep(.01)
   return httpx.Response(200,json={'models':[{'name':'qwen3:8b'}]})
  return mock.handle_request(request)
 app=create_app(TOKEN,tmp_path,transport=httpx.MockTransport(transport))
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   auth(ws);client.portal.call(app.state.models.start,AIConfig())
   model=app.state.models.config.model
   ws.send_json({'version':1,'type':'update_objective','model':model,'action':'create','fields':{'premise':'Find the old notebook.'}});until(ws,'character_state')
   ws.send_json({'version':1,'type':'list_models'});assert entered.wait(2)
   ws.send_json({'version':1,'type':'chat','model':model,'text':'Imagine the old notebook mystery.'})
   ws.send_json({'version':1,'type':'update_objective','model':model,'action':'abandon'})
   until(ws,'character_state');release.set();until(ws,'models')
   ws.send_json({'version':1,'type':'get_character_state','model':model});until(ws,'character_state')
   assert not wire and not app.state.speech.history
   assert app.state.speech.narrative.state['objective']['status']=='abandoned'
