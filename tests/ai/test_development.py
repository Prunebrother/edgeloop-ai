# SPDX-License-Identifier: AGPL-3.0-only
import hashlib,json,os,socket,subprocess,sys
from pathlib import Path
import pytest
from ai_observer.config import RuntimeConfig
from ai_observer.diagnostics import local_model_directories
ROOT=Path(__file__).resolve().parents[2]


def test_observer_occupied_port_is_actionable_and_does_not_publish_token():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
        result=subprocess.run([sys.executable,'-I','-m','ai_observer.server'],env=dict(os.environ,EDGELOOP_OBSERVER_PORT=str(port)),capture_output=True,text=True,timeout=10)
        assert result.returncode!=0 and 'occupied' in result.stderr and 'No process was stopped' in result.stderr
        assert 'Pairing token' not in result.stdout
        assert listener.getsockname()[1]==port


def test_ui_occupied_port_is_actionable():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
        result=subprocess.run([sys.executable,str(ROOT/'tools/serve_local.py'),str(port)],capture_output=True,text=True,timeout=10)
        assert result.returncode!=0 and 'No process was stopped' in result.stderr and 'choose another port' in result.stderr


def test_migrated_modelfile_and_lore_bytes_match_recorded_source():
    source=json.loads((ROOT/'docs/fork/f22/migration-sources.json').read_text())
    for record in source['files']:
        if record['destination'].startswith('characters/') and record['reason']=='byte-for-byte source migration':
            assert hashlib.sha256((ROOT/record['destination']).read_bytes()).hexdigest()==record['source_sha256']


def test_process_diagnostics_never_expose_unrelated_environment_values(tmp_path):
    directory=tmp_path/'42';directory.mkdir()
    (directory/'cmdline').write_bytes(b'ollama\0serve\0')
    (directory/'environ').write_text('OLLAMA_HOST=127.0.0.1:11435\0OLLAMA_MODELS=/models/characters\0PRIVATE_TOKEN=secret\0')
    assert local_model_directories('http://127.0.0.1:11435',tmp_path)==[{'pid':42,'model_directory':'/models/characters'}]
    assert local_model_directories('http://127.0.0.1:11434',tmp_path)==[]


def test_runtime_and_launcher_do_not_import_the_legacy_application():
    for directory in ['companion_ai','ai_observer']:
        for path in (ROOT/directory).glob('*.py'):
            content=path.read_text()
            assert 'from edgeloop_ai' not in content and 'import edgeloop_ai' not in content
    launch=(ROOT/'tools/serve-ai.sh').read_text()
    assert 'PYTHONPATH' not in launch and 'EDGELOOP_AI_SOURCE' not in launch and '-I -m ai_observer.server' in launch
    assert not any((ROOT/'companion_ai'/name).exists() for name in ['core.py','session.py','session_bridge.py','tools.py','app.py','audio.py'])
