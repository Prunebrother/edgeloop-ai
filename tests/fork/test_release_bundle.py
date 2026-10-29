"""Installer integrity and clean-user defaults; never manage real user services."""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundle_verification_rejects_corruption_missing_files_and_escape(tmp_path):
    bundle = load('bundle')
    file = tmp_path / 'payload'
    file.write_bytes(b'public release fixture')
    record = {'files': {'payload': {'bytes': file.stat().st_size, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}}}
    (tmp_path / 'BUNDLE.json').write_text(json.dumps(record))
    bundle.verify(tmp_path)
    file.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='integrity'):
        bundle.verify(tmp_path)
    file.unlink()
    with pytest.raises(ValueError, match='Missing'):
        bundle.verify(tmp_path)
    record['files'] = {'../outside': {'bytes': 0, 'sha256': ''}}
    (tmp_path / 'BUNDLE.json').write_text(json.dumps(record))
    with pytest.raises(ValueError, match='unsafe'):
        bundle.verify(tmp_path)


def test_new_user_gets_nova_and_existing_selection_is_preserved(tmp_path):
    bundle = load('bundle')
    bundle.configure(tmp_path, desktop=False, start=False)
    data = tmp_path / '.local/share/edgeloop-ai/data'
    from companion_ai.conversation import ModelManager
    from companion_ai.storage import SettingsStore
    assert ModelManager(store=SettingsStore(data)).config.model == 'nova-narrative-v1:latest'
    file = data / 'selection.json'
    original = json.dumps({'config': {'model': 'daisy-narrative-v1:latest'}})
    file.write_text(original)
    bundle.configure(tmp_path, desktop=False, start=False)
    assert file.read_text() == original
    assert not (tmp_path / '.config/systemd').exists()


def test_bundled_desktop_uses_its_runtime_and_store(tmp_path):
    installer = load('install_desktop')
    root = tmp_path / 'app with spaces'
    for name in ['.venv/bin/python', 'runtime/ollama/bin/ollama']:
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()
    home = tmp_path / 'user'
    installer.install(root, home, reload=False)
    units = home / '.config/systemd/user'
    ollama = (units / 'edgeloop-ai-ollama.service').read_text()
    assert str(root / 'models') in ollama
    assert str(root / 'runtime/ollama/bin/ollama') in ollama
    assert 'OLLAMA_NO_CLOUD=1' in ollama
    observer = (units / 'edgeloop-ai-observer.service').read_text()
    assert str(home / '.local/share/edgeloop-ai/data') in observer
    web = (units / 'edgeloop-ai-web.service').read_text()
    assert f'ExecStart="{root}/.venv/bin/python"' in web
    assert f'WorkingDirectory={root}\n' in web


def test_release_art_and_model_inventory_is_complete():
    inputs = json.loads((ROOT / 'release-inputs.json').read_text())
    catalog = json.loads((ROOT / 'src/assets/characters/manifest.json').read_text())
    assert len(inputs['characters']) == 10
    for name in inputs['characters']:
        assert any(line.startswith('FROM ') for line in (ROOT / f'characters/models/{name}/Modelfile').read_text().splitlines())
        assert name + ':latest' in catalog['models']
    for character in catalog['characters'].values():
        assert len(character['expressions']) == 12
        for image in character['expressions'].values():
            assert (ROOT / image.lstrip('/')).read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
