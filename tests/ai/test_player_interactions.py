# SPDX-License-Identifier: AGPL-3.0-only
"""Read-only Player notifications through real observer, queue and compiler."""
import asyncio
from copy import deepcopy
from uuid import uuid4
import json

import pytest
from companion_ai.player_events import PlayerFacts, PLAYER_EVENTS, player_evidence
from tests.ai.test_event_deck_content import service


def player(**updates):
    return dict(instance_id='00000000-0000-0000-0000-000000000001',opened=0,selected=0,started=0,
                workspace_open=False,has_video=False,playing=False,title=None,title_source='unknown') | updates


async def prepared(**options):
    r,s,wire,frames=await service(trend='steady',**options)
    s.deck()._start_done=True
    r.state['details']['player']=player();r.step(90,seconds=0)
    s.deck_observe(s.deck(),r.clock.mono())
    return r,s,wire,frames


def notify(r,s,kind,**updates):
    before=r.observation.sequence
    r.state['details']['player'].update(updates)
    r.step(90,seconds=0,kinds=[kind])
    evidence=next((e for e in reversed(r.observation.events) if e['sequence']>before and e['kind']==kind),None)
    assert evidence, (kind,r.observation.event_diagnostics)
    s.enqueue(kind,20,dict(event_id=evidence['event_id'],session_id=r.observation.session_id,
        at_ms=evidence['at_ms'],evidence=evidence['evidence'],player=deepcopy(r.state['details']['player'])))


async def settle(r,s):
    r.step(90,seconds=3);s.pump()
    if s.task:await s.task
    await asyncio.sleep(0)


@pytest.mark.parametrize('kind,updates',[
    ('player_opened',dict(opened=1,workspace_open=True)),
    ('video_selected',dict(selected=1,has_video=True,title='Aladdin',title_source='filename')),
    ('video_started',dict(selected=1,started=1,has_video=True,playing=True,title='Aladdin',title_source='filename')),
])
async def test_events_use_card_prompt_history_separation_and_read_only_facts(kind,updates):
    r,s,wire,frames=await prepared(status='IDLE')
    s.history.append(dict(role='user',content='Choose Marigold or Tinfoil.',session_id=r.observation.session_id))
    notify(r,s,kind,**updates);await settle(r,s)
    body=next(b for path,b in reversed(wire) if path=='/api/chat');messages=body['messages']
    assert [m['role'] for m in messages]==['system','assistant','user']
    assert 'Marigold' in messages[-2]['content'] and 'Marigold' not in messages[-1]['content']
    assert 'Verified Player interaction: '+kind in messages[-1]['content']
    assert 'You have no tools and cannot change the session' in messages[0]['content'] and not body.get('tools')
    if kind!='player_opened':assert 'Aladdin' in messages[-1]['content'] and 'Source: filename' in messages[-1]['content']
    assert 'Current verified session state: IDLE' in messages[-1]['content']
    assert any(f['type']=='speech' for f in frames)
    assert not any('EARLIER, THE PARTICIPANT' in m['content'] for m in s.history)
    await s.close()


async def test_rapid_events_coalesce_to_one_confirmed_start():
    r,s,wire,frames=await prepared()
    notify(r,s,'player_opened',opened=1,workspace_open=True)
    notify(r,s,'video_selected',selected=1,has_video=True,title='Aladdin',title_source='filename')
    notify(r,s,'video_started',started=1,playing=True)
    assert len(s.pending)==1 and s.pending[0]['kind']=='video_started'
    s.pump();assert not wire
    await settle(r,s)
    assert len([b for path,b in wire if path=='/api/chat'])==1
    assert len([f for f in frames if f['type']=='speech'])==1
    await s.close()


async def test_new_selection_supersedes_old_pending_playback():
    r,s,wire,frames=await prepared()
    notify(r,s,'video_started',selected=1,started=1,has_video=True,playing=True,title='First',title_source='filename')
    notify(r,s,'video_selected',selected=2,playing=False,title='Second')
    assert len(s.pending)==1 and s.pending[0]['kind']=='video_selected'
    await settle(r,s)
    body=next(b for path,b in wire if path=='/api/chat')
    assert 'Second' in body['messages'][-1]['content'] and 'First' not in body['messages'][-1]['content']
    await s.close()


async def test_player_does_not_interrupt_model_generation():
    r,s,wire,frames=await prepared()
    entered=asyncio.Event();release=asyncio.Event();old=s.adapter.reply
    async def delayed(*args,**kwargs):entered.set();await release.wait();return await old(*args,**kwargs)
    s.adapter.reply=delayed
    s.request('Hello',user=True);await entered.wait();task=s.task
    notify(r,s,'player_opened',opened=1,workspace_open=True);r.step(90,seconds=3);s.pump()
    assert s.task is task and not task.done() and len(s.pending)==1
    release.set();await task;await s.close()


async def test_mission_and_safety_precede_player_notifications():
    r,s,wire,frames=await prepared()
    notify(r,s,'player_opened',opened=1,workspace_open=True)
    r.state['edges']=3;r.step(90,seconds=3);s.pump();await s.task
    body=next(b for path,b in wire if path=='/api/chat')
    assert 'Three-edge milestone' in body['messages'][-1]['content']
    assert any(e['kind']=='player_opened' for e in s.pending)
    s.safety('emergency_stop');assert not s.pending
    assert frames[-1]['source']=='safety' and frames[-1]['interrupt'] is True
    await s.close()


@pytest.mark.parametrize('kind',sorted(PLAYER_EVENTS))
def test_initialization_refresh_reconnection_and_same_counters_prove_no_event(kind):
    a={'details':{'player':player(selected=1,started=1,has_video=True,playing=True,opened=1,workspace_open=True)}}
    assert player_evidence(kind,None,a) is None
    assert player_evidence(kind,a,a) is None
    b=deepcopy(a);b['details']['player']['instance_id']=str(uuid4())
    assert player_evidence(kind,a,b) is None
    assert player_evidence(kind,a,b,True) is None


def test_protocol_discards_directory_information():
    assert PlayerFacts(**player(title='/private/path/Aladdin',title_source='filename')).title=='Aladdin'


async def test_superseded_generation_is_discarded_without_cancelling_the_model():
    r,s,wire,frames=await prepared()
    entered=asyncio.Event();release=asyncio.Event();old=s.adapter.reply
    async def delayed(*args,**kwargs):entered.set();await release.wait();return await old(*args,**kwargs)
    s.adapter.reply=delayed
    notify(r,s,'video_selected',selected=1,has_video=True,title='First',title_source='filename')
    r.step(90,seconds=3);s.pump();await entered.wait();task=s.task
    notify(r,s,'video_selected',selected=2,title='Second')
    assert not task.done()
    release.set();await task
    assert not any(f['type']=='speech' for f in frames)
    assert any(e['player']['title']=='Second' for e in s.pending)
    await s.close()


async def test_counter_rollback_and_close_do_not_create_a_fresh_opening():
    r,s,wire,frames=await prepared()
    notify(r,s,'player_opened',opened=1,workspace_open=True)
    r.state['details']['player']['workspace_open']=False;r.step(90,seconds=0)
    await settle(r,s)
    assert not any('Verified Player interaction:' in b['messages'][-1]['content'] for path,b in wire if path=='/api/chat')
    assert not any(e['kind'] in PLAYER_EVENTS for e in s.pending)
    before=r.observation.sequence;r.state['details']['player']['opened']=0;r.step(90,seconds=0)
    assert r.observation.sequence==before
    await s.close()


async def test_opening_is_not_displaced_by_player_notification():
    from tests.ai.test_event_deck_content import DEFINITION
    r,s,wire,frames=await prepared()
    s.deck()._start_done=False
    notify(r,s,'player_opened',opened=1,workspace_open=True)
    await settle(r,s)
    current=next(b for path,b in wire if path=='/api/chat')['messages'][-1]['content']
    assert DEFINITION.session_start[0].brief in current and 'Verified Player interaction:' not in current
    assert any(e['kind']=='player_opened' for e in s.pending)
    await s.close()


async def test_closing_clears_optional_player_queue():
    from tests.ai.test_event_deck_content import DEFINITION
    from tests.ai.test_event_deck_integration import finish
    r,s,wire,frames=await prepared()
    notify(r,s,'player_opened',opened=1,workspace_open=True)
    finish(r,s)
    await settle(r,s)
    current=next(b for path,b in wire if path=='/api/chat')['messages'][-1]['content']
    assert DEFINITION.session_end[0].brief in current and 'Verified Player interaction:' not in current
    assert not any(e['kind'] in PLAYER_EVENTS for e in s.pending)
    await s.close()


async def test_arrival_keeps_priority_over_player_notification():
    from companion_ai.event_deck import Arrival,DeckSettings
    r,s,wire,frames=await prepared(status='IDLE')
    s.deck_settings=DeckSettings(enabled=True,countdown_seconds=0,arrival_settle_seconds=0)
    s.arrival=Arrival(s.active_model_id,r.clock.mono(),s.deck_settings)
    notify(r,s,'player_opened',opened=1,workspace_open=True)
    await settle(r,s)
    assert s.arrival.state in {'generated','delivered'}
    current=next(b for path,b in wire if path=='/api/chat')['messages'][-1]['content']
    assert 'Verified Player interaction:' not in current
    assert any(e['kind']=='player_opened' for e in s.pending)
    await s.close()


async def test_player_notification_does_not_cross_session_boundary():
    r,s,wire,frames=await prepared()
    notify(r,s,'player_opened',opened=1,workspace_open=True)
    r.step(90,seconds=0,reset=True)
    await settle(r,s)
    assert not any('Verified Player interaction:' in b['messages'][-1]['content'] for path,b in wire if path=='/api/chat')
    await s.close()


async def test_player_notification_does_not_cancel_background_model_curation():
    r,s,wire,frames=await prepared()
    cancelled=[]
    s.curator.cancel=lambda:cancelled.append(True)
    notify(r,s,'player_opened',opened=1,workspace_open=True)
    assert not cancelled
    await s.close()


@pytest.mark.parametrize('disabled',['events','character'])
async def test_existing_event_and_character_context_only_settings_are_respected(disabled):
    from companion_ai.event_intelligence import EventConfig
    r,s,wire,frames=await prepared()
    s.event_intelligence.config=EventConfig(enabled=disabled!='events',preferences={'nova':{'session':0 if disabled=='character' else 1}})
    cancelled=[];s.curator.cancel=lambda:cancelled.append(True)
    notify(r,s,'player_opened',opened=1,workspace_open=True)
    assert not s.pending and not cancelled
    assert s.recent_events[-1]['kind']=='player_opened'
    await s.close()
