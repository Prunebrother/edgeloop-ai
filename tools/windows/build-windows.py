#!/usr/bin/env python3
"""AGPL-3.0-only. Build the complete Windows x86_64 assets and setup program on a Linux build host.

Same reviewed source allowlist and model store as the Linux bundle; Windows Python, Ollama and
wheels from the pinned inputs in release-inputs.json. The model store is platform-neutral and is
created with the Linux Ollama from the same inputs. The setup program is compiled with Inno Setup
(under Wine on Linux, or natively with --iscc on Windows) and carries the part checksums.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('build_release', ROOT / 'tools/build-release.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
PREFIX = 'edgeloop-ai-windows-x86_64.tar.gz.part'
SPLIT = 1_900_000_000


def strip_bytecode(root):
    # Bytecode is not shipped: Python writes it on first use, so it never conflicts with verification.
    for cache in sorted(root.rglob('__pycache__'), reverse=True):
        shutil.rmtree(cache)
    for path in root.rglob('*.pyc'):
        path.unlink()


def extract_python(archive, target):
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as source:
        source.extractall(target, filter='data')
    strip_bytecode(target)
    if not (target / 'python/python.exe').is_file():
        raise ValueError('Unexpected Windows Python layout')


def stage_bundle(work, model_store, inputs, lite=False):
    stage = work / 'stage'
    if stage.exists() and any(stage.iterdir()):
        raise SystemExit('Use a fresh build workspace.')
    cache = work / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    stage.mkdir(parents=True, exist_ok=True)
    source = json.loads((ROOT / 'MANIFEST.json').read_text())['included']
    for name in [*source, 'MANIFEST.json']:
        # Windows names are case-insensitive: MANIFEST.json would overwrite the web app's manifest.json.
        out = stage / ('SOURCE-MANIFEST.json' if name == 'MANIFEST.json' else name)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, out)
    win = inputs['windows']
    build.acquire(win['python'], cache / 'python-windows.tar.gz')
    build.acquire(win['ollama'], cache / 'ollama-windows-amd64.zip')
    # Build-host tools only, never shipped: Linux Python for pip, Linux Ollama to create the model store.
    build.acquire(inputs['python'], cache / 'python.tar.gz')
    host = work / 'host'
    if host.exists():
        shutil.rmtree(host)
    (host / 'ollama').mkdir(parents=True)
    build.run('tar', '-xzf', cache / 'python.tar.gz', '-C', host)
    if not lite:
        build.acquire(inputs['ollama'], cache / 'ollama-linux-amd64.tar.zst')
        build.run('tar', '--zstd', '-xf', cache / 'ollama-linux-amd64.tar.zst', '-C', host / 'ollama')
    extract_python(cache / 'python-windows.tar.gz', stage / 'runtime')
    with zipfile.ZipFile(cache / 'ollama-windows-amd64.zip') as archive:
        for member in archive.infolist():
            if member.filename.startswith(('/', '\\')) or '..' in Path(member.filename).parts:
                raise ValueError('Unsafe Ollama archive entry')
        archive.extractall(stage / 'runtime/ollama')
    if not (stage / 'runtime/ollama/ollama.exe').is_file():
        raise ValueError('Unexpected Windows Ollama layout')
    build.run(host / 'python/bin/python3', '-m', 'pip', 'download', '--only-binary=:all:', '--platform', 'win_amd64',
              '--python-version', '3.12', '--implementation', 'cp', '--abi', 'cp312', '--dest', stage / 'wheelhouse',
              '-r', ROOT / 'requirements.lock', *inputs['build_requirements'], *win.get('extra_requirements', []))
    if not lite:
        build.import_models(model_store, stage, inputs)
        build.create_characters(stage, inputs, work / 'ollama-build.log', binary=host / 'ollama/bin/ollama')
    else:
        (stage / 'models').mkdir()  # Test bundle: everything except the model store.
    resolve_symlinks(stage)
    strip_bytecode(stage)
    seal(stage, inputs, lite)
    return stage


def resolve_symlinks(stage):
    # Ollama links name manifests to blobs. Windows cannot create symlinks without extra rights,
    # so the bundle carries a copy of each (small) target instead; only targets inside the stage.
    for path in sorted(stage.rglob('*')):
        if path.is_symlink():
            target = path.resolve()
            if not target.is_relative_to(stage.resolve()) or not target.is_file():
                raise ValueError('Symlink leaves the bundle: ' + str(path.relative_to(stage)))
            path.unlink()
            shutil.copyfile(target, path)


RESERVED = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(10)), *(f'lpt{i}' for i in range(10))}
# Installed below C:\\Users\\<name>\\AppData\\Local\\Programs\\EdgeLoop AI\\<version>\\, inside the 260-character limit.
MAX_RELATIVE = 160


def windows_problems(names):
    problems, seen = [], {}
    for name in names:
        folded = name.casefold()
        if folded in seen:
            problems.append(f'{name} and {seen[folded]} differ only in case')
        seen[folded] = name
        for part in name.split('/'):
            if part.split('.')[0].casefold() in RESERVED or any(c in part for c in '<>:"\\|?*') or part.endswith(('.', ' ')):
                problems.append(f'{name} is not a valid Windows name')
        if len(name) > MAX_RELATIVE:
            problems.append(f'{name} is too long for Windows paths')
    return problems


def seal(stage, inputs, lite=False):
    if any((stage / name).exists() for name in ['.venv', '.ai-data', '.git', 'node_modules']):
        raise ValueError('Build stage contains development or private runtime data')
    problems = windows_problems([p.relative_to(stage).as_posix() for p in stage.rglob('*')])
    if problems:
        raise ValueError('Not installable on Windows: ' + '; '.join(problems[:10]))
    files = {}
    for path in sorted(stage.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlinks are not portable to Windows: ' + str(path.relative_to(stage)))
        if path.is_file() and path.name != 'BUNDLE.json':
            files[path.relative_to(stage).as_posix()] = {'bytes': path.stat().st_size, 'sha256': build.digest(path)}
    record = {'version': inputs['version'], 'platform': inputs['windows']['platform'], 'lite': lite, 'inputs': inputs, 'files': files}
    (stage / 'BUNDLE.json').write_text(json.dumps(record, indent=2) + '\n')


def pack(stage, output):
    output.mkdir(parents=True, exist_ok=True)
    for old in output.glob(PREFIX + '*'):
        old.unlink()
    tar = subprocess.Popen(['tar', '--sort=name', '--mtime=2026-10-29 00:00:00Z', '--owner=0', '--group=0', '-c', '-C', str(stage), '.'], stdout=subprocess.PIPE)
    gzip = subprocess.Popen(['gzip', '-1', '-n'], stdin=tar.stdout, stdout=subprocess.PIPE)
    tar.stdout.close()
    split = subprocess.Popen(['split', '-b', str(SPLIT), '-d', '-a', '2', '-', str(output / PREFIX)], stdin=gzip.stdout)
    gzip.stdout.close()
    if any([split.wait(), gzip.wait(), tar.wait()]):
        raise RuntimeError('Bundle compression failed')
    shutil.copyfile(stage / 'BUNDLE.json', output / 'BUNDLE-windows.json')
    return sorted(output.glob(PREFIX + '*'))


def png_to_ico(png, ico):
    # A Vista-style icon: one PNG image inside an ICO container.
    data = png.read_bytes()
    width, height = struct.unpack('>II', data[16:24])
    ico.write_bytes(struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHII', width % 256, height % 256, 0, 0, 1, 32, len(data), 22) + data)


def setup_program(work, stage, parts, output, inputs, iscc):
    version = inputs['version']
    setup = work / 'setup'
    if setup.exists():
        shutil.rmtree(setup)
    setup.mkdir(parents=True)
    extract_python(work / 'cache/python-windows.tar.gz', setup / 'runtime')
    (setup / 'runtime/python').rename(setup / 'setup-python')
    shutil.copyfile(HERE / 'install_windows.py', setup / 'install_windows.py')
    shutil.copyfile(HERE / 'setup-notes.txt', setup / 'setup-notes.txt')
    shutil.copyfile(ROOT / 'LICENSE', setup / 'LICENSE.txt')
    png_to_ico(ROOT / 'icon-192.png', setup / 'edgeloop-ai.ico')
    manifest = {'version': version, 'base_url': f"{inputs['windows']['download_base']}/{version}",
                'parts': [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': build.digest(p)} for p in parts]}
    (setup / 'parts.json').write_text(json.dumps(manifest, indent=2) + '\n')
    size = sum(p['bytes'] for p in manifest['parts'])
    script = (HERE / 'edgeloop-ai.iss').read_text()
    script = script.replace('@VERSION@', version).replace('@NUMERIC_VERSION@', numeric(version)).replace('@EXTRA_SPACE@', str(size * 2 + 2_000_000_000))
    (setup / 'edgeloop-ai.iss').write_text(script, encoding='utf-8-sig')
    if iscc == 'none':
        print('Setup folder prepared (not compiled): ' + str(setup), flush=True)
        return None
    if iscc:
        command = [iscc, '/Q', f'/O{output}', str(setup / 'edgeloop-ai.iss')]
    else:
        prefix = os.environ.get('WINEPREFIX') or str(work / 'wine')
        command = ['wine', str(Path(prefix) / 'drive_c/InnoSetup/ISCC.exe'), '/Q', f'/O{wine_path(output)}', wine_path(setup / 'edgeloop-ai.iss')]
    env = dict(os.environ, WINEDEBUG='-all')
    env.setdefault('WINEPREFIX', str(work / 'wine'))
    subprocess.run(command, check=True, env=env)
    exe = output / f'EdgeLoop-AI-Setup-{version}.exe'
    if not exe.is_file():
        raise RuntimeError('Inno Setup produced no setup program')
    return exe


def numeric(version):
    # Windows file versions are four numbers; a release candidate keeps its number in the fourth.
    core, _, suffix = version.lstrip('v').partition('-')
    numbers = [int(x) for x in core.split('.')] + [0] * 3
    return '.'.join(map(str, numbers[:3] + [int(''.join(c for c in suffix if c.isdigit()) or 0)]))


def wine_path(path):
    return 'Z:' + str(Path(path).resolve()).replace('/', '\\')


def checksums(output):
    paths = sorted(p for p in output.iterdir() if p.is_file() and p.name != 'SHA256SUMS')
    (output / 'SHA256SUMS').write_text(''.join(f'{build.digest(p)}  {p.name}\n' for p in paths))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--model-store', type=Path, default=Path.home() / '.ollama/models')
    parser.add_argument('--dist', type=Path, help='Release asset folder (default WORK/dist); SHA256SUMS covers every file in it')
    parser.add_argument('--setup-only', action='store_true', help='Recompile the setup program from existing parts')
    parser.add_argument('--iscc', help="Path to a native ISCC.exe instead of Wine, or 'none' to only prepare the setup folder")
    parser.add_argument('--lite', action='store_true', help='Test build without the model store (not for release)')
    args = parser.parse_args()
    work = args.work.resolve()
    output = (args.dist or work / 'dist').resolve()
    inputs = json.loads((ROOT / 'release-inputs.json').read_text())
    if args.setup_only:
        stage, parts = work / 'stage', sorted(output.glob(PREFIX + '*'))
    else:
        stage = stage_bundle(work, args.model_store, inputs, args.lite)
        parts = pack(stage, output)
    exe = setup_program(work, stage, parts, output, inputs, args.iscc)
    checksums(output)
    print('Windows assets:', [(p.name, p.stat().st_size) for p in [*parts, exe] if p], flush=True)


if __name__ == '__main__':
    main()
