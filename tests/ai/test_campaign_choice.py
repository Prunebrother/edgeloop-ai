# SPDX-License-Identifier: AGPL-3.0-only
"""Choice definition, verified answer rules, and durable v4 state; no live models."""
import json
import pytest
from companion_ai.campaign import Book, Campaign, CampaignService, MissionNarrative, PROGRESS_FILE, migrate
from companion_ai.storage import SettingsStore
from tests.ai.test_campaign_chapter2 import tick, frames

CID='fixture_choice'
MODEL='fixture:latest'


def definition():
    return {'schema_version':1,'id':CID,'order':1,'title':'Intake protocol','description':'Fixture','starting_companions':['nova'],
        'missions':[{'id':'intake','order':1,'title':'Intake','summary':'Fixture','companion':'nova','flags':{'entry':'done'},
            'objectives':[{'id':'start','type':'session_started','label':'Start'},
                {'id':'stages','type':'stage_sequence','label':'Stages','stages':[
                    {'id':'baseline','label':'Baseline','seconds':10,'intensity':70},
                    {'id':'compliance','label':'Compliance','seconds':10,'intensity':90}]},
                {'id':'cover','type':'choice','label':'Answer question','after_stage':'stages:compliance',
                    'choice':{'prompt':'Which cover?','options':[
                        {'id':'analyst','label':'I am an analyst','sets':{'cover':'analyst'}},
                        {'id':'volunteer','label':'I volunteered','sets':{'cover':'volunteer'}}]}}]}]}


def service(tmp_path, data=None, narrative=None):
    c=Campaign.model_validate(data or definition())
    return CampaignService(SettingsStore(tmp_path),book=Book([c],{CID:narrative} if narrative else {}),identity=lambda m:'nova' if m==MODEL else 'other')


def running(svc):
    svc.start(CID,'intake')
    for r in frames('s',0,10,intensity=70):svc.observe(r,[],MODEL)
    return tick('s',10,intensity=70)


@pytest.mark.parametrize('change',[
    lambda o:o['choice'].update(options=o['choice']['options'][:1]),
    lambda o:o['choice'].update(options=o['choice']['options']*3),
    lambda o:o['choice']['options'][1].update(id='analyst'),
    lambda o:o['choice']['options'][0].update(id='not.snake'),
    lambda o:o['choice']['options'][0].update(label=' '*2),
    lambda o:o['choice']['options'][0].update(label='x'*121),
    lambda o:o['choice']['options'][0].update(sets={'other.inherited':'yes'}),
    lambda o:o.update(after_stage='stages:missing'),
    lambda o:o.update(after_stage='unknown:compliance'),
])
def test_choice_validation(change):
    data=definition();change(data['missions'][0]['objectives'][-1])
    with pytest.raises(ValueError):Campaign.model_validate(data)


def test_choice_flags_are_declared_and_options_not_model_context(tmp_path):
    svc=service(tmp_path);r=running(svc)
    assert svc.book.campaign(CID).own_flags()['cover']=={'analyst','volunteer'}
    before=svc.model_context(MODEL,r)
    assert 'I am an analyst' not in json.dumps(before) and 'I volunteered' not in json.dumps(before)
    assert 'Which cover?' not in json.dumps(svc.mission_text(CID,'intake'))
    svc.answer('cover','analyst',r,MODEL)
    # Changed after the 2026-11-20 live checks: models repeat an answer's words, so the brief only says it was answered.
    assert 'I am an analyst' not in svc.model_context(MODEL,r)['text'] and 'a question for the participant: answered' in svc.model_context(MODEL,r)['text']
    assert 'I volunteered' not in svc.model_context(MODEL,r)['text']


def test_choice_locked_until_stage_then_saved_before_session_reset(tmp_path):
    svc=service(tmp_path);svc.start(CID,'intake');r=tick('s',0,intensity=70);svc.observe(r,[],MODEL)
    choice=svc.state(r,MODEL)['attempt']['objectives'][-1]['choice']
    assert not choice['open'] and choice['locked_reason']=='Available during Compliance'
    with pytest.raises(ValueError,match='stage'):svc.answer('cover','analyst',r,MODEL)
    for r in frames('s',5,10,intensity=70):svc.observe(r,[],MODEL)
    svc.answer('cover','analyst',r,MODEL)
    saved=json.loads((tmp_path/PROGRESS_FILE).read_text())
    assert saved['schema_version']==4 and saved['campaigns'][CID]['choices']=={'intake':{'cover':'analyst'}}
    assert saved['campaigns'][CID]['flags']=={}
    svc.observe(tick('s',11,status='IDLE'),[],MODEL)
    again=service(tmp_path)
    assert again.attempt.choices=={'cover':'analyst'}
    assert again.state()['attempt']['objectives'][-1]['choice']['selected_label']=='I am an analyst'


@pytest.mark.parametrize('update,model', [({'status':'PAUSED'},MODEL),({'status':'IDLE'},MODEL),({'status':'RUNNING'},'other'),({'toy':False},MODEL),({'sim':True},MODEL),({'sid':'different'},MODEL)])
def test_choice_answer_needs_running_companion_real_devices(tmp_path,update,model):
    svc=service(tmp_path);running(svc)
    with pytest.raises(ValueError):svc.answer('cover','analyst',tick(**({'sid':'s','seconds':10,'intensity':70}|update)),model)
    assert not svc.attempt.choices


def test_choice_flags_first_completion_only_and_replay_retains_latest_answer(tmp_path):
    svc=service(tmp_path);r=running(svc);svc.answer('cover','analyst',r,MODEL)
    for r in frames('s',11,21,intensity=90):svc.observe(r,[],MODEL)
    assert svc.record(CID).flags=={'entry':'done','cover':'analyst'}
    svc.start(CID,'intake');assert svc.attempt.choices=={}
    for r in frames('replay',0,10,intensity=70):svc.observe(r,[],MODEL)
    svc.answer('cover','volunteer',r,MODEL)
    assert service(tmp_path).attempt.choices=={'cover':'volunteer'}
    for r in frames('replay',11,21,intensity=90):svc.observe(r,[],MODEL)
    assert svc.record(CID).choices=={'intake':{'cover':'volunteer'}}
    assert svc.record(CID).flags=={'entry':'done','cover':'analyst'}


@pytest.mark.parametrize('version',[1,2,3])
def test_old_save_migration_and_newer_guard(tmp_path,version):
    original={'schema_version':version,'campaigns':{CID:{'missions':{},'rewards':{},'records':{}}},'active':None}
    upgraded=migrate(original)
    assert upgraded['schema_version']==4 and upgraded['campaigns'][CID]['choices']==upgraded['campaigns'][CID]['routes']=={}
    assert original['schema_version']==version
    path=tmp_path/PROGRESS_FILE;path.write_text(json.dumps(original));assert not service(tmp_path).error
    path.write_text(json.dumps(original|{'schema_version':5}));before=path.read_bytes()
    assert service(tmp_path).error and path.read_bytes()==before


def test_invalid_option_and_failed_save_leave_choice_unchanged(tmp_path,monkeypatch):
    svc=service(tmp_path);r=running(svc)
    with pytest.raises(ValueError,match='option'):svc.answer('cover','missing',r,MODEL)
    monkeypatch.setattr(svc.store,'write',lambda *a:(_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):svc.answer('cover','analyst',r,MODEL)
    assert not svc.attempt.choices and not svc.record(CID).choices


def test_choice_moment_line_and_keyboard_shortcuts(tmp_path):
    import subprocess
    from pathlib import Path
    from companion_ai.campaign import Narrative
    n=Narrative.model_validate({'schema_version':1,'campaign':CID,'status':'approved','missions':{'intake':{
        'briefing':{'speaker':'nova','lines':['Fixture']},'completion':{'speaker':'nova','lines':['Fixture']},
        'milestones':{'cover:analyst':{'speaker':'nova','lines':['Chosen reaction']}}}}})
    svc=service(tmp_path,narrative=n);r=running(svc)
    root=Path(__file__).resolve().parents[2]
    for key in ['Enter','Space']:
        result=subprocess.run(['node',str(root/'tests/fork/campaign_ui_routing.mjs')],input=json.dumps({'repo':str(root),'messages':[svc.state(r,MODEL)],'key':key,'choice':True}),text=True,capture_output=True,check=True)
        assert json.loads(result.stdout)['engineActions']==[]
    updates=svc.answer('cover','analyst',r,MODEL)
    assert [m['key'] for m in updates if m['type']=='mission_milestone']==['cover:analyst']
