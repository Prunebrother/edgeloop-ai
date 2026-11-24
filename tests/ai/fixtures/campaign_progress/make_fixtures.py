# SPDX-License-Identifier: AGPL-3.0-only
"""Regenerate the committed save matrix; writes fixtures only, never live campaign progress.

Run from any directory: python /path/to/this/make_fixtures.py [--output-dir DIR].
Old formats omit fields they did not yet have; completion rewards use current mission ids.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CID = 'asterion_initiative'
STAMP = '2026-11-16T00:00:00+00:00'
LAST = '2026-11-17T00:00:00+00:00'


def save(version, through=0, active=None):
    campaign = json.loads((ROOT / 'config/campaigns' / CID / 'campaign.json').read_text())
    record = {'missions': {}, 'rewards': {}, 'completed_at': STAMP if through == 14 else None,
              'records': {'calibrated_max_bpm': 154, 'calibration_pass': 'dual'} if through else {}}
    if version >= 2: record['chapters'] = {}
    if version >= 3: record.update(flags={}, solved={})
    for mission in sorted(campaign['missions'], key=lambda m: m['order']):
        if mission['order'] > through: break
        record['missions'][mission['id']] = {'completions': 2 if mission['order'] == 1 else 1,
            'first_completed_at': STAMP, 'last_completed_at': LAST if mission['order'] == 1 else STAMP}
        for reward in mission['rewards']:
            record['rewards'][reward['type'] + ':' + reward['id']] = {'earned_at': STAMP, 'mission': mission['id']}
            if version >= 2 and reward['type'] == 'chapter_complete': record['chapters'][reward['id']] = {'completed_at': STAMP}
        if version >= 3: record['flags'].update(mission.get('flags', {}))
    return {'schema_version': version, 'campaigns': {CID: record},
            'active': {'campaign': CID, 'mission': active, 'started_at': LAST} if active else None}


def encode(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def fixtures():
    files = {}
    for version in (1, 2, 3):
        files[f'v{version}-fresh.json'] = encode(save(version))
        files[f'v{version}-mid-ch3.json'] = encode(save(version, 11, 'midnight_intruder'))
        files[f'v{version}-ch3-done.json'] = encode(save(version, 14))
    malformed = save(1, 11); malformed['campaigns'][CID]['missions']['orientation']['completions'] = 'twice'
    files['v1-malformed.json'] = encode(malformed)
    malformed = save(2, 11); malformed['campaigns'][CID]['unexpected_field'] = True
    files['v2-malformed.json'] = encode(malformed)
    files['v3-malformed.json'] = encode(save(3, 11, 'midnight_intruder'))[:-12]
    # Mission 12 has no puzzles. This extra realistic late-Ch3 save exercises v3's partial puzzle progress.
    puzzles = save(3, 13, 'ghost_in_the_machine')
    puzzles['campaigns'][CID]['solved'] = {'ghost_in_the_machine': ['log', 'money']}
    files['v3-partial-puzzles.json'] = encode(puzzles)
    current = deepcopy(puzzles); current['schema_version'] = 4
    current['campaigns'][CID].update(choices={}, routes={}, intros_seen={})
    # Match Progress/CampaignRecord field order and SettingsStore's formatting for a byte-stable no-op save.
    record = current['campaigns'][CID]
    order = ('missions', 'rewards', 'chapters', 'flags', 'completed_at', 'records', 'solved', 'choices', 'routes', 'intros_seen')
    current['campaigns'][CID] = {key: record[key] for key in order}
    files['v4-round-trip.json'] = encode(current)
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent)
    destination = parser.parse_args().output_dir; destination.mkdir(parents=True, exist_ok=True)
    for name, content in fixtures().items(): (destination / name).write_text(content, encoding='utf-8')


if __name__ == '__main__': main()
