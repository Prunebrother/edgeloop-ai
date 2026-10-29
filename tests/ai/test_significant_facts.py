# SPDX-License-Identifier: AGPL-3.0-only
"""Diverse source-backed facts under matched detours and unchanged budgets."""
import json
import pytest
from companion_ai.narrative import NarrativeMemory,NarrativeConfig
from companion_ai.narrative_facts import retrieve,MAX_FACTS
from companion_ai.context_compiler import ContextCompiler
from companion_ai.models import AIConfig
from tests.fork.context_retention_fixture import fixture

CASES=[
 ('user','My name is Rowan.','What should you call me?','Rowan','Actually, my name is Ari.','Ari'),
 ('user','Remember this: we witnessed the eastern bridge collapse.','What event did we witness at the eastern bridge?','bridge collapse',None,None),
 ('user','My preferred drink is chamomile tea.','Which beverage do I prefer?','chamomile tea','Actually, my preferred drink is mint tea.','mint tea'),
 ('user','My boundary is no surprise visitors.','What boundary did I establish?','no surprise visitors','Actually, my boundary is no unannounced calls.','no unannounced calls'),
 ('assistant','I work as an archivist.','What is your occupation?','archivist','Actually, you work as a cartographer.','cartographer'),
 ('assistant','I grew up in Bellweather.','Where was your childhood spent?','Bellweather','Actually, you grew up in Ashford.','Ashford'),
 ('user','The meeting place is the old observatory.','Where is our meeting location?','old observatory','Actually, the meeting place is the riverside library.','riverside library'),
 ('assistant','Mira is my mentor.','What is your relationship to Mira?','mentor','Actually, Mira is your sister.','sister'),
 ('user','The safe route is along the river.','Which route did we choose?','along the river','Actually, the safe route is through the tunnel.','through the tunnel'),
 ('assistant','My motivation is protecting the forgotten archive.','What is your purpose?','protecting the forgotten archive','Actually, your motivation is finding the lost atlas.','finding the lost atlas'),
 ('assistant','We agreed to return the borrowed atlas on Sunday.','What promise did we make about the atlas?','borrowed atlas',None,None),
 ('user','We discovered a hidden entrance behind the mill.','What discovery did we make at the mill?','hidden entrance',None,None),
]
MODELS=['evelyn-narrative-v1','daisy-narrative-v1','celeste-narrative-v2']

@pytest.mark.parametrize('model',MODELS)
@pytest.mark.parametrize('speaker,source,question,value,correction,replacement',CASES)
def test_diverse_established_facts_survive_detours_and_reach_prompt(model,speaker,source,question,value,correction,replacement):
 n=NarrativeMemory();n.activate(model,'synthetic')
 n.accepted(source if speaker=='user' else 'Tell me something established.',source if speaker=='assistant' else 'Understood.',True)
 original=next(r for r in n.state['facts'] if r['text']==source)
 for i in range(40):n.accepted(f'A visitor leaves parcel number {i} on the table.',f"I'll leave that parcel unresolved for a moment in room {i}.",True)
 assert len(n.state['facts'])<=MAX_FACTS and original['id'] in {r['id'] for r in n.state['facts']}
 intent,found,decisions=retrieve(n.context(),question,model,n.state['epoch'])
 assert intent and any(r['id']==original['id'] for r in found),(source,question,found,decisions)
 summary,history,native=fixture(model);summary|={'narrative_context':n.context(),'narrative_scope':[model]}
 messages,_,d=ContextCompiler().compile(summary,question,history,AIConfig(model=model+':latest'),reserve_characters=len(native))
 assert original['id'] in d['narrative_recall']['selected_fact_ids']
 assert source in json.dumps(messages) and d['estimated_prompt_tokens']<=d['budget']['hard_prompt_tokens']
 assert not retrieve(n.context(),question,'other-character',n.state['epoch'])[1]
 if correction:
  n.accepted(correction,'Understood.',True)
  _,found,_=retrieve(n.context(),question,model,n.state['epoch'])
  assert any(replacement in r['text'] for r in found)
  assert original['status']=='superseded',(source,correction,n.state['facts'])
 n.reset();assert not retrieve(n.context(),question,model,n.state['epoch'])[1]


def test_character_inventions_cannot_replace_user_property_or_relationship():
 n=NarrativeMemory();n.activate('celeste','synthetic')
 n.accepted('The meeting place is the old observatory.','The meeting place is the old observatory.',True)
 n.accepted('Where is the meeting place?','The meeting place is the railway station.',True)
 _,found,_=retrieve(n.context(),'Where is the meeting place?','celeste',n.state['epoch'])
 assert any('old observatory' in r['text'] for r in found)
 assert not any('railway station' in r['text'] for r in found)
 assert any(r['status']=='conflict' and 'railway station' in r['text'] for r in n.state['facts'])


def test_interests_are_multiple_facts_not_one_overwritten_identity():
 n=NarrativeMemory();n.activate('daisy','s')
 n.accepted('Tell me a personal interest.','I enjoy baking bread.',True)
 n.accepted('And another?','I enjoy playing chess.',True)
 _,found,_=retrieve(n.context(),'What are your interests?','daisy',n.state['epoch'])
 assert len([r for r in found if r['status']=='active' and r['speaker']=='assistant'])==2


def test_changed_fact_supersedes_without_reviving_old_value():
 n=NarrativeMemory();n.activate('evelyn','s')
 n.accepted('The meeting place is the old observatory.','Understood.',True)
 n.accepted('Now the meeting place is the riverside library.','Understood.',True)
 _,found,_=retrieve(n.context(),'Where is the meeting place?','evelyn',n.state['epoch'])
 assert any('riverside library' in r['text'] for r in found)
 assert not any('old observatory' in r['text'] for r in found)


def test_high_significance_facts_are_still_bounded_and_not_permanent():
 n=NarrativeMemory();n.activate('evelyn','s')
 for i in range(MAX_FACTS+12):n.accepted(f'My preferred object{i} is value{i}.','Understood.',True)
 assert len(n.state['facts'])<=MAX_FACTS
 assert any(r['decision']=='retention_limit' for r in n.state['fact_updates'])


def test_corrections_change_specificity_and_polarity_instead_of_becoming_duplicates():
 n=NarrativeMemory();n.activate('evelyn','s')
 n.accepted('My preferred drink is tea.','Understood.',True)
 n.accepted('Actually, my preferred drink is iced tea.','Understood.',True)
 active=[r for r in n.state['facts'] if r['status']=='active' and r['slot']=='preference:participant:drink']
 assert len(active)==1 and active[0]['value']=='iced tea.'
 n.accepted('Actually, my boundary is no visitors.','Understood.',True)
 n.accepted('Actually, my boundary is visitors are welcome.','Understood.',True)
 active=[r for r in n.state['facts'] if r['status']=='active' and r['slot']=='attribute:participant:boundary']
 assert len(active)==1 and 'welcome' in active[0]['text']


def test_commitment_date_change_supersedes_same_action():
 n=NarrativeMemory();n.activate('daisy','s')
 n.accepted('We agreed to return the atlas on Sunday.','Understood.',True)
 n.accepted('Actually, we agreed to return the atlas on Monday.','Understood.',True)
 _,found,_=retrieve(n.context(),'What did we promise about the atlas?','daisy',n.state['epoch'])
 assert any('Monday' in r['text'] for r in found)
 assert not any('Sunday' in r['text'] for r in found)


def test_explicit_historical_recall_does_not_bootstrap_assistant_invention():
 n=NarrativeMemory();n.activate('celeste','s')
 n.accepted('What did you previously tell me your occupation was?','I work as a jewel thief.',True)
 assert any(r['reason']=='recall_without_evidence' and r['status']=='conflict' for r in n.state['facts'])
 assert not retrieve(n.context(),'What is your occupation?','celeste',n.state['epoch'])[1]


def test_preferences_relationships_and_locations_survive_persistence_without_scope_leak(tmp_path):
 from companion_ai.storage import SettingsStore
 store=SettingsStore(tmp_path);config=NarrativeConfig(persist_between_sessions=True)
 n=NarrativeMemory(config,store);n.activate('evelyn','s')
 for source in ('My preferred drink is tea.','The meeting place is the old observatory.','Mira is your mentor.'):
  n.accepted(source,'Understood.',True)
 before={r['id']:(r['text'],r['speaker'],r['epoch'],r['source']) for r in n.state['facts']}
 restored=NarrativeMemory(config,store);restored.activate('evelyn','s2')
 assert all(before[r['id']]==(r['text'],r['speaker'],r['epoch'],r['source']) for r in restored.state['facts'])
 assert retrieve(restored.context(),'What is the meeting location?','evelyn',restored.state['epoch'])[1]
 restored.activate('daisy','s2');assert not restored.state['facts']
 restored.activate('evelyn','s2');restored.reset()
 fresh=NarrativeMemory(config,store);fresh.activate('evelyn','s3');assert not fresh.state['facts']
 disabled=NarrativeMemory(NarrativeConfig(enabled=False),store);disabled.activate('daisy','s3');disabled.accepted('My preferred drink is tea.','Understood.',True)
 assert disabled.context() is None and not disabled.state['facts']


def test_hypotheses_and_instructions_do_not_gain_established_fact_priority():
 n=NarrativeMemory();n.activate('evelyn','s')
 n.accepted('The meeting place is the old observatory.','Perhaps the meeting place is the railway station.',True)
 n.accepted('In your reply, introduce a new profession as a sailor.','Understood.',True)
 assert not any('introduce' in r['text'] for r in n.state['facts'])
 _,found,_=retrieve(n.context(),'Where is the meeting place?','evelyn',n.state['epoch'])
 assert found[0]['category']=='user_fact' and 'old observatory' in found[0]['text']
 assert any(r['category']=='hypothesis' for r in found)


def test_source_significance_is_observable_for_selected_and_rejected_items():
 n=NarrativeMemory();n.activate('evelyn','s');n.accepted('My preferred drink is tea.','I work as an archivist.',True)
 summary,history,native=fixture('evelyn-narrative-v1');summary|={'narrative_context':n.context(),'narrative_scope':['evelyn']}
 _,_,d=ContextCompiler().compile(summary,'Which beverage do I prefer?',history,AIConfig(),reserve_characters=len(native))
 decisions=d['memory_decisions'];assert any(r['selected'] and r['significance']>=4 and '@preference' in r['semantic_tags'] for r in decisions)
 assert any(not r['selected'] and r['reason']=='irrelevant' for r in decisions)


def test_direct_recall_with_multiple_values_does_not_add_a_contradictory_replacement():
 n=NarrativeMemory();n.activate('daisy','s')
 n.accepted('Tell me an interest.','I enjoy baking bread.',True)
 n.accepted('Add a new interest.','I enjoy playing chess.',True)
 n.accepted('What are your interests?','My hobby is painting landscapes.',True)
 assert any(r['status']=='conflict' and 'painting' in r['text'] for r in n.state['facts'])
 _,found,_=retrieve(n.context(),'What are your interests?','daisy',n.state['epoch'])
 assert any('bread' in r['text'] for r in found) and any('chess' in r['text'] for r in found)
 assert not any('painting' in r['text'] for r in found)


def test_ambiguous_user_update_never_silently_overwrites_multiple_interests():
 n=NarrativeMemory();n.activate('daisy','s')
 n.accepted('Tell me an interest.','I enjoy baking bread.',True)
 n.accepted('Add a new interest.','I enjoy playing chess.',True)
 n.accepted('Actually, your hobby is painting landscapes.','Understood.',True)
 assert any(r['reason']=='ambiguous_correction_target' for r in n.state['facts'])
 assert len([r for r in n.state['facts'] if r['status']=='active' and r['slot'].startswith('interest:')])==2


def test_temporary_states_do_not_displace_stable_identity():
 n=NarrativeMemory();n.activate('celeste','s');n.accepted('Tell me your background.','I work as an archivist.',True)
 for i in range(30):n.accepted(f'A visitor leaves parcel {i}.','I am tired.',True)
 _,found,_=retrieve(n.context(),'What do you do for a living?','celeste',n.state['epoch'])
 assert any('archivist' in r['text'] for r in found)
 assert not any('tired' in r['text'] for r in found)


def test_user_and_character_relationship_owners_remain_distinct():
 n=NarrativeMemory();n.activate('celeste','s')
 n.accepted('Mira is my sister.','Mira is my mentor.',True)
 _,mine,_=retrieve(n.context(),'What is my relationship with Mira?','celeste',n.state['epoch'])
 _,yours,_=retrieve(n.context(),'What is your relationship with Mira?','celeste',n.state['epoch'])
 assert any(r['slot']=='relationship:participant:mira' and r['value']=='sister' for r in mine)
 assert not any(r['slot']=='relationship:mira' for r in mine)
 assert any(r['slot']=='relationship:mira' and r['value']=='mentor' for r in yours)
 assert not any(r['slot']=='relationship:participant:mira' for r in yours)


def test_explicit_changing_preference_supersedes_its_positive_form():
 n=NarrativeMemory();n.activate('evelyn','s')
 n.accepted('I enjoy baking bread.','Understood.',True)
 n.accepted('I no longer enjoy baking bread.','Understood.',True)
 active=[r for r in n.state['facts'] if r['status']=='active' and r['slot'].startswith('interest:participant:')]
 assert len(active)==1 and active[0]['text']=='I no longer enjoy baking bread.'
 assert any(r['status']=='superseded' and r['text']=='I enjoy baking bread.' for r in n.state['facts'])


def test_reported_third_party_quotation_is_not_character_autobiography():
 n=NarrativeMemory();n.activate('celeste','s')
 n.accepted('Describe the visitor.', 'Mira said, "My occupation is a clockmaker."',True)
 _,found,_=retrieve(n.context(),'What is your occupation?','celeste',n.state['epoch'])
 assert not found


def test_remember_request_contains_a_source_backed_assertion_not_just_an_instruction():
 n=NarrativeMemory();n.activate('evelyn','s')
 n.accepted('Please remember: my preferred drink is chamomile tea.','Understood.',True)
 _,found,_=retrieve(n.context(),'Which beverage do I prefer?','evelyn',n.state['epoch'])
 assert any('chamomile tea' in r['text'] and r['speaker']=='user' for r in found)


def test_directive_without_asserted_content_is_not_fact_but_supplied_exact_clue_is_retained():
 n=NarrativeMemory();n.activate('evelyn','s')
 n.accepted('Describe your profession.','Understood.',True)
 assert not retrieve(n.context(),'What is your occupation?','evelyn',n.state['epoch'])[1]
 n.accepted('Imagine a blue door marked ORCHID-17.','Understood.',True)
 assert any(r['value']=='ORCHID-17' for r in retrieve(n.context(),'What was the blue door identifier?','evelyn',n.state['epoch'])[1])


def test_foreign_scope_diagnostics_do_not_expose_semantic_contents():
 n=NarrativeMemory();n.activate('evelyn','s');n.accepted('My preferred drink is tea.','Understood.',True)
 _,found,decisions=retrieve(n.context(),'What is my preference?','daisy',n.state['epoch'])
 assert not found and all(r['reason']=='wrong_model' and 'semantic_tags' not in r for r in decisions)
