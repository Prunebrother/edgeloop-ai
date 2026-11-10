// SPDX-License-Identifier: AGPL-3.0-only
// User interface for AI Settings Control: the settings panel and the change
// chips shown in the conversation. Engine side, so the AI layer receives these
// as functions and never imports engine modules. Model text is assigned with
// textContent only. Every button here is a user action.
import { sanitizeAiSettings, AI_RECOVERY_RANGE, AI_ROUND_REST_RANGE } from './gate.js';

export const SETTING_LABELS = Object.freeze({
    play_style: 'Play style', game: 'Game', endgame: 'Endgame', orgasm: 'Force Orgasm', intensity: 'Intensity', pause: 'Session', stop: 'Session'
});
const VALUE_LABELS = Object.freeze({
    classic: 'Classic', finisher: 'Finisher', milker: 'Milker', shortener: 'Glans Protector', headplay: 'Head Play', ultimate: 'Ultimate',
    bratty: 'Bratty', ruin: 'Ruin', off: 'No game', oracle: 'Oracle', survival: 'Survival', edgetrain: 'Edge Training', nnn: 'No Nut November',
    orgasm: 'Orgasm', rampdown: 'Soft landing', denial: 'Denial', RUNNING: 'Running', PAUSED: 'Paused', IDLE: 'Stopped', RAMPDOWN: 'Ramping down'
});

export function describeValue(setting, value) {
    if (value === null || value === undefined) return '—';
    if (setting === 'orgasm') return value ? 'On' : 'Off';
    if (setting === 'intensity') return `${Math.round(50 + Number(value))}%`;
    return VALUE_LABELS[value] || String(value);
}

export function describeChange(change) {
    const label = SETTING_LABELS[change.setting] || 'Setting';
    if (change.setting === 'pause') return 'Paused the session';
    if (change.setting === 'stop') return 'Stopped the session';
    return `${label}: ${describeValue(change.setting, change.from)} → ${describeValue(change.setting, change.to)}`;
}

// 90 -> '1 min 30 s', 0 -> 'Off'.
export function describeSeconds(seconds, zero = '0 s') {
    const n = Math.max(0, Math.round(Number(seconds) || 0));
    if (n === 0) return zero;
    const m = Math.floor(n / 60), s = n % 60;
    return m && s ? `${m} min ${s} s` : m ? `${m} min` : `${s} s`;
}

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

export function withAiSettingsPanel(control) {
    function mountPanel(container) {
        const box = element('details', 'ai-settings-panel');
        box.dataset.aiSettings = '';
        const summary = element('summary', '', 'AI Settings Control');
        const note = element('p', 'ai-settings-note',
            'Lets your companion change play style, game, endgame, Force Orgasm and intensity, and pause or stop. '
            + 'It can never start or resume a session, change heart-rate limits or devices. Emergency stop turns it off for the session.');
        const enabled = element('input'); enabled.type = 'checkbox'; enabled.dataset.aiSettingsEnabled = '';
        const enabledLabel = element('label', 'ai-settings-row'); enabledLabel.append(enabled, document.createTextNode(' Let the companion change session settings'));
        const mode = element('select'); mode.dataset.aiSettingsMode = '';
        for (const [value, text] of [['auto', 'Auto: apply right away'], ['ask', 'Ask me first']]) {
            const option = element('option', '', text); option.value = value; mode.append(option);
        }
        const modeLabel = element('label', 'ai-settings-row', 'Mode '); modeLabel.append(mode);
        const pacing = element('select'); pacing.dataset.aiSettingsPacing = '';
        for (const [value, text] of [['never', 'Never: only when I ask'], ['rarely', 'Rarely: at most every 10 min'],
            ['sometimes', 'Sometimes: at most every 5 min'], ['often', 'Often: at most every 2 min']]) {
            const option = element('option', '', text); option.value = value; pacing.append(option);
        }
        const pacingLabel = element('label', 'ai-settings-row', 'Changes on its own '); pacingLabel.append(pacing);
        const number = (key, min, max) => {
            const input = element('input'); input.type = 'number'; input.min = String(min); input.max = String(max); input.step = '1';
            input.dataset.aiSettingsField = key; return input;
        };
        const low = number('intensity_min', 0, 100), high = number('intensity_max', 0, 100), interval = number('min_interval_seconds', 15, 600);
        const band = element('label', 'ai-settings-row', 'Intensity band (slider 0–100) ');
        band.append(low, document.createTextNode(' to '), high);
        const pace = element('label', 'ai-settings-row', 'Minimum seconds between any changes ');
        pace.append(interval);
        // After an orgasm (I came): two sliders, each with its value read out next to its name.
        const after = element('fieldset', 'ai-settings-after');
        after.append(element('legend', '', 'After an orgasm'));
        const slider = (key, range, name, hint, zero) => {
            const row = element('label', 'ai-settings-slider');
            const head = element('span', 'ai-settings-slider-head');
            const value = element('output', 'ai-settings-slider-value');
            head.append(element('span', '', name), value);
            const input = element('input'); input.type = 'range';
            input.min = String(range.min); input.max = String(range.max); input.step = String(range.step);
            input.dataset.aiSettingsField = key;
            const show = () => { value.textContent = describeSeconds(input.value, zero); input.setAttribute('aria-valuetext', value.textContent); };
            input.addEventListener('input', show);
            row.append(head, input, element('span', 'ai-settings-hint', hint));
            after.append(row);
            return { input, show };
        };
        const recovery = slider('recovery_seconds', AI_RECOVERY_RANGE, 'Recovery',
            'Time to come down before your companion sets up the next round.');
        const rest = slider('round_rest_seconds', AI_ROUND_REST_RANGE, 'No Force Orgasm on its own for',
            'Your companion will not turn Force Orgasm on by itself this soon. You can still ask for it.', 'No block');
        const status = element('p', 'ai-settings-status'); status.setAttribute('role', 'status');
        const scope = element('p', 'ai-settings-note'); scope.dataset.aiSettingsProfile = '';
        box.append(summary, note, scope, enabledLabel, modeLabel, pacingLabel, band, pace, after, status);
        container.append(box);

        const paint = () => {
            const s = control.settings();
            const who = control.profile?.() || { key: null };
            scope.textContent = who.key ? 'Applies to ' + who.label + ' only. Custom characters start with this off.' : 'Applies to the built-in companions.';
            enabled.checked = s.enabled; mode.value = s.mode; pacing.value = s.pacing;
            low.value = String(s.intensity_min); high.value = String(s.intensity_max); interval.value = String(s.min_interval_seconds);
            recovery.input.value = String(s.recovery_seconds); rest.input.value = String(s.round_rest_seconds);
            recovery.show(); rest.show();
            const snap = control.snapshot();
            status.textContent = !s.enabled ? 'Off' : snap.revoked ? 'Paused after emergency stop until you start a new session'
                : s.mode === 'auto' ? 'On · auto' : 'On · asks first';
            box.dataset.state = !s.enabled ? 'off' : snap.revoked ? 'revoked' : 'on';
        };
        enabled.addEventListener('change', () => { control.configure({ enabled: enabled.checked }); });
        mode.addEventListener('change', () => { control.configure({ mode: mode.value }); });
        pacing.addEventListener('change', () => { control.configure({ pacing: pacing.value }); });
        for (const input of [low, high, interval, recovery.input, rest.input]) {
            input.addEventListener('change', () => {
                const next = sanitizeAiSettings({ ...control.settings(), [input.dataset.aiSettingsField]: Number(input.value) });
                control.configure(next);
                paint();
            });
        }
        const unsubscribe = control.subscribe(paint);
        paint();
        return () => { unsubscribe(); box.remove(); };
    }

    // A conversation chip for an applied, pending or declined change.
    function chip(result, { name = 'Companion', send = () => {} } = {}) {
        const node = element('div', 'ai-settings-chip');
        node.dataset.aiSettingsChip = result.status;
        node.setAttribute('role', 'status');
        const text = element('span', 'ai-settings-chip-text');
        const actions = element('span', 'ai-settings-chip-actions');
        node.append(text, actions);
        const show = (outcome) => {
            actions.replaceChildren();
            node.dataset.aiSettingsChip = outcome.status;
            if (outcome.status === 'applied') {
                text.textContent = `${name} · ${describeChange(outcome)}${outcome.clamped ? ' (kept inside your band)' : ''}`;
                if (outcome.undoable) {
                    const undo = element('button', 'ai-settings-undo', 'Undo'); undo.type = 'button';
                    undo.addEventListener('click', () => {
                        const ok = control.undo(outcome.id);
                        actions.replaceChildren(element('span', '', ok ? 'Undone' : 'Can no longer undo'));
                    });
                    actions.append(undo);
                }
            } else if (outcome.status === 'pending') {
                text.textContent = `${name} wants to change ${describeChange(outcome)}`;
                const allow = element('button', 'ai-settings-allow', 'Allow'); allow.type = 'button';
                const decline = element('button', 'ai-settings-decline', 'Decline'); decline.type = 'button';
                allow.addEventListener('click', () => { const r = control.confirm(outcome.id); if (r) { send(r); show(r.status === 'applied' ? r : { ...r, status: 'gone' }); } });
                decline.addEventListener('click', () => { const r = control.decline(outcome.id); if (r) { send(r); show({ ...r, status: 'gone' }); } });
                actions.append(allow, decline);
            } else {
                text.textContent = `${name}'s request was not applied`;
            }
        };
        show(result);
        return node;
    }

    return { ...control, mountPanel, chip };
}
