# SPDX-License-Identifier: AGPL-3.0-only
"""H1 Entry Protocol (HELIX-050): the shipped definition played through the campaign service, no live model."""
import json
from companion_ai.campaign import Book
from tests.ai.test_campaign import service, results
from tests.ai.test_campaign_chapter2 import seed, tick

HID = 'rise_of_helix'
H1 = 'h1_entry_protocol'
IRIS = 'iris-narrative-f29-v018:latest'


def h1_service(tmp_path):
    seed(tmp_path, None)  # The Asterion Initiative completed: Helix is open.
    svc = service(tmp_path)
    svc.identity = lambda model: 'iris' if model == IRIS else None
    svc.start(HID, H1)
    return svc


def play(svc, start, end, intensity, edges=0):
    out, r = [], None
    for t in range(start, end + 1, 5):
        r = tick('s', t, intensity=intensity, edges=edges)
        out += svc.observe(r, [], IRIS)
    return out, r


def test_shipped_h1_definition():
    m = Book.load().campaign(HID).mission(H1)
    assert [o.id for o in m.objectives] == ['hr', 'toy', 'start', 'intake', 'edges', 'cover', 'badge']
    intake = m.objectives[3]
    assert [(s.id, s.seconds, s.intensity, s.set_to) for s in intake.stages] == [
        ('baseline', 300, 70, True), ('compliance', 300, 90, True), ('threshold', 300, 110, True)]
    assert m.objectives[5].after_stage == 'intake:compliance'
    assert [o.id for o in m.objectives[5].choice.options] == ['volunteer', 'analyst', 'defector']
    assert m.objectives[6].puzzle.answer == 'subject'
    # No AI settings control: directed, and no stage needs the model (every stage is set_to).
    assert m.settings_control.directed and m.settings_control.allowed == ['intensity']
    n = Book.load().narratives[HID].missions[H1]
    assert set(n.directions) == {'start', 'intake:compliance', 'intake:threshold', 'cover:volunteer', 'cover:analyst',
                                 'cover:defector', 'edges:done', 'intake:done'}
    assert set(n.milestones) == {'badge:done'} and len(n.director_context) <= 400


def test_h1_full_run_ramp_choice_puzzle_flags_and_private_directions(tmp_path):
    svc = h1_service(tmp_path)
    sent = []
    out, r = play(svc, 0, 300, 70); sent += out
    ramp = [d for d in svc.take_directives() if d.get('scripted')]
    assert not svc.settings_check({'setting': 'intensity', 'value': 40}, r)  # the model never gets a settings step
    # A level change costs one frame of stage time: Compliance fills from 310 to 605.
    out, r = play(svc, 305, 605, 90); sent += out
    ramp += [d for d in svc.take_directives() if d.get('scripted')]
    sent += svc.answer('cover', 'defector', r, IRIS)
    sent += svc.answer('badge', 'subject', r, IRIS)
    out, r = play(svc, 610, 910, 110, edges=3); sent += out
    ramp += [d for d in svc.take_directives() if d.get('scripted')]
    # One intensity request per stage, at its start: 70%, 90%, 110% (slider value = percent - 50).
    assert [(d['key'], d['fallback']['value']) for d in ramp] == [('intake:baseline', 20), ('intake:compliance', 40), ('intake:threshold', 60)]
    [result] = results(sent)
    assert svc.record(HID).flags == {'h1_entry': 'completed', 'rpu_designation': 'discovered', 'h1_cover': 'defector'}
    cues = svc.take_cues()
    keys = [c.get('key') for c in cues if c['kind'] == 'moment']
    assert {'start', 'intake:compliance', 'cover:defector', 'intake:threshold', 'edges:done', 'intake:done'} <= set(keys)
    assert [m['key'] for m in sent if m['type'] == 'mission_milestone'] == ['badge:done']
    # Directions reach only the model's card brief, never the browser.
    blob = json.dumps(sent)
    directions = Book.load().narratives[HID].missions[H1].directions.values()
    assert not any(text in blob for text in directions)
    assert 'Panic' not in blob and 'Reproductive Production Unit 001' not in blob


def test_h1_briefing_reads_as_story_draft_and_all_five_missions_are_written(tmp_path):
    svc = h1_service(tmp_path)
    text = svc.mission_text(HID, H1)
    assert text['narrative_status'] == 'draft' and text['narrative_draft']
    state = next(c for c in svc.state()['campaigns'] if c['id'] == HID)
    assert state['narrative_status'] == 'placeholder'
    assert [m['narrative_status'] for m in state['missions']] == ['draft'] * 5


def test_puzzle_status_is_explicit_and_keeps_game_words_out(tmp_path):
    """Live checks 2026-11-20: 'puzzle "Your badge": open now' became 'the badge puzzle' and was read as solved."""
    svc = h1_service(tmp_path)
    play(svc, 0, 300, 70)
    _, r = play(svc, 305, 605, 90)
    text = svc.model_context(IRIS, r)['text']
    assert 'NOT solved yet' in text and 'puzzle "' not in text and 'Entry Protocol' not in text and 'never by a menu label' in text
    svc.answer('badge', 'subject', r, IRIS)
    assert 'they have worked out the question about your badge' in svc.model_context(IRIS, r)['text']
