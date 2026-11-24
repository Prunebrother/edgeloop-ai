# SPDX-License-Identifier: AGPL-3.0-only
"""H5 Controlled Release (HELIX-054/055): both routes of the shipped definition, played through the campaign
service, no live model."""
import json
import pytest
from companion_ai.campaign import Book
from tests.ai.test_campaign import results
from tests.ai.test_campaign_chapter2 import tick
from tests.ai.test_campaign_helix_h1 import HID, IRIS
from tests.ai.test_campaign_helix_h3 import VEX, play as play_vex
from tests.ai.test_campaign_helix_h4 import H4, h4_service, milestones

H5 = 'h5_controlled_release'


def h5_service(tmp_path, offer='refuse', deal='owe'):
    svc = h4_service(tmp_path, offer=deal)
    play_vex(svc, 'h4', 0, 0)
    _, r = play_vex(svc, 'h4', 5, 305, edges=3)
    svc.answer('offer', offer, r, VEX)
    assert results(play_vex(svc, 'h4', 310, 1085, edges=6)[0])
    svc.take_cues(); svc.take_directives()
    svc.start(HID, H5)
    return svc


def play(svc, sid, start, end, edges=0, orgasms=0, intensity=100):
    out, r = [], None
    for t in range(start, end + 1, 5):
        r = tick(sid, t, intensity=intensity, edges=edges, orgasms=orgasms)
        out += svc.observe(r, [], IRIS)
    return out, r


def test_shipped_h5_definition():
    m = Book.load().campaign(HID).mission(H5)
    assert m.companion == 'iris' and m.prerequisites == [H4] and m.difficulty == 'challenge'
    assert [o.id for o in m.objectives] == ['hr', 'toy', 'start', 'trust', 'override', 'run', 'protocol', 'sample']
    run, protocol, sample = m.objectives[5], m.objectives[6], m.objectives[7]
    assert (run.count, run.milestones, run.within_seconds, run.warnings) == (5, [2, 4], 720, [300, 60])
    assert [(s.id, s.seconds, s.intensity) for s in protocol.stages] == [('warmup', 300, None), ('sustain', 600, None), ('release', 300, None)]
    assert (sample.count, sample.after, sample.optional) == (1, 'protocol', False)
    assert m.objectives[4].puzzle.kind == 'code' and m.objectives[3].after_stage is None
    assert [(r.id, r.objectives, r.sets) for r in m.completion.any_of] == [
        ('escape', ['override', 'run'], {'h5_route': 'escaped'}), ('release', ['protocol', 'sample'], {'h5_route': 'released'})]
    assert m.settings_control.allowed == ['intensity'] and not m.settings_control.directed  # author 2026-11-24: Iris controls
    assert {r.key for r in m.rewards} == {'milestone:helix_undercover_out', 'chapter_complete:undercover'}
    assert not any(r.type == 'campaign_complete' for r in m.rewards)  # Chapter 2 teaser: the campaign stays open
    assert m.flags == {'h5_release': 'completed'}


@pytest.mark.parametrize('offer,expect', [('accept', 'said yes to her'), ('refuse', 'So now it\'s my turn'), ('stall', "don't know what you told her")])
def test_irises_briefing_follows_seraphines_offer(tmp_path, offer, expect):
    lines = h5_service(tmp_path, offer=offer).mission_text(HID, H5)['briefing']['lines']
    assert len(lines) == 3 and expect in lines[1] and lines[2].startswith('The lift needs an override')


def test_escape_route_override_and_five_edges(tmp_path):
    svc = h5_service(tmp_path, offer='refuse', deal='owe')
    sent = []
    out, r = play(svc, 'h5', 0, 0); sent += out
    sent += svc.answer('trust', 'with_iris', r, IRIS)
    out, r = play(svc, 'h5', 5, 100, edges=2); sent += out
    clues = svc.mission_text(HID, H5)
    [wrong] = svc.answer('override', 'VALE', r, IRIS)
    assert 'Seraphine Vale' in json.dumps(wrong)
    svc.clock = lambda: 10 ** 10  # past any wrong-answer cool-down
    sent += svc.answer('override', ' iris ', r, IRIS)
    out, r = play(svc, 'h5', 105, 200, edges=5); sent += out
    [result] = results(sent)
    assert result['route'] == {'id': 'escape', 'label': 'Escape: the lift, with Iris'}
    flags = svc.record(HID).flags
    assert (flags['h5_route'], flags['h5_trust'], flags['h5_release']) == ('escaped', 'iris', 'completed')
    assert 'undercover' in svc.record(HID).chapters and svc.record(HID).completed_at is None
    assert [b['speaker'] for b in result['epilogue']] == ['iris', 'seraphine', 'mira']
    assert "I'm coming with you" in result['epilogue'][0]['lines'][0] and 'Run, darling' in result['epilogue'][1]['lines'][1]
    assert 'wiped the sublevel cameras' in result['epilogue'][2]['lines'][0]
    close = result['chapter_completion']
    assert close['speaker'] == 'seraphine' and 'Chapter 2' in close['lines'][-1]
    assert milestones(sent)[0] == 'start' and 'run:left300' not in milestones(sent)
    keys = {c.get('key') for c in svc.take_cues() if c['kind'] == 'moment'}
    assert {'trust:with_iris', 'run:2', 'override:done'} <= keys


def test_timer_runs_out_then_release_route(tmp_path):
    svc = h5_service(tmp_path, offer='accept', deal='ask')
    sent = []
    out, r = play(svc, 'h5', 0, 0); sent += out
    sent += svc.answer('trust', 'honest', r, IRIS)
    out, r = play(svc, 'h5', 5, 760, edges=1); sent += out
    assert milestones(sent)[:4] == ['start', 'run:left300', 'run:left60', 'run:expired']
    assert not results(sent)
    out, r = play(svc, 'h5', 765, 1210, edges=3); sent += out
    assert not results(sent)  # the protocol is done, the sample is not
    out, r = play(svc, 'h5', 1215, 1225, edges=3, orgasms=1); sent += out
    [result] = results(sent)
    assert result['route']['id'] == 'release'
    assert svc.record(HID).flags['h5_route'] == 'released' and svc.record(HID).flags['h5_trust'] == 'unsure'
    assert [b['speaker'] for b in result['epilogue']] == ['iris', 'seraphine', 'mira']
    assert 'She signed it' in result['epilogue'][0]['lines'][0] and 'decided was mine' in result['epilogue'][1]['lines'][1]
    assert 'burgundy pen' in result['epilogue'][2]['lines'][0]


def test_iris_never_sees_the_override_or_answer_text(tmp_path):
    svc = h5_service(tmp_path, offer='accept')
    play(svc, 'h5', 0, 0)
    _, r = play(svc, 'h5', 5, 100, edges=2)
    svc.answer('trust', 'with_myself', r, IRIS)
    text = svc.model_context(IRIS, r)['text']
    assert 'IRIS' not in text and "I'll get you out too" not in text and 'Answer Iris' not in text
    assert 'never guess it' in text and 'Story so far: They accepted your mother' in text
    n = Book.load().narratives[HID].missions[H5]
    blob = json.dumps(svc.mission_text(HID, H5))
    assert 'when' not in blob and n.director_context not in blob and 'answer_code' not in blob
