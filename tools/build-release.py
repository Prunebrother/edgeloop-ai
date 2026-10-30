#!/usr/bin/env python3
"""AGPL-3.0-only. Build complete Linux assets from reviewed source and pinned inputs.

Requires Linux x86_64, Python 3.12+, curl, tar, bsdtar, zstd, gzip and split. Network is
used only to acquire public runtime/dependency inputs. Only the two named base
manifests and their content-addressed blobs are imported from --model-store;
private character aliases, keys, prompts, logs and history are never copied.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
HTTP = build_opener(ProxyHandler({}))


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(*args, **kwargs):
    # Build-time imports must not create machine-path bytecode in the stage.
    kwargs.setdefault('env', dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    subprocess.run([str(x) for x in args], check=True, **kwargs)


def acquire(record, target):
    if not target.is_file() or digest(target) != record['sha256']:
        run('curl', '-fL', '--retry', '3', record['url'], '-o', target)
    if digest(target) != record['sha256']:
        raise ValueError('Runtime checksum mismatch: ' + target.name)


def import_models(source, stage, inputs):
    for record in inputs['models']:
        manifest = source / 'manifests' / record['manifest']
        value = json.loads(manifest.read_text())
        model = [x for x in value['layers'] if x['mediaType'] == 'application/vnd.ollama.image.model']
        if len(model) != 1 or model[0]['digest'] != 'sha256:' + record['weights_sha256']:
            raise ValueError('Wrong base-model weights: ' + record['name'])
        for layer in [value['config'], *value['layers']]:
            name = layer['digest'].replace(':', '-')
            if not name.startswith('sha256-') or len(name) != 71:
                raise ValueError('Invalid blob identifier')
            blob = source / 'blobs' / name
            if digest(blob) != layer['digest'][7:] or blob.stat().st_size != layer['size']:
                raise ValueError('Base-model blob integrity failure: ' + name)
            out = stage / 'models/blobs' / name
            out.parent.mkdir(parents=True, exist_ok=True)
            if not out.exists() or digest(out) != layer['digest'][7:]:
                # Copy, never hardlink to a developer's live store.
                shutil.copyfile(blob, out)
            if layer['mediaType'] == 'application/vnd.ollama.image.license':
                notice = stage / 'licenses/models' / (record['name'].replace('/', '_').replace(':', '_') + '.txt')
                notice.parent.mkdir(parents=True, exist_ok=True)
                notice.write_bytes(blob.read_bytes())
        out = stage / 'models/manifests' / record['manifest']
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(manifest, out)


def create_characters(stage, inputs, log):
    # This daemon owns an isolated model store and a dynamically allocated port.
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    endpoint = f'http://127.0.0.1:{port}'
    env = dict(os.environ, OLLAMA_HOST=endpoint, OLLAMA_MODELS=str(stage / 'models'), OLLAMA_NO_CLOUD='1')
    binary = stage / 'runtime/ollama/bin/ollama'
    with log.open('w') as stream:
        process = subprocess.Popen([str(binary), 'serve'], env=env, stdout=stream, stderr=stream)
        try:
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError('Build Ollama exited; inspect the private build log')
                try:
                    with HTTP.open(endpoint + '/api/tags', timeout=1):
                        break
                except OSError:
                    time.sleep(.25)
            else:
                raise RuntimeError('Build Ollama did not become ready')
            for name in inputs['characters']:
                run(binary, 'create', name, '-f', stage / f'characters/models/{name}/Modelfile', env=env)
        finally:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def seal(stage, inputs):
    if any((stage / name).exists() for name in ['.venv', '.ai-data', '.git', 'node_modules']):
        raise ValueError('Build stage contains development or private runtime data')
    # Seal every build, including --pack-only, with the bundled Python version.
    # Regenerate checked-hash bytecode with neutral, relative code filenames;
    # never patch compiled binary strings or compile with the host interpreter.
    for path in stage.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(stage.resolve()):
            raise ValueError('External symlink: ' + str(path.relative_to(stage)))
    run(stage / 'runtime/python/bin/python3', '-I', '-B',
        ROOT / 'tools/seal-python.py', stage)
    files = {}
    for path in sorted(stage.rglob('*')):
        if path.name == 'BUNDLE.json':
            continue
        if path.is_file():
            if not path.resolve().is_relative_to(stage.resolve()):
                raise ValueError('External symlink: ' + str(path))
            files[str(path.relative_to(stage))] = {'bytes': path.stat().st_size, 'sha256': digest(path)}
    (stage / 'BUNDLE.json').write_text(json.dumps({'version': inputs['version'], 'inputs': inputs, 'files': files}, indent=2) + '\n')


def pack(stage, output):
    output.mkdir(parents=True, exist_ok=True)
    prefix = output / 'edgeloop-ai-linux-x86_64.tar.gz.part'
    for old in output.glob(prefix.name + '*'):
        old.unlink()
    tar = subprocess.Popen(['tar', '--sort=name', '--mtime=2026-10-29 00:00:00Z', '--owner=0', '--group=0', '-c', '-C', str(stage), '.'], stdout=subprocess.PIPE)
    gzip = subprocess.Popen(['gzip', '-1', '-n'], stdin=tar.stdout, stdout=subprocess.PIPE)
    tar.stdout.close()
    split = subprocess.Popen(['split', '-b', '1900000000', '-d', '-a', '2', '-', str(prefix)], stdin=gzip.stdout)
    gzip.stdout.close()
    codes = [split.wait(), gzip.wait(), tar.wait()]
    if any(codes):
        raise RuntimeError('Bundle compression failed: ' + str(codes))
    shutil.copyfile(ROOT / 'install.sh', output / 'install.sh')
    (output / 'install.sh').chmod(0o755)
    shutil.copyfile(stage / 'BUNDLE.json', output / 'BUNDLE.json')
    # Export only the reviewed source allowlist, without Git or local metadata.
    source = json.loads((ROOT / 'MANIFEST.json').read_text())['included']
    version = json.loads((stage / 'BUNDLE.json').read_text())['version']
    source_archive = output / f'edgeloop-ai-source-{version}.tar.gz'
    with source_archive.open('wb') as stream:
        source_tar = subprocess.Popen(['tar', '--sort=name', '--mtime=2026-10-29 00:00:00Z',
            '--owner=0', '--group=0', '--null', '-c', '-C', str(ROOT), '-T', '-'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        source_gzip = subprocess.Popen(['gzip', '-n'], stdin=source_tar.stdout, stdout=stream)
        source_tar.stdout.close()
        source_tar.stdin.write(('\0'.join(sorted([*source, 'MANIFEST.json']))+'\0').encode())
        source_tar.stdin.close()
        if any([source_gzip.wait(), source_tar.wait()]):
            raise RuntimeError('Source archive compression failed')
    paths = [output / 'install.sh', output / 'BUNDLE.json', source_archive,
             *sorted(output.glob(prefix.name + '*'))]
    (output / 'SHA256SUMS').write_text(''.join(f'{digest(p)}  {p.name}\n' for p in paths))
    print('Release assets:', [(p.name, p.stat().st_size) for p in paths], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--model-store', type=Path, required=True)
    parser.add_argument('--pack-only', action='store_true')
    args = parser.parse_args()
    work = args.work.resolve()
    stage = work / 'stage'
    inputs = json.loads((ROOT / 'release-inputs.json').read_text())
    if not args.pack_only:
        if stage.exists() and any(stage.iterdir()):
            parser.error('Use a fresh build workspace. --pack-only is for a reviewed, already prepared stage.')
        cache = work / 'cache'
        cache.mkdir(parents=True, exist_ok=True)
        stage.mkdir(parents=True, exist_ok=True)
        # Explicit public source allowlist; never archive a working checkout.
        source = json.loads((ROOT / 'MANIFEST.json').read_text())['included']
        for name in [*source, 'MANIFEST.json']:
            out = stage / name
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, out)
            shutil.copymode(ROOT / name, out)
        acquire(inputs['python'], cache / 'python.tar.gz')
        acquire(inputs['ollama'], cache / 'ollama-linux-amd64.tar.zst')
        (stage / 'runtime').mkdir(exist_ok=True)
        run('tar', '-xzf', cache / 'python.tar.gz', '-C', stage / 'runtime')
        (stage / 'runtime/ollama').mkdir(exist_ok=True)
        run('tar', '--zstd', '-xf', cache / 'ollama-linux-amd64.tar.zst', '-C', stage / 'runtime/ollama')
        (stage / 'third-party-sources').mkdir(exist_ok=True)
        for record in inputs.get('third_party_sources', []):
            original = cache / record.get('source_name', record['name'])
            acquire(record, original)
            output = stage / 'third-party-sources' / record['name']
            if record.get('recipe') == 'openmp-source-export-v1':
                run(sys.executable, '-B', ROOT / 'tools/export-openmp-source.py', original,
                    output, '--expected-sha256', record['sha256'])
                if digest(output) != record['output_sha256']:
                    raise ValueError('Corresponding-source export checksum mismatch')
            else:
                shutil.copyfile(original, output)
        python = stage / 'runtime/python/bin/python3'
        run(python, '-m', 'pip', 'download', '--only-binary=:all:', '--dest', stage / 'wheelhouse', '-r', ROOT / 'requirements.lock', *inputs['build_requirements'])
        import_models(args.model_store, stage, inputs)
        create_characters(stage, inputs, work / 'ollama-build.log')
    seal(stage, inputs)
    pack(stage, work / 'dist')


if __name__ == '__main__':
    main()
