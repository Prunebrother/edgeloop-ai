# SPDX-License-Identifier: AGPL-3.0-only
"""Campaign-scoped cards: synthetic decks, saved progress and mocked observer facts only."""
import json
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_observer.server import create_app
from companion_ai.campaign import Book, Campaign, CampaignRecord, CampaignService, PROGRESS_FILE, Progress
from companion_ai.event_deck import Eligibility, EventDeck, load_definition
from companion_ai.storage import SettingsStore
from tests.ai.test_event_deck import card, context, definition, deliver, started
from tests.ai.test_event_deck_integration import rig

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def book(monkeypatch):
    campaigns = [Campaign.model_validate({
        'schema_version': 1, 'id': cid, 'order': order, 'title': cid, 'description': 'Synthetic campaign',
        'starting_companions': ['nova'],
        'missions': [{'id': mid, 'order': i, 'title': mid, 'summary': 'Synthetic mission', 'companion': 'nova',
                      'objectives': [{'id': 'begin', 'type': 'session_started', 'label': 'Begin'}],
                      'flags': {'deal': 'accepted', 'reviewed': 'yes'}}
                     for i, mid in enumerate(('shared_mission', 'second_mission'), 1)],
    }) for order, cid in enumerate(('helix', 'asterion'), 1)]
    book = Book(campaigns)
    monkeypatch.setattr(Book, 'load', classmethod(lambda cls: book))
    return book


def scoped_card(**rules):
    return card('scoped', eligibility=Eligibility(**rules))


def test_unused_scope_fields_do_not_change_legacy_package_serialization():
    fields = {'campaigns', 'missions', 'flags'}
    assert not fields.intersection(Eligibility().model_dump(mode='json'))
    rules = {'campaigns': ['helix'], 'missions': ['helix/shared_mission'], 'flags': ['deal']}
    saved = Eligibility(**rules).model_dump(mode='json')
    assert {key: saved[key] for key in fields} == rules


def drawn_with(rules, **scope):
    target = started(normal=[scoped_card(**rules)])
    play = target.next_play(context(**scope), 1).play
    return play.card.id if play else None


@pytest.mark.parametrize('scope,expected', [
    ({}, None), ({'campaign': 'helix'}, None),
    ({'campaign': 'asterion', 'mission': 'shared_mission'}, None),
    ({'campaign': 'helix', 'mission': 'shared_mission'}, 'scoped'),
    ({'campaign': 'helix', 'mission': 'second_mission'}, 'scoped'),
])
def test_campaign_cards_require_a_matching_active_mission(scope, expected):
    assert drawn_with({'campaigns': ['helix']}, **scope) == expected


@pytest.mark.parametrize('scope,expected', [
    ({}, None), ({'mission': 'shared_mission'}, None),
    ({'campaign': 'helix'}, None),
    ({'campaign': 'asterion', 'mission': 'shared_mission'}, None),
    ({'campaign': 'helix', 'mission': 'second_mission'}, None),
    ({'campaign': 'helix', 'mission': 'shared_mission'}, 'scoped'),
])
def test_qualified_mission_cards_cannot_leak_to_another_campaign(scope, expected):
    assert drawn_with({'missions': ['helix/shared_mission']}, **scope) == expected


def test_local_book_mission_ids_and_multiple_campaigns_are_supported():
    for campaign in ('helix', 'asterion'):
        assert drawn_with({'missions': ['shared_mission']}, campaign=campaign, mission='shared_mission') == 'scoped'
        assert drawn_with({'campaigns': ['helix', 'asterion']}, campaign=campaign, mission='second_mission') == 'scoped'


def test_campaign_mission_and_flag_rules_all_apply_together():
    rules = {'campaigns': ['helix'], 'missions': ['shared_mission', 'helix/second_mission'], 'flags': ['deal']}
    assert drawn_with(rules, campaign='helix', mission='second_mission', flags=frozenset({'deal'})) == 'scoped'
    assert drawn_with(rules, campaign='helix', mission='second_mission') is None
    assert drawn_with(rules, campaign='asterion', mission='shared_mission', flags=frozenset({'deal'})) is None


def test_flag_card_becomes_drawable_after_every_required_flag_is_set():
    target = started(normal=[scoped_card(flags=['deal', 'reviewed'])])
    for flags in (frozenset(), frozenset({'deal'}), frozenset({'reviewed'})):
        assert target.next_play(context(flags=flags), 1).play is None
    play = target.next_play(context(flags=frozenset({'deal', 'reviewed', 'extra'})), 1).play
    assert play.card.id == 'scoped'
    deliver(target, play, 1)


@pytest.mark.parametrize('field', ['campaigns', 'missions', 'flags'])
def test_empty_scope_lists_are_rejected_but_none_is_unrestricted(field):
    with pytest.raises(ValidationError, match=field):
        Eligibility(**{field: []})
    assert drawn_with({field: None}) == 'scoped'


@pytest.mark.parametrize('rules,kind,name', [
    ({'campaigns': ['missing']}, 'campaign', 'missing'),
    ({'campaigns': ['helix', 'missing']}, 'campaign', 'missing'),
    ({'missions': ['missing']}, 'mission', 'missing'),
    ({'missions': ['missing/shared_mission']}, 'mission', 'missing/shared_mission'),
    ({'missions': ['helix/missing']}, 'mission', 'helix/missing'),
])
def test_loading_rejects_unknown_campaign_and_mission_ids(book, rules, kind, name):
    loaded, error = load_definition(definition(normal=[scoped_card(**rules)]).model_dump())
    assert loaded is None
    assert error == f'Event deck card "scoped" names unknown {kind} "{name}"; deck unavailable.'


@pytest.mark.parametrize('rules', [
    {'campaigns': ['helix']}, {'missions': ['shared_mission']},
    {'missions': ['helix/shared_mission', 'asterion/second_mission']},
    {'flags': ['deal', 'reviewed']},
])
def test_loading_accepts_book_ids_and_known_flags(book, caplog, rules):
    source = definition(normal=[scoped_card(**rules)])
    assert load_definition(source.model_dump()) == (source, None)
    assert not caplog.records


def test_loading_validates_sequence_steps_too(book):
    from tests.ai.test_event_deck import mission
    sequence = mission()
    sequence = sequence.model_copy(update={'steps': [card('step', 'mission', eligibility=Eligibility(campaigns=['missing']))]})
    loaded, error = load_definition(definition(sequences=[sequence]).model_dump())
    assert loaded is None and '"step" names unknown campaign "missing"' in error


def test_unknown_flags_warn_without_rejecting_the_deck(book, caplog):
    source = definition(normal=[scoped_card(flags=['deal', 'deall'])])
    with caplog.at_level(logging.WARNING, logger='companion_ai.event_deck'):
        assert load_definition(source.model_dump()) == (source, None)
    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        ('WARNING', 'Event deck card "scoped" names unknown campaign flag "deall"')]


def test_shipped_cards_keep_revision_10_eligibility_in_freeplay_and_asterion():
    # Captured before this change using revision 10's _eligible. Bit i is context i.
    baseline = json.loads((ROOT / 'tests/ai/fixtures/event_deck_eligibility_v10.json').read_text())
    raw = json.loads((ROOT / 'config/event-deck.json').read_text())
    loaded, error = load_definition(raw)
    assert error is None
    # The deck may grow (rev 12 adds Seraphine's personal cards): every card of the baseline must keep exactly
    # its revision-10 eligibility; a new card is checked by its own content tests instead.
    assert raw.pop('revision') > baseline['baseline_revision']
    cards = [*loaded.session_start, *loaded.session_end, *loaded.normal, *loaded.arrival,
             *(card for sequence in loaded.sequences for card in sequence.steps)]
    for scope in ({}, {'campaign': 'asterion_initiative', 'mission': 'first_assessment', 'flags': frozenset({'player_suspicion'})}):
        actual = {card.id: sum(1 << i for i, values in enumerate(baseline['contexts'])
                              if EventDeck._eligible(card, context(**(values | scope)))) for card in cards
                  if card.id in baseline['eligible_context_masks']}
        assert actual == baseline['eligible_context_masks']


def test_scope_uses_saved_flag_keys_from_the_active_campaign_or_all_campaigns(book, tmp_path):
    store = SettingsStore(tmp_path)
    progress = Progress(campaigns={
        'helix': CampaignRecord(flags={'reviewed': 'no'}),
        'asterion': CampaignRecord(flags={'deal': 'accepted'}),
    })
    store.write(PROGRESS_FILE, progress.model_dump(mode='json'))
    service = CampaignService(store, book=book)
    assert service.deck_scope() == (None, None, frozenset({'reviewed', 'deal'}))
    service.start('helix', 'shared_mission')
    assert service.deck_scope() == ('helix', 'shared_mission', frozenset({'reviewed'}))
    campaign, mission, flags = service.deck_scope()
    assert drawn_with({'flags': ['deal']}, campaign=campaign, mission=mission, flags=flags) is None
    service.start('asterion', 'shared_mission')
    assert service.deck_scope() == ('asterion', 'shared_mission', frozenset({'deal'}))
    service.error = 'Progress unavailable'
    assert service.deck_scope() == (None, None, frozenset())


async def test_deck_context_carries_the_observer_scope_and_refreshes_it():
    replay, speech, _, _ = rig()
    try:
        assert (speech.deck_context(0).campaign, speech.deck_context(0).mission, speech.deck_context(0).flags) == (None, None, frozenset())
        scope = ['helix', 'shared_mission', frozenset({'deal'})]
        speech.campaign_scope = lambda: tuple(scope)
        first = speech.deck_context(replay.clock.mono())
        assert (first.campaign, first.mission, first.flags) == tuple(scope)
        scope[:] = [None, None, frozenset({'deal', 'reviewed'})]
        second = speech.deck_context(replay.clock.mono())
        assert (second.campaign, second.mission, second.flags) == tuple(scope)
        assert first.flags == frozenset({'deal'})
    finally:
        await speech.close()


async def test_observer_wires_scope_to_the_campaign_service(book, tmp_path):
    app = create_app('x' * 40, tmp_path)
    try:
        campaign, speech = app.state.campaign, app.state.speech
        assert speech.campaign_scope() == (None, None, frozenset())
        campaign.start('helix', 'shared_mission')
        assert speech.campaign_scope() == ('helix', 'shared_mission', frozenset())
    finally:
        await app.state.speech.close()
