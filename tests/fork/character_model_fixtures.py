# SPDX-License-Identifier: AGPL-3.0-only
"""Resolve browser-fixture model lists without starting an observer or browser."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def installed_model_names(extra_models=''):
    names = json.loads((ROOT / 'tests/fixtures/character-models.json').read_text())
    return names + [name for name in extra_models.split(',') if name and name not in names]


def helix_extra_models():
    manifest = (ROOT / 'src/assets/characters/manifest.json').read_text()
    return ','.join(sorted(set(re.findall(
        r'"([a-z0-9-]+(?:-narrative|-placeholder)[a-z0-9-]*:latest)"', manifest))))
