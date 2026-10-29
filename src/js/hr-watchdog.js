// Heart-rate signal watchdog. Pure state machine, no DOM and no timers, so
// every transition runs under node:test. app.js feeds it packet timestamps
// and asks for a verdict once per second.
//
// Two clocks are tracked:
//   lastPacketAt  - the last notification of ANY kind (even 0 BPM).
//   lastValidAt   - the last notification that carried a usable BPM.
//
// Verdicts, measured from the last VALID reading:
//   'ok'       - a usable reading arrived within holdMs.
//   'holding'  - between holdMs and staleMs: keep driving with the last valid
//                HR, never drop to 0 (a watch or relay app that updates every
//                2-5 s, or a single missed strap packet, lands here at most).
//   'stale'    - longer than staleMs without a usable reading: the signal is
//                lost, the motors must stop and the session pauses.
//
// noContact is set when packets keep arriving but carry no usable BPM (poor
// electrode contact reports 0), or when the sensor's own contact bit says so.

export const MIN_VALID_BPM = 35;
export const MAX_VALID_BPM = 250;

export const DEFAULT_WATCHDOG_SETTINGS = Object.freeze({
    staleMs: 8000,
    holdMs: 5000,
    autoResume: true
});

export const MIN_STALE_SECONDS = 3;
export const MAX_STALE_SECONDS = 20;

export function isValidBpm(bpm) {
    return Number.isFinite(bpm) && bpm >= MIN_VALID_BPM && bpm <= MAX_VALID_BPM;
}

// Clamp the typed signal-loss timeout to the supported range (seconds).
export function clampStaleSeconds(value, fallback = DEFAULT_WATCHDOG_SETTINGS.staleMs / 1000) {
    const n = typeof value === 'number' ? value : parseInt(String(value ?? ''), 10);
    if (!Number.isFinite(n)) return fallback;
    return Math.max(MIN_STALE_SECONDS, Math.min(MAX_STALE_SECONDS, Math.round(n)));
}

function normalizeSettings(input = {}) {
    const staleMs = Number.isFinite(input.staleMs) && input.staleMs > 0
        ? input.staleMs
        : DEFAULT_WATCHDOG_SETTINGS.staleMs;
    const holdMs = Number.isFinite(input.holdMs) && input.holdMs >= 0
        ? input.holdMs
        : DEFAULT_WATCHDOG_SETTINGS.holdMs;
    const autoResume = input.autoResume === undefined
        ? DEFAULT_WATCHDOG_SETTINGS.autoResume
        : Boolean(input.autoResume);
    return { staleMs, holdMs, autoResume };
}

// Stateless classification. A missing timestamp means "never heard from the
// sensor", which is treated as stale: the app resets both clocks on connect
// and on session start, so this only happens when something went wrong.
export function classifyHrSignal({ lastPacketAt, lastValidAt, now, staleMs, holdMs, sensorContact = null }) {
    const s = normalizeSettings({ staleMs, holdMs });
    // The hold band can never extend past the stale threshold, otherwise a
    // short user-typed timeout would be silently ignored.
    const holdLimitMs = Math.min(s.holdMs, s.staleMs);
    const validKnown = Number.isFinite(lastValidAt);
    const packetKnown = Number.isFinite(lastPacketAt);
    const sinceValidMs = validKnown ? Math.max(0, now - lastValidAt) : Infinity;
    const sincePacketMs = packetKnown ? Math.max(0, now - lastPacketAt) : Infinity;

    let status = 'ok';
    if (sinceValidMs > s.staleMs) status = 'stale';
    else if (sinceValidMs > holdLimitMs) status = 'holding';

    // Packets newer than the last valid reading mean the sensor is talking
    // but reporting no usable pulse.
    const packetsWithoutPulse = packetKnown && (!validKnown || lastPacketAt > lastValidAt);
    const noContact = sensorContact === false || packetsWithoutPulse;

    return { status, noContact, sinceValidMs, sincePacketMs };
}

// Stateful wrapper: remembers the clocks, the settings and whether the
// alarm has already been raised, so the caller can react to each transition
// exactly once instead of re-triggering every tick.
export function createHrWatchdog(settings = {}) {
    let opts = normalizeSettings(settings);
    let lastPacketAt = null;
    let lastValidAt = null;
    let sensorContact = null;
    let lastStatus = 'ok';
    // True from the moment 'stale' was reported until a usable reading is
    // back, so the alarm is raised once per loss.
    let tripped = false;

    return {
        configure(next = {}) {
            opts = normalizeSettings({ ...opts, ...next });
            return { ...opts };
        },
        get settings() {
            return { ...opts };
        },
        // Fresh start (BLE connect, session start/resume, simulator engaged):
        // both clocks are set to `now` and any pending alarm is cleared.
        reset(now) {
            lastPacketAt = now;
            lastValidAt = now;
            sensorContact = null;
            lastStatus = 'ok';
            tripped = false;
        },
        // Record a notification. Returns true when the reading is usable.
        recordPacket(now, bpm, contact = null) {
            lastPacketAt = now;
            sensorContact = contact === true || contact === false ? contact : null;
            if (!isValidBpm(bpm)) return false;
            lastValidAt = now;
            return true;
        },
        get lastPacketAt() {
            return lastPacketAt;
        },
        get lastValidAt() {
            return lastValidAt;
        },
        get tripped() {
            return tripped;
        },
        // Whether a usable reading arrived recently enough that the signal is
        // not stale right now. Side-effect free: START / RESUME gate on it
        // without disturbing the once-per-transition bookkeeping.
        isFresh(now) {
            return classifyHrSignal({
                lastPacketAt,
                lastValidAt,
                now,
                staleMs: opts.staleMs,
                holdMs: opts.holdMs,
                sensorContact
            }).status !== 'stale';
        },
        // The full verdict ('ok' | 'holding' | 'stale'), also side-effect
        // free. isFresh() cannot tell 'ok' from 'holding', but a caller that
        // must not act on a FROZEN pulse (the microphone boost, which would
        // otherwise climb on room noise through a dropout) needs that
        // distinction: only 'ok' means hrCurrent is a live reading.
        status(now) {
            return classifyHrSignal({
                lastPacketAt,
                lastValidAt,
                now,
                staleMs: opts.staleMs,
                holdMs: opts.holdMs,
                sensorContact
            }).status;
        },
        // One verdict per tick. `tripped` in the result is true only on the
        // tick that crossed into 'stale'; `recovered` only on the tick that
        // first saw a usable reading again after a loss.
        evaluate(now) {
            const verdict = classifyHrSignal({
                lastPacketAt,
                lastValidAt,
                now,
                staleMs: opts.staleMs,
                holdMs: opts.holdMs,
                sensorContact
            });
            const justTripped = verdict.status === 'stale' && !tripped;
            const recovered = verdict.status !== 'stale' && tripped;
            if (justTripped) tripped = true;
            if (recovered) tripped = false;
            const changed = verdict.status !== lastStatus;
            lastStatus = verdict.status;
            return {
                ...verdict,
                changed,
                tripped: justTripped,
                recovered,
                shouldResume: recovered && opts.autoResume
            };
        }
    };
}
