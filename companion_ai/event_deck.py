# SPDX-License-Identifier: AGPL-3.0-only
"""Director 2.0 event card deck, driven by ConversationService when a model's deck is enabled.

No provider, character, device, journal, storage or clock access. Callers pass in
already validated observations and the current time, so behavior is deterministic.

State is in memory only and lasts as long as the process. A deck rebuilt mid-session, by
a restart or a model switch, can't know what was delivered, so a counter milestone already
reached when it first sees the session is treated as past and never replayed. Nothing else
here, including idempotent session finalization, survives a restart.

Lanes, highest priority first: session_end > session_start > mission > narrative >
normal. The mandatory start card precedes everything except session ending. Only normal
cards wait for the countdown; every lane waits for the output channel to be free. Only
narrative and normal cards count toward the unsolicited limit. The 'arrival' lane plays
outside any session's deck, through Arrival below, so it has no place in this order.

Play lifecycle:
  proposed  -> accepted | deferred | cancelled
  accepted  -> generated | suppressed | failed | cancelled
  generated -> delivered | suppressed | failed | cancelled

  accepted:  the scheduler accepted the request; no model text exists yet.
  generated: the model produced text that passed validation; nobody has seen it.
  delivered: the reply was actually published. Only this counts a card as played.
             Speech playback is separate; see response_completed().
"""
from collections import Counter, OrderedDict, deque
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, NamedTuple
from pydantic import ConfigDict, Field, model_validator
from .models import StrictModel

Lane = Literal['session_start', 'normal', 'narrative', 'mission', 'session_end', 'arrival']
Status = Literal['proposed', 'accepted', 'generated', 'delivered', 'deferred', 'cancelled', 'suppressed', 'failed']

CARD_ID = r'^[a-z0-9][a-z0-9_.-]{0,63}$'
SHARED = 'shared'
SETTINGS_FILE = 'deck-settings.json'
ACTIVE_STATUSES = frozenset({'RUNNING', 'RAMPDOWN'})
PROTECTIVE_FAULTS = frozenset({'signal_lost', 'no_contact'})
# 'missing' means no HR sensor is ready; 'holding' and 'stale' are real signal problems.
USABLE_SIGNALS = frozenset({'ok', 'missing'})
# Endings the user caused; these keep their closing reaction with proactive dialogue off.
USER_ENDED_TERMINATIONS = frozenset({'manual_stop', 'calibration_completed', 'accidental_release'})
# Matches the terminations for which the observer already withholds a closing reaction.
NO_CLOSING_TERMINATIONS = frozenset({'cancelled', 'safety_stop', 'cancelled_or_unclassified_stop'})
TRANSITIONS = {
    'proposed': frozenset({'accepted', 'deferred', 'cancelled'}),
    'accepted': frozenset({'generated', 'suppressed', 'failed', 'cancelled'}),
    'generated': frozenset({'delivered', 'suppressed', 'failed', 'cancelled'}),
}
INTERRUPTED = frozenset({'deferred', 'cancelled'})
UNPRODUCTIVE = frozenset({'suppressed', 'failed'})


class DeckLifecycleError(ValueError):
    """A caller skipped a lifecycle stage, such as delivering text never generated."""


class _Frozen(StrictModel):
    model_config = ConfigDict(frozen=True)


class Eligibility(_Frozen):
    statuses: list[Literal['RUNNING', 'RAMPDOWN']] = Field(default_factory=lambda: ['RUNNING', 'RAMPDOWN'], min_length=1)
    min_seconds: int | None = Field(default=None, ge=0)
    max_seconds: int | None = Field(default=None, ge=0)
    min_edges: int | None = Field(default=None, ge=0)
    max_edges: int | None = Field(default=None, ge=0)
    requires_story_welcome: bool = False
    requires_hr: bool = False
    # Only these verified trend directions qualify; 'unknown' never does.
    hr_trends: list[Literal['steady', 'rising', 'falling']] | None = Field(default=None, min_length=1)
    # Needs something the participant actually said this session, not earlier commentary.
    requires_conversation: bool = False

    @model_validator(mode='after')
    def ordered(self):
        if self.hr_trends and not self.requires_hr:
            raise ValueError('A heart-rate trend rule requires a current heart rate')
        for low, high in ((self.min_seconds, self.max_seconds), (self.min_edges, self.max_edges)):
            if low is not None and high is not None and low > high:
                raise ValueError('Eligibility minimum exceeds maximum')
        return self


class Card(_Frozen):
    id: str = Field(pattern=CARD_ID)
    kind: Lane
    audience: str = Field(default=SHARED, pattern=CARD_ID)
    intent: str = Field(pattern=CARD_ID)
    brief: str = Field(min_length=1, max_length=400)
    # What has just happened, for the model. The brief is what to do about it.
    occasion: str | None = Field(default=None, min_length=1, max_length=160)
    eligibility: Eligibility = Field(default_factory=Eligibility)
    memory: Literal['none', 'story'] = 'none'
    repeat: bool = True

    @model_validator(mode='after')
    def policy(self):
        if self.kind in {'normal', 'session_start', 'session_end', 'arrival'} and self.memory != 'none':
            raise ValueError('Routine, start, closing and arrival cards cannot write Story Memory')
        if self.kind in {'session_start', 'session_end', 'arrival'} and self.eligibility != Eligibility():
            raise ValueError('Mandatory start, closing and arrival cards take no eligibility rules')
        return self


class SequenceTrigger(_Frozen):
    event_kinds: list[str] = Field(default_factory=list, max_length=16)
    min_edges: int | None = Field(default=None, ge=1)
    min_seconds: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def one_style(self):
        counters = self.min_edges is not None or self.min_seconds is not None
        if bool(self.event_kinds) == counters:
            raise ValueError('A trigger uses either verified event kinds or engine counters')
        return self


class Sequence(_Frozen):
    id: str = Field(pattern=CARD_ID)
    lane: Literal['narrative', 'mission']
    audience: str = Field(default=SHARED, pattern=CARD_ID)
    trigger: SequenceTrigger
    steps: list[Card] = Field(min_length=1, max_length=8)

    @model_validator(mode='after')
    def consistent(self):
        if any(card.kind != self.lane or card.audience != self.audience for card in self.steps):
            raise ValueError('Sequence steps must match the sequence lane and audience')
        if self.lane == 'narrative' and not self.trigger.event_kinds:
            raise ValueError('Narrative sequences start only from verified events')
        return self


class DeckDefinition(_Frozen):
    schema_version: Literal[1] = 1
    revision: int = Field(default=1, ge=1)
    session_start: list[Card] = Field(min_length=1, max_length=32)
    session_end: list[Card] = Field(min_length=1, max_length=32)
    normal: list[Card] = Field(default_factory=list, max_length=256)
    sequences: list[Sequence] = Field(default_factory=list, max_length=64)
    # Played outside any session's deck, so they never enter or shift its shuffle.
    arrival: list[Card] = Field(default_factory=list, max_length=8)

    @model_validator(mode='after')
    def consistent(self):
        for kind, cards in (('session_start', self.session_start), ('session_end', self.session_end), ('normal', self.normal), ('arrival', self.arrival)):
            if any(card.kind != kind for card in cards):
                raise ValueError('Card kind does not match its deck section')
        for name, cards in (('session_start', self.session_start), ('session_end', self.session_end)):
            audiences = [card.audience for card in cards]
            if SHARED not in audiences or len(audiences) != len(set(audiences)):
                raise ValueError(name + ' needs one shared card and at most one card per companion')
        ids = [card.id for card in (*self.session_start, *self.session_end, *self.normal, *self.arrival)]
        ids += [step.id for sequence in self.sequences for step in sequence.steps]
        if len(ids) != len(set(ids)):
            raise ValueError('Card IDs must be unique')
        if len({sequence.id for sequence in self.sequences}) != len(self.sequences):
            raise ValueError('Sequence IDs must be unique')
        return self


# The card deck is Director 2.0's proactive dialogue and is on by default (v0.4.0). A saved
# per-model setting still turns it off; an invalid settings file always turns it off.
DEFAULT_DECK_ENABLED = True


class DeckSettings(_Frozen):
    enabled: bool = Field(default_factory=lambda: DEFAULT_DECK_ENABLED)
    countdown_seconds: float = Field(default=10., ge=0, le=3600)
    interruption_retry_seconds: float = Field(default=2., ge=0, le=300)
    mission_spacing_seconds: float = Field(default=4., ge=0, le=300)
    opening_window_seconds: int = Field(default=120, ge=0, le=7200)
    max_attempts: int = Field(default=2, ge=1, le=8)
    max_session_attempts: int = Field(default=4, ge=1, le=32)
    max_interruptions: int = Field(default=3, ge=1, le=16)
    max_backoff_seconds: float = Field(default=300., ge=0, le=3600)
    step_ttl_seconds: float = Field(default=300., ge=1, le=7200)
    # How long safety, mute, disconnect or status may hold a closing before it is obsolete.
    closing_ttl_seconds: float = Field(default=60., ge=1, le=300)
    # Waiting for output or for the user spends only this outer limit, never the TTL.
    closing_max_hold_seconds: float = Field(default=300., ge=1, le=3600)
    # A test harness's declaration that the whole session's telemetry is synthetic.
    simulated_session: bool = False
    # Rapid switching settles on one companion before anything is generated.
    arrival_settle_seconds: float = Field(default=3., ge=0, le=60)
    # How long a greeting may wait for quiet, counted from the first poll after activation. Generation isn't covered.
    arrival_ttl_seconds: float = Field(default=120., ge=1, le=1800)
    # Switching away and straight back is not a new arrival.
    arrival_repeat_seconds: float = Field(default=300., ge=0, le=86400)


class DeckContext(_Frozen):
    """Already validated observer facts. Deliberately has no journal or memory field."""
    session_id: str
    status: str
    seconds: int = Field(default=0, ge=0)
    edges: int = Field(default=0, ge=0)
    fresh: bool = True
    signal: str = 'ok'
    no_contact: bool = False
    watchdog_paused: bool = False
    fault: str = 'none'
    quiet: bool = False
    user_active: bool = False
    output_busy: bool = False
    conversation_active: bool = False
    unsolicited_limit_reached: bool = False
    story_welcome: bool = False
    hr_current: bool = False
    hr_trend: str = 'unknown'
    has_conversation: bool = False
    proactive_enabled: bool = True
    event_reactions_enabled: bool = True


class DeckModelSettings(_Frozen):
    enabled: bool = Field(default_factory=lambda: DEFAULT_DECK_ENABLED)
    countdown_seconds: float = Field(default=10., ge=0, le=3600)
    simulated_session: bool = False


class DeckSettingsFile(_Frozen):
    schema_version: Literal[1] = 1
    models: dict[str, DeckModelSettings] = Field(default_factory=dict)


class SessionResult(_Frozen):
    """The finalized engine snapshot; unknown keys, including journal data, are rejected."""
    active_running_seconds: int | float | None = None
    last_verified_running_ticks: int | None = None
    edges: int | None = None
    experience: str | None = None
    goal: str | None = None
    termination: str | None = None
    completion_status: str | None = None
    completion_source: str | None = None
    completeness: str | None = None


@dataclass(frozen=True)
class Play:
    id: str
    card: Card
    lane: Lane
    scope: str
    session_id: str
    epoch: str
    sequence_id: str | None = None
    session_result: SessionResult | None = None

    def opportunity(self):
        """Scheduling data for the Director's card turn; never a user message or telemetry."""
        # The topic selects which verified facts reach the model, so a card sees the
        # measurement its eligibility rule depends on and no others.
        rule = self.card.eligibility
        topic = ('story' if self.lane == 'narrative' else 'milestones' if self.lane == 'mission'
                 else 'physiology' if rule.requires_hr
                 else 'milestones' if rule.min_edges is not None or rule.max_edges is not None
                 else 'timing' if rule.min_seconds is not None or rule.max_seconds is not None
                 else 'general')
        value = {'intent': self.card.intent, 'topic_key': 'card:' + self.card.id, 'reference_id': None,
                 'session_id': self.session_id, 'card_id': self.card.id, 'lane': self.lane,
                 'brief': self.card.brief, 'memory': self.card.memory, 'focus_topic': topic}
        if self.session_result is not None:
            value['session_result'] = self.session_result.model_dump()
        return value


class Draw(NamedTuple):
    play: Play | None
    reason: str


def load_definition(raw):
    """Fail closed: an invalid definition gives no deck and a generic diagnostic."""
    try:
        return DeckDefinition.model_validate(raw), None
    except (ValueError, TypeError):
        return None, 'Invalid or unsupported event deck definition; deck unavailable.'


def scope_key(scope):
    return sha256(scope.encode()).hexdigest()


def load_model_settings(store, scope):
    """Exact per-model settings from a caller-supplied store. Invalid files disable the deck."""
    if store is None:
        return DeckSettings(), None
    try:
        saved = DeckSettingsFile.model_validate(store.read(SETTINGS_FILE, {}))
    except (ValueError, TypeError, OSError):
        return DeckSettings(enabled=False), 'Invalid or unsupported deck settings; deck disabled. Existing file preserved.'
    entry = saved.models.get(scope_key(scope), DeckModelSettings())
    return DeckSettings(enabled=entry.enabled, countdown_seconds=entry.countdown_seconds, simulated_session=entry.simulated_session), None


def shuffled(card_ids, seed):
    """Seeded order, independent of declaration order and Python's random module."""
    return sorted(card_ids, key=lambda card_id: sha256((seed + '\0' + card_id).encode()).digest())


class _Run:
    __slots__ = ('sequence', 'step', 'since')

    def __init__(self, sequence, now):
        self.sequence, self.step, self.since = sequence, 0, now

    @property
    def card(self):
        return self.sequence.steps[self.step]


class EventDeck:
    """One companion's deck for one session. Only one play can be open at a time."""

    def __init__(self, definition, scope, identity, session_id, epoch, settings=None):
        if identity == SHARED:
            raise ValueError('Companion identity cannot be the shared audience')
        self.definition, self.scope, self.identity = definition, scope, identity
        self.session_id, self.epoch = session_id, epoch
        self.settings = settings or DeckSettings()
        visible = lambda audience: audience in {SHARED, identity}
        self._cards = {card.id: card for card in definition.normal if visible(card.audience)}
        self._sequences = [s for s in definition.sequences if visible(s.audience)]
        self._cycle = 0
        self._seed = '\0'.join((scope, session_id, str(definition.revision)))
        self._queue = shuffled(self._cards, self._seed + '\0' + str(self._cycle))
        self._played = []
        self._retired = set()
        self._last_delivered = None
        self._attempts = Counter()
        self._session_attempts = Counter()
        self._interruptions = Counter()
        self._start_card = self._mandatory(definition.session_start)
        self._start_done = False
        self._start_outcome = None
        self._sensor_seen = False
        self._device_seen = False
        self._runs = []
        self._activated = set()
        self._counter_baseline = None
        self._occurrences = OrderedDict()
        self._activations = deque(maxlen=32)
        self._ready_at = float('-inf')
        self._retry_at = float('-inf')
        self._urgent_retry_at = float('-inf')
        self._mission_ready_at = float('-inf')
        self._unproductive_streak = 0
        self._active = None
        self._status = None
        self._terminal = OrderedDict()
        self._plays = 0
        self._finalized = False
        self._closing = None
        self._closing_card = self._mandatory(definition.session_end)
        self._closing_deadline = None
        self._closing_hold_limit = None
        self._closing_outcome = None
        self._closing_rejected = None
        self._closing_retry_at = float('-inf')
        # Told once, whenever a pending closing ends, so a drop is recorded where it happens.
        self.on_closing_closed = None
        self._repeat_finalizations = 0
        self._counts = Counter()
        self._history = deque(maxlen=64)

    def _mandatory(self, cards):
        by_audience = {card.audience: card for card in cards}
        return by_audience.get(self.identity, by_audience[SHARED])

    # Verified triggers

    def verified_event(self, kind, occurrence_id, session_id, now):
        """Caller passes only observer-accepted events. One occurrence activates once."""
        if self._finalized or session_id != self.session_id or occurrence_id in self._occurrences:
            return []
        self._occurrences[occurrence_id] = True
        if len(self._occurrences) > 256:
            self._occurrences.popitem(last=False)
        return [self._activate(s, occurrence_id, now) for s in self._sequences
                if kind in s.trigger.event_kinds and s.id not in self._activated]

    def observe(self, context, now):
        """Counter-based missions, evaluated regardless of whether speech is allowed now."""
        if self._finalized or context.session_id != self.session_id or not context.fresh or context.status not in ACTIVE_STATUSES | {'PAUSED'}:
            return []
        first_observation = self._counter_baseline is None
        if first_observation:
            self._counter_baseline = {'edges': context.edges, 'seconds': context.seconds}
        activated = []
        for sequence in self._sequences:
            trigger = sequence.trigger
            if sequence.id in self._activated or trigger.event_kinds:
                continue
            if (trigger.min_edges is None or context.edges >= trigger.min_edges) and (trigger.min_seconds is None or context.seconds >= trigger.min_seconds):
                if first_observation:
                    # Only a crossing this deck observes is an event. Skipping is the safe
                    # direction: at worst one milestone goes unmentioned, none is repeated.
                    self._activated.add(sequence.id)
                    self._record(sequence.steps[0].id, sequence.lane, 'skipped', now, 'reached_before_first_observation')
                else:
                    activated.append(self._activate(sequence, 'counters', now))
        return activated

    def _activate(self, sequence, occurrence, now):
        self._activated.add(sequence.id)
        self._runs.append(_Run(sequence, now))
        self._activations.append({'sequence_id': sequence.id, 'lane': sequence.lane, 'occurrence': occurrence, 'at': now})
        return sequence.id

    # Drawing

    @property
    def closing_pending(self):
        return self._closing is not None

    @property
    def closing_outcome(self):
        return self._closing_outcome

    def subscribes(self, kind):
        return any(kind in s.trigger.event_kinds for s in self._sequences)

    def next_play(self, context, now, triggered_only=False):
        """Propose the next card. Proposing consumes nothing.

        triggered_only stops short of normal cards, so a scheduler can serve triggered
        cards ahead of its own event reactions and normal draws after them.
        """
        if not self.settings.enabled:
            return Draw(None, 'deck_disabled')
        if context.session_id != self.session_id:
            return Draw(None, 'wrong_session')
        self._track_hardware(context)
        self.observe(context, now)
        self._drop_disabled_reactions(context, now)
        if self._active is not None:
            return Draw(None, 'play_active')
        if self._finalized:
            return self._next_closing(context, now)
        if not context.proactive_enabled:
            return Draw(None, 'proactive_disabled')
        reason = self._gate(context)
        if reason:
            return Draw(None, reason)
        if not self._start_done and context.seconds > self.settings.opening_window_seconds:
            # A reconnect or restart mid-session must not replay the opening.
            self._start_done = True
            self._start_outcome = 'opening_window_passed'
            self._record(self._start_card.id, 'session_start', 'skipped', now, 'opening_window_passed')
        if not self._start_done:
            if now < self._urgent_retry_at:
                return Draw(None, 'retry_wait')
            return Draw(self._propose(self._start_card, 'session_start'), 'session_start')
        run = self._next_run('mission', context, now)
        if run:
            if now < self._urgent_retry_at:
                return Draw(None, 'retry_wait')
            if now < self._mission_ready_at:
                return Draw(None, 'mission_spacing')
            return Draw(self._propose(run.card, 'mission', run.sequence.id), 'mission')
        if context.unsolicited_limit_reached:
            return Draw(None, 'unsolicited_limit')
        if context.conversation_active:
            return Draw(None, 'active_conversation')
        run = self._next_run('narrative', context, now)
        if run:
            if now < self._urgent_retry_at:
                return Draw(None, 'retry_wait')
            return Draw(self._propose(run.card, 'narrative', run.sequence.id), 'narrative')
        if triggered_only:
            return Draw(None, 'no_triggered_card')
        if now < self._ready_at:
            return Draw(None, 'countdown')
        if now < self._retry_at:
            return Draw(None, 'retry_wait')
        card_id = self._next_normal(context)
        if card_id is None:
            return Draw(None, 'no_eligible_card' if self._queue or self._played else 'deck_exhausted')
        return Draw(self._propose(self._cards[card_id], 'normal'), 'normal')

    def _track_hardware(self, context):
        """One snapshot can't tell "no sensor" from "sensor lost", but session history can."""
        if context.fresh:
            self._sensor_seen = self._sensor_seen or context.signal != 'missing'
            self._device_seen = self._device_seen or context.fault == 'none'

    def _drop_disabled_reactions(self, context, now):
        """Event Intelligence off ends event-driven runs; counter missions are independent."""
        if context.event_reactions_enabled:
            return
        for run in [r for r in self._runs if r.sequence.trigger.event_kinds]:
            self._runs.remove(run)
            self._activated.discard(run.sequence.id)
            self._record(run.card.id, run.sequence.lane, 'discarded', now, 'event_reactions_disabled')

    def _safety_reason(self, context, closing=False):
        if context.quiet:
            return 'user_requested_quiet'
        if not context.fresh:
            return 'stale_observation'
        if context.watchdog_paused or context.no_contact or context.fault in PROTECTIVE_FAULTS:
            return 'protective_state'
        if not closing and context.signal not in USABLE_SIGNALS:
            return 'signal_unavailable'
        if context.signal == 'missing' and self._sensor_seen:
            return 'sensor_disconnected'
        if context.fault == 'device_unready' and self._device_seen:
            return 'device_disconnected'
        return None

    def _gate(self, context):
        reason = self._safety_reason(context)
        if reason:
            return reason
        if context.status not in ACTIVE_STATUSES:
            return 'session_inactive'
        if context.user_active:
            return 'user_active'
        if context.output_busy:
            return 'output_busy'
        return None

    def _next_closing(self, context, now):
        if self._closing is None:
            return Draw(None, 'session_closed')
        if now > self._closing_hold_limit:
            self._close_session('hold_limit_reached', now)
            return Draw(None, 'closing_expired')
        if not context.proactive_enabled and self._closing.termination not in USER_ENDED_TERMINATIONS:
            reason = 'proactive_disabled'
        else:
            reason = self._safety_reason(context, closing=True) or ('closing_waiting_for_idle' if context.status != 'IDLE' else None)
        if reason:
            return Draw(None, 'closing_expired' if self.closing_blocked(now) else reason)
        if context.user_active:
            return Draw(None, 'user_active')
        if context.output_busy:
            return Draw(None, 'output_busy')
        if now < self._closing_retry_at:
            return Draw(None, 'retry_wait')
        return Draw(self._propose(self._closing_card, 'session_end', session_result=self._closing), 'session_end')

    def closing_blocked(self, now):
        """A deliberate block spends the TTL. True once that has ended the closing."""
        if self._closing is None or now <= self._closing_deadline:
            return False
        self._close_session('expired', now)
        return True

    def abandon_closing(self, reason, now):
        """The closing can no longer be reached: the service moved on to another deck, or stopped."""
        self._close_session(reason, now)

    def _next_run(self, lane, context, now):
        for run in list(self._runs):
            if run.sequence.lane != lane:
                continue
            if self._eligible(run.card, context):
                return run
            if now - run.since > self.settings.step_ttl_seconds:
                self._record(run.card.id, lane, 'skipped', now, 'ineligible_step_expired')
                self._advance(run, now)
                if run in self._runs and self._eligible(run.card, context):
                    return run
        return None

    def _next_normal(self, context):
        # Two passes at most: ineligible cards stay in place and can never spin here.
        for _ in range(2):
            for card_id in self._queue:
                if self._eligible(self._cards[card_id], context):
                    return card_id
            if not self._played:
                return None
            self._reshuffle()
        return None

    def _reshuffle(self):
        self._cycle += 1
        order = shuffled(self._played, self._seed + '\0' + str(self._cycle))
        if not self._queue and len(order) > 1 and order[0] == self._last_delivered:
            order.append(order.pop(0))
        self._queue += order
        self._played = []
        self._attempts.clear()

    @staticmethod
    def _eligible(card, context):
        rule = card.eligibility
        return (context.status in rule.statuses
                and (rule.min_seconds is None or context.seconds >= rule.min_seconds)
                and (rule.max_seconds is None or context.seconds <= rule.max_seconds)
                and (rule.min_edges is None or context.edges >= rule.min_edges)
                and (rule.max_edges is None or context.edges <= rule.max_edges)
                and (not rule.requires_story_welcome or context.story_welcome)
                and (not rule.requires_hr or (context.fresh and context.hr_current))
                and (rule.hr_trends is None or context.hr_trend in rule.hr_trends)
                and (not rule.requires_conversation or context.has_conversation))

    def _propose(self, card, lane, sequence_id=None, session_result=None):
        self._plays += 1
        identity = '\0'.join((self.scope, self.session_id, str(self._plays)))
        play = Play(sha256(identity.encode()).hexdigest()[:32], card, lane, self.scope, self.session_id, self.epoch, sequence_id, session_result)
        self._active, self._status = play, 'proposed'
        self._counts['proposed'] += 1
        return play

    # Lifecycle

    def transition(self, play_id, status, now, reason=None):
        """Advance the open play. Safe to call late: a settled or unknown play returns False."""
        if self._active is None or self._active.id != play_id:
            return False
        if status not in TRANSITIONS[self._status]:
            raise DeckLifecycleError(f'Cannot move a play from {self._status} to {status}')
        self._counts[status] += 1
        play = self._active
        self._record(play.card.id, play.lane, status, now, reason)
        self._status = status
        if status in {'accepted', 'generated'}:
            return True
        self._terminal[play.id] = status
        if len(self._terminal) > 64:
            self._terminal.popitem(last=False)
        self._active, self._status = None, None
        if status == 'delivered':
            self._on_delivered(play, now)
        elif status in UNPRODUCTIVE:
            self._on_unproductive(play, now)
        else:
            self._on_interrupted(play, now)
        return True

    def status(self, play_id):
        if self._active is not None and self._active.id == play_id:
            return self._status
        return self._terminal.get(play_id)

    def response_completed(self, now):
        """Any finished response, including playback later: restart the countdown from now."""
        self._ready_at = max(self._ready_at, now + self.settings.countdown_seconds)

    def _on_delivered(self, play, now):
        self._unproductive_streak = 0
        self._retry_at = self._urgent_retry_at = float('-inf')
        self._ready_at = now + self.settings.countdown_seconds
        card = play.card
        if play.lane == 'normal':
            self._queue.remove(card.id)
            self._last_delivered = card.id
            if card.repeat:
                self._played.append(card.id)
            else:
                self._retired.add(card.id)
        else:
            if play.lane == 'mission':
                self._mission_ready_at = now + self.settings.mission_spacing_seconds
            self._complete(play, now, 'delivered')

    def _on_unproductive(self, play, now):
        # Normal cards back off exponentially so silence or failures can't busy-loop.
        # Triggered cards retry on a short delay: their tries are bounded and backoff
        # from unrelated normal cards must not hold back a milestone.
        self._unproductive_streak += 1
        if play.lane == 'normal':
            # The floor keeps a zero countdown from retrying a silent model on every poll.
            delay = max(self.settings.interruption_retry_seconds, self.settings.countdown_seconds * 2 ** (self._unproductive_streak - 1))
            self._retry_at = now + min(delay, max(self.settings.max_backoff_seconds, self.settings.countdown_seconds))
        else:
            self._urgent_retry_at = now + self.settings.interruption_retry_seconds
        card = play.card
        self._attempts[card.id] += 1
        self._session_attempts[card.id] += 1
        if play.lane == 'session_end':
            # Mandatory, so one silent or failed attempt doesn't end it. The same bounded tries as any triggered card.
            if self._attempts[card.id] >= self.settings.max_attempts:
                self._close_session(self._terminal[play.id], now)
            else:
                self._closing_retry_at = now + self.settings.interruption_retry_seconds
        elif play.lane != 'normal':
            if self._attempts[card.id] >= self.settings.max_attempts:
                self._record(card.id, play.lane, 'skipped', now, 'attempts_exhausted')
                self._complete(play, now, 'attempts_exhausted')
        elif self._session_attempts[card.id] >= self.settings.max_session_attempts:
            self._queue.remove(card.id)
            self._retired.add(card.id)
            self._record(card.id, play.lane, 'retired', now, 'session_attempts_exhausted')
        elif self._attempts[card.id] >= self.settings.max_attempts:
            self._queue.remove(card.id)
            self._played.append(card.id)
        else:
            self._queue.remove(card.id)
            self._queue.append(card.id)

    def _on_interrupted(self, play, now):
        retry_at = now + self.settings.interruption_retry_seconds
        if play.lane == 'normal':
            self._retry_at = retry_at
        else:
            self._urgent_retry_at = retry_at
        card = play.card
        self._interruptions[card.id] += 1
        if self._interruptions[card.id] < self.settings.max_interruptions:
            return
        self._interruptions[card.id] = 0
        if play.lane == 'normal':
            self._queue.remove(card.id)
            self._queue.append(card.id)
        elif play.lane == 'session_end':
            self._close_session('interruptions_exhausted', now)
        else:
            self._record(card.id, play.lane, 'skipped', now, 'interruptions_exhausted')
            self._complete(play, now, 'interruptions_exhausted')

    def _complete(self, play, now, outcome):
        """Finish a non-normal play, whether it was delivered or skipped."""
        if play.lane == 'session_start':
            self._start_done = True
            self._start_outcome = outcome
        elif play.lane == 'session_end':
            self._close_session('delivered', now)
        else:
            run = next((r for r in self._runs if r.sequence.id == play.sequence_id), None)
            if run:
                self._advance(run, now)

    def _advance(self, run, now):
        run.step += 1
        run.since = now
        if run.step >= len(run.sequence.steps):
            self._runs.remove(run)

    # Session and storyline boundaries

    def finish_session(self, session_id, result, now, closing_permitted=True):
        """Idempotent: the first signal wins; later ones change nothing and return False.

        Pending cards are cancelled immediately. The closing card, when permitted, is
        then the only thing this deck can propose. An invalid snapshot fails closed.
        """
        if session_id != self.session_id:
            return False
        if self._finalized:
            self._repeat_finalizations += 1
            return False
        self._finalized = True
        self._cancel_active(now, 'session_finished')
        self._runs.clear()
        self._queue, self._played = [], []
        self._start_done = True
        try:
            snapshot = SessionResult.model_validate(result)
        except (ValueError, TypeError):
            self._closing_rejected = 'invalid_session_result'
            return True
        if not closing_permitted:
            self._closing_rejected = 'closing_not_permitted'
        elif snapshot.termination in NO_CLOSING_TERMINATIONS:
            self._closing_rejected = 'termination_without_closing'
        else:
            self._closing = snapshot
            self._closing_deadline = now + self.settings.closing_ttl_seconds
            self._closing_hold_limit = now + self.settings.closing_max_hold_seconds
        return True

    def _close_session(self, reason, now):
        if self._closing is None:
            return
        self._closing = None
        self._closing_outcome = reason
        self._record(self._closing_card.id, 'session_end', 'closed', now, reason)
        if self.on_closing_closed:
            self.on_closing_closed(reason)

    def _cancel_active(self, now, reason):
        """A boundary cancellation, so it never counts against the card's retries."""
        if self._active is None:
            return
        play = self._active
        self._counts['cancelled'] += 1
        self._record(play.card.id, play.lane, 'cancelled', now, reason)
        self._terminal[play.id] = 'cancelled'
        self._active, self._status = None, None

    def narrative_reset(self, epoch, now):
        """A new storyline drops narrative progress. Old occurrences still cannot replay."""
        self.epoch = epoch
        if self._active is not None and self._active.lane == 'narrative':
            self._cancel_active(now, 'storyline_reset')
        self._runs = [run for run in self._runs if run.sequence.lane != 'narrative']
        self._activated -= {s.id for s in self._sequences if s.lane == 'narrative'}

    # Diagnostics: bounded, with card IDs and no brief or dialogue text.

    def _record(self, card_id, lane, status, at, reason=None):
        self._history.append({'card_id': card_id, 'lane': lane, 'status': status, 'at': at, 'reason': reason})

    def snapshot(self):
        finite = lambda value: None if value == float('-inf') else value  # Published as strict JSON.
        return {'enabled': self.settings.enabled, 'scope': self.scope, 'session_id': self.session_id,
                'cycle': self._cycle, 'remaining': len(self._queue), 'played': len(self._played),
                'retired': sorted(self._retired), 'start_done': self._start_done,
                'start_outcome': self._start_outcome,
                'active_sequences': [run.sequence.id for run in self._runs],
                'activations': list(self._activations), 'counter_baseline': self._counter_baseline,
                'ready_at': finite(self._ready_at),
                'retry_at': finite(self._retry_at), 'urgent_retry_at': finite(self._urgent_retry_at),
                'unproductive_streak': self._unproductive_streak, 'finalized': self._finalized,
                'closing_pending': self._closing is not None, 'closing_rejected': self._closing_rejected,
                'closing_outcome': self._closing_outcome,
                'repeat_finalizations': self._repeat_finalizations, 'counts': dict(self._counts),
                'history': list(self._history)[-16:]}


class Arrival:
    """One companion activation's greeting. It belongs to no session's deck and holds no history.

    At most one generation is ever attempted. A deferral keeps it waiting within its time limit;
    every other outcome is final, so refreshes and repeated state updates can't play it twice.
    The time limit governs only the wait. A generation in progress is bounded by the model timeout,
    and ConversationService rechecks model, lifecycle and protective state before publishing it.
    """
    WAITING, ACTIVE = {'armed', 'deferred'}, {'accepted', 'generated'}

    def __init__(self, scope, now, settings):
        self.id, self.scope, self.armed_at, self.settings = sha256(f'{scope}\0{now}\0{id(self)}'.encode()).hexdigest()[:32], scope, now, settings
        self.observed_at, self.state, self.reason = None, 'armed', None

    def status(self, play_id):
        return self.state if play_id == self.id else None

    def transition(self, play_id, status, now, reason=None):
        """The same interface as EventDeck, so turn settlement is shared. Final states stay final."""
        if play_id == self.id and (self.state in self.WAITING or self.state in self.ACTIVE):
            self.state, self.reason = status, reason

    def observe(self, now):
        if self.observed_at is None: self.observed_at = now

    def settled(self, now):
        return self.observed_at is not None and now - self.observed_at >= self.settings.arrival_settle_seconds

    def expired(self, now):
        return self.observed_at is not None and now - self.observed_at > self.settings.arrival_ttl_seconds

    def snapshot(self):
        return {'state': self.state, 'reason': self.reason}


class DeckRegistry:
    """Decks by exact (model scope, session). Eviction loses state; in-memory only."""

    def __init__(self, definition, settings=None, max_decks=8):
        self.definition, self.settings, self.max_decks = definition, settings or DeckSettings(), max_decks
        self._decks = OrderedDict()

    def deck(self, scope, identity, session_id, epoch, settings=None):
        key = (scope, session_id)
        deck = self._decks.get(key)
        if deck is None:
            deck = EventDeck(self.definition, scope, identity, session_id, epoch, settings or self.settings)
            self._decks[key] = deck
            if len(self._decks) > self.max_decks:
                self._decks.popitem(last=False)
        elif deck.identity != identity:
            raise ValueError('A model scope cannot change companion identity')
        self._decks.move_to_end(key)
        return deck
