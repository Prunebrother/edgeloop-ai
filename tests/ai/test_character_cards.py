# SPDX-License-Identifier: AGPL-3.0-only
"""Character expansion: shipped content through the normal deck and real compiler."""
import asyncio
from collections import Counter

import pytest

from companion_ai.conversation import character_identity
from companion_ai.event_deck import Eligibility
from tests.ai.test_event_deck_content import (
    ALL, DEFINITION, context, deck, deliver, play_only, prompt, service,
)

PACK = {
    'nova': ('curiosity', 'challenge', 'borrowed-wonder', 'alien-menu', 'chosen-name',
             'human-variable', 'beautiful-error', 'session-mystery', 'unfamiliar-stars',
             'mystery-book', 'research-partner', 'project-autonomy'),
    'daisy': ('production', 'encouragement', 'farm-future', 'recipe-pride', 'gate-debate',
              'prized-volunteer', 'friendly-bargain', 'farm-quiet', 'family-legacy',
              'stubborn-charm', 'pie-diplomacy', 'hat-contest'),
    'evelyn': ('observation-edges', 'observation-trend', 'research-appetite',
               'imagined-seminar', 'human-complexity', 'null-result', 'precision-game',
               'after-hours', 'off-duty-botany', 'research-ambition', 'peer-review', 'composure'),
    'celeste': ('evaluation', 'personal', 'mission-challenge', 'polished-excuse',
                'earned-concession', 'negotiating-silence', 'mission-stakes',
                'quiet-competence', 'public-promise', 'ceremonial-pen', 'reluctant-smile',
                'ambition-wager'),
}
MODELS = dict(zip(PACK, ('nova-narrative-f29-v011:latest', 'daisy-narrative-f29-v014:latest',
                        'evelyn-narrative-f29-v013:latest', 'celeste-narrative-f29-v012:latest')))
IDS = {f'{identity}-{suffix}' for identity, suffixes in PACK.items() for suffix in suffixes}
CARDS = [card for card in DEFINITION.normal if card.id in IDS]
LEGACY_IDS = {f'{identity}-{suffix}' for identity, suffixes in PACK.items() for suffix in suffixes[:2]}
EXPANSION = [card for card in CARDS if card.id not in LEGACY_IDS]


def test_pack_has_twelve_distinct_prompts_each_and_globally_unique_ids():
    assert len(CARDS) == len(IDS) == 48
    assert len({c.brief for c in CARDS}) == 48
    assert Counter(c.audience for c in CARDS) == {identity: 12 for identity in PACK}
    assert len({c.id for c in ALL}) == len(ALL)


@pytest.mark.parametrize('card', EXPANSION, ids=lambda c: c.id)
def test_new_character_cards_need_no_measurements_history_or_memory_permission(card):
    assert card.kind == 'normal' and card.memory == 'none' and card.repeat
    assert card.eligibility == Eligibility(statuses=['RUNNING'])
    target = deck(card.audience)
    assert target._eligible(card, context(signal='missing'))
    for status in ('IDLE', 'PAUSED', 'RAMPDOWN'):
        assert not target._eligible(card, context(status=status))


@pytest.mark.parametrize('state', [{}, {'edges': 2, 'seconds': 600},
                                  {'edges': 5, 'seconds': 1300, 'hr_current': True, 'hr_trend': 'rising'}])
@pytest.mark.parametrize('identity', [*PACK, 'generic'])
def test_full_shuffle_includes_only_own_pack_once_per_cycle(identity, state):
    target = deck(identity)
    ctx = context(**state)
    expected = {c.id for c in DEFINITION.normal
                if c.audience in {'shared', identity} and target._eligible(c, ctx)}
    own = {f'{identity}-{suffix}' for suffix in PACK.get(identity, ())}
    assert set(target._queue) & IDS == own
    assert len(target._queue) == len(set(target._queue))
    # Mid-session decks skip the opening; do not accidentally consume a normal
    # card as setup. Observe this state first to establish milestone baselines.
    target.observe(ctx, 0)
    target._start_done = True
    cycles = []
    for cycle in range(2):
        drawn = []
        for offset in range(len(expected)):
            now = 1 + cycle * len(expected) + offset
            play = target.next_play(ctx, now).play
            assert play.lane == 'normal'
            assert target.next_play(ctx, now).play is None  # one in-flight delivery
            deliver(target, play, now)
            assert target.transition(play.id, 'delivered', now) is False
            drawn.append(play.card.id)
        assert set(drawn) == expected and len(drawn) == len(set(drawn))
        cycles.append(drawn)
    assert cycles[0][-1] != cycles[1][0]
    assert target.snapshot()['counts']['delivered'] == 2 * len(expected)


@pytest.mark.parametrize('identity', PACK)
def test_current_f29_model_selects_its_own_expansion(identity):
    assert character_identity(MODELS[identity]) == identity


@pytest.mark.parametrize('card', EXPANSION, ids=lambda c: c.id)
async def test_expansion_compiles_without_participant_figures_or_story_writes(card):
    r, s, wire, frames = await service(identity=card.audience, edges=5, seconds=900)
    before = list(s.narrative.state['developments'])
    play_only(s, card.id)
    s.pump()
    await s.task
    await asyncio.sleep(0)
    current = prompt(wire)
    assert card.brief in current
    assert 'mention no counts, times or readings' in current
    assert 'Edges this session' not in current and 'Running time:' not in current
    assert s.narrative.state['developments'] == before
    assert len([f for f in frames if f['type'] == 'speech']) == 1


@pytest.mark.parametrize('identity', PACK)
async def test_answered_user_message_is_background_not_a_new_card_request(identity):
    r, s, wire, frames = await service(identity=identity, edges=2, seconds=600)
    prior = 'Choose a fictional café name: Copper Teacup or Velvet Lantern.'
    assert s.request(prior, user=True)['accepted']
    await s.task
    await asyncio.sleep(0)
    for _ in range(90):
        r.step(None, seconds=1)
    play_only(s, next(c.id for c in EXPANSION if c.audience == identity))
    s.pump()
    await s.task
    await asyncio.sleep(0)
    body = next(b for path, b in reversed(wire) if path == '/api/chat')
    # The production last_user policy keeps answered user text in a labelled
    # assistant context turn; it never places it in the current card task.
    assert [m['role'] for m in body['messages']] == ['system', 'assistant', 'user']
    assert body['messages'][-1]['role'] == 'user'
    current = body['messages'][-1]['content']
    assert 'already answered; background only, do not answer it again' in body['messages'][1]['content']
    assert prior in body['messages'][1]['content'] and prior not in current
    assert 'the participant has not just spoken' in current
    assert 'Edges this session' not in current and 'Running time:' not in current
    assert not body.get('tools') and body['think'] is False
    assert not [f for f in frames if f['type'] == 'conversation_error']
    await s.close()



def test_common_inventory_and_fixed_state_draw_proportions():
    assert len([c for c in DEFINITION.normal if c.audience == 'shared']) == 25
    # No conversation history: the follow-up card is ineligible in both states.
    target = deck('nova')
    for ctx, expected in ((context(edges=2, seconds=600, signal='missing'), (11, 12)),
                          (context(edges=2, seconds=600, hr_current=True, hr_trend='rising'), (12, 12))):
        eligible = [c for c in DEFINITION.normal if c.audience in {'shared', 'nova'}
                    and target._eligible(c, ctx)]
        assert (sum(c.audience == 'shared' for c in eligible),
                sum(c.audience == 'nova' for c in eligible)) == expected
