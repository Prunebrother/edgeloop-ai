import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createWriteCoalescer, DEFAULT_WRITE_WINDOW_MS } from './write-coalescer.js';

// A hand-driven clock: nothing runs until the test fires it.
function fakeTimers() {
    const queued = new Map();
    let next = 1;
    return {
        setTimer(fn, ms) {
            const id = next++;
            queued.set(id, { fn, ms });
            return id;
        },
        clearTimer(id) {
            queued.delete(id);
        },
        armed() {
            return queued.size;
        },
        fire() {
            const entries = [...queued.entries()];
            queued.clear();
            entries.forEach(([, { fn }]) => fn());
            return entries.length;
        },
        delays() {
            return [...queued.values()].map(({ ms }) => ms);
        }
    };
}

function counter(result = true) {
    const calls = { n: 0 };
    const write = () => { calls.n += 1; return result; };
    return { calls, write };
}

describe('createWriteCoalescer', () => {
    it('writes nothing until the window expires', () => {
        const timers = fakeTimers();
        const { calls, write } = counter();
        const c = createWriteCoalescer({ write, windowMs: 400, ...timers });
        c.schedule();
        assert.equal(calls.n, 0, 'a scheduled write must not happen on the spot');
        assert.equal(c.pending(), true);
        timers.fire();
        assert.equal(calls.n, 1);
        assert.equal(c.pending(), false);
    });

    it('collapses a burst of keystrokes into one write', () => {
        const timers = fakeTimers();
        const { calls, write } = counter();
        const c = createWriteCoalescer({ write, windowMs: 400, ...timers });
        for (let i = 0; i < 25; i++) c.schedule();
        assert.equal(timers.armed(), 1, 'only one timer may be armed for a burst');
        timers.fire();
        assert.equal(calls.n, 1, `25 keystrokes wrote ${calls.n} times`);
    });

    it('does not let later keys push the deadline back', () => {
        // A debounce that restarts on every key never writes while a key is
        // held down. The window is a ceiling: the first unwritten edit arms
        // it and nothing after that re-arms it.
        const timers = fakeTimers();
        const { calls, write } = counter();
        const c = createWriteCoalescer({ write, windowMs: 400, ...timers });
        assert.equal(c.schedule(), true, 'the first edit arms the window');
        assert.equal(c.schedule(), false, 'a later edit joins the running window');
        assert.equal(c.schedule(), false);
        assert.equal(timers.armed(), 1);
        timers.fire();
        assert.equal(calls.n, 1);
        // And the next edit after a write arms a fresh window.
        assert.equal(c.schedule(), true);
        timers.fire();
        assert.equal(calls.n, 2);
    });

    it('flush writes what is outstanding, right now', () => {
        const timers = fakeTimers();
        const { calls, write } = counter();
        const c = createWriteCoalescer({ write, windowMs: 400, ...timers });
        c.schedule();
        assert.equal(c.flush(), true, 'flush returns what the write returned');
        assert.equal(calls.n, 1);
        assert.equal(timers.armed(), 0, 'flush must disarm the pending timer');
        // The timer, had it somehow survived, must not write a second time.
        timers.fire();
        assert.equal(calls.n, 1);
    });

    it('flush on nothing pending writes nothing', () => {
        const timers = fakeTimers();
        const { calls, write } = counter();
        const c = createWriteCoalescer({ write, windowMs: 400, ...timers });
        assert.equal(c.flush(), false);
        assert.equal(calls.n, 0, 'an idle flush must not touch the store');
        c.schedule();
        c.flush();
        assert.equal(c.flush(), false, 'flushing twice must not write twice');
        assert.equal(calls.n, 1);
    });

    it('reports a failed write instead of swallowing it', () => {
        const timers = fakeTimers();
        const c = createWriteCoalescer({ write: () => false, windowMs: 400, ...timers });
        c.schedule();
        assert.equal(c.flush(), false, 'a store that refused the write must be reported');
    });

    it('a throwing write does not strand the coalescer', () => {
        const timers = fakeTimers();
        let boom = true;
        let writes = 0;
        const c = createWriteCoalescer({
            write: () => { writes += 1; if (boom) throw new Error('quota'); return true; },
            windowMs: 400,
            ...timers
        });
        c.schedule();
        assert.throws(() => c.flush(), /quota/);
        assert.equal(c.pending(), false, 'a failed write must not leave the queue armed forever');
        boom = false;
        c.schedule();
        assert.equal(c.flush(), true);
        assert.equal(writes, 2);
    });

    it('cancel drops the pending write without performing it', () => {
        const timers = fakeTimers();
        const { calls, write } = counter();
        const c = createWriteCoalescer({ write, windowMs: 400, ...timers });
        assert.equal(c.cancel(), false, 'nothing to cancel');
        c.schedule();
        assert.equal(c.cancel(), true);
        assert.equal(c.pending(), false);
        timers.fire();
        assert.equal(calls.n, 0);
    });

    it('a clearTimer that throws cannot lose the write', () => {
        const timers = fakeTimers();
        const { calls, write } = counter();
        const c = createWriteCoalescer({
            write,
            windowMs: 400,
            setTimer: timers.setTimer,
            clearTimer: () => { throw new Error('no such timer'); }
        });
        c.schedule();
        assert.equal(c.flush(), true);
        assert.equal(calls.n, 1);
    });

    it('uses a sane window and refuses a nonsense one', () => {
        const timers = fakeTimers();
        const { write } = counter();
        assert.equal(createWriteCoalescer({ write, ...timers }).windowMs, DEFAULT_WRITE_WINDOW_MS);
        for (const bad of [0, -1, NaN, 'soon', null, undefined, Infinity]) {
            const c = createWriteCoalescer({ write, windowMs: bad, ...timers });
            assert.equal(c.windowMs, DEFAULT_WRITE_WINDOW_MS, `windowMs ${bad}`);
        }
        const c = createWriteCoalescer({ write, windowMs: 250, ...timers });
        c.schedule();
        assert.deepEqual(timers.delays(), [250], 'the window must be handed to the timer');
    });

    it('refuses to exist without a write function', () => {
        assert.throws(() => createWriteCoalescer(), TypeError);
        assert.throws(() => createWriteCoalescer({ write: 'persist' }), TypeError);
    });

    it('the window is short enough that a reload cannot outrun a typed limit', () => {
        // The store exists so a reload gets the typed limits back. Pair this
        // with the flush on pagehide in app.js and nothing typed is lost;
        // even without it the exposure is under half a second.
        assert.ok(DEFAULT_WRITE_WINDOW_MS <= 500, `${DEFAULT_WRITE_WINDOW_MS} ms is too long to hold a typed limit`);
    });
});

describe('app.js uses the coalescer for the session limits', () => {
    const src = readFileSync(new URL('./app.js', import.meta.url), 'utf8');

    it('writes the settings blob through it rather than on every key', () => {
        assert.ok(/createWriteCoalescer\(/.test(src), 'app.js must build a coalescer');
        const at = src.indexOf('function persistSessionLimits');
        assert.ok(at >= 0, 'persistSessionLimits is gone - rename this guard with it');
        const body = src.slice(at, src.indexOf('\n}', at));
        assert.ok(/sessionLimitsWriter\.(schedule|flush)\(/.test(body),
            'persistSessionLimits must go through the coalescer');
        assert.ok(!/\breturn persistSettings\(\);/.test(body),
            'persistSessionLimits must not write the whole blob on every keystroke');
    });

    it('drains the queue on anything that can end the page', () => {
        assert.ok(/pagehide'[^\n]*sessionLimitsWriter\.flush\(\)/.test(src),
            'a pending typed limit must be written before the page goes away');
        assert.ok(/visibilitychange'[\s\S]{0,200}sessionLimitsWriter\.flush\(\)/.test(src),
            'a hidden tab may never come back: flush there too');
    });
});
