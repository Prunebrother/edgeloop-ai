# SPDX-License-Identifier: AGPL-3.0-only
"""Conservative checks for explicit session claims, not a prose/emotion classifier."""
import re

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

def violations(text,canonical,history=(),trigger=None,completed=(),journal=()):
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
    user_text=' '.join(m.get('content','') for m in history if m.get('role')=='user')
    for sentence in re.findall(r'[^.!?\n]+[.!?\n]?',clean):
        historical=bool(re.search(r'\b(?:previous|last|historical)\b',sentence,re.I)) and not re.search(r'\b(?:current|currently|now|still)\b',sentence,re.I)
        physical_values={h[k] for r in journal for source,h in r.get('heart_rate',{}).items() if source=='BLE sensor' and not h.get('simulated',True) for k in ('minimum','maximum')}
        quoted_values=[n for _,_,n in explicit_bpm(sentence)]
        historical_physical=historical and bool(quoted_values) and all(n in physical_values for n in quoted_values)
        fictional=bool(re.search(r'\b(?:fictional|imagined|hypothetical|pretend|in the story)\b',sentence,re.I))
        attributed=bool(re.search(r'\b(?:you (?:said|say|reported|report|describe)|according to you)\b',sentence,re.I) and re.search(r'\b(?:pulse|heart rate|heart)\b',user_text,re.I))
        uncertain=bool(re.search(r"\b(unknown|unavailable|cannot|can't|not known|not measured|not your|not a measurement|whether|if)\b",sentence,re.I))
        if not uncertain and not sentence.rstrip().endswith('?'):
            posture=re.search(r"\byou(?:(?:'re| are)\s+|\s+)(sitting|standing|lying|sit|stand|lie)\b",sentence,re.I)
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
            value=re.search(r'\b'+label+r'\s*(?:is|at|shows|reads|:|=)\s*(\d+)\b',sentence,re.I)
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
