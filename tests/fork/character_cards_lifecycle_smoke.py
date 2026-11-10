# SPDX-License-Identifier: AGPL-3.0-only
"""Opt-in real F29 samples of the shared lifecycle lanes; synthetic state only.

No engine/device APIs, model creation, model pulls or persistent settings. The
normal-card harness covers all 48 personal cards separately. Read the report:
a delivered response is not a semantic quality approval.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path

from ai_observer.observation import ObserverDirector
from companion_ai.conversation import ConversationService, ModelManager
from companion_ai.director import DirectorConfig
from companion_ai.event_deck import Arrival, DeckSettings
from companion_ai.models import AIConfig
from tests.ai.test_arrival_comparison import journal, record
from tests.ai.test_character_cards import MODELS
from tests.ai.test_event_deck_content import DEFINITION
from tests.ai.test_event_deck_integration import finish
from tests.fork.character_cards_smoke import Audit
from tests.fork.event_replay import Replay

CASES = ('arrival-first', 'arrival-returning', 'arrival-greeting', 'opening',
         'edges-3-reached', 'edges-7-reached', 'edges-10-reached', 'closing',
         'emergency-stop')


async def run(args):
    if os.environ.get('EDGELOOP_LIVE_ACCEPTANCE') != '1':
        raise RuntimeError('Set EDGELOOP_LIVE_ACCEPTANCE=1')
    if args.url != 'http://127.0.0.1:11435':
        raise ValueError('Use the existing local 11435 endpoint')
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'synthetic_only': True, 'physical_hardware': False,
              'agent_controls': False, 'thinking': False, 'cases': []}
    audit = Audit()
    try:
        for identity, model in MODELS.items():
            for case in CASES:
                r = Replay()
                idle = case.startswith('arrival-')
                r.state.update(status='IDLE' if idle else 'RUNNING', edges=0, seconds=0)
                r.state['devices'].update(toy_ready=not idle, handy=not idle,
                                          hr_ready=True, simulated_hr=True)
                r.state['safety'].update(fault='none', signal='ok')
                r.step(90, seconds=0, source='simulator')
                manager = ModelManager(args.url, transport=audit)
                await manager.select(AIConfig(model=model, max_tokens=384))
                manager.current_summary = r.observation.summary
                assert manager.tool_executor is None
                frames = []
                director = ObserverDirector(DirectorConfig(), clock=r.clock.mono)
                s = ConversationService(r.observation, frames.append, manager,
                                        clock=r.clock.mono, director=director)
                s.deck_settings = DeckSettings(enabled=True, countdown_seconds=0,
                                               arrival_settle_seconds=0,
                                               simulated_session=True)
                s.deck_definition = DEFINITION
                calls = len(audit.calls)
                try:
                    if idle:
                        s.arrival = Arrival(s.active_model_id, r.clock.mono(), s.deck_settings)
                        if case == 'arrival-first':
                            r.observation.journal = journal()
                        elif case == 'arrival-returning':
                            r.observation.journal = journal([record(
                                s.active_model_id, now_ms=int(r.clock.wall()*1000),
                                edges=7, seconds=720, heart_rate={})])
                        else:
                            r.observation.journal = journal(ai_access=False)
                    elif case.startswith('edges-'):
                        value = int(case.split('-')[1])
                        deck = s.deck()
                        deck._start_done = True
                        s.deck_observe(deck, r.clock.mono())
                        deck._activated.update(seq.id for seq in DEFINITION.sequences
                                               if seq.id != f'edges-{value}')
                        r.state['edges'] = value
                        r.step(90, seconds=5, source='simulator')
                    elif case == 'closing':
                        r.state.update(edges=4, seconds=600)
                        r.step(90, seconds=0, source='simulator')
                        s.deck()._start_done = True
                        finish(r, s)
                    elif case == 'emergency-stop':
                        r.state['details']['terminal_outcome'] = 'safety_stop'
                        r.step(90, seconds=0, source='simulator', status='IDLE')
                        s.safety('emergency_stop')
                    s.pump()
                    if s.task is not None:
                        await s.task
                        await asyncio.sleep(0)
                    requests = audit.calls[calls:]
                    item = {'identity': identity, 'model': model, 'card': case,
                            'text': '\n'.join(f['text'] for f in frames if f['type']=='speech'),
                            'errors': [f for f in frames if f['type']=='conversation_error'],
                            'suppressed': [f for f in frames if f['type']=='response_suppressed'],
                            'provider_calls': len(requests), 'requests': requests,
                            'synthetic_state': {'status': r.state['status'],
                                                'edges': r.state['edges'],
                                                'seconds': r.state['seconds']},
                            'director_reason': director.last_reason}
                    if case == 'emergency-stop':
                        # An immediate deterministic safety notice is required;
                        # only model-generated commentary must be absent.
                        assert not requests, item
                        assert all(f.get('source') == 'safety' for f in frames
                                   if f['type'] == 'speech'), item
                    report['cases'].append(item)
                    output.write_text(json.dumps(report, indent=2)+'\n')
                    print(identity, case, repr(item['text']), flush=True)
                finally:
                    await s.close()
        report['provider_calls'] = len(audit.calls)
    finally:
        output.write_text(json.dumps(report, indent=2)+'\n')
        await audit.inner.aclose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:11435')
    parser.add_argument('--output', required=True)
    asyncio.run(run(parser.parse_args()))
