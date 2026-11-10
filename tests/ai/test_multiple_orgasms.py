"""Several orgasms in one session: I came counts one, the session keeps running, the companion
reacts each time and knows how many there were this session and across its recorded sessions."""
from copy import deepcopy
import json
import pytest
from companion_ai.context_compiler import PHASE_FACTS, orgasm_facts
from companion_ai.event_deck import RECOVERY_SECONDS, session_phase
from companion_ai.session_history import earlier_orgasms
from companion_ai.settings_control import ROUND_REST_SECONDS, Proposal, decision_content, proposal_request
from tests.ai.test_event_deck_content import DEFINITION, context, deck, play_only, prompt, service
from tests.ai.test_f251 import change
from tests.ai.test_f284 import SCOPE, setup, stop


def running(seconds=300, count=1, last=280, orgasm_mode=False):
    return {'session_id': 's', 'status': 'RUNNING', 'seconds': seconds, 'experience': 'classic', 'goal': 'tease', 'intensity': 100,
            'details': {'orgasm_mode': orgasm_mode, 'orgasm_count': count, 'last_orgasm_seconds': last, 'endgame': 'orgasm'}}


# Phase

@pytest.mark.parametrize('seconds,phase', [(280, 'recovery'), (280 + RECOVERY_SECONDS - 1, 'recovery'), (280 + RECOVERY_SECONDS, 'building')])
def test_recovery_lasts_the_window_after_a_reported_orgasm(seconds, phase):
    assert session_phase(running(seconds)) == phase


def test_a_new_force_orgasm_during_recovery_is_a_finish_again():
    assert session_phase(running(300, orgasm_mode=True)) == 'finishing'


# Observer and journal

def report_orgasm(c, o, s, count, seconds):
    s = deepcopy(s); s['details'].update(orgasm_count=count, last_orgasm_seconds=seconds)
    return change(c, o, s, 'orgasm_reported', seconds=seconds)


def test_each_reported_orgasm_is_an_accepted_event_and_the_journal_keeps_the_count(tmp_path):
    c, o, s, j = setup(tmp_path)
    s, accepted = report_orgasm(c, o, s, 1, 240)
    assert accepted and o.report['status'] == 'RUNNING'
    assert any(e['kind'] == 'orgasm_reported' and 'session count 0 -> 1' in e['evidence'] for e in o.events)
    s, accepted = report_orgasm(c, o, s, 2, 520)
    assert accepted and sum(e['kind'] == 'orgasm_reported' for e in o.events) == 2
    s = stop(c, o, s)
    record = j.data['records'][0]
    assert record['orgasms'] == 2 and record['completion_status'] == 'user_reported'
    assert o.completed_sessions[-1]['orgasms'] == 2
    assert j.snapshot(sort='orgasms')['records'][0]['orgasms'] == 2
    assert j.retrieve('How many edges did the previous session have?', SCOPE)[0]['orgasms'] == 2


def test_an_unchanged_count_proves_no_orgasm(tmp_path):
    c, o, s, j = setup(tmp_path)
    s, _ = change(c, o, s, 'orgasm_reported', seconds=60)
    assert not any(e['kind'] == 'orgasm_reported' for e in o.events)


class Journal:
    def __init__(self, records, access=True):
        self.error = None
        self.data = {'ai_access': access, 'records': records}


def row(session, orgasms, scope=SCOPE):
    return {'session_id': session, 'orgasms': orgasms, 'companions': [{'model_scope': scope, 'companion': 'evelyn'}]}


def test_the_all_time_total_counts_only_this_companions_own_sessions_and_needs_permission():
    journal = Journal([row('a', 2), row('b', 1), row('c', 5, 'other-scope'), row('now', 9)])
    assert earlier_orgasms(journal, SCOPE, {'now'}) == 3
    assert earlier_orgasms(Journal([row('a', 2)], access=False), SCOPE) is None


# Card prompt facts

@pytest.mark.parametrize('card,lane,result,expected,absent', [
    # A reaction gets this session's count only: given both, the model reported the total as this session's.
    ({'intent': 'orgasm_reaction', 'orgasms': 2, 'total_orgasms': 7, 'total_known': True}, 'mission', None,
     ['this session: 2'], ['all your recorded sessions', '7']),
    ({'intent': 'orgasm_total', 'orgasms': 2, 'total_orgasms': 7, 'total_known': True}, 'normal', None,
     ['this session: 2', 'this one included: 7'], []),
    ({'intent': 'general_conversation', 'orgasms': 1, 'total_orgasms': 4, 'total_known': True}, 'normal', None,
     ['this session: 1'], ['all your recorded sessions']),
    ({'intent': 'general_conversation', 'orgasms': 0, 'total_orgasms': 4, 'total_known': True}, 'normal', None, [], ['Orgasms']),
    ({'intent': 'orgasm_total', 'orgasms': 0, 'total_orgasms': 0, 'total_known': False}, 'normal', None,
     ['this session: 0', 'not available to you'], ['all your recorded sessions']),
    ({'intent': 'session_closing', 'orgasms': 0, 'total_orgasms': 3, 'total_known': True}, 'session_end', {'orgasms': 2},
     ['this session: 2', 'this one included: 5'], []),
    ({'intent': 'arrival_returning', 'orgasms': 0, 'total_orgasms': 6, 'total_known': True}, 'arrival', None,
     ['all your recorded sessions together: 6'], ['this session', 'this one included']),
])
def test_orgasm_counts_reach_only_the_cards_that_need_them(card, lane, result, expected, absent):
    text = '\n'.join(orgasm_facts(card, lane, result))
    assert all(e in text for e in expected) and not any(a in text for a in absent), text


async def test_a_recovery_card_is_told_the_session_goes_on_and_the_count():
    r, s, wire, _ = await service(seconds=300, orgasms=1, last_orgasm=290)
    play_only(s, 'recovery-still-going')
    s.pump(); await s.task
    current = prompt(wire)
    assert PHASE_FACTS['recovery'] in current and 'Orgasms the participant reported this session: 1.' in current


async def test_the_orgasm_reaction_plays_again_for_every_reported_orgasm():
    r, s, wire, frames = await service(seconds=300, orgasms=1, last_orgasm=290)
    target = s.deck(); target._start_done = True; target._queue = []; target._played = []
    for n in (1, 2):
        target.verified_event('orgasm_reported', f'orgasm-{n}', target.session_id, n)
        s.pump(); await s.task
        assert 'The participant just reported an orgasm' in prompt(wire)
        assert 'Verified result' not in prompt(wire)
    assert [a['sequence_id'] for a in target._activations].count('orgasm-reported') == 2


def test_one_reaction_at_a_time_for_quick_successive_reports():
    target = deck('nova')
    assert target.verified_event('orgasm_reported', 'one', target.session_id, 1) == ['orgasm-reported']
    assert target.verified_event('orgasm_reported', 'two', target.session_id, 2) == []


# AI Settings Control

def test_the_decision_step_knows_the_count_and_the_rest_rule():
    content = decision_content(running(300, 2, 200))
    assert 'Orgasms the participant reported this session: 2, the last one 1 min 40 s ago' in content
    assert 'never within 3 minutes of the last orgasm' in content


@pytest.mark.parametrize('trigger,since,allowed', [('own', ROUND_REST_SECONDS - 1, False), ('own', ROUND_REST_SECONDS, True), ('user', 10, True)])
def test_an_own_new_round_waits_for_the_rest_but_a_user_request_does_not(trigger, since, allowed):
    proposal = Proposal.model_validate({'change': 'orgasm', 'value': True, 'reason': 'Another one.'})
    assert (proposal_request(proposal, running(300 + since, 1, 300), trigger) is not None) is allowed


# Next round: no keyword needed. Recovery over -> invited settings decision -> a card kicks the round off.

from companion_ai.context_compiler import round_facts
from companion_ai.settings_control import ROUND_DECISION


def test_the_round_decision_is_invited_and_never_ends_pauses_or_forces():
    content = decision_content(running(400, 1, 300), round_start=True)
    assert ROUND_DECISION in content and 'Nobody asked' not in content and 'never within 3 minutes' not in content
    for change, value in (('orgasm', True), ('pause', True), ('stop', True)):
        assert proposal_request(Proposal.model_validate({'change': change, 'value': value, 'reason': 'x'}), running(400, 1, 300), 'round') is None
    assert proposal_request(Proposal.model_validate({'change': 'play_style', 'value': 'milker', 'reason': 'x'}), running(400, 1, 300), 'round')['trigger'] == 'round'


def test_round_facts_claim_only_a_verified_change():
    applied = round_facts({'change': {'setting': 'play_style', 'from': 'classic', 'to': 'milker', 'reason': 'Round two.'}})[0]
    assert 'you yourself just changed the play style from' in applied and 'Round two.' in applied
    assert 'do not say or hint that you changed anything' in round_facts({'change': None})[0]
    assert 'do not say or hint' in round_facts(None)[0]


class RoundAdapter:
    mode = 'ollama'
    def __init__(self, reply): self.reply = reply; self.contents = []
    async def decide_settings(self, content, schema, timeout):
        self.contents.append(content); return self.reply


@pytest.mark.parametrize('seconds,started', [(300 + RECOVERY_SECONDS - 1, False), (300 + RECOVERY_SECONDS, True)])
async def test_the_round_starts_when_recovery_ends_without_any_user_message(seconds, started):
    r, s, wire, frames = await service(seconds=seconds, orgasms=1, last_orgasm=300)
    s.deck()._start_done = True
    assert s.maybe_start_round(s.state.report) is started
    if started:
        await s.settings.task
        assert s.round_changes[s.state.session_id]['count'] == 1
        assert [a['sequence_id'] for a in s.deck()._activations].count('next-round') == 1
        assert s.maybe_start_round(s.state.report) is False  # once per orgasm


async def test_the_round_card_is_told_the_count_and_that_nothing_was_changed_without_settings_control():
    r, s, wire, frames = await service(seconds=400, orgasms=1, last_orgasm=300)
    s.deck()._start_done = True; s.deck()._counter_baseline = {'edges': 0, 'seconds': 0}
    assert s.maybe_start_round(s.state.report); await s.settings.task
    s.pump(); await s.task
    current = prompt(wire)
    assert 'a new round begins' in current and 'this session: 1' in current and 'do not say or hint that you changed anything' in current
    assert 'all your recorded sessions' not in current


async def test_a_new_force_orgasm_after_recovery_needs_no_round_card():
    r, s, wire, frames = await service(seconds=400, orgasms=1, last_orgasm=300, orgasm_mode=True)
    assert s.maybe_start_round(s.state.report) is False and s.rounds_started[s.state.session_id] == 1


# The user's After an orgasm settings (AI Settings panel) drive the companion too.

def with_settings(report, **ai):
    report['details']['ai_settings'] = {'enabled': True, 'revoked': False, 'applied': 0, 'pacing': 'sometimes', **ai}
    return report


@pytest.mark.parametrize('recovery,seconds,phase', [(150, 280 + 149, 'recovery'), (150, 280 + 150, 'building'), (30, 280 + 30, 'building'),
                                                    (999, 280 + RECOVERY_SECONDS, 'building')])
def test_the_recovery_follows_the_users_setting(recovery, seconds, phase):
    assert session_phase(with_settings(running(seconds), recovery_seconds=recovery)) == phase


@pytest.mark.parametrize('rest,since,allowed', [(300, 299, False), (300, 300, True), (0, 0, True)])
def test_the_own_force_orgasm_block_follows_the_users_setting(rest, since, allowed):
    proposal = Proposal.model_validate({'change': 'orgasm', 'value': True, 'reason': 'Another one.'})
    report = with_settings(running(300 + since, 1, 300), round_rest_seconds=rest)
    assert (proposal_request(proposal, report, 'own') is not None) is allowed


def test_the_decision_step_states_the_users_block_or_none():
    assert 'never within 5 minutes of the last orgasm' in decision_content(with_settings(running(300, 1, 200), round_rest_seconds=300))
    assert 'never within' not in decision_content(with_settings(running(300, 1, 200), round_rest_seconds=0))


def test_a_second_finish_request_is_told_force_orgasm_reset_itself():
    content = decision_content(running(600, 1, 290), user_text='Make me cum again, please.', recent=[{'setting': 'orgasm', 'to': True}])
    assert 'also again after an earlier orgasm -> orgasm true' in content
    assert content.rstrip().endswith('Force Orgasm is off since their last orgasm.')
    assert 'orgasm -> true' not in content
    assert 'is off since their last orgasm' not in decision_content(running(600, 1, 290, orgasm_mode=True), user_text='harder')
    assert 'is off since their last orgasm' not in decision_content(running(600, 0, None), user_text='Make me cum.')


def test_the_session_count_forbids_inventing_more():
    text = '\n'.join(orgasm_facts({'intent': 'general_conversation', 'orgasms': 1, 'total_orgasms': 1, 'total_known': True}, 'normal', None))
    assert 'Never say or suggest there were more' in text


# Codex review 2026-11-10: a round change must be announced even when the next-round card cannot play.

@pytest.mark.parametrize('spontaneous,card,announced', [(True, True, False), (False, False, True)])
async def test_a_round_change_falls_back_to_a_settings_card_when_the_round_card_cannot_play(monkeypatch, spontaneous, card, announced):
    import companion_ai.conversation as conversation
    r, s, wire, frames = await service(seconds=400, orgasms=1, last_orgasm=300)
    s.deck()._start_done = True
    s.director.config.spontaneous_enabled = spontaneous
    entry = {'status': 'announced', 'request': {'id': 'q1', 'setting': 'intensity', 'reason': 'next round'}, 'outcome': {'from': 60, 'to': 70}}
    monkeypatch.setattr(conversation, 'settings_available', lambda report: True)
    monkeypatch.setattr(s, 'adapter', RoundAdapter(None))
    async def run(*args, **kwargs): return {'id': 'q1'}
    async def settled(*args, **kwargs): return entry
    monkeypatch.setattr(s.settings, 'run', run); monkeypatch.setattr(s.settings, 'settled', settled)
    assert s.maybe_start_round(s.state.report); await s.settings.task
    assert ('next-round' in [a['sequence_id'] for a in s.deck()._activations]) is card
    assert (entry in s.settings_cards) is announced
    assert s.round_changes[s.state.session_id]['change']['to'] == 70
