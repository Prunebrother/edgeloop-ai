# SPDX-License-Identifier: AGPL-3.0-only
"""Completion checkpoints and one final reaction; synthetic facts, no hardware/model calls."""
from copy import deepcopy
import json,time
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from ai_observer.server import create_app
from companion_ai.context import compose_messages
from companion_ai.context_compiler import ContextConfig
from companion_ai.models import AIConfig,SpeechPolicy
from companion_ai.session_journal import SessionJournal
from companion_ai.storage import SettingsStore
from tests.ai.test_f284 import setup,stop
from tests.ai.test_f251 import change
from tests.fork.test_observer import TOKEN,ORIGIN,auth,until,frame,snapshot


def test_completion_checkpoint_persists_without_calibration_and_finalizes_once(tmp_path):
 c,o,s,j=setup(tmp_path)
 s['details']['completion_reported']=True
 s,_=change(c,o,s,'edge',seconds=321,edges=7)
 saved=SessionJournal(SettingsStore(tmp_path)).data['records']
 assert len(saved)==1 and saved[0]['completion_status']=='user_reported'
 assert saved[0]['active_running_seconds']==321 and saved[0]['edges']==7
 assert saved[0]['experience']==s['experience'] and saved[0]['goal']==s['goal']
 # Cancelled calibration makes no observer write: report is already durable.
 assert j.active is not None and s['session_id'] not in j.data.get('closed_sessions',[])
 s,_=change(c,o,s,'edge');assert len(j.data['records'])==1
 stop(c,o,s);record=SessionJournal(SettingsStore(tmp_path)).data['records'][0]
 assert record['completion_status']=='user_reported' and len(j.data['records'])==1
 assert o.completed_sessions[-1]['completion_status']=='user_reported'


def test_completion_checkpoint_respects_recording_permission(tmp_path):
 c,o,s,j=setup(tmp_path,False,False);s['details']['completion_reported']=True
 change(c,o,s,'edge');assert j.data['records']==[]

class Adapter:
 mode='ollama';config=AIConfig(model='nova-narrative-v1:latest')
 def __init__(self):self.calls=[]
 async def reply(self,summary,prompt,history):
  self.calls.append((summary,prompt,history))
  return 'We can leave this session here.'


def send(ws,epoch,sequence,s,kind=None):
 s=deepcopy(s)
 s.setdefault('details',{})['captured_at_ms']=int(time.time()*1000)
 # Existing protocol requires the whole Details shape, so use the fixture below.
 event=[{'id':str(uuid4()),'kind':kind,'session_id':s['session_id'],'at_ms':s['details']['captured_at_ms']}] if kind else []
 payload=frame(epoch,sequence,s,event)
 from ai_observer.protocol import Observation
 Observation.model_validate(payload)
 ws.send_json(payload);assert until(ws,'observation_ack')['accepted']
 return s


def final_session(tmp_path,*,reported=False,outcome='manual_stop',muted=False,quiet=False,protect=False):
 from tests.fork.grounding_cases import Clock,snapshot as detailed_snapshot
 a=Adapter();app=create_app(TOKEN,tmp_path,adapter=a)
 app.state.speech.policy=SpeechPolicy(enabled=not muted,event_responses=True)
 app.state.journal.command('configure',recording=True,ai_access=False)
 with TestClient(app) as client:
  with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
   epoch=auth(ws)['epoch'];s=detailed_snapshot(Clock());s.update(status='RUNNING',seconds=321,edges=7,experience='headplay',goal='calibrate' if reported else 'tease',active_mode='calibrate' if reported else 'headplay')
   s['details'].update(hr_recorded_at_ms=None,completion_reported=reported,warmup_active=False)
   s['hr']=None;s['devices'].update(hr_ready=False,simulated_hr=False,toy_ready=True,handy=True);s['safety']['fault']='none'
   s=send(ws,epoch,0,s)
   speech=app.state.speech
   speech.director.memory['quiet_requested']=quiet
   speech.director.last_spoken=speech.clock();speech.director.last_reaction=speech.clock()
   speech.last_event=speech.clock();speech.last_user=speech.clock();speech.busy_until=speech.clock()+100
   if protect:s['safety'].update(signal='stale',fault='signal_lost',watchdog_paused=True)
   s['status']='IDLE';s['details']['terminal_outcome']=outcome
   send(ws,epoch,1,s,'stop')
   # Without a deck no closing reaction is generated in any case; Director 2.0's Closing card owns it.
   time.sleep(.05)
   # Repeated terminal/reset frames cannot enqueue another closing turn.
   s['seconds']=s['edges']=0;send(ws,epoch,2,s,'stop');time.sleep(.35)
   assert len(app.state.journal.data['records'])==1
 return a,app

@pytest.mark.parametrize('reported',[False,True])
@pytest.mark.parametrize('outcome',['manual_stop','other_stop'])
def test_final_result_is_recorded_without_a_legacy_reaction_and_closing_prompt_keeps_facts_and_privacy(tmp_path,reported,outcome):
 a,app=final_session(tmp_path,reported=reported,outcome=outcome)
 assert not a.calls
 # The final result is still recorded with its facts; Director 2.0's Closing card speaks it (see test_event_deck_integration).
 result=app.state.speech.director.aggregates['session_ended']['session_result']
 assert result['active_running_seconds']==321 and result['edges']==7
 assert result['experience']=='headplay' and result['completion_status']==('user_reported' if reported else 'unknown')
 assert not app.state.journal.data['ai_access'] and not app.state.speech.pending

@pytest.mark.parametrize('kwargs',[{'muted':True},{'quiet':True},{'protect':True},{'outcome':'safety_stop'}])
def test_no_closing_reaction_for_muted_quiet_or_safety_stop(tmp_path,kwargs):
 a,_=final_session(tmp_path,**kwargs);assert a.calls==[]


@pytest.mark.parametrize('interruption',['signal_lost','emergency_stop','disconnect'])
async def test_safety_or_disconnect_cancels_closing_generation(interruption):
 import asyncio
 from tests.ai.test_f285 import rig
 gate=asyncio.Event()
 class Slow(Adapter):
  async def reply(self,summary,prompt,history):
   self.calls.append(summary);await gate.wait();return 'This closing reply must never be shown.'
 r,s,a,frames=rig(Slow());r.observation.report['status']='IDLE';r.observation.report['safety']['fault']='none'
 event={'kind':'session_ended','session_id':r.observation.session_id,'event_id':'closing','session_result':{'completion_status':'unknown'}}
 result=s.request('Closing session',False,event=event);assert result['accepted']
 await asyncio.sleep(0)
 if interruption=='disconnect':r.observation.connected=False
 else:s.safety(interruption)
 gate.set();await asyncio.gather(*tuple(s.tasks),return_exceptions=True)
 assert not any(f['type']=='speech' and f.get('source')=='event' for f in frames)
 await s.close()


def test_emergency_after_termination_interrupts_and_no_closing_reply_starts_without_the_deck(tmp_path):
 import asyncio,threading
 from tests.fork.grounding_cases import Clock,snapshot as detailed_snapshot
 release=threading.Event();frames=[]
 class Slow(Adapter):
  async def reply(self,summary,prompt,history):
   self.calls.append(summary)
   while not release.is_set():await asyncio.sleep(.01)
   return 'This reply must be cancelled.'
 a=Slow();app=create_app(TOKEN,tmp_path,adapter=a)
 original=app.state.speech.publish
 def publish(message):frames.append(message);original(message)
 app.state.speech.publish=publish
 try:
  with TestClient(app) as client:
   with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
    epoch=auth(ws)['epoch'];s=detailed_snapshot(Clock())
    s['devices'].update(toy_ready=True,handy=True);s['safety']['fault']='none'
    s['details'].update(hr_recorded_at_ms=None,warmup_active=False)
    s['hr']=None;s=send(ws,epoch,0,s)
    s['status']='IDLE';s['details']['terminal_outcome']='manual_stop'
    s=send(ws,epoch,1,s,'stop')
    # Without a deck no closing reply starts, and an emergency marker afterwards still interrupts.
    s['details']['terminal_outcome']='safety_stop';send(ws,epoch,2,s)
    release.set();time.sleep(.05)
    assert not a.calls and any(f['type']=='speech_cancel' for f in frames)
    assert not any(f['type'] in ('response_start','speech') and f.get('source')=='event' for f in frames)
 finally:release.set()
