# SPDX-License-Identifier: AGPL-3.0-only
"""Code puzzle secrets, normalisation, rate limits, and current-try progressive clues."""
import json
import pytest
from ai_observer.protocol import CampaignCommand, Messages
from companion_ai.campaign import Book, Campaign, Puzzle, moment_keys, normalize_code
from tests.ai.test_campaign_choice import CID, MODEL, definition as choice_definition, service
from tests.ai.test_campaign_chapter2 import frames, tick

SECRET='Helix 7'


def definition():
    data=choice_definition()
    data['missions'][0]['objectives'] += [
        {'id':'edges','type':'edge_count','label':'Edges','count':2,'milestones':[1]},
        {'id':'vault','type':'puzzle_solved','label':'Puzzle: vault','puzzle':{
            'kind':'code','title':'Vault','question':'Enter the code.','answer_code':SECRET,'max_length':12,'hint':'Read the clues again.',
            'clues':['Visible clue.',{'text':'Start clue','reveal_at':'start'},
                {'text':'Compliance clue','reveal_at':'stages:compliance'},
                {'text':'Threshold clue','reveal_at':'edges:1'},
                {'text':'Choice clue','reveal_at':'cover:analyst'},
                {'text':'Goal clue','reveal_at':'stages:done'},
                {'text':'Choice done clue','reveal_at':'cover:done'},{'text':'Always object clue'}]}}]
    return data


def puzzle(data):return data['missions'][0]['objectives'][-1]['puzzle']
def state(svc,r=None):return next(o['puzzle'] for o in svc.state(r,MODEL)['attempt']['objectives'] if o['id']=='vault')
def running(tmp_path,data=None):
    svc=service(tmp_path,data or definition());svc.start(CID,'intake')
    r=tick('s',0,intensity=70);svc.observe(r,[],MODEL)
    return svc,r


@pytest.mark.parametrize('change',[
    {'answer_code':None},{'answer_code':''},{'answer_code':'x'*41},{'max_length':0},{'max_length':41},
    {'options':[{'id':'a','label':'A'},{'id':'b','label':'B'}]}, {'answer':'a'},{'answer':None},{'options':None},
    {'kind':'unknown'},{'answer_code':'  '},{'answer_code':'code\n'},
    {'answer_code':'ßß','max_length':3},
])
def test_code_model_rejects_malformed_or_mixed_data(change):
    value=puzzle(definition())|change
    with pytest.raises(ValueError):Puzzle.model_validate(value)


@pytest.mark.parametrize('change',[
    {'options':None},{'answer':None},{'answer':'missing'},{'answer_code':'private'},{'answer_code':None},{'max_length':12},{'max_length':40}
])
def test_choice_puzzle_keeps_its_required_fields(change):
    value={'title':'Choice','clues':['Clue'],'question':'Which?','options':[{'id':'a','label':'A'},{'id':'b','label':'B'}],'answer':'a','hint':'Try again'}|change
    with pytest.raises(ValueError):Puzzle.model_validate(value)


def test_default_choice_kind_and_both_models_roundtrip():
    choice=Puzzle(title='Choice',clues=['Clue'],question='Which?',options=[{'id':'a','label':'A'},{'id':'b','label':'B'}],answer='a',hint='Try again')
    assert choice.kind=='choice' and Puzzle.model_validate(choice.model_dump())==choice
    code=Puzzle.model_validate(puzzle(definition()));assert Puzzle.model_validate(code.model_dump())==code
    raw=puzzle(definition());raw.pop('max_length');assert Puzzle.model_validate(raw).max_length==40


@pytest.mark.parametrize('value',['HELIX 7','helix 7','  ＨＥＬＩＸ　７  ','Helix     7','\u00a0helix 7\u00a0'])
def test_code_normalisation_accepts_case_width_and_spacing(tmp_path,value):
    svc,r=running(tmp_path);svc.answer('vault',value,r,MODEL)
    assert 'vault' in svc.attempt.solved


@pytest.mark.parametrize('secret,submission',[('Straße','STRASSE'),('0413','０４１３'),('K7','K7')])
def test_nfkc_casefold_and_leading_zeroes(tmp_path,secret,submission):
    data=definition();puzzle(data)['answer_code']=secret
    svc,r=running(tmp_path,data);svc.answer('vault',submission,r,MODEL)
    assert 'vault' in svc.attempt.solved
    assert normalize_code(submission)==normalize_code(secret)


@pytest.mark.parametrize('value',['x'*13,'a\nb','a\tb','a\rb','a\x00b','a\x85b','a\u200bb','   ',''])
def test_malformed_codes_are_refused_without_wrong_hint_or_rate_penalty(tmp_path,value):
    svc,r=running(tmp_path)
    with pytest.raises(ValueError,match='Malformed code'):svc.answer('vault',value,r,MODEL)
    assert 'wrong' not in state(svc,r) and svc.attempt.code_failures=={} and svc.attempt.code_revision=={}


@pytest.mark.parametrize('update,model',[({'status':'PAUSED'},MODEL),({'status':'IDLE'},MODEL),({},'other'),({'toy':False},MODEL),({'sim':True},MODEL),({'sid':'other'},MODEL)])
def test_code_answers_still_require_running_mission_companion_and_real_devices(tmp_path,update,model):
    svc,r=running(tmp_path)
    with pytest.raises(ValueError):svc.answer('vault',SECRET,tick(**({'sid':'s','seconds':0,'intensity':70}|update)),model)
    assert not svc.attempt.solved


def test_five_wrong_codes_lock_for_ten_seconds_then_reset_on_new_try(tmp_path):
    svc,r=running(tmp_path);clock=[1000.];svc.clock=lambda:clock[0]
    for n in range(5):
        [m]=svc.answer('vault','wrong',r,MODEL)
        assert state(svc,r)['wrong'] is True and state(svc,r)['answer_revision']==n+1
    with pytest.raises(ValueError,match='Too many attempts. Wait a moment.'):svc.answer('vault',SECRET,r,MODEL)
    clock[0]+=9.99
    with pytest.raises(ValueError,match='Too many attempts'):svc.answer('vault',SECRET,r,MODEL)
    clock[0]+=.01;svc.answer('vault',SECRET,r,MODEL);assert 'vault' in svc.attempt.solved
    # A separate unfinished try can be ended while rate-limited, then answered immediately in the next session.
    other,r=running(tmp_path/'reset');other.clock=lambda:1000.
    for _ in range(5):other.answer('vault','wrong',r,MODEL)
    other.observe(tick('s',1,status='IDLE'),[],MODEL)
    r=tick('new',0,intensity=70);other.observe(r,[],MODEL);other.answer('vault',SECRET,r,MODEL)
    assert 'vault' in other.attempt.solved


def test_all_progressive_moments_work_without_narrative_lines_and_reset_hides_clues(tmp_path):
    svc=service(tmp_path,definition());svc.start(CID,'intake')
    assert state(svc)['clues']==['Visible clue.','Always object clue']
    r=tick('s',0,intensity=70);svc.observe(r,[],MODEL)
    assert state(svc,r)['clues']==['Visible clue.','Start clue','Always object clue']
    assert state(svc,r)['new_clues']==[1]
    svc.answer('vault','wrong',r,MODEL);assert 'new_clues' not in state(svc,r)
    for r in frames('s',5,10,intensity=70):svc.observe(r,[],MODEL)
    assert 'Compliance clue' in state(svc,r)['clues']
    svc.answer('cover','analyst',r,MODEL)
    assert {'Choice clue','Choice done clue'}<=set(state(svc,r)['clues'])
    r=tick('s',11,intensity=90,edges=1);svc.observe(r,[],MODEL)
    assert 'Threshold clue' in state(svc,r)['clues']
    for r in frames('s',16,21,intensity=90,edges=1):svc.observe(r,[],MODEL)
    assert 'Goal clue' in state(svc,r)['clues'] and svc.attempt.marked==set()
    assert {'start','stages:compliance','cover:analyst','cover:done','edges:1','stages:done'}<=svc.attempt.fired
    svc.observe(tick('s',22,status='IDLE'),[],MODEL)
    assert state(svc)['clues']==['Visible clue.','Always object clue']
    assert not svc.attempt.fired


@pytest.mark.parametrize('key',['stages:baseline','stages:unknown','missing:done','cover:unknown','edges:9'])
def test_clue_reveal_key_is_checked_when_campaign_loads(tmp_path,key):
    data=definition();puzzle(data)['clues']=[{'text':'Hidden','reveal_at':key}]
    folder=tmp_path/CID;folder.mkdir();(folder/'campaign.json').write_text(json.dumps(data))
    book=Book.load(tmp_path);assert not book.campaigns and book.errors


def test_directions_and_clues_use_one_key_helper():
    c=Campaign.model_validate(definition());keys=moment_keys(c.missions[0])
    assert {'start','stages:compliance','edges:1','cover:analyst','cover:done','vault:done'}<=keys
    assert 'stages:baseline' not in keys


def test_secret_absent_from_all_emitted_messages_in_full_run_and_wrong_submissions(tmp_path):
    svc,r=running(tmp_path);messages=[svc.state(r,MODEL),svc.mission_text(CID,'intake')]
    # This wrong submission contains the entire secret: even it must never be echoed back.
    messages+=svc.answer('vault',SECRET+'?',r,MODEL)
    messages+=svc.take_cues();messages.append(svc.model_context(MODEL,r))
    for r in frames('s',5,10,intensity=70):messages+=svc.observe(r,[],MODEL)
    messages+=svc.answer('cover','analyst',r,MODEL)
    for r in frames('s',11,21,intensity=90,edges=2):messages+=svc.observe(r,[],MODEL)
    messages+=svc.take_cues();messages.append(svc.model_context(MODEL,r))
    messages+=svc.answer('vault',SECRET,r,MODEL)
    messages+=svc.take_cues();messages.append(svc.state(r,MODEL));messages.append(svc.model_context(MODEL,r))
    assert any(m and m.get('type')=='mission_result' for m in messages)
    assert SECRET not in json.dumps(messages) and 'answer_code' not in json.dumps(messages)
    with pytest.raises(ValueError) as error:svc.answer('vault',SECRET,r,MODEL)
    assert SECRET not in str(error.value)


def test_strict_answer_command_accepts_code_text_but_not_extra_fields():
    message={'version':1,'type':'campaign','action':'answer','objective_id':'vault','answer':' Ｈｅｌｉｘ  ７ '}
    assert Messages.validate_json(json.dumps(message)).answer==message['answer']
    for bad in [message|{'unexpected':True},message|{'objective_id':None},message|{'answer':None},message|{'action':'get'}]:
        with pytest.raises(ValueError):CampaignCommand.model_validate(bad)


def test_progressive_clues_work_for_existing_choice_puzzles_too(tmp_path):
    data=definition();value=puzzle(data);value.pop('answer_code');value.pop('max_length')
    value.update(kind='choice',options=[{'id':'a','label':'A'},{'id':'b','label':'B'}],answer='a')
    svc,r=running(tmp_path,data)
    assert 'options' in state(svc,r) and 'max_length' not in state(svc,r)
    r=tick('s',1,intensity=70,edges=1);svc.observe(r,[],MODEL)
    assert 'Threshold clue' in state(svc,r)['clues'] and state(svc,r)['new_clues']
    svc.answer('vault','b',r,MODEL)
    assert state(svc,r)['wrong']=='b' and 'new_clues' not in state(svc,r)
    svc.answer('vault','a',r,MODEL);assert 'vault' in svc.attempt.solved


def test_legacy_choice_option_ids_still_refuse_malformed_text_at_campaign_boundary(tmp_path):
    data=definition();value=puzzle(data);value.pop('answer_code');value.pop('max_length')
    value.update(kind='choice',options=[{'id':'a','label':'A'},{'id':'b','label':'B'}],answer='a')
    svc,r=running(tmp_path,data)
    with pytest.raises(ValueError,match='Malformed puzzle'):svc.answer('vault','x<script>',r,MODEL)
    assert 'wrong' not in state(svc,r)


def test_refused_rate_limited_answer_does_not_acknowledge_new_clues(tmp_path):
    svc,r=running(tmp_path);clock=[1000.];svc.clock=lambda:clock[0]
    for _ in range(5):svc.answer('vault','wrong',r,MODEL)
    r=tick('s',1,intensity=70,edges=1);svc.observe(r,[],MODEL)
    assert state(svc,r)['new_clues']
    with pytest.raises(ValueError,match='Too many attempts'):svc.answer('vault','wrong',r,MODEL)
    assert state(svc,r)['new_clues']
    clock[0]+=10;svc.answer('vault','wrong',r,MODEL);assert 'new_clues' not in state(svc,r)
