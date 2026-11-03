"""Run in the EdgeLoop checkout after applying the experimental patch.

This tests only synthetic in-memory journal rows, never the user's .ai-data.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from companion_ai.nova_verified_bridge import summarize_existing_journal, requested_cross_companions
from companion_ai.session_journal import SessionJournal
from companion_ai.storage import SettingsStore

NOW=datetime(2026,10,30,18,0,tzinfo=timezone.utc)
NOVA='ollama:http://127.0.0.1:11435:nova-narrative-v1:latest'
EVELYN='ollama:http://127.0.0.1:11435:evelyn-narrative-v1:latest'


def row(ident, name, seconds=1200, edges=3, age=2, **extra):
    r={'session_id':ident,'first_observed_at':(NOW-timedelta(days=age)).isoformat(),
       'companions':[{'companion':name}], 'active_running_seconds':seconds,
       'edges':edges, 'heart_rate':{'SENSITIVE':'NEVER-LEAK'},
       'raw_transcript':'PRIVATE-TRANSCRIPT','settings':{'secret':'NO'},
       'completion_status':'user_reported'}
    r.update(extra)
    return r


def journal(tmp_path):
    return SessionJournal(SettingsStore(tmp_path))


def test_default_denied(tmp_path):
    j=journal(tmp_path)
    j.data['records'].append(row('r1','daisy'))
    assert summarize_existing_journal(j,frozenset({'daisy'}),now=NOW)['status']=='denied'


def test_private_records_never_reach_nova(tmp_path):
    j=journal(tmp_path)
    j.command('configure',recording=True,ai_access=True,nova_cross_companion=True)
    j.data['records']=[row('r1','daisy',1200,3),row('r2','evelyn',1800,5),row('r3','daisy',None,None),
                       row('shared','daisy',companions=[{'companion':'daisy'},{'companion':'evelyn'}])]
    result=summarize_existing_journal(j,frozenset({'daisy','evelyn'}),now=NOW)
    assert result['status']=='authorized_data'
    assert result['by_companion']['daisy']['session_count']==2
    assert result['by_companion']['daisy']['duration_known_sessions']==1
    assert result['by_companion']['evelyn']['engine_edge_count_total_known']==5
    assert result['excluded_multi_companion_records']==1
    text=json.dumps(result)
    for secret in ('PRIVATE-TRANSCRIPT','NEVER-LEAK','shared','r1','r2','r3','SENSITIVE'):
        assert secret not in text


def test_no_implicit_null_zero(tmp_path):
    j=journal(tmp_path)
    j.command('configure',recording=True,ai_access=True,nova_cross_companion=True)
    j.data['records']=[row('r1','daisy',None,None)]
    result=summarize_existing_journal(j,frozenset({'daisy'}),now=NOW)
    assert result['by_companion']['daisy']['duration_known_sessions']==0
    assert result['by_companion']['daisy']['engine_edge_count_total_known'] is None


def test_raw_nova_cross_history_denied_even_when_analytics_enabled(tmp_path):
    j=journal(tmp_path)
    j.command('configure',recording=True,ai_access=True,nova_cross_companion=True)
    j.data['records']=[row('r1','evelyn',1200,3)]
    assert j.retrieve('How long was my previous session with Evelyn?',NOVA)==[]
    assert requested_cross_companions('Compare my sessions with Evelyn and Daisy',NOVA)==frozenset({'evelyn','daisy'})
    assert requested_cross_companions('Compare sessions with Evelyn',EVELYN)==frozenset()
    assert requested_cross_companions('Tell me about gardening with Daisy',NOVA)==frozenset()


def test_no_evidence_in_ambiguous_or_shared(tmp_path):
    j=journal(tmp_path)
    j.command('configure',recording=True,ai_access=True,nova_cross_companion=True)
    j.data['records']=[row('r1','daisy',1200,3,companions=[{'companion':'daisy'},{'companion':'nova'}])]
    result=summarize_existing_journal(j,frozenset({'daisy'}),now=NOW)
    assert result['status']=='no_retained_records'
    assert not result['may_claim_journal_read']


def test_revocation_and_persistence(tmp_path):
    j=journal(tmp_path)
    j.command('configure',recording=True,ai_access=True,nova_cross_companion=True)
    j.data['records'].append(row('r1','daisy'))
    assert summarize_existing_journal(j,frozenset({'daisy'}),now=NOW)['status']=='authorized_data'
    j.command('configure',nova_cross_companion=False)
    assert summarize_existing_journal(j,frozenset({'daisy'}),now=NOW)['status']=='denied'
    assert journal(tmp_path).data['nova_cross_companion'] is False


def test_malformed_or_outside_window_not_counted(tmp_path):
    j=journal(tmp_path)
    j.command('configure',recording=True,ai_access=True,nova_cross_companion=True)
    j.data['records']=[row('old','daisy',age=40),row('bad','daisy',seconds=True),row('future','daisy',age=-1)]
    result=summarize_existing_journal(j,frozenset({'daisy'}),now=NOW)
    assert result['by_companion']['daisy']['duration_known_sessions']==0
    assert result['by_companion']['daisy']['edge_count_known_sessions']==1


def test_wrong_permission_type_fails_closed(tmp_path):
    j=journal(tmp_path)
    j.command('configure',recording=True,ai_access=True,nova_cross_companion=True)
    j.data['nova_cross_companion']='true'
    assert summarize_existing_journal(j,frozenset({'daisy'}),now=NOW)['status']=='denied'
