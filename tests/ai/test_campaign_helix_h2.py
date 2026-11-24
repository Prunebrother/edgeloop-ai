# SPDX-License-Identifier: AGPL-3.0-only
"""H2 Shadow Evaluation (HELIX-051): the shipped definition played through the campaign service, no live model."""
import json
import pytest
from companion_ai.campaign import Book
from tests.ai.test_campaign import results
from tests.ai.test_campaign_chapter2 import tick
from tests.ai.test_campaign_helix_h1 import HID, H1, IRIS, h1_service, play as play_h1

H2 = 'h2_shadow_evaluation'
MIRA = 'mira-narrative-f29-v017:latest'


def finish_h1(tmp_path, cover='defector'):
    svc = h1_service(tmp_path)
    play_h1(svc, 0, 300, 70)
    _, r = play_h1(svc, 305, 605, 90)
    svc.answer('cover', cover, r, IRIS)
    svc.answer('badge', 'subject', r, IRIS)
    out, _ = play_h1(svc, 610, 910, 110, edges=3)
    assert results(out)
    svc.take_cues(); svc.take_directives()
    return svc


def h2_service(tmp_path, cover='defector'):
    svc = finish_h1(tmp_path, cover)
    svc.identity = lambda model: {IRIS: 'iris', MIRA: 'mira'}.get(model)
    svc.start(HID, H2)
    return svc


def play(svc, sid, start, end, edges=0, orgasms=0, intensity=100):
    out, r = [], None
    for t in range(start, end + 1, 5):
        r = tick(sid, t, intensity=intensity, edges=edges, orgasms=orgasms)
        out += svc.observe(r, [], MIRA)
    return out, r


def run(svc, sid, recognised, offer, orgasm):
    """Rapport and Pressure (0-780 s), both choices, then Verdict with the edges (and the optional orgasm)."""
    sent = []
    out, r = play(svc, sid, 0, 10); sent += out
    sent += svc.answer('recognised', recognised, r, MIRA)
    out, r = play(svc, sid, 15, 790, edges=3); sent += out
    sent += svc.answer('offer', offer, r, MIRA)
    out, r = play(svc, sid, 795, 1095, edges=6, orgasms=1 if orgasm else 0); sent += out
    return sent


def test_shipped_h2_definition():
    m = Book.load().campaign(HID).mission(H2)
    assert m.companion == 'mira' and m.prerequisites == [H1]
    assert [o.id for o in m.objectives] == ['hr', 'toy', 'start', 'evaluation', 'edges', 'recognised', 'offer', 'sample']
    seq = m.objectives[3]
    assert [(s.id, s.seconds, s.intensity) for s in seq.stages] == [('rapport', 300, None), ('pressure', 480, None), ('verdict', 300, None)]
    assert m.objectives[4].count == 6
    assert (m.objectives[5].after_stage, m.objectives[6].after_stage) == ('evaluation:rapport', 'evaluation:verdict')
    assert m.objectives[7].optional and m.objectives[7].type == 'orgasm_count'
    # Mira steers the intensity herself (author decision 1a): intensity only, not directed by the campaign.
    assert m.settings_control.allowed == ['intensity'] and not m.settings_control.directed
    n = Book.load().narratives[HID].missions[H2]
    assert set(n.milestones) == {'start'} and 'start' not in n.directions
    assert len(n.director_context) <= 400 and len(n.story_so_far) == 3 and n.story_so_far[-1].when is None
    assert [e.when.eq for e in n.epilogue] == ['owed', 'refused', 'undecided']


def test_h2_full_run_with_the_optional_orgasm(tmp_path):
    svc = h2_service(tmp_path)
    assert svc.allowed_settings() == frozenset({'intensity'}) and not svc.settings_directed()
    # Saved story reaches Mira's brief as one line: H1's cover answer (defector).
    brief = svc.model_context(MIRA, tick('h2', 0))['text']
    assert 'Story so far: On intake they told Iris they used to work for Asterion' in brief
    sent = run(svc, 'h2', 'turned', 'owe', orgasm=True)
    [result] = results(sent)
    flags = svc.record(HID).flags
    assert flags['h2_evaluation'] == 'completed' and flags['h2_recognised'] == 'turned' and flags['h2_mira_deal'] == 'owed'
    assert flags['h1_cover'] == 'defector'
    assert [e['lines'][0][:13] for e in result['epilogue']] == ["Mira's report"]
    assert 'Nothing unusual' in result['epilogue'][0]['lines'][0]
    assert [m['key'] for m in sent if m['type'] == 'mission_milestone'] == ['start']
    keys = {c.get('key') for c in svc.take_cues() if c['kind'] == 'moment'}
    assert {'evaluation:pressure', 'evaluation:verdict', 'recognised:turned', 'offer:owe', 'edges:done', 'sample:done', 'evaluation:done'} <= keys
    assert svc.record(HID).records[f'{H2}.sample'] == 1
    # Directions, the director context and story-so-far rules never reach the browser.
    blob = json.dumps(sent)
    n = Book.load().narratives[HID].missions[H2]
    assert not any(t in blob for t in n.directions.values())
    assert n.director_context not in blob and not any(rule.text in blob for rule in n.story_so_far)


def test_h2_completes_without_the_optional_orgasm_and_epilogue_follows_the_offer(tmp_path):
    svc = h2_service(tmp_path, cover='volunteer')
    assert 'Story so far: On intake they said they answered' in svc.model_context(MIRA, tick('h2', 0))['text']
    sent = run(svc, 'h2', 'denied', 'truth', orgasm=False)
    [result] = results(sent)
    assert 'protecting something' in result['epilogue'][0]['lines'][0] and len(result['epilogue']) == 1
    assert svc.record(HID).flags['h2_mira_deal'] == 'refused'


def test_h2_offer_waits_for_the_verdict_stage(tmp_path):
    svc = h2_service(tmp_path)
    _, r = play(svc, 'h2', 0, 400)
    with pytest.raises(ValueError, match='not available before its stage'):
        svc.answer('offer', 'owe', r, MIRA)
    svc.answer('recognised', 'admitted', r, MIRA)  # the first question is open from the start


def test_h2_replay_keeps_first_flags_while_its_text_follows_the_replay(tmp_path):
    svc = h2_service(tmp_path)
    run(svc, 'h2', 'admitted', 'owe', orgasm=False)
    svc.start(HID, H2)
    [result] = results(run(svc, 'h2b', 'turned', 'ask', orgasm=False))
    assert result['replay'] and 'never late' in result['epilogue'][0]['lines'][0]
    flags = svc.record(HID).flags
    assert flags['h2_mira_deal'] == 'owed' and flags['h2_recognised'] == 'admitted'


def test_a_chosen_answer_reaches_the_brief_as_the_participants_words(tmp_path):
    """Live checks 2026-11-20: Mira repeated the answer's words whenever the brief quoted them, attributed or not."""
    svc = h2_service(tmp_path)
    _, r = play(svc, 'h2', 0, 10)
    assert 'a question for the participant is waiting' in svc.model_context(MIRA, r)['text']
    svc.answer('recognised', 'denied', r, MIRA)
    text = svc.model_context(MIRA, r)['text']
    assert 'a question for the participant: answered' in text and 'Answer Mira' not in text
    assert 'confused with someone else' not in text and 'Choice: ' not in text


def test_the_completion_brief_does_not_quote_the_answers_either(tmp_path):
    svc = h2_service(tmp_path)
    run(svc, 'h2', 'denied', 'truth', orgasm=False)
    text = svc.model_context(MIRA, tick('h2', 1100))['text']
    assert 'mission is complete' in text and 'The participant answered a question in this mission.' in text and 'Answer Mira' not in text
    assert 'nothing to hide' not in text and 'confused with someone else' not in text
