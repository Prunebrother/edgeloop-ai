# SPDX-License-Identifier: AGPL-3.0-only
"""An old version guard refuses v4 safely while real observer routing and Freeplay remain usable."""
import asyncio
from contextlib import suppress
import json
from uuid import uuid4
import httpx
import pytest
import companion_ai.campaign as campaign
from ai_observer.server import create_app
from tests.ai.test_campaign import CID, MODEL, service
from tests.ai.test_campaign_migration_matrix import install, fingerprint
from tests.ai.test_event_deck_content import service as speech_service, play_only, prompt


@pytest.fixture
def newer_save(tmp_path, monkeypatch):
    path = install(tmp_path, 'v4-round-trip.json'); before = fingerprint(path)
    # Simulate an older executable's compatibility guard, not a conversion of its compiled Progress model.
    monkeypatch.setattr(campaign, 'SCHEMA_VERSION', 3)
    monkeypatch.setattr(campaign, 'MIGRATIONS', {k: v for k, v in campaign.MIGRATIONS.items() if k < 3})
    return tmp_path, path, before


def test_older_version_guard_keeps_newer_save_and_only_disables_campaign(newer_save):
    root, path, before = newer_save; svc = service(root)
    assert 'saved by a newer EdgeLoop AI' in svc.error
    assert svc.state()['error'] == svc.error and svc.state()['campaigns']
    assert svc.progress.active is None and svc.attempt is None
    assert svc.model_context(MODEL['nova'], {'status': 'RUNNING'}) is None
    assert svc.allowed_settings() is None and svc.observe({'status': 'RUNNING'}, [], MODEL['nova']) == []
    for action in (lambda: svc.start(CID, 'orientation'), lambda: svc.answer('log', 'internal', {}, MODEL['nova'])):
        with pytest.raises(ValueError, match='saved by a newer EdgeLoop AI'): action()
    assert fingerprint(path) == before


async def test_freeplay_chat_and_shipped_deck_still_deliver_with_newer_save(newer_save):
    root, path, before = newer_save; svc = service(root)
    r, speech, wire, frames = await speech_service(edges=2, seconds=200)
    speech.campaign_brief = lambda: svc.model_context(MODEL['nova'], r.observation.report)
    try:
        assert speech.request('Tell me about the garden.', user=True)['accepted']; await speech.task
        assert any(message['type'] == 'speech' for message in frames)
        assert 'CAMPAIGN MISSION' not in prompt(wire)
        # A separate real deck scheduler avoids the first user reply's busy interval.
        await speech.close()
        r, speech, wire, frames = await speech_service(edges=2, seconds=200)
        speech.campaign_brief = lambda: svc.model_context(MODEL['nova'], r.observation.report)
        play_only(speech, 'edge-count-first'); speech.pump(); assert speech.task; await speech.task
        assert 'A MOMENT TO SPEAK' in prompt(wire)
        assert any(message['type'] == 'speech' for message in frames)
        assert fingerprint(path) == before
    finally: await speech.close()


class Socket:
    """In-memory transport for the actual /observe endpoint; no sockets or TestClient threads."""
    headers = {'origin': 'http://127.0.0.1:8770'}

    def __init__(self): self.incoming = asyncio.Queue(); self.outgoing = asyncio.Queue()
    async def accept(self): pass
    async def receive_text(self): return await self.incoming.get()
    async def send_json(self, message): await self.outgoing.put(message)
    async def close(self, **kwargs): pass
    async def send(self, message): await self.incoming.put(json.dumps(message))
    async def until(self, kind):
        async with asyncio.timeout(3):
            while True:
                message = await self.outgoing.get()
                if message['type'] == kind: return message


async def test_observer_returns_command_error_for_start_and_answer_instead_of_crashing(newer_save):
    root, path, before = newer_save
    app = create_app('x' * 40, root, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    ws = Socket(); endpoint = next(route.endpoint for route in app.routes if route.path == '/observe')
    task = asyncio.create_task(endpoint(ws))
    try:
        await ws.send({'version': 1, 'type': 'auth', 'token': 'x' * 40, 'browser_id': str(uuid4())})
        await ws.until('ready')
        for command in ({'action': 'get'}, {'action': 'start', 'campaign_id': CID, 'mission_id': 'orientation'},
                        {'action': 'answer', 'objective_id': 'log', 'answer': 'internal'}):
            await ws.send({'version': 1, 'type': 'campaign', **command})
            state = await ws.until('campaign_state')
            assert 'saved by a newer EdgeLoop AI' in state['error']
            if command['action'] != 'get': assert state['command_error'] == state['error']
            assert not task.done()
        assert fingerprint(path) == before
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError): await task
        await app.state.speech.close()
