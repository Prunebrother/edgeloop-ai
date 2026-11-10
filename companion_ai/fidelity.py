# SPDX-License-Identifier: AGPL-3.0-only
"""Conservative checks for explicit session claims, not a prose/emotion classifier."""
import re
from .session_history import plain_record

class GroundingError(ValueError):
    def __init__(self,codes):
        self.codes=tuple(codes)
        super().__init__('The model reply conflicted with current EdgeLoop facts after one correction attempt ('+', '.join(codes)+'). No completed reply was saved. Current telemetry may be unavailable; try again.')

NUMERIC_BPM=re.compile(r'\b(\d{1,3}(?:\.\d{1,2})?)\s*(?:bpm|beats\s*(?:per\s*minute|/\s*min))\b',re.I)
# Common whole-BPM word forms, including those seen in actual smoke responses.
ONES={'zero':0,'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,
      'ten':10,'eleven':11,'twelve':12,'thirteen':13,'fourteen':14,'fifteen':15,'sixteen':16,'seventeen':17,'eighteen':18,'nineteen':19}
TENS={'twenty':20,'thirty':30,'forty':40,'fifty':50,'sixty':60,'seventy':70,'eighty':80,'ninety':90}
WORDS=re.compile(r'\b((?:(?:one|two|three) hundred(?: and)?[ -]+)?(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[ -]+(?:one|two|three|four|five|six|seven|eight|nine))?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)|(?:one|two|three) hundred)\s*(?:bpm|beats per minute)\b',re.I)

def word_number(text):
    total=0;part=0
    for word in text.lower().replace('-',' ').split():
        if word=='hundred':part*=100
        elif word!='and':part+=ONES.get(word,TENS.get(word,0))
    return total+part

def explicit_bpm(text):
    clean=text.replace('**','').replace('_','')
    return [(m.start(),m.end(),float(m[1])) for m in NUMERIC_BPM.finditer(clean)]+[(m.start(),m.end(),word_number(m[1])) for m in WORDS.finditer(clean)]

def current_claim(sentence):
    # Negated, conditional or explicitly historical statements are not direct claims.
    return not re.search(r"\b(not|cannot|can't|isn't|aren't|was|were|earlier|previous|historical|whether|if)\b",sentence,re.I)

def timing_violations(text,canonical,completed=()):
    """Narrow checks for explicit duration claims; not a general language verifier."""
    counter=canonical['facts']['seconds'];codes=[]
    for sentence in re.findall(r'[^.!?]+',text):
        historical=re.search(r'\b(?:previous|completed|last|finished)\s+session\b',sentence,re.I)
        if historical:
            duration=re.search(r'\b(\d+(?:\.\d+)?)\s*(seconds?|minutes?|hours?)\b',sentence,re.I)
            if duration and not re.search(r"\b(?:unavailable|unknown|cannot|can't|not known|not measured)\b",sentence,re.I):
                value=float(duration[1])*(60 if duration[2].lower().startswith('minute') else 3600 if duration[2].lower().startswith('hour') else 1)
                final=completed[-1].get('active_running_seconds') if completed else None
                if final is None:codes.append('unavailable_completed_duration')
                elif abs(value-final)>1:codes.append('wrong_completed_duration')
            continue
        if re.search(r"\b(?:unavailable|unknown|not measured|cannot|can't|not known|fictional|imagined|earlier)\b",sentence,re.I):continue
        duration=bool(re.search(r'\b(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:seconds?|minutes?|hours?)\b',sentence,re.I))
        if duration and (re.search(r'\b(?:wall[ -]clock|real time|paused duration|pause (?:has )?lasted|including pauses)\b',sentence,re.I)):
            codes.append('unsupported_wall_or_paused_duration')
        match=re.search(r'\b(?:engine (?:clock|counter)|active running (?:counter|time)|session (?:running time|clock))\b[^0-9]{0,45}(\d+(?:\.\d+)?)\s*(seconds?|minutes?|hours?)\b',sentence,re.I)
        if match:
            if not counter['known'] or not counter['current']:codes.append('unavailable_session_timing')
            else:
                value=float(match[1])*(60 if match[2].lower().startswith('minute') else 3600 if match[2].lower().startswith('hour') else 1)
                tolerance=1 if match[2].lower().startswith('second') else 15
                if abs(value-counter['value'])>tolerance:codes.append('wrong_running_counter')
    return codes

# Natural-language session measurements, on card turns only. A recognised count or duration must match a
# verified value, unless its wording shows it isn't a claim about this session's progress:
# a goal, a hypothetical, fiction, someone else, or something the user said. This is pattern
# matching over common phrasing, not a language verifier, so unusual wording can pass.
NUMBER_WORD=r'(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|a hundred|one hundred|(?:half )?a dozen)'
COUNT=r'(\d{1,4}|'+NUMBER_WORD+r')'
ORDINALS={word:index+1 for index,word in enumerate('first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth'.split())}
ORDINAL=r'(\d{1,3}(?:st|nd|rd|th)|'+'|'.join(ORDINALS)+r')'
EDGE_ADJECTIVE=r'(?:\s+(?:whole|full|solid|clean|verified|confirmed|recorded|logged|counted|total|straight|good|long|hard|separate|distinct|successful|beautiful|perfect|careful))'
EDGE_COUNTS=[re.compile(p,re.I) for p in (
    r'\b'+COUNT+EDGE_ADJECTIVE+r'{0,2}[ -]+edges?\b(?!\s+(?:cases?|lords?|lines?|weights?|detection|computing))(?!\s+of\s+(?:the|a|an|my|his|her|their|our|those|these)\b(?!\s+session))',
    r'\bedges?\s*(?:number|no\.?|#)\s*'+COUNT+r'\b',
    r"\b(?:this is|that's|that is|that was|here's|on|at|reached|hit)\s+edge\s+"+COUNT+r'\b',
    r'\bedged\s+(?:\w+\s+){0,2}?'+COUNT+r'\s+times\b',
    r'\bedged\s+(?:\w+\s+){0,2}?(once|twice|thrice)\b',
    r'\b'+COUNT+r'\s+times?\s+(?:\w+\s+){0,2}?(?:to|at|on|near|over)\s+the\s+edge\b',
    r'\b(once|twice|thrice)\s+(?:\w+\s+){0,2}?(?:to|at|on|near|over)\s+the\s+edge\b',
    r'\b(?:to|at|on|near|over)\s+the\s+edge\s+'+COUNT+r'\s+times\b',
    r'\b(?:to|at|on|near|over)\s+the\s+edge\s+(once|twice|thrice)\b',
    r'\b'+COUNT+r'\s+(?:trips|visits|climbs|approaches|returns)\s+to\s+the\s+edge\b',
    r"\b(?:edge\s+(?:count(?:er)?|tally|total|number|score)|(?:count(?:er)?|tally|total)\s+of\s+edges|total\s+edges|your\s+edges|edges\s+(?:so far|this session))\b(?:\s+\w+){0,3}?\s*(?:is|are|at|of|:|=|reads?|says?|shows?|sits?|stands?|now|to)\s*(?:at\s+)?"+COUNT+r'\b',
)]
EDGE_ORDINAL=re.compile(r'\b'+ORDINAL+r"(?:\s+\w+)?\s+edge\b(?!\s+(?:cases?))",re.I)
PAUSE_COUNTS=[re.compile(p,re.I) for p in (
    r'\bpaused\s+(?:\w+\s+){0,2}?'+COUNT+r'\s+times\b',
    r'\bpaused\s+(?:\w+\s+){0,2}?(once|twice|thrice)\b',
    r'\b'+COUNT+r"\s+pauses?\s+(?:so far|now|already|this session|in this session|today)\b",
    r"\b(?:you've|you have|you|we've|we have)\s+(?:had|taken|made)\s+"+COUNT+r'\s+pauses?\b',
    r'\byour\s+'+COUNT+r'\s+pauses?\b',
    r'\bpause\s+(?:count(?:er)?|tally|total)\b(?:\s+\w+){0,3}?\s*(?:is|at|of|:|=|reads?|says?|shows?|sits?|stands?|now)\s*(?:at\s+)?'+COUNT+r'\b',
)]
QUANTITY=r'(?:\d+(?:\.\d+)?|'+NUMBER_WORD+r'|an?)'
PART=r'\b'+QUANTITY+r'(?:\s+and\s+a\s+half)?[ -]+(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)\b'
DURATION=r'(three quarters? of an hour|(?:a\s+)?quarter(?:\s+of\s+an)?\s+hour|half\s+an\s+hour|(?:a\s+)?half[ -]hour|an?\s+hour\s+and\s+a\s+half|'+PART+r'(?:\s*(?:,|and)?\s*'+PART+r')?)'
DURATION_CLAIMS=[re.compile(p,re.I) for p in (
    r"\b(?:you|you've|you have|you're|you are|we|we've|we have|we're|this session|the session|your session)\b[^,;:]{0,40}?\b(?:been|going|running|lasted|held|holding|stayed|kept|edging|at this|at it|made it|gone|run|survived|endured|clocked|logged|passed|crossed|reached|hit)\b[^,;:]{0,20}?"+DURATION,
    r'\b'+DURATION+r"\s+(?:in\b(?!\s+(?:the|a|an|my)\b)|into\b|so far\b|now\b|already\b|on the clock\b|running\b|elapsed\b|gone\b|down\b|and counting\b|and still\b|ha(?:s|ve) passed\b|of (?:this|running|session|edging|active|runtime|the session)\b)",
    r"\b(?:session (?:has|is|time|length|duration|clock)|time (?:so far|elapsed)|running time|elapsed time|active time|clock (?:is|says|reads|shows))\b[^,;:]{0,30}?"+DURATION,
    r"\bit(?:'s| is| has) been\s+(?:(?:about|around|nearly|almost|over|roughly|just|only)\s+)?"+DURATION+r"(?!\s+since\b(?!\s+(?:you|we)\s+(?:began|started)|\s+the\s+start))",
)]
# Time said to have been spent together. Somewhere else named after it, or a day other than this one, is a story.
_ROUGH=r"(?:(?:about|around|nearly|almost|over|roughly|just|only|some|barely)\s+)?"
_NOT_ELSEWHERE=r"(?!\s+(?:in(?!\s+this\s+session)|at|on|through|across|around|inside|near|under|over|during|while|yesterday|once|last|this\s+(?:week|morning|afternoon|evening|month|year))\b)"
_WITH_ME=r"(?:with\s+(?:me|us)|together|here|in\s+this\s+session|edging|on\s+the\s+edge|at\s+(?:it|this))"
DURATION_CLAIMS+=[re.compile(p,re.I) for p in (
    r"\b(?:you|you've|you have|we|we've|we have)\s+(?:\w+\s+)?(?:spent|shared|had)\s+"+_ROUGH+DURATION+r"\s+"+_WITH_ME+r"\b"+_NOT_ELSEWHERE,
    r"\b(?:you|you've|you have)\s+(?:\w+\s+)?spent\s+"+_ROUGH+DURATION+r"\W*$",
    r"\b(?:i|i've|i have)\s+(?:\w+\s+)?(?:spent|shared)\s+"+_ROUGH+DURATION+r"\s+with\s+you\b"+_NOT_ELSEWHERE,
    r"\b(?:i|i've|i have)\s+(?:had|kept|held)\s+you\s+(?:\w+\s+){0,2}?(?:for\s+)?"+_ROUGH+DURATION+_NOT_ELSEWHERE,
    r"^\W*"+_ROUGH+DURATION+r"\s+(?:with\s+(?:me|you|us)|together)\b"+_NOT_ELSEWHERE,
)]
# "twenty-five minutes and eleven seconds" is one duration. Split at "and", its tail reads as a claim of eleven seconds.
# "We've been walking for two hours" names some other activity, and the character may have a story to tell.
OTHER_ACTIVITY=re.compile(r"\bbeen\s+(?!going\b|running\b|edging\b|holding\b|lasting\b|staying\b|keeping\b|stroking\b|teasing\b|playing\b)\w+ing\b",re.I)
COMPOUND_DURATION=re.compile(PART+r'\s*(?:,|and)\s*'+PART,re.I)
IDIOMS=re.compile(r"\b(?:can't believe|cannot believe|not bad|not only|no doubt|isn't it|aren't you|haven't you|don't you|didn't you|won't you|not even)\b",re.I)
NOT_A_SESSION_CLAIM=re.compile(r"\b(?:if|whether|suppose|supposing|imagine|imagined|imagining|pretend|hypothetical\w*|fiction\w*|story|stories|roleplay|role-play|scene|what if|unless|once upon|in theory|wish|dream\w*)\b",re.I)
ATTRIBUTED=re.compile(r"\b(?:you (?:said|say|told me|mentioned|reported|report|claim(?:ed)?|describe[ds]?)|according to you|you're telling me)\b",re.I)
USER_MEASUREMENT=re.compile(r"\b(?:edg(?:e|es|ed|ing)|minutes?|mins?|hours?|seconds?|pauses?|paused)\b",re.I)
SCHEDULED_PROMPTS=('Director card (','Observed application event (')
PROSPECTIVE=re.compile(r"\b(?:try|trying|aim|aiming|goal|target|next|bet|wager|challenge|could|might|would|should|may|shall|will|going to|gonna|want|hope|plan|let's|let us|see if|see how|need|needs|must|until|till|before|by the time|once|when|another|additional|extra|further|away|to go|left|remaining|short of|ahead|wait\w*|await\w*|upcoming|coming|toward|towards|chas\w*|on the way|closer|nearing|within reach|at a time|per|every|each|typical(?:ly)?|usually|average|most people|some people|normally|generally|then)\b|\b\w+'ll\b|\bmore\b(?! than)|\bmilestone\b(?!.*\b(?:reached|hit|crossed|passed|made)\b)",re.I)
NEGATED=re.compile(r"\b(?:not|never|no longer|cannot|unknown|unavailable|unable|unsure|no way)\b|n['’]t\b",re.I)
OTHER_SUBJECT=re.compile(r"\b(?:she|he|they|her|his|their|someone|my|others?|people|patients?|subjects?|blades?|swords?|knife|knives|razors?|cards?|tables?|cubes?|triangles?|squares?|polygons?|prisms?|graphs?|maps?|frames?|boxes|box|paper|pages?|shapes?|hexagons?|diamonds?|coins?|cliffs?|ledges?|dice)\b",re.I)
PAST_SESSION=re.compile(r"\b(?:(?:previous|completed|last|finished|prior|past|earlier|other)\s+(?:sessions?|outings?|runs?|rounds?|attempts?|bouts?)|last (?:time|night|week)|yesterday|ago|personal best|your best|record|all-time|journal)\b",re.I)
VERIFIABLE_PAST=re.compile(r"\b(?:previous|completed|last|finished|prior)\s+(?:session|outing|run|round|attempt|bout)\b|\blast time\b",re.I)
HAS_VERB=re.compile(r"\b(?:you've|you're|you|we've|we're|we|that's|it's|i've|i|have|has|had|is|are|reached|hit|made|got|logged|counted)\b",re.I)
PAST_TENSE=re.compile(r"\b(?:was|were|had|felt|came|went)\b",re.I)
AT_LEAST=r"(?:more than|over|at least|past|passed|beyond|above|north of|upwards of|surpassed|crossed|exceeded)"
AT_MOST=r"(?:fewer than|less than|under|at most|no more than|not even)"
ROUGHLY=r"(?:about|around|roughly|approximately|nearly|almost|close to|just under|just over|some)"

def spoken_number(text):
    text=text.lower().strip()
    if re.fullmatch(r'\d+(?:\.\d+)?',text):return float(text)
    if text in {'once','a','an'}:return 1
    if text=='twice':return 2
    if text=='thrice':return 3
    if text=='a dozen':return 12
    if text=='half a dozen':return 6
    return word_number(text.replace('a hundred','one hundred'))

def spoken_ordinal(text):
    text=text.lower()
    return int(text[:-2]) if text[0].isdigit() else ORDINALS[text]

def seconds_said(text):
    """Returns (seconds, tolerance) for a spoken duration."""
    text=text.lower()
    for pattern,value,tolerance in ((r'three quarters?',2700,300),(r'quarter',900,300),(r'\ban?\s+hour\s+and\s+a\s+half',5400,900),(r'half[ -]?(?:an\s+)?hour',1800,300)):
        if re.search(pattern,text):return value,tolerance
    total=0;tolerance=20
    for quantity,half,unit in re.findall(r'('+QUANTITY+r')(\s+and\s+a\s+half)?[ -]+(sec|min|hour|hr)',text,re.I):
        size={'sec':1,'min':60,'hour':3600,'hr':3600}[unit]
        total+=(spoken_number(quantity)+(.5 if half else 0))*size
        tolerance={'sec':20,'min':90,'hour':900,'hr':900}[unit]
    return total,tolerance

def direction_of(prefix):
    prefix=prefix[-30:]
    for name,words in (('at_most',AT_MOST),('at_least',AT_LEAST),('roughly',ROUGHLY)):
        if re.search(r'\b'+words+r'\s+(?:\w+\s+)?$',prefix,re.I):return name
    return 'exact'

def supported(value,direction,verified,tolerance=0,past=False):
    if not verified:return False
    if direction=='at_least':return max(verified)+tolerance>=value
    if direction=='at_most':return min(verified)-tolerance<=value
    margin=max(tolerance,1) if direction=='roughly' else tolerance
    if past and value<=max(verified)+margin:return True
    return any(abs(value-known)<=margin for known in verified)

def clauses_of(sentence):
    """Clauses, each knowing whether its wording, or an unfinished neighbour's, excludes it."""
    joined=COMPOUND_DURATION.sub(lambda m:m[0].replace(',','\0').replace(' and ',' \1 '),IDIOMS.sub(' ',sentence))
    parts=[c.replace('\0',',').replace('\1','and') for c in re.split(r"[,;:—–]|\s-\s|\s(?:and|but)\s",joined) if c.strip()]
    own=[bool(PROSPECTIVE.search(c) or NEGATED.search(c) or OTHER_SUBJECT.search(c)) for c in parts]
    result=[]
    for index,part in enumerate(parts):
        excluded=own[index]
        if not excluded and not HAS_VERB.search(part):
            excluded=(index>0 and own[index-1]) or (index+1<len(parts) and own[index+1])
        result.append((part,excluded))
    return result

def verified_values(field,canonical,told,trigger,completed,result_key=None):
    """The values a claim may state: this turn's facts, and only those facts."""
    result=(trigger or {}).get('session_result')
    if result:
        value=result.get(result_key or field)
        return {value} if value is not None else set()
    fact=canonical['facts'][field];values=set()
    if fact['known'] and fact['current']:
        values.add(fact['value'])
        # The counter can advance during generation; what the model was told still stands.
        for earlier in told or ():
            if earlier and earlier.get('session_id')==canonical.get('session_id'):
                seen=earlier['facts'].get(field)
                if seen and seen['known'] and seen['current']:values.add(seen['value'])
    status=canonical['facts']['status']
    if status['current'] and status['value']=='IDLE':
        values.update(record[result_key or field] for record in completed if record.get(result_key or field) is not None)
    return values

def measurement_violations(clean,canonical,told,trigger,completed,user_text):
    codes=[];completed=list(completed or ())
    edges=verified_values('edges',canonical,told,trigger,completed);pauses=verified_values('pauses',canonical,told,trigger,completed)
    seconds=verified_values('seconds',canonical,told,trigger,completed,'active_running_seconds')
    for sentence in re.findall(r'[^.!?\n]+(?:\.\d+[^.!?\n]*)*[.!?\n]?',clean):
        tag=re.search(r"(?:,\s*(?:right|haven't you|isn't it|didn't you|aren't you|no|yes|eh)\s*\?)\s*$",sentence,re.I)
        if sentence.rstrip().endswith('?') and not tag:continue
        if NOT_A_SESSION_CLAIM.search(sentence) or (ATTRIBUTED.search(sentence) and USER_MEASUREMENT.search(user_text)) or re.search(r'["“”]',sentence):continue
        for clause,excluded in clauses_of(sentence):
            if excluded:continue
            past_session=PAST_SESSION.search(sentence)
            past=bool(PAST_TENSE.search(clause))
            for pattern in EDGE_COUNTS:
                for match in pattern.finditer(clause):
                    said=spoken_number(match[1])
                    if said==1 and re.search(r'\bthe\s+$',clause[:match.start()],re.I):continue
                    if past_session:
                        if VERIFIABLE_PAST.search(sentence) and said not in {record.get('edges') for record in completed}:codes.append('unsupported_completed_edges')
                        continue
                    if not supported(said,direction_of(clause[:match.start()]),edges,past=past):codes.append('wrong_edges')
            if not past_session:
                for match in EDGE_ORDINAL.finditer(clause):
                    said=spoken_ordinal(match[1])
                    present=re.search(r"\b(?:that's|that is|this is|here's|now|just)\b",clause[:match.start()],re.I)
                    if not edges or (said not in edges if present and not past else said>max(edges)):codes.append('wrong_edges')
                for pattern in PAUSE_COUNTS:
                    for match in pattern.finditer(clause):
                        if not supported(spoken_number(match[1]),direction_of(clause[:match.start()]),pauses,past=past):codes.append('wrong_pauses')
                for pattern in DURATION_CLAIMS:
                    for match in pattern.finditer(clause):
                        if re.search(r'\b(?:wall[ -]clock|real time|including pauses)\b',clause,re.I):continue
                        if re.search(r'\bby\s+(?:\w+\s+)?$',clause[:match.start(1)],re.I):continue
                        if OTHER_ACTIVITY.search(clause[:match.start(1)]):continue
                        value,tolerance=seconds_said(match[1])
                        if not seconds:codes.append('unavailable_session_timing')
                        elif not supported(value,direction_of(clause[:match.start(1)]),seconds,tolerance,past):codes.append('wrong_running_counter')
    return codes

# Wording that presents a reading as an authenticated measurement of a real body.
PHYSICAL_READING=re.compile(r"\b(?:real(?!-time)|actual|physical|authentic(?:ated)?|genuine|biometric)\s+(?:\w+\s+)?(?:heart ?rate|heart ?beat|pulse|bpm|readings?|measurements?|samples?|data)\b",re.I)
MEASURED_READING=re.compile(r"\b(?:verified|confirmed|measured|recorded|validated|sensor)\s+(?:\w+\s+)?(?:heart ?rate|heart ?beat|pulse|bpm|readings?|measurements?)\b|\b(?:heart ?rate|heart ?beat|pulse|bpm)\b.{0,25}\b(?:measured|verified|confirmed|authenticated)\b",re.I)
SENSOR_READING=re.compile(r"\b(?:BLE|Polar(?: H10)?|sensor|monitor|strap|wearable)\b(?:\s+\w+){0,2}?\s+(?:reads?|reading|says?|picked up|registers?|registered|detect(?:s|ed)?|logs?|logged|has you at|puts you at|captured|measured)\b|\bfrom\s+(?:your|the)\s+(?:\w+\s+)?(?:BLE|Polar|sensor|monitor|strap|wearable)\b",re.I)
SENSED_BODY=re.compile(r"\bI\s+(?:can\s+)?(?:feel|hear|sense|detect)\b.{0,25}\byour\s+(?:pulse|heart(?:\s?beat| rate)?)\b",re.I)
BODY_STATE=re.compile(r"\byour\s+(?:own\s+)?(?:current\s+)?(?:resting\s+)?(?:heart(?:\s?beat| rate)?|pulse)\b.{0,60}\b(?:\d{2,3}\b|pounding|thumping|hammering|elevated|spik(?:ed|ing)|jump(?:ed|ing)|drop(?:ped|ping)|settl(?:ed|ing)|slow(?:ed|ing)|calm(?:ed|ing)?)\b",re.I)
SIMULATION_LABEL=re.compile(r"\b(?:simulat\w*|derived|not physical)\b",re.I)
# Contrast or doubt about a physical measurement is the honest thing to say, not a claim to one.
NOT_CLAIMING_PHYSICAL=re.compile(r"\b(?:rather than|instead of|without|until|unless|whether|if)\b",re.I)

def provenance_violations(sentence):
    """Only for a simulated source. Labelled simulation readings stay allowed."""
    if NEGATED.search(sentence) or NOT_CLAIMING_PHYSICAL.search(sentence) or sentence.rstrip().endswith('?'):return []
    if PHYSICAL_READING.search(sentence) or SENSED_BODY.search(sentence):return ['simulated_reading_presented_as_physical']
    if SIMULATION_LABEL.search(sentence):return []
    if MEASURED_READING.search(sentence) or SENSOR_READING.search(sentence) or BODY_STATE.search(sentence):return ['simulated_reading_presented_as_physical']
    return []

# How a run was produced isn't dialogue. Attributing a heart rate as simulated stays allowed, and "synthetic"
# alone stays allowed because it can be a character's own nature (Nova's "synthetic mind").
CARD_TEST_LANGUAGE=re.compile(r"(?<!\bmy )(?<!\bthis )\bsynthetic[- ](?:test|session|run|data|rhythm|pulse|heart|values?|numbers?|edges?|counts?|telemetry)\b|\btest[- ](?:run|session|data|drive)\b|\bsimulat\w*[- ](?:session|run|test|data|edges?|counts?|numbers?|values?)\b|\bedge[- ]counter\b|\btelemetry\b",re.I)

_ENDED_SUBJECT=r"(?:session|training|tease|experience|run)"
_ENDED_WORD=r"(?:over|ended|finished|done|complete|completed|concluded|closed|wrapped up|stopped|finali[sz]ed)"
_ENDED_ADVERB=r"(?:now |officially |finally |all |truly |at last )*"
# Claims that the session has ended. A mission, milestone, objective or goal may be complete.
SESSION_ENDED=re.compile(
 rf"\b{_ENDED_SUBJECT}(?:['’]s| is| has| has been| was)?\s+{_ENDED_ADVERB}{_ENDED_WORD}\b"
 rf"|\b(?:end|close|conclusion|finish|completion|finale)\s+of\s+(?:your|our|this|the)\s+(?:[\w'’-]+\s+){{0,3}}{_ENDED_SUBJECT}\b"
 rf"|\b(?:ended|finished|completed|concluded|wrapped up|closed out|stopped|finali[sz]ed)\s+(?:your|our|this|the)\s+(?:[\w'’-]+\s+){{0,3}}{_ENDED_SUBJECT}\b"
 rf"|\b(?:we|you)(?:['’]re|['’]ve| are| have)?\s+{_ENDED_ADVERB}(?:done|finished)\b(?!\s+(?:with\s+)?(?:this|that|the|your)\s+(?:mission|milestone|objective|goal))"
 rf"|\b(?:job|work)(?:['’]s| is)?\s+{_ENDED_ADVERB}(?:done|finished|over)\b"
 r"|\bthat['’]?s a wrap\b|\bcall(?:ing)?\s+(?:it|this|that)(?:\s+\w+)?\s+(?:a day|done|finished|quits)\b|\bearned\s+(?:your|this|a)(?:\s+\w+){0,3}\s+rest\b",re.I)
_NOT_A_CLAIM=re.compile(r"\b(?:not|never|no|yet|before|until|till|if|when|once|unless|still|almost|nearly|soon|will)\b|n['’]t\b|['’]ll\b",re.I)

def premature_session_end(text):
    """A plain claim of an ending. Negations, conditions, futures and questions don't count."""
    for sentence in re.findall(r"[^.!?;]+[.!?;]*",text):
        if sentence.rstrip().endswith('?') or _NOT_A_CLAIM.search(sentence):continue
        if SESSION_ENDED.search(sentence):return True
    return False

# Arrival and Closing cards only. Every figure of an earlier session must be one that was dealt.
FIRST_SESSION=re.compile(r"\b(?:first|maiden|inaugural)\s+(?:\w+\s+)?(?:session|time|meeting|encounter|outing|collaboration)\b|\bnever\s+(?:\w+\s+)?(?:met|done this|had a session|worked together)\b|\b(?:haven['’]t|have not|hadn['’]t)\s+(?:\w+\s+)?(?:met|had a session|worked together)\b|\bfresh start\b|\bnew beginning\b|\bfinally (?:meet|met|meeting)\b",re.I)
SHARED_PAST=re.compile(r"\b(?:welcome back|back again|you(?:['’]re| are)? back|came back|come back|hello again|see(?:ing)? you again|good to have you back|missed you|been a while|been too long|long time|(?:last|previous|prior|earlier|other)\s+(?:time|session|sessions|run|round|visit|outing|attempt)|since (?:we|you|i) last|since our last|our last|we last|as before|remember when|like before)\b",re.I)
PAST_MARKER=re.compile(r"\b(?:(?:last|previous|prior|earlier)\s+(?:time|session|round|visit|outing|attempt)|previously|back then|that session|before|ago|our last|your last|we last)\b",re.I)
MORE_EDGES=re.compile(r"\b(?:more|additional|extra)\s+edges?\b|\bedges?\s+(?:more|up)\b|\bup from\b",re.I)
FEWER_EDGES=re.compile(r"\b(?:fewer|less)\s+edges?\b|\bedges?\s+(?:fewer|down|short)\b|\bdown from\b",re.I)
LONGER=re.compile(r"\b(?:longer|outlasted|more time)\b",re.I)
SHORTER=re.compile(r"\b(?:shorter|briefer|less time|shrank|cut short|trails?|trailed|trailing)\b",re.I)
BRISK=re.compile(r"\b(?:brisk|brisker|tighter|brevity)\b",re.I)
SAME_AS_BEFORE=re.compile(r"\b(?:identical|match(?:es|ed|ing)?\s+(?:the\s+(?:last|previous)|(?:\w+\s+)?(?:count|number|tally|figures?))|same\s+(?:count|number|(?:length|duration|running\s+time)(?!\s+of\b))|mirror(?:s|ed|ing)?)\b",re.I)
NEAR_NEGATION=re.compile(r"(?:\b(?:not|no|never|neither|nor|nothing about|without|cannot)\b|n['’]t\b)\W+(?:\w+\W+){0,2}$",re.I)
NEXT_TIME=re.compile(r"\bnext\b|\bagain\b|\b(?:could|would|should|might|shall|let['’]s|see if)\b|['’]ll\b",re.I)
# "the last one" names a session, not a figure of one.
NAMED_PRIOR=re.compile(r"\b(?:previous|last|prior|earlier|usual)\s+(?!one\b)"+COUNT+r"\b(?![ -]+(?:minutes?|mins?|seconds?|secs?|hours?|hrs?|days?|weeks?|months?|edges?))",re.I)
NOT_A_COUNT=r"(?![ -]*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?|times?|of\s+(?:us|you|them)|hundred)\b)"
EDGE_DIFFERENCE=re.compile(r'\b'+COUNT+r'\s+(?:(more|extra|additional|fewer|less)\s+(?:edges?\b|than\b)|edges?\s+(up|down|more|fewer|short)\b)|\b(rise|gain|jump|increase|drop|fall|dip|decline|loss)\s+of\s+'+COUNT+NOT_A_COUNT,re.I)
INCREASE_WORD=re.compile(r'more|extra|additional|up|rise|gain|jump|increase',re.I)
# One figure against another: only when the figure named is the earlier session's edge count.
EDGES_ABOVE=re.compile(r"\b(?:(?:more|greater|higher)\s+than|beats?|surpass\w*|exceed\w*|outnumber\w*|tops?)\s+(?:(?:the|your|our|those|that|last|previous|prior)\s+)*"+COUNT+r"\b"+NOT_A_COUNT,re.I)
EDGES_BELOW=re.compile(r"\b(?:(?:fewer|less|lower)\s+than|short\s+of|shy\s+of|under|below)\s+(?:(?:the|your|our|those|that|last|previous|prior)\s+)*"+COUNT+r"\b"+NOT_A_COUNT,re.I)
CLAUSE_BREAK=re.compile(r"[;:—–]|\s-\s|,?\s+\b(?:but|yet|though|although|while|even if|even though)\b",re.I)
COMPARED_WITH=re.compile(r"\b(?:than|compared|against|versus|instead of)\b",re.I)
PRIOR_REFERENCE=re.compile(r"\b(?:last|previous|prior|earlier)\s+(?:[\w-]+\s+)?(?:time|session|run|outing|round|attempt|bout|visit|stop|one|marathon|sprint)\b|\b(?:your|our)\s+last\b|\b(?:than|from)\s+before\b",re.I)
# "Longer than I expected" compares with an expectation, and "stay a little longer" with nothing.
THAN_EXPECTED=re.compile(r"\bthan\s+(?:(?:i|we|you)(?:['’]d)?\s+(?:expected|thought|think|hoped|imagined|guessed|predicted|would)\b|expected\b|usual\b)",re.I)
LOOKS_AHEAD=re.compile(r"\bnext\b|\b(?:let['’]s|let\s+us|see\s+if|could|might|shall|try|aim)\b",re.I)
SESSION_LENGTH=re.compile(r"\b(?:longer|shorter|briefer)\s+(?:\w+\s+)?(?:run|session|stretch|outing|sitting|one|haul|effort|attempt|bout)\b|\b(?:this|it|run|session|stretch|outing)\b(?:['’]s)?\s+(?:was|is|felt|feels|ran|seemed|seems|went|lasted)\s+(?:\w+\s+){0,2}?(?:longer|shorter|briefer)\b",re.I)
CURRENT_REFERENCE=re.compile(r"\bthis\s+(?:[\w-]+\s+)?(?:time|session|run|outing|round|attempt|bout|one)\b|\btoday\b|\bnow\b",re.I)
# Words whose object is the earlier session: it is the yardstick then, not the thing described.
YARDSTICK=re.compile(r"\b(?:than|as|compared\s+(?:to|with)|against|versus|vs\.?|relative\s+to|from|since|after|over|short\s+of|outpac\w*|beat\w*|outlast\w*|outdid|surpass\w*|top(?:s|ped)?|exceed\w*|trail\w*)\s+(?:[\w-]+\s+){0,2}?$",re.I)
CURRENT_YARDSTICK=re.compile(r"\b(?:than|as|compared\s+(?:to|with)|against|versus|vs\.?)\s+(?:[\w-]+\s+){0,2}?$",re.I)
# Conjoined predicates each make their own claim, so negation and subject are read per part.
PART_BREAK=re.compile(r",|\b(?:and|or)\b",re.I)
# What a clause with no session of its own needs before it can be read as continuing a comparison: "but had fewer edges".
STATES_RESULT=re.compile(r"\b(?:had|ran|went|lasted|was|were|got|made|managed|finished|stopped|logged)\b",re.I)
OWN_SUBJECT=re.compile(r"\W*(?:you|you['’]\w+|we|we['’]\w+|it|it['’]s|this|that|the)\b",re.I)
# "That last session's shorter run": the possessive settles it, whatever else the sentence does with that session.
PRIOR_POSSESSIVE=re.compile(r"\b(?:last|previous|prior|earlier)\s+\w+['’]s\s+(?:\w+\s+)?$",re.I)
ONE_BEFORE=re.compile(r"\b(?:one|session|run|time)\s+before\b",re.I)
# "You went longer this time" has no earlier session in it, but it does claim a direction.
RAN_THIS_TIME=re.compile(r"\b(?:you|we)(?:['’]ve)?\s+(?:went|ran|lasted|held\s+on|kept\s+going|stayed)\b",re.I)
AS_LONG=re.compile(r"\bas\s+long\s+as\s+(?:(?:the|your|our|that)\s+)?(?:last|previous|prior|earlier)\b",re.I)
AS_MANY=re.compile(r"\bas\s+many\s+(?:edges\s+)?as\s+(?:(?:the|your|our|that)\s+)?(?:last|previous|prior|earlier)\b",re.I)
# Each session has its own figures, so one credited to the wrong session is wrong even though it was dealt.
_UNIT=r"(edges?|minutes?|mins?)"
_SESSION_WORD=r"(?:time|session|run|round|outing|attempt|bout)"
_PRIOR_NAME=r"(?:last|previous|prior|earlier)\s+"+_SESSION_WORD
_THIS_NAME=r"this\s+"+_SESSION_WORD
# Words that put a second figure or a comparison between a figure and the session named after it.
_NOT_BETWEEN=r"than|against|compared|versus|over|off|beats?|beating|past|from|to|of|more|fewer|less|longer|shorter|short|shy|up|down|under|above|below|and|after|since|behind|ahead|match\w*"
FIGURE_THEN_SESSION=re.compile(r"\b"+COUNT+r"(?:[ -]+"+_UNIT+r")?\s+((?:(?!(?:"+_NOT_BETWEEN+r")\b)\w+\s+){0,3}?)(?:(?:in|on|at|during)\s+)?(?:(?:(?:the|your|our|that)\s+)?("+_PRIOR_NAME+r")|("+_THIS_NAME+r"))\b",re.I)
SESSION_THEN_FIGURE=re.compile(r"\b(?:("+_PRIOR_NAME+r")(?:['’]s\s+(?:\w+\s+)?|\s+(?:had|ran|lasted|took|gave|managed|reached|hit|yielded)\s+(?:\w+\s+)?)|("+_THIS_NAME+r")['’]s\s+(?:\w+\s+)?)"+COUNT+r"(?:[ -]+"+_UNIT+r")?\b(?![ -]+(?:more|fewer|less|longer|shorter)\b)",re.I)
FINAL_EDGE=re.compile(r"\b(?:after|stop\w*|end\w*|quit|finish\w*|wrap\w*|final|halt\w*)\b",re.I)
AS_RUNNING_TIME=re.compile(r"\s+of\s+(?:running\s+time|runtime|run\s+time)\b|\s+(?:duration|session|marathon)\b",re.I)
RAN_FOR=re.compile(r"\b(?:ran|lasted)\s+(?:for\s+)?(?:\w+\s+)?$",re.I)
TIME_DIFFERENCE=re.compile(DURATION+r'\s+(?:longer|shorter|more|less)\b',re.I)
ANY_DURATION=re.compile(DURATION+r'(?!\s+ago\b)',re.I)
TIME_QUANTITY=r'('+QUANTITY+r'|a few|a couple of|couple of|several)\s+(hours?|days?|weeks?|months?|years?)'
# Anchored to wording about the gap, so "three days in the greenhouse" stays the character's own story.
TIME_SINCE=[re.compile(p,re.I) for p in (
    r'\b'+TIME_QUANTITY+r'\s+(?:ago|since|away|apart|later)\b',
    r"\b(?:it['’]s been|it has been|been|after)\s+(?:(?:about|almost|nearly|over|only|just|roughly|around)\s+)?"+TIME_QUANTITY+r'\b(?!\s+(?:in|at|of|on|with)\b)',
    r'^\W*'+TIME_QUANTITY+r'\s+(?:and|without)\b')]
NAMED_TIME={'yesterday':(12,48),'last night':(6,30),'last week':(120,336),'last month':(480,1440),'this morning':(0,14),'earlier today':(0,20)}
NAMED_TIME_PATTERN=re.compile(r'\b(?:'+'|'.join(NAMED_TIME)+r')\b',re.I)
# A statement of health or fitness as fact. Teasing about stamina or asking what someone felt is the character's voice.
_CAPACITY=r"(?:fitness|health|conditioning|stamina|endurance|physiology|cardio\w*)"
BODY_INFERENCE=re.compile(r"\b(?:fitter|healthier)\b|\b"+_CAPACITY+r"(?:\s+of\s+yours)?\s+(?:(?:has|have|is|are|was|were)\s+)?(?:(?:clearly|really|now|already|certainly|definitely)\s+)?(?:improv\w+|better|stronger|sharpen\w*|grow\w*|increas\w*|declin\w*|wors\w*|weak\w*)\b|\b(?:improv\w+|build\w*|built|strengthen\w*)\s+(?:your\s+)?"+_CAPACITY+r"\b|\byour\s+(?:health|heart|muscles|nerves)\s+(?:(?:is|are|has|have|must\s+be|looks?|seems?)\b)|\b(?:saw|watched|heard|felt)\s+you\s+(?:\w+\s+){0,2}(?:trembl|shak|gasp|pant|sweat|shiver|quiver)\w*",re.I)
OBJECTIVE_STANDARD=re.compile(r"\bobjectively\b|\bby any (?:objective |reasonable )?(?:standard|measure)\b|\b(?:clinically|medically)\b|\bscientifically (?:proven|established|verified)\b|\bverified (?:standard|benchmark)\b",re.I)
# "Either your stamina is growing or you refuse to yield" offers a reading, not a verified fact.
UNCERTAIN=re.compile(r"\b(?:either|perhaps|maybe|might|may|could|possibly|probably|suspect|wonder|guess|suppose|wager|if|whether)\b|\?\s*$",re.I)

# Whether a figure is said of a session, or of something else altogether. The checks on these cards exist
# for the session's record, so a character's afternoon in the greenhouse is none of their business.
ADDRESSEE=re.compile(r"\b(?:you|you['’]\w+|your|we|we['’]\w+|our)\b",re.I)
FIRST_PERSON=re.compile(r"\b(?:i|i['’]\w+|me)\b",re.I)
SESSION_NAMED=re.compile(r"\b(?:this|that|the|your|our)\s+(?:[\w'’-]+\s+)?session\b|\b(?:last|previous|prior)\s+session\b",re.I)
YOUR_RUN=re.compile(r"\b(?:this|your|our)\s+(?:[\w'’-]+\s+)?(?:run|outing|attempt|round|bout|stretch|sitting|marathon)\b",re.I)
PERFORMANCE=re.compile(r"\b(?:you|you['’](?:ve|d)|you\s+have|we|we['’](?:ve|d)|we\s+have)\s+(?:\w+\s+){0,2}?(?:lasted|ran|run|held|stayed|kept|edged|survived|endured|clocked|logged|stopped|finished|managed|went|gone|made\s+it)\b",re.I)
BARE_FIGURE=re.compile(r"^\W*(?:(?:just|only|barely|nearly|almost|about|around|over|under|exactly|that['’]s|that\s+(?:was|is)|it\s+(?:was|ran|lasted))\s+)*$",re.I)
BARE_ENDING=re.compile(r"^\s*(?:longer|shorter|flat|total|exactly|straight)?\W*$",re.I)
# "A mere thirteen minutes" passes judgment on a figure, and on these cards the figure is the session's.
JUDGED_FIGURE=re.compile(r"\b(?:mere|measly|paltry|tidy|solid|respectable|impressive|pathetic|whole|full)\s+$",re.I)

# "Ninety minutes with me." has no subject to make it anyone else's.
TIME_WITH_ME=re.compile(r"^\W*"+_ROUGH+DURATION+r"\s+(?:with\s+(?:me|you|us)|together)\b"+_NOT_ELSEWHERE,re.I)

def anecdote(sentence):
    """Somebody else's, or the speaker's own, with neither the person addressed nor a session in it."""
    return bool((OTHER_SUBJECT.search(sentence) or FIRST_PERSON.search(sentence)) and not ADDRESSEE.search(sentence) and not SESSION_NAMED.search(sentence))

def clause_at(sentence,position):
    """The clause holding position, split where clauses_of splits."""
    start=0
    for match in re.finditer(r"[,;:—–]|\s-\s|\s(?:and|but)\s",sentence):
        if match.end()<=position:start=match.end()
        elif match.start()>=position:return sentence[start:match.start()]
    return sentence[start:]

def session_figure(sentence,match):
    """Whether this duration is stated about a session or the person's performance in one."""
    before,after=sentence[:match.start(1)],sentence[match.end(1):]
    if SESSION_NAMED.search(sentence) or TIME_WITH_ME.search(sentence):return True
    if anecdote(sentence) or OTHER_ACTIVITY.search(before):return False
    if PRIOR_REFERENCE.search(sentence) or YOUR_RUN.search(sentence) or re.search(r"\byour\s+$",before,re.I):return True
    if AS_RUNNING_TIME.match(after) or RAN_FOR.search(before) or JUDGED_FIGURE.search(before) or BARE_FIGURE.match(before) and BARE_ENDING.match(after):return True
    if re.search(PERFORMANCE.pattern+r"(?:\s+\w+){0,3}?\s*$",before,re.I) or PERFORMANCE.search(after):return True
    return any(pattern.search(sentence) for pattern in DURATION_CLAIMS)

def history_records(summary,completed):
    """On these cards the dealt facts replace other history, so absent access can't be filled in."""
    history=(summary.get('deck_card') or {}).get('history')
    if history is None:return completed
    prior=history.get('prior') if history.get('status')=='found' and (history.get('prior') or {}).get('comparable') else None
    current=history.get('current')
    # The check for a named earlier session reads the last entry, so the earlier session goes last.
    return [{'edges':r.get('edges'),'active_running_seconds':r.get('seconds')} for r in (current,prior) if r]

def history_checked(codes,summary,text=None):
    """history_violations checks earlier-session durations with spoken-rounding tolerance instead."""
    card=summary.get('deck_card') or {}
    history=card.get('history')
    if history is None:return codes
    dropped={'wrong_completed_duration','unavailable_completed_duration'}|({'wrong_running_counter','unavailable_session_timing'} if card.get('lane')=='arrival' else set())
    # A difference or the earlier session's count is true here, and the general edge check knows neither.
    known={r.get('edges') for r in (history.get('prior'),history.get('current')) if r}|{((history.get('comparison') or {}).get('edges') or {}).get('difference')}
    if text is not None and history.get('prior') and {spoken_number(m[1]) for pattern in EDGE_COUNTS for m in pattern.finditer(text)}<=known:dropped|={'wrong_edges','unsupported_completed_edges'}
    return [code for code in codes if code not in dropped]

def part_bounds(clause,start,end,limit=None):
    limit=len(clause) if limit is None else limit
    left=max((m.end() for m in PART_BREAK.finditer(clause,0,start)),default=0)
    following=PART_BREAK.search(clause,end,limit)
    return left,following.start() if following else limit

def fragment(clause,match):
    """The words of a match's own part: "could" further along doesn't make a stated figure a wish, nor a negation of something else deny it."""
    left,right=part_bounds(clause,match.start(),match.end())
    return clause[left:right]

def not_stated(clause,match):
    part=fragment(clause,match)
    return bool(LOOKS_AHEAD.search(part) or NEGATED.search(part))

def flipped(direction):return 'decrease' if direction=='increase' else 'increase'

def session_named(clause,lo,hi):
    """The sessions named in clause[lo:hi], in order. One that is only a yardstick names this session as the subject."""
    found=[(m.start(),'current' if YARDSTICK.search(clause[:m.start()]) or m[0].lower().startswith(('than','from')) else 'prior') for m in PRIOR_REFERENCE.finditer(clause) if lo<=m.start() and m.end()<=hi]
    found+=[(m.start(),'prior' if CURRENT_YARDSTICK.search(clause[:m.start()]) else 'current') for m in CURRENT_REFERENCE.finditer(clause) if lo<=m.start() and m.end()<=hi]
    return [name for _,name in sorted(found)]

def compared_subject(clause,match,carried=None):
    """Which session a comparative describes, whichever end of the sentence names it.

    "More edges than last time" holds this session up against the earlier one, and "than this" the reverse.
    Otherwise it is the session named nearest: "last time you lasted longer", "you went longer last time".
    """
    start,end=match.start(),match.end();limit=len(clause)
    if PRIOR_POSSESSIVE.search(clause[:start]):return 'prior'
    pivot=COMPARED_WITH.search(clause,end)
    if pivot:
        if PRIOR_REFERENCE.search(clause,pivot.start()) or ONE_BEFORE.search(clause,pivot.start()):return 'current'
        if CURRENT_REFERENCE.search(clause,pivot.start()):return 'prior'
        limit=pivot.start()
    left,right=part_bounds(clause,start,end,limit)
    comma=clause.rfind(',',0,start)+1;after=clause.find(',',end,limit)
    after=limit if after<0 else after
    for lo,hi,pick in ((left,start,-1),(end,right,0),(comma,start,-1),(end,after,0),(0,start,-1),(end,limit,0)):
        names=session_named(clause,lo,hi)
        if names:return names[pick]
    return carried or 'current'

def relation(increase,subject,negated):
    """What a comparative says of this session's own figure, which is what the computed comparison describes."""
    direction='increase' if increase else 'decrease'
    if subject=='prior':direction=flipped(direction)
    return 'not_'+direction if negated else direction

def negated_here(clause,match):
    """A negation of this comparative itself, within its own part of the sentence."""
    return bool(NEAR_NEGATION.search(clause[part_bounds(clause,match.start(),match.end())[0]:match.start()]))

def contradicts(claim,direction):
    return direction==claim[4:] if claim.startswith('not_') else claim!=direction

def length_claims(clause,carried=None,continuing=False):
    """Every relation this clause claims for this session's length, each comparative on its own."""
    if THAN_EXPECTED.search(clause):return []
    claims=[]
    same=AS_LONG.search(clause)
    if same and not LOOKS_AHEAD.search(fragment(clause,same)):
        claims.append('decrease' if negated_here(clause,same) else 'unchanged')
    for pattern,increase in ((LONGER,True),(SHORTER,False),(BRISK,False)):
        for match in pattern.finditer(clause):
            brisk=pattern is BRISK
            referenced=COMPARED_WITH.search(clause) or PRIOR_REFERENCE.search(clause) or continuing and STATES_RESULT.search(fragment(clause,match))
            # "Wasn't longer than last time" still says something checkable: it rules one direction out.
            if not brisk and not LOOKS_AHEAD.search(fragment(clause,match)) and negated_here(clause,match) and referenced:
                claims.append(relation(increase,compared_subject(clause,match,carried),True));continue
            if not_stated(clause,match):continue
            if not referenced and (brisk or not (SESSION_LENGTH.search(clause) or CURRENT_REFERENCE.search(clause) and RAN_THIS_TIME.search(clause))):continue
            subject=compared_subject(clause,match,carried)
            # Brisk describes one session, so calling the earlier one brisk says nothing of this one.
            if brisk:
                if subject=='current':claims.append('brisk')
                continue
            # "That last session's shorter run" describes the earlier session, so this one was the longer.
            claims.append(relation(increase,subject,False))
    return claims

def edge_claims(clause,prior_edges,carried=None):
    """Every direction this clause claims for this session's edge count, each comparative on its own."""
    claims=[]
    same=AS_MANY.search(clause)
    if same and not LOOKS_AHEAD.search(fragment(clause,same)):claims.append('decrease' if negated_here(clause,same) else 'unchanged')
    for pattern,increase in ((MORE_EDGES,True),(FEWER_EDGES,False)):
        for match in pattern.finditer(clause):
            if LOOKS_AHEAD.search(fragment(clause,match)):continue
            if negated_here(clause,match):claims.append(relation(increase,compared_subject(clause,match,carried),True))
            elif not NEGATED.search(fragment(clause,match)):claims.append(relation(increase,compared_subject(clause,match,carried),False))
    for pattern,increase in ((EDGES_ABOVE,True),(EDGES_BELOW,False)):
        for match in pattern.finditer(clause):
            if spoken_number(match[1])==prior_edges and not not_stated(clause,match):claims.append(relation(increase,'current',False))
    return claims

def figure_matches(said,unit,record):
    """Whether a figure said of one session is that session's own. A bare number can be either of its figures."""
    edges,seconds=record.get('edges'),record.get('seconds')
    near=lambda:seconds is not None and abs(said*60-seconds)<=45
    if not unit:return said==edges or near() or edges is None and seconds is None
    return (edges is None or said==edges) if unit.lower().startswith('edge') else (seconds is None or near())

def credited_to_wrong_session(clause,prior,current,figures):
    """A dealt figure placed right beside the session it is said of, checked against that session alone. A figure nobody dealt is refused elsewhere."""
    for pattern,figure,unit,before,now in ((FIGURE_THEN_SESSION,1,2,4,5),(SESSION_THEN_FIGURE,3,4,1,2)):
        for match in pattern.finditer(clause):
            # With words between, a bare number could be counting anything: "three chances last time".
            bare_with_words=pattern is FIGURE_THEN_SESSION and not match[2] and match[3].strip()
            said=spoken_number(match[figure])
            if bare_with_words or not_stated(clause,match) or not match[unit] and said<=1 or said not in figures:continue
            # "Ran five minutes longer" is a difference, which comparison_violations checks.
            if re.match(r'(?:\s+(?:edges?|minutes?|mins?|seconds?|secs?|hours?))?\s+(?:longer|shorter|more|fewer|less)\b',clause[match.end():],re.I):continue
            if not figure_matches(said,match[unit],prior if match[before] else current):return True
    return False

# A quantity said in words: "by a single edge", "that extra minute".
SPOKEN_DIFFERENCE=re.compile(r"\bby\s+(?:just\s+|only\s+|barely\s+)?(?:a\s+|one\s+)(?:mere\s+|single\s+|lone\s+|solitary\s+|whole\s+)?(edge|minute|second)\b|\b(?:that|this|an|one|the)\s+(?:[a-z]+\s+)?extra\s+(edge|minute|second)\b|\b(?:a|one)\s+(?:full\s+|whole\s+|single\s+)?(minute|second)\s+(?:longer|shorter)\b",re.I)

def comparison_violations(sentence,history):
    """Each claim is read clause by clause against figures worked out before the model ran."""
    comparison=history.get('comparison') or {};prior=history.get('prior') or {};current=history.get('current') or {}
    edges,seconds=comparison.get('edges'),comparison.get('seconds')
    codes=[]
    minutes={round(r[0]/60) for r in ((prior.get('seconds'),),(current.get('seconds'),),((seconds or {}).get('difference'),)) if r[0] is not None}
    figures={v for v in (prior.get('edges'),current.get('edges'),(edges or {}).get('difference')) if v is not None}|minutes
    # A later clause can continue an earlier one: "last time you ran longer, but had fewer edges".
    named_in_sentence=bool(COMPARED_WITH.search(sentence) or PRIOR_REFERENCE.search(sentence))
    carried=None
    for clause in CLAUSE_BREAK.split(sentence):
        own=session_named(clause,0,len(clause))
        # "Last time you ran longer, but you had fewer edges" could mean either session, so it isn't read as either.
        ambiguous=carried=='prior' and not own and bool(OWN_SUBJECT.match(clause))
        hint=carried if carried=='prior' and not own and not ambiguous else None
        if not ambiguous:
            self_named=COMPARED_WITH.search(clause) or PRIOR_REFERENCE.search(clause) or EDGES_ABOVE.search(clause) or EDGES_BELOW.search(clause) or re.search(r'\bthis time\b',clause,re.I)
            if edges and prior.get('edges') is not None and (self_named or named_in_sentence and STATES_RESULT.search(clause)):
                if any(contradicts(claim,edges['direction']) for claim in edge_claims(clause,prior['edges'],hint)):codes.append('wrong_comparison')
            if seconds:
                for claim in length_claims(clause,hint,named_in_sentence):
                    if claim=='brisk':
                        faster=bool(re.search(r'\b(?:pace|tempo|rate|speed|outpac\w*)\b',clause,re.I) and current.get('seconds') and prior.get('seconds') and current.get('edges') is not None and prior.get('edges') is not None and current['edges']/current['seconds']>prior['edges']/prior['seconds'])
                        if seconds['direction']!='decrease' and not faster:codes.append('wrong_comparison')
                    elif contradicts(claim,seconds['direction']):codes.append('wrong_comparison')
            for match in EDGE_DIFFERENCE.finditer(clause):
                said=spoken_number(match[1] or match[5]);word=match[2] or match[3] or match[4]
                claimed=relation(bool(INCREASE_WORD.fullmatch(word)),compared_subject(clause,match,hint),False)
                if not not_stated(clause,match) and (not edges or said!=edges['difference'] or claimed!=edges['direction']):codes.append('wrong_comparison')
        for match in TIME_DIFFERENCE.finditer(clause):
            value,tolerance=seconds_said(match[1])
            if session_figure(clause,match) and not not_stated(clause,match) and (not seconds or abs(value-seconds['difference'])>min(tolerance,45)):codes.append('wrong_comparison')
        if not OTHER_SUBJECT.search(clause) and not THAN_EXPECTED.search(clause):
            for match in SPOKEN_DIFFERENCE.finditer(clause):
                if not_stated(clause,match) or LOOKS_AHEAD.search(fragment(clause,match)):continue
                unit=match[match.lastindex].lower()
                if unit=='edge':wrong=not edges or edges['difference']!=1
                else:wrong=not seconds or abs(seconds['difference']-(60 if unit=='minute' else 1))>(45 if unit=='minute' else 5)
                if wrong:codes.append('wrong_comparison')
        if not OTHER_SUBJECT.search(clause) and credited_to_wrong_session(clause,prior,current,figures):codes.append('wrong_session_figure')
        same=SAME_AS_BEFORE.search(clause)
        # A length is only a session's when a session is named: "a rope of the same length" isn't.
        if same and not not_stated(clause,same) and (PRIOR_REFERENCE.search(clause) or not re.search(r'length|duration|running',same[0],re.I)):
            # Only its own part of the clause: "the same number of edges and 5 minutes shorter" says nothing of the same time.
            part=fragment(clause,same)
            about_edges=re.search(r'\b(?:edges?|count|tally|number|figures?)\b',part,re.I);about_time=re.search(r'\b(?:minutes?|time|length|duration)\b',re.sub(r'\b(?:last|this|that|previous)\s+time\b','',part,flags=re.I),re.I)
            # "Matching last time's intensity" is an opinion about something that was never measured.
            relevant=([edges] if about_edges else [])+([seconds] if about_time else [])
            if any(c and c['direction']!='unchanged' for c in relevant):codes.append('wrong_comparison')
        # A figure said of the earlier session has to be one of the figures dealt, whatever its noun.
        if prior and PRIOR_REFERENCE.search(clause) and not OTHER_SUBJECT.search(clause):
            for match in re.finditer(r'\b'+COUNT+r'\b(?!-)'+NOT_A_COUNT+r'(?![ -]*(?:more|fewer|less)\b)',clause,re.I):
                said=spoken_number(match[1])
                if said>1 and said not in figures and not not_stated(clause,match):codes.append('unsupported_history_figure')
        first=min((m for pattern in (LONGER,SHORTER,MORE_EDGES,FEWER_EDGES) for m in pattern.finditer(clause)),key=lambda m:m.start(),default=None)
        if first:carried=compared_subject(clause,first,hint)
        elif own:carried=own[0]
    return codes

def history_violations(text,summary):
    card=summary.get('deck_card') or {};history=card.get('history')
    if history is None:return []
    codes=[];status=history.get('status');found=status=='found'
    prior=history.get('prior') if found and (history.get('prior') or {}).get('comparable') else None
    current=history.get('current') or {};comparison=history.get('comparison') or {}
    edges=comparison.get('edges');seconds=comparison.get('seconds')
    allowed_edges={r['edges'] for r in (prior,current) if r and r.get('edges') is not None}|({edges['difference']} if edges else set())
    allowed_seconds={r['seconds'] for r in (prior,current) if r and r.get('seconds') is not None}|({seconds['difference']} if seconds else set())
    clean=text.replace('**','').replace('_','')
    for sentence in re.findall(r'[^.!?\n]+(?:\.\d+[^.!?\n]*)*[.!?\n]?',clean):
        negated=bool(NEGATED.search(sentence))
        # Only a negation of the claim itself excuses it, not one elsewhere in the sentence.
        # Inference from figures needs figures. A greeting with none keeps only the general session checks.
        if (prior or current) and not UNCERTAIN.search(sentence) and any(not NEAR_NEGATION.search(sentence[:m.start()]) for m in BODY_INFERENCE.finditer(sentence)):codes.append('body_inference')
        if any(not NEAR_NEGATION.search(sentence[:m.start()]) for m in OBJECTIVE_STANDARD.finditer(sentence)):codes.append('objective_standard')
        # Stricter than the session checks: no other figure in any clause, rhetorical questions included.
        for pattern in EDGE_COUNTS:
            if not anecdote(sentence) and any(spoken_number(m[1]) not in allowed_edges for m in pattern.finditer(sentence)):codes.append('unsupported_history_figure')
        for match in ANY_DURATION.finditer(sentence):
            # "A second round" and "give me a minute" state no duration.
            if re.fullmatch(r'an?[ -]+(?:second|sec|minute|min)',match[1],re.I):continue
            # "Four edges in two hours" and "four hours of teasing" say how long a session ran, whatever else that figure resembles.
            ran=bool(COUNT_IN_TIME.search(sentence[:match.start()]) or TIME_OF_PLAY.match(sentence[match.end():]))
            # "I spent two hours in the greenhouse" and "give me five minutes" are nobody's session.
            if not ran and not session_figure(sentence,match):continue
            value,tolerance=seconds_said(match[1])
            # The time since the last session, if that is what this figure is. Anything else stays a claim about a session.
            gap=history.get('since_seconds')
            if not ran and gap is not None and value>=1800 and abs(value-gap)<=max(3600,.2*gap):continue
            # Rounding to the nearest minute is fine; 13 minutes for a 12-minute session isn't.
            close=lambda known:abs(value-known)<=(min(tolerance,45) if tolerance==90 else tolerance)
            if not any(close(known) for known in allowed_seconds):codes.append('unsupported_history_figure')
            # The difference between the sessions, offered as how long one of them ran.
            elif not any(close(r['seconds']) for r in (prior,current) if r and r.get('seconds') is not None) and (AS_RUNNING_TIME.match(sentence[match.end():]) or RAN_FOR.search(sentence[:match.start()]) and not re.match(r'\s+(?:longer|shorter|more|less)\b',sentence[match.end():],re.I)):codes.append('unsupported_history_figure')
        totals={r['edges'] for r in (prior,current) if r and r.get('edges') is not None}
        if not anecdote(sentence) and any(spoken_ordinal(m[1])>max(max(totals,default=0),1) for m in EDGE_ORDINAL.finditer(sentence)):codes.append('unsupported_history_figure')
        if (current or prior or {}).get('outcome')!='user_reported' and any(not NEAR_NEGATION.search(sentence[:m.start()]) and not re.search(r'\b(?:before|without|instead\s+of|rather\s+than)\s+$',sentence[:m.start()],re.I) for m in UNSUPPORTED_FINISH.finditer(sentence)):codes.append('unsupported_completion')
        # Which edge it stopped on is a count like any other.
        if FINAL_EDGE.search(sentence):
            for match in EDGE_ORDINAL.finditer(sentence):
                finals={r.get('edges') for r in ((prior,current) if PRIOR_REFERENCE.search(sentence) else (current or prior,)) if r}-{None}
                if finals and spoken_ordinal(match[1]) not in finals:codes.append('wrong_final_edge')
        # How long ago stays checked in a rhetorical question: "Five days and only one edge?" still says five days.
        since=history.get('since_seconds')
        for pattern in TIME_SINCE:
            for match in pattern.finditer(sentence):
                size={'hour':3600,'day':86400,'week':604800,'month':2592000,'year':31536000}[match[2].lower().rstrip('s')]
                said=match[1].lower()
                low,high=(2*size,9*size) if said in {'a few','several'} else (2*size,3*size) if said in {'a couple of','couple of'} else (spoken_number(said)*size,spoken_number(said)*size)
                if since is None or not low-size<=since<=high+size:codes.append('wrong_time_since')
        if sentence.rstrip().endswith('?'):continue
        if status!='none' and FIRST_SESSION.search(sentence):codes.append('first_session_claim')
        # "I haven't seen a new face in a long time" is the speaker's own story, not a past with the person addressed.
        if not found and any(not anecdote(clause_at(sentence,m.start())) for m in SHARED_PAST.finditer(sentence)):codes.append('invented_history')
        for match in NAMED_PRIOR.finditer(sentence):
            said=spoken_number(match[1])
            if OTHER_SUBJECT.search(sentence):continue
            if not prior or not (said==prior.get('edges') or prior.get('seconds') is not None and abs(said*60-prior['seconds'])<=45 and not re.search(r'\bedges?\b',sentence,re.I)):codes.append('unsupported_history_figure')
        if prior is None and not negated and not re.search(r"\b(?:I['’]d|I would|you['’]d|would|could|should)\s+have\b",sentence,re.I) and (PAST_MARKER.search(sentence) or re.search(r'\b(?:than|compared|against|last|previous)\b',sentence,re.I)) and (MORE_EDGES.search(sentence) or FEWER_EDGES.search(sentence) or LONGER.search(sentence) or SHORTER.search(sentence)):codes.append('invented_history')
        if prior is not None:codes+=comparison_violations(sentence,history)
        for match in NAMED_TIME_PATTERN.finditer(sentence):
            if not (ADDRESSEE.search(sentence) or SESSION_NAMED.search(sentence) or re.match(r"['’]s\s+(?:session|run|round|outing)\b",sentence[match.end():],re.I)):continue
            low,high=NAMED_TIME[match[0].lower()]
            if since is None or not low*3600<=since<=high*3600:codes.append('wrong_time_since')
    return list(dict.fromkeys(codes))

def corrected_closing(drafts,summary,check):
    """A Closing whose retry is spent. What is wrong goes, and a plain statement of the record stands in for it, so
    a mandatory card neither says something false nor disappears. Returns None if nothing can be said that passes."""
    history=(summary.get('deck_card') or {}).get('history') or {}
    plain=plain_record(history)
    if not plain or check(plain):return None
    best=[]
    for draft in drafts:
        sentences=[s.strip() for s in re.findall(r"[^.!?\n]+[.!?]*[\"'”’]?",re.sub(r"\[silence\]",' ',draft,flags=re.I)) if s.strip()]
        kept=[s if not check(s) else None for s in sentences]
        if sum(s is not None for s in kept)>sum(s is not None for s in best):best=kept
    if not best:return plain
    first=best.index(None) if None in best else len(best)
    text=' '.join(s for s in best[:first]+[plain]+best[first:] if s)
    return plain if check(text) else text

def addresses_by_own_name(text,speaker):
    """Calling the person by the companion's own name. Saying that name any other way stays allowed."""
    if not speaker:return False
    name=re.escape(speaker)
    return bool(re.search(r",\s*"+name+r"\s*(?:[.?!,;:]|$)|(?:^|[.!?]\s+)\W*"+name+r",\s",text,re.I))

COUNT_IN_TIME=re.compile(r"\bedges?\s+in\s+(?:\w+\s+){0,2}$",re.I)
TIME_OF_PLAY=re.compile(r"\s+of\s+(?:\w+\W+){0,2}(?:teas\w*|edging)\b",re.I)
UNSUPPORTED_FINISH=re.compile(r"\b(?:you\s+(?:\w+\s+)?(?:claimed|reported|declared)|claiming|reporting|declaring)\s+(?:a|your|the|that)\s+(?:\w+\s+)?finish\b",re.I)
# Dialogue has no authority over the device, so it can't have chosen a setting either.
SELECTED_SETTING=re.compile(r"\b(?:mode|settings?|intensity|speed|stroke)\s+I\s+(?:\w+\s+)?(?:selected|chose|picked|set)\b|\bI\s+(?:\w+\s+)?(?:selected|chose|picked)\s+(?:\w+\s+){0,3}(?:mode|settings?|intensity|speed|stroke)\b",re.I)

def relationship_violations(text,card):
    relationship=card.get('relationship')
    if relationship not in {'returning','unknown'}:return []
    speaker=card.get('speaker')
    named=speaker and re.search(r"\b(?:I am|I['’]m|my name is|call me)\s+(?:dr\.?\s+|ambassador\s+)?(?:\w+\s+)?"+re.escape(speaker)+r"\b",text,re.I)
    return (['first_session_claim'] if FIRST_SESSION.search(text) else [])+(['reintroduction'] if named and relationship=='returning' else [])

def settings_claims_allowed(codes,summary):
    """AI Settings Control: a character that verifiably changed a setting itself may say so."""
    card=summary.get('deck_card') or {}
    if card.get('settings_change') or summary.get('ai_settings_recent'):
        return [code for code in codes if code!='read_only_control_claim']
    return codes

SETTINGS_TOPIC={'play_style':r'style|mode|rhythm|classic|finisher|milk|glans|shortener|head ?play|ultimate|bratty|ruin',
    'game':r'game|oracle|survival|edge training|training',
    'endgame':r'endgame|ending|denial|deny|denied|climax|soft landing|landing|finish|orgasm|timer',
    'orgasm':r'orgasm|finish|climax|cum|force|release',
    'intensity':r'intensity|%|percent|harder|stronger|gentler|softer|pressure|dial|crank|turn(?:ed)? (?:it|things) (?:up|down)|notch|power',
    'pause':r'pause|break|breath|rest|halt|still'}

def settings_card_off_topic(text,card):
    """A settings card must say what was changed; a generic line does not announce it."""
    change=card.get('settings_change') or {}
    pattern=SETTINGS_TOPIC.get(change.get('setting'))
    return bool(pattern) and not re.search(r'\b(?:'+pattern+r')',text,re.I)

def settings_reply_announced(text,user_text,setting):
    """A chat reply that should announce a verified change: does it, beyond echoing the user's own words?"""
    pattern=SETTINGS_TOPIC.get(setting)
    if not pattern:return True
    said=re.sub(r'\s+',' ',(text or '')).strip()
    asked=re.sub(r'[^a-z0-9 ]','',re.sub(r'\s+',' ',(user_text or '')).lower()).strip()
    words=said.split(' ')
    # Drop a leading echo of the user's message, word by word.
    i=0
    for word in asked.split(' '):
        if i<len(words) and re.sub(r'[^a-z0-9]','',words[i].lower())==word:i+=1
        else:break
    rest=' '.join(words[i:]) if i>=max(2,len(asked.split(' '))//2) else said
    return len(rest.split())>=4 and bool(re.search(r'\b(?:'+pattern+r')',rest,re.I))

def card_language_violations(text,summary):
    """Unsolicited card turns only: a person who asks about the session can still be answered plainly."""
    card=summary.get('deck_card')
    if not card:return []
    # A mission can't have a finalized result, which only the closing card receives.
    return (['test_language'] if CARD_TEST_LANGUAGE.search(text) else [])+(['premature_session_end'] if card.get('lane')=='mission' and premature_session_end(text) else [])+(['addressed_by_own_name'] if addresses_by_own_name(text,card.get('speaker')) else [])+(['read_only_control_claim'] if SELECTED_SETTING.search(text) else [])+(['settings_card_off_topic'] if settings_card_off_topic(text,card) else [])+relationship_violations(text,card)+history_violations(text,summary)

def violations(text,canonical,history=(),trigger=None,completed=(),journal=(),told=(),card=False):
    """`card` adds the Director's checks for turns it generated itself. A person's conversation, with
    the deck on or off, keeps exactly the checks it has always had: dialogue such as "we've been walking
    for two hours" isn't a claim about a counter just because it has a number in it."""
    if not canonical:return []
    facts=canonical['facts'];codes=timing_violations(text,canonical,completed);clean=text.replace('**','').replace('_','')
    allowed={f['value'] for f in facts.values() if f['known'] and f['current'] and f['unit']=='BPM'}
    if trigger and trigger.get('category')=='derived':
        try:
            from .event_intelligence import DerivedEvent
            observation=DerivedEvent.model_validate(trigger['observation'])
            if observation.category=='derived' and observation.session_id==canonical['session_id']:
                allowed.update(abs(value) for value in (observation.first_bpm,observation.last_bpm,observation.change_bpm,observation.reference_bpm) if value is not None)
        except (ValueError,KeyError):pass
    hr=facts['hr'];reading=hr['value'] if hr['known'] and hr['current'] else None
    if reading is not None:
        for name in ['resting_bpm','single_max_bpm','dual_max_bpm','effective_max','pullback']:
            f=facts[name]
            if f['known'] and f['current']:allowed.add(abs(reading-f['value']))
    mentions=explicit_bpm(clean)
    past_values={n for m in history for _,_,n in explicit_bpm(m.get('content',''))}
    live_mentions=[]
    for start,end,n in mentions:
        prefix=re.split(r'[.!?;\n]',clean[:start])[-1]
        historical=bool(re.search(r'\b(earlier|previous|previously|mentioned|said|was|were)\b',prefix,re.I)) and not re.search(r'\b(current|currently|now|still)\b',prefix,re.I)
        historical=historical or bool(re.search(r'\b(?:last session|historical|journal)\b',prefix,re.I)) and not re.search(r'\b(?:current|currently|now|still)\b',prefix,re.I)
        journal_values={h[k] for r in journal for h in r.get('heart_rate',{}).values() for k in ('minimum','maximum')}
        if historical and (n in past_values or n in journal_values):continue
        live_mentions.append((start,end,n))
    if any(n not in allowed for _,_,n in live_mentions):codes.append('unsupported_bpm')
    # Models sometimes omit the unit while guessing a missing pulse (for
    # example "probably a healthy 72"). Do not accept that as uncertainty.
    hr_context=bool(re.search(r'\b(bpm|heart rate|pulse)\b',clean,re.I)) or bool(history and re.search(r'\b(bpm|heart rate|pulse)\b',history[-1].get('content',''),re.I))
    if reading is None and hr_context:
        for match in re.finditer(r'\b(\d{2,3})\b',clean):
            n=int(match[1])
            if any(start<=match.start()<end for start,end,_ in mentions):continue
            if not 35<=n<=250 or n in allowed:continue
            start=max(clean.rfind(x,0,match.start()) for x in ['.','!','?',';','\n'])+1
            end_candidates=[i for x in ['.','!','?',';','\n'] if (i:=clean.find(x,match.end()))>=0]
            clause=clean[start:min(end_candidates) if end_candidates else len(clean)]
            prefix=clean[start:match.start()]
            if re.search(r'\b(percent|seconds?|minutes?|hours?|years?|age|setting|maximum|ceiling|threshold|counter|samples?|timestamp|intensity|price|dollars?|pounds?|turn|frame|snapshot|sequence|UTC)\b|%',clause,re.I):continue
            if re.search(r"\bI(?:'m| am)\s+"+str(n)+r'\b',clause,re.I):continue
            if re.search(r'\b(earlier|previous|previously|mentioned|said|was|were)\b',prefix,re.I) and n in past_values and not re.search(r'\b(current|currently|now|still)\b',prefix,re.I):continue
            codes.append('unsupported_unitless_bpm');break

    # F2.5 live event acceptance: presentation output is never evidence about a
    # person's posture, health or physical pulse. Simulation cannot establish it.
    # Scheduled prompts travel in the user role, but nobody said them.
    user_text=' '.join(m.get('content','') for m in history if m.get('role')=='user' and not (card and m.get('content','').startswith(SCHEDULED_PROMPTS)))
    if card:codes+=measurement_violations(clean,canonical,told,trigger,completed,user_text)
    simulated_source=card and bool(facts['hr_source']['current'] and facts['hr_source']['value']=='simulator')
    for sentence in re.findall(r'[^.!?\n]+[.!?\n]?',clean):
        historical=bool(re.search(r'\b(?:previous|last|historical)\b',sentence,re.I)) and not re.search(r'\b(?:current|currently|now|still)\b',sentence,re.I)
        physical_values={h[k] for r in journal for source,h in r.get('heart_rate',{}).items() if source=='BLE sensor' and not h.get('simulated',True) for k in ('minimum','maximum')}
        quoted_values=[n for _,_,n in explicit_bpm(sentence)]
        historical_physical=historical and bool(quoted_values) and all(n in physical_values for n in quoted_values)
        fictional=bool(re.search(r'\b(?:fictional|imagined|hypothetical|pretend|in the story)\b',sentence,re.I))
        attributed=bool(re.search(r'\b(?:you (?:said|say|reported|report|describe)|according to you)\b',sentence,re.I) and re.search(r'\b(?:pulse|heart rate|heart)\b',user_text,re.I))
        if simulated_source and not fictional and not attributed and not historical_physical:codes+=provenance_violations(sentence)
        uncertain=bool(re.search(r"\b(unknown|unavailable|cannot|can't|not known|not measured|not your|not a measurement|whether|if)\b",sentence,re.I))
        if not uncertain and not sentence.rstrip().endswith('?'):
            posture=re.search(r"\byou(?:(?:'re| are)\s+|\s+)(sitting|standing|lying|sit|stand|lie)\b"+(r"(?!\s+(?:as|by|for|to|about|firm|out|up|a\s+chance)\b)" if card else ''),sentence,re.I)
            if posture and not re.search(r'\b(sit|sitting|sat|stand|standing|stood|lie|lying|lay)\b',user_text,re.I):codes.append('unsupported_user_posture')
            if re.search(r"\byou(?:'re| are)\s+(?:completely |perfectly )?safe\b",sentence,re.I) and not re.search(r"\bI(?:'m| am) safe\b",user_text,re.I):codes.append('unsupported_user_safety')
            if not (facts['hr_source']['current'] and facts['hr_source']['value']=='BLE sensor' and hr['current']):
                bodily=re.search(r"\b(?:your|our|my)\s+(?:own\s+)?(?:current\s+)?(?:resting\s+)?(?:hearts?(?: rate)?|pulse)\b.{0,80}\b(?:\d{2,3}\s*bpm|racing|climbing|rising|falling|resting|quiet|steady)\b",sentence,re.I)
                labeled=re.search(r"\byour\s+(?:heart rate|pulse)\b.{0,20}\b(?:simulated|simulator|not physical)\b",sentence,re.I)
                if bodily and not labeled and not fictional and not attributed and not historical_physical:codes.append('unmeasured_physiology_from_simulation_or_unknown')

        if sentence.rstrip().endswith('?'):continue
        negated=bool(re.search(r"\b(?:cannot|can't|won't|will not|did not|didn't|haven't|have not|not able|unable|no evidence|does not|doesn't)\b",sentence,re.I))
        if not negated and not fictional:
            control=re.search(r"\bI(?:['’](?:ll|ve)| will| have| am going to)?\s+(?:just\s+)?(?:adjust(?:ed)?|chang(?:e|ed)|set|rais(?:e|ed)|lower(?:ed)?|activat(?:e|ed)|modif(?:y|ied)|bypass(?:ed)?|operat(?:e|ed)|start(?:ed)?|stop(?:ped)?)\b.{0,45}\b(?:stimulation|transport|stroke|stroker|speed|intensity|device|hardware|safety threshold|Handy)\b",sentence,re.I)
            if control:codes.append('read_only_control_claim')
            live=bool(hr['current'] and facts['hr_source']['current'] and facts['hr_source']['value']=='BLE sensor')
            sensor=re.search(r'\b(?:BLE|Polar(?: H10)?|sensor|monitor)\b.{0,55}\b(?:working (?:normally|properly|well)|functioning|recording|tracking|measuring|reports|recorded|confirms|shows)\b',sentence,re.I)
            if sensor and not live and not (historical_physical and re.search(r'\brecorded\b',sentence,re.I)):codes.append('unsupported_live_sensor')
            trend=re.search(r"\b(?:your (?:heart rate|pulse)|heart rate|BPM)\b.{0,40}\b(?:rising|increasing|climbing|falling|dropping|decreasing)\b",sentence,re.I)
            if trend and not attributed and not re.search(r'\b(?:simulated|simulator)\b',sentence,re.I):
                direction='rising' if re.search(r'\b(?:rising|increasing|climbing)\b',trend[0],re.I) else 'falling'
                if not live or not facts['trend']['current'] or facts['trend']['value']!=direction:codes.append('unsupported_trend')
            if re.search(r'\b(?:sensor|readings?|data|measurements?|BPM)\b.{0,45}\b(?:prove|proves|confirm|confirms|demonstrate|demonstrates)\b.{0,60}\b(?:arousal|excited|excitement|physiological|fertility|health|safe|relaxed)\b',sentence,re.I):codes.append('unsupported_physiological_interpretation')
        motion=re.search(r'\b(?:Handy|VacuGlide|stroker|stimulation device)\b.{0,20}\b(?:is|remains|keeps)\s+(?:currently\s+)?(?:not\s+)?(?:moving|running|stimulating|pumping)\b',sentence,re.I)
        disconnected_motion=re.search(r"\b(?:Handy|VacuGlide|stroker|stimulation device)\b.{0,85}\b(?:sitting (?:still|idle)|is(?:n['’]t| not) (?:physically )?moving|is physically (?:moving|active)|is (?:actually )?(?:moving|pumping|stimulating))\b",sentence,re.I)
        if disconnected_motion and not facts['physical_motion']['current'] and not uncertain and not fictional:codes.append('unverified_physical_motion')
        if motion and not facts['physical_motion']['current'] and not fictional and not re.search(r"\b(cannot|can't|unknown|unavailable|whether|if|unable)\b",sentence,re.I):codes.append('unverified_physical_motion')
        generic_motion=re.search(r'\b(?:the|your|our)\s+(?:machine|hardware|equipment|device)\b.{0,15}\b(?:is|keeps)\s+(?:currently\s+)?(?:humming|moving|running|pumping|stimulating)\b',sentence,re.I)
        if generic_motion and not facts['physical_motion']['current'] and not uncertain and not re.search(r'\b(fictional|imagined|hypothetical|pretend)\b',sentence,re.I):codes.append('unverified_physical_motion')
        for name,label in [('handy','Handy'),('ble','BLE'),('intiface','Intiface'),('tcode','TCode'),('vacuglide','VacuGlide')]:
            claim=re.search(r'\b'+label+r"(?:'s|\s)[^.!?]{0,65}?\b(disconnected|connected)\b",sentence,re.I)
            if not claim:continue
            part=claim[0]
            uncertain=re.search(r"\b(unknown|unavailable|cannot|can't|whether|if|when|unable)\b",sentence,re.I)
            historical=re.search(r'\b(old|earlier|previous|previously|historical|was|were)\b',sentence,re.I) and not re.search(r'\b(current|currently|now|still)\b',sentence,re.I)
            if uncertain or historical:continue
            negative=claim[1].lower()=='disconnected' or bool(re.search(r"\b(not|isn't|aren't)\b",part,re.I))
            f=facts[name]
            if not f['current'] or not f['known'] or bool(f['value'])==negative:codes.append('unsupported_'+name+'_connection')
        if not current_claim(sentence):continue
        if facts['hr_source']['current'] and facts['hr_source']['value']=='simulator' and re.search(r'\b(?:from|via|by|using)\s+(?:(?:your|the|a)\s+)?(?:BLE|live|physical|real)\s+sensor\b|\b(?:BLE|live|physical|real)\s+sensor\s+(?:reports|reads|shows|measures)\b',sentence,re.I):codes.append('wrong_hr_source')
        for field,label in [('edges','edge count(?:er)?'),('pauses','pause count(?:er)?'),('seconds','elapsed(?: time)?')]:
            # A value in minutes or hours isn't a count of seconds; the duration check covers it.
            value=re.search(r'\b'+label+r'\s*(?:is|at|shows|reads|:|=)\s*(\d+)\b'+(r'(?!\s*(?:minutes?|mins?|hours?|hrs?)\b)' if card else ''),sentence,re.I)
            fact=facts[field]
            if value and (not fact['known'] or not fact['current'] or int(value[1])!=fact['value']):codes.append('wrong_'+field)
        control=re.search(r"\bI(?:'ve| have)?\s+(?:just\s+)?(?:set|changed|raised|lowered|started|stopped|paused|resumed|reset|connected|disconnected)\s+(?:your\s+|the\s+|this\s+|our\s+)?(?:intensity|session|Handy|counter|sensor|device|mode)\b",sentence,re.I)
        if control:codes.append('read_only_control_claim')
        match=re.search(r'\b(?:current heart rate|your heart rate|your pulse|your heart|current bpm)\b[^\d]{0,65}(\d{1,3}(?:\.\d{1,2})?)\s*(?:bpm|beats per minute)',sentence,re.I)
        if match and (reading is None or int(match[1])!=reading) and not re.search(r'ceiling|threshold|maximum|setting',match[0],re.I):codes.append('wrong_current_bpm')
        if re.search(r'\b(?:heart rate|pulse|bpm)\b.{0,45}\b(?:has been|keeps|continues)\b.{0,20}\b(climbing|rising|increasing|falling|dropping)\b',sentence,re.I) and not facts['trend']['known'] and not attributed and not fictional:codes.append('unsupported_trend')
        match=re.search(r'\bsession(?: status)?\b.{0,25}\b(?:is|remains|currently|officially)\s+(?:(?:currently|officially)\s+)?(running|paused|idle|stopped)\b',sentence,re.I)
        if match:
            actual=facts['status']['value'] if facts['status']['current'] else None
            target={'running':{'RUNNING','RAMPDOWN'},'paused':{'PAUSED'},'idle':{'IDLE'},'stopped':{'IDLE'}}[match[1].lower()]
            if actual not in target:codes.append('unsupported_session_status')
    if 'wrong_hr_source' in codes and 'unsupported_live_sensor' in codes:codes.remove('unsupported_live_sensor')
    # The older, more specific codes already name these claims.
    if card and {'wrong_hr_source','unsupported_live_sensor','unmeasured_physiology_from_simulation_or_unknown'}&set(codes):codes=[c for c in codes if c!='simulated_reading_presented_as_physical']
    if card and 'wrong_seconds' in codes:codes=[c for c in codes if c!='wrong_running_counter']
    return list(dict.fromkeys(codes))[:6]


def event_violations(text,event):
    """Narrow disambiguation for a proven engine action, not emotion classification."""
    if event and event.get('category')=='derived':
        observation=event.get('observation',{})
        change=observation.get('change_bpm')
        if observation.get('simulated'):
            for sentence in re.findall(r'[^.!?]+',text):
                if re.search(r"\b(?:your|our|my)\s+(?:own\s+)?(?:actual\s+)?(?:heart(?: rate)?|pulse|body)\b",sentence,re.I) and not re.search(r"\b(?:not your|not our|not my|cannot|can't|unmeasured|not measured)\b",sentence,re.I):return ['simulator_is_not_user_physiology']
        for sentence in re.findall(r'[^.!?]+',text):
            if re.search(r'\b(?:heart|pulse|BPM|spike|rise|fall|drop|increase|decrease|numbers|readings?|elevation)\b',sentence,re.I) and re.search(r"\b(?:suggests?|suggesting|indicates?|indicating|tells me|means?|proves?|proof|because)\b.{0,140}\b(?:you|your|yourself)\b",sentence,re.I):return ['unsupported_physiological_interpretation']
        for sentence in re.findall(r'[^.!?]+',text):
            measurement=re.search(r'\b(?:simulator|simulated|BPM|pulse|heart|elevation|rise|fall|drop|readings|numbers)\b',sentence,re.I)
            emotion=re.search(r"\b(?:your (?:excitement|nerves|anxiety|arousal|distress)|sudden calm|settled (?:your )?nerves)\b",sentence,re.I)
            negative=re.search(r"\b(?:not|never|no evidence|cannot|can't|doesn't|does not)\b",sentence,re.I)
            if (measurement or re.search(r'\b(?:simulator|simulated|BPM|pulse|readings)\b',text,re.I)) and emotion and not negative:return ['unsupported_physiological_interpretation']
        if re.search(r'\b(?:frantic|calm|relaxed|aroused|distressed|excited|nervous)\s+\d{2,3}\b',text,re.I):return ['unsupported_physiological_interpretation']
        if change is not None:
            for match in re.finditer(r'\b(?:rose|increased|fell|decreased|changed|rise|fall|increase|decrease)\s+(?:by|of)\s+([+-]?\d+(?:\.\d+)?)\s*BPM',text,re.I):
                if abs(abs(float(match[1]))-abs(change))>.1:return ['incorrect_derived_change']
        if re.search(r'\b(?:BPM|heart.rate|pulse|rise|increase|decrease)\b.{0,50}\b(?:proves|means|because)\b.{0,45}\b(?:excited|aroused|relaxed|anxious|distressed|calm)\b',text,re.I):return ['unsupported_physiological_interpretation']
    if event and event.get('kind')=='came_early' and re.search(r"\b(?:show(?:ed|ing)? up early|arriv(?:e|ed|ing|al) early|early arrival)\b",text,re.I):
        return ['came_early_means_reported_premature_release_not_early_arrival']
    return []
