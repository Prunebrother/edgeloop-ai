# SPDX-License-Identifier: AGPL-3.0-only
"""HELIX-004/007: shipped placeholder shell, campaign unlocks and release refusal."""
import json
from pathlib import Path
import pytest
from companion_ai.campaign import Book, Narrative, NarrativeBlock, Objective
from tests.ai.test_campaign import CID, MODEL, service, report, run, results
from tests.ai.test_campaign_chapter2 import seed
from tests.ai.test_campaign_helix_foundations import finish_mission_14

HID = 'rise_of_helix'
MISSIONS = ['h1_entry_protocol', 'h2_shadow_evaluation', 'h3_extraction_assessment', 'h4_breach_detected', 'h5_controlled_release']
COMPANIONS = ['iris', 'mira', 'vex9', 'vex9', 'iris']
# Missions with real data (their own tests: test_campaign_helix_h<n>.py). Since H5 (2026-11-24) that is all of Chapter 1.
REAL = set(MISSIONS)
# Early warning only: the hard limits are the 48 KB test (test_campaign_chapter3) and the observer's 64 KB.
# A real Helix mission costs about 2.2 KB of board state; all five real stays near 34 KB.
BUDGET = 36000


def helix(svc):
    return next(c for c in svc.state()['campaigns'] if c['id'] == HID)


def test_shipped_definition_chain_companions_and_teaser():
    book = Book.load()
    assert not book.errors and [c.id for c in book.campaigns] == [CID, HID]
    campaign = book.campaign(HID)
    assert campaign.order == 2 and campaign.title == 'Rise of Helix'
    assert not campaign.available_from_start
    assert campaign.requires_campaigns == campaign.inherits_flags_from == [CID]
    assert campaign.starting_companions == ['iris', 'mira', 'vex9', 'seraphine']
    assert campaign.mission_words == ['protocol', 'procedure', 'operation']
    assert [(c.number, c.id, c.teaser) for c in campaign.chapters] == [(1, 'undercover', False), (2, 'helix_ch2', True)]
    assert [m.id for m in campaign.missions] == MISSIONS
    assert [m.companion for m in campaign.missions] == COMPANIONS
    for i, mission in enumerate(campaign.missions):
        assert mission.prerequisites == ([MISSIONS[i - 1]] if i else [])
        assert mission.story.chapter == 1
        if mission.id in REAL: continue  # Real definitions have their own tests (tests/ai/test_campaign_helix_h<n>.py).
        assert mission.summary.startswith('PLACEHOLDER')
        assert [o.type for o in mission.objectives] == ['hr_monitor_connected', 'toy_connected', 'session_started', 'edge_count']
        assert all(o.label == 'PLACEHOLDER objective' for o in mission.objectives)
        assert mission.objectives[-1].count == 1
    assert ('chapter_complete', 'undercover') in [(r.type, r.id) for r in campaign.missions[-1].rewards]
    assert not any(r.type == 'campaign_complete' for m in campaign.missions for r in m.rewards)
    narrative = book.narratives[HID]
    # All five missions and the Chapter 1 close are Draft text; the chapter intro is still placeholder, so the campaign still reads as placeholder.
    assert narrative.status == 'draft' and narrative.placeholder() and set(narrative.missions) == set(MISSIONS)
    assert all(b.status == 'placeholder' and all(line.startswith('PLACEHOLDER') for line in b.lines)
               for mid, m in narrative.missions.items() if mid not in REAL for b in m.blocks())
    assert all(b.status == 'draft' for mid in REAL for b in narrative.missions[mid].blocks())
    assert narrative.chapters['undercover'].status == 'draft' and narrative.chapters['undercover'].speaker == 'seraphine'
    assert all(b.status == 'placeholder' for b in narrative.chapter_intros['undercover'])
    catalog = json.loads((Path(__file__).resolve().parents[2] / 'src/assets/characters/manifest.json').read_text())
    # Iris graduated from placeholder on 2026-11-20 (approved art, persona and cards).
    assert 'status' not in catalog['characters']['iris']
    assert catalog['models']['iris-narrative-f29-v018:latest'] == 'iris'


def test_fresh_progress_lists_locked_campaign_reason_and_refuses_start(tmp_path):
    svc = service(tmp_path)
    campaign = helix(svc)
    assert not campaign['available']
    assert campaign['requires'] == [{'id': CID, 'title': 'The Asterion Initiative', 'completed': False}]
    assert campaign['locked_reason'] == 'Complete The Asterion Initiative to unlock.'
    assert all(m['state'] == 'locked' for m in campaign['missions'])
    with pytest.raises(ValueError, match='locked'): svc.start(HID, MISSIONS[0])
    with pytest.raises(ValueError, match='locked'): svc.mission_text(HID, MISSIONS[0])


def test_completed_asterion_opens_only_the_first_helix_mission_and_briefing(tmp_path):
    seed(tmp_path, None)
    svc = service(tmp_path)
    campaign = helix(svc)
    assert campaign['available'] and campaign['locked_reason'] is None
    assert campaign['requires'][0]['completed']
    assert [m['state'] for m in campaign['missions']] == ['available', *['locked'] * 4]
    assert campaign['narrative_status'] == 'placeholder'
    assert all(m['narrative_status'] == 'placeholder' and not m['narrative_draft'] for m in campaign['missions'] if m['id'] not in REAL)
    assert all(m['narrative_draft'] for m in campaign['missions'] if m['id'] in REAL)
    assert campaign['chapters'][0]['available'] and campaign['chapters'][1]['teaser']
    text = svc.mission_text(HID, MISSIONS[0])
    assert text['narrative_draft'] and text['briefing']['speaker'] == 'iris' and text['briefing']['status'] == 'draft'
    assert text['briefing']['lines'][0].startswith("Oh! You're the new")
    svc.start(HID, MISSIONS[0])  # A definition needs no installed model to load/start; selection remains the UI's existing gate.
    assert svc.state()['active']['campaign'] == HID


def test_final_asterion_completion_announces_new_campaign_once_and_not_on_replay(tmp_path):
    svc, [result] = finish_mission_14(tmp_path)
    assert result['unlocked_campaigns'] == [{'id': HID, 'title': 'Rise of Helix'}]
    assert helix(svc)['available']
    assert not results(run(svc, 'nova', report(sid='p')))
    svc = service(tmp_path)  # Reload must not make the next replay announce an unlock.
    svc.start(CID, 'ghost_in_the_machine')
    run(svc, 'nova', report(sid='replay'))
    out = []
    for oid, choice in [('log', 'internal'), ('money', 'helix'), ('record', 'inside')]:
        out += svc.answer(oid, choice, report(sid='replay'), MODEL['nova'])
    [replay] = results(out)
    assert replay['replay'] and replay['unlocked_campaigns'] == []


def test_ordinary_mission_has_no_campaign_unlock(tmp_path):
    svc = service(tmp_path); svc.start(CID, 'orientation')
    [result] = results(run(svc, 'nova', report(edges=0), report(edges=1)))
    assert result['unlocked_campaigns'] == []


def test_failed_final_save_announces_unlock_only_after_success(tmp_path):
    svc = seed(tmp_path, 'ghost_in_the_machine')
    run(svc, 'nova', report(sid='p'))
    for oid, choice in [('log', 'internal'), ('money', 'helix')]: svc.answer(oid, choice, report(sid='p'), MODEL['nova'])
    write = svc.store.write
    def broken(*args):
        if args[1]['active'] is None: raise OSError('disk full')
        return write(*args)
    svc.store.write = broken
    assert not results(svc.answer('record', 'inside', report(sid='p'), MODEL['nova']))
    assert not helix(svc)['available']
    svc.store.write = write
    [result] = results(run(svc, 'nova', report(sid='p')))
    assert result['unlocked_campaigns'] == [{'id': HID, 'title': 'Rise of Helix'}]


@pytest.mark.parametrize('where', ['narrative', 'briefing', 'completion', 'epilogue', 'milestone'])
def test_placeholder_status_precedes_draft_and_keeps_draft_boolean(tmp_path, where):
    seed(tmp_path, None)
    svc = service(tmp_path)
    narrative = svc.book.narratives[HID].model_copy(deep=True)
    svc.book = Book(svc.book.campaigns, svc.book.narratives | {HID: narrative})
    narrative.status = 'approved'
    block = narrative.missions[MISSIONS[0]]
    for m in narrative.missions.values():
        for b in m.blocks(): b.status = 'approved'
    for b in narrative.chapters.values(): b.status = 'approved'
    block.completion.status = 'draft'
    placeholder = NarrativeBlock(speaker='iris', lines=['PLACEHOLDER test.'], status='placeholder')
    if where == 'narrative': narrative.status = 'placeholder'
    elif where == 'epilogue': block.epilogue = [placeholder]
    elif where == 'milestone': block.milestones = {'start': placeholder}
    else: setattr(block, where, placeholder)
    state = helix(svc)
    assert state['narrative_status'] == 'placeholder'
    assert state['missions'][0]['narrative_status'] == 'placeholder'
    assert svc.mission_text(HID, MISSIONS[0])['narrative_status'] == 'placeholder'
    assert state['missions'][0]['narrative_draft'] == (where != 'completion')


def test_draft_and_approved_statuses_still_work(tmp_path):
    svc = service(tmp_path)
    assert svc.state()['campaigns'][0]['missions'][0]['narrative_status'] is None
    narrative = svc.book.narratives[CID].model_copy(deep=True)
    narrative.missions['orientation'].completion.status = 'draft'
    svc.book = Book(svc.book.campaigns, svc.book.narratives | {CID: narrative})
    assert svc.mission_text(CID, 'orientation')['narrative_status'] == 'draft'
    assert svc.mission_text(CID, 'orientation')['narrative_draft']


def test_both_shipped_campaigns_fit_the_early_warning_budget_and_retain_objective_keys(tmp_path):
    svc = service(tmp_path)
    state = svc.state()
    assert len(json.dumps(state).encode()) < BUDGET
    for campaign in state['campaigns']:
        definition = svc.book.campaign(campaign['id'])
        for mission in campaign['missions']:
            for shown, objective in zip(mission['objectives'], definition.mission(mission['id']).objectives):
                original = objective.model_dump(exclude_none=True, exclude={'puzzle', 'choice'})
                assert set(shown) == set(original)
                assert shown['styles'] == (original['styles'] if objective.type == 'style_stages' else [])
                assert {k: v for k, v in shown.items() if k != 'styles'} == {k: v for k, v in original.items() if k != 'styles'}


@pytest.mark.parametrize('where', ['narrative', 'briefing', 'completion', 'epilogue', 'milestone', 'chapter', 'campaign_complete', 'approved'])
def test_release_refuses_placeholder_narrative_or_any_placeholder_block(tmp_path, monkeypatch, where):
    from tests.fork.test_story_art import release_tree, inventory, load
    release_tree(tmp_path)
    narrative = Book.load().narratives[CID].model_dump(exclude_none=True)
    if where == 'narrative': narrative['status'] = 'placeholder'
    elif where == 'briefing': narrative['missions']['orientation']['briefing']['status'] = 'placeholder'
    elif where == 'completion': narrative['missions']['orientation']['completion']['status'] = 'placeholder'
    elif where == 'epilogue': narrative['missions']['orientation']['epilogue'] = [{'speaker': 'nova', 'status': 'placeholder', 'lines': ['PLACEHOLDER']}]
    elif where == 'milestone': narrative['missions']['orientation']['milestones'] = {'start': {'speaker': 'nova', 'status': 'placeholder', 'lines': ['PLACEHOLDER']}}
    elif where == 'chapter': narrative['chapters']['introduction']['status'] = 'placeholder'
    elif where == 'campaign_complete': narrative['campaign_complete']['status'] = 'placeholder'
    # This fixture tests review statuses; use its manifest speaker and provide a complete campaign definition.
    def fixture_speaker(value):
        if isinstance(value, dict):
            if 'speaker' in value: value['speaker'] = 'test'
            for child in value.values(): fixture_speaker(child)
        elif isinstance(value, list):
            for child in value: fixture_speaker(child)
    fixture_speaker(narrative)
    folder = tmp_path / 'config/campaigns' / HID; folder.mkdir(parents=True)
    (folder / 'campaign.json').write_text(Book.load().campaign(CID).model_copy(update={'id': HID}).model_dump_json())
    (folder / 'narrative.json').write_text(json.dumps(narrative | {'campaign': HID}))
    inventory(tmp_path)
    module = load('validate-release'); monkeypatch.setattr(module, 'ROOT', tmp_path)
    result = module.validate()
    assert result['passed'] == (where == 'approved')
    if where != 'approved': assert {'path': HID, 'category': 'placeholder campaign narrative'} in result['errors']
    # A public test build may ship unfinished story text (the game badges it); a stable release may not.
    assert module.validate(test_build=True)['passed']


def test_helix_chain_finishes_chapter_but_keeps_campaign_open(tmp_path):
    seed(tmp_path, None)
    svc = service(tmp_path)
    svc.identity = lambda model: model  # Fixture identity only; no Intern model is installed or registered.
    # The chain test walks the five missions with one edge each: missions with real data get a one-edge body here.
    shell = svc.book.campaign(HID); narrative = svc.book.narratives[HID].model_copy(deep=True)
    body = [Objective.model_validate(o) for o in ({'id': 'hr', 'type': 'hr_monitor_connected', 'label': 'HR'},
            {'id': 'toy', 'type': 'toy_connected', 'label': 'Toy'}, {'id': 'start', 'type': 'session_started', 'label': 'Start'},
            {'id': 'edge', 'type': 'edge_count', 'count': 1, 'label': 'One edge'})]
    for mid in REAL:
        narrative.missions[mid] = narrative.missions[mid].model_copy(update={'directions': {}, 'milestones': {}, 'story_so_far': []})
    missions = [m.model_copy(update={'objectives': body, 'settings_control': None, 'completion': None}) if m.id in REAL else m for m in shell.missions]
    svc.book = Book([svc.book.campaign(CID), shell.model_copy(update={'missions': missions})], svc.book.narratives | {HID: narrative})
    for index, (mid, companion) in enumerate(zip(MISSIONS, COMPANIONS)):
        svc.start(HID, mid)
        svc.observe(report(sid=mid, edges=0), [], companion)
        [result] = results(svc.observe(report(sid=mid, edges=1), [], companion))
        assert not result['campaign_complete'] and result['unlocked_campaigns'] == []
        assert result['unlocked_missions'] == ([MISSIONS[index + 1]] if index < 4 else [])
    assert result['chapter_complete']['id'] == 'undercover'
    assert result['chapter_completion']['status'] == 'draft' and result['chapter_completion']['speaker'] == 'seraphine'
    assert not helix(service(tmp_path))['completed']


def test_multiple_campaign_requirements_use_their_titles(tmp_path):
    svc = service(tmp_path)
    other = svc.book.campaign(CID).model_copy(update={'id': 'other', 'title': 'Another Campaign'})
    shell = svc.book.campaign(HID).model_copy(update={'requires_campaigns': [CID, 'other']})
    svc.book = Book([svc.book.campaign(CID), other, shell], svc.book.narratives)
    assert helix(svc)['locked_reason'] == 'Complete The Asterion Initiative and Another Campaign to unlock.'
