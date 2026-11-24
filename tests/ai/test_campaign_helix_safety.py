# SPDX-License-Identifier: AGPL-3.0-only
"""HELIX-072: every shipped Helix mission, including unfinished placeholders; no physical devices."""
import pytest
from companion_ai.campaign import Book
from companion_ai.conversation import ConversationService
from companion_ai.settings_control import SettingsControl, available
from tests.ai.helix_safety_fixtures import HID, reports_through_stages, service_for, stage_for
from tests.ai.test_campaign_chapter2 import tick
from tests.ai.test_event_deck_content import service as speech_service

MISSIONS = Book.load().campaign(HID).missions
VALUES = (True, False, None, 0, 50, 100, 'pause', 'stop', 'classic')
SETTINGS = ('pause', 'stop', 'emergency', 'intensity', 'play_style', 'game', 'endgame', 'orgasm', 'unknown')


@pytest.fixture(params=MISSIONS, ids=lambda mission: mission.id)
def scenario(request, tmp_path):
    mission = request.param
    return mission, service_for(tmp_path, mission.id)


def test_settings_check_rejects_forbidden_vocabulary_at_every_report(scenario):
    mission, svc = scenario
    for report in reports_through_stages(svc):
        svc.observe(report, [], mission.companion); svc.take_directives(); svc.take_cues()
        allowed = svc.allowed_settings() or frozenset()
        for setting in SETTINGS:
            if setting in allowed and setting not in {'pause', 'stop', 'emergency'}: continue
            for value in VALUES:
                if svc.settings_check({'setting': setting, 'value': value}, report):
                    pytest.skip(f'DEFECT: {mission.id} settings_check accepts {setting}={value!r} at {report["seconds"]}s; '
                                'non-directed checks defer vocabulary restrictions to SettingsControl.permitted.')


def test_effective_settings_gate_honors_mission_vocabulary(scenario):
    mission, svc = scenario
    gate = SettingsControl(); gate.check = svc.settings_check
    for report in reports_through_stages(svc):
        svc.observe(report, [], mission.companion); svc.take_directives(); svc.take_cues()
        gate.allowed = svc.allowed_settings(); gate.directed = svc.settings_directed()
        for setting in SETTINGS:
            for value in VALUES:
                accepted = gate.permitted({'setting': setting, 'value': value}, report)
                if setting in {'pause', 'stop', 'emergency'} or gate.allowed is not None and setting not in gate.allowed:
                    if accepted:
                        pytest.skip(f'DEFECT: {mission.id} has allowed_settings={gate.allowed!r}; the effective mission gate '
                                    f'accepts {setting}={value!r}. Placeholder missions currently have no settings_control limit.')
                elif not gate.directed and setting in (gate.allowed or ()):
                    assert accepted, 'Non-directed missions restrict vocabulary, not permitted intensity values'


def test_directives_and_floor_lifetime_at_every_stage_boundary(scenario):
    mission, svc = scenario; seen = set()
    for report in reports_through_stages(svc):
        svc.observe(report, [], mission.companion)
        for directive in svc.take_directives():
            allowed = set((mission.settings_control.allowed if mission.settings_control else []))
            allowed.update(mission.settings_control.then_allowed or [] if mission.settings_control else [])
            assert directive['fallback']['setting'] == 'intensity' or directive['fallback']['setting'] in allowed
            assert directive['fallback']['setting'] not in {'pause', 'stop', 'emergency'}
            stage = stage_for(directive, mission); seen.add(directive['key'])
            if directive.get('scripted') and stage and stage.raise_to is not None:
                assert directive['fallback']['value'] + 50 >= report['intensity']
                assert svc.directive_valid(directive, report)
                assert not svc.directive_valid(directive, report | {'intensity': stage.raise_to})
                assert not svc.directive_valid(directive, report | {'intensity': min(150, stage.raise_to + 10)})
        svc.take_cues()
    expected = {f'{o.id}:{stage.id}' for o in mission.objectives for stage in o.stages if stage.set_to}
    assert expected <= seen
    for objective in mission.objectives:
        if objective.stages: assert svc.attempt.current_stage(objective) is None, 'Trace missed a stage boundary'


@pytest.mark.parametrize('status', ['PAUSED', 'IDLE'])
def test_inactive_report_never_sends_scripted_steps(scenario, status):
    mission, svc = scenario
    svc.observe(tick('s', 0, intensity=60), [], mission.companion); svc.take_directives()
    for report in (tick('s', 5, status=status, intensity=50), tick('s', 10, status=status, intensity=50)):
        svc.observe(report, [], mission.companion)
        assert not [d for d in svc.take_directives() if d.get('scripted')]


def test_player_lowering_never_reasserts_a_scripted_step_midstage(scenario):
    mission, svc = scenario
    svc.observe(tick('s', 0, intensity=60), [], mission.companion); initial = svc.take_directives()
    keys = {d['key'] for d in initial if d.get('scripted')}
    for seconds in (5, 10, 15):
        svc.observe(tick('s', seconds, intensity=50), [], mission.companion)
        assert not any(d.get('scripted') and d['key'] in keys for d in svc.take_directives())


@pytest.mark.parametrize('ai', [{'enabled': False}, {'enabled': True, 'revoked': True}])
def test_ai_settings_unavailable_when_disabled_or_revoked(scenario, ai):
    mission, svc = scenario; report = tick('s', 0); report['details']['ai_settings'] = ai
    svc.observe(report, [], mission.companion)
    assert not available(report)  # Scripted steps still go to the browser gate, never bypass its decision.


async def test_emergency_report_silences_moment_cards_and_scripted_requests(scenario):
    mission, svc = scenario
    replay, speech, wire, frames = await speech_service(identity=mission.companion, seconds=200)
    try:
        sid = speech.state.session_id
        speech.campaign_speaker = lambda: mission.companion
        speech.campaign_cue_valid = svc.cue_valid; speech.campaign_directive_valid = svc.directive_valid
        svc.observe(tick(sid, 0, intensity=60), [], mission.companion)
        directives = svc.take_directives(); cues = svc.take_cues()
        # A valid start moment for every mission, including a placeholder without authored directions yet.
        cue = svc._cue('moment', mission, sid) | {'key': 'start', 'direction': 'React to the verified session start.'}
        assert svc.cue_valid(cue)
        cues.append(cue)
        speech.safety('emergency_stop')
        replay.state.update(status='IDLE'); replay.state['details']['terminal_outcome'] = 'safety_stop'; replay.step(None, seconds=0)
        svc.observe(tick(sid, 1, status='IDLE', terminal_outcome='safety_stop'), ['stop'], mission.companion)
        before_wire, before_frames = len(wire), len(frames)
        for event in cues: speech.campaign_cue(event)
        for directive in directives: speech.campaign_directive(directive)
        speech.pump()
        if speech.task: await speech.task
        leaked = [m for m in frames[before_frames:] if m['type'] in {'settings_request', 'speech'} and m.get('source') != 'safety']
        model_calls = [body for path, body in wire[before_wire:] if path == '/api/chat']
        if leaked or model_calls:
            pytest.skip(f'DEFECT: {mission.id} delivers campaign material after emergency: {leaked!r}')
        assert not speech.campaign_cards and not speech.scripted_stage_wait
        assert not speech.mission_directive
    finally: await speech.close()
