// SPDX-License-Identifier: AGPL-3.0-only
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createAiSettingsControl } from './control.js';

function harness({ settings = { enabled: true }, refuse = false } = {}) {
    let clock = 1000000;
    const engine = { status: 'RUNNING', signal: 'ok', toyReady: true,
        current: { play_style: 'classic', game: 'off', endgame: 'orgasm', orgasm: false, intensity: 50 } };
    const applied = [];
    let saved = null;
    const control = createAiSettingsControl({
        load: () => settings, save: (value) => { saved = value; }, now: () => clock,
        context: () => ({ status: engine.status, signal: engine.signal, toyReady: engine.toyReady, current: { ...engine.current } }),
        apply: (change) => {
            applied.push(change);
            if (refuse) return;
            if (change.setting === 'pause') engine.status = 'PAUSED';
            else if (change.setting === 'stop') engine.status = 'IDLE';
            else engine.current[change.setting] = change.to;
        }
    });
    const ask = (setting, value, id = 'req_' + String(applied.length + 10).padStart(8, '0'), trigger = 'user') =>
        control.request({ version: 1, type: 'settings_request', id, session_id: 's1', setting, value, trigger, reason: 'You looked too relaxed.' }, { sessionId: 's1' });
    return { control, engine, applied, ask, tick: (ms) => { clock += ms; }, saved: () => saved };
}

test('off by default: nothing is applied until the user enables it', () => {
    const h = harness({ settings: null });
    assert.equal(h.control.settings().enabled, false);
    assert.equal(h.ask('play_style', 'bratty').reason, 'disabled');
    assert.equal(h.applied.length, 0);
    h.control.configure({ enabled: true });
    assert.deepEqual(h.saved(), { ...h.control.settings() });
    assert.equal(h.ask('play_style', 'bratty').status, 'applied');
});

test('auto mode applies, reports from/to and the reason, and advances the snapshot counter', () => {
    const h = harness();
    const result = h.ask('endgame', 'denial');
    assert.deepEqual([result.status, result.from, result.to, result.reason, result.undoable], ['applied', 'orgasm', 'denial', 'You looked too relaxed.', true]);
    assert.deepEqual(h.control.snapshot(), { enabled: true, revoked: false, applied: 1, last_id: result.id, last_setting: 'endgame', applying_id: null,
        pacing: 'sometimes', recovery_seconds: 90, round_rest_seconds: 180, own_ready: false });
});

test('a change the engine silently refuses is reported as rejected, not applied', () => {
    const h = harness({ refuse: true });
    const result = h.ask('game', 'oracle');
    assert.deepEqual([result.status, result.reason], ['rejected', 'engine_refused']);
    assert.equal(h.control.snapshot().applied, 0);
});

test('rate limit counts from the last applied change', () => {
    const h = harness();
    assert.equal(h.ask('intensity', 60).status, 'applied');
    assert.equal(h.ask('play_style', 'milker').reason, 'rate_limited');
    h.tick(45000);
    assert.equal(h.ask('play_style', 'milker').status, 'applied');
});

test('emergency stop revokes until the user starts a new session', () => {
    const h = harness();
    h.control.revoke();
    assert.equal(h.ask('pause', true).reason, 'revoked_by_emergency_stop');
    assert.equal(h.control.snapshot().revoked, true);
    h.control.newSession();
    assert.equal(h.ask('pause', true).status, 'applied');
});

test('Undo restores the previous value once, only while the AI value is still current', () => {
    const h = harness();
    const result = h.ask('play_style', 'bratty');
    assert.equal(h.control.undo(result.id), true);
    assert.equal(h.engine.current.play_style, 'classic');
    assert.equal(h.control.undo(result.id), false);
    h.tick(45000);
    const second = h.ask('intensity', 70);
    h.engine.current.intensity = 40;
    assert.equal(h.control.undo(second.id), false);
    assert.equal(h.engine.current.intensity, 40);
    assert.equal(h.ask('pause', true).undoable, false);
});

test('ask mode waits for the user and re-checks the request on confirm', () => {
    const h = harness({ settings: { enabled: true, mode: 'ask' } });
    const pending = h.ask('orgasm', true, 'req_aaaaaaaa');
    assert.equal(pending.status, 'pending');
    assert.equal(h.applied.length, 0);
    assert.equal(h.ask('intensity', 60).reason, 'confirmation_pending');
    assert.equal(h.ask('pause', true).status, 'applied', 'pause never waits for confirmation');
    assert.equal(h.control.confirm('req_aaaaaaaa').reason, 'not_running', 'the session moved on, so the request is refused');
    h.engine.status = 'RUNNING';
    h.ask('endgame', 'denial', 'req_bbbbbbbb');
    assert.equal(h.control.decline('req_bbbbbbbb').reason, 'declined_by_user');
    h.ask('endgame', 'denial', 'req_cccccccc');
    assert.equal(h.control.confirm('req_cccccccc').status, 'applied');
});

test('the audit log is bounded and records rejections', () => {
    const h = harness();
    for (let i = 0; i < 70; i += 1) h.ask('SESSION_RESET', true);
    const audit = h.control.audit();
    assert.equal(audit.length, 50);
    assert.ok(audit.every((entry) => entry.status === 'rejected' && entry.reason === 'invalid_request'));
});

test('the projection taken during an AI change is labelled; a user Undo is not', () => {
    const seen = [];
    let control;
    const current = { play_style: 'classic', game: 'off', endgame: 'orgasm', orgasm: false, intensity: 50 };
    control = createAiSettingsControl({ load: () => ({ enabled: true }), now: () => 0,
        context: () => ({ status: 'RUNNING', signal: 'ok', toyReady: true, current: { ...current } }),
        apply: (change) => { current[change.setting] = change.to; seen.push(control.snapshot().applying_id); } });
    const result = control.request({ version: 1, type: 'settings_request', id: 'req_labelled', session_id: 's', setting: 'play_style', value: 'ruin' }, { sessionId: 's' });
    assert.equal(control.snapshot().applying_id, null);
    control.undo(result.id);
    assert.deepEqual(seen, ['req_labelled', null]);
});

test('own-initiative changes are paced; changes the user asks for are not', () => {
    const h = harness({ settings: null });
    h.control.configure({ enabled: true });
    assert.equal(h.ask('play_style', 'bratty', 'req_own00001', 'own').reason, 'paced', 'enabling starts the pacing clock');
    assert.equal(h.control.snapshot().own_ready, false);
    assert.equal(h.ask('intensity', 60, 'req_user0001', 'user').status, 'applied');
    h.tick(299000);
    assert.equal(h.ask('play_style', 'bratty', 'req_own00002', 'own').reason, 'paced', 'counts from the last AI change');
    h.tick(1000);
    assert.equal(h.control.snapshot().own_ready, true);
    assert.equal(h.ask('play_style', 'bratty', 'req_own00003', 'own').status, 'applied');
    assert.equal(h.ask('pause', true, 'req_own00004', 'own').status, 'applied', 'pause is never paced');
});

test('pacing options, and Never leaves only changes the user asks for', () => {
    for (const [pacing, seconds] of [['often', 120], ['sometimes', 300], ['rarely', 600]]) {
        const h = harness({ settings: { enabled: true, pacing } });
        h.control.newSession();
        h.tick(seconds * 1000 - 1);
        assert.equal(h.ask('endgame', 'denial', 'req_pace0001', 'own').reason, 'paced', pacing);
        h.tick(1);
        assert.equal(h.ask('endgame', 'denial', 'req_pace0002', 'own').status, 'applied', pacing);
    }
    const never = harness({ settings: { enabled: true, pacing: 'never' } });
    never.tick(10 ** 9);
    assert.equal(never.ask('endgame', 'denial', 'req_never001', 'own').reason, 'own_changes_off');
    assert.equal(never.control.snapshot().own_ready, false);
    assert.equal(never.ask('endgame', 'denial', 'req_never002', 'user').status, 'applied');
});

test('a custom persona has its own profile that starts off and is restored on switching', () => {
    const store = new Map([[null, { enabled: true }]]);
    let clock = 1000000;
    const engine = { status: 'RUNNING', signal: 'ok', toyReady: true, current: { play_style: 'classic', game: 'off', endgame: 'orgasm', orgasm: false, intensity: 50 } };
    const control = createAiSettingsControl({
        load: (profile) => store.get(profile ?? null) ?? null, save: (value, profile) => store.set(profile ?? null, value), now: () => clock,
        context: () => ({ status: engine.status, signal: engine.signal, toyReady: engine.toyReady, current: { ...engine.current } }),
        apply: (change) => { engine.current[change.setting] = change.to; } });
    const ask = () => control.request({ version: 1, type: 'settings_request', id: 'req_00000099', session_id: 's1', setting: 'intensity', value: 60, trigger: 'user', reason: 'Because.' }, { sessionId: 's1' });
    assert.equal(control.settings().enabled, true);
    // Wren on any model: her own profile, off although the built-ins are on.
    control.selectProfile('custom.wren-calloway', 'Wren Calloway');
    assert.equal(control.settings().enabled, false);
    assert.deepEqual(control.profile(), { key: 'custom.wren-calloway', label: 'Wren Calloway' });
    assert.equal(ask().status, 'rejected');
    // Explicit opt-in is stored for Wren only.
    control.configure({ enabled: true });
    assert.equal(store.get('custom.wren-calloway').enabled, true);
    control.selectProfile('custom.ilse', 'Ilse');
    assert.equal(control.settings().enabled, false);
    control.selectProfile(null);
    assert.equal(control.settings().enabled, true);
    assert.equal(control.profile().key, null);
    control.configure({ enabled: false });
    assert.equal(store.get(null).enabled, false);
    control.selectProfile('custom.wren-calloway', 'Wren Calloway');
    assert.equal(control.settings().enabled, true);
    // Anything that is not a custom identity falls back to the built-in profile.
    control.selectProfile('daisy');
    assert.equal(control.profile().key, null);
    assert.equal(control.settings().enabled, false);
});
