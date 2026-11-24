#!/usr/bin/env python3
"""AGPL-3.0-only. Strict story-art registry and on-disk checksum validation.

load_registry(path) checks the JSON schema; validate(registry, root) additionally checks
all files under the campaign directory. Both return the registry or raise ValueError.
"""
import hashlib
import json
from pathlib import Path
import re

ID = re.compile(r'[a-z0-9][a-z0-9_-]*')
KINDS = {'illustration', 'environment', 'key_art', 'chapter_splash', 'thumbnail'}
STATUSES = {'placeholder', 'draft', 'awaiting_review', 'approved', 'integrated'}
TOP_KEYS = {'schema_version', 'campaign', 'slots'}
SLOT_KEYS = {'kind', 'file', 'status', 'sha256', 'source', 'approved_by', 'approved_at', 'explicit', 'description'}


def _schema(registry):
    def require(condition, message):
        if not condition: raise ValueError(message)
    require(isinstance(registry, dict) and set(registry) == TOP_KEYS, 'registry: missing or unknown keys')
    require(type(registry['schema_version']) is int and registry['schema_version'] == 1, 'registry: invalid schema_version')
    require(isinstance(registry['campaign'], str) and ID.fullmatch(registry['campaign']), 'registry: invalid campaign')
    require(isinstance(registry['slots'], dict), 'registry: slots must be an object')
    for slot, item in registry['slots'].items():
        require(isinstance(slot, str) and ID.fullmatch(slot), f'{slot}: invalid slot id')
        require(isinstance(item, dict) and set(item) == SLOT_KEYS, f'{slot}: missing or unknown keys')
        require(isinstance(item['kind'], str) and item['kind'] in KINDS, f'{slot}: invalid kind')
        require(isinstance(item['status'], str) and item['status'] in STATUSES, f'{slot}: invalid status')
        require(isinstance(item['file'], str) and re.fullmatch(r'[a-z0-9][a-z0-9_-]*\.webp', item['file']), f'{slot}: invalid file')
        require(isinstance(item['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', item['sha256']), f'{slot}: invalid sha256')
        require(type(item['explicit']) is bool, f'{slot}: explicit must be a boolean')
        require(isinstance(item['description'], str), f'{slot}: invalid description')
        for key in ('approved_by', 'approved_at'):
            require(item[key] is None or isinstance(item[key], str), f'{slot}: invalid {key}')
        source = item['source']
        require(source is None or (isinstance(source, dict) and set(source) == {'workflow', 'seed', 'take'}), f'{slot}: invalid source keys')
        if source is not None:
            require(isinstance(source['workflow'], str) and isinstance(source['take'], str)
                    and (source['seed'] is None or type(source['seed']) is int), f'{slot}: invalid source')
    return registry


def load_registry(path):
    return _schema(json.loads(Path(path).read_text(encoding='utf-8')))


def validate(registry, root):
    _schema(registry)
    root = Path(root)
    if root.absolute() != root.resolve(): raise ValueError('registry: symlink directory is not allowed')
    for slot, item in registry['slots'].items():
        target = root / item['file']
        if target.is_symlink() or not target.is_file(): raise ValueError(f'{slot}: missing file or symlink')
        if hashlib.sha256(target.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError(f'{slot}: sha256 mismatch')
    return registry
