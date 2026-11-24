# SPDX-License-Identifier: AGPL-3.0-only
"""Private authored directions for verified moments, with no browser or standing-prompt leaks."""
import json
import pytest
from companion_ai.campaign import Book, Campaign, Narrative, card_brief
from companion_ai.conversation import ConversationService
from tests.ai.test_campaign_choice import CID, MODEL, definition, service
from tests.ai.test_campaign_chapter2 import frames, tick
from tests.ai.test_campaign_scripted_intensity import speech_stub
from tests.ai.test_settings_control import outcome

PRIVATE='Private cue: notice the careful choice, without repeating this instruction.'


def narrative(directions=None,milestones=None):
    return Narrative.model_validate({'schema_version':1,'campaign':CID,'status':'approved','missions':{'intake':{
        'briefing':{'speaker':'nova','lines':['Fixture briefing']},'completion':{'speaker':'nova','lines':['Fixture completion']},
        'directions':directions if directions is not None else {'start':PRIVATE,'stages:compliance':PRIVATE,'cover:analyst':PRIVATE,'edges:done':PRIVATE},
        'milestones':milestones or {}}}})


def directed_service(tmp_path):
    data=definition();data['missions'][0]['objectives'].append({'id':'edges','type':'edge_count','count':1,'label':'Edge'})
    n=narrative();n.missions['intake'].check_directions(Campaign.model_validate(data).missions[0])
    return service(tmp_path,data,n)


@pytest.mark.parametrize('text',['',' '*2,'x'*201,'one\ntwo','one\rtwo','[[expression:neutral]]','one\u2028two'])
def test_direction_text_validation(text):
    with pytest.raises(ValueError):narrative({'start':text})


def test_same_moment_cannot_be_line_and_direction():
    with pytest.raises(ValueError,match='both'):narrative({'start':PRIVATE},{'start':{'speaker':'nova','lines':['Fixture']}})


@pytest.mark.parametrize('key',['missing:done','stages:baseline','stages:missing','cover:unknown','edges:2'])
def test_direction_keys_validated_when_book_loads(tmp_path,key):
    folder=tmp_path/CID;folder.mkdir();data=definition()
    (folder/'campaign.json').write_text(json.dumps(data));(folder/'narrative.json').write_text(narrative({key:PRIVATE}).model_dump_json())
    book=Book.load(tmp_path)
    assert not book.campaigns and 'cannot fire' in book.errors[0]['detail']


def test_stage_choice_goal_directions_once_and_never_sent_to_browser(tmp_path):
    svc=directed_service(tmp_path);svc.start(CID,'intake');out=[]
    for r in frames('s',0,10,intensity=70):out+=svc.observe(r,[],MODEL)
    cues=svc.take_cues();assert [c['key'] for c in cues]==['start','stages:compliance']
    assert all(c['kind']=='moment' and svc.cue_valid(c) for c in cues)
    out+=svc.answer('cover','analyst',r,MODEL)
    [choice]=svc.take_cues();assert choice['key']=='cover:analyst' and choice['chosen_label']=='I am an analyst'
    out+=svc.observe(tick('s',11,intensity=90,edges=1),[],MODEL)
    [goal]=svc.take_cues();assert goal['kind']=='moment' and goal['key']=='edges:done'
    out+=svc.observe(tick('s',12,intensity=90,edges=1),[],MODEL);assert svc.take_cues()==[]
    for browser_message in [*out,svc.state(r,MODEL),svc.progress_update(r,MODEL),svc.mission_text(CID,'intake')]:assert PRIVATE not in json.dumps(browser_message)
    assert PRIVATE not in svc.model_context(MODEL,r)['text']
    svc.observe(tick('s',13,status='IDLE'),[],MODEL);assert not svc.cue_valid(goal)


def test_scripted_goal_suppresses_plain_card_and_direction(tmp_path):
    data=definition();data['missions'][0]['objectives'].append({'id':'edges','type':'edge_count','count':1,'label':'Edge'})
    n=narrative({}, {'edges:done':{'speaker':'nova','lines':['Scripted goal']}})
    svc=service(tmp_path,data,n);svc.start(CID,'intake');svc.observe(tick('s',0,intensity=70),[],MODEL)
    out=svc.observe(tick('s',1,intensity=70,edges=1),[],MODEL)
    assert [m['key'] for m in out if m['type']=='mission_milestone']==['edges:done']
    assert not svc.take_cues()


def test_card_brief_has_direction_and_ends_with_current_session_state(tmp_path):
    svc=directed_service(tmp_path);svc.start(CID,'intake');svc.observe(tick('s',0,intensity=70),[],MODEL);[cue]=svc.take_cues()
    assert 'Direction: '+PRIVATE in card_brief(cue,'RUNNING')
    assert 'do not quote or mention the direction' in card_brief(cue,'RUNNING')
    assert card_brief(cue,'RUNNING').endswith('The session is still running and can carry on.')
    assert card_brief(cue,'IDLE').endswith('The session has ended.')
    svc.abandon();assert not svc.cue_valid(cue)


@pytest.mark.parametrize('status',['applied','rejected'])
def test_direction_waits_for_scripted_setting_outcome_and_confirming_report(tmp_path,status):
    data=definition();data['missions'][0]['objectives'][1]['stages'][0]['set_to']=True
    svc=service(tmp_path,data,narrative({'start':PRIVATE}));svc.start(CID,'intake')
    r=tick('s',0,intensity=60);svc.observe(r,[],MODEL);[directive]=svc.take_directives()
    speech,sent=speech_stub(svc,r)
    ConversationService.campaign_directive(speech,directive)
    assert ConversationService.scripted_stage_pending(speech,r)
    request=sent[0]
    ConversationService.settings_outcome(speech,outcome(id=request['id'],status=status,setting='intensity',to=20))
    if status=='applied':
        assert ConversationService.scripted_stage_pending(speech,r)
        r=tick('s',1,intensity=70)
    assert not ConversationService.scripted_stage_pending(speech,r)
    assert len(sent)==1


async def test_private_direction_reaches_only_its_card_brief_and_not_wire_messages():
    from tests.ai.test_event_deck_content import service as speech, prompt
    from tests.ai.test_campaign import cue_for
    r,s,wire,frames_=await speech(identity='evelyn',edges=0,seconds=200,reply='A clean, efficient effort; I expected nothing less from you.')
    s.deck()._start_done=True;s.campaign_speaker=lambda:'evelyn'
    cue=cue_for(s,kind='moment')|{'key':'cover:analyst','direction':PRIVATE,'chosen_label':'I am an analyst'}
    s.campaign_cue(cue);s.pump();await s.task
    assert PRIVATE in prompt(wire) and 'I am an analyst' not in prompt(wire)
    assert PRIVATE not in json.dumps(frames_)
    assert s.request('How are things?',user=True)['accepted'];await s.task
    assert PRIVATE not in prompt(wire), 'direction persisted into a later ordinary turn'


def test_scripted_stage_releases_reaction_on_verified_level_even_before_ack(tmp_path):
    data=definition();data['missions'][0]['objectives'][1]['stages'][0]['set_to']=True
    svc=service(tmp_path,data,narrative({'start':PRIVATE}));svc.start(CID,'intake')
    r=tick('s',0,intensity=60);svc.observe(r,[],MODEL);[d]=svc.take_directives()
    speech,sent=speech_stub(svc,r);ConversationService.campaign_directive(speech,d)
    assert not ConversationService.scripted_stage_pending(speech,tick('s',1,intensity=70))


def test_direction_for_a_counted_threshold_is_valid(tmp_path):
    data=definition();data['missions'][0]['objectives'].append({'id':'edges','type':'edge_count','count':3,'milestones':[1],'label':'Edges'})
    n=narrative({'edges:1':PRIVATE});n.missions['intake'].check_directions(Campaign.model_validate(data).missions[0])
    svc=service(tmp_path,data,n);svc.start(CID,'intake');svc.observe(tick('s',0,intensity=70),[],MODEL)
    svc.observe(tick('s',1,intensity=70,edges=1),[],MODEL);[cue]=svc.take_cues()
    assert cue['key']=='edges:1' and cue['direction']==PRIVATE


def test_player_lowering_after_applied_stage_does_not_hold_the_direction(tmp_path):
    data=definition();data['missions'][0]['objectives'][1]['stages'][0]['set_to']=True
    svc=service(tmp_path,data,narrative({'start':PRIVATE}));svc.start(CID,'intake')
    r=tick('s',0,intensity=60);svc.observe(r,[],MODEL);[d]=svc.take_directives()
    speech,sent=speech_stub(svc,r);ConversationService.campaign_directive(speech,d)
    r=tick('s',1,intensity=50);r['details']['ai_settings']={'last_id':sent[0]['id']}
    assert not ConversationService.scripted_stage_pending(speech,r)
    svc.observe(r,[],MODEL);assert not svc.take_directives()


async def test_stage_request_precedes_reaction_and_reaction_reads_new_intensity(tmp_path):
    from tests.ai.test_event_deck_content import service as speech, prompt
    r,s,wire,frames_=await speech(identity='nova',seconds=200,reply='A clean, efficient effort; I expected nothing less from you.')
    s.deck()._start_done=True;s.campaign_speaker=lambda:'nova'
    data=definition();data['missions'][0]['objectives'][1]['stages'][0]['set_to']=True
    svc=service(tmp_path,data,narrative({'start':PRIVATE}));svc.start(CID,'intake')
    sid=s.state.session_id;svc.observe(tick(sid,200,intensity=100),[],MODEL)
    s.campaign_cue_valid=svc.cue_valid;s.campaign_directive_valid=svc.directive_valid
    for d in svc.take_directives():s.campaign_directive(d)
    for cue in svc.take_cues():s.campaign_cue(cue)
    assert frames_[-1]['type']=='settings_request' and not wire
    assert not s.pump_campaign_card(s.clock())
    r.state['intensity']=70;r.step(seconds=0)
    assert s.pump_campaign_card(s.clock());await s.task
    assert PRIVATE in prompt(wire) and s.state.report['intensity']==70
    assert len([f for f in frames_ if f['type']=='settings_request'])==1
