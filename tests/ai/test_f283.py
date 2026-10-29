"""Narrative evidence regressions; no physical hardware or live inference."""
import asyncio,json,re
from copy import deepcopy
from pathlib import Path
import httpx,pytest
from companion_ai.narrative import NarrativeMemory,NarrativeConfig
from companion_ai.narrative_facts import MAX_FACTS,native_canon,operational_text
from companion_ai.context_compiler import ContextCompiler,ContextConfig
from companion_ai.context import ContextBudgetError
from companion_ai.models import AIConfig
from companion_ai.storage import SettingsStore
from companion_ai.conversation import ConversationService,ModelManager
from tests.ai.test_f251 import observation

QUOTE='The truth was hidden in plain sight.'
POTS='vintage, slightly dented teapots'
MODELS=('evelyn-narrative-v1','daisy-narrative-v1','celeste-narrative-v2')
ROOT=Path(__file__).resolve().parents[2]
def memory(model=MODELS[0],store=None,persist=False):
 n=NarrativeMemory(NarrativeConfig(persist_between_sessions=persist),store);n.activate(model,'synthetic-session');return n

def establish(n):
 n.accepted('The Glasshouse page said: "'+QUOTE+'".','I collect '+POTS+'.',True)

def compile_memory(n,prompt,history=None,config=None,native=True):
 c,o,s=observation();source=(ROOT/'characters/models'/n.scope/'Modelfile').read_text() if native else ''
 text=re.search(r'SYSTEM\s+"""(.*?)"""',source,re.S)[1] if source else ''
 return ContextCompiler(config).compile(o.summary()|{'conversation_source':'user','narrative_context':n.context(True)},prompt,history or [],AIConfig(model=n.scope+':latest'),reserve_characters=len(text))

@pytest.mark.parametrize('model',MODELS)
@pytest.mark.parametrize('question,expected',[('What did the page say?',QUOTE),('What do you collect?',POTS)])
def test_exact_recall_after_long_detour_for_each_character(model,question,expected):
 n=memory(model);establish(n)
 for i in range(48):n.accepted('Can we discuss the garden?','A breeze passes the garden wall '+str(i)+'.',True)
 history=[{'role':'user' if i%2 else 'assistant','content':'An unrelated recent gardening exchange '+str(i)+'.'} for i in range(8)]
 messages,_,d=compile_memory(n,question,history)
 assert expected in json.dumps(messages,ensure_ascii=False)
 assert d['narrative_recall']['selected_fact_ids'] and d['narrative_recall']['evidence']=='selected'
 assert len(n.state['facts'])<=MAX_FACTS
 selected=[r for r in n.state['facts'] if r['id'] in d['narrative_recall']['selected_fact_ids']]
 assert any(r['speaker']==('user' if expected==QUOTE else 'assistant') for r in selected)
 assert all(r['model_scope']==model and r['epoch']==n.state['epoch'] for r in selected)

@pytest.mark.parametrize('question,answer,expected',[('What did the page say?','It said: "The answer sleeps beneath the roses."',QUOTE),('What do you collect?','I collect embroidered handkerchiefs.',POTS)])
def test_contradictory_assistant_recall_is_quarantined(question,answer,expected):
 n=memory();establish(n);n.accepted(question,answer,True)
 assert any(r['status']=='conflict' for r in n.state['facts'])
 m,_,d=compile_memory(n,question,[{'role':'assistant','content':answer}])
 assert expected in json.dumps(m)
 assert not any(message['content']==answer for message in m)
 assert any(x['reason']=='inactive_or_conflicting' for x in d['memory_decisions'])
 assert answer not in n.state['developments']

@pytest.mark.parametrize('correction,question,expected,old',[('Actually, the page said: "We left the lantern burning."','What did the page say?','We left the lantern burning.',QUOTE),('No, you collect blue porcelain bowls, not teapots.','What do you collect?','blue porcelain bowls',POTS)])
def test_explicit_user_correction_supersedes_dialogue(correction,question,expected,old):
 n=memory();establish(n);n.observe_user(correction)
 m,_,d=compile_memory(n,question)
 assert expected in json.dumps(m) and old not in json.dumps(m)
 assert any(r['status']=='superseded' for r in n.state['facts'])
 assert any(r['speaker']=='user' and r['value']==expected and r['status']=='active' for r in n.state['facts'])


def test_user_correction_cannot_override_explicit_native_relationship():
 n=memory(MODELS[2]);source=(ROOT/'characters/models/celeste-narrative-v2/Modelfile').read_text();n.set_canon(source)
 n.observe_user('Actually, Laurent is your brother.')
 assert native_canon(source)['relationship:laurent']=='husband'
 assert any(r['reason']=='native_canon_conflict' for r in n.state['facts'])
 c,o,_=observation()
 m,_,d=ContextCompiler().compile(o.summary()|{'conversation_source':'user','narrative_context':n.context(True),'narrative_canon':native_canon(source)},'What did we establish about Laurent?',[],AIConfig())
 assert 'Laurent is your brother' not in json.dumps(m)

@pytest.mark.parametrize('prompt',['What did the page say?','What do you collect?'])
def test_missing_evidence_requests_uncertainty(prompt):
 n=memory();m,_,d=compile_memory(n,prompt)
 assert d['narrative_recall']['evidence']=='unavailable'
 assert 'acknowledge uncertainty' in m[-1]['content'] and 'no matching structured memory selected' in m[-1]['content']


def test_hypothesis_is_not_promoted_to_an_established_quotation():
 n=memory();n.accepted('Perhaps the page says "A blue moon rises."','It might be a theory.',True)
 assert any(r['category']=='hypothesis' for r in n.state['facts'])
 assert not any(r['category']=='user_fact' and r['exact'] for r in n.state['facts'])
 m,_,d=compile_memory(n,'What did the page say?')
 assert 'hypothesis' in m[-1]['content'] and 'hypotheses are not established facts' in m[-1]['content']

@pytest.mark.parametrize('text',['The fictional session in chapter 7 begins at midnight.','Her heart was broken in chapter 12.','I keep 3 teapots by the window.'])
def test_innocent_numbers_and_operational_story_words_are_retained(text):
 n=memory();n.accepted(text,'An agreed fictional detail.',True)
 assert any(r['text']==text for r in n.state['facts'])
 assert not operational_text(text)

@pytest.mark.parametrize('text',['Your BPM is 98.','The BLE sensor is disconnected.','The session is running for 42 seconds.'])
def test_actual_operational_claims_are_not_story_facts(text):
 n=memory();n.accepted(text,text,True)
 assert not n.state['facts'] and n.excerpt(text) is None


def test_story_reset_preserves_transcript_but_excludes_old_epoch():
 n=memory();establish(n);old=n.state['epoch']
 history=[{'role':'user','content':QUOTE,'narrative_epoch':old}]
 n.reset();assert n.state['epoch']!=old and not n.state['facts'] and not n.state['developments']
 c,o,_=observation()
 m,_,d=ContextCompiler().compile(o.summary()|{'conversation_source':'user','narrative_context':n.context(True),'narrative_epoch':n.state['epoch']},'What did the page say?',history,AIConfig())
 assert QUOTE not in json.dumps(m) and history[0]['content']==QUOTE
 assert d['narrative_recall']['evidence']=='unavailable'


def test_reset_persistence_failure_does_not_publish_a_new_memory_epoch(tmp_path):
 store=SettingsStore(tmp_path);n=memory(store=store,persist=True);establish(n);before=deepcopy(n.state)
 def fail(*args):raise OSError('test disk failure')
 store.write=fail
 with pytest.raises(OSError):n.reset()
 assert n.state==before


def test_records_persist_with_provenance_and_do_not_resurrect_after_reset(tmp_path):
 store=SettingsStore(tmp_path);n=memory(store=store,persist=True);establish(n);original=n.state['facts'][0]
 restored=memory(store=store,persist=True)
 assert restored.state['facts'][0]==original
 restored.reset();again=memory(store=store,persist=True)
 assert not again.state['facts'] and not again.state['developments']


def test_legacy_memory_migration_does_not_invent_speaker_identity(tmp_path):
 store=SettingsStore(tmp_path);n=memory(store=store,persist=True)
 old=deepcopy(n.state);old.pop('facts');old.pop('facts_initialized');old['version']=1
 old['developments']=['"'+QUOTE+'"','I have a collection of '+POTS+'.']
 store.write(n.path(n.scope),old)
 loaded=memory(store=store,persist=True)
 assert loaded.state['facts'] and all(r['speaker']=='unknown' and r['source']=='legacy_excerpt' for r in loaded.state['facts'])
 m,_,d=compile_memory(loaded,'What did the page say?');assert QUOTE in json.dumps(m)
 assert d['narrative_recall']['selected_fact_ids']
 m,_,d=compile_memory(loaded,'What do you collect?');assert POTS in json.dumps(m)
 assert d['narrative_recall']['evidence']=='legacy_unattributed'

@pytest.mark.parametrize('model',MODELS)
def test_model_switch_does_not_mix_quotes_or_collections(model):
 n=memory(model);establish(n);epoch=n.state['epoch']
 other=next(m for m in MODELS if m!=model);n.activate(other,'synthetic-session')
 m,_,d=compile_memory(n,'What do you collect?');assert POTS not in json.dumps(m)
 n.activate(model,'synthetic-session');assert n.state['epoch']==epoch
 m,_,d=compile_memory(n,'What do you collect?');assert POTS in json.dumps(m)


def test_wrong_scope_and_epoch_records_are_not_selected():
 n=memory();establish(n);context=n.context(True);context['model_scope']='other';context['epoch']='a'*32
 c,o,_=observation();m,_,d=ContextCompiler().compile(o.summary()|{'conversation_source':'user','narrative_context':context},'What did the page say?',[],AIConfig())
 assert QUOTE not in json.dumps(m)
 assert any(x['reason'] in {'wrong_model','wrong_epoch'} for x in d['memory_decisions'])


def test_budget_exclusions_are_visible_without_dropping_current_request():
 n=memory();establish(n);prompt='What did the page say?'
 m,_,d=compile_memory(n,prompt,config=ContextConfig(narrative_tokens=0))
 assert d['narrative_recall']['evidence']=='budget_excluded'
 assert any(x['reason']=='budget' for x in d['memory_decisions'])
 assert m[-1]['content'].endswith(prompt) and 'acknowledge uncertainty' in m[-1]['content']

async def test_user_clue_is_stored_even_if_generation_is_cancelled():
 c,o,_=observation();gate=asyncio.Event()
 class Adapter:
  config=AIConfig(model=MODELS[0]+':latest');mode='ollama'
  async def reply(self,*args,**kw):await gate.wait();return 'An unrelated reply.'
 service=ConversationService(o,lambda _:None,Adapter(),clock=c.mono)
 service.request('The page says "'+QUOTE+'"',user=True);await asyncio.sleep(0)
 assert any(r['value']==QUOTE and r['speaker']=='user' for r in service.narrative.state['facts'])
 service.interrupt();await service.task;assert not service.history
 await service.close()

@pytest.mark.parametrize('model',MODELS)
async def test_outgoing_provider_keeps_native_identity_expression_and_exact_memory(model):
 n=memory(model);establish(n);wire=[]
 native=re.search(r'SYSTEM\s+"""(.*?)"""',(ROOT/'characters/models'/model/'Modelfile').read_text(),re.S)[1]
 def transport(request):
  if request.url.path=='/api/show':return httpx.Response(200,json={'system':native,'capabilities':['completion']})
  wire.append(json.loads(request.content))
  return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:focused]] The page said: "'+QUOTE+'"'},'done':True})+'\n')
 c,o,_=observation();manager=ModelManager(transport=httpx.MockTransport(transport));await manager.start(AIConfig(model=model+':latest'))
 result=await manager.reply(o.summary()|{'conversation_source':'user','narrative_context':n.context(True)},'What did the page say?',[])
 assert QUOTE in result and len(wire)==1 and wire[0]['think'] is False
 assert wire[0]['messages'][0]['content'].startswith(native+'\n\n')
 assert QUOTE in wire[0]['messages'][-1]['content']


def test_named_story_character_correction_replaces_the_previous_name():
 n=memory();n.accepted('The witness is named Lena.','We can question her tomorrow.',True)
 n.observe_user('Actually, the witness is named Mara.')
 m,_,d=compile_memory(n,'What did we establish about the witness?')
 assert 'Mara' in json.dumps(m) and 'named Lena' not in json.dumps(m)
 assert any(r['slot']=='name:witness' and r['value']=='Mara' and r['status']=='active' for r in n.state['facts'])


def test_preference_is_protected_from_a_contradictory_assistant_replacement():
 n=memory();n.accepted('Tell me about your tea.','My favorite tea is oolong.',True)
 n.accepted('What did you say about your favorite tea?','My favorite tea is green tea.',True)
 m,_,d=compile_memory(n,'What did you say about your favorite tea?')
 assert 'oolong' in json.dumps(m) and 'green tea' not in json.dumps(m)
 assert any(r['slot']=='preference:character:tea' and r['status']=='conflict' for r in n.state['facts'])
