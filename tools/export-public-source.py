#!/usr/bin/env python3
"""AGPL-3.0-only. Export the public source tree of one development commit.

Copies the committed tree (never the working tree, Git history or untracked files) into an
empty directory, removes everything tools/public-source-rules.json excludes, then refreshes
MANIFEST.json and runs tools/validate-release.py inside the export. Nothing is published.

    python3 tools/export-public-source.py --out /path/outside/the/repo [--rev HEAD] [--report report.json]
"""
import argparse
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def glob_regex(pattern):
    """'**' crosses directories, '*' stays within one path segment."""
    out = ''
    for token in re.split(r'(\*\*/?|\*)', pattern):
        out += '.*' if token.startswith('**') else '[^/]*' if token == '*' else re.escape(token)
    return re.compile(out + r'\Z')


def committed_files(rev):
    names = subprocess.check_output(['git', '-C', str(ROOT), 'ls-tree', '-r', '--name-only', '-z', rev]).decode().split('\0')
    return [n for n in names if n]


def plan(rev, rules):
    files = committed_files(rev)
    excluded = {}
    patterns = [(glob_regex(p), reason) for p, reason in rules['exclude'].items()]
    keep = set(rules['keep'])
    catalog = json.loads(subprocess.check_output(['git', '-C', str(ROOT), 'show', f"{rev}:{rules['art']['catalog']}"]))
    portraits = {p.lstrip('/') for c in catalog['characters'].values() for p in c['expressions'].values()}
    for name in files:
        if name in keep:
            continue
        reason = next((r for rx, r in patterns if rx.match(name)), None)
        if reason is None and name.startswith(rules['art']['root']) and name not in portraits:
            reason = rules['art']['reason']
        if reason:
            excluded[name] = reason
    missing_keep = sorted(keep - set(files))
    return [n for n in files if n not in excluded], excluded, missing_keep, portraits


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--rev', default='HEAD')
    parser.add_argument('--rules', type=Path, default=ROOT / 'tools/public-source-rules.json')
    parser.add_argument('--report', type=Path, help='Write the full include/exclude report here (outside --out)')
    parser.add_argument('--no-validate', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    if out.is_relative_to(ROOT):
        sys.exit('--out must be outside the development checkout')
    if out.exists() and any(out.iterdir()):
        sys.exit('--out must be empty or absent')
    rev = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', args.rev], text=True).strip()
    rules = json.loads(args.rules.read_text())
    included, excluded, missing_keep, portraits = plan(rev, rules)
    if missing_keep:
        sys.exit('Curated keep files missing from the commit: ' + ', '.join(missing_keep))
    out.mkdir(parents=True, exist_ok=True)
    archive = subprocess.check_output(['git', '-C', str(ROOT), 'archive', '--format=tar', rev, '--', *included])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(out, filter='data')
    for name in included:
        if not (out / name).is_file() or (out / name).is_symlink():
            sys.exit('Export produced a non-regular file: ' + name)
    refresh = subprocess.run([sys.executable, str(out / 'tools/refresh-release-manifest.py')] + [a for n in included for a in ('--include', n)],
                             cwd=out, capture_output=True, text=True)
    if refresh.returncode:
        sys.exit('Manifest refresh failed:\n' + refresh.stderr)
    validation = None
    if not args.no_validate:
        run = subprocess.run([sys.executable, str(out / 'tools/validate-release.py')], cwd=out, capture_output=True, text=True)
        validation = json.loads(run.stdout) if run.stdout.strip().startswith('{') else {'passed': False, 'output': run.stdout + run.stderr}
    reasons = {}
    for reason in excluded.values():
        reasons[reason] = reasons.get(reason, 0) + 1
    report = {'rev': rev, 'out': str(out), 'included': len(included), 'excluded': len(excluded), 'portraits': len(portraits),
              'excluded_by_reason': reasons, 'validation_passed': None if validation is None else validation.get('passed')}
    if args.report:
        args.report.write_text(json.dumps(report | {'included_files': included, 'excluded_files': excluded, 'validation': validation}, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if validation and not validation.get('passed'):
        print(json.dumps(validation.get('errors', validation)[:40], indent=1), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
