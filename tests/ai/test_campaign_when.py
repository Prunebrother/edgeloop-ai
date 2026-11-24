# SPDX-License-Identifier: AGPL-3.0-only
"""Conditional missions, frozen optional goals and narrative filtering; fixture content only."""
import json
from copy import deepcopy
import pytest
from companion_ai.campaign import (Book, Campaign, CampaignRecord, CampaignService, Narrative,
                                   moment_keys, NarrativeBlock, ChapterRecord)
from companion_ai.storage import SettingsStore
from tests.ai.test_campaign_chapter2 import tick

CID = 'fixture_when'
MODEL = 'fixture:latest'
YES = {'flag': 'cover', 'eq': 'analyst'}
NO = {'flag': 'cover', 'eq': 'volunteer'}


def definition():
    return {'schema_version': 1, 'id': CID, 'order': 1, 'title': 'Fixture', 'description': 'Fixture',
        'starting_companions': ['nova'], 'chapters': [{'number': 1, 'id': 'one', 'title': 'One', 'summary': 'Fixture'}],
        'missions': [{'id': 'intake', 'order': 1, 'title': 'Intake', 'summary': 'Fixture', 'companion': 'nova',
            'story': {'chapter': 1}, 'objectives': [
                {'id': 'start', 'type': 'session_started', 'label': 'Start'},
                {'id': 'edges', 'type': 'edge_count', 'label': 'Two edges', 'count': 2},
                {'id': 'cover', 'type': 'choice', 'label': 'Cover', 'choice': {'prompt': 'Cover?', 'options': [
                    {'id': 'analyst', 'label': 'Analyst', 'sets': {'cover': 'analyst'}},
                    {'id': 'volunteer', 'label': 'Volunteer', 'sets': {'cover': 'volunteer'}}]}},
                {'id': 'bonus', 'type': 'edge_count', 'label': 'Bonus goal', 'count': 3, 'milestones': [1], 'optional': True, 'when': YES}]}]}


def block(text, **fields):
    return {'speaker': 'nova', 'lines': [text], **fields}


def narrative():
    return {'schema_version': 1, 'campaign': CID, 'status': 'approved', 'missions': {'intake': {
        'briefing': block('Conditional briefing', when=YES), 'completion': block('Analyst completion', when=YES),
        'epilogue': [block('Volunteer ending', when=NO), block('Always ending')],
        'milestones': {'cover:analyst': block('Chosen analyst', when=YES),
                       'edges:done': block('Hidden milestone', when=NO),
                       'bonus:1': block('Bonus milestone', when=YES)}}},
        'chapter_intros': {'one': [block('Shown intro'), block('Hidden intro', when=NO, status='placeholder')]},
        'chapters': {'one': block('Hidden close', when=NO)}}


def service(tmp_path, data=None, text=None, flags=None):
    campaign = Campaign.model_validate(data or definition())
    story = Narrative.model_validate(text or narrative())
    svc = CampaignService(SettingsStore(tmp_path), book=Book([campaign], {CID: story}), identity=lambda m: 'nova' if m == MODEL else 'other')
    if flags is not None: svc.progress.campaigns.setdefault(CID, CampaignRecord()).flags.update(flags)
    return svc


def begin(svc, sid='s'):
    svc.start(CID, 'intake'); r = tick(sid, 0); svc.observe(r, [], MODEL); return r


def finish(svc, pick='analyst', sid='s'):
    r = begin(svc, sid); out = svc.answer('cover', pick, r, MODEL)
    out += svc.observe(tick(sid, 1, edges=2), [], MODEL)
    return out


@pytest.mark.parametrize('change', [
    lambda m: m.update(locked_reason='No condition'),
    lambda m: m.update(when=YES, locked_reason='two\nlines'),
    lambda m: m.update(when=YES, locked_reason=' '),
    lambda m: m['objectives'][1].update(when=YES),
    lambda m: m['objectives'][0].update(optional=True),
    lambda m: m['objectives'][0].update(type='hr_monitor_connected', optional=True),
    lambda m: m['objectives'][0].update(type='toy_connected', optional=True),
])
def test_invalid_condition_fields(change):
    data = definition(); change(data['missions'][0])
    with pytest.raises(ValueError): Campaign.model_validate(data)


@pytest.mark.parametrize('site', ['mission', 'objective', 'briefing', 'completion', 'epilogue', 'milestone', 'intro', 'close', 'campaign_close'])
@pytest.mark.parametrize('condition', [{'flag': 'typo', 'eq': 'analyst'}, {'flag': 'cover', 'eq': 'typo'}])
def test_load_rejects_unknown_conditions(tmp_path, site, condition):
    data, text = definition(), narrative(); mission = data['missions'][0]; story = text['missions']['intake']
    if site == 'mission': mission['when'] = condition
    elif site == 'objective': mission['objectives'][-1]['when'] = condition
    elif site == 'milestone': story['milestones']['edges:done']['when'] = condition
    elif site == 'intro': text['chapter_intros']['one'][0]['when'] = condition
    elif site == 'close': text['chapters']['one']['when'] = condition
    elif site == 'campaign_close': text['campaign_complete'] = block('Close', when=condition)
    elif site == 'epilogue': story['epilogue'][0]['when'] = condition
    else: story[site]['when'] = condition
    folder = tmp_path / CID; folder.mkdir(); (folder / 'campaign.json').write_text(json.dumps(data)); (folder / 'narrative.json').write_text(json.dumps(text))
    book = Book.load(tmp_path)
    assert not book.campaigns and len(book.errors) == 1
    assert 'unknown flag' in book.errors[0]['detail'] or 'nothing sets' in book.errors[0]['detail']


def test_inherited_flags_lock_reason_active_completed_and_progress(tmp_path):
    data = definition(); source = deepcopy(data); source.update(id='asterion_initiative', order=2)
    data.update(requires_campaigns=['asterion_initiative'], inherits_flags_from=['asterion_initiative'])
    second = deepcopy(data['missions'][0]); second.update(id='branch', order=2, when={'flag': 'asterion_initiative.cover', 'eq': 'analyst'}, locked_reason='An analyst must vouch for you.')
    data['missions'].append(second)
    svc = service(tmp_path, data, flags={'cover': 'analyst'}); svc.book.campaigns.append(Campaign.model_validate(source))
    svc.progress.campaigns['asterion_initiative'] = CampaignRecord(flags={'cover': 'volunteer'})
    campaign = svc.book.campaign(CID); mission = campaign.mission('branch')
    assert svc.story_flags(campaign) == {'cover': 'analyst', 'asterion_initiative.cover': 'volunteer'}
    state = svc.state()['campaigns'][0]
    assert state['missions'][1]['state'] == 'locked' and state['missions'][1]['locked_reason'] == second['locked_reason']
    assert state['progress']['total'] == state['chapters'][0]['progress']['total'] == 1
    svc.progress.campaigns['asterion_initiative'].flags['cover'] = 'analyst'
    assert svc.mission_state(campaign, mission) == 'available'
    svc.start(CID, 'branch'); svc.progress.campaigns['asterion_initiative'].flags['cover'] = 'volunteer'
    assert svc.mission_state(campaign, mission) == 'active'
    svc.abandon(); svc.start(CID, 'intake'); finish(svc)
    # Completed content keeps its state even when its condition subsequently becomes false.
    campaign.mission('intake').when = Campaign.model_validate(data).mission('branch').when
    assert svc.mission_state(campaign, campaign.mission('intake')) == 'completed'
    mission.locked_reason = None
    assert svc.state()['campaigns'][0]['missions'][1]['locked_reason'] == 'Not available on this story path.'


@pytest.mark.parametrize('visible', [False, True])
def test_optional_objective_visibility_frozen_and_never_required(tmp_path, visible):
    svc = service(tmp_path, flags={'cover': 'analyst' if visible else 'volunteer'}); r = begin(svc)
    ids = lambda: [o['id'] for o in svc.state()['attempt']['objectives']]
    assert ('bonus' in ids()) == visible
    assert ('Bonus goal' in svc.model_context(MODEL, r)['text']) == visible
    assert ('bonus' in [o['id'] for o in svc.state()['campaigns'][0]['missions'][0]['objectives']]) == visible
    svc.record(CID).flags['cover'] = 'volunteer' if visible else 'analyst'
    assert ('bonus' in ids()) == visible
    svc.answer('cover', 'analyst', r, MODEL)
    out = svc.observe(tick('s', 1, edges=2), [], MODEL)
    result = next(m for m in out if m['type'] == 'mission_result')
    assert result and svc.record(CID).missions['intake'].completions == 1
    if visible: assert not next(o for o in result['objectives'] if o['id'] == 'bonus')['done']
    else:
        assert 'Bonus goal' not in json.dumps(result)
        assert svc.record(CID).flags['cover'] == 'analyst'


def test_optional_moments_and_skipped_moments_still_fire(tmp_path):
    svc = service(tmp_path, flags={'cover': 'analyst'}); r = begin(svc)
    out = svc.answer('cover', 'analyst', r, MODEL)
    out += svc.observe(tick('s', 1, edges=1), [], MODEL)
    assert 'bonus:1' in svc.attempt.fired
    assert any(m.get('key') == 'bonus:1' for m in out)
    # A skipped scripted block still opens clues keyed to the same verified moment.
    svc.book.narratives[CID].missions['intake'].milestones['bonus:done'] = NarrativeBlock.model_validate(block('Hidden done', when=NO))
    svc.book.campaign(CID).mission('intake').objectives[1].count = 4
    out = svc.observe(tick('s', 2, edges=3), [], MODEL)
    assert 'bonus:done' in svc.attempt.fired and not any(m.get('key') == 'bonus:done' for m in out)
    assert {'bonus:done', 'bonus:1'} <= moment_keys(svc.attempt.mission)


def test_filtering_saved_briefing_chapters_badges_and_replay_overlay(tmp_path):
    svc = service(tmp_path, flags={'cover': 'analyst'})
    assert svc.mission_text(CID, 'intake')['briefing']['lines'] == ['Conditional briefing']
    chapter = svc.chapter_text(CID, 'one')
    assert len(chapter['intro']) == 1 and chapter['narrative_status'] is None
    first = finish(svc)
    assert next(m for m in first if m['type'] == 'mission_result')['completion']['lines'] == ['Analyst completion']
    saved = dict(svc.record(CID).flags)
    replay = finish(svc, 'volunteer', 'replay')
    result = next(m for m in replay if m['type'] == 'mission_result')
    assert result['completion'] is None and result['epilogue'][0]['lines'] == ['Volunteer ending']
    assert svc.record(CID).flags == saved
    assert 'Conditional briefing' in json.dumps(svc.mission_text(CID, 'intake'))
    assert not any(m.get('key') == 'cover:analyst' for m in replay)
    assert 'Hidden milestone' in json.dumps(replay)  # overlay matches this replay's volunteer choice
    assert '"when"' not in json.dumps(result)


def test_false_briefing_and_hidden_draft_do_not_reach_browser(tmp_path):
    text = narrative(); text['missions']['intake']['completion'].update(when=YES, status='draft')
    svc = service(tmp_path, text=text, flags={'cover': 'volunteer'})
    reply = svc.mission_text(CID, 'intake')
    assert reply['briefing'] is None and not reply['narrative_draft'] and reply['narrative_status'] is None
    svc.progress.campaigns[CID].chapters['one'] = ChapterRecord(completed_at='now')
    svc.record(CID).flags['cover'] = 'analyst'
    assert svc.chapter_text(CID, 'one')['close'] is None


def test_optional_puzzle_never_blocks_required_puzzle_and_hidden_answers_are_refused(tmp_path):
    data = definition(); objectives = data['missions'][0]['objectives']
    puzzle = {'id': 'extra', 'type': 'puzzle_solved', 'label': 'Extra puzzle', 'optional': True,
              'puzzle': {'title': 'Fixture', 'clues': ['Clue'], 'question': 'Pick', 'options': [{'id': 'yes', 'label': 'Yes'}, {'id': 'no', 'label': 'No'}], 'answer': 'yes', 'hint': 'Try'}}
    required = deepcopy(puzzle); required.update(id='required', optional=False)
    objectives[2:2] = [puzzle, required]
    svc = service(tmp_path, data, flags={'cover': 'volunteer'}); r = begin(svc)
    assert svc.attempt.puzzle_open(svc.attempt.mission.objectives[3])
    svc.answer('required', 'yes', r, MODEL)
    with pytest.raises(ValueError, match='Unknown'): svc.answer('bonus', 'yes', r, MODEL)
    svc.answer('cover', 'analyst', r, MODEL)
    assert any(m['type'] == 'mission_result' for m in svc.observe(tick('s', 1, edges=2), [], MODEL))
