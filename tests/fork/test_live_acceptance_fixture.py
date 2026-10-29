# SPDX-License-Identifier: AGPL-3.0-only
"""Guard the opt-in live fixture's network boundary using mocked transport only."""
import json
import httpx
import pytest
from tests.fork.live_acceptance_service import AuditedTransport

async def test_live_fixture_cannot_send_to_legacy_or_remote_ollama():
    delegated=[]
    transport=AuditedTransport(httpx.MockTransport(lambda request: delegated.append(request)))
    for origin in ['http://127.0.0.1:11434','http://example.com:11435']:
        with pytest.raises(ValueError,match='existing 11435'):
            await transport.handle_async_request(httpx.Request('GET',origin+'/api/tags'))
    assert not delegated

async def test_interrupted_fixture_never_reaches_real_transport_and_recovers():
    delegated=[]
    def handler(request):
        delegated.append(request.url.path)
        return httpx.Response(200,json={'models':[]})
    transport=AuditedTransport(httpx.MockTransport(handler));transport.disconnected=True
    request=httpx.Request('GET','http://127.0.0.1:11435/api/tags')
    with pytest.raises(httpx.ConnectError):await transport.handle_async_request(request)
    assert delegated==[] and transport.failures==1
    transport.disconnected=False
    assert (await transport.handle_async_request(request)).status_code==200
    assert delegated==['/api/tags']

async def test_live_audit_checks_exact_embedded_identity_without_storing_prompts():
    identity='Exact character definition.\n'
    def handler(request):
        if request.url.path=='/api/show':return httpx.Response(200,json={'system':identity})
        return httpx.Response(200,text='')
    transport=AuditedTransport(httpx.MockTransport(handler))
    await transport.handle_async_request(httpx.Request('POST','http://127.0.0.1:11435/api/show',json={'model':'test'}))
    payload={'model':'test','think':False,'stream':True,'options':{'num_predict':256},'messages':[{'role':'system','content':identity+'\n\nNeutral runtime context.'},{'role':'user','content':'F22_ALPHA private test content'}]}
    await transport.handle_async_request(httpx.Request('POST','http://127.0.0.1:11435/api/chat',json=payload))
    audit=transport.requests[-1]
    assert audit['embedded_system_preserved'] and audit['thinking'] is False
    assert audit['history_markers']==['F22_ALPHA'] and audit['tools_absent']
    assert 'private test content' not in json.dumps(audit)


async def test_midstream_fault_closes_only_the_test_response():
    class Stream(httpx.AsyncByteStream):
        closed=False
        async def __aiter__(self):
            yield b'first real frame\n'
            yield b'never forwarded\n'
        async def aclose(self):self.closed=True
    stream=Stream()
    transport=AuditedTransport(httpx.MockTransport(lambda request:httpx.Response(200,stream=stream)))
    transport.interrupt_stream=True
    payload={'model':'test','think':False,'stream':True,'options':{'num_predict':16},'messages':[]}
    response=await transport.handle_async_request(httpx.Request('POST','http://127.0.0.1:11435/api/chat',json=payload))
    frames=[]
    with pytest.raises(httpx.ReadError):
        async for frame in response.stream:frames.append(frame)
    assert frames==[b'first real frame\n'] and stream.closed
    assert transport.stream_interruptions==1
