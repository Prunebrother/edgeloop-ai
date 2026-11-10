// SPDX-License-Identifier: AGPL-3.0-only
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { authorize, parseRequest, sanitizeAiSettings, cleanReason, AI_PLAY_STYLES, AI_GAMES, AI_SETTINGS_DEFAULTS } from './gate.js';

const request = (setting, value, extra = {}) => ({ version: 1, type: 'settings_request', id: 'req_00000001', session_id: 's1', setting, value, reason: 'because', ...extra });
const context = (extra = {}) => ({
    settings: { enabled: true }, revoked: false, remotePage: false, sessionId: 's1', status: 'RUNNING', signal: 'ok', toyReady: true,
    now: 100000, lastAppliedAt: null,
    current: { play_style: 'classic', game: 'off', endgame: 'orgasm', orgasm: false, intensity: 50 },
    ...extra
});

test('defaults: off, auto mode, a bounded intensity band', () => {
    assert.deepEqual(sanitizeAiSettings(undefined), AI_SETTINGS_DEFAULTS);
    assert.equal(AI_SETTINGS_DEFAULTS.enabled, false);
    assert.equal(AI_SETTINGS_DEFAULTS.mode, 'auto');
    assert.deepEqual(sanitizeAiSettings({ intensity_min: 90, intensity_max: 10 }), AI_SETTINGS_DEFAULTS);
    assert.deepEqual(sanitizeAiSettings({ enabled: 'yes', mode: 'yolo', min_interval_seconds: 1 }), AI_SETTINGS_DEFAULTS);
});

test('every allowed setting applies with a valid value', () => {
    const cases = [['play_style', 'bratty'], ['game', 'oracle'], ['game', 'off', { game: 'survival' }], ['endgame', 'denial'],
        ['orgasm', true], ['intensity', 70], ['pause', true], ['stop', true]];
    for (const [setting, value, current] of cases) {
        const ctx = context();
        if (current) Object.assign(ctx.current, current);
        const result = authorize(request(setting, value), ctx);
        assert.equal(result.ok, true, `${setting}: ${result.reason}`);
        assert.equal(result.change.setting, setting);
    }
});

test('forbidden settings and values are rejected as invalid', () => {
    for (const [setting, value] of [['SESSION_STATE', 'RUNNING'], ['resume', true], ['start', true], ['reset', true], ['duration', 30],
        ['speed_window', [0, 100]], ['manual_pattern', 'wave'], ['max_hr', 200], ['device', 'handy'], ['play_style', 'script'],
        ['game', 'calibrate'], ['game', 'nnn'], ['endgame', 'explode'], ['orgasm', 'on'], ['intensity', 101], ['intensity', 50.5],
        ['intensity', '70'], ['pause', false], ['__proto__', 1], ['play_style', 'constructor']]) {
        assert.deepEqual(authorize(request(setting, value), context()), { ok: false, reason: 'invalid_request' }, `${setting}=${value}`);
    }
    assert.ok(!AI_PLAY_STYLES.includes('script'));
    assert.ok(!AI_GAMES.includes('calibrate'));
});

test('garbage requests never throw and are rejected', () => {
    for (const raw of [null, undefined, 1, 'pause', [], {}, { type: 'settings_request' }, request('pause', true, { version: 2 }),
        request('pause', true, { id: 'x' }), request('pause', true, { id: '../../etc' }), request('pause', true, { session_id: '' })]) {
        assert.equal(authorize(raw, context()).ok, false);
    }
    assert.equal(authorize(request('pause', true), undefined).ok, false);
});

test('disabled, revoked, remote pages and other sessions are refused', () => {
    assert.equal(authorize(request('pause', true), context({ settings: {} })).reason, 'disabled');
    assert.equal(authorize(request('pause', true), context({ revoked: true })).reason, 'revoked_by_emergency_stop');
    assert.equal(authorize(request('stop', true), context({ revoked: true })).reason, 'revoked_by_emergency_stop');
    assert.equal(authorize(request('pause', true), context({ remotePage: true })).reason, 'remote_page');
    assert.equal(authorize(request('intensity', 60), context({ sessionId: 's2' })).reason, 'stale_session');
});

test('the AI can only act on a running session and never starts or resumes one', () => {
    for (const status of ['IDLE', 'PAUSED', 'RAMPDOWN']) {
        for (const [setting, value] of [['play_style', 'bratty'], ['orgasm', true], ['intensity', 60]])
            assert.equal(authorize(request(setting, value), context({ status })).reason, 'not_running', `${setting} in ${status}`);
    }
    assert.equal(authorize(request('pause', true), context({ status: 'PAUSED' })).reason, 'not_running');
    assert.equal(authorize(request('pause', true), context({ status: 'RAMPDOWN' })).ok, true);
    assert.equal(authorize(request('stop', true), context({ status: 'PAUSED' })).ok, true);
    assert.equal(authorize(request('stop', true), context({ status: 'IDLE' })).reason, 'not_running');
});

test('changes need a fresh heart-rate signal and a ready toy; pause and stop do not', () => {
    for (const signal of ['holding', 'stale', 'missing', undefined]) {
        assert.equal(authorize(request('endgame', 'denial'), context({ signal })).reason, 'heart_rate_signal_not_ok');
        assert.equal(authorize(request('pause', true), context({ signal })).ok, true);
    }
    assert.equal(authorize(request('play_style', 'milker'), context({ toyReady: false })).reason, 'device_not_ready');
    assert.equal(authorize(request('stop', true), context({ toyReady: false, signal: 'stale' })).ok, true);
});

test('rate limit between applied changes; pause and stop are exempt', () => {
    const recent = context({ now: 100000, lastAppliedAt: 100000 - 44000 });
    assert.equal(authorize(request('intensity', 60), recent).reason, 'rate_limited');
    assert.equal(authorize(request('pause', true), recent).ok, true);
    assert.equal(authorize(request('intensity', 60), context({ now: 100000, lastAppliedAt: 100000 - 45000 })).ok, true);
    const slow = context({ settings: { enabled: true, min_interval_seconds: 120 }, now: 100000, lastAppliedAt: 100000 - 60000 });
    assert.equal(authorize(request('intensity', 60), slow).reason, 'rate_limited');
});

test('intensity is clamped into the user band and reports what was applied', () => {
    const high = authorize(request('intensity', 100), context());
    assert.deepEqual([high.change.to, high.change.clamped], [80, true]);
    const low = authorize(request('intensity', 0), context({ settings: { enabled: true, intensity_min: 30, intensity_max: 60 } }));
    assert.deepEqual([low.change.from, low.change.to, low.change.clamped], [50, 30, true]);
    assert.equal(authorize(request('intensity', 95), context({ current: { intensity: 80 } })).reason, 'unchanged');
});

test('a no-op change is rejected so no card announces it', () => {
    assert.equal(authorize(request('play_style', 'classic'), context()).reason, 'unchanged');
    assert.equal(authorize(request('orgasm', false), context()).reason, 'unchanged');
    assert.equal(authorize(request('game', 'off'), context()).reason, 'unchanged');
});

test('the reason is printable and bounded', () => {
    assert.equal(cleanReason('a\u0000b‮c\n\nd'), 'a b c d');
    assert.equal(cleanReason('x'.repeat(500)).length, 240);
    assert.equal(cleanReason(42), '');
    assert.equal(parseRequest(request('pause', true, { reason: undefined })).reason, '');
});

test('a request without a trigger counts as the companion\'s own idea; unknown triggers are invalid', async () => {
    const { ownChangeReady } = await import('./gate.js');
    assert.equal(parseRequest(request('pause', true)).trigger, 'own');
    assert.equal(parseRequest(request('pause', true, { trigger: 'user' })).trigger, 'user');
    assert.equal(parseRequest(request('pause', true, { trigger: 'admin' })), null);
    assert.equal(authorize(request('intensity', 60), context({ lastAiAt: 100000 - 10000 })).reason, 'paced');
    assert.equal(authorize(request('intensity', 60, { trigger: 'user' }), context({ lastAiAt: 100000 - 10000 })).ok, true);
    assert.equal(ownChangeReady({ pacing: 'often' }, 120000, 0), true);
    assert.equal(ownChangeReady({ pacing: 'never' }, 10 ** 12, 0), false);
});

test('round: the invited next-round decision skips pacing once a round is open, and never ends, pauses or forces', () => {
    const paced = { lastAiAt: 99000, settings: { enabled: true, pacing: 'sometimes' } };
    assert.equal(authorize(request('play_style', 'milker', { trigger: 'own' }), context(paced)).reason, 'paced');
    const result = authorize(request('play_style', 'milker', { trigger: 'round' }), context({ ...paced, roundPending: true, sinceOrgasm: 90 }));
    assert.equal(result.ok, true);
    assert.equal(result.change.trigger, 'round');
    assert.equal(authorize(request('play_style', 'milker', { trigger: 'round' }), context(paced)).reason, 'no_round_open');
    assert.equal(authorize(request('play_style', 'milker', { trigger: 'round' }),
        context({ roundPending: true, sinceOrgasm: 90, settings: { enabled: true, pacing: 'never' } })).reason, 'own_changes_off');
    for (const [setting, value] of [['orgasm', true], ['pause', true], ['stop', true]])
        assert.equal(authorize(request(setting, value, { trigger: 'round' }), context({ roundPending: true, sinceOrgasm: 90 })).reason, 'invalid_request');
    assert.equal(authorize(request('play_style', 'milker', { trigger: 'round' }),
        context({ roundPending: true, sinceOrgasm: 90, lastAppliedAt: 99000 })).reason, 'rate_limited');
});

test('after an orgasm: the recovery and the own Force Orgasm rest follow the user settings', () => {
    const settings = { enabled: true, pacing: 'often', recovery_seconds: 120, round_rest_seconds: 300 };
    const round = (since) => authorize(request('play_style', 'milker', { trigger: 'round' }), context({ settings, roundPending: true, sinceOrgasm: since }));
    assert.equal(round(119).reason, 'no_round_open');
    assert.equal(round(120).ok, true);
    const own = (since, trigger = 'own') => authorize(request('orgasm', true, { trigger }), context({ settings, sinceOrgasm: since }));
    assert.equal(own(299).reason, 'orgasm_rest');
    assert.equal(own(300).ok, true);
    assert.equal(own(10, 'user').ok, true);
    assert.equal(own(null).ok, true);
    assert.equal(authorize(request('orgasm', true), context({ settings: { ...settings, round_rest_seconds: 0 }, sinceOrgasm: 0 })).ok, true);
});

test('the after-orgasm settings are sanitized into their ranges', () => {
    assert.deepEqual([sanitizeAiSettings({ recovery_seconds: 29 }).recovery_seconds, sanitizeAiSettings({ recovery_seconds: 300 }).recovery_seconds,
        sanitizeAiSettings({ round_rest_seconds: 601 }).round_rest_seconds, sanitizeAiSettings({ round_rest_seconds: 0 }).round_rest_seconds], [90, 300, 180, 0]);
});
