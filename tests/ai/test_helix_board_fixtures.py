# SPDX-License-Identifier: AGPL-3.0-only
"""Browser fixture semantics against the real campaign service, independently of browser availability."""
import pytest
from companion_ai.campaign import Book, CampaignService
from companion_ai.storage import SettingsStore
from tests.ai.helix_board_fixtures import BID, book_with_board_fixtures
from tests.ai.helix_safety_fixtures import seed_progress
from tests.ai.test_campaign_chapter2 import tick


def service(tmp_path, campaign=BID, mission='floor_path', bonus='shown'):
    book = book_with_board_fixtures(); svc = CampaignService(SettingsStore(tmp_path), book=book, identity=lambda _: 'nova')
    svc.progress = seed_progress(book, mission, campaign)
    svc.progress.campaigns[campaign].flags['bonus'] = bonus
    svc._settle_completion(svc.progress); svc._save(svc.progress)
    return svc


def test_browser_fixture_does_not_mutate_shipped_definitions():
    source = Book.load(); before = [c.model_dump() for c in source.campaigns]
    book = book_with_board_fixtures(source); book.check_conditions(book.campaign(BID))
    assert before == [c.model_dump() for c in source.campaigns]
    assert {c.id for c in book.campaigns} >= {'asterion_initiative', 'rise_of_helix', BID}


def test_fixture_missions_really_lock_on_when_and_return_authored_or_generic_reason(tmp_path):
    svc = service(tmp_path)
    state = next(c for c in svc.state()['campaigns'] if c['id'] == BID)
    locked = {m['id']: m for m in state['missions']}
    assert locked['locked_path']['state'] == locked['generic_path']['state'] == 'locked'
    assert locked['locked_path']['locked_reason'] == 'An analyst must vouch for you.'
    assert locked['generic_path']['locked_reason'] == 'Not available on this story path.'
    for mid in ['locked_path', 'generic_path']:
        with pytest.raises(ValueError, match='locked'): svc.start(BID, mid)


@pytest.mark.parametrize('bonus', ['shown', 'hidden'])
def test_fixture_optional_visibility_and_floor_output_are_real_campaign_state(tmp_path, bonus):
    svc = service(tmp_path, bonus=bonus); svc.start(BID, 'floor_path'); report = tick('fixture', 0, intensity=60)
    svc.observe(report, [], 'nova')
    objectives = svc.state(report, 'nova')['attempt']['objectives']
    assert any(o['id'] == 'bonus' and o['optional'] for o in objectives) == (bonus == 'shown')
    ladder = next(o for o in objectives if o['id'] == 'ladder')
    assert ladder['stages'][0]['current'] and ladder['stages'][0]['seconds'] == 10
    assert all(not stage['needs_manual'] and stage['intensity'] is None for stage in ladder['stages'])
    [step] = svc.take_directives(); assert step['scripted'] and step['fallback']['value'] == 30


def test_fixture_completes_real_asterion_unlock_and_produces_the_notice_data(tmp_path):
    book = book_with_board_fixtures(); asterion = book.campaign('asterion_initiative'); final = max(asterion.missions, key=lambda m: m.order)
    svc = service(tmp_path, asterion.id, final.id); svc.start(asterion.id, final.id)
    assert not next(c for c in svc.state()['campaigns'] if c['id'] == 'rise_of_helix')['available']
    svc.observe(tick('fixture', 0), [], 'nova')
    result = next(m for m in svc.observe(tick('fixture', 1, edges=1), [], 'nova') if m['type'] == 'mission_result')
    assert result['campaign_complete'] and result['unlocked_campaigns'] == [{'id': 'rise_of_helix', 'title': 'Rise of Helix'}]
    assert next(c for c in svc.state()['campaigns'] if c['id'] == 'rise_of_helix')['available']


def test_active_campaign_and_mission_restore_after_reload(tmp_path):
    svc = service(tmp_path); svc.start(BID, 'floor_path')
    restored = CampaignService(SettingsStore(tmp_path), book=book_with_board_fixtures())
    assert restored.state()['active']['campaign'] == BID and restored.state()['active']['mission'] == 'floor_path'


def test_browser_fixture_endpoints_advance_real_floor_and_choice_without_a_socket(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    script = '''
import asyncio
import httpx
from companion_ai.models import AIConfig
from tests.ai.helix_board_fixtures import BID
from tests.fork.helix_browser_service import app
async def main():
    app.state.models.config = AIConfig(model='nova-narrative-v1:latest')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.post('/fixture/helix/seed', json={'campaign': BID, 'mission': 'floor_path', 'flags': {'bonus': 'hidden'}})
        assert response.json()['ok']
        app.state.campaign.start(BID, 'floor_path')
        response = await client.post('/fixture/helix/advance', json={'session_id': 'fixture', 'choice': 'cover'})
        assert response.json()['ok'] and app.state.campaign.attempt.session_id == 'fixture'
        objectives = app.state.campaign.state()['attempt']['objectives']
        assert not any(o['id'] == 'bonus' for o in objectives)
        assert next(o for o in objectives if o['id'] == 'cover')['choice']['open']
        response = await client.post('/fixture/helix/advance', json={'session_id': 'fixture', 'step': 'ladder:high'})
        assert response.json()['delivered'][0]['fallback']['value'] == 60
        assert next(o for o in app.state.campaign.attempt.objectives if o.id == 'ladder').stages[1].raise_to == 110
    await app.state.speech.close()
asyncio.run(main())
'''
    env = {k: v for k, v in os.environ.items() if k not in {'EDGELOOP_PAIRING_FILE', 'OLLAMA_HOST'}}
    env.update(EDGELOOP_CAMPAIGN_FIXTURE_DATA=str(tmp_path), EDGELOOP_HELIX_BOARD_FIXTURE='1',
               EDGELOOP_FIXTURE_UI_PORT='8932', EDGELOOP_FIXTURE_OBSERVER_PORT='8938')
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[2], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
