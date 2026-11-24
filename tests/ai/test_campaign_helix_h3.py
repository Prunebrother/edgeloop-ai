# SPDX-License-Identifier: AGPL-3.0-only
"""H3 Extraction Assessment (HELIX-052): the shipped definition played through the campaign service, no live model."""
import json
from companion_ai.campaign import Book
from tests.ai.test_campaign import results
from tests.ai.test_campaign_chapter2 import tick
from tests.ai.test_campaign_helix_h1 import HID, IRIS
from tests.ai.test_campaign_helix_h2 import H2, MIRA, h2_service, run as run_h2

H3 = 'h3_extraction_assessment'
VEX = 'vex9-narrative-f29-v016:latest'


def h3_service(tmp_path, cover='defector', offer='owe'):
    svc = h2_service(tmp_path, cover)
    assert results(run_h2(svc, 'h2', 'turned', offer, orgasm=False))
    svc.identity = lambda model: {IRIS: 'iris', MIRA: 'mira', VEX: 'vex9'}.get(model)
    svc.take_cues(); svc.take_directives()
    svc.start(HID, H3)
    return svc


def play(svc, sid, start, end, edges=0, orgasms=0, intensity=100):
    out, r = [], None
    for t in range(start, end + 1, 5):
        r = tick(sid, t, intensity=intensity, edges=edges, orgasms=orgasms)
        out += svc.observe(r, [], VEX)
    return out, r


def test_shipped_h3_definition():
    m = Book.load().campaign(HID).mission(H3)
    assert m.companion == 'vex9' and m.prerequisites == [H2] and m.difficulty == 'challenge'
    assert [o.id for o in m.objectives] == ['hr', 'toy', 'start', 'protocol', 'edges', 'discrepancy', 'sample', 'ultra']
    seq = m.objectives[3]
    assert [(s.id, s.seconds, s.raise_to, s.set_to, s.intensity) for s in seq.stages] == [
        ('calibration', 240, 80, True, None), ('stimulation', 360, 100, True, None),
        ('escalation', 360, 115, True, None), ('extraction', 240, 125, True, None)]
    edges, sample, ultra = m.objectives[4], m.objectives[6], m.objectives[7]
    assert (edges.count, edges.milestones) == (8, [3, 6])
    assert (sample.count, sample.after, sample.optional) == (1, 'edges', False)
    assert (ultra.count, ultra.after, ultra.optional) == (2, 'edges', True)
    assert m.objectives[5].after_stage == 'protocol:calibration'
    assert not any(o.type == 'puzzle_solved' for o in m.objectives)  # author 2026-11-20: no puzzle
    assert m.settings_control.allowed == ['intensity'] and m.settings_control.directed
    n = Book.load().narratives[HID].missions[H3]
    assert set(n.milestones) == {'start'} and 'start' not in n.directions
    assert len(n.director_context) <= 400 and len(n.story_so_far) == 3


def test_h3_full_run_ultra_and_mira_epilogue(tmp_path):
    svc = h3_service(tmp_path, offer='owe')
    brief = svc.model_context(VEX, tick('h3', 0))['text']
    assert 'Story so far: Their intake file, signed by Iris' in brief
    sent = []
    out, r = play(svc, 'h3', 0, 0, intensity=60); sent += out
    [floor] = [d for d in svc.take_directives() if d['key'] == 'protocol:calibration']
    assert floor['scripted'] and floor['fallback']['value'] == 30  # 80 %, sent by the protocol, not asked of VEX-9
    out, r = play(svc, 'h3', 5, 245, edges=3, intensity=60); sent += out
    sent += svc.answer('discrepancy', 'instruments', r, VEX)
    out, r = play(svc, 'h3', 250, 960, edges=8, intensity=70); sent += out
    out, r = play(svc, 'h3', 965, 1000, edges=8, orgasms=1, intensity=70); sent += out
    assert not results(sent)  # the protocol is still running
    out, r = play(svc, 'h3', 1005, 1205, edges=8, orgasms=2, intensity=70); sent += out
    [result] = results(sent)
    flags = svc.record(HID).flags
    assert flags['h3_assessment'] == 'completed' and flags['h3_discrepancy'] == 'blamed_instruments'
    assert [b['lines'][0] for b in result['epilogue']] == ["Mira, alone in the data centre, deletes one line from VEX-9's log. 'That's twice you owe me.'"]
    keys = {c.get('key') for c in svc.take_cues() if c['kind'] == 'moment'}
    assert {'edges:3', 'edges:6', 'edges:done', 'sample:done', 'ultra:done', 'discrepancy:instruments',
            'protocol:stimulation', 'protocol:escalation', 'protocol:extraction'} <= keys
    assert svc.record(HID).records[f'{H3}.ultra'] == 2
    blob = json.dumps(sent)
    n = Book.load().narratives[HID].missions[H3]
    assert not any(t in blob for t in n.directions.values()) and n.director_context not in blob


def test_an_orgasm_before_the_eighth_edge_is_not_the_sample(tmp_path):
    svc = h3_service(tmp_path, offer='truth')
    play(svc, 'h3', 0, 0)
    _, r = play(svc, 'h3', 5, 245, edges=5, orgasms=1)
    svc.answer('discrepancy', 'silent', r, VEX)
    out, _ = play(svc, 'h3', 250, 1205, edges=8, orgasms=1)
    assert not results(out)  # protocol and edges done, but no sample after the edges yet
    out, _ = play(svc, 'h3', 1210, 1215, edges=8, orgasms=2)
    [result] = results(out)  # the sample right after the protocol completes it at once
    assert 'leaves it exactly where it is' in result['epilogue'][0]['lines'][0]
    assert svc.record(HID).flags['h3_discrepancy'] == 'refused'


def test_vex_never_sees_the_answer_text(tmp_path):
    svc = h3_service(tmp_path)
    _, r = play(svc, 'h3', 0, 245)
    svc.answer('discrepancy', 'file', r, VEX)
    text = svc.model_context(VEX, r)['text']
    assert 'a question for the participant: answered' in text and 'Answer VEX-9' not in text and 'Paperwork usually is' not in text
