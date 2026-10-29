"""Matched context allocation/repair regressions. Synthetic state, no hardware/Ollama."""
import asyncio,json
from copy import deepcopy
import httpx,pytest
from companion_ai.context import compose_messages,ContextBudgetError
from companion_ai.context_compiler import ContextCompiler,ContextConfig,estimate
from companion_ai.conversation import ModelManager,ConversationService
from companion_ai.director import ConversationDirector
from companion_ai.models import AIConfig,MemoryConfig
from tests.fork.context_retention_fixture import fixture,baseline_compiler,MODELS,scenarios
from tests.ai.test_f251 import observation

@pytest.mark.parametrize('model',MODELS)
def test_matched_default_budget_reproduces_and_repairs_starvation(model):
 summary,history,native=fixture(model);before=deepcopy((summary,history));config=AIConfig(model=model+':latest')
 old,_,od=baseline_compiler().compile(summary,'Good evening.',history,config,reserve_characters=len(native))
 messages,_,d=ContextCompiler().compile(summary,'Good evening.',history,config,reserve_characters=len(native))
 assert len(old)==2 and not od['narrative_references']
 assert len(messages)>=4 and d['narrative_references']
 assert all(any(m['content']==h['content'] for m in messages) for h in history[-2:])
 assert d['budget']['soft_target_tokens']==2800
 assert d['estimated_prompt_tokens']<=d['budget']['hard_prompt_tokens']
 assert d['allocation']['protected_history_messages']==2 and d['allocation']['protected_story_items']==1
 assert (summary,history)==before and messages[-1]['content'].endswith('Good evening.')

@pytest.mark.parametrize('history_cap,story_cap',[(0,450),(1200,0),(0,0),(120,80),(1200,450)])
def test_reservations_respect_disabled_and_category_allowances(history_cap,story_cap):
 summary,history,native=fixture(MODELS[2])
 m,_,d=ContextCompiler(ContextConfig(history_tokens=history_cap,narrative_tokens=story_cap)).compile(summary,'Good evening.',history,AIConfig(),reserve_characters=len(native))
 assert d['budget']['categories']['history']<=history_cap and d['budget']['categories']['narrative']<=story_cap
 if not history_cap:assert len(m)==2
 if not story_cap:assert not d['narrative_references']

@pytest.mark.parametrize('context,max_tokens',[(8192,2048),(6250,2048),(5226,1024)])
def test_retention_sheds_optional_items_under_hard_pressure(context,max_tokens):
 summary,history,native=fixture(MODELS[2])
 messages,_,d=ContextCompiler().compile(summary,'Good evening.',history,AIConfig(context_length=context,max_tokens=max_tokens),reserve_characters=len(native))
 assert d['estimated_prompt_tokens']<=context-max_tokens-96
 assert messages[-1]['content'].endswith('Good evening.')
 assert any('CURRENT SESSION' in m['content'] for m in messages)


def test_long_mandatory_inputs_are_preserved_or_fail_explicitly():
 summary,history,native=fixture(MODELS[2]);request='Please explain: '+'語'*500
 m,_,_=ContextCompiler().compile(summary,request,history,AIConfig(),reserve_characters=len(native))
 assert m[-1]['content'].endswith(request)
 with pytest.raises(ContextBudgetError):ContextCompiler().compile(summary,request,history,AIConfig(context_length=4096,max_tokens=2048),reserve_characters=len(native))
 summary.update(conversation_source='revision',revision={'source':'user','original_request':request,'candidate_draft':'unabridged draft '*4000})
 with pytest.raises(ContextBudgetError):ContextCompiler().compile(summary,'repair',history,AIConfig(),reserve_characters=len(native))


def test_no_optional_inflation_without_available_context_and_memory_disable():
 summary,history,native=fixture(MODELS[0]);summary['narrative_context']={}
 _,_,d=ContextCompiler().compile(summary,'Hello',[],AIConfig(),reserve_characters=len(native))
 assert d['allocation']['soft_target_extension_tokens']==0
 m,_,d=ContextCompiler().compile(summary,'Hello',history,AIConfig(),MemoryConfig(enabled=False),reserve_characters=len(native))
 assert len(m)==2 and not d['narrative_references']


def test_relevant_story_is_reserved_before_extra_history_and_deduplicated():
 summary,history,native=fixture(MODELS[2]);summary['narrative_context']['developments']=[history[-1]['content']]
 m,_,d=ContextCompiler().compile(summary,'What did we agree about the blue notebook?',history,AIConfig(),reserve_characters=len(native))
 assert d['narrative_references'] and sum(x['content'].count(history[-1]['content']) for x in m)==1

@pytest.mark.parametrize('source',['user','event'])
@pytest.mark.parametrize('fallback',[False,True])
def test_revisions_preserve_original_draft_intent_and_event_evidence(source,fallback):
 summary,history,native=fixture(MODELS[0]);name='revision_'+source
 _,current,prompt=next(row for row in scenarios(summary) if row[0]==name)
 before=deepcopy(current)
 info={};m,_=compose_messages(current,prompt,history,AIConfig(),context_config=ContextConfig(enabled=not fallback),diagnostics=info)
 text=m[-1]['content'];revision=current['revision']
 assert json.dumps(revision['original_request'],ensure_ascii=False)[1:-1] in text
 assert revision['candidate_draft'] in text and 'Request no tools and perform no actions.' in text
 assert current==before
 if not fallback:
  assert info['focus']['category']=='revise_reply'
  assert 'No fresh unacknowledged triggering event' not in text
  if source=='event':assert current['trigger_event']['event_id'] in info['event_ids']


def test_old_revision_bug_reproduced_and_nonrevision_event_remains_compact():
 summary,history,_=fixture(MODELS[0]);_,current,prompt=next(row for row in scenarios(summary) if row[0]=='revision_event')
 current['narrative_context']={}
 original=current['revision']['original_request'];old=baseline_compiler()
 first,_,_=old.compile(current|{'conversation_source':'event'},original,[],AIConfig())
 retry,_,_=old.compile(current,prompt,[],AIConfig())
 assert first==retry and current['revision']['candidate_draft'] not in retry[-1]['content']
 normal=deepcopy(current);normal.pop('revision');normal['conversation_source']='event'
 m,_,d=ContextCompiler().compile(normal,original,[],AIConfig())
 assert d['focus']['category']=='react_event' and 'Respond to the verified triggering evidence' in m[-1]['content']

@pytest.mark.parametrize('revision',[None,{}, {'source':'user','original_request':'Hello'}, {'source':'bad','original_request':'a','candidate_draft':'b'}])
def test_malformed_revision_is_not_silently_compiled_as_a_new_event(revision):
 summary,history,_=fixture(MODELS[0]);summary.update(conversation_source='revision',revision=revision)
 with pytest.raises(ValueError,match='Revision requires'):ContextCompiler().compile(summary,'repair',history,AIConfig())

@pytest.mark.parametrize('prompt',['Hello.','Goodbye.','Tell me about your garden.'])
def test_ordinary_chat_has_no_device_or_measurement_statuses(prompt):
 summary,history,_=fixture(MODELS[1]);m,_,d=ContextCompiler().compile(summary,prompt,history,AIConfig())
 assert d['supporting_categories']==['status']
 text=m[-1]['content']
 for unrelated in ['BLE','Handy','VacuGlide','Measurement availability','Heart-rate source','physical_motion']:assert unrelated not in text
 assert 'read-only' in m[0]['content'] and 'sensor' in m[0]['content']

@pytest.mark.parametrize('prompt,fields',[('Current BPM and trend?',{'hr','trend','hr_source'}),('Is the Handy connected?',{'handy','physical_motion'}),('Which mode and goal?',{'experience','active_mode','goal'}),('How long has this session been running?',{'seconds','pauses'})])
def test_direct_operational_questions_retain_required_facts(prompt,fields):
 summary,history,_=fixture(MODELS[0]);m,_,d=ContextCompiler().compile(summary,prompt,history,AIConfig())
 assert fields<=set(d['supporting_categories'])
 if 'hr' in fields:assert '98 BPM' in m[-1]['content']


def test_current_protection_is_preserved_even_during_a_greeting():
 c,o,s=observation();o.report['safety'].update(signal='stale',watchdog_paused=True,fault='signal_lost');o.report['status']='PAUSED'
 m,_,d=ContextCompiler().compile(o.summary()|{'conversation_source':'user'},'Hello',[],AIConfig())
 assert {'hr','ble','status'}<=set(d['supporting_categories'])
 assert 'CURRENT PROTECTIVE OBSERVATION' in m[-1]['content'] and 'watchdog_paused' in m[-1]['content']
 assert 'Heart rate [hr]: unavailable' in m[-1]['content']


def test_epoch_and_abandonment_still_fence_history_and_story():
 summary,history,native=fixture(MODELS[2]);summary['narrative_epoch']='new'
 for item in history:item['narrative_epoch']='old'
 m,_,d=ContextCompiler().compile(summary,'New topic: discuss music.',history,AIConfig(),reserve_characters=len(native))
 assert len(m)==2 and not d['narrative_references'] and 'blue notebook' not in m[-1]['content']

async def manager_service(source='user',second='A new garden path leads toward the orchard.',block=False):
 c,o,s=observation();wire=[];entered=asyncio.Event();release=asyncio.Event();draft='The violet envelope waits beside the telescope.'
 async def handler(request):
  if request.url.path=='/api/show':return httpx.Response(200,json={'system':'Native character identity.','capabilities':['completion']})
  if request.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
  body=json.loads(request.content);wire.append(body)
  if len(wire)==2:
   entered.set()
   if block:await release.wait()
  text=draft if len(wire)==1 else second
  return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:neutral]] '+text},'done':True,'done_reason':'stop'})+'\n')
 m=ModelManager(transport=httpx.MockTransport(handler));await m.start(AIConfig(model=MODELS[0]+':latest',max_tokens=256));m.current_summary=o.summary
 frames=[];d=ConversationDirector(clock=c.mono);d.memory['responses'].append({'text':draft,'at':c.mono()})
 service=ConversationService(o,frames.append,m,clock=c.mono,director=d)
 service.director.memory['responses'].append({'text':draft,'at':c.mono()})
 prompt='Continue our fictional scene.' if source=='user' else 'Observed application event (not a user request): '+json.dumps({'kind':'completion_accepted'})
 event=None if source=='user' else {'kind':'completion_accepted','event_id':'repair-id','session_id':o.session_id,'evidence':'Verified synthetic completion.'}
 service.request(prompt,user=source=='user',event=event)
 return service,wire,frames,entered,release,prompt,draft

@pytest.mark.parametrize('source',['user','event'])
async def test_actual_director_retry_transports_original_and_candidate_once(source):
 service,wire,frames,_,_,prompt,draft=await manager_service(source)
 await service.task
 assert len(wire)==2 and all(r['think'] is False for r in wire)
 assert draft in wire[1]['messages'][-1]['content'] and json.dumps(prompt)[1:-1] in wire[1]['messages'][-1]['content']
 assert service.adapter.context_diagnostics['focus']['category']=='revise_reply'
 assert sum(f['type']=='speech' for f in frames)==1
 assert sum(f.get('reason')=='bounded_repetition_retry' for f in frames)==1
 assert len([h for h in service.history if h['role']=='user'])==(1 if source=='user' else 0)
 assert len(service.narrative.state['event_references'])==(1 if source=='event' else 0)
 assert service.director.counts['opportunities_dispatched']==0  # retries do not reschedule events
 await service.close()

@pytest.mark.parametrize('action',['reset','cancel','model_switch'])
async def test_inflight_revision_is_cancelled_without_saving_draft(action):
 service,wire,frames,entered,release,_,_=await manager_service(block=True)
 await asyncio.wait_for(entered.wait(),2)
 if action=='reset':service.reset_narrative()
 elif action=='model_switch':
  service.interrupt();service.adapter.config=AIConfig(model=MODELS[1]+':latest');service.activate_model()
 else:service.interrupt()
 release.set();await service.task
 assert not any(f['type']=='speech' for f in frames) and not service.history
 await service.close()

@pytest.mark.parametrize('source',['user','event'])
async def test_repair_still_passes_factual_validation_before_acceptance(source):
 service,wire,frames,_,_,_,draft=await manager_service(source,second="I've adjusted the stimulation transport.")
 await service.task
 assert len(wire)==3 and all(r['think'] is False for r in wire)
 assert not any('adjusted' in h['content'] for h in service.history)
 speech=[f for f in frames if f['type']=='speech']
 assert (len(speech)==1 and speech[0]['text']==draft) if source=='user' else not speech
 assert service.adapter.grounding_corrections and service.director.counts['regenerations']==1
 await service.close()

async def test_candidate_draft_is_not_evidence_of_a_user_report():
 from companion_ai.fidelity import GroundingError
 c,o,_=observation();wire=[]
 def handler(request):
  if request.url.path=='/api/show':return httpx.Response(200,json={'system':'Native identity.','capabilities':['completion']})
  wire.append(json.loads(request.content))
  return httpx.Response(200,text=json.dumps({'message':{'content':'You are standing.'},'done':True})+'\n')
 m=ModelManager(transport=httpx.MockTransport(handler));await m.start(AIConfig());m.current_summary=o.summary
 summary=o.summary()|{'conversation_source':'revision','revision':{'source':'user','original_request':'Hello.','candidate_draft':'You are standing.'}}
 with pytest.raises(GroundingError):await m.reply(summary,'The candidate draft says you are standing.',[])
 assert len(wire)==2 and all(r['think'] is False for r in wire)

@pytest.mark.parametrize('model',MODELS)
async def test_provider_receives_native_identity_and_retained_context(model):
 summary,history,native=fixture(model);wire=[]
 def handler(request):
  if request.url.path=='/api/show':return httpx.Response(200,json={'system':native,'capabilities':['completion']})
  wire.append(json.loads(request.content))
  return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:neutral]] Good evening.'},'done':True})+'\n')
 m=ModelManager(transport=httpx.MockTransport(handler));await m.start(AIConfig(model=model+':latest'))
 await m.reply(summary,'Good evening.',history)
 assert len(wire)==1 and wire[0]['think'] is False and wire[0]['messages'][0]['content'].startswith(native+'\n\n')
 assert m.context_diagnostics['allocation']['retained_history_messages']>=2
 assert m.context_diagnostics['allocation']['retained_story_items']>=1
 assert 'BLE' not in wire[0]['messages'][-1]['content']

@pytest.mark.parametrize('model',MODELS)
def test_realistic_long_dialogue_preserves_a_whole_recent_exchange(model):
 summary,history,native=fixture(model)
 history=[m|{'content':m['content']+' We agreed to keep the notebook on the bench, and return together tomorrow.'*8} for m in history]
 m,_,d=ContextCompiler().compile(summary,'Could we return to our garden plans?',history,AIConfig(),reserve_characters=len(native))
 assert all(any(message['content']==old['content'] for message in m) for old in history[-2:])
 assert d['narrative_references'] and d['estimated_prompt_tokens']<=d['budget']['hard_prompt_tokens']
