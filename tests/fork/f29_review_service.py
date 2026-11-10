# SPDX-License-Identifier: AGPL-3.0-only
"""Local simulator review fixture: real F29 inference, temporary settings, no drivers."""
import json
import os
import tempfile

import httpx
import uvicorn

from ai_observer.server import create_app
from companion_ai.models import AIConfig
from companion_ai.storage import SettingsStore
from tests.ai.test_character_cards import MODELS

TOKEN = 'f29-local-review-' + 'x' * 32
UI_PORT = int(os.getenv('EDGELOOP_FIXTURE_UI_PORT', '18970'))
PORT = int(os.getenv('EDGELOOP_FIXTURE_OBSERVER_PORT', '18968'))


class ReviewTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.inner = httpx.AsyncHTTPTransport()
        self.calls = []

    async def handle_async_request(self, request):
        assert (request.url.scheme, request.url.host, request.url.port) == ('http', '127.0.0.1', 11435)
        assert request.url.path in {'/api/tags', '/api/show', '/api/ps', '/api/chat', '/api/generate'}
        body = json.loads(request.content) if request.content else {}
        if request.url.path == '/api/chat':
            assert body['model'] in MODELS.values()
            assert body.get('think') is False and not body.get('tools')
            self.calls.append({'model': body['model'], 'thinking': False, 'tools': False})
        if request.url.path == '/api/generate':
            # ModelManager may release its own resident model; this never edits storage.
            assert body.get('keep_alive') == 0 and not body.get('prompt')
        response = await self.inner.handle_async_request(request)
        if request.url.path == '/api/tags' and response.status_code == 200:
            content = json.loads(await response.aread())
            content['models'] = [m for m in content['models'] if m['name'] in MODELS.values()]
            return httpx.Response(200, json=content)
        return response

    async def aclose(self):
        pass  # Short-lived provider clients share this pool until the fixture exits.


transport = ReviewTransport()
data = tempfile.TemporaryDirectory(prefix='edgeloop-f29-review-')
store = SettingsStore(data.name)
store.write('model-presets.json', {
    'ollama:' + m: AIConfig(model=m, max_tokens=384, thinking=False).model_dump()
    for m in MODELS.values()
})
app = create_app(TOKEN, data.name, transport=transport,
                 ollama_url='http://127.0.0.1:11435',
                 origins={f'http://127.0.0.1:{UI_PORT}'})
assert app.state.models.tool_executor is None


@app.get('/fixture/state')
async def state():
    return {'read_only': app.state.models.tool_executor is None,
            'calls': transport.calls, 'history': list(app.state.speech.history),
            'observation': app.state.observation.report}


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=PORT, access_log=False, ws_max_size=16384)
