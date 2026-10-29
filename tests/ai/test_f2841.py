# SPDX-License-Identifier: AGPL-3.0-only
import asyncio,json
from copy import deepcopy
import pytest
from companion_ai.narrative import NarrativeMemory,NarrativeConfig
from companion_ai.narrative_facts import retrieve,recall_violations,MAX_FACTS
from companion_ai.memory_curator import MemoryCurator,CuratorConfig
from companion_ai.context_compiler import ContextCompiler
from companion_ai.models import AIConfig
from companion_ai.storage import SettingsStore
from tests.fork.context_retention_fixture import fixture


def memory(model='evelyn',store=None):
    n=NarrativeMemory(NarrativeConfig(persist_between_sessions=store is not None),store);n.activate(model,'synthetic')
    n.accepted('Imagine a laboratory mystery. The blue laboratory door is marked ORCHID-17.','I enjoy tending an overgrown succulent.',True)
    return n

@pytest.mark.parametrize('model',['evelyn','daisy','celeste'])
def test_identifier_hobby_retained_selected_and_conflicts_quarantined(model):
    n=memory(model)
    for i in range(30):n.accepted(f'The guest leaves object number {i} by the window.',f'A curtain moves in room {i}.',True)
    n.accepted('What was the identifier on the blue laboratory door?','The blue laboratory door was marked RAVEN-22.',True)
    n.accepted('What is your hobby?','My hobby is folding handkerchiefs.',True)
    for question,expected in [('What was the identifier on the blue laboratory door?','ORCHID-17'),('What is your hobby?','overgrown succulent')]:
        intent,found,_=retrieve(n.context(),question,model,n.state['epoch']);assert intent and any(expected in r['text'] for r in found)
        assert all('RAVEN-22' not in r['text'] and 'handkerchiefs' not in r['text'] for r in found)
    assert len(n.state['facts'])<=MAX_FACTS


def test_user_correction_reset_and_premise_stability():
    n=memory();premise=n.state['premise']
    n.accepted('Tell me a story about tea.','The kettle is warm.',True);assert n.state['premise']==premise
    n.accepted('Actually, the blue laboratory door is marked ORCHID-18.','Understood.',True)
    assert retrieve(n.context(),'What was the door identifier?','evelyn',n.state['epoch'])[1][0]['value']=='ORCHID-18'
    n.reset();assert not retrieve(n.context(),'What is your hobby?','evelyn',n.state['epoch'])[1]


def test_recall_compilation_and_identifier_guard_under_budget():
    n=memory();summary,history,native=fixture('evelyn-narrative-v1');summary|={'narrative_context':n.context(),'narrative_scope':['evelyn']}
    messages,_,d=ContextCompiler().compile(summary,'What was the door identifier?',history,AIConfig())
    assert 'ORCHID-17' in json.dumps(messages) and d['narrative_recall']['selected_fact_ids']
    assert recall_violations('It was RAVEN-22.',summary,d)==['unsupported_narrative_identifier']
    assert not recall_violations('It was ORCHID-17.',summary,d)
    assert not recall_violations('I cannot recall that identifier.',summary,d)


def curator_payload(n):
    c=MemoryCurator();c.configure(CuratorConfig(enabled=True,interval_turns=8))
    for _ in range(8):c.note(n,'A visitor wears a green coat.','A fictional shadow crosses the doorway.',True)
    return c,c.payload(n)


def proposal(payload,**updates):
    r=next(r for r in payload['memories'] if 'ORCHID-17' in r['text'])
    return dict(source_ref=r['id'],quote=r['text'],category=r['category'],importance=5,action='retain',justification='Exact established clue',**updates)


def test_curator_default_interval_and_validated_significance(tmp_path):
    store=SettingsStore(tmp_path);n=memory(store=store);c=MemoryCurator(store)
    assert not c.config.enabled
    c.configure(CuratorConfig(enabled=True,interval_turns=8))
    for i in range(7):c.note(n,'A visitor waits.','A curtain moves.',True)
    assert not c.due(n);c.note(n,'A visitor waits.','A curtain moves.',True);assert c.due(n)
    p=c.payload(n);assert not c.due(n)
    c.apply(n,p,json.dumps({'proposals':[proposal(p)]}))
    assert next(r for r in n.state['facts'] if 'ORCHID-17' in r['text'])['importance']==5
    restored=memory(store=store);assert any(r['importance']==5 for r in restored.state['facts'])
    assert MemoryCurator(store).config.enabled

@pytest.mark.parametrize('mutation',['invent','wrong_ref','category','json','duplicate_key','extra_field','scope','revision'])
def test_curator_rejects_unsupported_or_stale_output(mutation):
    n=memory();c,p=curator_payload(n);q=proposal(p);raw=None
    if mutation=='invent':q['quote']='A blue door is marked FICTION-999.'
    if mutation=='wrong_ref':q['source_ref']='0'*32
    if mutation=='category':q['category']='hypothesis'
    if mutation=='extra_field':q['hardware_action']='activate'
    if mutation=='scope':p['model_scope']='daisy'
    if mutation=='revision':p['revision']-=1
    before=deepcopy(n.state)
    raw='not json' if mutation=='json' else '{"proposals":[],"proposals":[]}' if mutation=='duplicate_key' else json.dumps({'proposals':[q]})
    with pytest.raises(ValueError):c.apply(n,p,raw)
    assert n.state==before


def test_curator_no_assistant_overwrite_or_omission_of_established_fact():
    n=memory();c,p=curator_payload(n);q=proposal(p);q['action']='omit'
    assert c.apply(n,p,json.dumps({'proposals':[q]}))[0]['decision']=='protected_established_fact'
    n.accepted('What was the door identifier?','The door was marked RAVEN-22.',True)
    c,p=curator_payload(n);q=proposal(p)
    c.apply(n,p,json.dumps({'proposals':[q]}));assert retrieve(n.context(),'What was the door identifier?','evelyn',n.state['epoch'])[1][0]['value']=='ORCHID-17'


def test_curator_persistence_failure_is_atomic(tmp_path,monkeypatch):
    n=memory(store=SettingsStore(tmp_path));c,p=curator_payload(n);before=deepcopy(n.state)
    def fail(*a):raise OSError('synthetic storage failure')
    monkeypatch.setattr(n.store,'write',fail)
    with pytest.raises(OSError):c.apply(n,p,json.dumps({'proposals':[proposal(p)]}))
    assert n.state==before


def test_curator_does_not_capture_telemetry_or_cross_epoch():
    n=memory();c=MemoryCurator();c.configure(CuratorConfig(enabled=True,interval_turns=8))
    for _ in range(8):c.note(n,'My heart rate is 120 BPM.','The sensor is connected.',True)
    assert not c.due(n)
    c.note(n,'A lantern glows.','A moth settles.',True);assert c.due(n)
    p=c.payload(n);n.reset()
    with pytest.raises(ValueError):c.apply(n,p,json.dumps({'proposals':[]}))


async def test_scheduler_user_and_event_priority_and_single_inference():
    from companion_ai.conversation import ConversationService
    from tests.ai.test_f251 import observation
    c,o,s=observation();o.report['status']='IDLE';o.report['details']['warmup_active']=False
    gate=asyncio.Event();started=asyncio.Event()
    class Adapter:
        config=AIConfig();mode='ollama'
        async def curate_memory(self,*a):started.set();await gate.wait();return '{"proposals":[]}',{}
        async def reply(self,*a,**kw):return 'A quiet moment.'
    service=ConversationService(o,lambda m:None,Adapter(),clock=c.mono)
    service.curator.configure(CuratorConfig(enabled=True,interval_turns=8))
    for _ in range(8):service.curator.note(service.narrative,'A fictional lantern glows.','A moth settles.',True)
    service.maybe_curate();task=service.curator.task;await started.wait()
    service.maybe_curate();assert service.curator.task is task
    service.request('Hello',user=True);await asyncio.gather(task,return_exceptions=True)
    assert service.curator.diagnostics['status']=='cancelled'
    await service.close()


async def test_curator_uses_selected_provider_json_schema_think_off_and_context_lock(tmp_path):
    import httpx
    from companion_ai.conversation import ModelManager
    from companion_ai.llm import OllamaProvider
    from tests.ai.test_f25 import runtime
    wire=[];manager=ModelManager(store=SettingsStore(tmp_path),transport=runtime(wire))
    manager.mode='ollama';manager.config=AIConfig(model='celeste-narrative-v2:latest');manager.adapter=manager.provider()
    manager.model_metadata={'system':'Native character stays intact.'}
    bodies=[]
    async def transport(request):
        body=json.loads(request.content)
        if request.url.path=='/api/show':return httpx.Response(200,json={'system':'Native character stays intact.','capabilities':['completion','thinking']})
        bodies.append(body)
        return httpx.Response(200,text=json.dumps({'message':{'content':'{"proposals":[]}'},'done':True,'done_reason':'stop'})+'\n')
    manager.adapter.transport=httpx.MockTransport(transport)
    text,_=await manager.curate_memory({'sources':[],'memories':[]},5)
    assert json.loads(text)=={'proposals':[]}
    assert bodies[0]['model']=='celeste-narrative-v2:latest' and bodies[0]['think'] is False
    assert bodies[0]['format']['properties']['proposals'] and 'tools' not in bodies[0]
    assert bodies[0]['messages'][0]['content'].startswith('Native character stays intact.')
    assert manager.config.explicit_expressions and manager.config.max_tokens!=1024


def test_optional_curator_can_deprioritize_routine_development_without_hiding_recall():
    n=memory();n.accepted('The rain is ordinary.','A curtain moves.',True);c,p=curator_payload(n)
    r=next(r for r in p['memories'] if r['text']=='A curtain moves.')
    q={'source_ref':r['id'],'quote':r['text'],'category':r['category'],'importance':0,'action':'omit','justification':'Routine repetitive scenery'}
    c.apply(n,p,json.dumps({'proposals':[q]}))
    record=next(r for r in n.state['facts'] if r['id']==q['source_ref']);assert record['curator_omit']
    assert record['curator_source_ref']==q['source_ref']


def test_legacy_identifier_and_hobby_migrate_without_losing_provenance(tmp_path):
    from uuid import uuid4
    store=SettingsStore(tmp_path);n=memory(store=store)
    for r in n.state['facts']:
        r['slot']='detail:'+r['id'];r['exact']=False
    n.persist();before={r['id']:(r['text'],r['speaker'],r['epoch']) for r in n.state['facts']}
    restored=NarrativeMemory(NarrativeConfig(persist_between_sessions=True),store);restored.activate('evelyn','synthetic')
    for r in restored.state['facts']:assert before[r['id']]==(r['text'],r['speaker'],r['epoch'])
    assert any(r['slot'].startswith('identifier:') for r in restored.state['facts'])
    assert any(r['slot'].startswith(('hobby:character','interest:character:')) for r in restored.state['facts'])


def test_hypothesis_does_not_replace_identifier_and_model_isolation():
    n=memory();n.accepted('Perhaps the blue laboratory door is marked ORCHID-99.','That remains a theory.',True)
    _,found,_=retrieve(n.context(),'What was the identifier on the blue laboratory door?','evelyn',n.state['epoch'])
    assert found[0]['value']=='ORCHID-17' and any(r['category']=='hypothesis' for r in found)
    assert not retrieve(n.context(),'What is your hobby?','daisy',n.state['epoch'])[1]


async def test_curator_event_preemption_and_active_session_exclusion():
    from companion_ai.conversation import ConversationService
    from tests.ai.test_f251 import observation
    c,o,s=observation();started=asyncio.Event()
    class Adapter:
        config=AIConfig();mode='ollama'
        async def curate_memory(self,*a):started.set();await asyncio.Event().wait()
    service=ConversationService(o,lambda m:None,Adapter(),clock=c.mono)
    service.curator.configure(CuratorConfig(enabled=True,interval_turns=8))
    for _ in range(8):service.curator.note(service.narrative,'A lamp glows.','A shadow moves.',True)
    service.maybe_curate();assert service.curator.task is None # engine running
    o.report['status']='IDLE';service.maybe_curate();await started.wait();task=service.curator.task
    service.enqueue('completion_accepted',70,{'event_id':'synthetic'})
    await asyncio.gather(task,return_exceptions=True);assert service.curator.diagnostics['status']=='cancelled'
    await service.close()


async def test_wrong_generated_identifier_uses_existing_single_factual_repair(tmp_path):
    import httpx
    from companion_ai.conversation import ModelManager
    n=memory();summary,_,_=fixture('evelyn-narrative-v1')
    summary|={'narrative_context':n.context(),'narrative_scope':['evelyn']}
    requests=[]
    async def handle(request):
        if request.url.path=='/api/show':return httpx.Response(200,json={'system':'Native character.','capabilities':['completion','thinking']})
        body=json.loads(request.content);requests.append(body)
        text='It was RAVEN-22.' if len(requests)==1 else 'It was ORCHID-17.'
        return httpx.Response(200,text=json.dumps({'message':{'content':text},'done':True,'done_reason':'stop'})+'\n')
    manager=ModelManager(store=SettingsStore(tmp_path),transport=httpx.MockTransport(handle));manager.mode='ollama';manager.config=AIConfig(model='evelyn-narrative-v1:latest');manager.adapter=manager.provider()
    result=await manager.reply(summary,'What was the door identifier?',[])
    assert 'ORCHID-17' in result and len(requests)==2 and all(r['think'] is False for r in requests)
    assert manager.grounding_attempts==2


async def test_curator_setting_is_authenticated_and_does_not_generate(tmp_path):
    from fastapi.testclient import TestClient
    from ai_observer.server import create_app
    from tests.ai.test_character_menus import TOKEN,ORIGIN,auth,until
    from tests.ai.test_f25 import runtime
    wire=[];app=create_app(TOKEN,tmp_path,transport=runtime(wire))
    with TestClient(app) as client:
        with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
            auth(ws);ws.send_json({'version':1,'type':'configure_curator','config':{'enabled':True,'interval_turns':8,'timeout_seconds':10}})
            state=until(ws,'character_state');assert state['memory_curator']['config']['enabled'] and not wire
            ws.send_json({'version':1,'type':'configure_curator','config':{'enabled':True,'interval_turns':1}})
            assert until(ws,'protocol_error') and not wire
    assert MemoryCurator(SettingsStore(tmp_path)).config.enabled


def test_curator_source_excerpt_updates_existing_quotation_without_duplication():
    n=memory();n.accepted('The page says "The truth was hidden in plain sight."','The page may matter.',True)
    c,p=curator_payload(n)
    text='The page says "The truth was hidden in plain sight."';source={'id':'f'*32,'text':text,'speaker':'user'};p['sources'].append(source)
    q={'source_ref':source['id'],'quote':text,'category':'user_fact','importance':5,'action':'retain','justification':'Exact clue copied from a sourced sentence'}
    before=len(n.state['facts']);c.apply(n,p,json.dumps({'proposals':[q]}))
    assert len(n.state['facts'])==before
    r=next(r for r in n.state['facts'] if r['value']=='The truth was hidden in plain sight.')
    assert r['importance']==5 and r['curator_source_ref']==source['id']


@pytest.mark.parametrize('text,allowed',[('I spend my evenings restoring antique maps.',True),('Perhaps I spend my evenings restoring antique maps.',False),('The curtain crosses the doorway.',False)])
def test_sourced_curator_can_recognize_personal_details_but_not_promote_theories(text,allowed):
    n=memory();n.accepted('A visitor waits.',text,True);c,p=curator_payload(n)
    r=next(r for r in p['memories'] if r['text']==text)
    q={'source_ref':r['id'],'quote':text,'category':'character_detail','importance':5,'action':'retain','justification':'First-person personal detail from character dialogue'}
    if allowed:
        c.apply(n,p,json.dumps({'proposals':[q]}));record=next(r for r in n.state['facts'] if r['text']==text)
        assert record['category']=='character_detail' and record['speaker']=='assistant' and record['text']==text
    else:
        with pytest.raises(ValueError):c.apply(n,p,json.dumps({'proposals':[q]}))
