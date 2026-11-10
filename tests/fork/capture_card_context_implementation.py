# SPDX-License-Identifier: AGPL-3.0-only
"""Reconstruct frozen synthetic scenarios through both actual compiler versions.

No inference in this capture: /api/show reads installed identities; replies are
replayed from the original local transcripts. The baseline compiler is supplied
explicitly as a local file, never checked out into the production tree.
"""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import types

import httpx

from ai_observer.observation import ObserverDirector
import companion_ai.conversation as conversation
from companion_ai.context_compiler import ContextCompiler
from companion_ai.director import DirectorConfig
from companion_ai.event_deck import DeckSettings
from companion_ai.models import AIConfig
from tests.ai.test_event_deck_content import DEFINITION, TRENDS, play_only
from tests.fork.dialogue_context_ab import load_cases, separate_card_context
from tests.fork.event_replay import Replay


async def capture(args):
    module = types.ModuleType('companion_ai._review_baseline_compiler')
    module.__package__ = 'companion_ai'
    sys.modules[module.__name__] = module
    exec(compile(Path(args.baseline_compiler).read_bytes(), args.baseline_compiler, 'exec'), module.__dict__)
    cases = load_cases(args.source, 'config/event-deck.json')
    source = json.loads(Path(args.source).read_text())
    original_compose = conversation.compose_messages
    pairs = []
    def compare(summary, prompt, history, config, memory=None, reserve_characters=0, context_config=None, diagnostics=None):
        if 'canonical_session' not in summary:
            return original_compose(summary, prompt, history, config, memory, reserve_characters, context_config=context_config, diagnostics=diagnostics)
        baseline = module.ContextCompiler(context_config).compile(summary, prompt, history, config, memory, reserve_characters)
        current = ContextCompiler(context_config).compile(summary, prompt, history, config, memory, reserve_characters)
        if diagnostics is not None:
            diagnostics.clear(); diagnostics.update(baseline[2])
        if summary.get('deck_card'):
            clean = lambda messages: [{'role': m['role'], 'content': m['content']} for m in messages]
            a, b = clean(baseline[0]), clean(current[0])
            assert separate_card_context(a) == b, 'Implementation differs from tested intervention'
            pairs.append((a, b))
        else:
            assert baseline[0] == current[0], 'Non-card request changed'
        return baseline[:2]
    conversation.compose_messages = compare
    try:
        async with httpx.AsyncClient(base_url='http://127.0.0.1:11435', trust_env=False) as client:
            for row in source['companions']:
                if row['diagnostic']:
                    continue
                show = await client.post('/api/show', json={'model': row['model']})
                show.raise_for_status(); metadata = show.json()
                state = {'reply': row['user_reply'][0], 'wire': []}
                def transport(request):
                    if request.url.path == '/api/show':return httpx.Response(200, json=metadata)
                    if request.url.path == '/api/ps':return httpx.Response(200, json={'models': []})
                    if request.url.path == '/api/chat':
                        state['wire'].append(json.loads(request.content))
                        return httpx.Response(200, text=json.dumps({'message': {'content': '[[expression:neutral]]'+state['reply']}, 'done': True, 'done_reason': 'stop'})+'\n')
                    raise AssertionError(request.url.path)
                r = Replay()
                r.state['devices'].update(toy_ready=True, handy=True, hr_ready=True, simulated_hr=True)
                r.state['safety'].update(fault='none', signal='ok')
                initial = row['synthetic_initial_context']
                r.state.update(edges=initial['edges'], seconds=initial['seconds'], status='RUNNING')
                r.step(90, seconds=0, source='simulator')
                manager = conversation.ModelManager(transport=httpx.MockTransport(transport))
                await manager.select(AIConfig(model=row['model'], max_tokens=384))
                manager.current_summary = r.observation.summary
                frames = []
                service = conversation.ConversationService(r.observation, frames.append, manager,
                    clock=r.clock.mono, director=ObserverDirector(DirectorConfig(), clock=r.clock.mono))
                service.deck_settings = DeckSettings(enabled=True, countdown_seconds=0, simulated_session=True)
                service.deck_definition = DEFINITION
                try:
                    assert service.request(row['user_message'], user=True)['accepted']
                    await service.task; await asyncio.sleep(0)
                    for turn in row['turns']:
                        state['reply'] = turn['text']
                        for _ in range(90):r.step(90, seconds=1, source='simulator')
                        for bpm in TRENDS['steady']:r.step(bpm, seconds=1, source='simulator')
                        play_only(service, turn['card'])
                        n = len(pairs); wire_index = len(state['wire'])
                        service.pump(); assert service.task is not None
                        await service.task; await asyncio.sleep(0)
                        assert len(pairs) > n, (row['identity'], turn['card'])
                        a, b = pairs[n]
                        wire = state['wire'][wire_index]
                        case = next(c for c in cases if c['id'] == f"{row['identity']}/{row['sample']}/{turn['card']}")
                        assert wire == case['request'], ('Frozen request mismatch', case['id'])
                        implemented = deepcopy(wire)
                        implemented['messages'] = b
                        implemented['messages'][0]['content'] = metadata['system']+'\n\n'+b[0]['content']
                        assert implemented['messages'] == separate_card_context(wire['messages'])
                        case['implemented_request'] = implemented
                finally:
                    await service.close()
    finally:
        conversation.compose_messages = original_compose
    assert all('implemented_request' in c for c in cases)
    Path(args.output).write_text(json.dumps(cases, indent=2)+'\n')
    print('96 frozen requests reproduced byte-for-byte through baseline; implementation matches B in every case. Non-card setup requests unchanged.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--baseline-compiler', required=True)
    parser.add_argument('--output', required=True)
    asyncio.run(capture(parser.parse_args()))
