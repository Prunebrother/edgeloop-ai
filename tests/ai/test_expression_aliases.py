"""Near-miss expression IDs from the 2026-11 simulation runs resolve to the closest allowed expression."""
import pytest
from companion_ai.expressions import ALIASES, EXPRESSIONS, ExpressionStream, resolve_expression


def scan(text, card=False):
    stream = ExpressionStream(card=card)
    return (stream.feed(text) + stream.finish()).strip(), stream


def test_every_alias_points_at_an_allowed_expression():
    assert set(ALIASES.values()) <= set(EXPRESSIONS) and not set(ALIASES) & set(EXPRESSIONS)


@pytest.mark.parametrize('header,expected', [
    ('[[expression:curious]]', 'focused'), ('[[expression:confident]]', 'proud'), ('[[expression:pride]]', 'proud'),
    ('[[expression:prideful]]', 'proud'), ('[[expression:thoughtful]]', 'focused'), ('[[expression:content]]', 'happy'),
    ('[[expression:reassuring]]', 'comforting'), ('[[expression:practical]]', 'focused'), ('[[expression:Focused]]', 'focused'),
    ('[[expression:composed]]', 'neutral'), ('[[expression:hopeful]]', 'happy'), ('[[expression:bratty]]', 'mischievous'),
    ('[[focused:neutral]]', 'focused'), ('[[happy:125]]', 'happy'),
])
@pytest.mark.parametrize('card', [False, True])
def test_observed_near_misses_resolve(header, expected, card):
    text, stream = scan(header + '\nA quiet line.', card)
    assert text == 'A quiet line.' and stream.expression == expected and stream.valid is True


@pytest.mark.parametrize('header', ['[[expression:banana]]', '[[tone:playful]]', '[[expression]]', '[[unknown:happy]]'])
def test_unknown_ids_still_fall_back_and_stay_hidden(header):
    text, stream = scan(header + 'Hello')
    assert text == 'Hello' and stream.expression is None


def test_the_model_candidate_is_kept_for_diagnostics():
    assert scan('[[expression:curious]]Hi')[1].candidate == 'curious'


def test_resolver_only_reads_the_first_word_of_a_bare_header():
    assert resolve_expression('proud:anything') == 'proud' and resolve_expression('curious:x') is None
