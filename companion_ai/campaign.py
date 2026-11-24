# SPDX-License-Identifier: AGPL-3.0-only
"""Campaign progression: missions, verified objectives, rewards and saved progress.

The campaign requests scripted intensity only through the existing engine-side settings gate. It reads
the observer's canonical report after acceptance
(the same evidence the Session Journal uses) and decides, deterministically, whether a mission
objective is met. Model output is never evidence: nothing here reads chat or generated text.

Definitions live in config/campaigns/<campaign id>/campaign.json (rules) and narrative.json
(the scripted character lines). Progress is one JSON file in the observer's data directory.
See docs/fork/campaign/README.md.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import time
import unicodedata
from typing import Annotated, Literal
from pydantic import ConfigDict, Discriminator, Field, Tag, ValidationError, model_validator, model_serializer
from .expressions import EXPRESSIONS
from .models import StrictModel

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_DIR = ROOT / 'config/campaigns'
PROGRESS_FILE = 'campaign-progress.json'
SCHEMA_VERSION = 4
Identifier = Field(min_length=1, max_length=64, pattern=r'^[a-z0-9][a-z0-9_.-]*$')
Text = Field(min_length=1, max_length=600)
COUNTED = {'edge_count', 'orgasm_count'}
ObjectiveType = Literal['hr_monitor_connected', 'toy_connected', 'session_started', 'edge_count', 'orgasm_count',
                        'calibration_completed', 'calibration_saved', 'style_stages', 'stage_sequence', 'puzzle_solved', 'choice']
# The engine's play styles (snapshot `experience`), the configurations a style_stages objective can tell apart.
PLAY_STYLES = ('classic', 'finisher', 'milker', 'shortener', 'headplay', 'ultimate', 'bratty', 'ruin')
StyleName = Literal['classic', 'finisher', 'milker', 'shortener', 'headplay', 'ultimate', 'bratty', 'ruin']
# As the play-style cards in EdgeLoop name them.
# Words naming a mission's whole timed objective, as opposed to one of its stages.
DURATION_TOTAL_WORDS = ('assessment', 'evaluation', 'mission', 'encounter', 'calibration')
STYLE_WORDS = {'classic': 'Simple Ramp', 'finisher': 'Finisher', 'milker': 'Prostate Milker', 'shortener': 'Glans Protector',
               'headplay': 'Head Play', 'ultimate': 'Ultimate Milker', 'bratty': 'Bratty Tease', 'ruin': 'Ruin & Leak'}
# At most this many seconds of running time are credited between two observations (they arrive about every second);
# a longer gap, such as a reconnect, is not counted, since what happened in it is unknown.
MAX_STEP_SECONDS = 5
# Reward types with an application mechanism today: companion unlocks (campaign roster), milestones and
# campaign completion. The others are recorded as earned so a later feature can honour them.
RewardType = Literal['unlock_companion', 'milestone', 'chapter_complete', 'campaign_complete', 'story_branch', 'collectible', 'achievement']
# Rewards that mark completion: they follow from the completed missions and current definitions (recomputed on load).
COMPLETION_REWARDS = {'chapter_complete', 'campaign_complete'}
EngineMode = Literal['classic', 'finisher', 'milker', 'shortener', 'headplay', 'ultimate', 'bratty', 'ruin', 'script',
                     'survival', 'oracle', 'edgetrain', 'calibrate']
SettingName = Literal['play_style', 'game', 'endgame', 'orgasm', 'intensity', 'pause', 'stop']
LIVE = {'RUNNING', 'PAUSED', 'RAMPDOWN'}
MISSING = object()
# Objectives that are story moments when reached; the setup items before a session are not.
GOAL_TYPES = {'edge_count', 'orgasm_count', 'calibration_completed', 'calibration_saved', 'style_stages', 'stage_sequence', 'puzzle_solved', 'choice'}
COMPANION_ALIASES = {'evelyn': ('Voss',), 'daisy': ('Harper', 'Cloverfield'), 'celeste': ('IRRA',), 'mira': (), 'vex9': ('VEX-9', 'VEX')}
MODE_WORDS = {'calibrate': 'Calibration', 'edgetrain': 'Edge Training'}


def now_iso(clock=time.time):
    return datetime.fromtimestamp(clock(), timezone.utc).isoformat(timespec='seconds')


class Stage(StrictModel):
    """One step of a stage_sequence: active running time, either at a fixed engine intensity (snapshot %, 50-150,
    time waits at any other level) or at any intensity. `raise_to`: in a directed mission the companion raises the
    intensity to at least this level when the stage begins; the player may lower it again at no cost.
    `set_to`: the campaign itself sends the change once at the stage start, through the gate (no companion step):
    with `intensity`, that fixed level; with `raise_to`, the floor, and only when the level is below it."""
    id: str = Identifier
    label: str = Field(min_length=1, max_length=80)
    seconds: int = Field(ge=10, le=7200)
    intensity: int | None = Field(default=None, ge=50, le=150)
    raise_to: int | None = Field(default=None, ge=50, le=150)
    set_to: bool = False

    @model_validator(mode='after')
    def one_rule(self):
        if self.set_to and (self.intensity is None) == (self.raise_to is None): raise ValueError('set_to needs a fixed intensity or a raise_to floor')
        if self.intensity is not None and self.raise_to is not None: raise ValueError('a stage has a fixed intensity or a raise_to, not both')
        return self


class PuzzleOption(StrictModel):
    id: str = Identifier
    label: str = Field(min_length=1, max_length=120)


def normalize_code(text):
    """Comparison only; submitted text and the answer never enter a public view."""
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def code_controls(text):
    return any(unicodedata.category(c) in {'Cc', 'Cf', 'Cs'} for c in text)


class PuzzleClue(StrictModel):
    text: str = Field(min_length=1, max_length=600)
    reveal_at: str | None = Field(default=None, min_length=1, max_length=129)


class Puzzle(StrictModel):
    """Choice or code puzzle. Only the campaign checks its secret answer."""
    kind: Literal['choice', 'code'] = 'choice'
    title: str = Field(min_length=1, max_length=80)
    clues: list[str | PuzzleClue] = Field(min_length=1, max_length=8)
    question: str = Field(min_length=1, max_length=300)
    options: list[PuzzleOption] | None = Field(default=None, min_length=2, max_length=6)
    answer: str | None = Field(default=None, min_length=1, max_length=64, pattern=r'^[a-z0-9][a-z0-9_.-]*$')
    answer_code: str | None = Field(default=None, min_length=1, max_length=40)
    max_length: int = Field(default=40, ge=1, le=40)
    hint: str = Field(min_length=1, max_length=300)

    @model_validator(mode='before')
    @classmethod
    def kind_fields(cls, value):
        if isinstance(value, dict):
            forbidden = {'options', 'answer'} if value.get('kind') == 'code' else {'answer_code', 'max_length'}
            if forbidden & value.keys(): raise ValueError('puzzle fields must match its kind')
        return value

    @model_serializer(mode='wrap')
    def kind_data(self, handler):
        data = handler(self)
        for key in ('options', 'answer') if self.kind == 'code' else ('answer_code', 'max_length'): data.pop(key, None)
        return data

    @model_validator(mode='after')
    def answerable(self):
        if self.kind == 'code':
            if self.options is not None or self.answer is not None or self.answer_code is None:
                raise ValueError('code puzzles require answer_code and no options or answer')
            if code_controls(self.answer_code) or not normalize_code(self.answer_code) or len(normalize_code(self.answer_code)) > self.max_length:
                raise ValueError('code puzzle answer must be nonempty, control-free and fit max_length after normalisation')
        else:
            if self.answer_code is not None or self.max_length != 40 or self.options is None or self.answer is None:
                raise ValueError('choice puzzles require options and answer, without code fields')
            ids = [o.id for o in self.options]
            if len(ids) != len(set(ids)) or self.answer not in ids: raise ValueError('the answer must be one of the unique option ids')
        return self


class ChoiceOption(StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r'^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$')
    label: str = Field(min_length=1, max_length=120)
    sets: dict[str, str] = Field(default_factory=dict, max_length=12)

    @model_validator(mode='after')
    def own_flags(self):
        if not self.label.strip(): raise ValueError('choice labels must not be blank')
        for key, value in self.sets.items():
            if not FLAG_NAME.fullmatch(key) or not FLAG_VALUE.fullmatch(value): raise ValueError('choice sets use own snake_case flags and values')
        return self


class Choice(StrictModel):
    prompt: str = Field(min_length=1, max_length=300)
    options: list[ChoiceOption] = Field(min_length=2, max_length=4)

    @model_validator(mode='after')
    def unique_options(self):
        if not self.prompt.strip(): raise ValueError('choice prompt must not be blank')
        if len({o.id for o in self.options}) != len(self.options): raise ValueError('choice option ids must be unique')
        return self


class Objective(StrictModel):
    """Composable objectives, all decided from the engine's canonical report:
    - edge_count / orgasm_count: `count` events in the mission session, optional `milestones` thresholds,
      optional `after` (count only once that objective is met).
    - style_stages: `count` different play styles, each run for `seconds` of active time with no game on.
    - stage_sequence: `stages` in order, each `seconds` of active time at its intensity (within `tolerance`).
    - puzzle_solved: the `puzzle` answered correctly in the mission panel, in order, during the mission session.
      Solved puzzles are saved, so they survive the session ending, leaving the mission screen and a restart.
    - `within_seconds` on a count: only events within that much active running time of the mission-session start
      count (pauses freeze it); after it runs out the try is over and the next session starts a fresh clock.
      `warnings`: remaining-time marks (seconds) that get a scripted line."""
    id: str = Identifier
    type: ObjectiveType
    label: str = Text
    count: int | None = Field(default=None, ge=1, le=1000)
    milestones: list[int] = Field(default_factory=list, max_length=10)
    after: str | None = Field(default=None, max_length=64)
    seconds: int | None = Field(default=None, ge=10, le=7200)
    styles: list[StyleName] = Field(default_factory=lambda: list(PLAY_STYLES), min_length=1, max_length=8)
    stages: list[Stage] = Field(default_factory=list, max_length=8)
    tolerance: int = Field(default=2, ge=0, le=10)
    within_seconds: int | None = Field(default=None, ge=10, le=7200)
    warnings: list[int] = Field(default_factory=list, max_length=6)
    puzzle: Puzzle | None = None
    choice: Choice | None = None
    after_stage: str | None = Field(default=None, max_length=129)
    optional: bool = Field(default=False, exclude_if=lambda value: not value)
    when: 'When | None' = None

    @model_validator(mode='after')
    def counted(self):
        if self.when and not self.optional: raise ValueError('when is allowed only on optional objectives')
        if self.optional and self.type in {'hr_monitor_connected', 'toy_connected', 'session_started'}:
            raise ValueError('setup objectives cannot be optional')
        if (self.type in COUNTED | {'style_stages'}) != (self.count is not None):
            raise ValueError('count is required for edge_count, orgasm_count and style_stages, and not allowed otherwise')
        if (self.type == 'style_stages') != (self.seconds is not None):
            raise ValueError('seconds is required for style_stages and not allowed otherwise')
        if (self.type == 'stage_sequence') != bool(self.stages):
            raise ValueError('stages are required for stage_sequence and not allowed otherwise')
        if self.milestones and (self.type not in COUNTED or any(not 0 < n < self.count for n in self.milestones) or sorted(set(self.milestones)) != self.milestones):
            raise ValueError('milestones are increasing counts below the target, on edge_count/orgasm_count only')
        if self.after and self.type not in COUNTED: raise ValueError('after is for edge_count/orgasm_count only')
        if self.type == 'style_stages' and self.count > len(self.styles): raise ValueError('more stages than styles')
        if len({s.id for s in self.stages}) != len(self.stages): raise ValueError('stage ids must be unique')
        if (self.type == 'puzzle_solved') != (self.puzzle is not None): raise ValueError('puzzle is required for puzzle_solved and not allowed otherwise')
        if (self.type == 'choice') != (self.choice is not None): raise ValueError('choice is required for choice objectives only')
        if self.after_stage and self.type != 'choice': raise ValueError('after_stage is for choices only')
        if self.within_seconds is not None and self.type not in COUNTED: raise ValueError('within_seconds is for edge_count/orgasm_count only')
        if self.warnings and (self.within_seconds is None or any(not 0 < w < self.within_seconds for w in self.warnings)):
            raise ValueError('warnings are remaining seconds below within_seconds')
        return self


class Reward(StrictModel):
    type: RewardType
    id: str = Identifier
    label: str = Text

    @property
    def key(self):
        return f'{self.type}:{self.id}'


class SessionRequirement(StrictModel):
    """The engine mode the mission session must start in, as the snapshot reports it."""
    active_mode: EngineMode | None = None
    label: str | None = Field(default=None, max_length=200)


class SettingsLimit(StrictModel):
    """AI Settings Control during the mission: only these changes may be requested. Once the objective named in
    `after` is met, `then_allowed` applies instead (Mission 9: Force Orgasm only in the final phase)."""
    allowed: list[SettingName] = Field(min_length=1, max_length=7)
    # Directed: the companion changes settings only at the mission's own steps (EdgeLoop asks it to), never on its
    # own initiative or for a new round, and only to values the mission needs. A change the user asks for in chat
    # is also held to those values.
    directed: bool = False
    after: str | None = Field(default=None, max_length=64)
    then_allowed: list[SettingName] | None = Field(default=None, min_length=1, max_length=7)

    @model_validator(mode='after')
    def paired(self):
        if (self.after is None) != (self.then_allowed is None): raise ValueError('after and then_allowed go together')
        return self


class StoryMeta(StrictModel):
    chapter: int | None = Field(default=None, ge=1, le=1000)
    tags: list[str] = Field(default_factory=list, max_length=16)


FLAG_NAME = re.compile(r'[a-z0-9_]{1,48}')
FLAG_VALUE = re.compile(r'[a-z0-9_]{1,32}')
# A flag a condition reads: the campaign's own ("player_suspicion"), or one inherited from a campaign it requires,
# addressed with that campaign's id ("asterion_initiative.helix_connection").
FLAG_REF = re.compile(r'(?:[a-z0-9][a-z0-9_-]{0,63}\.)?[a-z0-9_]{1,48}')
WHEN_DEPTH = 4


class When(StrictModel):
    """A story condition over saved flags, decided by the campaign alone (never by a model).
    Exactly one of: all / any (lists of conditions), not (one condition), or flag with eq or in.
    A flag that was never set has no value: eq and in are false for it, `not` makes them true."""
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False, populate_by_name=True)
    all: list['When'] | None = Field(default=None, min_length=1, max_length=8)
    any: list['When'] | None = Field(default=None, min_length=1, max_length=8)
    not_: 'When | None' = Field(default=None, alias='not')
    flag: str | None = Field(default=None, max_length=113)
    eq: str | None = Field(default=None, max_length=32)
    in_: list[str] | None = Field(default=None, alias='in', min_length=1, max_length=8)

    @model_validator(mode='after')
    def one_rule(self):
        kinds = [k for k in ('all', 'any', 'not_', 'flag') if getattr(self, k) is not None]
        if len(kinds) != 1: raise ValueError('a condition is exactly one of all, any, not or flag')
        if self.flag is not None:
            if not FLAG_REF.fullmatch(self.flag): raise ValueError('flag must be a snake_case name, optionally <campaign>.<name>')
            if (self.eq is None) == (self.in_ is None): raise ValueError('flag needs exactly one of eq or in')
            if any(not FLAG_VALUE.fullmatch(v) for v in ([self.eq] if self.eq is not None else self.in_)): raise ValueError('flag values are short snake_case words')
        elif self.eq is not None or self.in_ is not None: raise ValueError('eq and in belong to a flag')
        if self.depth() > WHEN_DEPTH: raise ValueError(f'conditions nest at most {WHEN_DEPTH} deep')
        return self

    def depth(self):
        children = (self.all or []) + (self.any or []) + ([self.not_] if self.not_ else [])
        return 1 + max((c.depth() for c in children), default=0)

    def references(self):
        """(flag, value) pairs the condition can test; a value of None means 'any value' is not used here."""
        if self.flag is not None: return {(self.flag, v) for v in ([self.eq] if self.eq is not None else self.in_)}
        return set().union(*(c.references() for c in (self.all or []) + (self.any or []) + ([self.not_] if self.not_ else [])))


When.model_rebuild()
Objective.model_rebuild()


def evaluate(when, flags):
    """Is the condition true for these flags (name -> value)? Pure; no side effects."""
    if when is None: return True
    if when.all is not None: return all(evaluate(c, flags) for c in when.all)
    if when.any is not None: return any(evaluate(c, flags) for c in when.any)
    if when.not_ is not None: return not evaluate(when.not_, flags)
    value = flags.get(when.flag)
    return value == when.eq if when.eq is not None else value in when.in_


def check_when(when, declared):
    """Refuse a condition on a flag nothing can set, or on a value nothing sets (a typo would silently be false)."""
    for flag, value in sorted(when.references() if when else ()):
        if flag not in declared: raise ValueError(f'condition on unknown flag {flag}')
        if value not in declared[flag]: raise ValueError(f'condition on {flag}={value}, a value nothing sets')


def public_block(block, flags):
    """Only matching narrative reaches the browser; conditions stay in the campaign layer."""
    return block.model_dump(exclude_none=True, exclude={'when'}) if block and evaluate(block.when, flags) else None


def moment_keys(mission):
    keys = {'start'}
    for o in mission.objectives:
        if o.type in GOAL_TYPES: keys.add(f'{o.id}:done')
        keys.update(f'{o.id}:{st.id}' for st in o.stages[1:])
        keys.update(f'{o.id}:{n}' for n in o.milestones)
        if o.choice: keys.update(f'{o.id}:{option.id}' for option in o.choice.options)
    return keys


class CompletionRoute(StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r'^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$')
    label: str = Field(min_length=1, max_length=80)
    objectives: list[str] = Field(min_length=1, max_length=8)
    sets: dict[str, str] = Field(default_factory=dict, max_length=12)

    @model_validator(mode='after')
    def valid_route(self):
        if not self.label.strip(): raise ValueError('route labels must not be blank')
        if len(set(self.objectives)) != len(self.objectives): raise ValueError('route objectives must be unique')
        for key, value in self.sets.items():
            if not FLAG_NAME.fullmatch(key) or not FLAG_VALUE.fullmatch(value): raise ValueError('route sets use own snake_case flags and values')
        return self


class Completion(StrictModel):
    any_of: list[CompletionRoute] = Field(min_length=2, max_length=4)

    @model_validator(mode='after')
    def distinct_routes(self):
        if len({r.id for r in self.any_of}) != len(self.any_of): raise ValueError('route ids must be unique')
        if len({frozenset(r.objectives) for r in self.any_of}) != len(self.any_of): raise ValueError('routes must name different objective sets')
        return self


class Mission(StrictModel):
    id: str = Identifier
    order: int = Field(ge=1, le=10000)
    title: str = Field(min_length=1, max_length=80)
    summary: str = Text
    companion: str = Identifier
    prerequisites: list[str] = Field(default_factory=list, max_length=16)
    objectives: list[Objective] = Field(min_length=1, max_length=12)
    rewards: list[Reward] = Field(default_factory=list, max_length=12)
    session: SessionRequirement | None = None
    settings_control: SettingsLimit | None = None
    replay: Literal['allowed', 'disabled'] = 'allowed'
    difficulty: Literal['introductory', 'standard', 'challenge'] | None = None
    optional: bool = False
    when: When | None = None
    locked_reason: str | None = Field(default=None, min_length=1, max_length=160)
    completion: Completion | None = None
    story: StoryMeta | None = None
    hints: list[str] = Field(default_factory=list, max_length=8)
    # Earlier missions whose saved results this mission's companion is told about (Mission 9's review).
    review: list[str] = Field(default_factory=list, max_length=16)
    # Story flags the first completion sets (a replay never changes them), e.g. {"player_suspicion": "cleared"}.
    # Later features (card eligibility, briefs) can read them; the campaign itself only records them.
    flags: dict[str, str] = Field(default_factory=dict, max_length=12)

    @model_validator(mode='after')
    def unique_objectives(self):
        if self.locked_reason is not None and (not self.when or not self.locked_reason.strip() or code_controls(self.locked_reason) or len(self.locked_reason.splitlines()) != 1):
            raise ValueError('locked_reason requires when and a nonblank single line')
        ids = [o.id for o in self.objectives]
        if len(ids) != len(set(ids)): raise ValueError('objective ids must be unique within a mission')
        if self.completion:
            required = {o.id for o in self.objectives if not o.optional}
            if any(set(r.objectives) - required for r in self.completion.any_of):
                raise ValueError('routes must name existing, required objectives')
        for i, o in enumerate(self.objectives):
            if o.after_stage:
                stages = {f'{x.id}:{st.id}' for x in self.objectives if x.type == 'stage_sequence' for st in x.stages}
                if o.after_stage not in stages: raise ValueError(f'{o.id}: after_stage must name a stage in this mission')
            if o.after and o.after not in ids[:i]: raise ValueError(f'{o.id}: after must name an earlier objective')
        if self.settings_control and self.settings_control.after and self.settings_control.after not in ids:
            raise ValueError('settings_control.after must name an objective')
        keys = moment_keys(self)
        for o in self.objectives:
            if o.puzzle and any(isinstance(c, PuzzleClue) and c.reveal_at and c.reveal_at not in keys for c in o.puzzle.clues):
                raise ValueError('clue reveal_at must name a moment this mission can fire')
        for key, value in self.flags.items():
            if not FLAG_NAME.fullmatch(key) or not FLAG_VALUE.fullmatch(value): raise ValueError('flags are short snake_case names and values')
        return self


class Chapter(StrictModel):
    """Missions belong to a chapter through story.chapter (its number). A chapter is complete when the
    chapter_complete reward with its id is earned; it opens when the missions' prerequisites allow."""
    number: int = Field(ge=1, le=1000)
    id: str = Identifier
    title: str = Field(min_length=1, max_length=80)
    summary: str = Text
    # A chapter announced but not playable yet ("Coming soon"): it has no missions.
    teaser: bool = False


class Campaign(StrictModel):
    schema_version: Literal[1]
    id: str = Identifier
    order: int = Field(ge=1, le=10000)
    title: str = Field(min_length=1, max_length=80)
    description: str = Text
    artwork: str | None = Field(default=None, max_length=200, pattern=r'^[A-Za-z0-9_./-]+$')
    available_from_start: bool = True
    requires_campaigns: list[str] = Field(default_factory=list, max_length=8)
    # Campaigns whose story flags this one may read (read only, as "<campaign>.<flag>"); each must be required.
    inherits_flags_from: list[str] = Field(default_factory=list, max_length=8)
    # Extra words this campaign's companions use for a mission ("protocol"), so a premature "the protocol is
    # complete" is caught like "the mission is complete". Lowercase single words.
    mission_words: list[str] = Field(default_factory=list, max_length=8)
    starting_companions: list[str] = Field(default_factory=list, max_length=16)
    chapters: list[Chapter] = Field(default_factory=list, max_length=50)
    missions: list[Mission] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def consistent(self):
        ids = [m.id for m in self.missions]
        if len(ids) != len(set(ids)): raise ValueError('mission ids must be unique')
        if set(self.inherits_flags_from) - set(self.requires_campaigns): raise ValueError('inherits_flags_from must name required campaigns')
        if any(not re.fullmatch(r'[a-z]{3,24}', w) for w in self.mission_words): raise ValueError('mission_words are single lowercase words')
        known = set(ids)
        for m in self.missions:
            missing = [p for p in m.prerequisites if p not in known]
            if missing: raise ValueError(f'{m.id}: unknown prerequisite {missing[0]}')
            if set(m.review) - known: raise ValueError(f'{m.id}: review names an unknown mission')
        # Prerequisites must form a graph without cycles, so every mission is reachable.
        graph = {m.id: set(m.prerequisites) for m in self.missions}
        done = set()
        while graph:
            ready = [k for k, v in graph.items() if v <= done]
            if not ready: raise ValueError('mission prerequisites contain a cycle')
            for k in ready: done.add(k); graph.pop(k)
        unlocked = set(self.starting_companions) | {r.id for m in self.missions for r in m.rewards if r.type == 'unlock_companion'}
        for m in self.missions:
            if m.companion not in unlocked: raise ValueError(f'{m.id}: companion {m.companion} is never unlocked')
        if self.chapters:
            numbers = {c.number for c in self.chapters}
            if len(numbers) != len(self.chapters) or len({c.id for c in self.chapters}) != len(self.chapters): raise ValueError('chapter numbers and ids must be unique')
            teasers = {c.number for c in self.chapters if c.teaser}
            for m in self.missions:
                if not m.story or m.story.chapter not in numbers: raise ValueError(f'{m.id}: story.chapter must name a chapter')
                if m.story.chapter in teasers: raise ValueError(f'{m.id}: a teaser chapter has no missions')
            ends = {r.id for m in self.missions for r in m.rewards if r.type == 'chapter_complete'}
            if ends - {c.id for c in self.chapters}: raise ValueError('chapter_complete for an unknown chapter')
        return self

    def chapter_of(self, mission):
        number = mission.story.chapter if mission.story else None
        return next((c for c in self.chapters if c.number == number), None)

    def mission(self, mission_id):
        return next((m for m in self.missions if m.id == mission_id), None)

    def own_flags(self):
        """Every flag a mission of this campaign can set, with the values it can take."""
        declared = {}
        for m in self.missions:
            for key, value in m.flags.items(): declared.setdefault(key, set()).add(value)
            for route in m.completion.any_of if m.completion else ():
                for key, value in route.sets.items(): declared.setdefault(key, set()).add(value)
            for o in m.objectives:
                for option in o.choice.options if o.choice else ():
                    for key, value in option.sets.items(): declared.setdefault(key, set()).add(value)
        return declared


class NarrativeBlock(StrictModel):
    speaker: str = Identifier
    lines: list[str] = Field(min_length=1, max_length=20)
    # A block can be a draft inside an approved narrative (new text awaiting the author's review).
    status: Literal['draft', 'approved', 'placeholder'] | None = None
    # Scene presentation (HELIX-020/021, ADR-9). The speaker's portrait for this block (default neutral), a story
    # illustration shown full-bleed, or an environment behind the speaker. Slots are checked against the campaign's
    # story-art registry (src/assets/story/<campaign>/ASSETS.json) when the campaign loads.
    expression: Literal[EXPRESSIONS] | None = None
    image: str | None = Field(default=None, min_length=1, max_length=64, pattern=r'^[a-z0-9][a-z0-9_-]*$')
    background: str | None = Field(default=None, min_length=1, max_length=64, pattern=r'^[a-z0-9][a-z0-9_-]*$')
    when: When | None = None

    def slots(self):
        return [(field, getattr(self, field)) for field in ('image', 'background') if getattr(self, field)]


# Which registry slot kinds each scene field may name.
SCENE_SLOT_KINDS = {'image': {'illustration', 'key_art', 'chapter_splash'}, 'background': {'environment'}}
STORY_DIR = ROOT / 'src' / 'assets' / 'story'
MANIFEST = ROOT / 'src' / 'assets' / 'characters' / 'manifest.json'


def story_characters(manifest=MANIFEST):
    """Ids of story-only characters (HELIX-030): scripted lines and portraits, never a model or a companion."""
    try: characters = json.loads(Path(manifest).read_text())['characters']
    except (OSError, ValueError, KeyError, TypeError): return set()
    return {cid for cid, c in characters.items() if isinstance(c, dict) and c.get('role') == 'story'}


def unknown_speakers(book, manifest=MANIFEST):
    """Narrative speakers that have no manifest entry, per campaign (lint; HELIX-073 makes it a release rule)."""
    try: known = set((manifest if isinstance(manifest, dict) else json.loads(Path(manifest).read_text()))['characters'])
    except (OSError, ValueError, KeyError, TypeError): known = set()
    return {cid: sorted({b.speaker for b in n.all_blocks()} - known) for cid, n in book.narratives.items()
            if {b.speaker for b in n.all_blocks()} - known}


def check_story_slots(campaign_id, blocks, story_dir=STORY_DIR):
    """Every image/background a narrative names must be a slot of the right kind in the campaign's registry."""
    used = [(field, slot) for block in blocks for field, slot in block.slots()]
    if not used: return
    try:
        registry = story_dir[campaign_id] if isinstance(story_dir, dict) else json.loads((Path(story_dir) / campaign_id / 'ASSETS.json').read_text())
        slots = registry['slots']
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('narrative names story art but the campaign has no story-art registry') from None
    for field, slot in used:
        kind = slots.get(slot, {}).get('kind') if isinstance(slots, dict) and isinstance(slots.get(slot), dict) else None
        if kind is None: raise ValueError(f'unknown story-art slot {slot}')
        if kind not in SCENE_SLOT_KINDS[field]: raise ValueError(f'{field} cannot use the {kind} slot {slot}')


class StorySoFar(StrictModel):
    when: When | None = None
    text: str = Field(min_length=1, max_length=300)

    @model_validator(mode='after')
    def one_line(self):
        if not self.text.strip() or code_controls(self.text) or len(self.text.splitlines()) != 1 or '[[' in self.text:
            raise ValueError('story_so_far text is one nonblank line without [[')
        return self


class MissionNarrative(StrictModel):
    # One block, or up to four by one speaker (H4, 2026-11-20): the first is always shown and carries the art; later
    # blocks may have `when`. The blocks shown are merged, in order, into the one briefing block the browser shows.
    briefing: Annotated[Annotated[NarrativeBlock, Tag('block')] | Annotated[list[NarrativeBlock], Tag('blocks')],
                        Discriminator(lambda v: 'blocks' if isinstance(v, list) else 'block')]
    completion: NarrativeBlock
    # Further blocks after the completion, possibly by other speakers (Mission 14: Celeste's verdict, then Nova).
    # Up to 8 so `when` variants fit (H4: three by offer, three by Mira's deal, Iris); only matching ones are shown.
    epilogue: list[NarrativeBlock] = Field(default_factory=list, max_length=8)
    # Scripted lines for progress moments, keyed "<objective id>:<moment>": a count ("edges:5"), a completed
    # play-style stage ("styles:stage1"), a stage of a sequence ("assessment:baseline"), or "start" when the
    # mission session begins. Shown in the conversation; the model is not asked to speak for them.
    milestones: dict[str, NarrativeBlock] = Field(default_factory=dict, max_length=24)
    director_context: str | None = Field(default=None, max_length=400)
    directions: dict[str, str] = Field(default_factory=dict, max_length=24)
    # Private bounded brief text; public views serialize narrative blocks explicitly, never these rules.
    story_so_far: list[StorySoFar] = Field(default_factory=list, max_length=8)

    @model_validator(mode='after')
    def direction_texts(self):
        if isinstance(self.briefing, list):
            parts = self.briefing
            if not 1 <= len(parts) <= 4: raise ValueError('a briefing has 1-4 blocks')
            if parts[0].when is not None: raise ValueError('the first briefing block is always shown: no when')
            if len({b.speaker for b in parts}) != 1: raise ValueError('briefing blocks share one speaker')
            if sum(len(b.lines) for b in parts) > 20: raise ValueError('a briefing has at most 20 lines in all')
        if any(rule.when is None for rule in self.story_so_far[:-1]):
            raise ValueError('only the final story_so_far rule may be a fallback')
        if self.milestones.keys() & self.directions.keys(): raise ValueError('a moment cannot have both a scripted line and a direction')
        if any(not text.strip() or len(text) > 200 or len(text.splitlines()) != 1 or '[[' in text for text in self.directions.values()):
            raise ValueError('directions are 1-200 characters on one line, without [[')
        return self

    def check_directions(self, mission):
        if self.directions.keys() - moment_keys(mission): raise ValueError('direction for a moment this mission cannot fire')

    def briefing_blocks(self):
        return list(self.briefing) if isinstance(self.briefing, list) else [self.briefing]

    def public_briefing(self, flags):
        """The shown briefing blocks merged into one browser block (lines in order; art from the first)."""
        shown = [b for b in self.briefing_blocks() if evaluate(b.when, flags)]
        if not shown: return None
        merged = public_block(shown[0], flags)
        merged['lines'] = [line for b in shown for line in b.lines]
        statuses = {b.status for b in shown}
        for status in ('placeholder', 'draft'):
            if status in statuses: merged['status'] = status; break
        return merged

    def blocks(self, flags=None):
        return tuple(b for b in (*self.briefing_blocks(), self.completion, *self.epilogue, *self.milestones.values())
                     if flags is None or evaluate(b.when, flags))

    def draft(self, flags=None):
        return any(b.status == 'draft' for b in self.blocks(flags))

    def review_status(self, narrative_status, flags=None):
        if narrative_status == 'placeholder' or any(b.status == 'placeholder' for b in self.blocks(flags)): return 'placeholder'
        return 'draft' if self.draft(flags) else None


class Narrative(StrictModel):
    schema_version: Literal[1]
    campaign: str = Identifier
    status: Literal['draft', 'approved', 'placeholder']
    missions: dict[str, MissionNarrative]
    chapters: dict[str, NarrativeBlock] = Field(default_factory=dict, max_length=50)
    # HELIX-022: a short scene played on first entry to a chapter (saved as seen), replayable from the board.
    chapter_intros: dict[str, list[NarrativeBlock]] = Field(default_factory=dict, max_length=50)
    campaign_complete: NarrativeBlock | None = None

    def all_blocks(self):
        blocks = [b for m in self.missions.values() for b in m.blocks()] + list(self.chapters.values())
        blocks += [b for intro in self.chapter_intros.values() for b in intro]
        if self.campaign_complete: blocks.append(self.campaign_complete)
        return blocks

    def placeholder(self, flags=None):
        return self.status == 'placeholder' or any(b.status == 'placeholder' for b in self.all_blocks()
                                                  if flags is None or evaluate(b.when, flags))


class Book:
    """All campaigns found on disk. A broken campaign is left out and reported; the others still load."""

    def __init__(self, campaigns=(), narratives=None, errors=()):
        self.campaigns = sorted(campaigns, key=lambda c: (c.order, c.id))
        self.narratives = narratives or {}
        self.errors = list(errors)

    @classmethod
    def load(cls, directory=CAMPAIGN_DIR, story_dir=STORY_DIR, manifest=MANIFEST):
        campaigns, narratives, errors = [], {}, []
        story_only = story_characters(manifest)
        for path in sorted(Path(directory).glob('*/campaign.json')) if Path(directory).is_dir() else []:
            try:
                campaign = Campaign.model_validate(json.loads(path.read_text()))
                if campaign.id != path.parent.name: raise ValueError('campaign id must match its folder name')
                if any(c.id == campaign.id for c in campaigns): raise ValueError('duplicate campaign id')
                companions = [m.companion for m in campaign.missions] + list(campaign.starting_companions) + \
                    [r.id for m in campaign.missions for r in m.rewards if r.type == 'unlock_companion']
                for cid in companions:
                    if cid in story_only: raise ValueError(f'{cid} is a story-only character and cannot be a companion')
                narrative_path = path.parent / 'narrative.json'
                narrative = Narrative.model_validate(json.loads(narrative_path.read_text())) if narrative_path.exists() else None
                if narrative and narrative.campaign != campaign.id: raise ValueError('narrative belongs to another campaign')
                if narrative:
                    unknown = set(narrative.missions) - {m.id for m in campaign.missions}
                    if unknown: raise ValueError(f'narrative for unknown mission {sorted(unknown)[0]}')
                    for mid, block in narrative.missions.items():
                        block.check_directions(campaign.mission(mid))
                        objectives = {o.id for o in campaign.mission(mid).objectives}
                        if {k.split(':', 1)[0] for k in block.milestones} - objectives - {'start'}: raise ValueError(f'{mid}: milestone for an unknown objective')
                    if set(narrative.chapters) - {c.id for c in campaign.chapters}: raise ValueError('narrative for an unknown chapter')
                    if set(narrative.chapter_intros) - {c.id for c in campaign.chapters if not c.teaser}: raise ValueError('chapter intro for an unknown or teaser chapter')
                    if any(not 1 <= len(intro) <= 8 for intro in narrative.chapter_intros.values()): raise ValueError('a chapter intro has 1 to 8 blocks')
                    check_story_slots(campaign.id, narrative.all_blocks(), story_dir)
                campaigns.append(campaign)
                if narrative: narratives[campaign.id] = narrative
            except (ValueError, OSError, ValidationError) as exc:
                detail = str(exc).splitlines()[0][:200] if not isinstance(exc, ValidationError) else f'{exc.error_count()} definition errors'
                errors.append({'path': path.parent.name, 'detail': detail})
                logger.warning('Campaign %s not loaded: %s', path.parent.name, detail)
        book = cls(campaigns, narratives, errors)
        # Validate after all declarations are known, then remove dependent campaigns if a source was rejected.
        while True:
            rejected = []
            for campaign in book.campaigns:
                try:
                    if any(not book.campaign(cid) for cid in campaign.inherits_flags_from):
                        raise ValueError('inherits flags from a campaign that is not installed')
                    book.check_conditions(campaign)
                except ValueError as exc:
                    rejected.append(campaign)
                    book.errors.append({'path': campaign.id, 'detail': str(exc)[:200]})
                    logger.warning('Campaign %s not loaded: %s', campaign.id, exc)
            if not rejected: return book
            for campaign in rejected:
                book.campaigns.remove(campaign); book.narratives.pop(campaign.id, None)

    def campaign(self, campaign_id):
        return next((c for c in self.campaigns if c.id == campaign_id), None)

    def declared_flags(self, campaign):
        """The flags a campaign's conditions may read: its own, and those of the campaigns it inherits from."""
        declared = campaign.own_flags()
        for cid in campaign.inherits_flags_from:
            source = self.campaign(cid)
            for key, values in (source.own_flags() if source else {}).items(): declared[f'{cid}.{key}'] = set(values)
        return declared

    def check_conditions(self, campaign):
        declared = self.declared_flags(campaign)
        for mission in campaign.missions:
            check_when(mission.when, declared)
            for objective in mission.objectives: check_when(objective.when, declared)
        narrative = self.narratives.get(campaign.id)
        for block in narrative.all_blocks() if narrative else (): check_when(block.when, declared)
        for mission in narrative.missions.values() if narrative else ():
            for rule in mission.story_so_far: check_when(rule.when, declared)


# ---- Saved progress -------------------------------------------------------------------------

class MissionRecord(StrictModel):
    completions: int = Field(ge=1, le=1000000)
    first_completed_at: str = Field(max_length=40)
    last_completed_at: str = Field(max_length=40)


class RewardRecord(StrictModel):
    earned_at: str = Field(max_length=40)
    mission: str = Field(max_length=64)


class ChapterRecord(StrictModel):
    completed_at: str = Field(max_length=40)


class CampaignRecord(StrictModel):
    missions: dict[str, MissionRecord] = Field(default_factory=dict)
    rewards: dict[str, RewardRecord] = Field(default_factory=dict)
    chapters: dict[str, ChapterRecord] = Field(default_factory=dict)
    flags: dict[str, str] = Field(default_factory=dict, max_length=64)
    completed_at: str | None = Field(default=None, max_length=40)
    # Facts a mission confirmed and the campaign keeps, e.g. the calibrated maximum heart rate.
    records: dict[str, int | str | None] = Field(default_factory=dict, max_length=32)
    # Puzzles solved per mission not yet completed. Kept when the player leaves the mission and comes back,
    # cleared when the mission completes (a replay solves them again).
    solved: dict[str, list[str]] = Field(default_factory=dict, max_length=32)
    choices: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=100)
    routes: dict[str, str] = Field(default_factory=dict, max_length=100)
    # HELIX-022: chapter id -> when its intro was first seen. New in v4 files; absent means none seen.
    intros_seen: dict[str, str] = Field(default_factory=dict, max_length=50)


class ActiveMission(StrictModel):
    campaign: str = Field(max_length=64)
    mission: str = Field(max_length=64)
    started_at: str = Field(max_length=40)


class Progress(StrictModel):
    schema_version: Literal[4] = SCHEMA_VERSION
    campaigns: dict[str, CampaignRecord] = Field(default_factory=dict)
    active: ActiveMission | None = None


# Each entry upgrades a saved file by one version: MIGRATIONS[1] turns version 1 into version 2.
# A file from a newer app (higher version) is never rewritten; the campaign stays off instead.
def _v1_to_v2(data):
    """Version 2 adds chapters. Completion markers (campaign completed_at, completion rewards) are dropped here and
    recomputed from the completed missions under the current definitions when progress is loaded, so a campaign
    completed at Mission 5 under version 1 becomes 'Chapter 1 complete' once Chapter 2 exists."""
    if not isinstance(data.get('campaigns') or {}, dict): raise ValueError('campaigns must be an object')
    for record in (data.get('campaigns') or {}).values():
        if not isinstance(record, dict): continue
        record['completed_at'] = None
        rewards = record.get('rewards')
        if isinstance(rewards, dict):
            record['rewards'] = {k: v for k, v in rewards.items() if not (isinstance(k, str) and k.split(':', 1)[0] in COMPLETION_REWARDS)}
        record.setdefault('chapters', {})
    data['schema_version'] = 2
    return data


def _v2_to_v3(data):
    """Version 3 adds story flags and saved puzzle progress, and the campaign no longer ends with Chapter 2:
    completion markers are recomputed again on load (see _v1_to_v2), so a campaign completed at Mission 9 reopens."""
    data = _v1_to_v2(data)
    for record in (data.get('campaigns') or {}).values():
        if isinstance(record, dict): record.setdefault('flags', {})
    data['schema_version'] = 3
    return data


def _v3_to_v4(data):
    """Choices and routes belong to each campaign, indexed by mission (ids need not be globally unique)."""
    if not isinstance(data.get('campaigns') or {}, dict): raise ValueError('campaigns must be an object')
    for record in (data.get('campaigns') or {}).values():
        if isinstance(record, dict):
            record.setdefault('choices', {}); record.setdefault('routes', {})
    data['schema_version'] = 4
    return data


MIGRATIONS = {1: _v1_to_v2, 2: _v2_to_v3, 3: _v3_to_v4}


class NewerProgressError(ValueError):
    """An incompatible save is kept intact; the rest of the observer remains available."""


def migrate(data):
    if not isinstance(data, dict) or not isinstance(data.get('schema_version'), int) or isinstance(data.get('schema_version'), bool):
        raise ValueError('Unsupported campaign progress format')
    version = data['schema_version']
    if version > SCHEMA_VERSION: raise NewerProgressError('Campaign progress was saved by a newer EdgeLoop AI')
    while version < SCHEMA_VERSION:
        if version not in MIGRATIONS: raise ValueError(f'No migration from campaign progress version {version}')
        try: data = MIGRATIONS[version](deepcopy(data))
        except (AttributeError, TypeError, KeyError) as exc:
            # A malformed older file (say `campaigns` is a list) is refused like any invalid file: left untouched,
            # only the campaign switches off.
            raise ValueError(f'Campaign progress version {version} is malformed') from exc
        version = data['schema_version']
    return data


# ---- Evidence from the canonical report ------------------------------------------------------

def real_hr(report):
    """A heart-rate monitor the participant connected: ready, over Bluetooth, and not the built-in simulator."""
    d = (report or {}).get('devices') or {}
    return bool(d.get('hr_ready') and d.get('ble') and not d.get('simulated_hr'))


def toy_ready(report):
    return bool(((report or {}).get('devices') or {}).get('toy_ready'))


def details(report):
    return (report or {}).get('details') or {}


class Attempt:
    """One try at the active mission. Counts restart when the mission session ends before completion."""

    def __init__(self, mission, solved=(), choices=None, flags=None):
        self.mission = mission
        # Freeze optional-objective visibility for this try; choice overlays never change its goals mid-session.
        self.objectives = [o for o in mission.objectives if evaluate(o.when, flags or {})]
        self.session_id = None
        # The engine's running clock at the mission-session start (timed objectives), and timed goals run out.
        self.base_seconds = None
        self.expired = set()
        # Puzzles solved in this mission (saved; kept across sessions), and the last wrong pick per puzzle.
        self.solved = set(solved)
        self.choices = dict(choices or {})
        self.wrong = {}
        self.code_failures = {}; self.code_blocked = {}; self.code_revision = {}
        self.fired = set(); self.clue_seen = {}
        # Stages whose intensity raise is used up: the level was reached once in the stage (by the companion or the
        # player). After that the player may lower it, and nothing may raise it again in that stage.
        self.raised = set()
        self.set_sent = set()
        self.done = {}
        self.edges = self.orgasms = 0
        self.last_edges = self.last_orgasms = None
        # Per counted objective (an `after` objective counts only once its predecessor is met).
        self.counts = {}
        # Active running seconds: per play style (style_stages) and per stage id (stage_sequence).
        self.style_time = {}
        self.stage_time = {}
        # The last observation's time and configuration, so an interval is credited only when both ends agree.
        self.last_seconds = None
        self.last_config = None
        self.last_captured = None
        # Play styles that filled a stage, in the order they did, per style_stages objective.
        self.filled = {}
        # Scripted progress moments already shown in this try.
        self.marked = set()
        self.metric = None
        self.completed = False
        self.reset_reason = None
        self.cued = set()
        # All objectives met but not yet saved: kept until the save succeeds, whatever the next report says.
        self.pending = False
        # Milestone lines crossed by the completing report, sent with the completion once it is saved.
        self.pending_lines = []
        # Bumped on every reset, so a cue from an earlier try is recognised as stale.
        self.generation = 0

    def done_styles(self, o):
        """Play styles that filled a stage, in the order they did."""
        return list(self.filled.get(o.id, ()))

    def current_stage(self, o):
        return next((st for st in o.stages if self.stage_time.get(st.id, 0) < st.seconds), None)

    def elapsed(self):
        """Active running seconds since the mission-session start (the engine clock freezes while paused)."""
        if self.base_seconds is None or not isinstance(self.last_seconds, int): return 0
        return max(0, self.last_seconds - self.base_seconds)

    def remaining(self, o):
        return o.within_seconds if self.session_id is None else max(0, o.within_seconds - self.elapsed())

    def puzzle_open(self, o):
        """Puzzles are solved in order: open once every earlier puzzle of the mission is solved."""
        route_ids = self.route_objectives()
        same_path = {oid for r in self.mission.completion.any_of for oid in r.objectives if o.id in r.objectives} if self.mission.completion else set()
        earlier = [x.id for x in self.objectives[:self.objectives.index(o)] if x.type == 'puzzle_solved' and not x.optional
                   and (x.id not in route_ids or x.id in same_path)]
        return o.id not in self.solved and all(x in self.solved for x in earlier)

    def visible_clues(self, o):
        return [(i, c if isinstance(c, str) else c.text) for i, c in enumerate(o.puzzle.clues)
                if isinstance(c, str) or not c.reveal_at or c.reveal_at in self.fired]

    def acknowledge_clues(self, o):
        self.clue_seen[o.id] = {i for i, _ in self.visible_clues(o)}

    def choice_open(self, o):
        if o.id in self.choices: return False
        if not o.after_stage: return True
        oid, stage_id = o.after_stage.split(':', 1)
        sequence = next(x for x in self.mission.objectives if x.id == oid)
        index = next(i for i, st in enumerate(sequence.stages) if st.id == stage_id)
        return bool(self.session_id) and all(self.stage_time.get(st.id, 0) >= st.seconds for st in sequence.stages[:index])

    def view(self, report=None, companion_ok=False):
        live = {'hr_monitor_connected': real_hr(report), 'toy_connected': toy_ready(report)}
        items = []
        for o in self.objectives:
            done = bool(self.done.get(o.id)) or (self.session_id is None and live.get(o.type, False)) or o.id in self.solved or o.id in self.choices
            item = {'id': o.id, 'type': o.type, 'label': o.label, 'done': done, **({'optional': True} if o.optional else {})}
            if o.type in COUNTED:
                item.update(progress=min(self.counts.get(o.id, 0), o.count), count=o.count)
                if o.milestones: item['milestones'] = list(o.milestones)
                if o.after: item['after'] = o.after
                if o.within_seconds:
                    item.update(within_seconds=o.within_seconds, remaining=self.remaining(o), expired=o.id in self.expired)
            if o.type == 'puzzle_solved':
                z = o.puzzle
                clues = self.visible_clues(o)
                item['puzzle'] = {'title': z.title, 'clues': [text for _, text in clues], 'question': z.question, 'open': self.puzzle_open(o)}
                if z.kind == 'code': item['puzzle'].update(kind='code', max_length=z.max_length, answer_revision=self.code_revision.get(o.id, 0))
                else: item['puzzle']['options'] = [x.model_dump() for x in z.options]
                new = [n for n, (i, _) in enumerate(clues) if isinstance(z.clues[i], PuzzleClue) and z.clues[i].reveal_at and i not in self.clue_seen.get(o.id, set())]
                if new: item['puzzle']['new_clues'] = new
                if o.id in self.wrong and o.id not in self.solved: item['puzzle'].update(wrong=self.wrong[o.id], hint=z.hint)
            if o.type == 'choice':
                chosen = next((x for x in o.choice.options if x.id == self.choices.get(o.id)), None)
                label = None
                if o.after_stage:
                    oid, stage_id = o.after_stage.split(':', 1)
                    label = next(st.label for x in self.mission.objectives if x.id == oid for st in x.stages if st.id == stage_id)
                item['choice'] = {'prompt': o.choice.prompt, 'options': [{'id': x.id, 'label': x.label} for x in o.choice.options],
                                  'open': self.choice_open(o), 'selected': chosen.id if chosen else None,
                                  'selected_label': chosen.label if chosen else None,
                                  'locked_reason': None if chosen or self.choice_open(o) else f'Available during {label}'}
            if o.type == 'style_stages':
                filled = self.done_styles(o)
                current = (report or {}).get('experience') if self.session_id else None
                stages = [{'style': k, 'label': STYLE_WORDS.get(k, k), 'seconds': min(self.style_time[k], o.seconds), 'done': True} for k in filled]
                if current in o.styles and current not in filled and len(filled) < o.count:
                    stages.append({'style': current, 'label': STYLE_WORDS.get(current, current), 'seconds': self.style_time.get(current, 0), 'done': False, 'current': True})
                # Overall time: the filled stages plus the furthest partial styles that could still fill the rest,
                # so it never passes count x seconds (eight styles at 4:55 each are not 197%).
                partial = sorted((min(v, o.seconds) for k, v in self.style_time.items() if k in o.styles and k not in filled), reverse=True)
                item.update(progress=len(filled), count=o.count, stage_seconds=o.seconds, stages=stages,
                            elapsed=len(filled) * o.seconds + sum(partial[:max(0, o.count - len(filled))]))
            if o.type == 'stage_sequence':
                current = self.current_stage(o)
                item.update(stages=[{'id': st.id, 'label': st.label, 'intensity': st.intensity, 'raise_to': st.raise_to, 'set_to': st.set_to,
                                     'needs_manual': bool(st.set_to and st.intensity is not None and current is st and self.session_id and (report or {}).get('intensity') != st.intensity), 'seconds': st.seconds,
                                     'elapsed': min(self.stage_time.get(st.id, 0), st.seconds), 'done': self.stage_time.get(st.id, 0) >= st.seconds,
                                     'current': bool(self.session_id) and current is st} for st in o.stages],
                            elapsed=sum(min(self.stage_time.get(st.id, 0), st.seconds) for st in o.stages),
                            total=sum(st.seconds for st in o.stages), tolerance=o.tolerance)
            items.append(item)
        return {'session_id': self.session_id, 'objectives': items, 'companion_selected': companion_ok,
                'completed': self.completed, 'reset_reason': self.reset_reason,
                **({'routes': [{'id': r.id, 'label': r.label, 'objectives': list(r.objectives), 'met': self.route_met(r)}
                               for r in self.mission.completion.any_of]} if self.mission.completion else {})}

    def route_objectives(self):
        return {oid for r in self.mission.completion.any_of for oid in r.objectives} if self.mission.completion else set()

    def route_met(self, route):
        common = {o.id for o in self.objectives if not o.optional} - self.route_objectives()
        return all(self.done.get(oid) for oid in common | set(route.objectives))

    def winning_route(self):
        return next((r for r in self.mission.completion.any_of if self.route_met(r)), None) if self.mission.completion else None

    def ready(self):
        if self.mission.completion: return self.winning_route() is not None
        return all(self.done.get(o.id) for o in self.objectives if not o.optional)


class CampaignService:
    """Owns the campaign definitions, the saved progress and the in-memory attempt."""

    def __init__(self, store, book=None, identity=None, clock=time.time):
        self.store, self.clock = store, clock
        self.book = book if book is not None else Book.load()
        self.identity = identity or (lambda model: None)
        self.attempt = None
        self.error = None
        self.notice = None
        # The mission completed in the running session, so its companion can still be told until that session ends.
        self.finished = None
        # Verified mission moments for the companion to react to; the observer hands them to the speech service.
        self.cues = []
        # Mission steps at which the companion is asked to make a settings change (directed missions only).
        self.directives = []
        self.last_report = None
        try:
            raw = store.read(PROGRESS_FILE, MISSING)
            # Only a missing file starts fresh; every existing file, even one holding null, must validate.
            self.progress = Progress() if raw is MISSING else Progress.model_validate(migrate(raw))
        except (ValueError, OSError, ValidationError) as exc:
            self.progress = Progress()
            reason = str(exc) if isinstance(exc, NewerProgressError) else 'Campaign progress could not be read'
            self.error = reason + '. The file was left as it is and the campaign is unavailable; Freeplay is not affected.'
        self._settle_completion(self.progress)
        active = self.progress.active
        if active and not self._mission(active.campaign, active.mission):
            self.progress.active = None  # Its definition is gone (content removed); nothing else changes.
        if self.progress.active:
            active = self.progress.active
            self.attempt = Attempt(self._mission(active.campaign, active.mission), self.record(active.campaign).solved.get(active.mission, ()), self.record(active.campaign).choices.get(active.mission), self.story_flags(self.book.campaign(active.campaign)))

    def _settle_completion(self, progress):
        """Chapter and campaign completion follow from the completed missions under the current definitions:
        a completion reward a completed mission now carries (Chapter 1's, after the version 2 migration) is
        granted with that mission's first completion time. Nothing is written until the next save."""
        for campaign in self.book.campaigns:
            record = progress.campaigns.get(campaign.id)
            if not record: continue
            for mission in campaign.missions:
                entry = record.missions.get(mission.id)
                if not entry: continue
                for reward in mission.rewards:
                    if reward.type in COMPLETION_REWARDS and reward.key not in record.rewards:
                        record.rewards[reward.key] = RewardRecord(earned_at=entry.first_completed_at, mission=mission.id)
            for key, earned in record.rewards.items():
                kind, _, rid = key.partition(':')
                if kind == 'chapter_complete' and rid not in record.chapters: record.chapters[rid] = ChapterRecord(completed_at=earned.earned_at)
                if kind == 'campaign_complete' and rid == campaign.id and not record.completed_at: record.completed_at = earned.earned_at

    # -- lookups
    def _mission(self, campaign_id, mission_id):
        campaign = self.book.campaign(campaign_id)
        return campaign.mission(mission_id) if campaign else None

    def record(self, campaign_id):
        return self.progress.campaigns.get(campaign_id) or CampaignRecord()

    def deck_scope(self):
        """Active Book IDs and saved flag keys only; Freeplay sees keys from every campaign."""
        if self.error: return None, None, frozenset()
        active = self.progress.active
        if active:
            return active.campaign, active.mission, frozenset(self.record(active.campaign).flags)
        return None, None, frozenset(flag for record in self.progress.campaigns.values() for flag in record.flags)

    def companion_unlocked(self, campaign, companion):
        return companion in campaign.starting_companions or f'unlock_companion:{companion}' in self.record(campaign.id).rewards

    def story_flags(self, campaign, attempt=None):
        """The flags a campaign's conditions see: its own saved flags, plus inherited ones as "<campaign>.<flag>"."""
        flags = dict(self.record(campaign.id).flags)
        for cid in campaign.inherits_flags_from:
            flags.update({f'{cid}.{k}': v for k, v in self.record(cid).flags.items()})
        if attempt:
            for o in attempt.objectives:
                selected = next((x for x in o.choice.options if x.id == attempt.choices.get(o.id)), None) if o.choice else None
                if selected: flags.update(selected.sets)
            route = attempt.winning_route()
            if route: flags.update(route.sets)
        return flags

    # Kept in the campaign's records (no save-format change): an older app ignores it and shows the campaign locked.
    UNLOCKED_EARLY = 'unlocked_early_at'

    def campaign_available(self, campaign):
        if campaign.available_from_start: return True
        if self.record(campaign.id).records.get(self.UNLOCKED_EARLY): return True
        return all(self.record(c).completed_at for c in campaign.requires_campaigns)

    def unlock_early(self, campaign_id):
        """The player chose to play a later campaign without finishing the ones it requires (a playtest shortcut).
        Only that campaign opens; the required campaigns' progress is untouched and can still be finished."""
        campaign = self.book.campaign(campaign_id)
        if not campaign: raise ValueError('Unknown campaign.')
        if self.campaign_available(campaign): raise ValueError('This campaign is already open.')
        progress = self.progress.model_copy(deep=True)
        progress.campaigns.setdefault(campaign.id, CampaignRecord()).records[self.UNLOCKED_EARLY] = now_iso(self.clock)
        self._save(progress)

    def mission_state(self, campaign, mission):
        active = self.progress.active
        if active and active.campaign == campaign.id and active.mission == mission.id: return 'active'
        record = self.record(campaign.id)
        if mission.id in record.missions: return 'completed'
        if not self.campaign_available(campaign): return 'locked'
        if all(p in record.missions for p in mission.prerequisites) and self.companion_unlocked(campaign, mission.companion) and evaluate(mission.when, self.story_flags(campaign)):
            return 'available'
        return 'locked'

    def allowed_settings(self):
        """AI Settings Control limit while a mission with one is active; None means unrestricted."""
        if not self.attempt or self.attempt.completed or not self.attempt.mission.settings_control: return None
        limit = self.attempt.mission.settings_control
        if limit.after and self.attempt.done.get(limit.after): return frozenset(limit.then_allowed)
        return frozenset(limit.allowed)

    def settings_directed(self):
        attempt = self.attempt
        return bool(attempt and not attempt.completed and attempt.mission.settings_control and attempt.mission.settings_control.directed)

    def _needs(self, report):
        """What a directed mission needs from the settings right now, from its verified state:
        {'intensity': slider value} for a sequence stage, {'styles': unused styles, 'game': 'off'} for play-style
        stages, {'orgasm': True} once the step that opens the finish is met. Empty when nothing is needed."""
        attempt = self.attempt
        if not self.settings_directed() or not report or attempt.session_id != report.get('session_id'): return {}
        needs = {}
        limit = attempt.mission.settings_control
        for o in attempt.objectives:
            if attempt.done.get(o.id): continue
            if o.type == 'stage_sequence':
                stage = attempt.current_stage(o)
                now = report.get('intensity')
                if stage and stage.intensity is not None and not stage.set_to: needs['intensity'] = stage.intensity - 50
                # A raise is needed only while the level is below it: the player may always go higher or lower again.
                elif stage and stage.raise_to is not None and not stage.set_to and stage.id not in attempt.raised and isinstance(now, int) and now < stage.raise_to: needs['intensity'] = stage.raise_to - 50
            if o.type == 'style_stages':
                filled = attempt.done_styles(o)
                needs['styles'] = [k for k in o.styles if k not in filled]
                needs['game'] = 'off'
        if limit.after and attempt.done.get(limit.after) and 'orgasm' in (limit.then_allowed or ()) and not attempt.done.get(self._finish_id(attempt)):
            needs['orgasm'] = True
        return needs

    @staticmethod
    def _finish_id(attempt):
        return next((o.id for o in attempt.objectives if o.after), None)

    def settings_check(self, request, report):
        """Is this requested change one the directed mission needs? Other missions accept anything allowed."""
        if not self.settings_directed(): return True
        needs, setting, value = self._needs(report), request.get('setting'), request.get('value')
        if setting == 'intensity': return needs.get('intensity') == value
        if setting == 'play_style': return value in needs.get('styles', ()) and value != (report or {}).get('experience')
        if setting == 'game': return 'game' in needs and value == needs['game']
        if setting == 'orgasm': return needs.get('orgasm') is True and value is True
        return False

    def _directive(self, report, key):
        """A mission step at which the companion is asked to change a setting, with a fallback change that meets it."""
        attempt, needs = self.attempt, self._needs(report)
        current = {'intensity': report['intensity'] - 50 if isinstance(report.get('intensity'), int) else None,
                   'style': report.get('experience'), 'goal': report.get('goal'), 'orgasm': details(report).get('orgasm_mode')}
        if 'intensity' in needs and current['intensity'] != needs['intensity']:
            stage = next(attempt.current_stage(o) for o in attempt.objectives if o.type == 'stage_sequence' and not attempt.done.get(o.id))
            level = needs['intensity'] + 50
            if stage.intensity is not None:
                text = (f'Mission step from EdgeLoop: the assessment stage "{stage.label}" runs at {level}% intensity. '
                        f'Set intensity to {needs["intensity"]} now (that is {level}%). No other change is possible.')
                fallback = {'setting': 'intensity', 'value': needs['intensity'], 'reason': f'The {stage.label} stage of my assessment runs at {level}%.'}
            else:
                text = (f'Mission step from EdgeLoop: the "{stage.label}" stage begins, and you raise the intensity for it. '
                        f'Set intensity to {needs["intensity"]} now (that is {level}%). No other change is possible.')
                fallback = {'setting': 'intensity', 'value': needs['intensity'], 'reason': f'{stage.label}: a little more, {level}%.'}
        elif 'styles' in needs and current['goal'] != 'tease':
            text = 'Mission step from EdgeLoop: no stage time counts while a game is on. Set game to "off" now. No other change is possible.'
            fallback = {'setting': 'game', 'value': 'off', 'reason': 'My comparison only counts with the game off.'}
        elif 'styles' in needs and (current['style'] not in needs['styles']):
            options = needs['styles']
            text = ('Mission step from EdgeLoop: the current play style has filled its stage. Switch play_style to one not tested yet: '
                    + ', '.join(options) + '. Pick the one you are most curious about. No other change is possible.')
            fallback = {'setting': 'play_style', 'value': options[0], 'reason': 'Time for the next play style in my comparison.'}
        elif needs.get('orgasm') and current['orgasm'] is not True:
            text = ('Mission step from EdgeLoop: the assessment is complete and the participant may now finish. '
                    'Switch Force Orgasm on now (orgasm true). No other change is possible.')
            fallback = {'setting': 'orgasm', 'value': True, 'reason': 'The assessment is complete; now you may finish.'}
        else:
            return None
        return {'key': key, 'mission': attempt.mission.id, 'companion': attempt.mission.companion, 'session_id': attempt.session_id,
                'generation': attempt.generation, 'text': text, 'fallback': fallback}

    def directive_valid(self, directive, report):
        """Still the same try, and the change it asks for is still needed (the player may have made it already)."""
        attempt = self.attempt
        if self.error or not attempt or attempt.completed or attempt.mission.id != directive['mission']: return False
        if attempt.session_id != directive['session_id'] or attempt.generation != directive['generation']: return False
        if directive.get('scripted'):
            if not report or report.get('status') != 'RUNNING' or report.get('session_id') != attempt.session_id: return False
            level = report.get('intensity')
            return any(o.type == 'stage_sequence' and (st := attempt.current_stage(o)) and st.set_to
                       and f'{o.id}:{st.id}' == directive['key']
                       and (st.raise_to is None or not isinstance(level, int) or level < st.raise_to)  # a floor never lowers
                       for o in attempt.objectives)
        return self.settings_check(directive['fallback'], report) and self._directive(report, directive['key']) is not None

    def directive_current(self, directive):
        """directive_valid against the latest observation the campaign has seen."""
        return self.directive_valid(directive, self.last_report)

    def take_directives(self):
        directives, self.directives = self.directives, []
        return directives

    # -- views
    def state(self, report=None, model=None):
        campaigns = []
        for c in self.book.campaigns:
            record = self.record(c.id)
            narrative = self.book.narratives.get(c.id)
            flags = self.story_flags(c)
            missions = []
            for m in sorted(c.missions, key=lambda m: (m.order, m.id)):
                block = narrative.missions.get(m.id) if narrative else None
                state = self.mission_state(c, m)
                objectives = self.attempt.objectives if state == 'active' and self.attempt else [o for o in m.objectives if evaluate(o.when, flags)]
                missions.append({'id': m.id, 'order': m.order, 'title': m.title, 'summary': m.summary, 'companion': m.companion,
                    'state': state, 'prerequisites': m.prerequisites, 'optional': m.optional,
                    **({'locked_reason': m.locked_reason or 'Not available on this story path.'} if state == 'locked' and not evaluate(m.when, flags) else {}),
                    # Puzzle texts travel only in the attempt view (in session); answer and hint never leave the observer.
                    # Only style_stages uses styles; keep the key on other types without repeating all eight names.
                    'objectives': [o.model_dump(exclude_none=True, exclude={'puzzle', 'choice', 'when'}) |
                        ({'styles': []} if o.type != 'style_stages' else {}) for o in objectives],
                    'rewards': [{'type': r.type, 'id': r.id, 'label': r.label, 'earned': r.key in record.rewards} for r in m.rewards],
                    'session': m.session.model_dump(exclude_none=True) if m.session else None,
                    'settings_control': m.settings_control.model_dump() if m.settings_control else None,
                    'replay': m.replay, 'difficulty': m.difficulty,
                    'completions': record.missions[m.id].completions if m.id in record.missions else 0,
                    'chapter': m.story.chapter if m.story else None,
                    # The briefing and hints are fetched per mission (mission_text): the whole view must stay well under
                    # the observer's 64 KB message limit with several campaigns installed.
                    'narrative_status': block.review_status(narrative.status, flags) if block else ('placeholder' if narrative and narrative.status == 'placeholder' else None),
                    'narrative_draft': bool(block and block.draft(flags))})
            # A story-path exclusion counts like optional content, so an unreachable branch cannot lower progress.
            required = {m.id for m in c.missions if not m.optional and (self.mission_state(c, m) in {'active', 'completed'} or evaluate(m.when, flags))}
            done = sum(1 for mid in required if mid in record.missions)
            total = len(required)
            chapters = []
            for ch in sorted(c.chapters, key=lambda ch: ch.number):
                chapter_members = [m for m in missions if m['chapter'] == ch.number]
                members = [m for m in chapter_members if m['id'] in required]
                chapters.append({'number': ch.number, 'id': ch.id, 'title': ch.title, 'summary': ch.summary, 'teaser': ch.teaser,
                    'completed': ch.id in record.chapters, 'completed_at': record.chapters[ch.id].completed_at if ch.id in record.chapters else None,
                    'available': any(m['state'] != 'locked' for m in chapter_members),
                    'intro': bool(narrative and any(evaluate(b.when, flags) for b in narrative.chapter_intros.get(ch.id, [])) and not ch.teaser),
                    'intro_seen': ch.id in record.intros_seen,
                    'close': bool(narrative and ch.id in narrative.chapters and ch.id in record.chapters and evaluate(narrative.chapters[ch.id].when, flags)),
                    'progress': {'completed': sum(1 for m in members if m['completions']), 'total': len(members)}})
            requires = [{'id': cid, 'title': self.book.campaign(cid).title if self.book.campaign(cid) else cid,
                         'completed': bool(self.record(cid).completed_at)} for cid in c.requires_campaigns]
            available = self.campaign_available(c)
            locked_reason = None if available else 'Complete ' + ' and '.join(r['title'] for r in requires if not r['completed']) + ' to unlock.'
            unlocked_early = bool(record.records.get(self.UNLOCKED_EARLY)) and not all(r['completed'] for r in requires)
            campaigns.append({'id': c.id, 'title': c.title, 'description': c.description, 'artwork': c.artwork, 'chapters': chapters,
                'available': available, 'requires': requires, 'locked_reason': locked_reason,
                'can_unlock_early': not available, 'unlocked_early': unlocked_early, 'completed': bool(record.completed_at), 'completed_at': record.completed_at,
                'progress': {'completed': done, 'total': total}, 'companions': sorted(
                    {m.companion for m in c.missions if self.companion_unlocked(c, m.companion)}),
                'narrative_status': ('placeholder' if narrative.placeholder(flags) else narrative.status) if narrative else None, 'records': dict(record.records), 'flags': dict(record.flags), 'missions': missions})
        active = self.progress.active.model_dump() if self.progress.active else None
        attempt = None
        if self.attempt:
            attempt = self.attempt.view(report, bool(model) and self.identity(model) == self.attempt.mission.companion)
        return {'type': 'campaign_state', 'campaigns': campaigns, 'active': active, 'attempt': attempt,
                'error': self.error, 'notice': self.notice, 'definition_errors': self.book.errors}

    def mission_text(self, campaign_id, mission_id):
        """A mission's briefing and hints, for the briefing screen. Locked missions keep theirs (no spoilers)."""
        campaign = self.book.campaign(campaign_id)
        mission = campaign.mission(mission_id) if campaign else None
        if not mission: raise ValueError('Unknown mission.')
        if self.mission_state(campaign, mission) == 'locked': raise ValueError('This mission is still locked.')
        narrative = self.book.narratives.get(campaign.id)
        block = narrative.missions.get(mission.id) if narrative else None
        briefing = block.public_briefing(self.story_flags(campaign)) if block else None
        return {'type': 'mission_text', 'campaign': campaign.id, 'mission': mission.id, 'hints': list(mission.hints),
                'briefing': briefing,
                'narrative_status': block.review_status(narrative.status, self.story_flags(campaign)) if block else ('placeholder' if narrative and narrative.status == 'placeholder' else None),
                'narrative_draft': bool(block and block.draft(self.story_flags(campaign)))}

    def _chapter(self, campaign_id, chapter_id):
        campaign = self.book.campaign(campaign_id)
        chapter = next((ch for ch in campaign.chapters if ch.id == chapter_id), None) if campaign else None
        if not chapter or chapter.teaser: raise ValueError('Unknown chapter.')
        members = [m for m in campaign.missions if m.story and m.story.chapter == chapter.number]
        if not self.campaign_available(campaign) or not any(self.mission_state(campaign, m) != 'locked' for m in members):
            raise ValueError('This chapter is still locked.')
        return campaign, chapter

    def chapter_text(self, campaign_id, chapter_id):
        """A chapter's intro scene, and its closing block once the chapter is complete (no spoilers before)."""
        campaign, chapter = self._chapter(campaign_id, chapter_id)
        narrative = self.book.narratives.get(campaign.id)
        flags = self.story_flags(campaign)
        intro = [b for b in narrative.chapter_intros.get(chapter.id, []) if evaluate(b.when, flags)] if narrative else []
        close = narrative.chapters.get(chapter.id) if narrative and chapter.id in self.record(campaign.id).chapters else None
        if close and not evaluate(close.when, flags): close = None
        blocks = [*intro, *([close] if close else [])]
        placeholder = bool(narrative and narrative.status == 'placeholder') or any(b.status == 'placeholder' for b in blocks)
        return {'type': 'chapter_text', 'campaign': campaign.id, 'chapter': chapter.id, 'number': chapter.number, 'title': chapter.title,
                'intro': [public_block(b, flags) for b in intro], 'close': public_block(close, flags),
                'narrative_status': 'placeholder' if placeholder else ('draft' if any(b.status == 'draft' for b in blocks) else None),
                'narrative_draft': any(b.status == 'draft' for b in blocks)}

    def intro_seen(self, campaign_id, chapter_id):
        """Record that the chapter's intro has played once; it then no longer starts by itself."""
        campaign, chapter = self._chapter(campaign_id, chapter_id)
        narrative = self.book.narratives.get(campaign.id)
        if not narrative or chapter.id not in narrative.chapter_intros: raise ValueError('This chapter has no intro.')
        if chapter.id in self.record(campaign.id).intros_seen: return
        progress = self.progress.model_copy(deep=True)
        progress.campaigns.setdefault(campaign.id, CampaignRecord()).intros_seen[chapter.id] = now_iso(self.clock)
        self._save(progress)

    # -- commands
    def _save(self, progress):
        if self.error: raise ValueError(self.error)
        self.store.write(PROGRESS_FILE, progress.model_dump(mode='json'))
        self.progress = progress

    def start(self, campaign_id, mission_id, report=None):
        if self.error: raise ValueError(self.error)
        campaign = self.book.campaign(campaign_id)
        mission = campaign.mission(mission_id) if campaign else None
        if not mission: raise ValueError('Unknown mission.')
        if report and report.get('status') in LIVE: raise ValueError('Stop the current session before starting a mission.')
        state = self.mission_state(campaign, mission)
        if state == 'locked': raise ValueError('This mission is still locked.')
        if state == 'completed' and mission.replay != 'allowed': raise ValueError('This mission cannot be replayed.')
        progress = self.progress.model_copy(deep=True)
        progress.active = ActiveMission(campaign=campaign.id, mission=mission.id, started_at=now_iso(self.clock))
        if state == 'completed': progress.campaigns[campaign.id].choices.pop(mission.id, None)
        self._save(progress)
        self.attempt = Attempt(mission, self.record(campaign.id).solved.get(mission.id, ()), self.record(campaign.id).choices.get(mission.id), self.story_flags(campaign))
        self.notice = None
        self.finished = None
        self.directives = []

    # -- what the companion is told
    def _cue(self, kind, mission, session_id, objective=None):
        campaign = self.book.campaign(self.progress.active.campaign if self.progress.active else self.finished['campaign'])
        return {'kind': kind, 'campaign': campaign.id, 'campaign_title': campaign.title, 'mission': mission.id,
                'mission_title': mission.title, 'order': mission.order, 'companion': mission.companion,
                'session_id': session_id, 'objective': objective.label if objective else None,
                'generation': self.attempt.generation if self.attempt else None,
                'campaign_complete': bool(kind == 'mission_complete' and self.finished and self.finished['campaign_complete']),
                'chapter': self.finished.get('chapter') if kind == 'mission_complete' and self.finished else None,
                **({'route': self.finished['route']} if kind == 'mission_complete' and self.finished and self.finished.get('route') else {})}

    def take_cues(self):
        cues, self.cues = self.cues, []
        return cues

    def model_context(self, model, report):
        """A short factual brief for the mission's own companion, or None. Every value in it is the campaign's
        verified state; it gives the companion the story frame and never a way to complete anything."""
        if self.error or not report: return None
        companion = self.identity(model)
        sid, status = report.get('session_id'), report.get('status')
        finished = self.finished
        if finished and finished['session_id'] == sid and sid is not None:
            mission = self._mission(finished['campaign'], finished['mission'])
            campaign = self.book.campaign(finished['campaign'])
            if not mission or mission.companion != companion: return None
            lines = [f'Campaign story: {campaign.title}, Mission {mission.order}, "{mission.title}". In this story you set the participant this mission.',
                     'Verified by EdgeLoop: the mission is complete and saved. The participant has already seen your completion message.']
            if finished.get('chapter'): lines.append(f'This mission completes the chapter "{finished["chapter"]}".')
            if finished['campaign_complete']: lines.append('This was the final mission: the campaign is complete.')
            if finished.get('route'): lines.append('Route taken: ' + finished['route']['label'] + '.')
            for o in mission.objectives:
                if o.id not in finished['objectives']: continue
                # Only that it was answered: a model repeats an answer's words (live checks 2026-11-20).
                selected = next((x for x in o.choice.options if x.id == self.record(campaign.id).choices.get(mission.id, {}).get(o.id)), None) if o.choice else None
                if selected: lines.append('The participant answered a question in this mission.')
            lines.append('The session is still running; completing the mission does not end it, so carry on with the session as usual.'
                         if status in LIVE else 'The session has ended.')
            return {'companion': companion, 'mission': mission.id, 'state': 'completed', 'text': '\n'.join(lines),
                    'targets': sorted({o.count for o in mission.objectives if o.id in finished['objectives'] and o.type == 'edge_count' and o.count})}
        attempt = self.attempt
        if not attempt or attempt.completed or attempt.mission.companion != companion: return None
        mission = attempt.mission
        campaign = self.book.campaign(self.progress.active.campaign)
        goals = [o for o in attempt.objectives if o.type in GOAL_TYPES and o.id not in attempt.route_objectives()]
        mission_story = self.book.narratives.get(campaign.id).missions.get(mission.id) if self.book.narratives.get(campaign.id) else None
        # A mission with its own director_context leaves its title out: quoted, the title was repeated in dialogue
        # ('this "Breach Detected" farce', live checks 2026-11-20), even next to a rule not to say it. Missions
        # without one (Asterion) keep the title as their only description, as approved and played.
        titled = not (mission_story and mission_story.director_context)
        named = f', Mission {mission.order}, "{mission.title}"' if titled else f', Mission {mission.order}'
        lines = [f'Campaign story: {campaign.title}{named}. In this story you set the participant this mission, and they have read your briefing for it.',
                 # Choice labels ("Answer Seraphine") are panel prompts; a model repeats them, so they are not listed.
                 'The goal (EdgeLoop checks it, not you): ' + '; '.join([o.label for o in goals if o.type != 'choice']
                     + (['answer the questions in the mission panel'] if any(o.type == 'choice' for o in goals) else [])) + '.']
        if mission.completion: lines.append('This mission has more than one way to finish; EdgeLoop checks the completion.')
        if attempt.session_id == sid and sid is not None and status in LIVE:
            done = [o.label for o in goals if attempt.done.get(o.id) and o.type != 'choice']
            progress = []
            for o in goals: progress += self._progress_words(attempt, o, report)
            lines.append('Verified progress in this session: ' + (', '.join(progress) if progress else 'not complete yet') + '.'
                         + (' Already reached: ' + '; '.join(done) + '.' if done else ''))
            lines.append('The mission is not complete yet. Do not say it is, and do not end or pause the session for it.')
        else:
            need = 'a session with you, with a heart-rate monitor and a toy connected'
            mode = mission.session.active_mode if mission.session else None
            if mode: need += f', in {MODE_WORDS.get(mode, mode)} mode'
            lines.append(f'The mission session has not started. To begin, the participant starts {need}. Nothing counts toward it yet.')
        block = (self.book.narratives.get(campaign.id).missions.get(mission.id) if self.book.narratives.get(campaign.id) else None)
        if block and block.director_context: lines.append(block.director_context)
        if block:
            # Saved story only: a choice or route taken during this try is not history until completion saves it.
            history = next((rule.text for rule in block.story_so_far if evaluate(rule.when, self.story_flags(campaign))), None)
            if history: lines.append('Story so far: ' + history)
        if mission.review: lines.append(self._review_words(campaign, mission))
        if any(o.type == 'puzzle_solved' for o in attempt.objectives):
            lines.append('The participant works these questions out in EdgeLoop\'s mission panel, and EdgeLoop checks each answer. '
                         'You do not know the answers: never state, guess or confirm one; encourage and think aloud instead. '
                         'In the story never call them a puzzle, a riddle or a panel.')
        lines.append('If the participant asks what to do or how they are doing, answer from these lines. '
                     + ('Speak of the mission in your own words, as part of the story; do not quote its title like a label.' if titled
                      else 'Speak of the mission in your own words, as part of the story, never by a menu label.'))
        # How another mission is named, so talk of an earlier one is not read as a claim about this one.
        others = sorted({w for m in campaign.missions if m.id != mission.id for w in (m.title, f'Mission {m.order}')}
                        | {w for m in campaign.missions if m.companion != companion for w in (m.companion, *COMPANION_ALIASES.get(m.companion, ()))})
        return {'companion': companion, 'mission': mission.id, 'state': 'active', 'text': '\n'.join(lines),
                'targets': sorted({o.count for o in goals if o.type == 'edge_count' and o.count}), 'others': others,
                'mission_words': list(campaign.mission_words),
                'durations': self._durations(attempt, report) if attempt.session_id == sid and sid is not None else []}

    @staticmethod
    def _durations(attempt, report):
        """The mission's verified clocks, each with the words that name it, so a companion can state one even when
        the whole-session clock is longer, and a claim is checked against the clock it actually names.
        A clock: seconds, remaining (time left rather than time done), names, rank (a more specific name wins)
        and generic (it also answers a clause that names no clock, such as "this stage")."""
        clocks = []
        def add(seconds, names, rank, remaining=False, generic=False):
            if isinstance(seconds, int) and seconds >= 0:
                clocks.append({'seconds': seconds, 'remaining': remaining, 'names': sorted({n.lower() for n in names if n}),
                               'rank': rank, 'generic': generic})
        ordinals = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth')
        numbers = ('one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight')
        for item in attempt.view(report, True)['objectives']:
            if item['id'] in attempt.route_objectives(): continue
            whole = {item['id'], *DURATION_TOTAL_WORDS}
            stages = item.get('stages', ())
            if item['type'] == 'stage_sequence':
                add(item['elapsed'], whole, 1)
                add(item['total'] - item['elapsed'], whole, 1, remaining=True)
                for i, st in enumerate(stages):
                    names = {st['id'], st['label']}
                    for word in ('stage', 'phase'):
                        if i < len(ordinals): names |= {f'{ordinals[i]} {word}', f'{word} {numbers[i]}', f'{word} {i + 1}'}
                        if i == len(stages) - 1: names |= {f'final {word}', f'last {word}'}
                        if st['current']: names |= {f'this {word}', f'current {word}'}
                    add(st['elapsed'], names, 2, generic=st['current'])
                    add(st['seconds'] - st['elapsed'], names, 2, remaining=True, generic=st['current'])
            elif item['type'] == 'style_stages':
                add(item['elapsed'], whole | {'styles', 'play styles'}, 1)
                for st in stages:
                    names = {st['style'], st['label']} | ({'this style', 'current style', 'this play style', 'current play style'} if st.get('current') else set())
                    add(st['seconds'], names, 2, generic=bool(st.get('current')))
                    if st.get('current'): add(item['stage_seconds'] - st['seconds'], names, 2, remaining=True, generic=True)
            # A countdown: its limit and the verified time left ("ten minutes left").
            if item.get('within_seconds'):
                add(item['within_seconds'], {item['id'], 'limit', 'deadline', 'countdown', 'window', 'within'}, 1)
                add(item.get('remaining'), {item['id'], 'deadline', 'countdown', 'clock'}, 1, remaining=True, generic=True)
        return clocks

    @staticmethod
    def _progress_words(attempt, o, report):
        clock = lambda n: f'{n // 60}:{n % 60:02d}'
        n = attempt.counts.get(o.id, 0)
        def timed(words):
            if o.within_seconds is None or attempt.done.get(o.id): return words
            if o.id in attempt.expired: return words + f' (the {clock(o.within_seconds)} ran out for this try; the next session starts a fresh clock)'
            return words + f' ({clock(attempt.remaining(o))} of the {clock(o.within_seconds)} left; pauses stop the clock)'
        if o.type == 'edge_count': return [timed(f'{min(n, o.count)} of {o.count} edges')]
        if o.type == 'orgasm_count':
            words = f'{min(n, o.count)} of {o.count} reported orgasm' + ('s' if o.count > 1 else '')
            if o.after and not attempt.done.get(o.after): words += ' (only counted once the earlier goal is reached)'
            return [timed(words)]
        if o.type == 'choice':
            chosen = next((x for x in o.choice.options if x.id == attempt.choices.get(o.id)), None)
            # No quoted text at all: a model repeats an answer's words and even the objective's label ("'Answer
            # Seraphine' was the variable", live checks 2026-11-20). What the answer means reaches it through the
            # option's direction in the moment card.
            return ['a question for the participant: answered' if chosen
                    else 'a question for the participant is waiting; they answer it themselves, so do not ask it for them']
        if o.type == 'puzzle_solved':
            # Live checks 2026-11-20: 'puzzle "Your badge": open now' became "the badge puzzle" in dialogue and was read as
            # solved. The status is spelled out, and the game word stays out of the story.
            subject = o.puzzle.title.lower()
            if o.id in attempt.solved: return [f'they have worked out the question about {subject} (verified)']
            if attempt.puzzle_open(o): return [f'they are still working out the question about {subject}: NOT solved yet, so never say or imply they have worked it out']
            return [f'the question about {subject} has not come up yet']
        if o.type == 'style_stages':
            filled = attempt.done_styles(o)
            words = f'{len(filled)} of {o.count} play-style stages complete' + (' (' + ', '.join(STYLE_WORDS.get(k, k) for k in filled) + ')' if filled else '')
            style = report.get('experience')
            if report.get('goal') != 'tease': words += '; a game is on, so no stage time counts until it is switched off'
            elif style in filled: words += f'; the current play style, {STYLE_WORDS.get(style, style)}, has already filled a stage, so the participant should switch to a new one'
            elif style in o.styles: words += f'; current play style {STYLE_WORDS.get(style, style)}: {clock(min(attempt.style_time.get(style, 0), o.seconds))} of {clock(o.seconds)}'
            return [words]
        if o.type == 'stage_sequence':
            stage = attempt.current_stage(o)
            if not stage: return ['all assessment stages complete']
            number = o.stages.index(stage) + 1
            at = f', at {stage.intensity}% intensity' if stage.intensity is not None else ''
            words = (f'stage {number} of {len(o.stages)}, "{stage.label}"{at}: '
                     f'{clock(attempt.stage_time.get(stage.id, 0))} of {clock(stage.seconds)}')
            now = report.get('intensity')
            if stage.intensity is not None and isinstance(now, int) and abs(now - stage.intensity) > o.tolerance:
                words += f'; intensity is now {now}%, so this stage\'s clock is paused until the participant sets {stage.intensity}%'
            return [words]
        return []

    def _review_words(self, campaign, mission):
        """What the saved progress verifies about the missions under review: completion, and kept results."""
        record = self.record(campaign.id)
        parts = []
        for mid in mission.review:
            m = campaign.mission(mid)
            if mid not in record.missions:
                parts.append(f'Mission {m.order} "{m.title}" ({m.companion}): no completion on record'); continue
            facts = []
            for o in m.objectives:
                value = record.records.get(f'{mid}.{o.id}')
                if value in (None, ''): continue
                facts.append(f'{value} edges' if o.type == 'edge_count' else f'{value} reported orgasms' if o.type == 'orgasm_count' else f'play styles {value}' if o.type == 'style_stages' else str(value))
            parts.append(f'Mission {m.order} "{m.title}" ({m.companion}): completed' + (' with ' + ', '.join(facts) if facts else ', with no further detail on record'))
        return 'Reports on file (saved by EdgeLoop, the only evidence you have): ' + '; '.join(parts) + '.'

    def answer(self, objective_id, option_id, report, model):
        """A puzzle answer from the mission panel. The campaign checks it against its own definition; nothing a model
        says is involved. A wrong pick only shows the hint (try again as often as needed). A right one is saved first,
        then announced. Returns messages to publish; raises ValueError for an answer that cannot be taken now."""
        attempt = self.attempt
        if self.error: raise ValueError(self.error)
        if not attempt or attempt.completed: raise ValueError('No mission is in progress.')
        o = next((x for x in attempt.objectives if x.id == objective_id and x.type in {'puzzle_solved', 'choice'}), None)
        if not o: raise ValueError('Unknown puzzle or choice.')
        if o.type == 'choice':
            if o.id in attempt.choices: raise ValueError('That choice is already answered.')
            if not attempt.choice_open(o): raise ValueError('That choice is not available before its stage.')
            if option_id not in {x.id for x in o.choice.options}: raise ValueError('Unknown choice option.')
        if o.id in attempt.solved: raise ValueError('That puzzle is already solved.')
        if o.type == 'puzzle_solved' and not attempt.puzzle_open(o): raise ValueError('Solve the earlier puzzle first.')
        if self.identity(model) != attempt.mission.companion: raise ValueError('The puzzles count with the mission companion selected.')
        if not report or attempt.session_id is None or attempt.session_id != report.get('session_id') or report.get('status') not in LIVE:
            raise ValueError('Start the mission session first; the puzzles are solved during it.')
        if report.get('status') != 'RUNNING': raise ValueError('Resume the session to answer; puzzles are solved while it runs.')
        if not (real_hr(report) and toy_ready(report) and self._mode_ok(attempt.mission, report)):
            raise ValueError('The puzzles count only with your heart-rate monitor (not the simulator) and toy connected.')
        if o.type == 'puzzle_solved':
            z = o.puzzle
            if z.kind == 'code':
                if not isinstance(option_id, str) or code_controls(option_id): raise ValueError('Malformed code answer.')
                submitted = normalize_code(option_id)
                if not submitted or len(submitted) > z.max_length or code_controls(submitted): raise ValueError('Malformed code answer.')
                if self.clock() < attempt.code_blocked.get(o.id, 0): raise ValueError('Too many attempts. Wait a moment.')
                correct = submitted == normalize_code(z.answer_code)
            else:
                if not isinstance(option_id, str) or len(option_id) > 64 or not re.fullmatch(r'[a-z0-9][a-z0-9_.-]*', option_id): raise ValueError('Malformed puzzle answer.')
                correct = option_id == z.answer
            if not correct:
                attempt.acknowledge_clues(o)
                # Never echo code submissions, even wrong ones containing part of the real code.
                attempt.wrong[o.id] = True if z.kind == 'code' else option_id
                if z.kind == 'code':
                    attempt.code_revision[o.id] = attempt.code_revision.get(o.id, 0) + 1
                    count = attempt.code_failures.get(o.id, 0) + 1
                    attempt.code_failures[o.id] = count
                    if count >= 5:
                        attempt.code_blocked[o.id] = self.clock() + 10
                        attempt.code_failures[o.id] = 0
                return [self.progress_update(report, model)]
        progress = self.progress.model_copy(deep=True)
        record = progress.campaigns.setdefault(progress.active.campaign, CampaignRecord())
        if o.type == 'choice': record.choices.setdefault(attempt.mission.id, {})[o.id] = option_id
        else: record.solved[attempt.mission.id] = [*record.solved.get(attempt.mission.id, []), o.id]
        self._save(progress)
        if o.type == 'choice': attempt.choices[o.id] = option_id
        else:
            attempt.solved.add(o.id); attempt.acknowledge_clues(o)
            if o.puzzle.kind == 'code': attempt.code_revision[o.id] = attempt.code_revision.get(o.id, 0) + 1
        attempt.done[o.id] = True; attempt.wrong.pop(o.id, None)
        keys = ([f'{o.id}:{option_id}'] if o.type == 'choice' else []) + [f'{o.id}:done']
        lines = self._moments(attempt, keys)
        if attempt.ready():
            attempt.pending_lines += lines
            result = self._complete(attempt)
            if not result: return [self.state(report, model)]
            self.cues.append(self._cue('mission_complete', attempt.mission, attempt.session_id))
            return [*lines, self.state(report, model), result]
        if o.type == 'choice' and any(key in attempt.marked for key in keys): attempt.cued.add(o.id)
        return [self.progress_update(report, model), *lines]

    SWITCH_LOCKED = 'Switching companions is locked during a mission. Choose Freeplay in the main menu to leave the mission and switch freely.'

    def switch_refusal(self, target, current):
        """While a mission is active only its companion can be selected (Freeplay leaves the mission first).
        `target`/`current` are personas: a model name, or 'custom:<identity>' for a custom character."""
        active = self.progress.active
        if not active or target == current: return None
        campaign = self.book.campaign(active.campaign)
        mission = campaign.mission(active.mission) if campaign else None
        if mission and self.identity(target) == mission.companion: return None
        return self.SWITCH_LOCKED

    def abandon(self):
        progress = self.progress.model_copy(deep=True)
        progress.active = None
        self._save(progress)
        self.attempt = None
        self.cues = []
        self.directives = []

    # -- evidence
    def observe(self, report, events, model):
        """Called after the observer accepted an observation. Returns messages to publish (state changes, results)."""
        if report: self.last_report = report
        if self.error or not self.attempt or self.attempt.completed or not report: return []
        attempt, mission = self.attempt, self.attempt.mission
        if attempt.pending:
            # A completion that could not be saved is retried first; no later report can undo it.
            result = self._complete(attempt)
            if not result: return []
            self.cues.append(self._cue('mission_complete', mission, attempt.session_id))
            return [*attempt.pending_lines, self.state(report, model), result]
        before = json.dumps(attempt.view(report, False), sort_keys=True)
        companion_ok = self.identity(model) == mission.companion
        sid, status, d = report.get('session_id'), report.get('status'), details(report)
        kinds = {e for e in events}
        out = []
        if attempt.session_id and sid != attempt.session_id:
            self._reset(attempt, 'session_changed')
        # Adopt the mission session: running, with the mission's companion, a real heart-rate monitor, a toy
        # and the required engine mode. Each condition is the engine's own reported state.
        moments = []
        if attempt.session_id is None and status == 'RUNNING' and companion_ok:
            if real_hr(report) and toy_ready(report) and self._mode_ok(mission, report):
                attempt.session_id = sid
                attempt.last_edges, attempt.last_orgasms = report.get('edges', 0), d.get('orgasm_count') or 0
                attempt.last_seconds, attempt.last_config, attempt.last_captured = None, None, None
                attempt.base_seconds = report.get('seconds') if isinstance(report.get('seconds'), int) else 0
                attempt.reset_reason = None
                for o in attempt.objectives:
                    if o.type in {'hr_monitor_connected', 'toy_connected', 'session_started'}: attempt.done[o.id] = True
                moments.append('start')
        if attempt.session_id == sid and attempt.session_id is not None:
            edges, orgasms = report.get('edges', 0), d.get('orgasm_count') or 0
            # Evidence counts only while every mission condition still holds: the mission companion, a real
            # heart-rate monitor (not the simulator), a toy and the mission's mode. Activity without them only
            # moves the baselines on, so it can never count later.
            eligible = companion_ok and real_hr(report) and toy_ready(report) and self._mode_ok(mission, report)
            # An orgasm is a rise of the engine's counter (I came; Finished me in Survival and Calibration, once
            # confirmed) or an accepted Came Early, which ends the session without raising it. Each is its own report.
            # The completion_reported flag is never evidence: Finished me sets it before its confirm, so a
            # cancelled Finished me leaves it set (then Edged ends Calibration with no orgasm).
            new_orgasms = max(0, orgasms - attempt.last_orgasms) + (1 if 'came_early' in kinds else 0)
            new_edges = max(0, edges - attempt.last_edges)
            met_before = {k for k, v in attempt.done.items() if v}
            seconds = report.get('seconds')
            before_elapsed = attempt.elapsed()
            now_elapsed = max(0, seconds - attempt.base_seconds) if isinstance(seconds, int) and attempt.base_seconds is not None else before_elapsed
            late = lambda o: o.within_seconds is not None and (o.id in attempt.expired or now_elapsed > o.within_seconds)
            if eligible:
                attempt.edges += new_edges
                attempt.orgasms += new_orgasms
                for o in attempt.objectives:
                    # An `after` objective counts only events that come once its predecessor was already met.
                    if o.type not in COUNTED or (o.after and o.after not in met_before) or late(o): continue
                    new = new_edges if o.type == 'edge_count' else new_orgasms
                    old = attempt.counts.get(o.id, 0)
                    attempt.counts[o.id] = old + new
                    moments += [f'{o.id}:{n}' for n in o.milestones if old < n <= old + new]
            # Counters only grow inside a session; an IDLE reset to 0 must not count backwards or double.
            attempt.last_edges, attempt.last_orgasms = max(attempt.last_edges, edges), max(attempt.last_orgasms, orgasms)
            moments += self._credit_time(attempt, report, eligible)
            for o in attempt.objectives:
                stage = attempt.current_stage(o) if o.type == 'stage_sequence' else None
                if stage and stage.set_to and eligible and status == 'RUNNING' and (o.id, stage.id) not in attempt.set_sent:
                    attempt.set_sent.add((o.id, stage.id))
                    level = stage.intensity if stage.intensity is not None else stage.raise_to
                    # A floor only ever raises: a player already at or above it keeps their level.
                    if stage.intensity is not None or (isinstance(report.get('intensity'), int) and report['intensity'] < level):
                        self.directives.append({'scripted': True, 'key': f'{o.id}:{stage.id}', 'mission': mission.id,
                            'companion': mission.companion, 'session_id': attempt.session_id, 'generation': attempt.generation,
                            'fallback': {'setting': 'intensity', 'value': level - 50,
                                         'reason': f'{mission.title}: {stage.label} stage, ' + (f'{level}%.' if stage.intensity is not None else f'at least {level}%.')}})
                if stage and stage.raise_to is not None and isinstance(report.get('intensity'), int) and report['intensity'] >= stage.raise_to:
                    attempt.raised.add(stage.id)
            for o in attempt.objectives:
                if o.within_seconds is None or o.id in attempt.expired or attempt.counts.get(o.id, 0) >= o.count: continue
                if now_elapsed > o.within_seconds:
                    # Time is up for this try; nothing more counts toward it until the next session.
                    attempt.expired.add(o.id); moments.append(f'{o.id}:expired')
                else:
                    moments += [f'{o.id}:left{w}' for w in o.warnings if o.within_seconds - before_elapsed > w >= o.within_seconds - now_elapsed]
            # Stop pressed during the ease-down that follows a confirmed Finished me: the max is already saved
            # (calibration_saved is set only after the confirm) and the orgasm was counted in this try, so the
            # run counts as completed. Edged alone counts no orgasm, and a cancelled Finished me saves nothing.
            stopped_after_save = (d.get('terminal_outcome') == 'manual_stop' and d.get('calibration_saved') is True
                                  and attempt.orgasms >= 1)
            calibrated = d.get('terminal_outcome') == 'calibration_completed' or 'completion_accepted' in kinds or stopped_after_save
            ended_ok = companion_ok and real_hr(report) and self._mode_ok(mission, report)
            for o in attempt.objectives:
                if o.type in COUNTED and attempt.counts.get(o.id, 0) >= o.count: attempt.done[o.id] = True
                if o.type == 'style_stages' and len(attempt.done_styles(o)) >= o.count: attempt.done[o.id] = True
                if o.type == 'stage_sequence' and attempt.current_stage(o) is None: attempt.done[o.id] = True
                if o.type == 'puzzle_solved' and o.id in attempt.solved: attempt.done[o.id] = True
                if o.type == 'choice' and o.id in attempt.choices: attempt.done[o.id] = True
                if o.type == 'calibration_completed' and calibrated and ended_ok: attempt.done[o.id] = True
                if o.type == 'calibration_saved' and calibrated and ended_ok and d.get('calibration_saved') is True:
                    metric = d.get('dual_max_bpm') if d.get('calibration_pass') == 'dual' else d.get('single_max_bpm')
                    if isinstance(metric, int):
                        attempt.done[o.id] = True
                        attempt.metric = {'calibration_pass': d.get('calibration_pass'), 'max_bpm': metric}
            moments += [f'{o.id}:done' for o in attempt.objectives if o.type in GOAL_TYPES and attempt.done.get(o.id) and o.id not in met_before]
            if attempt.ready():
                # Milestones crossed by the same jump that completes the mission still get their lines, once,
                # and only after the completion is saved. (Built first: the active mission is cleared on save.)
                attempt.pending_lines += self._moments(attempt, moments)
                result = self._complete(attempt)
                if result:
                    out += attempt.pending_lines
                    out.append(result)
                    self.cues.append(self._cue('mission_complete', mission, sid))
            elif status == 'IDLE':
                # The session ended before the mission was done: the next session starts the counts again.
                # Time running out in that same last report still gets its line, before the try is reset.
                out += self._moments(attempt, [m for m in moments if m.endswith(':expired')])
                self._reset(attempt, 'session_ended')
            else:
                out += self._moments(attempt, moments)
                if moments and companion_ok and status == 'RUNNING' and self.settings_directed():
                    directive = self._directive(report, moments[-1])
                    if directive: self.directives = [d for d in self.directives if d.get('scripted')] + [directive]  # retain one-shot stage requests
                if companion_ok and not any(o.type == 'calibration_completed' for o in attempt.objectives):
                    # A goal reached while another still remains; setup items (strap, toy, session) are not story moments.
                    # In Calibration, Finished me reports the orgasm and ends the run a moment later: one moment, one card.
                    # A goal with its own scripted line is marked by that line, not also by the model.
                    scripted = self._narrative(mission)
                    for o in attempt.objectives:
                        if o.type in GOAL_TYPES and attempt.done.get(o.id) and o.id not in attempt.cued:
                            attempt.cued.add(o.id)
                            if scripted and f'{o.id}:done' in scripted.milestones.keys() | scripted.directions.keys(): continue
                            self.cues.append(self._cue('objective_reached', mission, sid, o))
        elif moments:
            out += self._moments(attempt, moments)
        if any(m['type'] == 'mission_result' for m in out):
            # The new state (no active mission) goes right before the result: milestone lines crossed by the
            # completing report come first, while the browser still shows the mission as active.
            out.insert(next(i for i, m in enumerate(out) if m['type'] == 'mission_result'), self.state(report, model))
        elif json.dumps(attempt.view(report, False), sort_keys=True) != before:
            # Only the try changed (a count, a stage clock): a small update, not the whole campaign view,
            # since stage clocks change every second.
            out.insert(0, self.progress_update(report, model))
        return out

    def progress_update(self, report=None, model=None):
        attempt = self.attempt.view(report, bool(model) and self.identity(model) == self.attempt.mission.companion) if self.attempt else None
        return {'type': 'campaign_progress', 'active': self.progress.active.model_dump() if self.progress.active else None,
                'attempt': attempt, 'notice': self.notice}

    def _credit_time(self, attempt, report, eligible):
        """Credit active running time to the play style or stage in effect. An interval counts only when the
        observations at both ends were running, eligible and in the same configuration, so a pause, a setting
        change or a gap makes that interval count for nothing. Returns the progress moments reached."""
        seconds = report.get('seconds')
        config = (report.get('status'), report.get('experience'), report.get('goal'), report.get('intensity'), bool(eligible))
        captured = details(report).get('captured_at_ms')
        last_seconds, last, last_captured = attempt.last_seconds, attempt.last_config, attempt.last_captured
        attempt.last_seconds, attempt.last_config, attempt.last_captured = seconds, config, captured
        if not isinstance(seconds, int) or not isinstance(last_seconds, int) or not last: return []
        step = seconds - last_seconds
        if not 0 < step <= MAX_STEP_SECONDS or not (config[4] and last[4]) or config[0] != 'RUNNING' or last[0] != 'RUNNING': return []
        # The two observations must also be close in capture time: after a reconnect or an unobserved gap
        # (which may hold a pause), the running clock alone cannot show what happened in between.
        # A client that sends no capture times (an old one, details: null) gets no mission time at all.
        if not (isinstance(captured, int) and isinstance(last_captured, int)) or not 0 < captured - last_captured <= (MAX_STEP_SECONDS + 2) * 1000: return []
        moments = []
        for o in attempt.objectives:
            if attempt.done.get(o.id): continue
            if o.type == 'style_stages':
                style = config[1]
                # One play style fills at most one stage; with a game on (anything but a plain tease) nothing counts.
                if style != last[1] or style not in o.styles or config[2] != 'tease' or last[2] != 'tease': continue
                filled = attempt.filled.setdefault(o.id, [])
                if style in filled: continue
                attempt.style_time[style] = attempt.style_time.get(style, 0) + step
                if attempt.style_time[style] >= o.seconds:
                    filled.append(style)
                    if len(filled) < o.count: moments.append(f'{o.id}:{len(filled)}')
            if o.type == 'stage_sequence':
                stage = attempt.current_stage(o)
                ok = lambda v: stage.intensity is None or isinstance(v, int) and abs(v - stage.intensity) <= o.tolerance
                if not stage or not (ok(config[3]) and ok(last[3])): continue
                attempt.stage_time[stage.id] = min(stage.seconds, attempt.stage_time.get(stage.id, 0) + step)
                following = attempt.current_stage(o)
                if attempt.stage_time[stage.id] >= stage.seconds and following: moments.append(f'{o.id}:{following.id}')
        return moments

    def _narrative(self, mission):
        campaign_id = self.progress.active.campaign if self.progress.active else None
        narrative = self.book.narratives.get(campaign_id) if campaign_id else None
        return narrative.missions.get(mission.id) if narrative else None

    def _moments(self, attempt, keys):
        """Once per try: send a scripted line to the player, or queue its private model direction."""
        attempt.fired.update(keys)
        block = self._narrative(attempt.mission)
        out = []
        for key in keys:
            if key in attempt.marked or not block: continue
            if key in block.directions:
                attempt.marked.add(key)
                objective = next((o for o in attempt.objectives if o.id == key.split(':', 1)[0]), None)
                cue = self._cue('moment', attempt.mission, attempt.session_id, objective) | {'key': key, 'direction': block.directions[key]}
                if objective and objective.choice and objective.id in attempt.choices:
                    cue['chosen_label'] = next(x.label for x in objective.choice.options if x.id == attempt.choices[objective.id])
                self.cues.append(cue)
                continue
            if key not in block.milestones: continue
            attempt.marked.add(key)
            line = public_block(block.milestones[key], self.story_flags(self.book.campaign(self.progress.active.campaign), attempt))
            if not line: continue
            out.append({'type': 'mission_milestone', 'campaign': self.progress.active.campaign, 'mission': attempt.mission.id,
                        'key': key, 'session_id': attempt.session_id, 'line': line})
        return out

    @staticmethod
    def _mode_ok(mission, report):
        return not mission.session or not mission.session.active_mode or report.get('active_mode') == mission.session.active_mode

    def cue_valid(self, cue):
        """Is a queued mission moment still true? A completion stays true for its session; a goal reached
        belongs to one try, so a reset, an abandon or a completed mission makes it stale."""
        if self.error: return False
        if cue['kind'] == 'mission_complete':
            return bool(self.finished and self.finished['mission'] == cue['mission'] and self.finished['session_id'] == cue['session_id'])
        attempt = self.attempt
        return bool(attempt and not attempt.completed and attempt.mission.id == cue['mission'] and attempt.session_id == cue['session_id']
                    and attempt.generation == cue.get('generation'))

    def _reset(self, attempt, reason):
        attempt.session_id = None; attempt.done = {}; attempt.edges = attempt.orgasms = 0
        attempt.last_edges = attempt.last_orgasms = None; attempt.metric = None; attempt.reset_reason = reason
        attempt.counts = {}; attempt.style_time = {}; attempt.stage_time = {}; attempt.filled = {}; attempt.marked = set()
        attempt.last_seconds = attempt.last_config = attempt.last_captured = None; attempt.base_seconds = None; attempt.expired = set(); attempt.wrong = {}; attempt.raised = set(); attempt.set_sent = set()
        attempt.code_failures = {}; attempt.code_blocked = {}; attempt.code_revision = {}; attempt.fired = set(); attempt.clue_seen = {}
        attempt.cued = set(); attempt.generation += 1
        campaign = self.book.campaign(self.progress.active.campaign)
        attempt.objectives = [o for o in attempt.mission.objectives if evaluate(o.when, self.story_flags(campaign))]
        self.directives = []

    def _complete(self, attempt):
        """Persist first, then announce. A failed write announces nothing and retries on the next observation."""
        active = self.progress.active
        campaign = self.book.campaign(active.campaign)
        mission = attempt.mission
        text_flags = self.story_flags(campaign, attempt)
        route = attempt.winning_route()
        progress = self.progress.model_copy(deep=True)
        record = progress.campaigns.setdefault(campaign.id, CampaignRecord())
        record.solved.pop(mission.id, None)
        if route: record.routes[mission.id] = route.id
        stamp = now_iso(self.clock)
        replay = mission.id in record.missions
        if replay:
            entry = record.missions[mission.id]
            entry.completions += 1; entry.last_completed_at = stamp
        else:
            record.missions[mission.id] = MissionRecord(completions=1, first_completed_at=stamp, last_completed_at=stamp)
        earned = []
        for reward in mission.rewards:
            if reward.key in record.rewards: continue  # Idempotent: a replay or a retry never grants twice.
            record.rewards[reward.key] = RewardRecord(earned_at=stamp, mission=mission.id)
            earned.append({'type': reward.type, 'id': reward.id, 'label': reward.label})
        if attempt.metric:
            record.records['calibration_pass'] = attempt.metric['calibration_pass']
            record.records['calibrated_max_bpm'] = attempt.metric['max_bpm']
        # Verified results the campaign keeps for later missions to refer to (the latest completion's).
        for o in attempt.objectives:
            if o.type in COUNTED: record.records[f'{mission.id}.{o.id}'] = attempt.counts.get(o.id, 0)
            if o.type == 'style_stages': record.records[f'{mission.id}.{o.id}'] = ', '.join(STYLE_WORDS.get(k, k) for k in attempt.done_styles(o))
        # Story flags follow the story's first pass: replaying an earlier mission never rewinds them.
        flags = {} if replay else dict(mission.flags)
        if not replay:
            for o in attempt.objectives:
                if o.choice:
                    selected = next((x for x in o.choice.options if x.id == attempt.choices.get(o.id)), None)
                    if selected: flags.update(selected.sets)
            if route: flags.update(route.sets)
        record.flags.update(flags)
        chapter_done = next((r.id for r in mission.rewards if r.type == 'chapter_complete' and r.id not in record.chapters), None)
        if chapter_done: record.chapters[chapter_done] = ChapterRecord(completed_at=stamp)
        campaign_done = any(r.type == 'campaign_complete' for r in mission.rewards) and record.completed_at is None
        if campaign_done: record.completed_at = stamp
        progress.active = None
        campaigns_before = {c.id for c in self.book.campaigns if self.campaign_available(c)}
        open_before = {m.id for m in campaign.missions if self.mission_state(campaign, m) in {'available', 'completed', 'active'}}
        try:
            self._save(progress)
        except (ValueError, OSError):
            attempt.pending = True
            self.notice = 'Mission complete, but progress could not be saved. Check free disk space; it will be saved on the next update.'
            logger.warning('Campaign progress could not be saved')
            return None
        attempt.completed = True
        self.notice = None
        chapter = next((ch for ch in campaign.chapters if ch.id == chapter_done), None)
        self.finished = {'campaign': campaign.id, 'mission': mission.id, 'session_id': attempt.session_id,
                         'campaign_complete': bool(campaign_done), 'chapter': chapter.title if chapter else None,
                         'objectives': [o.id for o in attempt.objectives],
                         'route': {'id': route.id, 'label': route.label} if route else None}
        narrative = self.book.narratives.get(campaign.id)
        block = narrative.missions.get(mission.id) if narrative else None
        newly = [m.id for m in campaign.missions if m.id not in open_before and self.mission_state(campaign, m) == 'available']
        unlocked_campaigns = [{'id': c.id, 'title': c.title} for c in self.book.campaigns
                              if c.id not in campaigns_before and self.campaign_available(c)]
        result = {'type': 'mission_result', 'campaign': campaign.id, 'mission': mission.id, 'title': mission.title,
                  'companion': mission.companion, 'replay': replay, 'earned': earned, 'unlocked_missions': newly,
                  'unlocked_campaigns': unlocked_campaigns,
                  **({'route': {'id': route.id, 'label': route.label}} if route else {}),
                  'objectives': attempt.view(None, True)['objectives'], 'records': dict(record.records),
                  'completion': public_block(block.completion, text_flags) if block else None,
                  'epilogue': [public_block(b, text_flags) for b in block.epilogue if evaluate(b.when, text_flags)] if block else [],
                  'chapter_complete': {'id': chapter.id, 'number': chapter.number, 'title': chapter.title} if chapter else None,
                  'chapter_completion': public_block(narrative.chapters.get(chapter.id), text_flags) if chapter and narrative else None,
                  'flags': flags, 'campaign_complete': bool(campaign_done),
                  'campaign_completion': public_block(narrative.campaign_complete, text_flags) if campaign_done and narrative else None}
        shown = [b for b in [result['completion'], *result['epilogue'], result['chapter_completion'], result['campaign_completion']] if b]
        result['narrative_status'] = 'placeholder' if narrative and narrative.status == 'placeholder' or any(b.get('status') == 'placeholder' for b in shown) else ('draft' if any(b.get('status') == 'draft' for b in shown) else None)
        result['narrative_draft'] = any(b.get('status') == 'draft' for b in shown)
        self.attempt = None
        return result


CAMPAIGN_CARD = 'campaign_moment'


def card_brief(cue, status):
    """The task for a companion's reaction to a verified mission moment."""
    where = f'your mission "{cue["mission_title"]}" ({cue["campaign_title"]}, Mission {cue["order"]})'
    if cue['kind'] == 'moment':
        # The direction describes the participant's answer; its exact words are left out, because a model repeats them.
        text = (f'React to a verified mission moment in {where}: Direction: {cue["direction"]}'
                + ' Say it in your own words, as yourself; do not quote or mention the direction.')
        return text + (' The session is still running and can carry on.' if status in LIVE else ' The session has ended.')
    if cue['kind'] == 'objective_reached':
        return (f'React to a verified mission moment: in {where}, the participant has just reached this goal: '
                f'"{cue["objective"]}". The mission is not complete yet, because another goal remains. '
                'Mark the moment in your own voice, as the one running this mission.')
    text = (f'React to a verified mission moment: the participant has just completed {where}, and EdgeLoop saved it. '
            'Your completion message is already on screen, so do not repeat it and do not announce the next mission. '
            'Add one short, personal remark in your own voice.')
    if cue.get('chapter'): text += f' This mission completes the chapter "{cue["chapter"]}".'
    if cue.get('route'): text += ' Route taken: ' + cue['route']['label'] + '.'
    if cue.get('campaign_complete'): text += ' This was the final mission: the campaign is complete.'
    text += ' The session is still running and can carry on.' if status in LIVE else ' The session has ended.'
    return text
