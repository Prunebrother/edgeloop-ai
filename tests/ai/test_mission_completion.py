# SPDX-License-Identifier: AGPL-3.0-only
"""A mission completes an objective. Only the finalized result ends the session. Mocked inference."""
import asyncio,json,re
import pytest
from companion_ai.event_deck import DeckSettings
from companion_ai.fidelity import card_language_violations,premature_session_end
from tests.ai.test_event_deck_content import ALL,DEFINITION,prompt,replies_in_turn,service
from tests.ai.test_event_deck_integration import finish

MISSIONS=[('edges-3-reached',3,{'edges-7','edges-10'}),('edges-7-reached',7,{'edges-3','edges-10'}),('edges-10-reached',10,{'edges-3','edges-7'})]
MISSION={'deck_card':{'lane':'mission'}}
def only_mission(s,done):
 deck=s.deck();deck._start_done=True;deck._counter_baseline={'edges':0,'seconds':0};deck._activated|=done
async def turn(s):
 s.pump();await s.task;await asyncio.sleep(0)
def spoken(frames):return [f['text'] for f in frames if f['type']=='speech']
def chats(wire):return [b for path,b in wire if path=='/api/chat']

# Taken from real-model drafts, or the same claim in other words
ENDED=['Ten edges completed, marking the end of your current Edge Training session with a flourish.',
 'Ten edges completed, marking the successful conclusion of your Edge Training under the Classic Tease experience.',
 'The tenth edge has fallen, marking the completion of your edge training.',
 'You are officially finished, my dear.','Ten edges completed; the job is done and you earned this quiet moment of rest.',
 "Ten edges done, and I'm calling this job finished with a smile.",'Ten edges down, and I say that job is officially finished.',
 'The session is over.',"The session's over, darling.",'This session has ended.','Your training is complete.','This Classic Tease is finished.',
 'We are done here.',"You've finished your Edge Training.","That's a wrap.",'I think we can call it a day.','You earned your rest.']
ALLOWED=['Ten edges done, and the session carries on.','That objective is complete, and we keep going.','The mission is complete.','Mission complete, darling.',
 "You've finished the mission, and there is more to come.",'That goal is done.','The milestone is finished.',"The session isn't over yet.",'The session is not over.',
 'Before this session ends, I want more.','When the session is over, we can talk.','Is the session over?','I finished the ledger.','The training goal is met.',
 'Ten edges cleared, a fine haul.','I will not call it a day.','The fence is finished.']

@pytest.mark.parametrize('line',ENDED)
def test_an_ending_claim_is_recognised(line):
 assert premature_session_end(line) and card_language_violations(line,MISSION)==['premature_session_end']

@pytest.mark.parametrize('line',ALLOWED)
def test_a_completed_objective_or_a_negated_ending_is_allowed(line):
 assert not premature_session_end(line) and card_language_violations(line,MISSION)==[]

@pytest.mark.parametrize('lane',['session_end','normal','session_start'])
def test_the_check_applies_to_missions_only(lane):
 assert card_language_violations('The session is over.',{'deck_card':{'lane':lane}})==[]

def test_a_user_turn_is_not_checked():
 assert card_language_violations('The session is over.',{})==[]

@pytest.mark.parametrize('card_id,edges,done',MISSIONS)
def test_a_mission_card_states_the_objective_and_claims_no_ending(card_id,edges,done):
 card=next(c for c in ALL if c.id==card_id)
 assert 'objective is complete' in card.occasion
 assert not re.search(r'finished|job|complete[sd]? the session|ended',card.occasion+card.brief,re.I)

def test_only_the_closing_brief_announces_an_ending():
 closing=next(c for c in ALL if c.id=='closing');assert closing.occasion=='The session has ended.' and 'session is over' in closing.brief

@pytest.mark.parametrize('card_id,edges,done',MISSIONS)
async def test_a_running_mission_is_told_the_session_continues(card_id,edges,done):
 r,s,wire,frames=await service(edges=edges);only_mission(s,done)
 await turn(s)
 text=prompt(wire)
 assert next(c for c in ALL if c.id==card_id).occasion in text and f'the participant has reached {edges} edges' in text
 assert 'Session status: still running. Completing an objective does not end the session.' in text and 'This session:' not in text
 assert s.state and r.state['status']=='RUNNING'

async def test_a_mission_after_running_does_not_claim_the_session_is_still_running():
 r,s,wire,frames=await service(edges=10,status='RAMPDOWN');only_mission(s,{'edges-3','edges-7'})
 await turn(s)
 assert 'objective is complete' in prompt(wire) and 'still running' not in prompt(wire)

async def test_a_normal_card_receives_no_mission_line():
 from tests.ai.test_event_deck_content import play_only
 r,s,wire,frames=await service(edges=3);play_only(s,'edge-count-first')
 await turn(s)
 assert 'completes an objective' not in prompt(wire)

async def test_an_ending_claim_gets_one_correction_and_the_retry_is_delivered():
 wire=[];good='Ten edges, and that objective is yours. On we go.'
 r,s,wire,frames=await service(edges=10,wire=wire,transport=replies_in_turn(wire,['Ten edges, and the session is over.',good]));only_mission(s,{'edges-3','edges-7'})
 await turn(s)
 assert len(chats(wire))==2 and spoken(frames)==[good] and 'that the session is over' in chats(wire)[1]['messages'][0]['content']
 assert 'premature_session_end' not in json.dumps(chats(wire)[1]['messages']) and 'the session is over.' not in json.dumps(chats(wire)[1]['messages'])
 assert s.deck().snapshot()['counts']['delivered']==1 and r.state['status']=='RUNNING'

async def test_a_persistent_ending_claim_is_never_delivered_and_shows_no_error():
 r,s,wire,frames=await service(edges=10,reply='Ten edges, and the session is over.');only_mission(s,{'edges-3','edges-7'})
 await turn(s)
 assert spoken(frames)==[] and not [f for f in frames if f['type']=='conversation_error'] and [f['reason'] for f in frames if f['type']=='response_suppressed']==['fidelity']
 assert s.deck().snapshot()['history'][-1]['reason']=='fidelity:premature_session_end' and not [m for m in s.history if m['role']=='assistant']

async def test_a_mission_does_not_finalize_or_close_anything():
 r,s,wire,frames=await service(edges=10,reply='Ten edges, and that objective is yours.');only_mission(s,{'edges-3','edges-7'})
 await turn(s)
 assert s.deck().snapshot()['counts']['delivered']==1 and not s.deck().closing_pending and r.state['status']=='RUNNING' and not r.observation.completed_sessions

async def closing_service(reply):
 r,s,wire,frames=await service(edges=4,seconds=600,reply=reply)
 s.deck_settings=DeckSettings(enabled=True,countdown_seconds=0);s.deck_definition=DEFINITION;s.deck()._start_done=True;s.deck()._counter_baseline={'edges':4,'seconds':600}
 return r,s,wire,frames

async def test_the_closing_may_announce_the_ending_once_the_result_is_final():
 line='The session is over, and four edges is your final tally.'
 r,s,wire,frames=await closing_service(line)
 finish(r,s);s.pump();await s.task;await asyncio.sleep(0)
 text=prompt(wire)
 assert spoken(frames)[-1]==line and 'This session: 4 edges in 10 minutes.' in text and 'still running' not in text

async def test_the_closing_keeps_the_participants_report_attributed_to_them():
 r,s,wire,frames=await closing_service('The session is over.')
 s.enqueue('session_ended',70,{'event_id':'end:reported','session_id':r.observation.session_id,'category':'authoritative','at_ms':int(r.clock.wall()*1000),'session_result':{'edges':4,'active_running_seconds':600,'termination':'manual_stop','completion_status':'user_reported'},'evidence':'test'})
 r.step(85,status='IDLE')
 s.pump();await s.task;await asyncio.sleep(0)
 assert 'The participant reported finishing. That is their own report, not a measurement.' in prompt(wire) and 'This session: 4 edges in 10 minutes.' in prompt(wire)

async def test_no_closing_is_generated_while_the_session_is_running():
 r,s,wire,frames=await service(edges=10,reply='Ten edges, and that objective is yours.');only_mission(s,{'edges-3','edges-7'})
 await turn(s)
 assert not [b for b in chats(wire) if 'This session:' in b['messages'][-1]['content']] and 'closing' not in [h['card_id'] for h in s.deck().snapshot()['history']]
