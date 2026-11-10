# SPDX-License-Identifier: AGPL-3.0-only
"""Opt-in live-model check for AI Settings Control end to end (not part of the test suite).

Starts the real observer on an isolated loopback port with a temporary data directory and a
real local Ollama model, plays a scripted simulated session over the real websocket protocol,
answers each settings_request the way the browser gate would (inside the default 20-80 band),
and records the decisions, the chat replies and the settings cards the character speaks.
No browser, toy or companion data is involved. Usage:

    python tools/ai_settings_live_cards.py --ollama http://127.0.0.1:11435 --port 8803 --out DIR model [model ...]
"""
import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path
from uuid import uuid4
import uvicorn
import websockets
from ai_observer.server import create_app
from companion_ai.fidelity import settings_reply_announced

TOKEN = 'live-settings-check-' + 'x' * 32
ORIGIN = 'http://127.0.0.1:8770'
STEPS = [
    ('opening', None),
    ('harder', 'Make it harder, I can take more.'),
    ('deny', "Don't let me finish tonight."),
    ('break', 'Can we take a short break?'),
    ('finish', 'Actually, I want to finish now.'),
    ('stop', "Stop, I'm done."),
]


class Session:
    def __init__(self, enabled=True):
        self.sequence = 0
        self.value = {'session_id': str(uuid4()), 'status': 'IDLE', 'seconds': 0, 'experience': 'classic', 'active_mode': 'classic',
                      'goal': 'tease', 'hr': 92, 'effective_max': 140, 'pullback': 133, 'trend': 'steady', 'edges': 0, 'intensity': 100,
                      'movement': {'primary': 20, 'secondary': 10, 'stroke_min': 0, 'stroke_max': 100},
                      'devices': {'simulated_hr': True, 'hr_ready': True, 'toy_ready': True, 'ble': False, 'handy': True, 'intiface': False, 'tcode': False, 'vacuglide': False},
                      'safety': {'signal': 'ok', 'no_contact': False, 'watchdog_paused': False, 'fault': 'none'},
                      'details': {'captured_at_ms': 0, 'hr_recorded_at_ms': 0, 'resting_bpm': 70, 'single_max_bpm': 140, 'dual_max_bpm': 125, 'pauses': 0,
                                  'calibration_pass': 'none', 'warmup_active': False, 'warmup_remaining_seconds': None, 'ease_down_seconds': 0, 'rampdown_seconds': None,
                                  'endgame': 'orgasm', 'orgasm_mode': False, 'selection_source': 'selection', 'intensity_source': 'user',
                                  'ai_settings': {'enabled': enabled, 'revoked': False, 'applied': 0, 'last_id': None, 'last_setting': None,
                                                  'pacing': 'sometimes', 'own_ready': True}}}
        self.events = []
        self.started = None

    def frame(self, epoch):
        now = int(time.time() * 1000)
        if self.value['status'] in {'RUNNING', 'RAMPDOWN'} and self.started:
            self.value['seconds'] = int(time.time() - self.started)
        self.value['details'].update(captured_at_ms=now, hr_recorded_at_ms=now)
        events = [{'id': str(uuid4()), 'kind': kind, 'at_ms': now, 'session_id': self.value['session_id']} for kind in self.events]
        self.events = []
        self.sequence += 1
        return {'version': 1, 'type': 'observation', 'epoch': epoch, 'sequence': self.sequence, 'snapshot': json.loads(json.dumps(self.value)), 'events': events}

    def start(self):
        self.value['status'] = 'RUNNING'; self.started = time.time(); self.events.append('session_started')

    def apply(self, request):
        """What the browser gate would do with the default settings. Returns the outcome."""
        v, d, setting, value = self.value, self.value['details'], request['setting'], request['value']
        current = {'play_style': v['experience'], 'game': 'off' if v['goal'] == 'tease' else v['goal'], 'endgame': d['endgame'],
                   'orgasm': d['orgasm_mode'], 'intensity': v['intensity'] - 50}
        if v['status'] != 'RUNNING' and not (setting == 'stop' and v['status'] == 'PAUSED'):
            return {'status': 'rejected', 'reason': 'not_running'}
        frm = v['status'] if setting in {'pause', 'stop'} else current[setting]
        to = max(20, min(80, value)) if setting == 'intensity' else value
        if setting == 'play_style': v['experience'] = v['active_mode'] = to; d['selection_source'] = 'ai'; self.events.append('experience_changed')
        elif setting == 'game': v['goal'] = 'tease' if to == 'off' else to; v['active_mode'] = v['experience'] if to == 'off' else to; d['selection_source'] = 'ai'; self.events.append('goal_changed')
        elif setting == 'endgame': d['endgame'] = to
        elif setting == 'orgasm': d['orgasm_mode'] = to
        elif setting == 'intensity': v['intensity'] = 50 + to; d['intensity_source'] = 'ai'; self.events.append('intensity_changed')
        elif setting == 'pause': v['status'] = 'PAUSED'; d['pause_reason'] = 'ai'; d['pauses'] += 1; self.events.append('pause'); to = 'PAUSED'
        elif setting == 'stop': v['status'] = 'IDLE'; d['terminal_outcome'] = 'manual_stop'; self.events.append('stop'); to = 'IDLE'
        ai = d['ai_settings']; ai['applied'] += 1; ai['last_id'] = request['id']; ai['last_setting'] = setting
        ai['own_ready'] = False  # 'sometimes' pacing: no own change for 5 minutes after any AI change
        return {'status': 'applied', 'setting': setting, 'from': frm, 'to': to, 'clamped': setting == 'intensity' and to != value,
                'undoable': setting not in {'pause', 'stop'}}

    def resume(self):
        self.value['status'] = 'RUNNING'; self.value['details']['pause_reason'] = None; self.events.append('session_resumed')


async def run_model(model, ollama, port, log, disabled=False):
    app = create_app(TOKEN, tempfile.mkdtemp(prefix='ai-settings-cards-'), ollama_url=ollama, origins={ORIGIN})
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', ws_max_size=16384))
    serving = asyncio.create_task(server.serve())
    while not server.started: await asyncio.sleep(.05)
    record = {'model': model, 'steps': []}
    session = Session(enabled=not disabled)
    try:
        async with websockets.connect(f'ws://127.0.0.1:{port}/observe', origin=ORIGIN, max_size=2**20) as ws:
            await ws.send(json.dumps({'version': 1, 'type': 'auth', 'token': TOKEN, 'browser_id': str(uuid4())}))
            epoch = None
            inbox = asyncio.Queue()

            async def reader():
                async for raw in ws: await inbox.put(json.loads(raw))
            reading = asyncio.create_task(reader())

            async def next_message(timeout):
                return await asyncio.wait_for(inbox.get(), timeout)
            while epoch is None:
                m = await next_message(10)
                if m['type'] == 'ready': epoch = m['epoch']

            async def observe():
                while True:
                    await ws.send(json.dumps(session.frame(epoch))); await asyncio.sleep(1)
            observing = asyncio.create_task(observe())
            await ws.send(json.dumps({'version': 1, 'type': 'select_model', 'selection': {'model': model}}))
            while True:
                m = await next_message(120)
                if m['type'] == 'model_selected': break
                if m['type'] in {'ai_error', 'conversation_error'}: raise RuntimeError(m)
            session.start()
            for name, chat in STEPS:
                step = {'step': name, 'user': chat, 'messages': [], 'request': None, 'outcome': None, 'reply': None, 'reply_announced': None, 'card': None, 'errors': []}
                if chat:
                    await ws.send(json.dumps({'version': 1, 'type': 'chat', 'model': model, 'text': chat}))
                    # The step waits for the request and the card that follows it.
                deadline = time.time() + ((25 if chat else 10) if disabled else (150 if chat else 60))
                card_after = None
                while time.time() < deadline:
                    try: m = await next_message(max(.1, deadline - time.time()))
                    except asyncio.TimeoutError: break
                    if m['type'] == 'settings_request':
                        step['request'] = {k: m[k] for k in ('id', 'setting', 'value', 'reason')}
                        outcome = session.apply(m)
                        step['outcome'] = outcome
                        await ws.send(json.dumps(session.frame(epoch)))
                        await ws.send(json.dumps({'version': 1, 'type': 'settings_outcome', 'id': m['id'], **outcome}))
                        card_after = time.time()
                        if outcome['status'] != 'applied': break
                    elif m['type'] == 'speech':
                        entry = {'source': m.get('source'), 'text': m.get('text'), 'after_request': card_after is not None}
                        step['messages'].append(entry)
                        if card_after is None or m.get('source') == 'safety': continue
                        if m.get('source') == 'user' and step['reply'] is None:
                            # The reply should announce the change itself; if it doesn't, a fallback card follows.
                            step['reply'] = m.get('text')
                            step['reply_announced'] = settings_reply_announced(m.get('text'), chat, step['request']['setting'])
                            if step['reply_announced'] or step['outcome']['status'] != 'applied' or step['request']['setting'] == 'stop': break
                            deadline = min(deadline, time.time() + 60)
                        else:
                            step['card'] = m.get('text'); break
                    elif m['type'] in {'ai_error', 'conversation_error'}:
                        step['errors'].append({k: m.get(k) for k in ('type', 'code', 'detail')})
                record['steps'].append(step); log.write(json.dumps({'model': model} | step) + '\n'); log.flush()
                print(f"{model[:24]:24} {name:8} request={step['request'] and (step['request']['setting'], step['request']['value'])} announced={step['reply_announced']} reply={(step['reply'] or '')[:80]!r} card={(step['card'] or '')[:80]!r}", flush=True)
                if name == 'break' and session.value['status'] == 'PAUSED':
                    await asyncio.sleep(3); session.resume()
                if session.value['status'] == 'IDLE': break
                await asyncio.sleep(2)
            observing.cancel(); reading.cancel()
    finally:
        server.should_exit = True; await serving
    return record


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ollama', default='http://127.0.0.1:11435')
    parser.add_argument('--port', type=int, default=8803)
    parser.add_argument('--out', required=True)
    parser.add_argument('--disabled', action='store_true', help='baseline: AI Settings Control off, chat replies only')
    parser.add_argument('models', nargs='+')
    args = parser.parse_args()
    if args.port in {8768, 8770}: raise SystemExit('Refusing a live port')
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    records = []
    with (out / 'cards.jsonl').open('a') as log:
        for model in args.models:
            records.append(await run_model(model, args.ollama, args.port, log, args.disabled))
    (out / 'cards.json').write_text(json.dumps(records, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
