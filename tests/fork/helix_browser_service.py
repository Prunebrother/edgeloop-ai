# SPDX-License-Identifier: AGPL-3.0-only
"""Owned browser fixture for Helix safety/board tests; no shipping endpoints or hardware."""
import os
import sys
from pathlib import Path

# Direct-script launchers put tests/fork, rather than the repository, on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.fork.character_model_fixtures import helix_extra_models

# Before the shared fixture imports: Helix companions (Iris, Seraphine, ...) must count as installed models.
os.environ.setdefault('EDGELOOP_FIXTURE_EXTRA_MODELS', helix_extra_models())
import uvicorn
from fastapi import Request
from companion_ai.campaign import PROGRESS_FILE
from tests.ai.helix_safety_fixtures import HID, STAMP, reports_through_stages, seed_progress
from tests.fork.campaign_browser_service import app, LAST, observe
from tests.fork.browser_service import OBSERVER_PORT

if os.environ.get('EDGELOOP_HELIX_BOARD_FIXTURE') == '1':
    from tests.ai.helix_board_fixtures import book_with_board_fixtures
    app.state.campaign.book = book_with_board_fixtures(app.state.campaign.book)


@app.get('/fixture/helix/book')
async def book():
    return {'campaigns': [campaign.model_dump(mode='json') for campaign in app.state.campaign.book.campaigns]}


@app.post('/fixture/helix/seed')
async def seed(request: Request):
    body = await request.json(); svc = app.state.campaign
    progress = seed_progress(svc.book, body['mission'], body.get('campaign', HID))
    if os.environ.get('EDGELOOP_HELIX_BOARD_FIXTURE') == '1' and body.get('campaign') == 'fixture_helix_board':
        progress.campaigns[body['campaign']].flags.update(body.get('flags', {}))
    if body.get('seen', True):
        for cid, record in progress.campaigns.items():
            narrative = svc.book.narratives.get(cid)
            if narrative: record.intros_seen.update({chapter: STAMP for chapter in narrative.chapter_intros})
    svc._settle_completion(progress); svc._save(progress)
    svc.attempt = None; svc.finished = None; svc.notice = None; svc.cues.clear(); svc.directives.clear(); LAST.clear()
    app.state.speech.publish(svc.state())
    return {'ok': True}


@app.post('/fixture/helix/advance')
async def advance(request: Request):
    """Credit canonical fixture reports to a named stage/choice and optionally deliver that real scripted step."""
    import time
    body = await request.json(); svc = app.state.campaign
    if not svc.attempt: return {'ok': False, 'error': 'Start a fixture mission first'}
    mission = svc.attempt.mission; selected = body.get('step'); choice = body.get('choice'); latest = None; steps = []
    for report in reports_through_stages(svc, body['session_id']):
        latest = report
        for message in observe(report, [], app.state.models.config.model, fixture=True):
            if message['type'] not in {'campaign_progress', 'campaign_state'}: app.state.speech.publish(message)
        steps.extend(svc.take_directives()); svc.take_cues()  # Synthetic traversal never asks a live model to react.
        if selected and any(step['key'] == selected for step in steps): break
        if choice and any(o.id == choice and svc.attempt.choice_open(o) for o in svc.attempt.objectives): break
        if not selected and not choice: break
    LAST.update(report=latest, at=time.monotonic())
    app.state.speech.publish(svc.state(latest, app.state.models.config.model))
    delivered = []
    if selected:
        for step in steps:
            if step['key'] == selected:
                app.state.speech.campaign_directive(step); delivered.append(step)
    return {'ok': True, 'report': latest, 'delivered': delivered, 'steps': steps}


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=OBSERVER_PORT, access_log=False, ws_max_size=16384)
