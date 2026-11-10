# SPDX-License-Identifier: AGPL-3.0-only
"""Controlled role-only replay of captured synthetic Character Card requests.

Experiment only: no production compiler patch, new scheduling or output filters.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import random
import time

import httpx

from companion_ai.expressions import HEADER_REMINDER, ExpressionStream

SEEDS = (271828, 314159)
STANDING = 'STANDING INSTRUCTION FROM THE PARTICIPANT (still applies):\n'
BOUNDARY = HEADER_REMINDER + '\nA MOMENT TO SPEAK.'
EXPECTED_DECK = '39e04b7cc5362b3c83ca56b9d6c06d9a24a74da79bf07326003cf46eba95c1cb'
EXPECTED_SOURCE = 'f9eceb3f4440804bbcf4e69e8d8956eaf72d459a67e6a179f7f3950fdaca9ec5'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def separate_card_context(messages):
    """Move labelled historical context out of the current card instruction.

    Only an experiment helper. A production implementation must use the compiler's
    existing structured variables and deck-card guard, not parse user-authored text.
    """
    result = deepcopy(messages)
    if not result or result[-1]['role'] != 'user' or BOUNDARY not in result[-1]['content']:
        return result
    content = result[-1]['content']
    prefix, task = content.split(BOUNDARY, 1)
    task = BOUNDARY + task
    standing = ''
    if prefix.startswith(STANDING):
        standing, separator, prefix = prefix.partition('\n\n')
        if not separator:
            raise ValueError('Malformed generated standing-instruction block')
        standing += separator
    if not prefix:
        return result
    result[-1]['content'] = standing + task
    result.insert(len(result)-1, {'role': 'assistant', 'content': prefix})
    return result


def load_cases(source, deck):
    raw = Path(source).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_SOURCE, 'Frozen source changed'
    assert hashlib.sha256(Path(deck).read_bytes()).hexdigest() == EXPECTED_DECK, 'Personal deck changed'
    cards = {c['id']: c for c in json.loads(Path(deck).read_text())['normal']
             if c.get('audience', 'shared') != 'shared'}
    data = json.loads(raw)
    cases = []
    for row in data['companions']:
        if row['diagnostic']:
            continue
        for turn in row['turns']:
            body = deepcopy(turn['requests'][0])
            assert turn['brief'] == cards[turn['card']]['brief']
            assert turn['brief'] in body['messages'][-1]['content']
            assert not body.get('tools') and body['think'] is False and body['stream'] is True
            before = body['messages']
            after = separate_card_context(before)
            assert before[0] == after[0]
            # No words, task instructions or native/factual content are changed.
            assert ''.join(m['content'] for m in before) == ''.join(m['content'] for m in after)
            text = before[-1]['content']
            route = ('answered_user' if 'EARLIER, THE PARTICIPANT SAID' in text else
                     'story_context' if 'Story details from your conversation' in text else 'none')
            assert not text.startswith(STANDING), 'Frozen cases unexpectedly contain standing instructions'
            cases.append({'id': f"{row['identity']}/{row['sample']}/{turn['card']}",
                          'identity': row['identity'], 'model': row['model'],
                          'scenario': row['sample'], 'card': turn['card'], 'brief': turn['brief'],
                          'synthetic_context': turn['synthetic_context'],
                          'prior_user': row['user_message'], 'prior_reply': row['user_reply'],
                          'markers': ('marigold', 'tinfoil', 'paper boat') if row['sample']=='early'
                                     else ('copper', 'teacup', 'velvet', 'lantern', 'café'),
                          'route': route, 'request': body})
    assert len(cases) == 96 and len(cards) == 48
    return cases


async def generate(client, body):
    content = ''; thinking = 0; final = {}; started = time.monotonic()
    async with client.stream('POST', '/api/chat', json=body) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line:
                continue
            frame = json.loads(line)
            if frame.get('error'):
                raise RuntimeError(frame['error'])
            content += frame.get('message', {}).get('content', '')
            thinking += len(frame.get('message', {}).get('thinking', ''))
            if frame.get('done'):
                final = frame
    if not final:
        raise RuntimeError('No completed response')
    parser = ExpressionStream(card=True)
    text = (parser.feed(content) + parser.finish()).strip()
    return {'text': text, 'raw_content': content, 'expression': parser.expression,
            'thinking_characters': thinking, 'seconds': round(time.monotonic()-started, 3),
            'done_reason': final.get('done_reason'),
            'prompt_eval_count': final.get('prompt_eval_count'), 'eval_count': final.get('eval_count')}


def write_blind(out, cases, results):
    indexed = {c['id']: c for c in cases}
    selected = [r for r in results if r['seed'] == SEEDS[0]]
    random.Random(8675309).shuffle(selected)
    packet = []; key = {}
    for number, result in enumerate(selected, 1):
        case = indexed[result['case']]; blind = f'Q{number:03d}'
        key[blind] = {'case': result['case'], 'variant': result['variant'], 'seed': result['seed']}
        packet.append({'blind_id': blind, 'identity': case['identity'], 'card': case['card'],
                       'scenario': case['scenario'], 'brief': case['brief'],
                       'synthetic_context': case['synthetic_context'],
                       'prior_user': case['prior_user'], 'prior_reply': case['prior_reply'],
                       'text': result['text']})
    (out/'blind-review.json').write_text(json.dumps(packet, indent=2)+'\n')
    (out/'blind-key.json').write_text(json.dumps(key, indent=2)+'\n')


async def run(args):
    if os.environ.get('EDGELOOP_LIVE_ACCEPTANCE') != '1':
        raise RuntimeError('Set EDGELOOP_LIVE_ACCEPTANCE=1')
    if args.url != 'http://127.0.0.1:11435':
        raise ValueError('Only existing local 11435 allowed')
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    cases = load_cases(args.source, args.deck)
    if args.compiled_cases:
        compiled = json.loads(Path(args.compiled_cases).read_text())
        assert [c['id'] for c in compiled] == [c['id'] for c in cases]
        for case, actual in zip(cases, compiled):
            assert case['request'] == actual['request']
            assert actual['implemented_request']['messages'] == separate_card_context(case['request']['messages'])
            assert {k:v for k,v in actual['implemented_request'].items() if k!='messages'} == {k:v for k,v in case['request'].items() if k!='messages'}
            case['implemented_request'] = actual['implemented_request']
    (out/'cases.json').write_text(json.dumps(cases, indent=2)+'\n')
    result_file = out/'results.json'
    results = json.loads(result_file.read_text()) if args.resume and result_file.exists() else []
    completed = {(r['case'], r['seed'], r['variant']) for r in results}
    async with httpx.AsyncClient(base_url=args.url, timeout=180, trust_env=False) as client:
        tags = await client.get('/api/tags'); tags.raise_for_status()
        assert {c['model'] for c in cases} <= {m['name'] for m in tags.json()['models']}
        metadata = {}
        for model in dict.fromkeys(c['model'] for c in cases):
            response = await client.post('/api/show', json={'model': model}); response.raise_for_status()
            native = response.json().get('system', '')
            assert native and all(c['request']['messages'][0]['content'].startswith(native+'\n\n')
                                  for c in cases if c['model']==model)
            metadata[model] = {'native_system_sha256': hashlib.sha256(native.encode()).hexdigest(),
                               'details': response.json().get('details')}
        (out/'model-metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
        for index, case in enumerate(cases):
            for seed_index, seed in enumerate(SEEDS):
                order = ('A','B') if (index+seed_index)%2 == 0 else ('B','A')
                for arm in order:
                    if (case['id'], seed, arm) in completed:
                        continue
                    body = deepcopy(case['request'])
                    body['options']['seed'] = seed
                    if arm == 'B':
                        if args.compiled_cases:
                            body = deepcopy(case['implemented_request'])
                            body['options']['seed'] = seed
                        else:
                            body['messages'] = separate_card_context(body['messages'])
                    answer = await generate(client, body)
                    results.append({'case': case['id'], 'variant': arm, 'seed': seed,
                                    'request_sha256': digest(body),
                                    'literal_markers': [m for m in case['markers'] if m in answer['text'].casefold()],
                                    **answer})
                    result_file.write_text(json.dumps(results, indent=2)+'\n')
                    print(len(results), case['identity'], case['card'], seed, arm,
                          'markers='+str(bool(results[-1]['literal_markers'])), flush=True)
    write_blind(out, cases, results)
    assert len(results) == 384


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--deck', default='config/event-deck.json')
    parser.add_argument('--output', required=True)
    parser.add_argument('--url', default='http://127.0.0.1:11435')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--compiled-cases', help='Actual compiler-parity capture; B uses implemented requests directly')
    asyncio.run(run(parser.parse_args()))
