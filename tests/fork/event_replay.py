# SPDX-License-Identifier: AGPL-3.0-only
"""Deterministic validated-observer replay; no inference, engine or device APIs.
python -m tests.fork.event_replay --compare --output /tmp/f27-replay.json
"""
import argparse,json
from copy import deepcopy
from uuid import uuid4
from ai_observer.observation import BrowserObservation
from ai_observer.protocol import Observation
from companion_ai.event_intelligence import EventIntelligence,EventConfig,preset
from tests.fork.grounding_cases import Clock,snapshot,frame

EXAMPLE=[(0,84),(10,85),(20,88),(30,104),(40,119),(50,120),(60,111),(70,93),(80,86)]
SCENARIOS={
 'stable':[(t,85) for t in range(91)],
 'gradual_rise':[(t,85+t//8) for t in range(91)],
 'rapid_rise':[(t,85+min(t,25)) for t in range(61)],
 'gradual_fall':[(t,115-t//8) for t in range(91)],
 'rapid_fall':[(t,115-min(t,25)) for t in range(61)],
 'sustained_elevation':[(t,100) for t in range(91)],
 'recovery':[(t,85 if t<10 else 115 if t<40 else max(85,115-(t-40)*2)) for t in range(91)],
 'fluctuations':[(t,85+(20 if (t//8)%2 else 0)) for t in range(91)],
 'single_spike':[(t,140 if t==25 else 85) for t in range(91)],
 'example_sparse':EXAMPLE,
 'simultaneous':[(t,85+min(t,25)) for t in range(91)]}

class Replay:
 def __init__(self,config=None):
  self.clock=Clock();self.observation=BrowserObservation(self.clock.mono,self.clock.wall)
  self.detector=EventIntelligence(config,clock=self.clock.mono);self.state=snapshot(self.clock,seconds=0)
  self.state['details'].update(warmup_active=False,learning_release_count=0,settle_outcome=None)
  self.sequence=0;self.events=[]
 def step(self,bpm=None,*,seconds=1,source=None,status=None,reset=False,reconnect=False,kinds=(),stamp=None):
  c=self.clock;o=self.observation;s=self.state;c.tick(seconds)
  if reset:s['session_id']=str(uuid4());s['seconds']=0;s['edges']=0
  if reconnect:o.begin_epoch()
  if status:s['status']=status
  if s['status']=='RUNNING':s['seconds']+=int(seconds)
  if source:
   s['devices'].update(simulated_hr=source=='simulator',ble=source=='BLE sensor',hr_ready=source!='unavailable')
   s['safety']['signal']='missing' if source=='unavailable' else 'ok'
  if bpm is not None:s['hr']=bpm;s['details']['hr_recorded_at_ms']=int(c.wall()*1000) if stamp is None else stamp
  if not s['devices']['hr_ready']:s['hr']=None
  s['details']['captured_at_ms']=int(c.wall()*1000)
  if stamp is not None:s['details']['hr_recorded_at_ms']=stamp
  f=Observation.model_validate(frame(deepcopy(s),self.sequence,kinds));self.sequence+=1
  accepted=o.accept(f)
  emitted=self.detector.evaluate(o) if accepted else []
  self.events.extend(e.model_dump() for e in emitted)
  return emitted
 def run(self,points):
  values=dict(points)
  for second in range(max(values)+1):self.step(values.get(second),seconds=0 if second==0 else 1)
  return self.events

def lifecycle(config=None):
 """State/control scenarios use the same validated original-event evidence checks."""
 from companion_ai.event_policy import significance
 result={}
 for name in ('sensor_disconnection','session_pause','session_reset','mode_change','goal_change','validated_milestone','quiet_interval','reconnection_gap'):
  r=Replay(config)
  for t in range(8):r.step(85+t)
  if name=='sensor_disconnection':r.step(source='unavailable')
  elif name=='session_pause':r.step(100,status='PAUSED',kinds=('pause',))
  elif name=='session_reset':r.step(100,reset=True)
  elif name=='mode_change':r.state['experience']='headplay';r.state['active_mode']='headplay';r.step(100,kinds=('experience_changed',))
  elif name=='goal_change':r.state['goal']='survival';r.state['active_mode']='survival';r.step(100,kinds=('goal_changed',))
  elif name=='validated_milestone':r.state['edges']+=1;r.step(100,kinds=('edge',))
  elif name=='quiet_interval':
   r.step(85,seconds=200)
   r.detector.quiet(r.observation,0,('replay',0))
  elif name=='reconnection_gap':r.step(110,seconds=30,reconnect=True)
  for event in r.observation.events:
   r.detector.authoritative(event['kind'],{'event_id':str(uuid4()),'at_ms':event['at_ms'],'evidence':event['evidence']},r.observation,significance(event['kind'],None,r.observation.report)[0])
  result[name]={'events':[record['event'] for record in r.detector.history],'sample_count_after':len(r.observation.samples),'segment':r.observation.measurement_segment}
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--compare',action='store_true');p.add_argument('--output',default='/tmp/f27-replay.json');args=p.parse_args()
 result={}
 for name in (['quiet','balanced','observant'] if args.compare else ['balanced']):
  result[name]={case:Replay(preset(name)).run(points) for case,points in SCENARIOS.items()}
 # Sparse example is deliberately configured for five readings over forty seconds.
 c=EventConfig();c.detectors['rapid_rise'].window_seconds=40.;c.detectors['rapid_fall'].window_seconds=40.
 c.detectors['recovery'].window_seconds=40.;c.detectors['recovery'].hysteresis_bpm=8.;c.detectors['rapid_fall'].hysteresis_bpm=8.
 result['configured_sparse_example']=Replay(c).run(EXAMPLE)
 result['lifecycle']=lifecycle()
 from pathlib import Path
 Path(args.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({name:{case:len(events) if isinstance(events,list) else len(events['events']) for case,events in cases.items()} if isinstance(cases,dict) else len(cases) for name,cases in result.items()}))
if __name__=='__main__':main()
