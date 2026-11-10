# SPDX-License-Identifier: AGPL-3.0-only
"""Upstream-integration guards: snapshot/protocol stay in step with the engine's
modes, the observer protocol carries no commands, and the local server never
exposes an agent or relay endpoint."""
import pytest
import re
import typing
from pathlib import Path

from ai_observer import protocol
from tools.serve_local import public_file

ROOT = Path(__file__).resolve().parents[2]


def js_list(source: str, name: str) -> list[str]:
    match = re.search(rf'{name}\s*=\s*\[([^\]]*)\]', source)
    assert match, f'{name} not found'
    return re.findall(r"'([^']+)'", match.group(1))


def literal(annotation) -> list[str]:
    return list(typing.get_args(annotation))


ENGINE = (ROOT / 'src/js/engine.js').read_text()
SNAPSHOT = (ROOT / 'src/js/ai/snapshot.js').read_text()
TEASE = js_list(ENGINE, 'export const TEASE_MODES')
GAMES = js_list(ENGINE, 'export const GAME_MODES')


def test_snapshot_and_protocol_accept_every_engine_play_style():
    # A play style the observer does not know makes the projection fail closed,
    # which silently blinds the companion for that session.
    # 'script' is set by the video player (applyModeSelection('script')) and is
    # not part of TEASE_MODES; observe it whenever the engine can select it.
    app = (ROOT / 'src/js/app.js').read_text()
    styles = set(TEASE) | ({'script'} if "applyModeSelection('script')" in app else set())
    assert sorted(js_list(SNAPSHOT, 'const modes')) == sorted(styles)
    assert sorted(literal(protocol.Mode)) == sorted(styles)
    active = literal(protocol.Snapshot.model_fields['active_mode'].annotation)
    assert styles | set(GAMES) <= set(active)


def test_snapshot_and_protocol_accept_every_engine_goal():
    goals = js_list(SNAPSHOT, 'const goals')
    assert set(GAMES) | {'tease', 'nnn'} <= set(goals)
    assert sorted(literal(protocol.Goal)) == sorted(goals)


COMMANDS = {'SESSION_STATE', 'SESSION_RESET', 'MODE_CHANGE', 'ENDGAME', 'DURATION', 'INTENSITY',
            'SPEED_WINDOW', 'ORGASM_TOGGLE', 'EDGE_MARK', 'MANUAL_PATTERN', 'MANUAL_LEVEL'}


def test_observer_protocol_is_closed_and_has_no_engine_commands():
    schema = protocol.Messages.json_schema()
    types = set()

    def walk(node):
        if isinstance(node, dict):
            if 'type' in node.get('properties', {}):
                const = node['properties']['type'].get('const')
                if const: types.add(const)
            for child in node.values(): walk(child)
        elif isinstance(node, list):
            for child in node: walk(child)
    walk(schema)
    assert types == {'observation', 'select_model', 'chat', 'list_models', 'cancel_generation',
                     'reset_narrative', 'get_character_state', 'configure_director', 'configure_events',
                     'conversation_activity', 'configure_context', 'update_objective', 'session_journal',
                     'configure_curator','settings_outcome','character_builder'}
    assert not types & COMMANDS


def test_ai_settings_requests_use_their_own_bounded_vocabulary():
    """AI Settings Control (docs/fork/dev/AI_SETTINGS_CONTROL.md): the observer may only *request* one of these,
    and the browser's engine-side gate decides. No engine command name is ever sent."""
    from companion_ai.settings_control import SETTINGS, Proposal
    assert set(SETTINGS)=={'play_style','game','endgame','orgasm','intensity','pause','stop'}
    assert not set(SETTINGS) & COMMANDS
    assert set(Proposal.model_json_schema()['properties']['change']['enum'])==set(SETTINGS)|{'none'}
    source=(ROOT/'companion_ai/settings_control.py').read_text()
    assert not any(command in source for command in COMMANDS)
    assert "'type':'settings_request'" in source


def test_observer_server_never_emits_engine_commands():
    server = (ROOT / 'ai_observer/server.py').read_text()
    emitted = set(re.findall(r"'type':'([A-Za-z_]+)'", server))
    assert emitted and not emitted & COMMANDS


def test_local_server_exposes_no_agent_relay_or_worker_paths(tmp_path):
    for raw in ['/api/agent/abcdefghijklmnopqrstuv', '/api/agent', '/api/room/peer', '/worker/index.js',
                '/tools/edgeloop_openwebui.py', '/wrangler.jsonc', '/app/host.mjs', '/ai_observer/server.py']:
        assert public_file(raw) is None, raw


def test_director_has_a_display_name_for_every_observable_mode_and_goal():
    from companion_ai.grounding import MODE_NAMES
    active = literal(protocol.Snapshot.model_fields['active_mode'].annotation)
    for value in set(literal(protocol.Mode)) | set(literal(protocol.Goal)) | set(active):
        assert MODE_NAMES.get(value), value
    assert MODE_NAMES['bratty'] == 'Bratty Tease' and MODE_NAMES['nnn'] == 'No Nut November'


def test_pause_reason_reaches_validated_facts_and_director_wording():
    from ai_observer.observation import BrowserObservation
    from ai_observer.protocol import Observation
    from companion_ai.grounding import render_facts, SessionFacts
    from tests.fork.grounding_cases import Clock, snapshot, frame
    clock = Clock(); observation = BrowserObservation(clock.mono, clock.wall)
    value = snapshot(clock, status='PAUSED')
    value['details'].update(pause_reason='edged', warmup_active=False, warmup_remaining_seconds=None)
    observation.accept(Observation.model_validate(frame(value)))
    fact = SessionFacts.model_validate(observation.canonical()).facts['pause_reason']
    assert fact.known and fact.current and fact.value == 'edged'
    text = render_facts(observation.canonical())
    assert 'Edged button: the user marked an edge (not counted as a pause) [edged]' in text
    value = snapshot(clock); value['details']['pause_reason'] = None
    running = BrowserObservation(clock.mono, clock.wall); running.accept(Observation.model_validate(frame(value)))
    assert not SessionFacts.model_validate(running.canonical()).facts['pause_reason'].known


def test_pause_reason_is_a_closed_category():
    import pydantic
    import pytest
    from ai_observer.protocol import Observation
    from tests.fork.grounding_cases import Clock, snapshot, frame
    value = snapshot(Clock(), status='PAUSED')
    value['details'].update(pause_reason=':'.join(['AA', 'BB', 'CC', 'DD', 'EE', 'FF']), warmup_active=False, warmup_remaining_seconds=None)
    with pytest.raises(pydantic.ValidationError):
        Observation.model_validate(frame(value))


def test_director_context_names_the_pause_reason_only_while_paused():
    from ai_observer.observation import BrowserObservation
    from ai_observer.protocol import Observation
    from companion_ai.context_compiler import ContextCompiler
    from companion_ai.models import AIConfig, MemoryConfig
    from tests.fork.grounding_cases import Clock, snapshot, frame

    def prompt_for(status, reason):
        clock = Clock(); observation = BrowserObservation(clock.mono, clock.wall)
        value = snapshot(clock, status=status)
        value['details'].update(pause_reason=reason, warmup_active=False, warmup_remaining_seconds=None)
        observation.accept(Observation.model_validate(frame(value)))
        summary = observation.summary() | {'conversation_source': 'user'}
        messages, _, _ = ContextCompiler().compile(summary, 'How is it going?', [], AIConfig(max_tokens=320), MemoryConfig(max_messages=64))
        return '\n'.join(m['content'] for m in messages)
    assert 'Why the engine is paused [pause_reason]: Relube break' in prompt_for('PAUSED', 'relube')
    assert 'pause_reason' not in prompt_for('RUNNING', None)


def test_selection_source_is_a_closed_category():
    from ai_observer.protocol import Observation
    from tests.fork.grounding_cases import Clock, frame, snapshot
    clock = Clock()
    for source in ('selection', 'media'):
        value = snapshot(clock); value['details'].update(selection_source=source, warmup_active=False, warmup_remaining_seconds=None)
        assert Observation.model_validate(frame(value)).snapshot.details.selection_source == source
    value = snapshot(clock); value['details'].update(selection_source='agent', warmup_active=False, warmup_remaining_seconds=None)
    with pytest.raises(Exception):
        Observation.model_validate(frame(value))
    # Older pages that do not send it are read as a selection.
    value = snapshot(clock); value['details'].pop('selection_source', None)
    assert Observation.model_validate(frame(value)).snapshot.details.selection_source == 'selection'


@pytest.mark.parametrize('source,spoken', [('selection', True), ('media', False)])
def test_media_caused_play_style_change_is_recorded_but_not_acknowledged_as_a_selection(tmp_path, source, spoken):
    from fastapi.testclient import TestClient
    from ai_observer.server import create_app
    from tests.ai.test_f25 import runtime
    from tests.fork.grounding_cases import Clock, frame, snapshot
    from tests.fork.test_observer import ORIGIN, TOKEN, auth, until
    clock = Clock(); wire = []
    app = create_app(TOKEN, tmp_path, clock=clock.mono, transport=runtime(wire)); app.state.observation.wall = clock.wall
    value = snapshot(clock); value.update(status='IDLE'); value['details'].update(warmup_active=False, warmup_remaining_seconds=None)
    with TestClient(app) as client:
        with client.websocket_connect('/observe', headers={'Origin': ORIGIN}) as ws:
            ready = auth(ws)
            def observe(sequence, kinds):
                f = frame(value, sequence, kinds); f['epoch'] = ready['epoch']; ws.send_json(f)
                return until(ws, 'observation_ack')
            observe(0, [])
            clock.tick(.3); value['details']['captured_at_ms'] = int(clock.wall() * 1000)
            value.update(experience='script', active_mode='script'); value['details']['selection_source'] = source
            observe(1, ['experience_changed'])
            records = [r for r in app.state.speech.event_intelligence.history if r['event'].get('kind') == 'experience_changed']
            assert records, 'the play-style change was not recorded'
            if spoken:
                assert any(e['kind'] == 'experience_changed' for e in app.state.speech.pending)
            else:
                assert records[-1]['decision'] == 'context_only:media_initialization'
                assert not any(e['kind'] == 'experience_changed' for e in app.state.speech.pending)
                assert app.state.observation.report['experience'] == 'script'
