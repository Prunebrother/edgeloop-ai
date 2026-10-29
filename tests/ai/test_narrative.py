# SPDX-License-Identifier: AGPL-3.0-only
import asyncio,json
from copy import deepcopy
import httpx,pytest
from companion_ai.narrative import NarrativeMemory,NarrativeConfig
from companion_ai.storage import SettingsStore
from companion_ai.models import AIConfig,MemoryConfig,SpeechPolicy
from companion_ai.conversation import ConversationService,ModelManager
from companion_ai.context import compose_messages
from companion_ai.director import ConversationDirector,DirectorConfig
from ai_observer.observation import ObserverDirector
from ai_observer.protocol import Observation,Messages
from tests.fork.grounding_cases import Clock,snapshot,frame
from tests.ai.test_f25 import runtime
from tests.ai.test_f251 import observation,change

def narrative():
    n=NarrativeMemory();n.activate('evelyn','s1');return n

def test_bounded_quotes_no_invented_summary_or_physiological_history():
    n=narrative();n.accepted('Imagine a mystery in the observatory.','I will keep the blue envelope for later.',True)
    for i in range(50):n.accepted('I choose the garden.','The letter bears a violet seal. Your BPM is 98. The device is moving.',True)
    c=n.context();assert c['premise']=='Imagine a mystery in the observatory.'
    assert c['choices']==['I choose the garden.'] and len(c['developments'])<=3
    assert len(json.dumps(c))<6500 and not any('BPM' in f['text'] or 'device' in f['text'] for f in c['facts'])
    assert 'fallible' in c['provenance'] and c['phase']=='development'

def test_scope_session_restoration_and_opt_in_local_persistence(tmp_path):
    store=SettingsStore(tmp_path);n=NarrativeMemory(store=store);n.activate('e','s1')
    n.accepted('Imagine a blue door.','I will keep the key.',True)
    n.activate('d','s1');assert n.context()['premise'] is None
    n.activate('e','s1');assert 'blue door' in n.context()['premise']
    n.activate('e','s2');assert n.context()['premise'] is None
    assert not list(tmp_path.rglob('*.json'))
    n=NarrativeMemory(NarrativeConfig(persist_between_sessions=True),store);n.activate('e','s1')
    n.accepted('Imagine a blue door.','I will keep the key.',True)
    restored=NarrativeMemory(NarrativeConfig(persist_between_sessions=True),store);restored.activate('e','s2')
    assert restored.context()['premise'] and not restored.state['initiative_allowed']
    restored.reset();assert restored.context()['premise'] is None
    again=NarrativeMemory(NarrativeConfig(persist_between_sessions=True),store);again.activate('e','s2');assert again.context()['premise'] is None

def test_unanswered_questions_and_quiet_do_not_trigger_initiative():
    n=narrative();n.accepted('Imagine a mystery. I choose the blue door.','Shall we open the envelope?',True)
    assert not n.opportunity()
    n.accepted('Yes, open it.','I will keep the seal for later.',True);assert n.opportunity()
    n.accepted('', 'A violet seal gleams in the lamplight.',False,initiative=True);assert not n.opportunity()
    n.accepted('Please stay quiet.','Of course.',True);assert not n.opportunity()

def test_narrative_phase_requires_story_or_verified_development():
    n=narrative();n.accepted('Hello.','Good evening.',True)
    assert n.context()['phase']=='opening'
    n.accepted('Imagine a mystery.','A folded map lies on the table.',True)
    n.accepted('', 'A new clue.',False,event='milestone');assert n.context()['phase']=='variation'
    n.accepted('', 'We can return to the mystery later.',False,event='came_early');assert n.context()['phase']=='resolution_or_transition'

def test_context_separates_fiction_from_current_facts_and_budget():
    c,o,s=observation();summary=o.summary()|{'conversation_source':'user','narrative_context':narrative().context()}
    messages,warnings=compose_messages(summary,'What is current BPM?',[],AIConfig())
    text=messages[-1]['content'];assert 'PRIMARY FOCUS' in text and 'CURRENT SESSION' in text
    assert 'NARRATIVE CONTEXT' not in text and '98' in text
    assert 'never override CURRENT SESSION' in messages[0]['content']

async def test_cancel_reset_switch_and_event_identity_do_not_save_partial_story():
    c,o,s=observation();gate=asyncio.Event()
    class Adapter:
        config=AIConfig();mode='ollama'
        async def reply(self,*a,**k):await gate.wait();return 'A violet envelope.'
    a=Adapter();speech=ConversationService(o,lambda m:None,a,clock=c.mono)
    speech.request('Imagine a mystery.',user=True);await asyncio.sleep(0)
    speech.reset_narrative();gate.set();await speech.task
    assert not speech.history and speech.narrative.context()['premise'] is None
    # A recent event must not become a user request's trigger via loop shadowing.
    calls=[]
    async def reply(summary,*args,**kwargs):calls.append(summary);return 'A different letter.'
    a.reply=reply;speech.recent_events.append({'kind':'edge','at':c.mono(),'priority':30})
    speech.request('Imagine a mystery.',user=True);await speech.task
    assert 'trigger_event' not in calls[-1]
    a.config=AIConfig(model='daisy-qwen35:latest');speech.activate_model();assert speech.narrative.context()['premise'] is None
    await speech.close()

async def test_extended_forty_turn_session_and_transport_thinking_off():
    c,o,s=observation();wire=[];turn=0
    transport=runtime(wire,'[[expression:focused]]The blue envelope remains beside the brass key.')
    m=ModelManager(transport=transport);await m.select(AIConfig(model='evelyn-lite-v1:latest'))
    speech=ConversationService(o,lambda _:None,m,clock=c.mono,director=ObserverDirector(DirectorConfig(regenerate_once=False),clock=c.mono))
    # Mock language is deliberately repetitive: this asserts bounded mechanics,
    # not subjective story quality. Full lifecycle sources use validated snapshots.
    prompts=['Imagine an observatory mystery. I choose the blue envelope.']+['Continue the mystery with a fresh detail.' for _ in range(39)]
    for i,p in enumerate(prompts):
        c.tick(1);s['details']['captured_at_ms']=int(c.wall()*1000);s['details']['hr_recorded_at_ms']=int(c.wall()*1000)
        if i==7:s['experience']='headplay'
        if i==10:s['goal']='oracle'
        if i==15:s['edges']+=1
        if i==22:s['status']='PAUSED';s['details']['warmup_active']=False
        if i==24:s['status']='RUNNING'
        if i==32:s['status']='IDLE';s['details']['warmup_active']=False
        kinds={7:['experience_changed'],10:['goal_changed'],15:['edge'],22:['pause'],24:['session_resumed'],32:['stop']}.get(i,[])
        message=Observation.model_validate(frame(s,i+1,kinds));assert o.accept(message)
        assert all(e.id in o.accepted_event_ids for e in message.events)
        speech.request(p,user=True);await speech.task
        assert len(speech.history)<=8 and len(json.dumps(speech.narrative.context()))<6500
    assert len(wire)==40 and all(w['think'] is False for _,w in wire)
    assert all('PRIMARY FOCUS' in w['messages'][-1]['content'] for _,w in wire)
    assert all(w['messages'][-1]['content'].count('NARRATIVE CONTEXT')<=1 for _,w in wire)
    assert all('[[expression:' not in r['content'] for r in speech.history)
    assert 'blue envelope' in speech.narrative.context()['premise']
    assert len(speech.history)==8
    await speech.close()

async def test_director_initiative_requires_engagement_and_is_spent_once():
    c,o,s=observation();calls=[]
    class Adapter:
        config=AIConfig();mode='ollama'
        async def reply(self,summary,prompt,history):calls.append(summary);return 'The violet seal suggests a different path.'
    d=ObserverDirector(DirectorConfig(regenerate_once=False),clock=c.mono);d.session_status='RUNNING'
    speech=ConversationService(o,lambda _:None,Adapter(),clock=c.mono,director=d)
    speech.narrative.accepted('Imagine a mystery. I choose the garden.','I will keep the key for later.',True)
    d.user('Continue the story.');c.tick(121)
    s['details']['captured_at_ms']=int(c.wall()*1000);s['details']['hr_recorded_at_ms']=int(c.wall()*1000);o.accept(Observation.model_validate(frame(s,1)))
    speech.pump();await speech.task
    assert len(calls)==1 and calls[0]['narrative_initiative'] and 'trigger_event' not in calls[0]
    c.tick(121);speech.pump();assert len(calls)==1
    d.memory['consecutive_unsolicited']=2;assert d.narrative_opportunity(True)[1]=='unsolicited_limit'
    await speech.close()

def test_reset_message_is_read_only_strict_protocol():
    assert Messages.validate_python({'version':1,'type':'reset_narrative'}).type=='reset_narrative'
    with pytest.raises(ValueError):Messages.validate_python({'version':1,'type':'reset_narrative','command':'start'})


def test_story_context_omits_irrelevant_numeric_data_but_retains_canonical_checks():
    from companion_ai.fidelity import violations
    c,o,s=observation();summary=o.summary()|{'conversation_source':'user','narrative_context':narrative().context()}
    messages,_=compose_messages(summary,'Imagine a mystery.',[],AIConfig())
    assert '98 BPM' not in messages[-1]['content'] and 'Heart rate [hr]' not in messages[-1]['content'] and 'HR source:' not in messages[-1]['content']
    assert o.canonical()['facts']['hr']['value']==98
    assert 'unmeasured_physiology_from_simulation_or_unknown' in violations('Our hearts are humming at 98 BPM.',o.canonical())
    assert 'unmeasured_physiology_from_simulation_or_unknown' in violations('My heart is hovering near 98 BPM.',o.canonical())
    assert not violations('The simulator reports 98 BPM; this is not your actual pulse.',o.canonical())

async def test_freshness_reconnect_reset_and_memory_disabled_block_initiative():
    c,o,s=observation()
    class Adapter:
        config=AIConfig();mode='ollama';memory=MemoryConfig(enabled=False)
        async def reply(self,*a,**kw):raise AssertionError('No inference expected')
    d=ObserverDirector(clock=c.mono);d.session_status='RUNNING';speech=ConversationService(o,lambda _:None,Adapter(),clock=c.mono,director=d)
    speech.narrative.accepted('Imagine a mystery. I choose the garden.','I will keep the key.',True)
    c.tick(130);speech.pump();assert speech.task is None
    speech.adapter.memory=MemoryConfig();speech.pump();assert speech.task is None # stale
    o.begin_epoch();speech.pump();assert speech.task is None
    old=speech.narrative.session;s['session_id']='11111111-2222-4333-8444-555555555555'
    s['details']['captured_at_ms']=int(c.wall()*1000);o.accept(Observation.model_validate(frame(s,1)))
    speech.sync_narrative();assert speech.narrative.session!=old and speech.narrative.context()['premise'] is None
    await speech.close()


def test_previous_session_operational_dialogue_is_omitted_on_story_continuation():
    c,o,s=observation();summary=o.summary()|{'conversation_source':'user','narrative_context':narrative().context()}
    history=[{'role':'assistant','content':'The session was at 120 BPM.','session_id':'old'}, {'role':'user','content':'The blue envelope matters.','session_id':'old'}]
    messages,warnings=compose_messages(summary,'Continue our mystery.',history,AIConfig())
    assert not any(m['content']=='The session was at 120 BPM.' for m in messages)
    assert any(m['content']=='The blue envelope matters.' for m in messages)
    assert warnings


def test_optional_story_context_yields_to_current_facts_under_tight_budget():
    c,o,s=observation();n=narrative();n.accepted('Imagine a mystery.','A blue envelope waits.',True)
    for char in 'abcdefgh':n.accepted('I choose the garden.',char*175+'.',True)
    summary=o.summary()|{'conversation_source':'user','narrative_context':n.context()}
    # Derive a small remaining budget from the actual prompt, not a tokenizer guess.
    config=AIConfig(max_tokens=512)
    messages,_=compose_messages(summary,'Continue the story.',[],config)
    from companion_ai.context_compiler import ContextConfig,estimate
    base,_=compose_messages(summary,'Continue the story.',[],config,context_config=ContextConfig(narrative_tokens=0))
    required=sum(estimate(m['content'])+32 for m in base)
    reserve=int((config.context_length-config.max_tokens-96-required-8)*2.5)
    messages,warnings=compose_messages(summary,'Continue the story.',[],config,reserve_characters=reserve)
    assert 'CURRENT SESSION' in messages[-1]['content']
    assert 'NARRATIVE CONTEXT' not in messages[-1]['content'] and any('narrative' in w for w in warnings)
    assert n.context()['premise']


def test_narrative_cannot_claim_generic_hardware_motion_or_paused_after_stop():
    from companion_ai.fidelity import violations
    c,o,s=observation()
    assert 'unverified_physical_motion' in violations('The machine is humming along.',o.canonical())
    assert not violations('In the imagined scene, the machine is humming along.',o.canonical())
    o.report['status']='IDLE'
    assert 'unsupported_session_status' in violations('With the session officially paused, we can talk.',o.canonical())


@pytest.mark.parametrize('reply',['[[expression:focused]]A new clue waits by the window.','[SILENCE]'])
async def test_initiative_wire_payload_and_silence_spend_one_bounded_opportunity(reply):
    c,o,s=observation();wire=[];m=ModelManager(transport=runtime(wire,reply));await m.select(AIConfig(model='daisy-narrative-v1:latest'))
    d=ObserverDirector(DirectorConfig(regenerate_once=False),clock=c.mono);d.session_status='RUNNING'
    speech=ConversationService(o,lambda _:None,m,clock=c.mono,director=d)
    speech.narrative.accepted('Imagine a mystery. I choose the garden.','I will keep the key.',True)
    d.user('Continue our story.');c.tick(121)
    s['details']['captured_at_ms']=int(c.wall()*1000);s['details']['hr_recorded_at_ms']=int(c.wall()*1000);assert o.accept(Observation.model_validate(frame(s,1)))
    speech.pump();await speech.task
    assert len(wire)==1 and wire[0][1]['think'] is False
    assert 'bounded narrative opportunity' in wire[0][1]['messages'][0]['content']
    c.tick(121);speech.pump();assert len(wire)==1
    await speech.close()
