// Pure funscript builder. The cockpit samples the engine output at 4 Hz
// (speed %, secondary %, stroke zone) and this module turns that timeline
// into real stroke actions for a player: a ping-pong between strokeMin and
// strokeMax whose half-stroke period is derived from the speed with the SAME
// mapping the Intiface linear driver uses (see strokeDurationMs in
// hardware/intiface.js: 100% speed ~ 180 ms per half-stroke, 0% ~ 2200 ms,
// scaled by the travel fraction). Zero speed holds position.
//
// No DOM, no storage: everything here runs under node:test.

export const FUNSCRIPT_SAMPLE_INTERVAL_MS = 250;
// Four hours of 4 Hz samples; older samples are dropped first.
export const FUNSCRIPT_MAX_SAMPLES = 4 * 60 * 60 * (1000 / FUNSCRIPT_SAMPLE_INTERVAL_MS);

export const HALF_STROKE_MIN_MS = 180;
export const HALF_STROKE_MAX_MS = 2200;
export const MIN_TRAVEL_FRACTION = 0.08;
// A sample only describes what the toy was doing until the next sample. When
// the recording has a hole longer than this (a pause, a lost tab), nothing was
// sent to the toy, so the script holds instead of inventing strokes.
export const SAMPLE_GAP_HOLD_MS = 4 * FUNSCRIPT_SAMPLE_INTERVAL_MS;

function clampPercent(value, fallback = 0) {
    const n = Number(value);
    if (!Number.isFinite(n)) return fallback;
    return Math.max(0, Math.min(100, Math.round(n)));
}

// Milliseconds for one half-stroke (one direction) at `speedPercent` over
// `travelFraction` (0-1) of full travel. Mirrors the Intiface linear driver.
export function halfStrokeMs(speedPercent, travelFraction) {
    const speed = clampPercent(speedPercent, 0);
    const span = Math.max(MIN_TRAVEL_FRACTION, Number.isFinite(travelFraction) ? travelFraction : 1);
    const duration = HALF_STROKE_MIN_MS + ((100 - speed) / 100) * (HALF_STROKE_MAX_MS - HALF_STROKE_MIN_MS);
    return Math.max(1, Math.round(duration * span));
}

// Coerce one raw sample into { at, speed, secondary, strokeMin, strokeMax }
// with integer percents and an ordered zone. Returns null for an unusable
// sample (non-finite or negative timestamp).
export function normalizeSample(sample) {
    if (!sample || typeof sample !== 'object') return null;
    const at = Number(sample.at);
    if (!Number.isFinite(at) || at < 0) return null;
    let strokeMin = clampPercent(sample.strokeMin, 0);
    let strokeMax = clampPercent(sample.strokeMax, 100);
    if (strokeMax < strokeMin) [strokeMin, strokeMax] = [strokeMax, strokeMin];
    return {
        at: Math.round(at),
        speed: clampPercent(sample.speed, 0),
        secondary: clampPercent(sample.secondary, 0),
        strokeMin,
        strokeMax
    };
}

// Append a sample to the live buffer, dropping the OLDEST samples once the
// cap is reached. Returns the buffer for chaining.
export function pushSample(buffer, sample, maxSamples = FUNSCRIPT_MAX_SAMPLES) {
    const clean = normalizeSample(sample);
    if (!clean) return buffer;
    buffer.push(clean);
    const cap = Number.isFinite(maxSamples) && maxSamples > 0 ? Math.floor(maxSamples) : FUNSCRIPT_MAX_SAMPLES;
    if (buffer.length > cap) buffer.splice(0, buffer.length - cap);
    return buffer;
}

function cleanTimeline(samples) {
    if (!Array.isArray(samples)) return [];
    const out = [];
    let lastAt = -1;
    for (const raw of samples) {
        const s = normalizeSample(raw);
        if (!s) continue;
        // Timeline must be monotonic: a sample that goes backwards is dropped.
        if (s.at < lastAt) continue;
        if (s.at === lastAt && out.length > 0) {
            out[out.length - 1] = s;
            continue;
        }
        out.push(s);
        lastAt = s.at;
    }
    return out;
}

function pushAction(actions, at, pos) {
    const prev = actions.length > 0 ? actions[actions.length - 1] : null;
    const safeAt = prev ? Math.max(prev.at + 1, Math.round(at)) : Math.max(0, Math.round(at));
    actions.push({ at: safeAt, pos: clampPercent(pos, 0) });
    return safeAt;
}

// Primary channel: real strokes. Output actions have strictly increasing
// integer `at` (ms) and integer `pos` 0-100 within each sample's zone.
export function buildStrokeActions(samples) {
    const timeline = cleanTimeline(samples);
    const actions = [];
    if (timeline.length === 0) return actions;

    const end = timeline[timeline.length - 1].at;
    let pos = timeline[0].strokeMin;
    let dir = 1;
    let t = timeline[0].at;
    let i = 0;
    pushAction(actions, t, pos);

    while (t < end) {
        while (i + 1 < timeline.length && timeline[i + 1].at <= t) i += 1;
        const s = timeline[i];
        const nextAt = i + 1 < timeline.length ? timeline[i + 1].at : end;
        // This sample only vouches for the toy until the next one arrives, or
        // until the recording went silent (a pause is not recorded as motion).
        const activeUntil = Math.min(nextAt, s.at + SAMPLE_GAP_HOLD_MS);
        if (s.speed <= 0 || t >= activeUntil) {
            // Hold position until the next sample.
            if (i + 1 >= timeline.length) break;
            t = nextAt;
            i += 1;
            continue;
        }
        const last = actions[actions.length - 1];
        if (last.at < t) {
            // A hold just ended: pin the held position so a player does not
            // interpolate a slow drift across the pause.
            pushAction(actions, t, pos);
        }
        const travel = (s.strokeMax - s.strokeMin) / 100;
        const half = halfStrokeMs(s.speed, travel);
        const target = dir > 0 ? s.strokeMax : s.strokeMin;
        t += half;
        pushAction(actions, t, target);
        pos = target;
        dir = -dir;
    }

    const last = actions[actions.length - 1];
    if (last.at < end) pushAction(actions, end, pos);
    return actions;
}

// Secondary channel (.v0 convention): `pos` is the vibration level. Runs of
// the same level collapse to a step (previous level pinned right before the
// change) so the file stays small without a player ramping between levels.
export function buildVibrationActions(samples) {
    const timeline = cleanTimeline(samples);
    const actions = [];
    if (timeline.length === 0) return actions;

    let level = timeline[0].secondary;
    pushAction(actions, timeline[0].at, level);
    for (let i = 1; i < timeline.length; i++) {
        const s = timeline[i];
        if (s.secondary === level) continue;
        const prevSample = timeline[i - 1];
        const last = actions[actions.length - 1];
        if (last.at < prevSample.at) pushAction(actions, prevSample.at, level);
        level = s.secondary;
        pushAction(actions, s.at, level);
    }
    const end = timeline[timeline.length - 1].at;
    if (actions[actions.length - 1].at < end) pushAction(actions, end, level);
    return actions;
}

export function toFunscript(actions) {
    return {
        version: '1.0',
        inverted: false,
        range: 100,
        actions: Array.isArray(actions) ? actions : []
    };
}

// Convenience: both channel scripts from one sample timeline.
export function buildFunscripts(samples) {
    return {
        primary: toFunscript(buildStrokeActions(samples)),
        secondary: toFunscript(buildVibrationActions(samples))
    };
}
