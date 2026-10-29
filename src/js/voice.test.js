import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
    voiceBandLevel,
    clampMicGate,
    clampMicBoostBpm,
    micBoostFromLevel,
    MIN_MIC_GATE,
    MAX_MIC_GATE,
    DEFAULT_MIC_GATE,
    MIN_MIC_BOOST_BPM,
    MAX_MIC_BOOST_BPM,
    DEFAULT_MIC_BOOST_BPM,
    sampleMicLevel,
    micBoostedHr,
    MIC_CAPTURE_CONSTRAINTS,
    MIC_SPEECH_TAIL_MS,
    MIC_SPEECH_MAX_HOLD_MS,
    describeMicProcessing,
    micSampleSuppressed,
    clearMicBoost,
    startMicMonitor,
    stopMicMonitor,
    speechHooks,
    MIC_VOICE_BAND_LO_HZ,
    MIC_VOICE_BAND_HI_HZ,
    resolveMicBoost
} from './voice.js';
import { calculateEngineOutputs, hasReleasedEdge, resolveEdgeTriggerHr } from './engine.js';

// Slice app.js between two literal anchors, FAILING when either is missing.
//
// A plain `src.slice(src.indexOf(a))` yields the empty string once `a` has
// been renamed (indexOf -1 -> slice(-1) -> one character -> slice(0, -1) ->
// ''), and every NEGATIVE assertion made against '' passes. A guard written
// that way stops guarding on the next innocuous rename, silently, while its
// louder siblings fail and get fixed. Every source-grep test in this file
// goes through here, so a missing anchor is a failure, never a pass.
function anchoredBody(src, startAnchor, endAnchor, { maxLength = 0 } = {}) {
    const start = src.indexOf(startAnchor);
    assert.ok(start >= 0, `anchor not found in app.js: ${startAnchor}`);
    const from = maxLength > 0 ? src.slice(start, start + maxLength) : src.slice(start);
    if (!endAnchor) return from;
    const end = from.indexOf(endAnchor, startAnchor.length);
    assert.ok(end > 0, `end anchor not found after "${startAnchor}": ${endAnchor}`);
    return from.slice(0, end);
}
import { countSurvivalBreach, isSurvivalDefeated, tickEdgeTraining } from './session-rules.js';

const SAMPLE_RATE = 44100;
const FFT_SIZE = 1024;
const BIN_COUNT = FFT_SIZE / 2;
const binHz = SAMPLE_RATE / FFT_SIZE;

function emptyBins() {
    return new Uint8Array(BIN_COUNT);
}

function binsWithEnergy(hz, magnitude = 200) {
    const data = emptyBins();
    const bin = Math.round(hz / binHz);
    if (bin >= 0 && bin < data.length) data[bin] = magnitude;
    return data;
}

describe('microphone voice-band gate', () => {
    it('clamps the noise gate', () => {
        assert.equal(MIN_MIC_GATE, 8);
        assert.equal(MAX_MIC_GATE, 90);
        assert.equal(DEFAULT_MIC_GATE, 40);
        assert.equal(clampMicGate(3), MIN_MIC_GATE);
        assert.equal(clampMicGate(200), MAX_MIC_GATE);
        assert.equal(clampMicGate('42'), 42);
        assert.equal(clampMicGate('abc'), DEFAULT_MIC_GATE);
        assert.equal(MIC_VOICE_BAND_LO_HZ, 250);
        assert.equal(MIC_VOICE_BAND_HI_HZ, 4000);
    });

    it('ignores low-frequency motor rumble', () => {
        const rumble = binsWithEnergy(80, 255);
        assert.equal(voiceBandLevel(rumble, SAMPLE_RATE, FFT_SIZE), 0);
    });

    it('hears energy in the voice band', () => {
        const voice = binsWithEnergy(1000, 255);
        const level = voiceBandLevel(voice, SAMPLE_RATE, FFT_SIZE);
        assert.ok(level > 0);
        assert.ok(level <= 100);
    });

    it('ignores hiss above the voice band', () => {
        const hiss = binsWithEnergy(8000, 255);
        assert.equal(voiceBandLevel(hiss, SAMPLE_RATE, FFT_SIZE), 0);
    });

    it('returns 0 for empty or missing data', () => {
        assert.equal(voiceBandLevel([], SAMPLE_RATE, FFT_SIZE), 0);
        assert.equal(voiceBandLevel(null, SAMPLE_RATE, FFT_SIZE), 0);
        assert.equal(sampleMicLevel({}), 0);
        assert.equal(sampleMicLevel({ micAnalyser: null }), 0);
    });
});

describe('microphone loudness boost', () => {
    it('clamps the extra-BPM cap', () => {
        assert.equal(clampMicBoostBpm(-3), MIN_MIC_BOOST_BPM);
        assert.equal(clampMicBoostBpm(99), MAX_MIC_BOOST_BPM);
        assert.equal(clampMicBoostBpm('8'), DEFAULT_MIC_BOOST_BPM);
        assert.equal(clampMicBoostBpm('nope'), DEFAULT_MIC_BOOST_BPM);
        assert.equal(clampMicBoostBpm(0), 0);
    });

    it('is silent at or under the gate and scales up to the cap', () => {
        assert.equal(micBoostFromLevel(40, 40, 8), 0);
        assert.equal(micBoostFromLevel(20, 40, 8), 0);
        assert.equal(micBoostFromLevel(100, 40, 8), 8);
        assert.equal(micBoostFromLevel(70, 40, 8), 4);
        assert.equal(micBoostFromLevel(100, 40, 0), 0);
        assert.ok(micBoostFromLevel(90, 40, 8) > micBoostFromLevel(50, 40, 8));
    });
});

describe('the microphone boost stays on the engine path', () => {
    const loud = { sensorHr: 132, micBoost: 20, ceiling: 150, micEnabled: true, pulseFresh: true };

    it('adds the boost up to the effective ceiling and never past it', () => {
        assert.equal(micBoostedHr(loud), 150);
        assert.equal(micBoostedHr({ ...loud, sensorHr: 120 }), 140);
        assert.equal(micBoostedHr({ ...loud, sensorHr: 150 }), 150, 'never past the ceiling');
        assert.equal(micBoostedHr({ ...loud, sensorHr: 155 }), 155, 'never downward');
    });

    it('returns the sensor pulse when the monitor is off or silent', () => {
        assert.equal(micBoostedHr({ ...loud, micEnabled: false }), 132);
        assert.equal(micBoostedHr({ ...loud, micBoost: 0 }), 132);
        assert.equal(micBoostedHr({ ...loud, micBoost: -5 }), 132);
        assert.equal(micBoostedHr({ ...loud, micBoost: NaN }), 132);
    });

    it('does not boost a held or stale reading', () => {
        // During the watchdog's hold window hrCurrent is frozen; the engine
        // must not climb on room noise while it waits for a real pulse.
        assert.equal(micBoostedHr({ ...loud, pulseFresh: false }), 132);
    });

    it('freezes the boost through the watchdog hold window instead of dropping it', () => {
        // The hold band is 5 s and is NOT user-configurable (hr-watchdog.js
        // keeps holdMs at 5000; raising the signal-loss timeout, which the
        // README tells watch users to do, never widens it). A watch relaying
        // every ~5 s trips it on ordinary jitter.
        //
        // A binary gate removed the whole boost in one tick, and in every
        // tease mode the speed curve FALLS as heart rate rises, so the toys
        // sped UP at the moment the reading was least trustworthy.
        assert.equal(resolveMicBoost({ micBoost: 20, heldBoost: 0, pulseFresh: true }), 20);
        assert.equal(resolveMicBoost({ micBoost: 20, heldBoost: 8, pulseFresh: false }), 8, 'frozen at the last fresh value');
        assert.equal(resolveMicBoost({ micBoost: 0, heldBoost: 8, pulseFresh: false }), 8, 'a quiet tick cannot drop it either');
        assert.equal(resolveMicBoost({ micBoost: -4, heldBoost: -4, pulseFresh: false }), 0);
        assert.equal(resolveMicBoost({ micBoost: NaN, heldBoost: NaN, pulseFresh: true }), 0);
        assert.equal(resolveMicBoost(), 0);

        // A caller that tracks no held value keeps the old behaviour.
        assert.equal(micBoostedHr({ ...loud, pulseFresh: false }), 132);
        assert.equal(micBoostedHr({ ...loud, pulseFresh: false, heldBoost: 20 }), 150, 'the held boost still applies');

        // Continuity across ok -> holding, on the real engine. Pixel Watch
        // setup from the README: Resting 70 / Climax 150, Classic Tease,
        // gamma 2, mic cap 20, sensor 110.
        const shared = {
            minHr: 70, maxHr: 150, sessionStatus: 'RUNNING', activeMode: 'classic', gamma: 2, intensityValue: 50
        };
        const sensorHr = 110;
        const fresh = micBoostedHr({ sensorHr, micBoost: 20, heldBoost: 20, ceiling: 150, micEnabled: true, pulseFresh: true });
        const holding = micBoostedHr({ sensorHr, micBoost: 20, heldBoost: 20, ceiling: 150, micEnabled: true, pulseFresh: false });
        const before = calculateEngineOutputs({ ...shared, hr: fresh, edgeHr: sensorHr, isEdged: false });
        const during = calculateEngineOutputs({ ...shared, hr: holding, edgeHr: sensorHr, isEdged: false });
        assert.equal(during.primaryPercent, before.primaryPercent, 'a missed packet must not move the stroker');
        assert.equal(during.secondaryPercent, before.secondaryPercent, 'nor the vibrator');

        // What the old gate did: a 31-point surge on both channels.
        const dropped = calculateEngineOutputs({ ...shared, hr: sensorHr, edgeHr: sensorHr, isEdged: false });
        assert.ok(dropped.primaryPercent - before.primaryPercent > 25, 'the regression this pins is a real surge');
    });

    it('leaves a missing or broken pulse alone', () => {
        assert.ok(Number.isNaN(micBoostedHr({ ...loud, sensorHr: NaN })));
        assert.equal(micBoostedHr({ ...loud, ceiling: NaN }), 132);
        assert.equal(micBoostedHr(), undefined);
    });

    it('room noise cannot count an edge or advance Edge Training', () => {
        // Real pulse 132, typed Climax 150, a room at voice-band level 100.
        const sensorHr = 132;
        const ceiling = 150;
        const engineHr = micBoostedHr({ sensorHr, micBoost: 20, ceiling, micEnabled: true, pulseFresh: true });
        assert.equal(engineHr, ceiling);

        const shared = { minHr: 60, maxHr: ceiling, sessionStatus: 'RUNNING', activeMode: 'edgetrain', trainingState: 'climb' };
        const out = calculateEngineOutputs({ ...shared, hr: engineHr, edgeHr: sensorHr, isEdged: false });
        assert.equal(out.newEdgeTriggered, false, 'noise must not count an edge');
        assert.equal(out.isEdged, false);

        const train = tickEdgeTraining(
            { state: 'climb', holdSeconds: 0, edgesDone: 0 },
            {
                isEdged: out.isEdged,
                released: hasReleasedEdge(sensorHr, ceiling, resolveEdgeTriggerHr(ceiling, 100, 60)),
                holdGoal: 15,
                edgesGoal: 5,
                orgasmMode: false
            }
        );
        assert.equal(train.state, 'climb', 'noise must not start a hold');
        assert.equal(train.edgesDone, 0);
        assert.equal(train.justFinished, false, 'noise must never arm Force Orgasm');

        // Nor may it drive the two CLIMB games harder. Their ramp is
        // `48 + progress * 52` - inverted against every tease mode - so a
        // boosted progress would push the primary UP, and `micBoostedHr` caps
        // the boost at the ceiling, not at the pullback mark, so room noise
        // could pin it at 100% for the last BPM of the approach: hardest
        // exactly where the wearer is closest to climax. Those ramps read the
        // sensor alone.
        const quietTrain = calculateEngineOutputs({ ...shared, hr: sensorHr, edgeHr: sensorHr, isEdged: false });
        assert.equal(out.primaryPercent, quietTrain.primaryPercent, 'noise must not speed up the Edge Training climb');
        assert.equal(out.secondaryPercent, quietTrain.secondaryPercent);

        const oracleShared = { ...shared, activeMode: 'oracle', oracleState: 'APPROACH' };
        const oracleLoud = calculateEngineOutputs({ ...oracleShared, hr: engineHr, edgeHr: sensorHr, isEdged: false });
        const oracleQuiet = calculateEngineOutputs({ ...oracleShared, hr: sensorHr, edgeHr: sensorHr, isEdged: false });
        assert.equal(oracleLoud.primaryPercent, oracleQuiet.primaryPercent, 'noise must not speed up the Oracle approach');

        // In a tease mode the curve FALLS with heart rate, so the boost does
        // what the design says: a louder wearer is treated as closer to the
        // edge and the toys back off.
        const teaseShared = { ...shared, activeMode: 'classic' };
        const teaseLoud = calculateEngineOutputs({ ...teaseShared, hr: engineHr, edgeHr: sensorHr, isEdged: false });
        const teaseQuiet = calculateEngineOutputs({ ...teaseShared, hr: sensorHr, edgeHr: sensorHr, isEdged: false });
        assert.ok(teaseLoud.primaryPercent < teaseQuiet.primaryPercent, 'a louder wearer is teased more slowly');
    });

    it('app.js gates the boost on a LIVE reading, not merely a non-stale one', () => {
        // pulseIsFresh() is true throughout the watchdog's hold window, where
        // hrCurrent is frozen. If the call site used it alone the engine would
        // still climb on room noise during a dropout, which is exactly what
        // the README and the Audio tab promise it does not do.
        const src = readFileSync(new URL('./app.js', import.meta.url), 'utf8');
        const args = anchoredBody(src, 'micBoostedHr({', '});');
        assert.ok(args.includes('pulseFresh'), 'the boost must be gated on the reading');
        assert.ok(
            /const pulseFresh = pulseIsLive\(\);/.test(src),
            'app.js must gate the boost on pulseIsLive(), not on pulseIsFresh()'
        );
        assert.ok(
            args.includes('heldBoost:'),
            'and it must hand over the held boost, so a hold window freezes it rather than dropping it'
        );
        // ...and pulseIsLive() must mean the watchdog's own 'ok', so the gate
        // cannot drift out of step with a verdict mirrored into state.
        const gate = anchoredBody(src, 'function pulseIsLive(', '}');
        assert.ok(
            /hrWatchdog\.status\([^)]*\)\s*===\s*'ok'/.test(gate),
            "pulseIsLive() must read the watchdog status and accept only 'ok'"
        );
    });

    it('the MIC badge reports the boost that was applied, not the raw level', () => {
        // The cockpit BPM number reads the sensor now, so the badge is the
        // only place the wearer sees the boost. It must go dark whenever
        // micBoostedHr() suppressed it (no live reading, or already at the
        // ceiling) instead of announcing a push that is not happening.
        assert.equal(micBoostedHr({ sensorHr: 150, micBoost: 8, ceiling: 150, micEnabled: true, pulseFresh: true }), 150);
        assert.equal(micBoostedHr({ sensorHr: 120, micBoost: 8, ceiling: 150, micEnabled: true, pulseFresh: false }), 120);

        const src = readFileSync(new URL('./app.js', import.meta.url), 'utf8');
        const branch = anchoredBody(src, "getElementById('micActiveBadge')", 'MIC LISTEN');
        assert.ok(!/state\.micBoost/.test(branch), 'the badge must not read the raw state.micBoost');
        assert.ok(/micApplied/.test(branch), 'the badge must read the applied delta');
    });

    it('room noise cannot end Survival or enter the saved peak', () => {
        const sensorHr = 144;
        const ceiling = 150;
        const engineHr = micBoostedHr({ sensorHr, micBoost: 8, ceiling, micEnabled: true, pulseFresh: true });
        assert.equal(engineHr, ceiling);

        let ticks = 0;
        for (let i = 0; i < 5; i++) ticks = countSurvivalBreach(ticks, sensorHr, ceiling, true);
        assert.equal(ticks, 0, 'the sensor pulse never breached the ceiling');
        assert.equal(isSurvivalDefeated(ticks), false);

        // What app.js compares against state.peakHr and paints on the cockpit
        // is the sensor value, so a pulse that was never measured cannot be
        // stored in the session record.
        const peakHr = Math.max(140, sensorHr);
        assert.equal(peakHr, 144);
        assert.notEqual(peakHr, engineHr);
    });
});


// --- Package B: the measurement itself and its lifecycle -------------------

function bandBins(magnitude) {
    const data = emptyBins();
    for (let i = 0; i < data.length; i++) {
        const hz = i * binHz;
        if (hz >= MIC_VOICE_BAND_LO_HZ && hz <= MIC_VOICE_BAND_HI_HZ) data[i] = magnitude;
    }
    return data;
}

function analyserState(magnitude) {
    let bins = bandBins(magnitude);
    const state = {
        micBoost: 0,
        micLastLevel: 0,
        micSpeechAt: 0,
        setRoomMagnitude(next) { bins = bandBins(next); },
        micAudioCtx: { sampleRate: SAMPLE_RATE, close: async () => {} },
        micAnalyser: {
            fftSize: FFT_SIZE,
            frequencyBinCount: BIN_COUNT,
            getByteFrequencyData(target) { target.set(bins.subarray(0, target.length)); }
        }
    };
    return state;
}

function withSynth(synth, fn) {
    const original = speechHooks.getSynth;
    speechHooks.getSynth = () => synth;
    try {
        return fn();
    } finally {
        speechHooks.getSynth = original;
    }
}

describe('microphone capture constraints', () => {
    it('asks the browser to switch its audio processing off, but never hard-fails', () => {
        // AGC moves gain at ~6 dB/s and erases a 20 dB build in about three
        // seconds; noise suppression is tuned to discard breathing. Both must
        // be requested OFF, and with `ideal` so a browser that cannot honour
        // them still gives the wearer a microphone.
        assert.deepEqual(MIC_CAPTURE_CONSTRAINTS.noiseSuppression, { ideal: false });
        assert.deepEqual(MIC_CAPTURE_CONSTRAINTS.autoGainControl, { ideal: false });
        assert.deepEqual(MIC_CAPTURE_CONSTRAINTS.echoCancellation, { ideal: true });
        assert.deepEqual(MIC_CAPTURE_CONSTRAINTS.channelCount, { ideal: 1 });
        for (const value of Object.values(MIC_CAPTURE_CONSTRAINTS)) {
            assert.ok(!('exact' in value), 'a hard constraint would leave the user with no microphone');
        }
    });

    it('treats an unreported flag as still active, never as clean', () => {
        // Safari reports neither noiseSuppression nor autoGainControl, so an
        // `=== true` check would call a fully processed stream clean.
        const safari = describeMicProcessing({ echoCancellation: true });
        assert.equal(safari.clean, false);
        assert.deepEqual(safari.active, ['noiseSuppression', 'autoGainControl']);
        assert.deepEqual(safari.unknown, ['noiseSuppression', 'autoGainControl']);
        assert.match(safari.message, /will not say/);

        const refused = describeMicProcessing({ noiseSuppression: true, autoGainControl: false });
        assert.equal(refused.clean, false);
        assert.deepEqual(refused.active, ['noiseSuppression']);
        assert.deepEqual(refused.unknown, []);
        assert.match(refused.message, /noise suppression/);

        const honoured = describeMicProcessing({ noiseSuppression: false, autoGainControl: false });
        assert.equal(honoured.clean, true);
        assert.deepEqual(honoured.active, []);

        // A browser that returns nothing at all is not evidence of a clean stream.
        assert.equal(describeMicProcessing(undefined).clean, false);
        assert.equal(describeMicProcessing(null).clean, false);
    });
});

describe('the microphone never hears the app', () => {
    it('suppresses the sampler while speaking and for a short tail', () => {
        assert.equal(micSampleSuppressed({ speaking: true, now: 1000, lastSpeechAt: 0 }), true);
        assert.equal(micSampleSuppressed({ speaking: false, lastSpeechAt: 1000, now: 1000 }), true);
        assert.equal(micSampleSuppressed({ speaking: false, lastSpeechAt: 1000, now: 1000 + MIC_SPEECH_TAIL_MS - 1 }), true);
        assert.equal(micSampleSuppressed({ speaking: false, lastSpeechAt: 1000, now: 1000 + MIC_SPEECH_TAIL_MS }), false);
        assert.equal(micSampleSuppressed({ speaking: false, lastSpeechAt: 0, now: 5000 }), false);
        assert.equal(micSampleSuppressed(), false);
    });

    it('holds the last level instead of measuring its own text-to-speech', () => {
        // Every spoken cue lands in the 250-4000 Hz band the sampler uses and
        // on speakers the echo canceller has no reference for it, so the app
        // used to read its own voice as +6 to +8 BPM of arousal.
        const state = analyserState(60);
        const quiet = withSynth({ speaking: false }, () => sampleMicLevel(state, 10_000));
        assert.ok(quiet > 0);
        assert.equal(state.micLastLevel, quiet);

        // The cue starts: the room now reads far louder, but all of that
        // extra energy is the app's own voice coming back off the speakers.
        state.setRoomMagnitude(230);
        const whileSpeaking = withSynth({ speaking: true }, () => sampleMicLevel(state, 11_000));
        assert.equal(whileSpeaking, quiet, 'the app must not hear itself');
        assert.equal(state.micSpeechAt, 11_000);
        assert.equal(state.micLastLevel, quiet, 'the held level is not overwritten by the cue');

        const inTail = withSynth({ speaking: false }, () => sampleMicLevel(state, 11_000 + MIC_SPEECH_TAIL_MS - 1));
        assert.equal(inTail, quiet, 'the tail of a cue is not a measurement either');

        const after = withSynth({ speaking: false }, () => sampleMicLevel(state, 11_000 + MIC_SPEECH_TAIL_MS));
        assert.ok(after > quiet, 'the room is measured again once the tail has passed');
        assert.equal(state.micLastLevel, after);

        // And the suppressed reading is not a free pass to zero either: a
        // held level keeps the boost where it was, it does not invent one.
        assert.equal(micBoostFromLevel(whileSpeaking, DEFAULT_MIC_GATE, DEFAULT_MIC_BOOST_BPM),
            micBoostFromLevel(quiet, DEFAULT_MIC_GATE, DEFAULT_MIC_BOOST_BPM));
    });

    it('a held level has a shelf life: a stuck speech flag cannot latch a boost', () => {
        // utter() already carries a fallback timer "for browsers that never
        // fire end"; on those same browsers speechSynthesis.speaking can stay
        // true after the cue is over. Holding the last level forever would
        // latch a boost on a room nobody is measuring any more - exactly the
        // failure the stop-path clearing exists to prevent. Past the shelf
        // life the microphone contributes nothing.
        const state = analyserState(200);
        const measured = withSynth({ speaking: false }, () => sampleMicLevel(state, 0));
        assert.ok(measured > 0);

        // The room falls silent, so anything non-zero from here is the hold.
        state.setRoomMagnitude(0);
        const stuck = { speaking: true };
        assert.equal(withSynth(stuck, () => sampleMicLevel(state, 1_000)), measured);
        assert.equal(
            withSynth(stuck, () => sampleMicLevel(state, 1_000 + MIC_SPEECH_MAX_HOLD_MS)),
            measured,
            'a normal cue still holds the last level'
        );
        const lapsed = withSynth(stuck, () => sampleMicLevel(state, 1_000 + MIC_SPEECH_MAX_HOLD_MS + 1));
        assert.equal(lapsed, 0, 'a hold that never ends must fall to zero, not latch');
        assert.equal(state.micLastLevel, 0);
        assert.equal(micBoostFromLevel(lapsed, DEFAULT_MIC_GATE, DEFAULT_MIC_BOOST_BPM), 0);
    });

    it('the hold clock restarts after the app falls silent', () => {
        const state = analyserState(200);
        const measured = withSynth({ speaking: false }, () => sampleMicLevel(state, 1_000));
        assert.ok(measured > 0);
        assert.equal(withSynth({ speaking: true }, () => sampleMicLevel(state, 2_000)), measured);
        assert.equal(withSynth({ speaking: false }, () => sampleMicLevel(state, 3_000)), measured);
        // A cue much later still gets a full shelf life of its own.
        assert.equal(
            withSynth({ speaking: true }, () => sampleMicLevel(state, 30_000)),
            measured,
            'a later cue gets a fresh hold, not the old clock'
        );
    });

    it('still returns zero with no analyser', () => {
        assert.equal(sampleMicLevel({}), 0);
    });
});

describe('microphone boost lifecycle', () => {
    it('clearMicBoost zeroes the boost and the held level', () => {
        const state = { micBoost: 7, micApplied: 7, micLastLevel: 63, micSpeechAt: 99, micHoldSince: 5 };
        clearMicBoost(state);
        assert.equal(state.micBoost, 0);
        assert.equal(state.micApplied, 0, 'the badge must not keep claiming a boost either');
        assert.equal(state.micHoldSince, 0);
        assert.equal(state.micLastLevel, 0);
        assert.equal(state.micSpeechAt, 0);
        assert.doesNotThrow(() => clearMicBoost(null));
    });

    it('stopMicMonitor drops the boost with the monitor', () => {
        const state = analyserState(200);
        state.micBoost = 9;
        state.micProcessing = { clean: false };
        let stopped = 0;
        state.micStream = { getTracks: () => [{ stop() { stopped += 1; } }] };
        stopMicMonitor(state);
        assert.equal(stopped, 1);
        assert.equal(state.micAnalyser, null);
        assert.equal(state.micProcessing, null);
        assert.equal(state.micBoost, 0, 'a boost must never outlive the monitor that measured it');
        assert.equal(state.micLastLevel, 0);
    });

    it('a lost microphone is reported and the boost goes to zero', async () => {
        const track = {
            getSettings: () => ({ noiseSuppression: true, autoGainControl: undefined }),
            stop() { this.stopped = true; },
            stopped: false
        };
        const stream = { getAudioTracks: () => [track], getTracks: () => [track] };
        const audioCtx = {
            state: 'running',
            sampleRate: SAMPLE_RATE,
            resume: async () => {},
            close: async () => {},
            createMediaStreamSource: () => ({ connect() {} }),
            createAnalyser: () => ({ fftSize: 0, smoothingTimeConstant: 0, frequencyBinCount: BIN_COUNT, getByteFrequencyData() {} })
        };
        let asked = null;
        const priorNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
        Object.defineProperty(globalThis, 'navigator', {
            value: { mediaDevices: { getUserMedia: async (c) => { asked = c; return stream; } } },
            configurable: true,
            writable: true
        });
        globalThis.window = { AudioContext: function () { return audioCtx; } };
        try {
            const state = { micBoost: 0, micLastLevel: 0, micSpeechAt: 0 };
            const lost = [];
            await startMicMonitor(state, { onLost: (m) => lost.push(m) });

            assert.deepEqual(asked.audio, MIC_CAPTURE_CONSTRAINTS, 'the constraints must reach getUserMedia');
            assert.equal(state.micProcessing.clean, false, 'the refusal must be surfaced');
            assert.deepEqual(state.micProcessing.active, ['noiseSuppression', 'autoGainControl']);
            assert.equal(typeof track.onended, 'function');
            assert.equal(typeof track.onmute, 'function');

            const onmute = track.onmute;
            const onended = track.onended;

            state.micBoost = 8;
            onmute();
            assert.equal(state.micBoost, 0, 'a muted microphone must not leave a boost latched');
            // The app has just told the wearer the microphone is gone, so the
            // capture, the AudioContext, the analyser and the ~60 Hz meter
            // loop must be gone too: otherwise the browser keeps its
            // recording indicator lit on a device the app declared lost and
            // the meter keeps reading "below gate" off a dead stream.
            assert.equal(state.micAnalyser, null, 'onmute must tear the monitor down');
            assert.equal(state.micStream, null);
            assert.equal(state.micAudioCtx, null);
            assert.equal(track.stopped, true, 'the capture track must be stopped');
            assert.equal(lost.length, 1);

            state.micBoost = 8;
            onended();
            assert.equal(state.micBoost, 0, 'a dead microphone must not leave a boost latched');
            assert.equal(state.micAnalyser, null, 'and the badge condition must go false');
            assert.equal(lost.length, 2);
        } finally {
            delete globalThis.window;
            if (priorNavigator) Object.defineProperty(globalThis, 'navigator', priorNavigator);
            else delete globalThis.navigator;
        }
    });
});

describe('the microphone cannot reach the engine by the back door', () => {
    const src = readFileSync(new URL('./app.js', import.meta.url), 'utf8');

    it('the running engine reads the applied gate and cap, not the modal sliders', () => {
        const body = anchoredBody(src, 'function tickSessionGuardsAndGames', 'paintMicMeter(level)');
        assert.ok(/micBoostFromLevel\(/.test(body));
        assert.ok(
            /clampMicGate\(advancedSettings\.micSensitivityThreshold\)/.test(body),
            'the gate must come from the applied settings'
        );
        assert.ok(
            /clampMicBoostBpm\(advancedSettings\.micBoostMaxBpm\)/.test(body),
            'the cap must come from the applied settings'
        );
        assert.ok(!/liveMicGate\(\)/.test(body), 'a dragged slider must not change a running session');
        assert.ok(!/liveMicBoostCap\(\)/.test(body), 'a dragged slider must not change a running session');
    });

    it('the meter paints without driving the engine', () => {
        // Both assertions below are negative, so the body must be proved to
        // exist first: anchoredBody() fails on a missing anchor instead of
        // handing back '' (against which every negative assertion passes).
        const body = anchoredBody(src, 'function paintMicMeter', '\nfunction renderMicProcessingNote');
        assert.ok(body.includes('micLevelBar'), 'the meter body must have been found');
        assert.ok(!/updateEngine\(\)/.test(body), 'a ~60 Hz animation frame must not re-enter the engine');
        assert.ok(!/state\.micBoost\s*=/.test(body), 'only the once-a-second tick owns the boost');
    });

    it('every stop path clears the boost', () => {
        for (const fn of ['function resetSessionCounters', 'function pauseSession']) {
            const body = anchoredBody(src, fn, '', { maxLength: 1400 });
            assert.ok(/clearMicBoost\(state\)/.test(body), `${fn} must clear the microphone boost`);
        }
        // STOP and Reset both run resetSessionCounters().
        for (const fn of ['function stopSession', "resetBtn?.addEventListener('click'"]) {
            const body = anchoredBody(src, fn, '', { maxLength: 1600 });
            assert.ok(/resetSessionCounters\(\)/.test(body), `${fn} must go through resetSessionCounters`);
        }
    });

    it('the slider preview is confined to Session Setup while it is on screen', () => {
        // closeModal() hides the overlay only; #modalBodyParams keeps its
        // visible state until some other modal is opened, so that class on
        // its own is not evidence that Session Setup is still up. Read it
        // alone and a dragged, never-applied gate goes on driving the meter
        // and the cockpit badge for the rest of the session.
        const body = anchoredBody(src, 'function paramsModalOpen', '\n}');
        assert.ok(/overlay/.test(body), 'a dismissed modal must not count as open');
    });

    it('the cockpit badge shows what the engine applied, not the meter preview', () => {
        // paintMicMeter runs from the ~60 Hz meter loop and would otherwise
        // overwrite the honest badge updateEngine just painted, announcing
        // MIC +N from a raw level while the boost was suppressed (watchdog
        // holding a reading, or the pulse already at the ceiling).
        const body = anchoredBody(src, 'function paintMicMeter', '\nfunction renderMicProcessingNote');
        assert.ok(/state\.micApplied/.test(body), 'the badge must read the applied delta');
        const badge = anchoredBody(body, 'if (badge &&', '');
        assert.ok(!/\bboost\b/.test(badge), 'the meter preview must not reach the cockpit badge');
        assert.ok(/MIC \+\$\{applied\}/.test(badge), 'the badge must print the applied delta');
    });

    it('the MIC badge is hidden again when the monitor is not live', () => {
        const engineBlock = anchoredBody(src, "const micBadge = document.getElementById('micActiveBadge')", 'state.effectiveMinHr');
        assert.ok(/classList\.add\('hidden'\)/.test(engineBlock), 'the cockpit badge must be able to go dark');

        const paintBlock = anchoredBody(src, 'function paintMicMeter', '\nfunction renderMicProcessingNote');
        const tail = anchoredBody(paintBlock, 'MIC LISTEN', '');
        assert.ok(
            /else if \(badge\)[\s\S]*classList\.add\('hidden'\)/.test(tail),
            'Test microphone with the toggle off must not leave MIC LISTEN lit forever'
        );
    });
});
