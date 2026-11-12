# SPDX-License-Identifier: AGPL-3.0-only
"""Mira authoring and no-download build guard tests. Live voice quality is separate."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from companion_ai.llm import OllamaProvider

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('mira_check', ROOT / 'tools/check_mira.py')
mira = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mira)


def test_authoring_follows_standard_template_and_existing_parameter_conventions():
    assert all(mira.offline_checks().values())


def test_missing_base_never_invokes_build_or_download(monkeypatch):
    monkeypatch.setattr(mira, 'api', lambda *args: {'models': []})
    monkeypatch.setattr(mira.subprocess, 'run', lambda *args, **kwargs: pytest.fail('Must not invoke ollama without installed base'))
    with pytest.raises(RuntimeError, match='no download or build attempted'):
        mira.prepare('http://127.0.0.1:11435', build=True)


def test_existing_different_mira_is_preserved(monkeypatch):
    def api(host, path, data=None):
        return {'models': [{'name': mira.BASE}, {'name': mira.NAME}]} if path == '/api/tags' else {'system': 'A different existing character'}
    monkeypatch.setattr(mira, 'api', api)
    monkeypatch.setattr(mira.subprocess, 'run', lambda *args, **kwargs: pytest.fail('Must not overwrite existing different model'))
    with pytest.raises(RuntimeError, match='preserving it'):
        mira.prepare('http://127.0.0.1:11435', build=True)


def test_create_uses_installed_base_and_only_the_new_tag(monkeypatch):
    monkeypatch.setattr(mira, 'api', lambda *args: {'models': [{'name': mira.BASE}]})
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stderr='')
    monkeypatch.setattr(mira.subprocess, 'run', run)
    assert mira.prepare('http://127.0.0.1:11435', build=True)['status'] == 'created'
    assert calls[0][0] == ['ollama', 'create', mira.NAME, '-f', str(mira.SOURCE)]
    assert calls[0][1]['env']['OLLAMA_HOST'] == 'http://127.0.0.1:11435'
    assert len(calls) == 1  # no pull, no server start, no aliases altered


@pytest.mark.parametrize('host', ['https://127.0.0.1', 'http://other.example', 'http://127.0.0.1:11435/private', 'http://user:pass@localhost', 'http://127.0.0.1:99999'])
def test_live_runner_rejects_nonlocal_or_credentialed_origins(host):
    with pytest.raises(Exception):
        mira.origin(host)


@pytest.mark.asyncio
async def test_dialogue_cases_use_real_provider_native_persona_and_current_runtime_protocol(monkeypatch):
    bodies = []
    def transport(request):
        if request.url.path == '/api/show':
            return httpx.Response(200, json={'system': mira.source_system(mira.SOURCE.read_text()), 'capabilities': ['completion']})
        assert request.url.host == '127.0.0.1' and request.url.port == 11435
        assert request.url.path == '/api/chat'
        body = json.loads(request.content)
        bodies.append(body)
        case = mira.CASES[len(bodies) - 1]
        expression = case.get('expression', 'neutral')
        return httpx.Response(200, content=json.dumps({'message': {'content': '[[expression:' + expression + ']] A synthetic fixture response.'}, 'done': True, 'done_reason': 'stop'}) + '\n')
    monkeypatch.setattr(mira, 'OllamaProvider', lambda model, base_url: OllamaProvider(model, base_url=base_url, transport=httpx.MockTransport(transport)))
    rows = await mira.dialogue('http://127.0.0.1:11435')
    assert len(rows) == 10 and all(r['protocol_pass'] for r in rows)
    assert all(r['semantic_review'] == 'required' for r in rows)  # A fixture is not real model-quality evidence.
    for body in bodies:
        assert body['model'] == mira.NAME and body['think'] is False
        assert 'tools' not in body
        assert body['options']['num_ctx'] == 8192 and body['options']['num_predict'] == 384
        assert 'HELIX-MORPH/09' in body['messages'][0]['content']
        assert mira.FORMAT_INSTRUCTION in body['messages'][0]['content']
        assert mira.SYSTEM_RULES in body['messages'][0]['content']
