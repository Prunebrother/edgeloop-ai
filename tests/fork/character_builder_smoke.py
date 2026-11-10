# SPDX-License-Identifier: AGPL-3.0-only
"""Opt-in live Character Builder run on real local models; synthetic session state only.

  EDGELOOP_LIVE_ACCEPTANCE=1 python -m tests.fork.character_builder_smoke \
      --url http://127.0.0.1:11435 --output /tmp/character-builder-smoke.json

1. Wren (fixture package) on the shared base model: a user chat, then Director card turns
   in a simulated running session (event replay, no device).
2. Wren on Daisy's F29 model: the custom persona must replace Daisy's embedded identity.
3. Daisy again on the same model, without the package: the built-in identity must return.
No model creation, pulls, engine/device APIs or persistent settings. Read the transcript:
the identity checks are lexical and do not approve dialogue quality.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import tempfile

from ai_observer.observation import ObserverDirector
from companion_ai import character_builder as cb
from companion_ai.conversation import ConversationService, ModelManager
from companion_ai.director import DirectorConfig
from companion_ai.event_deck import DeckSettings
from companion_ai.models import AIConfig
from companion_ai.storage import SettingsStore
from tests.fork.character_cards_smoke import Audit
from tests.fork.event_replay import Replay

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/character-builder'
BASE = 'huihui_ai/qwen3.5-abliterated:9b'
DAISY = 'daisy-narrative-f29-v014:latest'
QUESTION = 'Tell me who you are and where we are right now, in two sentences.'
DAISY_CANON = re.compile(r'\b(?:Daisy|Cloverfield|IRRA|Proven Breeder|Evelyn|Nova|Celeste|farm)\b', re.I)
WREN_WORLD = re.compile(r'\b(?:Wren|Stillwater|Saltglass|lighthouse|lamp|keeper|tide|gull|storm)\b', re.I)


def wren(model):
    world = json.loads((FIXTURE / 'world-saltglass.json').read_text())
    character = json.loads((FIXTURE / 'character-wren.json').read_text()) | {'model': model}
    return cb.load_package(cb.compose(world, character, (FIXTURE / 'wren.png').read_bytes()))


def replay():
    r = Replay()
    r.state['devices'].update(toy_ready=True, handy=True, hr_ready=True, simulated_hr=True)
    r.state['safety'].update(fault='none', signal='ok')
    r.state.update(status='RUNNING', edges=0, seconds=0)
    r.step(88, seconds=0, source='simulator')
    return r


async def service(url, audit, model, character, r, store):
    manager = ModelManager(url, transport=audit, store=store)
    await manager.select(AIConfig(model=model, max_tokens=384), character=character)
    manager.current_summary = r.observation.summary
    frames = []
    director = ObserverDirector(DirectorConfig(), clock=r.clock.mono)
    s = ConversationService(r.observation, frames.append, manager, clock=r.clock.mono, director=director)
    s.deck_settings = DeckSettings(enabled=True, countdown_seconds=0, simulated_session=True)
    return manager, s, frames, director


def spoken(frames, start=0):
    return [f for f in frames[start:] if f['type'] == 'speech']


async def ask(s, frames):
    start = len(frames)
    s.request(QUESTION, True)
    await s.task
    return ' '.join(f['text'] for f in spoken(frames, start))


async def run(args):
    if os.environ.get('EDGELOOP_LIVE_ACCEPTANCE') != '1':
        raise RuntimeError('Set EDGELOOP_LIVE_ACCEPTANCE=1 for real local inference')
    if args.url != 'http://127.0.0.1:11435':
        raise ValueError('Use the existing local 11435 endpoint')
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'synthetic_only': True, 'physical_hardware': False, 'agent_controls': False, 'thinking': False,
              'package_sha256': wren(BASE).content_sha256, 'steps': []}
    audit = Audit()
    store = SettingsStore(tempfile.mkdtemp(prefix='character-builder-smoke-'))
    try:
        # 1. Wren on the shared base model: chat, then Director card turns.
        r = replay()
        manager, s, frames, director = await service(args.url, audit, BASE, wren(BASE), r, store)
        reply = await ask(s, frames)
        report['steps'].append({'case': 'wren_base_chat', 'model': BASE, 'text': reply,
                                'canon_leak': bool(DAISY_CANON.search(reply)), 'world_terms': sorted({m.casefold() for m in WREN_WORLD.findall(reply)})})
        print('wren/base chat:', reply, flush=True)
        cards = []
        for turn in range(args.cards):
            for _ in range(8):
                r.step(90 + turn % 3, seconds=15, source='simulator')
            if turn == 1:
                r.state['edges'] = 2
                r.step(92, seconds=1, source='simulator')
            calls = len(audit.calls)
            start = len(frames)
            s.pump()
            if s.task is not None and not s.task.done():
                await s.task
            request = audit.calls[calls:]
            card_text = request[-1]['messages'][-1]['content'] if request else ''
            card_id = next((c.id for c in wren(BASE).cards if c.brief in card_text), 'shared:' + (re.search(r'Task: (.{0,60})', card_text) or [None, ''])[1] if card_text else None)
            text = ' '.join(f['text'] for f in spoken(frames, start))
            cards.append({'turn': turn, 'card': card_id, 'text': text, 'director_reason': director.last_reason,
                          'persona_in_system': bool(request) and request[-1]['messages'][0]['content'].startswith(wren(BASE).persona_system),
                          'suppressed': [f.get('reason') for f in frames[start:] if f['type'] == 'response_suppressed']})
            print(f'wren/base card {turn}:', card_id, '->', text or director.last_reason, flush=True)
        report['steps'].append({'case': 'wren_base_cards', 'cards': cards})
        await s.close()

        # 2. Wren on Daisy's own model: persona replaces the embedded identity.
        r = replay()
        manager, s, frames, _ = await service(args.url, audit, DAISY, wren(DAISY), r, store)
        reply = await ask(s, frames)
        system = audit.calls[-1]['messages'][0]['content']
        report['steps'].append({'case': 'wren_on_daisy_model', 'model': DAISY, 'text': reply,
                                'system_has_daisy': 'Daisy' in system, 'canon_leak': bool(DAISY_CANON.search(reply)),
                                'world_terms': sorted({m.casefold() for m in WREN_WORLD.findall(reply)})})
        print('wren/daisy-model chat:', reply, flush=True)
        await s.close()

        # 3. Built-in Daisy on the same model, same store: built-in compatibility.
        r = replay()
        manager, s, frames, _ = await service(args.url, audit, DAISY, None, r, store)
        reply = await ask(s, frames)
        report['steps'].append({'case': 'daisy_builtin', 'model': DAISY, 'text': reply,
                                'daisy_identity': bool(re.search(r'\b(?:Daisy|Cloverfield)\b', reply)),
                                'wren_leak': bool(re.search(r'\b(?:Wren|Stillwater|Saltglass)\b', reply))})
        print('daisy builtin chat:', reply, flush=True)
        await s.close()
        report['provider_calls'] = len(audit.calls)
    finally:
        output.write_text(json.dumps(report, indent=2) + '\n')
        await audit.inner.aclose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:11435')
    parser.add_argument('--output', required=True)
    parser.add_argument('--cards', type=int, default=6)
    asyncio.run(run(parser.parse_args()))
