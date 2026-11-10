# SPDX-License-Identifier: AGPL-3.0-only
"""Deterministic Phase 1A deck tests: time is passed in, with no inference or hardware."""
import ast
from pathlib import Path
import pytest
from pydantic import ValidationError
import companion_ai.event_deck as module
from companion_ai.event_deck import (Card, DeckContext, DeckDefinition, DeckLifecycleError, DeckRegistry, DeckSettings,
                                     Eligibility, EventDeck, SessionResult, Sequence, SequenceTrigger, load_definition, shuffled)

SCOPE = 'ollama:http://127.0.0.1:11435:evelyn-narrative-f29-v013:latest'
OTHER_SCOPE = 'ollama:http://127.0.0.1:11435:daisy-narrative-f29-v014:latest'
SESSION = 'session-a'
EPOCH = 'a' * 32
RESULT = {'active_running_seconds': 600, 'last_verified_running_ticks': 600, 'edges': 4, 'experience': 'classic',
          'goal': 'tease', 'termination': 'manual_stop', 'completion_status': 'unknown', 'completion_source': None,
          'completeness': 'final_counter_captured', 'orgasms': None}


def card(card_id, kind='normal', **values):
    return Card(id=card_id, kind=kind, intent=values.pop('intent', 'comment'), brief='Brief for ' + card_id, **values)


def mission(sequence_id='first-edges', *step_ids, **trigger):
    steps = [card(step, 'mission') for step in (step_ids or (sequence_id + '-1',))]
    return Sequence(id=sequence_id, lane='mission', trigger=SequenceTrigger(**(trigger or {'min_edges': 2})), steps=steps)


def narrative(sequence_id='story', *step_ids, kinds=('edge',)):
    steps = [card(step, 'narrative', memory='story') for step in (step_ids or (sequence_id + '-1',))]
    return Sequence(id=sequence_id, lane='narrative', trigger=SequenceTrigger(event_kinds=list(kinds)), steps=steps)


def definition(normal=None, sequences=()):
    if normal is None:
        normal = [card(f'n{i}') for i in range(5)]
    return DeckDefinition(session_start=[card('start', 'session_start')], session_end=[card('end', 'session_end')],
                          normal=list(normal), sequences=list(sequences))


def settings(**values):
    return DeckSettings(**({'enabled': True} | values))


def deck(*, normal=None, sequences=(), identity='evelyn', scope=SCOPE, session=SESSION, **values):
    return EventDeck(definition(normal, sequences), scope, identity, session, EPOCH, settings(**values))


def context(**values):
    return DeckContext(**({'session_id': SESSION, 'status': 'RUNNING'} | values))


def deliver(target, play, now):
    assert target.transition(play.id, 'accepted', now)
    assert target.transition(play.id, 'generated', now)
    assert target.transition(play.id, 'delivered', now)


def outcome(target, play, status, now):
    if status not in {'deferred', 'cancelled'}:
        target.transition(play.id, 'accepted', now)
    target.transition(play.id, status, now)


def started(**values):
    """A deck whose mandatory start card has been delivered, at time 0, with no countdown."""
    target = deck(**({'countdown_seconds': 0, 'mission_spacing_seconds': 0} | values))
    deliver(target, target.next_play(context(), 0).play, 0)
    return target


def draw_all(target, count, now=0):
    cards = []
    for _ in range(count):
        play = target.next_play(context(), now).play
        cards.append(play.card.id)
        deliver(target, play, now)
    return cards


# Schema

def test_feature_flag_is_on_by_default_and_a_disabled_deck_proposes_nothing():
    assert DeckSettings().enabled is True
    target = EventDeck(definition(), SCOPE, 'evelyn', SESSION, EPOCH, DeckSettings(enabled=False))
    assert target.next_play(context(), 0) == (None, 'deck_disabled')


def test_cards_have_no_weights():
    with pytest.raises(ValidationError):
        Card(id='a', kind='normal', intent='x', brief='y', weight=2)


def test_routine_start_and_closing_cards_cannot_write_story_memory():
    for kind in ('normal', 'session_start', 'session_end'):
        with pytest.raises(ValidationError):
            card('a', kind, memory='story')
    assert card('a', 'narrative', memory='story').memory == 'story'


def test_narrative_sequences_require_verified_events():
    with pytest.raises(ValidationError):
        Sequence(id='s', lane='narrative', trigger=SequenceTrigger(min_edges=1), steps=[card('a', 'narrative')])


@pytest.mark.parametrize('values', [{}, {'event_kinds': ['edge'], 'min_edges': 1}])
def test_a_trigger_has_exactly_one_style(values):
    with pytest.raises(ValidationError):
        SequenceTrigger(**values)


def test_definition_rejects_duplicates_and_a_missing_shared_mandatory_card():
    with pytest.raises(ValidationError):
        definition(normal=[card('dup'), card('dup')])
    with pytest.raises(ValidationError):
        DeckDefinition(session_start=[card('s', 'session_start', audience='evelyn')], session_end=[card('e', 'session_end')])
    with pytest.raises(ValidationError):
        DeckDefinition(session_start=[card('s', 'normal')], session_end=[card('e', 'session_end')])


def test_load_definition_fails_closed_and_accepts_json_shaped_input():
    assert load_definition({'schema_version': 2}) == (None, 'Invalid or unsupported event deck definition; deck unavailable.')
    loaded, error = load_definition(definition(sequences=[mission()]).model_dump())
    assert error is None and loaded == definition(sequences=[mission()])


def test_module_is_cpu_only():
    tree = ast.parse(Path(module.__file__).read_text())
    imported = {node.module if isinstance(node, ast.ImportFrom) else alias.name
                for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names}
    assert imported == {'collections', 'dataclasses', 'hashlib', 'typing', 'pydantic', 'models'}


# Seeded shuffle and sequential drawing

def test_shuffle_matches_a_fixed_order_and_ignores_declaration_order():
    ids = [f'n{i}' for i in range(5)]
    assert shuffled(ids, 'seed') == GOLDEN_ORDER
    assert shuffled(list(reversed(ids)), 'seed') == GOLDEN_ORDER


def test_same_seed_replays_and_another_session_or_scope_differs():
    def run(scope=SCOPE, session=SESSION):
        target = deck(normal=[card(f'n{i}') for i in range(24)], scope=scope, session=session, countdown_seconds=0)
        ctx = context(session_id=session)
        drawn = []
        for _ in range(25):
            play = target.next_play(ctx, 0).play
            drawn.append(play.card.id)
            deliver(target, play, 0)
        return drawn
    assert run() == run()
    assert run() != run(session='session-b')
    assert run() != run(scope=OTHER_SCOPE)


def test_each_card_plays_once_per_cycle_and_never_repeats_across_the_boundary():
    for session in ('s1', 's2', 's3', 's4', 's5', 's6'):
        target = deck(session=session, countdown_seconds=0)
        ctx = context(session_id=session)
        deliver(target, target.next_play(ctx, 0).play, 0)
        drawn = []
        for _ in range(15):
            play = target.next_play(ctx, 0).play
            drawn.append(play.card.id)
            deliver(target, play, 0)
        for start in range(0, 15, 5):
            assert sorted(drawn[start:start + 5]) == [f'n{i}' for i in range(5)]
        assert all(left != right for left, right in zip(drawn, drawn[1:]))


def test_one_deck_mixes_shared_and_own_character_cards_only():
    normal = [card('shared-a'), card('shared-b'), card('evelyn-a', audience='evelyn'), card('daisy-a', audience='daisy')]
    assert sorted(draw_all(started(normal=normal), 3)) == ['evelyn-a', 'shared-a', 'shared-b']


def test_character_start_and_closing_cards_override_the_shared_ones():
    custom = DeckDefinition(session_start=[card('start', 'session_start'), card('start-e', 'session_start', audience='evelyn')],
                            session_end=[card('end', 'session_end'), card('end-e', 'session_end', audience='evelyn')])
    evelyn = EventDeck(custom, SCOPE, 'evelyn', SESSION, EPOCH, settings())
    daisy = EventDeck(custom, OTHER_SCOPE, 'daisy', SESSION, EPOCH, settings())
    assert evelyn.next_play(context(), 0).play.card.id == 'start-e'
    assert daisy.next_play(context(), 0).play.card.id == 'start'
    evelyn.finish_session(SESSION, RESULT, 1)
    assert evelyn.next_play(context(status='IDLE'), 1).play.card.id == 'end-e'


# Order and priority

def test_mandatory_start_card_precedes_active_missions():
    target = deck(sequences=[mission()])
    target.verified_event('edge', 'occ-1', SESSION, 0)
    assert target.next_play(context(edges=5), 0).play.card.id == 'start'


def test_priority_is_mission_then_narrative_then_normal():
    target = started(sequences=[narrative(), mission(event_kinds=['edge'])])
    target.verified_event('edge', 'occ-1', SESSION, 0)
    lanes = []
    for _ in range(3):
        play = target.next_play(context(), 0).play
        lanes.append(play.lane)
        deliver(target, play, 0)
    assert lanes == ['mission', 'narrative', 'normal']


def test_session_ending_outranks_everything_including_the_start_card():
    target = deck(sequences=[mission(event_kinds=['edge'])])
    target.verified_event('edge', 'occ-1', SESSION, 0)
    target.finish_session(SESSION, RESULT, 0)
    assert target.next_play(context(status='IDLE'), 0).play.lane == 'session_end'


def test_sequences_run_in_order_and_two_missions_do_not_overwrite_each_other():
    target = started(sequences=[mission('m1', 'm1-a', 'm1-b', event_kinds=['edge']), mission('m2', 'm2-a', event_kinds=['edge'])])
    assert target.verified_event('edge', 'occ-1', SESSION, 0) == ['m1', 'm2']
    assert draw_all(target, 3)[:3] == ['m1-a', 'm1-b', 'm2-a']


def test_counter_mission_fires_once_from_engine_counters():
    target = started(sequences=[mission(min_edges=2, min_seconds=60)])
    assert target.next_play(context(edges=2, seconds=59), 0).play.lane == 'normal' and target.transition(target._active.id, 'cancelled', 0)
    play = target.next_play(context(edges=2, seconds=60), 10).play
    assert play.lane == 'mission'
    deliver(target, play, 10)
    assert target.next_play(context(edges=9, seconds=99), 10).play.lane == 'normal'
    assert [a['sequence_id'] for a in target.snapshot()['activations']] == ['first-edges']


def test_milestone_is_recorded_even_when_speech_is_blocked():
    target = started(sequences=[mission()])
    assert target.next_play(context(edges=3, quiet=True), 0) == (None, 'user_requested_quiet')
    assert target.snapshot()['active_sequences'] == ['first-edges']


def test_duplicate_or_foreign_occurrences_do_not_activate():
    target = started(sequences=[narrative(kinds=('edge', 'milestone'))])
    assert target.verified_event('edge', 'occ-1', 'other-session', 0) == []
    assert target.verified_event('edge', 'occ-1', SESSION, 0) == ['story']
    assert target.verified_event('milestone', 'occ-1', SESSION, 0) == []
    assert target.verified_event('milestone', 'occ-2', SESSION, 0) == []


# Cadence and gates

def test_default_countdown_is_ten_seconds_with_no_legacy_floor():
    assert DeckSettings().countdown_seconds == 10
    target = deck()
    deliver(target, target.next_play(context(), 0).play, 0)
    assert target.next_play(context(), 9.9) == (None, 'countdown')
    assert target.next_play(context(), 10).play.lane == 'normal'


def test_countdown_is_configurable():
    target = deck(countdown_seconds=3)
    deliver(target, target.next_play(context(), 0).play, 0)
    assert target.next_play(context(), 2.9).reason == 'countdown'
    assert target.next_play(context(), 3).play


def test_completed_response_restarts_the_countdown_and_never_shortens_it():
    target = deck()
    deliver(target, target.next_play(context(), 0).play, 0)
    target.response_completed(6)
    assert target.next_play(context(), 15.9).reason == 'countdown'
    assert target.next_play(context(), 16).play
    target.response_completed(0)
    assert target._ready_at == 16


@pytest.mark.parametrize('values,reason', [
    ({'quiet': True}, 'user_requested_quiet'), ({'fresh': False}, 'stale_observation'),
    ({'watchdog_paused': True}, 'protective_state'), ({'no_contact': True}, 'protective_state'),
    ({'fault': 'signal_lost'}, 'protective_state'), ({'fault': 'no_contact'}, 'protective_state'),
    ({'signal': 'stale'}, 'signal_unavailable'), ({'signal': 'holding'}, 'signal_unavailable'),
    ({'signal': 'unknown-value'}, 'signal_unavailable'), ({'status': 'PAUSED'}, 'session_inactive'),
    ({'output_busy': True}, 'output_busy'), ({'proactive_enabled': False}, 'proactive_disabled'),
    ({'status': 'IDLE'}, 'session_inactive'), ({'user_active': True}, 'user_active'),
    ({'session_id': 'other'}, 'wrong_session')])
def test_gates_block_without_consuming_anything(values, reason):
    target = deck()
    assert target.next_play(context(**values), 0) == (None, reason)
    assert target.next_play(context(), 0).play.card.id == 'start'


def test_only_one_play_can_be_open():
    target = deck()
    target.next_play(context(), 0)
    assert target.next_play(context(), 0) == (None, 'play_active')


# Lifecycle

def test_generated_accepted_and_delivered_are_distinct_and_only_delivery_consumes():
    target = started()
    play = target.next_play(context(), 0).play
    before = target.snapshot()
    assert target.status(play.id) == 'proposed'
    target.transition(play.id, 'accepted', 0)
    assert target.status(play.id) == 'accepted'
    target.transition(play.id, 'generated', 0)
    assert target.status(play.id) == 'generated'
    assert target.snapshot()['remaining'] == before['remaining'] and target.snapshot()['played'] == 0
    target.transition(play.id, 'delivered', 0)
    assert target.status(play.id) == 'delivered'
    assert target.snapshot()['remaining'] == before['remaining'] - 1 and target.snapshot()['played'] == 1


@pytest.mark.parametrize('start,status', [('proposed', 'delivered'), ('proposed', 'generated'), ('proposed', 'suppressed'),
                                          ('accepted', 'delivered'), ('accepted', 'deferred'), ('generated', 'accepted')])
def test_lifecycle_stages_cannot_be_skipped(start, status):
    target = deck()
    play = target.next_play(context(), 0).play
    if start in {'accepted', 'generated'}:
        target.transition(play.id, 'accepted', 0)
    if start == 'generated':
        target.transition(play.id, 'generated', 0)
    with pytest.raises(DeckLifecycleError):
        target.transition(play.id, status, 0)
    assert target.status(play.id) == start


@pytest.mark.parametrize('status', ['deferred', 'cancelled'])
def test_interrupted_card_stays_next_and_is_not_consumed(status):
    target = started()
    play = target.next_play(context(), 0).play
    outcome(target, play, status, 0)
    assert target.snapshot()['played'] == 0
    assert target.next_play(context(), 2).play.card.id == play.card.id


def test_interruption_waits_a_short_retry_delay():
    target = started()
    outcome(target, target.next_play(context(), 0).play, 'deferred', 0)
    assert target.next_play(context(), 1.9).reason == 'retry_wait'


def test_settling_late_or_twice_changes_nothing():
    target = started()
    play = target.next_play(context(), 0).play
    deliver(target, play, 0)
    snapshot = target.snapshot()
    assert target.transition(play.id, 'delivered', 0) is False
    assert target.transition(play.id, 'cancelled', 0) is False
    assert target.transition('unknown', 'delivered', 0) is False
    assert target.snapshot() == snapshot


def test_diagnostics_are_bounded_and_contain_no_card_text():
    target = started(normal=[card('n0'), card('n1')])
    for _ in range(100):
        play = target.next_play(context(), 0).play
        deliver(target, play, 0)
    snapshot = target.snapshot()
    assert len(snapshot['history']) <= 16 and 'Brief for' not in str(snapshot)


# Bounded retries

@pytest.mark.parametrize('status', ['suppressed', 'failed'])
def test_unproductive_card_is_retried_at_most_twice_per_cycle(status):
    target = started(max_backoff_seconds=0)
    seen = []
    for now in range(10):
        play = target.next_play(context(), now).play
        seen.append(play.card.id)
        outcome(target, play, status, now)
    assert sorted(seen) == sorted(f'n{i}' for i in range(5) for _ in range(2))
    assert target.snapshot()['cycle'] == 0 and target.snapshot()['remaining'] == 0
    assert target.snapshot()['counts'].get('delivered') == 1  # only the start card


@pytest.mark.parametrize('status', ['suppressed', 'failed'])
def test_card_that_never_succeeds_is_retired_and_the_deck_ends_instead_of_looping(status):
    target = started(normal=[card('only')], max_backoff_seconds=0)
    plays = 0
    for now in range(0, 2000, 2):
        draw = target.next_play(context(), now)
        if draw.play is None and draw.reason == 'deck_exhausted':
            break
        if draw.play:
            plays += 1
            outcome(target, draw.play, status, now)
    assert plays == DeckSettings().max_session_attempts
    assert target.snapshot()['retired'] == ['only']


def test_silence_moves_on_to_a_different_card():
    target = started(max_backoff_seconds=0)
    first = target.next_play(context(), 0).play
    outcome(target, first, 'suppressed', 0)
    assert target.next_play(context(), 1).play.card.id != first.card.id


def test_a_success_elsewhere_keeps_the_deck_moving_after_a_bad_card():
    target = started(normal=[card('bad'), card('good')], max_backoff_seconds=0, max_attempts=1, max_session_attempts=1)
    delivered = []
    for now in range(0, 40):
        play = target.next_play(context(), now).play
        if play and play.card.id == 'bad':
            outcome(target, play, 'failed', now)
        elif play:
            delivered.append(play.card.id)
            deliver(target, play, now)
    assert target.snapshot()['retired'] == ['bad'] and len(delivered) >= 30


def test_repeated_failures_back_off_up_to_the_cap_and_delivery_resets_it():
    target = started(countdown_seconds=10, normal=[card(f'n{i}') for i in range(30)], max_backoff_seconds=40)
    ready = []
    now = 10
    for _ in range(5):
        outcome(target, target.next_play(context(), now).play, 'failed', now)
        ready.append(target._retry_at - now)
        now = target._retry_at
    assert ready == [10, 20, 40, 40, 40]
    deliver(target, target.next_play(context(), now).play, now)
    assert target.snapshot()['unproductive_streak'] == 0 and target._ready_at - now == 10


def test_repeated_deferral_rotates_a_normal_card_away():
    target = started(max_interruptions=3, interruption_retry_seconds=0)
    first = target.next_play(context(), 0).play
    outcome(target, first, 'deferred', 0)
    for _ in range(2):
        play = target.next_play(context(), 0).play
        assert play.card.id == first.card.id
        outcome(target, play, 'deferred', 0)
    assert target.next_play(context(), 0).play.card.id != first.card.id


def test_ineligible_cards_stay_unconsumed_and_are_skipped_without_blocking():
    target = started(normal=[card('late', eligibility=Eligibility(min_seconds=100)), card('early')])
    assert draw_all(target, 3) == ['early'] * 3
    assert target.next_play(context(seconds=100), 0).play is not None
    assert target.snapshot()['remaining'] >= 1


def test_all_ineligible_returns_a_reason_without_reshuffling_forever():
    target = started(normal=[card('late', eligibility=Eligibility(min_seconds=100))])
    cycle = target.snapshot()['cycle']
    for now in range(50):
        assert target.next_play(context(), now) == (None, 'no_eligible_card')
    assert target.snapshot()['cycle'] == cycle


def test_story_welcome_is_required_where_declared():
    target = started(normal=[card('story-ish', eligibility=Eligibility(requires_story_welcome=True))])
    assert target.next_play(context(), 0).reason == 'no_eligible_card'
    assert target.next_play(context(story_welcome=True), 0).play


def test_non_repeating_card_is_gone_after_delivery():
    target = started(normal=[card('once', repeat=False)])
    assert draw_all(target, 1) == ['once']
    assert target.next_play(context(), 0) == (None, 'deck_exhausted')


def test_start_card_cannot_block_the_deck_forever():
    target = deck(countdown_seconds=0, max_attempts=2, max_backoff_seconds=0, interruption_retry_seconds=1)
    outcome(target, target.next_play(context(), 0).play, 'failed', 0)
    assert target.next_play(context(), .5) == (None, 'retry_wait')
    play = target.next_play(context(), 1).play
    assert play.lane == 'session_start'
    outcome(target, play, 'failed', 1)
    assert target.snapshot()['start_outcome'] == 'attempts_exhausted'
    assert target.next_play(context(), 1).play.lane == 'normal'


@pytest.mark.parametrize('status,bound', [('failed', 2), ('suppressed', 2), ('deferred', 3), ('cancelled', 3)])
def test_mission_step_cannot_block_lower_lanes_forever(status, bound):
    target = started(sequences=[mission('m', 'm-a', 'm-b', event_kinds=['edge'])], max_backoff_seconds=0, interruption_retry_seconds=0)
    target.verified_event('edge', 'occ', SESSION, 0)
    for _ in range(bound):
        play = target.next_play(context(), 0).play
        assert play.card.id == 'm-a'
        outcome(target, play, status, 0)
    assert target.next_play(context(), 0).play.card.id == 'm-b'


def test_ineligible_mission_step_falls_through_then_expires():
    step = card('m-a', 'mission', eligibility=Eligibility(min_edges=99))
    sequence = Sequence(id='m', lane='mission', trigger=SequenceTrigger(event_kinds=['edge']), steps=[step])
    target = started(sequences=[sequence], step_ttl_seconds=100)
    target.verified_event('edge', 'occ', SESSION, 0)
    play = target.next_play(context(), 50).play
    assert play.lane == 'normal'
    outcome(target, play, 'cancelled', 50)
    target.next_play(context(), 200)
    assert target.snapshot()['active_sequences'] == []


# Approved decisions: sensorless sessions

def test_session_without_hr_sensor_plays_every_card_that_does_not_need_hr():
    normal = [card('plain'), card('hr', eligibility=Eligibility(requires_hr=True))]
    target = deck(normal=normal, sequences=[mission(), narrative()], countdown_seconds=0)
    ctx = context(signal='missing', edges=2)
    target.observe(context(signal='missing'), 0)
    target.verified_event('edge', 'occ', SESSION, 0)
    drawn = []
    for _ in range(5):
        play = target.next_play(ctx, 0).play
        drawn.append(play.card.id)
        deliver(target, play, 0)
    assert drawn == ['start', 'first-edges-1', 'story-1', 'plain', 'plain']


def test_hr_card_needs_a_current_verified_reading():
    target = started(normal=[card('hr', eligibility=Eligibility(requires_hr=True))])
    assert target.next_play(context(hr_current=False), 0).reason == 'no_eligible_card'
    assert target.next_play(context(hr_current=True), 0).play.card.id == 'hr'


def test_sensor_lost_mid_session_blocks_until_it_returns():
    target = started()
    assert target.next_play(context(signal='missing'), 0).reason == 'sensor_disconnected'
    assert target.next_play(context(signal='ok'), 0).play is not None


def test_a_sensor_that_was_never_there_is_not_a_disconnect():
    target = deck(countdown_seconds=0)
    assert target.next_play(context(signal='missing'), 0).play.card.id == 'start'


def test_device_lost_mid_session_blocks_but_a_session_without_a_toy_does_not():
    target = started()
    assert target.next_play(context(fault='device_unready'), 0).reason == 'device_disconnected'
    never = deck(countdown_seconds=0)
    assert never.next_play(context(fault='device_unready'), 0).play.card.id == 'start'


# Approved decisions: opening card

@pytest.mark.parametrize('status,bound,recorded', [('failed', 2, 'attempts_exhausted'), ('suppressed', 2, 'attempts_exhausted'),
                                                   ('deferred', 3, 'interruptions_exhausted'), ('cancelled', 3, 'interruptions_exhausted')])
def test_failed_opening_card_is_recorded_and_the_deck_continues(status, bound, recorded):
    target = deck(countdown_seconds=0, interruption_retry_seconds=0)
    for _ in range(bound):
        play = target.next_play(context(), 0).play
        assert play.lane == 'session_start'
        outcome(target, play, status, 0)
    assert target.snapshot()['start_outcome'] == recorded
    assert target.next_play(context(), 0).play.lane == 'normal'


def test_delivered_opening_card_records_delivery():
    assert started().snapshot()['start_outcome'] == 'delivered'


# Approved decisions: triggered timing

@pytest.mark.parametrize('sequence', [mission(event_kinds=['edge']), narrative()], ids=['mission', 'narrative'])
def test_triggered_cards_bypass_the_countdown_and_restart_it_after_delivery(sequence):
    target = deck(sequences=[sequence])
    deliver(target, target.next_play(context(), 0).play, 0)
    assert target.next_play(context(), 1).reason == 'countdown'
    target.verified_event('edge', 'occ', SESSION, 1)
    play = target.next_play(context(), 1).play
    assert play.lane == sequence.lane
    deliver(target, play, 1)
    assert target.next_play(context(), 10.9).reason == 'countdown'
    assert target.next_play(context(), 11).play.lane == 'normal'


@pytest.mark.parametrize('values,reason', [({'output_busy': True}, 'output_busy'), ({'user_active': True}, 'user_active')])
def test_triggered_cards_wait_for_output_and_never_interrupt_the_user(values, reason):
    target = started(sequences=[mission(event_kinds=['edge'])])
    target.verified_event('edge', 'occ', SESSION, 0)
    assert target.next_play(context(**values), 0) == (None, reason)
    assert target.next_play(context(), 0).play.lane == 'mission'


def test_opening_card_also_ignores_a_countdown_from_an_earlier_reply():
    target = deck()
    target.response_completed(0)
    assert target.next_play(context(), 1).play.card.id == 'start'


def test_normal_backoff_does_not_hold_back_a_milestone():
    target = started(countdown_seconds=10, sequences=[mission(event_kinds=['edge'])], max_backoff_seconds=300)
    outcome(target, target.next_play(context(), 10).play, 'failed', 10)
    assert target.next_play(context(), 11).reason == 'retry_wait'
    target.verified_event('edge', 'occ', SESSION, 11)
    assert target.next_play(context(), 11).play.lane == 'mission'


def test_triggered_retries_are_spaced_rather_than_immediate():
    target = started(sequences=[mission(event_kinds=['edge'])], interruption_retry_seconds=2)
    target.verified_event('edge', 'occ', SESSION, 0)
    outcome(target, target.next_play(context(), 0).play, 'failed', 0)
    assert target.next_play(context(), 1.9) == (None, 'retry_wait')
    assert target.next_play(context(), 2).play.lane == 'mission'


def test_closing_never_overlaps_active_output_or_interrupts_the_user():
    target = started()
    target.finish_session(SESSION, RESULT, 1)
    assert target.next_play(context(status='IDLE', user_active=True), 1) == (None, 'user_active')
    assert target.next_play(context(status='IDLE', output_busy=True), 1) == (None, 'output_busy')
    assert target.next_play(context(status='IDLE'), 1).play.lane == 'session_end'


def test_opening_and_missions_bypass_the_unsolicited_limit_but_narrative_and_normal_do_not():
    target = deck(countdown_seconds=0, mission_spacing_seconds=0, sequences=[mission(event_kinds=['edge']), narrative()])
    ctx = context(unsolicited_limit_reached=True)
    deliver(target, target.next_play(ctx, 0).play, 0)
    assert target.next_play(ctx, 0) == (None, 'unsolicited_limit')
    target.verified_event('edge', 'occ', SESSION, 0)
    play = target.next_play(ctx, 0).play
    assert play.lane == 'mission'
    deliver(target, play, 0)
    assert target.next_play(ctx, 0) == (None, 'unsolicited_limit')
    assert target.next_play(context(), 0).play.lane == 'narrative'


def test_recent_conversation_holds_narrative_and_normal_but_not_missions():
    target = started(sequences=[mission(event_kinds=['edge'])])
    ctx = context(conversation_active=True)
    assert target.next_play(ctx, 0) == (None, 'active_conversation')
    target.verified_event('edge', 'occ', SESSION, 0)
    assert target.next_play(ctx, 0).play.lane == 'mission'


def test_consecutive_missions_are_spaced_to_prevent_flooding():
    target = deck(countdown_seconds=0, mission_spacing_seconds=4, sequences=[mission('m', 'm-a', 'm-b', event_kinds=['edge'])])
    deliver(target, target.next_play(context(), 0).play, 0)
    target.verified_event('edge', 'occ', SESSION, 0)
    deliver(target, target.next_play(context(), 0).play, 0)
    assert target.next_play(context(), 3.9) == (None, 'mission_spacing')
    assert target.next_play(context(), 4).play.card.id == 'm-b'


def test_triggered_only_never_returns_a_normal_card():
    target = started()
    assert target.next_play(context(), 0, triggered_only=True) == (None, 'no_triggered_card')
    assert target.next_play(context(), 0).play.lane == 'normal'


def test_opening_is_skipped_rather_than_replayed_late_in_a_session():
    target = deck(countdown_seconds=0)
    assert target.next_play(context(seconds=121), 0).play.lane == 'normal'
    assert target.snapshot()['start_outcome'] == 'opening_window_passed'


def test_snapshot_is_strict_json():
    import json
    assert json.dumps(deck().snapshot(), allow_nan=False)


def test_model_settings_are_exact_scope_with_safe_defaults():
    from companion_ai.event_deck import load_model_settings, scope_key
    class Store:
        def __init__(self, value):
            self.value = value
        def read(self, name, default=None):
            if isinstance(self.value, Exception):
                raise self.value
            return self.value
    assert load_model_settings(None, SCOPE)[0] == DeckSettings()
    saved = {'schema_version': 1, 'models': {scope_key(SCOPE): {'enabled': True, 'countdown_seconds': 15}}}
    assert load_model_settings(Store(saved), SCOPE)[0].enabled and load_model_settings(Store(saved), SCOPE)[0].countdown_seconds == 15
    other, error = load_model_settings(Store(saved), OTHER_SCOPE)
    assert other == DeckSettings() and error is None and other.countdown_seconds == 10
    for bad in ({'schema_version': 2}, {'models': {scope_key(SCOPE): {'enabled': True, 'unknown': 1}}}, ValueError('unreadable')):
        result, error = load_model_settings(Store(bad), SCOPE)
        assert not result.enabled and error


# Approved decisions: controls

def test_event_intelligence_off_keeps_ordinary_draws_and_counter_missions():
    target = started(sequences=[mission(min_edges=2)])
    ctx = context(edges=2, event_reactions_enabled=False)
    play = target.next_play(ctx, 0).play
    assert play.lane == 'mission'
    deliver(target, play, 0)
    assert target.next_play(ctx, 0).play.lane == 'normal'


def test_event_intelligence_off_discards_event_reactions_without_later_replay():
    target = started(sequences=[narrative(), mission('event-mission', event_kinds=['edge'])])
    target.verified_event('edge', 'occ-1', SESSION, 0)
    assert target.next_play(context(event_reactions_enabled=False), 0).play.lane == 'normal'
    assert target.snapshot()['active_sequences'] == []
    target.transition(target._active.id, 'cancelled', 0)
    assert target.verified_event('edge', 'occ-1', SESSION, 3) == []
    assert target.verified_event('edge', 'occ-2', SESSION, 3) == ['story', 'event-mission']


def test_proactive_off_suppresses_unsolicited_cards_but_keeps_a_user_ended_closing():
    target = started(sequences=[mission()])
    ctx = context(edges=9, proactive_enabled=False)
    assert target.next_play(ctx, 0) == (None, 'proactive_disabled')
    assert target.snapshot()['active_sequences'] == ['first-edges']
    target.finish_session(SESSION, RESULT, 1)
    assert target.next_play(context(status='IDLE', proactive_enabled=False), 1).play.lane == 'session_end'


@pytest.mark.parametrize('values,reason', [({'quiet': True}, 'user_requested_quiet'), ({'no_contact': True}, 'protective_state'), ({'signal': 'missing'}, 'sensor_disconnected')])
def test_user_ended_closing_with_proactive_off_still_respects_safety_mute_and_disconnect(values, reason):
    target = started()
    target.finish_session(SESSION, RESULT, 1)
    assert target.next_play(context(**({'status': 'IDLE', 'proactive_enabled': False} | values)), 1) == (None, reason)


def test_ending_the_user_did_not_cause_stays_silent_with_proactive_off():
    target = started()
    target.finish_session(SESSION, RESULT | {'termination': 'other_stop'}, 1)
    assert target.next_play(context(status='IDLE', proactive_enabled=False), 1) == (None, 'proactive_disabled')
    assert target.next_play(context(status='IDLE'), 1).play.lane == 'session_end'


# Session finalization

def test_finish_cancels_pending_cards_and_closing_comes_first_without_a_countdown():
    target = deck(sequences=[mission(event_kinds=['edge'])])
    deliver(target, target.next_play(context(), 0).play, 0)
    target.verified_event('edge', 'occ', SESSION, 0)
    assert target.finish_session(SESSION, RESULT, 1) is True
    draw = target.next_play(context(status='IDLE'), 1)
    assert draw.reason == 'session_end' and draw.play.card.id == 'end'
    deliver(target, draw.play, 1)
    assert target.next_play(context(status='IDLE'), 100) == (None, 'session_closed')


def test_a_late_reply_for_a_cancelled_card_cannot_be_delivered():
    target = started()
    play = target.next_play(context(), 0).play
    target.transition(play.id, 'accepted', 0)
    target.finish_session(SESSION, RESULT, 1)
    assert target.status(play.id) == 'cancelled'
    assert target.transition(play.id, 'delivered', 2) is False


def test_repeated_finalization_creates_one_closing_card_and_keeps_the_first_snapshot():
    target = started()
    assert target.finish_session(SESSION, RESULT, 1) is True
    assert target.finish_session(SESSION, RESULT | {'edges': 99}, 1) is False
    play = target.next_play(context(status='IDLE'), 1).play
    assert target.finish_session(SESSION, RESULT, 1) is False
    assert target.status(play.id) == 'proposed'
    deliver(target, play, 1)
    assert target.finish_session(SESSION, RESULT, 2) is False
    assert target.next_play(context(status='IDLE'), 2) == (None, 'session_closed')
    assert play.opportunity()['session_result']['edges'] == 4
    assert target.snapshot()['repeat_finalizations'] == 3
    assert target.snapshot()['counts']['delivered'] == 2


def test_finish_for_another_session_is_ignored():
    target = started()
    assert target.finish_session('other', RESULT, 1) is False
    assert target.next_play(context(), 1).play.lane == 'normal'


def test_nothing_activates_after_finalization():
    target = started(sequences=[mission(event_kinds=['edge'])])
    target.finish_session(SESSION, RESULT, 1)
    assert target.verified_event('edge', 'occ', SESSION, 1) == []
    assert target.observe(context(edges=9), 1) == []


def test_closing_uses_only_the_finalized_snapshot():
    target = started()
    target.finish_session(SESSION, RESULT, 1)
    payload = target.next_play(context(status='IDLE'), 1).play.opportunity()
    assert payload['session_result'] == RESULT and payload['memory'] == 'none'
    assert not [key for key in payload if 'journal' in key or 'history' in key]
    assert 'journal' not in str(DeckContext.model_fields) and 'journal' not in str(SessionResult.model_fields)


@pytest.mark.parametrize('bad', [RESULT | {'journal_context': []}, RESULT | {'heart_rate': {}}, {'edges': 'four'}, 'not-a-dict'])
def test_invalid_or_excess_snapshot_fails_closed_with_no_closing(bad):
    target = started()
    assert target.finish_session(SESSION, bad, 1) is True
    assert target.next_play(context(status='IDLE'), 1) == (None, 'session_closed')
    assert target.snapshot()['closing_rejected'] == 'invalid_session_result'


@pytest.mark.parametrize('termination', ['safety_stop', 'cancelled', 'cancelled_or_unclassified_stop'])
def test_protective_terminations_get_no_closing(termination):
    target = started()
    target.finish_session(SESSION, RESULT | {'termination': termination}, 1)
    assert target.next_play(context(status='IDLE'), 1) == (None, 'session_closed')


def test_caller_can_withhold_the_closing():
    target = started()
    target.finish_session(SESSION, RESULT, 1, closing_permitted=False)
    assert target.next_play(context(status='IDLE'), 1) == (None, 'session_closed')


@pytest.mark.parametrize('values,reason', [({'quiet': True}, 'user_requested_quiet'), ({'fresh': False}, 'stale_observation'),
                                           ({'no_contact': True}, 'protective_state'), ({'watchdog_paused': True}, 'protective_state'),
                                           ({'status': 'RUNNING'}, 'closing_waiting_for_idle'), ({'user_active': True}, 'user_active')])
def test_closing_still_respects_safety_quiet_and_user_gates(values, reason):
    target = started()
    target.finish_session(SESSION, RESULT, 1)
    assert target.next_play(context(**({'status': 'IDLE'} | values)), 1) == (None, reason)


def test_closing_works_in_a_session_that_never_had_a_sensor_but_not_after_a_disconnect():
    never = deck(countdown_seconds=0)
    ctx = context(signal='missing')
    deliver(never, never.next_play(ctx, 0).play, 0)
    never.finish_session(SESSION, RESULT, 1)
    assert never.next_play(context(status='IDLE', signal='missing'), 1).play.lane == 'session_end'
    lost = started()
    lost.finish_session(SESSION, RESULT, 1)
    assert lost.next_play(context(status='IDLE', signal='missing'), 1) == (None, 'sensor_disconnected')


def test_closing_expires_rather_than_waiting_forever():
    target = started(closing_ttl_seconds=60)
    target.finish_session(SESSION, RESULT, 1)
    assert target.next_play(context(status='IDLE', quiet=True), 61).play is None
    assert target.next_play(context(status='IDLE', quiet=True), 62) == (None, 'closing_expired')
    assert target.next_play(context(status='IDLE'), 62) == (None, 'session_closed')
    assert target.closing_outcome == 'expired'


@pytest.mark.parametrize('hold,reason', [({'output_busy': True}, 'output_busy'), ({'user_active': True}, 'user_active')])
def test_temporary_holds_do_not_spend_the_ttl_but_have_an_outer_limit(hold, reason):
    target = started(closing_ttl_seconds=60, closing_max_hold_seconds=300)
    target.finish_session(SESSION, RESULT, 1)
    assert target.next_play(context(**({'status': 'IDLE'} | hold)), 200) == (None, reason)
    assert target.next_play(context(status='IDLE'), 201).play.lane == 'session_end'
    other = started(closing_ttl_seconds=60, closing_max_hold_seconds=300)
    other.finish_session(SESSION, RESULT, 1)
    assert other.next_play(context(**({'status': 'IDLE'} | hold)), 302) == (None, 'closing_expired')
    assert other.closing_outcome == 'hold_limit_reached'


def test_a_block_spends_the_ttl_only_while_it_lasts_as_a_block():
    target = started(closing_ttl_seconds=60)
    target.finish_session(SESSION, RESULT, 1)
    assert not target.closing_blocked(61) and target.closing_pending
    assert target.closing_blocked(62) and not target.closing_pending


def test_subscribes_reports_only_event_triggers():
    target = deck(sequences=[mission(event_kinds=['edge']), mission('counter', 'c-a', min_edges=2)])
    assert target.subscribes('edge') and not target.subscribes('milestone')


@pytest.mark.parametrize('status', ['suppressed', 'failed'])
def test_silent_or_failed_closing_gets_bounded_retries_and_then_closes(status):
    target = started(max_attempts=2, interruption_retry_seconds=2)
    closed = []
    target.on_closing_closed = closed.append
    target.finish_session(SESSION, RESULT, 1)
    outcome(target, target.next_play(context(status='IDLE'), 1).play, status, 1)
    assert target.closing_pending and not closed
    assert target.next_play(context(status='IDLE'), 2) == (None, 'retry_wait')
    outcome(target, target.next_play(context(status='IDLE'), 3).play, status, 3)
    assert not target.closing_pending and target.closing_outcome == status and closed == [status]
    assert target.next_play(context(status='IDLE'), 9) == (None, 'session_closed')


def test_interrupted_closing_retries_a_bounded_number_of_times():
    target = started(max_interruptions=2, interruption_retry_seconds=0)
    target.finish_session(SESSION, RESULT, 1)
    for _ in range(2):
        outcome(target, target.next_play(context(status='IDLE'), 1).play, 'cancelled', 1)
    assert target.next_play(context(status='IDLE'), 1) == (None, 'session_closed')


# Memory and scope isolation

def test_play_declares_its_memory_policy():
    target = started(sequences=[narrative()])
    routine = target.next_play(context(), 0).play
    assert routine.opportunity()['memory'] == 'none'
    outcome(target, routine, 'cancelled', 0)
    target.verified_event('edge', 'occ', SESSION, 0)
    assert target.next_play(context(), 2).play.opportunity()['memory'] == 'story'


def test_narrative_reset_drops_progress_but_never_replays_an_old_occurrence():
    target = started(sequences=[narrative(), mission(event_kinds=['edge'])])
    target.verified_event('edge', 'occ-1', SESSION, 0)
    deliver(target, target.next_play(context(), 0).play, 0)
    open_play = target.next_play(context(), 0).play
    assert open_play.lane == 'narrative'
    target.narrative_reset('b' * 32, 1)
    assert target.status(open_play.id) == 'cancelled' and target.epoch == 'b' * 32
    assert target.verified_event('edge', 'occ-1', SESSION, 1) == []
    assert target.verified_event('edge', 'occ-2', SESSION, 1) == ['story']
    assert target.next_play(context(), 1).play.epoch == 'b' * 32


def test_narrative_reset_keeps_normal_order_and_missions():
    run = started(sequences=[mission(event_kinds=['edge'])])
    untouched = started()
    run.narrative_reset('b' * 32, 0)
    assert draw_all(run, 3) == draw_all(untouched, 3)


def test_registry_isolates_exact_scopes_and_sessions():
    registry = DeckRegistry(definition(), settings(countdown_seconds=0))
    evelyn = registry.deck(SCOPE, 'evelyn', SESSION, EPOCH)
    assert registry.deck(SCOPE, 'evelyn', SESSION, EPOCH) is evelyn
    assert registry.deck(OTHER_SCOPE, 'daisy', SESSION, EPOCH) is not evelyn
    assert registry.deck(SCOPE.replace('11435', '11436'), 'evelyn', SESSION, EPOCH) is not evelyn
    assert registry.deck(SCOPE, 'evelyn', 'session-b', EPOCH) is not evelyn
    with pytest.raises(ValueError):
        registry.deck(SCOPE, 'daisy', SESSION, EPOCH)


def test_progress_in_one_scope_does_not_touch_another():
    registry = DeckRegistry(definition(), settings(countdown_seconds=0))
    evelyn = registry.deck(SCOPE, 'evelyn', SESSION, EPOCH)
    daisy = registry.deck(OTHER_SCOPE, 'daisy', SESSION, EPOCH)
    play = evelyn.next_play(context(), 0).play
    deliver(evelyn, play, 0)
    evelyn.finish_session(SESSION, RESULT, 1)
    assert daisy.transition(play.id, 'accepted', 1) is False
    assert daisy.next_play(context(), 1).play.card.id == 'start'


def test_registry_is_bounded():
    registry = DeckRegistry(definition(), settings(), max_decks=2)
    first = registry.deck(SCOPE, 'evelyn', 's1', EPOCH)
    registry.deck(SCOPE, 'evelyn', 's2', EPOCH)
    registry.deck(SCOPE, 'evelyn', 's3', EPOCH)
    assert registry.deck(SCOPE, 'evelyn', 's1', EPOCH) is not first


def test_a_character_cannot_activate_another_characters_sequence():
    private = Sequence(id='d', lane='mission', audience='daisy', trigger=SequenceTrigger(event_kinds=['edge']), steps=[card('d-a', 'mission', audience='daisy')])
    target = started(sequences=[private])
    assert target.verified_event('edge', 'occ', SESSION, 0) == []


GOLDEN_ORDER = ['n3', 'n0', 'n1', 'n4', 'n2']


def test_a_trend_rule_needs_a_current_heart_rate_and_a_listed_direction():
    with pytest.raises(ValueError):
        Eligibility(hr_trends=['rising'])
    with pytest.raises(ValueError):
        Eligibility(requires_hr=True, hr_trends=['unknown'])
    with pytest.raises(ValueError):
        Eligibility(requires_hr=True, hr_trends=[])
    target = deck(normal=[Card(id='trend', kind='normal', intent='comment', brief='Brief', eligibility=Eligibility(requires_hr=True, hr_trends=['rising']))], countdown_seconds=0)
    ctx = context(hr_current=True, hr_trend='rising')
    deliver(target, target.next_play(ctx, 0).play, 0)
    assert target.next_play(context(hr_current=False, hr_trend='rising'), 0) == (None, 'no_eligible_card')
    assert target.next_play(context(hr_current=True, hr_trend='unknown'), 0) == (None, 'no_eligible_card')
    assert target.next_play(context(hr_current=True, hr_trend='falling'), 0) == (None, 'no_eligible_card')
    assert target.next_play(ctx, 0).play.card.id == 'trend'


@pytest.mark.parametrize('rule,topic', [({}, 'general'), ({'min_edges': 1}, 'milestones'), ({'max_edges': 4}, 'milestones'), ({'min_seconds': 300}, 'timing'), ({'max_seconds': 90}, 'timing'), ({'requires_hr': True}, 'physiology'), ({'requires_hr': True, 'min_edges': 1}, 'physiology')])
def test_a_card_is_given_the_facts_its_rule_depends_on(rule, topic):
    from companion_ai.event_deck import Play
    card = Card(id='c', kind='normal', intent='comment', brief='Brief', eligibility=Eligibility(**rule))
    assert Play('id', card, 'normal', SCOPE, SESSION, EPOCH).opportunity()['focus_topic'] == topic
