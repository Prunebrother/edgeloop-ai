# SPDX-License-Identifier: AGPL-3.0-only
"""Rise of Helix foundations (docs/fork/campaign/rise_of_helix, Milestone A): several campaigns side by side,
mission text on demand, Asterion's ending, inherited story flags and `when` conditions."""
import json
import shutil
import pytest
from companion_ai.campaign import Book, CampaignService, CAMPAIGN_DIR
from companion_ai.storage import SettingsStore
from tests.ai.test_campaign import CID, MODEL, identity, report, service, run, results

LIMIT = 65536  # ai_observer.server.publish refuses any larger message


def clone(tmp_path, cid, order):
    """A copy of The Asterion Initiative under another id: a second full-size campaign."""
    root = tmp_path / 'campaigns'
    if not root.exists(): shutil.copytree(CAMPAIGN_DIR / CID, root / CID)
    (root / cid).mkdir()
    definition = json.loads((CAMPAIGN_DIR / CID / 'campaign.json').read_text()) | {'id': cid, 'order': order}
    narrative = json.loads((CAMPAIGN_DIR / CID / 'narrative.json').read_text()) | {'campaign': cid}
    (root / cid / 'campaign.json').write_text(json.dumps(definition))
    (root / cid / 'narrative.json').write_text(json.dumps(narrative))
    return Book.load(root)


# ---- HELIX-002: mission text on demand

def test_the_campaign_view_carries_no_briefings_hints_or_puzzle_texts(tmp_path):
    state = service(tmp_path).state()
    missions = state['campaigns'][0]['missions']
    assert all('briefing' not in m and 'hints' not in m for m in missions)
    assert all('puzzle' not in o for m in missions for o in m['objectives'])
    assert len(json.dumps(state).encode()) < 36000  # early warning; hard limits are 48 KB (tests) and 64 KB (observer)


def test_two_full_size_campaigns_fit_the_message_limit_with_room_to_spare(tmp_path):
    book = clone(tmp_path, 'second_story', 2)
    assert [c.id for c in book.campaigns] == [CID, 'second_story'] and not book.errors
    assert len(json.dumps(service(tmp_path, book).state()).encode()) < LIMIT - 8192


def test_mission_text_returns_the_briefing_and_hints_of_an_open_mission(tmp_path):
    svc = service(tmp_path)
    text = svc.mission_text(CID, 'orientation')
    assert text['type'] == 'mission_text' and text['campaign'] == CID and text['mission'] == 'orientation'
    assert text['briefing']['speaker'] == 'nova' and text['briefing']['lines']
    assert text['hints'] == svc.book.campaign(CID).mission('orientation').hints
    assert text['narrative_draft'] is False


def test_mission_text_is_refused_for_locked_and_unknown_missions(tmp_path):
    svc = service(tmp_path)
    with pytest.raises(ValueError, match='locked'): svc.mission_text(CID, 'first_assessment')
    with pytest.raises(ValueError, match='Unknown'): svc.mission_text(CID, 'nope')
    with pytest.raises(ValueError, match='Unknown'): svc.mission_text('nope', 'orientation')


def test_puzzle_texts_still_reach_the_banner_through_the_attempt_only(tmp_path):
    from tests.ai.test_campaign_chapter3 import seed, view
    svc = seed(tmp_path, 'ghost_in_the_machine')
    assert view(svc, 'log')['puzzle']['question']
    dumped = json.dumps(svc.state())
    puzzle = svc.book.campaign(CID).mission('ghost_in_the_machine').objectives
    answers = [o.puzzle.answer for o in puzzle if o.puzzle]
    hints = [o.puzzle.hint for o in puzzle if o.puzzle]
    assert not any(f'"{h}"' in dumped for h in hints)
    assert all(f'"answer": "{a}"' not in dumped for a in answers)


def test_the_observer_answers_mission_text_requests(tmp_path):
    from fastapi.testclient import TestClient
    from ai_observer.server import create_app
    from tests.fork.test_observer import TOKEN, ORIGIN, auth, until
    app = create_app(TOKEN, tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect('/observe', headers={'Origin': ORIGIN}) as ws:
            auth(ws)
            ws.send_json({'version': 1, 'type': 'campaign', 'action': 'mission_text', 'campaign_id': CID, 'mission_id': 'orientation'})
            text = until(ws, 'mission_text')
            assert text['mission'] == 'orientation' and text['briefing']['lines']
            ws.send_json({'version': 1, 'type': 'campaign', 'action': 'mission_text', 'campaign_id': CID, 'mission_id': 'first_assessment'})
            assert 'locked' in until(ws, 'campaign_state')['command_error']
            ws.send_json({'version': 1, 'type': 'campaign', 'action': 'mission_text', 'campaign_id': CID})
            assert until(ws, 'protocol_error')


# ---- HELIX-003: The Asterion Initiative ends with Mission 14

def finish_mission_14(tmp_path):
    from tests.ai.test_campaign_chapter2 import seed
    svc = seed(tmp_path, 'ghost_in_the_machine')
    run(svc, 'nova', report(sid='p'))
    out = []
    for oid, option in (('log', 'internal'), ('money', 'helix'), ('record', 'inside')):
        out += svc.answer(oid, option, report(sid='p'), MODEL['nova'])
    return svc, results(out)


def test_mission_14_completes_the_campaign_with_celestes_closing_lines(tmp_path):
    svc, [result] = finish_mission_14(tmp_path)
    assert result['chapter_complete']['id'] == 'shadows_of_helix' and result['campaign_complete']
    closing = result['campaign_completion']
    assert closing['speaker'] == 'celeste' and any('Helix Dynamics' in line for line in closing['lines'])
    assert result['earned'][-1] == {'type': 'campaign_complete', 'id': CID, 'label': 'The Asterion Initiative complete'}
    [cue] = svc.take_cues()
    assert cue['campaign_complete'] and cue['chapter'] == 'Shadows of Helix'
    campaign = svc.state()['campaigns'][0]
    assert campaign['completed'] and campaign['completed_at']
    saved = json.loads((tmp_path / 'campaign-progress.json').read_text())
    assert saved['campaigns'][CID]['completed_at'] and 'campaign_complete:asterion_initiative' in saved['campaigns'][CID]['rewards']


def test_the_teaser_chapter_is_gone_and_no_chapter_is_a_teaser():
    campaign = Book.load().campaign(CID)
    assert [c.id for c in campaign.chapters] == ['introduction', 'advanced_research', 'shadows_of_helix']
    assert not any(c.teaser for c in campaign.chapters)


@pytest.mark.parametrize('version', [2, 3])
def test_a_player_who_finished_mission_14_before_finds_the_campaign_complete(tmp_path, version):
    """Saved before Mission 14 completed the campaign: completion follows from the missions on load."""
    from tests.ai.test_campaign_chapter2 import seed, STAMP
    seed(tmp_path, None, version=version)
    progress = json.loads((tmp_path / 'campaign-progress.json').read_text())
    record = progress['campaigns'][CID]
    record['rewards'].pop('campaign_complete:asterion_initiative', None)
    record['completed_at'] = None
    (tmp_path / 'campaign-progress.json').write_text(json.dumps(progress))
    svc = service(tmp_path)
    campaign = svc.state()['campaigns'][0]
    assert campaign['completed'] and campaign['completed_at'] == STAMP
    assert svc.record(CID).rewards['campaign_complete:asterion_initiative'].mission == 'ghost_in_the_machine'


def test_a_campaign_requiring_asterion_opens_only_once_asterion_is_complete(tmp_path):
    root = tmp_path / 'campaigns'
    shutil.copytree(CAMPAIGN_DIR / CID, root / CID)
    (root / 'next_story').mkdir()
    (root / 'next_story' / 'campaign.json').write_text(json.dumps({'schema_version': 1, 'id': 'next_story', 'order': 2, 'title': 'Next',
        'description': 'x', 'available_from_start': False, 'requires_campaigns': [CID], 'starting_companions': ['nova'],
        'missions': [{'id': 'one', 'order': 1, 'title': 'One', 'summary': 'x', 'companion': 'nova',
                      'objectives': [{'id': 'e', 'type': 'edge_count', 'count': 1, 'label': 'Edge'}]}]}))
    book = Book.load(root)
    fresh = service(tmp_path / 'fresh', book)
    assert [c['available'] for c in fresh.state()['campaigns']] == [True, False]
    with pytest.raises(ValueError, match='locked'): fresh.start('next_story', 'one')
    from tests.ai.test_campaign_chapter2 import seed
    seed(tmp_path / 'done', None)
    done = service(tmp_path / 'done', book)
    assert [c['available'] for c in done.state()['campaigns']] == [True, True]
    done.start('next_story', 'one')


# ---- HELIX-005: story flags other campaigns can read, and `when` conditions

from pydantic import ValidationError
from companion_ai.campaign import When, evaluate, check_when


def when(data):
    return When.model_validate(data)


@pytest.mark.parametrize('condition,flags,expected', [
    ({'flag': 'cover', 'eq': 'researcher'}, {'cover': 'researcher'}, True),
    ({'flag': 'cover', 'eq': 'researcher'}, {'cover': 'volunteer'}, False),
    ({'flag': 'cover', 'eq': 'researcher'}, {}, False),
    ({'flag': 'cover', 'in': ['researcher', 'volunteer']}, {'cover': 'volunteer'}, True),
    ({'flag': 'cover', 'in': ['researcher', 'volunteer']}, {}, False),
    ({'not': {'flag': 'cover', 'eq': 'blown'}}, {}, True),
    ({'not': {'flag': 'cover', 'eq': 'blown'}}, {'cover': 'blown'}, False),
    ({'all': [{'flag': 'a', 'eq': 'x'}, {'flag': 'b', 'eq': 'y'}]}, {'a': 'x', 'b': 'y'}, True),
    ({'all': [{'flag': 'a', 'eq': 'x'}, {'flag': 'b', 'eq': 'y'}]}, {'a': 'x'}, False),
    ({'any': [{'flag': 'a', 'eq': 'x'}, {'flag': 'b', 'eq': 'y'}]}, {'b': 'y'}, True),
    ({'any': [{'flag': 'a', 'eq': 'x'}, {'flag': 'b', 'eq': 'y'}]}, {}, False),
    ({'flag': 'asterion_initiative.helix_connection', 'eq': 'discovered'}, {'asterion_initiative.helix_connection': 'discovered'}, True),
])
def test_when_evaluates_each_operator(condition, flags, expected):
    assert evaluate(when(condition), flags) is expected


def test_no_condition_is_always_true():
    assert evaluate(None, {}) is True


@pytest.mark.parametrize('bad', [
    {}, {'flag': 'a'}, {'flag': 'a', 'eq': 'x', 'in': ['x']}, {'eq': 'x'}, {'all': []},
    {'all': [{'flag': 'a', 'eq': 'x'}], 'any': [{'flag': 'a', 'eq': 'x'}]}, {'flag': 'Bad Name', 'eq': 'x'},
    {'flag': 'a', 'eq': 'Not Snake'}, {'flag': 'a', 'eq': 'x', 'extra': 1}, {'flag': 'a.b.c', 'eq': 'x'},
    {'not': {'not': {'not': {'not': {'flag': 'a', 'eq': 'x'}}}}},
])
def test_when_refuses_malformed_conditions(bad):
    with pytest.raises(ValidationError): when(bad)


def test_check_when_refuses_unknown_flags_and_values_nothing_sets():
    declared = {'cover': {'researcher', 'volunteer'}}
    check_when(when({'flag': 'cover', 'in': ['researcher', 'volunteer']}), declared)
    with pytest.raises(ValueError, match='unknown flag'): check_when(when({'flag': 'covr', 'eq': 'researcher'}), declared)
    with pytest.raises(ValueError, match='nothing sets'): check_when(when({'not': {'flag': 'cover', 'eq': 'blown'}}), declared)


def test_asterion_declares_its_story_flags_for_campaigns_that_inherit_them():
    flags = Book.load().campaign(CID).own_flags()
    assert flags['player_suspicion'] == {'suspected', 'cleared'} and flags['helix_connection'] == {'discovered'}


def inheriting(tmp_path, inherits, requires=(CID,)):
    root = tmp_path / 'campaigns'
    if not root.exists(): shutil.copytree(CAMPAIGN_DIR / CID, root / CID)
    (root / 'next_story').mkdir(exist_ok=True)
    (root / 'next_story' / 'campaign.json').write_text(json.dumps({'schema_version': 1, 'id': 'next_story', 'order': 2, 'title': 'Next',
        'description': 'x', 'available_from_start': False, 'requires_campaigns': list(requires), 'inherits_flags_from': list(inherits),
        'starting_companions': ['nova'], 'missions': [{'id': 'one', 'order': 1, 'title': 'One', 'summary': 'x', 'companion': 'nova',
        'objectives': [{'id': 'e', 'type': 'edge_count', 'count': 1, 'label': 'Edge'}], 'flags': {'cover': 'researcher'}}]}))
    return Book.load(root)


def test_a_campaign_reads_inherited_flags_with_the_campaign_prefix(tmp_path):
    from tests.ai.test_campaign_chapter2 import seed
    book = inheriting(tmp_path, [CID])
    assert not book.errors
    declared = book.declared_flags(book.campaign('next_story'))
    assert declared['cover'] == {'researcher'} and declared[f'{CID}.helix_connection'] == {'discovered'}
    seed(tmp_path / 'p', None)
    progress = json.loads((tmp_path / 'p' / 'campaign-progress.json').read_text())
    progress['campaigns'][CID]['flags'] = {k: v for m in book.campaign(CID).missions for k, v in m.flags.items()}
    (tmp_path / 'p' / 'campaign-progress.json').write_text(json.dumps(progress))
    svc = service(tmp_path / 'p', book)
    flags = svc.story_flags(book.campaign('next_story'))
    assert flags[f'{CID}.helix_connection'] == 'discovered' and flags[f'{CID}.player_suspicion'] == 'cleared'
    assert evaluate(when({'flag': f'{CID}.asterion_insider', 'eq': 'suspected'}), flags)
    # Read only: nothing the second campaign does writes Asterion's flags.
    svc.start('next_story', 'one')
    run(svc, 'nova', report(sid='n'), report(sid='n', edges=1))
    assert svc.record('next_story').flags == {'cover': 'researcher'} and 'cover' not in svc.record(CID).flags


def test_inheriting_needs_a_required_and_installed_campaign(tmp_path):
    book = inheriting(tmp_path / 'a', [CID], requires=())
    assert [e['path'] for e in book.errors] == ['next_story'] and not book.campaign('next_story')
    shutil.copytree(CAMPAIGN_DIR / CID, tmp_path / 'b' / 'campaigns' / CID)
    shutil.rmtree(tmp_path / 'b' / 'campaigns' / CID)
    book = inheriting(tmp_path / 'b', [CID])
    assert book.errors == [{'path': 'next_story', 'detail': 'inherits flags from a campaign that is not installed'}]


def test_vex9_is_named_among_the_other_companions_in_a_mission_brief(tmp_path):
    """HELIX-006 (campaign part): talk of VEX-9's mission is not read as a claim about the current one."""
    root = tmp_path / 'campaigns'
    (root / 'duo').mkdir(parents=True)
    (root / 'duo' / 'campaign.json').write_text(json.dumps({'schema_version': 1, 'id': 'duo', 'order': 1, 'title': 'Duo', 'description': 'x',
        'starting_companions': ['nova', 'vex9'], 'missions': [
            {'id': 'a', 'order': 1, 'title': 'A', 'summary': 'x', 'companion': 'nova', 'objectives': [{'id': 'e', 'type': 'edge_count', 'count': 1, 'label': 'Edge'}]},
            {'id': 'b', 'order': 2, 'title': 'B', 'summary': 'x', 'companion': 'vex9', 'objectives': [{'id': 'e', 'type': 'edge_count', 'count': 1, 'label': 'Edge'}]}]}))
    svc = service(tmp_path, Book.load(root))
    svc.start('duo', 'a')
    others = svc.model_context(MODEL['nova'], report())['others']
    assert {'vex9', 'VEX-9', 'VEX'} <= set(others)


def test_a_campaign_adds_its_own_words_for_a_mission_to_the_premature_completion_check(tmp_path):
    """HELIX-006 (fidelity part): Asterion's words stay; a campaign can add e.g. "protocol"."""
    from companion_ai.fidelity import campaign_violations
    active = {'campaign_state': 'active', 'campaign_others': []}
    assert campaign_violations('The mission is complete.', active) == ['premature_mission_complete']
    assert campaign_violations('The protocol is complete.', active) == []
    words = active | {'campaign_mission_words': ['protocol']}
    assert campaign_violations('The protocol is complete.', words) == ['premature_mission_complete']
    assert campaign_violations('The protocol is not complete yet.', words) == []
    assert campaign_violations('You passed the earlier protocol.', words) == []
    assert campaign_violations('The protocol is complete.', active | {'campaign_mission_words': ['Bad Word!']}) == []
    root = tmp_path / 'campaigns'
    (root / 'words').mkdir(parents=True)
    definition = {'schema_version': 1, 'id': 'words', 'order': 1, 'title': 'W', 'description': 'x', 'starting_companions': ['nova'],
        'mission_words': ['protocol'], 'missions': [{'id': 'a', 'order': 1, 'title': 'A', 'summary': 'x', 'companion': 'nova',
        'objectives': [{'id': 'e', 'type': 'edge_count', 'count': 1, 'label': 'Edge'}]}]}
    (root / 'words' / 'campaign.json').write_text(json.dumps(definition))
    svc = service(tmp_path, Book.load(root))
    svc.start('words', 'a')
    assert svc.model_context(MODEL['nova'], report())['mission_words'] == ['protocol']
    (root / 'words' / 'campaign.json').write_text(json.dumps(definition | {'mission_words': ['Two Words']}))
    assert Book.load(root).errors


# ---- HELIX-021 (data part): scene fields on narrative blocks

def scene_book(tmp_path, block_fields, registry=True):
    """A copy of Asterion whose first briefing carries scene fields, with a small story-art registry."""
    root = tmp_path / 'campaigns'; shutil.copytree(CAMPAIGN_DIR / CID, root / CID)
    path = root / CID / 'narrative.json'
    narrative = json.loads(path.read_text())
    narrative['missions']['orientation']['briefing'] |= block_fields
    path.write_text(json.dumps(narrative))
    story = tmp_path / 'story'
    if registry:
        (story / CID).mkdir(parents=True)
        (story / CID / 'ASSETS.json').write_text(json.dumps({'schema_version': 1, 'campaign': CID, 'slots': {
            'h_arrival': {'kind': 'illustration'}, 'env_lab': {'kind': 'environment'}, 'chapter_1_splash': {'kind': 'chapter_splash'}}}))
    return Book.load(root, story)


def test_a_block_can_name_an_expression_an_image_and_a_background(tmp_path):
    book = scene_book(tmp_path, {'expression': 'concerned', 'image': 'h_arrival', 'background': 'env_lab'})
    assert not book.errors
    text = service(tmp_path, book).mission_text(CID, 'orientation')
    assert {k: text['briefing'].get(k) for k in ('expression', 'image', 'background')} == \
        {'expression': 'concerned', 'image': 'h_arrival', 'background': 'env_lab'}


def test_blocks_without_scene_fields_send_none(tmp_path):
    text = service(tmp_path).mission_text(CID, 'orientation')
    assert not {'expression', 'image', 'background'} & set(text['briefing'])


@pytest.mark.parametrize('fields, registry, detail', [
    ({'expression': 'angry'}, True, '1 definition errors'),
    ({'image': 'nope'}, True, 'unknown story-art slot nope'),
    ({'image': 'env_lab'}, True, 'image cannot use the environment slot env_lab'),
    ({'background': 'h_arrival'}, True, 'background cannot use the illustration slot h_arrival'),
    ({'image': 'h_arrival'}, False, 'no story-art registry'),
    ({'image': '../x'}, True, '1 definition errors'),
])
def test_bad_scene_fields_reject_the_campaign(tmp_path, fields, registry, detail):
    book = scene_book(tmp_path, fields, registry)
    assert CID not in [c.id for c in book.campaigns]
    assert any(detail in e['detail'] for e in book.errors), book.errors


def test_a_chapter_splash_may_be_shown_as_an_image(tmp_path):
    assert not scene_book(tmp_path, {'image': 'chapter_1_splash'}).errors


# ---- HELIX-030: story-only characters

from companion_ai.campaign import MANIFEST, story_characters, unknown_speakers


def story_manifest(tmp_path):
    catalog = json.loads(MANIFEST.read_text())
    catalog['characters']['nova']['role'] = 'story'
    path = tmp_path / 'manifest.json'; path.write_text(json.dumps(catalog))
    return path


def test_the_chief_scientist_is_a_story_only_placeholder_without_a_model():
    catalog = json.loads(MANIFEST.read_text())
    scientist = catalog['characters']['helix_scientist']
    assert scientist['role'] == 'story' and scientist['status'] == 'placeholder'
    assert list(scientist['expressions']) == ['neutral'] and 'animations' not in scientist
    assert 'helix_scientist' not in catalog['models'].values()
    assert story_characters() == {'helix_scientist'}


def test_a_story_only_character_cannot_be_a_mission_companion(tmp_path):
    root = tmp_path / 'campaigns'; shutil.copytree(CAMPAIGN_DIR / CID, root / CID)
    book = Book.load(root, manifest=story_manifest(tmp_path))
    assert CID not in [c.id for c in book.campaigns]
    assert 'nova is a story-only character and cannot be a companion' in book.errors[0]['detail']


def test_a_story_only_character_cannot_be_unlocked_or_start_as_a_companion(tmp_path):
    root = tmp_path / 'campaigns'; shutil.copytree(CAMPAIGN_DIR / CID, root / CID)
    path = root / CID / 'campaign.json'; definition = json.loads(path.read_text())
    definition['starting_companions'] += ['helix_scientist']; path.write_text(json.dumps(definition))
    assert 'helix_scientist is a story-only character' in Book.load(root).errors[0]['detail']


def test_narrative_speakers_without_a_manifest_entry_are_listed():
    assert unknown_speakers(Book.load()) == {}
