# SPDX-License-Identifier: AGPL-3.0-only
"""The standing system rules: one shared text, and the setting-change paragraph chosen from the snapshot."""
from companion_ai.context import SAFETY_INSTRUCTIONS, safety_instructions
from companion_ai.context_compiler import GROUNDING
from companion_ai.system_rules import CONTROL_OFF, CONTROL_ON, FACTS, SYSTEM_RULES, VOICE, settings_control_on, system_rules


def snap(enabled=True, revoked=False, fresh=True):
    return {'observation_fresh': fresh, 'state': {'details': {'ai_settings': {'enabled': enabled, 'revoked': revoked}}}}


def test_on_only_for_a_fresh_enabled_unrevoked_snapshot():
    assert settings_control_on(snap())
    assert not settings_control_on(snap(enabled=False))
    assert not settings_control_on(snap(revoked=True))  # Emergency stop
    assert not settings_control_on(snap(fresh=False))
    assert not settings_control_on({'observation_fresh': True, 'state': None})
    assert not settings_control_on({'observation_fresh': True, 'state': {'details': None}})
    assert not settings_control_on(None) and not settings_control_on({})


def test_exactly_one_control_paragraph_and_the_shared_text_always():
    on, off = system_rules(snap()), system_rules(snap(enabled=False))
    assert CONTROL_ON in on and CONTROL_OFF not in on
    assert CONTROL_OFF in off and CONTROL_ON not in off
    for text in (on, off):
        assert FACTS in text and VOICE in text
        assert 'You have no tools' in text and 'Never encourage pushing past safety limits' in text
        assert 'consent' in text and 'never read feelings or reasons into a number' in text
        assert "Don't quote or repeat the user's message" in text


def test_default_and_legacy_use_the_off_text():
    assert GROUNDING == SYSTEM_RULES == system_rules()
    assert CONTROL_OFF in SYSTEM_RULES
    assert SAFETY_INSTRUCTIONS.startswith(SYSTEM_RULES)
    assert CONTROL_ON in safety_instructions(snap()) and 'If stopped, acknowledge the stop.' in safety_instructions(snap())


def test_no_retired_jargon():
    for text in (system_rules(snap()), system_rules()):
        for phrase in ('original controls', 'operational claims', 'transport', 'No hardware-control tools exist'):
            assert phrase not in text
