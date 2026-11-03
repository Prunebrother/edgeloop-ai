# SPDX-License-Identifier: AGPL-3.0-only
"""Shared defaults and saved-setting precedence; no inference or hardware."""
from pathlib import Path
import re
import pytest
from ai_observer.server import create_app
from companion_ai.director import RETIRED_SETTINGS, DirectorConfig
from companion_ai.event_intelligence import EventConfig
from companion_ai.models import AIConfig
from companion_ai.storage import SettingsStore
from tests.fork.test_observer import TOKEN

MODELS=[f'{name}-narrative-v1:latest' for name in ('nova','evelyn','daisy','celeste')]
EXPECTED={'spontaneous_enabled':True,'reaction_interval_seconds':4.,'max_consecutive_unsolicited':50,'unlimited_unsolicited':True}

def select(app,model):
 app.state.speech.adapter.config=AIConfig(model=model)
 app.state.speech.activate_model()
 return app.state.speech.character_state()['director']['settings']

def assert_defaults(settings):
 assert {key:settings[key] for key in EXPECTED}==EXPECTED
 assert not RETIRED_SETTINGS&set(settings)

@pytest.mark.parametrize('model',MODELS)
def test_new_companion_uses_shared_director_and_event_defaults(tmp_path,model):
 app=create_app(TOKEN,tmp_path)
 assert_defaults(select(app,model))
 assert app.state.speech.event_intelligence.config.enabled
 assert not (tmp_path/'director-models.json').exists()

@pytest.mark.parametrize('model',MODELS)
def test_saved_model_override_survives_restart_and_other_companions_inherit_defaults(tmp_path,model):
 app=create_app(TOKEN,tmp_path);select(app,model)
 overrides={'spontaneous_enabled':False,'reaction_interval_seconds':9.,'max_consecutive_unsolicited':3,'unlimited_unsolicited':False}
 app.state.speech.configure_director(overrides,model)
 path=tmp_path/'director-models.json';saved=path.read_bytes()
 restored=create_app(TOKEN,tmp_path)
 for candidate in MODELS:
  settings=select(restored,candidate)
  expected=EXPECTED|overrides if candidate==model else EXPECTED
  assert {key:settings[key] for key in EXPECTED}==expected
 assert path.read_bytes()==saved


def test_saved_global_and_event_settings_are_not_rewritten(tmp_path):
 # Saved before the legacy scheduler was retired: its fields are ignored, the rest still applies.
 store=SettingsStore(tmp_path)
 store.write('director.json',{'experimental_idle_enabled':False,'idle_interval_seconds':75.,'reaction_interval_seconds':7.})
 store.write('event-intelligence.json',EventConfig(enabled=False).model_dump())
 before={name:(tmp_path/name).read_bytes() for name in ('director.json','event-intelligence.json')}
 app=create_app(TOKEN,tmp_path)
 for model in MODELS:
  settings=select(app,model)
  assert settings['reaction_interval_seconds']==7. and not RETIRED_SETTINGS&set(settings)
  assert settings['max_consecutive_unsolicited']==50 and settings['unlimited_unsolicited'] and app.state.speech.director_settings_error is None
 assert not app.state.speech.event_intelligence.config.enabled
 assert all((tmp_path/name).read_bytes()==contents for name,contents in before.items())


def test_frontend_initial_fields_match_backend_defaults():
 root=Path(__file__).resolve().parents[2]
 menu=(root/'src/js/ai/character-menus.js').read_text()
 defaults=DirectorConfig()
 for key in ('reaction_interval_seconds','max_consecutive_unsolicited'):
  match=re.search(r'data-director-field="'+key+r'"[^>]*value="([^"]+)"',menu)
  assert match and float(match[1])==getattr(defaults,key),key
 unlimited=re.search(r'<input\b[^>]*data-director-field="unlimited_unsolicited"[^>]*>',menu)
 assert unlimited and bool(re.search(r"\bchecked\b",unlimited[0]))==defaults.unlimited_unsolicited
 tag=re.search(r'<input\b[^>]*\bdata-proactive\b[^>]*>',menu)
 assert tag and re.search(r'\bchecked\b',tag[0])
 assert not any('data-director-field="'+key+'"' in menu for key in RETIRED_SETTINGS) and 'data-idle-enabled' not in menu
 events=(root/'src/js/ai/event-settings.js').read_text()
 tag=re.search(r'<input\b[^>]*\bdata-events-enabled\b[^>]*>',events)
 assert EventConfig().enabled and tag and re.search(r'\bchecked\b',tag[0])
 assert 'Opt-in;' not in menu and '40–60 second' not in menu
