import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
    TCODE_BAUD_RATE,
    KNOWN_AXES,
    FALLBACK_AXIS_IDS,
    DEFAULT_DEVICE_NAME,
    isAxisId,
    axisKind,
    isCentredAxis,
    restPositionFor,
    looksLikeBootBanner,
    describeAxis,
    formatMagnitude,
    formatAxisCommand,
    formatLine,
    splitLines,
    parseAxisLine,
    parseIdentification,
    fallbackDeviceName,
    fallbackAxes,
    defaultAxisRoles,
    rotationAmplitude,
    scalarLevel,
    describeSerialSupport,
    describeSerialError
} from './tcode-protocol.js';

describe('axis ids', () => {
    it('accepts the spec axes and rejects everything else', () => {
        Object.keys(KNOWN_AXES).forEach((id) => assert.equal(isAxisId(id), true, id));
        assert.equal(isAxisId('L9'), true);
        assert.equal(isAxisId('l0'), false);
        assert.equal(isAxisId('L'), false);
        assert.equal(isAxisId('L00'), false);
        assert.equal(isAxisId('X0'), false);
        assert.equal(isAxisId(null), false);
    });
    it('classifies kinds and rest positions', () => {
        assert.equal(axisKind('L0'), 'linear');
        assert.equal(axisKind('R2'), 'rotate');
        assert.equal(axisKind('V1'), 'vibe');
        assert.equal(axisKind('A0'), 'aux');
        assert.equal(axisKind('Z0'), null);
        assert.equal(restPositionFor('L0'), 0);
        assert.equal(restPositionFor('R1'), 0.5);
        assert.equal(restPositionFor('V0'), 0);
        assert.equal(restPositionFor('A0'), 0);
        // Surge and sway are neutral at the mechanical centre, not in a corner.
        assert.equal(restPositionFor('L1'), 0.5);
        assert.equal(restPositionFor('L2'), 0.5);
        assert.equal(isCentredAxis('L0'), false);
        assert.equal(isCentredAxis('L1'), true);
        assert.equal(isCentredAxis('R2'), true);
        assert.equal(isCentredAxis('V0'), false);
    });
    it('describes axes with the device text or the spec name', () => {
        assert.equal(describeAxis('L0'), 'Stroke (up / down)');
        assert.equal(describeAxis('L0', ' Up/Down '), 'Up/Down');
        assert.equal(describeAxis('L9'), 'Unknown axis');
    });
    it('uses 115200 baud', () => {
        assert.equal(TCODE_BAUD_RATE, 115200);
    });
});

describe('command formatting', () => {
    it('renders a 4-digit magnitude clamped to 0..1', () => {
        assert.equal(formatMagnitude(0), '0000');
        assert.equal(formatMagnitude(0.5), '5000');
        assert.equal(formatMagnitude(1), '9999');
        assert.equal(formatMagnitude(1.7), '9999');
        assert.equal(formatMagnitude(-3), '0000');
        assert.equal(formatMagnitude(NaN), '0000');
        assert.equal(formatMagnitude('abc'), '0000');
        assert.equal(formatMagnitude(0.12345), '1235');
        assert.equal(formatMagnitude(0.2), '2000');
        assert.equal(formatMagnitude(0.99999), '9999');
    });
    it('appends the interval when given, the speed otherwise', () => {
        assert.equal(formatAxisCommand('L0', 0.5, { intervalMs: 500 }), 'L05000I500');
        assert.equal(formatAxisCommand('L0', 0.5, { intervalMs: 500.4 }), 'L05000I500');
        assert.equal(formatAxisCommand('R0', 0.5), 'R05000');
        assert.equal(formatAxisCommand('V0', 0.25, { speed: 800 }), 'V02500S800');
        assert.equal(formatAxisCommand('V0', 0, { intervalMs: 0 }), 'V00000');
        assert.equal(formatAxisCommand('V0', 0, { intervalMs: -5, speed: NaN }), 'V00000');
        assert.equal(formatAxisCommand('L0', 1, { intervalMs: 1e9 }), 'L09999I99999');
    });
    it('refuses a bad axis id', () => {
        assert.throws(() => formatAxisCommand('X0', 0.5), /Invalid T-Code axis/);
        assert.throws(() => formatAxisCommand('', 0.5), /Invalid T-Code axis/);
    });
    it('assembles a newline-terminated line', () => {
        assert.equal(formatLine(['L05000I500', 'R05000I500']), 'L05000I500 R05000I500\n');
        assert.equal(formatLine('L00000I400'), 'L00000I400\n');
        assert.equal(formatLine(['', null, ' V00000 ']), 'V00000\n');
        assert.equal(formatLine([]), '');
    });
});

describe('reply parsing', () => {
    it('splits lines and keeps the unterminated remainder', () => {
        const parts = splitLines('OSR2\r\nTCode v0.3\n\nL0 st');
        assert.deepEqual(parts.lines, ['OSR2', 'TCode v0.3']);
        assert.equal(parts.rest, 'L0 st');
        assert.deepEqual(splitLines(''), { lines: [], rest: '' });
        assert.deepEqual(splitLines(null), { lines: [], rest: '' });
    });
    it('parses axis lines in the common spellings', () => {
        assert.deepEqual(parseAxisLine('L0 stroke'), { id: 'L0', description: 'stroke' });
        assert.deepEqual(parseAxisLine('r1: Roll'), { id: 'R1', description: 'Roll' });
        assert.deepEqual(parseAxisLine('V0 - Vibe motor'), { id: 'V0', description: 'Vibe motor' });
        assert.deepEqual(parseAxisLine('A0'), { id: 'A0', description: 'Valve / suck' });
        assert.equal(parseAxisLine('OK'), null);
        assert.equal(parseAxisLine('L00000'), null);
        assert.equal(parseAxisLine(''), null);
    });
    it('builds the identification from D0 / D1 / D2 replies', () => {
        const ident = parseIdentification({
            name: ['D0', 'SR6 Tempest'],
            version: ['TCode v0.3'],
            axisLines: ['D2', 'L0 stroke', 'L1 surge', 'R0 twist', 'L0 duplicate', 'garbage', 'V0 vibe']
        });
        assert.equal(ident.name, 'SR6 Tempest');
        assert.equal(ident.version, 'TCode v0.3');
        assert.equal(ident.identified, true);
        assert.deepEqual(ident.axes.map((a) => a.id), ['L0', 'L1', 'R0', 'V0']);
        assert.equal(ident.axes[1].description, 'surge');
    });
    it('falls back to the OSR2 axis set for a silent device', () => {
        const ident = parseIdentification({ name: [], version: [], axisLines: [] });
        assert.equal(ident.name, DEFAULT_DEVICE_NAME);
        assert.equal(ident.version, '');
        assert.equal(ident.identified, false);
        assert.deepEqual(ident.axes.map((a) => a.id), FALLBACK_AXIS_IDS);
        assert.deepEqual(ident.axes, fallbackAxes());
        assert.deepEqual(parseIdentification(), ident);
        assert.deepEqual(parseIdentification({ name: 'OSSM', version: 'v0.3', axisLines: 'L0 stroke' }).axes, [{ id: 'L0', description: 'stroke' }]);
    });
    it('names a silent device after its USB ids so two rigs do not share one config', () => {
        assert.equal(fallbackDeviceName({ usbVendorId: 0x1a86, usbProductId: 0x7523 }), 'TCode device 1a86:7523');
        assert.equal(fallbackDeviceName({ usbVendorId: 0x10c4, usbProductId: 0xea60 }), 'TCode device 10c4:ea60');
        assert.equal(fallbackDeviceName({ usbVendorId: 0x1a86 }), 'TCode device 1a86');
        assert.equal(fallbackDeviceName({}), DEFAULT_DEVICE_NAME);
        assert.equal(fallbackDeviceName(null), DEFAULT_DEVICE_NAME);
        assert.equal(fallbackDeviceName(undefined), DEFAULT_DEVICE_NAME);
        assert.equal(fallbackDeviceName({ usbVendorId: 'abc', usbProductId: -1 }), DEFAULT_DEVICE_NAME);
        assert.equal(fallbackDeviceName({ usbVendorId: 0x1a86, usbProductId: 0x10000 }), 'TCode device 1a86');
        const silent = parseIdentification({ name: [], version: [], axisLines: [], portInfo: { usbVendorId: 0x1a86, usbProductId: 0x7523 } });
        assert.equal(silent.name, 'TCode device 1a86:7523');
        assert.equal(silent.identified, false);
        // A D0 reply always wins over the USB ids.
        const named = parseIdentification({ name: ['OSSM'], portInfo: { usbVendorId: 0x1a86, usbProductId: 0x7523 } });
        assert.equal(named.name, 'OSSM');
    });
    it('never takes an auto-reset boot banner for a name or version', () => {
        assert.equal(looksLikeBootBanner('ets Jul 29 2019 12:21:46'), true);
        assert.equal(looksLikeBootBanner('rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)'), true);
        assert.equal(looksLikeBootBanner('I (31) boot: ESP-IDF v4.4'), true);
        assert.equal(looksLikeBootBanner('OSR2 Test Rig'), false);
        const ident = parseIdentification({
            name: ['ets Jul 29 2019 12:21:46', 'configsip: 0, SPIWP:0xee', 'SR6'],
            version: ['mode:DIO, clock div:1', 'TCode v0.3'],
            axisLines: ['L0 stroke']
        });
        assert.equal(ident.name, 'SR6');
        assert.equal(ident.version, 'TCode v0.3');
        const onlyBanner = parseIdentification({ name: ['rst:0x1 (POWERON_RESET)'], version: [], axisLines: [] });
        assert.equal(onlyBanner.name, DEFAULT_DEVICE_NAME);
    });

    it('truncates absurd names', () => {
        const ident = parseIdentification({ name: ['x'.repeat(200)] });
        assert.equal(ident.name.length, 60);
    });
});

describe('roles and levels', () => {
    it('defaults L0 to primary, V0 to secondary and the rest OFF', () => {
        const roles = defaultAxisRoles([{ id: 'L0' }, { id: 'R0' }, { id: 'R1' }, { id: 'V0' }, { id: 'A0' }, { id: 'bad' }]);
        assert.deepEqual(roles, { L0: 'primary', R0: 'off', R1: 'off', V0: 'secondary', A0: 'off' });
        assert.deepEqual(defaultAxisRoles([{ id: 'L0' }, { id: 'R0' }]), { L0: 'primary', R0: 'off' });
        assert.deepEqual(defaultAxisRoles(null), {});
    });
    it('scales the rotation amplitude by speed and cap', () => {
        assert.equal(rotationAmplitude(100, 100), 0.5);
        assert.equal(rotationAmplitude(50, 100), 0.25);
        assert.equal(rotationAmplitude(100, 50), 0.25);
        assert.equal(rotationAmplitude(0, 100), 0);
        assert.equal(rotationAmplitude(250, 900), 0.5);
        assert.equal(rotationAmplitude('x', undefined), 0);
    });
    it('scales scalar axes by speed and cap', () => {
        assert.equal(scalarLevel(100), 1);
        assert.equal(scalarLevel(60, 50), 0.3);
        assert.equal(scalarLevel(-5, 100), 0);
        assert.equal(scalarLevel(NaN, NaN), 0);
    });
});

describe('browser text', () => {
    it('names the supporting browsers and calls out the unsupported ones', () => {
        assert.match(describeSerialSupport('Mozilla/5.0 (X11; Linux x86_64) Firefox/120.0'), /Firefox does not implement Web Serial/);
        assert.match(describeSerialSupport('Mozilla/5.0 (Linux; Android 14) Chrome/120'), /not available on Android/);
        assert.match(describeSerialSupport('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari'), /iPhone or iPad/);
        assert.match(describeSerialSupport('Mozilla/5.0 (Macintosh) Version/17 Safari/605'), /Safari does not implement Web Serial/);
        const generic = describeSerialSupport('');
        assert.match(generic, /Chrome and Edge on a desktop/);
        assert.match(generic, /not available on Android, iOS, Firefox or Safari/);
    });
    it('blames the insecure origin, not the browser, on desktop Chrome over plain http', () => {
        const chrome = 'Mozilla/5.0 (X11; Linux x86_64) Chrome/128';
        assert.match(describeSerialSupport(chrome, false), /secure origin/);
        assert.match(describeSerialSupport(chrome, false), /https:\/\/ or http:\/\/localhost/);
        assert.doesNotMatch(describeSerialSupport(chrome, false), /not available in this browser/);
        assert.match(describeSerialSupport(chrome, true), /not available in this browser/);
        // A browser that lacks Web Serial altogether is still told so.
        assert.match(describeSerialSupport('Mozilla/5.0 (X11; Linux x86_64) Firefox/120.0', false), /Firefox does not implement/);
    });
    it('maps serial errors to actionable text', () => {
        assert.equal(describeSerialError({ name: 'NotFoundError' }).kind, 'cancelled');
        assert.equal(describeSerialError({ name: 'SecurityError' }).kind, 'blocked');
        const busy = describeSerialError({ name: 'NetworkError', message: 'Failed to open serial port.' });
        assert.equal(busy.kind, 'busy');
        assert.match(busy.message, /Intiface Central/);
        assert.match(busy.message, /dialout/);
        assert.equal(describeSerialError({ name: 'InvalidStateError' }).kind, 'busy');
        assert.equal(describeSerialError(new Error('boom')).message, 'Serial error: boom');
        assert.equal(describeSerialError(null).message, 'Serial connection failed.');
    });
});
