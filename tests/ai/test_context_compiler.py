# SPDX-License-Identifier: AGPL-3.0-only
from copy import deepcopy
import pytest
from companion_ai.context import compose_messages,compose_legacy,ContextBudgetError
from companion_ai.context_compiler import ContextCompiler,ContextConfig,estimate
from companion_ai.models import AIConfig,MemoryConfig
from tests.fork.grounding_cases import cases

def compile(case=None,prompt='Hello',**updates):
 case=case or cases()[1];summary=case.summary()|updates
 messages,warnings,diagnostics=ContextCompiler().compile(summary,prompt,case.history,AIConfig(max_tokens=320),MemoryConfig(max_messages=64))
 return messages,warnings,diagnostics

@pytest.mark.parametrize('prompt,topic,fields,omitted',[
 ('Hello','general',['status'],['hr','hr_source','seconds','goal']),
 ('What is my current BPM?','physiology',['hr','hr_source','trend'],['seconds','goal']),
 ('Which mode and goal are selected?','configuration',['experience','active_mode','goal'],['hr','seconds']),
 ('How long has the session been running?','timing',['seconds','pauses'],['hr','goal']),
 ('Is the Handy connected?','devices',['handy','physical_motion'],['hr','seconds'])])
def test_primary_focus_selects_authoritative_facts(prompt,topic,fields,omitted):
 messages,warnings,d=compile(prompt=prompt)
 assert d['focus']['category']=='answer_user' and d['focus']['topic']==topic
 assert set(fields)<=set(d['supporting_categories'])
 assert not set(omitted)&set(d['supporting_categories'])
 assert messages[-1]['content'].endswith(prompt)
 assert sum(m['content'].count('CURRENT SESSION —') for m in messages)==1

@pytest.mark.parametrize('name',['idle_no_sensor','active_simulated','active_ble','paused','stopped','restart_counters','stale_connection','hardware_disconnected_active'])
def test_lifecycle_keeps_unknown_sources_and_current_semantics(name):
 case=next(c for c in cases() if c.name==name)
 messages,_,d=compile(case,'What is the current BPM?')
 text=messages[-1]['content']
 if not case.observation.hr_current():assert 'Heart rate [hr]: unavailable' in text
 else:assert str(case.observation.hr)+' BPM' in text
 assert d['focus']['category']=='answer_user'

def test_user_priority_over_event_and_inference_free_compilation():
 case=cases()[1];event={'kind':'edge','event_id':'verified','session_id':case.observation.session_id,'significance':'major'}
 messages,_,d=compile(prompt='Which book should we discuss?',trigger_event=event)
 assert d['focus']['source']=='real_user' and d['focus']['category']=='answer_user'
 assert 'Answer the current user message first' in messages[-1]['content']

@pytest.mark.parametrize('reason,event',[('stale_or_unavailable',{'created_at_ms':1}),('wrong_session',{'session_id':'old'}),('already_acknowledged',{'id':'acked'})])
def test_invalid_events_never_become_primary_focus(reason,event):
 case=cases()[1];obs={'id':'x','kind':'rapid_rise','category':'derived','session_id':case.observation.session_id}|event
 _,_,d=compile(conversation_source='event',trigger_event={'kind':'rapid_rise','category':'derived','observation':obs},narrative_context={'event_references':[{'event_id':'acked'}]})
 assert d['focus']['category']=='context_only' and d['excluded_events'][0]['reason']==reason

def test_budget_never_truncates_current_message_or_changes_stored_history():
 case=cases()[-1];before=deepcopy(case.history);prompt='Please retain my exact instruction: '+'violet '*200
 messages,warnings,d=compile(case,prompt)
 assert messages[-1]['content'].endswith(prompt) and case.history==before
 assert warnings and d['estimated_prompt_tokens']<=d['budget']['hard_prompt_tokens']
 with pytest.raises(ContextBudgetError):
  ContextCompiler().compile(case.summary(),'long '*5000,[],AIConfig(context_length=512,max_tokens=96))


def test_estimate_is_not_claimed_as_tokenizer_and_unicode_budget_is_conservative():
 assert estimate('語'*100)>estimate('a'*100)
 _,_,d=compile();assert 'not tokenizer-exact' in d['estimate_method']
 assert 'grounding' in d['budget']['categories'] and 'expression' in d['budget']['categories']


def test_explicit_f27_fallback_preserves_baseline_without_touching_default():
 case=cases()[1];kwargs=(case.summary(),'Hello',[],AIConfig())
 assert compose_messages(*kwargs,context_config=ContextConfig(enabled=False))==compose_legacy(*kwargs)
 assert sum(len(m['content']) for m in compose_messages(*kwargs)[0])<sum(len(m['content']) for m in compose_legacy(*kwargs)[0])

@pytest.mark.parametrize('value',[{'history_tokens':-1},{'target_prompt_tokens':9000},{'schema_version':2},{'event_max_age_seconds':999}])
def test_invalid_budgets_are_rejected(value):
 with pytest.raises(ValueError):ContextConfig.model_validate(value)


def test_multi_part_user_query_keeps_each_requested_fact_without_multiple_focuses():
 _,_,d=compile(prompt='Give the current BPM, maximum setting, selected mode and elapsed seconds.')
 assert {'hr','single_max_bpm','goal','seconds'}<=set(d['supporting_categories'])
 assert d['focus']['category']=='answer_user'


def test_unrelated_event_is_not_stuffed_into_user_book_discussion():
 case=cases()[1]
 messages,_,d=compile(prompt='Let us discuss books.',trigger_event={'kind':'edge','event_id':'edge-book','session_id':case.observation.session_id})
 assert not d['event_ids'] and 'edge-book' not in messages[-1]['content']


def test_relevant_commitment_callback_outranks_unrelated_recent_excerpts():
 n={'phase':'development','premise':'An observatory mystery.','commitments':['I will bring the violet notebook.'],'developments':['The kitchen smells of bread.','The roses are blooming.'],'choices':['I choose the violet notebook.']}
 messages,_,d=compile(prompt='What did you promise about the violet notebook?',narrative_context=n)
 assert d['narrative_references'] and any(x['selected'] for x in d['memory_decisions'] if x['category']=='commitment')
 assert 'violet notebook' in messages[-1]['content']


def test_new_topic_omits_story_memory_without_erasing_it():
 n={'premise':'The blue envelope mystery.','developments':['A hidden map.']};before=deepcopy(n)
 messages,_,d=compile(prompt='New topic: tell me about music.',narrative_context=n)
 assert n==before and not d['narrative_references']
 assert 'blue envelope' not in messages[-1]['content']


def test_direct_compiler_client_honors_explicit_epoch_boundary():
 case=cases()[1];case.history=[{'role':'user','content':'The abandoned blue envelope.','narrative_epoch':'old'},{'role':'user','content':'I prefer jazz.','narrative_epoch':'new'}]
 messages,_,_=compile(case,prompt='Hello',narrative_epoch='new')
 assert not any('abandoned' in m['content'] for m in messages)
 assert any('jazz' in m['content'] for m in messages)


def test_fresh_premise_does_not_replay_abandonment_request_or_its_acknowledgement():
 case=cases()[1];case.history=[{'role':'user','content':"Let's abandon this storyline and discuss music."},{'role':'assistant','content':'We can discuss piano music instead.'}]
 messages,_,_=compile(case,prompt='Imagine a fresh garden mystery. I choose the silver ribbon.',narrative_context={'premise':None,'choices':["Let's abandon this storyline and discuss music."],'developments':['We can discuss piano music instead.']})
 assert not any('piano music' in m['content'] or 'discuss music' in m['content'] for m in messages)


def test_negative_abandonment_keeps_active_story_context():
 messages,_,d=compile(prompt='Do not abandon the story. Keep the violet notebook.',narrative_context={'premise':'The violet notebook mystery.'})
 assert 'premise:0' in d['narrative_references'] and 'violet notebook mystery' in messages[-1]['content']


def test_recent_explicit_directive_outranks_optional_narrative_under_soft_pressure():
 case=cases()[1];instruction='Never invent an answer to my questions. '+'Keep the answer transparent. '*35
 case.history=[{'role':'user','content':instruction}]
 info={};messages,warnings=compose_messages(case.summary()|{'narrative_context':{'premise':'A library mystery.','developments':['A desk clue.']}},'Hello',case.history,AIConfig(),context_config=ContextConfig(target_prompt_tokens=512,history_tokens=100),diagnostics=info)
 assert any(m['content']==instruction for m in messages)
 assert any('explicit user directive' in w for w in warnings)


def test_explicit_operational_boundary_is_a_directive_not_an_old_measurement():
 case=cases()[1];instruction='Never infer feelings from heart rate or claim hardware control.'
 case.history=[{'role':'user','content':instruction,'session_id':'earlier-session'}]
 messages,_,_=compile(case,prompt='What is my current BPM?')
 assert any(m['content']==instruction for m in messages)
 assert 'Heart rate [hr]: 98 BPM' in messages[-1]['content']


def test_unknown_model_without_narrative_uses_generic_grounded_context():
 case=cases()[1];info={}
 messages,_=compose_messages(case.summary(),'What is the current BPM?',[],AIConfig(model='future-character:latest'),diagnostics=info)
 assert info['model']=='future-character:latest' and info['focus']['category']=='answer_user'
 assert not info['narrative_references'] and 'Heart rate [hr]: 98 BPM' in messages[-1]['content']


async def test_event_arriving_mid_generation_cannot_replace_user_focus():
 import asyncio,json,httpx
 from companion_ai.conversation import ConversationService,ModelManager
 from companion_ai.director import DirectorConfig
 from ai_observer.observation import ObserverDirector
 from tests.fork.event_replay import Replay
 from tests.ai.test_f25 import runtime
 r=Replay();r.step(85,seconds=0);entered=asyncio.Event();release=asyncio.Event();wire=[];calls=[]
 base=runtime(wire,'[[expression:focused]]The fictional notebook remains our clue.')
 async def transport(request):
  if request.url.path=='/api/chat':calls.append(json.loads(request.content));entered.set();await release.wait()
  return base.handle_request(request)
 manager=ModelManager(transport=httpx.MockTransport(transport));await manager.select(AIConfig(model='evelyn-narrative-v1:latest'));manager.current_summary=r.observation.summary
 director=ObserverDirector(DirectorConfig(regenerate_once=False),clock=r.clock.mono);director.session_status='RUNNING'
 service=ConversationService(r.observation,lambda _:None,manager,clock=r.clock.mono,director=director);service.event_intelligence=r.detector
 service.request('Continue our fictional mystery.',user=True);await entered.wait()
 for bpm in range(85,111):service.process_derived(r.step(bpm))
 service.pump()
 assert manager.context_diagnostics['focus']['category']=='answer_user'
 assert any(row['decision']=='deferred:active_generation' for row in r.detector.history)
 assert len(calls)==1 and calls[0]['think'] is False
 release.set();await service.task
 assert manager.context_diagnostics['focus']['category']=='answer_user' and len(calls)==1
 await service.close()
