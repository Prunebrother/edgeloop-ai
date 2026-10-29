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
from .fact_semantics import describe_fact,semantic_terms,fact_tags,equivalent_fact,significance,correction_anchor,instruction_only,requires_evidence,relation_candidates,fact_subject

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
    importance:int=Field(default=2,ge=0,le=5)
    curator_omit:bool=False
    curator_source_ref:str | None=Field(default=None,pattern=r'^[a-f0-9]{32}$')
    curator_reason:str=Field(default='',max_length=120)

HYPOTHESIS=re.compile(r'\b(?:maybe|perhaps|might|could|suspect|hypothes\w*|theor\w*|I think)\b',re.I)
CORRECTION=re.compile(r"^\s*(?:actually\b|correction\b|now[, ]|from now on\b|I (?:no longer|now)\b|no[,!:]|not quite\b|that['’]s wrong\b|to correct\b|remember[: ,])|\b(?:rather than|instead of)\b",re.I)
QUOTED=re.compile(r'["“]([^"”\n]+)["”]')
OBJECT=re.compile(r'\b(?:(?P<name>[A-Z][a-z]+)\s+)?(?P<object>page|note|letter|inscription|message|book|sign|clue|door|gate|crate|locker)\b')

IDENTIFIER=re.compile(r'\b[A-Z][A-Z0-9]{1,}(?:[-_]\d+[A-Z0-9_-]*)\b')

def identifier_slot(text,cue=''):
    context=text+' '+cue
    obj=re.search(r'\b(door|gate|crate|locker|sign|page|note|letter)\b',context,re.I)
    color=re.search(r'\b(blue|red|green|white|black|violet|yellow)\b',context,re.I)
    return 'identifier:'+ (obj[1].lower() if obj else 'unscoped')+(':'+color[1].lower() if color else '')

def upgrade_fact(raw):
    """Reclassify legacy retained excerpts without changing identity/provenance/wording."""
    r=dict(raw)
    if r['slot'].startswith('relationship:') and (detail:=describe_fact(r['text'],r['speaker'],r.get('cue',''))):r['slot']=detail['slot']
    if r['slot'].startswith('detail:'):
        code=IDENTIFIER.search(r['text'])
        if code:r.update(slot=identifier_slot(r['text'],r.get('cue','')),value=code[0],exact=True)
        elif detail:=describe_fact(r['text'],r['speaker'],r.get('cue','')):
            r.update(slot=detail['slot'])
            if detail['value'] is not None:r['value']=detail['value']
            if r['speaker']=='assistant' and r['category']!='hypothesis' and detail['slot'].startswith(('attribute:','interest:','hobby:','preference:','boundary:','relationship:')):r['category']='character_detail'
    return r

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
    other=bool(re.search(r'\b(?:remember|recall|previously|earlier|you told me|we agreed|did we|did you|did I)\b',prompt,re.I))
    identifier=bool(re.search(r'\b(?:what|which|recall|remember|exact)\b.*\b(?:identifier|code|marked|label|door|gate|locker)\b',prompt,re.I))
    hobby=bool(re.search(r'\b(?:what|which|recall|remember)\b.*\b(?:hobb\w*|pastime|spare time|free time|tend\w*|care for)\b',prompt,re.I))
    return 'identifier' if identifier else 'hobby' if hobby else 'quotation' if quote else 'collection' if collection else 'detail' if other or re.search(r"\b(?:what|which|where|who|how|when)\b|\bwhat['’]s\b",prompt,re.I) and any(t.startswith('@') for t in semantic_terms(prompt)) else None

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
        cat=category or ('hypothesis' if HYPOTHESIS.search(original) else 'user_fact' if speaker=='user' else 'character_detail' if slot.startswith(('collection:','relationship:','preference:','hobby:')) and speaker=='assistant' else 'development')
        if re.search(r"\b(?:I['’]ll|I will|promise|we['’]ll|we will)\b",original,re.I) and cat!='hypothesis':cat='commitment'
        records.append(NarrativeFact(id=uuid4().hex,category=cat,speaker=speaker,model_scope=scope,epoch=epoch,text=original,value=value,slot=('hypothesis:'+slot if cat=='hypothesis' else slot),cue=cue[:160],exact=exact,source=source).model_dump())
    for match in QUOTED.finditer(clean):
        if IDENTIFIER.fullmatch(match[1]):continue
        prefix=clean[max(0,clean.rfind('.',0,match.start())+1):match.start()]
        add(match[0],match[1],quotation_slot(prefix,cue),True,'hypothesis' if HYPOTHESIS.search(prefix) else 'user_fact' if speaker=='user' else 'character_detail' if speaker=='assistant' else 'development')
    for sentence in re.split(r'(?<=[.!?])\s+|\n+',clean):
        sentence=sentence.strip()
        if not sentence or sentence.endswith('?') or operational_text(sentence):continue
        code=IDENTIFIER.search(sentence)
        if code:
            add(sentence,code[0],identifier_slot(sentence,cue),True)
        def add_descriptor(detail):
            original=sentence if len(sentence)<=320 and not code else sentence[detail['start']:detail['start']+320]
            if len(original)==320:original=original.rsplit(' ',1)[0]
            category='hypothesis' if HYPOTHESIS.search(sentence) else 'commitment' if detail['kind']=='commitment' else 'character_detail' if speaker=='assistant' and detail['slot'].startswith(('attribute:','interest:','hobby:','preference:','boundary:','relationship:')) else None
            value=detail['value'] if detail['value'] is not None and len(detail['value'])<=320 else original
            add(original,value,detail['slot'],category=category)
        if code:
            detail=describe_fact(sentence,speaker,cue)
            if detail and not detail['slot'].startswith('proposition:'):add_descriptor(detail)
            continue
        if instruction_only(sentence):continue
        if speaker=='user' and re.match(r"^(?:hello|hi|hey|good (?:morning|evening|night)|thanks|thank you|please|continue|tell me|imagine)\b",sentence,re.I) and not describe_fact(sentence,speaker,cue):continue
        match=re.search(r'\b(I|you|[A-Z][a-z]+)\s+(?:collects?|(?:have|keep) (?:a )?(?:small )?collection of)\s+(.+?)(?:[.!?]|$)',sentence,re.I)
        if match:
            subject=match[1].casefold();value=re.split(r',?\s+not\b|\s+instead of\b',match[2],maxsplit=1,flags=re.I)[0].strip()
            target='character' if subject=='i' and speaker=='assistant' or subject=='you' and speaker=='user' or subject not in {'i','you'} and subject in scope.casefold() else 'unspecified' if speaker=='unknown' and subject in {'i','you'} else 'participant' if subject in {'i','you'} else subject
            add(sentence,value,'collection:'+target);continue
        match=re.search(r'\b(?:my (?:small )?collection (?:is|includes|contains|consists of)|a collection of)\s+(.+?)(?:[.!?]|$)',sentence,re.I)
        if match:add(sentence,match[1],'collection:character' if speaker=='assistant' else 'collection:participant' if speaker=='user' else 'collection:unspecified');continue
        match=re.search(r"\b(?:the )?(witness|stranger|visitor|gardener|suspect|character) (?:is (?:called|named)|name is) ([A-Z][a-z]+(?: [A-Z][a-z]+)?)\b",sentence)
        if match:add(sentence,match[2],'name:'+match[1].casefold());continue
        detail=describe_fact(sentence,speaker,cue)
        if detail:
            add_descriptor(detail);continue
        if QUOTED.search(sentence):continue
        if speaker=='user' and recall_intent(cue)=='quotation' and not re.match(r'\s*(?:what|how|why|continue|tell|please)\b',sentence,re.I):
            add(sentence,sentence,quotation_slot('',cue),True);continue
        personal=bool(re.search(r'\b(?:I (?:like|love|prefer|enjoy|am|was|grew)|my \w+ (?:is|was))\b',sentence,re.I))
        category='character_detail' if personal and speaker=='assistant' else None
        add(sentence,sentence,'detail:'+norm(sentence)[:70],category=category)
    return records

def merge(records,candidates,correction=False,canon=None):
    """First established slot wins; explicit user corrections may supersede dialogue."""
    canon=canon or {};decisions=[]
    for record in records:record.update(upgrade_fact(record))
    for item in candidates:
        if correction and item['speaker']=='user':item['reason']='explicit_user_correction'
        if any(r['status']=='active' and r['slot']==item['slot'] and r['category']==item['category'] and r['speaker']==item['speaker'] and norm(r['value'])==norm(item['value']) for r in records):continue
        slot=item['slot']
        if slot.startswith('identifier:'):
            anchors=[r for r in records if r['status']=='active' and r['slot'].split(':')[:2]==slot.split(':')[:2]]
            if len(anchors)==1 and (correction or item['speaker']=='assistant' and recall_intent(item['cue'])=='identifier'):
                item['slot']=slot=anchors[0]['slot']
        # Resolve an unscoped recall/correction to one sourced relation, never to
        # all facts about a person. Multiple candidates remain ambiguous.
        if correction and item['speaker']=='user' or item['speaker']=='assistant' and recall_intent(item['cue']):
            anchor=correction_anchor(item,records)
            if anchor:item['slot']=slot=anchor
        active=[r for r in records if r['status']=='active' and r['slot']==slot and r['category']!='hypothesis']
        if correction and item['speaker']=='user' and slot.startswith('quotation:') and not active:
            quotes=[r for r in records if r['status']=='active' and r['exact'] and r['category']!='hypothesis' and (slot.endswith('unscoped') or r['slot'].endswith(slot.split(':')[-1]))]
            if len(quotes)==1:active=quotes;item['slot']=quotes[0]['slot'];slot=item['slot']
        # A recall answer must not create a second unnamed version of one known quote.
        if item['speaker']=='assistant' and slot.startswith('quotation:') and recall_intent(item['cue'])=='quotation' and not active:
            quotes=[r for r in records if r['status']=='active' and r['exact'] and r['category']!='hypothesis']
            if len(quotes)==1:active=quotes;item['slot']=quotes[0]['slot']
            elif not quotes:item.update(status='conflict',reason='recall_without_evidence')
        if item['speaker']=='assistant' and not active and not canon.get(slot) and recall_intent(item.get('cue','')) and requires_evidence(item.get('cue',''),item):
            item.update(status='conflict',reason='recall_without_evidence')
        if correction and item['speaker']=='user' and not active and len(relation_candidates(item,records))>1:
            item.update(status='conflict',reason='ambiguous_correction_target')
        same=next((r for r in active if norm(r['value'])==norm(item['value']) or not correction and not item['exact'] and not slot.startswith('identifier:') and equivalent_fact(r['value'],item['value'])),None)
        if same:
            if item['speaker']=='user' and same['speaker']!='user':same.update(status='superseded',reason='user_confirmed')
            else:continue
        elif canon.get(slot) and norm(item['value'])!=norm(canon[slot]):item.update(status='conflict',reason='native_canon_conflict')
        elif active:
            if item['speaker']=='user' and correction:
                for old in active:old.update(status='superseded',reason='explicit_user_correction')
                item['reason']='explicit_user_correction'
            else:item.update(status='conflict',reason='contradicts_established_detail')
        records.append(item);decisions.append({'id':item['id'],'category':item['category'],'decision':item['reason'] if item['status']!='active' else 'stored','significance':significance(item),'semantic_tags':sorted(fact_tags(item))})
    def priority(r):return significance(r),r.get('importance',2)
    while len(records)>MAX_FACTS:
        index=min(range(len(records)),key=lambda i:(priority(records[i]),i));old=records.pop(index)
        decisions.append({'id':old['id'],'decision':'retention_limit','significance':significance(old),'semantic_tags':sorted(fact_tags(old))})
    return decisions

def retrieve(narrative,prompt,scope=None,epoch=None,canon=None):
    intent=recall_intent(prompt);query=semantic_terms(prompt);ranked=[];diagnostics=[]
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
        try:r=upgrade_fact(NarrativeFact.model_validate(raw).model_dump())
        except ValueError:continue
        boundary='wrong_model' if scope and r['model_scope']!=scope else 'wrong_epoch' if epoch and r['epoch']!=epoch else None
        if boundary:
            diagnostics.append({'id':r['id'],'category':r['category'],'speaker':r['speaker'],'reason':boundary,'selected':False});continue
        reason='not_an_asserted_fact' if instruction_only(r['text']) and not r['exact'] else 'inactive_or_conflicting' if r['status']!='active' else 'native_canon_conflict' if (canon or {}).get(r['slot']) and norm(r['value'])!=norm(canon[r['slot']]) else None
        overlap=len((query-{w for w in query if w.startswith('@')})&semantic_terms(r['text']+' '+r['slot']))
        tags=fact_tags(r);concept_overlap=len({w for w in query if w.startswith('@')}&tags)
        cue_overlap=len(query&semantic_terms(r['cue']))
        if intent=='identifier':matched=r['slot'].removeprefix('hypothesis:').startswith('identifier:') and bool(overlap)
        elif intent=='quotation':
            matched=bool(r['exact'] or r['source']=='legacy_excerpt' and r['category']=='development' and r['slot'].startswith('detail:') or 'collect' in query and r['slot']=='collection:character')
        elif intent=='collection':
            matched=r['slot']=='collection:character' or r['source']=='legacy_excerpt' and r['slot'].startswith('collection:')
        else:
            matched=bool(overlap or concept_overlap or cue_overlap and r['source']=='legacy_excerpt')
            target='participant' if re.search(r'\bmy\b',prompt,re.I) else 'character' if re.search(r'\byour\b',prompt,re.I) else None
            subject=fact_subject(r)
            if target and subject in {'character','participant'} and subject!=target:matched=False
            if target and r['slot'].startswith('quotation:') and subject not in {'character','participant'}:matched=False
        if not reason and not matched:reason='irrelevant'
        if not reason and r.get('curator_omit') and not intent:reason='curator_low_value'
        if reason:
            decision={'id':r['id'],'category':r['category'],'speaker':r['speaker'],'reason':reason,'selected':False}
            if reason not in {'wrong_model','wrong_epoch'}:decision.update(significance=significance(r),semantic_tags=sorted(tags))
            diagnostics.append(decision);continue
        established=r['category'] not in {'hypothesis','development'}
        score=(100 if intent and established else 10)+(40 if intent=='quotation' and r['exact'] or intent=='collection' and r['slot']=='collection:character' else 0)+overlap*8+concept_overlap*12+significance(r)*2+cue_overlap+r.get('importance',2)*2+(5 if r['speaker']=='user' else 0)+(20 if r['reason']=='explicit_user_correction' else 0)
        ranked.append((score,r))
    ranked.sort(key=lambda pair:pair[0],reverse=True)
    if intent is None and ranked and significance(ranked[0][1])>=3 and re.search(r'\b(?:what|which|where|who|how|when)\b',prompt,re.I):intent='detail'
    return intent,[r for _,r in ranked],diagnostics


def recall_violations(text,summary,diagnostics,native=''):
    """Only explicit replacement identifiers in recall; no general fiction rewriting."""
    if (diagnostics.get('narrative_recall') or {}).get('intent')!='identifier':return []
    if re.search(r"\b(?:unknown|unavailable|uncertain|not sure|cannot|can't|could|new identifier)\b",text,re.I):return []
    selected=set((diagnostics.get('narrative_recall') or {}).get('selected_fact_ids',[]))
    narrative=summary.get('narrative_context') or {}
    allowed={m[0] for r in narrative.get('facts',[]) if r['id'] in selected for m in IDENTIFIER.finditer(r['text'])}
    proposed={m[0] for m in IDENTIFIER.finditer(text)}
    wrong={code for code in proposed if code not in allowed and code not in native}
    return ['unsupported_narrative_identifier'] if wrong else []
