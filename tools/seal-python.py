#!/usr/bin/env python3
"""AGPL-3.0-only. Regenerate release bytecode without builder filesystem paths.

Run with the release's bundled interpreter, using -I -B. Checked-hash caches
survive archive timestamp normalization. Code filenames are relative to the
neutral edgeloop-ai/ prefix. This does not change Python source or executables.
"""
import compileall
import importlib.util
import marshal
from pathlib import Path, PurePosixPath
import py_compile
import shutil
import sys
import types


def code_filenames(code):
    yield code.co_filename
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            yield from code_filenames(value)


def prepare(root):
    root = root.resolve()
    library = root / 'runtime/python/lib' / f'python{sys.version_info.major}.{sys.version_info.minor}'
    if not library.is_dir():
        raise ValueError('Bundled interpreter version does not match the runtime library')
    for path in root.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(root):
            raise ValueError('External symlink in release stage')
    # Discard all old caches, including caches generated during pack-only review.
    for directory in list(root.rglob('__pycache__')):
        if directory.exists():
            shutil.rmtree(directory)
    for path in root.rglob('*'):
        if path.suffix in {'.pyc', '.pyo'}:
            path.unlink()
    if not compileall.compile_dir(str(library), force=True, quiet=1,
            stripdir=str(root), prependdir='edgeloop-ai', optimize=0,
            invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH):
        raise ValueError('Runtime bytecode compilation failed')
    count = 0
    for path in root.rglob('*.pyc'):
        data = path.read_bytes()
        if data[:4] != importlib.util.MAGIC_NUMBER or int.from_bytes(data[4:8], 'little') != 3:
            raise ValueError('Unexpected Python bytecode version or invalidation mode')
        for name in code_filenames(marshal.loads(data[16:])):
            parts = PurePosixPath(name).parts
            if not name.startswith('edgeloop-ai/') or PurePosixPath(name).is_absolute() or '..' in parts or '\\' in name:
                raise ValueError('Noncanonical bytecode code filename')
        count += 1
    print(f'Sealed {count} checked-hash Python caches with canonical code filenames.')
    return count


if __name__ == '__main__':
    prepare(Path(sys.argv[1]))
