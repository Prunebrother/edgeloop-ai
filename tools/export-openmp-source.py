#!/usr/bin/env python3
"""AGPL-3.0-only. Export pinned OpenMP corresponding source without a Go core fixture.

The original signed/pinned RPM is never modified. Preserve all source text,
patches, build recipes and notices; omit exactly the unrelated binary Go ELF
test core. The changed container is explicitly labeled as a source export.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile

EXCLUDED = 'gcc-8.5.0-20210514/libgo/go/debug/elf/testdata/hello-world-core.gz'
GCC_ARCHIVE = 'gcc-8.5.0-20210514.tar.xz'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def rewrite_gcc(source, destination):
    removed = []
    retained = {}
    with tarfile.open(source, 'r:xz') as original, tarfile.open(destination, 'w:xz', preset=6) as output:
        for member in original:
            name = member.name
            if name.startswith('/') or '..' in PurePosixPath(name).parts:
                raise ValueError('Unsafe upstream source member')
            if name == EXCLUDED:
                if not member.isfile():
                    raise ValueError('Unexpected excluded fixture type')
                removed.append({'name': name, 'sha256': hashlib.file_digest(original.extractfile(member), 'sha256').hexdigest(), 'bytes': member.size})
                continue
            if member.isfile():
                stream = original.extractfile(member)
                h = hashlib.sha256()
                class Reader:
                    def read(self, n):
                        data = stream.read(n)
                        h.update(data)
                        return data
                output.addfile(member, Reader())
                retained[name] = {'sha256': h.hexdigest(), 'bytes': member.size}
            else:
                output.addfile(member)
                retained[name] = {'type': member.type.decode('ascii'), 'link': member.linkname}
    if len(removed) != 1:
        raise ValueError('Expected exactly one excluded upstream core fixture')
    return {'removed': removed, 'retained': retained}


def export(rpm, destination, expected_sha256, audit_report=None):
    if digest(rpm) != expected_sha256:
        raise ValueError('Pinned source RPM checksum mismatch')
    with tempfile.TemporaryDirectory(prefix='openmp-source-') as folder:
        temp = Path(folder)
        names = subprocess.check_output(['bsdtar', '-tf', str(rpm)], text=True).splitlines()
        if any(n.startswith('/') or '..' in PurePosixPath(n).parts for n in names):
            raise ValueError('Unsafe RPM member')
        subprocess.run(['bsdtar', '-xf', str(rpm), '-C', str(temp)], check=True)
        if any(p.is_symlink() for p in temp.rglob('*')):
            raise ValueError('Unexpected source RPM symlink')
        transformed = temp / 'gcc-filtered.tar.xz'
        result = rewrite_gcc(temp / GCC_ARCHIVE, transformed)
        transformed.replace(temp / GCC_ARCHIVE)
        provenance = {'original_source_rpm': rpm.name, 'original_sha256': expected_sha256,
            'recipe': 'openmp-source-export-v1', 'date': '2026-10-30',
            'gcc_archive_sha256': digest(temp / GCC_ARCHIVE), 'excluded': result['removed'],
            'retained_tree_sha256': hashlib.sha256(json.dumps(result['retained'], sort_keys=True).encode()).hexdigest()}
        (temp / 'SOURCE-EXPORT.json').write_text(json.dumps(provenance, indent=2)+'\n')
        (temp / 'PRIVACY-SOURCE-EXPORT.md').write_text('''# Modified corresponding-source container

Exported on 2026-10-30 by the EdgeLoop AI maintainer from the pinned AlmaLinux GCC source RPM identified in SOURCE-EXPORT.json. This is not the original RPM and does not carry its package signature.

Exactly one unrelated binary Go ELF core-dump test fixture was omitted because it contains captured credential environment data. All remaining GCC source files, libgomp source, patches, build recipes, copyright notices and licenses are preserved without content changes. No compiler, OpenMP library or model binary was patched or rebuilt. The optional Go ELF test requiring that fixture is not runnable from this export; OpenMP build sources and scripts are unaffected.

The original input URL/hash is recorded in release-inputs.json, and SOURCE-EXPORT.json records the exclusion and retained-tree digest. These source modifications and the export tooling are provided under the applicable existing licenses; no third-party authorship is reassigned.
''')
        with destination.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed, tarfile.open(fileobj=compressed, mode='w|') as archive:
            for path in sorted(temp.rglob('*')):
                if not path.is_file():
                    continue
                info = tarfile.TarInfo(str(path.relative_to(temp)))
                info.size = path.stat().st_size
                info.mode = 0o644
                info.mtime = 1793318400
                info.uid = info.gid = 0
                info.uname = info.gname = 'root'
                with path.open('rb') as stream:
                    archive.addfile(info, stream)
        if audit_report:
            audit_report.write_text(json.dumps({'provenance': provenance, 'retained': result['retained'], 'output_sha256': digest(destination)}, indent=2)+'\n')
        print('Created documented source export; retained', len(result['retained']), 'GCC members and omitted one unrelated core fixture.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rpm', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--audit-report', type=Path)
    args = parser.parse_args()
    export(args.rpm, args.output, args.expected_sha256, args.audit_report)
