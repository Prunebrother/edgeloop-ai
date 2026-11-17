# SPDX-License-Identifier: AGPL-3.0-only
"""Reproductions from the Codex review of Chapter 3 (a948c59..c29f67d), kept as regression tests."""
import json
import subprocess
from pathlib import Path
import pytest
from tests.ai.test_campaign import CID, MODEL, run, results, service
from tests.ai.test_campaign_chapter2 import seed, tick, frames, milestones
from tests.ai.test_campaign_review_ch2 import control_for
from tests.ai.test_settings_control import Adapter, outcome
from companion_ai.campaign import PROGRESS_FILE

REPO = Path(__file__).resolve().parents[2]


def ui(messages, key=None):
    result = subprocess.run(['node', str(REPO / 'tests/fork/campaign_ui_routing.mjs')],
                            input=json.dumps({'repo': str(REPO), 'messages': messages, 'key': key}),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize('updates', [{'status': 'PAUSED'}, {'status': 'RAMPDOWN'}, {'sim': True}, {'toy': False}])
def test_puzzle_answers_require_current_running_eligible_session(tmp_path, updates):
    svc = seed(tmp_path, 'ghost_in_the_machine')
    run(svc, 'nova', tick('n', 0))
    r = tick('n', 1, **updates)
    run(svc, 'nova', r)
    with pytest.raises(ValueError):
        svc.answer('log', 'internal', r, MODEL['nova'])
    assert 'log' not in svc.attempt.solved


@pytest.mark.parametrize('leave', ['abandon', 'another_mission'])
def test_solved_puzzles_survive_leaving_and_returning_to_mission(tmp_path, leave):
    svc = seed(tmp_path, 'ghost_in_the_machine')
    run(svc, 'nova', tick('n', 0))
    svc.answer('log', 'internal', tick('n', 1), MODEL['nova'])
    run(svc, 'nova', tick('n', 1, status='IDLE'))
    if leave == 'abandon':
        svc.abandon()
    else:
        svc.start(CID, 'the_anomaly')
    svc.start(CID, 'ghost_in_the_machine')
    again = service(tmp_path)
    assert 'log' in again.attempt.solved


def test_completing_the_mission_clears_its_saved_puzzles_for_a_replay(tmp_path):
    svc = seed(tmp_path, 'ghost_in_the_machine')
    run(svc, 'nova', tick('n', 0))
    for oid, option in (('log', 'internal'), ('money', 'helix'), ('record', 'inside')):
        out = svc.answer(oid, option, tick('n', 1), MODEL['nova'])
    assert results(out)
    assert json.loads((tmp_path / PROGRESS_FILE).read_text())['campaigns'][CID]['solved'] == {}
    svc.start(CID, 'ghost_in_the_machine')
    assert svc.attempt.solved == set()


@pytest.mark.asyncio
async def test_mira_cannot_re_raise_mid_stage_through_chat_after_player_lowers(tmp_path):
    svc = seed(tmp_path, 'midnight_intruder')
    first = tick('m', 0, intensity=90)
    run(svc, 'mira', first)
    [directive] = svc.take_directives()
    control = control_for(svc)
    request = await control.run(Adapter('{"change":"none"}'), first, MODEL['mira'], lambda message: None, directive=directive)
    control.outcome(outcome(id=request['id'], setting='intensity', **{'from': 40, 'to': 50}))
    run(svc, 'mira', *frames('m', 1, 121, intensity=100))
    lowered = tick('m', 122, intensity=60)
    lowered['details']['ai_settings'] = {'enabled': True, 'revoked': False, 'applied': 1, 'pacing': 'sometimes'}
    run(svc, 'mira', lowered)
    assert svc.take_directives() == []
    sent = []
    await control.run(Adapter('{"change":"intensity","value":50,"reason":"Discovery calls for 100%."}'),
        lowered, MODEL['mira'], sent.append, user_text='Make it softer please')
    assert sent == []


def test_the_next_stage_still_gets_its_raise_after_the_player_lowered_it(tmp_path):
    svc = seed(tmp_path, 'midnight_intruder')
    run(svc, 'mira', *frames('m', 0, 300, intensity=100), *frames('m', 305, 600, intensity=60))
    [step] = svc.take_directives()
    assert step['key'] == 'encounter:deception' and step['fallback']['value'] == 60


def test_space_on_puzzle_button_does_not_reach_engine_shortcut(tmp_path):
    svc = seed(tmp_path, 'ghost_in_the_machine')
    r = tick('n', 0)
    run(svc, 'nova', r)
    for key in ('Space', 'Enter'):
        assert ui([svc.state(r, MODEL['nova'])], key=key)['engineActions'] == []


def test_expiry_line_survives_same_frame_session_end(tmp_path):
    svc = seed(tmp_path, 'the_empty_vault')
    run(svc, 'daisy', tick('v', 0), tick('v', 900))
    out = svc.observe(tick('v', 901, status='IDLE', terminal_outcome='premature_release'), ['came_early'], MODEL['daisy'])
    assert not results(out)
    assert milestones(out) == ['delivery:expired']


def test_came_early_at_exact_deadline_counts(tmp_path):
    svc = seed(tmp_path, 'the_empty_vault')
    run(svc, 'daisy', tick('v', 0), tick('v', 899))
    assert results(svc.observe(tick('v', 900, status='IDLE', terminal_outcome='premature_release'), ['came_early'], MODEL['daisy']))


def test_countdown_jump_warnings_are_once_and_goal_prevents_expiry(tmp_path):
    svc = seed(tmp_path, 'the_empty_vault')
    run(svc, 'daisy', tick('v', 0))
    assert milestones(run(svc, 'daisy', tick('v', 850))) == ['delivery:left300', 'delivery:left60']
    assert milestones(run(svc, 'daisy', tick('v', 850))) == []
    assert results(run(svc, 'daisy', tick('v', 851, orgasms=1)))
    assert run(svc, 'daisy', tick('v', 1000, orgasms=1)) == []


# ---- Second retest (Codex): Mira's named stages are separate clocks

def test_mira_stage_claims_are_checked_against_the_named_stage(tmp_path):
    from tests.fork.event_replay import Replay
    from companion_ai.fidelity import violations
    replay = Replay()
    sid = replay.state['session_id']
    svc = seed(tmp_path, 'midnight_intruder')
    run(svc, 'mira', *frames(sid, 0, 600, intensity=100), tick(sid, 605, intensity=110))
    replay.state.update(seconds=605, intensity=110)
    replay.step(None, seconds=0)
    canonical = replay.observation.summary()['canonical_session']
    clocks = svc.model_context(MODEL['mira'], replay.observation.report)['durations']
    wrong = lambda text: 'wrong_running_counter' in violations(text, canonical, card=True, durations=clocks)
    assert not wrong('Ten minutes of active time in Discovery.')
    assert wrong('Ten minutes of active time in Deception.')
    assert wrong('Ten minutes of active time in this stage.')
    assert not wrong('Ten minutes into the encounter.')
