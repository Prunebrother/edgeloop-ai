# SPDX-License-Identifier: AGPL-3.0-only
"""Dev identities and release boundaries, without building models or using Ollama."""
import copy
import json
from pathlib import Path
import struct
import subprocess
import sys
from unittest.mock import MagicMock
import pytest
from tests.fork.test_story_art import load, inventory, release_tree

ROOT = Path(__file__).resolve().parents[2]
# No shipped companion is a placeholder since Seraphine graduated (2026-11-23); the boundary tests use a
# synthetic one, so they prove the rule is based on status, not on the current cast.
IDS = ()


def catalog():
    return json.loads((ROOT / 'src/assets/characters/manifest.json').read_text())


def test_no_shipped_companion_is_a_placeholder():
    data = catalog()
    # Companions are the characters with a model; story-only characters (the Helix scientist) are not covered here.
    companions = set(data['models'].values())
    assert [cid for cid, c in data['characters'].items() if cid in companions and c.get('status') == 'placeholder'] == list(IDS)
    assert not [tag for tag in data['models'] if 'placeholder' in tag]
    assert not list((ROOT / 'characters/models').glob('*-placeholder'))


def test_validator_refuses_a_placeholder_by_name(tmp_path, monkeypatch):
    path, data = release_tree(tmp_path); cid = 'future'
    # The fixture's expressions are '0'..'11'; clips are irrelevant to the placeholder refusal.
    data['characters'][cid] = {'name': 'Future (placeholder)', 'status': 'placeholder',
                               'expressions': {e: f'/Character_Art/Future/{e}.png' for e in data['expressions']}}
    for source in set(data['characters'][cid]['expressions'].values()):
        p = tmp_path / source.lstrip('/'); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'fixture')
    path.write_text(json.dumps(data)); inventory(tmp_path)
    validator = load('validate-release'); monkeypatch.setattr(validator, 'ROOT', tmp_path)
    result = validator.validate()
    assert not result['passed']
    assert {'path': cid, 'category': 'placeholder manifest character'} in result['errors']


def test_export_omits_placeholder_art_models_and_catalog_in_temporary_git_repo(tmp_path, monkeypatch):
    exporter = load('export-public-source'); repo = tmp_path / 'repo'; repo.mkdir()
    data = copy.deepcopy(catalog())
    # An arbitrary future id proves this boundary is based on status, not the current cast.
    data['characters']['future'] = {'name': 'Future', 'status': 'placeholder', 'expressions': {'neutral': '/Character_Art/Future/n.png'}}
    data['models']['future-model:latest'] = 'future'
    data['characters'] = {k: v for k, v in data['characters'].items() if k in {*IDS, 'future'}} | {'public': {'name': 'Public', 'expressions': {'neutral': '/Character_Art/Public/n.png'}}}
    data['models'] = {tag: cid for tag, cid in data['models'].items() if cid in data['characters']} | {'public-model:latest': 'public'}
    files = {'src/assets/characters/manifest.json': json.dumps(data), 'MANIFEST.json': '{"included":{}}',
             'docs/fork/upstream-pin.json': '{"files":{}}', 'docs/fork/f2-changes.json': '{}',
             'tools/refresh-release-manifest.py': (ROOT / 'tools/refresh-release-manifest.py').read_text()}
    for cid, character in data['characters'].items():
        for source in set(character['expressions'].values()): files[source.lstrip('/')] = 'synthetic art'
    for tag in data['models']: files[f'characters/models/{tag.removesuffix(":latest")}/Modelfile'] = 'FROM synthetic'
    for name, text in files.items():
        p = repo / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Synthetic export fixture'], check=True)
    rules = {'exclude': {}, 'keep': [], 'art': {'catalog': 'src/assets/characters/manifest.json', 'root': 'Character_Art/', 'reason': 'unreferenced art'}}
    rulefile = tmp_path / 'rules.json'; rulefile.write_text(json.dumps(rules))
    monkeypatch.setattr(exporter, 'ROOT', repo)
    included, excluded, missing, portraits = exporter.plan('HEAD', rules)
    assert not missing and portraits == {'Character_Art/Public/n.png'}
    assert 'characters/models/public-model/Modelfile' in included
    for model in ['future-model']:
        assert f'characters/models/{model}/Modelfile' in excluded
    destination = tmp_path / 'export'
    monkeypatch.setattr(sys, 'argv', ['export-public-source.py', '--out', str(destination), '--rules', str(rulefile), '--no-validate'])
    exporter.main()
    exported = json.loads((destination / rules['art']['catalog']).read_text())
    assert set(exported['characters']) == {'public'}
    assert exported['models'] == {'public-model:latest': 'public'}
    assert sorted(p.relative_to(destination).as_posix() for p in (destination / 'Character_Art').rglob('*') if p.is_file()) == ['Character_Art/Public/n.png']
    assert sorted(p.parent.name for p in (destination / 'characters/models').glob('*/Modelfile')) == ['public-model']
    assert set(json.loads((destination / 'MANIFEST.json').read_text())['included']).issubset(included)


def test_bundle_builder_creates_only_explicit_release_models(tmp_path, monkeypatch):
    builder = load('build-release'); inputs = json.loads((ROOT / 'release-inputs.json').read_text())
    placeholder_models = {tag.removesuffix(':latest') for tag, cid in catalog()['models'].items() if catalog()['characters'][cid].get('status') == 'placeholder'}
    assert not placeholder_models.intersection([*inputs['characters'], *inputs['intermediate_characters']])
    assert not any(name in json.dumps(inputs) for name in placeholder_models)
    # Exercise the builder's command plan using a fake daemon and socket; no server is started.
    sock = MagicMock(); sock.__enter__.return_value.getsockname.return_value = ('127.0.0.1', 19001)
    monkeypatch.setattr(builder.socket, 'socket', lambda: sock)
    process = MagicMock(); process.poll.return_value = None
    monkeypatch.setattr(builder.subprocess, 'Popen', lambda *a, **k: process)
    response = MagicMock(); response.__enter__.return_value.read.return_value = json.dumps({'models': [{'name': n + ':latest'} for n in inputs['characters']] + inputs['models']}).encode()
    monkeypatch.setattr(builder.HTTP, 'open', lambda *a, **k: response)
    commands = []; monkeypatch.setattr(builder, 'run', lambda *a, **k: commands.append(a))
    builder.create_characters(tmp_path, inputs, tmp_path / 'fixture.log')
    created = [cmd[2] for cmd in commands if cmd[1] == 'create']
    assert created == [*inputs['intermediate_characters'], *inputs['characters']]
    assert not placeholder_models.intersection(created)


def test_silhouette_generator_skips_without_pillow(tmp_path, monkeypatch, capsys):
    from tools.make_placeholder_companions import generate
    monkeypatch.setitem(sys.modules, 'PIL', None)
    assert generate(tmp_path) == []
    assert 'Skipped: Pillow' in capsys.readouterr().out


def test_silhouette_generator_matches_committed_images(tmp_path):
    pytest.importorskip('PIL')
    from PIL import Image
    from tools.make_placeholder_companions import generate
    for path in generate(tmp_path):
        assert path.read_bytes() == (ROOT / path.relative_to(tmp_path)).read_bytes()
        with Image.open(path) as image:
            assert image.size == (1024, 1536) and image.getpixel((0, 0)) == (128, 128, 128)


def test_iris_graduated_from_placeholder_to_a_real_companion():
    """Iris got author-approved art, idle clips, persona and cards on 2026-11-20."""
    data = catalog(); character = data['characters']['iris']
    assert character['name'] == 'Iris Vale' and 'status' not in character and 'role' not in character
    assert data['models']['iris-narrative-v1:latest'] == 'iris' and data['models']['iris-narrative-f29-v018:latest'] == 'iris'
    assert 'iris-placeholder:latest' not in data['models'] and not (ROOT / 'characters/models/iris-placeholder').exists()
    for e in data['expressions']:
        assert character['expressions'][e] == f'/Character_Art/Iris/expressions/iris_{e}.png'
        assert character['animations'][e] == {'webm': f'/Character_Art/Iris/animations/iris_{e}.webm'}
        assert struct.unpack('>II', (ROOT / f'Character_Art/Iris/expressions/iris_{e}.png').read_bytes()[16:24]) == (1024, 1536)
        assert (ROOT / f'Character_Art/Iris/animations/iris_{e}.webm').read_bytes()[:4] == b'\x1aE\xdf\xa3'


def test_seraphine_graduated_from_placeholder_to_a_real_companion():
    """Seraphine got author-approved art, idle clips, persona, cards and greetings (2026-11-21..23)."""
    from companion_ai.conversation import character_identity
    data = catalog(); character = data['characters']['seraphine']
    assert character['name'] == 'Seraphine Vale' and 'status' not in character and 'role' not in character
    for tag in ('seraphine-narrative-v1:latest', 'seraphine-narrative-f29-v019:latest'):
        assert data['models'][tag] == 'seraphine' and character_identity(tag) == 'seraphine'
    assert 'seraphine-placeholder:latest' not in data['models'] and not (ROOT / 'characters/models/seraphine-placeholder').exists()
    for e in data['expressions']:
        assert character['expressions'][e] == f'/Character_Art/Seraphine/expressions/seraphine_{e}.png'
        assert character['animations'][e] == {'webm': f'/Character_Art/Seraphine/animations/seraphine_{e}.webm'}
        assert struct.unpack('>II', (ROOT / f'Character_Art/Seraphine/expressions/seraphine_{e}.png').read_bytes()[16:24]) == (1024, 1536)
        assert (ROOT / f'Character_Art/Seraphine/animations/seraphine_{e}.webm').read_bytes()[:4] == b'\x1aE\xdf\xa3'
