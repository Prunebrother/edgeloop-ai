// Source guard for the one piece of the end-stop margin that lives in app.js
// and cannot be imported here: the wiring that keeps the typed setting, the
// input the wearer reads and the number the driver uses saying the same
// thing. app.js needs a DOM, so this reads it as text, the way the other
// app.js guards in this suite do.
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { sanitizeSetting } from '../settings-schema.js';
import { HANDY_DEFAULT_END_MARGIN } from './handy-protocol.js';

const APP = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
const STATE = readFileSync(new URL('../state.js', import.meta.url), 'utf8');
const INDEX = readFileSync(new URL('../../../index.html', import.meta.url), 'utf8');

function bodyOf(name) {
    const at = APP.indexOf(`function ${name}`);
    assert.ok(at >= 0, `${name} is gone - rename this guard with it`);
    return APP.slice(at, APP.indexOf('\n}', at));
}

describe('the end-stop margin is settled like every other setting', () => {
    it('has a stored default and a row to type it into', () => {
        assert.match(STATE, /handyEndMargin:/, 'the margin must be persisted with the rest');
        assert.match(INDEX, /id="handyEndMarginInput"[^>]*min="0"[^>]*max="10"/,
            'the input must carry the same 0-10 bounds the clamp does');
    });

    it('is clamped wherever it enters: load, Apply and Import', () => {
        // The clamp is one entry in the settings schema, which syncGuardSettings
        // runs over every field on load, on Apply and on import. Asserted by
        // behaviour rather than by the spelling of a line in app.js: a source
        // match passes just as happily over a line that no longer does anything.
        assert.equal(sanitizeSetting('handyEndMargin', 99), 10);
        assert.equal(sanitizeSetting('handyEndMargin', -3), 0);
        assert.equal(sanitizeSetting('handyEndMargin', 'wide'), HANDY_DEFAULT_END_MARGIN);
        assert.equal(sanitizeSetting('handyEndMargin', 7), 7);
        assert.match(bodyOf('syncGuardSettings'), /applySettingSchema\(advancedSettings\)/,
            'and syncGuardSettings has to be the place that runs it');
    });

    // The defect this guard exists for: syncHwEnvelopeInputs is the function
    // the import handler calls to repaint this panel. It repainted the two
    // envelope inputs and not the margin, so an imported file left the input
    // showing one number while the driver used another.
    it('is repainted into its input after a settings import', () => {
        const body = bodyOf('syncHwEnvelopeInputs');
        assert.match(body, /handyEndMarginInput/,
            'syncHwEnvelopeInputs must repaint the margin input, not only the envelope');
        assert.match(body, /clampEndMargin\(/, 'and clamp what it paints');
        assert.match(APP, /syncHwEnvelopeInputs\(\);[\s\S]{0,400}syncGuardSettings\(\);[\s\S]{0,800}persistSettings\(\)/,
            'the import path must still run the envelope sync');
    });

    // The margin yields rather than shrink a stroke below its minimum width,
    // so a narrow envelope sitting on an end gets no protection. The readout
    // must say so rather than leave the wearer to infer it.
    it('says so when the envelope is too narrow for the margin to act', () => {
        const body = bodyOf('updateHandySlideDisplay');
        assert.match(body, /sent\.min === 0 \|\| sent\.max === 100/,
            'the readout must detect a sent range still sitting on an end');
        assert.match(body, /too narrow/, 'and name it in words');
    });

    // The readout is computed from the ENVELOPE, so it describes a full-length
    // stroke and nothing else: warm-up and every narrowing mode send less than
    // it says. A flat "sent to the device" would be false for most of a
    // session, and this row is read precisely when a device surprised someone.
    it('says that its readout is a full-length stroke, not every stroke', () => {
        const body = bodyOf('updateHandySlideDisplay');
        assert.match(body, /full-length stroke/,
            'the readout must scope itself to a full-length stroke');
        assert.ok(!/`Sent to the device/.test(body),
            'it must not claim to be what every tick sends');
        assert.match(INDEX, /id="handySlideDisplay"[^>]*>[^<]*full-length stroke/,
            'the placeholder the modal paints before the first sync must say the same');
    });

    it('reaches the driver, and reaches nothing else', () => {
        assert.match(APP, /dispatchHandy\([^)]*advancedSettings\.handyEndMargin\)/,
            'the margin must be handed to The Handy driver');
        const dispatch = bodyOf('dispatchHardware');
        assert.ok(!/dispatchIntiface\([^)]*handyEndMargin/.test(dispatch),
            'Intiface takes the envelope, never the Handy margin');
        assert.ok(!/dispatchTCode\([^)]*handyEndMargin/.test(dispatch),
            'T-Code takes the envelope, never the Handy margin');
        assert.ok(!/handyEndMargin/.test(bodyOf('effectiveStrokeRange')),
            'the funscript export records what the engine asked for, not the margined range');
    });
});
