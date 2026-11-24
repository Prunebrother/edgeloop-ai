# SPDX-License-Identifier: AGPL-3.0-only
"""Companion readiness across the shipped manifest, campaign book and browser fixtures.

PNG/WebM signatures and serving boundaries already have asset tests. Here their
public-file helper checks existence while the assertions enforce complete rosters.
"""
import re

import pytest

from companion_ai.campaign import Book
from companion_ai.expressions import EXPRESSIONS
from tests.ai.helix_safety_fixtures import HID
from tests.fork.character_model_fixtures import helix_extra_models, installed_model_names
from tests.fork.test_character_assets import ROOT, static
from tests.fork.test_placeholder_companions import IDS, catalog

CATALOG = catalog()
COMPANIONS = {cid: character for cid, character in CATALOG['characters'].items()
              if character.get('role') != 'story'}
BOOK = Book.load()


def model_tags(cid):
    return {tag for tag, owner in CATALOG['models'].items() if owner == cid}


def campaign_companions(campaign):
    return (set(campaign.starting_companions) | {m.companion for m in campaign.missions}
            | {r.id for m in campaign.missions for r in m.rewards if r.type == 'unlock_companion'})


# The manifest also maps legacy local tags (evelyn-v11, daisy-world, ...) so the app recognises models a
# player built before the narrative releases; those never had a Modelfile in the repo. Shipped tags do.
SHIPPED = re.compile(r'-(narrative|placeholder)(-|:)')


@pytest.mark.parametrize('tag,cid', sorted((t, c) for t, c in CATALOG['models'].items() if SHIPPED.search(t)),
                         ids=sorted(t for t in CATALOG['models'] if SHIPPED.search(t)))
def test_manifest_models_have_modelfiles_with_a_parent(tag, cid):
    assert cid in COMPANIONS, f'{tag}: unknown or story-only companion {cid}'
    path = ROOT / 'characters/models' / tag.removesuffix(':latest') / 'Modelfile'
    if not path.is_file():
        pytest.skip(f'DEFECT: manifest model {tag} has no {path.relative_to(ROOT)}')
    assert re.search(r'^\s*FROM[^\S\n]+[^\s#][^\n]*', path.read_text(), re.MULTILINE), tag


@pytest.mark.parametrize('cid', sorted(cid for cid, character in COMPANIONS.items()
                                      if character.get('status') != 'placeholder'))
def test_full_companions_have_matching_complete_art_and_real_models(cid):
    character = COMPANIONS[cid]
    assert set(CATALOG['expressions']) == set(EXPRESSIONS)
    assert set(character['expressions']) == set(character.get('animations', {})) == set(EXPRESSIONS), cid
    portraits = set(character['expressions'].values())
    clips = {formats['webm'] for formats in character['animations'].values()}
    assert len(portraits) == len(clips) == len(EXPRESSIONS), cid
    for sources, suffix in ((portraits, '.png'), (clips, '.webm')):
        for source in sources:
            assert source.endswith(suffix) and static.public_file(source), (cid, source)
    tags = model_tags(cid)
    assert tags and all('placeholder' not in tag.casefold() for tag in tags), (cid, tags)


def test_every_placeholder_companion_is_covered_by_the_placeholder_contract():
    # That contract already asserts the display-name suffix; story portraits are not companions.
    placeholders = {cid for cid, character in COMPANIONS.items() if character.get('status') == 'placeholder'}
    assert placeholders <= set(IDS), f'Add placeholder contract coverage for {sorted(placeholders - set(IDS))}'


@pytest.mark.parametrize('campaign,cid', [
    pytest.param(campaign, cid, id=f'{campaign.id}-{cid}')
    for campaign in BOOK.campaigns for cid in sorted(campaign_companions(campaign))
])
def test_campaign_companions_are_installable_in_their_browser_fixture(campaign, cid):
    assert not BOOK.errors, BOOK.errors  # Book.load omits broken campaigns; do not silently lose coverage.
    installed = set(installed_model_names(helix_extra_models() if campaign.id == HID else ''))
    assert cid in COMPANIONS, f'{campaign.id}: unknown or story-only companion {cid}'
    tags = model_tags(cid)
    assert tags, f'{campaign.id}: {cid} has no manifest model tags'
    # The app needs one installed model per companion, not every tag the manifest maps to her.
    if not tags & installed:
        pytest.skip(f'DEFECT: {campaign.id} browser fixture has none of {cid} models {sorted(tags)}')


def test_helix_narrative_uses_the_canonical_company_name():
    assert not BOOK.errors, BOOK.errors
    assert HID in BOOK.narratives
    # Serialize the whole narrative, including directions, context and conditional recaps,
    # rather than only the currently visible dialogue blocks. Modelfiles are out of scope.
    narrative = BOOK.narratives[HID].model_dump_json().casefold()
    for obsolete in ('Helix Biotechnology', 'Helix Corporation'):
        assert obsolete.casefold() not in narrative, f'Use Helix Dynamics instead of {obsolete}'
