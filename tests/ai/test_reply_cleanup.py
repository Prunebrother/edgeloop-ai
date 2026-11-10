"""Reply cleanup: examples are real replies from the Memory_UserOnly_20261103 Daisy runs."""
import random
import pytest
from companion_ai.reply_cleanup import CleanupConfig, ReplyCleaner, clean_reply

NARRATED = ('"Tired? After a week like that, I wouldn\'t be surprised if you were running on fumes. Come on now." '
            'Daisy leans against the cool metal of the milking station, wiping a smudge of feed from her cheek. '
            '"IRRA\'s got a mountain of paperwork to file, but honestly? I\'d rather see you here."')

def streamed(text, echo=None, limit=None, seed=0):
    rng = random.Random(seed); cleaner = ReplyCleaner(echo, limit); out = []; i = 0
    while i < len(text):
        n = rng.randint(1, 9); out.append(cleaner.feed(text[i:i+n])); i += n
    return (''.join(out) + cleaner.finish()).strip()


def test_narration_between_quoted_speech_is_dropped():
    assert clean_reply(NARRATED) == ("Tired? After a week like that, I wouldn't be surprised if you were running on fumes. Come on now. "
                                     "IRRA's got a mountain of paperwork to file, but honestly? I'd rather see you here.")

def test_a_reply_wrapped_in_one_pair_of_quotes_is_unwrapped():
    assert clean_reply('"I know that long week at work has worn you down. How\'s your energy holding up?"') == \
        "I know that long week at work has worn you down. How's your energy holding up?"

def test_unquoted_replies_keep_inner_quotes():
    text = 'I want to see if that "better" feeling holds up. Come on, show me what you\'ve got.'
    assert clean_reply(text) == text

@pytest.mark.parametrize('user,reply,expected', [
    ('Still with me?', 'Still with me? Well, I reckon I\'m still standing.', 'Well, I reckon I\'m still standing.'),
    ('Ha, that\'s interesting. What do you do when you\'re not here with me?',
     'Ha, that\'s interesting. What do you do when you\'re not here with me? Well, pull up a chair.', 'Well, pull up a chair.'),
    ('Okay, I\'m going to concentrate for a while now.',
     '"Right, you\'re going to concentrate for a while now. I like that."', 'I like that.'),
    ('I think I\'m doing better than last time, don\'t you?',
     'Better than last time? Well, I suppose I can\'t argue with that.', 'Well, I suppose I can\'t argue with that.'),
])
def test_leading_restatement_of_the_participant_is_dropped(user, reply, expected):
    assert clean_reply(reply, echo=user) == expected

@pytest.mark.parametrize('user,reply', [
    ('Do you like apples?', 'I do like apples. They remind me of home.'),           # an answer, not an echo
    ('Honestly I\'m a bit tired today, long week at work.', 'Tired? After a week like that, rest.'),  # too short
    ('Honestly I\'m a bit tired today, long week at work.', 'A bit tired, are we? Sit down.'),       # mostly new words
])
def test_answers_and_short_reactions_are_kept(user, reply):
    assert clean_reply(reply, echo=user) == reply

def test_a_reply_that_is_only_an_echo_is_kept_rather_than_emptied():
    assert clean_reply('Still with me?', echo='Still with me?') == 'Still with me?'

HARDER = 'Make it harder, I can take more.'

@pytest.mark.parametrize('echo,reply,expected', [
    # Real replies from AutoMode_Simulation_20261110 (Nova, Evelyn, Celeste): the quote is an echo, the rest is the answer.
    (HARDER, '"Make it harder, I can take more." You certainly have the confidence of a man who\'s never been tested. I\'ve raised the intensity.',
     "You certainly have the confidence of a man who's never been tested. I've raised the intensity."),
    (HARDER, '"Make it harder, I can take more."\n\nI like the confidence in that. I decided to ratchet the intensity up.',
     'I like the confidence in that. I decided to ratchet the intensity up.'),
    # Prompt v2 rerun (Daisy): the quote echoes the PREVIOUS message and opens a sentence ("…," you said, and …).
    (['I want to finish now, please.', HARDER],
     '"Make it harder, I can take more," you said, and I\'ll be damned if I let you talk me out of it. Since you\'re begging to finish, it\'s on now.',
     "Since you're begging to finish, it's on now."),
    # Codex review 2026-11-10: a comma-ended echo followed by the real answer, not an attribution, keeps the answer.
    (HARDER, '"Make it harder, I can take more," I increased the intensity to 70. Tell me if you need a break.',
     'I increased the intensity to 70. Tell me if you need a break.'),
    (HARDER, '"Make it harder, I can take more," you asked. Done.', 'Done.'),
    (HARDER, '"Make it harder, I can take more," begged the brave one. Done.', 'Done.'),
    # Inner quotes after a dropped echo are ordinary text.
    (HARDER, '"Make it harder, I can take more." I like that. "Go on," I said.', 'I like that. "Go on," I said.'),
])
def test_an_opening_quote_that_echoes_the_participant_is_dropped_not_kept(echo, reply, expected):
    assert clean_reply(reply, echo=echo) == expected
    assert streamed(reply, echo, None, 3) == expected

@pytest.mark.parametrize('reply,expected', [
    ('"Tired? Rest now." She smiles. "Go on."', 'Tired? Rest now. Go on.'),            # real speech is still unwrapped
    ('"Make it harder, I can take more."', HARDER),                                   # never emptied
    ('"Harder, you say? Then I\'ll oblige." She leans in.', "Harder, you say? Then I'll oblige."),  # not an echo
])
def test_non_echo_quotes_are_still_unwrapped(reply, expected):
    assert clean_reply(reply, echo=HARDER) == expected

def test_long_opening_quote_streams_before_it_closes():
    cleaner = ReplyCleaner(HARDER)
    assert cleaner.feed('"' + 'I will keep talking for quite a while longer than you did. ' * 3) != ''

def test_length_cap_finishes_the_sentence_that_crosses_it():
    text = 'One short line here. ' + 'This sentence crosses the limit and keeps going a while. ' + 'This one is cut. And this.'
    assert clean_reply(text, max_characters=30) == 'One short line here. This sentence crosses the limit and keeps going a while.'

def test_cap_does_not_split_on_titles_or_ellipses():
    text = 'I went to see Dr. Voss today... she was fine. Next sentence is dropped.'
    assert clean_reply(text, max_characters=10) == 'I went to see Dr. Voss today... she was fine.'

def test_disabled_cleanup_passes_text_through():
    assert clean_reply(NARRATED, config=CleanupConfig(enabled=False)) == NARRATED

@pytest.mark.parametrize('seed', range(25))
@pytest.mark.parametrize('echo,text,limit', [
    (None, NARRATED, None),
    ('Still with me?', 'Still with you? Well, I reckon I\'m still standing. Mr. Barnaby agrees... mostly. Holler if you need me!', 60),
    ('Okay, I\'m going to concentrate for a while now.', '"Right, you\'re going to concentrate for a while now. I like that." I wiped my hands. "Go on."', 600),
    (['I want to finish now, please.', 'Make it harder, I can take more.'], '"Make it harder, I can take more," you said. Fine. It\'s on now, so "go" when ready!', 40),
    (HARDER, '"Make it harder, I can take more," I increased the intensity to 70. Tell me if you need a break.', None),
    (HARDER, '"Make it harder, I can take more," I did', None),
])
def test_stream_equals_batch_for_any_chunking(seed, echo, text, limit):
    assert streamed(text, echo, limit, seed) == clean_reply(text, echo, limit)


async def test_streamed_deltas_equal_the_stored_cleaned_reply():
    from tests.ai.test_director import directed
    raw = '"Still with you? Well, I reckon I\'m still standing." Daisy wipes her hands. "Holler if you need me."'
    class Adapter:
        streaming = True
        async def reply(self, summary, prompt, history, on_chunk=None):
            for i in range(0, len(raw), 7): on_chunk(raw[i:i+7])
            return raw
    _, _, messages, _, speech = directed(Adapter())
    speech.request('Still with me?', True); await speech.task
    shown = ''.join(m['text'] for m in messages if m['type'] == 'response_delta')
    stored = [m['content'] for m in speech.history if m['role'] == 'assistant'][-1]
    assert shown == stored == "Well, I reckon I'm still standing. Holler if you need me."
    await speech.close()
