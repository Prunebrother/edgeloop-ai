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
from companion_ai.llm import collect_reply, OllamaProvider,ChatMessage,LLMRequest,ToolDefinition,ToolCall,LLMEvent,NoVisibleResponseError
from companion_ai.storage import SettingsStore
from tests.ai.support import ObservationFixture
async def test_long_embedded_identity_is_rejected_without_truncation():
    embedded='X'*16000
    provider=OllamaProvider('qwen3:8b',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'system':embedded})))
    messages,_=compose_messages({},'Hello',[],AIConfig())
    with pytest.raises(ValueError,match='Embedded model instructions'):
        await collect_reply(provider,LLMRequest(AIConfig(),tuple(ChatMessage(**m) for m in messages)))
    assert provider.embedded_system==embedded


async def test_context_error_delivery_explains_budget_without_ollama_restart_advice():
    from companion_ai.context import ContextBudgetError
    class Adapter:
        async def reply(self,*args):
            raise ContextBudgetError(6000,4096)
    emitted=[];speech=ConversationService(ObservationFixture(),emitted.append,Adapter())
    speech.request('Hello',user=True);await speech.task
    error=next(m for m in emitted if m['type']=='conversation_error')
    assert '6000' in error['detail'] and '4096' in error['detail']
    assert 'Adapt' in error['detail'] and 'Start Ollama' not in error['detail']
    assert not speech.history
    await speech.close()
