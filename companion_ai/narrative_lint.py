# SPDX-License-Identifier: AGPL-3.0-only
"""Pure narrative checks over a loaded Book, character catalog and campaign -> ASSETS.json mappings.

No files, models or network are opened here. Callers load their own inputs. Review findings are
editorial prompts only: they never certify a claim or turn it into a release failure.
"""
import re
from typing import Literal, NamedTuple
from .campaign import check_story_slots, check_when, unknown_speakers
from .expressions import EXPRESSIONS

# Authored phrases, intentionally short and editable; these are review cues, not a control-policy parser.
REAL_CONTROL_CLAIMS = (
    "I'll turn it up",
    "I'm increasing",
    "I've set the",
    "I'll stop the device",
    "you can't stop",
    'you are not allowed to stop',
)


class Finding(NamedTuple):
    severity: Literal['error', 'warning', 'review']
    campaign: str
    location: str
    message: str


def blocks(narrative):
    """Stable locations for every block, including chapter scenes and the campaign close."""
    for mid, mission in narrative.missions.items():
        base = f'missions.{mid}'
        parts = mission.briefing_blocks()
        for i, block in enumerate(parts):
            yield base + ('.briefing' if len(parts) == 1 else f'.briefing[{i}]'), block
        yield base + '.completion', mission.completion
        for index, block in enumerate(mission.epilogue): yield f'{base}.epilogue[{index}]', block
        for key, block in mission.milestones.items(): yield f'{base}.milestones.{key}', block
    for cid, block in narrative.chapters.items(): yield f'chapters.{cid}', block
    for cid, intro in narrative.chapter_intros.items():
        for index, block in enumerate(intro): yield f'chapter_intros.{cid}[{index}]', block
    if narrative.campaign_complete: yield 'campaign_complete', narrative.campaign_complete


def lint(book, manifest, story_registry, release=False) -> list[Finding]:
    """manifest is the parsed character catalog; story_registry maps campaign ids to parsed registries.

    Book.load errors remain errors here: a rejected definition must never silently disappear from a release.
    All authored branches are checked, regardless of the current player's flags.
    """
    findings = [Finding('error', error['path'], 'campaign.json', error['detail']) for error in book.errors]
    unknown = unknown_speakers(book, manifest)
    def condition(cid, location, when, declared):
        try: check_when(when, declared)
        except ValueError as exc: findings.append(Finding('error', cid, location, str(exc)))
    def status(cid, location, value):
        if value in {'draft', 'placeholder'}:
            findings.append(Finding('error' if release else 'warning', cid, location, value + ' campaign narrative'))
    def claims(cid, location, text):
        normalized = text.replace('\u2019', "'")
        for phrase in REAL_CONTROL_CLAIMS:
            pattern = r'(?<!\w)' + re.escape(phrase).replace(r'\ ', r'\s+') + r'(?!\w)'
            for match in re.finditer(pattern, normalized, re.IGNORECASE):
                findings.append(Finding('review', cid, location,
                    f'Review real-control claim: "{phrase}" (column {match.start() + 1})'))
    for campaign in book.campaigns:
        declared = book.declared_flags(campaign)
        for mission in campaign.missions:
            base = f'missions.{mission.id}'
            condition(campaign.id, base + '.when', mission.when, declared)
            for objective in mission.objectives:
                condition(campaign.id, base + f'.objectives.{objective.id}.when', objective.when, declared)
    for cid, narrative in sorted(book.narratives.items()):
        campaign = book.campaign(cid)
        declared = book.declared_flags(campaign) if campaign else {}
        if not campaign: findings.append(Finding('error', cid, 'narrative.json', 'narrative has no campaign definition'))
        status(cid, 'status', narrative.status)
        for location, block in blocks(narrative):
            if block.speaker in unknown.get(cid, ()):
                findings.append(Finding('error', cid, location + '.speaker', 'unknown narrative speaker ' + block.speaker))
            if block.expression is not None and block.expression not in EXPRESSIONS:
                findings.append(Finding('error', cid, location + '.expression', 'unknown expression ' + block.expression))
            condition(cid, location + '.when', block.when, declared)
            for field, _ in block.slots():
                probe = block.model_copy(update={other: None for other in ('image', 'background') if other != field})
                try: check_story_slots(cid, [probe], story_registry)
                except ValueError as exc: findings.append(Finding('error', cid, location + '.' + field, str(exc)))
            status(cid, location + '.status', block.status)
            for index, line in enumerate(block.lines): claims(cid, f'{location}.lines[{index}]', line)
        for mid, mission in narrative.missions.items():
            base = f'missions.{mid}'
            for index, rule in enumerate(mission.story_so_far):
                condition(cid, f'{base}.story_so_far[{index}].when', rule.when, declared)
            for key, direction in mission.directions.items(): claims(cid, base + '.directions.' + key, direction)
    return findings
