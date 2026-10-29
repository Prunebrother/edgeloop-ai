# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded grammatical fact descriptors and transparent lexical retrieval.
No entity/value inventories, inference, storage, or authoritative telemetry here.
Descriptors index source statements; they never supply missing facts.
"""
import re

# Concepts describe relations, not permissible fictional values or character traits.
CONCEPTS={
 'interest':{'hobby','hobbies','pastime','pastimes','interest','interests','leisure','off-duty'},
 'preference':{'prefer','preferred','preference','preferences','favorite','favourite'},
 'boundary':{'boundary','boundaries','avoid','dislike','uncomfortable','unwanted'},
 'role':{'job','occupation','profession','professional','role','career','work'},
 'origin':{'childhood','upbringing','hometown','origin','raised','grew'},
 'residence':{'home','residence','live','reside'},
 'identity':{'name','named','called','call','identity'},
 'relationship':{'relationship','related','relative','family','spouse','husband','wife','sister','brother','mentor'},
 'commitment':{'promise','promised','agreement','agreed','commitment','plan','planned','decided'},
 'discovery':{'discovery','discovered','found','learned','revealed'},
 'location':{'where','location','located','place','hidden','hid'},
 'motivation':{'motivation','purpose','ambition','aim','objective','goal'},
}
# Small relation-independent lexical families; unknown words use morphology only.
LEXEMES=(('old','antique','vintage'),('maintain','tend','care','nurture','cultivate','grow'),('restore','repair','refurbish'),('draw','sketch'))
STOP=set('a an the i you my your our we it is am are was were be been do did does have has had what which how why who when tell me us about remember recall please actually earlier previously really rather quite little from for of to in on and but with that this as at by its their they would should could can say said know told'.split())

def stem(word):
    word=word.casefold();forms=[word]
    if word.endswith('ies'):forms.append(word[:-3]+'y')
    elif word.endswith('s') and len(word)>3:forms.append(word[:-1])
    if word.endswith('ing') and len(word)>5:
        root=word[:-3];forms.extend((root,root+'e'))
        if len(root)>1 and root[-1]==root[-2]:forms.append(root[:-1])
    if word.endswith('ed') and len(word)>4:forms.extend((word[:-2],word[:-1]))
    for family in LEXEMES:
        if set(forms)&set(family):return family[0]
    return forms[1] if len(forms)>1 else word

def semantic_terms(text):
    words=set(re.findall(r"[a-z]+(?:-[a-z]+)?|\d+",text.casefold()))
    result={stem(w) for w in words if w not in STOP}
    for concept,values in CONCEPTS.items():
        if words&values:result.add('@'+concept)
    if re.search(r'\b(?:spare|free|leisure) time\b|\baway from work\b',text,re.I):result.add('@interest')
    if re.search(r'\bfor a living\b|\bprofessionally\b',text,re.I):result.add('@role')
    return result

def owner(pronoun,speaker):
    return ('character' if speaker=='assistant' else 'participant') if pronoun.lower() in {'i','my','me'} else ('participant' if speaker=='assistant' else 'character')

def key(text):return '_'.join(re.findall(r'[a-z0-9]+',text.casefold())[:9])

def descriptor(slot,kind,start=0,value=None,open_relation=False):return dict(slot=slot,kind=kind,start=start,value=value,open_relation=open_relation)

def instruction_only(text):
    return bool(re.match(r"\s*(?:in your (?:reply|response)|(?:please )?(?:reply|respond|introduce|tell me|continue|imagine|describe|explain|list|show|give|ask|write|include|add)\b|(?:can|could|would) you\b)",text,re.I))

def describe_fact(text,speaker,cue=''):
    """Recognize attributed propositions via grammar, across arbitrary domains.
    Return a stable subject/relation key, not a paraphrased source. Unknown syntax
    remains an ordinary excerpt. Questions, instructions and wishes are not facts.
    """
    if instruction_only(text) or re.search(r'\b(?:said|says|wrote|replied|stated)\b[^\"“]*[\"“]',text,re.I):return None
    if speaker not in {'assistant','user'} or text.rstrip().rstrip('\"”').endswith('?'):return None
    # Do not convert quoted/third-person reports or hypothetical wishes into identity.
    if re.search(r"\bI (?:would|might|could) (?:like|love|enjoy)|\bif I (?:had|were)\b",text,re.I):return None
    contrast=re.search(r'\bbut\s+(?=(?:I|my)\b)',text,re.I)
    if contrast:
        result=describe_fact(text[contrast.end():],speaker,cue)
        if result and result['kind'] in {'interest','preference','commitment','discovery'}:return result|{'start':result['start']+contrast.end()}
    m=re.search(r'\b(my|your)\s+((?:(?:personal|favorite|favourite|preferred|main|real|true|little)\s+)?[a-z][a-z -]{0,38}?)\s+(?:is|are|involves?|includes?|consists? of)\s+(.+)',text,re.I)
    if m:
        target=owner(m[1],speaker);attribute=m[2].lower();tags=semantic_terms(attribute)
        kind=next((c for c in ('boundary','interest','preference','role','identity','motivation','origin','residence') if '@'+c in tags),'attribute')
        # Preserve existing slot contracts when upgrading stored facts.
        if kind=='interest':slot='hobby:'+target
        elif kind=='preference':slot='preference:'+target+':'+key(re.sub(r'\b(?:favorite|favourite|preferred)\s*','',attribute))
        else:slot='attribute:'+target+':'+key(attribute)
        return descriptor(slot,kind,m.start(),m[3].strip(),open_relation=kind=='interest')
    m=re.search(r'\b([A-Z][a-z]+)(?: [A-Z][a-z]+)? is (your|my) ([a-z]+)\b',text)
    if m:
        target=owner(m[2],speaker);slot='relationship:'+('participant:' if target=='participant' else '')+m[1].lower()
        return descriptor(slot,'relationship',m.start(),m[3])
    # Habitual activity / emotional attachment: any activity, not a list of objects.
    leisure=re.search(r"\bI(?:['’]ve| have)?(?: been)?\s+(?:spend|spending|pass)\b.{0,60}\b(?:(?:free|spare|leisure) time|(?:my |quiet |free )?(?:evenings|weekends))\b|\b(?:in|during) my (?:free|spare|leisure) time\b|\bwhen I(?:['’]m| am) (?:off duty|not working)\b",text,re.I)
    attachment=re.search(r'\bI\s+(?:(?:really|rather|quite|also|do)\s+)?(?:enjoy|love|like|prefer|delight in)\s+|\bI\s+(?:do\s+)?(?:find|take)\b.{0,75}\b(?:joy|pleasure|satisfaction|comfort|solace|peace|precision|refuge)\b.{0,35}\b(?:in|from)\s+',text,re.I)
    # A changed stance retains the same relation key and original polarity.
    # Only the grammatical index is normalized; stored source wording is untouched.
    stance=re.search(r"\bI (?:do not|don't|no longer|never|now) (like|love|enjoy|prefer)\s+",text,re.I)
    if stance:
        indexed='I '+stance[1]+' '+text[stance.end():]
        result=describe_fact(indexed,speaker,cue)
        if result:return result|{'start':stance.start(),'value':None}
    negation=re.search(r"\bI (?:do not|don't|never)\b",text,re.I)
    if negation:
        contrast=re.search(r'\bbut\s+(?=(?:I|my)\b)',text,re.I)
        if contrast:
            result=describe_fact(text[contrast.end():],speaker,cue)
            if result:return result|{'start':result['start']+contrast.end()}
        if re.search(r"\bI (?:do not|don't) (?:want|like|consent|accept|allow|enjoy)\b",text,re.I):
            return descriptor('boundary:'+owner('I',speaker)+':'+key(text[negation.end():]),'boundary',negation.start())
        return None
    if leisure or attachment:
        m=leisure or attachment;target=owner('I',speaker)
        activity=bool(leisure or re.search(r'\b\w{2,}ing\b',text[m.end():]))
        tail=semantic_terms(text[m.end():]);facet='_'.join(sorted(t for t in tail if not t.startswith('@')))[:65] or 'unspecified'
        return descriptor(('interest:' if activity else 'preference:')+target+':'+facet,'interest' if activity else 'preference',m.start(),open_relation=True)
    # Stable autobiographical predicates, not a whitelist of professions/locations.
    m=re.search(r'\b(I|you)\s+(?:am|are|work as|live in|reside in|grew up in|was born in|were born in)\s+(.+)',text,re.I)
    if m:
        relation=text[m.start()+len(m[1]):m.start(2)].strip().lower();target=owner(m[1],speaker)
        kind='residence' if relation in {'live in','reside in'} else 'origin' if 'born' in relation or 'grew' in relation else 'role' if relation=='work as' or re.match(r'(?:a|an)\s+',m[2],re.I) else 'state'
        return descriptor('attribute:'+target+':'+kind,kind,m.start(),m[2])
    m=re.search(r"\b(?P<subject>I|we)\s+(?:promise to|agreed to|agree to|decided to|commit to|will|['’]ll)\s+(?P<action>.+)",text,re.I)
    if not m:m=re.search(r"\b(?P<subject>I|we)['’]ll\s+(?P<action>.+)",text,re.I)
    if m:
        # Routine meta replies are not durable promises; retain substantive actions.
        action=m['action'];routine=bool(re.search(r'\b(?:reply|respond|say|consider|see what|leave .*unresolved|for a moment)\b',action,re.I))
        base=re.split(r'\s+(?:on|at|by|after|before|when)\b',action,maxsplit=1,flags=re.I)[0]
        subject=owner('I',speaker) if m['subject'].lower()=='i' else 'joint'
        return descriptor('commitment:'+subject+':'+key(base),'routine' if routine else 'commitment',m.start(),action)
    m=re.search(r'\b(?:we|I)\s+(?:discovered|found|learned|revealed)\s+(.+)',text,re.I)
    if m:return descriptor('discovery:'+key(m[1]),'discovery',m.start(),m[1])
    # Subject + copular property: names, story places, possession and changing facts.
    # Requiring an explicit relation avoids treating arbitrary chatter as identity.
    m=re.match(r'\s*(?:(?:Actually|Correction|Now|From now on)[,:]?\s+)?(?:The |the )?([A-Z]?[a-z][a-zA-Z0-9\'’ -]{1,65}?)\s+(is|was|are|were)\s+(.+)',text)
    if m:
        subject=m[1].strip();value=m[3].strip();kind='location' if re.match(r'(?:in|at|under|behind|beside|near|inside|outside)\b',value,re.I) else 'attribute'
        return descriptor('proposition:'+key(subject),kind,m.start(),value)
    # Instructions and hypotheses lacking an asserted relation stay low-value.
    return None

def fact_subject(record):
    parts=record['slot'].removeprefix('hypothesis:').split(':')
    if parts[0]=='relationship' and len(parts)==2:return 'character'
    return parts[1] if len(parts)>1 else None

def fact_tags(record):
    desc=describe_fact(record['text'],record['speaker'],record.get('cue',''))
    tags=semantic_terms(record['slot'])
    if desc:tags.add('@'+desc['kind'])
    if record['category']=='commitment':tags.add('@commitment')
    return tags

def equivalent_fact(left,right):
    """Conservative proposition equivalence; preserve the original source/ID.
    Ignore optional modifiers only; require compatible action AND object concepts.
    """
    negative=r"\b(?:not|never|no longer|former|don't|cannot|can't)\b"
    if bool(re.search(negative,left,re.I))!=bool(re.search(negative,right,re.I)):return False
    a=semantic_terms(left)-{'@interest','@preference'};b=semantic_terms(right)-{'@interest','@preference'}
    # Surface labels do not form part of an asserted value.
    a-={'hobby','hobbies','pastime','personal'};b-={'hobby','hobbies','pastime','personal'}
    a.discard('find');b.discard('find')
    return bool(a and b and (a<=b or b<=a))

def relation_candidates(item,records):
    desc=describe_fact(item['text'],item['speaker'],item.get('cue',''))
    if not desc or not desc.get('open_relation'):return []
    subject=item['slot'].split(':')[1:2]
    return [r for r in records if r['status']=='active' and r['category']!='hypothesis' and r['slot'].split(':')[1:2]==subject and '@'+desc['kind'] in fact_tags(r)]

def correction_anchor(item,records):
    matches=relation_candidates(item,records)
    equivalents=[r for r in matches if equivalent_fact(r['value'],item['value'])]
    if len(equivalents)==1:return equivalents[0]['slot']
    return matches[0]['slot'] if len(matches)==1 else None

def requires_evidence(cue,item):
    historical=bool(re.search(r'\b(?:remember|recall|previously|earlier|did (?:I|you|we)|you told me)\b',cue,re.I))
    if historical:return True
    if re.search(r'\b(?:invent|introduce|imagine|new|suppose|should|could)\b',cue,re.I):return False
    desc=describe_fact(item['text'],item['speaker'],cue)
    return bool(desc and '@'+desc['kind'] in semantic_terms(cue) and re.search(r'\b(?:what|which|where|who|how|when)\b',cue,re.I))

def significance(record):
    """Bounded salience tiers; oldest loses ties, so nothing is permanent."""
    if record['status']!='active' or record.get('curator_omit'):return 0
    if record['category']=='hypothesis':return 1
    desc=describe_fact(record['text'],record['speaker'],record.get('cue',''))
    if desc and desc['kind'] in {'routine','state'}:return 1
    if record.get('reason')=='explicit_user_correction':return 6
    if record['speaker']=='user' and re.search(r'\b(?:important|remember this|keep in mind|do not forget|don.t forget)\b',record['text'],re.I):return 5
    if record['exact']:return 5 if record['speaker']=='user' else 4
    if desc and desc['kind'] not in {'routine','attribute'}:return 4
    if record['slot'].startswith(('relationship:','collection:','preference:','name:','identifier:','boundary:','attribute:')):return 4
    if record['category'] in {'character_detail','commitment'}:return 3
    if desc:return 3
    return 2 if record['speaker']=='user' else 1
