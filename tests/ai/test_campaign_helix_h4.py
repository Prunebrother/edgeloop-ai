# SPDX-License-Identifier: AGPL-3.0-only
"""H4 Breach Detected (HELIX-053): the shipped definition played through the campaign service, no live model."""
import json
from companion_ai.campaign import Book
from tests.ai.test_campaign import results
from tests.ai.test_campaign_helix_h1 import HID
from tests.ai.test_campaign_helix_h3 import H3, VEX, h3_service, play

H4 = 'h4_breach_detected'


def h4_service(tmp_path, cover='defector', offer='owe'):
    svc = h3_service(tmp_path, cover, offer)
    play(svc, 'h3', 0, 0)
    _, r = play(svc, 'h3', 5, 245, edges=3)
    svc.answer('discrepancy', 'file', r, VEX)
    play(svc, 'h3', 250, 1000, edges=8)
    assert results(play(svc, 'h3', 1005, 1205, edges=8, orgasms=1)[0])
    svc.take_cues(); svc.take_directives()
    svc.start(HID, H4)
    return svc


def milestones(sent):
    return [m['key'] for m in sent if m['type'] == 'mission_milestone']


def test_shipped_h4_definition():
    m = Book.load().campaign(HID).mission(H4)
    assert m.companion == 'vex9' and m.prerequisites == [H3] and m.difficulty == 'challenge'
    assert [o.id for o in m.objectives] == ['hr', 'toy', 'start', 'detention', 'edges', 'deadline', 'offer', 'sample']
    assert [(s.id, s.seconds) for s in m.objectives[3].stages] == [('processing', 300), ('interrogation', 480), ('extraction', 300)]
    deadline = m.objectives[5]
    assert (deadline.count, deadline.within_seconds, deadline.warnings, deadline.optional) == (6, 600, [180, 60], True)
    assert m.objectives[7].optional and m.objectives[7].after == 'edges'
    assert not any(o.type == 'puzzle_solved' for o in m.objectives)  # author 2026-11-20: no puzzle
    assert m.settings_control.allowed == ['intensity'] and not m.settings_control.directed
    assert m.flags == {'h4_exposed': 'true'}


def test_seraphines_briefing_knows_whether_iris_covered_for_them(tmp_path):
    lines = h4_service(tmp_path, cover='defector').mission_text(HID, H4)['briefing']['lines']
    assert "My daughter wrote 'volunteer' on your form." in lines[1] and len(lines) == 4
    other = h4_service(tmp_path / 'b', cover='analyst').mission_text(HID, H4)['briefing']['lines']
    assert 'Someone in my building believed your story' in other[1] and not any('daughter' in x for x in other)


def test_deadline_met_offer_refused_and_three_epilogue_blocks(tmp_path):
    svc = h4_service(tmp_path, offer='owe')
    sent = []
    out, r = play(svc, 'h4', 0, 0); sent += out
    out, r = play(svc, 'h4', 5, 305, edges=3); sent += out
    sent += svc.answer('offer', 'refuse', r, VEX)
    out, r = play(svc, 'h4', 310, 545, edges=5); sent += out   # both warnings (7:00, 9:00) before the 6th edge
    out, r = play(svc, 'h4', 550, 1085, edges=6); sent += out
    [result] = results(sent)
    assert milestones(sent)[:5] == ['start', 'detention:interrogation', 'deadline:left180', 'deadline:left60', 'deadline:done']
    flags = svc.record(HID).flags
    assert flags['h4_exposed'] == 'true' and flags['h4_offer'] == 'refused'
    assert [b['speaker'] for b in result['epilogue']] == ['seraphine', 'mira', 'iris']
    assert 'personnel file' in result['epilogue'][0]['lines'][0] and 'deleted that line once' in result['epilogue'][1]['lines'][0]
    keys = {c.get('key') for c in svc.take_cues() if c['kind'] == 'moment'}
    assert {'edges:3', 'edges:done', 'offer:refuse', 'detention:extraction'} <= keys
    blob = json.dumps(sent)
    n = Book.load().narratives[HID].missions[H4]
    assert not any(t in blob for t in n.directions.values()) and n.director_context not in blob and 'when' not in json.dumps(svc.mission_text(HID, H4))


def test_an_expired_deadline_is_story_not_failure(tmp_path):
    svc = h4_service(tmp_path, offer='ask')
    sent = []
    out, r = play(svc, 'h4', 0, 0); sent += out
    out, r = play(svc, 'h4', 5, 400, edges=2); sent += out
    sent += svc.answer('offer', 'stall', r, VEX)
    out, r = play(svc, 'h4', 405, 700, edges=4); sent += out
    out, r = play(svc, 'h4', 705, 1085, edges=6); sent += out
    [result] = results(sent)
    assert 'deadline:expired' in milestones(sent) and 'deadline:done' not in milestones(sent)
    assert svc.record(HID).flags['h4_offer'] == 'stalled'
    assert 'never left an offer open' in result['epilogue'][0]['lines'][0] and 'copy of everything' in result['epilogue'][1]['lines'][0]


def test_vex_never_sees_the_offer_answer_text(tmp_path):
    svc = h4_service(tmp_path)
    play(svc, 'h4', 0, 0)
    _, r = play(svc, 'h4', 5, 305)
    svc.answer('offer', 'accept', r, VEX)
    text = svc.model_context(VEX, r)['text']
    assert 'a question for the participant: answered' in text and 'Answer Seraphine' not in text and 'I work for you now' not in text
    assert 'Seraphine Vale' in text and 'Story so far: In the lab they blamed their intake file' in text
