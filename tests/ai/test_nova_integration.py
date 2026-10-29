# SPDX-License-Identifier: AGPL-3.0-only
"""Nova's real source/asset contract; inference uses isolated HTTP mocks only."""
import json
import pytest
from pathlib import Path
import httpx
from companion_ai.event_intelligence import EventConfig
from companion_ai.llm import OllamaProvider,LLMRequest,ChatMessage,collect_reply
from companion_ai.models import AIConfig
from companion_ai.narrative import NarrativeMemory,NarrativeConfig
from companion_ai.storage import SettingsStore
from tests.fork.test_character_assets import static

ROOT=Path(__file__).resolve().parents[2]
MODEL='nova-narrative-v1:latest'

def test_nova_assets_public_only_when_referenced_and_all_expressions_supplied():
 if not (ROOT/'Character_Art').exists():pytest.skip('Optional character artwork excluded pending redistribution permission')
 manifest=json.loads((ROOT/'src/assets/characters/manifest.json').read_text());nova=manifest['characters']['nova']
 assert manifest['models'][MODEL]=='nova' and nova['name']=='Nova'
 assert nova['expressions']['excited']=='/Character_Art/Nova/expressions/nova_excited.png'
 assert all(nova['expressions'].values())
 for expression,asset in nova['expressions'].items():
  if not asset:continue
  file=static.public_file(asset)
  assert file and file.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
 assert static.public_file('/Character_Art/Nova/nova_reference.png') is None
 assert static.public_file('/characters/models/nova-narrative-v1/Modelfile') is None
 assert static.public_file('/Character_Art/Nova/expressions/../../../../.git/config') is None


def test_nova_preferences_migrate_without_changing_older_character_settings():
 config=EventConfig().model_dump();config['preferences'].pop('nova');config['preferences']['daisy']['session']=2
 restored=EventConfig.model_validate(config)
 assert restored.preferences['nova']=={'physiology':1,'session':1,'configuration':1,'story':1}
 restored.preferences['nova']['session']=0
 assert restored.relevance(MODEL,'session')==0
 assert restored.relevance('daisy-narrative-v1:latest','session')==2
 assert restored.relevance('nova-unknown:latest','session')==1
 assert EventConfig.model_validate(restored.model_dump()).preferences==restored.preferences


def test_nova_story_isolation_reset_and_persistence(tmp_path):
 store=SettingsStore(tmp_path);config=NarrativeConfig(persist_between_sessions=True)
 n=NarrativeMemory(config,store);n.activate('evelyn-narrative-v1:latest','s');n.accepted('The secret phrase is amber lantern.','Understood.',True)
 n.activate(MODEL,'s');assert not n.state['facts'];n.accepted('My preferred constellation is Lyra.','I enjoy astronomy.',True)
 original=[(r['id'],r['speaker'],r['text']) for r in n.state['facts']]
 restored=NarrativeMemory(config,store);restored.activate(MODEL,'s2');assert [(r['id'],r['speaker'],r['text']) for r in restored.state['facts']]==original
 restored.reset();assert not restored.state['facts'];restored.activate('evelyn-narrative-v1:latest','s2');assert any('amber lantern' in r['text'] for r in restored.state['facts'])


async def test_nova_native_persona_is_verbatim_and_thinking_stays_off():
 source=(ROOT/'characters/models/nova-narrative-v1/Modelfile').read_text();native=source.split('SYSTEM """',1)[1].rsplit('"""',1)[0].strip();wire=[]
 def runtime(request):
  if request.url.path=='/api/show':return httpx.Response(200,json={'system':native,'capabilities':['completion','thinking'],'thinking':{'values':[True,False]}})
  assert request.url.path=='/api/chat';payload=json.loads(request.content);wire.append(payload)
  return httpx.Response(200,text=json.dumps({'message':{'content':'[[expression:playful]] Hello.'},'done':True})+'\n')
 provider=OllamaProvider(MODEL,transport=httpx.MockTransport(runtime));config=AIConfig(model=MODEL)
 await collect_reply(provider,LLMRequest(config,(ChatMessage(role='system',content='Read-only runtime grounding.'),ChatMessage(role='user',content='Hello.'))))
 assert len(wire)==1 and wire[0]['think'] is False
 assert wire[0]['messages'][0]['content']==native+'\n\nRead-only runtime grounding.'
 assert 'ASTERION-SYN/07' in native and 'You chose the name Nova yourself.' in native


def test_nova_journal_history_is_named_explicitly_and_respects_privacy(tmp_path):
 from companion_ai.session_journal import SessionJournal,companion
 journal=SessionJournal(SettingsStore(tmp_path));journal.command('configure',ai_access=True)
 assert companion(MODEL)=='nova'
 for identity,scope in [('nova',MODEL),('evelyn','evelyn-narrative-v1:latest')]:
  journal.data['records'].append({'session_id':identity+'-synthetic','companions':[{'companion':identity,'model_scope':scope,'model':scope}],'setting_changes':[],'setting_changes_truncated':False,'active_running_seconds':120})
 assert journal.retrieve('How long was my previous session?',MODEL)[0]['session_id']=='nova-synthetic'
 assert journal.retrieve('How long was my previous session with Nova?','evelyn-narrative-v1:latest')[0]['session_id']=='nova-synthetic'
 assert journal.retrieve('How long was my previous session?','evelyn-narrative-v1:latest')[0]['session_id']=='evelyn-synthetic'
 journal.command('configure',ai_access=False)
 assert not journal.retrieve('How long was my previous session with Nova?','evelyn-narrative-v1:latest')
