# SPDX-License-Identifier: AGPL-3.0-only
"""Campaign progression (docs/fork/campaign/README.md): definitions, verified objectives, rewards, saved progress."""
import json
from pathlib import Path
import pytest
from companion_ai.campaign import Book, CampaignService, Campaign, PROGRESS_FILE, real_hr
from companion_ai.settings_control import SettingsControl
from companion_ai.storage import SettingsStore

MODELS = {'nova-narrative-f29-v011:latest': 'nova', 'evelyn-narrative-f29-v013:latest': 'evelyn',
          'daisy-narrative-f29-v014:latest': 'daisy', 'celeste-narrative-f29-v012:latest': 'celeste',
          'mira-narrative-f29-v015:latest': 'mira'}
MODEL = {v: k for k, v in MODELS.items()}
ORDER = ['orientation', 'first_assessment', 'country_connections', 'directors_test', 'certification']
CHAPTER2 = ['endurance_study', 'cloverfield_quota', 'adaptive_calibration', 'directors_reassessment']
CHAPTER3 = ['the_anomaly', 'the_empty_vault', 'midnight_intruder', 'loyalty_test', 'ghost_in_the_machine']
CID = 'asterion_initiative'


def identity(model):
    return MODELS.get(model)


def service(tmp_path, book=None):
    return CampaignService(SettingsStore(tmp_path), book=book, identity=identity)


def report(status='RUNNING', sid='s1', edges=0, orgasms=0, hr=True, ble=True, sim=False, toy=True, mode='classic', **extra):
    details = {'orgasm_count': orgasms, 'calibration_pass': 'none'} | extra
    return {'session_id': sid, 'status': status, 'edges': edges, 'active_mode': mode, 'goal': 'tease',
            'devices': {'hr_ready': hr, 'ble': ble, 'simulated_hr': sim, 'toy_ready': toy},
            'details': details}


def states(svc):
    campaign = svc.state()['campaigns'][0]
    return {m['id']: m['state'] for m in campaign['missions']}


def run(svc, companion, *reports, events=()):
    out = []
    for r in reports:
        out += svc.observe(r, list(events), MODEL[companion])
    return out


def results(out):
    return [m for m in out if m['type'] == 'mission_result']


def finish_orientation(svc):
    svc.start(CID, 'orientation')
    return results(run(svc, 'nova', report(edges=0), report(edges=1)))


# ---- 4. registration and discovery

def test_the_shipped_campaign_loads_and_is_available_from_the_start(tmp_path):
    book = Book.load()
    assert book.errors == []
    assert [c.id for c in book.campaigns] == [CID]
    state = service(tmp_path).state()
    campaign = state['campaigns'][0]
    assert campaign['title'] == 'The Asterion Initiative' and campaign['available'] and not campaign['completed']
    assert [m['id'] for m in campaign['missions']] == ORDER + CHAPTER2 + CHAPTER3
    assert [m['companion'] for m in campaign['missions']] == ['nova', 'evelyn', 'daisy', 'celeste', 'nova', 'evelyn', 'daisy', 'nova', 'celeste',
                                                              'evelyn', 'daisy', 'mira', 'celeste', 'nova']
    assert campaign['progress'] == {'completed': 0, 'total': 14}
    assert campaign['narrative_status'] == 'approved'
    assert all(m['briefing'] for m in campaign['missions'])


def test_a_second_campaign_registers_from_data_alone(tmp_path):
    root = tmp_path / 'campaigns'
    for cid, order in (('second_story', 2), ('first_story', 1)):
        (root / cid).mkdir(parents=True)
        (root / cid / 'campaign.json').write_text(json.dumps({'schema_version': 1, 'id': cid, 'order': order, 'title': cid,
            'description': 'x', 'starting_companions': ['nova'], 'missions': [{'id': 'one', 'order': 1, 'title': 'One', 'summary': 'x',
            'companion': 'nova', 'objectives': [{'id': 'e', 'type': 'edge_count', 'count': 1, 'label': 'Edge'}]}]}))
    book = Book.load(root)
    assert [c.id for c in book.campaigns] == ['first_story', 'second_story'] and book.errors == []


@pytest.mark.parametrize('change,error', [
    (lambda c: c['missions'][1].update(prerequisites=['nope']), 'unknown prerequisite'),
    (lambda c: c['missions'][0].update(prerequisites=['certification']), 'cycle'),
    (lambda c: c['missions'][1].update(companion='stranger'), 'never unlocked'),
    (lambda c: c['missions'][0]['objectives'].append({'id': 'x', 'type': 'edge_count', 'label': 'x'}), 'count is required'),
    (lambda c: c['missions'][0]['objectives'].append({'id': 'x', 'type': 'llm_said_so', 'label': 'x'}), 'Input should be'),
])
def test_invalid_definitions_are_rejected(change, error):
    data = json.loads((Path(__file__).resolve().parents[2] / 'config/campaigns' / CID / 'campaign.json').read_text())
    change(data)
    with pytest.raises(ValueError, match=error):
        Campaign.model_validate(data)


def test_a_broken_campaign_is_skipped_and_the_others_still_load(tmp_path):
    root = tmp_path / 'campaigns'
    (root / 'broken').mkdir(parents=True)
    (root / 'broken' / 'campaign.json').write_text('{not json')
    book = Book.load(root)
    assert book.campaigns == [] and book.errors[0]['path'] == 'broken'


# ---- 5. prerequisites and companion unlocks

def test_only_the_first_mission_is_available_at_the_start(tmp_path):
    assert states(service(tmp_path)) == {'orientation': 'available', 'first_assessment': 'locked', 'country_connections': 'locked',
                                         'directors_test': 'locked', 'certification': 'locked'} | {m: 'locked' for m in CHAPTER2 + CHAPTER3}
    with pytest.raises(ValueError, match='locked'):
        service(tmp_path).start(CID, 'first_assessment')


def test_a_mission_cannot_start_during_a_running_session(tmp_path):
    with pytest.raises(ValueError, match='Stop the current session'):
        service(tmp_path).start(CID, 'orientation', report(status='PAUSED'))


# ---- 6, 7, 8. completion, successor unlock, companion reward

def test_orientation_completes_on_one_real_edge_and_unlocks_evelyn(tmp_path):
    svc = service(tmp_path)
    svc.start(CID, 'orientation')
    assert states(svc)['orientation'] == 'active'
    out = run(svc, 'nova', report(edges=0))
    attempt = out[0]['attempt']
    assert {o['id']: o['done'] for o in attempt['objectives']} == {'hr': True, 'toy': True, 'start': True, 'edge': False}
    out = run(svc, 'nova', report(edges=1))
    [result] = results(out)
    assert result['mission'] == 'orientation' and not result['replay']
    assert result['earned'] == [{'type': 'unlock_companion', 'id': 'evelyn', 'label': 'Dr. Evelyn Voss joins the campaign'}]
    assert result['unlocked_missions'] == ['first_assessment']
    assert result['completion']['speaker'] == 'nova'
    assert states(svc)['orientation'] == 'completed' and states(svc)['first_assessment'] == 'available'
    assert svc.state()['campaigns'][0]['companions'] == ['evelyn', 'nova']


def test_the_session_keeps_running_after_completion_and_the_result_is_sent_once(tmp_path):
    svc = service(tmp_path)
    assert len(finish_orientation(svc)) == 1
    assert run(svc, 'nova', report(edges=2), report(edges=3), report(status='IDLE', edges=3)) == []


def test_nothing_counts_before_hr_toy_and_companion_are_in_place(tmp_path):
    svc = service(tmp_path)
    svc.start(CID, 'orientation')
    assert results(run(svc, 'nova', report(edges=0, hr=False), report(edges=1, hr=False))) == []
    assert results(run(svc, 'nova', report(sid='s2', edges=0, sim=True), report(sid='s2', edges=1, sim=True))) == []
    assert results(run(svc, 'nova', report(sid='s3', edges=0, toy=False), report(sid='s3', edges=1, toy=False))) == []
    assert results(run(svc, 'evelyn', report(sid='s4', edges=0), report(sid='s4', edges=1))) == []
    assert results(run(svc, 'nova', report(sid='s5', edges=0), report(sid='s5', edges=1)))


def test_the_heart_rate_simulator_is_not_a_monitor():
    assert real_hr(report()) and not real_hr(report(sim=True)) and not real_hr(report(ble=False))


def test_edges_made_with_another_companion_selected_do_not_count(tmp_path):
    svc = service(tmp_path)
    finish_orientation(svc)
    svc.start(CID, 'first_assessment')
    run(svc, 'evelyn', report(sid='a', edges=0), report(sid='a', edges=2))
    run(svc, 'nova', report(sid='a', edges=6))
    assert svc.state()['attempt']['objectives'][3]['progress'] == 2
    assert results(run(svc, 'evelyn', report(sid='a', edges=9)))


def test_five_edges_must_fall_in_one_session(tmp_path):
    svc = service(tmp_path)
    finish_orientation(svc)
    svc.start(CID, 'first_assessment')
    out = run(svc, 'evelyn', report(sid='a', edges=0), report(sid='a', edges=4), report(sid='a', status='IDLE', edges=4))
    assert results(out) == [] and svc.state()['attempt']['reset_reason'] == 'session_ended'
    assert svc.state()['attempt']['objectives'][3]['progress'] == 0
    assert results(run(svc, 'evelyn', report(sid='b', edges=0), report(sid='b', edges=5)))[0]['earned'][0]['id'] == 'daisy'


@pytest.mark.parametrize('final', [
    {'orgasms': 1},                                   # I came
    {'orgasms': 1, 'completion_reported': True},      # Finished me, confirmed: the counter rises
])
def test_an_orgasm_reported_through_the_engine_counts_once(tmp_path, final):
    svc = _to(tmp_path, 'country_connections')
    mode = 'survival' if 'completion_reported' in final else 'classic'
    out = run(svc, 'daisy', report(sid='c', mode=mode), report(sid='c', mode=mode, **final))
    assert results(out)[0]['earned'][0]['id'] == 'celeste'


def test_came_early_counts_as_an_orgasm(tmp_path):
    svc = _to(tmp_path, 'country_connections')
    run(svc, 'daisy', report(sid='c'))
    assert results(svc.observe(report(sid='c', status='IDLE'), ['came_early', 'stop'], MODEL['daisy']))


def test_an_orgasm_and_completion_report_together_count_one(tmp_path):
    svc = _to(tmp_path, 'directors_test')
    run(svc, 'celeste', report(sid='d'), report(sid='d', edges=5, orgasms=1, completion_reported=True))
    # 5 edges + 1 orgasm finished it; the second orgasm objective never needed a second report.
    assert states(svc)['directors_test'] == 'completed'


def test_directors_test_needs_both_counts_in_one_session(tmp_path):
    svc = _to(tmp_path, 'directors_test')
    assert results(run(svc, 'celeste', report(sid='d'), report(sid='d', orgasms=1), report(sid='d', status='IDLE', orgasms=1))) == []
    assert results(run(svc, 'celeste', report(sid='e'), report(sid='e', edges=5))) == []
    [result] = results(run(svc, 'celeste', report(sid='e', edges=5, orgasms=1)))
    assert result['unlocked_missions'] == ['certification'] and result['earned'][0]['id'] == 'assessments_passed'


# ---- Mission 5: Calibration ending with Finished me

def calibrate(**extra):
    return report(mode='calibrate', calibration_pass='primary', single_max_bpm=150, **extra)


def test_certification_needs_calibration_mode(tmp_path):
    svc = _to(tmp_path, 'certification')
    run(svc, 'nova', report(sid='f'))
    assert svc.state()['attempt']['session_id'] is None


def test_certification_completes_the_campaign_on_a_saved_finished_me_run(tmp_path):
    svc = _to(tmp_path, 'certification')
    run(svc, 'nova', calibrate(sid='f'), calibrate(sid='f', orgasms=1, calibration_saved=True))
    [result] = results(svc.observe(calibrate(sid='f', status='IDLE', orgasms=1, calibration_saved=True, terminal_outcome='calibration_completed'),
                                   ['completion_accepted'], MODEL['nova']))
    # Mission 5 now completes Chapter 1; its closing lines (approved text) are the chapter's.
    assert not result['campaign_complete'] and result['chapter_complete'] == {'id': 'introduction', 'number': 1, 'title': 'Introduction'}
    assert result['chapter_completion']['speaker'] == 'nova' and 'certified participant' in result['chapter_completion']['lines'][0]
    assert {k: result['records'][k] for k in ('calibration_pass', 'calibrated_max_bpm')} == {'calibration_pass': 'primary', 'calibrated_max_bpm': 150}
    state = service(tmp_path).state()['campaigns'][0]
    assert not state['completed'] and state['progress'] == {'completed': 5, 'total': 14}
    assert [(c['completed'], c['progress']) for c in state['chapters']][:2] == [(True, {'completed': 5, 'total': 5}), (False, {'completed': 0, 'total': 4})]


def test_edged_saves_the_max_but_does_not_certify(tmp_path):
    svc = _to(tmp_path, 'certification')
    run(svc, 'nova', calibrate(sid='f'), calibrate(sid='f', edges=1, calibration_saved=True))
    out = svc.observe(calibrate(sid='f', status='IDLE', edges=1, calibration_saved=True, terminal_outcome='calibration_completed'), ['completion_accepted'], MODEL['nova'])
    assert results(out) == [] and states(svc)['certification'] == 'active'


def test_stop_during_the_ease_down_after_a_saved_finished_me_still_certifies(tmp_path):
    # Playtest 2026-11-17: the max was saved, then Stop was pressed while the toys eased down.
    svc = _to(tmp_path, 'certification')
    run(svc, 'nova', calibrate(sid='f'), calibrate(sid='f', orgasms=1, calibration_saved=True))
    [result] = results(svc.observe(calibrate(sid='f', status='IDLE', orgasms=1, calibration_saved=True, terminal_outcome='manual_stop'),
                                   ['stop'], MODEL['nova']))
    assert result['chapter_complete']['id'] == 'introduction' and result['records']['calibrated_max_bpm'] == 150


def test_stop_without_a_saved_max_or_an_orgasm_does_not_certify(tmp_path):
    svc = _to(tmp_path, 'certification')
    # A cancelled Finished me: nothing saved.
    run(svc, 'nova', calibrate(sid='f'), calibrate(sid='f', completion_reported=True))
    assert results(svc.observe(calibrate(sid='f', status='IDLE', completion_reported=True, terminal_outcome='manual_stop'), ['stop'], MODEL['nova'])) == []
    # Edged saves the max but counts no orgasm.
    run(svc, 'nova', calibrate(sid='g'), calibrate(sid='g', edges=1, calibration_saved=True))
    assert results(svc.observe(calibrate(sid='g', status='IDLE', edges=1, calibration_saved=True, terminal_outcome='manual_stop'), ['stop'], MODEL['nova'])) == []
    assert states(svc)['certification'] == 'active'


def test_a_failed_save_does_not_certify(tmp_path):
    svc = _to(tmp_path, 'certification')
    run(svc, 'nova', calibrate(sid='f'), calibrate(sid='f', orgasms=1, calibration_saved=False))
    out = svc.observe(calibrate(sid='f', status='IDLE', orgasms=1, calibration_saved=False, terminal_outcome='calibration_completed'), ['completion_accepted'], MODEL['nova'])
    assert results(out) == [] and not svc.state()['campaigns'][0]['completed']


def test_ai_settings_are_limited_to_intensity_during_certification_only(tmp_path):
    svc = _to(tmp_path, 'certification')
    assert svc.allowed_settings() == frozenset({'intensity'})
    svc.abandon()
    assert svc.allowed_settings() is None
    svc.start(CID, 'orientation')
    assert svc.allowed_settings() is None


def test_settings_control_drops_a_restricted_request():
    import asyncio

    class Adapter:
        def __init__(self, answer): self.answer = answer
        async def decide_settings(self, content, schema, timeout):
            self.content = content
            return json.dumps(self.answer)
    ai = {'enabled': True, 'revoked': False, 'applied': 0, 'own_ready': True}
    r = report(mode='calibrate') | {'intensity': 100, 'experience': 'classic', 'seconds': 60}
    r['details'] |= {'ai_settings': ai, 'endgame': 'orgasm', 'orgasm_mode': False}
    control = SettingsControl(); control.allowed = frozenset({'intensity'}); sent = []
    adapter = Adapter({'change': 'game', 'value': 'survival', 'reason': 'x'})
    assert asyncio.run(control.run(adapter, r, 'm', sent.append)) is None and sent == []
    assert control.diagnostics['status'] == 'restricted' and 'only these changes are possible: intensity' in adapter.content
    assert asyncio.run(control.run(Adapter({'change': 'intensity', 'value': 70, 'reason': 'x'}), r, 'm', sent.append))['setting'] == 'intensity'


# ---- 9, 10, 12. persistence, duplicates, replay

def test_progress_survives_a_restart(tmp_path):
    svc = service(tmp_path)
    finish_orientation(svc)
    svc.start(CID, 'first_assessment')
    again = service(tmp_path)
    assert states(again)['orientation'] == 'completed' and states(again)['first_assessment'] == 'active'
    assert again.attempt and again.attempt.session_id is None  # a session never resumes across restarts
    saved = json.loads((tmp_path / PROGRESS_FILE).read_text())
    assert saved['schema_version'] == 3 and saved['active']['mission'] == 'first_assessment'
    assert set(saved['campaigns'][CID]['rewards']) == {'unlock_companion:evelyn'}


def test_replay_grants_nothing_twice(tmp_path):
    svc = service(tmp_path)
    finish_orientation(svc)
    svc.start(CID, 'orientation')
    [again] = results(run(svc, 'nova', report(sid='y'), report(sid='y', edges=1)))
    assert again['replay'] and again['earned'] == [] and again['unlocked_missions'] == []
    saved = json.loads((tmp_path / PROGRESS_FILE).read_text())['campaigns'][CID]
    assert saved['missions']['orientation']['completions'] == 2 and list(saved['rewards']) == ['unlock_companion:evelyn']


def test_a_failed_save_announces_nothing_and_retries(tmp_path):
    svc = service(tmp_path)
    svc.start(CID, 'orientation')
    real = svc.store.write
    svc.store.write = lambda *a: (_ for _ in ()).throw(OSError('disk full'))
    out = run(svc, 'nova', report(edges=0), report(edges=1))
    assert results(out) == [] and 'could not be saved' in svc.state()['notice']
    svc.store.write = real
    assert results(run(svc, 'nova', report(edges=1)))
    assert states(service(tmp_path))['orientation'] == 'completed'


# ---- 11. invalid or missing data

def test_no_file_means_a_fresh_start(tmp_path):
    assert service(tmp_path).error is None and not (tmp_path / PROGRESS_FILE).exists()


@pytest.mark.parametrize('content', ['{broken', '[]', '{"schema_version": 1, "campaigns": {"asterion_initiative": {"missions": {"orientation": {"completions": "lots"}}}}}',
                                     '{"schema_version": 99}', '{"schema_version": true}'])
def test_unreadable_progress_is_kept_and_disables_only_the_campaign(tmp_path, content):
    (tmp_path / PROGRESS_FILE).write_text(content)
    svc = service(tmp_path)
    assert svc.error and svc.state()['error']
    with pytest.raises(ValueError):
        svc.start(CID, 'orientation')
    assert svc.observe(report(edges=3), [], MODEL['nova']) == []
    assert (tmp_path / PROGRESS_FILE).read_text() == content


def test_progress_for_removed_content_is_ignored(tmp_path):
    (tmp_path / PROGRESS_FILE).write_text(json.dumps({'schema_version': 1, 'active': {'campaign': 'gone', 'mission': 'x', 'started_at': 't'},
        'campaigns': {'gone': {'missions': {'x': {'completions': 1, 'first_completed_at': 't', 'last_completed_at': 't'}}}}}))
    svc = service(tmp_path)
    assert svc.error is None and svc.attempt is None and states(svc)['orientation'] == 'available'


# ---- 13. campaign isolation

def test_progress_is_kept_per_campaign(tmp_path):
    root = tmp_path / 'campaigns'
    for cid in ('alpha', 'beta'):
        (root / cid).mkdir(parents=True)
        (root / cid / 'campaign.json').write_text(json.dumps({'schema_version': 1, 'id': cid, 'order': 1, 'title': cid, 'description': 'x',
            'starting_companions': ['nova'], 'missions': [{'id': 'one', 'order': 1, 'title': 'One', 'summary': 'x', 'companion': 'nova',
            'objectives': [{'id': 'e', 'type': 'edge_count', 'count': 1, 'label': 'Edge'}],
            'rewards': [{'type': 'unlock_companion', 'id': 'evelyn', 'label': 'Evelyn'}]}]}))
    svc = service(tmp_path / 'data', Book.load(root))
    svc.start('alpha', 'one')
    results(run(svc, 'nova', report(edges=0), report(edges=1)))
    by_id = {c['id']: c for c in svc.state()['campaigns']}
    assert by_id['alpha']['completed'] is False and by_id['alpha']['progress']['completed'] == 1
    assert by_id['beta']['progress']['completed'] == 0 and by_id['beta']['companions'] == ['nova']
    assert by_id['beta']['missions'][0]['state'] == 'available' and by_id['beta']['missions'][0]['rewards'][0]['earned'] is False


def test_abandon_clears_the_active_mission_and_keeps_completions(tmp_path):
    svc = service(tmp_path)
    finish_orientation(svc)
    svc.start(CID, 'first_assessment')
    svc.abandon()
    again = service(tmp_path)
    assert again.progress.active is None and states(again)['orientation'] == 'completed' and states(again)['first_assessment'] == 'available'


def _to(tmp_path, mission):
    """Progress saved as if every mission before `mission` was completed, then `mission` started."""
    svc = service(tmp_path)
    for done in ORDER[:ORDER.index(mission)]:
        svc.start(CID, done)
        companion = svc.attempt.mission.companion
        if done == 'certification':
            raise AssertionError('not needed')
        sid = 'pre-' + done
        if done == 'country_connections':
            out = run(svc, companion, report(sid=sid), report(sid=sid, orgasms=1))
        elif done == 'directors_test':
            out = run(svc, companion, report(sid=sid), report(sid=sid, edges=5, orgasms=1))
        else:
            out = run(svc, companion, report(sid=sid), report(sid=sid, edges=5))
        assert results(out), done
    svc.start(CID, mission)
    return svc


# ---- Through the observer: the browser can navigate, only accepted engine evidence completes

def test_observer_websocket_runs_a_mission_end_to_end(tmp_path):
    import time
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from ai_observer.server import create_app
    from tests.fork.test_observer import TOKEN, ORIGIN, auth, until, frame, snapshot
    app = create_app(TOKEN, tmp_path)
    app.state.models.config = app.state.models.config.model_copy(update={'model': 'nova-narrative-f29-v011:latest'})
    sid = str(uuid4())

    def state(**updates):
        s = snapshot()
        s.update({'session_id': sid, 'edges': 0} | updates)
        s['devices'] |= {'simulated_hr': False, 'ble': True, 'hr_ready': True, 'toy_ready': True, 'handy': True}
        s['details'] = {'captured_at_ms': int(time.time() * 1000), 'hr_recorded_at_ms': None, 'calibration_pass': 'none', 'warmup_active': False,
                        'resting_bpm': 70, 'single_max_bpm': 150, 'dual_max_bpm': None, 'pauses': 0, 'warmup_remaining_seconds': None,
                        'ease_down_seconds': None, 'rampdown_seconds': None}
        return s
    with TestClient(app) as client:
        with client.websocket_connect('/observe', headers={'Origin': ORIGIN}) as ws:
            ready = auth(ws)
            ws.send_json({'version': 1, 'type': 'campaign', 'action': 'get'})
            assert until(ws, 'campaign_state')['campaigns'][0]['missions'][0]['state'] == 'available'
            ws.send_json({'version': 1, 'type': 'campaign', 'action': 'start', 'campaign_id': CID, 'mission_id': 'first_assessment'})
            assert 'locked' in until(ws, 'campaign_state')['command_error']
            ws.send_json({'version': 1, 'type': 'campaign', 'action': 'start', 'campaign_id': CID, 'mission_id': 'orientation'})
            assert until(ws, 'campaign_state')['active']['mission'] == 'orientation'
            ws.send_json(frame(ready['epoch'], seq=1, state=state(status='IDLE', seconds=0, hr=None)))
            assert until(ws, 'observation_ack')['accepted']
            time.sleep(.12)
            ws.send_json(frame(ready['epoch'], seq=2, state=state(seconds=1, hr=None)))
            # The campaign update is published before the observation is acknowledged.
            assert until(ws, 'campaign_progress', 3)['attempt']['session_id'] == sid
            assert until(ws, 'observation_ack', 3)['accepted']
            # The speech service sees the brief for Nova, built from the campaign's verified state.
            told = app.state.speech.campaign_brief()
            assert 'Mission 1, "Orientation"' in told['text'] and '0 of 1 edges' in told['text']
            cards = []
            app.state.speech.campaign_cue = cards.append
            time.sleep(.12)
            ws.send_json(frame(ready['epoch'], seq=3, state=state(seconds=5, edges=1, hr=None)))
            result = until(ws, 'mission_result')
            assert result['mission'] == 'orientation' and result['earned'][0]['id'] == 'evelyn'
            assert [(c['kind'], c['companion'], c['session_id']) for c in cards] == [('mission_complete', 'nova', sid)]
            assert 'complete and saved' in app.state.speech.campaign_brief()['text']
    saved = json.loads((tmp_path / PROGRESS_FILE).read_text())
    assert saved['active'] is None and 'orientation' in saved['campaigns'][CID]['missions']


# ---- The companion knows the mission it leads (brief) and reacts to verified mission moments (cards)

def brief(svc, companion, r):
    return svc.model_context(MODEL[companion], r)


def test_the_brief_goes_only_to_the_mission_companion(tmp_path):
    svc = _to(tmp_path, 'first_assessment')
    assert brief(svc, 'daisy', report(sid='a')) is None
    assert brief(svc, 'mira', report(sid='a')) is None
    waiting = brief(svc, 'evelyn', report(sid='a', status='IDLE'))
    assert waiting['state'] == 'active' and 'Mission 2, "First Assessment"' in waiting['text']
    assert 'Reach 5 edges in this session' in waiting['text'] and 'has not started' in waiting['text']
    assert 'heart-rate monitor' in waiting['text'] and waiting['targets'] == [5]
    assert 'Calibration mode' in brief(_to(tmp_path / 'c', 'certification'), 'nova', report(status='IDLE'))['text']


def test_the_brief_carries_only_verified_progress(tmp_path):
    svc = _to(tmp_path, 'first_assessment')
    run(svc, 'evelyn', report(sid='a'), report(sid='a', edges=2))
    text = brief(svc, 'evelyn', report(sid='a', edges=2))['text']
    assert '2 of 5 edges' in text and 'not complete yet' in text and 'do not end or pause' in text
    # Edges counted only with Evelyn selected: a simulator session or another session shows no progress.
    assert 'has not started' in brief(svc, 'evelyn', report(sid='other'))['text']


def test_after_completion_the_brief_says_so_until_the_next_session(tmp_path):
    svc = _to(tmp_path, 'first_assessment')
    run(svc, 'evelyn', report(sid='a'), report(sid='a', edges=5))
    done = brief(svc, 'evelyn', report(sid='a', edges=6))
    assert done['state'] == 'completed' and 'complete and saved' in done['text'] and 'still running' in done['text']
    assert 'has ended' in brief(svc, 'evelyn', report(sid='a', edges=6, status='IDLE'))['text']
    assert brief(svc, 'evelyn', report(sid='b')) is None
    assert brief(svc, 'nova', report(sid='a')) is None


def test_a_broken_progress_file_tells_the_companion_nothing(tmp_path):
    (tmp_path / PROGRESS_FILE).write_text('{')
    assert service(tmp_path).model_context(MODEL['nova'], report()) is None


def cues(svc):
    return [(c['kind'], c['objective']) for c in svc.take_cues()]


def test_mission_complete_is_a_cue_and_setup_items_are_not(tmp_path):
    svc = service(tmp_path)
    svc.start(CID, 'orientation')
    run(svc, 'nova', report(sid='a'))
    assert cues(svc) == []
    run(svc, 'nova', report(sid='a', edges=1))
    [cue] = svc.take_cues()
    assert cue['kind'] == 'mission_complete' and cue['companion'] == 'nova' and cue['session_id'] == 'a'
    assert cue['mission_title'] == 'Orientation' and cue['order'] == 1 and not cue['campaign_complete']


def test_a_goal_reached_before_the_last_one_is_its_own_cue_once(tmp_path):
    svc = _to(tmp_path, 'directors_test')
    svc.take_cues()
    run(svc, 'celeste', report(sid='d'), report(sid='d', edges=5), report(sid='d', edges=6))
    assert cues(svc) == [('objective_reached', 'Reach 5 edges in this session')]
    run(svc, 'celeste', report(sid='d', edges=6, orgasms=1))
    assert cues(svc) == [('mission_complete', None)]


def test_no_cue_for_another_companion_or_a_session_that_ended(tmp_path):
    svc = _to(tmp_path, 'directors_test')
    svc.take_cues()
    run(svc, 'celeste', report(sid='d'))
    run(svc, 'nova', report(sid='d', edges=5))
    assert cues(svc) == []
    # Came Early ends the session: the orgasm counts, but the attempt restarts, so it is not a story moment.
    run(svc, 'celeste', report(sid='d', status='IDLE', orgasms=1))
    assert cues(svc) == [] and svc.state()['attempt']['reset_reason'] == 'session_ended'


def test_the_final_mission_cue_marks_the_campaign_complete(tmp_path):
    svc = _to(tmp_path, 'certification')
    svc.take_cues()
    run(svc, 'nova', calibrate(sid='f'), calibrate(sid='f', orgasms=1, calibration_saved=True))
    svc.observe(calibrate(sid='f', status='IDLE', orgasms=1, calibration_saved=True, terminal_outcome='calibration_completed'), ['completion_accepted'], MODEL['nova'])
    # Finished me raised the orgasm count before the run ended: still one card, not two.
    [cue] = svc.take_cues()
    assert cue['kind'] == 'mission_complete' and not cue['campaign_complete'] and cue['chapter'] == 'Introduction'
    assert 'completes the chapter "Introduction"' in brief(svc, 'nova', calibrate(sid='f', status='IDLE'))['text']


def test_abandoning_drops_queued_cues(tmp_path):
    svc = _to(tmp_path, 'directors_test')
    run(svc, 'celeste', report(sid='d'), report(sid='d', edges=5))
    svc.abandon()
    assert svc.take_cues() == []


def test_the_card_task_says_what_happened_and_not_to_repeat_the_script():
    from companion_ai.campaign import card_brief
    cue = {'kind': 'mission_complete', 'mission_title': 'First Assessment', 'campaign_title': 'The Asterion Initiative', 'order': 2,
           'objective': None, 'campaign_complete': False}
    live = card_brief(cue, 'RUNNING')
    assert 'just completed your mission "First Assessment"' in live and 'do not repeat it' in live and 'still running' in live
    assert 'has ended' in card_brief(cue, 'IDLE')
    assert 'campaign is complete' in card_brief(cue | {'campaign_complete': True}, 'IDLE')
    goal = card_brief(cue | {'kind': 'objective_reached', 'objective': 'Reach 5 edges in this session'}, 'RUNNING')
    assert '"Reach 5 edges in this session"' in goal and 'not complete yet' in goal


@pytest.mark.parametrize('text,edges,flagged', [
    ('That is two of the five edges I asked for.', 2, False),
    ('Two down, out of five edges for my assessment.', 2, False),
    ('You have reached five edges.', 2, True),          # a count, not a target: the engine says two
    ('You have reached five edges.', 5, False),
    ('You have reached seven edges for the assessment.', 2, True),  # not the target either
    ('You have reached five edges for my assessment.', 2, True),   # Codex: a count, whatever the word nearby
    ('Five edges for the mission, done.', 2, True),
    ('Three more and you will have the five edges I asked for.', 2, False),
])
def test_a_mission_target_may_be_named_as_a_target_but_never_as_the_count(text, edges, flagged):
    from companion_ai.fidelity import violations
    from tests.ai.test_event_deck_content import Replay
    r = Replay(); r.state.update(edges=edges, status='RUNNING'); r.step(None, seconds=0)
    canonical = r.observation.summary()['canonical_session']
    codes = violations(text, canonical, card=True, targets=[5])
    assert ('wrong_edges' in codes) is flagged, codes


EVELYN_BRIEF = {'text': 'Campaign: The Asterion Initiative, Mission 2, "First Assessment". You are leading this mission.\nVerified progress in this session: 2 of 5 edges.', 'targets': [5], 'state': 'active'}


async def test_a_chat_reply_and_a_director_card_both_get_the_brief():
    from tests.ai.test_event_deck_content import service as speech, prompt, play_only
    r, s, wire, _ = await speech(identity='evelyn', edges=2, seconds=200)
    s.campaign_brief = lambda: EVELYN_BRIEF
    assert s.request('How am I doing?', user=True)['accepted']; await s.task
    assert 'CAMPAIGN MISSION' in prompt(wire) and '2 of 5 edges' in prompt(wire)
    r, s, wire, _ = await speech(identity='evelyn', edges=2, seconds=200)
    s.campaign_brief = lambda: EVELYN_BRIEF
    play_only(s, 'edge-count-first'); s.pump(); await s.task
    card = prompt(wire)
    assert 'A MOMENT TO SPEAK' in card and '2 of 5 edges' in card and 'Mention it only if it fits' in card


async def test_without_a_mission_nothing_is_added():
    from tests.ai.test_event_deck_content import service as speech, prompt
    r, s, wire, _ = await speech(identity='evelyn', edges=2, seconds=200)
    assert s.request('How am I doing?', user=True)['accepted']; await s.task
    assert 'CAMPAIGN MISSION' not in prompt(wire)


def cue_for(s, companion='evelyn', kind='mission_complete'):
    return {'kind': kind, 'campaign': CID, 'campaign_title': 'The Asterion Initiative', 'mission': 'first_assessment',
            'mission_title': 'First Assessment', 'order': 2, 'companion': companion, 'session_id': s.state.session_id,
            'objective': None, 'campaign_complete': False}


async def test_the_mission_companion_reacts_to_a_verified_completion():
    from tests.ai.test_event_deck_content import service as speech, prompt
    r, s, wire, frames = await speech(identity='evelyn', edges=5, seconds=200)
    s.deck()._start_done = True
    s.campaign_speaker = lambda: 'evelyn'; s.campaign_brief = lambda: EVELYN_BRIEF
    s.campaign_cue(cue_for(s))
    s.pump(); await s.task
    card = prompt(wire)
    assert 'just completed your mission "First Assessment"' in card and 'do not repeat it' in card
    assert not s.campaign_cards and s.director.last_reason == 'campaign_card'


@pytest.mark.parametrize('setup', ['other_companion', 'switched_away', 'quiet', 'spontaneous_off', 'old_session'])
async def test_a_mission_card_does_not_play_when_it_should_not(setup):
    from tests.ai.test_event_deck_content import service as speech
    r, s, wire, frames = await speech(identity='evelyn', edges=5, seconds=200)
    s.deck()._start_done = True
    speaker = ['evelyn']
    s.campaign_speaker = lambda: speaker[0]
    cue = cue_for(s, companion='daisy' if setup == 'other_companion' else 'evelyn')
    if setup == 'old_session': cue['session_id'] = 'previous'
    s.campaign_cue(cue)
    if setup == 'switched_away': speaker[0] = 'daisy'
    if setup == 'quiet': s.director.memory['quiet_requested'] = True
    if setup == 'spontaneous_off': s.director.config.spontaneous_enabled = False
    before = len(wire)
    s.pump()
    if s.task: await s.task
    assert not any(path == '/api/chat' and 'mission' in b['messages'][-1]['content'] for path, b in wire[before:])


# Live check 2026-11-16 (tools/campaign_live_check.py): Celeste's own edge card at 4 of 5 edges said the test was cleared.
@pytest.mark.parametrize('text,flagged', [
    ("Four edges secured, and the campaign still breathes; you have cleared the Director's Test with a quiet competence.", True),
    ('The First Assessment is officially complete.', True),
    ('You earned that certification with a single, solid finish.', True),
    ("Four edges now; the fifth would complete my assessment.", False),
    ("You haven't passed the test yet.", False),
    ('Once you finish the mission, we can talk.', False),
    ('Do you think you have passed the test?', False),
    ('The engine keeps running, and so do you.', False),
    # Codex: a qualifier elsewhere in the sentence does not soften the claim.
    ('The mission is complete, but we are not stopping.', True),
    ('You have passed the test, and I will reward you.', True),
])
def test_an_open_mission_is_never_declared_done(text, flagged):
    from companion_ai.fidelity import campaign_violations
    assert ('premature_mission_complete' in campaign_violations(text, {'campaign_state': 'active'})) is flagged
    assert campaign_violations(text, {'campaign_state': 'completed'}) == []
    assert campaign_violations(text, {}) == []


def test_a_mission_card_must_say_something():
    from companion_ai.fidelity import campaign_violations
    card = {'deck_card': {'campaign': {'kind': 'mission_complete'}}}
    assert campaign_violations('First Assessment', card) == ['campaign_card_too_short']
    assert campaign_violations('A clean, efficient run; I expected nothing less.', card) == []


def test_corrections_explain_a_mission_claim_in_plain_words():
    from companion_ai.context_compiler import CAMPAIGN_CORRECTIONS
    assert 'still open' in CAMPAIGN_CORRECTIONS['premature_mission_complete']


async def test_after_completion_only_the_mission_card_hears_about_it():
    from tests.ai.test_event_deck_content import service as speech, prompt, play_only
    r, s, wire, _ = await speech(identity='evelyn', edges=2, seconds=200)
    s.campaign_brief = lambda: {'text': 'Verified by EdgeLoop: the mission is complete and saved.', 'targets': [5], 'state': 'completed'}
    play_only(s, 'edge-count-first'); s.pump(); await s.task
    assert 'complete and saved' not in prompt(wire)


# ---- Codex review 2026-11-16

def test_calibration_edged_after_a_cancelled_finished_me_does_not_certify(tmp_path):
    """Finished me sets the report flag before its confirm; cancel, then Edged, leaves it set with no orgasm."""
    svc = _to(tmp_path, 'certification')
    run(svc, 'nova', calibrate(sid='f'), calibrate(sid='f', completion_reported=True), calibrate(sid='f', edges=1, completion_reported=True, calibration_saved=True))
    out = svc.observe(calibrate(sid='f', status='IDLE', edges=1, completion_reported=True, calibration_saved=True, terminal_outcome='calibration_completed'),
                      ['completion_accepted'], MODEL['nova'])
    assert results(out) == [] and states(svc)['certification'] == 'active'


@pytest.mark.parametrize('mode', ['survival', 'calibrate'])
def test_a_cancelled_finished_me_is_no_orgasm(tmp_path, mode):
    """Finished me sets the report flag before its confirm; a cancel leaves it set with no orgasm counted."""
    svc = _to(tmp_path, 'country_connections')
    run(svc, 'daisy', report(sid='c', mode=mode), report(sid='c', mode=mode, completion_reported=True))
    assert svc.state()['attempt']['objectives'][-1]['progress'] == 0 and states(svc)['country_connections'] == 'active'


def test_a_flag_and_a_counter_in_consecutive_frames_are_one_orgasm(tmp_path):
    svc = _to(tmp_path, 'directors_test')
    run(svc, 'celeste', report(sid='d', mode='survival'), report(sid='d', mode='survival', completion_reported=True),
        report(sid='d', mode='survival', orgasms=1, completion_reported=True))
    assert svc.state()['attempt']['objectives'][-1]['progress'] == 1
    svc2 = _to(tmp_path / 'b', 'directors_test')
    run(svc2, 'celeste', report(sid='d', mode='survival'), report(sid='d', mode='survival', orgasms=1),
        report(sid='d', mode='survival', orgasms=1, completion_reported=True))
    assert svc2.state()['attempt']['objectives'][-1]['progress'] == 1


@pytest.mark.parametrize('change', [{'sim': True}, {'ble': False}, {'toy': False}])
def test_edges_made_after_switching_to_the_simulator_or_losing_a_device_do_not_count(tmp_path, change):
    svc = service(tmp_path)
    svc.start(CID, 'orientation')
    out = run(svc, 'nova', report(sid='a'), report(sid='a', edges=1, **change), report(sid='a', edges=1))
    assert results(out) == [] and svc.state()['attempt']['objectives'][-1]['progress'] == 0
    assert results(run(svc, 'nova', report(sid='a', edges=2)))


def test_a_completion_waiting_for_its_save_survives_the_next_session(tmp_path):
    svc = service(tmp_path)
    svc.start(CID, 'orientation')
    real = svc.store.write
    def broken(*args): raise OSError('disk full')
    svc.store.write = broken
    assert results(run(svc, 'nova', report(sid='a'), report(sid='a', edges=1))) == []
    svc.store.write = real
    [result] = results(run(svc, 'nova', report(sid='b')))
    assert result['mission'] == 'orientation'
    assert [c['kind'] for c in svc.take_cues()] == ['mission_complete']
    assert states(service(tmp_path))['orientation'] == 'completed'


def test_a_progress_file_holding_null_is_invalid_and_kept(tmp_path):
    (tmp_path / PROGRESS_FILE).write_text('null')
    svc = service(tmp_path)
    assert svc.error
    with pytest.raises(ValueError): svc.start(CID, 'orientation')
    assert (tmp_path / PROGRESS_FILE).read_text() == 'null'


def test_a_goal_cue_goes_stale_when_its_try_resets_or_is_abandoned(tmp_path):
    svc = _to(tmp_path, 'directors_test'); svc.take_cues()
    run(svc, 'celeste', report(sid='d'), report(sid='d', edges=5))
    [cue] = svc.take_cues()
    assert svc.cue_valid(cue)
    run(svc, 'celeste', report(sid='d', edges=5, status='IDLE'))
    assert not svc.cue_valid(cue), 'the session ended without the orgasm; same session id'
    svc2 = _to(tmp_path / 'b', 'directors_test'); svc2.take_cues()
    run(svc2, 'celeste', report(sid='d'), report(sid='d', edges=5))
    [cue] = svc2.take_cues()
    svc2.abandon()
    assert not svc2.cue_valid(cue)


def test_a_completion_cue_stays_valid_for_its_session(tmp_path):
    svc = service(tmp_path)
    svc.start(CID, 'orientation')
    run(svc, 'nova', report(sid='a'), report(sid='a', edges=1))
    [cue] = svc.take_cues()
    assert svc.cue_valid(cue) and svc.cue_valid(cue | {'session_id': 'a'})
    assert not svc.cue_valid(cue | {'session_id': 'b'})


def test_talk_of_an_earlier_mission_is_not_a_claim_about_this_one():
    from companion_ai.fidelity import campaign_violations
    summary = {'campaign_state': 'active', 'campaign_others': ['First Assessment', 'Mission 2', 'evelyn', 'Voss']}
    for text in ("You passed Evelyn's assessment with ease.", 'The First Assessment is complete, and now you face me.',
                 'You completed the earlier test; this one is harder.', 'Dr. Voss says her test is done.'):
        assert campaign_violations(text, summary) == [], text
    assert campaign_violations("You passed Evelyn's assessment, and you have passed my test too.", summary) == ['premature_mission_complete']


def test_the_brief_names_the_other_missions_for_the_check(tmp_path):
    others = brief(_to(tmp_path, 'directors_test'), 'celeste', report(status='IDLE'))['others']
    assert 'First Assessment' in others and 'Mission 2' in others and 'evelyn' in others and 'Voss' in others
    assert "The Director's Test" not in others and 'celeste' not in others


def test_a_custom_character_on_a_companion_model_is_not_that_companion(tmp_path):
    """Codex: Wren running on Daisy's model completed Daisy's mission and got her brief."""
    from companion_ai.conversation import character_identity
    svc = CampaignService(SettingsStore(tmp_path), identity=character_identity)
    svc.start(CID, 'orientation')
    assert results(svc.observe(report(sid='a'), [], 'custom:wren')) == []
    assert results(svc.observe(report(sid='a', edges=1), [], 'custom:wren')) == []
    assert svc.model_context('custom:wren', report(sid='a')) is None
    assert svc.state()['attempt']['session_id'] is None


def test_the_observer_resolves_the_persona_for_the_campaign(tmp_path):
    from types import SimpleNamespace
    from ai_observer.server import create_app
    from tests.fork.test_observer import TOKEN
    app = create_app(TOKEN, tmp_path)
    app.state.models.config = app.state.models.config.model_copy(update={'model': 'nova-narrative-f29-v011:latest'})
    app.state.campaign.start(CID, 'orientation')
    assert app.state.speech.campaign_speaker() == 'nova'
    app.state.models.character = SimpleNamespace(identity='wren')
    assert app.state.speech.campaign_speaker() == 'generic'
    assert app.state.speech.campaign_fields()['campaign_context'] is None


def protect(r, **safety):
    r.state['safety'].update(safety); r.step(None, seconds=1)


@pytest.mark.parametrize('setup', ['watchdog', 'no_contact', 'signal_lost', 'emergency_event', 'safety_stop', 'goal_after_end'])
async def test_a_mission_card_waits_out_protection_and_never_follows_an_emergency_stop(setup):
    from tests.ai.test_event_deck_content import service as speech
    r, s, wire, frames = await speech(identity='evelyn', edges=5, seconds=200)
    s.deck()._start_done = True
    s.campaign_speaker = lambda: 'evelyn'
    cue = cue_for(s, kind='objective_reached' if setup == 'goal_after_end' else 'mission_complete')
    s.campaign_cue(cue)
    if setup == 'watchdog': protect(r, watchdog_paused=True)
    if setup == 'no_contact': protect(r, no_contact=True)
    if setup == 'signal_lost': protect(r, fault='signal_lost')
    if setup == 'emergency_event': s.safety('emergency_stop')
    if setup in {'safety_stop', 'goal_after_end'}:
        r.state.update(status='IDLE')
        r.state['details']['terminal_outcome'] = 'safety_stop' if setup == 'safety_stop' else 'manual_stop'
        r.step(None, seconds=1)
    before = len(wire)
    s.pump()
    if s.task: await s.task
    assert not any(path == '/api/chat' and 'mission' in b['messages'][-1]['content'] for path, b in wire[before:])


async def test_a_completion_may_still_be_told_just_after_calibration_ends():
    from tests.ai.test_event_deck_content import service as speech, prompt
    r, s, wire, frames = await speech(identity='evelyn', edges=5, seconds=200)
    s.deck()._start_done = True
    s.campaign_speaker = lambda: 'evelyn'
    s.campaign_cue(cue_for(s))
    r.state.update(status='IDLE'); r.state['details']['terminal_outcome'] = 'calibration_completed'; r.step(None, seconds=1)
    s.pump(); await s.task
    assert 'just completed your mission' in prompt(wire)


async def test_a_stale_cue_is_dropped_by_the_speech_service():
    from tests.ai.test_event_deck_content import service as speech
    r, s, wire, frames = await speech(identity='evelyn', edges=5, seconds=200)
    s.deck()._start_done = True
    s.campaign_speaker = lambda: 'evelyn'
    s.campaign_cue_valid = lambda cue: False   # the try reset, or the mission was abandoned
    s.campaign_cue(cue_for(s, kind='objective_reached'))
    s.pump()
    assert not s.campaign_cards


async def test_the_brief_is_refreshed_when_the_reply_is_generated():
    """Codex: a reply queued at two of five edges was generated after the mission completed, with the old brief."""
    from tests.ai.test_event_deck_content import service as speech, prompt
    r, s, wire, _ = await speech(identity='evelyn', edges=2, seconds=200)
    told = [EVELYN_BRIEF]
    s.campaign_brief = lambda: told[0]
    base = s.adapter.current_summary
    s.adapter.current_summary = lambda: base() | s.campaign_fields()
    assert s.request('How am I doing?', user=True)['accepted']
    told[0] = None   # the mission was abandoned before dispatch
    await s.task
    assert 'CAMPAIGN MISSION' not in prompt(wire)


# ---- Codex retest 2026-11-16 (its reproductions, /tmp/edgeloop-campaign-retest)

def test_came_early_is_distinct_from_an_earlier_orgasm_with_another_companion(tmp_path):
    svc = _to(tmp_path, 'country_connections')
    run(svc, 'daisy', report(sid='c'))
    run(svc, 'nova', report(sid='c', orgasms=1))
    run(svc, 'daisy', report(sid='c', orgasms=1))
    out = svc.observe(report(sid='c', status='IDLE', orgasms=1, terminal_outcome='premature_release'), ['came_early'], MODEL['daisy'])
    assert results(out), 'Came Early with Daisy completes her mission; the earlier orgasm with Nova is separate'


def test_two_orgasms_are_two_and_nova_s_does_not_count(tmp_path):
    svc = _to(tmp_path, 'directors_test')
    run(svc, 'celeste', report(sid='d'), report(sid='d', orgasms=1))
    run(svc, 'nova', report(sid='d', orgasms=2))
    assert svc.state()['attempt']['objectives'][-1]['progress'] == 1


async def test_a_completion_queued_by_the_emergency_observation_never_speaks(tmp_path):
    from tests.ai.test_event_deck_content import service as speech
    r, s, wire, frames = await speech(identity='nova', edges=0, seconds=200, reply='A clean, efficient effort; I expected nothing less from you.')
    s.deck()._start_done = True
    s.campaign_speaker = lambda: 'nova'
    svc = service(tmp_path)
    svc.start(CID, 'orientation')
    sid = s.state.session_id
    svc.observe(report(sid=sid), [], MODEL['nova'])
    s.campaign_cue_valid = svc.cue_valid
    s.safety('emergency_stop')
    r.state['details']['terminal_outcome'] = 'safety_stop'
    r.step(status='IDLE', seconds=0)
    svc.observe(report(sid=sid, status='IDLE', edges=1, terminal_outcome='safety_stop'), ['stop'], MODEL['nova'])
    for cue in svc.take_cues(): s.campaign_cue(cue)
    r.state['details']['terminal_outcome'] = None
    r.clock.tick(3); r.step(seconds=0)
    s.pump()
    if s.task: await s.task
    assert not [m for m in frames if m['type'] == 'speech' and m.get('source') != 'safety']
    assert states(svc)['orientation'] == 'completed', 'the progress itself still counts'


@pytest.mark.parametrize('text,flagged', [
    ('You have reached the five edges I asked for.', True),
    ("You've hit the five edges I asked for.", True),
    ('Three more and you will have the five edges I asked for.', False),
    ('That is two of the five edges I asked for.', False),
])
def test_a_target_named_in_an_achievement_claim_is_still_a_count(text, flagged):
    from companion_ai.fidelity import violations
    from tests.ai.test_event_deck_content import Replay
    r = Replay(); r.state.update(edges=2, status='RUNNING'); r.step(None, seconds=0)
    assert ('wrong_edges' in violations(text, r.observation.summary()['canonical_session'], card=True, targets=[5])) is flagged


def test_another_mission_named_in_the_same_clause_does_not_excuse_this_one():
    from companion_ai.fidelity import campaign_violations
    summary = {'campaign_state': 'active', 'campaign_others': ['evelyn', 'First Assessment']}
    assert 'premature_mission_complete' in campaign_violations("You have passed my test just as you passed Evelyn's assessment.", summary)


# ---- Companion switching: free in Freeplay, locked to the mission's companion during a mission

def test_switching_companions_is_locked_during_a_mission_only(tmp_path):
    svc = service(tmp_path)
    nova, evelyn = MODEL['nova'], MODEL['evelyn']
    assert svc.switch_refusal(evelyn, nova) is None  # no mission: Freeplay rules
    svc.start(CID, 'orientation')
    assert svc.switch_refusal(evelyn, nova) == svc.SWITCH_LOCKED
    assert svc.switch_refusal('custom:wren', nova) == svc.SWITCH_LOCKED  # custom characters wait for Freeplay
    assert svc.switch_refusal(nova, evelyn) is None  # selecting the mission's companion (Begin)
    assert svc.switch_refusal(evelyn, evelyn) is None  # re-selecting the current one changes nothing
    assert service(tmp_path).switch_refusal(evelyn, nova) == svc.SWITCH_LOCKED  # survives a restart
    svc.abandon()
    assert svc.switch_refusal(evelyn, nova) is None


def test_the_observer_refuses_a_model_switch_during_a_mission(tmp_path):
    from fastapi.testclient import TestClient
    from ai_observer.server import create_app
    from tests.fork.test_observer import TOKEN, ORIGIN, auth, until
    app = create_app(TOKEN, tmp_path)
    app.state.models.config = app.state.models.config.model_copy(update={'model': MODEL['nova']})
    with TestClient(app) as client:
        with client.websocket_connect('/observe', headers={'Origin': ORIGIN}) as ws:
            auth(ws)
            ws.send_json({'version': 1, 'type': 'campaign', 'action': 'start', 'campaign_id': CID, 'mission_id': 'orientation'})
            assert until(ws, 'campaign_state')['active']['mission'] == 'orientation'
            ws.send_json({'version': 1, 'type': 'select_model', 'selection': {'model': MODEL['evelyn']}})
            refused = until(ws, 'ai_error')
            assert refused['code'] == 'campaign_locked' and 'Freeplay' in refused['detail'] and refused['selection_failed']
            assert app.state.models.config.model == MODEL['nova']
            ws.send_json({'version': 1, 'type': 'campaign', 'action': 'abandon'})
            assert until(ws, 'campaign_state')['active'] is None
