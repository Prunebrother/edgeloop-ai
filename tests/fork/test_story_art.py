# SPDX-License-Identifier: AGPL-3.0-only
"""Story registry, serving boundaries, deterministic placeholders and release gate (no real art)."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest
from tools.story_art import load_registry, validate

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location('story_' + name.replace('-', '_'), ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def fixture(root):
    folder = root / 'src/assets/story/test_campaign'; folder.mkdir(parents=True)
    (folder / 'arrival.webp').write_bytes(b'synthetic webp')
    item = {'kind': 'illustration', 'file': 'arrival.webp', 'status': 'integrated',
            'sha256': hashlib.sha256(b'synthetic webp').hexdigest(), 'source': None,
            'approved_by': None, 'approved_at': None, 'explicit': False, 'description': 'A reception area'}
    registry = {'schema_version': 1, 'campaign': 'test_campaign', 'slots': {'arrival': item}}
    (folder / 'ASSETS.json').write_text(json.dumps(registry))
    return folder, registry


def test_registry_valid_file(tmp_path):
    folder, registry = fixture(tmp_path)
    assert validate(load_registry(folder / 'ASSETS.json'), folder) == registry


@pytest.mark.parametrize('change, match', [
    ({'unknown': True}, 'unknown keys'), ({'status': 'ready'}, 'invalid status'),
    ({'sha256': '0' * 64}, 'sha256 mismatch'), ({'file': 'missing.webp'}, 'missing file'),
    ({'source': {'workflow': 'test', 'seed': 1, 'take': 'test.png', 'unknown': 1}}, 'source keys'),
    ({'explicit': 'false'}, 'boolean'), ({'file': '../escape.webp'}, 'invalid file'),
])
def test_registry_rejects_invalid_slot(tmp_path, change, match):
    folder, registry = fixture(tmp_path)
    registry['slots']['arrival'].update(change)
    with pytest.raises(ValueError, match=match): validate(registry, folder)


def test_registry_rejects_top_level_unknown_key_and_symlinks(tmp_path):
    folder, registry = fixture(tmp_path)
    with pytest.raises(ValueError, match='unknown keys'): validate(registry | {'extra': 1}, folder)
    (folder / 'arrival.webp').unlink()
    other = tmp_path / 'other.webp'; other.write_bytes(b'synthetic webp')
    (folder / 'arrival.webp').symlink_to(other)
    with pytest.raises(ValueError, match='symlink'): validate(registry, folder)


def boundary_cases(tmp_path):
    folder, registry = fixture(tmp_path)
    for name in ['unreferenced.webp', 'image.png', 'UPPER.WEBP']:(folder / name).write_bytes(b'fixture')
    (folder / 'link.webp').symlink_to(folder / 'arrival.webp')
    registry['slots']['link'] = registry['slots']['arrival'] | {'file': 'link.webp'}
    (folder / 'ASSETS.json').write_text(json.dumps(registry))
    base = '/src/assets/story/test_campaign/'
    cases = [(base + 'arrival.webp', True), (base + 'ASSETS.json', True),
             (base + 'unreferenced.webp', False), (base + 'image.png', False),
             (base + '../test_campaign/arrival.webp', False), (base + '%2e%2e/test_campaign/arrival.webp', False),
             (base + 'arrival.webp%00', False), (base + 'arrival.webp\0', False),
             (base + 'sub\\arrival.webp', False), (base + 'link.webp', False),
             (base + 'UPPER.WEBP', False), (base + './arrival.webp', False),
             (base + '/arrival.webp', False)]
    return [p for p, _ in cases], [ok for _, ok in cases]


def test_python_host_acceptance_and_refusal(tmp_path):
    paths, expected = boundary_cases(tmp_path)
    assert [load('serve_local').public_file(p, tmp_path) is not None for p in paths] == expected


def test_node_host_parity(tmp_path):
    if not (ROOT / 'app/host.mjs').is_file(): pytest.skip('Node host is not part of the public export')
    paths, expected = boundary_cases(tmp_path)
    script = "import {publicFile} from './app/host.mjs'; console.log(JSON.stringify(JSON.parse(process.argv[1]).map(p=>!!publicFile(p,process.argv[2]))));"
    result = subprocess.run(['node', '--input-type=module', '-e', script, json.dumps(paths), str(tmp_path)], cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize('bad', ['campaign', 'slots', 'symlink'])
def test_hosts_refuse_invalid_or_symlinked_registry(tmp_path, bad):
    folder, registry = fixture(tmp_path)
    if bad == 'campaign': registry['campaign'] = 'other'
    if bad == 'slots': registry['slots'] = []
    path = folder / 'ASSETS.json'; path.write_text(json.dumps(registry))
    if bad == 'symlink':
        other = tmp_path / 'registry.json'; other.write_text(path.read_text()); path.unlink(); path.symlink_to(other)
    assert load('serve_local').public_file('/src/assets/story/test_campaign/arrival.webp', tmp_path) is None
    if (ROOT / 'app/host.mjs').is_file():
        script = "import {publicFile} from './app/host.mjs'; console.log(!!publicFile('/src/assets/story/test_campaign/arrival.webp',process.argv[1]));"
        result = subprocess.run(['node', '--input-type=module', '-e', script, str(tmp_path)], cwd=ROOT, capture_output=True, text=True, check=True)
        assert result.stdout.strip() == 'false'


def inventory(root):
    files = {p.relative_to(root).as_posix(): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in root.rglob('*') if p.is_file() and p.name != 'MANIFEST.json'}
    (root / 'MANIFEST.json').write_text(json.dumps({'included': files}))


def release_tree(root):
    catalog = {'expressions': [str(n) for n in range(12)], 'characters': {'test': {'expressions': {}}}}
    for n in range(12):
        name = f'Character_Art/Test/{n}.png'; target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'fixture'); catalog['characters']['test']['expressions'][str(n)] = '/' + name
    path = root / 'src/assets/characters/manifest.json'; path.parent.mkdir(parents=True); path.write_text(json.dumps(catalog))
    return path, catalog


@pytest.mark.parametrize('case', ['no_story', 'integrated', 'placeholder', 'explicit', 'sha', 'character'])
def test_release_gate(tmp_path, monkeypatch, case):
    path, catalog = release_tree(tmp_path)
    if case == 'character':
        catalog['characters']['test']['status'] = 'placeholder'; path.write_text(json.dumps(catalog))
    if case not in {'no_story', 'character'}:
        folder, registry = fixture(tmp_path)
        if case == 'placeholder': registry['slots']['arrival']['status'] = 'placeholder'
        if case == 'explicit': registry['slots']['arrival']['explicit'] = True
        if case == 'sha': registry['slots']['arrival']['sha256'] = '0' * 64
        (folder / 'ASSETS.json').write_text(json.dumps(registry))
    inventory(tmp_path)
    module = load('validate-release'); monkeypatch.setattr(module, 'ROOT', tmp_path)
    result = module.validate()
    assert result['passed'] == (case in {'no_story', 'integrated'}), result
    if case not in {'no_story', 'integrated'}:
        assert any(('test' if case == 'character' else 'arrival') in str(e) for e in result['errors'])



@pytest.mark.parametrize('case', ['placeholder', 'explicit', 'sha', 'character'])
def test_test_build_allows_only_unintegrated_story_art(tmp_path, monkeypatch, case):
    """--test-build (public test builds) lets a placeholder story slot through; explicit art, a wrong hash and a
    placeholder character stay blocking."""
    path, catalog = release_tree(tmp_path)
    if case == 'character':
        catalog['characters']['test']['status'] = 'placeholder'; path.write_text(json.dumps(catalog))
    else:
        folder, registry = fixture(tmp_path)
        if case == 'placeholder': registry['slots']['arrival']['status'] = 'placeholder'
        if case == 'explicit': registry['slots']['arrival']['explicit'] = True
        if case == 'sha': registry['slots']['arrival']['sha256'] = '0' * 64
        (folder / 'ASSETS.json').write_text(json.dumps(registry))
    inventory(tmp_path)
    module = load('validate-release'); monkeypatch.setattr(module, 'ROOT', tmp_path)
    result = module.validate(test_build=True)
    assert result['passed'] == (case == 'placeholder'), result
    assert result['test_build'] and bool(result['test_build_allowed']) == (case == 'placeholder')
    assert not module.validate()['passed']

def test_placeholder_generator_is_repeatable_and_preserves_other_slots(tmp_path):
    # Pillow is deliberately not a runtime dependency of EdgeLoop.
    pytest.importorskip('PIL')
    from tools.make_placeholder_art import generate
    from PIL import Image
    generate('test_campaign', ['h_arrival', 'env_lab'], tmp_path)
    folder = tmp_path / 'src/assets/story/test_campaign'
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    generate('test_campaign', ['h_arrival'], tmp_path)
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}
    with Image.open(folder / 'h_arrival.webp') as image: assert image.size == (1536, 864)
    registry = load_registry(folder / 'ASSETS.json'); registry['slots']['h_arrival']['status'] = 'integrated'
    (folder / 'ASSETS.json').write_text(json.dumps(registry))
    with pytest.raises(ValueError, match='reviewed art'): generate('test_campaign', ['h_arrival'], tmp_path)


def test_seed_registry_matches_all_declared_placeholder_files():
    folder = ROOT / 'src/assets/story/rise_of_helix'
    registry = validate(load_registry(folder / 'ASSETS.json'), folder)
    assert len(registry['slots']) == 18
    assert all(item['status'] == 'placeholder' and not item['explicit'] for item in registry['slots'].values())


def test_release_validation_rules_for_story_only_characters(tmp_path, monkeypatch):
    """HELIX-030: a story character needs a neutral portrait, no model and no clips, and need not have all 12."""
    import importlib.util, hashlib
    spec = importlib.util.spec_from_file_location('vr_story', ROOT / 'tools/validate-release.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    catalog = json.loads((ROOT / 'src/assets/characters/manifest.json').read_text())
    catalog['characters'] = {k: v for k, v in catalog['characters'].items() if v.get('status') != 'placeholder'}
    for c in catalog['characters'].values():
        c.pop('animations', None)
    catalog['characters']['sci'] = {'name': 'Scientist', 'role': 'story', 'expressions': {'neutral': '/Character_Art/Sci/n.png'}}
    for c in catalog['characters'].values():
        for p in c['expressions'].values():
            (tmp_path / p.lstrip('/')).parent.mkdir(parents=True, exist_ok=True); (tmp_path / p.lstrip('/')).write_bytes(b'png')
    path = tmp_path / 'src/assets/characters/manifest.json'; path.parent.mkdir(parents=True)

    def errors(cat):
        path.write_text(json.dumps(cat))
        files = {str(p.relative_to(tmp_path)): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                 for p in tmp_path.rglob('*') if p.is_file() and p.name != 'MANIFEST.json'}
        (tmp_path / 'MANIFEST.json').write_text(json.dumps({'included': files}))
        return {(e['path'], e['category']) for e in module.validate()['errors']}

    assert errors(catalog) == set()
    bad = json.loads(json.dumps(catalog)); bad['models']['sci:latest'] = 'sci'
    assert ('sci', 'story character mapped to a model') in errors(bad)
    bad = json.loads(json.dumps(catalog)); bad['characters']['sci']['animations'] = {'neutral': {'webm': '/Character_Art/Sci/n.webm'}}
    (tmp_path / 'Character_Art/Sci/n.webm').write_bytes(b'webm')
    assert ('sci', 'story character with animations') in errors(bad)
    (tmp_path / 'Character_Art/Sci/n.webm').unlink()
    bad = json.loads(json.dumps(catalog)); bad['characters']['sci']['role'] = 'villain'
    assert ('sci', 'unknown character role') in errors(bad)
    bad = json.loads(json.dumps(catalog)); bad['characters']['sci']['status'] = 'placeholder'
    assert ('sci', 'placeholder manifest character') in errors(bad)
