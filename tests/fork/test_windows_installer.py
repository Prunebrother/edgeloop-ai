# SPDX-License-Identifier: AGPL-3.0-only
"""Windows installer, build checks and launcher logic that can be tested on any platform."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load('build_windows', 'tools/windows/build-windows.py')
installer = load('install_windows', 'tools/windows/install_windows.py')
launcher = load('edgeloop_ai_windows', 'tools/windows/edgeloop_ai_windows.py')
serve = load('serve_local', 'tools/serve_local.py')


def test_windows_name_rules():
    assert build.windows_problems(['index.html', 'src/js/app.js']) == []
    assert 'differ only in case' in build.windows_problems(['MANIFEST.json', 'manifest.json'])[0]
    assert build.windows_problems(['docs/con.txt'])
    assert build.windows_problems(['a/b:c.js'])
    assert build.windows_problems(['trailing.'])
    assert build.windows_problems(['x' * 200])


def test_source_manifest_is_renamed_in_the_windows_bundle():
    text = (ROOT / 'tools/windows/build-windows.py').read_text()
    assert "'SOURCE-MANIFEST.json' if name == 'MANIFEST.json'" in text
    # The committed tree itself must stay free of other case collisions.
    names = [str(p.relative_to(ROOT).as_posix()) for p in ROOT.glob('src/**/*')]
    assert build.windows_problems(names) == []


def test_windows_file_version():
    assert build.numeric('v0.6.0-rc1') == '0.6.0.1'
    assert build.numeric('v0.6.0') == '0.6.0.0'


def test_pinned_windows_inputs():
    win = json.loads((ROOT / 'release-inputs.json').read_text())['windows']
    for key in ['python', 'ollama', 'inno_setup']:
        assert len(win[key]['sha256']) == 64 and win[key]['url'].startswith('https://')
    assert win['download_base'].startswith('https://github.com/')
    assert 'colorama==0.4.6' in win['extra_requirements']


def make_tar(files):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for name, body in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    return data.getvalue()


def split(blob, size):
    return [blob[i:i + size] for i in range(0, len(blob), size)]


def test_parts_are_streamed_into_one_extraction(tmp_path):
    files = {'./a.txt': b'alpha' * 1000, './dir/b.bin': os.urandom(50_000)}
    paths = []
    for i, chunk in enumerate(split(make_tar(files), 7_000)):
        path = tmp_path / f'p.part{i:02d}'
        path.write_bytes(chunk)
        paths.append(path)
    incoming = installer.extract(paths, tmp_path / 'v1')
    assert incoming.name == 'v1.incoming'
    assert (incoming / 'dir/b.bin').read_bytes() == files['./dir/b.bin']


def test_extraction_refuses_unsafe_members(tmp_path):
    path = tmp_path / 'evil.part00'
    path.write_bytes(make_tar({'../escape.txt': b'x'}))
    with pytest.raises(tarfile.TarError):
        installer.extract([path], tmp_path / 'v1')
    assert not (tmp_path / 'escape.txt').exists()


class Parts(BaseHTTPRequestHandler):
    blobs, served, fail_once = {}, [], set()
    truncate = {}
    ignore_range_once, wrong_range_once = set(), set()

    def log_message(self, *args):
        pass

    def do_GET(self):
        name = self.path.rsplit('/', 1)[-1]
        body = self.blobs[name]
        start = int(self.headers.get('Range', 'bytes=0-')[6:].split('-')[0])
        self.served.append((name, start))
        if name in self.ignore_range_once:
            self.ignore_range_once.discard(name)
            start = 0
        if name in self.fail_once:
            # Corrupt the first full download so the checksum retry is exercised.
            self.fail_once.discard(name)
            body = b'X' * len(body)
        self.send_response(206 if start else 200)
        self.send_header('Content-Length', str(len(body) - start))
        if start:
            reported = 0 if name in self.wrong_range_once else start
            self.wrong_range_once.discard(name)
            self.send_header('Content-Range', f'bytes {reported}-{len(body) - 1}/{len(body)}')
        self.end_headers()
        if self.truncate.get(name, 0):
            self.truncate[name] -= 1
            self.wfile.write(body[start:start + 1000])
            self.close_connection = True
            return
        self.wfile.write(body[start:])


@pytest.fixture
def server():
    Parts.blobs, Parts.served, Parts.fail_once = {}, [], set()
    Parts.truncate, Parts.ignore_range_once, Parts.wrong_range_once = {}, set(), set()
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Parts)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{httpd.server_port}'
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def part(name, body):
    return {'name': name, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}


def test_download_resumes_and_retries_on_bad_checksum(tmp_path, server):
    a, b = os.urandom(3 * installer.CHUNK + 5), os.urandom(1000)
    Parts.blobs, Parts.served, Parts.fail_once = {'a.part00': a, 'b.part01': b}, [], {'b.part01'}
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'a.part00.partial').write_bytes(a[:installer.CHUNK])  # An interrupted earlier run.
    found = installer.acquire([part('a.part00', a), part('b.part01', b)], server, cache, None)
    assert [p.read_bytes() for p in found] == [a, b]
    assert ('a.part00', installer.CHUNK) in Parts.served
    assert [s for s in Parts.served if s[0] == 'b.part01'] == [('b.part01', 0), ('b.part01', 0)]


def test_offline_parts_next_to_setup_are_used(tmp_path, server):
    body = os.urandom(2000)
    Parts.blobs, Parts.served = {'a.part00': b''}, []
    offline = tmp_path / 'usb'
    offline.mkdir()
    (offline / 'a.part00').write_bytes(body)
    found = installer.acquire([part('a.part00', body)], server, tmp_path / 'cache', offline)
    assert found == [offline / 'a.part00'] and Parts.served == []


def test_truncated_download_resumes_instead_of_starting_over(tmp_path, server, monkeypatch):
    monkeypatch.setattr(installer.time, 'sleep', lambda _: None)
    body = os.urandom(5000)
    Parts.blobs, Parts.truncate = {'p': body}, {'p': 2}
    target = tmp_path / 'p'
    installer.download(server + '/p', target, len(body), hashlib.sha256(body).hexdigest())
    assert target.read_bytes() == body
    assert Parts.served == [('p', 0), ('p', 1000), ('p', 2000)]


def test_exhausted_download_keeps_partial_for_next_setup(tmp_path, server):
    body = os.urandom(5000)
    Parts.blobs, Parts.truncate = {'p': body}, {'p': 1}
    target = tmp_path / 'p'
    checksum = hashlib.sha256(body).hexdigest()
    with pytest.raises(RuntimeError, match='Could not download'):
        installer.download(server + '/p', target, len(body), checksum, attempts=1)
    assert (tmp_path / 'p.partial').read_bytes() == body[:1000]
    installer.download(server + '/p', target, len(body), checksum)
    assert target.read_bytes() == body
    assert Parts.served == [('p', 0), ('p', 1000)]


@pytest.mark.parametrize('behavior', ['ignore_range_once', 'wrong_range_once'])
def test_resume_handles_ignored_or_incorrect_ranges(tmp_path, server, monkeypatch, behavior):
    monkeypatch.setattr(installer.time, 'sleep', lambda _: None)
    body = os.urandom(5000)
    Parts.blobs = {'p': body}
    getattr(Parts, behavior).add('p')
    (tmp_path / 'p.partial').write_bytes(body[:1000])
    target = tmp_path / 'p'
    installer.download(server + '/p', target, len(body), hashlib.sha256(body).hexdigest())
    assert target.read_bytes() == body
    assert Parts.served == [('p', 1000)] * (2 if behavior == 'wrong_range_once' else 1)


@pytest.fixture
def install_case(tmp_path, monkeypatch):
    """Small real filesystem transactions; only bundle acquisition and Python setup are replaced."""
    destination = tmp_path / 'app/v2'
    cache, data = tmp_path / 'cache', tmp_path / 'data'
    cache.mkdir()
    cached = cache / 'part00'
    cached.write_bytes(b'verified download')
    manifest = {'parts': [{'name': cached.name}], 'base_url': 'unused'}
    monkeypatch.setattr(installer, 'acquire', lambda *args: [cached])

    def extract(*args):
        incoming = destination.with_name('v2.incoming')
        incoming.mkdir(parents=True, exist_ok=True)
        (incoming / 'release-inputs.json').write_text(json.dumps({'default_model': 'nova:latest'}))
        return incoming

    monkeypatch.setattr(installer, 'extract', extract)
    monkeypatch.setattr(installer, 'verify', lambda root: None)
    monkeypatch.setattr(installer, 'stop_installed', lambda folder: None)
    monkeypatch.setattr(installer, 'prepare_python', lambda root: (root / 'READY').touch())
    return manifest, destination, cache, None, data


@pytest.mark.parametrize('phase', ['prepare_python', 'configure'])
@pytest.mark.parametrize('same_version', [True, False])
def test_failed_install_preserves_working_release_and_downloads(install_case, monkeypatch, phase, same_version):
    manifest, destination, cache, _, data = install_case
    working = destination if same_version else destination.with_name('v1')
    working.mkdir(parents=True)
    (working / 'WORKING').touch()
    data.mkdir()
    (data / 'selection.json').write_text('{"config":{"model":"mine"}}')

    def fail(*args):
        raise PermissionError('injected failure')

    monkeypatch.setattr(installer, phase, fail)
    with pytest.raises(PermissionError, match='injected failure'):
        installer.install(*install_case)
    assert (working / 'WORKING').is_file()
    assert not (destination / 'READY').exists()
    assert (cache / 'part00').exists()
    assert json.loads((data / 'selection.json').read_text())['config']['model'] == 'mine'


@pytest.mark.parametrize('replacement_exists', [True, False])
def test_retry_restores_pending_backup_even_if_download_fails(install_case, monkeypatch, replacement_exists):
    _, destination, _, _, _ = install_case
    previous = destination.with_name('v2.previous')
    previous.mkdir(parents=True)
    (previous / 'WORKING').touch()
    if replacement_exists:
        destination.mkdir()
        (destination / 'INCOMPLETE').touch()

    def fail(*args):
        raise RuntimeError('download unavailable')

    monkeypatch.setattr(installer, 'acquire', fail)
    with pytest.raises(RuntimeError, match='download unavailable'):
        installer.install(*install_case)
    assert (destination / 'WORKING').is_file()
    assert not (destination / 'INCOMPLETE').exists()
    assert not previous.exists()


def test_failed_retry_restores_working_backup_not_interrupted_replacement(install_case, monkeypatch):
    _, destination, _, _, _ = install_case
    previous = destination.with_name('v2.previous')
    previous.mkdir(parents=True)
    (previous / 'WORKING').touch()
    destination.mkdir()
    (destination / 'INCOMPLETE').touch()

    def fail(*args):
        raise RuntimeError('Python setup failed again')

    monkeypatch.setattr(installer, 'prepare_python', fail)
    with pytest.raises(RuntimeError, match='failed again'):
        installer.install(*install_case)
    assert (destination / 'WORKING').is_file()
    assert not (destination / 'INCOMPLETE').exists()


def test_failed_promotion_restores_previous_installation(install_case, monkeypatch):
    _, destination, _, _, _ = install_case
    destination.mkdir(parents=True)
    (destination / 'WORKING').touch()
    rename = Path.rename

    def fail_incoming(path, target):
        if path.name.endswith('.incoming'):
            raise PermissionError('promotion denied')
        return rename(path, target)

    monkeypatch.setattr(Path, 'rename', fail_incoming)
    with pytest.raises(PermissionError, match='promotion denied'):
        installer.install(*install_case)
    assert (destination / 'WORKING').exists()


def test_success_keeps_backups_until_setup_finalizes(install_case):
    manifest, destination, cache, _, data = install_case
    destination.mkdir(parents=True)
    (destination / 'WORKING').touch()
    older = destination.with_name('v1')
    older.mkdir()
    (older / 'OLD').touch()
    (cache / 'unrelated').touch()
    installer.install(*install_case)
    previous = destination.with_name('v2.previous')
    assert (previous / 'WORKING').is_file()
    assert (older / 'OLD').is_file()
    assert (destination / 'READY').is_file()
    assert (cache / 'part00').exists()
    assert (data / 'selection.json').exists()

    installer.finalize(destination, manifest, cache)
    assert not previous.exists()
    assert not older.exists()
    assert not (cache / 'part00').exists()
    assert (cache / 'unrelated').exists()
    assert (destination / 'READY').exists()
    installer.finalize(destination, manifest, cache)  # Idempotent cleanup.


def test_interrupted_cleanup_cannot_restore_half_deleted_backup(install_case, monkeypatch):
    manifest, destination, cache, _, _ = install_case
    destination.mkdir(parents=True)
    (destination / 'WORKING').touch()
    installer.install(*install_case)
    remove = installer.shutil.rmtree

    def partial_cleanup(path, **kwargs):
        if path.name.endswith('.retired'):
            (path / 'WORKING').unlink()
        else:
            remove(path, **kwargs)

    monkeypatch.setattr(installer.shutil, 'rmtree', partial_cleanup)
    installer.finalize(destination, manifest, cache)
    installer.recover_previous(destination)
    assert (destination / 'READY').is_file()
    assert destination.with_name('v2.retired').is_dir()


def test_new_install_selects_default_model_and_keeps_existing_settings(tmp_path):
    root = tmp_path / 'v1'
    root.mkdir()
    (root / 'release-inputs.json').write_text(json.dumps({'default_model': 'nova:latest'}))
    data = tmp_path / 'data'
    installer.configure(root, data)
    assert json.loads((data / 'selection.json').read_text())['config']['model'] == 'nova:latest'
    (data / 'selection.json').write_text('{"config": {"model": "mine"}}')
    installer.configure(root, data)
    assert 'mine' in (data / 'selection.json').read_text()


def test_launcher_service_plan_is_loopback_and_private(tmp_path):
    paths = launcher.layout(root=tmp_path / 'app', base=tmp_path / 'base')
    plan = launcher.services(paths, root=tmp_path / 'app', env={'PATH': 'x', 'OLLAMA_HOST': '0.0.0.0', 'EDGELOOP_OBSERVER_PORT': '1'})
    names = [s[0] for s in plan]
    assert names == ['ollama', 'observer', 'web']
    ollama, observer, web = (s[2] for s in plan)
    assert ollama['OLLAMA_HOST'] == '127.0.0.1:11435' and ollama['OLLAMA_NO_CLOUD'] == '1'
    assert ollama['OLLAMA_MODELS'] == str(tmp_path / 'app/models')
    assert observer['EDGELOOP_OBSERVER_PORT'] == '8768'
    assert observer['EDGELOOP_FORK_AI_DATA'] == str(tmp_path / 'base/data')
    assert observer['EDGELOOP_PAIRING_FILE'] == web['EDGELOOP_PAIRING_FILE'] == str(tmp_path / 'base/runtime/pairing.json')
    assert all(url.startswith('http://127.0.0.1:') for *_, url, _ in plan)
    assert plan[1][1][1:] == ['-I', '-m', 'ai_observer.server']


def test_launcher_only_stops_the_processes_it_started(tmp_path):
    import psutil
    me = psutil.Process()
    assert launcher.ours({'pid': me.pid, 'created': me.create_time(), 'exe': me.exe()}) is not None
    # A reused PID belongs to a different process: different start time or program.
    assert launcher.ours({'pid': me.pid, 'created': me.create_time() - 100, 'exe': me.exe()}) is None
    assert launcher.ours({'pid': me.pid, 'created': me.create_time(), 'exe': str(tmp_path / 'other.exe')}) is None
    assert launcher.ours({}) is None


def test_windows_home_override(tmp_path):
    assert launcher.base_dir({'EDGELOOP_WINDOWS_HOME': str(tmp_path)}) == tmp_path
    assert launcher.base_dir({'LOCALAPPDATA': str(tmp_path)}) == tmp_path / 'EdgeLoop AI'


@pytest.mark.parametrize('raw', ['/src/js/..%5C..%5C.venv%5Cpyvenv.cfg', '/src/js/app.js::$DATA', '/src/js/C:x.js', '/MANIFEST.json'])
def test_static_server_refuses_windows_path_tricks(raw):
    assert serve.public_file(raw) is None


def test_static_server_still_serves_the_app():
    assert serve.public_file('/src/js/app.js') is not None
    assert serve.public_file('/') is not None


def test_symlinks_become_copies_and_may_not_leave_the_bundle(tmp_path):
    stage = tmp_path / 'stage'
    (stage / 'models/blobs').mkdir(parents=True)
    (stage / 'models/blobs/sha256-x').write_text('{"manifest": 1}')
    (stage / 'models/latest').symlink_to('blobs/sha256-x')
    build.resolve_symlinks(stage)
    assert not (stage / 'models/latest').is_symlink()
    assert (stage / 'models/latest').read_text() == '{"manifest": 1}'
    (tmp_path / 'outside').write_text('secret')
    (stage / 'escape').symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError):
        build.resolve_symlinks(stage)
