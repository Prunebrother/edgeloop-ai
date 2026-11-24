# SPDX-License-Identifier: AGPL-3.0-only
from companion_ai.fidelity import mission_clock_values


def test_campaign_defined_stage_names_select_their_clock():
    clocks=[{'seconds':600,'names':['the interrogation stage','interrogation'],'rank':2},
            {'seconds':0,'names':['current stage'],'rank':2,'generic':True}]
    assert mission_clock_values('ten minutes in the interrogation stage',clocks)=={600}


def test_clause_without_any_clock_name_or_generic_word():
    assert mission_clock_values('ten minutes of active time',[
        {'seconds':600,'names':['interrogation'],'generic':True}]) is None


def test_campaign_name_can_identify_generic_time_left_clock():
    clocks=[{'seconds':600,'names':['interrogation'],'rank':2},
            {'seconds':120,'names':[],'generic':True,'remaining':True}]
    assert mission_clock_values('two minutes remaining in interrogation',clocks)=={120}


def test_stage_labels_are_not_generic_clock_words():
    for label in ['baseline','development','evaluation','comparison','encounter','delivery']:
        assert mission_clock_values(f'ten minutes in {label}',[
            {'seconds':600,'names':['interrogation'],'generic':True}]) is None
