# SPDX-License-Identifier: AGPL-3.0-only
"""Isolated Character Builder browser fixture: real observer, mocked Ollama that records requests.

The mocked model has a built-in identity (Daisy) in its Modelfile SYSTEM so the test can prove
that the custom persona replaces it. No real model, device or live port is used.
"""
import json
import os
import tempfile
import httpx
import uvicorn
from ai_observer.server import create_app

UI_PORT = int(os.environ['EDGELOOP_FIXTURE_UI_PORT'])
OBSERVER_PORT = int(os.environ['EDGELOOP_FIXTURE_OBSERVER_PORT'])
TOKEN = 'browser-fixture-token-' + 'x' * 32
MODELS = ['huihui_ai/qwen3.5-abliterated:9b', 'daisy-narrative-f29-v014:latest']
DAISY = 'You are Daisy Mae Harper, an adult woman in the fictional EdgeLoop world. You own Cloverfield Farm.'
CHATS = []


def runtime(request):
    path = request.url.path
    if path == '/api/tags':
        return httpx.Response(200, json={'models': [{'name': m} for m in MODELS]})
    if path == '/api/show':
        return httpx.Response(200, json={'system': DAISY, 'capabilities': ['completion', 'thinking'],
                                         'thinking': {'values': [True, False]}, 'model_info': {'qwen35.context_length': 8192}})
    if path == '/api/ps':
        return httpx.Response(200, json={'models': []})
    body = json.loads(request.content)
    if 'messages' not in body:
        return httpx.Response(200, json={'done': True})
    CHATS.append(body)
    system = body['messages'][0]['content'] if body['messages'][0]['role'] == 'system' else ''
    current = body['messages'][-1]['content']
    if 'Wren Calloway' in system and 'A MOMENT TO SPEAK' in current:
        # Distinct lines, so the Director's repetition guard keeps every card reply.
        turns = sum('A MOMENT TO SPEAK' in c['messages'][-1]['content'] for c in CHATS)
        line = ['Logged: the tide turns at half past, and so do you.', 'Logged: one gull, three circles, no message yet.',
                'Logged: lamp trimmed, visitor still here. Good watch.', 'Logged: wind from the north, steady as you.'][(turns - 1) % 4]
    elif 'Wren Calloway' in system:
        line = 'Stillwater light, Saltglass Reach. You came on the supply boat.'
    else:
        line = 'Cloverfield Farm says hello.'
    return httpx.Response(200, text=json.dumps({'message': {'content': line}, 'done': True, 'done_reason': 'stop'}) + '\n')


app = create_app(TOKEN, tempfile.mkdtemp(prefix='character-builder-fixture-'), transport=httpx.MockTransport(runtime),
                 origins={f'http://127.0.0.1:{UI_PORT}'})


@app.post('/fixture/fast-deck')
async def fast_deck():
    from companion_ai.director import DirectorConfig
    from companion_ai.event_deck import DeckSettings
    from companion_ai.models import SpeechPolicy
    speech = app.state.speech
    speech.policy = SpeechPolicy(min_interval_seconds=0.0, user_grace_seconds=0.0)
    app.state.director.config = DirectorConfig(user_idle_before_spontaneous_seconds=0.0)
    speech.deck_settings = DeckSettings(enabled=True, countdown_seconds=0)
    speech.last_event = float('-inf')
    speech.busy_until = 0
    return {'ok': True}


@app.get('/fixture/chats')
async def chats():
    return [{'model': c['model'], 'system': c['messages'][0]['content'] if c['messages'][0]['role'] == 'system' else '',
             'last': c['messages'][-1]['content']} for c in CHATS]


@app.get('/fixture/scope')
async def scope():
    return {'scope': app.state.speech.active_model_id, 'deck': app.state.speech.deck_diagnostics()}


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=OBSERVER_PORT, access_log=False, ws_max_size=16384)
