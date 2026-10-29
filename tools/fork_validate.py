"""AGPL-3.0-only: verify the original fork baseline and optionally its tests.
No download, browser profile, AI backend or hardware connection is used.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / 'docs/fork/upstream-pin.json'


def verify():
    pin = json.loads(PIN.read_text())
    failures = []
    changes_path=ROOT / "docs/fork/f2-changes.json"
    changes=json.loads(changes_path.read_text()) if changes_path.exists() else {}
    if any(name not in pin["files"] or record["base_sha256"]!=pin["files"][name] for name,record in changes.items()):
        raise ValueError("Invalid reviewed change manifest")
    exclusions=json.loads((ROOT/'docs/fork/release-exclusions.json').read_text())
    if any(name not in pin['files'] or (ROOT/name).exists() for name in exclusions):
        raise ValueError('Invalid release exclusion manifest')
    for name, digest in pin['files'].items():
        if name in exclusions: continue
        path = ROOT / name
        if (path.is_symlink() or not path.resolve().is_relative_to(ROOT)
                or not path.is_file() or sha256(path.read_bytes()).hexdigest() != changes.get(name, {}).get('sha256', digest)):
            failures.append(name)
    if failures:
        raise ValueError('Original files differ from the pin: ' + ', '.join(failures))
    return {key: pin[key] for key in ('version', 'commit', 'repository', 'license')} | {'unchanged_files': len(pin['files'])-len(changes), 'reviewed_changes':list(changes)}


def tests():
    results = []
    for path in sorted((ROOT / 'src/js').rglob('*.test.js')):
        result = subprocess.run(['node', '--test', '--test-isolation=none', '--test-reporter=tap', str(path)],
                                cwd=ROOT, capture_output=True, text=True, timeout=210)
        counts = {key: int(value) for key, value in re.findall(
            r'^# (tests|pass|fail|cancelled|skipped) (\d+)$', result.stdout, re.M)}
        record = {'file': str(path.relative_to(ROOT)), 'exit_code': result.returncode, **counts}
        results.append(record)
        print(json.dumps(record), flush=True)
        if result.returncode:
            print(result.stdout[-4000:]); print(result.stderr[-2000:])
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests', action='store_true')
    parser.add_argument('--report', default='/tmp/edgeloop-fork-validation.json')
    args = parser.parse_args()
    reference = verify()
    print(json.dumps(reference), flush=True)
    rows = tests() if args.tests else []
    report = {'reference': reference, 'test_files': rows,
              'tests': sum(row.get('tests', 0) for row in rows),
              'failed_files': sum(row['exit_code'] != 0 for row in rows)}
    Path(args.report).write_text(json.dumps(report, indent=2) + '\n')
    if report['failed_files']:
        raise SystemExit(1)
