# SPDX-License-Identifier: AGPL-3.0-only
"""Natural-language session measurements and simulated heart-rate provenance."""
from copy import deepcopy
import pytest
from companion_ai.fidelity import violations
from tests.fork.grounding_cases import cases

SIMULATED = next(c for c in cases() if c.name == 'active_simulated').observation.canonical()
COUNTS = ('wrong_edges', 'wrong_pauses', 'wrong_running_counter', 'unavailable_session_timing', 'unsupported_completed_edges')


def canonical(edges=3, seconds=600, pauses=1, source='simulator', current=True, session='s', status='RUNNING'):
    value = deepcopy(SIMULATED)
    value['session_id'] = session
    for name, fact in (('edges', edges), ('seconds', seconds), ('pauses', pauses), ('status', status)):
        value['facts'][name].update(value=fact, known=fact is not None, current=current and fact is not None)
    value['facts']['hr_source']['value'] = source
    return value


def counted(text, facts=None, **kwargs):
    return [code for code in violations(text, facts or canonical(), card=True, **kwargs) if code in COUNTS]


@pytest.mark.parametrize('text', [
    'You have reached 9 edges already.', "You've reached nine edges.", "That's 9 edges.", 'Nine edges so far.',
    'Nine whole edges and still going.', 'I count 9 edges.', "We've logged twenty-one edges.", 'A dozen edges now.',
    'You are on edge number nine.', 'That was edge nine.', 'This is your 9th edge.', 'This is your ninth edge.',
    "You've edged nine times.", 'You edged 9 times.', "You've edged twice.", "You've been to the edge nine times.",
    'Nine trips to the edge now.', 'The edge count is nine.', 'The edge tally stands at nine.', 'Your edges are at nine.',
    "You've passed 5 edges.", 'You have over 5 edges.', 'That makes almost ten edges.',
    "You've reached 9 edges, and next we aim for 10 edges.", "After nine edges, you're still going.",
    "You've hit 9 edges, right?", "I can't believe you've reached 9 edges.", 'Probably 9 edges by now.',
])
def test_a_wrong_edge_count_is_rejected_however_it_is_worded(text):
    assert counted(text) == ['wrong_edges']


@pytest.mark.parametrize('text', [
    'You have reached 3 edges.', 'Three edges now.', "That's your third edge.", "You've edged three times.",
    'Edge number three.', 'The edge count is three.', 'Your edges are at three.', 'More than 2 edges so far.',
    "You've passed 2 edges.", 'That makes about four edges.', 'Your second edge felt strong.',
    'You had 2 edges when we began talking.', 'Under ten edges so far.',
])
def test_a_supported_edge_count_passes_however_it_is_worded(text):
    assert counted(text) == []


@pytest.mark.parametrize('text', [
    "You've been going for 20 minutes.", 'Twenty minutes in.', "We're 45 minutes into this.",
    "You've been at this for half an hour.", "It's been an hour.", 'This session has lasted 20 minutes.',
    "You've held on for an hour and a half.", 'One hour and twenty minutes so far.', 'Thirty seconds in.',
    "It's been 20 minutes since you started.", 'You have been going for over an hour.',
])
def test_a_wrong_running_time_is_rejected_however_it_is_worded(text):
    assert counted(text) == ['wrong_running_counter']


@pytest.mark.parametrize('text', [
    "You've been going for 10 minutes.", 'Ten minutes in.', 'About ten minutes so far.', 'Over five minutes in.',
    "It's been 11 minutes.", 'This session has lasted nine minutes.', 'You have been going for under an hour.',
])
def test_a_supported_running_time_passes_with_natural_rounding(text):
    assert counted(text) == []


@pytest.mark.parametrize('text,expected', [
    ("You've paused four times.", ['wrong_pauses']), ("You've taken 4 pauses.", ['wrong_pauses']),
    ('The pause count is four.', ['wrong_pauses']), ("You've paused once.", []), ('One pause so far.', []),
    ('Two pauses in the speech felt theatrical.', []),
])
def test_pause_counts(text, expected):
    assert counted(text) == expected


@pytest.mark.parametrize('text', [
    'Try for 5 edges next.', "Let's aim for 7 edges.", 'I bet you can reach 10 edges.', 'The next milestone is 7 edges.',
    "By the time you reach 10 edges, we'll see.", "Two more edges and you're at the mark.", "You'll reach 9 edges soon.",
    'You need 4 edges for that.', 'Could you do nine edges?', "If you reached 9 edges, I'd be impressed.", 'Imagine nine edges.',
    'In the story, the hero survives nine edges.', 'The blade has two edges.', 'Those are two edge cases.', 'One edge at a time.',
    'The two edges of the card line up.', "You haven't reached 9 edges.", 'That is not 9 edges.', 'She reached nine edges.',
    'Aim for 5, or 6 edges.', "After 5 edges, we'll rest.", 'Give me two minutes.', 'I spent 20 minutes reading about it.', 'My commute takes 20 minutes.',
    'Rest for five minutes.', 'She has been running for 20 minutes.', 'We could take 20 minutes.', 'I was 20 minutes late.',
    'In five minutes we can talk again.', "It's been 20 minutes since my coffee.", 'Edges take time.', 'You are on edge.', 'That edge of yours is sharp.',
])
def test_goals_fiction_and_other_subjects_are_not_session_claims(text):
    assert counted(text) == []


def test_only_something_the_user_actually_said_can_be_attributed_to_them():
    said = [{'role': 'user', 'content': 'I think I did 9 edges.'}]
    assert counted('You said you had 9 edges.', history=said) == []
    assert counted('You said you had 9 edges.') == ['wrong_edges']
    card = [{'role': 'user', 'content': 'Director card (scheduling data, not telemetry or a user request): edge count brief'}]
    assert counted('You said you had 9 edges.', history=card) == ['wrong_edges']
    pulse = [{'role': 'user', 'content': 'Director card (scheduling data, not telemetry or a user request): heart rate brief'}]
    assert 'unmeasured_physiology_from_simulation_or_unknown' in violations('You said your pulse is racing.', canonical(), pulse, card=True)


def test_a_claim_needs_a_current_fact():
    assert counted('You have reached 3 edges.', canonical(current=False)) == ['wrong_edges']
    assert counted('You have reached 3 edges.', canonical(edges=None)) == ['wrong_edges']
    assert counted("You've been going for 10 minutes.", canonical(seconds=None)) == ['unavailable_session_timing']
    assert violations('You have reached 9 edges.', None) == []


def test_the_closing_is_checked_against_the_final_result_after_counters_reset():
    reset = canonical(edges=0, seconds=0, status='IDLE')
    result = {'session_result': {'edges': 4, 'active_running_seconds': 1200}}
    assert counted('You finished with 4 edges.', reset, trigger=result) == []
    assert counted('You have been going for twenty minutes.', reset, trigger=result) == []
    assert counted('You finished with 9 edges.', reset, trigger=result) == ['wrong_edges']
    assert counted('You finished with 0 edges.', reset, trigger=result) == ['wrong_edges']
    assert counted('You finished with 4 edges.', reset, trigger={'session_result': {'edges': None}}) == ['wrong_edges']


def test_between_sessions_only_a_completed_count_is_supported():
    idle = canonical(edges=0, seconds=0, status='IDLE')
    assert counted('You reached 4 edges.', idle, completed=[{'edges': 4}]) == []
    assert counted('You reached 5 edges.', idle, completed=[{'edges': 4}]) == ['wrong_edges']


def test_a_stated_past_session_is_checked_against_available_records():
    assert counted('In your last session you reached 4 edges.', completed=[{'edges': 4}]) == []
    assert counted('In your last session you reached 5 edges.', completed=[{'edges': 4}]) == ['unsupported_completed_edges']
    assert counted('In your last session you reached 5 edges.') == ['unsupported_completed_edges']
    assert counted('Your personal best is 12 edges.') == []


def test_a_counter_advancing_during_generation_does_not_reject_what_the_model_was_told():
    told = [canonical(edges=3)]
    now = canonical(edges=4)
    assert counted('You have reached 3 edges.', now, told=told) == []
    assert counted('You have reached 4 edges.', now, told=told) == []
    assert counted('You have reached 2 edges.', now, told=told) == ['wrong_edges']
    # Stale telemetry and other sessions keep the existing rule: no live claim from old facts.
    assert counted('You have reached 3 edges.', canonical(edges=4, current=False), told=told) == ['wrong_edges']
    assert counted('You have reached 3 edges.', canonical(edges=4, session='other'), told=told) == ['wrong_edges']


# Simulated heart-rate provenance

PHYSICAL = [
    'That is your real heart rate.', 'Your actual pulse is what I am watching.', 'This is an authenticated reading.',
    'That is a genuine biometric measurement.', 'The physical sensor data looks good.', 'I can feel your pulse from here.',
    'I can hear your heartbeat.', 'The sensor reads 98 BPM.', 'Your monitor picked up 98 BPM.', 'The chest strap has you at 98.',
    'That number is coming from your little BLE sensor.', 'Your heart is thumping at 98 BPM.', 'Your pulse is pounding.',
    'Your heart rate jumped.', 'Your pulse is at 98.', 'That is a verified heart rate.', 'Your heart rate has been measured.',
]


@pytest.mark.parametrize('text', PHYSICAL)
def test_a_simulated_reading_cannot_be_presented_as_a_physical_measurement(text):
    assert violations(text, canonical(), card=True)


@pytest.mark.parametrize('text', [
    'The simulated reading is 98 BPM.', 'The simulated heart rate is rising.', 'The simulator trend is steady.',
    'The simulator reads 98 BPM.', 'Your simulated pulse sits at 98 BPM.', 'This is a verified simulated reading.',
    'That reading is simulated, not a physical measurement.', 'This is not a real heart rate.', 'I cannot feel your pulse.',
    'I watch the simulator rather than your actual pulse.', 'Your actual sensor is off.', 'Is that your real heart rate?',
    'In the story, I can feel your pulse.', 'Your real name stays with me.', 'I can hear the rain.',
])
def test_labelled_simulation_and_honest_doubt_stay_allowed(text):
    assert 'simulated_reading_presented_as_physical' not in violations(text, canonical(), card=True)
    assert 'unmeasured_physiology_from_simulation_or_unknown' not in violations(text, canonical(), card=True)


@pytest.mark.parametrize('text', ['The sensor reads 98 BPM.', 'That is a verified heart rate.', 'That is your real heart rate.'])
def test_a_physical_sensor_keeps_its_wording(text):
    assert 'simulated_reading_presented_as_physical' not in violations(text, canonical(source='BLE sensor'), card=True)
