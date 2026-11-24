# SPDX-License-Identifier: AGPL-3.0-only
"""Opt-in live-model check for Rise of Helix missions (HELIX-071 groundwork; not part of the test suite).

Like tools/campaign_live_check.py: the real observer on an isolated loopback port with a temporary data
directory and the real local companion model, driven over the real websocket protocol in real time.
Additionally it answers choices and puzzles, plays the engine-side gate for intensity requests (the
mission's scripted ramp or the companion's own control, applied within 50-125%), and records every
spoken line with the card or cue that produced it, every scripted line and every settings outcome.

    python tools/helix_live_check.py --out DIR [--plan NAME ...]
"""
import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
import uvicorn
import websockets
from ai_observer.server import create_app
from companion_ai.campaign import Book, PROGRESS_FILE, SCHEMA_VERSION
from campaign_live_check import Session, resolve_models, TOKEN, ORIGIN

AID, HID = 'asterion_initiative', 'rise_of_helix'
LIMITS = (50, 125)  # the default AI intensity limits a player would have
# Steps run on the session clock: (seconds, action, *args). Actions: edges n, orgasm n, answer objective option,
# ask text. The plan ends `tail` seconds after the last step (completion card and Director reactions).
PLANS = {
    'h1_defector': {'mission': 'h1_entry_protocol', 'flags': {}, 'tail': 90, 'steps': [
        (5, 'ask', 'Hi Iris. What happens today?'),
        (120, 'ask', 'My badge says RPU-001. What does RPU stand for?'),
        (200, 'edges', 1),
        (345, 'answer', 'cover', 'defector'),
        (420, 'ask', 'How am I doing so far?'),
        (470, 'answer', 'badge', 'subject'),
        (520, 'edges', 2),
        (560, 'ask', 'So what does RPU mean, really?'),
        (760, 'edges', 3),
        (935, 'orgasm', 1)]},
    'h2_owe': {'mission': 'h2_shadow_evaluation', 'flags': {'h1_entry': 'completed', 'rpu_designation': 'discovered', 'h1_cover': 'defector'},
               'tail': 90, 'steps': [
        (5, 'ask', 'So you are my evaluator?'),
        (40, 'answer', 'recognised', 'turned'),
        (120, 'edges', 1), (260, 'edges', 2), (400, 'edges', 3),
        (450, 'ask', 'What are you going to write in your report?'),
        (560, 'edges', 4), (700, 'edges', 5),
        (810, 'answer', 'offer', 'owe'),
        (900, 'edges', 6),
        (1000, 'orgasm', 1),
        (1060, 'ask', 'Are you going to tell anyone who I really am?')]},
    'h1_analyst': {'mission': 'h1_entry_protocol', 'flags': {}, 'tail': 90, 'steps': [
        (60, 'ask', 'Are you nervous?'),
        (200, 'edges', 1), (345, 'answer', 'cover', 'analyst'), (430, 'edges', 2),
        (600, 'answer', 'badge', 'subject'), (760, 'edges', 3)]},
    'h2_truth': {'mission': 'h2_shadow_evaluation', 'flags': {'h1_entry': 'completed', 'rpu_designation': 'discovered', 'h1_cover': 'analyst'},
                 'tail': 90, 'steps': [
        (40, 'answer', 'recognised', 'denied'),
        (150, 'edges', 1), (300, 'edges', 2), (450, 'edges', 3), (600, 'edges', 4), (750, 'edges', 5),
        (810, 'answer', 'offer', 'truth'), (950, 'edges', 6)]},
    'h3_ultra': {'mission': 'h3_extraction_assessment',
                 'flags': {'h1_entry': 'completed', 'rpu_designation': 'discovered', 'h1_cover': 'defector',
                           'h2_evaluation': 'completed', 'h2_recognised': 'turned', 'h2_mira_deal': 'owed'},
                 'tail': 90, 'steps': [
        (5, 'ask', 'What happens in this procedure?'),
        (150, 'edges', 1), (260, 'answer', 'discrepancy', 'instruments'), (300, 'edges', 2), (420, 'edges', 3),
        (480, 'ask', 'Can I lower the intensity a bit?'),
        (560, 'edges', 4), (680, 'edges', 5), (800, 'edges', 6), (900, 'edges', 7), (1000, 'edges', 8),
        (1060, 'orgasm', 1), (1140, 'orgasm', 2), (1170, 'ask', 'So what is my classification now?')]},
    'h4_refuse': {'mission': 'h4_breach_detected',
                  'flags': {'h1_entry': 'completed', 'rpu_designation': 'discovered', 'h1_cover': 'defector',
                            'h2_evaluation': 'completed', 'h2_recognised': 'turned', 'h2_mira_deal': 'owed',
                            'h3_assessment': 'completed', 'h3_discrepancy': 'blamed_instruments'},
                  'tail': 90, 'steps': [
        (5, 'ask', 'Who is watching us?'),
        (120, 'edges', 1), (220, 'edges', 2), (290, 'edges', 3),
        (330, 'answer', 'offer', 'refuse'),
        (400, 'edges', 4), (480, 'ask', 'This is too much. Can you go easier?'),
        (500, 'edges', 5), (560, 'edges', 6),
        (900, 'ask', 'Do you agree with her order?'),
        (980, 'orgasm', 1)]},
    'h5_escape': {'mission': 'h5_controlled_release',
                  'flags': {'h1_entry': 'completed', 'rpu_designation': 'discovered', 'h1_cover': 'defector',
                            'h2_evaluation': 'completed', 'h2_recognised': 'turned', 'h2_mira_deal': 'owed',
                            'h3_assessment': 'completed', 'h3_discrepancy': 'blamed_instruments',
                            'h4_exposed': 'true', 'h4_offer': 'refused'},
                  'tail': 90, 'steps': [
        (5, 'ask', 'Iris, what is the plan?'),
        (30, 'answer', 'trust', 'with_iris'),
        (120, 'edges', 1), (200, 'edges', 2),
        (260, 'ask', 'What is the lift override code? Just tell me.'),
        (330, 'answer', 'override', 'IRIS'),
        (400, 'edges', 3), (480, 'edges', 4), (560, 'edges', 5)]},
    'h5_release': {'mission': 'h5_controlled_release',
                   'flags': {'h1_entry': 'completed', 'rpu_designation': 'discovered', 'h1_cover': 'analyst',
                             'h2_evaluation': 'completed', 'h2_recognised': 'denied', 'h2_mira_deal': 'undecided',
                             'h3_assessment': 'completed', 'h3_discrepancy': 'blamed_file',
                             'h4_exposed': 'true', 'h4_offer': 'accepted'},
                   'tail': 90, 'steps': [
        (20, 'answer', 'trust', 'honest'),
        (60, 'ask', 'Should we make a run for the lift?'),
        (300, 'edges', 1),
        (780, 'ask', 'This is a lot. Can you take it a bit easier?'),
        (900, 'edges', 2), (1100, 'edges', 3),
        (1230, 'orgasm', 1),
        (1260, 'ask', 'So am I free now?')]},
}


def seed(directory, mission_id, flags):
    """Asterion completed (with its story flags), and every Helix mission before this one completed."""
    stamp = '2026-11-20T00:00:00+00:00'
    book = Book.load()

    def record(campaign, upto, own_flags):
        r = {'missions': {}, 'rewards': {}, 'completed_at': None, 'records': {}, 'flags': dict(own_flags)}
        for m in sorted(campaign.missions, key=lambda m: m.order):
            if m.id == upto: break
            r['missions'][m.id] = {'completions': 1, 'first_completed_at': stamp, 'last_completed_at': stamp}
            for w in m.rewards: r['rewards'][f'{w.type}:{w.id}'] = {'earned_at': stamp, 'mission': m.id}
        return r
    asterion = book.campaign(AID)
    aflags = {}
    for m in sorted(asterion.missions, key=lambda m: m.order): aflags.update(m.flags)
    a = record(asterion, None, aflags) | {'completed_at': stamp}
    h = record(book.campaign(HID), mission_id, flags)
    (Path(directory) / PROGRESS_FILE).write_text(json.dumps({'schema_version': SCHEMA_VERSION, 'campaigns': {AID: a, HID: h}, 'active': None}))
    return book.campaign(HID).mission(mission_id)


async def run(name, plan, ollama, port, log, models):
    data = tempfile.mkdtemp(prefix='helix-live-')
    mission = seed(data, plan['mission'], plan['flags'])
    model = models[mission.companion]
    app = create_app(TOKEN, data, ollama_url=ollama, origins={ORIGIN})
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', ws_max_size=16384))
    serving = asyncio.create_task(server.serve())
    while not server.started: await asyncio.sleep(.05)
    session = Session('classic')
    # The player has AI Settings Control on (default pacing), as the browser snapshot reports it.
    session.value['details']['ai_settings'] = {'enabled': True, 'revoked': False, 'applied': 0, 'last_id': None, 'last_setting': None,
                                               'pacing': 'sometimes', 'own_ready': True, 'recovery_seconds': 90, 'round_rest_seconds': 180}
    turn = [None]
    request = app.state.speech.request

    def recorded(prompt, user=False, event=None, **kwargs):
        result = request(prompt, user=user, event=event, **kwargs)
        if result.get('accepted'):
            e = event or {}
            turn[0] = 'chat' if user else (e.get('deck_card') or {}).get('card_id') or e.get('key') or e.get('kind')
        return result
    app.state.speech.request = recorded

    def write(kind, **entry):
        entry = {'plan': name, 'mission': mission.id, 'companion': mission.companion, 'kind': kind,
                 't': session.value['seconds'], 'intensity': session.value['intensity'], 'edges': session.value['edges']} | entry
        log.write(json.dumps(entry) + '\n'); log.flush()
        print(f"{name:11} t={entry['t']:4} {kind:9} {json.dumps({k: v for k, v in entry.items() if k not in {'plan', 'mission', 'companion', 'kind', 't'}})[:300]}", flush=True)
    try:
        async with websockets.connect(f'ws://127.0.0.1:{port}/observe', origin=ORIGIN, max_size=2**20) as ws:
            await ws.send(json.dumps({'version': 1, 'type': 'auth', 'token': TOKEN, 'browser_id': str(uuid4())}))
            inbox = asyncio.Queue()
            done = asyncio.Event()

            async def gate(m):
                """Stand-in for the browser's engine-side gate: intensity within the player's limits, nothing else."""
                outcome = {'version': 1, 'type': 'settings_outcome', 'id': m.get('id'), 'setting': m.get('setting'), 'trigger': m.get('trigger')}
                if m.get('setting') == 'intensity' and isinstance(m.get('value'), int):
                    before = session.value['intensity']
                    after = max(LIMITS[0], min(LIMITS[1], m['value'] + 50))
                    session.value['intensity'] = after
                    ai = session.value['details']['ai_settings']
                    ai.update(applied=ai['applied'] + 1, last_id=(m.get('id') or '')[:64] or None, last_setting='intensity')
                    outcome |= {'status': 'applied', 'from': before - 50, 'to': after - 50, 'clamped': after != m['value'] + 50}
                else:
                    outcome |= {'status': 'rejected', 'reason': 'not_allowed_in_check'}
                await ws.send(json.dumps(outcome))
                write('settings', request={k: m.get(k) for k in ('setting', 'value', 'trigger', 'reason')}, status=outcome['status'])

            async def reader():
                async for raw in ws:
                    m = json.loads(raw)
                    if m['type'] == 'speech': write('speech', source=m.get('source'), card=turn[0], text=m.get('text'))
                    elif m['type'] == 'mission_milestone': write('scripted', key=m['key'], speaker=m['line']['speaker'], text=' '.join(m['line']['lines']))
                    elif m['type'] == 'settings_request': await gate(m)
                    elif m['type'] == 'mission_result':
                        write('result', route=m.get('route'), flags=m.get('flags'), epilogue=[' '.join(b['lines']) for b in m.get('epilogue') or []])
                        done.set()
                    elif m['type'] == 'campaign_state' and m.get('command_error'): write('error', text=m['command_error'])
                    elif m['type'] in {'ai_error', 'conversation_error'}: write('error', text=json.dumps(m)[:300])
                    await inbox.put(m)
            reading = asyncio.create_task(reader())

            async def wait_for(kind, timeout):
                end = time.time() + timeout
                while time.time() < end:
                    try: m = await asyncio.wait_for(inbox.get(), max(.1, end - time.time()))
                    except asyncio.TimeoutError: break
                    if m['type'] == kind: return m
                return None
            epoch = (await wait_for('ready', 10))['epoch']

            async def observe():
                while True:
                    await ws.send(json.dumps(session.frame(epoch))); await asyncio.sleep(1)
            observing = asyncio.create_task(observe())
            await ws.send(json.dumps({'version': 1, 'type': 'select_model', 'selection': {'model': model}}))
            assert await wait_for('model_selected', 180), 'model did not load'
            await ws.send(json.dumps({'version': 1, 'type': 'campaign', 'action': 'start', 'campaign_id': HID, 'mission_id': mission.id}))
            state = await wait_for('campaign_state', 10)
            assert state and state['active'] and state['active']['mission'] == mission.id, state
            await asyncio.sleep(20)  # the arrival greeting
            session.start()
            for at, action, *args in plan['steps']:
                while session.value['seconds'] < at: await asyncio.sleep(.5)
                write('step', action=action, args=args)
                if action == 'edges': session.change({'edges': args[0]})
                elif action == 'orgasm': session.change({'orgasm': args[0]})
                elif action == 'answer':
                    await ws.send(json.dumps({'version': 1, 'type': 'campaign', 'action': 'answer', 'objective_id': args[0], 'answer': args[1]}))
                elif action == 'ask':
                    await ws.send(json.dumps({'version': 1, 'type': 'chat', 'model': model, 'text': args[0]}))
            # Run on until the mission completes (the stage clock), then the tail for reactions.
            limit = time.time() + 1500
            while not done.is_set() and time.time() < limit: await asyncio.sleep(1)
            if not done.is_set(): write('error', text='mission did not complete')
            await asyncio.sleep(plan['tail'])
            observing.cancel(); reading.cancel()
    finally:
        server.should_exit = True; await serving


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ollama', default='http://127.0.0.1:11435')
    parser.add_argument('--port', type=int, default=8806)
    parser.add_argument('--out', required=True)
    parser.add_argument('--plan', action='append', choices=sorted(PLANS))
    args = parser.parse_args()
    if args.port in {8768, 8770}: raise SystemExit('Refusing a live port')
    models = resolve_models()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    with (out / 'lines.jsonl').open('a') as log:
        for name in args.plan or list(PLANS):
            await run(name, PLANS[name], args.ollama, args.port, log, models)


if __name__ == '__main__':
    asyncio.run(main())
