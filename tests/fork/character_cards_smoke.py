# SPDX-License-Identifier: AGPL-3.0-only
"""Opt-in character-card quality sample; existing local models, no device connection.

Run from the repository root:
  EDGELOOP_LIVE_ACCEPTANCE=1 python -m tests.fork.character_cards_smoke \
      --url http://127.0.0.1:11435 --output /tmp/character-cards-smoke.json
Each card is isolated to guarantee two samples in different simulated sessions
(plus normal bounded retries). Shuffle and duplicate delivery are tested separately.
Read the transcript: lexical repetition checks do not establish dialogue quality.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time

import httpx

from ai_observer.observation import ObserverDirector
from companion_ai.conversation import ConversationService, ModelManager
from companion_ai.director import DirectorConfig, repetition
from companion_ai.event_deck import DeckSettings
from companion_ai.models import AIConfig
from tests.ai.test_character_cards import CARDS, MODELS
from tests.ai.test_event_deck_content import DEFINITION, TRENDS, play_only
from tests.fork.event_replay import Replay


class Audit(httpx.AsyncBaseTransport):
    def __init__(self):
        self.inner = httpx.AsyncHTTPTransport()
        self.calls = []

    async def handle_async_request(self, request):
        assert request.url.path in {'/api/show', '/api/ps', '/api/chat'}
        if request.url.path == '/api/chat':
            body = json.loads(request.content)
            assert body['think'] is False and not body.get('tools')
            self.calls.append(body)
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        pass  # Provider clients share this pool; the harness closes it once.


# Deliberately unrelated, answered prompts expose stale-message callbacks.
SCENARIOS = (
    ('early', 2, 600, 'For a fictional paper boat, pick either Marigold or Tinfoil as its name.',
     ('marigold', 'tinfoil', 'paper boat')),
    ('established', 5, 1300, 'Choose a fictional café name: Copper Teacup or Velvet Lantern.',
     ('copper', 'teacup', 'velvet', 'lantern', 'café')),
)
DIAGNOSTIC = {'nova': 'nova-borrowed-wonder', 'daisy': 'daisy-gate-debate',
              'evelyn': 'evelyn-after-hours', 'celeste': 'celeste-polished-excuse'}


async def run(args):
    if os.environ.get('EDGELOOP_LIVE_ACCEPTANCE') != '1':
        raise RuntimeError('Set EDGELOOP_LIVE_ACCEPTANCE=1 for real local inference')
    report = {'base': 'e60708a', 'url': args.url, 'thinking': False,
              'hardware': 'none; synthetic Replay observations only', 'companions': [],
              'quality': 'Manual transcript review required; two samples are not a reliability estimate.'}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    previous_calls = 0
    if args.resume and output.exists():
        report = json.loads(output.read_text())
        assert report['url'] == args.url and report['base'] == 'e60708a'
        complete = []
        for row in report['companions']:
            expected = {c.id: c.brief for c in CARDS if c.audience == row['identity']}
            if row['diagnostic']:
                expected = {DIAGNOSTIC[row['identity']]: expected[DIAGNOSTIC[row['identity']]]}
            assert row['model'] == MODELS[row['identity']]
            assert all(expected[t['card']] == t['brief'] for t in row['turns'])
            if {t['card'] for t in row['turns']} == set(expected) and len(row['turns']) == len(expected):
                complete.append(row)
            else:
                report.setdefault('incomplete_attempts', []).append(row)
        report['companions'] = complete
        previous_calls = report.get('provider_calls', 0)
    audit = Audit()
    try:
        for identity, model in MODELS.items():
            scenarios = list(SCENARIOS)
            if args.diagnostics:
                scenarios += [('original-message', 0, 0, 'What is your name? Please answer briefly.',
                               ('brevity', 'briefly', 'your name')),
                              ('no-prior-message', 0, 0, None, ())]
            for sample, edges, seconds, user, markers in scenarios:
                if any(row['identity'] == identity and row['sample'] == sample
                       for row in report['companions']):
                    continue
                r = Replay()
                # These flags belong only to the in-memory synthetic observation.
                r.state['devices'].update(toy_ready=True, handy=True, hr_ready=True, simulated_hr=True)
                r.state['safety'].update(fault='none', signal='ok')
                r.state.update(edges=edges, seconds=seconds, status='RUNNING')
                r.step(90, seconds=0, source='simulator')
                manager = ModelManager(args.url, transport=audit)
                await manager.select(AIConfig(model=model, max_tokens=384))
                manager.current_summary = r.observation.summary
                frames = []
                director = ObserverDirector(DirectorConfig(), clock=r.clock.mono)
                s = ConversationService(r.observation, frames.append, manager,
                                        clock=r.clock.mono, director=director)
                s.deck_settings = DeckSettings(enabled=True, countdown_seconds=0, simulated_session=True)
                s.deck_definition = DEFINITION
                row = {'identity': identity, 'model': model, 'sample': sample,
                       'diagnostic': sample not in {'early', 'established'},
                       'synthetic_initial_context': {'status': 'RUNNING', 'edges': edges,
                                                     'seconds': seconds, 'heart_rate': 90, 'hr_source': 'simulator'},
                       'turns': [], 'user_message': user, 'user_reply': []}
                report['companions'].append(row)
                try:
                    if user:
                        assert s.request(user, user=True)['accepted']
                        await s.task
                        await asyncio.sleep(0)
                        row['user_reply'] = [f['text'] for f in frames if f['type'] == 'speech']
                        row['user_errors'] = [f for f in frames if f['type'] == 'conversation_error']
                        assert row['user_reply'] and not row['user_errors'], row
                    cards = [c for c in CARDS if c.audience == identity]
                    if row['diagnostic']:
                        cards = [c for c in cards if c.id == DIAGNOSTIC[identity]]
                    elif sample == 'established':
                        cards.reverse()
                    previous = []
                    for card in cards:
                        # Advance fresh observations past user grace/output time.
                        # Keep the simulated sensor continuously available: removing
                        # it after an HR card correctly gates later speech as a disconnect.
                        for _ in range(90):
                            r.step(90, seconds=1, source='simulator')
                        synthetic_hr = list(TRENDS['steady'])
                        for bpm in synthetic_hr:
                            r.step(bpm, seconds=1, source='simulator')
                        play_only(s, card.id)
                        before, calls = len(frames), len(audit.calls)
                        started = time.monotonic()
                        s.pump()
                        assert s.task is not None and not s.task.done(), s.director.last_reason
                        await s.task
                        await asyncio.sleep(0)
                        visible = [f['text'] for f in frames[before:] if f['type'] == 'speech']
                        text = '\n'.join(visible)
                        item = {'card': card.id, 'brief': card.brief, 'text': text,
                                'synthetic_context': {'status': r.state['status'], 'edges': r.state['edges'],
                                                      'seconds': r.state['seconds'], 'heart_rate': r.state['hr'],
                                                      'hr_source': 'simulator' if synthetic_hr else 'unavailable',
                                                      'synthetic_hr_samples': synthetic_hr},
                                'seconds': round(time.monotonic() - started, 2),
                                'provider_calls': len(audit.calls) - calls,
                                'requests': audit.calls[calls:],
                                'repetition': repetition(text, previous) if text else None,
                                'prior_message_markers': [m for m in markers if m in text.casefold()],
                                'errors': [f for f in frames[before:] if f['type'] == 'conversation_error'],
                                'suppressed': [f for f in frames[before:] if f['type'] == 'response_suppressed']}
                        row['turns'].append(item)
                        if text:
                            previous.append(text)
                        report['provider_calls'] = previous_calls + len(audit.calls)
                        output.write_text(json.dumps(report, indent=2) + '\n')
                        print(identity, sample, card.id, repr(text), flush=True)
                finally:
                    await s.close()
        report['provider_calls'] = previous_calls + len(audit.calls)
    finally:
        output.write_text(json.dumps(report, indent=2) + '\n')
        await audit.inner.aclose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:11435')
    parser.add_argument('--resume', action='store_true', help='Retain complete runs after validating their briefs; archive and restart partial runs')
    parser.add_argument('--diagnostics', action='store_true', help='Compare the original prior message with no prior message')
    parser.add_argument('--output', default='/tmp/character-cards-smoke.json')
    asyncio.run(run(parser.parse_args()))
