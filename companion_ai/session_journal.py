# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded, opt-in factual history. Consumes observer evidence; never controls EdgeLoop."""
from copy import deepcopy
from datetime import datetime, timezone
import re

MAX_RECORDS = 100
MAX_CHANGES = 32
SETTINGS = ('experience', 'goal', 'intensity')
DETAIL_SETTINGS = ('resting_bpm', 'single_max_bpm', 'dual_max_bpm')

def iso(stamp):
    return datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat() if stamp is not None else None

def model_name(scope):
    match=re.match(r'^[^:]+:(?:https?://(?:\[[^\]]+\]|[^:/]+)(?::\d+)?|local):(.*)$',scope or '')
    return match[1] if match else scope or ''

def companion(scope):
    model = model_name(scope)
    return model.split('-narrative')[0] or 'unknown'

class SessionJournal:
    def __init__(self, store):
        self.store = store
        self.active = None
        self.error = None
        try:
            self.data = store.read('session-journal.json', {'schema_version': 1, 'recording': False, 'ai_access': False, 'records': []})
            if not isinstance(self.data, dict) or self.data.get('schema_version') != 1 or not isinstance(self.data.get('records'), list):
                raise ValueError('Unsupported journal format')
            if not isinstance(self.data.get('recording'), bool) or not isinstance(self.data.get('ai_access'), bool):
                raise ValueError('Invalid privacy settings')
            self.data['records'] = self.data['records'][-MAX_RECORDS:]
        except (ValueError, OSError):
            self.data = {'schema_version': 1, 'recording': False, 'ai_access': False, 'records': []}
            self.error = 'Journal could not be read; recording and AI access are disabled. Existing file preserved.'

    def save(self, data):
        if self.error:
            raise ValueError(self.error)
        self.store.write('session-journal.json', data)
        self.data = data

    def command(self, action, **fields):
        data = deepcopy(self.data)
        if action == 'configure':
            for key in ('recording', 'ai_access'):
                if fields.get(key) is not None: data[key] = fields[key]
        elif action == 'delete':
            data['records'] = [r for r in data['records'] if r['session_id'] != fields['session_id']]
        elif action == 'clear':
            data['records'] = []
        elif action == 'report_completion':
            record = next((r for r in data['records'] if r['session_id'] == fields['session_id']), None)
            if record is None: raise ValueError('Session record was not found')
            if record['completion_status'] != 'accepted_application_event':
                record['completion_status'] = 'user_reported'
                record['completion_source'] = 'explicit journal user report; not sensor evidence'
        else: raise ValueError('Unknown journal action')
        self.save(data)
        if not data['recording']: self.active = None

    def snapshot(self, offset=0, sort='date', descending=True, session_id=None):
        keys={'date':'first_observed_at','duration':'active_running_seconds','edges':'edges','companion':'companion','completion':'completion_status','experience':'experience','goal':'goal','hr':'hr'}
        def value(r):
            if sort=='companion': return r['companions'][-1]['companion'] if r['companions'] else ''
            if sort=='hr': return min((h['minimum'] for h in r['heart_rate'].values()),default=-1)
            v=r.get(keys.get(sort,'first_observed_at'))
            return v if v is not None else -1 if sort in {'duration','edges'} else ''
        records=sorted(self.data['records'],key=value,reverse=descending)
        fields={'session_id','start_at','first_observed_at','active_running_seconds','edges','completion_status','heart_rate','experience','goal'}
        rows=[{k:deepcopy(v) for k,v in r.items() if k in fields}|{'companion':', '.join(dict.fromkeys(c['companion'] for c in r['companions']))} for r in records[offset:offset+10]]
        detail=next((deepcopy(r) for r in records if r['session_id']==session_id),None)
        return {'recording':self.data['recording'],'ai_access':self.data['ai_access'],'records':rows,'detail':detail,'total':len(records),'offset':offset,'error':self.error,'limit':MAX_RECORDS}

    def observe(self, observer, previous, summaries):
        """Called only after canonical observer acceptance. Storage failure never blocks stopping."""
        if not self.data['recording']: return
        r = observer.report
        sid = r['session_id']
        d = r.get('details') or {}
        scope = observer.model_scope
        if sid in self.data.get('closed_sessions',[]): return
        if self.active and self.active['session_id'] != sid: self.active = None
        if self.active is None and r['status'] != 'IDLE':
            known_start = bool(previous and previous['status'] == 'IDLE' and r['status'] == 'RUNNING' and r['seconds'] == 0)
            self.active = {'session_id': sid, 'start_at': iso(d.get('captured_at_ms')) if known_start else None,
                'first_observed_at': iso(d.get('captured_at_ms')), 'start_source': 'observed_engine_start' if known_start else 'start_unavailable',
                'companions': [], 'settings': {}, 'setting_changes': [], 'setting_changes_truncated': False,
                'heart_rate': {}, 'quality': {'incomplete_start': not known_start, 'telemetry_gap': False, 'sensor_unavailable': False},
                'completion_status': 'unknown', 'completion_source': None, 'events': [], '_last_sample': None}
        a = self.active
        if a is None: return
        identity = {'model_scope': scope, 'model': model_name(scope) or None, 'companion': companion(scope)}
        if not a['companions'] or a['companions'][-1] != identity:
            if len(a['companions']) < 16: a['companions'].append(identity)
            else:
                a['companions']=a['companions'][:15]+[identity]
                a['quality']['companion_changes_truncated'] = True
        stamp = d.get('captured_at_ms')
        if not observer.fresh():a['quality']['stale_observation']=True
        if stamp is None: a['quality']['missing_timestamp'] = True
        if previous:
            prior_stamp = (previous.get('details') or {}).get('captured_at_ms')
            if stamp is not None and prior_stamp is not None and stamp-prior_stamp > 5000: a['quality']['telemetry_gap'] = True
        settings = {k: r[k] for k in SETTINGS}
        settings.update({k: r['movement'][k] for k in ('stroke_min','stroke_max')})
        settings.update({k: d[k] for k in DETAIL_SETTINGS if d.get(k) is not None})
        # An IDLE reset must not replace the last settings with default values.
        if r['status'] != 'IDLE' or d.get('terminal_outcome'):
            for key, value in settings.items():
                if key in a['settings'] and a['settings'][key] != value:
                    if len(a['setting_changes']) < MAX_CHANGES:
                        a['setting_changes'].append({'setting': key, 'from': a['settings'][key], 'to': value, 'at': iso(stamp), 'source': 'observed selected engine setting; not hardware readback'})
                    else: a['setting_changes_truncated'] = True
            a['settings'] = settings
        if observer.hr_current() and (r['status'] != 'IDLE' or summaries):
            source = observer.hr_source()
            sample = d.get('hr_recorded_at_ms')
            # Even simulator values need a distinct source stamp to count as samples.
            if sample is not None and a['_last_sample'] != (source, sample):
                hr = a['heart_rate'].setdefault(source, {'minimum': r['hr'], 'maximum': r['hr'], 'samples': 0,
                    'simulated': source == 'simulator', 'quality': 'valid observer samples only; incomplete coverage possible'})
                hr['minimum'] = min(hr['minimum'], r['hr']); hr['maximum'] = max(hr['maximum'], r['hr']); hr['samples'] += 1
                a['_last_sample'] = (source, sample)
        elif r['status'] != 'IDLE': a['quality']['sensor_unavailable'] = True
        for e in observer.events:
            if e.get('session_id') == sid and e['event_id'] in observer.accepted_event_ids:
                if not any(v['event_id'] == e['event_id'] for v in a['events']):
                    a['events'] = (a['events'] + [{k: e.get(k) for k in ('event_id', 'kind', 'at_ms')}])[-32:]
                if e['kind'] == 'completion_accepted':
                    a['completion_status'] = 'accepted_application_event'; a['completion_source'] = 'validated original engine action; not physiological proof'
                elif e['kind'] == 'came_early' and a['completion_status'] == 'unknown':
                    a['completion_status'] = 'user_reported'; a['completion_source'] = 'validated user early-release action; not sensor evidence'
        if not summaries: return
        final = summaries[-1]
        if final['session_id'] != sid: return
        record = {k: deepcopy(v) for k, v in a.items() if not k.startswith('_')}
        record.update({k: deepcopy(final.get(k)) for k in ('active_running_seconds', 'last_verified_running_ticks', 'edges', 'experience', 'goal', 'termination', 'final_verified_at_ms', 'completeness', 'confidence', 'sensor_available', 'measurement_source')})
        record['historical'] = True
        record['stop_reason'] = 'safety' if final['protection_observed'] else 'completion' if final['termination'] == 'calibration_completed' else 'normal' if final['termination'] == 'manual_stop' else 'unknown'
        record['settings_authority'] = 'selected/applied engine configuration only; physical device actions unverified'
        record['experiment'] = {'character_proposed': None, 'user_approved': None, 'engine_settings': deepcopy(a['settings']), 'observations_source': 'read_only_browser_observer'}
        data = deepcopy(self.data)
        if not any(v['session_id'] == sid for v in data['records']):
            data['records'] = (data['records'] + [record])[-MAX_RECORDS:]
            data['closed_sessions'] = (data.get('closed_sessions',[]) + [sid])[-256:]
            try: self.save(data)
            except (ValueError, OSError):
                self.error = 'Journal persistence failed; existing history preserved. Recording stopped; check local storage.'
                self.data['recording'] = False
        self.active = None

    @staticmethod
    def relevant(prompt):
        return bool(re.search(r'\b(previous|last|historical|history|compare|compared)\b|\bdid we use\b',prompt,re.I) and re.search(r'\b(session|sessions|edges?|HR|heart|bpm|pulse|settings?|configuration|duration|long|experience|goal)\b',prompt,re.I))

    def retrieve(self, prompt, scope):
        if not self.data['ai_access'] or self.error: return []
        if not self.relevant(prompt): return []
        records = [r for r in self.data['records'] if any(c['model_scope'] == scope for c in r['companions'])]
        # Factual history belongs to the user; another character is shared only when explicitly named.
        named = re.findall(r'\b(Evelyn|Daisy|Celeste|Nova)\b', prompt, re.I)
        if named: records = [r for r in self.data['records'] if any(c['companion'].casefold() in {n.casefold() for n in named} for c in r['companions'])]
        selected = records[-(2 if re.search(r'compar', prompt, re.I) else 1):]
        fields = {'session_id', 'start_at', 'first_observed_at', 'companions', 'historical', 'completion_status', 'stop_reason', 'quality', 'active_running_seconds', 'edges', 'experience', 'goal', 'completeness'}
        if re.search(r'\b(HR|heart|bpm|pulse)\b', prompt, re.I): fields.add('heart_rate')
        if re.search(r'\b(settings?|configuration|compare|compared)\b', prompt, re.I): fields |= {'settings', 'setting_changes'}
        result=[]
        for r in selected:
            item={k: deepcopy(v[-6:] if k=='setting_changes' else v) for k,v in r.items() if k in fields}
            item['companions']=[{k:v for k,v in c.items() if k!='model_scope'} for c in r['companions'][-4:]]
            item['setting_changes_partial']=len(r['setting_changes'])>6 or r['setting_changes_truncated']
            result.append(item)
        return result
