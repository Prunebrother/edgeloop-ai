# SPDX-License-Identifier: AGPL-3.0-only
"""Alternate completion paths, deterministic ties, durable replay records and private model cues."""
from copy import deepcopy
import json
import pytest
from companion_ai.campaign import Book, Campaign, CampaignService, Narrative, card_brief
from companion_ai.storage import SettingsStore
from tests.ai.test_campaign_when import CID, MODEL, definition as when_definition, narrative as when_narrative, block
from tests.ai.test_campaign_chapter2 import tick


def definition():
    data = when_definition(); m = data['missions'][0]
    m['objectives'][-1:] = [
        {'id': 'evidence', 'type': 'orgasm_count', 'label': 'Evidence target', 'count': 1},
        {'id': 'shared', 'type': 'edge_count', 'label': 'Common check', 'count': 1},
        {'id': 'strap', 'type': 'hr_monitor_connected', 'label': 'Strap'},
        {'id': 'toy', 'type': 'toy_connected', 'label': 'Toy'},
        {'id': 'extra', 'type': 'edge_count', 'label': 'Optional check', 'count': 10, 'optional': True}]
    m['completion'] = {'any_of': [
        {'id': 'escape', 'label': 'Escape with the code', 'objectives': ['edges', 'cover'], 'sets': {'route': 'escape'}},
        {'id': 'release', 'label': 'Release the evidence', 'objectives': ['evidence'], 'sets': {'route': 'release'}}]}
    return data


def service(tmp_path, data=None):
    c = Campaign.model_validate(data or definition()); text = when_narrative()
    text['missions']['intake'].update(completion=block('Escape ending', when={'flag': 'route', 'eq': 'escape'}),
        epilogue=[block('Release ending', when={'flag': 'route', 'eq': 'release'})])
    text['missions']['intake']['milestones'] = {'evidence:done': block('Route milestone', when={'flag': 'route', 'eq': 'release'})}
    return CampaignService(SettingsStore(tmp_path), book=Book([c], {CID: Narrative.model_validate(text)}), identity=lambda _: 'nova')


def begin(svc, sid='s'):
    svc.start(CID, 'intake'); svc.observe(tick(sid, 0), [], MODEL)


def take(svc, route='escape', sid='s'):
    begin(svc, sid)
    if route == 'escape': svc.answer('cover', 'analyst', tick(sid, 0), MODEL)
    return svc.observe(tick(sid, 1, edges=2 if route == 'escape' else 1, orgasms=route == 'release'), [], MODEL)


@pytest.mark.parametrize('change', [
    lambda m: m['completion'].update(any_of=m['completion']['any_of'][:1]),
    lambda m: m['completion'].update(any_of=m['completion']['any_of'] * 3),
    lambda m: m['completion']['any_of'][1].update(id='escape'),
    lambda m: m['completion']['any_of'][0].update(id='not.snake'),
    lambda m: m['completion']['any_of'][0].update(label=''),
    lambda m: m['completion']['any_of'][0].update(label=' '),
    lambda m: m['completion']['any_of'][0].update(label='x' * 81),
    lambda m: m['completion']['any_of'][0].update(objectives=[]),
    lambda m: m['completion']['any_of'][0].update(objectives=['edges'] * 9),
    lambda m: m['completion']['any_of'][0].update(objectives=['missing']),
    lambda m: m['completion']['any_of'][0].update(objectives=['extra']),
    lambda m: m['completion']['any_of'][1].update(objectives=['cover', 'edges']),
    lambda m: m['completion']['any_of'][0].update(objectives=['edges', 'edges']),
    lambda m: m['completion']['any_of'][0].update(sets={'inherited.flag': 'escape'}),
    lambda m: m['completion']['any_of'][0].update(sets={'route': 'not valid'}),
])
def test_invalid_routes(change):
    data = definition(); change(data['missions'][0])
    with pytest.raises(ValueError): Campaign.model_validate(data)


def test_route_flags_declared_and_validated_at_load(tmp_path):
    data = definition(); data['missions'][0]['when'] = {'flag': 'route', 'eq': 'escape'}
    c = Campaign.model_validate(data); assert c.own_flags()['route'] == {'escape', 'release'}
    folder = tmp_path / CID; folder.mkdir(); (folder / 'campaign.json').write_text(json.dumps(data))
    assert not Book.load(tmp_path).errors
    data['missions'][0]['when']['eq'] = 'typo'; (folder / 'campaign.json').write_text(json.dumps(data))
    assert 'nothing sets' in Book.load(tmp_path).errors[0]['detail']


@pytest.mark.parametrize('route', ['escape', 'release'])
def test_either_route_completes_with_common_goals_and_only_taken_flags(tmp_path, route):
    svc = service(tmp_path); result = next(m for m in take(svc, route) if m['type'] == 'mission_result')
    assert result['route'] == {'id': route, 'label': 'Escape with the code' if route == 'escape' else 'Release the evidence'}
    assert svc.record(CID).routes == {'intake': route} and svc.record(CID).flags['route'] == route
    assert svc.record(CID).flags.get('cover') == ('analyst' if route == 'escape' else None)
    assert not next(o for o in result['objectives'] if o['id'] == 'extra')['done']
    assert bool(result['completion']) == (route == 'escape')
    assert bool(result['epilogue']) == (route == 'release')
    cue = next(c for c in svc.take_cues() if c['kind'] == 'mission_complete')
    assert result['route']['label'] in card_brief(cue, 'RUNNING')
    assert result['route']['label'] in svc.model_context(MODEL, tick('s', 2))['text']


@pytest.mark.parametrize('route', ['escape', 'release'])
def test_common_required_goal_blocks_every_route(tmp_path, route):
    data = definition(); data['missions'][0]['objectives'][4]['count'] = 3
    svc = service(tmp_path, data); out = take(svc, route)
    assert not any(m['type'] == 'mission_result' for m in out)
    assert not svc.attempt.ready() and all(not r['met'] for r in svc.state()['attempt']['routes'])
    assert any(m['type'] == 'mission_result' for m in svc.observe(tick('s', 2, edges=3, orgasms=route == 'release'), [], MODEL))


def test_tie_uses_first_list_route_and_replay_records_latest_without_rewinding_flags(tmp_path):
    svc = service(tmp_path); begin(svc)
    svc.answer('cover', 'analyst', tick('s', 0), MODEL)
    result = next(m for m in svc.observe(tick('s', 1, edges=2, orgasms=1), [], MODEL) if m['type'] == 'mission_result')
    assert result['route']['id'] == 'escape'
    saved_flags = dict(svc.record(CID).flags)
    replay = take(svc, 'release', 'replay'); result = next(m for m in replay if m['type'] == 'mission_result')
    assert result['route']['id'] == 'release' and svc.record(CID).routes['intake'] == 'release'
    assert svc.record(CID).flags == saved_flags and result['flags'] == {}
    assert result['completion'] is None and result['epilogue'][0]['lines'] == ['Release ending']
    assert any(m.get('key') == 'evidence:done' for m in replay)
    assert service(tmp_path).record(CID).routes['intake'] == 'release'


def test_route_overlay_not_saved_and_model_does_not_name_alternatives(tmp_path):
    svc = service(tmp_path); begin(svc)
    text = svc.model_context(MODEL, tick('s', 0))['text']
    assert 'more than one way to finish' in text
    assert all(route['label'] not in text for route in definition()['missions'][0]['completion']['any_of'])
    assert 'Two edges' not in text and 'Evidence target' not in text
    attempt = svc.attempt; attempt.done.update(start=True, strap=True, toy=True, shared=True, evidence=True)
    assert svc.story_flags(svc.book.campaign(CID), attempt)['route'] == 'release'
    assert svc.record(CID).flags == {}
    assert svc.state()['attempt']['routes'][1]['met']


def test_failed_route_save_announces_nothing_then_retries_exactly_once(tmp_path, monkeypatch):
    svc = service(tmp_path); begin(svc); real = svc.store.write
    monkeypatch.setattr(svc.store, 'write', lambda *a: (_ for _ in ()).throw(OSError('full')))
    out = svc.observe(tick('s', 1, edges=1, orgasms=1), [], MODEL)
    assert not any(m['type'] in {'mission_result', 'mission_milestone'} for m in out)
    assert not svc.record(CID).routes and svc.attempt.pending
    monkeypatch.setattr(svc.store, 'write', real)
    out = svc.observe(tick('s', 2, status='IDLE'), [], MODEL)
    assert sum(m['type'] == 'mission_result' for m in out) == 1
    assert sum(m.get('key') == 'evidence:done' for m in out) == 1
    assert svc.record(CID).routes == {'intake': 'release'}


def test_alternative_puzzles_do_not_block_each_other(tmp_path):
    data = definition(); m = data['missions'][0]
    from tests.ai.test_campaign_code_puzzle import definition as code_definition
    puzzle = next(o for o in code_definition()['missions'][0]['objectives'] if o['type'] == 'puzzle_solved')
    puzzle['puzzle']['clues'] = ['Fixture clue']
    a, b = deepcopy(puzzle), deepcopy(puzzle); a['id'] = 'edges'; b['id'] = 'evidence'
    m['objectives'][1] = a; m['objectives'][3] = b
    svc = service(tmp_path, data); begin(svc)
    assert all(o['puzzle']['open'] for o in svc.state()['attempt']['objectives'] if 'puzzle' in o)
