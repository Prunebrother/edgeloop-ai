import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
    DEFAULT_WATCHDOG_SETTINGS,
    MIN_VALID_BPM,
    MIN_STALE_SECONDS,
    MAX_STALE_SECONDS,
    isValidBpm,
    clampStaleSeconds,
    classifyHrSignal,
    createHrWatchdog
} from './hr-watchdog.js';

describe('isValidBpm / clampStaleSeconds', () => {
    it('rejects 0, low and impossible readings', () => {
        assert.equal(isValidBpm(0), false);
        assert.equal(isValidBpm(MIN_VALID_BPM - 1), false);
        assert.equal(isValidBpm(MIN_VALID_BPM), true);
        assert.equal(isValidBpm(251), false);
        assert.equal(isValidBpm(NaN), false);
        assert.equal(isValidBpm(undefined), false);
    });

    it('clamps the typed timeout to the supported range', () => {
        assert.equal(clampStaleSeconds('8'), 8);
        assert.equal(clampStaleSeconds(1), MIN_STALE_SECONDS);
        assert.equal(clampStaleSeconds(99), MAX_STALE_SECONDS);
        assert.equal(clampStaleSeconds('abc'), 8);
        assert.equal(clampStaleSeconds(undefined, 12), 12);
    });
});

describe('classifyHrSignal', () => {
    const base = { staleMs: 8000, holdMs: 5000 };

    it('is ok right after a valid reading', () => {
        const v = classifyHrSignal({ ...base, lastPacketAt: 1000, lastValidAt: 1000, now: 1500 });
        assert.equal(v.status, 'ok');
        assert.equal(v.noContact, false);
        assert.equal(v.sinceValidMs, 500);
    });

    it('holds between holdMs and staleMs, stale only after staleMs', () => {
        assert.equal(classifyHrSignal({ ...base, lastPacketAt: 0, lastValidAt: 0, now: 5000 }).status, 'ok');
        assert.equal(classifyHrSignal({ ...base, lastPacketAt: 0, lastValidAt: 0, now: 5001 }).status, 'holding');
        assert.equal(classifyHrSignal({ ...base, lastPacketAt: 0, lastValidAt: 0, now: 8000 }).status, 'holding');
        assert.equal(classifyHrSignal({ ...base, lastPacketAt: 0, lastValidAt: 0, now: 8001 }).status, 'stale');
    });

    it('flags noContact when packets arrive without a usable pulse', () => {
        const v = classifyHrSignal({ ...base, lastPacketAt: 3000, lastValidAt: 1000, now: 3200 });
        assert.equal(v.status, 'ok');
        assert.equal(v.noContact, true);
    });

    it('trusts the sensor contact bit', () => {
        const v = classifyHrSignal({ ...base, lastPacketAt: 1000, lastValidAt: 1000, now: 1200, sensorContact: false });
        assert.equal(v.noContact, true);
        const ok = classifyHrSignal({ ...base, lastPacketAt: 1000, lastValidAt: 1000, now: 1200, sensorContact: true });
        assert.equal(ok.noContact, false);
    });

    it('treats a sensor never heard from as stale (fail safe)', () => {
        assert.equal(classifyHrSignal({ ...base, lastPacketAt: null, lastValidAt: null, now: 100 }).status, 'stale');
    });

    it('never lets the hold band extend past the stale threshold', () => {
        const v = classifyHrSignal({ staleMs: 3000, holdMs: 5000, lastPacketAt: 0, lastValidAt: 0, now: 3001 });
        assert.equal(v.status, 'stale');
        const h = classifyHrSignal({ staleMs: 3000, holdMs: 5000, lastPacketAt: 0, lastValidAt: 0, now: 2999 });
        assert.equal(h.status, 'ok');
    });

    it('falls back to the defaults on garbage settings', () => {
        const v = classifyHrSignal({ staleMs: -1, holdMs: 'x', lastPacketAt: 0, lastValidAt: 0, now: 7000 });
        assert.equal(v.status, 'holding');
        assert.equal(DEFAULT_WATCHDOG_SETTINGS.staleMs, 8000);
    });
});

describe('createHrWatchdog', () => {
    it('starts ok after reset and reports each transition exactly once', () => {
        const wd = createHrWatchdog();
        wd.reset(0);
        assert.equal(wd.evaluate(1000).status, 'ok');
        const holding = wd.evaluate(6000);
        assert.equal(holding.status, 'holding');
        assert.equal(holding.changed, true);
        assert.equal(holding.tripped, false);
        const stale = wd.evaluate(9000);
        assert.equal(stale.status, 'stale');
        assert.equal(stale.tripped, true);
        // Every following tick stays stale but must NOT re-trigger the alarm.
        const again = wd.evaluate(10000);
        assert.equal(again.status, 'stale');
        assert.equal(again.tripped, false);
        assert.equal(again.changed, false);
        assert.equal(wd.tripped, true);
    });

    it('recovers once when a usable reading returns and asks to auto-resume', () => {
        const wd = createHrWatchdog({ autoResume: true });
        wd.reset(0);
        wd.evaluate(9000);
        assert.equal(wd.recordPacket(9500, 88), true);
        const back = wd.evaluate(9600);
        assert.equal(back.status, 'ok');
        assert.equal(back.recovered, true);
        assert.equal(back.shouldResume, true);
        const next = wd.evaluate(9700);
        assert.equal(next.recovered, false);
        assert.equal(next.shouldResume, false);
    });

    it('does not ask to auto-resume when the setting is off', () => {
        const wd = createHrWatchdog({ autoResume: false });
        wd.reset(0);
        wd.evaluate(9000);
        wd.recordPacket(9500, 88);
        const back = wd.evaluate(9600);
        assert.equal(back.recovered, true);
        assert.equal(back.shouldResume, false);
    });

    it('a single missed packet on a 1 Hz strap never trips it', () => {
        const wd = createHrWatchdog();
        wd.reset(0);
        let now = 0;
        for (let i = 1; i <= 30; i++) {
            now = i * 1000;
            if (i === 15) continue; // one dropped notification
            wd.recordPacket(now, 90);
            const v = wd.evaluate(now + 10);
            assert.equal(v.status, 'ok', `tick ${i}`);
            assert.equal(v.tripped, false);
        }
        // Even the tick right after the miss (2 s since the last valid) is ok.
        assert.equal(wd.evaluate(16000).status, 'ok');
    });

    it('a 5 s cadence broadcaster stays ok/holding and never goes stale', () => {
        const wd = createHrWatchdog();
        wd.reset(0);
        const seen = new Set();
        for (let now = 0; now <= 120000; now += 1000) {
            // A watch app pushes every 5 s with up to 400 ms of jitter.
            if (now % 5000 === 0) wd.recordPacket(now + 400, 95);
            const v = wd.evaluate(now + 500);
            seen.add(v.status);
            assert.notEqual(v.status, 'stale', `at ${now}`);
            assert.equal(v.tripped, false);
        }
        assert.ok(seen.has('ok'));
        assert.equal(seen.has('stale'), false);
    });

    it('trips at the configured timeout, not the default', () => {
        const wd = createHrWatchdog({ staleMs: 3000 });
        wd.reset(0);
        assert.equal(wd.evaluate(2900).status, 'ok');
        const v = wd.evaluate(3100);
        assert.equal(v.status, 'stale');
        assert.equal(v.tripped, true);
        assert.deepEqual(wd.configure({ staleMs: 20000 }).staleMs, 20000);
        // Same timestamps, longer timeout: the signal is not stale any more.
        assert.equal(wd.evaluate(3200).status, 'ok');
    });

    it('packets with 0 BPM refresh the packet clock but not the valid clock', () => {
        const wd = createHrWatchdog();
        wd.reset(0);
        wd.recordPacket(1000, 92);
        assert.equal(wd.recordPacket(2000, 0), false);
        assert.equal(wd.lastPacketAt, 2000);
        assert.equal(wd.lastValidAt, 1000);
        const v = wd.evaluate(2100);
        assert.equal(v.status, 'ok');
        assert.equal(v.noContact, true);
        // Long enough without a pulse the motors still stop, whatever the
        // packet clock says.
        const stale = wd.evaluate(9200);
        assert.equal(stale.status, 'stale');
        assert.equal(stale.noContact, true);
        assert.equal(stale.sinceValidMs, 8200);
    });

    it('a valid packet flagged as no contact by the sensor still counts as a reading', () => {
        const wd = createHrWatchdog();
        wd.reset(0);
        assert.equal(wd.recordPacket(1000, 80, false), true);
        const v = wd.evaluate(1100);
        assert.equal(v.status, 'ok');
        assert.equal(v.noContact, true);
        wd.recordPacket(2000, 80, true);
        assert.equal(wd.evaluate(2100).noContact, false);
    });

    it('reset clears a pending alarm', () => {
        const wd = createHrWatchdog();
        wd.reset(0);
        wd.evaluate(9000);
        assert.equal(wd.tripped, true);
        wd.reset(9000);
        assert.equal(wd.tripped, false);
        const v = wd.evaluate(9500);
        assert.equal(v.status, 'ok');
        assert.equal(v.recovered, false);
    });
    it('isFresh follows the stale threshold without touching the transition bookkeeping', () => {
        const wd = createHrWatchdog({ staleMs: 8000 });
        wd.reset(0);
        assert.equal(wd.isFresh(7999), true);
        assert.equal(wd.isFresh(8001), false);
        assert.equal(wd.tripped, false);
        wd.recordPacket(9000, 0);        // a packet without a pulse
        assert.equal(wd.isFresh(9000), false);
        wd.recordPacket(9500, 88);
        assert.equal(wd.isFresh(9600), true);
        assert.equal(wd.evaluate(9600).status, 'ok');
    });
    it('status() reports the hold window that isFresh() cannot distinguish', () => {
        // isFresh() answers "not stale", so it stays true all the way through
        // 'holding', where hrCurrent is frozen on the last valid reading.
        // Callers that must not act on a frozen pulse ask for the status.
        const wd = createHrWatchdog({ staleMs: 8000, holdMs: 5000 });
        wd.reset(0);
        assert.equal(wd.status(4999), 'ok');
        assert.equal(wd.status(6000), 'holding');
        assert.equal(wd.isFresh(6000), true, 'the hold window is not stale');
        assert.equal(wd.status(8001), 'stale');
        // Side-effect free, exactly like isFresh().
        assert.equal(wd.tripped, false);
        wd.recordPacket(9000, 91);
        assert.equal(wd.status(9000), 'ok');
    });
});
