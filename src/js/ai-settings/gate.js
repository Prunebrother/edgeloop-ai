// SPDX-License-Identifier: AGPL-3.0-only
// AI Settings Control gate. Pure and deterministic: no DOM, storage, clock or
// network access. app.js passes in the live session context and the user's
// AI settings; the gate answers whether one companion request may be applied
// and, if so, the exact change. Anything not explicitly allowed is rejected.
// The engine applies an accepted change through the same handler as the
// on-page control, so heart-rate limits, watchdogs, device readiness and
// emergency stop keep their own authority. See docs/fork/dev/AI_SETTINGS_CONTROL.md.
import { TEASE_MODES } from '../engine.js';
import { ENDGAME_TYPES } from '../session-rules.js';

// Script mode needs a loaded funscript and is the Player's to choose.
export const AI_PLAY_STYLES = Object.freeze(TEASE_MODES.filter((mode) => mode !== 'script'));
// Calibration changes the user's own heart-rate limits; it is never selectable.
export const AI_GAMES = Object.freeze(['off', 'oracle', 'survival', 'edgetrain']);
export const AI_ENDGAMES = Object.freeze([...ENDGAME_TYPES]);
export const AI_SETTINGS = Object.freeze(['play_style', 'game', 'endgame', 'orgasm', 'intensity', 'pause', 'stop']);
// Only reduce stimulation, so they skip the signal, readiness and rate checks.
const REDUCING = new Set(['pause', 'stop']);

// How often the companion may change something on its own initiative. A change the user asks for
// in chat is not paced by this, only by min_interval_seconds. Seconds since the last AI change
// (or since the user started the session).
export const AI_PACING = Object.freeze({ never: null, rarely: 600, sometimes: 300, often: 120 });

export const AI_SETTINGS_DEFAULTS = Object.freeze({
    enabled: false,
    mode: 'auto',
    pacing: 'sometimes',
    intensity_min: 20,
    intensity_max: 80,
    min_interval_seconds: 45,
    // After a reported orgasm: the recovery before a new round can be set up, and how long the
    // companion may not turn Force Orgasm on by its own choice. The user's own request is not blocked.
    recovery_seconds: 90,
    round_rest_seconds: 180
});
export const AI_RECOVERY_RANGE = Object.freeze({ min: 30, max: 300, step: 10 });
export const AI_ROUND_REST_RANGE = Object.freeze({ min: 0, max: 600, step: 30 });

const REASON_MAX = 240;
const ID_PATTERN = /^[A-Za-z0-9_-]{8,64}$/;

function isPlainObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function wholeInRange(value, lo, hi) {
    return Number.isInteger(value) && value >= lo && value <= hi;
}

// Saved or user-edited settings; invalid fields fall back to the defaults.
export function sanitizeAiSettings(raw) {
    const src = isPlainObject(raw) ? raw : {};
    const out = { ...AI_SETTINGS_DEFAULTS };
    if (typeof src.enabled === 'boolean') out.enabled = src.enabled;
    if (src.mode === 'auto' || src.mode === 'ask') out.mode = src.mode;
    if (Object.hasOwn(AI_PACING, src.pacing)) out.pacing = src.pacing;
    if (wholeInRange(src.intensity_min, 0, 100)) out.intensity_min = src.intensity_min;
    if (wholeInRange(src.intensity_max, 0, 100)) out.intensity_max = src.intensity_max;
    if (out.intensity_min > out.intensity_max) {
        out.intensity_min = AI_SETTINGS_DEFAULTS.intensity_min;
        out.intensity_max = AI_SETTINGS_DEFAULTS.intensity_max;
    }
    if (wholeInRange(src.min_interval_seconds, 15, 600)) out.min_interval_seconds = src.min_interval_seconds;
    if (wholeInRange(src.recovery_seconds, AI_RECOVERY_RANGE.min, AI_RECOVERY_RANGE.max)) out.recovery_seconds = src.recovery_seconds;
    if (wholeInRange(src.round_rest_seconds, AI_ROUND_REST_RANGE.min, AI_ROUND_REST_RANGE.max)) out.round_rest_seconds = src.round_rest_seconds;
    return out;
}

// Model text shown to the user and sent back to the observer: printable, bounded.
export function cleanReason(value) {
    if (typeof value !== 'string') return '';
    return value.replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩]/g, ' ')
        .replace(/\s+/g, ' ').trim().slice(0, REASON_MAX);
}

// Request shape only. Returns {setting, value, id, session_id, reason} or null.
export function parseRequest(raw) {
    if (!isPlainObject(raw) || raw.version !== 1 || raw.type !== 'settings_request') return null;
    if (typeof raw.id !== 'string' || !ID_PATTERN.test(raw.id)) return null;
    if (typeof raw.session_id !== 'string' || raw.session_id.length < 1 || raw.session_id.length > 64) return null;
    if (!AI_SETTINGS.includes(raw.setting)) return null;
    const { setting } = raw;
    let value;
    if (setting === 'play_style') value = AI_PLAY_STYLES.includes(raw.value) ? raw.value : undefined;
    else if (setting === 'game') value = AI_GAMES.includes(raw.value) ? raw.value : undefined;
    else if (setting === 'endgame') value = AI_ENDGAMES.includes(raw.value) ? raw.value : undefined;
    else if (setting === 'orgasm') value = typeof raw.value === 'boolean' ? raw.value : undefined;
    else if (setting === 'intensity') value = wholeInRange(raw.value, 0, 100) ? raw.value : undefined;
    else value = raw.value === undefined || raw.value === null || raw.value === true ? true : undefined;
    if (value === undefined) return null;
    // Absent means the companion's own idea: the stricter case. 'round' is the decision EdgeLoop invites
    // once per reported orgasm when its recovery is over; it sets up the next round, so it never ends,
    // pauses or forces anything.
    const trigger = raw.trigger === undefined ? 'own' : raw.trigger;
    if (trigger !== 'own' && trigger !== 'user' && trigger !== 'round') return null;
    if (trigger === 'round' && (setting === 'pause' || setting === 'stop' || (setting === 'orgasm' && value === true))) return null;
    return { id: raw.id, session_id: raw.session_id, setting, value, trigger, reason: cleanReason(raw.reason) };
}

function reject(reason) {
    return { ok: false, reason };
}

// True when pacing allows an unprompted change now. lastAiAt is the last applied AI change or the user's session start.
export function ownChangeReady(settings, now, lastAiAt) {
    const gap = AI_PACING[sanitizeAiSettings(settings).pacing];
    if (gap === null) return false;
    return !Number.isFinite(lastAiAt) || now - lastAiAt >= gap * 1000;
}

// A new round may be set up once per reported orgasm, after its recovery, and not while Force Orgasm is on.
export function roundOpen(settings, ctx) {
    const s = sanitizeAiSettings(settings);
    return Boolean(ctx?.roundPending) && Number.isFinite(ctx?.sinceOrgasm) && ctx.sinceOrgasm >= s.recovery_seconds
        && !(isPlainObject(ctx.current) && ctx.current.orgasm === true);
}

// ctx: {settings, revoked, remotePage, sessionId, status, signal, toyReady, now (ms), lastAppliedAt (ms|null), lastAiAt (ms|null),
//       sinceOrgasm (session seconds since the last reported orgasm, or null), roundPending (an orgasm has no round yet),
//       current: {play_style, game, endgame, orgasm, intensity}}
export function authorize(raw, ctx) {
    const request = parseRequest(raw);
    if (!request) return reject('invalid_request');
    const settings = sanitizeAiSettings(ctx?.settings);
    if (!settings.enabled) return reject('disabled');
    if (ctx.revoked) return reject('revoked_by_emergency_stop');
    if (ctx.remotePage) return reject('remote_page');
    if (request.session_id !== ctx.sessionId) return reject('stale_session');
    const { setting } = request;
    const status = ctx.status;
    if (setting === 'stop') {
        if (!['RUNNING', 'RAMPDOWN', 'PAUSED'].includes(status)) return reject('not_running');
    } else if (setting === 'pause') {
        if (!['RUNNING', 'RAMPDOWN'].includes(status)) return reject('not_running');
    } else if (status !== 'RUNNING') {
        return reject('not_running');
    }
    if (!REDUCING.has(setting)) {
        if (ctx.signal !== 'ok') return reject('heart_rate_signal_not_ok');
        if (!ctx.toyReady) return reject('device_not_ready');
        if (Number.isFinite(ctx.lastAppliedAt) && ctx.now - ctx.lastAppliedAt < settings.min_interval_seconds * 1000)
            return reject('rate_limited');
        if (request.trigger === 'own' && !ownChangeReady(settings, ctx.now, ctx.lastAiAt))
            return reject(settings.pacing === 'never' ? 'own_changes_off' : 'paced');
        // The invited round decision skips the pacing gap (it is not unprompted), but 'never' still means never.
        if (request.trigger === 'round') {
            if (settings.pacing === 'never') return reject('own_changes_off');
            if (!roundOpen(settings, ctx)) return reject('no_round_open');
        }
        if (request.trigger === 'own' && setting === 'orgasm' && request.value === true
            && Number.isFinite(ctx.sinceOrgasm) && ctx.sinceOrgasm < settings.round_rest_seconds)
            return reject('orgasm_rest');
    }
    const current = isPlainObject(ctx.current) ? ctx.current : {};
    let to = request.value;
    if (setting === 'intensity') to = Math.max(settings.intensity_min, Math.min(settings.intensity_max, to));
    const from = REDUCING.has(setting) ? status : current[setting];
    if (!REDUCING.has(setting) && from === to) return reject('unchanged');
    return {
        ok: true,
        change: { id: request.id, setting, from: from ?? null, to, clamped: to !== request.value, trigger: request.trigger, reason: request.reason }
    };
}
