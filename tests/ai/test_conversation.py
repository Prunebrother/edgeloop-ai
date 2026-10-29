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
async def settle(service):
    if service.task:
        await service.task


async def test_busy_drop_interrupt_and_safety_cancel():
    gate = asyncio.Event()
    class Slow:
        async def reply(self, *args):
            await gate.wait()
            return 'Old response'
    messages = []
    service = ConversationService(ObservationFixture(), messages.append, Slow())
    service.policy = SpeechPolicy(min_interval_seconds=0.0)
    service.request('edge')
    await asyncio.sleep(0)
    assert service.request('trend')['reason'] == 'busy'
    service.policy = SpeechPolicy(min_interval_seconds=0.0, interruption='interrupt')
    assert service.request('trend')['accepted']
    await asyncio.sleep(0)
    service.safety('emergency_stop')
    gate.set()
    await settle(service)
    assert messages[-1]['source'] == 'safety'
    assert not any(m.get('text') == 'Old response' for m in messages)
    await service.close()


@pytest.mark.parametrize('url', ['https://example.com', 'http://192.168.1.2:11434', 'http://localhost@evil.com', 'http://localhost/api', 'http://localhost?redirect=1'])
def test_ollama_restricted_to_loopback(url):
    with pytest.raises(ValueError):
        OllamaAdapter('test', url)


async def test_model_failure_does_not_change_device():
    def fail(request):
        return httpx.Response(503)
    messages = []
    state = ObservationFixture()
    service = ConversationService(state, messages.append, OllamaAdapter('test', transport=httpx.MockTransport(fail)))
    service.request('Hi', user=True)
    await settle(service)
    assert messages[-1]['type'] == 'conversation_error'
    assert not state.device.moving
    await service.close()
