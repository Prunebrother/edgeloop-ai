"""AGPL-3.0-only. Browser observations and bounded evidence; never a session engine."""
from collections import deque, OrderedDict
from copy import deepcopy
from dataclasses import dataclass
import time
from companion_ai.director import ConversationDirector
from companion_ai.grounding import Fact, SessionFacts, HistoricalEvent

@dataclass(frozen=True)
class ObservedDevice:
    moving: bool | None = None
    velocity: int | None = None
    pattern: str = 'unknown'

class Measurement(tuple):
    def __new__(cls,at,bpm,at_ms):
        value=super().__new__(cls,(at,bpm));value.at_ms=at_ms;return value

class BrowserObservation:
    def __init__(self, clock=time.monotonic, wall=time.time, journal=None):
        self.clock,self.wall=clock,wall
        self.journal=journal
        self.report=None;self.received=None;self.connected=False;self.sequence=-1;self.session_id=None
        self.invalid_sample_stamp=None;self.measurement_segment=0;self.trend_segment_at=self.clock()
        self.samples=deque(maxlen=512);self.retired_sessions=deque(maxlen=64)
        self.completed_sessions=deque(maxlen=8);self.model_scope=None;self.event_diagnostics=deque(maxlen=32)
        self.events=deque(maxlen=32);self.seen_events=OrderedDict();self.accepted_event_ids=set()
        self.connection_epoch=0
        self.capture_delay=0;self.last_sample=None;self.sample_source=None;self.last_capture=None;self.segment_started=self.clock()

    def begin_epoch(self):
        self.connection_epoch+=1
        self.connected=False;self.sequence=-1;self.received=None
        self.measurement_segment+=1;self.trend_segment_at=self.clock()
        self.samples.clear();self.events.clear();self.seen_events.clear();self.accepted_event_ids.clear()
        self.last_sample=None;self.sample_source=None;self.last_capture=None;self.segment_started=self.clock()

    def accept(self, message):
        if message.sequence<=self.sequence or message.snapshot.session_id in self.retired_sessions:return False
        report=message.snapshot.model_dump(exclude_unset=True);details=report.get('details') or {}
        captured=details.get('captured_at_ms')
        if captured is not None and (captured>self.wall()*1000+1000 or self.last_capture is not None and captured<self.last_capture):return False
        previous=self.report;gap=not self.fresh()
        if details and previous and self.session_id==report['session_id'] and report['status']!='IDLE':
            if report['seconds']<previous['seconds'] or report['edges']<previous['edges']:return False
            old_details=previous.get('details') or {}
            if details.get('pauses') is not None and old_details.get('pauses') is not None and details['pauses']<old_details['pauses']:return False
        changed=self.session_id!=report['session_id']
        if changed:
            if self.session_id is not None:self.retired_sessions.append(self.session_id)
            self.events.clear();self.seen_events.clear()
        if changed or gap or previous and previous['status']!=report['status']:
            self.measurement_segment+=1;self.trend_segment_at=self.clock()
            self.samples.clear();self.last_sample=None;self.segment_started=self.clock()
        self.sequence=message.sequence;self.report=report;self.session_id=report['session_id']
        self.received=self.clock();self.connected=True;self.last_capture=captured
        self.capture_delay=max(0,self.wall()-captured/1000) if captured is not None else 0
        source=self.hr_source()
        if source!=self.sample_source or not self.hr_current():
            self.measurement_segment+=1;self.trend_segment_at=self.clock()
            self.samples.clear();self.last_sample=None;self.segment_started=self.clock()
        self.sample_source=source
        stamp=details.get('hr_recorded_at_ms')
        if stamp is not None and self.last_sample is not None and (stamp<self.last_sample or stamp==self.last_sample and previous and report.get('hr')!=previous.get('hr')):
            self.invalid_sample_stamp=stamp;self.samples.clear();self.measurement_segment+=1
        elif stamp is not None and self.invalid_sample_stamp is not None and stamp>self.invalid_sample_stamp:self.invalid_sample_stamp=None
        if self.hr_current() and stamp is not None and stamp!=self.last_sample:
            at=self.received-max(0,details['captured_at_ms']-stamp)/1000-self.capture_delay
            if self.samples and (at<=self.samples[-1][0] or at-self.samples[-1][0]>15):
                self.samples.clear();self.measurement_segment+=1;self.trend_segment_at=at
            elif self.samples and at-self.samples[-1][0]>5:self.trend_segment_at=at
            if self.clock()-at<=5 and at>=self.segment_started-.001:self.samples.append(Measurement(at,self.report['hr'],stamp))
            self.last_sample=stamp
        self.samples=deque((s for s in self.samples if self.clock()-s[0]<=180),maxlen=512)
        self.accepted_event_ids.clear()
        for event in message.events:
            reason=('duplicate_identity' if event.id in self.seen_events else
                    'wrong_session' if event.session_id is not None and event.session_id!=self.session_id else
                    'stale_source_timestamp' if event.at_ms is not None and (captured is None or event.at_ms>captured or captured-event.at_ms>5000) else None)
            evidence=None if reason else self.event_evidence(event.kind,previous,report,gap)
            self.event_diagnostics.append({'id':event.id,'kind':event.kind,'session_id':event.session_id,
                'sequence':message.sequence,'source_at_ms':event.at_ms,'received_at_ms':int(self.wall()*1000),
                'decision':reason or ('accepted_transition' if evidence else 'unproven_transition')})
            if reason:continue
            self.seen_events[event.id]=True
            if len(self.seen_events)>256:self.seen_events.popitem(last=False)
            if evidence:self.accepted_event_ids.add(event.id)
            if evidence:self.events.append({'event_id':event.id,'kind':event.kind,'evidence':evidence,'session_id':self.session_id,'sequence':self.sequence,'at_ms':event.at_ms,'received':self.clock()-(max(0,captured-event.at_ms)/1000+self.capture_delay if captured is not None and event.at_ms is not None else 0)})
        if previous and previous['session_id']==report['session_id'] and previous['status']!='IDLE' and report['status']=='IDLE':
            terminal=details.get('terminal_outcome')
            pre_reset=bool(terminal and report['seconds']>=previous['seconds'] and report['edges']>=previous['edges'])
            final=report if pre_reset else previous
            final_stamp=(final.get('details') or {}).get('captured_at_ms')
            complete=bool(pre_reset and captured is not None and not gap)
            classification=('calibration_completed' if terminal=='calibration_completed' and any(e.kind=='completion_accepted' and e.id in self.accepted_event_ids for e in message.events) else
                            'accidental_release' if terminal=='premature_release' or any(e.kind=='came_early' and e.id in self.accepted_event_ids for e in message.events) else
                            'manual_stop' if terminal=='manual_stop' else 'cancelled' if terminal=='cancelled' else
                            'stop_with_protection_observed' if previous['safety']['watchdog_paused'] or previous['safety']['fault'] in {'signal_lost','no_contact'} else 'cancelled_or_unclassified_stop')
            self.completed_sessions.append({'session_id':self.session_id,'model_scope':self.model_scope,
                'active_running_seconds':final['seconds'] if complete else None,
                'last_verified_running_ticks':final['seconds'], 'edges':final['edges'],
                'experience':final['experience'],'goal':final['goal'],'termination':classification,
                'final_verified_at_ms':final_stamp,'received_at_ms':int(self.wall()*1000),
                'protection_observed':previous['safety']['watchdog_paused'] or previous['safety']['fault'] in {'signal_lost','no_contact'},
                'sensor_available':self.hr_current(),'measurement_source':self.hr_source(),
                'milestones':[{k:v for k,v in e.items() if k in {'event_id','kind','evidence','sequence','at_ms'}} for e in list(self.events)[-6:]],
                'completeness':'final_counter_captured' if complete else 'final_duration_unavailable',
                'confidence':'verified_engine_ticks' if complete else 'partial_observation',
                'wall_clock_seconds':None,'paused_seconds':None})
        if self.journal is not None:
            summaries=list(self.completed_sessions)[-1:] if previous and previous['session_id']==report['session_id'] and previous['status']!='IDLE' and report['status']=='IDLE' else []
            self.journal.observe(self,previous,summaries)
        return True

    def completed(self):
        # Read-only facts shared only with the model observing their termination.
        return [deepcopy({k:v for k,v in s.items() if k!='model_scope'}) | {
            'historical':True,'age_seconds':round(max(0,self.wall()-s['received_at_ms']/1000),1),
            'stale':self.wall()*1000-s['received_at_ms']>86400000}
            for s in self.completed_sessions if s['model_scope']==self.model_scope][-3:]

    @staticmethod
    def event_evidence(kind,p,r,gap):
        if not p or gap:return None
        if p['session_id']!=r['session_id']:
            return 'session status changed IDLE -> RUNNING' if kind=='session_started' and p['status']=='IDLE' and r['status']=='RUNNING' else None
        if kind in {'stop','pause','session_resumed','session_started'}:
            allowed={'stop':r['status']=='IDLE' and p['status']!='IDLE','pause':r['status']=='PAUSED' and p['status'] in {'RUNNING','RAMPDOWN'},'session_resumed':p['status']=='PAUSED' and r['status'] in {'RUNNING','RAMPDOWN'},'session_started':p['status']=='IDLE' and r['status']=='RUNNING'}
            return f"session status changed {p['status']} -> {r['status']}" if allowed[kind] else None
        if kind=='completion_accepted':
            outcome=(r.get('details') or {}).get('terminal_outcome')
            if p['status'] not in {'RUNNING','PAUSED','RAMPDOWN'}:return None
            if outcome=='calibration_completed' and p['active_mode']=='calibrate' and r['status']=='IDLE':return 'Accepted calibration completion; engine ended the session after the confirmed action (not a physiological diagnosis)'
            if outcome=='survival_restart' and (p.get('details') or {}).get('terminal_outcome')!='survival_restart' and p['active_mode']=='survival' and r['status']=='RUNNING':return 'Accepted Survival completion; original engine restarted its climb, session counter continues (not session termination)'
            return None
        if kind=='came_early':
            before=(p.get('details') or {}).get('learning_release_count')
            after=(r.get('details') or {}).get('learning_release_count')
            ending=(r.get('details') or {}).get('settle_outcome')=='premature_release' or r['status']=='IDLE'
            if p['status'] in {'RUNNING','PAUSED'} and p['active_mode'] not in {'survival','calibrate'} and isinstance(before,int) and isinstance(after,int) and after>before and ending:
                return f'engine accepted premature release: learning counter {before} -> {after}; ending settle or stop confirmed'
            return None
        if kind=='edge':return f"engine edge counter increased {p['edges']} -> {r['edges']}" if r['edges']>p['edges'] else None
        fields={'experience_changed':'experience','goal_changed':'goal','intensity_changed':'intensity'}
        if kind in fields:
            f=fields[kind];return f'{f} changed {p[f]} -> {r[f]}' if r[f]!=p[f] else None
        if kind=='mode_changed' and (r['experience']!=p['experience'] or r['goal']!=p['goal']):return 'selected experience or goal changed'
        if kind=='threshold_changed' and any((r.get('details') or {}).get(k)!=(p.get('details') or {}).get(k) for k in ['single_max_bpm','dual_max_bpm']):return 'maximum setting changed; this is not an HR measurement'
        if kind=='device_changed' and r['devices']!=p['devices']:return 'reported device connections/readiness changed'
        if kind=='signal_lost' and r['safety']['signal']=='stale' and p['safety']['signal']!='stale':return 'HR signal became stale'
        if kind=='signal_restored' and r['safety']['signal']=='ok' and p['safety']['signal']=='stale':return 'HR signal became available'
        if kind=='no_contact' and r['safety']['no_contact'] and not p['safety']['no_contact']:return 'HR sensor reported no contact'
        if kind=='milestone' and r['seconds']//300>p['seconds']//300:return 'engine elapsed counter crossed a five-minute boundary'
        return None

    def age(self):return None if self.received is None else max(0,self.clock()-self.received)+self.capture_delay
    def fresh(self):return self.connected and self.age() is not None and self.age()<=5
    def hr_source(self):
        if not self.report:return 'unavailable'
        d=self.report['devices']
        return 'simulator' if d['simulated_hr'] else 'BLE sensor' if d['ble'] else 'unavailable'
    def hr_current(self):
        if not self.fresh() or self.report['hr'] is None:return False
        if self.invalid_sample_stamp is not None and (self.report.get('details') or {}).get('hr_recorded_at_ms')==self.invalid_sample_stamp:return False
        r=self.report
        if not r['devices']['hr_ready'] or r['safety']['no_contact'] or r['safety']['signal']!='ok' or (r.get('details') or {}).get('hr_live') is False:return False
        if self.hr_source()=='simulator':return True # The original simulator is a persistent manual slider.
        d=r.get('details') or {};stamp=d.get('hr_recorded_at_ms')
        return self.hr_source()=='BLE sensor' and stamp is not None and (d['captured_at_ms']-stamp)/1000+(self.age() or 0)<=5
    @property
    def status(self):return self.report['status'] if self.report else 'UNKNOWN'
    @property
    def hr(self):return self.report['hr'] if self.hr_current() else None
    @property
    def trend(self):
        samples=[(t,b) for t,b in self.samples if self.clock()-t<=15 and t>=self.trend_segment_at][-12:]
        if not self.hr_current() or len(samples)<4 or samples[-1][0]-samples[0][0]<3:return 'unknown'
        changes=[b[1]-a[1] for a,b in zip(samples,samples[1:])];delta=samples[-1][1]-samples[0][1]
        if delta>=3 and all(d>=0 for d in changes):return 'rising'
        if delta<=-3 and all(d<=0 for d in changes):return 'falling'
        if max(b for _,b in samples)-min(b for _,b in samples)<=2:return 'steady'
        return 'unknown'
    @property
    def emergency(self):return False # The original application alone owns emergency state.
    @property
    def device(self):return ObservedDevice() # Engine percentages do not establish physical movement.
    def snapshot(self):
        return {'source':'original_edgeloop','read_only':True,'observation_fresh':self.fresh(),'status':self.status,
                'seconds':self.report['seconds'] if self.report else None,'hr':self.hr,'trend':self.trend,
                'device':self.device.__dict__,'reported_state':deepcopy(self.report)}

    def canonical(self):
        r=self.report or {};d=r.get('details') or {};current=self.fresh();facts={};captured=d.get('captured_at_ms')
        valid_samples=[(t,b) for t,b in self.samples if self.clock()-t<=15 and t>=self.trend_segment_at][-12:] if self.hr_current() else []
        span=valid_samples[-1][0]-valid_samples[0][0] if len(valid_samples)>1 else 0
        def add(name,value,kind,source,unit=None,available=True,reason='unavailable',observed=...):
            known=value is not None;live=known and current and available
            facts[name]=Fact(value=value,unit=unit,kind=kind,source=source,known=known,current=live,
                             observed_at_ms=captured if observed is ... else observed,reason='current' if live else 'stale' if not current else reason)
        add('hr',r.get('hr'),'measurement' if self.hr_source()=='BLE sensor' else 'derived','state.sensorHr; '+self.hr_source(),'BPM',self.hr_current(),'unavailable, held or no contact',d.get('hr_recorded_at_ms'))
        add('hr_source',self.hr_source() if r else None,'status','devices.simulated_hr / devices.ble')
        for name,key in [('resting_bpm','minHr'),('single_max_bpm','maxHr'),('dual_max_bpm','dualMaxHr')]:add(name,d.get(name),'setting','validated '+key+' DOM input via original sanitizeHrLimits / dual bounds','BPM')
        upstream={'effective_max':'state.effectiveMaxHr','pullback':'state.edgeTriggerHr','status':'state.sessionStatus',
                  'seconds':'state.sessionSeconds','experience':'state.teaseMode','active_mode':'state.activeMode',
                  'goal':'state.gameMode or tease','intensity':'50 + state.intensityValue','edges':'state.edges'}
        for name,unit,kind in [('effective_max','BPM','derived'),('pullback','BPM','derived'),('status',None,'status'),('seconds','seconds','status'),('experience',None,'setting'),('active_mode',None,'status'),('goal',None,'setting'),('intensity','percent','setting'),('edges','count','status')]:add(name,r.get(name),kind,upstream[name],unit)
        add('pauses',d.get('pauses'),'status','state.pauses','count')
        add('trend',self.trend if self.trend!='unknown' else None,'derived','4+ distinct HR samples, span >=3 seconds, monotonic direction; 15-second window',reason='mixed samples; no consistent direction' if len(valid_samples)>=4 and span>=3 else 'insufficient timestamped sample evidence')
        for name,key in [('primary','strokerSpeed'),('secondary','prostateSpeed')]:add(name,(r.get('movement') or {}).get(name),'engine_value','state.'+key+'; NOT hardware readback','percent')
        add('physical_motion',None,'measurement','not collected; no hardware feedback available')
        sources={'toy_ready':'hardwareReadiness().toyReady (assigned stimulation availability)','ble':'isBleConnected()','handy':'handyConnected','intiface':'isIntifaceConnected() (transport only)','tcode':'isTCodeConnected() (transport only)','vacuglide':'isVacuglideConnected()'}
        for name,source in sources.items():add(name,(r.get('devices') or {}).get(name),'status',source)
        for name in ['calibration_pass','warmup_active','warmup_remaining_seconds','ease_down_seconds','rampdown_seconds']:add(name,d.get(name),'derived' if name.startswith('warmup') else 'status','original EdgeLoop phase fields / warm-up badge projection','seconds' if name.endswith('seconds') else None)
        events=[HistoricalEvent(**{k:v for k,v in e.items() if k!='received'},age_seconds=round(max(0,self.clock()-e['received']),1)) for e in self.events if self.clock()-e['received']<=120][-6:] if current else []
        return SessionFacts(session_id=self.session_id,sequence=self.sequence,captured_at_ms=captured,age_seconds=None if self.age() is None else round(self.age(),2),current=current,facts=facts,events=events,trend_samples=len(valid_samples),trend_span_seconds=max(0,round(span,2))).model_dump()

    def summary(self):
        return {'source':'original_edgeloop','read_only':True,'observation_fresh':self.fresh(),
                'observation_age_seconds':None if self.age() is None else round(self.age(),1),
                'state':deepcopy(self.report) if self.fresh() else None,'canonical_session':self.canonical(),
                'completed_sessions':self.completed(),
                'availability':'current observation' if self.fresh() else 'unavailable; never present prior readings as current'}

class ObserverDirector(ConversationDirector):
    def context(self,snapshot,prompt,events,user,memory_enabled=True):
        result=super().context(snapshot,prompt,events,user,memory_enabled)
        # Shared dialogue pacing remains; only this validated canonical data is model evidence.
        return result | {key:snapshot[key] for key in ('source','read_only','observation_fresh','observation_age_seconds','state','availability','canonical_session','completed_sessions') if key in snapshot}
