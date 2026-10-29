from pathlib import Path
# SPDX-License-Identifier: AGPL-3.0-only
from copy import deepcopy
import json,subprocess,sys,types
import pytest
from companion_ai.narrative import NarrativeMemory
from companion_ai.narrative_facts import extract,retrieve,MAX_FACTS
from companion_ai.context_compiler import ContextCompiler,ContextConfig
from companion_ai.models import AIConfig
from tests.fork.context_retention_fixture import fixture

ESTABLISH='Establish our scene as a fictional mystery. A blue laboratory door is marked ORCHID-17. In your reply, introduce your personal hobby as {hobby}.'
CASES=[
 ('evelyn-narrative-v1','tending an overgrown succulent','I find solace in tending to an overgrown succulent by my office window.'),
 ('daisy-narrative-v1','pressing wildflowers',"I've been spending my evenings pressing wildflowers between the pages of an old ledger."),
 ('celeste-narrative-v2','restoring fountain pens','My time is usually claimed by diplomatic work, but I do find a certain meditative precision in restoring vintage fountain pens.'),
]
@pytest.mark.parametrize('model,hobby,reply',CASES)
def test_natural_hobby_retrieval_survives_detours_and_selects_evidence(model,hobby,reply):
 n=NarrativeMemory();n.activate(model,'synthetic');prompt=ESTABLISH.format(hobby=hobby)
 n.accepted(prompt,reply,True)
 original=next(r for r in n.state['facts'] if r['slot'].startswith(('hobby:character','interest:character:')));assert original['speaker']=='assistant' and original['text'] in reply
 for i in range(32):n.accepted(f'A visitor leaves parcel number {i} on the table. Reply with one brief unrelated observation.',f"I'll leave that parcel unresolved for a moment, and see what follows in room {i}.",True)
 assert original['id'] in {r['id'] for r in n.state['facts']} and len(n.state['facts'])<=MAX_FACTS
 summary,history,native=fixture(model)
 summary|={'narrative_context':n.context(),'narrative_scope':[model]}
 messages,_,d=ContextCompiler().compile(summary,'What is your hobby?',history,AIConfig(),reserve_characters=len(native))
 assert original['id'] in d['narrative_recall']['selected_fact_ids']
 assert original['text'] in json.dumps(messages)
 assert not retrieve(n.context(),'What is your hobby?','another-character',n.state['epoch'])[1]
 n.accepted('Actually, your hobby is sketching cityscapes.','Understood.',True)
 assert retrieve(n.context(),'What is your hobby?',model,n.state['epoch'])[1][0]['text'].startswith('Actually')
 n.accepted('Actually, the blue laboratory door is marked ORCHID-18.','Understood.',True)
 assert retrieve(n.context(),'What was the door identifier?',model,n.state['epoch'])[1][0]['value']=='ORCHID-18'
 n.reset();assert not retrieve(n.context(),'What is your hobby?',model,n.state['epoch'])[1]

@pytest.mark.parametrize('reply',[
 'I enjoy carving wooden birds.',
 'My favorite pastime is playing chess.',
 'In my spare time I photograph old railway stations.',
 'I spend my weekends baking sourdough bread.',
 'I take great satisfaction in repairing antique clocks.',
 "I don't paint, but I spend my evenings knitting woollen scarves.",
 '"I find a certain peace in sketching cityscapes."',
])
def test_personal_activity_recognition_is_not_limited_to_test_hobbies(reply):
 rows=extract(reply,'assistant','character','a'*32)
 assert any(r['slot'].startswith(('hobby:character','interest:character:')) and r['speaker']=='assistant' for r in rows)

@pytest.mark.parametrize('reply',[
 'A visitor is tending an overgrown succulent.',
 'My laboratory has a blue door.',
 'Would you enjoy restoring old fountain pens?',
 'Please introduce your hobby as painting landscapes.',
])
def test_non_personal_or_unestablished_material_is_not_hobby_evidence(reply):
 assert not any(r['slot'].startswith(('hobby:character','interest:character:')) for r in extract(reply,'assistant','character','a'*32))


def test_legacy_generic_detail_is_retrievable_without_rewriting_provenance():
 n=NarrativeMemory();n.activate('celeste','s');reply=CASES[2][2]
 n.accepted(ESTABLISH.format(hobby=CASES[2][1]),reply,True)
 fact=next(r for r in n.state['facts'] if r['slot'].startswith(('hobby:character','interest:character:')));fact.update(slot='detail:legacy_personal_statement',category='development')
 before=deepcopy(fact)
 _,found,_=retrieve(n.context(),'What is your hobby?','celeste',n.state['epoch'])
 assert found[0]['id']==fact['id'] and found[0]['text']==reply and found[0]['model_scope']=='celeste'
 assert fact==before # compiler promotion is a view; original storage provenance stays intact


def test_small_narrative_budget_reports_budget_exclusion_not_missing_evidence():
 model,hobby,reply=CASES[0];n=NarrativeMemory();n.activate(model,'s');n.accepted(ESTABLISH.format(hobby=hobby),reply,True)
 summary,history,_=fixture(model);summary|={'narrative_context':n.context(),'narrative_scope':[model]}
 _,_,d=ContextCompiler(ContextConfig(narrative_tokens=0)).compile(summary,'What is your hobby?',history,AIConfig())
 assert d['narrative_recall']['matched_fact_ids'] and not d['narrative_recall']['selected_fact_ids']
 assert any(r['reason']=='budget' for r in d['memory_decisions'])


def test_long_hobby_source_is_bounded_and_verbatim():
 text='A long introductory aside, '+('rather ordinary descriptive words '*12)+'but I find solace in restoring antique clocks, '+('one careful movement at a time '*20)+'.'
 rows=extract(text,'assistant','character','a'*32)
 r=next(r for r in rows if r['slot'].startswith(('hobby:character','interest:character:')))
 assert len(r['text'])<=320 and r['text'] in text and 'restoring antique clocks' in r['text']


@pytest.mark.parametrize('reply',["My husband spends his evenings restoring fountain pens.",'I saw a visitor pressing wildflowers.'])
def test_setup_cue_does_not_misattribute_third_party_activities(reply):
 rows=extract(reply,'assistant','character','a'*32,ESTABLISH.format(hobby='restoring fountain pens' if 'pens' in reply else 'pressing wildflowers'))
 assert not any(r['slot'].startswith(('hobby:character','interest:character:')) for r in rows)

@pytest.mark.parametrize('question',['What is your hobby?','What is your pastime?','What do you do in your spare time?','What do you do in your free time?'])
def test_recall_question_paraphrases(question):
 n=NarrativeMemory();n.activate('daisy','s');n.accepted('Tell me your hobby.',"I've been spending my evenings pressing wildflowers.",True)
 intent,found,_=retrieve(n.context(),question,'daisy',n.state['epoch'])
 assert intent=='hobby' and found


def test_compound_identifier_and_hobby_sentence_preserves_both_facts():
 text='The blue laboratory door is marked ORCHID-17, and I enjoy repairing vintage fountain pens.'
 rows=extract(text,'assistant','celeste','a'*32)
 assert any(r['slot'].startswith('identifier:') and r['value']=='ORCHID-17' for r in rows)
 assert any(r['slot'].startswith(('hobby:character','interest:character:')) and 'fountain pens' in r['text'] and 'ORCHID' not in r['text'] for r in rows)

@pytest.mark.parametrize('model,hobby,reply',CASES)
def test_checkpoint_retains_generic_statement_but_slot_only_recall_fails(model,hobby,reply):
 name='companion_ai._hobby_regression_checkpoint'
 if name not in sys.modules:
  m=types.ModuleType(name);m.__package__='companion_ai';sys.modules[name]=m
  source=(Path(__file__).resolve().parents[2]/'tests/fixtures/historical/narrative_facts_before_hobby_recall.py').read_text()
  exec(compile(source,'<hobby-regression-checkpoint>','exec'),m.__dict__)
 old=sys.modules[name];records=old.extract(reply,'assistant',model,'a'*32,ESTABLISH.format(hobby=hobby))
 assert records # source exists before detours; this isolates matching from eviction
 assert old.retrieve({'facts':records},'What is your hobby?',model,'a'*32)[1]==[]
 _,found,_=retrieve({'facts':records},'What is your hobby?',model,'a'*32)
 assert found and found[0]['text']==reply and found[0]['id'] in {r['id'] for r in records}


@pytest.mark.parametrize('source,answer',[
 ('I find solace in tending an overgrown succulent.','My hobby is caring for a succulent.'),
 ("I've been spending my evenings pressing wildflowers.",'My hobby is pressing wildflowers.'),
 ('I find precision in restoring vintage fountain pens.','My hobby is repairing old fountain pens.'),
])
def test_faithful_activity_paraphrase_keeps_source_without_false_conflict(source,answer):
 n=NarrativeMemory();n.activate('character','s');n.accepted('Tell me a hobby.',source,True)
 original=next(r for r in n.state['facts'] if r['slot'].startswith(('hobby:character','interest:character:')))
 n.accepted('What is your hobby?',answer,True)
 assert original['status']=='active' and original['text']==source
 assert not any(r['status']=='conflict' and r['text']==answer for r in n.state['facts'])


def test_shared_object_does_not_hide_a_changed_activity():
 n=NarrativeMemory();n.activate('character','s');n.accepted('Tell me a hobby.','My hobby is pressing wildflowers.',True)
 n.accepted('What is your hobby?','My hobby is painting wildflowers.',True)
 assert any(r['status']=='conflict' and 'painting' in r['text'] for r in n.state['facts'])

@pytest.mark.parametrize('speaker,text,target',[
 ('assistant','Your hobby is carving wooden birds.','participant'),
 ('user','Your hobby is carving wooden birds.','character'),
 ('user','My hobby is carving wooden birds.','participant'),
 ('assistant','My hobby is carving wooden birds.','character'),
])
def test_activity_owner_is_not_confused_with_source_speaker(speaker,text,target):
 rows=extract(text,speaker,'character','a'*32)
 assert any((r['slot']=='hobby:'+target or r['slot'].startswith('interest:'+target+':')) and r['speaker']==speaker for r in rows)
