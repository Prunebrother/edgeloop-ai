# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded private history rules: saved flags only and no browser-bound narrative leaks."""
import json
from copy import deepcopy
import pytest
from companion_ai.campaign import Book, Campaign, CampaignRecord, MissionNarrative
from tests.ai.test_campaign_when import (CID, MODEL, YES, NO, definition, narrative, service, begin, block)
from tests.ai.test_campaign_chapter2 import tick

FIRST = 'PRIVATE_HISTORY_FIRST'
SECOND = 'PRIVATE_HISTORY_SECOND'
FALLBACK = 'PRIVATE_HISTORY_FALLBACK'


def story(rules):
    text = narrative(); text['missions']['intake']['story_so_far'] = rules; return text


@pytest.mark.parametrize('rules', [
    [{'text': ''}], [{'text': ' '}], [{'text': 'x' * 301}], [{'text': 'two\nlines'}],
    [{'text': 'two\rlines'}], [{'text': 'two\u2028lines'}], [{'text': 'unsafe [[token]]'}],
    [{'text': 'null\x00'}], [{'text': 'fallback first'}, {'when': YES, 'text': 'Conditional'}],
    [{'when': YES, 'text': 'x'}] * 9,
])
def test_invalid_history_rules(rules):
    with pytest.raises(ValueError): MissionNarrative.model_validate(story(rules)['missions']['intake'])


@pytest.mark.parametrize('condition', [{'flag': 'unknown', 'eq': 'analyst'}, {'flag': 'cover', 'eq': 'unknown'}])
def test_history_conditions_checked_at_book_load(tmp_path, condition):
    folder = tmp_path / CID; folder.mkdir(); (folder / 'campaign.json').write_text(json.dumps(definition()))
    (folder / 'narrative.json').write_text(json.dumps(story([{'when': condition, 'text': FIRST}])))
    book = Book.load(tmp_path)
    assert not book.campaigns and len(book.errors) == 1


@pytest.mark.parametrize('flags,rules,expected', [
    ({'cover': 'analyst'}, [{'when': YES, 'text': FIRST}, {'when': YES, 'text': SECOND}, {'text': FALLBACK}], FIRST),
    ({'cover': 'volunteer'}, [{'when': YES, 'text': FIRST}, {'when': NO, 'text': SECOND}, {'text': FALLBACK}], SECOND),
    ({}, [{'when': YES, 'text': FIRST}, {'text': FALLBACK}], FALLBACK),
    ({}, [{'when': YES, 'text': FIRST}], None),
    ({}, [], None),
])
def test_first_match_fallback_or_no_line(tmp_path, flags, rules, expected):
    svc = service(tmp_path, text=story(rules), flags=flags); r = begin(svc)
    lines = svc.model_context(MODEL, r)['text'].splitlines()
    assert [line for line in lines if line.startswith('Story so far:')] == ([] if expected is None else ['Story so far: ' + expected])
    # Regardless of rule count the authored addition grows the brief by at most one line.
    svc.book.narratives[CID].missions['intake'].story_so_far = []
    assert len(lines) - len(svc.model_context(MODEL, r)['text'].splitlines()) == (expected is not None)


def test_history_uses_saved_flags_not_current_choice_overlay(tmp_path):
    svc = service(tmp_path, text=story([{'when': YES, 'text': FIRST}, {'when': NO, 'text': SECOND}]), flags={'cover': 'volunteer'})
    r = begin(svc); svc.answer('cover', 'analyst', r, MODEL)
    assert svc.story_flags(svc.book.campaign(CID), svc.attempt)['cover'] == 'analyst'
    assert 'Story so far: ' + SECOND in svc.model_context(MODEL, r)['text']
    assert FIRST not in svc.model_context(MODEL, r)['text']
    assert svc.record(CID).flags == {'cover': 'volunteer'}


def test_inherited_history_and_private_completed_brief(tmp_path):
    data = definition(); data.update(requires_campaigns=['asterion_initiative'], inherits_flags_from=['asterion_initiative'])
    svc = service(tmp_path, data, story([{'when': {'flag': 'asterion_initiative.cover', 'eq': 'analyst'}, 'text': FIRST}]))
    source = deepcopy(definition()); source['id'] = 'asterion_initiative'; svc.book.campaigns.append(Campaign.model_validate(source))
    svc.progress.campaigns['asterion_initiative'] = CampaignRecord(flags={'cover': 'analyst'})
    r = begin(svc); assert 'Story so far: ' + FIRST in svc.model_context(MODEL, r)['text']
    svc.answer('cover', 'analyst', r, MODEL); svc.observe(tick('s', 1, edges=2), [], MODEL)
    assert FIRST not in svc.model_context(MODEL, tick('s', 2))['text']


def test_history_never_leaks_in_any_browser_message_of_a_run(tmp_path):
    rules = [{'when': YES, 'text': FIRST}, {'when': NO, 'text': SECOND}, {'text': FALLBACK}]
    svc = service(tmp_path, text=story(rules), flags={'cover': 'analyst'})
    outgoing = [svc.state(), svc.mission_text(CID, 'intake'), svc.chapter_text(CID, 'one')]
    svc.start(CID, 'intake'); outgoing.append(svc.state())
    r = tick('s', 0); outgoing.extend(svc.observe(r, [], MODEL)); outgoing.append(svc.progress_update(r, MODEL))
    assert FIRST in svc.model_context(MODEL, r)['text']
    outgoing.extend(svc.answer('cover', 'analyst', r, MODEL)); outgoing.extend(svc.observe(tick('s', 1, edges=2), [], MODEL))
    outgoing.extend([svc.state(), svc.mission_text(CID, 'intake'), svc.chapter_text(CID, 'one')])
    types = {message['type'] for message in outgoing}
    assert {'campaign_state', 'mission_text', 'chapter_text', 'campaign_progress', 'mission_milestone', 'mission_result'} <= types
    def walk(value):
        if isinstance(value, dict):
            assert 'story_so_far' not in value
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
        elif isinstance(value, str): assert all(private not in value for private in [FIRST, SECOND, FALLBACK])
    for message in outgoing: walk(message)


def test_history_ignores_route_overlay_while_completion_save_is_pending(tmp_path, monkeypatch):
    from companion_ai.campaign import StorySoFar
    from tests.ai.test_campaign_routes import service as route_service, take, begin as route_begin
    svc = route_service(tmp_path); take(svc, 'escape')
    svc.book.narratives[CID].missions['intake'].story_so_far = [
        StorySoFar(when={'flag': 'route', 'eq': 'release'}, text=SECOND),
        StorySoFar(when={'flag': 'route', 'eq': 'escape'}, text=FIRST)]
    route_begin(svc, 'replay')
    monkeypatch.setattr(svc.store, 'write', lambda *a: (_ for _ in ()).throw(OSError('full')))
    r = tick('replay', 1, edges=1, orgasms=1); svc.observe(r, [], MODEL)
    assert svc.attempt.pending and svc.story_flags(svc.book.campaign(CID), svc.attempt)['route'] == 'release'
    text = svc.model_context(MODEL, r)['text']
    assert 'Story so far: ' + FIRST in text and SECOND not in text
