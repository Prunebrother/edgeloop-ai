# SPDX-License-Identifier: AGPL-3.0-only
from copy import deepcopy
from uuid import uuid4
import json
import pytest
from ai_observer.observation import BrowserObservation
from ai_observer.protocol import Observation,Messages
from companion_ai.session_journal import SessionJournal,MAX_RECORDS
from companion_ai.storage import SettingsStore
from companion_ai.context_compiler import ContextCompiler
from companion_ai.models import AIConfig
from companion_ai.fidelity import violations
from tests.ai.test_f251 import change
from tests.fork.grounding_cases import Clock,snapshot,frame

SCOPE='ollama:http://127.0.0.1:11435:evelyn-narrative-v1:latest'

def setup(tmp_path,record=True,access=True):
    j=SessionJournal(SettingsStore(tmp_path));j.command('configure',recording=record,ai_access=access)
    c=Clock();o=BrowserObservation(c.mono,c.wall,journal=j);o.model_scope=SCOPE
    s=snapshot(c);s.update(status='IDLE',seconds=0);s['details']['warmup_active']=False
    assert o.accept(Observation.model_validate(frame(s)))
    s['session_id']=str(uuid4());s,_=change(c,o,s,'session_started',status='RUNNING')
    return c,o,s,j

def stop(c,o,s,outcome='manual_stop',kind='stop'):
    s=deepcopy(s);s['details'].update(terminal_outcome=outcome,warmup_active=False)
    return change(c,o,s,kind,status='IDLE')[0]

def test_opt_in_and_independent_access(tmp_path):
    c,o,s,j=setup(tmp_path,False,False);stop(c,o,s);assert j.snapshot()['total']==0
    assert not SessionJournal(SettingsStore(tmp_path)).data['recording']

@pytest.mark.parametrize('pause', [True,False])
def test_duration_pause_reset_and_persistence(tmp_path,pause):
    c,o,s,j=setup(tmp_path)
    s,_=change(c,o,s,'edge',seconds=120,edges=3)
    if pause:
        s['details']['warmup_active']=False;s,_=change(c,o,s,'pause',status='PAUSED')
        c.tick(4);s,_=change(c,o,s,'session_resumed',status='RUNNING')
    s=stop(c,o,s);record=j.data['records'][0]
    assert record['start_at'].endswith('+00:00') and record['active_running_seconds']==120 and record['edges']==3
    s,_=change(c,o,s,'stop',seconds=0,edges=0);assert len(j.data['records'])==1
    restored=SessionJournal(SettingsStore(tmp_path));assert restored.data['records']==j.data['records']
    assert restored.retrieve('How long was the previous session?',SCOPE)[0]['active_running_seconds']==120
    restored.command('configure',ai_access=False);assert restored.retrieve('previous session',SCOPE)==[]
    assert restored.data['recording'] and len(restored.data['records'])==1

@pytest.mark.parametrize('outcome,kind,accepted', [('manual_stop','stop',False),('calibration_completed','completion_accepted',True),('other_stop','completion_accepted',False)])
def test_completion_classification(tmp_path,outcome,kind,accepted):
    c,o,s,j=setup(tmp_path);o.report['active_mode']=s['active_mode']='calibrate'
    stop(c,o,s,outcome,kind)
    assert (j.data['records'][0]['completion_status']=='accepted_application_event')==accepted
    assert j.data['records'][0]['stop_reason']==('completion' if accepted else 'normal' if outcome=='manual_stop' else 'unknown')

def test_physical_hr_ranges_disconnect_stale_and_simulation(tmp_path):
    c,o,s,j=setup(tmp_path)
    # first observed simulator sample remains in its own bucket
    s['devices'].update(simulated_hr=False,ble=True,hr_ready=True)
    for value in (81,105,92):
        c.tick(1);s['details']['hr_recorded_at_ms']=int(c.wall()*1000)
        s,_=change(c,o,s,'device_changed',hr=value)
    s['devices'].update(ble=False,hr_ready=False);s['safety']['signal']='stale'
    s,_=change(c,o,s,'signal_lost',hr=None)
    stop(c,o,s);r=j.data['records'][0]
    assert r['heart_rate']['BLE sensor']['minimum']==81 and r['heart_rate']['BLE sensor']['maximum']==105
    assert r['heart_rate']['BLE sensor']['samples']==3 and not r['heart_rate']['BLE sensor']['simulated']
    assert r['heart_rate']['simulator']['simulated'] and r['quality']['sensor_unavailable']
    assert r['sensor_available'] is False


def test_setting_changes_model_changes_and_model_isolation(tmp_path):
    c,o,s,j=setup(tmp_path);s,_=change(c,o,s,'intensity_changed',intensity=120)
    o.model_scope=SCOPE.replace('evelyn','daisy');s,_=change(c,o,s,'goal_changed',goal='oracle')
    stop(c,o,s);r=j.data['records'][0]
    assert len(r['companions'])==2 and r['settings']['intensity']==120 and r['settings']['goal']=='oracle'
    assert len(r['setting_changes'])==2 and r['experiment']['character_proposed'] is None
    assert j.retrieve('previous session',SCOPE) and j.retrieve('previous session',o.model_scope)
    assert not j.retrieve('previous session',SCOPE.replace('evelyn','celeste'))
    assert j.retrieve('Which settings did we use with Evelyn last time?',SCOPE.replace('evelyn','celeste'))
    assert not j.retrieve('Hello Evelyn',SCOPE)


def test_partial_final_unknown_and_safety(tmp_path):
    c,o,s,j=setup(tmp_path);s['safety'].update(watchdog_paused=True,fault='signal_lost');s['details']['warmup_active']=False
    s,_=change(c,o,s,'pause',status='PAUSED',seconds=20)
    c.tick(1);s['details']=None;s.update(status='IDLE',seconds=0)
    assert o.accept(Observation.model_validate(frame(s,o.sequence+1)))
    r=j.data['records'][0];assert r['active_running_seconds'] is None and r['stop_reason']=='safety'
    assert r['completeness']=='final_duration_unavailable'


def test_deletion_clear_user_report_and_replay(tmp_path):
    c,o,s,j=setup(tmp_path);s=stop(c,o,s);sid=s['session_id']
    j.command('report_completion',session_id=sid);assert j.data['records'][0]['completion_status']=='user_reported'
    j.command('delete',session_id=sid);assert j.retrieve('previous session',SCOPE)==[]
    s['details']['terminal_outcome']=None;s,_=change(c,o,s,'session_started',status='RUNNING');stop(c,o,s)
    assert not j.data['records'];j.command('clear');assert not SessionJournal(SettingsStore(tmp_path)).data['records']


def test_journal_context_budget_and_narrative_independence(tmp_path):
    c,o,s,j=setup(tmp_path);s,_=change(c,o,s,'edge',seconds=90,edges=2);stop(c,o,s)
    from companion_ai.narrative import NarrativeMemory
    n=NarrativeMemory();n.activate(SCOPE,'session');n.reset()
    query='How long was my previous session?';records=j.retrieve(query,SCOPE)
    messages,_,diag=ContextCompiler().compile(o.summary()|{'journal_context':records},query,[],AIConfig())
    text=json.dumps(messages);assert 'SESSION JOURNAL' in text and '90' in text and diag['journal_session_ids']==[s['session_id']]
    assert diag['estimated_prompt_tokens'] < AIConfig().context_length-AIConfig().max_tokens
    assert not violations('The previous session lasted 90 seconds.',o.canonical(),completed=records,journal=records)
    assert 'wrong_completed_duration' in violations('The previous session lasted 0 seconds.',o.canonical(),completed=records,journal=records)
    assert j.retrieve('Hello!',SCOPE)==[]


def test_storage_failure_does_not_block_stop(tmp_path,monkeypatch):
    c,o,s,j=setup(tmp_path)
    def fail(*a):raise OSError('synthetic disk failure')
    monkeypatch.setattr(j.store,'write',fail);stop(c,o,s)
    assert o.status=='IDLE' and j.error and not j.data['recording']

@pytest.mark.parametrize('action',['get','configure','delete','clear','report_completion'])
def test_authenticated_protocol_commands(action):
    fields={'session_id':str(uuid4())} if action in {'delete','report_completion'} else {}
    assert Messages.validate_python(dict(version=1,type='session_journal',action=action,**fields)).action==action


def test_bounded_retention_and_paging(tmp_path):
    c,o,s,j=setup(tmp_path)
    for i in range(MAX_RECORDS+2):
        stop(c,o,s);s['session_id']=str(uuid4());s['details']['terminal_outcome']=None
        s,_=change(c,o,s,'session_started',status='RUNNING',seconds=0)
    assert len(j.data['records'])==MAX_RECORDS
    assert len(j.snapshot()['records'])==10 and j.snapshot(offset=90)['total']==MAX_RECORDS
    assert len(json.dumps(j.snapshot()).encode())<65536


def test_authenticated_journal_workflow_and_no_inference(tmp_path):
    from fastapi.testclient import TestClient
    from ai_observer.server import create_app
    from tests.ai.test_character_menus import TOKEN,ORIGIN,auth,until
    from tests.ai.test_f25 import runtime
    wire=[];app=create_app(TOKEN,tmp_path,transport=runtime(wire))
    with TestClient(app) as client:
        with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
            auth(ws)
            def command(action,**fields):
                ws.send_json(dict(version=1,type='session_journal',action=action,**fields));return until(ws,'session_journal')
            assert not command('get')['journal']['recording']
            assert command('configure',recording=True)['journal']['recording']
            assert not command('configure',ai_access=False)['journal']['ai_access']
            assert command('clear')['journal']['total']==0
            assert not wire
    assert SessionJournal(SettingsStore(tmp_path)).data['recording']


def test_historical_hr_validation_does_not_authorize_current_measurement(tmp_path):
    c,o,s,j=setup(tmp_path);stop(c,o,s)
    records=j.retrieve('What was the HR last session?',SCOPE)
    value=records[0]['heart_rate']['simulator']['minimum']
    assert 'unsupported_bpm' not in violations(f'The previous session simulator minimum was {value} BPM.',o.canonical(),journal=records)
    assert 'unsupported_bpm' in violations('The previous session minimum was 249 BPM.',o.canonical(),journal=records)
    assert 'unsupported_live_sensor' in violations('The BLE sensor is working normally.',o.canonical(),journal=records)


def test_corrupt_store_is_preserved(tmp_path):
    path=tmp_path/'session-journal.json';path.write_text('{broken')
    j=SessionJournal(SettingsStore(tmp_path));assert j.error and not j.data['recording']
    with pytest.raises(ValueError):j.command('configure',recording=True)
    assert path.read_text()=='{broken'


@pytest.mark.parametrize('model',['evelyn','daisy','celeste'])
def test_privacy_compiler_does_not_leak_ephemeral_history_or_other_models(tmp_path,model):
    c,o,s,j=setup(tmp_path);stop(c,o,s)
    scope=SCOPE.replace('evelyn',model)
    if model!='evelyn':assert j.retrieve('previous session',scope)==[]
    query='How long was my previous session?'
    messages,_,_=ContextCompiler().compile(o.summary()|{'journal_access_denied':True},query,[{'role':'assistant','content':'The previous session lasted 42 seconds.'}],AIConfig())
    output=json.dumps(messages)
    assert 'Historical session access is disabled' in output
    assert 'COMPLETED SESSIONS' not in output and 'lasted 42 seconds' not in output
    assert not j.retrieve('What did the previous fictional page say?',scope)


def test_observer_restart_mid_session_marks_missing_start(tmp_path):
    c,o,s,j=setup(tmp_path);s,_=change(c,o,s,'edge',seconds=50,edges=3)
    restored=SessionJournal(SettingsStore(tmp_path));new=BrowserObservation(c.mono,c.wall,journal=restored);new.model_scope=SCOPE
    assert new.accept(Observation.model_validate(frame(s)))
    stop(c,new,s);r=restored.data['records'][0]
    assert r['start_at'] is None and r['quality']['incomplete_start']
    assert r['active_running_seconds']==50 and r['first_observed_at']


def test_stale_bpm_not_counted_and_comparison_retains_current_facts(tmp_path):
    c,o,s,j=setup(tmp_path)
    s['devices'].update(simulated_hr=False,ble=True,hr_ready=True)
    s['details']['hr_recorded_at_ms']-=10000
    s,_=change(c,o,s,'device_changed',hr=200)
    stop(c,o,s)
    assert 'BLE sensor' not in j.data['records'][0]['heart_rate']
    records=j.retrieve("How does today's session compare with the previous one?",SCOPE)
    _,_,diag=ContextCompiler().compile(o.summary()|{'journal_context':records},"How does today's session compare with the previous one?",[],AIConfig())
    assert {'seconds','experience','goal','edges'}<=set(diag['supporting_categories'])


def test_historical_retrieval_supports_future_untagged_models(tmp_path):
    from companion_ai.session_journal import model_name
    assert model_name('ollama:http://127.0.0.1:11435:future-character')=='future-character'
    assert model_name('ollama:http://[::1]:11435:future-character:v3')=='future-character:v3'


def test_missing_named_history_does_not_substitute_other_completed_session(tmp_path):
    c,o,s,j=setup(tmp_path);stop(c,o,s)
    query='Which settings did we use with Celeste last time?'
    assert j.retrieve(query,SCOPE)==[]
    messages,_,_=ContextCompiler().compile(o.summary()|{'journal_lookup':True,'journal_context':[]},query,[],AIConfig())
    output=json.dumps(messages)
    assert 'no matching historical record' in output and 'COMPLETED SESSIONS' not in output


def test_natural_historical_physical_hr_reference_is_not_a_live_claim(tmp_path):
    c,o,s,j=setup(tmp_path);stop(c,o,s)
    records=[{'heart_rate':{'BLE sensor':{'minimum':81,'maximum':105,'simulated':False,'samples':3}}}]
    assert 'unmeasured_physiology_from_simulation_or_unknown' not in violations('Your heart rate in the previous session was 81 BPM.',o.canonical(),journal=records)
    assert 'unsupported_live_sensor' not in violations('The previous session BLE sensor recorded a minimum of 81 BPM.',o.canonical(),journal=records)
    assert 'unsupported_live_sensor' in violations('The BLE sensor is working normally.',o.canonical(),journal=records)
    assert 'unsupported_bpm' in violations('Your heart rate in the previous session was 99 BPM.',o.canonical(),journal=records)
