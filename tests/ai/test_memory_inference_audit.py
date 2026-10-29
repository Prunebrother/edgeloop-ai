# SPDX-License-Identifier: AGPL-3.0-only
import asyncio,json
import httpx,pytest
from tests.fork.memory_inference_audit import InferenceAudit

class Stream(httpx.AsyncByteStream):
    def __init__(self,chunks,stall=False):self.chunks=chunks;self.stall=stall;self.closed=False
    async def __aiter__(self):
        for chunk in self.chunks:yield chunk
        if self.stall:await asyncio.Event().wait()
    async def aclose(self):self.closed=True

def audit(timeout=30):
    events=[];record={'request':2,'model':'evelyn-narrative-v1:latest','curator':False,'think':False,'input_characters':123}
    return InferenceAudit(record,timeout,lambda value,**kwargs:events.append(json.loads(value))),events,record

async def test_inference_deadline_bounds_stalled_stream_and_closes_owned_request():
    a,events,record=audit();stream=Stream([b'{"message":{"content":"synthetic"}}\n'],stall=True)
    response=httpx.Response(200,stream=stream)
    transport=httpx.MockTransport(lambda request:response)
    result=await a.forward(transport,httpx.Request('POST','http://127.0.0.1:11435/api/chat'))
    with pytest.raises(TimeoutError):await result.aread()
    assert record['status']=='timeout' and stream.closed
    assert events[-1]['event']=='inference_timeout' and 'synthetic' not in json.dumps(events)

async def test_inference_deadline_includes_wait_for_response_headers():
    a,events,record=audit()
    async def hang(request):await asyncio.Event().wait()
    with pytest.raises(TimeoutError):await a.forward(httpx.MockTransport(hang),httpx.Request('POST','http://127.0.0.1:11435/api/chat'))
    assert record['status']=='timeout'

async def test_audited_stream_preserves_chunks_and_records_only_terminal_metrics():
    a,events,record=audit(1000);chunks=[b'{"message":{"content":"private synthetic text"},"done":false}\n',b'{"done":true,"prompt_eval_',b'count":42,"eval_count":7}\n']
    result=await a.forward(httpx.MockTransport(lambda r:httpx.Response(200,stream=Stream(chunks))),httpx.Request('POST','http://127.0.0.1:11435/api/chat'))
    assert await result.aread()==b''.join(chunks)
    assert record['prompt_eval_count']==42 and record['eval_count']==7 and record['status']=='completed'
    assert 'private synthetic text' not in json.dumps(events)

async def test_cancelled_request_records_cancellation_and_closes_stream():
    a,events,record=audit(1000);stream=Stream([],stall=True)
    result=await a.forward(httpx.MockTransport(lambda r:httpx.Response(200,stream=stream)),httpx.Request('POST','http://127.0.0.1:11435/api/chat'))
    task=asyncio.create_task(result.aread());await asyncio.sleep(.01);task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert record['status']=='cancelled' and stream.closed


def test_fixture_pipeline_uses_test_timeouts_and_logs_requests_without_touching_ollama(monkeypatch,capsys):
    import importlib,sys
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from tests.fork.test_observer import until
    for key,value in {'EDGELOOP_MEMORY_ARM':'B','EDGELOOP_LIVE_ACCEPTANCE':'0','EDGELOOP_FIXTURE_OBSERVER_PORT':'18958','EDGELOOP_FIXTURE_UI_PORT':'18950','EDGELOOP_FIXTURE_TOKEN':'synthetic-progress-fixture-'+'x'*32,'EDGELOOP_FIXTURE_OLLAMA_TIMEOUT_MS':'5000'}.items():monkeypatch.setenv(key,value)
    name='tests.fork.intelligent_memory_service';monkeypatch.delitem(sys.modules,name,raising=False)
    fixture=importlib.import_module(name)
    class NoExternalOllama(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):raise AssertionError('Mock fixture touched external Ollama')
    fixture.audit.inner=NoExternalOllama()
    try:
        with TestClient(fixture.app) as client:
            with client.websocket_connect('/observe',headers={'Origin':'http://127.0.0.1:18950'}) as ws:
                ws.send_json({'version':1,'type':'auth','token':fixture.TOKEN,'browser_id':str(uuid4())});until(ws,'ready')
                model='evelyn-narrative-v1:latest'
                ws.send_json({'version':1,'type':'select_model','selection':{'model':model},'thinking':False});until(ws,'model_selected')
                assert fixture.app.state.models.config.timeout_seconds==6
                ws.send_json({'version':1,'type':'chat','model':model,'text':'Establish our scene as a fictional laboratory mystery.'})
                assert 'overgrown succulent' in until(ws,'speech')['text']
        record=fixture.audit.records[-1];assert record['request']==1 and record['status']=='completed' and record['timeout_ms']==5000
        output=capsys.readouterr().out;assert 'inference_started' in output and 'inference_completed' in output
        assert fixture.TOKEN not in output and 'Establish our scene' not in output
    finally:
        fixture.directory.cleanup();sys.modules.pop(name,None)
