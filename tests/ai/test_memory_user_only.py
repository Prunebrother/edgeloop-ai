"""Default memory policy: companion-spoken facts are not stored, only the latest user message is replayed.
Synthetic state, no hardware or live inference. See Memory_UserOnly_20261103 for the real-model A/B."""
import json
from companion_ai.narrative import NarrativeMemory,NarrativeConfig
from tests.ai.test_f283 import compile_memory,establish,POTS

def memory(**config):
 n=NarrativeMemory(NarrativeConfig(**config));n.activate('evelyn-narrative-v1','synthetic-session');return n

def test_companion_statements_are_not_stored_as_facts_by_default():
 n=memory()
 n.accepted('Tell me about yourself.','I collect '+POTS+'. My favorite tea is oolong.',True)
 assert not any(r['speaker']=='assistant' for r in n.state['facts'])
 assert not any(u.get('speaker')=='assistant' and u['decision'] not in {'contradicts_established_detail','native_canon_conflict','recall_without_evidence'} for u in n.state['fact_updates'])

def test_user_facts_are_still_stored_by_default():
 n=memory()
 n.accepted('My preferred drink is tea.','Noted.',True)
 assert any(r['speaker']=='user' and 'tea' in r['text'] for r in n.state['facts'])
 assert not any(r['speaker']=='assistant' for r in n.state['facts'])

def test_opt_in_still_stores_companion_statements():
 n=memory(assistant_facts=True)
 n.accepted('Tell me about yourself.','I collect '+POTS+'.',True)
 assert any(r['speaker']=='assistant' and r['slot']=='collection:character' for r in n.state['facts'])

def test_companion_line_contradicting_a_user_correction_is_still_quarantined():
 n=memory()
 n.observe_user('No, you collect blue porcelain bowls, not teapots.')
 before=json.dumps(n.state['facts'])
 n.accepted('What do you collect?','I collect embroidered handkerchiefs.',True)
 assert json.dumps(n.state['facts'])==before  # nothing stored or rewritten from the companion's line
 m,_,_=compile_memory(n,'What do you collect?')
 assert 'blue porcelain bowls' in json.dumps(m) and 'handkerchiefs' not in json.dumps(m)

def test_stored_companion_facts_reach_the_prompt_only_on_a_recall_question():
 # Legacy or opt-in state may still hold companion facts; ordinary turns must not feed them back.
 n=memory(assistant_facts=True);establish(n)
 ordinary,_,_=compile_memory(n,'Those dented teapots sound lovely.')  # overlaps the fact, but is not a recall question
 recall,_,_=compile_memory(n,'What do you collect?')
 assert 'speaker=assistant' not in json.dumps(ordinary)
 assert POTS in json.dumps(recall)

def test_companion_reply_clips_are_not_kept_as_story_excerpts():
 n=memory()
 n.accepted('How was your day?',"I'll show you the root cellar later. Better than last time, are we?",True)
 assert not n.state['developments'] and not n.state['commitments'] and not n.state['premise']
 assert n.context(for_compiler=True)['threads']==[]  # the open question is not replayed
 assert n.state['threads']  # ...but is still tracked as the cue for the user's answer

def test_user_premise_and_choices_are_still_kept():
 n=memory()
 n.accepted('Imagine a story where we choose the north path.','A fine start.',True)
 assert n.state['premise'] and n.state['choices'] and not n.state['developments']

def test_story_card_replies_still_advance_story_memory():
 n=memory()
 n.accepted('Story card','The lantern in the north barn flickers out.',False,story=True)
 assert n.state['developments']==['The lantern in the north barn flickers out.']

def test_opt_in_keeps_companion_clips():
 n=memory(assistant_excerpts=True)
 n.accepted('How was your day?','The calves are plotting something.',True)
 assert n.state['developments']
