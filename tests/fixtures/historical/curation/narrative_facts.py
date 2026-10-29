# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded CPU-only extraction/retrieval helpers for the existing NarrativeMemory.
No store, inference, embeddings, session evidence or character definition lives here.
"""
from uuid import uuid4
from hashlib import sha256
import re
from typing import Literal
from pydantic import Field
from .models import StrictModel
from .expressions import clean_dialogue

MAX_FACTS=16
class NarrativeFact(StrictModel):
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    category:Literal['user_fact','character_detail','hypothesis','development','commitment']
    speaker:Literal['user','assistant','unknown']
    model_scope:str=Field(max_length=512)
    epoch:str=Field(pattern=r'^[a-f0-9]{32}$')
    text:str=Field(min_length=1,max_length=320)
    value:str=Field(min_length=1,max_length=320)
    slot:str=Field(max_length=100)
    cue:str=Field(default='',max_length=160)
    exact:bool=False
    status:Literal['active','superseded','conflict']='active'
    reason:str=Field(default='dialogue',max_length=64)
    source:Literal['dialogue','legacy_excerpt']='dialogue'

HYPOTHESIS=re.compile(r'\b(?:maybe|perhaps|might|could|suspect|hypothes\w*|theor\w*|I think)\b',re.I)
CORRECTION=re.compile(r"^\s*(?:actually\b|correction\b|no[,!:]|not quite\b|that['’]s wrong\b|to correct\b|remember[: ,])|\b(?:rather than|instead of)\b",re.I)
QUOTED=re.compile(r'["“]([^"”\n]+)["”]')
OBJECT=re.compile(r'\b(?:(?P<name>[A-Z][a-z]+)\s+)?(?P<object>page|note|letter|inscription|message|book|sign|clue)\b')

def norm(text):return ' '.join(re.findall(r'\w+',text.casefold()))
def terms(text):
    words=set(re.findall(r'[a-z]{3,}',text.casefold()))-set('the and was were what when where did does have your you our with that this about from said tell remember'.split())
    if any(w.startswith('collect') for w in words):words.add('collect')
    return words

def operational_text(text):
    """Reject actual measurement/state assertions, not every number or story noun."""
    if QUOTED.search(text) or re.search(r'\b(?:fiction\w*|imagined|novel|in the story|page|inscription)\b',text,re.I):return False
    return bool(re.search(r'\b\d+(?:\.\d+)?\s*(?:BPM|beats per minute)\b|\b(?:BPM|heart rate|pulse)\b.{0,24}\b\d{2,3}\b|\b(?:sensor|BLE|Polar|monitor|Handy|device|stroker|hardware)\b.{0,65}\b(?:connected|disconnected|recording|measuring|moving|stopped|speed|intensity)\b|\bsession\b.{0,45}\b(?:running|paused|stopped|seconds|minutes|elapsed)\b',text,re.I))

def recall_intent(prompt):
    quote=bool(re.search(r'\b(?:what|which|recall|remember|repeat|exact)\b.*\b(?:page|note|letter|inscription|quotation|quote|wording|clue|words)\b',prompt,re.I))
    collection=bool(re.search(r'\b(?:what|which|recall|remember)\b.*\bcollect\w*\b',prompt,re.I))
    other=bool(re.search(r'\b(?:remember|recall|previously|earlier|you told me|we agreed|did we|did you)\b',prompt,re.I))
    return 'quotation' if quote else 'collection' if collection else 'detail' if other else None

def quotation_slot(text,cue):
    match=OBJECT.search(text) or OBJECT.search(cue)
    if not match:return 'quotation:unscoped'
    name=(match['name'] or '').casefold()
    if name in {'the','a','this','that','what','which'}:name=''
    return 'quotation:'+(':'.join(filter(None,[name,match['object'].casefold()])))

def native_canon(text):
    # Derive only explicit named relationship statements from the existing SYSTEM.
    # This does not define a new persona or guess unstated relationships.
    result={}
    for match in re.finditer(r'(?m)^([A-Z][a-z]+(?: [A-Z][a-z]+)+):\s*\nYour (husband|wife|spouse|brother|sister|father|mother)\b',text):
        result['relationship:'+match[1].split()[0].casefold()]=match[2].casefold()
    return result

def extract(text,speaker,scope,epoch,cue='',source='dialogue'):
    clean=clean_dialogue(text).strip();records=[]
    def add(original,value,slot,exact=False,category=None):
        if not original or len(original)>320 or not value or len(value)>320:return
        if len(slot)>100:slot=slot.split(':',1)[0]+':'+sha256(slot.encode()).hexdigest()[:32]
        cat=category or ('hypothesis' if HYPOTHESIS.search(original) else 'user_fact' if speaker=='user' else 'character_detail' if slot.startswith(('collection:','relationship:','preference:')) and speaker=='assistant' else 'development')
        if re.search(r"\b(?:I['’]ll|I will|promise|we['’]ll|we will)\b",original,re.I) and cat!='hypothesis':cat='commitment'
        records.append(NarrativeFact(id=uuid4().hex,category=cat,speaker=speaker,model_scope=scope,epoch=epoch,text=original,value=value,slot=('hypothesis:'+slot if cat=='hypothesis' else slot),cue=cue[:160],exact=exact,source=source).model_dump())
    for match in QUOTED.finditer(clean):
        prefix=clean[max(0,clean.rfind('.',0,match.start())+1):match.start()]
        add(match[0],match[1],quotation_slot(prefix,cue),True,'hypothesis' if HYPOTHESIS.search(prefix) else 'user_fact' if speaker=='user' else 'character_detail' if speaker=='assistant' else 'development')
    for sentence in re.split(r'(?<=[.!?])\s+|\n+',clean):
        sentence=sentence.strip()
        if not sentence or sentence.endswith('?') or QUOTED.search(sentence) or operational_text(sentence):continue
        if speaker=='user' and re.match(r"^(?:hello|hi|hey|good (?:morning|evening|night)|thanks|thank you|please|continue|tell me|imagine)\b",sentence,re.I):continue
        match=re.search(r"\b(my|your) (?:favorite|favourite|preferred) ([a-z]+) is (.+?)(?:[.!?]|$)",sentence,re.I)
        if match:
            target='character' if match[1].lower()=='my' and speaker=='assistant' or match[1].lower()=='your' and speaker=='user' else 'participant'
            add(sentence,match[3],'preference:'+target+':'+match[2].lower());continue
        match=re.search(r'\b(I|you|[A-Z][a-z]+)\s+(?:collects?|(?:have|keep) (?:a )?(?:small )?collection of)\s+(.+?)(?:[.!?]|$)',sentence,re.I)
        if match:
            subject=match[1].casefold();value=re.split(r',?\s+not\b|\s+instead of\b',match[2],maxsplit=1,flags=re.I)[0].strip()
            target='character' if subject=='i' and speaker=='assistant' or subject=='you' and speaker=='user' or subject not in {'i','you'} and subject in scope.casefold() else 'unspecified' if speaker=='unknown' and subject in {'i','you'} else 'participant' if subject in {'i','you'} else subject
            add(sentence,value,'collection:'+target);continue
        match=re.search(r'\b(?:my (?:small )?collection (?:is|includes|contains|consists of)|a collection of)\s+(.+?)(?:[.!?]|$)',sentence,re.I)
        if match:add(sentence,match[1],'collection:character' if speaker=='assistant' else 'collection:participant' if speaker=='user' else 'collection:unspecified');continue
        match=re.search(r"\b(?:the )?(witness|stranger|visitor|gardener|suspect|character) (?:is (?:called|named)|name is) ([A-Z][a-z]+(?: [A-Z][a-z]+)?)\b",sentence)
        if match:add(sentence,match[2],'name:'+match[1].casefold());continue
        match=re.search(r'\b([A-Z][a-z]+)(?: [A-Z][a-z]+)? is (?:your|my) (husband|wife|spouse|brother|sister|father|mother)\b',sentence)
        if match:add(sentence,match[2],'relationship:'+match[1].casefold());continue
        if speaker=='user' and recall_intent(cue)=='quotation' and not re.match(r'\s*(?:what|how|why|continue|tell|please)\b',sentence,re.I):
            add(sentence,sentence,quotation_slot('',cue),True);continue
        personal=bool(re.search(r'\b(?:I (?:like|love|prefer|enjoy|am|was|grew)|my \w+ (?:is|was))\b',sentence,re.I))
        category='character_detail' if personal and speaker=='assistant' else None
        add(sentence,sentence,'detail:'+norm(sentence)[:70],category=category)
    return records

def merge(records,candidates,correction=False,canon=None):
    """First established slot wins; explicit user corrections may supersede dialogue."""
    canon=canon or {};decisions=[]
    for item in candidates:
        if correction and item['speaker']=='user':item['reason']='explicit_user_correction'
        if any(r['status']=='active' and r['slot']==item['slot'] and r['category']==item['category'] and r['speaker']==item['speaker'] and norm(r['value'])==norm(item['value']) for r in records):continue
        slot=item['slot'];active=[r for r in records if r['status']=='active' and r['slot']==slot and r['category']!='hypothesis']
        if correction and item['speaker']=='user' and slot.startswith('quotation:') and not active:
            quotes=[r for r in records if r['status']=='active' and r['exact'] and r['category']!='hypothesis' and (slot.endswith('unscoped') or r['slot'].endswith(slot.split(':')[-1]))]
            if len(quotes)==1:active=quotes;item['slot']=quotes[0]['slot'];slot=item['slot']
        # A recall answer must not create a second unnamed version of one known quote.
        if item['speaker']=='assistant' and slot.startswith('quotation:') and recall_intent(item['cue'])=='quotation' and not active:
            quotes=[r for r in records if r['status']=='active' and r['exact'] and r['category']!='hypothesis']
            if len(quotes)==1:active=quotes;item['slot']=quotes[0]['slot']
            elif not quotes:item.update(status='conflict',reason='recall_without_evidence')
        same=next((r for r in active if norm(r['value'])==norm(item['value'])),None)
        if same:
            if item['speaker']=='user' and same['speaker']!='user':same.update(status='superseded',reason='user_confirmed')
            else:continue
        elif canon.get(slot) and norm(item['value'])!=norm(canon[slot]):item.update(status='conflict',reason='native_canon_conflict')
        elif active:
            if item['speaker']=='user' and correction:
                for old in active:old.update(status='superseded',reason='explicit_user_correction')
                item['reason']='explicit_user_correction'
            else:item.update(status='conflict',reason='contradicts_established_detail')
        records.append(item);decisions.append({'id':item['id'],'category':item['category'],'decision':item['reason'] if item['status']!='active' else 'stored'})
    def priority(r):
        return (0 if r['status']!='active' else 1 if r['category'] in {'development','hypothesis'} else 2 if r['slot'].startswith('detail:') else 3 if r['speaker']!='user' else 4)
    while len(records)>MAX_FACTS:
        index=min(range(len(records)),key=lambda i:(priority(records[i]),i));old=records.pop(index)
        decisions.append({'id':old['id'],'decision':'retention_limit'})
    return decisions

def retrieve(narrative,prompt,scope=None,epoch=None,canon=None):
    intent=recall_intent(prompt);query=terms(prompt);ranked=[];diagnostics=[]
    records=narrative.get('facts')
    if records is None:
        if epoch and not re.fullmatch(r'[a-f0-9]{32}',epoch):return intent,[],[]
        records=[]
        for key in ('developments','choices','commitments'):
            for text in narrative.get(key,[]):
                for r in extract(text,'unknown',scope or 'legacy',epoch or '0'*32,source='legacy_excerpt'):
                    r['id']=sha256((r['model_scope']+r['epoch']+r['text']).encode()).hexdigest()[:32]
                    records.append(r)
        records=records[-MAX_FACTS:]
    for raw in records[:MAX_FACTS]:
        try:r=NarrativeFact.model_validate(raw).model_dump()
        except ValueError:continue
        reason='inactive_or_conflicting' if r['status']!='active' else 'wrong_model' if scope and r['model_scope']!=scope else 'wrong_epoch' if epoch and r['epoch']!=epoch else 'native_canon_conflict' if (canon or {}).get(r['slot']) and norm(r['value'])!=norm(canon[r['slot']]) else None
        overlap=len(query&terms(r['text']+' '+r['cue']+' '+r['slot']))
        if intent=='quotation':
            matched=bool(r['exact'] or r['source']=='legacy_excerpt' and r['category']=='development' and r['slot'].startswith('detail:') or 'collect' in query and r['slot']=='collection:character')
        elif intent=='collection':
            matched=r['slot']=='collection:character' or r['source']=='legacy_excerpt' and r['slot'].startswith('collection:')
        else:matched=bool(overlap)
        if not reason and not matched:reason='irrelevant'
        if reason:diagnostics.append({'id':r['id'],'category':r['category'],'speaker':r['speaker'],'reason':reason,'selected':False});continue
        established=r['category'] not in {'hypothesis','development'}
        score=(100 if intent and established else 10)+(40 if intent=='quotation' and r['exact'] or intent=='collection' and r['slot']=='collection:character' else 0)+overlap*4+(5 if r['speaker']=='user' else 0)+(20 if r['reason']=='explicit_user_correction' else 0)
        ranked.append((score,r))
    ranked.sort(key=lambda pair:pair[0],reverse=True)
    return intent,[r for _,r in ranked],diagnostics
