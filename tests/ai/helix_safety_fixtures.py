# SPDX-License-Identifier: AGPL-3.0-only
"""Test-only Helix setup: prior campaign facts and every shipped stage boundary, with no hardware."""
from companion_ai.campaign import (Book, CampaignRecord, CampaignService, MissionRecord,
                                   Progress, RewardRecord, SCHEMA_VERSION)
from companion_ai.storage import SettingsStore
from tests.ai.test_campaign_chapter2 import tick

HID = 'rise_of_helix'
STAMP = '2026-11-20T00:00:00+00:00'


def complete(record, mission):
    record.missions[mission.id] = MissionRecord(completions=1, first_completed_at=STAMP, last_completed_at=STAMP)
    for reward in mission.rewards: record.rewards[reward.key] = RewardRecord(earned_at=STAMP, mission=mission.id)
    record.flags.update(mission.flags)
    # A deterministic, valid prior story path. No fixture assumes particular flag names or choice ids.
    for objective in mission.objectives:
        if objective.choice:
            option = objective.choice.options[0]
            record.choices.setdefault(mission.id, {})[objective.id] = option.id
            record.flags.update(option.sets)
    if mission.completion:
        route = mission.completion.any_of[0]
        record.routes[mission.id] = route.id; record.flags.update(route.sets)


def seed_progress(book, mission_id, campaign_id=HID):
    target = book.campaign(campaign_id); mission = target.mission(mission_id)
    progress = Progress(schema_version=SCHEMA_VERSION)
    visited = set()
    def prerequisite(cid):
        if cid in visited: return
        visited.add(cid); source = book.campaign(cid)
        for parent in source.requires_campaigns: prerequisite(parent)
        record = progress.campaigns.setdefault(cid, CampaignRecord())
        for previous in sorted(source.missions, key=lambda m: m.order): complete(record, previous)
    for parent in target.requires_campaigns: prerequisite(parent)
    record = progress.campaigns.setdefault(campaign_id, CampaignRecord())
    for previous in sorted(target.missions, key=lambda m: m.order):
        if previous.order >= mission.order: break
        complete(record, previous)
    return progress


def service_for(tmp_path, mission_id, book=None):
    book = book or Book.load()
    svc = CampaignService(SettingsStore(tmp_path), book=book, identity=lambda model: model)
    svc.progress = seed_progress(book, mission_id)
    svc._settle_completion(svc.progress); svc._save(svc.progress)
    svc.start(HID, mission_id)
    return svc


def stage_for(directive, mission):
    return next((stage for objective in mission.objectives for stage in objective.stages
                 if f'{objective.id}:{stage.id}' == directive['key']), None)


def reports_through_stages(svc, sid='helix-safety'):
    """5-second observations respect MAX_STEP_SECONDS and visit every authored stage, then two minutes beyond."""
    mission = svc.attempt.mission
    total = sum(stage.seconds for objective in mission.objectives for stage in objective.stages)
    horizon = total + 120 + 15 * sum(len(o.stages) for o in mission.objectives) if total else 180
    for seconds in range(0, horizon + 1, 5):
        stages = [svc.attempt.current_stage(o) for o in svc.attempt.objectives if o.stages]
        current = next((stage for stage in stages if stage), None)
        intensity = current.intensity if current and current.intensity is not None and seconds else 60
        # Floor stages intentionally run below the floor: player reductions never stop their clock.
        report = tick(sid, seconds, intensity=intensity)
        report['active_mode'] = mission.session.active_mode if mission.session and mission.session.active_mode else 'classic'
        yield report
