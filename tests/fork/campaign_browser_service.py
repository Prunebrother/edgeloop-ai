# SPDX-License-Identifier: AGPL-3.0-only
"""Campaign browser fixture: the real observer with mocked Ollama (tests/fork/browser_service.py).

/fixture/campaign/evidence hands the campaign one synthetic observer report. It stands in for a
real heart-rate strap and toy, which a browser test cannot connect; the shipping app has no such path."""
import os
import httpx
import uvicorn
from fastapi import Request
from ai_observer.server import create_app
from tests.fork.browser_service import runtime, TOKEN, UI_PORT, OBSERVER_PORT
from companion_ai.campaign import PROGRESS_FILE

DATA = os.environ['EDGELOOP_CAMPAIGN_FIXTURE_DATA']
app = create_app(TOKEN, DATA, transport=httpx.MockTransport(runtime), origins={f'http://127.0.0.1:{UI_PORT}'})
import time
if os.environ.get('EDGELOOP_CHOICE_FIXTURE') == '1':
    from companion_ai.campaign import Book, Campaign
    from tests.ai.test_campaign_choice import definition
    from copy import deepcopy
    data = definition()
    choice = data['missions'][0]['objectives'][-1]
    data['missions'][0]['objectives'] += [dict(deepcopy(choice), id=oid) for oid in ('cover_space', 'cover_pad')]
    app.state.campaign.book = Book([Campaign.model_validate(data)])
if os.environ.get('EDGELOOP_CODE_PUZZLE_FIXTURE') == '1':
    from companion_ai.campaign import Book, Campaign
    from tests.ai.test_campaign_code_puzzle import definition
    app.state.campaign.book = Book([Campaign.model_validate(definition())])
if os.environ.get('EDGELOOP_ROUTE_FIXTURE') == '1':
    from companion_ai.campaign import Book, Campaign
    from tests.ai.test_campaign_routes import definition
    app.state.campaign.book = Book([Campaign.model_validate(definition())])
LAST = {}
_answer = app.state.campaign.answer
_observe = app.state.campaign.observe
_mission_text = app.state.campaign.mission_text
SCENES = os.environ.get('EDGELOOP_SCENE_FIXTURE') == '1'


def scene_block(label, **art):
    return {'speaker': 'mira', 'lines': ['PLACEHOLDER scene fixture — ' + label], 'status': 'placeholder', **art}


def mission_text(campaign, mission):
    message = _mission_text(campaign, mission)
    if SCENES:
        message = dict(message, briefing=scene_block('briefing', expression='concerned', image='h_arrival', background='env_reception'), narrative_status='placeholder')
    return message


app.state.campaign.mission_text = mission_text


def observe(report, events, model, fixture=False):
    # The fixture stands in for the engine: while its running stand-in session is recent, the page's own
    # (idle, hardware-less) reports would end it as a session change, which no real engine report would do.
    stand_in = LAST.get('report')
    if not fixture and stand_in and stand_in.get('status') == 'RUNNING' and time.monotonic() - LAST['at'] < 15 \
            and (report or {}).get('session_id') != stand_in.get('session_id'): return []
    messages = _observe(report, events, model)
    if SCENES:
        for message in messages:
            if message['type'] == 'mission_result':
                message.update(completion=scene_block('background', expression='concerned', background='env_reception'),
                               epilogue=[scene_block('illustration', image='h_arrival'),
                                         scene_block('missing slot', image='not_a_slot'),
                                         scene_block('load failure', image='h_breach'),
                                         scene_block('plain')])
    return messages


def answer(objective_id, option_id, report, model):
    # Puzzle answers come from the page's real buttons; the running session they need is the fixture's stand-in.
    return _answer(objective_id, option_id, LAST.get('report') or report, model)


app.state.campaign.answer = answer
app.state.campaign.observe = observe


@app.post('/fixture/campaign/evidence')
async def evidence(request: Request):
    body = await request.json()
    # A batch is handed over in one go, so the page's own idle observations cannot interleave with it.
    LAST.update(report=(body.get('reports') or [body['report']])[-1], at=time.monotonic())
    sent = [m for r in body.get('reports') or [body['report']]
            for m in observe(r, body.get('events', []), app.state.models.config.model, fixture=True)]
    # A real session sends about one update a second; a batch keeps only the last of consecutive progress
    # updates, so it cannot overflow the browser's outbound queue (32 messages).
    for i, message in enumerate(sent):
        if message['type'] == 'campaign_progress' and i + 1 < len(sent) and sent[i + 1]['type'] == 'campaign_progress': continue
        app.state.speech.publish(message)
    return {'sent': [m['type'] for m in sent], 'model': app.state.models.config.model}


@app.post('/fixture/campaign/saves')
async def saves(request: Request):
    """Make progress writes fail (a full disk) or work again."""
    store = app.state.campaign.store
    if not hasattr(store, 'real_write'): store.real_write = store.write
    def broken(*args): raise OSError('disk full (fixture)')
    store.write = store.real_write if (await request.json())['ok'] else broken
    return {'ok': True}


@app.post('/fixture/campaign/progress')
async def seed(request: Request):
    """Saved progress as if every mission before `mission` was completed, then publish the new state."""
    from companion_ai.campaign import Progress, SCHEMA_VERSION
    svc = app.state.campaign
    campaign = svc.book.campaign((await request.json())['campaign'])
    upto = (await request.json())['mission']
    stamp = '2026-11-16T00:00:00+00:00'
    record = {'missions': {}, 'rewards': {}, 'chapters': {}, 'completed_at': None, 'records': {}}
    for m in sorted(campaign.missions, key=lambda m: m.order):
        if m.id == upto: break
        record['missions'][m.id] = {'completions': 1, 'first_completed_at': stamp, 'last_completed_at': stamp}
        for r in m.rewards: record['rewards'][r.key] = {'earned_at': stamp, 'mission': m.id}
    svc.progress = Progress.model_validate({'schema_version': SCHEMA_VERSION, 'campaigns': {campaign.id: record}, 'active': None})
    svc._settle_completion(svc.progress)
    svc.store.write(PROGRESS_FILE, svc.progress.model_dump(mode='json'))
    svc.attempt = None
    app.state.speech.publish(svc.state())
    return {'ok': True}


@app.get('/fixture/campaign')
async def progress():
    path = os.path.join(DATA, PROGRESS_FILE)
    return {'saved': open(path).read() if os.path.exists(path) else None, 'model': app.state.models.config.model}


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=OBSERVER_PORT, access_log=False, ws_max_size=16384)
