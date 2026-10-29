// Pure T-Code helpers for the direct serial driver (tcode.js): command
// formatting, identification parsing, default axis roles and the
// browser-support text. No DOM, no Web Serial, fully unit-tested.
//
// Protocol notes (T-Code v0.3 as published by tempestvr; written from memory
// of the spec, not copied from it, so check odd firmware against the
// document):
//   - Serial 115200 baud, 8N1. Commands are ASCII lines ending in "\n".
//   - An axis command is <axis><magnitude>[I<ms>|S<speed>], e.g. L05000I500:
//     move L0 to 50.00 % over 500 ms. The magnitude is 1-4 digits read as a
//     decimal fraction (5000 = 0.5000, 500 = 0.500, 5 = 0.5); we always send
//     four digits so there is no ambiguity.
//   - Several commands may share one line, separated by spaces.
//   - Axes: L0 stroke (up/down), L1 surge, L2 sway, R0 twist, R1 roll,
//     R2 pitch, V0 vibe, V1 lube / aux, A0 valve / suck, A1 aux.
//   - Identification: D0 -> device name, D1 -> T-Code version, D2 -> axis
//     list, one line per axis ("L0 stroke" style). Replies end in "\n".
//   - Rest: the stroke axis L0 at 0 (bottom), surge / sway (L1 / L2) and the
//     rotation axes centred at 0.5, vibe and aux axes at 0 (off). Driving
//     L1 / L2 to 0 would slam the sleeve into a corner of the mechanism.

export const TCODE_BAUD_RATE = 115200;
export const AXIS_ROLES = ['primary', 'secondary', 'off'];
export const DEFAULT_DEVICE_NAME = 'TCode device';

// Human descriptions for the axis ids the spec defines.
export const KNOWN_AXES = {
    L0: 'Stroke (up / down)',
    L1: 'Surge (forward / back)',
    L2: 'Sway (left / right)',
    R0: 'Twist',
    R1: 'Roll',
    R2: 'Pitch',
    V0: 'Vibe',
    V1: 'Lube / aux',
    A0: 'Valve / suck',
    A1: 'Aux'
};

// What a silent device (no D2 reply) is assumed to have: the OSR2 set.
export const FALLBACK_AXIS_IDS = ['L0', 'R0', 'R1', 'R2', 'V0'];

const AXIS_ID_RE = /^[LRVA][0-9]$/;

export function isAxisId(id) {
    return typeof id === 'string' && AXIS_ID_RE.test(id);
}

// 'linear' (L), 'rotate' (R), 'vibe' (V), 'aux' (A) or null.
export function axisKind(id) {
    if (!isAxisId(id)) return null;
    switch (id[0]) {
        case 'L': return 'linear';
        case 'R': return 'rotate';
        case 'V': return 'vibe';
        default: return 'aux';
    }
}

// Axes whose neutral is the mechanical centre: every rotation axis and the
// linear axes other than the stroke (surge L1, sway L2). They swing around
// 0.5 by the engine speed instead of being mapped onto the stroke envelope.
export function isCentredAxis(id) {
    const kind = axisKind(id);
    return kind === 'rotate' || (kind === 'linear' && id !== 'L0');
}

// The safe position for an axis when the engine is silent.
export function restPositionFor(id) {
    return isCentredAxis(id) ? 0.5 : 0;
}

export function describeAxis(id, description = '') {
    const own = String(description || '').trim();
    if (own) return own;
    return KNOWN_AXES[id] || 'Unknown axis';
}

export function clampPosition(value, fallback = 0) {
    const n = Number(value);
    if (!Number.isFinite(n)) return fallback;
    return Math.max(0, Math.min(1, n));
}

// A 0..1 position as the 4-digit magnitude the device reads as a fraction
// (0.5 -> "5000"; 1.0 saturates at "9999", the largest 4-digit value).
export function formatMagnitude(position) {
    const p = clampPosition(position, 0);
    return String(Math.min(9999, Math.round(p * 10000))).padStart(4, '0');
}

// One axis command. An interval (ms) makes the device take that long to
// reach the target; a speed (magnitude per 100 ms) is the alternative form.
// Garbage ids throw: a typo must never reach the device as a stray command.
export function formatAxisCommand(id, position, { intervalMs, speed } = {}) {
    if (!isAxisId(id)) throw new Error(`Invalid T-Code axis id: ${id}`);
    let cmd = `${id}${formatMagnitude(position)}`;
    const interval = Number(intervalMs);
    if (Number.isFinite(interval) && interval > 0) {
        cmd += `I${Math.min(99999, Math.round(interval))}`;
    } else {
        const spd = Number(speed);
        if (Number.isFinite(spd) && spd > 0) cmd += `S${Math.min(99999, Math.round(spd))}`;
    }
    return cmd;
}

// Several commands on one newline-terminated line. Empty input yields ''.
export function formatLine(commands) {
    const parts = (Array.isArray(commands) ? commands : [commands])
        .map((c) => String(c || '').trim())
        .filter((c) => c.length > 0);
    if (parts.length === 0) return '';
    return `${parts.join(' ')}\n`;
}

// Split a receive buffer into complete lines (CR stripped, blank lines
// dropped) and the unterminated remainder.
export function splitLines(buffer) {
    const text = String(buffer || '');
    const pieces = text.split('\n');
    const rest = pieces.pop();
    const lines = pieces.map((l) => l.replace(/\r/g, '').trim()).filter((l) => l.length > 0);
    return { lines, rest };
}

// One D2 reply line: "L0 stroke", "L0: Stroke", "L0 - Up/Down" ... -> { id,
// description }, or null when the line does not start with an axis id.
export function parseAxisLine(line) {
    const text = String(line || '').replace(/\r/g, '').trim();
    const match = /^([LRVA][0-9])\b\s*[:\-]?\s*(.*)$/i.exec(text);
    if (!match) return null;
    const id = match[1].toUpperCase();
    return { id, description: describeAxis(id, match[2]) };
}

// Boot output of an auto-resetting board (opening the port toggles DTR /
// RTS, which restarts Arduino-class boards and ESP32 dev kits). The ESP32
// ROM prints its banner at 115200 baud and it must never be taken for a
// device name or version.
const BOOT_BANNER_RE = /^(ets\s|rst:|boot:|configsip|clk_drv|mode:|load:|entry\s|ho \d|[IEWD] \(\d+\)|waiting for download|invalid header)/i;

export function looksLikeBootBanner(line) {
    return BOOT_BANNER_RE.test(String(line || '').trim());
}

function cleanReply(line, command) {
    const text = String(line || '').replace(/\r/g, '').trim();
    if (!text) return '';
    // Some firmware echoes the command before answering it.
    if (text.toUpperCase() === command) return '';
    if (looksLikeBootBanner(text)) return '';
    return text;
}

export function fallbackAxes() {
    return FALLBACK_AXIS_IDS.map((id) => ({ id, description: KNOWN_AXES[id] }));
}

function hex4(value) {
    const n = Number(value);
    if (!Number.isInteger(n) || n < 0 || n > 0xffff) return '';
    return n.toString(16).padStart(4, '0');
}

// The name a device that does not answer D0 is saved under. Settings are
// remembered per name, so two silent rigs must not share one config: the USB
// vendor:product ids from SerialPort.getInfo() tell them apart ("TCode device
// 1a86:7523"). Only a port with no ids at all gets the plain default.
export function fallbackDeviceName(portInfo) {
    const info = portInfo && typeof portInfo === 'object' ? portInfo : {};
    const ids = [hex4(info.usbVendorId), hex4(info.usbProductId)].filter(Boolean);
    if (ids.length === 0) return DEFAULT_DEVICE_NAME;
    return `${DEFAULT_DEVICE_NAME} ${ids.join(':')}`;
}

// Build { name, version, axes, identified } from the raw reply lines. A
// device that answered nothing gets the fallback name (see
// fallbackDeviceName), an empty version and the fallback axis set;
// `identified` says whether D2 produced any axis.
export function parseIdentification({ name = [], version = [], axisLines = [], portInfo = null } = {}) {
    const nameLines = (Array.isArray(name) ? name : [name]).map((l) => cleanReply(l, 'D0')).filter(Boolean);
    const versionLines = (Array.isArray(version) ? version : [version]).map((l) => cleanReply(l, 'D1')).filter(Boolean);
    const seen = new Set();
    const axes = [];
    (Array.isArray(axisLines) ? axisLines : [axisLines]).forEach((line) => {
        const parsed = parseAxisLine(cleanReply(line, 'D2'));
        if (!parsed || seen.has(parsed.id)) return;
        seen.add(parsed.id);
        axes.push(parsed);
    });
    const identified = axes.length > 0;
    return {
        name: nameLines[0] ? nameLines[0].slice(0, 60) : fallbackDeviceName(portInfo),
        version: versionLines[0] ? versionLines[0].slice(0, 30) : '',
        axes: identified ? axes : fallbackAxes(),
        identified
    };
}

// Default roles: L0 drives the primary channel, V0 (when present) the
// secondary one, everything else is OFF until the user assigns it.
export function defaultAxisRoles(axes) {
    const roles = {};
    (Array.isArray(axes) ? axes : []).forEach((axis) => {
        const id = axis && axis.id;
        if (!isAxisId(id)) return;
        if (id === 'L0') roles[id] = 'primary';
        else if (id === 'V0') roles[id] = 'secondary';
        else roles[id] = 'off';
    });
    return roles;
}

export function isAxisRole(role) {
    return AXIS_ROLES.includes(role);
}

// Rotation axes swing around the centre; the swing grows with the engine
// speed and the user's cap (100 % = full 0..1 travel).
export function rotationAmplitude(speedPercent, capPercent = 100) {
    const speed = Number(speedPercent);
    const cap = Number(capPercent);
    const s = Number.isFinite(speed) ? Math.max(0, Math.min(100, speed)) : 0;
    const c = Number.isFinite(cap) ? Math.max(0, Math.min(100, cap)) : 100;
    return Math.round(0.5 * (s / 100) * (c / 100) * 10000) / 10000;
}

// Vibe / aux axes are scalar: engine speed scaled by the cap, 0..1.
export function scalarLevel(speedPercent, capPercent = 100) {
    const speed = Number(speedPercent);
    const cap = Number(capPercent);
    const s = Number.isFinite(speed) ? Math.max(0, Math.min(100, speed)) : 0;
    const c = Number.isFinite(cap) ? Math.max(0, Math.min(100, cap)) : 100;
    return Math.round((s / 100) * (c / 100) * 1000) / 1000;
}

// Why Web Serial is missing, with the browsers that do have it. On a
// supporting desktop browser the usual reason is a plain http:// origin
// (navigator.serial only exists in secure contexts), so the caller passes
// `secureContext` and gets that told instead of a wrong browser hint.
export function describeSerialSupport(userAgent = '', secureContext = true) {
    const ua = String(userAgent || '');
    const isIOS = /iPhone|iPad|iPod/i.test(ua);
    const isAndroid = /Android/i.test(ua);
    const isFirefox = /Firefox/i.test(ua);
    const isSafari = /Safari/i.test(ua) && !/Chrome|Chromium|CriOS|Edg/i.test(ua);
    const supported = 'Web Serial is available in Chrome and Edge on a desktop (Windows, macOS, Linux, ChromeOS)';
    if (isIOS) return `Web Serial is not available on iPhone or iPad in any browser. ${supported}; on iOS use Intiface Central instead.`;
    if (isAndroid) return `Web Serial is not available on Android. ${supported}; on Android use Intiface Central instead.`;
    if (isFirefox) return `Firefox does not implement Web Serial. ${supported}.`;
    if (isSafari) return `Safari does not implement Web Serial. ${supported}.`;
    if (secureContext === false) return 'Web Serial needs a secure origin: open EdgeLoop over https:// or http://localhost, then press Connect again.';
    return `Web Serial is not available in this browser. ${supported}; it is not available on Android, iOS, Firefox or Safari.`;
}

// Map a requestPort / open failure to a short, honest status line.
export function describeSerialError(error) {
    const name = error && error.name ? String(error.name) : '';
    const message = error && error.message ? String(error.message) : '';
    if (name === 'NotFoundError') {
        return { kind: 'cancelled', message: 'No port selected. Plug the device in over USB, then pick its port in the browser dialog.' };
    }
    if (name === 'SecurityError') {
        return { kind: 'blocked', message: 'The browser blocked the port request. Open EdgeLoop over https:// or localhost and press Connect directly.' };
    }
    if (name === 'NetworkError' || name === 'InvalidStateError' || /open|busy|access denied|permission/i.test(message)) {
        return { kind: 'busy', message: 'Could not open the port. Close Intiface Central or any other app that holds the COM port first; on Linux your user must be in the dialout group.' };
    }
    return { kind: 'failed', message: message ? `Serial error: ${message}` : 'Serial connection failed.' };
}
