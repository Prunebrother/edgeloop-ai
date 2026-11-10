# SPDX-License-Identifier: AGPL-3.0-only
"""Phase 1C: the shipped card library. Mocked inference, real compiler, no hardware."""
import asyncio,itertools,json,re
from pathlib import Path
import httpx
import pytest
from ai_observer.observation import ObserverDirector
from companion_ai.conversation import ConversationService,ModelManager,character_identity
from companion_ai.director import DirectorConfig
from companion_ai.event_deck import DeckSettings,EventDeck,load_definition,DeckContext
from companion_ai.event_intelligence import EventConfig
from companion_ai.models import AIConfig
from tests.ai.test_f25 import runtime
from tests.fork.event_replay import Replay

ROOT=Path(__file__).resolve().parents[2]
RAW=json.loads((ROOT/'config/event-deck.json').read_text())
DEFINITION,ERROR=load_definition(RAW)
SESSION='session';COMPANIONS=['nova','evelyn','daisy','celeste']
MODELS={'nova':'nova-narrative-v1:latest','evelyn':'evelyn-narrative-v1:latest','daisy':'daisy-narrative-v1:latest','celeste':'celeste-narrative-v2:latest'}

def normal():return {card.id:card for card in DEFINITION.normal}
def missions():return {sequence.id:sequence for sequence in DEFINITION.sequences}
def context(**values):return DeckContext(**({'session_id':SESSION,'status':'RUNNING'}|values))
def deck(identity='nova',**settings):return EventDeck(DEFINITION,'scope:'+identity,identity,SESSION,'epoch',DeckSettings(**({'enabled':True,'countdown_seconds':0,'mission_spacing_seconds':0}|settings)))
CLOCK=itertools.count(1)

def deliver(target,play,now=0):
 for status in ('accepted','generated','delivered'):target.transition(play.id,status,now)

def drawn(target,ctx,limit=120):
 """Every normal card this session state can draw, through whole shuffled cycles."""
 seen=[]
 for _ in range(limit):
  now=next(CLOCK);draw=target.next_play(ctx,now)
  if not draw.play:break
  if draw.play.lane=='normal':seen.append(draw.play.card.id)
  deliver(target,draw.play,now)
 return seen


# Inventory

def test_the_shipped_library_is_valid_and_has_a_new_revision():
 assert ERROR is None and DEFINITION.revision==5 and RAW['schema_version']==1

@pytest.mark.parametrize('intent,count',[('edge_commentary',2),('session_duration',2),('hr_trend',3),('encouragement',2),('performance_observation',2),('playful_challenge',2),('recovery',2),('general_conversation',4),('finish_encouragement',2)])
def test_every_shared_category_is_present(intent,count):
 assert len([c for c in DEFINITION.normal if c.intent==intent and c.audience=='shared'])==count

@pytest.mark.parametrize('audience,intents',[('nova',{'character_curiosity_nova','character_challenge_nova'}),('evelyn',{'scientific_observation'}),('daisy',{'cloverfield_production','cloverfield_encouragement'}),('celeste',{'diplomatic_evaluation','personal_observation'})])
def test_every_companion_has_its_requested_themes(audience,intents):
 cards=[c for c in DEFINITION.normal if c.audience==audience]
 assert len(cards)==15 and intents<={c.intent for c in cards}
 assert [c.id for c in cards if c.eligibility.phases==['finishing']]==[audience+'-finish']
 assert [c.id for c in cards if c.eligibility.phases==['recovery']]==[audience+'-another-load']
 assert len([c for c in cards if c.intent=='orgasm_count' and c.eligibility.min_orgasms==1])==1

def test_opening_and_closing_are_single_shared_cards():
 assert [(c.id,c.audience) for c in DEFINITION.session_start]==[('opening','shared')]
 assert [(c.id,c.audience) for c in DEFINITION.session_end]==[('closing','shared')]

def test_the_mission_pack_is_three_counter_milestones_and_a_repeatable_orgasm_reaction():
 assert {k:(v.lane,v.audience,v.trigger.min_edges,v.trigger.min_seconds,v.trigger.event_kinds,len(v.steps),v.repeat) for k,v in missions().items()}=={f'edges-{n}':('mission','shared',n,None,[],1,False) for n in (3,7,10)}|{'orgasm-reported':('mission','shared',None,None,['orgasm_reported'],1,True),'next-round':('mission','shared',None,None,['round_ready'],1,True)}


# Cards are intentions, within the existing boundaries

ALL=[*DEFINITION.session_start,*DEFINITION.session_end,*DEFINITION.normal,*[step for s in DEFINITION.sequences for step in s.steps]]

@pytest.mark.parametrize('card',ALL,ids=[c.id for c in ALL])
def test_every_card_states_an_intention_within_bounds(card):
 assert card.memory=='none'
 assert not re.search(r'["“”]',card.brief),'Fixed dialogue'
 assert not re.search(r'\d',card.brief),'A number must come from verified facts'
 assert not re.search(r'\b(?:intensity|speed|stroke|stimulation|device|hardware|toy|pullback|threshold)\b',card.brief,re.I),'Hardware subject'

def test_the_library_has_no_weights_or_probabilities():
 fields={key for card in RAW['normal'] for key in card}
 assert fields<={'id','kind','audience','intent','brief','eligibility'}

@pytest.mark.parametrize('card',[c for c in DEFINITION.normal if c.intent=='playful_challenge' or c.id=='nova-challenge'],ids=lambda c:c.id)
def test_challenges_never_ask_for_settings_changes(card):
 assert 'Never ask for a change to settings' in card.brief and card.eligibility.statuses==['RUNNING']

@pytest.mark.parametrize('card',ALL,ids=[c.id for c in ALL])
def test_no_card_restricts_how_demanding_a_character_may_be(card):
 assert not re.search(r'\b(?:limits?|comfort|discomfort|pain)\b',card.brief,re.I) or card.eligibility.requires_hr

@pytest.mark.parametrize('card',[c for c in DEFINITION.normal if c.eligibility.requires_hr],ids=lambda c:c.id)
def test_heart_rate_cards_need_a_verified_trend_and_claim_no_cause(card):
 assert card.eligibility.hr_trends and re.search(r'no cause',card.brief,re.I)


# Character isolation

@pytest.mark.parametrize('identity',COMPANIONS+['generic'])
def test_each_companion_sees_only_shared_and_its_own_cards(identity):
 ctx=context(edges=5,seconds=1300,hr_current=True,hr_trend='falling')
 seen=drawn(deck(identity),ctx)
 foreign={c.id for c in DEFINITION.normal if c.audience not in {'shared',identity}}
 own={c.id for c in DEFINITION.normal if c.audience==identity and not c.eligibility.phases and not c.eligibility.min_orgasms}
 assert not foreign&set(seen) and own<=set(seen) and seen
 assert not {c.id for c in DEFINITION.normal if c.eligibility.phases or c.eligibility.min_orgasms or c.eligibility.min_total_orgasms}&set(seen)

@pytest.mark.parametrize('identity',COMPANIONS)
def test_every_companions_current_model_resolves_to_its_cards(identity):
 assert character_identity(MODELS[identity])==identity


# Unavailable measurements

def test_no_sensor_never_draws_a_heart_rate_card_and_the_deck_carries_on():
 seen=drawn(deck('evelyn'),context(edges=5,seconds=1300,signal='missing'))
 assert seen and not [c for c in seen if normal()[c].eligibility.requires_hr]

def test_a_current_rate_with_no_verified_trend_draws_no_trend_card():
 seen=drawn(deck('evelyn'),context(edges=5,hr_current=True,hr_trend='unknown'))
 assert seen and not [c for c in seen if normal()[c].eligibility.requires_hr]

@pytest.mark.parametrize('trend,expected',[('rising',{'hr-rising'}),('falling',{'hr-falling','recovery-easing'}),('steady',{'hr-steady'})])
def test_only_the_matching_trend_card_is_available(trend,expected):
 seen=drawn(deck(),context(edges=5,hr_current=True,hr_trend=trend))
 assert {c for c in seen if normal()[c].eligibility.requires_hr}==expected

def test_a_deferred_card_stays_in_the_deck_and_plays_once_its_measurement_returns():
 target=deck('evelyn');first=drawn(target,context(edges=0,seconds=0),limit=8)
 assert 'evelyn-observation-trend' not in first
 later=drawn(target,context(edges=1,seconds=0,hr_current=True,hr_trend='rising'),limit=40)
 assert 'evelyn-observation-trend' in later and 'evelyn-observation-edges' in later

def test_counter_cards_wait_for_their_counters():
 seen=drawn(deck(),context())
 assert seen and not [c for c in seen if normal()[c].eligibility.min_edges or normal()[c].eligibility.min_seconds]

def test_edge_commentary_tracks_the_count():
 assert 'edge-count-first' in drawn(deck(),context(edges=4)) and 'edge-count-many' not in drawn(deck(),context(edges=4))
 assert 'edge-count-many' in drawn(deck(),context(edges=5)) and 'edge-count-first' not in drawn(deck(),context(edges=5))

def test_only_ramp_down_cards_and_factual_cards_play_during_ramp_down():
 seen=drawn(deck(),context(status='RAMPDOWN'))
 assert seen==['recovery-winding-down']*len(seen) and seen


# The existing scheduler over the shipped library

def test_order_is_opening_then_missions_in_ascending_order_then_normal():
 target=deck();ctx=context(edges=10);order=[]
 target.observe(context(),-1)
 for step in range(4):
  play=target.next_play(ctx,step).play;order.append(play.card.id);deliver(target,play,step)
 assert order==['opening','edges-3-reached','edges-7-reached','edges-10-reached']
 assert target.next_play(ctx,5).play.lane=='normal'

def test_each_milestone_plays_once():
 target=deck();seen=[]
 for edges in (1,3,3,4,7,7,8,10,10,12):
  for _ in range(3):
   now=next(CLOCK);draw=target.next_play(context(edges=edges),now)
   if draw.play:
    if draw.play.lane!='normal':seen.append(draw.play.card.id)
    deliver(target,draw.play,now)
 assert seen==['opening','edges-3-reached','edges-7-reached','edges-10-reached']

def test_missions_continue_with_event_intelligence_off():
 target=deck();deliver(target,target.next_play(context(),0).play,0)
 assert target.next_play(context(edges=3,event_reactions_enabled=False),1).play.card.id=='edges-3-reached'

def test_the_closing_outranks_every_ready_card():
 target=deck();deliver(target,target.next_play(context(),0).play,0)
 target.finish_session(SESSION,{'termination':'manual_stop','edges':10},1)
 assert target.next_play(context(status='IDLE',edges=10),2).play.card.id=='closing'

def test_the_draw_is_unweighted_and_seeded_per_model():
 first=EventDeck(DEFINITION,'scope:nova','nova',SESSION,'epoch',DeckSettings(enabled=True))
 same=EventDeck(DEFINITION,'scope:nova','nova',SESSION,'epoch',DeckSettings(enabled=True))
 other=EventDeck(DEFINITION,'scope:other','nova',SESSION,'epoch',DeckSettings(enabled=True))
 assert first._queue==same._queue and first._queue!=other._queue and len(first._queue)==len(set(first._queue))


# Through the real compiler

TRENDS={'rising':(90,94,98,102,106,110),'falling':(110,106,102,98,94,90),'steady':(90,90,90,90,90,90)}

def replies_in_turn(wire,replies,during=lambda:None):
 """Inference returning each reply in turn, repeating the last."""
 count=itertools.count()
 def handler(request):
  if request.url.path=='/api/chat':
   wire.append((request.url.path,json.loads(request.content)));during()
   body=replies[min(next(count),len(replies)-1)]
   return httpx.Response(200,text=json.dumps({'message':{'content':body},'done':True,'done_reason':'stop'})+'\n')
  return runtime([],'').handler(request)
 return httpx.MockTransport(handler)

async def connect(r,identity='nova',reply='A clear line of thought.',wire=None,transport=None):
 """A new service on an existing observation: what a restart rebuilds, in memory, from nothing."""
 wire=[] if wire is None else wire
 m=ModelManager(transport=transport or runtime(wire,reply));await m.select(AIConfig(model=MODELS[identity]));m.current_summary=r.observation.summary
 frames=[];d=ObserverDirector(DirectorConfig(regenerate_once=False),clock=r.clock.mono)
 s=ConversationService(r.observation,frames.append,m,clock=r.clock.mono,director=d)
 s.deck_settings=DeckSettings(enabled=True,countdown_seconds=0);s.deck_identity=identity;s.deck_definition=DEFINITION
 return s,frames

async def service(identity='nova',reply='A clear line of thought.',edges=0,seconds=0,trend=None,status='RUNNING',transport=None,wire=None,orgasm_mode=None,orgasms=0,last_orgasm=None):
 r=Replay();r.state['devices'].update(toy_ready=True,handy=True);r.state['safety']['fault']='none'
 r.state.update(edges=edges,seconds=seconds,status=status)
 if orgasm_mode is not None:r.state['details']['orgasm_mode']=orgasm_mode
 if orgasms:r.state['details'].update(orgasm_count=orgasms,last_orgasm_seconds=last_orgasm)
 if trend:
  for bpm in TRENDS[trend]:r.step(bpm,seconds=1)
 else:
  r.state['devices'].update(hr_ready=False,simulated_hr=False);r.state['safety']['signal']='missing'
  r.step(None,seconds=0)
 wire=[] if wire is None else wire
 s,frames=await connect(r,identity,reply,wire,transport)
 return r,s,wire,frames

def play_only(s,card_id):
 """Isolate one shipped card: the scheduler stays real, the deck holds just that card."""
 card=next(c for c in ALL if c.id==card_id)
 deck=s.deck();deck._start_done=True;deck._cards={card.id:card};deck._queue=[card.id];deck._played=[];deck._activated|={q.id for q in DEFINITION.sequences};deck._runs=[]

def prompt(wire):
 return next(b for path,b in reversed(wire) if path=='/api/chat')['messages'][-1]['content']

@pytest.mark.parametrize('card_id,state,expected,hidden',[
 ('edge-count-first',{'edges':3,'seconds':700},r'Edges this session: 3',r'Running time|700|11 minutes'),
 ('duration-settling',{'edges':3,'seconds':700},r'Running time: 11 minutes 40 seconds',r'Edges this session'),
 ('general-remark',{'edges':3,'seconds':700},r'mention no counts, times or readings',r'Edges this session|Running time|11 minutes')])
async def test_a_card_receives_the_facts_it_needs_and_no_others(card_id,state,expected,hidden):
 r,s,wire,_=await service(**state);play_only(s,card_id)
 s.pump();await s.task
 current=prompt(wire)
 assert re.search(expected,current,re.S),current
 assert not re.search(hidden,current,re.S),current

async def test_a_heart_rate_card_receives_the_reading_and_labels_its_source():
 r,s,wire,_=await service(trend='rising')
 assert r.observation.trend=='rising' and s.deck_context(r.clock.mono()).hr_current
 assert s.deck_context(r.clock.mono()).hr_trend=='rising'
 play_only(s,'hr-rising');s.pump();await s.task
 current=prompt(wire)
 assert re.search(r'Heart rate: 110 BPM and rising\. SIMULATED',current) and 'not a measurement of this person' in current

async def test_the_deck_context_never_reports_a_trend_it_cannot_verify():
 r,s,_,_=await service()
 ctx=s.deck_context(r.clock.mono())
 assert ctx.hr_current is False and ctx.hr_trend=='unknown'

async def test_heart_rate_cards_obey_event_intelligence_and_the_physiology_preference():
 r,s,_,_=await service(trend='rising')
 assert s.deck_context(r.clock.mono()).hr_current
 s.event_intelligence.configure(EventConfig(enabled=False))
 assert not s.deck_context(r.clock.mono()).hr_current
 s.event_intelligence.configure(EventConfig(enabled=True,preferences={'nova':{'physiology':0}}))
 assert not s.deck_context(r.clock.mono()).hr_current

async def test_a_wrong_count_in_a_form_the_fidelity_check_recognises_is_not_delivered():
 r,s,wire,frames=await service(edges=3,reply='Your edge count is 9.');play_only(s,'edge-count-first')
 s.pump();await s.task;await asyncio.sleep(0)
 assert not [f for f in frames if f['type']=='speech'] and s.deck().snapshot()['counts'].get('delivered',0)==0

@pytest.mark.parametrize('reply',['You have reached 9 edges already.',"That's nine edges.",'You have edged nine times.','This is your ninth edge.',"You've been going for 20 minutes."])
async def test_a_wrong_count_in_free_form_wording_is_not_delivered(reply):
 r,s,wire,frames=await service(edges=3,seconds=600,reply=reply);play_only(s,'edge-count-first')
 s.pump();await s.task;await asyncio.sleep(0)
 assert not [f for f in frames if f['type']=='speech'] and s.deck().snapshot()['counts'].get('delivered',0)==0
 assert not [m for m in s.history if m['role']=='assistant'] and s.deck().snapshot()['counts']['suppressed']==1
 assert not [f for f in frames if f['type']=='conversation_error'] and [f['reason'] for f in frames if f['type']=='response_suppressed']==['fidelity']

async def test_a_wrong_count_is_regenerated_once_and_only_the_correct_reply_is_delivered():
 wire=[]
 r,s,wire,frames=await service(edges=3,wire=wire,transport=replies_in_turn(wire,['You have reached 9 edges already.','Three edges, and counting.']));play_only(s,'edge-count-first')
 s.pump();await s.task;await asyncio.sleep(0)
 assert [f['text'] for f in frames if f['type']=='speech']==['Three edges, and counting.']
 assert len([b for path,b in wire if path=='/api/chat'])==2 and 'CORRECTION REQUIRED: your draft stated an edge count' in wire[-1][1]['messages'][0]['content'] and 'wrong_edges' not in wire[-1][1]['messages'][0]['content']
 assert [m['content'] for m in s.history if m['role']=='assistant']==['Three edges, and counting.']

async def test_a_counter_advancing_during_generation_does_not_reject_the_count_the_model_was_told():
 wire=[];holder={}
 def advance():
  holder['r'].state.update(edges=4);holder['r'].step(None,seconds=1)
 r,s,wire,frames=await service(edges=3,wire=wire,transport=replies_in_turn(wire,['You have reached 3 edges.'],advance));holder['r']=r;play_only(s,'edge-count-first')
 s.pump();await s.task;await asyncio.sleep(0)
 assert r.state['edges']==4 and len(wire)==1 and [f['text'] for f in frames if f['type']=='speech']==['You have reached 3 edges.']

async def test_a_rejected_reply_never_reaches_story_memory():
 r,s,wire,frames=await service(edges=3,reply='You have reached 9 edges already.');play_only(s,'edge-count-first')
 developments=list(s.narrative.state['developments'])
 s.pump();await s.task;await asyncio.sleep(0)
 assert s.narrative.state['developments']==developments

async def test_a_labelled_simulated_trend_is_delivered_and_a_physical_claim_is_not():
 r,s,wire,frames=await service(trend='rising',reply='The simulated heart rate is rising.');play_only(s,'hr-rising')
 s.pump();await s.task;await asyncio.sleep(0)
 assert [f['text'] for f in frames if f['type']=='speech']==['The simulated heart rate is rising.']
 r,s,wire,frames=await service(trend='rising',reply='Your real pulse is pounding.');play_only(s,'hr-rising')
 s.pump();await s.task;await asyncio.sleep(0)
 assert not [f for f in frames if f['type']=='speech'] and s.deck().snapshot()['counts'].get('delivered',0)==0

async def test_a_correct_count_is_delivered():
 r,s,wire,frames=await service(edges=3,reply='That makes 3 edges so far.');play_only(s,'edge-count-first')
 s.pump();await s.task;await asyncio.sleep(0)
 assert [f['text'] for f in frames if f['type']=='speech']==['That makes 3 edges so far.'] and s.deck().snapshot()['counts']['delivered']==1

def state_for(card):
 rule=card.eligibility
 return {'edges':rule.max_edges if rule.max_edges is not None else rule.min_edges or 0,'seconds':rule.min_seconds or 0,
  'trend':(rule.hr_trends or [None])[0],'status':rule.statuses[0],'orgasm_mode':(rule.phases or ['building'])[0]=='finishing',
  # Recovery: an orgasm a moment ago. Count cards: one earlier this session, past the recovery window.
  'orgasms':1 if rule.phases==['recovery'] or rule.min_orgasms else 0,
  'last_orgasm':max(0,(rule.min_seconds or 0)-10) if rule.phases==['recovery'] else 0 if rule.min_orgasms else None}

@pytest.mark.parametrize('card',[c for c in DEFINITION.normal],ids=lambda c:c.id)
async def test_every_normal_card_is_drawable_and_compiles_for_its_companion(card):
 identity=card.audience if card.audience!='shared' else 'nova'
 r,s,wire,frames=await service(identity=identity,**state_for(card));play_only(s,card.id)
 if card.eligibility.min_total_orgasms:s.orgasm_counts=lambda report=None:{'orgasms':0,'total_orgasms':card.eligibility.min_total_orgasms,'total_known':True}
 if card.eligibility.min_orgasms:r.state['seconds']=max(r.state['seconds'],200);r.step(None,seconds=0)
 if card.eligibility.requires_conversation:s.history.append({'role':'user','content':'I like quiet mornings.','session_id':r.state['session_id']})
 s.pump();assert s.task and not s.task.done(),s.director.last_reason
 await s.task;await asyncio.sleep(0)
 assert not [f for f in frames if f['type']=='conversation_error']
 assert [f['source'] for f in frames if f['type']=='speech']==['event']
 body=next(b for path,b in reversed(wire) if path=='/api/chat')
 assert body['think'] is False and not body.get('tools')
 assert card.brief in prompt(wire) and 'This is not a message from them' in prompt(wire)

@pytest.mark.parametrize('edges,card_id',[(3,'edges-3-reached'),(7,'edges-3-reached'),(10,'edges-3-reached')])
async def test_a_mission_turn_receives_the_verified_edge_count(edges,card_id):
 r,s,wire,frames=await service(edges=edges);s.deck()._start_done=True;s.deck()._counter_baseline={'edges':0,'seconds':0}
 s.pump();await s.task
 assert s.adapter is not None and next(c for c in ALL if c.id==card_id).occasion in prompt(wire) and card_id not in prompt(wire)
 assert f'the participant has reached {edges} edges' in prompt(wire)

async def test_the_opening_card_reaches_the_model_for_every_companion():
 for identity in COMPANIONS:
  r,s,wire,frames=await service(identity=identity)
  s.pump();await s.task
  assert 'Mark the start in your own voice' in prompt(wire)


# Restart: a rebuilt deck never replays a milestone already reached

def missions_played(target,ctx,now=1000):
 seen=[]
 for step in range(6):
  draw=target.next_play(ctx,now+step)
  if draw.play:
   if draw.play.lane=='mission':seen.append(draw.play.card.id)
   deliver(target,draw.play,now+step)
 return seen

def test_a_milestone_reached_before_the_first_observation_is_not_replayed():
 target=deck();target.observe(context(edges=8,seconds=900),0)
 snapshot=target.snapshot()
 assert missions_played(target,context(edges=8,seconds=900))==[]
 assert snapshot['counter_baseline']=={'edges':8,'seconds':900} and snapshot['activations']==[]
 assert {('edges-3-reached','reached_before_first_observation'),('edges-7-reached','reached_before_first_observation')}<={(h['card_id'],h['reason']) for h in snapshot['history']}

def test_only_crossings_after_the_first_observation_play():
 target=deck();missions_played(target,context(edges=5,seconds=900))
 assert missions_played(target,context(edges=6,seconds=901))==[]
 assert missions_played(target,context(edges=7,seconds=902),2000)==['edges-7-reached']
 assert missions_played(target,context(edges=7,seconds=903),3000)==[]
 assert missions_played(target,context(edges=11,seconds=904),4000)==['edges-10-reached']

def test_a_new_session_from_zero_still_plays_every_milestone():
 target=deck();assert missions_played(target,context())==[]
 assert missions_played(target,context(edges=10),2000)==['edges-3-reached','edges-7-reached','edges-10-reached']

@pytest.mark.parametrize('state',[{'fresh':False},{'status':'IDLE'},{'session_id':'other'}])
def test_an_invalid_observation_cannot_become_the_baseline(state):
 target=deck();target.observe(context(edges=9,**state),0)
 assert target.snapshot()['counter_baseline'] is None
 target.observe(context(),1);assert target.snapshot()['counter_baseline']=={'edges':0,'seconds':0}
 assert target.observe(context(edges=3),2)==['edges-3']

def test_a_paused_session_can_set_the_baseline():
 target=deck();target.observe(context(edges=5,status='PAUSED'),0)
 assert target.snapshot()['counter_baseline']['edges']==5
 assert target.observe(context(edges=5),1)==[]

async def test_a_restart_does_not_replay_a_delivered_milestone_and_later_crossings_still_play():
 r,s,wire,frames=await service(edges=0)
 s.deck_observe(s.deck(),r.clock.mono());s.deck()._start_done=True
 r.state.update(edges=3);r.step(None,seconds=130)
 s.pump();await s.task;await asyncio.sleep(0)
 assert next(c for c in ALL if c.id=='edges-3-reached').occasion in prompt(wire) and s.deck().snapshot()['counts']['delivered']==1
 await s.close()
 # The service restarts; the browser's session and counters carry on.
 wire2=[];restarted,_=await connect(r,wire=wire2)
 assert restarted.deck().session_id==r.state['session_id']
 restarted.deck()._cards={};restarted.deck()._queue=[];restarted.pump()
 assert not wire2 and restarted.deck().snapshot()['activations']==[] and restarted.deck().snapshot()['counter_baseline']['edges']==3
 r.state.update(edges=7);r.step(None,seconds=5)
 restarted.pump();await restarted.task
 occasion=lambda card_id:next(c for c in ALL if c.id==card_id).occasion
 assert occasion('edges-7-reached') in prompt(wire2) and occasion('edges-3-reached') not in prompt(wire2)

async def test_a_model_switch_mid_session_does_not_replay_milestones():
 r,s,wire,frames=await service(edges=5,identity='nova')
 s.deck_observe(s.deck(),r.clock.mono())
 assert s.deck().snapshot()['counter_baseline']['edges']==5 and s.deck().snapshot()['activations']==[]

async def test_the_baseline_is_taken_while_speech_is_not_allowed():
 r,s,wire,frames=await service(edges=0)
 s.director.config=s.director.config.model_copy(update={'spontaneous_enabled':False})
 s.pump();assert not wire and s.deck().snapshot()['counter_baseline']=={'edges':0,'seconds':0}


# Off by default, and off in the live application

def test_the_library_does_not_enable_anything():
 # The on-by-default switch lives in code (DEFAULT_DECK_ENABLED), never in the card library.
 assert DeckSettings().enabled is True and 'enabled' not in RAW and not (ROOT/'deck-settings.json').exists()
