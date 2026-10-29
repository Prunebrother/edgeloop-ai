"""AGPL-3.0-only. Verify and configure a complete, offline EdgeLoop bundle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def verify(root=ROOT):
    record = json.loads((root / 'BUNDLE.json').read_text())
    for name, expected in record['files'].items():
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError('Missing or unsafe bundled file: ' + name)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != expected['sha256'] or path.stat().st_size != expected['bytes']:
            raise ValueError('Bundled file failed integrity check: ' + name)
    print(f"Verified {len(record['files'])} bundled files.")


def configure(home, desktop=True, start=True, root=ROOT):
    # New installs start with a real companion. Preserve all existing user settings.
    data = home / '.local/share/edgeloop-ai/data'
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = data / 'selection.json'
    if not config.exists():
        config.write_text(json.dumps({'config': {'model': 'nova-narrative-v1:latest', 'thinking': False}}) + '\n')
        config.chmod(0o600)
    if desktop:
        from install_desktop import install
        install(root=root, home=home)
        if start:
            subprocess.run([str(root / '.venv/bin/python'), str(root / 'tools/edgeloop-ai'), 'start'], check=True)
    print('Installation complete. Open EdgeLoop AI from your application menu.' if desktop else 'Offline environment prepared; desktop integration was skipped.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['verify', 'configure'])
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--no-desktop', action='store_true', help='Prepare only; do not install user services or shortcuts')
    parser.add_argument('--no-start', action='store_true', help='Install shortcuts without starting the application')
    args = parser.parse_args()
    if args.action == 'verify':
        verify()
    else:
        configure(args.home, not args.no_desktop, not args.no_start)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit('EdgeLoop installation failed: ' + str(exc))
