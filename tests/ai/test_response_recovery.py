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
from companion_ai.llm import OllamaProvider,ChatMessage,LLMRequest,ToolDefinition,ToolCall,LLMEvent,NoVisibleResponseError,collect_reply
from companion_ai.storage import SettingsStore
from tests.ai.support import ObservationFixture
def runtime_fixture(visible_on_retry=True):
    calls=[]
    def handler(request):
        body=json.loads(request.content) if request.content else {}
        if request.url.path=='/api/show':
            return httpx.Response(200,json={'system':'I am Evelyn.','capabilities':['completion','thinking','tools'],'model_info':{'test.context_length':8192}})
        if request.url.path=='/api/ps':
            return httpx.Response(200,json={'models':[]})
        if request.url.path=='/api/generate':
            return httpx.Response(200,json={'done':True})
        calls.append(body)
        row={'message':{'thinking':'PRIVATE REASONING'},'done':True,'done_reason':'length','eval_count':body['options']['num_predict']}
        if visible_on_retry and len(calls)>1:
            row={'message':{'content':'Good morning! Evelyn here.'},'done':True,'done_reason':'stop'}
        return httpx.Response(200,text=json.dumps(row)+'\n')
    return httpx.MockTransport(handler),calls


async def test_reasoning_only_output_fails_without_retry_or_leak():
    transport,calls=runtime_fixture()
    manager=ModelManager(transport=transport)
    await manager.start(AIConfig(model='evelyn-v11:latest'))
    with pytest.raises(NoVisibleResponseError):await manager.reply({},'Hello',[])
    assert len(calls)==1 and calls[0]['think'] is False
    assert 'PRIVATE' not in json.dumps(list(manager.metrics.samples))


async def test_output_retry_shares_one_total_deadline():
    from companion_ai.llm import OutputBudgetExceededError
    class Slow:
        calls=0
        async def stream(self,request):
            self.calls+=1
            await asyncio.sleep(.6 if self.calls==1 else 10)
            raise OutputBudgetExceededError(request.config)
            yield
    manager=ModelManager();manager.mode='ollama';manager.config=AIConfig(timeout_seconds=1.0);manager.adapter=Slow()
    with pytest.raises(TimeoutError):await asyncio.wait_for(manager.reply({},'Hello',[]),1.5)
    assert manager.adapter.calls==2


@pytest.mark.parametrize('finishes',[True,False])
async def test_partial_thinking_reply_retries_with_reset_and_never_saves_truncation(finishes):
    from companion_ai.llm import OutputBudgetExceededError
    calls=[]
    def runtime(request):
        if request.url.path=='/api/show':
            return httpx.Response(200,json={'system':'Exact embedded identity.','capabilities':['completion','thinking']})
        body=json.loads(request.content);calls.append(body)
        complete=finishes and len(calls)==2
        return httpx.Response(200,text=json.dumps({'message':{'content':'A complete answer.' if complete else 'An unfinished sen'},'done':True,'done_reason':'stop' if complete else 'length'})+'\n')
    manager=ModelManager(transport=httpx.MockTransport(runtime))
    await manager.start(AIConfig(model='evelyn-lite-v1:latest'))
    messages=[];speech=ConversationService(ObservationFixture(),messages.append,manager,director=ConversationDirector(DirectorConfig(enabled=False)))
    speech.request('Hello',user=True);await speech.task
    assert len(calls)==2 and [c['options']['num_predict'] for c in calls]==[2048,4096]
    assert all(c['think'] is False for c in calls)
    assert calls[0]['messages']==calls[1]['messages']
    starts=[i for i,m in enumerate(messages) if m['type']=='response_start']
    assert len(starts)==2 and messages[starts[1]]['reason']=='output_budget_retry'
    final=[m for m in messages if m['type']=='speech']
    if finishes:
        assert final[-1]['text']=='A complete answer.'
        assert [m['content'] for m in speech.history]==['Hello','A complete answer.']
        assert ''.join(m['text'] for m in messages[starts[1]+1:] if m['type']=='response_delta')=='A complete answer.'
    else:
        assert not final and not speech.history
        assert '4096-token output limit' in next(m['detail'] for m in messages if m['type']=='conversation_error')
    await speech.close();await manager.stop()


async def test_non_thinking_truncation_is_explicit_not_a_success():
    from companion_ai.llm import OutputBudgetExceededError
    provider=OllamaProvider('test',transport=httpx.MockTransport(lambda r:httpx.Response(200,text=json.dumps({'message':{'content':'Unfinished'},'done':True,'done_reason':'length'})+'\n')))
    with pytest.raises(OutputBudgetExceededError,match='incomplete'):
        await collect_reply(provider,LLMRequest(AIConfig(model='test',thinking=False), (ChatMessage('user','Hi'),)))
