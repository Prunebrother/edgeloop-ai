#!/usr/bin/env python3
"""AGPL-3.0-only. Refresh public source hashes; review the result before publishing."""
import hashlib
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include', action='append', default=[], help='Explicit additional public source file')
    args = parser.parse_args()
    pin = json.loads((ROOT / 'docs/fork/upstream-pin.json').read_text())
    path = ROOT / 'docs/fork/f2-changes.json'
    changes = json.loads(path.read_text())
    for name, base in pin['files'].items():
        file = ROOT / name
        if not file.is_file():
            continue
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        if digest != base:
            record = changes.setdefault(name, {'base_sha256': base, 'reason': 'Complete local-app release packaging; original engine and hardware controls preserved.'})
            record['sha256'] = digest
    path.write_text(json.dumps(changes, indent=2) + '\n')
    manifest_path = ROOT / 'MANIFEST.json'
    manifest = json.loads(manifest_path.read_text())
    if (ROOT / '.git').is_dir():
        names = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard', '-z']).decode().split('\0')
    else:
        # Source exports have no repository metadata. Preserve the reviewed
        # allowlist rather than sweeping private reports into the release.
        names = list(manifest['included'])
    names.extend(args.include)
    manifest['included'] = {}
    for name in sorted(set(names) - {'', 'MANIFEST.json'}):
        file = ROOT / name
        if not file.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError('Public source path escapes the source export')
        if file.is_symlink():
            raise ValueError('Public source symlink not allowed: ' + name)
        if file.is_file():
            manifest['included'][name] = {'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'bytes': file.stat().st_size, 'executable': bool(file.stat().st_mode & 0o111)}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f"Refreshed {len(manifest['included'])} public file hashes. Review the diff and run validate-release.py.")


if __name__ == '__main__':
    main()
