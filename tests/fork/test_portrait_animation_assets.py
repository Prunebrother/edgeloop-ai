# SPDX-License-Identifier: AGPL-3.0-only
"""Curated animation boundaries, export selection and release inventory. No sockets/models."""
import importlib.util
import json
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location('portrait_' + name.replace('-', '_'), ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def catalog():
    return {'expressions': ['neutral', 'happy'], 'characters': {'any-identity': {
        'expressions': {'neutral': '/Character_Art/Test/neutral.png'},
        'animations': {'neutral': {'webm': '/Character_Art/Test/idle.webm', 'mp4': '/Character_Art/Test/idle.mp4'}}}}}


def tree(tmp_path, c):
    m = tmp_path / 'src/assets/characters/manifest.json'
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps(c))
    for p in ['neutral.png', 'idle.webm', 'idle.mp4', 'unreferenced.webm']:
        dest = tmp_path / 'Character_Art/Test' / p
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b'synthetic fixture')


def test_both_hosts_allow_only_declared_clips_and_keep_private_paths_closed(tmp_path):
    c = catalog()
    tree(tmp_path, c)
    # Python and Node run the same boundary cases, including a symlink to an in-root file.
    (tmp_path / 'Character_Art/Test/link.webm').symlink_to(tmp_path / 'Character_Art/Test/idle.webm')
    c['characters']['any-identity']['animations']['happy'] = {'webm': '/Character_Art/Test/link.webm'}
    tree(tmp_path, c)
    paths = ['/Character_Art/Test/idle.webm', '/Character_Art/Test/idle.mp4', '/Character_Art/Test/neutral.png',
             '/Character_Art/Test/unreferenced.webm', '/Character_Art/Test/link.webm', '/.ai-data/private.webm',
             '/Character_Art/Test/../Test/idle.webm', '/Character_Art/Test/%2e%2e/Test/idle.webm',
             '/Character_Art/Test/idle.webm%00', '/Character_Art/Test\\idle.webm']
    static = load('serve_local')
    py = [static.public_file(p, tmp_path) is not None for p in paths]
    script = "import {publicFile} from './app/host.mjs'; console.log(JSON.stringify(JSON.parse(process.argv[1]).map(p=>!!publicFile(p,process.argv[2]))));"
    result = subprocess.run(['node', '--input-type=module', '-e', script, json.dumps(paths), str(tmp_path)], cwd=ROOT, capture_output=True, text=True, check=True)
    assert py == json.loads(result.stdout) == [True, True, True, False, False, False, False, False, False, False]


@pytest.mark.parametrize('expression,formats', [
    ('not-an-expression', {'webm': '/Character_Art/Test/idle.webm'}),
    ('happy', {'webm': 'https://other/idle.webm'}),
    ('happy', {'webm': '/Character_Art/Test/../Test/unreferenced.webm'}),
    ('happy', {'webm': '/Character_Art/Test/unreferenced.webm?x=1'}),
    ('happy', {'webm': '/Character_Art/Test/idle.mp4'}),
    ('happy', {'avi': '/Character_Art/Test/unreferenced.webm'}),
])
def test_invalid_declarations_do_not_expand_static_access(tmp_path, expression, formats):
    c = catalog()
    c['characters']['any-identity']['animations'] = {expression: formats}
    tree(tmp_path, c)
    assert load('serve_local').public_file('/Character_Art/Test/unreferenced.webm', tmp_path) is None
    assert load('serve_local').public_file('/Character_Art/Test/idle.webm', tmp_path) is None


def export_plan(monkeypatch, c, files):
    module = load('export-public-source')
    monkeypatch.setattr(module, 'committed_files', lambda rev: files)
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **k: json.dumps(c).encode())
    rules = {'exclude': {}, 'keep': [], 'art': {'catalog': 'catalog.json', 'root': 'Character_Art/', 'reason': 'unreferenced'}}
    return module.plan('fixture', rules)


def test_export_keeps_declared_animations_without_sweeping_the_art_archive(monkeypatch):
    c = catalog()
    files = ['Character_Art/Test/' + p for p in ['neutral.png', 'idle.webm', 'idle.mp4', 'unreferenced.webm']]
    included, excluded, _, portraits = export_plan(monkeypatch, c, files)
    assert set(included) == set(files[:3])
    assert excluded == {files[3]: 'unreferenced'}
    assert portraits == {files[0]}  # The existing portrait count keeps its meaning.


def test_export_refuses_missing_and_unsafe_declared_assets(monkeypatch):
    with pytest.raises(ValueError, match='not committed'):
        export_plan(monkeypatch, catalog(), [])
    c = catalog()
    c['characters']['any-identity']['animations']['neutral']['webm'] = '/Character_Art/Test/../private.webm'
    with pytest.raises(ValueError, match='Invalid curated'):
        export_plan(monkeypatch, c, [])


def test_release_inventory_accepts_declared_video_but_preserves_every_png(tmp_path, monkeypatch):
    module = load('validate-release')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    c = json.loads((ROOT / 'src/assets/characters/manifest.json').read_text())
    for character in c['characters'].values():
        character.pop('animations', None)  # Only the fixture clip below is declared.
        for p in character['expressions'].values():
            target = tmp_path / p.lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'fixture PNG')
    c['characters']['nova']['animations'] = {'neutral': {'webm': '/Character_Art/Nova/idle.webm'}}
    clip = tmp_path / 'Character_Art/Nova/idle.webm'
    clip.write_bytes(b'fixture WebM')
    manifest = tmp_path / 'src/assets/characters/manifest.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(c))
    import hashlib
    files = {str(p.relative_to(tmp_path)): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in tmp_path.rglob('*') if p.is_file()}
    (tmp_path / 'MANIFEST.json').write_text(json.dumps({'included': files}))
    assert module.validate()['passed']
    clip.unlink()
    assert 'missing declared animation' in {x['category'] for x in module.validate()['errors']}
    clip.write_bytes(b'fixture WebM')
    (tmp_path / 'Character_Art/Nova/unreferenced.mp4').write_bytes(b'private archive')
    assert 'unexpected unreferenced art' in {x['category'] for x in module.validate()['errors']}


def test_shipped_clip_declarations_point_at_committed_webm_files():
    """The curated catalog's clips exist, use the safe path shape and are WebM (EBML) files."""
    import re
    c = json.loads((ROOT / 'src/assets/characters/manifest.json').read_text())
    shape = re.compile(r'^/Character_Art/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.webm$')
    declared = 0
    for character in c['characters'].values():
        for expression, formats in character.get('animations', {}).items():
            assert expression in c['expressions']
            src = formats['webm']
            assert shape.match(src), src
            data = (ROOT / src.lstrip('/')).read_bytes()[:4]
            assert data == b'\x1a\x45\xdf\xa3', src
            declared += 1
    if c['presentation'].get('animated_characters_enabled'):
        assert declared > 0
