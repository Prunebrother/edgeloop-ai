# SPDX-License-Identifier: AGPL-3.0-only
# Ported conversation/provider assertions from legacy 9e89fa1; no legacy engine fixture.
import asyncio,json,time
import httpx,pytest
from dataclasses import replace
from pathlib import Path
from companion_ai.conversation import ConversationService,ModelManager,OllamaAdapter
from companion_ai.models import AIConfig,MemoryConfig,SpeechPolicy
from companion_ai.context import compose_messages,ContextBudgetError
from companion_ai.director import ConversationDirector,DirectorConfig,repetition,numerical_request
from companion_ai.llm import OllamaProvider,ChatMessage,LLMRequest,ToolDefinition,ToolCall,LLMEvent,NoVisibleResponseError
from companion_ai.storage import SettingsStore
from tests.ai.support import ObservationFixture
class Clock:
    now=100.
    def __call__(self):return self.now


def directed(adapter=None):
    clock=Clock();state=ObservationFixture(clock,clock);messages=[]
    director=ConversationDirector(clock=clock)
    speech=ConversationService(state,messages.append,adapter,clock,director)
    return clock,state,messages,director,speech


def test_book_reading_does_not_request_measurements():
    assert not numerical_request('I enjoy reading books and painting.')
    assert not numerical_request('Pick a number for our story.')
    assert numerical_request('What is my current heart rate in BPM?')


def test_repetition_normalizes_phrases_and_questions():
    assert repetition('Hello, Finch!',['hello finch'])['exact_duplicate']
    score=repetition('A new thought. What would you like to talk about?', ['A different start. What would you like to talk about?'])
    assert score['repeated_question']==1.
    assert repetition('Rain makes a good soundtrack.',['Let us talk about astronomy.'])['similarity']<.7


def test_equivalent_events_deduplicated_and_aggregated():
    clock,state,_,director,speech=directed()
    for hr in [90,91,92,94]:speech.enqueue('hr_rising',20,{'hr':hr,'delta_bpm':10})
    assert len(speech.pending)==1
    assert director.counts['events_suppressed']==3
    assert director.aggregates['hr_rising']['count']==4
    clock.now+=91;speech.enqueue('hr_rising',20,{'hr':100})
    assert director.counts['significant_events_retained']==2


def test_current_topic_protected_and_category_cooldown():
    clock,_,_,director,_=directed()
    director.user('Let us talk about old libraries and books.')
    event={'kind':'hr_rising'}
    assert director.opportunity(event)[1]=='active_conversation'
    clock.now+=31
    assert director.opportunity(event)[1]=='continue_user_topic'
    clock.now+=91
    assert director.opportunity(event)[0]
    director.dispatched(event,'test')
    clock.now+=121
    assert director.opportunity(event)[1]=='category_cooldown'


async def test_event_response_retained_as_assistant_not_user_and_shared_with_next_turn():
    calls=[]
    class Adapter:
        async def reply(self,summary,prompt,history):
            calls.append((summary,prompt,history))
            return 'Rain suits a mystery story.' if len(calls)==1 else 'The detective should take the quieter street.'
    clock,state,messages,director,speech=directed(Adapter())
    speech.request('An application opportunity',user=False);await speech.task
    clock.now+=31
    speech.request('Continue our story.',user=True);await speech.task
    assert any(m['role']=='assistant' and m['content']=='Rain suits a mystery story.' for m in calls[1][2])
    assert all(r['origin']=='real_user' for r in director.records if r['role']=='user')
    assert not any(m['role']=='user' and m['content']=='An application opportunity' for m in speech.history)
    assert calls[0][0]['conversation_source']=='event'
    await speech.close()


async def test_event_turn_receives_completed_user_history_and_no_numerical_prompt():
    calls=[]
    class Adapter:
        async def reply(self,summary,prompt,history):
            calls.append((summary,prompt,history));return 'A quiet room makes a fine setting.'
    clock,state,_,director,speech=directed(Adapter())
    speech.request('Let us tell a story.',user=True);await speech.task
    clock.now+=100;state.report['status']='RUNNING';state.received=clock.now;speech.policy=SpeechPolicy(min_interval_seconds=0.,user_grace_seconds=0.)
    speech.enqueue('hr_rising',20,{'hr':119,'delta_bpm':25});speech.pump();await speech.task
    assert calls[-1][2] and '119' not in calls[-1][1] and '119' not in json.dumps({k:v for k,v in calls[-1][0].items() if k!='narrative_scope'})
    await speech.close()


async def test_one_bounded_regeneration_and_no_loop():
    calls=[]
    class Adapter:
        async def reply(self,*args):calls.append(args);return 'The same familiar response.'
    clock,_,messages,director,speech=directed(Adapter())
    director.accepted('The same familiar response.',True)
    speech.request('Tell me something.',True);await speech.task
    assert len(calls)==2 and director.counts['regenerations']==1
    assert len([m for m in messages if m['type']=='speech'])==1
    assert len([r for r in director.records if r['origin']=='assistant_dialogue'])==2
    await speech.close()


async def test_repetitive_unsolicited_candidate_suppressed_before_streaming():
    class Adapter:
        streaming=True
        async def reply(self,summary,prompt,history,on_chunk=None):
            on_chunk('Same observation.');return 'Same observation.'
    _,_,messages,director,speech=directed(Adapter())
    director.accepted('Same observation.',True)
    speech.request('Opportunity',False);await speech.task
    assert not any(m['type'] in {'speech','response_delta'} for m in messages)
    assert messages[-1]['type']=='response_suppressed'
    await speech.close()


async def test_user_requested_silence_needs_no_inference():
    class Never:
        async def reply(self,*args):raise AssertionError('must not infer')
    _,_,messages,director,speech=directed(Never())
    result=speech.request('No need to reply, just be quiet.',True)
    assert result['silence'] and speech.task is None
    assert messages[-1]['reason']=='user_requested_silence'
    await speech.close()


@pytest.mark.parametrize("marker", ["[SILENCE]", "SILENCE", "silence"])
async def test_model_chosen_silence_not_saved_or_spoken(marker):
    class Quiet:
        async def reply(self,*args):return marker
    _,_,messages,director,speech=directed(Quiet())
    speech.request('Opportunity',False);await speech.task
    assert not speech.history and not director.memory['responses']
    assert messages[-1]['reason']=='intentional_silence'
    await speech.close()


async def test_thinking_is_counted_but_never_exposed_as_dialogue():
    def handler(request):
        if request.url.path=='/api/show':return httpx.Response(200,json={})
        assert json.loads(request.content)['think'] is False
        return httpx.Response(200,text='\n'.join(json.dumps(row) for row in [
            {'message':{'thinking':'PRIVATE REASONING'},'done':False},
            {'message':{'content':'Visible answer.'},'done':True,'eval_count':10,'eval_duration':100000000}])+'\n')
    provider=OllamaProvider('qwen3:8b',transport=httpx.MockTransport(handler))
    events=[e async for e in provider.stream(LLMRequest(AIConfig(thinking=False),(ChatMessage('user','Hello'),)))]
    assert ''.join(e.text for e in events)=='Visible answer.'
    assert 'PRIVATE' not in json.dumps(provider.metrics.samples[-1])
    assert provider.metrics.samples[-1]['thinking_characters']==17
    assert provider.metrics.samples[-1]['thinking_tokens'] is None


async def test_thinking_budget_exhaustion_records_diagnostics_without_leak():
    provider=OllamaProvider('qwen3:8b',transport=httpx.MockTransport(lambda r:httpx.Response(200,text=json.dumps({'message':{'thinking':'secret'},'done':True,'done_reason':'length','eval_count':16})+'\n')))
    with pytest.raises(ValueError,match='no visible response'):
        [e async for e in provider.stream(LLMRequest(AIConfig(thinking=False),()))]
    assert provider.metrics.samples[-1]['done_reason']=='length'
    assert 'secret' not in json.dumps(provider.metrics.samples[-1])


def test_prompt_provenance_and_neutral_runtime():
    summary={'conversation_source':'event','director':{'enabled':True}}
    messages,_=compose_messages(summary,'Application opportunity',[{'role':'assistant','content':'Prior event dialogue','origin':'assistant_dialogue','at':100.}],AIConfig())
    assert len([m for m in messages if m['role']=='system'])==1
    assert messages[-1]['role']=='user' and messages[-1]['origin']=='system_event'
    assert 'APPLICATION EVENT' in messages[-1]['content'] and 'Application opportunity' in messages[-1]['content']
    assert 'at' not in messages[1]
    assert all(word not in messages[0]['content'] for word in ['Personality:', 'Conversational style:', 'Response preference:', 'Character:'])


def test_followup_remark_keeps_topic_and_explicit_new_subject_changes_it():
    director=ConversationDirector()
    director.user('I bought a mystery book.')
    director.user('Continue that opening with one vivid detail.')
    assert director.memory['topic']=='books'
    director.user('Back to dinner: tomatoes and garlic.')
    assert director.memory['topic']=='food'


def test_repetition_comparison_is_bounded_for_adversarial_text():
    import time
    text='a '*2000
    started=time.perf_counter();score=repetition(text,[text]*12)
    assert score['exact_duplicate'] and time.perf_counter()-started<.25


def test_stale_command_ack_is_context_only_when_relevant():
    _,state,_,director,_=directed()
    director.user('Let us talk about books.')
    summary=director.context(state.summary(),'Continue the story.',[{'kind':'command_ack','operation':'set_pattern','status':'executed'}],True)
    assert not summary['recent_events']


async def test_unsolicited_assistant_memory_persists_without_a_following_user_turn(tmp_path):
    from companion_ai.storage import SettingsStore
    class Manager(ModelManager):
        async def reply(self,*args,**kwargs):return 'The rain gives our story a quiet rhythm.'
    manager=Manager(store=SettingsStore(tmp_path))
    manager.memory=MemoryConfig(persist_between_sessions=True)
    _,_,_,director,speech=directed(manager)
    speech.request('Application opportunity',False);await speech.task
    saved=manager.store.read(speech.memory_path())
    assert saved and saved[-1]['role']=='assistant' and saved[-1]['origin']=='assistant_dialogue'
    assert not any(m['role']=='user' for m in saved)
    _,_,_,other_director,restored=directed(manager)
    assert restored.history[-1]['content']=='The rain gives our story a quiet rhythm.'
    await speech.close();await restored.close()


async def test_regeneration_deadline_retains_original_and_discards_partial_revision():
    class Adapter:
        streaming=True
        calls=0
        async def reply(self,summary,prompt,history,on_chunk=None):
            self.calls+=1
            if self.calls==2:
                on_chunk('UNFINISHED REVISION')
                await asyncio.sleep(10)
            on_chunk('A familiar response.');return 'A familiar response.'
    _,_,messages,director,speech=directed(Adapter())
    director.config=DirectorConfig(max_regeneration_seconds=.1)
    director.accepted('A familiar response.',True)
    speech.request('A small thought.',True)
    await asyncio.wait_for(speech.task,.5)
    assert messages[-1]['type']=='speech' and messages[-1]['text']=='A familiar response.'
    last_start=max(i for i,m in enumerate(messages) if m['type']=='response_start')
    assert all('UNFINISHED' not in m.get('text','') for m in messages[last_start:])
    await speech.close()
