# SPDX-License-Identifier: AGPL-3.0-only
"""What an unsolicited card turn sends to the model. Mocked inference, real compiler."""
import asyncio,json,re
import pytest
from companion_ai.context_compiler import CARD_OPENINGS
from companion_ai.expressions import EXPRESSIONS,FORMAT_INSTRUCTION,HEADER_REMINDER,ExpressionStream,clean_dialogue
from companion_ai.event_deck import DeckSettings,load_model_settings,scope_key
from companion_ai.storage import SettingsStore
from companion_ai.fidelity import card_language_violations
from tests.ai.test_event_deck_content import ALL,DEFINITION,connect,context,deck,drawn,play_only,prompt,replies_in_turn,service

INTERNAL=re.compile(r'PRIMARY FOCUS|DIRECTOR OPPORTUNITY|APPLICATION EVENT|director_opportunity|play_id|card_id|"lane"|"intent"|topic_key|focus_topic|general_conversation|edge_commentary|milestone_edges|session_result|manual_stop|completion_status|captured_at_ms|Session identity|\[edgetrain\]|\[classic\]')
EDGE='edge-count-first'

def speech(frames):return ''.join(f['text'] for f in frames if f['type']=='response_delta').strip()
def messages(wire):return next(b for path,b in reversed(wire) if path=='/api/chat')['messages']
def monologue(r,text):return {'role':'assistant','content':text,'origin':'assistant_dialogue','trigger_origin':'system_event','session_id':r.state['session_id'],'narrative_epoch':None}
def spoken(r,role,text):return {'role':role,'content':text,'origin':'real_user' if role=='user' else 'assistant_dialogue','trigger_origin':'real_user','session_id':r.state['session_id'],'narrative_epoch':None}
def retrying(s):s.director.config=s.director.config.model_copy(update={'regenerate_once':True})
async def turn(s):
 s.pump();await s.task;await asyncio.sleep(0)


# One concise instruction

@pytest.mark.parametrize('card_id,state',[(EDGE,{'edges':3}),('duration-long',{'seconds':1300}),('general-remark',{}),('hr-rising',{'trend':'rising'})])
async def test_a_card_turn_carries_no_internal_labels_and_states_its_brief_once(card_id,state):
 r,s,wire,frames=await service(**state);play_only(s,card_id)
 await turn(s)
 card=next(c for c in ALL if c.id==card_id);text=prompt(wire)
 assert text.count(card.brief)==1 and not INTERNAL.search(text) and card_id not in text and card.intent not in text and '{' not in text
 assert len(messages(wire))==2 and messages(wire)[-1]['role']=='user' and 'This is not a message from them' in text

async def test_settings_are_no_part_of_a_routine_card():
 r,s,wire,frames=await service(edges=3);play_only(s,EDGE)
 r.state['goal']='edgetrain';r.step(None,seconds=0)
 await turn(s)
 assert 'Classic Tease' not in prompt(wire) and 'Edge Training' not in prompt(wire)

async def test_the_grounding_boundaries_still_reach_the_model():
 r,s,wire,frames=await service(edges=3);play_only(s,EDGE)
 await turn(s)
 system=messages(wire)[0]['content']
 assert 'Simulator values are not the user' in system and 'No hardware-control tools exist' in system and 'Never claim you will adjust' in system

@pytest.mark.parametrize('lane_card,wanted',[(EDGE,'about 15 to 35 words'),('general-remark','about 15 to 35 words')])
async def test_normal_cards_ask_for_short_form(lane_card,wanted):
 r,s,wire,frames=await service(edges=3);play_only(s,lane_card)
 await turn(s)
 assert wanted in prompt(wire) and 'Make a statement, not a question' in prompt(wire)

async def test_a_mission_may_run_a_little_longer():
 r,s,wire,frames=await service(edges=0);s.deck()._start_done=True;s.deck()._counter_baseline={'edges':0,'seconds':0}
 r.state.update(edges=3);r.step(None,seconds=1)
 await turn(s)
 assert 'about 25 to 45 words' in prompt(wire) and 'the participant has reached 3 edges' in prompt(wire)

async def test_only_a_challenge_may_ask_something_when_nobody_has_spoken():
 r,s,wire,frames=await service();play_only(s,'challenge-wager')
 await turn(s)
 assert 'at most one short question' in prompt(wire) and 'Make a statement' not in prompt(wire)

async def test_a_user_turn_keeps_its_normal_prompt():
 r,s,wire,frames=await service(edges=3)
 s.request('How is it going?',user=True);await s.task
 text=prompt(wire)
 assert 'PRIMARY FOCUS' in text and 'USER MESSAGE (request, not session data)' in text and 'A MOMENT TO SPEAK' not in text and '15 to 35 words' not in text


# History: real exchanges only

async def test_earlier_commentary_is_not_replayed_as_conversation():
 r,s,wire,frames=await service(edges=3);play_only(s,EDGE)
 s.history.append(monologue(r,'Seven edges. That is a proper stretch of work.'))
 await turn(s)
 assert not [m for m in messages(wire) if m['role']=='assistant'] and 'proper stretch' not in json.dumps(messages(wire)) and 'Seven' not in json.dumps(messages(wire))

async def test_only_the_latest_user_message_is_replayed_and_commentary_is_dropped():
 r,s,wire,frames=await service();play_only(s,'general-remark')
 for index in range(4):s.history+=[spoken(r,'user',f'Tell me about barn {index}.'),spoken(r,'assistant',f'Barn {index} leans east.')]
 s.history.append(monologue(r,'An unprompted aside about fences.'))
 await turn(s)
 # Companion lines are never replayed, and the latest user line is background, not an unanswered turn.
 assert [m['role'] for m in messages(wire)]==['system','user'] and '- "Tell me about barn 3."' in prompt(wire) and 'barn 2' not in prompt(wire)
 assert 'fences' not in prompt(wire) and 'leans east' not in json.dumps(messages(wire))
 assert 'EARLIER, THE PARTICIPANT SAID (already answered' in prompt(wire) and 'What the participant said earlier, listed at the top, is real' in prompt(wire)

async def test_another_sessions_conversation_is_not_continued():
 r,s,wire,frames=await service();play_only(s,'general-remark')
 s.history.append(spoken(r,'user','Old session words.')|{'session_id':'older'})
 await turn(s)
 assert 'Old session' not in json.dumps(messages(wire))

async def test_a_stale_count_from_the_companion_is_not_replayed_and_history_is_marked_out_of_date():
 r,s,wire,frames=await service(edges=3);play_only(s,EDGE)
 s.history+=[spoken(r,'user','How many edges so far?'),spoken(r,'assistant','The edge counter says 2 edges.')]
 await turn(s)
 assert 'How many edges so far?' in prompt(wire) and 'The edge counter says 2' not in json.dumps(messages(wire))  # Only the user's side is replayed...
 assert 'may be out of date, so only the values listed here are current' in prompt(wire) and 'Edges this session: 3' in prompt(wire)  # ...and labelled as possibly stale.

async def test_the_transcript_itself_is_untouched():
 r,s,wire,frames=await service(edges=3);play_only(s,EDGE)
 s.history.append(monologue(r,'An unprompted aside about fences.'))
 await turn(s)
 assert s.history[0]['content']=='An unprompted aside about fences.' and len(s.history)==2

async def test_the_opening_guidance_rotates_and_never_quotes_earlier_commentary():
 seen=set()
 for count in range(4):
  r,s,wire,frames=await service(edges=3);play_only(s,EDGE)
  s.history+=[monologue(r,f'Well, pull up a chair number {index}.') for index in range(count)]
  await turn(s)
  text=prompt(wire);seen.update(line for line in CARD_OPENINGS if line in text)
  assert 'pull up' not in text
 assert seen==set(CARD_OPENINGS)

@pytest.mark.parametrize('earlier,draft',[
 ('Well, I have a barn to mend.','Well, I have ten fences left too.'),
 ('The ledger says I am running a tight ship.','Still, running a tight ship suits me fine.')])
async def test_recycled_wording_earns_one_regeneration(earlier,draft):
 wire=[];fresh='Rain on tin always sounds like applause to me.'
 r,s,wire,frames=await service(wire=wire,transport=replies_in_turn(wire,[draft,fresh]));play_only(s,'general-remark');retrying(s)
 s.history.append(monologue(r,earlier))
 await turn(s)
 chats=[b for path,b in wire if path=='/api/chat']
 assert len(chats)==2 and draft not in json.dumps(chats[1]['messages']) and speech(frames)==fresh and 'take a different angle' in chats[1]['messages'][-1]['content']

async def test_recycled_wording_alone_never_loses_the_line():
 wire=[];draft='Well, I have ten fences left too.'
 r,s,wire,frames=await service(wire=wire,transport=replies_in_turn(wire,[draft,draft]));play_only(s,'general-remark');retrying(s)
 s.history.append(monologue(r,'Well, I have a barn to mend.'))
 await turn(s)
 assert len([p for p,b in wire if p=='/api/chat'])==2 and speech(frames)==draft and s.deck().snapshot()['counts']['delivered']==1

async def test_distinct_wording_is_not_regenerated():
 wire=[];line='Rain on tin always sounds like applause to me.'
 r,s,wire,frames=await service(wire=wire,transport=replies_in_turn(wire,[line]));play_only(s,'general-remark');retrying(s)
 s.history.append(monologue(r,'Well, I have a barn to mend.'))
 await turn(s)
 assert len([p for p,b in wire if p=='/api/chat'])==1 and speech(frames)==line

async def test_a_user_turn_is_never_regenerated_for_recycled_wording():
 wire=[];draft='Well, I have ten fences left too.'
 r,s,wire,frames=await service(wire=wire,transport=replies_in_turn(wire,[draft]));retrying(s)
 s.history.append(monologue(r,'Well, I have a barn to mend.'))
 s.request('How are the fences?',user=True);await s.task
 assert len([p for p,b in wire if p=='/api/chat'])==1

def test_a_follow_up_needs_something_the_participant_said():
 assert 'general-follow-up' not in drawn(deck(),context())
 assert 'general-follow-up' in drawn(deck(),context(has_conversation=True))

async def test_the_live_context_finds_a_conversation_only_from_the_participant_this_session():
 r,s,wire,frames=await service()
 now=r.clock.mono()
 assert s.deck_context(now).has_conversation is False
 s.history.append(monologue(r,'An aside.'));assert s.deck_context(now).has_conversation is False
 s.history.append(spoken(r,'user','Old')|{'session_id':'older'});assert s.deck_context(now).has_conversation is False
 s.history.append(spoken(r,'user','Hello there.'));assert s.deck_context(now).has_conversation is True


# Factual context

async def test_simulated_heart_rate_is_labelled_in_the_prompt():
 r,s,wire,frames=await service(trend='steady');play_only(s,'hr-steady')
 await turn(s)
 assert 'SIMULATED: it comes from a simulator' in prompt(wire)

async def test_a_physical_source_is_not_called_simulated():
 r,s,wire,frames=await service(trend='steady')
 r.state['devices'].update(simulated_hr=False,ble=True);[r.step(90,seconds=1) for _ in range(5)]
 play_only(s,'hr-steady');await turn(s)
 assert 'Observed from a connected sensor' in prompt(wire) and 'SIMULATED' not in prompt(wire)

async def test_a_declared_simulation_labels_all_of_its_telemetry_and_is_off_by_default():
 r,s,wire,frames=await service(edges=3);play_only(s,EDGE);await turn(s)
 assert 'values are simulated' not in prompt(wire)
 r,s,wire,frames=await service(edges=3);s.deck_settings=DeckSettings(enabled=True,countdown_seconds=0,simulated_session=True);play_only(s,EDGE);await turn(s)
 assert 'These values are simulated, not from a real person' in prompt(wire) and 'without calling them simulated' in prompt(wire)
 assert not re.search(r'\bsynthetic\b|\btest\b',prompt(wire),re.I)

def test_the_simulation_flag_comes_only_from_settings(tmp_path):
 store=SettingsStore(tmp_path);scope='ollama:x:m'
 assert load_model_settings(store,scope)[0].simulated_session is False
 store.write('deck-settings.json',{'schema_version':1,'models':{scope_key(scope):{'enabled':True,'simulated_session':True}}})
 assert load_model_settings(store,scope)[0].simulated_session is True and DeckSettings().simulated_session is False

@pytest.mark.parametrize('result,expected,absent',[
 ({'edges':10,'active_running_seconds':227,'termination':'manual_stop','completion_status':'user_reported','experience':'classic','goal':'edgetrain'},['The participant reported finishing. That is their own report','This session: 10 edges in 3 minutes 47 seconds.'],['Classic Tease','Edge Training']),
 ({'edges':4,'active_running_seconds':None,'termination':'manual_stop','completion_status':'unknown'},['no finish was reported','This session: 4 edges','Its length is not known'],['reported finishing']),
 ({'edges':None,'active_running_seconds':None,'termination':'other_stop','completion_status':'unknown'},['how it ended is not known','edge count and length not known'],[]),
])
async def test_the_closing_states_the_final_result_in_words(result,expected,absent):
 from companion_ai.context_compiler import closing_facts
 text='\n'.join(closing_facts(result))
 assert all(item in text for item in expected) and not any(item in text for item in absent) and not INTERNAL.search(text)


# Rejected commentary

async def test_a_rejected_card_is_recorded_but_is_not_shown_as_an_inference_failure():
 r,s,wire,frames=await service(edges=3,reply='You have reached 9 edges already.');play_only(s,EDGE)
 await turn(s)
 snapshot=s.deck().snapshot()
 assert not [f for f in frames if f['type'] in {'conversation_error','speech'}] and [f['reason'] for f in frames if f['type']=='response_suppressed']==['fidelity']
 assert snapshot['counts']['suppressed']==1 and snapshot['history'][-1]['reason']=='fidelity:wrong_edges' and s.director.counts['responses_suppressed']==1
 assert [(d['card_id'],d['codes']) for d in s.director.decisions if d['reason']=='deck_card_rejected']==[(EDGE,['wrong_edges'])]

async def test_a_rejected_card_stays_within_the_bounded_retry_lifecycle():
 r,s,wire,frames=await service(edges=3,reply='You have reached 9 edges already.');play_only(s,EDGE)
 for _ in range(6):
  r.step(None,seconds=4);s.pump()
  if s.task and not s.task.done():await s.task
  await asyncio.sleep(0)
 snapshot=s.deck().snapshot()
 assert snapshot['counts'].get('delivered',0)==0 and snapshot['counts']['suppressed']<=4 and EDGE in snapshot['retired']

async def test_a_genuine_inference_failure_on_a_card_is_still_an_error():
 import httpx
 def broken(request):
  if request.url.path=='/api/chat':return httpx.Response(500,text='down')
  from tests.ai.test_f25 import runtime
  return runtime([],'').handler(request)
 r,s,wire,frames=await service(edges=3,transport=httpx.MockTransport(broken));play_only(s,EDGE)
 await turn(s)
 assert [f['code'] for f in frames if f['type']=='conversation_error']==['generation_error'] and s.deck().snapshot()['counts']['failed']==1

async def test_a_users_rejected_reply_is_still_an_error():
 r,s,wire,frames=await service(edges=3,reply='The edge count is 9.')
 s.request('How many edges?',user=True);await s.task;await asyncio.sleep(0)
 assert [f['code'] for f in frames if f['type']=='conversation_error']==['grounding_violation'] and not [f for f in frames if f['type']=='response_suppressed']

async def test_a_legacy_reaction_keeps_its_existing_error():
 r,s,wire,frames=await service(edges=3,reply='The edge count is 9.')
 s.deck_settings=DeckSettings(enabled=False)
 s.request('Observed application event (not a user request): {}',event={'kind':'edge','priority':50,'at':r.clock.mono(),'event_id':'e1','session_id':r.state['session_id']});await s.task;await asyncio.sleep(0)
 assert [f['code'] for f in frames if f['type']=='conversation_error']==['grounding_violation']


async def test_a_repetition_retry_does_not_show_the_model_its_draft_or_raw_request():
 wire=[]
 line='Quiet barns keep their own stubborn counsel through the long afternoon.'
 r,s,wire,frames=await service(wire=wire,transport=replies_in_turn(wire,[line,line,'Rain on tin always sounds like applause to me.']))
 retrying(s)
 s.history.append(monologue(r,line));s.director.memory['event_responses'].append({'content':line,'at':r.clock.mono(),'event_id':None,'narrative_epoch':None})
 play_only(s,'general-remark')
 await turn(s)
 bodies=[b for path,b in wire if path=='/api/chat'];assert len(bodies)>=2
 for body in bodies:
  assert line not in json.dumps(body['messages']) and not INTERNAL.search(body['messages'][-1]['content'])


# Expression contract

@pytest.mark.parametrize('card_id,state',[(EDGE,{'edges':3}),('general-remark',{}),('hr-rising',{'trend':'rising'})])
async def test_a_card_prompt_opens_with_the_canonical_header_contract(card_id,state):
 r,s,wire,frames=await service(**state);play_only(s,card_id)
 await turn(s)
 assert prompt(wire).startswith(HEADER_REMINDER+'\nA MOMENT TO SPEAK') and prompt(wire).count('[[expression:ID]]')==1
 assert FORMAT_INSTRUCTION in messages(wire)[0]['content']

async def test_a_mission_and_a_retry_keep_the_contract():
 wire=[];line='Quiet barns keep their own stubborn counsel through the afternoon.'
 r,s,wire,frames=await service(wire=wire,transport=replies_in_turn(wire,[line,'Rain on tin always sounds like applause.']));play_only(s,'general-remark');retrying(s)
 s.history.append(monologue(r,line))
 await turn(s)
 bodies=[b for path,b in wire if path=='/api/chat']
 assert len(bodies)==2 and all(b['messages'][-1]['content'].startswith(HEADER_REMINDER) for b in bodies)

async def test_the_reminder_is_only_sent_when_headers_are_expected():
 r,s,wire,frames=await service(edges=3);play_only(s,EDGE)
 s.adapter.config=s.adapter.config.model_copy(update={'explicit_expressions':False})
 await turn(s)
 assert '[[expression' not in json.dumps(messages(wire))

async def test_a_user_turn_does_not_receive_the_card_reminder():
 r,s,wire,frames=await service(edges=3)
 s.request('How is it going?',user=True);await s.task
 assert HEADER_REMINDER not in json.dumps(messages(wire))

def test_the_contract_still_offers_all_twelve_expressions():
 assert len(EXPRESSIONS)==12 and all(item in FORMAT_INSTRUCTION for item in EXPRESSIONS) and '[[expression:ID]]' in HEADER_REMINDER and not any(item in HEADER_REMINDER for item in EXPRESSIONS)

MALFORMED=['[[happy:Daisy]]','[[happy:10]]','[[focused:ID]]','[[happy]]','[[HAPPY]]','[[ proud ]]','[[Expression:happy]]','[[expression: happy]]','[[expression:pride]]','[[expression]]','[expression:happy]','[happy:Daisy]','[happy]','[Proud]','[ expression : proud ]']
MID_LINE_PROSE=('[[happy]]','[[HAPPY]]','[[ proud ]]','[happy]','[Proud]')
def scan(chunks):
 stream=ExpressionStream(card=True)
 return (''.join(stream.feed(chunk) for chunk in chunks)+stream.finish()).strip(),stream

@pytest.mark.parametrize('tag',MALFORMED)
@pytest.mark.parametrize('split',[lambda text:[text],list],ids=['whole','per-character'])
def test_a_malformed_tag_is_never_visible_and_falls_back(tag,split):
 text,stream=scan(split(tag+'\nA quiet line.'))
 assert text=='A quiet line.' and stream.expression is None

@pytest.mark.parametrize('tag',MALFORMED)
def test_a_tag_after_a_valid_header_is_removed_and_mid_line_only_when_unmistakable(tag):
 assert scan(['[[expression:proud]]'+tag+'A quiet line.'])[0]=='A quiet line.' and scan(['[[expression:proud]]'+tag+'A quiet line.'])[1].expression=='proud'
 mid=scan(['Before '+tag+' after.'])[0]
 assert (tag in mid) if tag in MID_LINE_PROSE else ('[' not in mid)

@pytest.mark.parametrize('expression',EXPRESSIONS)
def test_every_canonical_header_is_still_accepted(expression):
 text,stream=scan(list(f'[[expression:{expression}]]\nA quiet line.'))
 assert text=='A quiet line.' and stream.expression==expression and stream.valid is True

@pytest.mark.parametrize('prose',['Plain [a] and [[ordinary]] brackets.','[sighs] Not a tag.','[happy days ahead','A [happy days] song.','An open [ bracket','['+'long prose '*10])
def test_ordinary_bracketed_prose_stays_visible(prose):
 assert scan(list(prose))[0]==prose.strip()

@pytest.mark.parametrize('tag',['[expression:hap','[happy:Dai','[[happy'])
def test_a_truncated_tag_is_not_released(tag):
 assert scan(['Line. '+tag])[0]=='Line.'

@pytest.mark.parametrize('reply,expression,source',[
 ('[[happy:Daisy]]\nA quiet line.',None,'fallback'),('[[happy]]\nA quiet line.',None,'fallback'),('[happy]\nA quiet line.',None,'fallback'),
 ('[[expression:proud]]\nA quiet line.','proud','model'),('[[expression:playful]]\nA quiet line.','playful','model')])
async def test_delivered_commentary_is_clean_and_uses_the_existing_fallback(reply,expression,source):
 r,s,wire,frames=await service(reply=reply);play_only(s,'general-remark')
 await turn(s)
 said=[f for f in frames if f['type']=='speech'][0]
 assert said['text']=='A quiet line.' and said['expression']==expression and said['expression_source']==source
 assert s.history[-1]['content']=='A quiet line.' and s.deck().snapshot()['counts']['delivered']==1


# Final dialogue refinement

@pytest.mark.parametrize('line',[
 'That is a fine synthetic test session.','Nice work for a simple test run.','Keep up with the synthetic rhythm.','A nice synthetic pulse.','Just synthetic data.','The edge counter finally ticked past three.',
 'Five edges in this simulated session.','Those simulated numbers look tidy.','The telemetry looks tidy.','A proper test-run of a day.'])
def test_test_language_is_caught_on_card_turns_only(line):
 assert card_language_violations(line,{'deck_card':{'lane':'normal'}})==['test_language'] and card_language_violations(line,{})==[]

@pytest.mark.parametrize('line',[
 'That simulated heart rate of 110 is climbing.','It is only simulated, so I will not read much into it.','That simulated pulse is holding steady.',
 'I will put you to the test, then.','The kitchen counter needs scrubbing.','A synthesis of habit and luck.',
 'Prove you can read a synthetic mind.','I dare you to guess which of my thousand synthetic memories I am using.','A masterclass in synthetic endurance.'])
def test_honest_attribution_and_ordinary_words_are_not_test_language(line):
 assert card_language_violations(line,{'deck_card':{'lane':'normal'}})==[]

async def test_test_language_gets_one_correction_and_the_correction_does_not_repeat_it():
 wire=[];fresh='Three already, and I reckon that suits you.'
 r,s,wire,frames=await service(edges=3,wire=wire,transport=replies_in_turn(wire,['A fine synthetic test session, this.',fresh]));play_only(s,EDGE)
 await turn(s)
 bodies=[b for path,b in wire if path=='/api/chat']
 assert len(bodies)==2 and speech(frames)==fresh and 'CORRECTION REQUIRED' in bodies[1]['messages'][0]['content']
 assert not re.search(r'synthetic|test_language',json.dumps(bodies[1]['messages']),re.I) and s.deck().snapshot()['counts']['delivered']==1

async def test_test_language_that_persists_is_suppressed_without_an_error():
 r,s,wire,frames=await service(edges=3,reply='A fine synthetic test session, this.');play_only(s,EDGE)
 await turn(s)
 assert not [f for f in frames if f['type'] in {'speech','conversation_error'}] and [f['reason'] for f in frames if f['type']=='response_suppressed']==['fidelity']
 assert s.deck().snapshot()['history'][-1]['reason']=='fidelity:test_language' and not [m for m in s.history if m['role']=='assistant']

async def test_a_user_may_still_hear_test_words_in_a_direct_reply():
 r,s,wire,frames=await service(edges=3,reply='It is a test run, as far as I can tell.')
 s.request('Is this a test?',user=True);await s.task;await asyncio.sleep(0)
 assert not [f for f in frames if f['type']=='conversation_error'] and [f for f in frames if f['type']=='speech'][0]['text']=='It is a test run, as far as I can tell.'

async def test_a_simulated_heart_rate_keeps_its_own_label_and_can_be_delivered():
 line='That simulated heart rate of 110 is climbing again.'
 r,s,wire,frames=await service(trend='rising',reply=line);s.deck_settings=DeckSettings(enabled=True,countdown_seconds=0,simulated_session=True);play_only(s,'hr-rising')
 await turn(s)
 assert 'If you mention it, call it simulated' in prompt(wire) and 'without calling them simulated' not in prompt(wire) and [f for f in frames if f['type']=='speech'][0]['text']==line

@pytest.mark.parametrize('draft',['A fine morning for it, I reckon.','Busy day today, I reckon.','This evening suits me.'])
async def test_a_named_time_of_day_earns_one_retry(draft):
 wire=[];fresh='I reckon the barn keeps its own hours.'
 r,s,wire,frames=await service(wire=wire,transport=replies_in_turn(wire,[draft,fresh]));play_only(s,'general-remark');retrying(s)
 await turn(s)
 bodies=[b for path,b in wire if path=='/api/chat']
 assert len(bodies)==2 and speech(frames)==fresh and 'no time of day' in bodies[1]['messages'][-1]['content'] and draft not in json.dumps(bodies[1]['messages'])

async def test_a_named_time_of_day_alone_never_loses_the_line():
 wire=[];draft='A fine morning for it, I reckon.'
 r,s,wire,frames=await service(wire=wire,transport=replies_in_turn(wire,[draft,draft]));play_only(s,'general-remark');retrying(s)
 await turn(s)
 assert speech(frames)==draft and s.deck().snapshot()['counts']['delivered']==1

async def test_the_grounding_guidance_reaches_the_model_and_keeps_room_to_play():
 r,s,wire,frames=await service(edges=3);play_only(s,EDGE)
 await turn(s)
 text=prompt(wire)
 assert 'with no time of day' in text and 'not their feelings, body, posture, past, family or character' in text and 'only as a guess or a tease' in text
 assert 'Your own world is welcome' in text and 'not as something that just happened' in text

@pytest.mark.parametrize('card',ALL,ids=lambda c:c.id)
def test_a_brief_reads_as_an_intention_not_as_system_language(card):
 assert not re.search(r'\b(?:verified|counter|session status|telemetry|source is a simulator|supplied)\b',card.brief,re.I)

@pytest.mark.parametrize('card_id,milestone',[('edges-3-reached','three-edge objective is complete'),('edges-7-reached','seven-edge objective is complete'),('edges-10-reached','ten-edge objective is complete')])
def test_mission_occasions_state_the_finished_result_with_no_ordinal(card_id,milestone):
 card=next(c for c in ALL if c.id==card_id)
 assert milestone in card.occasion and not re.search(r'\b(?:first|second|third|final)\b',card.occasion+card.brief,re.I)

def test_the_shuffle_seed_input_is_unchanged():
 assert DEFINITION.revision==2

@pytest.mark.parametrize('card',[c for c in ALL if c.eligibility.requires_hr],ids=lambda c:c.id)
def test_a_heart_rate_brief_leaves_the_source_to_the_reading_itself(card):
 assert not re.search(r'simulat',card.brief,re.I)

async def test_a_physical_reading_prompt_never_mentions_simulation():
 r,s,wire,frames=await service(trend='steady')
 r.state['devices'].update(simulated_hr=False,ble=True);[r.step(90,seconds=1) for _ in range(5)]
 play_only(s,'hr-steady');await turn(s)
 assert 'Observed from a connected sensor' in prompt(wire) and not re.search(r'simulat',prompt(wire),re.I)

