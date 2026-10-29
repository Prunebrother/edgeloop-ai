# SPDX-License-Identifier: AGPL-3.0-only
"""Common local-provider contract and the single Ollama transport implementation.

Cancel the consuming task to abort streaming; HTTP contexts close on cancellation.
No provider imports a character repository, speech engine or device controller.
"""
import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import json
import time
from typing import Literal, Protocol
from urllib.parse import urlparse
from uuid import uuid4
import httpx


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key in provider response')
        result[key] = value
    return result

from .models import AIConfig, ModelSelection
from .diagnostics import Metrics


def thinking_support(metadata):
    """Prefer explicit modern controls; retain older Qwen capability compatibility."""
    controls=metadata.get('thinking') or {}
    values=controls.get('values')
    if isinstance(values,list):
        return {'can_enable':any(v is True for v in values),'can_disable':any(v is False for v in values)}
    supported='thinking' in (metadata.get('capabilities') or [])
    return {'can_enable':supported,'can_disable':True}


class InferenceCompatibilityError(ValueError):
    """No retry or change to model definitions is permitted."""


class OutputBudgetExceededError(ValueError):
    def __init__(self, config):
        self.budget_exhausted = True
        super().__init__(f'{config.model} reached its {config.max_tokens}-token output limit before finishing. '
            'The visible reply is incomplete; it was not added to conversation memory. '
            'Try a shorter request or turn thinking off.')


class NoVisibleResponseError(ValueError):
    def __init__(self, config, done_reason=None):
        self.budget_exhausted = config.thinking and done_reason == 'length'
        reason = 'produced no visible response after spending its output budget reasoning' if self.budget_exhausted else 'returned no visible response'
        super().__init__(f'{config.model} {reason} ({config.max_tokens} output tokens). '
            'No answer was delivered. Thinking remains ' + ('enabled.' if config.thinking else 'disabled.'))


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict
    id: str = field(default_factory=lambda: 'call_' + uuid4().hex)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict

    def as_json(self):
        return {'type': 'function', 'function': {'name': self.name,
            'description': self.description, 'parameters': self.parameters}}


@dataclass(frozen=True)
class ChatMessage:
    role: Literal['system', 'user', 'assistant', 'tool']
    content: str = ''
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None
    origin: str | None = None

    def for_ollama(self):
        result = {'role': self.role, 'content': self.content}
        if self.tool_calls:
            result['tool_calls'] = [{'id': call.id, 'type': 'function',
                'function': {'name': call.name, 'arguments': call.arguments}} for call in self.tool_calls]
        if self.role == 'tool':
            result['tool_name'] = self.tool_name
        return result


@dataclass(frozen=True)
class LLMRequest:
    config: AIConfig
    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolDefinition, ...] = ()
    id: str = field(default_factory=lambda: uuid4().hex)
    response_schema: dict | None = None


@dataclass(frozen=True)
class LLMEvent:
    kind: Literal['text_delta', 'tool_call', 'completed']
    text: str = ''
    call: ToolCall | None = None
    usage: dict = field(default_factory=dict)


class LLMProvider(Protocol):
    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]: ...
    async def discover(self) -> list[dict]: ...
    async def capabilities(self, model: str) -> dict: ...
    async def loaded(self) -> list[dict]: ...
    async def unload(self, model: str | None = None, force: bool = False) -> None: ...


class OllamaProvider:
    streaming = True
    provider_name = 'ollama'

    def __init__(self, model, base_url='http://127.0.0.1:11434', transport=None, config=None, metrics=None):
        url = urlparse(base_url)
        if url.scheme != 'http' or url.hostname not in {'127.0.0.1', 'localhost', '::1'} or url.username or url.password or url.query or url.fragment or url.path not in {'', '/'}:
            raise ValueError('Ollama must use a loopback HTTP origin')
        self.model, self.base_url, self.transport = model, base_url.rstrip('/'), transport
        self.config = config or AIConfig(model=model)
        self.metrics = metrics or Metrics()
        self.attempted = False
        self.lock = asyncio.Lock()
        self.embedded_system = None
        self.thinking_controls = None

    def client(self, timeout=5):
        return httpx.AsyncClient(base_url=self.base_url, timeout=timeout, trust_env=False, transport=self.transport)

    async def discover(self):
        async with self.client() as client:
            result = await client.get('/api/tags')
            result.raise_for_status()
            models=result.json().get('models',[])
            if not isinstance(models,list) or any(not isinstance(m,dict) or not isinstance(m.get('name'),str) for m in models):
                raise ValueError('Invalid Ollama model discovery response')
            for model in models:ModelSelection.model_validate({'model':model['name']})
            return models

    async def describe(self, model):
        async with self.client() as client:
            result = await client.post('/api/show', json={'model': model})
            if result.status_code == 404:
                raise ValueError('Model is not installed locally: ' + model)
            result.raise_for_status()
            return result.json()

    async def capabilities(self, model):
        data = await self.describe(model)
        if model == self.model:
            self.embedded_system = data.get('system', '')
            self.thinking_controls = thinking_support(data)
        limits = [v for k, v in data.get('model_info', {}).items() if k.endswith('.context_length') and isinstance(v, int)]
        return {'model': model, 'system': data.get('system', ''), 'capabilities': data.get('capabilities', []),
                'context_length': min(limits) if limits else data.get('details', {}).get('context_length'),
                'details': data.get('details', {}), 'parameters': data.get('parameters', ''), 'thinking': data.get('thinking')}

    async def loaded(self):
        async with self.client() as client:
            result = await client.get('/api/ps')
            result.raise_for_status()
            return result.json().get('models', [])

    async def stream(self, request):
        config = request.config
        if config.thinking:
            raise InferenceCompatibilityError('Thinking must be OFF in this runtime')
        if self.embedded_system is None or self.thinking_controls is None or config.model != self.model:
            metadata = await self.describe(config.model)
            if not thinking_support(metadata)['can_disable']:
                raise InferenceCompatibilityError('Selected model cannot comply with think:false; select a compatible model')
            self.embedded_system = metadata.get('system', '')
            self.thinking_controls = thinking_support(metadata)
            self.model = config.model
        if not self.thinking_controls['can_disable']:
            raise InferenceCompatibilityError('Selected model cannot comply with think:false; select a compatible model')
        messages = [m.for_ollama() for m in request.messages]
        if any(m['role'] == 'system' for m in messages):
            if self.embedded_system is None:
                await self.capabilities(config.model)
            # One SYSTEM works with templates rendering only .System. Keep the
            # Modelfile SYSTEM verbatim; the application contributes runtime rules only.
            runtime = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
            system = self.embedded_system + '\n\n' + runtime if self.embedded_system else runtime
            messages = [{'role':'system', 'content':system}] + [m for m in messages if m['role'] != 'system']
            if sum(len(m['content']) + 80 for m in messages) + len(json.dumps([t.as_json() for t in request.tools])) > (config.context_length - config.max_tokens - 64) * 2.5:
                raise ValueError('Embedded model instructions and runtime exceed estimated context budget; increase context length')
        payload = {'model': config.model, 'messages': messages,
            'stream': True, 'think': False, 'keep_alive': config.idle_unload_seconds,
            'options': {'num_ctx': config.context_length, 'num_thread': config.cpu_threads,
                        'num_predict': config.max_tokens, 'temperature': config.temperature,
                        'top_p': config.top_p, 'top_k': config.top_k, 'repeat_penalty': config.repeat_penalty}}
        if request.response_schema is not None:
            payload['format'] = request.response_schema
        if request.tools:
            payload['tools'] = [tool.as_json() for tool in request.tools]
        self.attempted = True
        started = time.monotonic()
        first_token = None
        content_size = 0
        thinking_characters = thinking_chunks = 0
        final = None
        calls = {}
        timeout = httpx.Timeout(config.timeout_seconds, connect=2)
        async with asyncio.timeout(config.timeout_seconds), self.lock, self.client(timeout) as client:
            async with client.stream('POST', '/api/chat', json=payload) as response:
                if response.status_code in {400, 422}:
                    raise InferenceCompatibilityError('Ollama rejected the thinking-OFF chat protocol; no fallback enabling thinking was attempted')
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if len(line) > 65536:
                        raise ValueError('Provider stream frame too large')
                    data = json.loads(line, object_pairs_hook=strict_object)
                    if data.get('error'):
                        raise ValueError('Ollama reported a generation error')
                    message = data.get('message', {})
                    thought = message.get('thinking', '')
                    if isinstance(thought, str) and thought:
                        thinking_characters += len(thought)
                        thinking_chunks += 1
                    text = message.get('content', '')
                    if not isinstance(text, str):
                        raise ValueError('Invalid model content')
                    if text:
                        if first_token is None:
                            first_token = time.monotonic() - started
                        content_size += len(text)
                        if content_size > 4000:
                            raise ValueError('Model response exceeded companion limit')
                        yield LLMEvent('text_delta', text=text)
                    for index, item in enumerate(message.get('tool_calls', [])):
                        function = item.get('function', {})
                        args = function.get('arguments', {})
                        if isinstance(args, str):
                            args = json.loads(args, object_pairs_hook=strict_object)
                        if not isinstance(args, dict) or not isinstance(function.get('name'), str):
                            raise ValueError('Invalid structured tool call')
                        key = function.get('index', index)
                        call = ToolCall(function['name'], args, item.get('id') or f'call_{request.id}_{key}')
                        if key in calls and (calls[key].name != call.name or calls[key].arguments != call.arguments):
                            raise ValueError('Conflicting tool-call frames')
                        calls[key] = call
                        if len(calls) > 16:
                            raise ValueError('Too many tool calls')
                    if data.get('done'):
                        final = data
                        break
        if final is None:
            raise ValueError('Ollama returned an incomplete response')
        self.metrics.record(time.monotonic() - started, final, first_token)
        self.metrics.samples[-1].update({'provider': self.provider_name, 'model': config.model,
            'thinking_policy_status':'unexpected_reasoning_suppressed' if thinking_characters else 'off_requested',
            'thinking_enabled': False, 'thinking_characters': thinking_characters,
            'thinking_chunks': thinking_chunks, 'thinking_tokens': final.get('thinking_count'),
            'output_budget': config.max_tokens, 'visible_characters': content_size, 'prompt_tokens': final.get('prompt_eval_count'), 'done_reason': final.get('done_reason')})
        if not (content_size or calls):
            raise NoVisibleResponseError(config, final.get('done_reason'))
        if final.get('done_reason') == 'length':
            raise OutputBudgetExceededError(config)
        for call in calls.values():
            yield LLMEvent('tool_call', call=call)
        yield LLMEvent('completed', usage=dict(self.metrics.samples[-1]))

    async def unload(self, model=None, force=False):
        if not self.attempted and not force:
            return
        async with self.client(10) as client:
            result = await client.post('/api/generate', json={'model': model or self.model, 'keep_alive': 0, 'stream': False, 'think': False})
            result.raise_for_status()


async def collect_reply(provider, request, on_chunk=None, on_expression=None):
    """Text-only application path: structured calls require an explicit external router."""
    from .expressions import ExpressionStream
    parser = ExpressionStream(on_expression, request.config.explicit_expressions)
    content = ''
    async for event in provider.stream(request):
        if event.kind == 'text_delta':
            visible = parser.feed(event.text)
            content += visible
            if on_chunk and visible:
                on_chunk(visible)
        elif event.kind == 'tool_call':
            raise ValueError('Unrequested tool call; no executor is enabled')
    remainder=parser.finish()
    content += remainder
    if remainder and on_chunk:on_chunk(remainder)
    provider.last_expression_metadata={'version':1,'valid':parser.valid,'expression':parser.expression,'candidate':parser.candidate}
    if not content.strip():raise NoVisibleResponseError(request.config)
    return content.strip()
