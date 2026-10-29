# SPDX-License-Identifier: AGPL-3.0-only
"""Small project-local JSON store. Atomic replacement, no OS configuration."""
import json
import os
from pathlib import Path
import tempfile


class SettingsStore:
    def __init__(self, root):
        self.root = Path(root)

    def read(self, name, default=None):
        path = self.root / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text())
        except (ValueError, OSError) as exc:
            raise ValueError(f"Cannot read {path.name}; existing file was left intact") from exc

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.edgeloop-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(value, stream, indent=2, ensure_ascii=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
