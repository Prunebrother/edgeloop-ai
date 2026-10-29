# SPDX-License-Identifier: AGPL-3.0-only
"""Deterministic narrative observations over the existing validated sample buffer.
No ingestion, device, inference, medical or session-control interfaces.
"""
from collections import deque
from hashlib import sha256
from statistics import median
from typing import Literal
from copy import deepcopy
from pydantic import Field,model_validator
from .models import StrictModel

REGISTRY={
 'rapid_rise':('Rapid BPM increase','Confirmed endpoint groups increased; no cause established.','hr, source, timestamp'),
 'rapid_fall':('Rapid BPM decrease','Confirmed endpoint groups decreased; no interpretation of relaxation.','hr, source, timestamp'),
 'sustained_elevation':('Sustained elevation','All samples exceed a labeled reference for the configured duration.','hr, timestamp, reference'),
 'recovery':('Return toward measured reference','Earlier elevation and a sustained decrease toward an earlier measured reference. Not clinical recovery.','hr, timestamp, earlier measured baseline'),
 'fluctuations':('Repeated fluctuations','Alternating excursions in three-sample medians; isolated spikes are rejected.','hr, timestamp'),
 'stable':('Stable measurement interval','Bounded observed range; not evidence of comfort or emotional calm.','hr, timestamp'),
 'session_milestone':('Original session events','Reuse validated engine transitions/counters, never redetect milestones.','validated original event'),
 'configuration':('Session selections','Reuse confirmed experience/goal/settings changes; existing selection debounce applies.','validated selection transition'),
 'quiet':('Quiet opportunity','A scheduling opportunity only; welcome/initiative gates still apply.','Director clock and conversation activity')}
PHYSIOLOGY=frozenset(list(REGISTRY)[:6])

class DetectorRule(StrictModel):
 enabled: bool=True
 threshold_bpm: float=Field(default=15.,ge=2,le=60)
 window_seconds: float=Field(default=30.,ge=5,le=1800)
 duration_seconds: float=Field(default=20.,ge=3,le=120)
 min_samples: int=Field(default=5,ge=5,le=128)
 cooldown_seconds: float=Field(default=120.,ge=5,le=1800)
 hysteresis_bpm: float=Field(default=4.,ge=1,le=15)
 significance: Literal['major','routine']='major'
 reference: Literal['resting_setting','recent_measured','narrative_threshold']='resting_setting'
 reference_bpm: float=Field(default=100.,ge=35,le=220)
 reversals: int=Field(default=3,ge=2,le=6)
 @model_validator(mode='after')
 def consistent(self):
  if self.duration_seconds>self.window_seconds:raise ValueError('Duration must not exceed the detection window')
  if self.hysteresis_bpm>=self.threshold_bpm:raise ValueError('Hysteresis must be smaller than the change threshold')
  return self

def defaults():
 return {k:DetectorRule(**v) for k,v in {
  'rapid_rise':{},'rapid_fall':{},
  'sustained_elevation':{'window_seconds':60.,'duration_seconds':30.},
  'recovery':{'window_seconds':60.,'duration_seconds':20.,'reference':'recent_measured'},
  'fluctuations':{'window_seconds':90.,'duration_seconds':30.,'threshold_bpm':10.,'hysteresis_bpm':3.,'min_samples':9},
  'stable':{'enabled':False,'threshold_bpm':4.,'hysteresis_bpm':1.,'window_seconds':60.,'duration_seconds':45.,'significance':'routine'},
  'session_milestone':{'cooldown_seconds':5.},'configuration':{'cooldown_seconds':5.},
  'quiet':{'window_seconds':120.,'duration_seconds':30.,'significance':'routine'}}.items()}

class EventConfig(StrictModel):
 schema_version: Literal[1]=1
 enabled: bool=True
 preset: Literal['quiet','balanced','observant','custom']='balanced'
 max_gap_seconds: float=Field(default=12.,ge=2,le=15)
 proactive_interval_seconds: float=Field(default=120.,ge=15,le=1800)
 detectors: dict[str,DetectorRule]=Field(default_factory=defaults)
 # Relevance affects scheduling only, never shared facts or safety notices.
 preferences: dict[str,dict[str,int]]=Field(default_factory=lambda:{'generic':{'physiology':1,'session':1,'configuration':1,'story':1},'evelyn':{'physiology':1,'session':1,'configuration':1,'story':1},'daisy':{'physiology':1,'session':1,'configuration':1,'story':1},'celeste':{'physiology':1,'session':1,'configuration':1,'story':1},'nova':{'physiology':1,'session':1,'configuration':1,'story':1}})
 @model_validator(mode='after')
 def known(self):
  if set(self.detectors)-set(REGISTRY):raise ValueError('Unknown detector')
  self.detectors=defaults()|self.detectors
  if any(self.detectors[k].window_seconds>120 for k in PHYSIOLOGY):raise ValueError('Measurement windows are limited to 120 seconds')
  if set(self.preferences)-{'generic','evelyn','daisy','celeste','nova'}:raise ValueError('Unknown relevance identity')
  for prefs in self.preferences.values():
   if prefs.get('story',1)>1:raise ValueError('Story relevance supports 0 (context only) or 1 (eligible)')
   if set(prefs)-{'physiology','session','configuration','story'} or any(type(v)is not int or not 0<=v<=2 for v in prefs.values()):raise ValueError('Relevance must be 0, 1 or 2 in a known category')
  self.preferences={k:{'physiology':1,'session':1,'configuration':1,'story':1}|self.preferences.get(k,{}) for k in ('generic','evelyn','daisy','celeste','nova')}
  return self

 def relevance(self,model,category):
  # Same exact character aliases as the existing artwork manifest, not a new personality profile.
  import json
  from pathlib import Path
  manifest=json.loads((Path(__file__).resolve().parents[1]/'src/assets/characters/manifest.json').read_text())
  identity=manifest['models'].get(model,'generic')
  return self.preferences.get(identity,self.preferences['generic']).get(category,1)

def preset(name):
 c=EventConfig();c.preset=name
 if name=='quiet':
  c.proactive_interval_seconds=300.
  for key in PHYSIOLOGY:c.detectors[key].significance='routine';c.detectors[key].cooldown_seconds=300.
 elif name=='observant':
  c.proactive_interval_seconds=90.
  for key in ('rapid_rise','rapid_fall'):c.detectors[key].threshold_bpm=12.;c.detectors[key].cooldown_seconds=90.
 elif name!='balanced':raise ValueError('Unknown preset')
 return c

class DerivedEvent(StrictModel):
 contract:Literal['edgeloop.narrative-event.v1']='edgeloop.narrative-event.v1'
 id:str
 kind:str
 detector_id:str
 category:Literal['derived','authoritative','scheduling']
 source:str
 simulated:bool
 session_id:str|None
 first_at_ms:int|None
 last_at_ms:int|None
 created_at_ms:int
 change_bpm:float|None=None
 first_bpm:float|None=None
 last_bpm:float|None=None
 reference_bpm:float|None=None
 reference_kind:str|None=None
 unit:Literal['BPM']|None=None
 window_seconds:float
 sample_count:int=Field(ge=0,le=512)
 quality:Literal['sufficient_validated_samples','validated_transition','scheduling_only']
 significance:Literal['major','routine','critical']
 evidence:str
 config_revision:int
 rule:DetectorRule|None=None
 @model_validator(mode='after')
 def provenance(self):
  if self.category=='derived':
   if self.detector_id not in PHYSIOLOGY or self.kind!=self.detector_id or self.quality!='sufficient_validated_samples' or self.sample_count<5 or self.source not in {'simulator','BLE sensor'} or self.significance=='critical':raise ValueError('Invalid derived provenance')
   if self.first_at_ms is None or self.last_at_ms is None or self.first_at_ms>=self.last_at_ms or self.unit!='BPM':raise ValueError('Invalid measurement evidence')
  if self.category=='scheduling' and (self.sample_count or self.quality!='scheduling_only' or self.significance=='critical'):raise ValueError('Invalid scheduling provenance')
  return self

class EventIntelligence:
 def __init__(self,config=None,clock=None):
  import time
  self.clock=clock or time.monotonic;self.config=config or EventConfig();self.revision=1;self.applied_at=float('-inf')
  self.history=deque(maxlen=48);self.segment=None;self.latches={};self.last_emit={};self.commentary_at={};self.diagnostics={};self.last_significant=self.clock();self.quiet_key=None;self.error=None
 def configure(self,config):
  self.config=config;self.revision+=1;self.applied_at=self.clock();self.latches.clear();self.quiet_key=None;self.error=None
  # Earlier observations remain diagnostic history; only future samples may trigger new rules.
 def reason(self,key,reason):
  self.diagnostics.setdefault(key,{})['last_suppression']=reason
 def decision(self,event_id,decision,cooldown=0):
  for record in reversed(self.history):
   if record['event']['id']==event_id:
    if not record.get('stages') or record['stages'][-1]['decision']!=decision:
     record['stages']=(record.get('stages',[])+[{'decision':decision,'at':self.clock()}])[-12:]
    record['decision']=decision;record['cooldown_until']=self.clock()+max(0,cooldown);return
 def record(self,event):
  self.history.append({'event':event.model_dump(),'decision':'context_only' if event.significance=='routine' else 'detected'})
  if event.significance!='routine':self.last_significant=self.clock()
  return event
 def build(self,key,observation,samples,**values):
  now=self.clock();source=observation.hr_source();first=samples[0] if samples else None;last=samples[-1] if samples else None
  stamp=lambda sample:int(getattr(sample,'at_ms',observation.wall()*1000-(now-sample[0])*1000)) if sample else None
  start,end=stamp(first),stamp(last)
  identity=f'{observation.session_id}:{observation.measurement_segment}:{key}:{start}:{end}:{self.revision}'
  return DerivedEvent(id=sha256(identity.encode()).hexdigest()[:24],kind=key,detector_id=key,category='derived',source=source,simulated=source=='simulator',session_id=observation.session_id,first_at_ms=start,last_at_ms=end,created_at_ms=int(observation.wall()*1000),window_seconds=round(last[0]-first[0],3) if samples else 0,sample_count=len(samples),quality='sufficient_validated_samples',significance=self.config.detectors[key].significance,evidence=REGISTRY[key][1],config_revision=self.revision,rule=self.config.detectors[key],unit='BPM',**values)
 def evaluate(self,o):
  now=self.clock();segment=(o.session_id,o.measurement_segment)
  if segment!=self.segment:self.segment=segment;self.latches.clear();self.last_emit.clear();self.quiet_key=None
  if not self.config.enabled:
   for key in PHYSIOLOGY:self.reason(key,'event_intelligence_disabled')
   return []
  if o.status not in {'RUNNING','RAMPDOWN'} or not o.hr_current():
   for key in PHYSIOLOGY:self.reason(key,'inactive_or_unavailable_measurement')
   return []
  all_samples=[s for s in o.samples if s[0]>=self.applied_at and now-s[0]<=180]
  for index in range(len(all_samples)-1,0,-1):
   if all_samples[index][0]-all_samples[index-1][0]>self.config.max_gap_seconds:
    all_samples=all_samples[index:];break
  emitted=[]
  for key in REGISTRY:
   if key not in PHYSIOLOGY:continue
   rule=self.config.detectors[key]
   if not rule.enabled:self.reason(key,'detector_disabled');continue
   ss=[s for s in all_samples if now-s[0]<=rule.window_seconds]
   needed=max(rule.min_samples,9 if key=='fluctuations' else 5)
   if len(ss)<needed:self.reason(key,'insufficient_samples');continue
   if any(b[0]<=a[0] or b[0]-a[0]>self.config.max_gap_seconds for a,b in zip(ss,ss[1:])):self.reason(key,'sampling_gap');continue
   span=ss[-1][0]-ss[0][0]
   if now-ss[-1][0]>5:self.reason(key,'stale_last_sample');continue
   start=median(s[1] for s in ss[:3]);end=median(s[1] for s in ss[-3:]);delta=end-start
   valid=False;reset=False;ref=None;ref_kind=None
   if key in {'rapid_rise','rapid_fall'}:
    signed=delta if key=='rapid_rise' else -delta
    valid=span>=rule.duration_seconds and signed>=rule.threshold_bpm and all((s[1]-start if key=='rapid_rise' else start-s[1])>=rule.threshold_bpm-rule.hysteresis_bpm for s in ss[-3:])
    reset=signed<=rule.threshold_bpm-rule.hysteresis_bpm
   elif key=='sustained_elevation':
    if rule.reference=='resting_setting':ref=(o.report.get('details') or {}).get('resting_bpm');ref_kind='configured_resting_setting_not_measured_baseline'
    elif rule.reference=='narrative_threshold':ref=rule.reference_bpm;ref_kind='narrative_threshold_not_safety_limit'
    else:
     early=[s for s in all_samples if s[0]<ss[-1][0]-rule.duration_seconds]
     if len(early)>=3:ref=median(s[1] for s in early[:3]);ref_kind='earlier_measured_reference'
    tail=[s for s in ss if s[0]>=ss[-1][0]-rule.duration_seconds]
    if ref is None:self.reason(key,'reference_unavailable');continue
    valid=len(tail)>=rule.min_samples and tail[-1][0]-tail[0][0]>=rule.duration_seconds and all(s[1]>=ref+rule.threshold_bpm for s in tail)
    reset=end<ref+rule.threshold_bpm-rule.hysteresis_bpm
    if valid:ss=tail;start=median(s[1] for s in ss[:3]);delta=end-start
   elif key=='recovery':
    early=[s for s in all_samples if s[0]<ss[0][0]]
    if len(early)<3:self.reason(key,'no_earlier_measured_reference');continue
    ref=median(s[1] for s in early[:3]);ref_kind='earlier_measured_reference'
    elevated=sum(s[1]>=ref+rule.threshold_bpm for s in ss[:-3])>=2
    valid=elevated and span>=rule.duration_seconds and start-end>=rule.threshold_bpm and abs(end-ref)<=rule.hysteresis_bpm
    reset=abs(end-ref)>rule.hysteresis_bpm*2
   elif key=='stable':
    tail=[s for s in ss if s[0]>=ss[-1][0]-rule.duration_seconds]
    spread=max(s[1] for s in tail)-min(s[1] for s in tail)
    valid=len(tail)>=rule.min_samples and tail[-1][0]-tail[0][0]>=rule.duration_seconds and spread<=rule.threshold_bpm
    reset=spread>rule.threshold_bpm+rule.hysteresis_bpm
    if valid:ss=tail
   elif key=='fluctuations':
    smoothed=[median(s[1] for s in ss[i:i+3]) for i in range(len(ss)-2)]
    anchor=smoothed[0];direction=0;turns=0
    for value in smoothed[1:]:
     if direction==0:
      if abs(value-anchor)>=rule.threshold_bpm:direction=1 if value>anchor else -1;anchor=value
     elif (value-anchor)*direction>=0:anchor=value
     elif abs(value-anchor)>=rule.threshold_bpm:turns+=1;direction*=-1;anchor=value
    valid=span>=rule.duration_seconds and turns>=rule.reversals
    reset=turns==0
   if reset:self.latches[key]=False
   if not valid:self.reason(key,'condition_not_met');continue
   if self.latches.get(key):self.reason(key,'hysteresis_latched');continue
   if now-max(self.last_emit.get(key,float('-inf')),self.commentary_at.get(key,float('-inf')))<rule.cooldown_seconds:self.reason(key,'detector_cooldown');continue
   event=self.build(key,o,ss,change_bpm=round(delta,2),first_bpm=float(start),last_bpm=float(end),reference_bpm=float(ref) if ref is not None else None,reference_kind=ref_kind)
   self.latches[key]=True;self.last_emit[key]=now;self.diagnostics[key]={'last_detection_at_ms':event.created_at_ms,'last_suppression':None}
   emitted.append(self.record(event))
  return emitted
 def authoritative(self,kind,details,o,significance):
  key='configuration' if kind in {'experience_changed','goal_changed','mode_changed','intensity_changed','threshold_changed'} else 'session_milestone'
  rule=self.config.detectors[key];critical=significance=='critical'
  level='critical' if critical else rule.significance if significance=='major' and self.config.enabled and rule.enabled else 'routine'
  event=DerivedEvent(id=details['event_id'],kind=kind,detector_id=key,category='authoritative',source='original_edgeloop',simulated=o.hr_source()=='simulator',session_id=o.session_id,first_at_ms=details.get('at_ms'),last_at_ms=details.get('at_ms'),created_at_ms=int(o.wall()*1000),window_seconds=0,sample_count=0,quality='validated_transition',significance=level,evidence=details.get('evidence') or 'Validated original transition',config_revision=self.revision,rule=rule)
  self.diagnostics[key]={'last_detection_at_ms':event.created_at_ms,'last_suppression':None}
  self.record(event)
  return event,critical or self.config.enabled and rule.enabled
 def quiet(self,o,last_activity,scope):
  key='quiet';rule=self.config.detectors[key];now=self.clock()
  if not self.config.enabled or not rule.enabled:self.reason(key,'detector_disabled');return None
  if not o.fresh() or now-max(last_activity,self.last_significant)<rule.window_seconds:self.reason(key,'quiet_interval_not_elapsed');return None
  if scope==self.quiet_key:self.reason(key,'opportunity_already_considered');return None
  if now-max(self.last_emit.get(key,float('-inf')),self.commentary_at.get(key,float('-inf')))<rule.cooldown_seconds:self.reason(key,'detector_cooldown');return None
  self.quiet_key=scope;self.last_emit[key]=now
  event=DerivedEvent(id=sha256(str((scope,self.revision)).encode()).hexdigest()[:24],kind='quiet_interval',detector_id=key,category='scheduling',source='Director clock',simulated=False,session_id=o.session_id,first_at_ms=None,last_at_ms=None,created_at_ms=int(o.wall()*1000),window_seconds=rule.window_seconds,sample_count=0,quality='scheduling_only',significance=rule.significance,evidence='No significant event or conversation during configured interval; availability and willingness are not established.',config_revision=self.revision)
  return self.record(event)
 def snapshot(self):
  now=self.clock()
  records=deepcopy(list(self.history)[-16:])
  for record in records:record['cooldown_remaining_seconds']=round(max(0,record.pop('cooldown_until',0)-now),1)
  return {'config':self.config.model_dump(),'revision':self.revision,'error':self.error,'detectors':[{'id':key,'name':v[0],'description':v[1],'required_fields':v[2],'minimum_samples':max(self.config.detectors[key].min_samples,9 if key=='fluctuations' else 5) if key in PHYSIOLOGY else 0,**self.diagnostics.get(key,{}),'cooldown_remaining_seconds':round(max(0,self.config.detectors[key].cooldown_seconds-(now-max(self.last_emit.get(key,float('-inf')),self.commentary_at.get(key,float('-inf'))))),1)} for key,v in REGISTRY.items()], 'recent_events':records}

def load_config(store):
 try:
  raw=store.read('event-intelligence.json',{})
  if isinstance(raw,dict) and raw.get('schema_version')==0:raw=raw|{'schema_version':1}
  return EventConfig.model_validate(raw),None
 except (ValueError,OSError):return EventConfig(enabled=False),'Invalid or unsupported Event Intelligence configuration; observations disabled. Existing file preserved.'
