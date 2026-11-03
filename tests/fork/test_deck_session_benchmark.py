# SPDX-License-Identifier: AGPL-3.0-only
"""Invariants of the deterministic Event Deck session, flag on and flag off."""
import asyncio
import pytest
from tests.fork.deck_session_benchmark import STOP,evaluate


@pytest.fixture(scope='module')
def result():
    return asyncio.run(evaluate())


def test_the_benchmark_is_deterministic(result):
    assert asyncio.run(evaluate()) == result


@pytest.mark.parametrize('arm', ['off', 'on'])
def test_both_arms_stay_within_the_harness_limits(result, arm):
    row = result[arm]
    assert row['maximum_parallel_inference'] == 1
    assert row['errors'] == 0 and row['thinking_off'] and not row['hardware_tools_exposed']
    assert row['commentary_after_stop'] == 0 and row['speech_while_paused'] == 0
    assert row['user_preempted_a_generating_turn']


def test_flag_off_has_no_proactive_scheduler(result):
    # The legacy idle selector and event reactions are retired: with the deck off nothing is unsolicited.
    row = result['off']
    assert row['legacy_idle_turns'] == 0 and row['first_unsolicited'] is None
    assert not row['legacy_reactions_by_kind'].get('edge')
    assert not [turn for turn in row['turn_log'] if turn['lane'] or turn['card']]


def test_flag_on_replaces_legacy_initiative_and_duplicate_reactions(result):
    row = result['on']
    assert row['legacy_idle_turns'] == 0
    assert row['legacy_reactions_by_kind'] == {'experience_changed': 1}
    assert row['duplicate_occurrences_suppressed'] > 0


def test_flag_on_priority_order(result):
    row = result['on']
    assert row['first_unsolicited'] == 'session_start' and row['opening_deliveries'] == 1
    assert row['after_edge_order'] == ['mission', 'narrative', 'normal']
    log = [turn for turn in row['turn_log'] if turn['source'] == 'event' and turn['delivered']]
    assert log[0]['lane'] == 'session_start' and log[-1]['lane'] == 'session_end'
    assert log[0]['at'] == min(turn['at'] for turn in log)


def test_flag_on_has_no_duplicate_milestones(result):
    row = result['on']
    assert row['mission_deliveries'] == {'edge-card': 1, 'ten-minute-card': 1}
    assert row['duplicate_milestones'] == 0


def test_flag_on_ends_with_one_closing_from_the_final_snapshot_and_nothing_else(result):
    row = result['on']
    assert row['closing_reactions'] == 1 and row['closing_used_final_snapshot']
    assert row['commentary_after_stop'] == 0
    assert 2 <= row['closing_seconds_after_stop'] <= 2.5  # The safety notice's hold, then at once.
    after = [turn for turn in row['turn_log'] if turn['at'] >= STOP and turn['source'] == 'event']
    assert [turn['lane'] for turn in after] == ['session_end']


def test_flag_on_is_silent_in_protective_states(result):
    assert result['on']['speech_during_protective_state'] == 0


def test_flag_on_cadence_is_exactly_the_countdown_unless_a_user_or_block_holds_it(result):
    row = result['on']
    assert len(row['quiet_gaps']) >= 20 and row['quiet_gaps_outside_tolerance'] == []
    assert row['normal_within_hold_after_user'] == 0
    assert row['held_gaps'] and all(gap > 10.25 for gap in row['held_gaps'])


def test_scoped_memory_stays_isolated_between_exact_models(result):
    row = result['isolation']
    assert row['distinct_decks'] and row['same_deck_on_return']
    assert (row['nova_identity'], row['evelyn_identity']) == ('nova', 'evelyn')
    assert row['evelyn_turns'] > 0 and row['models_seen_after_switch'] == ['evelyn:latest']
    assert row['evelyn_saw_nova_cards'] == 0 and row['nova_saw_evelyn_cards'] == 0
    assert row['nova_dialogue_in_evelyn_prompts'] == 0 and row['evelyn_dialogue_in_nova_history'] == 0
    assert row['history_on_switch'] == 0 and row['nova_history_restored']
    assert row['nova_story_on_switch'] == 0 and row['nova_story_memory_restored']
    assert row['maximum_parallel_inference'] == 1


def test_routine_cards_stay_out_of_story_memory_while_story_cards_enter_it(result):
    row = result['isolation']
    assert row['routine_cards_measured'] > 0 and row['routine_cards_in_nova_story_memory'] == 0
    assert row['story_cards_delivered'] == 1 and row['story_cards_in_nova_story_memory'] == 1
