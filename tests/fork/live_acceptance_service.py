# SPDX-License-Identifier: AGPL-3.0-only
"""Explicit live-test fixture: real companion + Ollama, temporary settings, no drivers.

Only the test transport can be interrupted. No production observer, daemon,
model definition or model store is changed. Never use as a normal launcher.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import httpx
import uvicorn
from ai_observer.server import create_app
from companion_ai.models import AIConfig
from companion_ai.storage import SettingsStore

MODELS = ('evelyn-lite-v1:latest', 'evelyn-qwen35-stable:latest', 'daisy-qwen35:latest')
TOKEN = 'live-fixture-token-' + 'x' * 32
UI_PORT = int(os.environ.get('EDGELOOP_FIXTURE_UI_PORT', '8780'))
OBSERVER_PORT = int(os.environ.get('EDGELOOP_FIXTURE_OBSERVER_PORT', '8788'))

class InterruptedStream(httpx.AsyncByteStream):
    def __init__(self, response, owner):
        self.response, self.owner = response, owner

    async def __aiter__(self):
        async for chunk in self.response.stream:
            yield chunk
            # Close only this real inference socket, never a daemon/process.
            await self.response.aclose()
            self.owner.stream_interruptions += 1
            raise httpx.ReadError('Test-only connection interrupted during real streaming')

    async def aclose(self):
        await self.response.aclose()


class AuditedTransport(httpx.AsyncBaseTransport):
    def __init__(self, transport=None):
        self.inner = transport or httpx.AsyncHTTPTransport()
        self.disconnected = False
        self.interrupt_stream = False
        self.stream_interruptions = 0
        self.systems = {}
        self.requests = []
        self.failures = 0

    async def handle_async_request(self, request):
        if (request.url.scheme, request.url.host, request.url.port) != ('http', '127.0.0.1', 11435):
            raise ValueError('Live fixture only permits the existing 11435 Ollama')
        if self.disconnected:
            self.failures += 1
            raise httpx.ConnectError('Test-only interrupted Ollama transport', request=request)
        if request.url.path == '/api/chat':
            body = json.loads(request.content)
            embedded = self.systems.get(body['model'], '')
            system = '\n'.join(m['content'] for m in body['messages'] if m['role'] == 'system')
            self.requests.append({
                'model': body['model'], 'thinking': body.get('think'), 'stream': body.get('stream'),
                'tools_absent': not body.get('tools'),
                'embedded_system_preserved': bool(embedded) and system.startswith(embedded+'\n\n') and system.count(embedded) == 1,
                'embedded_system_sha256': hashlib.sha256(embedded.encode()).hexdigest(),
                'history_markers': sorted(set(re.findall(r'F22_(?:ALPHA|BETA|GAMMA)', '\n'.join(m['content'] for m in body['messages'])))),
                'max_tokens': body['options']['num_predict'],
            })
        response = await self.inner.handle_async_request(request)
        if request.url.path == '/api/show' and response.status_code == 200:
            body = json.loads(request.content)
            self.systems[body['model']] = json.loads(await response.aread()).get('system', '')
        if request.url.path == '/api/chat' and self.interrupt_stream:
            return httpx.Response(response.status_code, headers=response.headers, stream=InterruptedStream(response, self))
        return response

    async def aclose(self):
        # Providers create short-lived HTTP clients. Keep this fixture's pool
        # available across them; process teardown releases it after all requests.
        pass

transport = AuditedTransport()
data = tempfile.TemporaryDirectory(prefix='edgeloop-live-acceptance-')
store = SettingsStore(data.name)
store.write('model-presets.json', {'ollama:'+m: AIConfig(model=m, thinking=False, max_tokens=256, timeout_seconds=120, idle_unload_seconds=60).model_dump() for m in MODELS})
app = create_app(TOKEN, data.name, transport=transport, ollama_url='http://127.0.0.1:11435', origins={f'http://127.0.0.1:{UI_PORT}'})

@app.post('/fixture/connection/{mode}')
async def connection(mode: str):
    if mode not in {'up', 'down', 'cut-stream'}:
        return {'error': 'Expected up, down or cut-stream'}
    transport.disconnected = mode == 'down'
    transport.interrupt_stream = mode == 'cut-stream'
    return {'disconnected': transport.disconnected}

@app.get('/fixture/state')
async def observed():
    return {'requests':transport.requests, 'connection_failures':transport.failures, 'stream_interruptions':transport.stream_interruptions,
            'metrics':list(app.state.models.metrics.samples),
            'active_history':list(app.state.speech.history),
            'thinking':app.state.models.config.thinking,
            'read_only':app.state.models.tool_executor is None,
            'observation':app.state.observation.report}

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=OBSERVER_PORT, access_log=False, ws_max_size=16384)
