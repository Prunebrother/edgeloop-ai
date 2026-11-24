# SPDX-License-Identifier: AGPL-3.0-only
"""Committed old-format saves, preservation on refusal, and deterministic v4 round trips."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from companion_ai.campaign import PROGRESS_FILE, migrate
from tests.ai.test_campaign import CID, service

FIXTURES = Path(__file__).parent / 'fixtures/campaign_progress'


def install(tmp_path, name):
    target = tmp_path / PROGRESS_FILE
    shutil.copyfile(FIXTURES / name, target)
    return target


def fingerprint(path):
    return path.read_bytes(), path.stat().st_mtime_ns


@pytest.mark.parametrize('version', (1, 2, 3))
@pytest.mark.parametrize('state', ('fresh', 'mid-ch3', 'ch3-done'))
def test_committed_migration_matrix(tmp_path, version, state):
    path = install(tmp_path, f'v{version}-{state}.json'); before = fingerprint(path)
    original = json.loads(before[0]); old = original['campaigns'][CID]
    svc = service(tmp_path); record = svc.record(CID)
    assert svc.error is None and svc.progress.schema_version == 4
    assert record.choices == record.routes == {}
    assert record.records == old['records'] and record.flags == old.get('flags', {})
    assert {key: value.model_dump() for key, value in record.missions.items()} == old['missions']
    for key, reward in old['rewards'].items(): assert record.rewards[key].model_dump() == reward
    for key, chapter in old.get('chapters', {}).items(): assert record.chapters[key].model_dump() == chapter
    assert fingerprint(path) == before  # Loading alone never upgrades the file on disk.
    if state == 'mid-ch3':
        assert svc.progress.active.model_dump() == original['active']
        assert svc.attempt.mission.id == 'midnight_intruder'
        assert svc.state()['campaigns'][0]['missions'][11]['state'] == 'active'
        assert set(record.chapters) == {'introduction', 'advanced_research'}
    elif state == 'ch3-done':
        helix = next(c for c in svc.state()['campaigns'] if c['id'] == 'rise_of_helix')
        assert helix['available'] and helix['missions'][0]['state'] == 'available'
        assert record.completed_at == old['completed_at']
        assert set(record.chapters) == {'introduction', 'advanced_research', 'shadows_of_helix'}
    else:
        assert svc.progress.active is None and not record.missions and not record.chapters
    first = migrate(original)
    assert migrate(first) == first and original == json.loads(before[0])
    svc._save(svc.progress)
    upgraded = json.loads(path.read_text())
    assert upgraded['schema_version'] == 4 and upgraded['campaigns'][CID]['choices'] == upgraded['campaigns'][CID]['routes'] == {}


@pytest.mark.parametrize('version', (1, 2, 3))
def test_malformed_committed_files_are_not_touched_even_on_refused_actions(tmp_path, version):
    path = install(tmp_path, f'v{version}-malformed.json'); before = fingerprint(path)
    svc = service(tmp_path)
    assert svc.error and svc.state()['error'] == svc.error and svc.state()['campaigns']
    assert svc.allowed_settings() is None and svc.observe({'status': 'RUNNING'}, [], 'nova') == []
    with pytest.raises(ValueError): svc.start(CID, 'orientation')
    with pytest.raises(ValueError): svc.answer('log', 'internal', {}, 'nova')
    assert fingerprint(path) == before


def test_v3_partial_puzzles_survive_migration_and_resume(tmp_path):
    install(tmp_path, 'v3-partial-puzzles.json'); svc = service(tmp_path)
    assert svc.error is None and svc.progress.active.mission == 'ghost_in_the_machine'
    assert svc.attempt.solved == {'log', 'money'}
    puzzles = [o for o in svc.state()['attempt']['objectives'] if 'puzzle' in o]
    assert [p['done'] for p in puzzles] == [True, True, False]
    assert puzzles[-1]['puzzle']['open']
    svc._save(svc.progress)
    assert service(tmp_path).attempt.solved == {'log', 'money'}


def test_canonical_v4_noop_save_is_byte_equal(tmp_path):
    path = install(tmp_path, 'v4-round-trip.json'); before = path.read_bytes()
    svc = service(tmp_path); assert svc.error is None
    svc._save(svc.progress)
    assert path.read_bytes() == before
    assert migrate(json.loads(before)) == json.loads(before)


def test_fixture_generator_reproduces_every_committed_json(tmp_path):
    subprocess.run([sys.executable, str(FIXTURES / 'make_fixtures.py'), '--output-dir', str(tmp_path)], check=True)
    expected = {p.name: p.read_bytes() for p in FIXTURES.glob('*.json')}
    assert {p.name: p.read_bytes() for p in tmp_path.glob('*.json')} == expected
