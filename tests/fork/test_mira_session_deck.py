# SPDX-License-Identifier: AGPL-3.0-only
"""Mira session content through the real custom composer, dealer and compiler."""
from copy import deepcopy
import json
from pathlib import Path
import re
import pytest
from companion_ai import character_builder as cb
from companion_ai.event_deck import DeckContext, DeckSettings, EventDeck, load_definition
from companion_ai.expressions import EXPRESSIONS

ROOT = Path(__file__).resolve().parents[2]
RAW = json.loads((ROOT / 'characters/models/mira-narrative-v1/session-deck.json').read_text())
BASE_RAW = json.loads((ROOT / 'config/event-deck.json').read_text())
BASE = load_definition(BASE_RAW)[0]
# What a custom character inherits: the shared lifecycle cards, never a built-in companion's own.
SHARED_START = [c for c in BASE.session_start if c.audience == 'shared']
SHARED_END = [c for c in BASE.session_end if c.audience == 'shared']
WORLD = {'id': 'mira-test-world', 'name': 'EdgeLoop fixture', 'setting': 'A fictional adult companion setting with Helix, Asterion, Nova, Cloverfield, Evelyn, Daisy and Celeste.'}
CHARACTER = {'id': 'mira', 'world': WORLD['id'], 'name': 'Mira', 'short_name': 'Mira', 'model': 'mira-narrative-v1:latest',
             'personality': 'HELIX-MORPH/09, an adult synthetic Helix companion. Witty, mischievous and socially curious.',
             'voice': 'Concise, natural dialogue; respect boundaries and use only supplied session facts.',
             'relationship': 'An autonomous adult participant, with no assumed private history.', 'deck': RAW}


def package(raw=None):
    return cb.load_package(cb.compose(WORLD, deepcopy(CHARACTER) | {'deck': deepcopy(RAW if raw is None else raw)}))


def definition(raw=None):
    return cb.compose_definition(BASE, package(raw))


def context(**kwargs):
    return DeckContext(**({'session_id': 'session', 'status': 'RUNNING'} | kwargs))


def deck(**settings):
    return EventDeck(definition(), 'mira-test', 'custom.mira', 'session', 'epoch', DeckSettings(enabled=True, **settings))


def delivered(d, play, now):
    for status in ('accepted', 'generated', 'delivered'):
        d.transition(play.id, status, now)


def normals(d):
    d._start_done = True
    # These tests isolate reusable normal draws, not inherited common milestones.
    d._activated |= {s.id for s in BASE.sequences}


def test_twelve_cards_register_only_under_miras_custom_identity():
    p = package(); d = definition()
    own = [c for c in [*d.normal, *d.session_start, *d.session_end] if c.audience == p.identity]
    assert len(own) == 12 and len(p.cards) == 10
    assert all(c.id.startswith('mira.') and c.memory == 'none' for c in own)
    assert all(c.repeat for c in own)
    assert not any(c.audience in {'nova','celeste','evelyn','daisy'} for c in d.normal)
    assert d.sequences == BASE.sequences and d.arrival == BASE.arrival
    assert {c.kind for c in own} == {'normal','session_start','session_end'}
    for c in own:
        emotion = re.search(r'Use (\w+) delivery', c.brief)[1]
        assert emotion in EXPRESSIONS
        assert len(c.brief) <= 400 and not re.search(r'["“”]', c.brief)


def test_custom_deck_has_no_actions_new_events_or_memory_writes():
    p = package(); d = definition()
    assert set(p.deck) == {'shared','cards','session_start','session_end'}
    assert d.sequences == BASE.sequences
    assert all(c.memory == 'none' for c in [*d.normal,*d.session_start,*d.session_end])
    assert all(set(c) <= {'id','theme','brief','when','repeat','enabled'} for c in RAW['cards'])
    assert all(not c.eligibility.requires_story_welcome for c in d.normal)


def test_composition_is_pure():
    # Mira is now a standard companion in config/event-deck.json; this file keeps her DeckSpec as a
    # custom-path fixture. Composing it must not mutate the shared definition.
    before = BASE.model_dump(mode='json')
    definition()
    assert BASE.model_dump(mode='json') == before
    for identity in ('nova','celeste','evelyn','daisy'):
        assert len([c for c in BASE.normal if c.audience == identity]) == 15


def test_legacy_custom_package_hash_and_shared_lifecycle_are_unchanged():
    fixture = ROOT / 'tests/fixtures/character-builder'
    p = cb.compose(json.loads((fixture/'world-saltglass.json').read_text()), json.loads((fixture/'character-wren.json').read_text()), (fixture/'wren.png').read_bytes())
    assert p['content_sha256'] == '74b225d3fa418fb5cb5e4781935a96f56ad10478e54f727fc6bde55df6322e73'
    assert set(p['deck']) == {'shared','cards'}
    d = cb.compose_definition(BASE, cb.load_package(p))
    assert d.session_start == SHARED_START and d.session_end == SHARED_END


def test_opening_is_once_per_confirmed_session_and_not_replayed_on_late_activation():
    d = deck(); opening = d.next_play(context(), 0).play
    assert opening.card.id == 'mira.uninvited-company' and opening.lane == 'session_start'
    assert d.next_play(context(), 1).reason == 'play_active'
    delivered(d, opening, 0)
    assert d.next_play(context(), 9).reason == 'countdown'
    assert d.next_play(context(), 10).play.lane == 'normal'
    late = deck(); assert late.next_play(context(seconds=121), 0).play.lane == 'normal'


@pytest.mark.parametrize('changes', [
    {'status':'IDLE'}, {'status':'PAUSED'}, {'fresh':False}, {'quiet':True},
    {'no_contact':True}, {'watchdog_paused':True}, {'user_active':True},
    {'output_busy':True}, {'proactive_enabled':False}, {'fault':'signal_lost'},
])
def test_existing_session_safety_and_output_gates_remain_authoritative(changes):
    assert deck().next_play(context(**changes), 0).play is None


def test_normal_eligibility_uses_existing_counters_phase_and_state_only():
    cards = {c.id.split('.',1)[1]:c for c in definition().normal}
    eligible = EventDeck._eligible
    quality = cards['helix-quality-control']
    assert not eligible(quality, context(edges=2)) and eligible(quality, context(edges=3))
    assert quality.eligibility.min_edges == 3 and quality.eligibility.requires_hr is False
    prize = cards['eyes-on-prize']
    assert not eligible(prize, context()) and eligible(prize, context(phase='finishing'))
    surprise = cards['unexpected-results']
    assert not eligible(surprise, context()) and eligible(surprise, context(status='RAMPDOWN'))
    distraction = cards['professional-distraction']
    assert not eligible(distraction, context()) and eligible(distraction, context(has_conversation=True))
    for phase in ('building','finishing','recovery'):
        assert eligible(cards['little-encouragement'], context(phase=phase))


def test_countdown_output_busy_shuffle_and_no_immediate_duplicate():
    d = deck(); normals(d); ctx = context(edges=3, has_conversation=True)
    seen=[]
    for cycle in range(24):
        now=float(cycle*10)
        draw=d.next_play(ctx,now);assert draw.play is not None, draw.reason
        seen.append(draw.play.card.id)
        assert d.next_play(ctx,now).reason == 'play_active'
        delivered(d,draw.play,now)
        assert d.next_play(ctx,now+9).reason == 'countdown'
    assert all(a != b for a,b in zip(seen,seen[1:]))
    # All eight currently eligible normal cards are dealt once before recycling.
    count=sum(EventDeck._eligible(c,ctx) for c in definition().normal)
    assert len(set(seen[:count])) == count


def test_verified_common_milestones_precede_normal_mira_cards():
    d=deck(); d._start_done=True;d.observe(context(),0)
    draw=d.next_play(context(edges=3),1)
    assert draw.play.lane == 'mission' and draw.play.card.audience == 'shared'
    # No new Mira mission or event handler has been registered.
    assert [s.id for s in definition().sequences] == [s.id for s in BASE.sequences]


def test_interruption_and_failure_use_existing_bounded_retry_policies():
    d=deck();normals(d);p=d.next_play(context(),0).play
    d.transition(p.id,'accepted',0);d.transition(p.id,'cancelled',0,'user_interrupt')
    assert d.next_play(context(),1).play is None
    assert d.next_play(context(),2).play is not None


def test_farewell_is_only_after_verified_finalization_and_is_idempotent():
    d=deck();normals(d)
    assert all(c.kind != 'session_end' for c in d._cards.values())
    assert d.finish_session('session',{'termination':'manual_stop','edges':3,'active_running_seconds':100},20)
    assert not d.finish_session('session',{'termination':'manual_stop'},21)
    closing=d.next_play(context(status='IDLE'),22).play
    assert closing.lane == 'session_end' and closing.card.id == 'mira.until-next-time'
    delivered(d,closing,22)
    assert d.next_play(context(status='IDLE'),23).play is None


@pytest.mark.parametrize('termination', ['safety_stop','cancelled','cancelled_or_unclassified_stop'])
def test_protective_or_cancelled_endings_do_not_force_a_flirty_farewell(termination):
    d=deck();d.finish_session('session',{'termination':termination},20)
    assert d.next_play(context(status='IDLE'),21).play is None


def test_preview_reports_selected_lifecycle_overrides_not_both_versions():
    p=cb.compose(WORLD,deepcopy(CHARACTER));view=cb.preview(p,BASE)
    assert view['shared_lifecycle']['session_start'] == ['mira.uninvited-company']
    assert view['shared_lifecycle']['session_end'] == ['mira.until-next-time']
    assert len(view['cards']) == 10


@pytest.mark.parametrize('lane', ['session_start','session_end'])
def test_lifecycle_scope_lane_and_conditions_are_validated(lane):
    raw=deepcopy(RAW);raw[lane]['when']={'min_edges':1}
    with pytest.raises(Exception,match='lifecycle conditions'):
        cb.compose(WORLD,deepcopy(CHARACTER)|{'deck':raw})
    p=cb.compose(WORLD,deepcopy(CHARACTER));p['deck'][lane]['audience']='custom.someone-else'
    with pytest.raises(cb.BuilderError): cb.load_package(p)
    p=cb.compose(WORLD,deepcopy(CHARACTER));p['deck'][lane]['kind']='normal'
    with pytest.raises(cb.BuilderError): cb.load_package(p)


def test_disabled_lifecycle_overrides_retain_shared_cards_and_ids_must_be_unique():
    raw=deepcopy(RAW);raw['session_start']['enabled']=False;raw['session_end']['enabled']=False
    d=definition(raw);assert d.session_start==SHARED_START and d.session_end==SHARED_END
    raw=deepcopy(RAW);raw['session_start']['id']=raw['cards'][0]['id']
    with pytest.raises(Exception,match='unique'): cb.compose(WORLD,deepcopy(CHARACTER)|{'deck':raw})


@pytest.mark.asyncio
@pytest.mark.parametrize('card_key,emotion', [('uninvited-company','mischievous'),('helix-quality-control','focused')])
async def test_real_service_uses_mira_card_current_expression_protocol_and_no_action_paths(tmp_path,card_key,emotion):
    from ai_observer.observation import ObserverDirector
    from companion_ai.conversation import ConversationService, ModelManager
    from companion_ai.director import DirectorConfig
    from companion_ai.models import AIConfig
    from companion_ai.storage import SettingsStore
    from tests.fork.event_replay import Replay
    from tests.ai.test_character_builder import ollama
    wire=[];r=Replay();r.state['devices'].update(toy_ready=True,handy=True,hr_ready=False,simulated_hr=False)
    r.state['safety'].update(fault='none',signal='missing');r.state.update(status='RUNNING',edges=3 if card_key=='helix-quality-control' else 0,seconds=0);r.step(None,seconds=0)
    store=SettingsStore(tmp_path);manager=ModelManager(transport=ollama(wire,reply='[[expression:'+emotion+']] Helix paperwork has become unusually interesting.'),store=store)
    await manager.select(AIConfig(model=CHARACTER['model']),character=package());manager.current_summary=r.observation.summary
    frames=[];speech=ConversationService(r.observation,frames.append,manager,clock=r.clock.mono,director=ObserverDirector(DirectorConfig(regenerate_once=False),clock=r.clock.mono))
    speech.deck_settings=DeckSettings(enabled=True)
    narrative_before=deepcopy(speech.narrative.state)
    if card_key=='helix-quality-control':
        d=speech.deck();normals(d);d._queue=['mira.helix-quality-control']
    before=deepcopy(r.state);speech.pump();assert speech.task is not None
    await speech.task
    request=next(body for path,body in reversed(wire) if path=='/api/chat')
    expected=RAW['session_start'] if card_key=='uninvited-company' else next(c for c in RAW['cards'] if c['id']==card_key)
    assert expected['brief'] in request['messages'][-1]['content']
    if card_key=='helix-quality-control':
        assert 'Edges this session: 3' in request['messages'][-1]['content']
        assert 'Heart rate:' not in request['messages'][-1]['content']
    assert request['think'] is False and 'tools' not in request
    assert r.state==before
    assert any(f['type']=='response_expression' and f['expression']==emotion for f in frames)
    assert any(f['type']=='speech' for f in frames)
    assert not any(f.get('type') in {'settings_request','player_opened','video_selected','video_started'} for f in frames)
    assert not list(tmp_path.rglob('*journal*'))
    assert speech.narrative.state == narrative_before
    await speech.close()

def test_lifecycle_cards_share_existing_authored_card_limit():
    raw=deepcopy(RAW)
    for i in range(5):
        raw['cards'].append({'id':f'extra-{i}','theme':'banter','brief':'Offer a fresh remark.'})
    with pytest.raises(Exception,match='at most 16'):
        cb.compose(WORLD,deepcopy(CHARACTER)|{'deck':raw})
    raw['cards'].pop()
    assert len(package(raw).cards)==14


def test_library_save_reopen_and_recompose_preserve_overrides_without_activation(tmp_path):
    from companion_ai.storage import SettingsStore
    library=cb.Library(SettingsStore(tmp_path));library.save_world(WORLD);library.save_character(deepcopy(CHARACTER))
    reopened=library.read('characters','mira')
    assert reopened['deck']['session_start']['brief']==RAW['session_start']['brief']
    assert reopened['deck']['session_end']['brief']==RAW['session_end']['brief']
    composed=library.compose('mira')
    assert composed['content_sha256']==cb.compose(WORLD,deepcopy(CHARACTER))['content_sha256']
    assert library.active() is None
    assert len(json.dumps({'version':1,'type':'character_builder','action':'save_character','character':reopened}).encode())<16384

def test_saving_an_unchanged_legacy_source_does_not_add_null_fields_or_bump_revision(tmp_path):
    from companion_ai.storage import SettingsStore
    fixture=ROOT/'tests/fixtures/character-builder';source=json.loads((fixture/'character-wren.json').read_text())
    library=cb.Library(SettingsStore(tmp_path));saved=library.save_character(source)
    assert set(saved.model_dump()['deck'])=={'shared','cards'}
    assert library.save_character(library.read('characters',source['id'])).revision==saved.revision
