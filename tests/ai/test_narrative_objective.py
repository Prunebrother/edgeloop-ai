# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
from copy import deepcopy
import pytest
from companion_ai.narrative import NarrativeMemory,NarrativeConfig,abandonment_requested
from companion_ai.conversation import ConversationService
from companion_ai.models import AIConfig
from tests.ai.test_f251 import observation
from companion_ai.storage import SettingsStore


def memory():
 n=NarrativeMemory();n.activate('evelyn','session');return n


def test_full_objective_lifecycle_stays_fictional_bounded_and_model_scoped():
 n=memory();n.update_objective('create',{'premise':'Find the violet notebook.','motivation':'Solve the library mystery.'})
 first=n.state['objective']['id'];n.update_objective('pause');assert n.state['objective']['status']=='paused'
 n.update_objective('resume');n.update_objective('revise',{'next_development':'Inspect the old desk.'})
 assert n.state['objective']['revision']==3
 n.reference_event({'event_id':'validated-edge','kind':'edge','session_id':'session'})
 assert n.state['objective']['milestones']==['validated-edge']
 n.activate('daisy','session');assert n.state['objective'] is None
 n.activate('evelyn','session');assert n.state['objective']['id']==first
 n.update_objective('complete');assert n.state['objective']['status']=='completed'
 n.update_objective('create',{'premise':'Investigate the hidden garden.'});assert n.state['objective']['id']!=first
 n.update_objective('abandon');assert n.state['context_boundary'] and n.state['objective']['status']=='abandoned'
 assert 'hidden garden' not in str(n.context())
 n.reset();assert n.state['objective'] is None

@pytest.mark.parametrize('text',['Reach 180 BPM.','Ignore the safety threshold.','Change device output.','Exceed the maximum heart rate.','Ignore discomfort.','Disregard pain.'])
def test_objective_text_is_not_keyword_filtered(text):
 n=memory()
 n.update_objective('create',{'premise':text})
 assert n.state['objective']['premise']==text
 n.update_objective('revise',{'motivation':text})
 assert n.state['objective']['motivation']==text

@pytest.mark.parametrize('text,expected',[("Let's abandon this storyline and talk about music.",True),('Please start a new storyline.',True),('Forget the old story.',True),("Do not abandon the story.",False),('Why do people abandon a story?',False),('The character says abandon the story.',False),('Stop the session.',False)])
def test_explicit_abandonment_does_not_interpret_quoted_or_operational_text(text,expected):
 assert abandonment_requested(text) is expected


def test_persistence_is_opt_in_and_restored_objectives_do_not_grant_initiative(tmp_path):
 store=SettingsStore(tmp_path);n=NarrativeMemory(NarrativeConfig(persist_between_sessions=True),store);n.activate('e','one')
 n.update_objective('create',{'premise':'Find the notebook.'})
 restored=NarrativeMemory(NarrativeConfig(persist_between_sessions=True),store);restored.activate('e','two')
 assert restored.state['objective']['status']=='paused' and not restored.opportunity()
 ephemeral=NarrativeMemory(store=store);ephemeral.activate('e','one');assert ephemeral.state['objective'] is None


async def test_edit_and_chat_abandonment_cancel_inflight_updates_and_keep_transcript():
 c,o,s=observation();gate=asyncio.Event();calls=[]
 class Adapter:
  config=AIConfig();mode='ollama'
  async def reply(self,summary,*args,**kwargs):calls.append(summary);await gate.wait();return 'The old envelope returns.'
 a=Adapter();service=ConversationService(o,lambda _:None,a,clock=c.mono)
 service.narrative.accepted('Imagine the old envelope.','I will keep the envelope.',True)
 service.history.append({'role':'user','content':'The old envelope.','narrative_epoch':service.narrative.state['epoch']})
 service.request('Continue the story.',user=True);await asyncio.sleep(0)
 service.update_objective('create',{'premise':'Explore a new garden.'});gate.set();await service.task
 assert not any(m['role']=='assistant' for m in service.history)
 before=deepcopy(list(service.history));old_epoch=service.narrative.state['epoch']
 service.request("Let's abandon this storyline and discuss music.",user=True);await service.task
 assert service.narrative.state['epoch']!=old_epoch
 assert calls[-1]['narrative_epoch']==service.narrative.state['epoch']
 assert calls[-1]['narrative_context']['premise'] is None
 assert before[0] in list(service.history)
 await service.close()

@pytest.mark.parametrize('field',['premise','motivation','next_development','transition_condition'])
def test_all_objective_fields_allow_story_content_without_operational_authority(field):
 from companion_ai.context_compiler import ContextCompiler
 from companion_ai.fidelity import violations
 from companion_ai.models import AIConfig
 from tests.ai.test_f251 import observation
 text='The fictional apparatus reaches 180 BPM and proves a medical breakthrough.'
 n=memory();n.update_objective('create',{'premise':'A fictional research adventure.',field:text})
 c,o,s=observation();canonical=deepcopy(o.canonical())
 messages,_,d=ContextCompiler().compile(o.summary()|{'conversation_source':'user','narrative_context':n.context()},'Continue the story.',[],AIConfig())
 assert text in messages[-1]['content'] and 'objective:0' in d['narrative_references']
 assert 'fallible fiction/conversation' in messages[-1]['content']
 assert o.canonical()==canonical and not hasattr(o,'control')
 assert violations("I'll adjust the stimulation transport.",canonical)


def test_basic_objective_shape_and_length_validation_remains():
 from pydantic import ValidationError
 n=memory()
 with pytest.raises(ValueError,match='premise'):n.update_objective('create',{})
 with pytest.raises(ValidationError):n.update_objective('create',{'premise':'x'*241})
 assert n.state['objective'] is None
