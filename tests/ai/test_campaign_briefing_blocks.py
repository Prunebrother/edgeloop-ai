# SPDX-License-Identifier: AGPL-3.0-only
"""Multi-block briefings (H4, author 2026-11-20): one speaker, the first always shown, merged for the browser."""
import json
import pytest
from pydantic import ValidationError
from companion_ai.campaign import Narrative
from tests.ai.test_campaign_when import CID, NO, YES, block, narrative, service


def with_briefing(parts):
    text = narrative(); text['missions']['intake']['briefing'] = parts
    return text


def test_shown_blocks_merge_in_order_and_conditions_stay_private(tmp_path):
    parts = [block('Opening', expression='neutral', status='draft'), block('Analyst aside', when=YES), block('Volunteer aside', when=NO), block('Closing')]
    svc = service(tmp_path, text=with_briefing(parts), flags={'cover': 'analyst'})
    briefing = svc.mission_text(CID, 'intake')['briefing']
    assert briefing['lines'] == ['Opening', 'Analyst aside', 'Closing'] and briefing['expression'] == 'neutral'
    assert briefing['status'] == 'draft' and 'when' not in json.dumps(briefing)
    other = service(tmp_path / 'b', text=with_briefing(parts), flags={'cover': 'volunteer'})
    assert other.mission_text(CID, 'intake')['briefing']['lines'] == ['Opening', 'Volunteer aside', 'Closing']


def test_a_single_block_briefing_is_unchanged(tmp_path):
    svc = service(tmp_path, text=with_briefing(block('Only line')))
    assert svc.mission_text(CID, 'intake')['briefing']['lines'] == ['Only line']


def test_a_hidden_later_block_with_a_placeholder_status_does_not_mark_the_briefing(tmp_path):
    parts = [block('Opening', status='draft'), block('Hidden', when=NO, status='placeholder')]
    svc = service(tmp_path, text=with_briefing(parts), flags={'cover': 'analyst'})
    assert svc.mission_text(CID, 'intake')['briefing']['status'] == 'draft'


@pytest.mark.parametrize('parts, message', [
    ([], '1-4 blocks'),
    ([block('a')] * 5, '1-4 blocks'),
    ([block('a', when=YES), block('b')], 'first briefing block'),
    ([block('a'), {'speaker': 'evelyn', 'lines': ['b']}], 'one speaker'),
    ([{'speaker': 'nova', 'lines': ['x'] * 12}, {'speaker': 'nova', 'lines': ['y'] * 12}], 'at most 20 lines'),
])
def test_invalid_multi_block_briefings_are_rejected(parts, message):
    with pytest.raises(ValidationError, match=message):
        Narrative.model_validate(with_briefing(parts))
