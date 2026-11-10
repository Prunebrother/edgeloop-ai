"""Finishing phase: while Force Orgasm is on, cards stop pushing for more and speak to the finish.
Found in AutoMode_Simulation_20261110: after Force Orgasm, cards still said "Ready for the next ten?"."""
import pytest
from companion_ai.context_compiler import PHASE_FACTS
from companion_ai.event_deck import session_phase
from tests.ai.test_event_deck_content import DEFINITION, context, deck, play_only, prompt, service

FINISH = {c.id for c in DEFINITION.normal if c.eligibility.phases == ['finishing']}


@pytest.mark.parametrize('report,phase', [
    ({'status': 'RUNNING', 'details': {'orgasm_mode': True}}, 'finishing'),
    ({'status': 'RAMPDOWN', 'details': {'orgasm_mode': True}}, 'finishing'),
    ({'status': 'RUNNING', 'details': {'orgasm_mode': False}}, 'building'),
    ({'status': 'IDLE', 'details': {'orgasm_mode': True}}, 'building'),
    ({'status': 'RUNNING', 'details': {}}, 'building'),
    (None, 'building'),
])
def test_phase_comes_from_force_orgasm_in_the_snapshot(report, phase):
    assert session_phase(report) == phase


@pytest.mark.parametrize('identity', ['nova', 'evelyn', 'daisy', 'celeste'])
def test_only_finish_cards_are_eligible_while_finishing(identity):
    target = deck(identity)
    ctx = context(edges=9, seconds=560, phase='finishing')
    eligible = {c.id for c in DEFINITION.normal if c.audience in {'shared', identity} and target._eligible(c, ctx)}
    assert eligible == {'finish-urge', 'finish-permission', identity + '-finish'}
    building = {c.id for c in DEFINITION.normal if target._eligible(c, context(edges=9, seconds=560))}
    assert not building & FINISH


def test_milestones_still_play_while_finishing():
    target = deck('nova')
    assert all(target._eligible(step, context(edges=10, phase='finishing')) for seq in DEFINITION.sequences for step in seq.steps)


async def test_a_milestone_while_finishing_is_told_about_the_finish():
    r, s, wire, _ = await service(edges=3, seconds=560, orgasm_mode=True)
    milestone = next(step for seq in DEFINITION.sequences for step in seq.steps if step.id == 'edges-3-reached')
    s.deck()._start_done = True; s.deck()._counter_baseline = {'edges': 0, 'seconds': 0}
    s.pump(); await s.task
    current = prompt(wire)
    assert milestone.occasion in current and PHASE_FACTS['finishing'] in current


@pytest.mark.parametrize('orgasm_mode', [False, True])
async def test_the_finish_line_is_only_sent_while_finishing(orgasm_mode):
    r, s, wire, _ = await service(edges=3, seconds=300, orgasm_mode=orgasm_mode)
    play_only(s, 'finish-urge' if orgasm_mode else 'general-remark')
    s.pump(); await s.task
    assert (PHASE_FACTS['finishing'] in prompt(wire)) is orgasm_mode
