// SPDX-License-Identifier: AGPL-3.0-only
// AI Settings Control, engine side. Owns the user's AI settings, the
// per-session revocation, the audit log and Undo. Every companion request
// goes through gate.authorize(); an accepted change is applied by app.js with
// the same handler as the on-page control and then read back, so a change the
// engine refused is reported as rejected. Model output never reaches configure(),
// confirm() or undo(): those are called from user clicks only.
import { authorize, sanitizeAiSettings, ownChangeReady } from './gate.js';

export const AI_SETTINGS_STORAGE_KEY = 'edgeloop_ai_settings';
const AUDIT_LIMIT = 50;
const PENDING_TTL_MS = 60000;

export function createAiSettingsControl({ load = () => null, save = () => {}, now = () => Date.now(),
    context, apply, remotePage = false } = {}) {
    // Profiles: null is the built-in companions' shared setting (the original storage key);
    // a Character Builder persona has its own, which starts off until the user opts in.
    let profile = null, profileLabel = null;
    let settings = sanitizeAiSettings(load(profile));
    let revoked = false;
    let lastAppliedAt = null;
    let lastAiAt = null;
    let applied = 0;
    let last = null;
    let pending = null;
    let applying = null;
    const audit = [];
    const history = new Map();
    const listeners = new Set();

    const emit = (event) => { for (const fn of listeners) { try { fn(event); } catch { /* UI only */ } } };
    const record = (entry) => {
        audit.push({ at: now(), ...entry });
        while (audit.length > AUDIT_LIMIT) audit.shift();
    };
    const outcome = (id, status, extra = {}) => ({ version: 1, type: 'settings_outcome', id, status, ...extra });

    function contextFor(sessionId) {
        const live = context();
        return { ...live, settings, revoked, remotePage, sessionId: live.sessionId ?? sessionId, now: now(), lastAppliedAt, lastAiAt };
    }

    function commit(change, by) {
        const before = context().current?.[change.setting];
        // The projection taken inside apply() labels the resulting events as the AI's.
        // A user Undo is the user's own change, so it is not labelled.
        applying = by === 'ai' ? change.id : null;
        try { apply(change); } finally { applying = null; }
        const after = context();
        const reducing = change.setting === 'pause' || change.setting === 'stop';
        const took = reducing ? after.status !== change.from : after.current?.[change.setting] === change.to;
        if (!took) {
            record({ id: change.id, by, setting: change.setting, to: change.to, status: 'rejected', reason: 'engine_refused' });
            return outcome(change.id, 'rejected', { reason: 'engine_refused', setting: change.setting });
        }
        if (!reducing) lastAppliedAt = now();
        if (by === 'ai') lastAiAt = now();
        applied += 1;
        const to = reducing ? after.status : after.current[change.setting];
        last = { id: change.id, setting: change.setting, from: reducing ? change.from : before ?? change.from, to, applied };
        if (!reducing && by === 'ai') history.set(change.id, last);
        while (history.size > AUDIT_LIMIT) history.delete(history.keys().next().value);
        record({ id: change.id, by, setting: change.setting, from: last.from, to, status: 'applied', clamped: Boolean(change.clamped) });
        const result = outcome(change.id, 'applied', { setting: change.setting, from: last.from, to, clamped: Boolean(change.clamped),
            reason: change.reason, trigger: change.trigger ?? 'own', undoable: !reducing && by === 'ai' });
        emit({ kind: 'applied', outcome: result, by });
        return result;
    }

    return {
        settings: () => ({ ...settings }),
        configure(partial) {
            const wasEnabled = settings.enabled;
            settings = sanitizeAiSettings({ ...settings, ...partial });
            // Switching it on mid-session starts the pacing clock, so nothing changes the moment it is enabled.
            if (settings.enabled && !wasEnabled) lastAiAt = now();
            if (!settings.enabled) pending = null;
            try { save(settings, profile); } catch { /* storage is optional */ }
            emit({ kind: 'settings', settings: { ...settings } });
            return { ...settings };
        },
        // Called by the companion layer when the active character changes. Only an explicit
        // configure() by the user ever turns a profile on; a new profile loads as stored or off.
        selectProfile(next, label = null) {
            const key = typeof next === 'string' && /^custom\.[a-z0-9][a-z0-9-]{0,23}$/.test(next) ? next : null;
            profileLabel = key ? (typeof label === 'string' ? label.slice(0, 60) : key) : null;
            if (key === profile) { emit({ kind: 'settings', settings: { ...settings } }); return { ...settings }; }
            profile = key;
            let stored = null;
            try { stored = load(profile); } catch { stored = null; }
            settings = sanitizeAiSettings(stored);
            pending = null;
            // A profile that is already on restarts its pacing clock, as if it had just been enabled.
            if (settings.enabled) lastAiAt = now();
            emit({ kind: 'settings', settings: { ...settings } });
            return { ...settings };
        },
        profile: () => ({ key: profile, label: profileLabel }),
        // Called by the companion layer with a request from the observer.
        request(raw, { sessionId } = {}) {
            const id = typeof raw?.id === 'string' ? raw.id.slice(0, 64) : null;
            let verdict;
            try { verdict = authorize(raw, contextFor(sessionId)); } catch { verdict = { ok: false, reason: 'gate_error' }; }
            if (!verdict.ok) {
                record({ id, by: 'ai', setting: typeof raw?.setting === 'string' ? raw.setting.slice(0, 32) : null, status: 'rejected', reason: verdict.reason });
                return outcome(id, 'rejected', { reason: verdict.reason });
            }
            const reducing = verdict.change.setting === 'pause' || verdict.change.setting === 'stop';
            if (settings.mode === 'ask' && !reducing) {
                if (pending) {
                    record({ id, by: 'ai', setting: verdict.change.setting, status: 'rejected', reason: 'confirmation_pending' });
                    return outcome(id, 'rejected', { reason: 'confirmation_pending' });
                }
                pending = { change: verdict.change, sessionId, at: now() };
                emit({ kind: 'pending', change: { ...verdict.change } });
                return outcome(id, 'pending', { setting: verdict.change.setting, from: verdict.change.from, to: verdict.change.to, reason: verdict.change.reason });
            }
            try { return commit(verdict.change, 'ai'); } catch { return outcome(id, 'rejected', { reason: 'engine_error' }); }
        },
        // User clicks in ask mode. The request is re-checked, since the session may have moved on.
        confirm(id) {
            if (!pending || pending.change.id !== id) return null;
            const { change, sessionId, at } = pending;
            pending = null;
            if (now() - at > PENDING_TTL_MS) return outcome(id, 'rejected', { reason: 'confirmation_expired' });
            const verdict = authorize({ version: 1, type: 'settings_request', id, session_id: sessionId,
                setting: change.setting, value: change.to, trigger: change.trigger, reason: change.reason }, contextFor(sessionId));
            if (!verdict.ok) return outcome(id, 'rejected', { reason: verdict.reason });
            return commit(verdict.change, 'ai');
        },
        decline(id) {
            if (!pending || pending.change.id !== id) return null;
            pending = null;
            record({ id, by: 'user', status: 'rejected', reason: 'declined_by_user' });
            emit({ kind: 'declined', id });
            return outcome(id, 'rejected', { reason: 'declined_by_user' });
        },
        // User Undo of an AI change: the user's own action, applied through the same handler.
        undo(id) {
            const entry = history.get(id);
            if (!entry) return false;
            history.delete(id);
            const live = context();
            if (live.current?.[entry.setting] !== entry.to) return false;
            try {
                commit({ id: `undo_${id}`.slice(0, 64), setting: entry.setting, from: entry.to, to: entry.from, reason: '' }, 'user');
                return true;
            } catch { return false; }
        },
        // Emergency stop: no AI change for the rest of this session.
        revoke() {
            revoked = true;
            pending = null;
            record({ id: null, by: 'user', status: 'revoked', reason: 'emergency_stop' });
            emit({ kind: 'revoked' });
        },
        // A session started from IDLE by the user.
        newSession() {
            const wasRevoked = revoked;
            revoked = false;
            pending = null;
            lastAppliedAt = null;
            // Pacing counts from the user's own start, so the first unprompted change waits a full interval.
            lastAiAt = now();
            history.clear();
            if (wasRevoked) emit({ kind: 'restored' });
        },
        // Projection for the read-only snapshot, used by the observer to confirm a change.
        snapshot: () => ({ enabled: settings.enabled, revoked, applied, last_id: last?.id ?? null, last_setting: last?.setting ?? null,
            applying_id: applying, pacing: settings.pacing,
            recovery_seconds: settings.recovery_seconds, round_rest_seconds: settings.round_rest_seconds,
            own_ready: settings.enabled && !revoked && ownChangeReady(settings, now(), lastAiAt) }),
        audit: () => audit.map((entry) => ({ ...entry })),
        pending: () => (pending ? { ...pending.change } : null),
        subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
    };
}
