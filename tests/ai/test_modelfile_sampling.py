# SPDX-License-Identifier: AGPL-3.0-only
"""Sampling belongs to each companion's Modelfile: the app sends none unless code sets it on purpose."""
import json
import httpx
from companion_ai.conversation import ModelManager
from companion_ai.llm import ChatMessage, LLMRequest, OllamaProvider
from companion_ai.models import AIConfig, SAMPLING_KEYS, stored_config
from companion_ai.storage import SettingsStore

LEGACY = {'provider': 'ollama', 'model': 'nova-narrative-f29-v011:latest', 'context_length': 8192, 'max_tokens': 2048,
          'cpu_threads': 8, 'idle_unload_seconds': 120, 'temperature': 0.4, 'top_p': 0.95, 'top_k': 20,
          'repeat_penalty': 1.0, 'timeout_seconds': 120.0, 'thinking': False, 'explicit_expressions': True,
          'response_length': 'inherit'}


async def options_sent(config):
    sent = []

    def handler(request):
        if request.url.path == '/api/show':
            return httpx.Response(200, json={})
        sent.append(json.loads(request.content)['options'])
        return httpx.Response(200, text=json.dumps({'message': {'content': 'Hi.'}, 'done': True}) + '\n')
    provider = OllamaProvider(config.model, transport=httpx.MockTransport(handler), config=config)
    [e async for e in provider.stream(LLMRequest(config, (ChatMessage('user', 'Hello'),)))]
    return sent[-1]


async def test_default_config_sends_no_sampling_so_the_modelfile_applies():
    options = await options_sent(AIConfig(model='nova-narrative-f29-v011:latest'))
    assert not set(SAMPLING_KEYS) & set(options)
    # Context, thread and output budgets stay app-managed.
    assert options == {'num_ctx': 8192, 'num_thread': 8, 'num_predict': 2048}


async def test_a_value_set_on_purpose_is_sent_alone():
    options = await options_sent(AIConfig(model='m', temperature=0.0))
    assert options['temperature'] == 0.0
    assert not {'top_p', 'top_k', 'repeat_penalty'} & set(options)


def test_legacy_saved_selection_no_longer_overrides_the_modelfile(tmp_path):
    store = SettingsStore(tmp_path)
    store.write('selection.json', {'config': LEGACY, 'ollama_url': 'http://127.0.0.1:11435'})
    config = ModelManager(store=store).config
    assert config.model == LEGACY['model'] and all(getattr(config, k) is None for k in SAMPLING_KEYS)


def test_stored_config_drops_only_sampling_and_saving_round_trips():
    kept = stored_config(LEGACY)
    assert set(LEGACY) - set(kept) == set(SAMPLING_KEYS)
    config = AIConfig.model_validate(kept)
    assert AIConfig.model_validate(json.loads(json.dumps(config.model_dump()))) == config
    assert stored_config(None) == {}
