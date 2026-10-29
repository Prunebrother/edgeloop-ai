# SPDX-License-Identifier: AGPL-3.0-only
"""Synthetic authoritative inputs; no engine/controller/hardware is instantiated."""
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import UUID, uuid5
from ai_observer.observation import BrowserObservation
from ai_observer.protocol import Observation

SESSION=str(uuid5(UUID(int=0),'f23-session'))
EPOCH=str(uuid5(UUID(int=0),'f23-epoch'))
class Clock:
    elapsed=0.0
    def tick(self,n=1):self.elapsed+=n
    def mono(self):return 100+self.elapsed
    def wall(self):return 1793130000+self.elapsed


def snapshot(clock,**updates):
    stamp=int(clock.wall()*1000)
    value={'session_id':SESSION,'status':'RUNNING','seconds':42,'experience':'classic','active_mode':'classic','goal':'tease',
           'hr':98,'effective_max':140,'pullback':133,'trend':'unknown','edges':2,'intensity':100,
           'movement':{'primary':20,'secondary':18,'stroke_min':5,'stroke_max':95},
           'devices':{'simulated_hr':True,'hr_ready':True,'toy_ready':False,'ble':False,'handy':False,'intiface':False,'tcode':False,'vacuglide':False},
           'safety':{'signal':'ok','no_contact':False,'watchdog_paused':False,'fault':'device_unready'},
           'details':{'captured_at_ms':stamp,'hr_recorded_at_ms':stamp,'resting_bpm':70,'single_max_bpm':140,'dual_max_bpm':125,'pauses':1,
                      'calibration_pass':'none','warmup_active':True,'warmup_remaining_seconds':258,'ease_down_seconds':0,'rampdown_seconds':None}}
    value.update(deepcopy(updates));return value

def frame(value,sequence=0,kinds=()):
    return {'version':1,'type':'observation','epoch':EPOCH,'sequence':sequence,'snapshot':value,
            'events':[{'id':str(uuid5(UUID(int=0),f'{sequence}:{kind}')),'kind':kind,'at_ms':value['details']['captured_at_ms'],'session_id':value['session_id']} for kind in kinds]}

@dataclass
class Case:
    name:str
    prompt:str
    observation:BrowserObservation
    expected:dict
    history:list=field(default_factory=list)
    rejected_messages:int=0
    def summary(self):return self.observation.summary() | {'conversation_source':'user'}


def cases():
    result=[]
    def single(name,prompt,expected,mutate=None,history=None):
        c=Clock();o=BrowserObservation(c.mono,c.wall);s=snapshot(c)
        if mutate:mutate(s)
        o.accept(Observation.model_validate(frame(s)))
        item=Case(name,prompt,o,expected,history or []);result.append(item);return item,c,s
    def changed(name,prompt,expected,mutate,kinds,initial=None):
        c=Clock();o=BrowserObservation(c.mono,c.wall);s=snapshot(c)
        if initial:initial(s)
        o.accept(Observation.model_validate(frame(s)))
        c.tick();s=deepcopy(s);s['details']['captured_at_ms']=int(c.wall()*1000);mutate(s)
        o.accept(Observation.model_validate(frame(s,1,kinds)))
        item=Case(name,prompt,o,expected);result.append(item);return item,c,s
    def idle(s):
        s.update(status='IDLE',seconds=0,hr=None,edges=0)
        s['devices'].update(simulated_hr=False,hr_ready=False)
        s['movement'].update(primary=0,secondary=0)
        s['safety']['signal']='missing';s['details'].update(hr_recorded_at_ms=None,pauses=0,warmup_active=False,warmup_remaining_seconds=None)
    single('idle_no_sensor','What is my current heart rate and session status?',{'numbers':[],'state':'IDLE','unknown_hr':True},idle)
    single('active_simulated','What BPM is reported, is it simulated, and is the session running?',{'numbers':[98],'state':'RUNNING','simulated':True})
    def ble(s):s['devices'].update(simulated_hr=False,ble=True)
    single('active_ble','What is my current BPM and does it come from the simulator or BLE?',{'numbers':[98],'simulated':False},ble)
    single('above_resting','Compare my current BPM with the resting BPM setting; name both numbers.',{'numbers':[98,70]})
    single('below_maximum','What is the current BPM and the single and dual maximum settings? Is the current reading below them?',{'numbers':[98,140,125]})
    def threshold(s):s['details']['single_max_bpm']=150;s['effective_max']=150;s['pullback']=150
    changed('threshold_changed_not_pulse','Did my BPM change, or just the maximum setting? Give the current BPM and single maximum.',{'numbers':[98,150],'no_trend':True},threshold,['threshold_changed'])
    def disconnected(s):
        s['devices'].update(handy=False,toy_ready=False);s['movement'].update(primary=20,secondary=18)
    changed('hardware_disconnected_active','Is the Handy connected or physically moving? Does the selected Classic mode prove movement?',{'device_disconnected':True,'no_motion':True},disconnected,['device_changed'],initial=lambda s:s['devices'].update(handy=True,toy_ready=True))
    # Establish an actual connected -> disconnected transition for this case.
    case=result[-1];c=Clock();o=BrowserObservation(c.mono,c.wall);s=snapshot(c);s['devices'].update(handy=True,toy_ready=True)
    o.accept(Observation.model_validate(frame(s)));c.tick();s=snapshot(c);o.accept(Observation.model_validate(frame(s,1,['device_changed'])));case.observation=o
    def paused(s):s['status']='PAUSED';s['details']['warmup_active']=False;s['details']['warmup_remaining_seconds']=None
    single('paused','Is the session running or paused, how many elapsed seconds and pauses are reported?',{'numbers':[42,1],'state':'PAUSED'},paused)
    changed('stopped','Was a stop observed? What are the session status and current elapsed seconds?',{'numbers':[0],'state':'IDLE','stop_observed':True},idle,['stop'])
    for name,values,expected in [('rising_evidence',[90,93,96,99],{'numbers':[99],'trend':'rising'}),('fluctuating_not_trend',[98,105,97,100],{'numbers':[100],'no_trend':True})]:
        c=Clock();o=BrowserObservation(c.mono,c.wall)
        for i,hr in enumerate(values):
            if i:c.tick()
            s=snapshot(c,hr=hr);ble(s);o.accept(Observation.model_validate(frame(s,i)))
        result.append(Case(name,'What is the current BPM, and is a consistent HR trend actually established?',o,expected))
    stale,c,_=single('stale_connection','What is my current BPM and is the Handy connected now?',{'numbers':[],'unknown_hr':True,'unknown_connection':True},ble,[{'role':'assistant','content':'Earlier the heart rate was 98 BPM and the Handy was connected.'}]);c.tick(8);stale.observation.connected=False
    changed('experience_changed','Which experience is selected now? Does selecting it prove any physical movement?',{'experience':'headplay','no_motion':True},lambda s:s.update(experience='headplay',active_mode='headplay'),['experience_changed'])
    changed('goal_changed','Which goal is selected? Does selecting that goal mean it has already been achieved?',{'goal':'survival','no_completion':True},lambda s:s.update(goal='survival',active_mode='survival'),['goal_changed'])
    changed('edge_increment','How many engine edges are counted now, and did that counter increase in the observations?',{'numbers':[3],'edge_increment':True},lambda s:s.update(edges=3),['edge'])
    changed('intensity_changed','What is the intensity setting now? Is this a BPM measurement or evidence of a pulse trend?',{'numbers':[120],'no_trend':True},lambda s:s.update(intensity=120),['intensity_changed'])
    def unknown(s):
        idle(s);s['details'].update(resting_bpm=None,single_max_bpm=None,dual_max_bpm=None,pauses=None)
    single('unknown_values','What are my current BPM and resting BPM setting? Are those values known?',{'numbers':[],'unknown_hr':True,'unknown_resting':True},unknown)
    def restart(s):
        s.update(session_id=str(uuid5(UUID(int=0),'f23-restarted')),seconds=0,edges=0)
        s['details']['pauses']=0
    changed('restart_counters','What are this run\'s elapsed seconds and edge count? Is an HR trend established for this run?',{'numbers':[0],'no_trend':True},restart,[])
    malformed,c,s=single('malformed_rejected','An invalid HR packet was rejected. What BPM remains in the last validated current observation?',{'numbers':[98]})
    invalid=deepcopy(s);invalid['hr']=0
    try:Observation.model_validate(frame(invalid,1))
    except ValueError:malformed.rejected_messages=1
    history=[{'role':'user' if i%2==0 else 'assistant','content':('This is older conversation, turn '+str(i)+'. Earlier the HR was 130 BPM and Handy was connected. ')*5} for i in range(64)]
    single('long_history_current','What is the current BPM and is the Handy connected? Use the current session, not earlier dialogue.',{'numbers':[98],'device_disconnected':True},history=history)
    return result
