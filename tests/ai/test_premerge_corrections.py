# SPDX-License-Identifier: AGPL-3.0-only
"""Regressions for the pre-merge review of Director 2.0, one section per finding (A to H)."""
import asyncio,json,re
import pytest
from companion_ai import conversation,fidelity
from companion_ai.context_compiler import CARD_CORRECTIONS
from companion_ai.event_deck import Arrival,DeckSettings
from companion_ai.expressions import ExpressionStream,clean_dialogue
from companion_ai.fidelity import card_language_violations,corrected_closing,history_checked,history_records,history_violations,violations
from companion_ai.session_history import compare,comparison_words,plain_record,previous_session
from companion_ai.session_journal import SessionJournal
from tests.ai.test_arrival_comparison import Store,closing,earlier,idle,journal,now_ms,play,record,spoken
from tests.ai.test_event_deck_content import prompt,replies_in_turn,service
from tests.ai.test_event_deck_integration import RESULT,finish,rig,tick,turn
from tests.ai.test_session_measurements import canonical

RETURNING='Welcome back. Shall we begin, or just talk?'
GREETING='Well, here you are. Shall we begin, or just talk?'
FIRST='Hello there. This is our first session together. Shall we begin, or just talk?'


def closing_summary(prior_edges=7,prior_seconds=720,edges=10,seconds=900):
 prior={'edges':prior_edges,'seconds':prior_seconds,'experience':'classic','goal':'tease','outcome':'stopped','comparable':True}
 current={'edges':edges,'seconds':seconds,'experience':'classic','goal':'tease','outcome':'stopped'}
 return {'deck_card':{'lane':'session_end','history':{'status':'found','prior':prior,'current':current,'comparison':compare(current,prior)}}}

def wrong(line,**figures):
 return 'wrong_comparison' in card_language_violations(line,closing_summary(**figures))


# A. The session an idle observer still names is the one an Arrival is looking for

async def recorded_session(r,s,edges,seconds):
 """One session through the real observer and the real Journal, which is left IDLE holding its ID."""
 r.step(None,seconds=1,status='IDLE',reset=True)
 sid=r.state['session_id']
 r.step(None,seconds=0,status='RUNNING')
 r.state['edges']=edges
 r.step(None,seconds=seconds)
 r.step(None,seconds=1,status='IDLE')
 return sid

async def journalled(identity='daisy',reply=RETURNING):
 r,s,wire,frames=await idle(identity,reply)
 r.observation.model_scope=s.active_model_id
 r.observation.journal=SessionJournal(Store({'schema_version':1,'recording':True,'ai_access':True,'nova_cross_companion':False,'records':[]}))
 return r,s,wire,frames

async def test_arrival_sees_the_session_the_idle_observer_still_names():
 r,s,wire,frames=await journalled()
 sid=await recorded_session(r,s,4,300)
 assert r.observation.session_id==sid and r.observation.report['status']=='IDLE'
 assert [row['session_id'] for row in r.observation.journal.data['records']]==[sid]
 history=s.session_history()
 assert history['status']=='found' and history['prior']['edges']==4
 await play(s)
 assert 'first session' not in prompt(wire).lower() and 'Previous session: 4 edges' in prompt(wire)
 assert s.arrival.state=='delivered'

async def test_arrival_never_claims_a_first_session_when_the_only_record_is_the_retained_one():
 r,s,wire,frames=await journalled(reply=FIRST)
 await recorded_session(r,s,4,300)
 await play(s)
 assert spoken(frames)==[] and s.arrival.state=='suppressed' and 'first_session_claim' in s.arrival.reason

async def test_a_returning_greeting_states_the_true_interval_and_a_false_one_is_refused():
 r,s,wire,frames=await journalled(reply='Welcome back. It has been about 2 hours. Shall we begin, or just talk?')
 await recorded_session(r,s,4,300)
 r.clock.tick(7200);r.step(None,seconds=0)
 await play(s)
 assert 'about 2 hours ago' in prompt(wire) and s.arrival.state=='delivered'
 r,s,wire,frames=await journalled(reply='Welcome back. It has been about 9 days. Shall we begin, or just talk?')
 await recorded_session(r,s,4,300)
 r.clock.tick(7200);r.step(None,seconds=0)
 await play(s)
 assert spoken(frames)==[] and 'wrong_time_since' in s.arrival.reason

async def test_arrival_uses_the_newest_of_several_sessions_and_its_interval():
 r,s,wire,frames=await journalled()
 for edges in (2,3,5):
  await recorded_session(r,s,edges,300)
  r.clock.tick(3600)
 history=s.session_history()
 assert history['prior']['edges']==5 and 3000<history['since_seconds']<4200

async def test_closing_excludes_its_own_session_explicitly():
 r,s,wire,frames=await journalled()
 await recorded_session(r,s,2,120)
 newest=await recorded_session(r,s,9,900)
 assert s.session_history()['prior']['edges']==9
 assert s.session_history({newest})['prior']['edges']==2

async def test_closing_with_no_other_record_never_compares_a_session_with_itself():
 r,s,wire,frames=await journalled()
 only=await recorded_session(r,s,4,300)
 history=s.session_history({only})
 assert 'prior' not in history and history['status']=='none'

async def test_a_completed_session_the_journal_lacks_rules_out_first():
 r,s,wire,frames=await idle()
 r.observation.journal=journal()
 r.observation.completed_sessions.append({'session_id':r.observation.session_id,'model_scope':s.active_model_id})
 assert s.session_history()['status']=='incomplete'

async def test_talk_under_the_idle_id_alone_does_not_rule_out_first():
 r,s,wire,frames=await idle()
 r.observation.journal=journal()
 s.history.append({'role':'user','content':'hello','session_id':r.observation.session_id})
 assert s.session_history()['status']=='none'
 s.history.append({'role':'user','content':'older','session_id':'an-earlier-one'})
 assert s.session_history()['status']=='incomplete'

async def test_model_switch_keeps_each_models_own_history_and_reactivation_finds_it_again():
 r,s,wire,frames=await journalled()
 first=s.active_model_id
 await recorded_session(r,s,4,300)
 assert s.session_history()['prior']['edges']==4
 config=s.adapter.config
 s.adapter.config=config.model_copy(update={'model':'evelyn-narrative-v1:latest'});s.activate_model()
 assert s.active_model_id!=first and 'prior' not in s.session_history()
 s.adapter.config=config;s.activate_model()
 assert s.active_model_id==first and s.session_history()['prior']['edges']==4

async def test_a_backend_restart_reads_the_same_record():
 r,s,wire,frames=await journalled()
 await recorded_session(r,s,4,300)
 store=Store(r.observation.journal.data)
 r.observation.journal=SessionJournal(store)
 assert s.session_history()['prior']['edges']==4

async def test_journal_permission_and_exact_scope_still_rule():
 r,s,wire,frames=await journalled()
 await recorded_session(r,s,4,300)
 r.observation.journal.data['ai_access']=False
 assert s.session_history()=={'status':'denied'}
 r.observation.journal.data['ai_access']=True
 r.observation.journal.data['records'][0]['companions'].append({'model_scope':'ollama:http://x:nova:latest'})
 assert 'prior' not in s.session_history()


# B. Card checks belong to card turns

DIALOGUE=["We've been walking for two hours through the ruins.",'You have reached 9 edges already.','Twenty minutes in, the storm broke.','Your real pulse is what I am watching.']

@pytest.mark.parametrize('status',['RUNNING','IDLE'])
@pytest.mark.parametrize('line',DIALOGUE)
def test_the_new_checks_leave_a_persons_conversation_alone(line,status):
 assert violations(line,canonical(status=status))==[]

@pytest.mark.parametrize('status',['RUNNING','IDLE'])
@pytest.mark.parametrize('deck',[True,False])
@pytest.mark.parametrize('director',[True,False])
async def test_a_user_turn_is_delivered_whatever_the_flags(status,deck,director):
 line="We've been walking for two hours through the ruins."
 r,s,wire,frames=await service(reply=line,status=status,edges=3,seconds=600)
 s.director.config=s.director.config.model_copy(update={'enabled':director})
 s.deck_settings=DeckSettings(enabled=deck)
 s.request('Tell me about the ruins.',user=True);await s.task;await asyncio.sleep(0)
 assert line in spoken(frames) and not [f for f in frames if f['type']=='conversation_error']

def test_independent_safeguards_of_the_normal_pipeline_remain():
 assert 'wrong_edges' in violations('The edge count is 9.',canonical())
 assert 'wrong_running_counter' in violations('The session clock is 45 minutes.',canonical())
 assert 'unsupported_bpm' in violations('It is 219 BPM.',canonical())

def test_the_same_claim_is_still_checked_on_a_card():
 assert 'wrong_edges' in violations('You have reached 9 edges already.',canonical(),card=True)
 assert 'wrong_running_counter' in violations("You've been going for 45 minutes.",canonical(),card=True)


# C. Which session a comparative describes

# Current 10 edges and 900 s against 7 edges and 720 s; each line's truth is stated by the list it is in.
THIS_ONE_WAS_MORE=['You had more edges than last time.','This time you had more edges than last time.','More edges this time than last session.',
 'Last time you had fewer edges.','You had fewer edges last time.','Last time you had fewer edges than this time.','You had fewer edges last session.',
 'Compared to last time, you had more edges.','You had more edges compared with last time.',"You didn't have more edges last time.",'You had no more edges last session.',"You didn't have fewer edges than last time.",'Last session had fewer edges.','The last session had fewer edges than this one.']
THIS_ONE_WAS_LESS=['You had more edges last time.','You had more edges last session.','Last time you had more edges.','Last session you had more edges.','Last time, you had more edges.','You had more edges, last time.',
 'You had fewer edges than last time.','Fewer edges this time than last session.','Last time you had more edges than this time.','Compared to last time, you had fewer edges.',"You didn't have more edges than last time.","You didn't have fewer edges last time.",'Last session had more edges.','You had 3 more edges last time.']
THIS_ONE_WAS_LONGER=['You went longer than last time.','You lasted longer than last session.','You outlasted last time.','You went longer this time.','Last time you went shorter.','You went shorter last time.',
 'Last session you lasted a shorter time than this.','Compared with last time, you went longer.',"You didn't go longer last time.","Last time you didn't last longer.",'The last session ran shorter.','Your last session was shorter than this one.',"You didn't go shorter than last time."]
THIS_ONE_WAS_SHORTER=['You went longer last time.','Last time you lasted longer.','You lasted longer last session.','Last session you lasted longer.','Last time, you lasted longer.','You went shorter than last time.','You went shorter this time.',
 'Last time you lasted longer than this.','Compared with last time, you went shorter.',"You didn't last longer than last time.","You didn't go shorter last time.",'The last session ran longer.']
MORE={'edges':10,'prior_edges':7};LESS={'edges':4,'prior_edges':7};SAME_COUNT={'edges':7,'prior_edges':7}
LONG={'seconds':900,'prior_seconds':720};SHORT={'seconds':300,'prior_seconds':720};SAME_TIME={'seconds':720,'prior_seconds':720}

@pytest.mark.parametrize('line',THIS_ONE_WAS_MORE)
def test_a_claim_of_more_edges_for_this_session(line):
 assert not wrong(line,**MORE) and wrong(line,**LESS) if 'no more' not in line and "didn't" not in line else not wrong(line,**MORE)

@pytest.mark.parametrize('line',THIS_ONE_WAS_LESS)
def test_a_claim_of_fewer_edges_for_this_session(line):
 assert not wrong(line,**LESS) and wrong(line,**MORE) if "didn't" not in line else not wrong(line,**LESS)

@pytest.mark.parametrize('line',THIS_ONE_WAS_LONGER)
def test_a_claim_of_a_longer_session(line):
 assert not wrong(line,**LONG) and wrong(line,**SHORT) if "n't" not in line else not wrong(line,**LONG)

@pytest.mark.parametrize('line',THIS_ONE_WAS_SHORTER)
def test_a_claim_of_a_shorter_session(line):
 assert not wrong(line,**SHORT) and wrong(line,**LONG) if "n't" not in line else not wrong(line,**SHORT)

@pytest.mark.parametrize('line,figures',[
 ("You didn't have more edges last time.",LESS),("You didn't have more edges than last time.",MORE),
 ("You didn't have fewer edges than last time.",LESS),("You didn't have fewer edges last time.",MORE),
 ("You didn't go longer last time.",SHORT),("You didn't last longer than last time.",LONG),
 ("You didn't go shorter than last time.",SHORT),("You didn't go shorter last time.",LONG),
 ("Last time you didn't last longer.",SHORT)])
def test_a_negated_comparison_rules_out_one_direction(line,figures):
 assert wrong(line,**figures)

@pytest.mark.parametrize('line,figures',[
 ('You had more edges last time.',SAME_COUNT),('You had more edges than last time.',SAME_COUNT),('You had fewer edges last time.',SAME_COUNT),('You had fewer edges than last time.',SAME_COUNT),
 ('You went longer last time.',SAME_TIME),('Last time you lasted longer.',SAME_TIME),('You went longer than last time.',SAME_TIME),('You went shorter last time.',SAME_TIME)])
def test_an_unchanged_figure_refutes_either_direction(line,figures):
 assert wrong(line,**figures)

@pytest.mark.parametrize('line,figures',[
 ("You didn't have more edges last time.",SAME_COUNT),("You didn't have more edges than last time.",SAME_COUNT),("You didn't have fewer edges than last time.",SAME_COUNT),
 ('You had as many edges as last time.',SAME_COUNT),("You didn't go longer last time.",SAME_TIME),("You didn't last longer than last time.",SAME_TIME),('You went as long as last time.',SAME_TIME)])
def test_an_unchanged_figure_supports_what_it_should(line,figures):
 assert not wrong(line,**figures)

def test_a_difference_said_of_the_earlier_session_is_read_that_way():
 assert not wrong('You had 3 more edges last time.',edges=4,prior_edges=7)
 assert wrong('You had 3 more edges last time.',edges=10,prior_edges=7)
 assert not wrong('You had 3 more edges than last time.',edges=10,prior_edges=7)

@pytest.mark.parametrize('line',['Longer than I expected, this one.','Stay a little longer.',"Let's see if you can go longer than last time."])
def test_what_claims_no_direction_stays_free(line):
 assert not wrong(line,edges=4,prior_edges=7,seconds=300,prior_seconds=720)

def test_an_idiom_is_not_a_negated_comparison():
 assert not wrong('Not bad, more edges than last time.',**MORE)


# D. Dialogue tone is the character's own (the pressure filter is removed)

LANES=['normal','mission','session_start','narrative','arrival','session_end']
DEMANDING=['Push through the pain.','Ignore the pain.','Ignore your limits.',"Don't stop, push through the discomfort.",'Keep going past the pain.','Keep going, no matter how much it hurts.',"Don't push through the pain.",'Push your limits again.','You will do as I say, and you will enjoy it.','Harder. I did not say you could rest.']

@pytest.mark.parametrize('lane',LANES)
@pytest.mark.parametrize('line',DEMANDING)
def test_tone_is_not_refused_on_any_lane(lane,line):
 assert card_language_violations(line,{'deck_card':{'lane':lane}})==[]
 assert violations(line,canonical(),card=True)==[]

def test_the_mechanism_is_gone():
 assert not hasattr(fidelity,'pressure_violations') and not hasattr(fidelity,'PRESSURE')
 assert 'pressure' not in CARD_CORRECTIONS

async def test_a_demanding_line_is_delivered_with_no_correction():
 r,s,wire,frames=await service('celeste','You will ignore the pain and keep going for me.',edges=3,seconds=600)
 s.deck()._start_done=False
 s.pump();await s.task;await asyncio.sleep(0)
 assert spoken(frames)==['You will ignore the pain and keep going for me.'] and len([1 for p,b in wire if p=='/api/chat'])==1

@pytest.mark.parametrize('line,code',[('You have reached 9 edges already.','wrong_edges'),('I have raised the intensity for you.','read_only_control_claim'),('I just stopped the device.','read_only_control_claim'),('Your real pulse is what I am watching.','simulated_reading_presented_as_physical')])
def test_correctness_and_authority_checks_are_independent_of_tone(line,code):
 assert code in violations(line,canonical(),card=True)

def test_identity_and_history_checks_remain():
 assert 'addressed_by_own_name' in card_language_violations('Well done, Celeste.',{'deck_card':{'lane':'normal','speaker':'celeste'}})
 assert 'objective_standard' in card_language_violations('Objectively, that was poor.',closing_summary())
 assert 'body_inference' in card_language_violations('Your stamina is clearly improving.',closing_summary())


# E. The mandatory closing

async def closing_rig(texts):
 wire=[]
 r,s,wire,frames=await service('daisy',reply='unused',edges=3,seconds=600,wire=wire,transport=replies_in_turn(wire,texts))
 s.deck_settings=DeckSettings(enabled=True,countdown_seconds=0);s.deck()._start_done=True;s.deck()._counter_baseline={'edges':3,'seconds':600}
 r.observation.journal=journal()
 r.step(85,status='IDLE')
 s.enqueue('session_ended',70,{'event_id':'end','session_id':r.observation.session_id,'category':'authoritative','at_ms':now_ms(r),'session_result':RESULT,'evidence':'Session ended.'})
 return r,s,wire,frames

async def run_closing(r,s,polls=4):
 deck=s.deck()
 for _ in range(polls):
  s.pump()
  if s.task and not s.task.done():await s.task;await asyncio.sleep(0)
  r.clock.tick(5);r.step(85,status='IDLE')
  s.busy_until=0
 return deck

def drops(s):return [d['outcome'] for d in s.director.decisions if d['reason']=='deck_closing_dropped']

async def test_the_closing_is_not_offered_silence_but_other_cards_are():
 r,s,wire,frames=await closing_rig(['The session is over. A fair result.'])
 await run_closing(r,s,1)
 assert 'SILENCE' not in json.dumps([b['messages'] for p,b in wire if p=='/api/chat'])
 r2,s2,wire2,frames2=await service('daisy',reply='A clear line of thought.')
 s2.deck()._start_done=True;s2.deck_settings=DeckSettings(enabled=True,countdown_seconds=0)
 s2.pump();await s2.task
 assert 'SILENCE' in prompt(wire2)

async def test_a_silent_closing_is_retried_and_then_delivered():
 r,s,wire,frames=await closing_rig(['[SILENCE]','The session is over. A fair result.'])
 deck=await run_closing(r,s)
 assert spoken(frames)==['The session is over. A fair result.'] and deck.closing_outcome=='delivered' and drops(s)==[]

@pytest.mark.usefixtures('deck_off')
async def test_a_closing_silent_every_time_is_a_recorded_drop():
 r,s,wire,frames=await closing_rig(['[SILENCE]'])
 deck=await run_closing(r,s,6)
 assert spoken(frames)==[] and deck.closing_outcome=='suppressed' and drops(s)==['suppressed']
 assert len([1 for p,b in wire if p=='/api/chat'])==deck.settings.max_attempts
 assert any(f.get('closing_outcome')=='suppressed' for f in frames if f['type']=='ai_diagnostics')

async def test_a_transient_failure_is_retried():
 class Once:
  def __init__(self,inner):self.inner,self.done=inner,False
  async def reply(self,*args,**kwargs):
   if not self.done:
    self.done=True;raise ValueError('inference down')
   return await self.inner(*args,**kwargs)
 r,s,wire,frames=await closing_rig(['The session is over. A fair result.'])
 real=s.adapter.reply;s.adapter.reply=Once(real).reply
 deck=await run_closing(r,s)
 assert spoken(frames)==['The session is over. A fair result.'] and deck.closing_outcome=='delivered' and drops(s)==[]

async def test_repeated_wording_does_not_lose_the_closing():
 line='The session is over and it went about as well as these things ever go.'
 r,s,wire,frames=await closing_rig([line])
 s.director.memory['responses'].append({'text':line,'at':0})
 deck=await run_closing(r,s)
 assert spoken(frames)==[line] and deck.closing_outcome=='delivered'
 assert any(d['reason']=='closing_repetition_kept' for d in s.director.decisions)

@pytest.mark.parametrize('block',['quiet','mute','protective'])
async def test_authoritative_conditions_are_still_not_overridden(block):
 r,s,wire,frames=await closing_rig(['The session is over. A fair result.'])
 deck=s.deck()
 if block=='quiet':s.director.memory['quiet_requested']=True
 if block=='mute':s.policy=s.policy.model_copy(update={'enabled':False})
 if block=='protective':r.state['safety']['watchdog_paused']=True;r.step(85,status='IDLE')
 s.pump();r.clock.tick(deck.settings.closing_ttl_seconds+1)
 if block=='protective':r.step(85,status='IDLE')
 s.pump()
 assert spoken(frames)==[] and not [1 for p,b in wire if p=='/api/chat'] and deck.closing_outcome=='expired' and drops(s)==['expired']

async def test_a_user_turn_still_wins_and_the_closing_waits():
 r,s,wire,frames=await closing_rig(['A reply to you.','The session is over. A fair result.'])
 deck=s.deck()
 s.request('One question.',user=True);await s.task;await asyncio.sleep(0)
 assert deck.closing_pending and spoken(frames)==['A reply to you.'] and drops(s)==[]

async def test_interruptions_are_bounded_and_recorded():
 r,s,wire,frames=await closing_rig(['The session is over. A fair result.'])
 deck=s.deck()
 for _ in range(deck.settings.max_interruptions):
  s.pump();s.interrupt();await asyncio.gather(*s.tasks,return_exceptions=True);await asyncio.sleep(0)
  r.clock.tick(5);r.step(85,status='IDLE')
 assert deck.closing_outcome=='interruptions_exhausted' and drops(s)==['interruptions_exhausted']

async def test_a_new_session_ends_a_waiting_closing_on_the_record():
 r,s,wire,frames=await closing_rig(['The session is over. A fair result.'])
 deck=s.deck();s.director.memory['quiet_requested']=True;s.pump()
 r.step(85,seconds=0,status='RUNNING',reset=True);s.deck()
 assert deck.closing_outcome=='superseded' and drops(s)==['superseded']

async def test_a_service_stopping_records_the_drop_once():
 r,s,wire,frames=await closing_rig(['The session is over. A fair result.'])
 s.director.memory['quiet_requested']=True;s.pump();deck=s.deck()
 await s.close()
 assert deck.closing_outcome=='service_closed' and drops(s)==['service_closed']

async def test_delivery_is_not_recorded_as_a_drop():
 r,s,wire,frames=await closing_rig(['The session is over. A fair result.'])
 deck=await run_closing(r,s,1)
 assert deck.closing_outcome=='delivered' and drops(s)==[]

def closing_check(summary):
 def check(text):return history_checked(violations(text,canonical(edges=0,seconds=0,status='IDLE'),(),{'session_result':{'edges':summary['deck_card']['history']['current']['edges'],'active_running_seconds':summary['deck_card']['history']['current']['seconds']}},history_records(summary,()),card=True)+card_language_violations(text,summary),summary)
 return check

FIGURES=[(7,720,10,900),(7,720,4,300),(7,720,7,720),(7,720,7,420),(7,720,7,781),(1,61,2,122),(2,600,1,601),(7,None,10,None),(None,720,None,900),(1,45,1,46)]

@pytest.mark.parametrize('pe,ps,e,sec',FIGURES)
@pytest.mark.parametrize('drafts',[('You had more edges last time, and you ran longer. Well done.','It ran longer. Fine.'),('A strange night. You ran 99 minutes and had 40 edges. Sleep well.',),('Everything here is wrong: 40 edges.',),('Rest now. It was enough.',),('[SILENCE] Rest now.',)])
def test_correcting_a_closing_cannot_create_a_new_violation(pe,ps,e,sec,drafts):
 summary=closing_summary(pe,ps,e,sec);check=closing_check(summary)
 corrected=corrected_closing(drafts,summary,check)
 assert corrected and check(corrected)==[] and '[SILENCE]' not in corrected and plain_record(summary['deck_card']['history']) in corrected

def test_the_plain_record_compares_only_what_both_sessions_have():
 history={'current':{'edges':3,'seconds':None},'prior':{'edges':None,'seconds':540},'comparison':{'outcome':{'current':'stopped','prior':'stopped'}}}
 assert plain_record(history)=='3 edges this time.'
 history={'current':{'edges':3,'seconds':60},'prior':{'edges':5,'seconds':None},'comparison':{'edges':{'direction':'decrease','difference':2}}}
 assert plain_record(history)=='3 edges in 1 minute this time, against 5 edges last time.'


# F. The deterministic wording

@pytest.mark.parametrize('figures,words',[
 ((7,720,7,420),'This session had the same number of edges and ran 5 minutes shorter than the last one.'),
 ((7,720,7,720),'This session had the same number of edges and ran the same length as the last one.'),
 ((7,720,9,720),'This session had 2 more edges and ran the same length as the last one.'),
 ((7,720,6,781),'This session had 1 fewer edge and ran 1 minute 1 second longer than the last one.'),
 ((7,720,8,719),'This session had 1 more edge and ran 1 second shorter than the last one.'),
 ((7,None,7,None),'This session had the same number of edges as the last one.'),
 ((7,None,9,None),'This session had 2 more edges than the last one.'),
 ((None,720,None,720),'This session ran the same length as the last one.'),
 ((None,720,None,900),'This session ran 3 minutes longer than the last one.')])
def test_the_comparison_sentence_is_grammatical_and_passes_its_own_checks(figures,words):
 summary=closing_summary(*figures)
 assert comparison_words(summary['deck_card']['history'])==words
 assert closing_check(summary)(words)==[]

@pytest.mark.parametrize('edges',[0,1,2,7,8,12])
@pytest.mark.parametrize('seconds',[1,59,60,61,121,420,719,720,721,781,3600,3661])
def test_every_generated_sentence_passes_for_every_combination(edges,seconds):
 summary=closing_summary(7,720,edges,seconds);history=summary['deck_card']['history'];check=closing_check(summary)
 assert check(comparison_words(history))==[] and check(plain_record(history))==[]
 assert not re.search(r'same length than|\b1 (?:seconds|minutes|edges)\b',comparison_words(history)+plain_record(history))

def test_the_same_length_is_a_claim_like_any_other():
 assert wrong('This session ran the same length as the last one.',**SHORT)
 assert wrong('This session had the same number of edges as the last one.',**MORE)
 assert not wrong('A rope of the same length.',**SHORT)


# G. A character's own time

ANECDOTES=['I spent two hours in the greenhouse this week.',"Give me five minutes and I'll be ready.",'Give me five minutes longer.',"We've been walking for two hours through the ruins.",
 'I once waited forty minutes for a kettle.','She kept me talking for three hours.','It took my team eleven hours to map the cave.','I sharpened three edges on my blade.','I was in the greenhouse last night.']

@pytest.mark.parametrize('lane',['session_end','arrival'])
@pytest.mark.parametrize('line',ANECDOTES)
def test_a_characters_own_time_is_not_session_history(line,lane):
 summary=closing_summary();summary['deck_card']['lane']=lane
 assert history_violations(line,summary)==[]

@pytest.mark.parametrize('line',['You lasted thirteen minutes last time.','The last session ran thirteen minutes.','This session lasted thirteen minutes.','That last run took thirteen minutes.','You managed thirteen minutes.','Your thirteen minutes were enough.','Thirteen minutes.','A mere thirteen minutes.',"You've been going for thirteen minutes.",'Thirteen minutes of running time.'])
def test_a_figure_about_the_session_is_still_checked(line):
 assert 'unsupported_history_figure' in history_violations(line,closing_summary())

@pytest.mark.parametrize('line',['You had thirteen minutes more than last time.','This session ran thirteen minutes longer than the last one.'])
def test_a_wrong_difference_is_still_refused(line):
 assert history_violations(line,closing_summary())

def test_a_figure_about_the_session_may_be_right():
 assert history_violations('This session lasted fifteen minutes.',closing_summary())==[]
 assert history_violations('You managed twelve minutes last time.',closing_summary())==[]

def test_the_general_measurement_check_leaves_other_activities_alone_on_a_card():
 assert 'wrong_running_counter' not in violations("We've been walking for two hours through the ruins.",canonical(),card=True)
 assert 'wrong_running_counter' in violations("We've been going for two hours.",canonical(),card=True)


# H. The last check before an Arrival is published

def holding(s,change):
 """A reply that lets the state change while the greeting is being generated."""
 original=s.adapter.reply
 async def reply(*args,**kwargs):
  result=await original(*args,**kwargs);change();return result
 s.adapter.reply=reply

@pytest.mark.parametrize('change',['quiet','mute','events_off','proactive_off','director_off','stale','watchdog','no_contact','signal_lost','session','user_spoke','scope','stopped','closed','deck_off'])
async def test_a_greeting_overtaken_during_generation_is_not_published(change):
 r,s,wire,frames=await idle(reply=GREETING)
 def apply():
  if change=='quiet':s.director.memory['quiet_requested']=True
  if change=='mute':s.policy=s.policy.model_copy(update={'enabled':False})
  if change=='events_off':s.policy=s.policy.model_copy(update={'event_responses':False})
  if change=='proactive_off':s.director.config=s.director.config.model_copy(update={'spontaneous_enabled':False})
  if change=='director_off':s.director.config=s.director.config.model_copy(update={'enabled':False})
  if change=='stale':r.observation.fresh=lambda:False
  if change=='watchdog':r.observation.report['safety']['watchdog_paused']=True
  if change=='no_contact':r.observation.report['safety']['no_contact']=True
  if change=='signal_lost':r.observation.report['safety']['fault']='signal_lost'
  if change=='session':r.observation.report['status']='RUNNING'
  if change=='user_spoke':s.last_user=r.clock.mono()+1
  if change=='scope':s.adapter.config=s.adapter.config.model_copy(update={'model':'evelyn-narrative-v1:latest'})
  if change=='stopped':s.adapter.mode='stopped'
  if change=='closed':s.closed=True
  if change=='deck_off':s.deck_settings=DeckSettings(enabled=False)
 holding(s,apply)
 s.pump();arrival=s.arrival
 await s.task;await asyncio.sleep(0)
 assert spoken(frames)==[] and arrival.state=='cancelled'
 assert s.arrival_delivered=={}
 assert any(d['reason']=='arrival_cancelled' and d.get('detail')=='stale_at_delivery' for d in s.director.decisions)
 assert any(f['type']=='response_suppressed' for f in frames)

async def test_an_undisturbed_greeting_is_published():
 r,s,wire,frames=await idle(reply=GREETING)
 await play(s)
 assert spoken(frames)==[GREETING] and s.arrival.state=='delivered'


# Second review, 1: every comparative in a sentence is its own claim

LONGER_FEWER={'edges':4,'prior_edges':7,'seconds':900,'prior_seconds':720}
LONGER_MORE={'edges':10,'prior_edges':7,'seconds':900,'prior_seconds':720}
SHORTER_FEWER={'edges':4,'prior_edges':7,'seconds':300,'prior_seconds':720}
SHORTER_MORE={'edges':10,'prior_edges':7,'seconds':300,'prior_seconds':720}

@pytest.mark.parametrize('line,true_of,false_of',[
 ('This session ran longer than the last one and had fewer edges.',LONGER_FEWER,[LONGER_MORE,SHORTER_FEWER,SHORTER_MORE]),
 ('This session ran longer than the last one, and had fewer edges.',LONGER_FEWER,[LONGER_MORE,SHORTER_FEWER]),
 ('This session ran longer than the last one, but had fewer edges.',LONGER_FEWER,[LONGER_MORE,SHORTER_FEWER]),
 ('You had fewer edges and ran longer than last time.',LONGER_FEWER,[LONGER_MORE,SHORTER_FEWER]),
 ('You had fewer edges, but ran longer than last time.',LONGER_FEWER,[LONGER_MORE,SHORTER_FEWER]),
 ('You had more edges last time and ran shorter.',LONGER_FEWER,[SHORTER_FEWER,LONGER_MORE]),
 ('Last time you had more edges, but ran shorter.',LONGER_FEWER,[SHORTER_FEWER,LONGER_MORE]),
 ('The last one had more edges than this session and ran shorter.',LONGER_FEWER,[SHORTER_FEWER,LONGER_MORE]),
 ('You had more edges last time and went longer this time.',LONGER_FEWER,[SHORTER_FEWER,LONGER_MORE]),
 ('You went longer this time and had more edges last time.',LONGER_FEWER,[SHORTER_FEWER,LONGER_MORE]),
 ('This session ran shorter than the last one and had more edges.',SHORTER_MORE,[SHORTER_FEWER,LONGER_MORE]),
 ('This session had 3 more edges and ran 5 minutes longer than the last one.',{'edges':10,'prior_edges':7,'seconds':1020,'prior_seconds':720},[{'edges':4,'prior_edges':7,'seconds':1020,'prior_seconds':720},{'edges':10,'prior_edges':7,'seconds':420,'prior_seconds':720}]),
])
def test_each_comparative_is_checked_on_its_own(line,true_of,false_of):
 assert not wrong(line,**true_of)
 for figures in false_of:assert wrong(line,**figures),figures

@pytest.mark.parametrize('line,true_of,false_of',[
 ("This session ran longer than the last one and didn't have more edges.",LONGER_FEWER,[SHORTER_FEWER,LONGER_MORE]),
 ("You didn't have more edges and ran longer than last time.",LONGER_FEWER,[SHORTER_FEWER,LONGER_MORE]),
 ("This session wasn't longer than the last one and had more edges.",SHORTER_MORE,[LONGER_MORE,SHORTER_FEWER]),
 ('This session ran neither longer nor had more edges than the last one.',SHORTER_FEWER,[LONGER_FEWER,SHORTER_MORE]),
 ('You had as many edges as last time and ran longer.',{'edges':7,'prior_edges':7,'seconds':900,'prior_seconds':720},[LONGER_FEWER,{'edges':7,'prior_edges':7,'seconds':300,'prior_seconds':720}]),
])
def test_a_negation_or_match_belongs_to_its_own_comparative(line,true_of,false_of):
 assert not wrong(line,**true_of)
 for figures in false_of:assert wrong(line,**figures),figures

@pytest.mark.parametrize('line',['Last time you ran longer, but you had fewer edges.','You ran shorter than last time, but stay a little longer.',"This session ran shorter than the last one, and let's see if you can go longer."])
def test_ambiguous_or_forward_looking_parts_claim_nothing(line):
 assert not wrong(line,**SHORTER_MORE)


# Second review, 2: time said to have been spent in the session

SPENT=['You spent ninety minutes with me.','You spent 90 minutes with me.','You spent ninety minutes.',"You've spent an hour with me.",'We spent ninety minutes together.',"We've spent 90 minutes here.",'I spent ninety minutes with you.',"I've had you for ninety minutes.",'I kept you for an hour and a half.','Ninety minutes with me.','You spent about ninety minutes edging.','You spent ninety minutes in this session.']
NOT_SPENT=['You spent fifteen minutes with me.','You spent 15 minutes with me.','We spent about fifteen minutes together.',"I've had you for fifteen minutes."]
ELSEWHERE=['You spent ninety minutes in the greenhouse.','We spent ninety minutes together in the ruins.','You spent two hours with me in the library in that story.','I spent ninety minutes with the archivist.','She spent ninety minutes with me.','Spend ninety minutes with me sometime.','You could spend ninety minutes with me.','You spent two hours with me yesterday.','Ninety minutes with a good book.','I have had a headache for ninety minutes.','Give me ninety minutes.']

def running():return canonical(edges=3,seconds=900,status='RUNNING')

@pytest.mark.parametrize('line',SPENT)
def test_a_false_time_together_is_refused_while_running(line):
 assert 'wrong_running_counter' in violations(line,running(),card=True)

@pytest.mark.parametrize('line',SPENT)
def test_a_false_time_together_is_refused_on_a_closing(line):
 assert 'unsupported_history_figure' in history_violations(line,closing_summary(seconds=900))

@pytest.mark.parametrize('line',SPENT)
def test_a_false_time_together_is_refused_on_an_arrival(line):
 summary=closing_summary();summary['deck_card']['lane']='arrival'
 assert 'unsupported_history_figure' in history_violations(line,summary)

@pytest.mark.parametrize('line',NOT_SPENT)
def test_the_true_time_together_passes(line):
 assert 'wrong_running_counter' not in violations(line,running(),card=True)
 assert 'unsupported_history_figure' not in history_violations(line,closing_summary(seconds=900))

@pytest.mark.parametrize('line',ELSEWHERE)
def test_stories_and_other_time_are_left_alone(line):
 assert 'wrong_running_counter' not in violations(line,running(),card=True)
 assert 'unsupported_history_figure' not in history_violations(line,closing_summary(seconds=900))

def test_time_together_stays_a_card_check():
 assert violations('You spent ninety minutes with me.',running())==[]


# Second review, 3: what an Arrival prompt can see, through production composition

async def arrival_after_a_session(state):
 wire=[]
 replies=['You logged 77 edges in 72 minutes.','The old lighthouse stood dark above the rocks.','Well, here you are. Shall we begin, or just talk?']
 r,s,wire,frames=await service('daisy',status='IDLE',wire=wire,transport=replies_in_turn(wire,replies))
 r.observation.model_scope=s.active_model_id
 r.observation.journal=SessionJournal(Store({'schema_version':1,'recording':True,'ai_access':True,'nova_cross_companion':False,'records':[]}))
 r.step(None,seconds=1,status='IDLE',reset=True)
 r.step(None,seconds=0,status='RUNNING');r.state['edges']=77;r.step(None,seconds=4320)
 s.request('I reached 77 edges after 72 minutes.',user=True);await s.task;await asyncio.sleep(0)
 s.request('Tell me a story about the old lighthouse.',user=True);await s.task;await asyncio.sleep(0)
 r.step(None,seconds=1,status='IDLE');r.clock.tick(60);r.step(None,seconds=0)
 journal_now=r.observation.journal
 if state=='denied':journal_now.data['ai_access']=False
 if state=='unavailable':r.observation.journal=None
 if state=='incomplete':journal_now.data.update(records=[],recording=False)
 if state=='none':
  journal_now.data.update(records=[],closed_sessions=[]);r.observation.completed_sessions.clear()
  for message in s.history:message['session_id']=r.observation.session_id
 s.deck_settings=DeckSettings(enabled=True,countdown_seconds=0,arrival_settle_seconds=0)
 s.arrival=Arrival(s.active_model_id,r.clock.mono(),s.deck_settings);s.last_user=-1e9;s.director.memory['last_user']=-1e9;s.busy_until=0
 r.clock.tick(100);r.step(None,seconds=0)
 stored=[dict(m) for m in s.history]
 s.pump();await s.task;await asyncio.sleep(0)
 return r,s,wire,stored

STATES=['found','none','denied','unavailable','incomplete']

def arrival_messages(wire):
 return next(b for p,b in wire[::-1] if p=='/api/chat' and 'MOMENT TO SPEAK' in b['messages'][-1]['content'])['messages']

@pytest.mark.parametrize('state',STATES)
async def test_an_arrival_prompt_holds_no_transcript_in_any_state(state):
 r,s,wire,stored=await arrival_after_a_session(state)
 assert s.session_history()['status']==state
 messages=arrival_messages(wire)
 assert [m['role'] for m in messages]==['system','assistant','user']
 assert 'Story details' in messages[1]['content'] and 'lighthouse' not in messages[-1]['content']
 text=json.dumps(messages)
 assert 'I reached' not in text and 'You logged' not in text and '72 minutes' not in text

@pytest.mark.parametrize('state',['none','denied','unavailable','incomplete'])
async def test_unauthorized_figures_reach_no_part_of_the_prompt(state):
 r,s,wire,stored=await arrival_after_a_session(state)
 assert not re.search(r'\b77\b|\b72\b|4320|\bedges\b.*\d',json.dumps(arrival_messages(wire)))

async def test_authorized_figures_arrive_only_as_dealt():
 r,s,wire,stored=await arrival_after_a_session('found')
 text=arrival_messages(wire)[-1]['content']
 assert 'Previous session: 77 edges' in text and 'logged' not in text and 'I reached' not in text

@pytest.mark.parametrize('state',STATES)
async def test_story_memory_and_stored_conversation_are_preserved(state):
 r,s,wire,stored=await arrival_after_a_session(state)
 assert 'lighthouse' in arrival_messages(wire)[-2]['content']
 assert [m['content'] for m in s.history][:4]==[m['content'] for m in stored][:4] and 'I reached 77' in s.history[0]['content']
 assert not any('Story details from your conversation' in m['content'] for m in s.history)

async def test_a_user_turn_keeps_its_ordinary_memory():
 r,s,wire,stored=await arrival_after_a_session('found')
 s.request('What was that place again?',user=True);await s.task
 assert 'lighthouse' in json.dumps(arrival_messages_user(wire))

def arrival_messages_user(wire):return [b for p,b in wire if p=='/api/chat'][-1]['messages']

async def test_another_model_sees_nothing_of_it():
 r,s,wire,stored=await arrival_after_a_session('found')
 s.adapter.config=s.adapter.config.model_copy(update={'model':'evelyn-narrative-v1:latest'});s.activate_model()
 assert 'prior' not in s.session_history() and not list(s.history)

async def test_a_closing_still_sees_its_own_sessions_conversation():
 wire=[]
 r,s,wire,frames=await service('daisy',edges=3,seconds=600,wire=wire,transport=replies_in_turn(wire,['A reply about the lighthouse.','The session is over. A fair result.']))
 s.deck()._start_done=True;s.deck()._counter_baseline={'edges':3,'seconds':600}
 s.request('Tell me about the lighthouse.',user=True);await s.task;await asyncio.sleep(0)
 s.last_user=-1e9;s.busy_until=0;s.director.memory['last_user']=-1e9;r.observation.journal=journal()
 r.clock.tick(40);r.step(85,status='IDLE')
 s.enqueue('session_ended',70,{'event_id':'end','session_id':r.observation.session_id,'category':'authoritative','at_ms':now_ms(r),'session_result':RESULT,'evidence':'Session ended.'})
 s.pump();await s.task
 assert 'Tell me about the lighthouse.' in json.dumps(arrival_messages_user(wire))


# Second review, 4: ordinary brackets stay

def stream(chunks,**kw):
 parser=ExpressionStream(**kw)
 return (''.join(parser.feed(c) for c in chunks)+parser.finish()),parser

ORDINARY=['He looked [proud] of it.','She was [happy] then.','[sighs] Not again.','A note [[proud]] in the margin.','It read [expression] plainly.','The sign said [neutral: yes it did] once.']

@pytest.mark.parametrize('split',[lambda t:[t],list],ids=['whole','per-character'])
@pytest.mark.parametrize('line',ORDINARY)
def test_ordinary_brackets_stay_on_a_card_turn(line,split):
 assert stream(split(line),card=True)[0]==line

@pytest.mark.parametrize('line',['He looked [proud] of it.','[proud] of it, he was.','[[happy]] Hello.','A note [[proud]] here.','[happy:Daisy-is-prose] Hello.'])
def test_outside_card_turns_a_bracket_is_only_a_bracket(line):
 expected=line if '[[' not in line or ':' not in line else None
 assert stream([line])[0]==expected
 assert clean_dialogue(line)==line

@pytest.mark.parametrize('expression',['proud','happy'])
def test_the_canonical_header_is_handled_everywhere(expression):
 for kw in ({},{'card':True}):
  text,parser=stream([f'[[expression:{expression}]] He looked [proud] of it.'],**kw)
  assert text.strip()=='He looked [proud] of it.' and parser.expression==expression

@pytest.mark.parametrize('tag,expression',[('[happy]',None),('[[happy]]','happy'),('[happy:Daisy]',None),('[expression:happy]',None)])
def test_a_malformed_leading_header_goes_on_a_card_turn(tag,expression):
 text,parser=stream([tag+' Hello.'],card=True)
 assert text.strip()=='Hello.' and parser.expression==expression

@pytest.mark.parametrize('director',[True,False])
async def test_a_user_turn_keeps_brackets_through_the_real_path(director):
 line='He looked [proud] of it.'
 r,s,wire,frames=await service(reply=line)
 s.director.config=s.director.config.model_copy(update={'enabled':director})
 s.deck_settings=DeckSettings(enabled=False)
 s.request('How did he look?',user=True);await s.task;await asyncio.sleep(0)
 assert spoken(frames)==[line]

async def test_a_card_turn_keeps_brackets_through_the_real_path():
 line='He looked [proud] of it.'
 r,s,wire,frames=await service('daisy',reply='[happy] '+line,edges=3,seconds=600)
 s.pump();await s.task;await asyncio.sleep(0)
 assert spoken(frames)==[line]


# Second review, 6: the seams a mistake would hide behind

def spying(monkeypatch):
 seen=[];real=conversation.violations
 def spy(*args,**kwargs):
  seen.append(kwargs.get('card',False));return real(*args,**kwargs)
 monkeypatch.setattr(conversation,'violations',spy)
 return seen

@pytest.mark.parametrize('deck',[True,False])
async def test_a_user_turn_never_runs_the_card_checks(monkeypatch,deck):
 seen=spying(monkeypatch);line='You have reached 9 edges already.'
 r,s,wire,frames=await service(reply=line,edges=3,seconds=600)
 s.deck_settings=DeckSettings(enabled=deck)
 s.request('How is it going?',user=True);await s.task;await asyncio.sleep(0)
 assert seen==[False] and spoken(frames)==[line]

async def test_a_legacy_reaction_never_runs_the_card_checks(monkeypatch):
 seen=spying(monkeypatch);line='You have reached 9 edges already.'
 r,s,wire,frames=await service(reply=line,edges=3,seconds=600)
 s.deck_settings=DeckSettings(enabled=False)
 s.request('Observed application event (not a user request): {}',event={'kind':'edge','priority':50,'at':r.clock.mono(),'event_id':'e1','session_id':r.state['session_id']});await s.task;await asyncio.sleep(0)
 assert seen==[False] and spoken(frames)==[line]

async def test_a_card_turn_does_run_them(monkeypatch):
 seen=spying(monkeypatch)
 r,s,wire,frames=await service(reply='You have reached 9 edges already.',edges=3,seconds=600)
 s.pump();await s.task;await asyncio.sleep(0)
 assert seen and all(seen) and spoken(frames)==[]

@pytest.mark.parametrize('change',['quiet','session','stale','watchdog','scope'])
async def test_the_final_check_catches_what_changes_during_regeneration(change):
 """After the first freshness check has passed, only the check just before publishing can stop it."""
 r,s,wire,frames=await idle(reply=GREETING)
 s.director.config=s.director.config.model_copy(update={'regenerate_once':True})
 calls=[]
 async def reply(*args,**kwargs):
  calls.append(1)
  if len(calls)==1:return 'Good morning. Shall we begin?'
  if len(calls)==2:
   if change=='quiet':s.director.memory['quiet_requested']=True
   if change=='session':r.observation.report['status']='RUNNING'
   if change=='stale':r.observation.fresh=lambda:False
   if change=='watchdog':r.observation.report['safety']['watchdog_paused']=True
   if change=='scope':s.adapter.config=s.adapter.config.model_copy(update={'model':'evelyn-narrative-v1:latest'})
  return 'A different line entirely, for you to hear.'
 s.adapter.reply=reply
 s.pump();arrival=s.arrival
 await s.task;await asyncio.sleep(0)
 assert len(calls)==2 and spoken(frames)==[] and arrival.state=='cancelled' and s.arrival_delivered=={}
 assert any(d['reason']=='arrival_cancelled' and d.get('detail')=='stale_at_delivery' for d in s.director.decisions)

@pytest.mark.parametrize('deck',[True,False])
async def test_a_user_turn_never_runs_the_card_tag_removal(deck):
 line='[proud] of it, he was.'
 r,s,wire,frames=await service(reply=line,edges=3,seconds=600)
 s.deck_settings=DeckSettings(enabled=deck)
 s.request('How did he look?',user=True);await s.task;await asyncio.sleep(0)
 assert spoken(frames)==[line]


# Dialogue accuracy: the Director works it out, and the card says so plainly

def card_prompt(wire):return arrival_messages(wire)[-1]['content']

async def arrival_with(**values):
 r,s,wire,frames=await idle()
 r.observation.journal=journal([record(s.active_model_id,now_ms=now_ms(r),**values)])
 await play(s)
 return card_prompt(wire)

async def test_elapsed_time_and_session_length_are_separate_facts():
 text=await arrival_with(edges=4,seconds=230,ago_days=2/24)
 assert 'Last recorded session: ended about 2 hours ago. That is how long ago it ended, not how long it ran or when you last spoke.' in text and 'only contact' not in text
 assert 'Previous session: 4 edges in 3 minutes 50 seconds.' in text and 'Occasion: Returning participant.' in text

async def test_an_unknown_length_is_stated_and_nothing_stands_in_for_it():
 text=await arrival_with(edges=4,seconds=None,ago_days=2/24,completeness='final_duration_unavailable')
 assert 'Previous session: 4 edges. Its length is not known, so say nothing about how long it ran.' in text
 assert 'not how long it ran' in text and 'minutes' not in text.split('Task:')[0]

@pytest.mark.parametrize('line',['Four edges in two hours?','Four edges in just two hours; a brisk pace.','Four hours of pure teasing, and I am still wondering.','Two hours of edging, and you stopped.'])
def test_the_time_since_is_not_the_length_of_the_session(line):
 summary={'deck_card':{'lane':'arrival','history':{'status':'found','since_seconds':7200,'prior':{'edges':4,'seconds':None,'outcome':'stopped','comparable':True}}}}
 assert 'unsupported_history_figure' in card_language_violations(line,summary)

@pytest.mark.parametrize('line',['It has been two hours since you stopped.','Two hours have passed, and four edges is what you left me.','Two hours of silence from you.','Four edges, and I have waited two hours to say so.'])
def test_saying_how_long_ago_is_still_fine(line):
 summary={'deck_card':{'lane':'arrival','history':{'status':'found','since_seconds':7200,'prior':{'edges':4,'seconds':None,'outcome':'stopped','comparable':True}}}}
 assert card_language_violations(line,summary)==[]

@pytest.mark.parametrize('card_id,edges,words',[('edges-3-reached',3,'Three-edge milestone'),('edges-7-reached',7,'Seven-edge milestone'),('edges-10-reached',10,'Ten-edge milestone')])
async def test_a_milestone_arrives_finished(card_id,edges,words):
 from tests.ai.test_mission_completion import MISSIONS,only_mission
 done=next(d for c,e,d in MISSIONS if c==card_id)
 r,s,wire,frames=await service(edges=edges);only_mission(s,done)
 s.pump();await s.task
 text=[b for p,b in wire if p=='/api/chat'][-1]['messages'][-1]['content']
 assert words in text and f'Verified result: the participant has reached {edges} edges in this session.' in text
 assert 'Session status: still running.' in text and not re.search(r'\b(?:first|second|third|final) milestone\b',text)

@pytest.mark.parametrize('line',['Three edges down, and you are still going.','You have reached three edges.','Your third edge, and the objective is done.','Since your first edge, you have kept going.','I knew you could handle the pressure once the first edge got under your skin.'])
def test_a_milestone_can_still_be_celebrated(line):
 assert 'wrong_edges' not in card_language_violations(line,{'deck_card':{'lane':'mission'},'canonical_session':canonical(edges=3)})

async def test_a_closing_arrives_with_its_comparison_finished():
 r,s,wire,frames=await closing(RESULT|{'edges':10,'active_running_seconds':900},[earlier()])
 text=[b for p,b in wire if p=='/api/chat'][-1]['messages'][-1]['content']
 for line in ('Occasion: The session has ended.','- This session: 10 edges in 15 minutes.','- Previous session: 7 edges in 12 minutes.','- Verified difference: This session had 3 more edges and ran 3 minutes longer than the last one.','The participant stopped the session; no finish was reported.'):
  assert line in text
 assert 'Classic Tease' not in text and 'Goal' not in text

async def test_an_unknown_length_leaves_only_the_edges_to_compare():
 r,s,wire,frames=await closing(RESULT|{'edges':9,'active_running_seconds':530},[earlier(edges=4,seconds=None,completeness='final_duration_unavailable')])
 text=[b for p,b in wire if p=='/api/chat'][-1]['messages'][-1]['content']
 assert 'had 5 more edges' in text and 'How the lengths of the two sessions compare is not known.' in text and 'longer' not in text.split('Verified difference')[1].split('\n')[0]

TRUE=closing_summary(edges=10,seconds=900)
@pytest.mark.parametrize('line,figures',[("It ran three minutes longer than the last time we met, surpassing the previous count by exactly three edges.",{}),('Ten edges and fifteen minutes, a run that outpaced the last by three minutes and three edges.',{}),('It felt a bit shorter than the last one, which had seven edges and twelve minutes.',dict(edges=4,seconds=300)),('This session had 3 fewer edges and ran 3 minutes longer than the last one.',dict(edges=4,seconds=900))])
async def test_true_comparisons_survive_the_real_path(line,figures):
 f={'edges':10,'seconds':900}|figures
 r,s,wire,frames=await closing(RESULT|{'edges':f['edges'],'active_running_seconds':f['seconds']},[earlier()],reply='[[expression:neutral]]'+line)
 assert spoken(frames)==[line] and not s.adapter.grounding_corrections

@pytest.mark.parametrize('line,figures,code',[
 ("You bested the last session's tally by a single edge.",dict(edges=9,seconds=900),'wrong_comparison'),
 ('I wonder if that extra minute was worth it.',dict(edges=10,seconds=900),'wrong_comparison'),
 ('This session outpaced the last by a mere second.',dict(edges=10,seconds=900),'wrong_comparison'),
 ('That last session ran five minutes longer than this one.',dict(edges=9,seconds=530,prior_edges=4,prior_seconds=230),'wrong_comparison'),
 ("Before the next one drags on like yesterday's session.",dict(edges=4,seconds=300),'wrong_time_since'),
 ('You stopped it, claiming a finish.',dict(edges=4,seconds=900),'unsupported_completion'),
 ('You claimed a finish I never saw.',dict(edges=4,seconds=900),'unsupported_completion'),
])
def test_reported_false_claims_are_caught(line,figures,code):
 assert code in card_language_violations(line,closing_summary(**figures))

@pytest.mark.parametrize('line,figures',[
 ('You beat the last session by a single edge.',dict(edges=8,seconds=900)),
 ('I will take that extra minute.',dict(edges=10,seconds=780)),
 ('Give me an extra minute next time.',dict(edges=10,seconds=900)),
 ("You claimed no finish, and I noticed.",dict(edges=4,seconds=900)),
 ('It felt like you held out by a whisker.',dict(edges=10,seconds=900)),
 ('That last session ran five minutes longer than the one before.',dict(edges=9,seconds=530,prior_edges=4,prior_seconds=230)),
 ('I fixed the fence yesterday.',dict(edges=4,seconds=300)),
])
def test_their_true_or_fictional_neighbours_are_not(line,figures):
 assert card_language_violations(line,closing_summary(**figures))==[]

async def opening_prompt(identity,journal_value,reply='A new start in my own words.'):
 r,s,wire,frames=await service(identity,reply,edges=0,seconds=0)
 rows=journal_value(s.active_model_id,now_ms(r)) if callable(journal_value) else journal_value
 r.observation.journal=rows;r.observation.model_scope=s.active_model_id
 s.pump();await s.task;await asyncio.sleep(0)
 return [b for p,b in wire if p=='/api/chat'][-1]['messages'],s,frames

SEEDED=lambda access:(lambda scope,now:journal([record(scope,now_ms=now,edges=77,seconds=4320)],ai_access=access))
@pytest.mark.parametrize('kind,words,absent',[
 (SEEDED(True),'you have had sessions together before','first session'),
 (lambda scope,now:journal(),'this is your first session together','sessions together before'),
 (SEEDED(False),'Relationship: unknown to you','first session'),
 (None,'Relationship: unknown to you','first session'),
 (lambda scope,now:journal(recording=False),'Relationship: unknown to you','first session'),
])
async def test_an_opening_is_told_the_relationship_and_no_record(kind,words,absent):
 messages,s,frames=await opening_prompt('nova',kind)
 text=messages[-1]['content']
 assert words in text and absent not in text and not re.search(r'\b77\b|\b72\b|4320',json.dumps(messages))
 assert 'Occasion: A session is starting now.' in text and spoken(frames)

async def test_only_a_first_session_invites_an_introduction():
 first,_,_=await opening_prompt('nova',lambda scope,now:journal())
 returning,_,_=await opening_prompt('nova',SEEDED(True))
 assert 'do not refer to yourself by name' not in first[-1]['content'] and 'Introduce yourself in a few words' in first[-1]['content']
 assert 'do not refer to yourself by name' in returning[-1]['content'] and 'no introduction' in returning[-1]['content']

@pytest.mark.parametrize('relationship,line,code',[('returning','Hello there. I am Nova, and you intrigue me.','reintroduction'),('returning',"It is a privilege to finally meet you.",'first_session_claim'),('unknown','This is our first session together.','first_session_claim'),('returning',"I'm Nova, by the way.",'reintroduction')])
def test_a_relationship_is_held_to_what_it_says(relationship,line,code):
 assert code in card_language_violations(line,{'deck_card':{'lane':'session_start','relationship':relationship,'speaker':'nova'}})

@pytest.mark.parametrize('line',['Hello there. I am Nova, and this is our first session together.','I am Nova.'])
def test_a_first_session_may_introduce_itself(line):
 assert card_language_violations(line,{'deck_card':{'lane':'session_start','relationship':'first','speaker':'nova'}})==[]

@pytest.mark.parametrize('line',['The Classic mode I selected for you was too gentle.','I chose this setting for you.','I picked the speed myself.'])
def test_a_companion_did_not_choose_the_settings(line):
 assert 'read_only_control_claim' in card_language_violations(line,{'deck_card':{'lane':'normal'}})

@pytest.mark.parametrize('line',['I chose you for this.','I picked a fine evening to be strict.','Next time I decide how long you wait, and you will obey.','You are mine to command.'])
def test_fictional_dominance_is_not_a_settings_claim(line):
 assert card_language_violations(line,{'deck_card':{'lane':'normal'}})==[]

async def test_a_direction_shapes_a_reaction_without_being_handed_its_words():
 r,s,wire,frames=await closing(RESULT|{'edges':10},[earlier()],direction='You are strict and commanding.')
 text=[b for p,b in wire if p=='/api/chat'][-1]['messages'][-1]['content']
 assert 'never describe yourself in its words' in text and 'verified facts stay exactly as listed' in text and 'ahead of your usual manner' not in text

def test_card_guidance_keeps_generic_standards_out():
 from companion_ai.context_compiler import CARD_DIRECTION,CARD_GUIDANCE,CARD_INTERPRETATION
 assert 'standards' not in CARD_INTERPRETATION+CARD_GUIDANCE+CARD_DIRECTION and 'strict' not in CARD_INTERPRETATION+CARD_GUIDANCE+CARD_DIRECTION


# Lines the real models wrote in the accuracy run. Each of these was wrongly refused, or wrongly delivered.

@pytest.mark.parametrize('line,figures',[
 ('Fifteen minutes of sustained output, yielding five more edges than your last outing and running three minutes longer.',dict(edges=12,seconds=900)),
 ('Eight edges in thirteen minutes, a single edge more than your last run and a minute longer.',dict(edges=8,seconds=780)),
 ('Three fewer edges than before, and seven minutes shorter to boot.',dict(edges=4,seconds=300)),
 ('Four edges in fifteen minutes, a slower, more deliberate pace than the previous sprint.',dict(edges=4,seconds=900)),
 ('Seven edges in fifteen minutes, and you simply stopped the clock before claiming a finish.',dict(edges=7,seconds=900)),
 ('Nine edges, and you stopped the clock before declaring a finish.',dict(edges=9,seconds=530)),
])
def test_true_lines_a_model_wrote_are_not_refused(line,figures):
 assert card_language_violations(line,closing_summary(**figures))==[]

@pytest.mark.parametrize('line,figures,code',[
 ('Seven more edges than your last run, and nearly a full minute longer to earn them.',dict(prior_edges=4,prior_seconds=232,edges=11,seconds=590),'wrong_comparison'),
 ('Fifteen minutes yielded twelve edges, a modest gain over the previous twelve.',dict(edges=12,seconds=900),'unsupported_history_figure'),
])
def test_false_lines_a_model_wrote_are_refused(line,figures,code):
 assert code in card_language_violations(line,closing_summary(**figures))

def test_a_real_full_minute_longer_is_still_true():
 assert card_language_violations('A full minute longer than last time.',closing_summary(edges=8,seconds=780))==[]

def test_only_a_known_returning_companion_is_held_to_not_reintroducing():
 assert card_language_violations('I am Nova, and here we are.',{'deck_card':{'lane':'session_start','relationship':'unknown','speaker':'nova'}})==[]
 assert 'reintroduction' in card_language_violations('I am Nova, and here we are.',{'deck_card':{'lane':'session_start','relationship':'returning','speaker':'nova'}})

async def test_a_closing_says_the_difference_is_not_how_long_either_ran():
 r,s,wire,frames=await closing(RESULT|{'edges':4,'active_running_seconds':300},[earlier()])
 text=[b for p,b in wire if p=='/api/chat'][-1]['messages'][-1]['content']
 assert 'ran 7 minutes shorter than the last one. That is the gap between the two sessions, not how long either one ran.' in text

@pytest.mark.parametrize('line,figures',[('It felt like a steady endurance rather than a frantic sprint compared to last time.',dict(edges=7,seconds=900)),('Three extra edges and a full minute longer than I expected.',dict(edges=10,seconds=900))])
def test_figures_of_speech_around_a_comparison_are_not_refused(line,figures):
 assert card_language_violations(line,closing_summary(**figures))==[]

@pytest.mark.parametrize('line,figures',[
 ('It was the same count as last time, yet this run stretched three precious minutes longer than the previous one.',dict(edges=7,seconds=900)),
 ('I suppose I outpaced my own previous run, managing three extra edges and a few more minutes than the last.',dict(edges=10,seconds=900)),
 ('That session was three edges short of the last one.',dict(edges=4,seconds=300)),
 ('You stopped, leaving me with a result three edges short of last time.',dict(edges=4,seconds=300)),
 ('Three fewer edges than your last frantic sprint, and it felt too leisurely compared to our last frantic sprint.',dict(edges=4,seconds=900)),
])
def test_more_true_lines_a_model_wrote_are_not_refused(line,figures):
 assert card_language_violations(line,closing_summary(**figures))==[]

def test_a_lingering_extra_minute_is_still_a_figure():
 assert 'wrong_comparison' in card_language_violations('I tally the loss of three edges against that lingering extra minute.',closing_summary(edges=4,seconds=900))

def test_with_no_earlier_session_a_wish_is_not_invented_history():
 summary=closing_summary();summary['deck_card']['history']={'status':'none','current':summary['deck_card']['history']['current']}
 assert card_language_violations("I'd have loved to see one more edge before we called it a day.",summary)==[]
 assert 'invented_history' in card_language_violations('You had more edges than last time.',summary)

DAISY_FIRST_ARRIVALS=("Well, pull up a chair and let's get acquainted. I haven't had a session with anyone in a long time, and I'd hate to start with a stranger who doesn't know the Cloverfield way. Now, tell me how you'd like to begin this little adventure.",
    "Well, pull up a chair and say hello! I haven't had my hands on a new face like this in a long time, and I'd hate to let you slip away without a proper introduction. Tell me what you're feeling, and let's see if we can make this place feel right for you.")

@pytest.mark.parametrize('text',DAISY_FIRST_ARRIVALS)
def test_the_speakers_own_long_time_is_not_shared_history(text):
    assert history_violations(text,{'deck_card':{'lane':'arrival','history':{'status':'none'}}})==[]

@pytest.mark.parametrize('status',['none','denied'])
@pytest.mark.parametrize('text',["Welcome back!","It's been a long time.","I haven't seen you in a long time.","I've missed you.","Back again, I see.",
    "Like before, I'll take it slow with you.","Our last session was fun.","I remember when we first met in the barn.","I've been waiting a long time for you to come back."])
def test_a_past_with_the_person_addressed_is_still_invented_history(text,status):
    assert 'invented_history' in history_violations(text,{'deck_card':{'lane':'arrival','history':{'status':status}}})

def test_without_journal_access_no_earlier_session_is_still_unknown():
    assert 'first_session_claim' in history_violations(DAISY_FIRST_ARRIVALS[0],{'deck_card':{'lane':'arrival','history':{'status':'denied'}}})

def test_nova_may_mention_this_synthetic_heart():
 assert card_language_violations('You make this synthetic heart skip a beat.',{'deck_card':{'lane':'normal'}})==[]
 assert 'test_language' in card_language_violations('That was a synthetic session.',{'deck_card':{'lane':'normal'}})

def test_a_brisk_run_can_be_a_faster_one_that_ran_longer():
 assert card_language_violations('Twelve edges in fifteen minutes; a brisk, efficient run that outpaced the previous session by exactly five edges and three minutes.',closing_summary(edges=12,seconds=900))==[]
 assert 'wrong_comparison' in card_language_violations('A brisk run, shorter on edges than last time.',closing_summary(edges=4,seconds=900))
