import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
    FUNSCRIPT_MAX_SAMPLES,
    HALF_STROKE_MIN_MS,
    HALF_STROKE_MAX_MS,
    MIN_TRAVEL_FRACTION,
    SAMPLE_GAP_HOLD_MS,
    halfStrokeMs,
    normalizeSample,
    pushSample,
    buildStrokeActions,
    buildVibrationActions,
    toFunscript,
    buildFunscripts
} from './funscript.js';

function timeline(seconds, fields) {
    const out = [];
    for (let at = 0; at <= seconds * 1000; at += 250) {
        out.push({ at, ...fields });
    }
    return out;
}

function assertMonotonic(actions) {
    for (let i = 1; i < actions.length; i++) {
        assert.ok(actions[i].at > actions[i - 1].at, `at[${i}]=${actions[i].at} must exceed ${actions[i - 1].at}`);
    }
}

function assertBounds(actions, lo = 0, hi = 100) {
    for (const a of actions) {
        assert.ok(Number.isInteger(a.at) && a.at >= 0, 'at must be a non-negative integer');
        assert.ok(Number.isInteger(a.pos), 'pos must be an integer');
        assert.ok(a.pos >= lo && a.pos <= hi, `pos ${a.pos} outside ${lo}-${hi}`);
    }
}

describe('halfStrokeMs', () => {
    it('matches the Intiface linear driver mapping', () => {
        assert.equal(halfStrokeMs(100, 1), HALF_STROKE_MIN_MS);
        assert.equal(halfStrokeMs(0, 1), HALF_STROKE_MAX_MS);
        assert.equal(halfStrokeMs(50, 1), Math.round(HALF_STROKE_MIN_MS + 0.5 * (HALF_STROKE_MAX_MS - HALF_STROKE_MIN_MS)));
    });

    it('scales by travel with a floor on tiny zones', () => {
        assert.equal(halfStrokeMs(100, 0.5), Math.round(HALF_STROKE_MIN_MS * 0.5));
        assert.equal(halfStrokeMs(100, 0), Math.round(HALF_STROKE_MIN_MS * MIN_TRAVEL_FRACTION));
    });

    it('tolerates garbage', () => {
        assert.equal(halfStrokeMs(NaN, NaN), HALF_STROKE_MAX_MS);
        assert.equal(halfStrokeMs(500, 1), HALF_STROKE_MIN_MS);
    });
});

describe('normalizeSample / pushSample', () => {
    it('clamps percents, orders the zone and rounds the timestamp', () => {
        assert.deepEqual(
            normalizeSample({ at: 10.4, speed: 120, secondary: -3, strokeMin: 80, strokeMax: 20 }),
            { at: 10, speed: 100, secondary: 0, strokeMin: 20, strokeMax: 80 }
        );
        assert.equal(normalizeSample({ at: NaN }), null);
        assert.equal(normalizeSample(null), null);
    });

    it('caps the buffer at four hours, dropping the oldest', () => {
        assert.equal(FUNSCRIPT_MAX_SAMPLES, 57600);
        const buf = [];
        for (let i = 0; i < 12; i++) pushSample(buf, { at: i * 250, speed: i }, 10);
        assert.equal(buf.length, 10);
        assert.equal(buf[0].speed, 2);
        assert.equal(buf[9].speed, 11);
    });
});

describe('buildStrokeActions', () => {
    it('returns nothing for an empty timeline', () => {
        assert.deepEqual(buildStrokeActions([]), []);
        assert.deepEqual(buildStrokeActions(null), []);
    });

    it('produces monotonic timestamps and integer positions inside the zone', () => {
        const actions = buildStrokeActions(timeline(20, { speed: 70, strokeMin: 20, strokeMax: 80 }));
        assert.ok(actions.length > 10);
        assertMonotonic(actions);
        assertBounds(actions, 20, 80);
    });

    it('ping-pongs between strokeMin and strokeMax', () => {
        const actions = buildStrokeActions(timeline(5, { speed: 100, strokeMin: 10, strokeMax: 90 }));
        // First action pins the start position, then alternates max/min.
        assert.equal(actions[0].pos, 10);
        assert.equal(actions[1].pos, 90);
        assert.equal(actions[2].pos, 10);
        assert.equal(actions[3].pos, 90);
    });

    it('period scales with speed: full speed strokes every 180 ms, half speed slower', () => {
        const fast = buildStrokeActions(timeline(10, { speed: 100, strokeMin: 0, strokeMax: 100 }));
        const slow = buildStrokeActions(timeline(10, { speed: 50, strokeMin: 0, strokeMax: 100 }));
        assert.equal(fast[2].at - fast[1].at, HALF_STROKE_MIN_MS);
        assert.equal(slow[2].at - slow[1].at, halfStrokeMs(50, 1));
        assert.ok(fast.length > slow.length * 3);
    });

    it('a narrower zone strokes faster (scaled by travel)', () => {
        const full = buildStrokeActions(timeline(10, { speed: 60, strokeMin: 0, strokeMax: 100 }));
        const narrow = buildStrokeActions(timeline(10, { speed: 60, strokeMin: 40, strokeMax: 60 }));
        assert.ok(narrow.length > full.length);
    });

    it('holds position at zero speed', () => {
        const actions = buildStrokeActions(timeline(10, { speed: 0, strokeMin: 0, strokeMax: 100 }));
        assert.equal(actions.length, 2);
        assert.equal(actions[0].at, 0);
        assert.equal(actions[1].at, 10000);
        assert.equal(actions[0].pos, actions[1].pos);
    });

    it('pins the held position before resuming so players do not drift', () => {
        const samples = [
            ...timeline(2, { speed: 100, strokeMin: 0, strokeMax: 100 }),
            ...timeline(4, { speed: 0, strokeMin: 0, strokeMax: 100 }).map(s => ({ ...s, at: s.at + 2250 })).filter(s => s.at <= 6000),
            ...timeline(2, { speed: 100, strokeMin: 0, strokeMax: 100 }).map(s => ({ ...s, at: s.at + 6250 }))
        ];
        const actions = buildStrokeActions(samples);
        assertMonotonic(actions);
        // Find the resume point: an action at 6250 that repeats the held pos.
        const resumeIdx = actions.findIndex(a => a.at === 6250);
        assert.ok(resumeIdx > 0, 'expected a pin action at the resume time');
        assert.equal(actions[resumeIdx].pos, actions[resumeIdx - 1].pos);
    });

    it('holds across a hole in the recording instead of inventing strokes', () => {
        // 2 s of full-speed strokes, then a 10 s gap with no samples at all
        // (the session was paused, so the toy was stopped), then 1 s more.
        const samples = [
            ...timeline(2, { speed: 100, strokeMin: 0, strokeMax: 100 }),
            ...timeline(1, { speed: 100, strokeMin: 0, strokeMax: 100 }).map(s => ({ ...s, at: s.at + 12000 }))
        ];
        const actions = buildStrokeActions(samples);
        assertMonotonic(actions);
        assertBounds(actions);
        const gapStart = 2000 + SAMPLE_GAP_HOLD_MS + HALF_STROKE_MIN_MS;
        const inGap = actions.filter(a => a.at > gapStart && a.at < 12000);
        assert.equal(inGap.length, 0, 'no strokes may be generated inside the silent gap');
        // The script resumes stroking once samples come back.
        assert.ok(actions.some(a => a.at > 12000), 'expected strokes after the gap');
    });

    it('drops samples that go backwards in time', () => {
        const actions = buildStrokeActions([
            { at: 0, speed: 100 },
            { at: 1000, speed: 100 },
            { at: 500, speed: 100 },
            { at: 2000, speed: 100 }
        ]);
        assertMonotonic(actions);
        const last = actions[actions.length - 1];
        // The timeline ends at 2000 ms; a stroke in flight may overshoot by
        // at most one half-stroke, never by a whole dropped sample.
        assert.ok(last.at >= 2000 && last.at < 2000 + HALF_STROKE_MAX_MS, `last.at=${last.at}`);
    });
});

describe('buildVibrationActions', () => {
    it('emits the level as pos and steps on change', () => {
        const samples = [
            { at: 0, secondary: 20 },
            { at: 250, secondary: 20 },
            { at: 500, secondary: 20 },
            { at: 750, secondary: 80 },
            { at: 1000, secondary: 80 }
        ];
        const actions = buildVibrationActions(samples);
        assertMonotonic(actions);
        assertBounds(actions);
        assert.deepEqual(actions, [
            { at: 0, pos: 20 },
            { at: 500, pos: 20 },
            { at: 750, pos: 80 },
            { at: 1000, pos: 80 }
        ]);
    });

    it('returns nothing for an empty timeline', () => {
        assert.deepEqual(buildVibrationActions([]), []);
    });
});

describe('toFunscript / buildFunscripts', () => {
    it('wraps actions in the standard header', () => {
        const script = toFunscript([{ at: 0, pos: 0 }]);
        assert.equal(script.version, '1.0');
        assert.equal(script.inverted, false);
        assert.equal(script.range, 100);
        assert.equal(script.actions.length, 1);
        assert.deepEqual(toFunscript(null).actions, []);
    });

    it('builds both channels from one timeline', () => {
        const both = buildFunscripts(timeline(3, { speed: 50, secondary: 30, strokeMin: 0, strokeMax: 100 }));
        assert.ok(both.primary.actions.length > 2);
        assert.equal(both.secondary.actions[0].pos, 30);
        assertMonotonic(both.primary.actions);
        assertMonotonic(both.secondary.actions);
    });
});
