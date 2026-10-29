import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
    BANNER_SEVERITIES,
    BANNER_OWNER_ANY,
    bannerRank,
    mergeBannerMessage,
    planBannerUpdate,
    canClearBanner,
    hiddenBannerState
} from './alert-banner.js';

const MOTOR_ALERT = 'The Handy did not confirm a stop and may still be moving: check the device. (timeout)';
const MIC_ALERT = 'The microphone stopped (revoked, unplugged or taken by another app).';

describe('alert banner ranking', () => {
    it('ranks nothing below an advisory below a safety report', () => {
        assert.deepEqual(BANNER_SEVERITIES, ['none', 'advisory', 'safety']);
        assert.ok(bannerRank('safety') > bannerRank('advisory'));
        assert.ok(bannerRank('advisory') > bannerRank('none'));
        assert.equal(bannerRank('not-a-severity'), 0);
        assert.equal(bannerRank(undefined), 0);
    });

    it('a microphone advisory never destroys a report that a motor may be moving', () => {
        // The exact sequence from the field: the Handy stops answering, the
        // driver cannot confirm its stop, and a second later the OS hands the
        // microphone to another app. Whichever fired last used to win.
        const safety = planBannerUpdate(hiddenBannerState(), {
            message: MOTOR_ALERT, severity: 'safety', source: 'device'
        });
        assert.equal(safety.text, MOTOR_ALERT);
        assert.equal(safety.severity, 'safety');

        const after = planBannerUpdate(safety, { message: MIC_ALERT, severity: 'advisory', source: 'mic' });
        assert.ok(after.text.includes(MOTOR_ALERT), 'the safety report must survive');
        assert.ok(after.text.includes(MIC_ALERT), 'and the advisory must not be swallowed either');
        assert.equal(after.severity, 'safety', 'the banner keeps the higher rank');
        assert.equal(after.source, 'device', 'and its owner, so only that owner can clear it');
    });

    it('a safety report always replaces a standing advisory', () => {
        const advisory = planBannerUpdate(hiddenBannerState(), {
            message: MIC_ALERT, severity: 'advisory', source: 'mic'
        });
        const safety = planBannerUpdate(advisory, { message: MOTOR_ALERT, severity: 'safety', source: 'device' });
        assert.equal(safety.text, MOTOR_ALERT);
        assert.equal(safety.severity, 'safety');
        assert.equal(safety.source, 'device');
    });

    it('a later safety report replaces an earlier one of the same rank', () => {
        const first = planBannerUpdate(hiddenBannerState(), {
            message: 'Heart rate signal lost. Motors stopped.', severity: 'safety', source: 'hrSignal'
        });
        const second = planBannerUpdate(first, { message: MOTOR_ALERT, severity: 'safety', source: 'device' });
        assert.equal(second.text, MOTOR_ALERT);
        assert.equal(second.source, 'device');
    });

    it('an unknown or missing severity is treated as an advisory, never as safety', () => {
        const safety = planBannerUpdate(hiddenBannerState(), {
            message: MOTOR_ALERT, severity: 'safety', source: 'device'
        });
        for (const bogus of [undefined, null, 'critical', 'none', 42]) {
            const out = planBannerUpdate(safety, { message: 'anything', severity: bogus, source: 'x' });
            assert.equal(out.severity, 'safety', `"${String(bogus)}" must not outrank a safety report`);
            assert.ok(out.text.includes(MOTOR_ALERT));
        }
    });

    it('never repeats the same sentence twice', () => {
        // onmute can be followed by onended with the same wording.
        const safety = planBannerUpdate(hiddenBannerState(), {
            message: MOTOR_ALERT, severity: 'safety', source: 'device'
        });
        const once = planBannerUpdate(safety, { message: MIC_ALERT, severity: 'advisory', source: 'mic' });
        const twice = planBannerUpdate(once, { message: MIC_ALERT, severity: 'advisory', source: 'mic' });
        assert.equal(twice.text, once.text);
    });

    it('merges nothing when one side is empty', () => {
        assert.equal(mergeBannerMessage('', MIC_ALERT), MIC_ALERT);
        assert.equal(mergeBannerMessage(MOTOR_ALERT, ''), MOTOR_ALERT);
        assert.equal(mergeBannerMessage(null, undefined), '');
    });
});

describe('alert banner clearing', () => {
    const safety = planBannerUpdate(hiddenBannerState(), {
        message: MOTOR_ALERT, severity: 'safety', source: 'device'
    });

    it('is owned: a returning heart rate cannot clear a device report', () => {
        assert.equal(canClearBanner(safety, 'hrSignal'), false);
        assert.equal(canClearBanner(safety, 'remote'), false);
        assert.equal(canClearBanner(safety, 'mic'), false);
        assert.equal(canClearBanner(safety, 'device'), true);
    });

    it('a signal-loss banner is cleared by the pulse coming back, and only by it', () => {
        const hr = planBannerUpdate(hiddenBannerState(), {
            message: 'Heart rate signal lost. Motors stopped.', severity: 'safety', source: 'hrSignal'
        });
        assert.equal(canClearBanner(hr, 'hrSignal'), true);
        assert.equal(canClearBanner(hr, 'device'), false);
    });

    it('a microphone advisory appended to a safety report is not cleared by the microphone', () => {
        const merged = planBannerUpdate(safety, { message: MIC_ALERT, severity: 'advisory', source: 'mic' });
        assert.equal(canClearBanner(merged, 'mic'), false, 'the safety report still owns the banner');
        assert.equal(canClearBanner(merged, 'device'), true);
    });

    it('the wearer can always dismiss it by hand', () => {
        assert.equal(canClearBanner(safety, BANNER_OWNER_ANY), true);
        assert.equal(canClearBanner(hiddenBannerState(), 'anything'), true);
    });

    it('hiddenBannerState is really hidden', () => {
        assert.deepEqual(hiddenBannerState(), { visible: false, severity: 'none', source: 'none', text: '' });
    });
});

describe('app.js routes every banner write through the ranking', () => {
    const src = readFileSync(new URL('./app.js', import.meta.url), 'utf8');

    it('nothing writes #disconnectMsg or unhides the banner behind showAlertBanner()', () => {
        // One banner carries heart-rate loss, a dropped monitor, an offline
        // Handy, a dead remote link, "the Handy may still be moving" and the
        // microphone advisory. A direct write is how one of them silently
        // replaced another.
        const writes = src.match(/getElementById\('disconnectMsg'\)/g) || [];
        assert.equal(writes.length, 1, 'only showAlertBanner() may write the banner text');
        const unhides = src.match(/disconnectBanner'\)[\s\S]{0,40}?classList\.remove\('hidden'\)/g) || [];
        assert.ok(unhides.length <= 1, 'only showAlertBanner() may reveal the banner');
        const hides = src.match(/disconnectBanner'\)\??\.classList\.add\('hidden'\)/g) || [];
        assert.equal(hides.length, 1, 'only hideAlertBanner() may hide the banner');
    });

    it('the microphone reports at advisory level and the safety paths at safety level', () => {
        const mic = src.indexOf('function handleMicLost');
        assert.ok(mic >= 0, 'handleMicLost not found');
        const micBody = src.slice(mic, src.indexOf('\nfunction startMicMeterLoop'));
        assert.ok(/severity: 'advisory'/.test(micBody), 'a lost microphone is an advisory, not a safety report');

        const alert = src.indexOf('function triggerDisconnectAlert');
        assert.ok(alert >= 0, 'triggerDisconnectAlert not found');
        const alertBody = src.slice(alert, alert + 400);
        assert.ok(/severity: 'safety'/.test(alertBody), 'every disconnect alert is a safety report');
    });
});
