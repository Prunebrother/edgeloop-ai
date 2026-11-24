# SPDX-License-Identifier: AGPL-3.0-only
"""Campaign-owned intensity requests: once per stage/try, through the existing gate."""
from types import SimpleNamespace
import pytest
from companion_ai.campaign import Stage
from companion_ai.conversation import ConversationService
from tests.ai.test_campaign_choice import CID, MODEL, definition, service
from tests.ai.test_campaign_chapter2 import tick, frames


def scripted(tmp_path):
    data=definition()
    for st in data['missions'][0]['objectives'][1]['stages']:st['set_to']=True
    svc=service(tmp_path,data);svc.start(CID,'intake')
    return svc


@pytest.mark.parametrize('values',[{'set_to':True},{'set_to':True,'intensity':90,'raise_to':100}])
def test_set_to_needs_a_fixed_intensity_or_a_floor(values):
    with pytest.raises(ValueError):Stage(id='one',label='One',seconds=10,**values)


def floors(tmp_path):
    data=definition()
    for st,floor in zip(data['missions'][0]['objectives'][1]['stages'],(70,90,110)):
        st.pop('intensity',None);st.update(set_to=True,raise_to=floor)
    svc=service(tmp_path,data);svc.start(CID,'intake')
    return svc


def test_a_scripted_floor_raises_once_only_when_below_and_never_lowers(tmp_path):
    """H3 (author 2026-11-20): the protocol raises to a floor at each stage start; the companion is never asked."""
    assert Stage(id='one',label='One',seconds=10,set_to=True,raise_to=90).raise_to==90
    svc=floors(tmp_path)
    svc.observe(tick('f',0,intensity=60),[],MODEL)
    [first]=svc.take_directives()
    assert first['scripted'] and first['fallback']=={'setting':'intensity','value':20,'reason':'Intake: Baseline stage, at least 70%.'}
    assert svc.directive_valid(first,tick('f',0,intensity=60)) and not svc.directive_valid(first,tick('f',0,intensity=80))
    # Time counts at any intensity, so the player lowering it costs nothing; no repeat inside the stage.
    for r in frames('f',1,30,intensity=50):svc.observe(r,[],MODEL)
    assert all(d['key']!='stages:baseline' for d in svc.take_directives())
    # Already above the next floor: nothing is sent.
    svc2=floors(tmp_path/'b')
    for r in frames('g',0,40,intensity=120):svc2.observe(r,[],MODEL)
    assert svc2.take_directives()==[]
    state=svc2.state(tick('g',40,intensity=120),MODEL)['attempt']['objectives'][1]['stages']
    assert not any(st['needs_manual'] for st in state)
    assert not svc.settings_directed() or svc._needs(tick('f',30,intensity=50)).get('intensity') is None


def test_scripted_intensity_needs_no_settings_control_and_never_repeats_midstage(tmp_path):
    svc=scripted(tmp_path)
    svc.observe(tick('s',0,intensity=60),[],MODEL)
    [first]=svc.take_directives()
    assert first['scripted'] and first['fallback']=={'setting':'intensity','value':20,'reason':'Intake: Baseline stage, 70%.'}
    assert svc.directive_valid(first,tick('s',0,intensity=60)) and not svc.settings_directed()
    for r in [tick('s',1,intensity=70),tick('s',2,intensity=50),*frames('s',3,13,intensity=70)]:svc.observe(r,[],MODEL)
    [second]=svc.take_directives()
    assert second['key']=='stages:compliance' and second['fallback']['value']==40
    svc.observe(tick('s',14,intensity=50),[],MODEL);assert svc.take_directives()==[]
    assert not svc.directive_valid(first,tick('s',14,intensity=50))
    stage=svc.state(tick('s',14,intensity=50),MODEL)['attempt']['objectives'][1]['stages'][1]
    assert stage['needs_manual'] and stage['intensity']==90
    svc.observe(tick('s',15,status='IDLE'),[],MODEL)
    svc.observe(tick('new',0,intensity=50),[],MODEL)
    assert svc.take_directives()[0]['key']=='stages:baseline'


def speech_stub(svc,r):
    sent=[]
    state=SimpleNamespace(report=r,emergency=False,fresh=lambda:True)
    speech=SimpleNamespace(clock=lambda:1000.,scripted_stage_wait={},state=state,campaign_speaker=lambda:'nova',campaign_silenced=set(),campaign_directive_valid=svc.directive_valid,publish=sent.append)
    return speech,sent


@pytest.mark.parametrize('ai',[{'enabled':False},{'enabled':True,'revoked':True},{'enabled':True,'intensity_min':60,'intensity_max':80}])
def test_request_uses_mission_gate_trigger_without_model_even_when_gate_may_refuse(tmp_path,ai):
    svc=scripted(tmp_path);r=tick('s',0,intensity=60);r['details']['ai_settings']=ai
    svc.observe(r,[],MODEL);[step]=svc.take_directives()
    speech,sent=speech_stub(svc,r)
    ConversationService.campaign_directive(speech,step)
    assert len(sent)==1 and sent[0]['trigger']=='mission' and sent[0]['setting']=='intensity' and sent[0]['value']==20
    # There is no adapter on this object: sending this request cannot ask a model.
    svc.observe(tick('s',1,intensity=60),[],MODEL);assert svc.take_directives()==[]


def test_emergency_stop_silences_later_scripted_steps(tmp_path):
    svc=scripted(tmp_path);r=tick('s',0,intensity=60);svc.observe(r,[],MODEL);[step]=svc.take_directives()
    speech,sent=speech_stub(svc,r);speech.campaign_silenced.add('s')
    ConversationService.campaign_directive(speech,step);assert sent==[]
    speech.campaign_silenced.clear();speech.state.emergency=True
    ConversationService.campaign_directive(speech,step);assert sent==[]
