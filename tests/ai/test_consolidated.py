# SPDX-License-Identifier: AGPL-3.0-only
import asyncio,json,os,subprocess,sys
from pathlib import Path
import httpx,pytest
from companion_ai.conversation import ModelManager,ConversationService
from companion_ai.llm import thinking_support,NoVisibleResponseError
from companion_ai.models import AIConfig,MemoryConfig
from companion_ai.storage import SettingsStore
from tests.ai.support import ObservationFixture

NEW_MODELS=['evelyn-lite-v1:latest','evelyn-lite-candidate:latest','evelyn-qwen35-stable:latest','evelyn-qwen35:latest','daisy-qwen35:latest','daisy-v11:latest']
@pytest.mark.parametrize('model',NEW_MODELS)
@pytest.mark.parametrize('thinking',[False])
async def test_qwen35_embedded_identity_and_private_thinking_are_preserved(model,thinking):
    wire=[];identity='  Exact embedded character system for '+model+'\nUnchanged.\n'
    def runtime(request):
        if request.url.path=='/api/show':return httpx.Response(200,json={'system':identity,'capabilities':['completion','thinking'],'thinking':{'values':[True,False]},'model_info':{'qwen35.context_length':32768}})
        if request.url.path=='/api/ps':return httpx.Response(200,json={'models':[{'name':'unrelated:latest'}]})
        assert request.url.path=='/api/chat'
        wire.append(json.loads(request.content))
        return httpx.Response(200,text='\n'.join(json.dumps(row) for row in [
            {'message':{'thinking':'PRIVATE REASONING'},'done':False},
            {'message':{'content':'A visible answer.'},'done':False},
            {'message':{'content':''},'done':True,'done_reason':'stop'}])+'\n')
    manager=ModelManager(base_url='http://127.0.0.1:11435',transport=httpx.MockTransport(runtime))
    await manager.select(AIConfig(model=model,thinking=thinking))
    chunks=[];answer=await manager.reply({'source':'original_edgeloop','read_only':True},'Hello',[],on_chunk=chunks.append)
    body=wire[-1]
    assert answer=='A visible answer.' and chunks==[answer]
    assert body['think'] is thinking and body['model']==model and 'tools' not in body
    assert body['messages'][0]['content'].startswith(identity+'\n\n')
    assert body['messages'][0]['content'].count(identity)==1
    assert not any(x in body['messages'][0]['content'] for x in ['Personality:','Character:','Conversational style:'])
    assert 'PRIVATE' not in json.dumps(chunks) and 'PRIVATE' not in json.dumps(list(manager.metrics.samples))
    await manager.stop()

@pytest.mark.parametrize('values,expected',[([False],{'can_enable':False,'can_disable':True}),([True],{'can_enable':True,'can_disable':False}),([True,False],{'can_enable':True,'can_disable':True})])
def test_explicit_thinking_metadata_wins_over_generic_capability(values,expected):
    assert thinking_support({'capabilities':['completion','thinking'],'thinking':{'values':values}})==expected

async def test_endpoint_namespaces_keep_model_histories_separate(tmp_path):
    class Reply(ModelManager):
        async def reply(self,*args,**kwargs):return 'Visible response.'
    store=SettingsStore(tmp_path)
    first=Reply('http://127.0.0.1:11434',store=store);second=Reply('http://127.0.0.1:11435',store=store)
    for manager in [first,second]:manager.mode='ollama';manager.memory=MemoryConfig(persist_between_sessions=True)
    a=ConversationService(ObservationFixture(),lambda _:None,first);a.request('Legacy endpoint secret',user=True);await a.task
    b=ConversationService(ObservationFixture(),lambda _:None,second)
    assert not b.history and a.memory_path()!=b.memory_path()
    restored=ConversationService(ObservationFixture(),lambda _:None,first)
    assert any('Legacy endpoint secret' in m['content'] for m in restored.history)
    await a.close();await b.close();await restored.close()

def test_installed_observer_is_independent_of_legacy_checkout(tmp_path):
    code="import sys,companion_ai,ai_observer.server; assert not any(m.startswith('edgeloop_ai') for m in sys.modules); print(companion_ai.__file__)"
    env=dict(os.environ,PYTHONPATH='/nonexistent/legacy',PYTHONDONTWRITEBYTECODE='1')
    result=subprocess.run([sys.executable,'-I','-c',code],cwd=tmp_path,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert Path(result.stdout.strip()).resolve() == Path(__file__).resolve().parents[2]/'companion_ai/__init__.py'

async def test_selection_and_shutdown_do_not_unload_unrelated_external_models():
    seen=[]
    def runtime(request):
        seen.append(request.url.path)
        return httpx.Response(200,json={'capabilities':['completion','thinking'],'model_info':{'qwen.context_length':8192}} if request.url.path=='/api/show' else {'models':[{'name':'other-app:latest'}]})
    manager=ModelManager(transport=httpx.MockTransport(runtime))
    await manager.select(AIConfig());await manager.select(AIConfig(model='mira:latest'));await manager.stop()
    assert '/api/generate' not in seen


@pytest.mark.parametrize('payload',[{'models':[{'name':'No models loaded'}]},{'models':None},{'models':[{'name':42}]}])
async def test_invalid_discovery_is_rejected_before_a_model_can_be_selected(payload):
    from companion_ai.llm import OllamaProvider
    provider=OllamaProvider('test',transport=httpx.MockTransport(lambda request:httpx.Response(200,json=payload)))
    with pytest.raises(ValueError):await provider.discover()
