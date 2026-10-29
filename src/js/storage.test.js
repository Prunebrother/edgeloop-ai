import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { safeGet, safeParse, safeSet, safeRemove, saveHistoryTrimmed } from './storage.js';

// Minimal localStorage stand-in with an optional byte quota.
function fakeStorage(quotaBytes = Infinity) {
    const map = new Map();
    return {
        getItem: (k) => (map.has(k) ? map.get(k) : null),
        setItem: (k, v) => {
            const str = String(v);
            if (str.length > quotaBytes) {
                const err = new Error('QuotaExceededError');
                err.name = 'QuotaExceededError';
                throw err;
            }
            map.set(k, str);
        },
        removeItem: (k) => { map.delete(k); },
        _map: map
    };
}

describe('safeParse', () => {
    it('returns the stored value when it is valid JSON of the right shape', () => {
        const s = fakeStorage();
        s.setItem('k', JSON.stringify({ a: 1 }));
        assert.deepEqual(safeParse('k', {}, s), { a: 1 });
    });

    it('returns the fallback on missing keys and corrupt JSON', () => {
        const s = fakeStorage();
        assert.deepEqual(safeParse('missing', [], s), []);
        s.setItem('bad', '{not json');
        assert.deepEqual(safeParse('bad', [], s), []);
        s.setItem('empty', '');
        assert.deepEqual(safeParse('empty', { x: 1 }, s), { x: 1 });
    });

    it('returns the fallback when the shape does not match', () => {
        const s = fakeStorage();
        s.setItem('arr', '[1,2]');
        assert.deepEqual(safeParse('arr', { obj: true }, s), { obj: true });
        s.setItem('obj', '{"a":1}');
        assert.deepEqual(safeParse('obj', [], s), []);
        s.setItem('num', '5');
        assert.deepEqual(safeParse('num', [], s), []);
        s.setItem('nul', 'null');
        assert.deepEqual(safeParse('nul', [], s), []);
    });

    it('survives a storage that throws on read', () => {
        const s = { getItem: () => { throw new Error('blocked'); } };
        assert.deepEqual(safeParse('k', [], s), []);
    });

    it('survives a missing storage backend', () => {
        assert.deepEqual(safeParse('k', { d: 1 }, null), { d: 1 });
        assert.equal(safeSet('k', 1, null), false);
        assert.equal(safeRemove('k', null), false);
    });
});

describe('safeGet', () => {
    it('returns the raw string or the fallback', () => {
        const s = fakeStorage();
        s.setItem('k', 'v');
        assert.equal(safeGet('k', 'x', s), 'v');
        assert.equal(safeGet('missing', 'x', s), 'x');
        assert.equal(safeGet('k', 'x', { getItem: () => { throw new Error('blocked'); } }), 'x');
        assert.equal(safeGet('k', 'x', null), 'x');
    });
});

describe('safeSet', () => {
    it('stores strings as-is and objects as JSON', () => {
        const s = fakeStorage();
        assert.equal(safeSet('a', 'plain', s), true);
        assert.equal(s.getItem('a'), 'plain');
        assert.equal(safeSet('b', { x: 1 }, s), true);
        assert.equal(s.getItem('b'), '{"x":1}');
    });

    it('returns false instead of throwing when the quota is hit', () => {
        const s = fakeStorage(10);
        assert.equal(safeSet('big', 'x'.repeat(50), s), false);
        assert.equal(s.getItem('big'), null);
    });
});

describe('saveHistoryTrimmed', () => {
    const entry = (id, size) => ({ id, samples: Array.from({ length: size }, (_, i) => i) });

    it('saves everything when it fits', () => {
        const s = fakeStorage();
        const history = [entry(3, 2), entry(2, 2), entry(1, 2)];
        const out = saveHistoryTrimmed('h', history, s);
        assert.deepEqual(out, { saved: true, dropped: 0, stripped: false });
        assert.equal(JSON.parse(s.getItem('h')).length, 3);
    });

    it('drops the OLDEST entries first until it fits', () => {
        const history = [entry(3, 2), entry(2, 2), entry(1, 2)];
        const twoEntriesLength = JSON.stringify(history.slice(0, 2)).length;
        const s = fakeStorage(twoEntriesLength);
        const out = saveHistoryTrimmed('h', history, s);
        assert.deepEqual(out, { saved: true, dropped: 1, stripped: false });
        const stored = JSON.parse(s.getItem('h'));
        assert.deepEqual(stored.map(e => e.id), [3, 2]);
    });

    it('strips the newest trace when even one entry does not fit', () => {
        const history = [entry(9, 500), entry(8, 500)];
        const s = fakeStorage(200);
        const out = saveHistoryTrimmed('h', history, s);
        assert.equal(out.saved, true);
        assert.equal(out.stripped, true);
        assert.equal(out.dropped, 1);
        const stored = JSON.parse(s.getItem('h'));
        assert.equal(stored.length, 1);
        assert.equal(stored[0].id, 9);
        assert.deepEqual(stored[0].samples, []);
    });

    it('reports failure when nothing can be written', () => {
        const s = fakeStorage(1);
        const out = saveHistoryTrimmed('h', [entry(1, 1)], s);
        assert.equal(out.saved, false);
    });

    it('does not mutate the caller list', () => {
        const history = [entry(2, 2), entry(1, 2)];
        const s = fakeStorage(JSON.stringify(history.slice(0, 1)).length);
        saveHistoryTrimmed('h', history, s);
        assert.equal(history.length, 2);
    });
});
