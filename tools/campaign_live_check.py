# SPDX-License-Identifier: AGPL-3.0-only
"""Opt-in live-model check for campaign awareness (not part of the test suite).

Starts the real observer on an isolated loopback port with a temporary data directory and the
real local companion models, then plays each Asterion mission over the real websocket protocol:
earlier missions are seeded as completed, the mission is started, the companion is asked a
question before the session and during it, and the scripted session reaches the goal. Every
line the companion says is recorded with the phase it was said in, for review. The snapshots
claim a Bluetooth strap so the mission counts; no browser, strap, toy or companion data is involved.

    python tools/campaign_live_check.py --ollama http://127.0.0.1:11435 --port 8805 --out DIR [--runs N] [mission ...]
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
from companion_ai.campaign import Book, PROGRESS_FILE, SCHEMA_VERSION

TOKEN = 'live-campaign-check-' + 'x' * 32
ORIGIN = 'http://127.0.0.1:8770'
CID = 'asterion_initiative'
MODELS = {'nova': 'nova-narrative-f29-v011:latest', 'evelyn': 'evelyn-narrative-f29-v013:latest',
          'daisy': 'daisy-narrative-f29-v014:latest', 'celeste': 'celeste-narrative-f29-v012:latest'}
ASK_BEFORE = 'What do you need from me today?'
ASK_DURING = 'How am I doing so far?'
# What each mission's session does: steps of (seconds to wait, change). The goal is reached in the last steps.
PLANS = {
    'orientation': [(20, {'edges': 1})],
    'first_assessment': [(15, {'edges': 1}), (15, {'edges': 2}), ('ask', None), (15, {'edges': 3}), (15, {'edges': 4}), (15, {'edges': 5})],
    'country_connections': [(15, {'edges': 1}), ('ask', None), (20, {'orgasm': 1})],
    'directors_test': [(15, {'edges': 2}), ('ask', None), (15, {'edges': 4}), (15, {'edges': 5}), (45, {'orgasm': 1})],
    'certification': [(20, {}), ('ask', None), (20, {'orgasm': 1, 'calibration_saved': True}), (3, {'end': 'calibration_completed'})],
}


class Session:
    def __init__(self, mode):
        self.sequence = 0
        self.started = None
        self.events = []
        self.value = {'session_id': str(uuid4()), 'status': 'IDLE', 'seconds': 0, 'experience': 'classic', 'active_mode': mode,
                      'goal': 'tease', 'hr': 104, 'effective_max': 150, 'pullback': 142, 'trend': 'steady', 'edges': 0, 'intensity': 100,
                      'movement': {'primary': 20, 'secondary': 10, 'stroke_min': 0, 'stroke_max': 100},
                      'devices': {'simulated_hr': False, 'hr_ready': True, 'toy_ready': True, 'ble': True, 'handy': True, 'intiface': False, 'tcode': False, 'vacuglide': False},
                      'safety': {'signal': 'ok', 'no_contact': False, 'watchdog_paused': False, 'fault': 'none'},
                      'details': {'captured_at_ms': 0, 'hr_recorded_at_ms': 0, 'resting_bpm': 70, 'single_max_bpm': 150, 'dual_max_bpm': None, 'pauses': 0,
                                  'calibration_pass': 'primary' if mode == 'calibrate' else 'none', 'warmup_active': False, 'warmup_remaining_seconds': None,
                                  'ease_down_seconds': 0, 'rampdown_seconds': None, 'endgame': 'orgasm', 'orgasm_mode': False, 'orgasm_count': 0}}

    def frame(self, epoch):
        now = int(time.time() * 1000)
        if self.value['status'] == 'RUNNING' and self.started: self.value['seconds'] = int(time.time() - self.started)
        self.value['details'].update(captured_at_ms=now, hr_recorded_at_ms=now)
        events = [{'id': str(uuid4()), 'kind': kind, 'at_ms': now, 'session_id': self.value['session_id']} for kind in self.events]
        self.events = []
        self.sequence += 1
        return {'version': 1, 'type': 'observation', 'epoch': epoch, 'sequence': self.sequence, 'snapshot': json.loads(json.dumps(self.value)), 'events': events}

    def start(self):
        self.value['status'] = 'RUNNING'; self.started = time.time(); self.events.append('session_started')

    def change(self, change):
        d = self.value['details']
        if 'edges' in change: self.value['edges'] = change['edges']
        if 'orgasm' in change:
            d['orgasm_count'] = change['orgasm']; d['last_orgasm_seconds'] = self.value['seconds']; self.events.append('orgasm_reported')
        if 'calibration_saved' in change: d['calibration_saved'] = change['calibration_saved']
        if 'end' in change:
            self.value['status'] = 'IDLE'; d['terminal_outcome'] = change['end']; self.events.append('completion_accepted')


def seed(directory, mission_id):
    """Progress as if every mission before this one was completed."""
    campaign = Book.load().campaign(CID)
    ordered = sorted(campaign.missions, key=lambda m: m.order)
    stamp = '2026-11-16T00:00:00+00:00'
    record = {'missions': {}, 'rewards': {}, 'completed_at': None, 'records': {}}
    for m in ordered:
        if m.id == mission_id: break
        record['missions'][m.id] = {'completions': 1, 'first_completed_at': stamp, 'last_completed_at': stamp}
        for r in m.rewards: record['rewards'][f'{r.type}:{r.id}'] = {'earned_at': stamp, 'mission': m.id}
    (Path(directory) / PROGRESS_FILE).write_text(json.dumps({'schema_version': SCHEMA_VERSION, 'campaigns': {CID: record}, 'active': None}))
    return next(m for m in ordered if m.id == mission_id)


async def run_mission(mission_id, ollama, port, log, run):
    data = tempfile.mkdtemp(prefix='campaign-live-')
    mission = seed(data, mission_id)
    model = MODELS[mission.companion]
    app = create_app(TOKEN, data, ollama_url=ollama, origins={ORIGIN})
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', ws_max_size=16384))
    serving = asyncio.create_task(server.serve())
    while not server.started: await asyncio.sleep(.05)
    session = Session(mission.session.active_mode if mission.session and mission.session.active_mode else 'classic')
    phase = ['setup']
    lines = []
    # Which card (or chat) produced each turn: speech messages do not say, so the request is recorded.
    turn = [None]
    request = app.state.speech.request

    def recorded(prompt, user=False, event=None, **kwargs):
        result = request(prompt, user=user, event=event, **kwargs)
        if result.get('accepted'): turn[0] = 'chat' if user else ((event or {}).get('deck_card') or {}).get('card_id') or (event or {}).get('kind')
        return result
    app.state.speech.request = recorded
    try:
        async with websockets.connect(f'ws://127.0.0.1:{port}/observe', origin=ORIGIN, max_size=2**20) as ws:
            await ws.send(json.dumps({'version': 1, 'type': 'auth', 'token': TOKEN, 'browser_id': str(uuid4())}))
            inbox = asyncio.Queue()

            async def reader():
                async for raw in ws:
                    m = json.loads(raw)
                    if m['type'] == 'speech':
                        entry = {'run': run, 'mission': mission_id, 'companion': mission.companion, 'phase': phase[0], 'source': m.get('source'), 'card': turn[0],
                                 'edges': session.value['edges'], 'status': session.value['status'], 'text': m.get('text')}
                        lines.append(entry); log.write(json.dumps(entry) + '\n'); log.flush()
                        print(f"{mission_id:20} {phase[0]:12} {str(turn[0]):22} {m.get('text')!r}", flush=True)
                    if m['type'] == 'mission_result':
                        phase[0] = 'completed'
                        entry = {'run': run, 'mission': mission_id, 'phase': 'result', 'source': 'campaign', 'text': 'MISSION RESULT: ' + m['mission']}
                        lines.append(entry); log.write(json.dumps(entry) + '\n'); log.flush()
                    await inbox.put(m)
            reading = asyncio.create_task(reader())

            async def wait_for(kind, timeout):
                end = time.time() + timeout
                while time.time() < end:
                    try: m = await asyncio.wait_for(inbox.get(), max(.1, end - time.time()))
                    except asyncio.TimeoutError: break
                    if m['type'] == kind: return m
                    if m['type'] in {'ai_error', 'conversation_error'}: print('ERROR', m, flush=True)
                return None
            epoch = (await wait_for('ready', 10))['epoch']

            async def observe():
                while True:
                    await ws.send(json.dumps(session.frame(epoch))); await asyncio.sleep(1)
            observing = asyncio.create_task(observe())
            await ws.send(json.dumps({'version': 1, 'type': 'select_model', 'selection': {'model': model}}))
            assert await wait_for('model_selected', 180), 'model did not load'
            await ws.send(json.dumps({'version': 1, 'type': 'campaign', 'action': 'start', 'campaign_id': CID, 'mission_id': mission_id}))
            state = await wait_for('campaign_state', 10)
            assert state and state['active'] and state['active']['mission'] == mission_id, state

            async def ask(text, label):
                phase[0] = label
                await ws.send(json.dumps({'version': 1, 'type': 'chat', 'model': model, 'text': text}))
                end = time.time() + 120
                while time.time() < end:
                    await asyncio.sleep(1)
                    if any(l['phase'] == label and l['source'] == 'user' for l in lines): break
            await asyncio.sleep(25)  # an arrival greeting may play first
            await ask(ASK_BEFORE, 'ask_before')
            phase[0] = 'running'
            session.start()
            await asyncio.sleep(20)
            for wait, change in PLANS[mission_id]:
                if wait == 'ask':
                    await asyncio.sleep(4)  # let the last change reach the observer first
                    await ask(ASK_DURING, 'ask_during'); phase[0] = 'running'; continue
                await asyncio.sleep(wait)
                session.change(change)
            await asyncio.sleep(75)  # the completion card and any Director reaction
            observing.cancel(); reading.cancel()
    finally:
        server.should_exit = True; await serving
    return lines


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ollama', default='http://127.0.0.1:11435')
    parser.add_argument('--port', type=int, default=8805)
    parser.add_argument('--out', required=True)
    parser.add_argument('--runs', type=int, default=1)
    parser.add_argument('missions', nargs='*', default=list(PLANS))
    args = parser.parse_args()
    if args.port in {8768, 8770}: raise SystemExit('Refusing a live port')
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    with (out / 'lines.jsonl').open('a') as log:
        for run in range(args.runs):
            for mission in args.missions:
                await run_mission(mission, args.ollama, args.port, log, run)


if __name__ == '__main__':
    asyncio.run(main())
