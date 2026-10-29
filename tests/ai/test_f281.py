"""Physical-feedback regressions, synthetic engine snapshots only; no hardware/LLM."""
import asyncio
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import pytest
from ai_observer.protocol import Observation,Messages
from companion_ai.conversation import ConversationService
from companion_ai.context import compose_messages
from companion_ai.director import ConversationDirector
from companion_ai.event_policy import significance
from companion_ai.fidelity import violations
from companion_ai.models import AIConfig
from companion_ai.narrative import NarrativeMemory,NarrativeConfig
from companion_ai.storage import SettingsStore
from tests.ai.test_f251 import observation,change
from tests.fork.grounding_cases import frame

JOURNAL=dict(premise="Evelyn is compiling a fictional research journal comparing session duration, pacing and verified milestones.",
 motivation="To investigate patterns in reliable EdgeLoop observations and the user's voluntary feedback, without drawing medical conclusions.",
 next_development="After a completed session, Evelyn reviews the available session summary and discusses an interesting observation for her research journal.",
 transition_condition="Conclude the current journal chapter after a verified session completion and reflection.")

@pytest.mark.parametrize('mode,outcome,status,accepted',[
 ('calibrate','calibration_completed','IDLE',True),('survival','survival_restart','RUNNING',True),
 ('classic','manual_stop','IDLE',False),('classic','premature_release','IDLE',False),
 ('classic',None,'IDLE',False),('calibrate',None,'IDLE',False),('classic','calibration_completed','IDLE',False)])
def test_completion_requires_mode_specific_accepted_original_outcome(mode,outcome,status,accepted):
 c,o,s=observation();o.report['active_mode']=s['active_mode']=mode
 s['details'].update(terminal_outcome=outcome,warmup_active=False)
 s,f=change(c,o,s,'completion_accepted',status=status)
 assert bool(o.accepted_event_ids)==accepted
 if accepted:assert significance('completion_accepted',None,s)==('major',70)
 s,f=change(c,o,s,'completion_accepted');assert not o.accepted_event_ids

@pytest.mark.parametrize('status', ['RUNNING','PAUSED'])
@pytest.mark.parametrize('timestamp', [True,False])
def test_final_counter_survives_reset_and_is_not_wall_clock(status,timestamp):
 c,o,s=observation();s['seconds']=937;s['status']=status;o.report=deepcopy(s)
 s['details'].update(terminal_outcome='manual_stop',warmup_active=False)
 if not timestamp:
  s['details']=None
  c.tick(.3);f=Observation.model_validate({'version':1,'type':'observation','epoch':str(uuid4()),'sequence':o.sequence+1,'snapshot':dict(s,status='IDLE',seconds=0),'events':[]});assert o.accept(f)
 else:s,_=change(c,o,s,'stop',status='IDLE')
 record=o.completed()[-1]
 assert record['active_running_seconds']==(937 if timestamp else None)
 assert record['wall_clock_seconds'] is None and record['paused_seconds'] is None
 if timestamp:
  s,_=change(c,o,s,'stop',seconds=0,edges=0)
  assert o.canonical()['facts']['seconds']['value']==0
  assert o.completed()[-1]['active_running_seconds']==937 and len(o.completed())==1


def test_summary_sensor_availability_scope_retention_restart_and_staleness():
 c,o,s=observation();o.model_scope='evelyn';s['devices'].update(simulated_hr=False,hr_ready=False,ble=False);s['hr']=None
 s['details'].update(terminal_outcome='manual_stop',warmup_active=False);s,_=change(c,o,s,'stop',status='IDLE')
 assert not o.completed()[-1]['sensor_available'] and o.completed()[-1]['measurement_source']=='unavailable'
 previous=o.completed()[-1];s['session_id']=str(uuid4());s['details']['terminal_outcome']=None
 s,_=change(c,o,s,'session_started',status='RUNNING',seconds=0)
 assert o.completed()[-1]['session_id']==previous['session_id']
 o.model_scope='daisy';assert o.completed()==[]
 o.model_scope='evelyn';c.tick(86401);assert o.completed()[-1]['stale'] and not o.canonical()['current']
 for i in range(12):o.completed_sessions.append(deepcopy(o.completed_sessions[-1]))
 assert len(o.completed_sessions)==8 and len(o.completed())==3


async def test_completion_cooldowns_generation_stop_reset_duplicate_and_restart():
 c,o,s=observation();messages=[];gate=asyncio.Event()
 class Adapter:
  config=AIConfig(model='daisy-narrative-v1:latest');mode='ollama'
  async def reply(self,*args,**kw):await gate.wait();return 'A fine conclusion. Rest well.'
 d=ConversationDirector(clock=c.mono);service=ConversationService(o,messages.append,Adapter(),clock=c.mono,director=d)
 d.last_spoken=d.last_reaction=c.mono();d.memory['last_user']=c.mono();service.last_event=c.mono()
 service.event_intelligence.commentary_at['session_milestone']=c.mono()
 details={'event_id':'accepted','session_id':o.session_id}
 service.enqueue('completion_accepted',70,details);service.pump();await asyncio.sleep(0)
 assert service.task and not service.task.done()
 service.enqueue('completion_accepted',70,details);assert not service.pending
 service.safety('stop');o.report.update(status='IDLE',seconds=0);gate.set();await service.task
 assert sum(m['type']=='speech' and m['source']=='event' for m in messages)==1
 service.pump();assert not service.pending
 # New session boundary invalidates even an adapter that ignores cancellation.
 gate.clear();service.enqueue('completion_accepted',70,{'event_id':'second','session_id':o.session_id});service.pump();await asyncio.sleep(0)
 o.session_id=str(uuid4());o.report['session_id']=o.session_id;gate.set();await service.task
 assert sum(m['type']=='speech' and m['source']=='event' for m in messages)==1
 await service.close()


async def test_event_during_generation_waits_and_stale_start_cannot_follow_stop():
 c,o,s=observation();messages=[];gate=asyncio.Event()
 class Adapter:
  config=AIConfig();mode='ollama'
  async def reply(self,summary,*a,**k):
   await gate.wait()
   return 'Good evening.' if summary['conversation_source']=='user' else 'We can close here.'
 service=ConversationService(o,messages.append,Adapter(),clock=c.mono,director=ConversationDirector(clock=c.mono))
 service.request('Hello',user=True);await asyncio.sleep(0)
 service.enqueue('completion_accepted',70,{'event_id':'during','session_id':o.session_id});service.pump();assert service.pending
 gate.set();await service.task;service.pump();await service.task
 assert any(m['type']=='speech' and m['source']=='event' for m in messages)
 o.report.update(status='IDLE')
 assert not service.reaction_current({'trigger_event':{'kind':'session_started','session_id':o.session_id}})
 assert service.reaction_current({'trigger_event':{'kind':'completion_accepted','session_id':o.session_id}})
 await service.close()


def test_journal_objective_lifecycle_plan_context_persistence_and_model_isolation(tmp_path):
 n=NarrativeMemory(NarrativeConfig(persist_between_sessions=True),SettingsStore(tmp_path));n.activate('evelyn','one')
 n.update_objective('create',JOURNAL);identity=n.state['objective']['id']
 n.update_objective('update',{'next_development':'Reflect on verified session milestones.'})
 n.activate('daisy','one');assert not n.state['objective']
 n.activate('evelyn','one');assert n.state['objective']['id']==identity
 c,o,s=observation();summary=o.summary()|{'conversation_source':'event','trigger_event':{'kind':'completion_accepted','session_id':o.session_id},'narrative_context':n.context(True)}
 messages,warning=compose_messages(summary,'A verified session completion',[],AIConfig())
 assert 'research journal' in str(messages)
 restored=NarrativeMemory(NarrativeConfig(persist_between_sessions=True),SettingsStore(tmp_path));restored.activate('evelyn','new')
 assert restored.state['objective']['status']=='paused'
 n.update_objective('complete');n.update_objective('create',JOURNAL);n.update_objective('abandon');assert 'research journal' not in str(n.context())
 n.reset();assert n.state['objective'] is None
 n.accepted('Imagine a journal comparing verified session milestones. I will reflect after the session.','Agreed.',True)
 assert 'journal' in str(n.context())

@pytest.mark.parametrize('text,field', [('Adjust the stimulation transport accordingly.','motivation'),('Reach 180 BPM.','next_development'),('The data proves medical health.','premise')])
def test_objective_fields_allow_unrestricted_fictional_content(text,field):
 n=NarrativeMemory();n.activate('e','s')
 n.update_objective('create',JOURNAL|{field:text})
 assert n.state['objective'][field]==text

@pytest.mark.parametrize('action',['invalid','delete',''])
def test_invalid_lifecycle_is_action_specific(action):
 n=NarrativeMemory();n.activate('e','s')
 with pytest.raises(ValueError,match='lifecycle'):n.update_objective(action,JOURNAL)

@pytest.mark.parametrize('text', ["I'll adjust the stimulation transport accordingly.","I've changed the stroke speed.",'The Polar H10 is working normally.','The sensor recorded physiological changes.','Your heart rate is rising.','The data confirms your excitement.'])
def test_disconnected_sensor_and_authority_claims_are_rejected(text):
 c,o,s=observation();o.report['devices'].update(simulated_hr=False,ble=False,hr_ready=False)
 assert violations(text,o.canonical(),[{'role':'user','content':'I feel excited.'}])

@pytest.mark.parametrize('text', ['You can adjust the intensity yourself.',"I cannot adjust the stimulation transport.",'In the story, I adjust the fictional device.','You said you feel excited.','The sensor is unavailable.','Rest well. Goodbye.'])
def test_dialogue_fiction_and_user_reports_remain_free(text):
 c,o,s=observation();assert not violations(text,o.canonical())


def test_completed_duration_context_and_zero_rejection():
 c,o,s=observation();s['details'].update(terminal_outcome='manual_stop',warmup_active=False);s,_=change(c,o,s,'stop',status='IDLE');s,_=change(c,o,s,'stop',seconds=0)
 messages,_=compose_messages(o.summary()|{'conversation_source':'user'},'How long did the previous session last?',[],AIConfig())
 assert 'COMPLETED SESSIONS' in str(messages) and 'active_running_seconds' in str(messages)
 assert 'wrong_completed_duration' in violations('The previous session lasted 0 seconds.',o.canonical(),completed=o.completed())
 assert not violations('The previous session lasted 42 seconds of active running time.',o.canonical(),completed=o.completed())
 assert 'unavailable_completed_duration' in violations('The previous session lasted 0 seconds.',o.canonical())


def test_character_canon_remains_native_and_runtime_has_no_competing_persona():
 root=Path(__file__).resolve().parents[2]
 celeste=(root/'characters/models/celeste-narrative-v2/Modelfile').read_text()
 assert 'Laurent Armand:\nYour husband, whom you still love.' in celeste
 assert 'The participant:\nInitially' in celeste and 'senior\ndiplomat' in celeste
 assert 'Asterion Institute' in (root/'characters/models/evelyn-narrative-v1/Modelfile').read_text()
 assert 'Cloverfield' in (root/'characters/models/daisy-narrative-v1/Modelfile').read_text()
 c,o,s=observation()
 for name in ('evelyn-narrative-v1','daisy-narrative-v1','celeste-narrative-v2'):
  history=[{'role':'user','content':f'Turn {i}: Tell me about Laurent.'} for i in range(40)]
  messages,_=compose_messages(o.summary()|{'conversation_source':'user'},'Who is Laurent to you?',history,AIConfig(model=name+':latest'))
  assert 'named third parties' in messages[0]['content'] and 'scientist' not in messages[0]['content'].lower()


def test_objective_endpoint_contract_refresh_and_diagnostic_errors(tmp_path):
 from fastapi.testclient import TestClient
 from ai_observer.server import create_app
 from tests.fork.test_observer import TOKEN,ORIGIN,auth,until
 from tests.fork.test_observer import Reply
 app=create_app(TOKEN,tmp_path,adapter=Reply());model=app.state.models.config.model
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   auth(ws)
   def objective(action,fields=None):
    ws.send_json(dict(version=1,type='update_objective',model=model,action=action,fields=fields))
   objective('create',JOURNAL)
   state=until(ws,'character_state');assert state['objective_saved'] and state['narrative']['objective']['premise']==JOURNAL['premise']
   objective('update',{'motivation':'Review voluntary feedback.'});assert until(ws,'character_state')['narrative']['objective']['revision']==1
   objective('update',{'motivation':'Change the stroker speed.'});assert until(ws,'character_state')['narrative']['objective']['motivation']=='Change the stroker speed.'
   objective('create',JOURNAL);assert until(ws,'character_menu_error')['code']=='objective_lifecycle'
   objective('invalid');assert until(ws,'protocol_error')['errors']
   objective('complete');assert until(ws,'character_state')['narrative']['objective']['status']=='completed'
   objective('create',JOURNAL);until(ws,'character_state')
   objective('abandon');assert until(ws,'character_state')['narrative']['objective']['status']=='abandoned'
   ws.send_json(dict(version=1,type='update_objective',model='other:latest',action='create',fields=JOURNAL));assert 'changed' in until(ws,'character_menu_error')['detail']


def test_objective_persistence_failure_rolls_back_memory_and_does_not_cancel(tmp_path):
 c,o,s=observation()
 class Adapter:
  config=AIConfig();narrative_config=NarrativeConfig(persist_between_sessions=True);store=SettingsStore(tmp_path)
 service=ConversationService(o,lambda _:None,Adapter(),clock=c.mono)
 before=deepcopy(service.narrative.state);generation=service.generation
 def fail(*args):raise OSError('private path is not serialized')
 service.narrative.store.write=fail
 with pytest.raises(OSError):service.update_objective('create',JOURNAL)
 assert service.narrative.state==before and service.generation==generation


def test_live_measurement_requires_current_samples_not_displayed_value_or_sensation():
 c,o,s=observation();o.report['devices'].update(simulated_hr=False,ble=True,hr_ready=True)
 assert o.hr_current()
 assert 'unsupported_trend' in violations('Your heart rate is rising.',o.canonical(),[{'role':'user','content':'I feel excited.'}])
 c.tick(6);assert not o.hr_current()
 assert 'unsupported_live_sensor' in violations('The Polar H10 is working normally.',o.canonical())
 assert violations('Your current heart rate is 98 BPM.',o.canonical())


async def test_each_model_gets_own_conversational_scope_and_native_completion_context():
 from companion_ai.conversation import ModelManager
 import httpx,json
 calls=[]
 def handler(request):
  if request.url.path=='/api/show':
   model=json.loads(request.content)['model']
   return httpx.Response(200,json={'system':'Native identity of '+model,'capabilities':['completion']})
  body=json.loads(request.content);calls.append(body)
  assert body['think'] is False
  return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:neutral]] Acknowledged.'},'done':True})+'\n')
 c,o,s=observation();m=ModelManager(transport=httpx.MockTransport(handler));service=ConversationService(o,lambda _:None,m,clock=c.mono)
 for name in ['evelyn-narrative-v1:latest','daisy-narrative-v1:latest','celeste-narrative-v2:latest']:
  await m.start(AIConfig(model=name));service.activate_model()
  assert not service.history and service.narrative.state['objective'] is None
  service.update_objective('create',{'premise':'A private journal for '+name.split('-')[0]+'.'})
  service.request('Who are you?',user=True);await service.task
  assert calls[-1]['messages'][0]['content'].startswith('Native identity of '+name)
  assert all(other not in str(calls[-1]['messages']) for other in ['A private journal for '+n+'.' for n in ['evelyn','daisy','celeste'] if n not in name])
 await m.start(AIConfig(model='evelyn-narrative-v1:latest'));service.activate_model()
 assert 'evelyn' in service.narrative.state['objective']['premise'] and service.history
 await service.close()


def test_completion_e2e_survives_reset_with_identity_significance_stages_and_expression(tmp_path):
 import threading,json,httpx
 from fastapi.testclient import TestClient
 from ai_observer.server import create_app
 from tests.fork.test_observer import TOKEN,ORIGIN,auth,until
 from tests.fork.grounding_cases import Clock,snapshot
 release=threading.Event();requests=[]
 class Delayed(httpx.AsyncByteStream):
  async def __aiter__(self):
   yield b'{"message":{"content":"[[expression:neutral]]"},"done":false}\n'
   while not release.is_set():await asyncio.sleep(.01)
   yield b'{"message":{"content":"A conclusion worth recording."},"done":true}\n'
 def handler(request):
  if request.url.path=='/api/show':return httpx.Response(200,json={'system':'Native Daisy identity.','capabilities':['completion']})
  if request.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
  body=json.loads(request.content);requests.append(body);return httpx.Response(200,stream=Delayed())
 c=Clock();app=create_app(TOKEN,tmp_path,clock=c.mono,transport=httpx.MockTransport(handler));app.state.observation.wall=c.wall
 s=snapshot(c,active_mode='calibrate',goal='calibrate',seconds=937)
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   epoch=auth(ws)['epoch'];ws.send_json(dict(version=1,type='select_model',selection={'model':'daisy-narrative-v1:latest'}));until(ws,'model_selected')
   def send(seq,kinds):
    message=frame(s,seq,kinds);message['epoch']=epoch;ws.send_json(message);return message
   send(0,[]);until(ws,'observation_ack');c.tick(.3)
   s['status']='IDLE';s['details'].update(warmup_active=False,terminal_outcome='calibration_completed',captured_at_ms=int(c.wall()*1000))
   source=send(1,['completion_accepted','stop']);ack=until(ws,'observation_ack')
   assert ack['events'][-1]['preserve_reaction']
   start=until(ws,'response_start')
   c.tick(.3);s.update(seconds=0,edges=0);s['details'].update(terminal_outcome=None,captured_at_ms=int(c.wall()*1000))
   duplicate=send(2,['completion_accepted','stop']);ack=until(ws,'observation_ack');assert len(ack['rejected_events'])==2
   release.set();result=until(ws,'speech');assert result['id']==start['id'] and result['expression']=='neutral'
   record=app.state.speech.event_intelligence.snapshot()['recent_events'][0]
   assert record['event']['id']==source['events'][0]['id'] and record['event']['significance']=='major'
   assert record['decision']=='acknowledged' and any(v['decision']=='generation_started' for v in record['stages'])
   assert app.state.observation.completed()[-1]['active_running_seconds']==937
   assert len(requests)==1 and requests[0]['think'] is False


def test_acknowledged_event_is_only_reused_when_the_user_requests_history():
 c,o,s=observation();s,_=change(c,o,s,'edge',edges=3);event=o.canonical()['events'][-1]
 summary=o.summary()|{'conversation_source':'user','narrative_context':{'event_references':[{'event_id':event['event_id']}]}}
 from companion_ai.context_compiler import ContextCompiler
 messages,warnings,diagnostics=ContextCompiler().compile(summary,'What happened to the edge counter?',[],AIConfig())
 assert event['event_id'] in diagnostics['event_ids'] and 'already_acknowledged' in str(messages)
 # The same acknowledged occurrence cannot become a fresh autonomous trigger.
 summary|={'conversation_source':'event','trigger_event':{'kind':'edge','event_id':event['event_id'],'session_id':o.session_id}}
 _,_,diagnostics=ContextCompiler().compile(summary,'Observed application event',[],AIConfig())
 assert any(e['id']==event['event_id'] and e['reason']=='already_acknowledged' for e in diagnostics['excluded_events'])


def test_terminal_marker_attached_to_reset_counters_is_not_a_zero_length_summary():
 c,o,s=observation();s['details'].update(terminal_outcome='manual_stop',warmup_active=False)
 s,_=change(c,o,s,'stop',status='IDLE',seconds=0,edges=0)
 summary=o.completed()[-1]
 assert summary['active_running_seconds'] is None and summary['last_verified_running_ticks']==42


def test_explicit_reset_is_cancellation_and_never_successful_completion():
 c,o,s=observation();s['details'].update(terminal_outcome='cancelled',warmup_active=False)
 s,_=change(c,o,s,'stop',status='IDLE')
 assert o.completed()[-1]['termination']=='cancelled'
 assert o.completed()[-1]['active_running_seconds']==42
 assert all(e['kind']!='completion_accepted' for e in o.events)

@pytest.mark.parametrize('text', ['In this fictional scene, your pulse is racing.','In the story, the stroker is moving.','You said your pulse has been climbing.'])
def test_explicit_fiction_and_attributed_user_sensation_are_not_sensor_claims(text):
 c,o,s=observation()
 assert not violations(text,o.canonical(),[{'role':'user','content':'My pulse feels as though it is climbing.'}])
