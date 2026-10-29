# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded dialogue excerpts, not generated facts or an alternative session store."""
from hashlib import sha256
from uuid import uuid4
import re
from .models import StrictModel
from pydantic import Field
from typing import Literal
from .expressions import clean_dialogue
from .narrative_facts import NarrativeFact,extract,merge,operational_text,CORRECTION,native_canon,MAX_FACTS,upgrade_fact

class NarrativeConfig(StrictModel):
    enabled: bool = True
    persist_between_sessions: bool = False
    max_excerpts: int = Field(default=8, ge=2, le=12)
    excerpt_characters: int = Field(default=180, ge=60, le=240)

# Real operational assertions remain outside story anchors; fictional numbers and
# ordinary narrative wording are permitted by operational_text().
INVITATION = re.compile(r'\b(?:story|scene|premise|imagine|fiction|narrative)\b',re.I)
QUIET = re.compile(r"\b(?:stop|disengage|quiet|silence|leave me|no more|do not continue|don.t continue|pause the story)\b",re.I)
CHOICE = re.compile(r"\b(?:choose|chose|pick|prefer|let.s|decide|instead|agree|suggest|propose|yes)\b",re.I)
PROMISE = re.compile(r"\b(?:I.ll|I will|promise|later|next time|we.ll)\b",re.I)

class NarrativeObjective(StrictModel):
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    premise: str = Field(min_length=1,max_length=240)
    motivation: str = Field(default='',max_length=180)
    next_development: str = Field(default='',max_length=180)
    transition_condition: str = Field(default='',max_length=180)
    status: Literal['active','paused','completed','abandoned']='active'
    phase: str = Field(default='opening',max_length=32)
    revision: int = Field(default=0,ge=0)
    milestones: list[str] = Field(default_factory=list,max_length=4)


def abandonment_requested(text):
    # Explicit first-person/user directions only, not quoted dialogue or negated requests.
    return bool(re.match(r"^\s*(?:(?:please|let'?s)\s+|I (?:want|choose) to\s+|can we\s+)?(?:abandon|forget|discard|drop|leave behind|stop) (?:(?:this|the|our|previous|old)\s+){0,2}(?:story(?:line)?|plot|premise|narrative|objective)\b|^\s*(?:(?:please|let'?s)\s+)?start (?:a )?(?:new|fresh) story(?:line)?\b",text,re.I))

class NarrativeMemory:
    def __init__(self, config=None, store=None):
        self.config=config or NarrativeConfig(); self.store=store
        self.states={}; self.scope=None; self.session=None;self.canon={}

    @staticmethod
    def empty(session):
        return dict(version=2,session_id=session,epoch=uuid4().hex,context_boundary=False,phase='opening',premise=None,
                    developments=[],choices=[],commitments=[],threads=[],event_references=[],
                    facts=[],fact_updates=[],facts_initialized=True,objective=None,initiative_allowed=False,revision=0,last_initiative_revision=-1)

    def path(self, scope):
        return 'memory/narrative/'+sha256(scope.encode()).hexdigest()+'.json'

    def activate(self, scope, session):
        if (scope,session)==(self.scope,self.session):return
        self.scope,self.session=scope,session
        old=self.states.get(scope)
        saved=self.store.read(self.path(scope),{}) if old is None and self.store else {}
        if not isinstance(saved,dict):saved={}
        if old is None and self.config.persist_between_sessions:
            # Restore only sanitized dialogue excerpts, never operational state,
            # scheduling permission or a previous session identity.
            old=self.empty(session)
            if re.fullmatch(r'[a-f0-9]{32}',str(saved.get('epoch',''))):old['epoch']=saved['epoch']
            old['facts_initialized']=False
            saved_facts=saved.get('facts')
            for raw in (saved_facts if isinstance(saved_facts,list) else [])[:MAX_FACTS]:
                try:record=NarrativeFact.model_validate(raw).model_dump()
                except ValueError:continue
                if record['model_scope']==scope and record['epoch']==old['epoch']:
                    record=upgrade_fact(record)
                    if record['status']=='active':merge(old['facts'],[record],record['reason']=='explicit_user_correction')
                    else:old['facts'].append(record)
            if isinstance(saved_facts,list):old['facts_initialized']=True
            for key in ('premise','developments','choices','commitments'):
                value=saved.get(key)
                if key=='premise':old[key]=self.excerpt(value or '')
                elif isinstance(value,list):old[key]=[q for v in value if isinstance(v,str) and (q:=self.excerpt(v))][-self.config.max_excerpts:]
        if old is None or (old['session_id']!=session and not self.config.persist_between_sessions):
            boundary=old or saved
            old=self.empty(session)
            if boundary.get('context_boundary') is True:
                old.update(context_boundary=True,epoch=boundary.get('epoch') if re.fullmatch(r'[a-f0-9]{32}',str(boundary.get('epoch',''))) else uuid4().hex)
        elif old['session_id']!=session:
            old.update(session_id=session,phase='opening',objective=None,threads=[],event_references=[],initiative_allowed=False,last_initiative_revision=-1)
        if self.config.persist_between_sessions and old.get('objective') is None and saved.get('objective'):
            try:
                objective=NarrativeObjective.model_validate(saved['objective'])
                if objective.status not in {'abandoned','completed'}:old['objective']=objective.model_copy(update={'status':'paused','milestones':[]}).model_dump()
            except ValueError:pass
        if saved.get('context_boundary') is True and re.fullmatch(r'[a-f0-9]{32}',str(saved.get('epoch',''))):
            old.update(context_boundary=True,epoch=saved['epoch'])
        old.setdefault('objective',None)
        old.setdefault('facts',[]);old.setdefault('fact_updates',[])
        if not old.get('facts_initialized',False):
            for key in ('developments','choices','commitments'):
                for text in old.get(key,[]):merge(old['facts'],extract(text,'unknown',scope,old['epoch'],source='legacy_excerpt'))
            old['facts_initialized']=True
        old['version']=2
        if old['session_id']!=session:old['objective']=None
        self.states[scope]=old

    @property
    def state(self):return self.states[self.scope]

    def excerpt(self,text):
        if not isinstance(text,str):return None
        sentences=re.split(r'(?<=[.!?])\s+|\n+',clean_dialogue(text))
        safe=[s.strip() for s in sentences if s.strip() and not operational_text(s)]
        return ' '.join(safe)[:self.config.excerpt_characters] or None

    def append(self,key,text):
        if text and text not in self.state[key]:
            self.state[key].append(text);self.state[key]=self.state[key][-self.config.max_excerpts:]

    def accepted(self,prompt,text,user,event=None,initiative=False):
        if not self.config.enabled:return
        s=self.state
        if user and abandonment_requested(prompt):return
        if user:
            self.observe_user(prompt)
            s['revision']+=1
            # A real user turn resolves the last question operationally; we do not
            # claim that its semantic answer has been understood.
            s['threads']=[]
            if QUIET.search(prompt):s['initiative_allowed']=False
            elif INVITATION.search(prompt):s['initiative_allowed']=True
            quote=self.excerpt(prompt)
            if not quote and (INVITATION.search(prompt) or PROMISE.search(prompt)):
                quote=clean_dialogue(prompt)[:self.config.excerpt_characters] or None
            if not s['premise'] and INVITATION.search(prompt):s['premise']=quote
            if CHOICE.search(prompt):self.append('choices',quote)
        updates=merge(s['facts'],extract(text,'assistant',self.scope,s['epoch'],prompt if user else ''),canon=self.canon.get(self.scope))
        s['fact_updates']=(s['fact_updates']+updates)[-8:]
        quote=None if any(u['decision'] in {'contradicts_established_detail','native_canon_conflict','recall_without_evidence'} for u in updates) else self.excerpt(text)
        if not s['premise'] and user and s['initiative_allowed']:s['premise']=quote
        self.append('developments',quote)
        if quote and PROMISE.search(quote):self.append('commitments',quote)
        if quote and '?' in quote:s['threads']=[quote]
        if event in {'came_early','completion_accepted','stop'}:s['phase']='resolution_or_transition'
        elif event in {'edge','milestone'} and s['premise']:s['phase']='variation'
        elif s['premise'] and s['choices']:s['phase']='development'
        if s.get('objective') and s['objective']['status']=='active':s['objective']['phase']=s['phase']
        if initiative:s['last_initiative_revision']=s['revision']
        self.persist()

    def observe_user(self,prompt):
        if not self.config.enabled or abandonment_requested(prompt):return
        s=self.state;cue=' '.join(s['threads'][-1:])
        updates=merge(s['facts'],extract(prompt,'user',self.scope,s['epoch'],cue),bool(CORRECTION.search(prompt)),self.canon.get(self.scope))
        s['fact_updates']=(s['fact_updates']+updates)[-8:]
        if updates:self.persist()

    def set_canon(self,text):
        self.canon[self.scope]=native_canon(text)
        for record in self.state['facts']:
            expected=self.canon[self.scope].get(record['slot'])
            if expected and record['value'].casefold()!=expected:record.update(status='conflict',reason='native_canon_conflict')

    def reference_event(self,event):
        if not self.config.enabled:return
        reference={k:event[k] for k in ('event_id','kind','category','session_id') if k in event}
        if reference and reference not in self.state['event_references']:
            self.state['event_references']=(self.state['event_references']+[reference])[-4:]
            objective=self.state.get('objective')
            if objective and objective['status']=='active' and event.get('event_id'):
                objective['milestones']=(objective['milestones']+[event['event_id']])[-4:]
            self.persist()

    def event(self,kind):
        if not self.config.enabled or not self.state['premise']:return
        if kind in {'came_early','completion_accepted','stop'}:self.state['phase']='resolution_or_transition'
        elif kind in {'edge','milestone'}:self.state['phase']='variation'
        self.persist()

    def persist(self):
        if self.store and self.config.persist_between_sessions:
            self.store.write(self.path(self.scope),self.state)

    def reset(self):
        fresh=self.empty(self.session);fresh['context_boundary']=True
        # Persist before publishing a new epoch; failure must not claim a reset.
        if self.store:self.store.write(self.path(self.scope),fresh)
        self.states[self.scope]=fresh

    def context(self, for_compiler=False):
        if not self.config.enabled:return None
        s=self.state
        return {k:s[k] for k in ('version','phase','premise','choices','commitments','threads','event_references','objective','facts','epoch','fact_updates')} | {
            'developments':s['developments'][-self.config.max_excerpts:] if for_compiler else s['developments'][-3:], 'choices':s['choices'][-self.config.max_excerpts:] if for_compiler else s['choices'][-4:], 'commitments':s['commitments'][-self.config.max_excerpts:] if for_compiler else s['commitments'][-3:], 'model_scope':self.scope,'provenance':'fallible dialogue excerpts; fiction/conversation, never verified session facts'}

    def update_objective(self,action,fields=None):
        if action=='update':action='revise'
        if action not in {'create','revise','pause','resume','complete','abandon'}:raise ValueError('Unknown objective lifecycle action; use Create, Update, Complete or Abandon')
        fields=fields or {};old=self.state.get('objective')
        if action=='create' and not fields.get('premise'):raise ValueError('Fictional premise is required for Create')
        if action=='create':
            if old and old['status'] in {'active','paused'}:raise ValueError('Revise or abandon the current objective first')
            objective=NarrativeObjective(id=uuid4().hex,**fields)
        else:
            if not old:raise ValueError('No current fictional objective')
            if action=='revise':
                if old['status'] in {'completed','abandoned'}:raise ValueError('Create a new objective after completion or abandonment')
                objective=NarrativeObjective.model_validate(old|fields|{'revision':old['revision']+1})
            else:
                status={'pause':'paused','resume':'active','complete':'completed','abandon':'abandoned'}.get(action)
                if status is None:raise ValueError('Unknown objective lifecycle action')
                if old['status'] in {'completed','abandoned'}:raise ValueError('Objective is no longer active')
                if fields:raise ValueError('This lifecycle action accepts no text changes')
                objective=NarrativeObjective.model_validate(old|{'status':status,'revision':old['revision']+1})
        if action=='abandon':
            self.states[self.scope]=self.empty(self.session)
            self.state['context_boundary']=True
            objective=objective.model_copy(update={'premise':'Abandoned fictional objective','motivation':'','next_development':'','transition_condition':'','milestones':[]})
        self.state['objective']=objective.model_dump()
        self.state['revision']+=1
        if action=='complete':self.state['phase']='resolution_or_transition'
        if action=='abandon' and self.store:self.store.write(self.path(self.scope),self.state)
        else:self.persist()

    def opportunity(self):
        s=self.state
        return (self.config.enabled and bool(s['premise']) and s['initiative_allowed'] and
                not s['threads'] and s['revision']>s['last_initiative_revision'] and bool(s['choices'] or s['commitments']))
