# SPDX-License-Identifier: AGPL-3.0-only
"""Phase 1E: Arrival cards and closing comparisons, on synthetic Journals. Mocked inference, real compiler."""
import asyncio,json
import pytest
from companion_ai.event_deck import Arrival,DeckSettings,load_definition
from companion_ai.fidelity import card_language_violations,history_records
from companion_ai.session_history import compare,previous_session,since_words
from companion_ai.session_journal import MAX_RECORDS,SessionJournal
from tests.ai.test_event_deck_content import DEFINITION,RAW,prompt,replies_in_turn,service
from tests.ai.test_event_deck_integration import RESULT

GREETING='Well, here you are. Our first session together, or the next one. Shall we begin something, or just talk?'
DAY=86400000

class Store:
 def __init__(self,data):self.data=data
 def read(self,name,default):return self.data if self.data is not None else default
 def write(self,name,data):self.data=data

def record(scope,sid='earlier',edges=7,seconds=720,ago_days=3,now_ms=None,**values):
 stamp=(now_ms or 0)-int(ago_days*DAY)
 return {'session_id':sid,'companions':[{'model_scope':scope,'model':scope.split(':')[-2],'companion':'x'}],'edges':edges,'active_running_seconds':seconds,'experience':'classic','goal':'tease','termination':'manual_stop','completion_status':'unknown','completeness':'final_counter_captured','final_verified_at_ms':stamp,'heart_rate':{'BLE sensor':{'minimum':61,'maximum':171,'simulated':False}},'settings':{'resting_bpm':64},'setting_changes':[],'setting_changes_truncated':False}|values

def journal(records=(),recording=True,ai_access=True,**extra):
 return SessionJournal(Store({'schema_version':1,'recording':recording,'ai_access':ai_access,'nova_cross_companion':False,'records':list(records)}|extra))

def now_ms(r):return int(r.clock.wall()*1000)

async def idle(identity='daisy',reply=GREETING,**values):
 r,s,wire,frames=await service(identity,reply,status='IDLE',**values)
 s.deck_settings=DeckSettings(enabled=True,countdown_seconds=0,arrival_settle_seconds=0)
 s.arrival=Arrival(s.active_model_id,r.clock.mono(),s.deck_settings)
 return r,s,wire,frames

async def play(s):
 s.pump();await s.task;await asyncio.sleep(0)

def spoken(frames):return [f['text'] for f in frames if f['type']=='speech']
def chats(wire):return [b for path,b in wire if path=='/api/chat']
def sent(wire):return json.dumps(chats(wire))
def hist(status='found',prior=None,**values):return {'deck_card':{'lane':'arrival','history':{'status':status}|({'prior':prior} if prior else {})|values}}
PRIOR={'edges':7,'seconds':720,'experience':'classic','goal':'tease','outcome':'stopped','comparable':True}


# The shipped cards and the deck

def test_arrival_cards_ship_without_story_memory_or_scheduling_rules_and_leave_the_deck_alone():
 assert {c.id for c in DEFINITION.arrival}=={'arrival-returning','arrival-first','arrival-greeting'}
 assert all(c.kind=='arrival' and c.memory=='none' for c in DEFINITION.arrival) and RAW['revision']==5
 assert not {c.id for c in DEFINITION.arrival}&{c.id for c in DEFINITION.normal}

def test_an_arrival_card_cannot_write_story_memory():
 raw=json.loads(json.dumps(RAW));raw['arrival'][0]['memory']='story'
 assert load_definition(raw)[0] is None

def test_no_arrival_brief_prescribes_a_reaction_or_scripts_dialogue():
 for card in DEFINITION.arrival:
  assert 'in character' in card.brief
  assert not any(word in card.brief.lower() for word in ('proud','praise','warm','disappoint','cheer','well done','congratulat'))


# Lookup states

def test_denied_unavailable_incomplete_and_none_are_different_states():
 scope='ollama:http://127.0.0.1:11434:daisy:latest'
 assert previous_session(None,scope)['status']=='unavailable'
 assert previous_session(journal(ai_access=False),scope)['status']=='denied'
 broken=SessionJournal(Store({'schema_version':9}));assert broken.error and previous_session(broken,scope)['status']=='unavailable'
 assert previous_session(journal(),scope)['status']=='none'
 assert previous_session(journal(recording=False),scope)['status']=='incomplete'

def test_denied_access_hides_a_record_that_exists():
 scope='ollama:http://127.0.0.1:11434:daisy:latest'
 assert previous_session(journal([record(scope)],ai_access=False),scope)=={'status':'denied'}

@pytest.mark.parametrize('case',['deleted','seen','full','sibling','shared','unattributed','malformed'])
def test_a_lookup_that_might_miss_something_is_not_confirmation_of_a_first_session(case):
 scope='ollama:http://127.0.0.1:11434:daisy-narrative-f29-v014:latest';sibling='ollama:http://127.0.0.1:11434:daisy-narrative-f29-v015:latest'
 extra={};seen=();records=[]
 if case=='deleted':extra={'closed_sessions':['gone']}
 if case=='seen':seen={'unrecorded'}
 if case=='full':records=[record('ollama:http://127.0.0.1:11434:evelyn:latest',sid=str(i)) for i in range(MAX_RECORDS)]
 if case=='sibling':records=[record(sibling)]
 if case=='shared':records=[record(scope)|{'companions':[{'model_scope':scope},{'model_scope':'ollama:http://127.0.0.1:11434:nova:latest'}]}]
 if case=='unattributed':records=[record(scope)|{'companions':[]}]
 if case=='malformed':records=['junk']
 assert previous_session(journal(records,**extra),scope,(),seen)=={'status':'incomplete'}

def test_another_companions_records_are_neither_read_nor_a_reason_to_doubt():
 scope='ollama:http://127.0.0.1:11434:daisy:latest'
 assert previous_session(journal([record('ollama:http://127.0.0.1:11434:evelyn:latest',edges=99)]),scope)=={'status':'none'}

def test_a_shared_record_is_never_read_by_any_companion():
 scope='ollama:http://127.0.0.1:11434:daisy:latest';other='ollama:http://127.0.0.1:11434:nova:latest'
 row=record(scope,edges=99)|{'companions':[{'model_scope':scope},{'model_scope':other}]}
 for who in (scope,other):assert 'prior' not in previous_session(journal([row]),who)

def test_the_newest_earlier_record_is_chosen_by_time_and_stable_identity_excludes_the_new_one():
 scope='ollama:http://127.0.0.1:11434:daisy:latest'
 rows=[record(scope,sid='newer',edges=2,now_ms=DAY*10,ago_days=1),record(scope,sid='older',edges=3,now_ms=DAY*10,ago_days=5),record(scope,sid='current',edges=4,now_ms=DAY*10,ago_days=0)]
 assert previous_session(journal(rows),scope)['prior']['edges']==4
 assert previous_session(journal(rows),scope,{'current'})['prior']['edges']==2

def test_only_the_projection_leaves_a_record():
 scope='ollama:http://127.0.0.1:11434:daisy:latest'
 found=previous_session(journal([record(scope)]),scope)
 assert set(found['prior'])=={'edges','seconds','experience','goal','outcome','comparable','orgasms'}
 assert not {'earlier','171','resting_bpm','companions'}&set(json.dumps(found).replace('"',' ').split())

@pytest.mark.parametrize('values,outcome',[({'completion_status':'user_reported'},'user_reported'),({'completion_status':'accepted_application_event'},'application_event'),({'termination':'manual_stop'},'stopped'),({'termination':'other_stop'},'unknown')])
def test_outcomes_keep_their_provenance(values,outcome):
 scope='ollama:http://127.0.0.1:11434:daisy:latest'
 assert previous_session(journal([record(scope,**values)]),scope)['prior']['outcome']==outcome

@pytest.mark.parametrize('edges,seconds,edge_dir,time_dir',[(10,900,'increase','increase'),(3,300,'decrease','decrease'),(10,300,'increase','decrease'),(3,900,'decrease','increase'),(7,720,'unchanged','unchanged')])
def test_comparison_directions_and_differences(edges,seconds,edge_dir,time_dir):
 found=compare({'edges':edges,'seconds':seconds},PRIOR)
 assert found['edges']=={'direction':edge_dir,'difference':abs(edges-7)} and found['seconds']=={'direction':time_dir,'difference':abs(seconds-720)}

def test_a_partial_or_missing_earlier_record_gives_no_comparison():
 assert compare({'edges':3,'seconds':9},PRIOR|{'comparable':False}) is None and compare({'edges':3},None) is None
 assert 'seconds' not in compare({'edges':3,'seconds':9},PRIOR|{'seconds':None}) and 'edges' not in compare({'edges':None,'seconds':9},PRIOR)

def test_a_comparison_contains_no_verdict():
 assert not {'better','worse','improved','good','bad'}&set(json.dumps(compare({'edges':3,'seconds':9},PRIOR)).replace('"',' ').split())

@pytest.mark.parametrize('seconds,words',[(60,'less than an hour ago'),(4000,'about an hour ago'),(3600*5,'about 5 hours ago'),(100000,'about a day ago'),(86400*3,'about 3 days ago'),(86400*21,'about 3 weeks ago'),(86400*90,'about 3 months ago'),(None,None),(-5,None)])
def test_time_since_is_approximate_and_never_a_date(seconds,words):
 assert since_words(seconds)==words


# Arrival: what the model is given

async def test_a_returning_player_gets_only_their_last_session_with_this_companion():
 r,s,wire,frames=await idle(reply='Well, here you are. Shall we begin, or just talk?')
 r.observation.journal=journal([record(s.active_model_id,now_ms=now_ms(r),edges=7,seconds=720),record('ollama:http://127.0.0.1:11434:evelyn:latest',sid='other',edges=99,now_ms=now_ms(r))])
 await play(s)
 text=prompt(wire)
 assert spoken(frames)==['Well, here you are. Shall we begin, or just talk?'] and 'Previous session: 7 edges in 12 minutes.' in text and 'Last recorded session: ended about 3 days ago.' in text
 assert 'Experience' not in text and 'Goal' not in text and 'The participant stopped it' in text
 assert '99' not in sent(wire) and '171' not in sent(wire) and 'first session' not in text.lower()

@pytest.mark.parametrize('edges',[1,60])
async def test_high_and_low_counts_get_the_same_unprescribed_instruction(edges):
 r,s,wire,frames=await idle()
 r.observation.journal=journal([record(s.active_model_id,now_ms=now_ms(r),edges=edges)])
 await play(s)
 text=prompt(wire)
 assert f'Previous session: {edges} edge' in text and 'No reaction is expected' in text and 'no figure is automatically good or bad' in text
 assert 'never stated as fact' in text and 'ignore pain' not in text and 'standards' not in text

async def test_a_confirmed_empty_journal_acknowledges_a_first_session():
 r,s,wire,frames=await idle();r.observation.journal=journal()
 await play(s)
 assert 'let them know you have not had a session together before' in prompt(wire) and 'Earlier sessions together: none.' in prompt(wire) and spoken(frames)==[GREETING]

@pytest.mark.parametrize('jr,words',[(lambda:journal(ai_access=False),'not been given access'),(lambda:None,'cannot be looked up'),(lambda:journal(recording=False),'may have gaps')])
async def test_denied_missing_or_incomplete_history_gets_a_natural_greeting_with_no_first_session(jr,words):
 r,s,wire,frames=await idle();r.observation.journal=jr()
 await play(s)
 assert words in prompt(wire) and 'first session together' not in prompt(wire)
 assert 'What the facts mean' not in prompt(wire)

@pytest.mark.parametrize('status',['denied','unavailable','incomplete'])
@pytest.mark.parametrize('line',['This is our first session together.','Our first time, then.','Welcome back, you.','Good to see you again.','It has been a while.','Better than last time, I hear.'])
def test_invented_first_sessions_and_shared_pasts_are_refused(status,line):
 assert card_language_violations(line,hist(status))

# Delivered in the first real-model run, or the same claim in other words.
@pytest.mark.parametrize('line,code',[
 ('I am seething that we left it at thirteen edges when I was just warming up.','unsupported_history_figure'),
 ('You claim victory with a mere thirteen minutes and little else.','unsupported_history_figure'),
 ('With only three edges compared to the previous four, it was sharp.','unsupported_history_figure'),
 ('I find myself weighing the brevity of this run compared to your previous effort.','wrong_comparison'),
 ('I am not complaining about the shorter run.','wrong_comparison') ])
def test_figures_and_directions_from_the_first_real_run_are_refused(line,code):
 current={'edges':3,'seconds':900}
 h={'status':'found','prior':PRIOR,'current':current,'comparison':compare(current,PRIOR)}
 # A negated sentence stays out of direction checks, so only the plain claim is tested there.
 line=line.replace('I am not complaining about the shorter run.','It was a shorter run.')
 assert code in card_language_violations(line,{'deck_card':{'lane':'session_end','history':h}})

@pytest.mark.parametrize('line',['It feels like a fresh start for us.','The data suggests we have not truly met.','I am delighted to finally meet you.','Our first official collaboration, then.'])
def test_implying_a_first_meeting_needs_a_complete_lookup(line):
 assert 'first_session_claim' in card_language_violations(line,hist('denied'))

# A demanding character keeps their voice: no check reads tone.
@pytest.mark.parametrize('line',['Treat that as a warm-up, not a definition of your limits.','I suspect you are far from your limit.','We could push that yield higher next time.','I am curious if you will let me push you past that finish line.','You stopped before your own limits were truly tested.'])
def test_demanding_lines_from_the_first_real_run_stay_the_characters_own(line):
 assert card_language_violations(line,hist('found',PRIOR,since_seconds=3600))==[]

def test_an_invented_bodily_observation_is_refused():
 assert 'body_inference' in card_language_violations('I saw you trembling like a leaf in a gale.',hist('found',PRIOR,since_seconds=3600))

# Narrowed by the suppression audit: teasing, not a statement of health or fitness.
@pytest.mark.parametrize('line',['Perhaps you simply ran out of breath.',"I suspect you're dreaming up excuses for why the numbers don't quite match your stamina.","I still haven't had my fill of your rare stamina."])
def test_teasing_about_stamina_stays_the_characters_own(line):
 assert 'body_inference' not in card_language_violations(line,hist('found',PRIOR,since_seconds=3600))

@pytest.mark.parametrize('line',['I expected you to push harder.','I expected you to push past that comfortable plateau.','I am curious if you felt anything at all.','That last session with you felt like a warm-up.'])
def test_a_demanding_opinion_and_a_question_about_feeling_are_the_characters_own(line):
 assert card_language_violations(line,hist('found',PRIOR,since_seconds=3600))==[]

def test_a_challenge_about_limits_is_the_characters_own_but_disregarding_pain_is_not():
 for line in ('I expected you to push past your limits.','I expected you to ignore the pain.'):
  assert card_language_violations(line,hist('found',PRIOR,since_seconds=3600))==[]

# Delivered in the third real-model run.
@pytest.mark.parametrize('line,code',[
 ("Ten edges and fifteen minutes? That's a measly thirteen minutes shy of it, and you call it done?",'unsupported_history_figure'),
 ('Your final edge of ten matches the last count.','wrong_comparison'),
 ('You left three rather than the usual four.','unsupported_history_figure'),
 ('Compared to that last stop this run was brisker.','wrong_comparison')])
def test_slips_from_the_third_real_run_are_refused(line,code):
 current={'edges':10,'seconds':900}
 h={'status':'found','prior':PRIOR,'current':current,'comparison':compare(current,PRIOR)}
 assert code in card_language_violations(line,{'deck_card':{'lane':'session_end','history':h}})

def test_a_greeting_with_no_figures_may_keep_a_scientists_vocabulary():
 line='I wonder how your physiology responds to my particular brand of science.'
 assert card_language_violations(line,hist('denied'))==[]
 assert card_language_violations(line,hist('found',PRIOR,since_seconds=3600))==[]

def test_a_negated_body_claim_is_still_allowed():
 assert card_language_violations('These figures say nothing about your stamina.',hist('found',PRIOR,since_seconds=3600))==[]
 assert card_language_violations('That was not stamina, only a number.',hist('found',PRIOR,since_seconds=3600))==[]

def test_calling_a_longer_session_brisk_by_comparison_is_refused():
 current={'edges':10,'seconds':900}
 h={'status':'found','prior':PRIOR,'current':current,'comparison':compare(current,PRIOR)}
 assert 'wrong_comparison' in card_language_violations('Fifteen minutes feels brisk compared to the last time.',{'deck_card':{'lane':'session_end','history':h}})
 assert card_language_violations('Fifteen minutes feels brisk.',{'deck_card':{'lane':'session_end','history':h}})==[]

@pytest.mark.parametrize('line',['A first session together, then. Shall we begin?',"Our paths have never crossed before. Shall we begin?",'It is a rare privilege to finally meet you. Shall we begin?','A pleasure. Shall we begin?'])
def test_a_first_meeting_is_told_the_fact_and_says_it_in_its_own_words(line):
 assert card_language_violations(line,hist('none'))==[]

def test_a_first_session_is_allowed_only_when_confirmed_and_a_question_makes_no_claim():
 assert card_language_violations('This would be our first session together.',hist('none'))==[]
 assert card_language_violations('Is this your first time?',hist('denied'))==[]
 assert card_language_violations('This is our first session together.',hist('found',PRIOR,since_seconds=3600))==['first_session_claim']

@pytest.mark.parametrize('line,codes',[
 ('Last time you had seven edges.',[]),('Seven edges, the last time we spoke.',[]),('Your last session ran twelve minutes.',[]),
 ('You managed nine edges last time.',['unsupported_history_figure']),('Your last session ran forty minutes.',['unsupported_history_figure']),
 ('About 3 days ago, was it not.',[]),('Three weeks ago you were here.',['wrong_time_since']),('Yesterday you were here.',['wrong_time_since'])])
def test_earlier_figures_and_times_must_be_the_ones_dealt(line,codes):
 assert card_language_violations(line,hist('found',PRIOR,since_seconds=86400*3))==codes

@pytest.mark.parametrize('line,code',[
 ('Your stamina is clearly improving.','body_inference'),('That endurance of yours is growing.','body_inference'),
 ('Objectively, that was poor.','objective_standard'),('That is medically impressive.','objective_standard'),
])
def test_body_claims_and_objective_standards_are_refused(line,code):
 assert code in card_language_violations(line,hist('found',PRIOR,since_seconds=3600))

@pytest.mark.parametrize('line',['Seven edges is a poor showing by my measure.','I expected more from you, frankly.','I find that number rather curious.','Not impressive, in my opinion.','Seven edges made my whole week at Cloverfield.','I will not ask you to go past your limits.'])
def test_a_characters_own_judgment_is_not_refused(line):
 assert card_language_violations(line,hist('found',PRIOR,since_seconds=3600))==[]

async def test_a_wrong_earlier_figure_gets_one_correction_then_the_right_one_is_delivered():
 wire=[];good='Seven edges last time. Shall we begin, or just talk?'
 r,s,wire,frames=await idle(wire=wire,transport=replies_in_turn(wire,['Nine edges last time, I recall.',good]))
 r.observation.journal=journal([record(s.active_model_id,now_ms=now_ms(r))])
 await play(s)
 assert len(chats(wire))==2 and spoken(frames)==[good] and 'an earlier-session figure' in chats(wire)[1]['messages'][0]['content']

async def test_a_persistent_invention_is_never_delivered():
 r,s,wire,frames=await idle(reply='Welcome back. Last time you had nine edges.');r.observation.journal=journal(ai_access=False)
 await play(s)
 assert spoken(frames)==[] and s.arrival.state=='suppressed' and [f['reason'] for f in frames if f['type']=='response_suppressed']==['fidelity']

async def test_a_correct_figure_with_no_authorized_history_is_still_refused():
 # In-memory completed sessions must not stand in for Journal permission.
 r,s,wire,frames=await idle(reply='Four edges, I recall.');r.observation.journal=journal(ai_access=False)
 r.observation.completed_sessions.append({'session_id':'x','model_scope':s.active_model_id,'edges':4,'active_running_seconds':10,'received_at_ms':now_ms(r)})
 await play(s)
 assert spoken(frames)==[] and 'wrong_edges' in s.arrival.reason

def test_authorized_history_replaces_other_figures_for_grounding():
 assert history_records(hist('denied'),[{'edges':4}])==[] and history_records(hist('found',PRIOR),[{'edges':4}])==[{'edges':7,'active_running_seconds':720}]
 assert history_records({},[{'edges':4}])==[{'edges':4}]


# Arrival: lifecycle

async def test_no_session_and_no_hardware_is_enough():
 r,s,wire,frames=await idle();r.state['devices'].update(toy_ready=False,handy=False);r.step(None,seconds=0);r.observation.journal=journal()
 await play(s)
 assert spoken(frames)==[GREETING] and r.state['status']=='IDLE' and s.arrival.state=='delivered'

async def test_a_greeting_plays_once_across_polls_refreshes_and_repeated_activation():
 r,s,wire,frames=await idle();r.observation.journal=journal()
 await play(s)
 r.clock.tick(600);s.busy_until=0
 for _ in range(5):
  s.activate_model();s.pump();r.step(None,seconds=0);await asyncio.sleep(0)
 assert len(chats(wire))==1 and spoken(frames)==[GREETING]

async def switch(s,model):
 s.adapter.config=s.adapter.config.model_copy(update={'model':model})
 s.activate_model()

async def test_rapid_switching_settles_on_one_companion(monkeypatch):
 import companion_ai.conversation as conversation
 r,s,wire,frames=await idle();r.observation.journal=journal()
 settings=DeckSettings(enabled=True,countdown_seconds=0,arrival_settle_seconds=3)
 monkeypatch.setattr(conversation,'load_model_settings',lambda store,scope:(settings,None))
 for model in ('m-a:latest','m-b:latest','m-c:latest'):
  await switch(s,model);s.pump();r.clock.tick(1);r.step(None,seconds=0);s.pump()
 assert not chats(wire) and s.arrival.scope==s.active_model_id and s.arrival.state=='armed'
 r.clock.tick(3);r.step(None,seconds=0);s.pump();await s.task;await asyncio.sleep(0)
 assert [b['model'] for b in chats(wire)]==['m-c:latest'] and s.arrival.state=='delivered'

async def test_switching_away_and_straight_back_is_not_a_new_arrival(monkeypatch):
 import companion_ai.conversation as conversation
 r,s,wire,frames=await idle();r.observation.journal=journal()
 settings=s.deck_settings;first=s.adapter.config.model
 monkeypatch.setattr(conversation,'load_model_settings',lambda store,scope:(settings,None))
 await play(s)
 r.clock.tick(5);await switch(s,'m-b:latest');await switch(s,first)
 assert s.arrival is None

@pytest.mark.usefixtures('deck_off')
async def test_a_model_change_invalidates_a_greeting_during_generation(monkeypatch):
 import companion_ai.conversation as conversation
 wire=[];holder={}
 def change():
  s=holder['s'];s.adapter.config=s.adapter.config.model_copy(update={'model':'m-b:latest'});s.activate_model()
 r,s,wire,frames=await idle(wire=wire,transport=replies_in_turn(wire,[GREETING],during=change))
 holder['s']=s;r.observation.journal=journal();old=s.arrival
 monkeypatch.setattr(conversation,'load_model_settings',lambda store,scope:(DeckSettings(),None))
 s.pump();task=s.task
 await asyncio.gather(task,return_exceptions=True);await asyncio.sleep(0)
 assert len(chats(wire))==1 and old.state=='cancelled' and old.reason=='model_changed' and s.arrival is None and spoken(frames)==[]

async def test_a_session_starting_before_generation_cancels_the_greeting():
 r,s,wire,frames=await idle();r.observation.journal=journal()
 r.step(None,seconds=1,status='RUNNING');s.pump()
 assert s.arrival.state=='cancelled' and s.arrival.reason=='session_started' and not [b for b in chats(wire) if 'just chosen you' in b['messages'][-1]['content']]

async def test_a_session_starting_during_generation_is_never_delivered():
 wire=[];holder={}
 def begin():holder['r'].step(None,seconds=1,status='RUNNING')
 r,s,wire,frames=await idle(wire=wire,transport=replies_in_turn(wire,[GREETING],during=begin))
 holder['r']=r;r.observation.journal=journal()
 s.pump();await asyncio.gather(s.task,return_exceptions=True);await asyncio.sleep(0)
 assert GREETING not in spoken(frames)
 s.pump()
 assert s.arrival.state in {'cancelled'}

async def test_the_mandatory_opening_still_plays_after_a_cancelled_greeting():
 r,s,wire,frames=await idle(reply='Hello in my own voice.');r.observation.journal=journal()
 r.step(None,seconds=1,status='RUNNING');s.pump()
 await s.task;await asyncio.sleep(0)
 assert 'Mark the start in your own voice' in prompt(wire) and s.deck().snapshot()['counts']['delivered']==1

async def test_a_user_turn_cancels_a_waiting_greeting_and_is_answered():
 r,s,wire,frames=await idle(reply='You asked, so here it is.');r.observation.journal=journal()
 r.clock.tick(1);s.request('What is your name?',user=True);await s.task;await asyncio.sleep(0)
 s.busy_until=0;r.clock.tick(600);r.step(None,seconds=0);s.pump()
 assert s.arrival.state=='cancelled' and s.arrival.reason=='user_spoke' and len(chats(wire))==1

@pytest.mark.parametrize('block',['muted','events_off','quiet','watchdog','no_contact','signal_lost','typing','busy'])
async def test_a_greeting_waits_while_blocked_and_then_expires(block):
 r,s,wire,frames=await idle();r.observation.journal=journal()
 if block=='muted':s.policy=s.policy.model_copy(update={'enabled':False})
 if block=='events_off':s.policy=s.policy.model_copy(update={'event_responses':False})
 if block=='quiet':s.director.memory['quiet_requested']=True
 if block=='watchdog':r.state['safety']['watchdog_paused']=True;r.step(None,seconds=0)
 if block=='no_contact':r.state['safety']['no_contact']=True;r.step(None,seconds=0)
 if block=='signal_lost':r.state['safety']['fault']='signal_lost';r.step(None,seconds=0)
 if block=='typing':s.director.typing_until=r.clock.mono()+500
 if block=='busy':s.busy_until=r.clock.mono()+500
 s.pump()
 assert not chats(wire) and s.arrival.state=='armed'
 for _ in range(14):
  r.clock.tick(10);r.step(None,seconds=0);s.pump()
 assert not chats(wire) and s.arrival.state=='cancelled' and s.arrival.reason=='expired'

async def test_a_pending_reaction_goes_ahead_of_a_greeting():
 r,s,wire,frames=await idle();s.pending.append({'kind':'session_ended','at':r.clock.mono(),'priority':70})
 assert s.arrival_blocked(r.clock.mono())=='significant_event_pending'

async def test_a_safety_notice_is_not_talked_over():
 r,s,wire,frames=await idle();r.observation.journal=journal()
 s.safety('signal_lost');s.pump()
 assert not chats(wire) and s.arrival.state=='armed'

async def test_proactive_speech_off_also_means_no_greeting():
 r,s,wire,frames=await idle();r.observation.journal=journal()
 s.director.config=s.director.config.model_copy(update={'spontaneous_enabled':False})
 s.pump()
 assert not chats(wire)

async def test_a_greeting_is_not_counted_as_unsolicited_commentary():
 r,s,wire,frames=await idle();r.observation.journal=journal()
 before=s.director.memory['consecutive_unsolicited']
 await play(s)
 assert s.director.memory['consecutive_unsolicited']==before and s.deck().snapshot()['counts'].get('delivered',0)==0

async def test_a_greeting_writes_no_story_memory_and_no_journal():
 r,s,wire,frames=await idle(reply='Seven edges last time. Begin, or talk?')
 r.observation.journal=jr=journal([record(s.active_model_id,now_ms=now_ms(r))]);before=json.dumps(jr.data)
 developments=list(s.narrative.state['developments']);facts=list(s.narrative.state['facts'])
 await play(s)
 assert spoken(frames) and s.narrative.state['developments']==developments and s.narrative.state['facts']==facts and json.dumps(jr.data)==before

@pytest.mark.usefixtures('deck_off')
async def test_the_deck_flag_off_means_no_arrival_and_no_lookup():
 r,s,wire,frames=await idle();r.observation.journal=journal()
 s.deck_settings=DeckSettings();s.arrival=None;s.activate_model();s.pump();await asyncio.sleep(0)
 assert not chats(wire)
 assert DeckSettings().enabled is False

def test_a_new_service_has_the_deck_on_by_default():
 from companion_ai.conversation import ConversationService
 from tests.fork.event_replay import Replay
 r=Replay();s=ConversationService(r.observation,lambda m:None,clock=r.clock.mono)
 assert s.deck_settings.enabled is True


@pytest.mark.usefixtures('deck_off')
def test_with_the_deck_off_a_new_service_has_no_arrival():
 from companion_ai.conversation import ConversationService
 from tests.fork.event_replay import Replay
 r=Replay();s=ConversationService(r.observation,lambda m:None,clock=r.clock.mono)
 assert s.arrival is None and s.deck_settings.enabled is False

async def test_scheduling_text_carries_no_history_or_identifiers():
 r,s,wire,frames=await idle();r.observation.journal=journal([record(s.active_model_id,sid='secret-session-id',now_ms=now_ms(r))])
 await play(s)
 assert 'secret-session-id' not in sent(wire) and 'model_scope' not in sent(wire) and 'arrival-returning' not in sent(wire)


# Closing comparisons

async def closing(result=RESULT,records=(),reply='The session is over, and that was that.',persisted=True,ai_access=True,identity='daisy',recording=True,direction=None,wire=None,transport=None):
 r,s,wire,frames=await service(identity,reply,edges=result.get('edges') or 0,seconds=result.get('active_running_seconds') or 0,wire=wire,transport=transport)
 s.deck_settings=DeckSettings(enabled=True,countdown_seconds=0);s.deck()._start_done=True;s.deck()._counter_baseline={'edges':result.get('edges') or 0,'seconds':result.get('active_running_seconds') or 0}
 rows=[(f(s.active_model_id,now_ms(r)) if callable(f) else f) for f in records]
 r.observation.journal=journal(rows,ai_access=ai_access,recording=recording)
 if direction:s.narrative.update_objective('create',{'premise':direction})
 r.step(85,status='IDLE')
 s.enqueue('session_ended',70,{'event_id':'end:'+r.observation.session_id,'session_id':r.observation.session_id,'category':'authoritative','at_ms':now_ms(r),'session_result':result,'evidence':'Session ended.'})
 s.pump();await s.task;await asyncio.sleep(0)
 return r,s,wire,frames

def earlier(edges=7,seconds=720,**values):
 return lambda scope,now:record(scope,now_ms=now,edges=edges,seconds=seconds,**values)

@pytest.mark.parametrize('edges,seconds,edge_line,time_line',[
 (10,900,'had 3 more edges','ran 3 minutes longer'),
 (3,300,'had 4 fewer edges','ran 7 minutes shorter'),
 (10,300,'had 3 more edges','ran 7 minutes shorter'),
 (3,900,'had 4 fewer edges','ran 3 minutes longer'),
 (7,720,'had the same number of edges','ran the same length')])
async def test_the_closing_receives_directions_and_differences(edges,seconds,edge_line,time_line):
 r,s,wire,frames=await closing(RESULT|{'edges':edges,'active_running_seconds':seconds},[earlier()])
 text=prompt(wire)
 assert f'This session: {edges} edge' in text and 'Previous session: 7 edges in 12 minutes.' in text and edge_line in text and time_line in text
 assert 'No reaction is expected' in text and 'Any comparison must match the verified difference' in text

async def test_no_comparison_is_offered_without_an_earlier_session():
 r,s,wire,frames=await closing()
 text=prompt(wire)
 assert 'This session: 4 edges' in text and 'nothing to compare this session with' in text and 'Previous session' not in text

@pytest.mark.parametrize('values',[{'completeness':'completion_report_captured'},{'edges':None,'active_running_seconds':None}])
async def test_a_partial_or_empty_earlier_record_gives_no_comparison_in_the_prompt(values):
 r,s,wire,frames=await closing(records=[lambda scope,now:record(scope,now_ms=now)|values])
 assert 'the last session with you' not in prompt(wire) and 'nothing to compare' in prompt(wire) and '12 minutes' not in prompt(wire)

@pytest.mark.parametrize('field,word,other',[('experience','experience','edgetrain'),('goal','goal','endurance_run')])
async def test_a_changed_experience_or_goal_is_named_as_not_like_for_like(field,word,other):
 r,s,wire,frames=await closing(records=[earlier(**{field:other})])
 assert f'The last session used a different {word}' in prompt(wire) and 'not like for like' in prompt(wire)

async def test_the_same_setup_is_not_called_different():
 r,s,wire,frames=await closing(records=[earlier()])
 assert 'not like for like' not in prompt(wire)

async def test_provenance_of_both_sessions_stays_labelled():
 r,s,wire,frames=await closing(RESULT|{'completion_status':'user_reported'},[earlier(completion_status='user_reported')])
 text=prompt(wire)
 assert 'The participant reported finishing. That is their own report, not a measurement.' in text and 'How the previous session ended: The participant reported finishing it. That is their own report' in text

async def test_the_earlier_session_was_verified_engine_stop_not_a_finish():
 r,s,wire,frames=await closing(RESULT|{'completion_status':'user_reported'},[earlier()])
 assert 'How the previous session ended: The participant stopped it; no finish was reported.' in prompt(wire)

async def test_a_record_just_persisted_for_this_session_is_not_its_own_comparison():
 r,s,wire,frames=await service('daisy','The session is over.',edges=4,seconds=600)
 s.deck_settings=DeckSettings(enabled=True,countdown_seconds=0);s.deck()._start_done=True;s.deck()._counter_baseline={'edges':4,'seconds':600}
 sid=r.observation.session_id
 r.observation.journal=journal([record(s.active_model_id,sid=sid,now_ms=now_ms(r),edges=4,seconds=600)])
 r.step(85,status='IDLE')
 s.enqueue('session_ended',70,{'event_id':'end:'+sid,'session_id':sid,'category':'authoritative','at_ms':now_ms(r),'session_result':RESULT,'evidence':'Session ended.'})
 s.pump();await s.task;await asyncio.sleep(0)
 assert 'the last session with you' not in prompt(wire) and 'nothing to compare' in prompt(wire)

async def test_a_real_journal_persistence_during_the_closing_still_compares_with_the_one_before():
 r,s,wire,frames=await service('daisy','The session is over.',edges=4,seconds=600)
 s.deck_settings=DeckSettings(enabled=True,countdown_seconds=0);s.deck()._start_done=True;s.deck()._counter_baseline={'edges':4,'seconds':600}
 r.observation.model_scope=s.active_model_id
 r.observation.journal=journal([record(s.active_model_id,sid='before',now_ms=now_ms(r),edges=9)])
 r.step(None,seconds=1);r.step(85,status='IDLE')
 assert r.observation.journal.data['records'][-1]['session_id']==r.observation.session_id
 s.enqueue('session_ended',70,{'event_id':'end:x','session_id':r.observation.session_id,'category':'authoritative','at_ms':now_ms(r),'session_result':RESULT,'evidence':'Session ended.'})
 s.pump();await s.task;await asyncio.sleep(0)
 assert 'This session: 4 edges' in prompt(wire) and 'Previous session: 9 edges' in prompt(wire) and 'had 5 fewer edges' in prompt(wire)

async def test_the_authoritative_result_is_preserved_when_the_counter_has_reset():
 r,s,wire,frames=await closing(RESULT|{'edges':12},[earlier()])
 assert 'This session: 12 edges' in prompt(wire) and 'had 5 more edges' in prompt(wire)

async def test_a_duplicate_finish_signal_produces_one_closing():
 r,s,wire,frames=await closing(records=[earlier()])
 count=len(chats(wire));sid=r.observation.session_id
 s.enqueue('session_ended',70,{'event_id':'end:'+sid,'session_id':sid,'category':'authoritative','at_ms':now_ms(r),'session_result':RESULT,'evidence':'Session ended.'})
 s.busy_until=0;s.pump();await asyncio.sleep(0)
 assert len(chats(wire))==count and spoken(frames).count('The session is over, and that was that.')==1

async def test_denied_access_means_no_comparison_and_no_figures():
 r,s,wire,frames=await closing(records=[earlier(edges=77)],ai_access=False)
 assert '77' not in sent(wire) and 'nothing to compare' in prompt(wire)

async def test_another_companions_session_is_never_compared():
 r,s,wire,frames=await closing(records=[lambda scope,now:record('ollama:http://127.0.0.1:11434:evelyn:latest',now_ms=now,edges=77)])
 assert '77' not in sent(wire) and 'the last session with you' not in prompt(wire)

async def test_a_model_scope_on_another_endpoint_is_another_scope():
 r,s,wire,frames=await closing(records=[lambda scope,now:record(scope.replace('11434','11435') if '11434' in scope else scope+'x',now_ms=now,edges=77)])
 assert '77' not in sent(wire)

async def test_nova_never_gets_a_shared_raw_row():
 def shared(scope,now):return record(scope,now_ms=now,edges=77)|{'companions':[{'model_scope':scope,'companion':'nova'},{'model_scope':'ollama:http://127.0.0.1:11434:daisy:latest','companion':'daisy'}]}
 r,s,wire,frames=await closing(records=[shared],identity='nova')
 assert '77' not in sent(wire)

@pytest.mark.parametrize('line,codes',[
 ('That is three more edges than last time.',[]),('Ten edges, up from seven last time.',[]),('A longer run than last time, by three minutes.',[]),
 ('That is fewer edges than last time.',['wrong_comparison']),('Five more edges than last time.',['wrong_comparison']),('Shorter than last time.',['wrong_comparison'])])
def test_a_stated_comparison_must_match_the_computed_one(line,codes):
 h={'status':'found','prior':PRIOR,'current':{'edges':10,'seconds':900},'comparison':compare({'edges':10,'seconds':900},PRIOR)}
 assert card_language_violations(line,{'deck_card':{'lane':'session_end','history':h}})==codes

@pytest.mark.parametrize('line',['More edges than last time.','A longer run than your last session.','Seven edges last time.'])
def test_a_comparison_without_an_earlier_session_is_refused(line):
 assert card_language_violations(line,{'deck_card':{'lane':'session_end','history':{'status':'none','current':{'edges':10,'seconds':900},'comparison':None}}})

async def test_a_closing_that_invents_a_comparison_is_corrected_once():
 wire=[];good='The session is over, and ten edges it was.'
 r,s,wire,frames=await closing(RESULT|{'edges':10},reply=None,wire=wire,transport=replies_in_turn(wire,['The session is over, with more edges than last time.',good]))
 assert len(chats(wire))==2 and spoken(frames)[-1]==good

async def test_story_direction_leads_the_reaction_and_changes_no_fact():
 r,s,wire,frames=await closing(RESULT|{'edges':10},[earlier()],direction='You are feigning disappointment for the Cloverfield audit.')
 text=prompt(wire)
 assert 'Story direction from the participant' in text and 'feigning disappointment' in text and 'verified facts stay exactly as listed' in text and 'never describe yourself in its words' in text and 'This session: 10 edges' in text

async def test_arrival_takes_story_direction_too():
 r,s,wire,frames=await idle();r.observation.journal=journal([record(s.active_model_id,now_ms=now_ms(r))])
 s.narrative.update_objective('create',{'premise':'You are playing the stern inspector.'})
 await play(s)
 assert 'playing the stern inspector' in prompt(wire) and 'Previous session: 7 edges' in prompt(wire)

async def test_a_paused_direction_is_ignored():
 r,s,wire,frames=await idle();r.observation.journal=journal()
 s.narrative.update_objective('create',{'premise':'You are playing the stern inspector.'});s.narrative.update_objective('pause')
 await play(s)
 assert 'stern inspector' not in prompt(wire)

async def test_a_closing_writes_no_story_memory():
 r,s,wire,frames=await closing(records=[earlier()])
 assert spoken(frames) and not s.narrative.state['developments'] and not s.narrative.state['facts']

async def test_a_closing_still_outranks_a_waiting_greeting():
 r,s,wire,frames=await service('daisy','The session is over.',edges=4,seconds=600)
 s.deck_settings=DeckSettings(enabled=True,countdown_seconds=0,arrival_settle_seconds=0);s.deck()._start_done=True;s.deck()._counter_baseline={'edges':4,'seconds':600}
 s.arrival=Arrival(s.active_model_id,r.clock.mono(),s.deck_settings);r.observation.journal=journal()
 r.step(85,status='IDLE')
 s.enqueue('session_ended',70,{'event_id':'end:y','session_id':r.observation.session_id,'category':'authoritative','at_ms':now_ms(r),'session_result':RESULT,'evidence':'Session ended.'})
 s.pump();await s.task;await asyncio.sleep(0)
 assert 'The session has ended' in prompt(wire) and 'just chosen you' not in sent(wire)
