"""AGPL-3.0-only. Windows desktop lifecycle for the dedicated local EdgeLoop AI stack.

Windows has no systemd, so this supervisor starts the same three loopback services the Linux
units run (dedicated Ollama, read-only observer, static web UI), records them, and stops only
the processes it started. Occupied ports are reported, never freed by killing other programs.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[2]
URL = 'http://127.0.0.1:8770/'
PORTS = {'ollama': 11435, 'observer': 8768, 'web': 8770}
HTTP = build_opener(ProxyHandler({}))
TITLE = 'EdgeLoop AI'


def base_dir(env=os.environ):
    return Path(env.get('EDGELOOP_WINDOWS_HOME') or Path(env.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'EdgeLoop AI')


def layout(root=ROOT, base=None):
    base = base or base_dir()
    return {
        'python': root / '.venv/Scripts/python.exe',
        'ollama': root / 'runtime/ollama/ollama.exe',
        'models': root / 'models',
        'data': base / 'data',
        'runtime': base / 'runtime',
        'logs': base / 'logs',
        'state': base / 'runtime/stack.json',
        'pairing': base / 'runtime/pairing.json',
        'lock': base / 'runtime/control.lock',
    }


def services(paths, root=ROOT, env=os.environ):
    """The three services in start order: name, command, environment, health URL, health kind."""
    base = {k: v for k, v in env.items() if not k.startswith(('OLLAMA_', 'EDGELOOP_'))}
    ollama_env = dict(base, OLLAMA_HOST='127.0.0.1:11435', OLLAMA_MODELS=str(paths['models']), OLLAMA_NO_CLOUD='1',
                      OLLAMA_NUM_PARALLEL='1', OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_FLASH_ATTENTION='1')
    observer_env = dict(base, EDGELOOP_PAIRING_FILE=str(paths['pairing']), EDGELOOP_OBSERVER_PORT='8768',
                        EDGELOOP_OLLAMA_URL='http://127.0.0.1:11435', EDGELOOP_FORK_AI_DATA=str(paths['data']),
                        PYTHONUTF8='1')
    web_env = dict(base, EDGELOOP_PAIRING_FILE=str(paths['pairing']), PYTHONUTF8='1')
    python = str(paths['python'])
    return [
        ('ollama', [str(paths['ollama']), 'serve'], ollama_env, 'http://127.0.0.1:11435/api/tags', 'ollama'),
        ('observer', [python, '-I', '-m', 'ai_observer.server'], observer_env, 'http://127.0.0.1:8768/health', 'observer'),
        ('web', [python, str(root / 'tools/serve_local.py'), '8770'], web_env, URL, 'web'),
    ]


def healthy(url, kind):
    try:
        with HTTP.open(url, timeout=2) as response:
            if kind == 'web':
                return b'EdgeLoop' in response.read(4096)
            data = json.load(response)
            return isinstance(data.get('models'), list) if kind == 'ollama' else data.get('ok') is True and data.get('read_only') is True
    except (OSError, ValueError):
        return False


def port_free(port):
    import socket
    with socket.socket() as probe:
        if os.name == 'nt':
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def read_state(paths):
    try:
        return json.loads(paths['state'].read_text())
    except (OSError, ValueError):
        return {}


def ours(record):
    """The recorded process, only if it is still the very process we started (PIDs are reused)."""
    import psutil
    try:
        process = psutil.Process(record['pid'])
        if abs(process.create_time() - record['created']) > 1:
            return None
        if Path(process.exe()).resolve() != Path(record['exe']).resolve():
            return None
        return process
    except (psutil.Error, KeyError, OSError, TypeError, ValueError):
        return None


def stop_recorded(paths):
    import psutil
    state = read_state(paths)
    stopped = 0
    for name in ['web', 'observer', 'ollama']:
        process = ours(state.get(name, {}))
        if process is None:
            continue
        # Ollama runs model runners as child processes; stop the whole tree.
        tree = [*process.children(recursive=True), process]
        for item in tree:
            try:
                item.terminate()
            except psutil.Error:
                pass
        _, alive = psutil.wait_procs(tree, timeout=15)
        for item in alive:
            try:
                item.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(alive, timeout=5)
        stopped += 1
    for key in ['state', 'pairing']:
        try:
            paths[key].unlink()
        except FileNotFoundError:
            pass
    return stopped


def running(paths):
    state = read_state(paths)
    return bool(state) and all(ours(state.get(name, {})) for name in PORTS)


def start(paths, root=ROOT, deadline_seconds=90, open_browser=True):
    for directory in ['data', 'runtime', 'logs']:
        paths[directory].mkdir(parents=True, exist_ok=True)
    plan = services(paths, root)
    if running(paths) and all(healthy(url, kind) for _, _, _, url, kind in plan):
        if open_browser:
            os.startfile(URL)
        return 'already running'
    stop_recorded(paths)
    for name, port in PORTS.items():
        if not port_free(port):
            raise RuntimeError(f'Port {port} ({name}) is in use by another program. Close it and try again. No other program was stopped.')
    import psutil
    state = {}
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    try:
        for name, command, env, url, kind in plan:
            log = (paths['logs'] / f'{name}.log').open('ab')
            process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       creationflags=flags, close_fds=True)
            log.close()
            info = psutil.Process(process.pid)
            state[name] = {'pid': process.pid, 'created': info.create_time(), 'exe': info.exe()}
            paths['state'].write_text(json.dumps(state))
            deadline = time.monotonic() + deadline_seconds
            while not healthy(url, kind):
                if process.poll() is not None:
                    raise RuntimeError(f'The {name} service exited. See {paths["logs"] / (name + ".log")}.')
                if time.monotonic() > deadline:
                    raise RuntimeError(f'The {name} service did not become ready. See {paths["logs"] / (name + ".log")}.')
                time.sleep(.5)
    except BaseException:
        stop_recorded(paths)
        raise
    if open_browser:
        os.startfile(URL)
    return 'started'


def message(text, failed=False):
    # Started from a Start menu shortcut there is no console, so show a dialog.
    print(text, file=sys.stderr if failed else sys.stdout, flush=True)
    if os.name == 'nt' and (sys.stdout is None or not sys.stdout.isatty()) and not os.environ.get('EDGELOOP_WINDOWS_QUIET'):
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10 if failed else 0x40)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    parser.add_argument('--no-browser', action='store_true', help='Start services without opening the browser')
    parser.add_argument('--quiet', action='store_true', help='No dialogs (used by setup and uninstall)')
    args = parser.parse_args(argv)
    if args.quiet:
        os.environ['EDGELOOP_WINDOWS_QUIET'] = '1'
    paths = layout()
    paths['runtime'].mkdir(parents=True, exist_ok=True)
    import msvcrt
    with paths['lock'].open('a+') as lock:
        # One lifecycle action at a time; a second click waits for the first.
        while True:
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(.25)
        if args.action == 'status':
            state = read_state(paths)
            for name, _, _, url, kind in services(paths):
                alive = ours(state.get(name, {})) is not None
                print(f'{name}: {"running" if alive else "stopped"}, {"healthy" if healthy(url, kind) else "not answering"}')
            print('Logs: ' + str(paths['logs']))
            return 0
        if args.action == 'stop':
            stop_recorded(paths)
            message('EdgeLoop AI stopped. Web server, AI observer and Ollama are off. The browser tab can be closed.')
            return 0
        outcome = start(paths, open_browser=not args.no_browser)
        print(f'EdgeLoop AI {outcome}: {URL}', flush=True)
        return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError) as exc:
        message('EdgeLoop AI: ' + str(exc), failed=True)
        sys.exit(1)
