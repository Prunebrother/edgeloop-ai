"""Installer integrity and clean-user defaults; never manage real user services."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import shlex
import shutil
import subprocess
import sys
import tarfile
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


def test_seal_regenerates_canonical_hash_caches_on_repeated_pack_only_builds(tmp_path):
    builder = load('build-release')
    source = tmp_path / f'runtime/python/lib/python{sys.version_info.major}.{sys.version_info.minor}/probe.py'
    source.parent.mkdir(parents=True)
    source.write_text('def outer():\n    return lambda: 42\n')
    python = tmp_path / 'runtime/python/bin/python3'
    python.parent.mkdir()
    python.write_text('#!/bin/bash\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
    python.chmod(0o755)
    for _ in range(2):
        py_compile.compile(str(source), doraise=True)
        assert list(tmp_path.rglob('*.pyc'))
        builder.seal(tmp_path, {'version': 'test'})
        record = json.loads((tmp_path / 'BUNDLE.json').read_text())
        cache = next(tmp_path.rglob('*.pyc'))
        data = cache.read_bytes()
        assert int.from_bytes(data[4:8], 'little') == 3
        import marshal
        sealer = load('seal-python')
        assert set(sealer.code_filenames(marshal.loads(data[16:]))) == {'edgeloop-ai/' + str(source.relative_to(tmp_path))}
        assert str(cache.relative_to(tmp_path)) in record['files']
        load('bundle').verify(tmp_path)
        # Checked-hash invalidation survives the tar timestamp rewrite without
        # changing the sealed bytes, even if a caller omits -B.
        os.utime(source, (1793232000, 1793232000))
        subprocess.run([sys.executable, '-S', '-c',
                        'import sys; sys.path.insert(0, sys.argv[1]); import probe; assert probe.outer()() == 42',
                        str(source.parent)], check=True)
        assert cache.read_bytes() == data


def test_seal_rejects_an_external_symlink_before_compilation(tmp_path):
    target = tmp_path / 'external'
    target.write_text('private fixture')
    stage = tmp_path / 'stage'
    stage.mkdir()
    (stage / 'outside').symlink_to(target)
    with pytest.raises(ValueError, match='External symlink'):
        load('build-release').seal(stage, {'version': 'test'})


def test_corresponding_source_export_omits_only_the_unrelated_core_fixture(tmp_path):
    import io
    exporter = load('export-openmp-source')
    original = tmp_path / 'original.tar.xz'
    safe = {'gcc-8.5.0-20210514/COPYING3': b'original license fixture',
            'gcc-8.5.0-20210514/libgomp/source.c': b'original OpenMP source fixture'}
    with tarfile.open(original, 'w:xz') as archive:
        for name, data in {**safe, exporter.EXCLUDED: b'captured environment fixture'}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    output = tmp_path / 'export.tar.xz'
    result = exporter.rewrite_gcc(original, output)
    assert [x['name'] for x in result['removed']] == [exporter.EXCLUDED]
    with tarfile.open(output, 'r:xz') as archive:
        assert set(archive.getnames()) == set(safe)
        for name, data in safe.items():
            assert archive.extractfile(name).read() == data


@pytest.mark.parametrize('fixed', [False, True])
def test_download_installer_preserves_sealed_bytecode_and_cached_parts(tmp_path, fixed):
    # A tiny offline release reproduces Python rewriting sealed bytecode after
    # tar normalizes source timestamps. The inner installer stays unpatched,
    # as it does in the existing v0.3.0 release.
    stage = tmp_path / 'stage'
    lib = stage / 'runtime/python/lib'
    lib.mkdir(parents=True)
    probe = lib / 'cache_probe.py'
    probe.write_text('value = 42\n')
    os.utime(probe, (1704067200, 1704067200))
    py_compile.compile(str(probe), doraise=True)
    python = stage / 'runtime/python/bin/python3'
    python.parent.mkdir()
    runner = 'import cache_probe, runpy, sys; sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name="__main__")'
    python.write_text('#!/bin/bash\nexport PYTHONPATH="$(dirname "$0")/../lib"\nexec '
                      + shlex.quote(sys.executable) + ' -c ' + shlex.quote(runner) + ' "$@"\n')
    python.chmod(0o755)
    (stage / 'tools').mkdir()
    shutil.copyfile(ROOT / 'tools/bundle.py', stage / 'tools/bundle.py')
    (stage / 'tools/install-bundle.sh').write_text(
        '#!/bin/bash\nset -eu\ncd "$(dirname "$0")/.."\n'
        'runtime/python/bin/python3 tools/bundle.py verify\n'
        'touch "$HOME/installation-complete"\n')
    files = {str(p.relative_to(stage)): {'bytes': p.stat().st_size,
             'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in stage.rglob('*') if p.is_file()}
    (stage / 'BUNDLE.json').write_text(json.dumps({'files': files}))
    assets = tmp_path / 'assets'
    assets.mkdir()
    part = assets / 'edgeloop-ai-linux-x86_64.tar.gz.part00'
    def normalize(info):
        info.mtime = 1793232000
        return info
    with tarfile.open(part, 'w:gz') as archive:
        archive.add(stage, arcname='.', filter=normalize)
    (assets / 'SHA256SUMS').write_text(hashlib.sha256(part.read_bytes()).hexdigest() + '  ' + part.name + '\n')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    curl = bin_dir / 'curl'
    curl.write_text('#!/bin/bash\nset -eu\nwhile (($#)); do\n'
                    'case "$1" in https://*) name=${1##*/};; -o) shift; out=$1;; esac\nshift\ndone\n'
                    'echo "$name" >> "$DOWNLOAD_LOG"\ncp "$RELEASE_ASSETS/$name" "$out"\n')
    curl.chmod(0o755)
    installer = tmp_path / 'install.sh'
    text = (ROOT / 'install.sh').read_text()
    if not fixed:
        text = text.replace('export PYTHONDONTWRITEBYTECODE=1\n', '')
    installer.write_text(text)
    home = tmp_path / 'home'
    home.mkdir()
    env = dict(os.environ, HOME=str(home), XDG_CACHE_HOME=str(home / '.cache'),
               PATH=str(bin_dir) + os.pathsep + os.environ['PATH'],
               RELEASE_ASSETS=str(assets), DOWNLOAD_LOG=str(tmp_path / 'downloads'))
    env.pop('PYTHONDONTWRITEBYTECODE', None)
    for attempt in range(2):
        result = subprocess.run(['bash', str(installer)], env=env, capture_output=True, text=True)
        if fixed:
            assert result.returncode == 0, result.stdout + result.stderr
            assert (home / 'installation-complete').is_file()
            assert 'No such file' not in result.stderr
        else:
            assert result.returncode != 0
            assert 'Bundled file failed integrity check:' in result.stderr
            assert 'cache_probe' in result.stderr
    # Failed installs retry from verified cached parts; successful installs reuse
    # the destination. Neither path should download the large archive twice.
    assert (tmp_path / 'downloads').read_text().splitlines().count(part.name) == 1
