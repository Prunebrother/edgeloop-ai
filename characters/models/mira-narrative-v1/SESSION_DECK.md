# Mira: reusable session deck

> **Status 2026-11-12:** these cards now ship in `config/event-deck.json` as standard cards
> (`mira-<id>`, audience `mira`), shuffled together with the common deck like the other
> companions; `mira-uninvited-company` and `mira-until-next-time` replace the shared opening
> and closing for Mira only. `session-deck.json` stays as the DeckSpec source and as a fixture
> for the custom-character path (`tests/fork/test_mira_session_deck.py`); it is not loaded at runtime.

`session-deck.json` is a Character Builder `DeckSpec`: ten repeatable normal
cards plus optional personal `session_start` / `session_end` briefs. It contains
no narrative sequence, mission, action, Journal objective, media command or
persistent relationship/espionage state. It is not a complete character package.

The definition was inspected against `experiment/ai-companion` at `e4e4acc` and
the existing custom composer, dealer, context compiler and conversation service.
The development base and the other four companions' deck content are unchanged.
Live remote verification failed with GitHub DNS unavailable; no base was changed.

## Cards

All IDs below gain the custom character's ID prefix during composition, e.g.
`mira.helix-quality-control`; the audience becomes `custom.mira`. Titles are
editorial names, not extra schema fields. Emotion is brief-level delivery
guidance using existing canonical IDs; the current model expression header still
chooses the actual visual state. The Director/renderer does not force an emotion.

| Card / local ID | Delivery | Existing eligibility / timing |
| --- | --- | --- |
| Uninvited Company / `uninvited-company` | `mischievous` | Mandatory `session_start`, once per session, only inside the existing opening window |
| Helix Quality Control / `helix-quality-control` | `focused` | Normal draw, `RUNNING`, verified edge tally at least three |
| A Very Tempting Offer / `tempting-offer` | `flirty` | Normal draw, `RUNNING`; optional pitch only if welcome |
| Slippery Little Secrets / `slippery-secrets` | `playful` | Normal draw, `RUNNING`; hypothetical fluid-body boast, no actual intrusion |
| Eyes on the Prize / `eyes-on-prize` | `focused` | Normal draw, `RUNNING`, existing `finishing` phase |
| Professional Distraction / `professional-distraction` | `flirty` | Normal draw, `RUNNING`, participant has spoken in this session; flirtation must still be welcome |
| Almost Innocent / `almost-innocent` | `mischievous` | Normal draw, `RUNNING`; no invented accusation or completed theft |
| Competitive Intelligence / `competitive-intelligence` | `proud` | Normal draw, `RUNNING`; clearly personal corporate boasting |
| Unexpected Results / `unexpected-results` | `surprised` | Normal draw, verified `RAMPDOWN`, any existing session phase |
| A Little Encouragement / `little-encouragement` | `happy` | Normal draw, `RUNNING`, building/finishing/recovery; supports choice rather than physical endurance |
| The Procurement Department / `procurement-department` | `playful` | Normal draw, `RUNNING`; a fresh fictional procurement slogan, no transaction |
| Until Next Time / `until-next-time` | `flirty` or restrained warmth if unwelcome | Existing `session_end` after finalization from a verified final snapshot; not merely idle or rampdown |

Normal cards with no explicit phase retain the current `building` default.
No card reads heart rate or Journal data. Quality Control may discuss only the
edge tally supplied by the compiler; an edge is not biological proof or an
available sample. Cards contain intentions, not fixed spoken lines.

## Cooldowns, priority and repetition

There is no added card-specific timer or new poll. Existing character-scoped
settings remain authoritative:

- Normal countdown defaults to 10 seconds after delivered/completed output and
  uses the user's saved per-character countdown when present.
- Existing priority remains session end > session start > common milestone
  cards > narrative (if otherwise present) > normal. No Mira narrative or
  milestone sequence is introduced here.
- Opening is skipped when a newly built deck first observes a session beyond
  the existing 120-second opening window; selecting Mira mid-session is not a
  new session start.
- Only one play can be active. Eligible normal cards are shuffled, consumed only
  after delivery, and recycled without an immediate repeated card when another
  eligible choice exists. Eligibility changes can make a small subset repeat
  more often; there is no new permanent once-only state.
- Existing interruption retry is 2 seconds, max interruptions 3; existing bounded
  failure/silence backoff remains capped at 300 seconds.
- Closing finalization is idempotent and supersedes pending session cards.
  Existing safety/cancellation, quiet, freshness, output, expiry and session
  checks still apply; this deck does not force a flirty farewell after a safety
  stop. Normal countdown does not delay the existing mandatory lifecycle lanes.

The `shared: lifecycle` choice preserves shared arrivals and existing common
milestone/session reactions, without shared routine normal cards or other
companions' personal cards. Existing common sequences are inherited unchanged;
they are not new Mira missions or story progression.

## Adaptations from the concepts

Quality Control uses the current authenticated tally after the existing
three-edge threshold; it does not claim a newly crossed threshold on every draw.
Unexpected Results reacts to verified winding-down state instead of inventing a
new surprise event or biological result. Eyes on the Prize uses the existing
finishing phase without predicting completion. The two pitches use different
angles: an optional future-donation offer and absurd procurement bureaucracy.
None can divert a donation, obtain a sample, grant access or change gameplay.
Opening/closing use existing mandatory lanes instead of pretending they are
ordinary random draws. The farewell is permitted only after confirmed ending.

## Narrow custom integration

The baseline custom schema supported only normal personal cards. To honor the
requested opening and confirmed farewell, the custom composer now accepts
optional `deck.session_start` and `deck.session_end` CardSpec objects. It compiles
these into the existing lifecycle `Card` kinds with the same custom audience and
ID namespace. They cannot add custom eligibility or write Story Memory. Missing
or disabled overrides fall back to the shared lifecycle cards.

No Director, scheduler, event type, context/AI protocol, hardware, player or
shared deck implementation changed. Legacy packages without overrides keep
identical composed bytes/hash, and existing custom source files need no new
fields. Normal plus lifecycle cards count toward the existing sixteen-card
limit. The builder preserves lifecycle fields on normal-card saves, counts them
in its existing meter, and previews the effective opening/closing IDs. These two
briefs are currently edited in source JSON; no new editor workflow was added.

To use it, attach the contents of `session-deck.json` as the `deck` property of
Mira's finalized Character Builder source. Use the existing save → preview →
activate path to compose and validate it. Existing code registers the IDs and
scopes automatically; do not edit `config/event-deck.json` or add model-name
checks. The worktree's updated custom loader is required for these overrides.

This task does not create or activate a complete persona package. The custom
composer replaces a model's native persona, so finalize Mira's authored custom
world/persona from the edited Modelfile before activation. The edited working
Modelfile and all twelve artwork files are left untouched. Artwork installation,
model building and finishing the custom persona are outside this deck task.

## Validation

Relevant pytest coverage includes real composition, legacy hash preservation,
card eligibility, safety gates, shuffle/countdown, interruption handling,
common-milestone priority, finalization, scoped lifecycle validation, and the
real conversation service/compiler with mocked Ollama. It checks the supplied
edge tally, current expression metadata, no tool request, unchanged engine state,
no Journal files and unchanged narrative state. Mocked generation is not evidence
that a live model will never hallucinate; live dialogue review remains required.

The existing builder browser regression fixture also covers preserving personal
lifecycle briefs when saving normal cards and enforcing the shared card limit.
Run it on a host with working Playwright Chromium. Sandbox browser/socket
restrictions are reported separately, never counted as passing tests.
