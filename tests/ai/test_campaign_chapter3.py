# SPDX-License-Identifier: AGPL-3.0-only
"""Chapter 3 of the Asterion Initiative (docs/fork/campaign/README.md): the timed delivery, Mira's staged encounter,
Celeste's 40 edges then the finish, Nova's puzzles (checked by the campaign, saved), story flags and the Chapter 4 teaser."""
import json
import pytest
from pydantic import ValidationError
from ai_observer.protocol import CampaignCommand
from companion_ai.campaign import PROGRESS_FILE
from tests.ai.test_campaign import CID, CHAPTER3, MODEL, report, results, run, service, states
from tests.ai.test_campaign_chapter2 import STAMP, frames, milestones, seed, tick, view


def answer(svc, oid, option, r, companion='nova'):
    return svc.answer(oid, option, r, MODEL[companion])


# ---- chapter and unlocking

def test_chapter_3_opens_after_chapter_2_and_chapter_4_is_a_teaser(tmp_path):
    svc = seed(tmp_path, 'the_anomaly')
    campaign = svc.state()['campaigns'][0]
    chapters = {c['id']: c for c in campaign['chapters']}
    assert chapters['advanced_research']['completed'] and chapters['shadows_of_helix']['available']
    assert chapters['shadows_of_helix']['progress'] == {'completed': 0, 'total': 5}
    assert chapters['rise_of_helix']['teaser'] and not chapters['rise_of_helix']['available'] and chapters['rise_of_helix']['progress']['total'] == 0
    assert not campaign['completed']
    assert not any(m['narrative_draft'] for m in campaign['missions'])
    locked = seed(tmp_path / 'b', 'directors_reassessment')
    assert states(locked)['the_anomaly'] == 'locked'


def test_mira_joins_the_campaign_after_the_empty_vault_only(tmp_path):
    svc = seed(tmp_path, 'the_empty_vault')
    assert 'mira' not in svc.state()['campaigns'][0]['companions']
    run(svc, 'daisy', tick('v', 0), tick('v', 60, orgasms=1))
    campaign = svc.state()['campaigns'][0]
    assert 'mira' in campaign['companions'] and states(svc)['midnight_intruder'] == 'available'


@pytest.mark.parametrize('mission,companion', zip(CHAPTER3, ['evelyn', 'daisy', 'mira', 'celeste', 'nova']))
def test_each_chapter_3_mission_counts_only_with_its_companion(tmp_path, mission, companion):
    svc = seed(tmp_path, mission)
    run(svc, 'nova' if companion != 'nova' else 'evelyn', report(sid='x'))
    assert svc.state()['attempt']['session_id'] is None
    run(svc, companion, report(sid='x'))
    assert svc.state()['attempt']['session_id'] == 'x'


# ---- Mission 10: thirty edges

def test_the_anomaly_marks_10_and_20_and_completes_at_30_with_its_flag(tmp_path):
    svc = seed(tmp_path, 'the_anomaly')
    out = run(svc, 'evelyn', report(sid='a'), report(sid='a', edges=10), report(sid='a', edges=10), report(sid='a', edges=21))
    assert milestones(out) == ['start', 'edges:10', 'edges:20']
    [result] = results(run(svc, 'evelyn', report(sid='a', edges=30)))
    assert result['flags'] == {'evelyn_research_sabotage': 'discovered'} and result['unlocked_missions'] == ['the_empty_vault']
    assert svc.state()['campaigns'][0]['flags'] == {'evelyn_research_sabotage': 'discovered'}


# ---- Mission 11: one orgasm within 15 minutes of running time

def test_an_orgasm_within_15_minutes_completes_the_empty_vault(tmp_path):
    svc = seed(tmp_path, 'the_empty_vault')
    out = run(svc, 'daisy', tick('v', 100), *frames('v', 100, 700))
    assert milestones(out) == ['start', 'delivery:left300'] and view(svc, 'delivery', tick('v', 700))['remaining'] == 300
    out = run(svc, 'daisy', *frames('v', 705, 945))
    assert milestones(out) == ['delivery:left60']
    [result] = results(run(svc, 'daisy', tick('v', 1000, orgasms=1)))  # 900 s after the start at 100
    assert result['flags'] == {'cloverfield_theft': 'discovered'}


def test_pauses_stop_the_clock(tmp_path):
    svc = seed(tmp_path, 'the_empty_vault')
    run(svc, 'daisy', *frames('v', 0, 800))
    # Paused for a long time: the engine clock does not move, and neither does the countdown.
    run(svc, 'daisy', *[tick('v', 800, status='PAUSED') for _ in range(50)])
    assert view(svc, 'delivery', tick('v', 800))['remaining'] == 100
    assert results(run(svc, 'daisy', tick('v', 805), tick('v', 810, orgasms=1)))


def test_time_running_out_ends_the_try_and_a_new_session_starts_a_fresh_clock(tmp_path):
    svc = seed(tmp_path, 'the_empty_vault')
    out = run(svc, 'daisy', *frames('v', 0, 905))
    assert milestones(out)[-1] == 'delivery:expired'
    out = run(svc, 'daisy', tick('v', 910, orgasms=1), tick('v', 920, orgasms=2))
    assert not results(out) and milestones(out) == [] and view(svc, 'delivery')['expired'] and view(svc, 'delivery')['progress'] == 0
    assert 'ran out for this try' in brief_text(svc, 'daisy', tick('v', 921, orgasms=2))
    run(svc, 'daisy', tick('v', 925, status='IDLE', orgasms=2))
    assert view(svc, 'delivery')['remaining'] == 900 and not view(svc, 'delivery')['expired']
    assert results(run(svc, 'daisy', tick('w', 0), tick('w', 30, orgasms=1)))


def test_came_early_in_time_counts(tmp_path):
    svc = seed(tmp_path, 'the_empty_vault')
    run(svc, 'daisy', *frames('v', 0, 300))
    assert results(svc.observe(tick('v', 302, status='IDLE', terminal_outcome='premature_release'), ['came_early'], MODEL['daisy']))


def brief_text(svc, companion, r):
    return svc.model_context(MODEL[companion], r)['text']


# ---- Mission 12: Mira's 30-minute encounter

def encounter(svc, sid='m', level=lambda t: 100):
    return run(svc, 'mira', *[tick(sid, t, intensity=level(t)) for t in range(0, 1805, 5)])


def test_the_encounter_runs_on_time_at_any_intensity(tmp_path):
    svc = seed(tmp_path, 'midnight_intruder')
    out = encounter(svc, level=lambda t: 60 if t % 100 < 50 else 140)  # wildly varying: still counts
    [result] = results(out)
    assert milestones(out) == ['start', 'encounter:deception', 'encounter:confrontation']
    assert result['flags'] == {'mira_infiltration': 'completed', 'player_suspicion': 'suspected'}
    assert [b['speaker'] for b in result['epilogue']] == ['nova']


def test_mira_raises_the_intensity_at_each_stage_unless_it_is_already_higher(tmp_path):
    svc = seed(tmp_path, 'midnight_intruder')
    assert svc.settings_directed() and svc.allowed_settings() == {'intensity'}
    run(svc, 'mira', tick('m', 0, intensity=90))
    [step] = svc.take_directives()
    assert step['fallback']['value'] == 50 and 'Set intensity to 50 now (that is 100%)' in step['text']
    run(svc, 'mira', *frames('m', 5, 600, intensity=90))  # the player kept it lower: no cost to progress
    [step] = svc.take_directives()
    assert step['key'] == 'encounter:deception' and step['fallback']['value'] == 60
    assert svc.settings_check({'setting': 'intensity', 'value': 60}, tick('m', 601, intensity=90))
    assert not svc.settings_check({'setting': 'intensity', 'value': 40}, tick('m', 601, intensity=90))
    run(svc, 'mira', *frames('m', 605, 1200, intensity=130))  # the player went higher: no step for confrontation
    assert svc.take_directives() == []
    assert not svc.settings_check({'setting': 'intensity', 'value': 70}, tick('m', 1201, intensity=130))


def test_the_encounter_restarts_when_the_session_ends(tmp_path):
    svc = seed(tmp_path, 'midnight_intruder')
    run(svc, 'mira', *frames('m', 0, 900))
    run(svc, 'mira', tick('m', 900, status='IDLE', terminal_outcome='safety_stop'))
    assert view(svc, 'encounter')['elapsed'] == 0 and states(svc)['midnight_intruder'] == 'active'


# ---- Mission 13: 40 edges, then the finish

def test_the_loyalty_test_counts_only_an_orgasm_after_40_edges(tmp_path):
    svc = seed(tmp_path, 'loyalty_test')
    out = run(svc, 'celeste', report(sid='l'), report(sid='l', edges=10), report(sid='l', edges=26, orgasms=1))
    assert milestones(out) == ['start', 'edges:10', 'edges:25'] and view(svc, 'judgment')['progress'] == 0
    out = run(svc, 'celeste', report(sid='l', edges=40, orgasms=1))
    assert milestones(out) == ['edges:done'] and not results(out)
    assert not [c for c in svc.take_cues() if c['kind'] == 'objective_reached']  # the scripted line marks it
    [result] = results(run(svc, 'celeste', report(sid='l', edges=40, orgasms=2)))
    assert result['flags'] == {'celeste_judgment': 'provisional'}


# ---- Mission 14: Nova's puzzles

def test_puzzle_answers_and_hints_stay_in_the_observer(tmp_path):
    svc = seed(tmp_path, 'ghost_in_the_machine')
    text = json.dumps(svc.state())
    assert '"answer"' not in text and 'Follow each owner up the chain' not in text
    puzzle = view(svc, 'log')['puzzle']
    assert puzzle['open'] and [o['id'] for o in puzzle['options']] == ['carried', 'internal', 'outside', 'none']
    assert not view(svc, 'money')['puzzle']['open']


def test_puzzles_need_the_running_session_with_nova(tmp_path):
    svc = seed(tmp_path, 'ghost_in_the_machine')
    with pytest.raises(ValueError, match='Start the mission session'):
        answer(svc, 'log', 'internal', report(sid='n', status='IDLE'))
    run(svc, 'nova', report(sid='n'))
    with pytest.raises(ValueError, match='mission companion'):
        answer(svc, 'log', 'internal', report(sid='n'), companion='evelyn')
    with pytest.raises(ValueError, match='earlier puzzle'):
        answer(svc, 'money', 'helix', report(sid='n'))
    with pytest.raises(ValueError, match='Unknown puzzle'):
        answer(svc, 'edges', 'x', report(sid='n'))


def test_a_wrong_answer_shows_the_hint_and_never_blocks(tmp_path):
    svc = seed(tmp_path, 'ghost_in_the_machine')
    run(svc, 'nova', report(sid='n'))
    for wrong in ('carried', 'none', 'carried'):
        [update] = answer(svc, 'log', wrong, report(sid='n'))
        item = next(o for o in update['attempt']['objectives'] if o['id'] == 'log')
        assert update['type'] == 'campaign_progress' and item['puzzle']['wrong'] == wrong and 'locker' in item['puzzle']['hint']
    out = answer(svc, 'log', 'internal', report(sid='n'))
    assert milestones(out) == ['log:done'] and view(svc, 'log')['done'] and 'hint' not in view(svc, 'log')['puzzle']


def test_solved_puzzles_are_saved_and_survive_the_session_and_a_restart(tmp_path):
    svc = seed(tmp_path, 'ghost_in_the_machine')
    run(svc, 'nova', report(sid='n'))
    answer(svc, 'log', 'internal', report(sid='n'))
    assert json.loads((tmp_path / PROGRESS_FILE).read_text())['campaigns'][CID]['solved'] == {'ghost_in_the_machine': ['log']}
    run(svc, 'nova', report(sid='n', status='IDLE'))
    again = service(tmp_path)
    assert view(again, 'log')['done'] and view(again, 'money')['puzzle']['open']
    run(again, 'nova', report(sid='p'))
    answer(again, 'money', 'helix', report(sid='p'))
    out = answer(again, 'record', 'inside', report(sid='p'))
    [result] = results(out)
    assert result['chapter_complete']['id'] == 'shadows_of_helix'
    assert [b['speaker'] for b in result['epilogue']] == ['celeste', 'nova'] and result['chapter_completion']['speaker'] == 'nova'
    assert [c['kind'] for c in again.take_cues()] == ['mission_complete']
    flags = again.state()['campaigns'][0]['flags']
    assert flags['player_suspicion'] == 'cleared' and flags['helix_connection'] == 'discovered' and flags['asterion_insider'] == 'suspected'


def test_a_mission_already_solved_completes_when_the_next_session_starts(tmp_path):
    svc = seed(tmp_path, 'ghost_in_the_machine')
    progress = json.loads((tmp_path / PROGRESS_FILE).read_text())
    progress['campaigns'][CID]['solved'] = {'ghost_in_the_machine': ['log', 'money', 'record']}
    (tmp_path / PROGRESS_FILE).write_text(json.dumps(progress))
    assert results(run(service(tmp_path), 'nova', report(sid='q')))


def test_a_correct_answer_that_cannot_be_saved_is_not_solved(tmp_path):
    svc = seed(tmp_path, 'ghost_in_the_machine')
    run(svc, 'nova', report(sid='n'))
    def broken(*args): raise OSError('disk full')
    svc.store.write = broken
    with pytest.raises(OSError): answer(svc, 'log', 'internal', report(sid='n'))
    assert not view(svc, 'log')['done'] and view(svc, 'log')['puzzle']['open']


def test_the_answer_command_is_strict():
    ok = {'version': 1, 'type': 'campaign', 'action': 'answer', 'objective_id': 'log', 'answer': 'internal'}
    assert CampaignCommand.model_validate(ok).answer == 'internal'
    for bad in ({'answer': None}, {'objective_id': None}, {'answer': 'x<script>'}, {'action': 'get'}):
        with pytest.raises(ValidationError): CampaignCommand.model_validate(ok | bad)


# ---- flags, replay and saved progress

def test_replaying_an_earlier_mission_never_rewinds_the_story(tmp_path):
    svc = seed(tmp_path)  # everything completed, suspicion cleared
    progress = json.loads((tmp_path / PROGRESS_FILE).read_text())
    progress['campaigns'][CID]['flags'] = {'player_suspicion': 'cleared'}
    (tmp_path / PROGRESS_FILE).write_text(json.dumps(progress))
    svc = service(tmp_path)
    svc.start(CID, 'midnight_intruder')
    [result] = results(encounter(svc))
    assert result['replay'] and result['flags'] == {} and svc.state()['campaigns'][0]['flags'] == {'player_suspicion': 'cleared'}


def test_version_2_progress_reopens_a_campaign_completed_at_mission_9(tmp_path):
    seed(tmp_path, 'the_anomaly')
    progress = json.loads((tmp_path / PROGRESS_FILE).read_text())
    progress['schema_version'] = 2  # as saved by the Chapter 2 build: no flags, no puzzle progress
    progress['campaigns'][CID].pop('flags', None)
    record = progress['campaigns'][CID]
    record['completed_at'] = STAMP
    record['rewards']['campaign_complete:asterion_initiative'] = {'earned_at': STAMP, 'mission': 'directors_reassessment'}
    progress['active'] = None
    (tmp_path / PROGRESS_FILE).write_text(json.dumps(progress))
    assert json.loads((tmp_path / PROGRESS_FILE).read_text())['schema_version'] == 2
    svc = service(tmp_path)
    campaign = svc.state()['campaigns'][0]
    assert svc.error is None and not campaign['completed'] and campaign['flags'] == {} and states(svc)['the_anomaly'] == 'available'
    svc.start(CID, 'the_anomaly')
    saved = json.loads((tmp_path / PROGRESS_FILE).read_text())
    assert saved['schema_version'] == 3 and 'campaign_complete:asterion_initiative' not in saved['campaigns'][CID]['rewards']
    assert saved['active'] == {'campaign': CID, 'mission': 'the_anomaly', 'started_at': saved['active']['started_at']}


def test_malformed_puzzle_progress_leaves_the_file_and_freeplay_alone(tmp_path):
    seed(tmp_path, 'ghost_in_the_machine')
    progress = json.loads((tmp_path / PROGRESS_FILE).read_text())
    progress['campaigns'][CID]['solved'] = {'ghost_in_the_machine': 'log'}
    raw = json.dumps(progress)
    (tmp_path / PROGRESS_FILE).write_text(raw)
    svc = service(tmp_path)
    assert svc.error and svc.observe(report(), [], MODEL['nova']) == []
    with pytest.raises(ValueError): svc.answer('log', 'internal', report(), MODEL['nova'])
    assert (tmp_path / PROGRESS_FILE).read_text() == raw


def test_the_campaign_view_stays_well_under_the_message_limit(tmp_path):
    assert len(json.dumps(seed(tmp_path, 'ghost_in_the_machine').state())) < 48000


def test_the_countdown_is_a_verified_duration_for_the_companion(tmp_path):
    svc = seed(tmp_path, 'the_empty_vault')
    run(svc, 'daisy', *frames('v', 0, 300))
    clocks = svc.model_context(MODEL['daisy'], tick('v', 300))['durations']
    assert {(c['seconds'], c['remaining']) for c in clocks} == {(900, False), (600, True)}
