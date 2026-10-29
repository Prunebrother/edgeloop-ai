# SPDX-License-Identifier: AGPL-3.0-only
"""CPU-only conversation policy. No provider, character or device-controller imports."""
from collections import Counter, deque
from difflib import SequenceMatcher
import json
import logging
import re
import time
from typing import Annotated, Literal
from pydantic import Field
from .models import StrictModel
from .event_policy import REACTIVE_EVENTS, SELECTION_EVENTS

Origin = Literal['real_user', 'assistant_dialogue', 'edgeloop_telemetry', 'simulated_telemetry', 'tool_result', 'safety_event', 'system_event']
Category = Literal['observation', 'significant_event', 'conversational_opportunity', 'safety_event']
logger = logging.getLogger(__name__)

class DirectorConfig(StrictModel):
    enabled: bool = True
    spontaneous_enabled: bool = True
    narrative_initiative_enabled: bool = True
    max_consecutive_unsolicited: int = Field(default=2, ge=1, le=4)
    selection_debounce_seconds: float = Field(default=2.0, ge=.2, le=10)
    reaction_interval_seconds: float = Field(default=4.0, ge=0, le=60)
    reaction_user_grace_seconds: float = Field(default=2.0, ge=0, le=30)
    spontaneous_interval_seconds: float = Field(default=120., ge=0, le=3600)
    user_idle_before_spontaneous_seconds: float = Field(default=30., ge=0, le=600)
    topic_protection_seconds: float = Field(default=90., ge=0, le=600)
    dedup_seconds: float = Field(default=90., ge=0, le=600)
    aggregation_seconds: float = Field(default=30., ge=1, le=300)
    category_cooldowns: dict[Literal['physiology','edge','device','session','tool'], Annotated[float, Field(ge=0, le=3600)]] = Field(default_factory=lambda: {'physiology':180.,'edge':120.,'device':90.,'session':120.,'tool':60.})
    repetition_threshold: float = Field(default=.82, ge=.5, le=1)
    regenerate_once: bool = True
    max_regeneration_seconds: float = Field(default=8., ge=.1, le=30)


def silent_response(text):
    return text.strip().casefold() in {'[silence]', 'silence'}


def normalize(text):
    return ' '.join(re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.casefold()))


def questions(text):
    return [normalize(q) for q in re.findall(r'[^.!?]*\?', text) if normalize(q)]


def repetition(text, previous):
    current=normalize(text);words=current.split()
    best=phrase=question_score=0.;exact=False
    qs=questions(text)
    for old in previous[-12:]:
        prior=normalize(old)
        if not current or not prior:continue
        exact |= current==prior
        a,b=set(words),set(prior.split())
        similarity=max(SequenceMatcher(None,words[:128],prior.split()[:128],autojunk=False).ratio(),len(a&b)/max(1,len(a|b)))
        best=max(best,similarity)
        grams={' '.join(words[i:i+5]) for i in range(max(0,len(words)-4))}
        oldwords=prior.split();oldgrams={' '.join(oldwords[i:i+5]) for i in range(max(0,len(oldwords)-4))}
        phrase=max(phrase,len(grams&oldgrams)/max(1,min(len(grams),len(oldgrams))))
        for q in qs:
            for oq in questions(old):
                question_score=max(question_score,SequenceMatcher(None,q.split()[:40],oq.split()[:40],autojunk=False).ratio())
    return {'similarity':round(best,3),'repeated_phrase':round(phrase,3),'repeated_question':round(question_score,3),'exact_duplicate':exact}

TOPICS = {'books':{'book','books','reading','novel','novels','story','stories','library'},
    'music':{'music','song','songs','jazz','guitar','album','piano'},
    'art':{'paint','painting','painted','drawing','lighthouse','art','watercolor','palette','color','colors'},
    'space':{'space','star','stars','planet','moon','astronomy','telescope'},
    'food':{'cook','cooking','food','pasta','coffee','tea','recipe','dinner','tomatoes','garlic'},
    'outdoors':{'walk','walking','rain','garden','trees','weather','hiking'},
    'session':{'session','telemetry','bpm','pulse','heart','device','pattern','intensity','pause','resume','stop','simulator'}}
STOPWORDS=set('the and you your i my a an to of it is was me that this what how about with for in on just really would could please tell think more now like'.split())


def topic_for(text, previous=None):
    words=set(normalize(text).split())
    scores={key:len(words&v) for key,v in TOPICS.items()}
    best=max(scores,key=scores.get)
    if scores[best]:return best
    if previous and not re.search(r'new topic|something else|another subject|talk about|on another note',text,re.I):return None
    content=[w for w in normalize(text).split() if w not in STOPWORDS and len(w)>3]
    return ' / '.join(content[:2]) or None


def numerical_request(text):
    return bool(re.search(r'\b(bpm|pulse|heart.?rate|telemetry)\b|\b(?:current|latest|sensor|session|physiological)\s+(?:readings?|measurements?|numbers?)\b',text,re.I))


def tools_relevant(text):
    # Restricts tool exposure; never creates a plan or executes text.
    return numerical_request(text) or bool(re.search(
        r'\b(pause|resume|stop|halt|simulator|device|edgeloop|intensity|get_session_state|list_patterns|set_pattern|set_intensity)\b|'
        r'\b(?:set|change|switch).{0,24}\b(?:pattern|gentle|moderate)\b|\b(?:list|available|what|which)\b.{0,24}\bpatterns?\b', text, re.I))


def group_for(kind):
    if kind.startswith('hr_') or kind in {'rapid_rise','rapid_fall','sustained_elevation','recovery','fluctuations','stable'}:return 'physiology'
    if kind=='edge':return 'edge'
    if kind=='command_ack':return 'tool'
    if kind.startswith('device'):return 'device'
    return 'session'

class ConversationDirector:
    def __init__(self, config=None, clock=time.monotonic):
        self.config=config or DirectorConfig()
        self.clock=clock
        self.counts=Counter()
        self.decisions=deque(maxlen=64)
        self.records=deque(maxlen=128)
        self.recent_observations=deque(maxlen=32)
        self.aggregates={}
        self.seen={}
        self.last_category={}
        self.last_spoken=float('-inf')
        self.last_reaction=float('-inf')
        self.typing_until=0
        self.last_reason='No speech requested'
        self.model_states={}
        self.active_scope='default'
        self.activate('default')
        self.session_status='IDLE'
        self.current_origin='simulated_telemetry'

    def activate(self, scope):
        self.active_scope=scope
        self.memory=self.model_states.setdefault(scope,{'topic':None,'topics':deque(maxlen=8),'questions':deque(maxlen=12),'responses':deque(maxlen=24),'event_responses':deque(maxlen=8),'last_user':float('-inf'),'consecutive_unsolicited':0})

    def log(self, reason, **details):
        entry={'at':self.clock(),'reason':reason,**details}
        self.decisions.append(entry)
        logger.info('conversation_director %s',json.dumps(entry,separators=(',',':')))

    def record(self, origin, content, role='system', **metadata):
        entry={'origin':origin,'role':role,'content':content,'at':self.clock(),'scope':self.active_scope,**metadata}
        self.records.append(entry)
        return entry

    def user(self, text):
        self.record('real_user',text,'user')
        self.memory['last_user']=self.clock()
        self.memory['consecutive_unsolicited']=0
        topic=topic_for(text,self.memory['topic'])
        if topic:
            if topic!=self.memory['topic']:self.memory['topics'].append(topic)
            self.memory['topic']=topic

    def observation(self, kind, details=None, origin='simulated_telemetry'):
        self.counts['events_received']+=1
        self.counts['observations']+=1
        self.counts['observations_silent']+=1
        self.current_origin=origin
        if details and details.get('status'):self.session_status=details['status']
        # Rolling samples remain data and never enter user dialogue.
        self.recent_observations.append({'kind':kind,'at':self.clock(),'origin':origin})

    def receive(self, kind, priority, details=None, origin=None):
        now=self.clock();details=details or {};origin=origin or ('tool_result' if kind=='command_ack' else self.current_origin)
        self.counts['events_received']+=1
        category='safety_event' if priority>=100 else 'significant_event'
        group=group_for(kind)
        signature=kind+':'+json.dumps({k:v for k,v in details.items() if k not in {'hr','delta_bpm','ack_id','age_seconds','reason','received_at_ms','sequence'}},sort_keys=True,separators=(',',':'))
        self.seen={k:v for k,v in self.seen.items() if now-v<=self.config.dedup_seconds}
        if len(self.seen)>=256:self.seen.pop(next(iter(self.seen)))
        previous=self.aggregates.get(kind)
        count=previous['count']+1 if previous and now-previous['at']<=self.config.aggregation_seconds else 1
        aggregate={'kind':kind,'count':count,'at':now,'origin':origin,'category':category,'group':group,**details}
        self.aggregates[kind]=aggregate
        self.aggregates={k:v for k,v in self.aggregates.items() if now-v['at']<=300}
        if len(self.aggregates)>32:self.aggregates.pop(next(iter(self.aggregates)))
        self.record(origin,json.dumps({'kind':kind,**details},separators=(',',':')))
        if self.config.enabled and category!='safety_event' and signature in self.seen:
            self.counts['events_suppressed']+=1;self.log('equivalent_event',kind=kind)
            return False
        self.seen[signature]=now
        self.counts['significant_events_retained']+=1
        return True

    def opportunity(self, event):
        now=self.clock();group=group_for(event['kind'])
        if self.clock()<self.typing_until:return False,'user_typing'
        if not self.config.enabled:return True,'baseline_scheduler'
        if not self.config.spontaneous_enabled:return False,'spontaneous_disabled'
        if event['kind'] in {'completion_accepted','came_early'}:return True,'verified_completion_action:'+event['kind']
        if event['kind'] in REACTIVE_EVENTS:
            if now<event.get('not_before',0):return False,'selection_settling'
            if now-self.memory['last_user']<self.config.reaction_user_grace_seconds:return False,'user_turn_grace'
            if now-self.last_reaction<self.config.reaction_interval_seconds:return False,'reaction_cooldown'
            return True,'verified_action:'+event['kind']
        if self.memory['consecutive_unsolicited']>=self.config.max_consecutive_unsolicited:return False,'unsolicited_limit'
        if group=='tool':return False,'acknowledgement_already_available'
        if now-self.memory['last_user']<self.config.user_idle_before_spontaneous_seconds:return False,'active_conversation'
        if now-self.last_spoken<self.config.spontaneous_interval_seconds:return False,'spontaneous_frequency'
        if now-self.last_category.get(group,float('-inf'))<self.config.category_cooldowns.get(group,90):return False,'category_cooldown'
        if self.memory['topic'] not in {None,'session'} and now-self.memory['last_user']<self.config.topic_protection_seconds:return False,'continue_user_topic'
        return True,'conversational_opportunity:'+group

    def narrative_opportunity(self, engaged):
        now=self.clock()
        if not (self.config.enabled and self.config.spontaneous_enabled and self.config.narrative_initiative_enabled):return False,'narrative_disabled'
        if self.clock()<self.typing_until:return False,'user_typing'
        if not engaged:return False,'no_welcome_narrative_thread'
        if self.session_status not in {'RUNNING','RAMPDOWN'}:return False,'narrative_session_inactive'
        if self.memory['consecutive_unsolicited']>=self.config.max_consecutive_unsolicited:return False,'unsolicited_limit'
        if now-self.memory['last_user']<self.config.user_idle_before_spontaneous_seconds:return False,'active_conversation'
        if now-self.last_spoken<self.config.spontaneous_interval_seconds:return False,'spontaneous_frequency'
        return True,'bounded_narrative_continuation'

    def dispatched(self,event,reason):
        if event['kind'] in REACTIVE_EVENTS:self.last_reaction=self.clock()
        self.last_spoken=self.clock();self.last_category[group_for(event['kind'])]=self.clock()
        self.last_reason=reason
        self.counts['opportunities_dispatched']+=1
        self.counts['conversational_opportunities']+=1
        self.record('system_event','Conversational opportunity: '+event['kind'],category='conversational_opportunity')
        self.log(reason,kind=event['kind'])

    def context(self, snapshot, prompt, events, user, memory_enabled=True):
        if not self.config.enabled:return snapshot
        numeric=numerical_request(prompt) if user else False
        relevant=self.memory['topic']=='session' or numeric or not user
        state={k:snapshot[k] for k in ('status','emergency_latched') if k in snapshot}
        if relevant or snapshot.get('emergency_latched'):
            state.update({k:v for k,v in snapshot.items() if k in {'stop_reason','device_moving','simulated_pattern'}})
        if numeric:state.update({k:v for k,v in snapshot.items() if k in {'hr','seconds','signal','trend','edges','simulated_velocity'}})
        elif relevant:state.update({k:v for k,v in snapshot.items() if k in {'signal','trend'}})
        relevant_events=[]
        for e in events[-6:]:
            if e.get('priority',0)>=100 or relevant:
                item={k:v for k,v in e.items() if k not in {'at','ack_id','hr','delta_bpm'}}
                if not numeric and isinstance(item.get('device'),dict):item['device']={k:v for k,v in item['device'].items() if k in {'moving','pattern','simulated'}}
                relevant_events.append(item)
        state.update(conversation_source='user' if user else 'event',recent_events=relevant_events,
            director={'enabled':True,'topic':self.memory['topic'] if memory_enabled else topic_for(prompt),'recent_subjects':list(self.memory['topics'])[-4:] if memory_enabled else [],
                'recent_questions':list(self.memory['questions'])[-3:] if memory_enabled else [], 'numerical_telemetry_requested':numeric,
                'event_origin':self.current_origin})
        return state

    def history(self, base, limit):
        # Retain genuine user turns preferentially; include recent unsolicited assistant dialogue.
        extra=[m for m in self.memory['event_responses'] if not any(x.get('content')==m['content'] for x in base)][-2:]
        return sorted([*base,*extra],key=lambda m:m.get('at',0))[-limit:]

    def assess(self,text,user=False,prompt=''):
        score=repetition(text,[r['text'] for r in self.memory['responses']])
        numeric=bool(re.search(r'\b\d{2,3}\s*(?:bpm|beats per minute)\b',text,re.I))
        permitted=user and (numerical_request(prompt) or bool(re.search(r'\b(repeat|again|exactly|nickname|your name)\b',prompt,re.I)))
        selection_ack=False
        if not user and prompt.startswith('Observed application event (not a user request): ') and len(text.split())<=40:
            try:
                event=json.loads(prompt.split(': ',1)[1])
                from .grounding import MODE_NAMES
                field='experience' if event.get('kind')=='experience_changed' else 'goal'
                value=event.get('current_'+field)
                names=[str(value),MODE_NAMES.get(value,'')]
                selection_ack=event.get('kind') in SELECTION_EVENTS and value!=event.get('previous_'+field) and bool(re.search(r'\b(selected|selection|picked|chose|chosen)\b',text,re.I)) and any(name and re.search(r'\b'+re.escape(name)+r'\b',text,re.I) for name in names)
            except (ValueError,TypeError):pass
        derived_numeric=False
        if not user and prompt.startswith('Observed application event (not a user request): '):
            try:derived_numeric=json.loads(prompt.split(': ',1)[1]).get('category')=='derived'
            except (ValueError,TypeError):pass
        numeric_requested=numerical_request(prompt) or derived_numeric
        threshold=max(.95,self.config.repetition_threshold) if selection_ack else self.config.repetition_threshold
        excessive=not permitted and (score['exact_duplicate'] or score['similarity']>=threshold or score['repeated_phrase']>=(.9 if selection_ack else .65) or score['repeated_question']>=.9 or numeric and not numeric_requested)
        device_narration = user and not tools_relevant(prompt) and bool(re.search(r'\b(simulator|telemetry|device|heart.rate|bpm)\b|\bpulse pattern\b',text,re.I))
        excessive = excessive or device_narration
        score.update(verified_selection_ack=selection_ack,excessive=excessive,unrequested_device_narration=device_narration,unrequested_numeric=numeric and not numeric_requested,permitted_repetition=permitted)
        self.counts['responses_assessed']+=1
        self.log('repetition_assessment',**score)
        return score

    def accepted(self,text,user):
        self.memory['responses'].append({'text':text,'at':self.clock()})
        self.memory['questions'].extend(questions(text))
        item=self.record('assistant_dialogue',text,'assistant',trigger_origin='real_user' if user else self.current_origin)
        if not user:
            self.memory['consecutive_unsolicited']+=1
            self.memory['event_responses'].append(item)
            self.counts['unsolicited_dialogue_generated']+=1
        self.last_reason='user_turn' if user else self.last_reason

    def status(self):
        return {'config':self.config.model_dump(),'counts':dict(self.counts),'events_received':self.counts['events_received'],
            'events_suppressed':self.counts['events_suppressed'],'significant_events_retained':self.counts['significant_events_retained'],
            'unsolicited_dialogue_generated':self.counts['unsolicited_dialogue_generated'],'most_recent_reason_for_speaking':self.last_reason,
            'current_topic':self.memory['topic'],'recent_subjects':list(self.memory['topics']),'recent_questions':list(self.memory['questions']),
            'previous_assistant_responses':[r['text'] for r in self.memory['responses']][-4:],
            'recent_observations':list(self.recent_observations)[-8:],'session_status':self.session_status,
            'aggregates':list(self.aggregates.values())[-8:],'decisions':list(self.decisions)[-20:]}
