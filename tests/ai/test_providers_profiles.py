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
def fake_runtime(limit=8192):
    requests=[]
    def handler(request):
        body=json.loads(request.content) if request.content else {}
        requests.append((request.url.path,body))
        if request.url.path=='/api/show':
            if body['model']=='missing:latest':
                return httpx.Response(404,json={'error':'missing'})
            return httpx.Response(200,json={'capabilities':['completion','thinking','tools'],'model_info':{'test.context_length':limit}})
        if request.url.path=='/api/tags':
            return httpx.Response(200,json={'models':[{'name':'qwen3:8b'},{'name':'mira:latest'}]})
        if request.url.path=='/api/ps':
            return httpx.Response(200,json={'models':[{'name':'qwen3:8b','size_vram':123}]})
        if request.url.path=='/api/generate':
            return httpx.Response(200,json={'done':True})
        return httpx.Response(200,text=json.dumps({'message':{'content':'Hello Mira.'},'done':True,'eval_count':3,'eval_duration':100000000})+'\n')
    return httpx.MockTransport(handler), requests


async def test_normalized_tool_call_and_result_round_trip():
    calls=[]
    def handler(request):
        if request.url.path=='/api/show':return httpx.Response(200,json={'capabilities':['completion']})
        body=json.loads(request.content);calls.append(body)
        if len(calls)==1:
            assert body['tools'][0]['function']['name']=='read_state'
            return httpx.Response(200,text=json.dumps({'message':{'tool_calls':[{'function':{'name':'read_state','arguments':{'scope':'session'}}}]},'done':True})+'\n')
        assert body['messages'][-1]['role']=='tool'
        assert body['messages'][-1]['tool_name']=='read_state'
        assert json.loads(body['messages'][-1]['content'])=={'moving':False}
        return httpx.Response(200,text=json.dumps({'message':{'content':'Stationary.'},'done':True})+'\n')
    provider=OllamaProvider('qwen3:8b',transport=httpx.MockTransport(handler))
    req=LLMRequest(AIConfig(),(ChatMessage('user','Read state.'),),(ToolDefinition('read_state','Read state',{'type':'object'}),))
    events=[e async for e in provider.stream(req)]
    call=next(e.call for e in events if e.kind=='tool_call')
    assert call.name=='read_state' and call.arguments=={'scope':'session'}
    assert req.id in call.id
    messages=req.messages+(ChatMessage('assistant',tool_calls=(call,)),ChatMessage('tool',json.dumps({'moving':False}),tool_call_id=call.id,tool_name=call.name))
    events=[e async for e in provider.stream(replace(req,messages=messages))]
    assert ''.join(e.text for e in events)=='Stationary.'


async def test_cancel_closes_provider_stream():
    entered,closed=asyncio.Event(),asyncio.Event()
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b''
        async def aclose(self):
            closed.set()
    provider=OllamaProvider('qwen3:8b',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={}) if r.url.path=='/api/show' else httpx.Response(200,stream=Stream())))
    async def consume():
        return [e async for e in provider.stream(LLMRequest(AIConfig(),(ChatMessage('user','Hello'),)))]
    task=asyncio.create_task(consume())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert closed.is_set()


async def test_total_inference_deadline():
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(10)
            yield b''
    provider=OllamaProvider('qwen3:8b',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={}) if r.url.path=='/api/show' else httpx.Response(200,stream=Stream())))
    with pytest.raises(TimeoutError):
        [e async for e in provider.stream(LLMRequest(AIConfig(timeout_seconds=1.0),(ChatMessage('user','Hi'),)))]


async def test_missing_model_does_not_unload_or_cancel_current(tmp_path):
    transport,requests=fake_runtime()
    manager=ModelManager(transport=transport)
    await manager.start(AIConfig())
    canceled=[]
    async def interrupt():canceled.append(True)
    with pytest.raises(ValueError,match='not installed'):
        await manager.select(AIConfig(model='missing:latest'),interrupt=interrupt)
    assert manager.config.model=='qwen3:8b' and manager.mode=='ollama'
    assert not canceled
    assert not any(path=='/api/generate' for path,_ in requests)


async def test_context_adaptation_is_explicit_and_retains_stored_history():
    transport,_=fake_runtime(limit=2048)
    manager=ModelManager(transport=transport)
    with pytest.raises(ValueError,match='explicitly adapt'):
        await manager.select(AIConfig(model='mira:latest',max_tokens=96))
    result=await manager.select(AIConfig(model='mira:latest',max_tokens=96),context_policy='adapt')
    assert result['config']['context_length']==2048
    assert result['context_warnings']
    history=[{'role':'user','content':'remember this '+str(i)+'x'*2000} for i in range(8)]
    original=list(history)
    messages,warnings=compose_messages({},'Hello',history,AIConfig(context_length=2048,max_tokens=96))
    assert history==original and warnings
    assert messages[-1]['content']=='Hello'


def test_runtime_is_never_silently_truncated():
    with pytest.raises(ValueError, match='not truncated'):
        compose_messages({'data':'x'*3000},'Hi',[],AIConfig(context_length=512))


def test_atomic_settings_failure_retains_previous_file(tmp_path,monkeypatch):
    store=SettingsStore(tmp_path);store.write('test.json',{'value':'old'})
    def fail(*args):raise OSError('disk full')
    monkeypatch.setattr('companion_ai.storage.os.replace',fail)
    with pytest.raises(OSError):store.write('test.json',{'value':'new'})
    assert store.read('test.json')=={'value':'old'}


async def test_model_histories_and_opt_in_persistent_memory(tmp_path):
    store=SettingsStore(tmp_path)
    class TestManager(ModelManager):
        async def reply(self,*args,**kwargs):return "A test-model reply."
    manager=TestManager(store=store)
    manager.mode="ollama"
    manager.memory=MemoryConfig(persist_between_sessions=True)
    speech=ConversationService(ObservationFixture(),lambda m:None,manager)
    speech.request('My nickname is Finch.',user=True);await speech.task
    original=list(speech.history)
    assert store.read(speech.memory_path()) == original
    manager.config=AIConfig(model='mira:latest');speech.activate_model()
    assert not speech.history
    speech.request('My nickname is Robin.',user=True);await speech.task
    manager.config=AIConfig();speech.activate_model()
    assert list(speech.history)==original
    restored=ConversationService(ObservationFixture(),lambda m:None,manager)
    assert list(restored.history)==original
    await speech.close();await restored.close()


async def test_switch_isolates_and_restores_full_user_context(tmp_path):
    transport, requests=fake_runtime()
    manager=ModelManager(transport=transport,store=SettingsStore(tmp_path))
    await manager.start(AIConfig())
    speech=ConversationService(ObservationFixture(),lambda m:None,manager)
    speech.request('My nickname is Finch.',user=True);await speech.task
    before=list(speech.history)
    async def cancel():
        speech.interrupt()
        await asyncio.gather(*speech.tasks,return_exceptions=True)
    await manager.select(AIConfig(model='mira:latest'),interrupt=cancel)
    speech.request('Hello Mira',user=True);await speech.task
    assert 'Finch' not in json.dumps([b for p,b in requests if p=='/api/chat'][-1])
    await manager.select(AIConfig(),interrupt=cancel)
    speech.activate_model()
    assert list(speech.history)==before
    await speech.close()


async def test_provider_registry_accepts_non_ollama_implementation():
    from companion_ai.llm import LLMEvent
    class OtherProvider:
        def __init__(self,*args):pass
        async def stream(self,request):
            assert request.config.provider=='local-compatible'
            assert request.messages[0].role=='system'
            yield LLMEvent('text_delta',text='Provider independent.')
            yield LLMEvent('completed')
        async def unload(self,model=None,force=False):pass
    manager=ModelManager()
    manager.factories['local-compatible']=OtherProvider
    await manager.start(AIConfig(provider='local-compatible',model='other'))
    assert await manager.reply({},'Hi',[])=='Provider independent.'
    await manager.stop()
