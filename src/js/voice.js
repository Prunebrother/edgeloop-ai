/**
 * Local TTS prompts and optional microphone arousal monitor.
 *
 * Cues go through a short queue (voice-queue.js) instead of cancelling
 * whatever is being said: back-to-back cues are all heard, duplicates are
 * dropped and at most three wait. Only speakNow() (safety-critical cues)
 * and cancelSpeech() (STOP / Reset / voice turned off) interrupt speech.
 */
import { createCueQueue } from './voice-queue.js';

const queue = createCueQueue({ maxQueued: 3 });
let activeToken = 0;
let fallbackTimer = null;

// Tests replace these hooks to assert that speak() is actually called.
export const speechHooks = {
    getSynth() {
        return typeof window !== 'undefined' ? window.speechSynthesis : null;
    },
    UtteranceCtor() {
        if (typeof SpeechSynthesisUtterance === 'function') return SpeechSynthesisUtterance;
        return typeof window !== 'undefined' ? window.SpeechSynthesisUtterance : null;
    }
};

function synth() {
    return speechHooks.getSynth();
}

export function listSpeechVoices() {
    const s = synth();
    if (!s) return [];
    return s.getVoices() || [];
}

function clearFallbackTimer() {
    if (fallbackTimer) {
        clearTimeout(fallbackTimer);
        fallbackTimer = null;
    }
}

// Speak one utterance and advance the queue when it ends. A token guards
// the callbacks so a cancelled utterance can never pop the NEXT cue, and a
// fallback timer keeps the queue moving on browsers that never fire `end`.
function utter(text, voiceURI) {
    const s = synth();
    const Utterance = speechHooks.UtteranceCtor();
    if (!s || !Utterance) return;
    const token = ++activeToken;
    clearFallbackTimer();
    const utterance = new Utterance(text);
    utterance.rate = 0.95;
    utterance.pitch = 0.92;
    if (voiceURI) {
        const match = listSpeechVoices().find((voice) => voice.voiceURI === voiceURI);
        if (match) utterance.voice = match;
    }
    const done = () => {
        if (token !== activeToken) return;
        clearFallbackTimer();
        const next = queue.next();
        if (next) utter(next, voiceURI);
    };
    utterance.onend = done;
    utterance.onerror = done;
    fallbackTimer = setTimeout(done, 3000 + text.length * 120);
    try {
        s.speak(utterance);
    } catch (e) {
        done();
    }
}

// Enqueue a cue. Nothing already speaking is interrupted.
export function speakPrompt(enabled, text, voiceURI = '') {
    if (!enabled || !text || !synth()) return;
    if (!queue.enqueue(text)) return;
    if (queue.isIdle()) {
        const next = queue.next();
        if (next) utter(next, voiceURI);
    }
}

// Safety-critical cue: drops everything waiting, cuts the current cue and
// speaks `text` immediately.
export function speakNow(text, voiceURI = '') {
    const s = synth();
    if (!text || !s) return;
    activeToken += 1;
    const mine = activeToken;
    clearFallbackTimer();
    queue.jump(text);
    try {
        s.cancel();
    } catch (e) { /* nothing to cancel */ }
    // Chrome drops an utterance queued in the same tick as cancel(); a short
    // delay makes the urgent cue reliable. Skipped if silenced meanwhile.
    setTimeout(() => {
        if (activeToken === mine) utter(text, voiceURI);
    }, 50);
}

// Silence everything: current cue and queue. Used on STOP, Reset and when
// voice guidance is switched off.
export function cancelSpeech() {
    activeToken += 1;
    clearFallbackTimer();
    queue.clear();
    const s = synth();
    if (!s) return;
    try {
        s.cancel();
    } catch (e) { /* nothing to cancel */ }
}

export function setMindgamePrompt(text, visible) {
    const box = document.getElementById('mindgameContainer');
    const el = document.getElementById('mindgamePromptText');
    if (el && text) el.textContent = `"${text}"`;
    if (box) box.classList.toggle('hidden', !visible);
}

// What we ask the browser to capture. The browser's OWN defaults are the
// enemy here: Chrome and Firefox both enable noise suppression (tuned to
// keep speech and throw breathing away) and automatic gain control (which
// moves gain at about 6 dB/s, erasing a 20 dB arousal build in roughly
// three seconds). Left alone, the feature measures exactly what the
// browser is deleting. Every value is `ideal`, never `exact`: a hard
// constraint failure would leave the wearer with no microphone at all,
// which is worse than a processed one.
export const MIC_CAPTURE_CONSTRAINTS = Object.freeze({
    echoCancellation: { ideal: true },
    noiseSuppression: { ideal: false },
    autoGainControl: { ideal: false },
    channelCount: { ideal: 1 }
});

export const MIC_PROCESSING_LABELS = Object.freeze({
    noiseSuppression: 'noise suppression',
    autoGainControl: 'automatic gain control',
    echoCancellation: 'echo cancellation'
});

// Pure: read `track.getSettings()` back and say whether the browser really
// switched the processing off. Anything that is not exactly `false` counts
// as "may still be active" - Safari reports neither flag at all, so an
// `=== true` check would quietly call a processed stream clean.
export function describeMicProcessing(settings) {
    const s = settings && typeof settings === 'object' ? settings : {};
    const active = [];
    const unknown = [];
    for (const key of ['noiseSuppression', 'autoGainControl']) {
        if (s[key] === false) continue;
        active.push(key);
        if (s[key] === undefined) unknown.push(key);
    }
    const clean = active.length === 0;
    const names = active.map((k) => MIC_PROCESSING_LABELS[k]).join(' and ');
    let message;
    if (clean) {
        message = 'Browser audio processing is off. The meter shows real room loudness.';
    } else if (unknown.length === active.length) {
        message = `This browser will not say whether ${names} are on, so assume they are: they flatten a build-up, and your gate is calibrated against a processed signal.`;
    } else {
        message = `Your browser refused to switch off ${names}. It flattens a build-up, so calibrate the gate against what this meter actually shows.`;
    }
    return { clean, active, unknown, message };
}

// Zero the microphone's contribution to the engine and forget the held
// level. Called from every stop path: a boost must never outlive the
// monitor that measured it.
export function clearMicBoost(state) {
    if (!state) return;
    state.micBoost = 0;
    state.micBoostHeld = 0;
    state.micApplied = 0;
    state.micLastLevel = 0;
    state.micSpeechAt = 0;
    state.micHoldSince = 0;
}

// Must be called from inside a user gesture (a click): the AudioContext is
// created and resumed BEFORE the permission prompt awaits, because a context
// created after the gesture has ended starts suspended on most browsers.
// `onLost` is called when the microphone goes away under us (revoked,
// unplugged, grabbed by another app); the boost is already zero by then.
export async function startMicMonitor(state, { onLost = null } = {}) {
    stopMicMonitor(state);
    if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('Microphone not supported in this browser');
    }
    const AudioCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtor) {
        throw new Error('Web Audio not supported in this browser');
    }
    const audioCtx = new AudioCtor();
    try {
        if (audioCtx.state !== 'running') await audioCtx.resume();
    } catch (e) { /* resume is best effort; getUserMedia may still unlock it */ }
    let stream;
    try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: MIC_CAPTURE_CONSTRAINTS, video: false });
    } catch (e) {
        audioCtx.close().catch(() => {});
        throw e;
    }
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.65;
    source.connect(analyser);
    state.micStream = stream;
    state.micAudioCtx = audioCtx;
    state.micAnalyser = analyser;
    clearMicBoost(state);
    const track = stream.getAudioTracks?.()[0] || null;
    state.micProcessing = describeMicProcessing(track?.getSettings?.());
    if (track) {
        // A dead or muted track keeps returning zeroes forever, so without
        // these the last boost stays latched with the badge still lit.
        track.onended = () => {
            stopMicMonitor(state);
            if (onLost) onLost('The microphone stopped (revoked, unplugged or taken by another app).');
        };
        track.onmute = () => {
            // Torn down exactly like `onended`. Clearing the boost alone left
            // the capture, the AudioContext, the analyser and the ~60 Hz
            // meter loop running on a dead stream after the app had already
            // told the wearer the microphone was gone: the browser kept its
            // recording indicator lit, and the meter kept reading "below
            // gate" - the wording for a working microphone in a quiet room.
            stopMicMonitor(state);
            if (onLost) onLost('The microphone went silent (muted by the system or another app).');
        };
    }
    if (audioCtx.state !== 'running') {
        try {
            await audioCtx.resume();
        } catch (e) { /* the level sampler simply reads silence until it runs */ }
    }
}

export function stopMicMonitor(state) {
    // The boost goes first: nothing below may leave it latched if it throws.
    clearMicBoost(state);
    if (state.micAnimId) {
        cancelAnimationFrame(state.micAnimId);
        state.micAnimId = null;
    }
    if (state.micStream) {
        state.micStream.getTracks().forEach((track) => {
            track.onended = null;
            track.onmute = null;
            track.stop();
        });
        state.micStream = null;
    }
    if (state.micAudioCtx) {
        try {
            state.micAudioCtx.close()?.catch?.(() => {});
        } catch (e) { /* already closed */ }
        state.micAudioCtx = null;
    }
    state.micAnalyser = null;
    state.micProcessing = null;
}

// Voice-band gate: ignore rumble from strokers / vibrators (mostly <250 Hz)
// and keep panting, speech and other user noise (roughly 250-4000 Hz).
export const MIC_VOICE_BAND_LO_HZ = 250;
export const MIC_VOICE_BAND_HI_HZ = 4000;
export const MIN_MIC_GATE = 8;
export const MAX_MIC_GATE = 90;
export const DEFAULT_MIC_GATE = 40;

// Extra BPM added to the working heart rate when the wearer is louder
// than the gate. 0 = listen only (meter and badge, no loop effect).
export const MIN_MIC_BOOST_BPM = 0;
export const MAX_MIC_BOOST_BPM = 20;
export const DEFAULT_MIC_BOOST_BPM = 8;

export function clampMicGate(value, fallback = DEFAULT_MIC_GATE) {
    const n = typeof value === 'number' ? Math.round(value) : parseInt(String(value), 10);
    if (!Number.isFinite(n)) return fallback;
    return Math.max(MIN_MIC_GATE, Math.min(MAX_MIC_GATE, n));
}

export function clampMicBoostBpm(value, fallback = DEFAULT_MIC_BOOST_BPM) {
    const n = typeof value === 'number' ? Math.round(value) : parseInt(String(value), 10);
    if (!Number.isFinite(n)) return fallback;
    return Math.max(MIN_MIC_BOOST_BPM, Math.min(MAX_MIC_BOOST_BPM, n));
}

// Map voice-band level (0-100) onto 0..maxBpm. Silence or anything at/under
// the gate is 0; full-band loudness (100) is the cap. Louder = closer to the
// edge. The engine still cannot pass the effective climax ceiling.
export function micBoostFromLevel(level, gate, maxBpm) {
    const cap = clampMicBoostBpm(maxBpm, 0);
    if (cap <= 0) return 0;
    const g = clampMicGate(gate);
    const lv = typeof level === 'number' && Number.isFinite(level) ? level : parseInt(String(level), 10);
    if (!Number.isFinite(lv) || lv <= g) return 0;
    const span = Math.max(1, 100 - g);
    const t = Math.min(1, (lv - g) / span);
    return Math.round(t * cap);
}

// Fold the microphone boost into the heart rate the ENGINE runs on. This is
// the only place room loudness becomes heart rate, and the result is used for
// the speed curve alone: the edge flag, every guard, game, counter, the
// cockpit readout and the session record all judge `sensorHr`, so noise can
// never count an edge, advance a game, end Survival or enter the saved peak.
//
// The boost only ever pushes UP and only as far as the effective ceiling, and
// only on a FRESH reading: during the watchdog's hold window the pulse is
// frozen, and climbing on sound alone would drive the toys off room noise.
export function micBoostedHr({
    sensorHr,
    micBoost = 0,
    heldBoost = 0,
    ceiling,
    micEnabled = false,
    pulseFresh = false
} = {}) {
    if (!Number.isFinite(sensorHr)) return sensorHr;
    if (!micEnabled) return sensorHr;
    const boost = resolveMicBoost({ micBoost, heldBoost, pulseFresh });
    if (boost <= 0) return sensorHr;
    if (!Number.isFinite(ceiling) || sensorHr >= ceiling) return sensorHr;
    return Math.min(ceiling, sensorHr + boost);
}

// Pure: how much boost the engine may use this tick.
//
// On a fresh reading it is the live measurement. During the watchdog's HOLD
// window the pulse is frozen, and so is the boost: it keeps the value
// measured on the LAST fresh reading and neither grows nor drops out.
//
// Growing it there would let sound alone drive the toys while no pulse is
// arriving. Dropping it there is worse, and is what a plain on/off gate did:
// the engine's heart rate fell by the whole boost in a single tick, and in
// every tease mode the speed curve falls as heart rate rises, so the motors
// SPED UP - measured at +31 points on both channels with a 20 BPM cap - at
// the exact moment the reading was least trustworthy. A watch or relay app
// pushing every ~5 s trips the 5 s hold band on ordinary jitter.
//
// `heldBoost` defaults to 0, so a caller that does not track it gets the old
// "no boost without a fresh reading" behaviour. A stale reading pauses the
// session and every stop path calls clearMicBoost(), so nothing is held past
// a dropout that actually matters.
export function resolveMicBoost({ micBoost = 0, heldBoost = 0, pulseFresh = false } = {}) {
    const live = Number.isFinite(micBoost) && micBoost > 0 ? micBoost : 0;
    if (pulseFresh) return live;
    return Number.isFinite(heldBoost) && heldBoost > 0 ? heldBoost : 0;
}

// Pure: average magnitude of analyser frequency bins inside the voice band,
// scaled 0-100. Low-frequency motor noise is dropped on purpose.
export function voiceBandLevel(freqBytes, sampleRate, fftSize) {
    if (!freqBytes || !freqBytes.length) return 0;
    const rate = Number.isFinite(sampleRate) && sampleRate > 0 ? sampleRate : 44100;
    const size = Number.isFinite(fftSize) && fftSize > 0 ? fftSize : (freqBytes.length * 2);
    const binHz = rate / size;
    let sum = 0;
    let n = 0;
    for (let i = 0; i < freqBytes.length; i++) {
        const hz = i * binHz;
        if (hz < MIC_VOICE_BAND_LO_HZ || hz > MIC_VOICE_BAND_HI_HZ) continue;
        const mag = freqBytes[i];
        if (!Number.isFinite(mag)) continue;
        sum += mag;
        n += 1;
    }
    if (!n) return 0;
    return Math.min(100, Math.round((sum / n) / 2.55));
}

// How long after the app stops speaking the sampler stays suppressed, so
// the tail of a cue (and its room reverberation) is not measured either.
export const MIC_SPEECH_TAIL_MS = 700;

// How long the sampler may keep holding one level before it gives up and
// contributes nothing. utter() already carries a fallback timer for
// browsers that never fire `end`; on those same browsers
// `speechSynthesis.speaking` can stay true long after the cue is over, and
// an unbounded hold would latch a boost measured from a room nobody is
// listening to any more. Past this the microphone reads zero until it can
// hear the room again: a stale measurement must never drive the toys.
export const MIC_SPEECH_MAX_HOLD_MS = 10000;

// Pure: is the sampler muted right now because the app itself is talking?
export function micSampleSuppressed({
    speaking = false,
    lastSpeechAt = 0,
    now = 0,
    tailMs = MIC_SPEECH_TAIL_MS
} = {}) {
    if (speaking) return true;
    const last = Number.isFinite(lastSpeechAt) ? lastSpeechAt : 0;
    if (last <= 0) return false;
    const tail = Number.isFinite(tailMs) ? Math.max(0, tailMs) : 0;
    const t = Number.isFinite(now) ? now : 0;
    return t >= last && (t - last) < tail;
}

// The app's own voice cues land squarely in the 250-4000 Hz band this
// sampler was tuned to, and on speakers the echo canceller has no
// reference for them, so every spoken cue read as +6 to +8 BPM of
// "arousal". While the app is speaking (and for a short tail afterwards)
// the last level is HELD instead of measured: the app never hears itself.
export function sampleMicLevel(state, now = Date.now()) {
    const s = synth();
    const speaking = Boolean(s && s.speaking);
    if (speaking) state.micSpeechAt = now;
    const held = Number.isFinite(state.micLastLevel) ? state.micLastLevel : 0;
    if (micSampleSuppressed({ speaking, lastSpeechAt: state.micSpeechAt, now })) {
        if (!Number.isFinite(state.micHoldSince) || !state.micHoldSince) state.micHoldSince = now;
        if (now - state.micHoldSince > MIC_SPEECH_MAX_HOLD_MS) {
            state.micLastLevel = 0;
            return 0;
        }
        return held;
    }
    state.micHoldSince = 0;
    const analyser = state.micAnalyser;
    if (!analyser) {
        state.micLastLevel = 0;
        return 0;
    }
    const data = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(data);
    const sampleRate = state.micAudioCtx?.sampleRate || 44100;
    const level = voiceBandLevel(data, sampleRate, analyser.fftSize);
    state.micLastLevel = level;
    return level;
}
