# SPDX-License-Identifier: AGPL-3.0-only
"""Skip to Rise of Helix: a later campaign can be opened early without touching the campaign it requires."""
import json
import pytest
from ai_observer.protocol import CampaignCommand
from companion_ai.campaign import CampaignRecord
from tests.ai.test_campaign import CID, service
from tests.ai.test_campaign_chapter2 import seed
from tests.ai.test_campaign_helix_shell import HID, MISSIONS, helix


def test_unlock_early_opens_only_helix_and_keeps_asterion_progress(tmp_path):
    svc = service(tmp_path)
    before = svc.state()['campaigns'][0]
    assert helix(svc)['can_unlock_early'] and not helix(svc)['unlocked_early']
    svc.unlock_early(HID)
    campaign = helix(svc)
    assert campaign['available'] and campaign['unlocked_early'] and not campaign['can_unlock_early']
    assert campaign['locked_reason'] is None and campaign['requires'][0]['completed'] is False
    assert [m['state'] for m in campaign['missions']] == ['available', *['locked'] * 4]
    after = svc.state()['campaigns'][0]
    assert after['id'] == CID and after['progress'] == before['progress'] and not after['completed']
    svc.mission_text(HID, MISSIONS[0])
    svc.start(HID, MISSIONS[0])
    # Saved: a new service on the same data directory still sees Helix open.
    assert helix(service(tmp_path))['available']


def test_unlock_early_refuses_open_unknown_and_starting_campaigns(tmp_path):
    svc = service(tmp_path)
    with pytest.raises(ValueError, match='Unknown campaign'): svc.unlock_early('nope')
    with pytest.raises(ValueError, match='already open'): svc.unlock_early(CID)
    svc.unlock_early(HID)
    with pytest.raises(ValueError, match='already open'): svc.unlock_early(HID)


def test_finishing_asterion_after_an_early_unlock_drops_the_note(tmp_path):
    svc = service(tmp_path)
    svc.unlock_early(HID)
    progress = svc.progress.model_copy(deep=True)
    progress.campaigns.setdefault(CID, CampaignRecord()).completed_at = '2026-11-24T00:00:00+00:00'
    svc._save(progress)
    campaign = helix(svc)
    assert campaign['available'] and campaign['requires'][0]['completed']
    assert not campaign['unlocked_early'] and not campaign['can_unlock_early']


def test_a_normally_opened_helix_offers_no_skip(tmp_path):
    seed(tmp_path, None)
    campaign = helix(service(tmp_path))
    assert campaign['available'] and not campaign['can_unlock_early'] and not campaign['unlocked_early']


@pytest.mark.parametrize('raw,ok', [({'campaign_id': HID}, True), ({}, False), ({'campaign_id': HID, 'mission_id': 'h1_entry_protocol'}, False),
                                    ({'campaign_id': HID, 'chapter_id': 'undercover'}, False)])
def test_unlock_early_command_shape(raw, ok):
    try: CampaignCommand.model_validate({'version': 1, 'type': 'campaign', 'action': 'unlock_early'} | raw); valid = True
    except ValueError: valid = False
    assert valid == ok
