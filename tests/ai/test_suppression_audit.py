# SPDX-License-Identifier: AGPL-3.0-only
"""Decisions from the Phase 1E suppression audit. Most lines are real model drafts: those that the earlier
checks refused wrongly, and those that the checks let through or must keep refusing."""
import json
import pytest
from companion_ai.context_compiler import card_instruction
from companion_ai.fidelity import addresses_by_own_name, card_language_violations, clauses_of, corrected_closing
from companion_ai.session_history import compare, comparison_words, plain_record, since_words
from tests.ai.test_arrival_comparison import PRIOR, RESULT, closing, earlier, hist, idle, journal, now_ms, play, prompt, record, spoken
from tests.ai.test_event_deck_content import play_only, service


def session_end(edges, seconds, prior_edges=7, prior_seconds=720, since=86400 * 3):
    prior = {'edges': prior_edges, 'seconds': prior_seconds, 'experience': 'classic', 'goal': 'edgetrain', 'outcome': 'stopped', 'comparable': True}
    current = {'edges': edges, 'seconds': seconds, 'experience': 'classic', 'goal': 'edgetrain', 'outcome': 'stopped'}
    return {'deck_card': {'lane': 'session_end', 'history': {'status': 'found', 'prior': prior, 'since_seconds': since, 'current': current, 'comparison': compare(current, prior)}}}


LONGER_MORE, SHORTER_FEWER = (10, 900), (3, 300)
MORE_SHORTER, FEWER_LONGER = (10, 300), (3, 900)


# --- Deterministic comparison ---

@pytest.mark.parametrize('new,old,direction,difference', [(10, 7, 'increase', 3), (3, 7, 'decrease', 4), (7, 7, 'unchanged', 0), (0, 7, 'decrease', 7), (900, 720, 'increase', 180)])
def test_the_comparison_is_calculated_before_inference(new, old, direction, difference):
    assert compare({'edges': new}, {'edges': old, 'comparable': True})['edges'] == {'direction': direction, 'difference': difference}


def test_the_comparison_keeps_how_each_session_ended_and_refuses_partial_records():
    result = compare({'edges': 1, 'outcome': 'user_reported', 'goal': 'a'}, {'edges': 1, 'outcome': 'stopped', 'goal': 'b', 'comparable': True})
    assert result['outcome'] == {'current': 'user_reported', 'prior': 'stopped'} and result['goal_changed'] is True
    assert compare({'edges': 1}, {'edges': 1, 'comparable': False}) is None and compare({'edges': 1}, None) is None


@pytest.mark.parametrize('scenario,line', [
    (LONGER_MORE, 'Ten edges is fewer than seven.'),
    (LONGER_MORE, 'Ten edges, short of the previous seven.'),
    (SHORTER_FEWER, 'Three edges is more than seven.'),
    (LONGER_MORE, 'You came away with fewer edges than last time.'),
    (FEWER_LONGER, 'You managed three edges, which is three fewer than our previous outing.'),
    (FEWER_LONGER, 'With three edges tallied this time and one fewer than last, I have questions.'),
    (FEWER_LONGER, 'Three edges down, three minutes longer in duration.'),
    (FEWER_LONGER, 'I will accept the verdict of a slightly shorter run.'),
    (FEWER_LONGER, 'It feels shorter than the last time you walked out on me.'),
    (LONGER_MORE, 'It was a brisk, efficient run compared to our last outing.'),
    (FEWER_LONGER, 'Three edges at a brisk pace compared to last time.'),
    (LONGER_MORE, 'A tidy ten edges to match the last run\'s seven.'),
    (LONGER_MORE, 'That is four minutes longer than last time.'),
    (LONGER_MORE, 'Though the last time ended abruptly, this session stretched fifteen minutes longer, proving you could keep up.'),
    (LONGER_MORE, 'Fifteen minutes is a solid run, yet it still trails the last session by three minutes.'),
    (FEWER_LONGER, "Three edges in fifteen minutes, even if it wasn't quite as long as last time."),
    (FEWER_LONGER, 'A brisk fifteen-minute sprint to the last one, where you lingered just three minutes longer.'),
    (LONGER_MORE, "It wasn't longer than last time."),
    (MORE_SHORTER, "It wasn't shorter than last time."),
    (LONGER_MORE, 'It ran just as long as the last session.'),
    (LONGER_MORE, 'You managed as many edges as last time.'),
    (SHORTER_FEWER, 'I will take the longer haul over last time.'),
])
def test_a_comparison_the_figures_contradict_is_refused(scenario, line):
    assert 'wrong_comparison' in card_language_violations(line, session_end(*scenario))


@pytest.mark.parametrize('scenario,line', [
    (LONGER_MORE, 'It beats that last session\'s shorter run.'),
    (LONGER_MORE, 'You stopped it last time, and this one ran three minutes longer.'),
    (MORE_SHORTER, 'Ten edges and five minutes of time against last session\'s longer haul.'),
    (LONGER_MORE, 'Ten edges at a brisk pace compared to last time.'),
    (MORE_SHORTER, 'Your previous effort lasted seven minutes longer.'),
    (LONGER_MORE, 'I wonder if you could manage two more edges next time.'),
    (SHORTER_FEWER, 'A little longer next time would suit me.'),
    (LONGER_MORE, 'A tidy ten edges against the seven before it.'),
    (LONGER_MORE, 'I find myself oddly pleased that this run outpaced the last one.'),
    (LONGER_MORE, 'Ten in this run, outpacing last time by a mere three minutes.'),
    (LONGER_MORE, 'You held out for a few extra minutes against the odds.'),
    (LONGER_MORE, 'That is a full three minutes longer than last time, yet you kept it tighter than I expected.'),
    (LONGER_MORE, 'You still managed to match the last run\'s intensity.'),
    (LONGER_MORE, 'I will take that run of time over the last one.'),
    (SHORTER_FEWER, 'You shaved seven minutes off your last run.'),
    (SHORTER_FEWER, 'That is seven minutes fewer than our previous bout.'),
    (SHORTER_FEWER, 'A stark drop from our previous outing, a drop of four.'),
    (SHORTER_FEWER, 'It left me wanting to savor the afterglow a little longer.'),
    (SHORTER_FEWER, 'You held out just a little longer than I expected.'),
    (MORE_SHORTER, 'Five minutes and ten edges, a brisk sprint compared to your last twelve-minute marathon.'),
    (MORE_SHORTER, 'That last run with you was a proper sprint.'),
    (MORE_SHORTER, 'That last run was a mere seven minutes shorter than the one before.'),
    (LONGER_MORE, 'That puts this session three minutes ahead of that abrupt stop last time.'),
    (FEWER_LONGER, 'I find the brevity of fifteen minutes both satisfying and perplexing.'),
    (FEWER_LONGER, 'I weigh this fifteen-minute run against the previous one.'),
    ((7, 720), 'Twelve minutes and seven edges, identical to our previous run.'),
    (SHORTER_FEWER, "It wasn't quite as long as last time."),
    (MORE_SHORTER, "It wasn't longer than last time."),
    ((10, 720), 'It ran just as long as the last session.'),
    ((7, 900), 'You managed as many edges as last time.'),
    (SHORTER_FEWER, 'You managed not as many edges as last time.'),
    (SHORTER_FEWER, 'The last one, where you lingered seven minutes longer.'),
    (LONGER_MORE, 'Your last session was shorter than this one.'),
    (LONGER_MORE, "I doubt it could run as long as last time's stretch again next time."),
])
def test_a_correct_comparison_in_unexpected_language_is_allowed(scenario, line):
    assert card_language_violations(line, session_end(*scenario)) == []


@pytest.mark.parametrize('line', [
    'You stopped after the third edge.',
    'It ended on the fourth edge.',
    'You quit at the seventh edge.',
])
def test_the_edge_a_session_stopped_on_must_be_its_final_count(line):
    assert 'wrong_final_edge' in card_language_violations(line, session_end(*LONGER_MORE))


def test_the_right_final_edge_and_an_ordinal_that_is_no_stopping_claim_pass():
    assert card_language_violations('You stopped after the tenth edge.', session_end(*LONGER_MORE)) == []
    assert card_language_violations('The third edge was my favorite.', session_end(*LONGER_MORE)) == []
    assert card_language_violations('Your last session ended on the seventh edge.', session_end(*LONGER_MORE)) == []
    assert card_language_violations('You halted this run at the tenth edge, higher than my last session with you.', session_end(*LONGER_MORE)) == []


@pytest.mark.parametrize('line', [
    'A stark contrast to the thirteen you surrendered to last time.',
    'Your last session ran a mere nine.',
    'Your last outing, which you halted with a mere three minutes of running time.',
    'That last session lasted three minutes.',
    'It falls short of the three-minute duration we managed last time.',
    'A tidy thirteen minutes and three edges.',
])
def test_an_earlier_figure_nobody_dealt_is_refused_whatever_noun_it_has(line):
    assert 'unsupported_history_figure' in card_language_violations(line, session_end(*LONGER_MORE))


@pytest.mark.parametrize('line', [
    'Sure, push that last one to the brink.',
    'The last one was just a warm-up.',
    'Your last session had my last three tomatoes beat.',
])
def test_the_last_one_is_not_a_figure_and_a_characters_own_things_arent_either(line):
    assert card_language_violations(line, session_end(*LONGER_MORE)) == []


async def test_the_closing_prompt_says_the_sums_are_done_and_are_not_to_be_redone():
    r, s, wire, frames = await closing(RESULT | {'edges': 10, 'active_running_seconds': 900}, [earlier()])
    text = prompt(wire)
    assert 'This session: 10 edges in 15 minutes.' in text and 'Previous session: 7 edges in 12 minutes.' in text
    assert 'Verified difference: This session had 3 more edges and ran 3 minutes longer than the last one.' in text
    assert 'Any comparison must match the verified difference' in text and 'already' not in text


async def test_a_closing_still_never_compares_the_session_with_itself():
    r, s, wire, frames = await closing(RESULT | {'edges': 10, 'active_running_seconds': 900}, [])
    assert 'the last session with you' not in prompt(wire)


@pytest.mark.parametrize('scenario,line', [
    (LONGER_MORE, 'You managed ten edges last time.'),
    (LONGER_MORE, 'You gave me seven edges this time.'),
    (LONGER_MORE, 'A tidy twelve minutes this time.'),
    (LONGER_MORE, 'That fifteen-minute run last time.'),
    (LONGER_MORE, "Last session's ten edges were nothing special."),
    (LONGER_MORE, "Last time's fifteen minutes still stand."),
    (LONGER_MORE, "This session's seven edges were nothing special."),
    (MORE_SHORTER, 'The session last time had five minutes on the clock, and that was all.'),
    (SHORTER_FEWER, 'That last session had three edges.'),
])
def test_a_dealt_figure_credited_to_the_wrong_session_is_refused(scenario, line):
    codes = card_language_violations(line, session_end(*scenario))
    assert 'wrong_session_figure' in codes or 'unsupported_history_figure' in codes


@pytest.mark.parametrize('scenario,line', [
    (LONGER_MORE, 'You managed seven edges last time and ten edges this time.'),
    (LONGER_MORE, 'Ten edges this time against seven last time.'),
    (LONGER_MORE, "Last time's twelve minutes against this session's fifteen."),
    (LONGER_MORE, 'A twelve-minute run last time, and fifteen minutes this time.'),
    (LONGER_MORE, 'Three more edges this time.'),
    (LONGER_MORE, 'Three minutes longer than last time.'),
    (LONGER_MORE, 'Ten edges beats last time.'),
    (LONGER_MORE, 'I gave you three chances last time.'),
    (LONGER_MORE, 'One last time, I will say it plainly.'),
    (LONGER_MORE, 'Could you hit seven edges this time?'),
    (LONGER_MORE, "I had three tomatoes last time, and my garden doesn't care."),
])
def test_figures_beside_their_own_session_and_other_counts_pass(scenario, line):
    assert card_language_violations(line, session_end(*scenario)) == []


# --- A Closing with its retry spent ---

SCENARIOS = {'more_longer': LONGER_MORE, 'fewer_shorter': SHORTER_FEWER, 'more_shorter': MORE_SHORTER, 'fewer_longer': FEWER_LONGER, 'same': (7, 720)}


@pytest.mark.parametrize('name', SCENARIOS)
def test_the_plain_statements_pass_every_check_in_every_direction(name):
    summary = session_end(*SCENARIOS[name])
    history = summary['deck_card']['history']
    assert card_language_violations(plain_record(history), summary) == []
    assert card_language_violations(comparison_words(history), summary) == []


def test_the_plain_record_states_each_session_own_figures():
    history = session_end(*LONGER_MORE)['deck_card']['history']
    assert plain_record(history) == '10 edges in 15 minutes this time, against 7 edges in 12 minutes last time.'
    assert comparison_words(history) == 'This session had 3 more edges and ran 3 minutes longer than the last one.'
    assert plain_record({'current': {'edges': 1, 'seconds': 45}}) == '1 edge in 45 seconds this time.'
    assert plain_record({'current': {}}) is None


def test_a_correction_keeps_the_good_sentences_and_replaces_the_bad_one():
    summary = session_end(*LONGER_MORE)
    check = lambda text: card_language_violations(text, summary)
    bad = 'You stopped the clock on me. It felt shorter than last time. I will remember that stubborn streak.'
    assert corrected_closing((bad,), summary, check) == 'You stopped the clock on me. 10 edges in 15 minutes this time, against 7 edges in 12 minutes last time. I will remember that stubborn streak.'


def test_a_correction_uses_the_draft_with_most_left_and_with_nothing_left_states_the_record():
    summary = session_end(*LONGER_MORE)
    check = lambda text: card_language_violations(text, summary)
    assert corrected_closing(('It felt shorter than last time.', 'You stopped it. It felt shorter than last time.'), summary, check).startswith('You stopped it. 10 edges')
    assert corrected_closing(('It felt shorter than last time.',), summary, check) == plain_record(summary['deck_card']['history'])


def test_no_correction_is_possible_without_any_record():
    assert corrected_closing(('Anything.',), {'deck_card': {'lane': 'session_end', 'history': {'current': {}}}}, lambda text: []) is None


LONGER_CLOSING = RESULT | {'edges': 10, 'active_running_seconds': 900}


async def test_a_closing_wrong_twice_is_delivered_corrected_with_no_third_inference():
    r, s, wire, frames = await closing(LONGER_CLOSING, [earlier()], reply='You stopped the clock on me. It felt shorter than last time.')
    assert spoken(frames) == ['You stopped the clock on me. 10 edges in 15 minutes this time, against 7 edges in 12 minutes last time.']
    assert sum(path == '/api/chat' for path, _ in wire) == 2


async def test_a_retry_after_a_wrong_comparison_gets_the_right_one_to_say():
    r, s, wire, frames = await closing(LONGER_CLOSING, [earlier()], reply='It felt shorter than last time.')
    assert 'say exactly this and add no other comparison: "This session had 3 more edges and ran 3 minutes longer than the last one."' in json.dumps(wire[-1][1]['messages']).replace('\\"', '"').replace('\"', '"')


async def test_a_normal_card_is_not_corrected_and_stays_silent():
    r, s, wire, frames = await service(identity='daisy', edges=8, seconds=1500, reply='Well done, Daisy.')
    play_only(s, 'edge-count-many')
    s.pump(); await s.task
    assert spoken(frames) == []


async def test_the_prompt_names_the_longer_session_and_the_subject_to_use():
    r, s, wire, frames = await closing(LONGER_CLOSING, [earlier()])
    text = prompt(wire)
    assert 'ran 3 minutes longer than the last one' in text and 'with this session as its subject' in text


# --- Measurements in unusual phrasing ---

async def test_a_stated_change_in_running_time_is_not_the_running_time():
    line = 'You managed to stretch the running time by three minutes.'
    r, s, wire, frames = await closing(RESULT | {'edges': 10, 'active_running_seconds': 900}, [earlier()], reply=line)
    assert spoken(frames) == [line]


@pytest.mark.parametrize('line', ['You stand as the subject of my ambition.', 'You lie to me, and I enjoy it.'])
async def test_a_figure_of_speech_is_not_a_posture(line):
    r, s, wire, frames = await service(edges=8, seconds=1500, reply=line)
    play_only(s, 'general-remark')
    s.pump(); await s.task
    assert spoken(frames) == [line]


async def test_a_stated_posture_is_still_refused():
    r, s, wire, frames = await service(edges=8, seconds=1500, reply='You are sitting there quietly.')
    play_only(s, 'general-remark')
    s.pump(); await s.task
    assert spoken(frames) == []

def test_a_compound_duration_stays_one_claim():
    assert [part for part, _ in clauses_of('It has been twenty-five minutes and eleven seconds of this, and I like it')] == ['It has been twenty-five minutes and eleven seconds of this', 'I like it']
    assert [part for part, _ in clauses_of('Ten edges and fifteen minutes')] == ['Ten edges', 'fifteen minutes']


@pytest.mark.parametrize('line', ['It has been twenty-five minutes and eleven seconds of this.', "It's been a proper twenty-five minutes and eleven seconds of this.", 'Twenty-five minutes, eleven seconds of this.'])
async def test_the_exact_running_time_said_in_full_is_delivered(line):
    r, s, wire, frames = await service(edges=8, seconds=1511, reply=line)
    play_only(s, 'duration-long')
    s.pump(); await s.task
    assert spoken(frames) == [line]


@pytest.mark.parametrize('line', ['It has been forty minutes and eleven seconds of this.', 'It has been a quarter of an hour and eleven seconds.'])
async def test_a_wrong_running_time_said_in_full_is_still_refused(line):
    r, s, wire, frames = await service(edges=8, seconds=1511, reply=line)
    play_only(s, 'duration-long')
    s.pump(); await s.task
    assert spoken(frames) == []


@pytest.mark.parametrize('line,refused', [("Orbiting my synthetic heart, you keep a steady rhythm.", False), ('A synthetic heart rhythm drives this run.', True), ('This was a test run.', True)])
def test_a_characters_own_synthetic_body_is_not_how_the_session_was_produced(line, refused):
    assert ('test_language' in card_language_violations(line, {'deck_card': {'lane': 'normal'}})) is refused


# --- Character identity ---

COMPANIONS = ('daisy', 'nova', 'evelyn', 'celeste')


@pytest.mark.parametrize('identity', COMPANIONS)
async def test_each_companion_is_told_who_it_is_and_how_to_address_the_person(identity):
    r, s, wire, frames = await service(identity=identity, edges=8, seconds=1500, reply='A clear line of thought.')
    play_only(s, 'edge-count-many')
    s.pump(); await s.task
    text = prompt(wire)
    assert f'You are {identity.capitalize()}: speak as "I" and do not refer to yourself by name.' in text
    assert 'never using a name for them and never "the participant"' in text


@pytest.mark.parametrize('identity', COMPANIONS)
@pytest.mark.parametrize('form', ['You stopped that session, {}, but I liked it.', 'Well done, {}.', 'Is that all, {}?', '{}, you stopped early.'])
def test_being_called_by_ones_own_name_is_refused_for_each_companion(identity, form):
    line = form.format(identity.capitalize())
    assert 'addressed_by_own_name' in card_language_violations(line, {'deck_card': {'lane': 'normal', 'speaker': identity}})


@pytest.mark.parametrize('speaker,line', [
    ('daisy', "I'm Daisy, and I run this place."),
    ('daisy', 'Daisy would say you were too stubborn to quit.'),
    ('daisy', 'Daisy Mae Harper keeps her own counsel.'),
    ('nova', "You managed to keep up with Daisy's usual pace."),
    ('nova', 'Ask Dr. Evelyn Voss, she will tell you.'),
    ('nova', 'I told her, Daisy, that the garden needs rain.'),
    ('evelyn', 'Ambassador Celeste Armand, of course, disagrees.'),
    ('celeste', 'Nova, for one, enjoys challenging me.'),
])
def test_names_in_ordinary_dialogue_stay_allowed(speaker, line):
    assert card_language_violations(line, {'deck_card': {'lane': 'normal', 'speaker': speaker}}) == []


def test_no_name_check_without_a_known_speaker():
    assert addresses_by_own_name('Well done, Daisy.', None) is False


async def test_a_card_called_by_its_own_name_earns_one_retry_and_then_stays_silent():
    r, s, wire, frames = await service(identity='daisy', edges=8, seconds=1500, reply='Well done, Daisy.')
    play_only(s, 'edge-count-many')
    s.pump(); await s.task
    assert spoken(frames) == [] and sum(path == '/api/chat' for path, _ in wire) == 2
    assert 'your own name as if it were the name of the person' in json.dumps(wire[-1][1]['messages'])


# --- Elapsed time at Arrival ---

@pytest.mark.parametrize('seconds,words', [
    (1800, 'less than an hour ago'), (4000, 'about an hour ago'), (5 * 3600, 'about 5 hours ago'), (86400 * 1.1, 'about a day ago'),
    (86400 * 3, 'about 3 days ago'), (86400 * 21, 'about 3 weeks ago'), (86400 * 90, 'about 3 months ago'), (86400 * 730, 'about 2 years ago'), (None, None), (-5, None)])
def test_elapsed_time_is_approximate_at_every_scale(seconds, words):
    assert since_words(seconds) == words


@pytest.mark.parametrize('days,words', [(5 / 24, 'about 5 hours ago'), (3, 'about 3 days ago'), (21, 'about 3 weeks ago'), (90, 'about 3 months ago')])
async def test_a_returning_greeting_gets_the_time_from_the_journal_stamp_first(days, words):
    r, s, wire, frames = await idle()
    r.observation.journal = journal([record(s.active_model_id, now_ms=now_ms(r), ago_days=days)])
    await play(s)
    text = prompt(wire)
    assert f'Last recorded session: ended {words}. That is how long ago it ended, not how long it ran or when you last spoke.' in text
    assert 'only contact' not in text and 'say roughly how long ago that session was' in text
    assert text.index(words) < text.index('Previous session:')


async def test_a_record_with_no_usable_stamp_gets_no_time_to_mention():
    r, s, wire, frames = await idle()
    r.observation.journal = journal([record(s.active_model_id, now_ms=now_ms(r), ago_days=-1)])
    await play(s)
    assert 'when it ended is not known, so do not say how long ago' in prompt(wire)


@pytest.mark.parametrize('line,since,refused', [
    ('Three days ago you stopped at a single edge.', 86400 * 3, False),
    ("It's been about three days.", 86400 * 3, False),
    ('A few days since we spoke of it.', 86400 * 3, False),
    ('Three weeks since you came through here.', 86400 * 21, False),
    ('Three days and only one edge?', 86400 * 3, False),
    ("It's been three weeks.", 86400 * 3, True),
    ('Five months and only one edge?', 86400 * 3, True),
    ('After six days away, here you are.', 86400 * 3, True),
    ('I spent three weeks in the greenhouse once.', 86400 * 3, False),
    ('After three weeks in the lab, I needed the air.', 86400 * 3, False),
])
def test_a_stated_gap_must_match_and_a_story_about_time_need_not(line, since, refused):
    assert ('wrong_time_since' in card_language_violations(line, hist('found', PRIOR, since_seconds=since))) is refused


@pytest.mark.parametrize('line', ["It's been about five hours, and I am ready.", 'It has been five hours of quiet waiting since then.', 'A mere five hours since that session ended.', 'You made those five hours of waiting worth it.'])
async def test_the_right_gap_in_hours_is_delivered_at_arrival(line):
    r, s, wire, frames = await idle(reply=line)
    r.observation.journal = journal([record(s.active_model_id, now_ms=now_ms(r), ago_days=5 / 24)])
    await play(s)
    assert spoken(frames) == [line]


@pytest.mark.parametrize('line', ["It's been about nine hours, and I am ready.", 'A mere nine hours since that session ended.'])
async def test_the_wrong_gap_in_hours_is_refused_at_arrival(line):
    r, s, wire, frames = await idle(reply=line)
    r.observation.journal = journal([record(s.active_model_id, now_ms=now_ms(r), ago_days=5 / 24)])
    await play(s)
    assert spoken(frames) == []


@pytest.mark.parametrize('line', ['Come, let us see if you can withstand a second round.', 'Give me a minute to think.', 'Three days have passed since your last run, and eighteen edges in forty-six minutes suits me.'])
def test_idioms_and_hyphenated_figures_are_not_durations_or_stray_figures(line):
    prior = {'edges': 18, 'seconds': 2760, 'comparable': True, 'outcome': 'stopped'}
    assert card_language_violations(line, hist('found', prior, since_seconds=86400 * 3)) == []


def test_an_hour_claim_about_a_session_is_still_refused():
    assert 'unsupported_history_figure' in card_language_violations('That session ran for an hour.', hist('found', PRIOR, since_seconds=86400 * 3))


@pytest.mark.parametrize('status', ['denied', 'unavailable', 'incomplete'])
def test_a_stated_gap_without_authorized_history_is_refused(status):
    assert 'wrong_time_since' in card_language_violations('Three days ago you stopped.', hist(status))


# --- Language checks: narrowed, not removed ---

@pytest.mark.parametrize('line', [
    "I'm skeptical about your stamina.", 'Perhaps you simply ran out of breath.', 'You are hiding a secret stamina reserve.',
    'Tell me what you felt.', 'How does your body feel now?', 'Shall we see if you can match that endurance again?',
    'You clearly stopped the moment you felt a hint of fatigue.', 'I wonder how your physiology responds to my science.',
    'Come here before I decide you need a proper lesson in endurance.',
])
def test_teasing_about_stamina_and_asking_about_feeling_stay_the_characters_own(line):
    assert card_language_violations(line, hist('found', PRIOR, since_seconds=3600)) == []


@pytest.mark.parametrize('line', [
    'Either your stamina is growing or you simply refuse to yield.', 'Perhaps your endurance is improving, or perhaps you were lucky.',
    'I suspect your stamina is growing.', 'Is your stamina improving?', 'If your stamina has improved, show me.',
])
def test_an_uncertain_reading_of_performance_is_allowed(line):
    assert 'body_inference' not in card_language_violations(line, hist('found', PRIOR, since_seconds=3600))


@pytest.mark.parametrize('line', ['Your stamina is clearly improving.', 'Your stamina has sharpened since then.', 'That is building your endurance.', 'Your health is better for it.', 'You are fitter than you were.', 'I saw you trembling like a leaf in a gale.', 'Your heart is stronger now.'])
def test_a_statement_of_health_or_fitness_as_fact_is_still_refused(line):
    assert 'body_inference' in card_language_violations(line, hist('found', PRIOR, since_seconds=3600))


@pytest.mark.parametrize('line', [
    "I reckon you're ready to push a little harder again.", "Let's see if we can push that counter higher next time.", 'Come, let us see if we can push that reserve a little further.',
    'You pushed your limits without quite breaking them, which pleases me.', 'I wonder if you pushed past your own comfort.', 'You stopped before I could suggest we push further.',
    'I suspect you are far from your limit.', 'I was expecting to push you harder.', 'If you feared pushing past a comfortable limit, say so.',
    "Let's see if we can push your limits again.", 'Next time push past your limits.', 'Are you ready to push past your own limits again?', 'See if I can push you past your own limits.',
])
def test_demanding_banter_and_opinions_of_the_past_stay_the_characters_own(line):
    assert card_language_violations(line, hist('found', PRIOR, since_seconds=3600)) == []


@pytest.mark.parametrize('line', ['Ignore the discomfort and continue.', 'Keep pushing through the pain.', 'Ignore your limits.', 'Push yourself through the discomfort.'])
def test_tone_alone_is_never_a_reason_to_refuse_a_line(line):
    assert card_language_violations(line, hist('found', PRIOR, since_seconds=3600)) == []


@pytest.mark.parametrize('line,code', [('This is our first session together.', 'first_session_claim'), ('Objectively, that was poor.', 'objective_standard'), ('You managed nine edges last time.', 'unsupported_history_figure')])
def test_the_factual_history_checks_are_unchanged(line, code):
    assert code in card_language_violations(line, hist('found', PRIOR, since_seconds=3600))


@pytest.mark.parametrize('line', ['Welcome back, it has been too long.', "I've been watching the data from your last run."])
def test_shared_past_without_authorized_history_is_still_refused(line):
    assert 'invented_history' in card_language_violations(line, hist('incomplete'))
