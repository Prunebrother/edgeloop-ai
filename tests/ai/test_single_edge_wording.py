# SPDX-License-Identifier: AGPL-3.0-only
"""Evelyn's arrival, 2026-11-16: the facts said 27 edges and 1 reported orgasm; she greeted
the player with "a single edge and a solitary climax". The figures are now dealt on separate
lines, and "single/lone/solitary edge" is checked as the count 1, like "one edge" already was."""
import pytest
from companion_ai.context_compiler import arrival_facts
from companion_ai.fidelity import history_violations, spoken_number

HISTORY = {'status': 'found', 'since_seconds': 6 * 86400 + 3600,
           'prior': {'edges': 27, 'seconds': 1400, 'experience': 'headplay', 'goal': 'tease',
                     'outcome': 'user_reported', 'comparable': True, 'orgasms': 1}}
SUMMARY = {'deck_card': {'lane': 'arrival', 'history': HISTORY}}


def test_edges_length_and_orgasms_are_separate_lines_that_cannot_be_swapped():
    lines = arrival_facts(HISTORY)
    assert 'Edges in the previous session: 27.' in lines
    assert 'Length of the previous session: 23 minutes 20 seconds.' in lines
    assert 'Orgasms the participant reported in it: 1. That is the orgasm count; the edge count is the 27 above.' in lines
    assert not any('27 edges in' in line for line in lines)


def test_unknown_figures_stay_explicit():
    lines = arrival_facts({**HISTORY, 'prior': {**HISTORY['prior'], 'seconds': None}})
    assert 'Length of the previous session: not known, so say nothing about how long it ran.' in lines
    lines = arrival_facts({**HISTORY, 'prior': {**HISTORY['prior'], 'edges': None, 'seconds': None}})
    assert lines[1] == 'The previous session: edge count and length not known, so state neither.'


def test_no_orgasm_note_when_the_counts_match():
    lines = arrival_facts({**HISTORY, 'prior': {**HISTORY['prior'], 'edges': 1}})
    assert 'Orgasms the participant reported in it: 1.' in lines


@pytest.mark.parametrize('word', ['single', 'singular', 'lone', 'solitary', 'sole'])
def test_one_without_a_number_word_is_one(word):
    assert spoken_number(word) == 1


@pytest.mark.parametrize('reply', [
    'You finished with a single edge and a solitary climax; I find that efficiency both refreshing and slightly underwhelming.',
    'Your last run was efficient, a single edge delivered with the precision of a surgeon.',
    'Your last effort left us with a single, rather modest edge to celebrate.',
    'You claimed that singular edge for yourself.',
    'That single, solitary edge was underwhelming.',
    'You finished with a lone edge.',
])
def test_a_single_edge_contradicting_the_record_is_caught(reply):
    assert 'unsupported_history_figure' in history_violations(reply, SUMMARY)


@pytest.mark.parametrize('reply', [
    'Twenty-seven edges in a single session is a formidable tally.',
    'Twenty-seven edges to fuel a single climax; quite the ratio.',
    'That single reported climax still lingers in my notes.',
    'You walked a single knife edge between restraint and release.',
    'A single razor-sharp edge of wit.',
])
def test_single_about_something_else_is_not_an_edge_count(reply):
    assert 'unsupported_history_figure' not in history_violations(reply, SUMMARY)


# Daisy's load tally, 2026-11-16: the brief asked for "the listed number of loads" while the facts
# listed edges (27) and orgasms (1); 19 of 20 replays said "twenty-seven loads".
import json
from pathlib import Path
from companion_ai.fidelity import card_language_violations, orgasm_count_violations

DECK = json.loads((Path(__file__).resolve().parents[2] / 'config/event-deck.json').read_text())
CARDS = {c['id']: c for c in DECK['normal']}
RUNNING = {'deck_card': {'lane': 'normal', 'orgasms': 1}}


def test_count_cards_name_the_count_they_mean():
    assert 'listed number of orgasms' in CARDS['daisy-load-tally']['brief'] and 'not the edge count' in CARDS['daisy-load-tally']['brief']
    assert 'listed edge count' in CARDS['edge-count-many']['brief']
    assert 'listed total' in CARDS['orgasms-total']['brief']
    steps = [s for q in DECK['sequences'] for s in q['steps'] if s['id'] == 'orgasm-reported-reaction']
    assert 'listed orgasm counts' in steps[0]['brief']


@pytest.mark.parametrize('reply', [
    "Twenty-seven loads in one go is a harvest I'd be proud to show my father.",
    "That's twenty-seven loads right there, a proper harvest.",
    '27 orgasms, what a day.',
])
def test_a_load_count_that_is_really_the_edge_count_is_caught(reply):
    assert 'unsupported_orgasm_count' in orgasm_count_violations(reply, RUNNING)
    assert 'unsupported_orgasm_count' in card_language_violations(reply, RUNNING)


@pytest.mark.parametrize('reply', [
    'One load is a fine start for the day.',
    'A single load, and a good one.',
    "I'd love to see two more loads before sundown.",
    "Twenty-seven edges and one load: a proper day's work.",
    'Three climaxes would make a record.',
])
def test_the_real_count_and_wishes_pass(reply):
    assert orgasm_count_violations(reply, RUNNING) == []


def test_no_orgasm_facts_means_no_orgasm_check():
    assert orgasm_count_violations('Twenty-seven loads.', {'deck_card': {'lane': 'normal'}}) == []


def test_the_total_and_earlier_sessions_count_as_known():
    summary = {'deck_card': {'lane': 'normal', 'orgasms': 1, 'total_orgasms': 3, 'total_known': True}}
    assert orgasm_count_violations('Three orgasms between us now.', summary) == []


def test_two_dozen_edges_is_a_count():
    assert spoken_number('two dozen') == 24
    assert 'unsupported_history_figure' in history_violations('Two dozen edges and one reported finish.', SUMMARY)
