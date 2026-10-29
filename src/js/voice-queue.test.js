import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { createCueQueue, DEFAULT_MAX_QUEUED } from './voice-queue.js';

describe('createCueQueue', () => {
    it('starts idle and promotes cues in order', () => {
        const q = createCueQueue();
        assert.equal(q.isIdle(), true);
        assert.equal(q.enqueue('Edge. Back off.'), true);
        assert.equal(q.enqueue('Hold. Fifteen seconds.'), true);
        assert.equal(q.next(), 'Edge. Back off.');
        assert.equal(q.isIdle(), false);
        assert.equal(q.next(), 'Hold. Fifteen seconds.');
        assert.equal(q.next(), null);
        assert.equal(q.isIdle(), true);
    });

    it('drops a cue identical to the one speaking or the last one queued', () => {
        const q = createCueQueue();
        q.enqueue('Edge. Back off.');
        q.next();
        assert.equal(q.enqueue('Edge. Back off.'), false);
        assert.equal(q.enqueue('Recovered. Resume.'), true);
        assert.equal(q.enqueue('Recovered. Resume.'), false);
        assert.deepEqual(q.queued, ['Recovered. Resume.']);
    });

    it('caps the queue and drops the oldest waiting cue', () => {
        const q = createCueQueue({ maxQueued: 3 });
        q.enqueue('one');
        q.next();
        q.enqueue('two');
        q.enqueue('three');
        q.enqueue('four');
        q.enqueue('five');
        assert.deepEqual(q.queued, ['three', 'four', 'five']);
        assert.equal(q.current, 'one');
    });

    it('jump discards the queue and speaks immediately', () => {
        const q = createCueQueue();
        q.enqueue('one');
        q.next();
        q.enqueue('two');
        q.enqueue('three');
        assert.equal(q.jump('Heart rate signal lost. Motors stopped.'), 'Heart rate signal lost. Motors stopped.');
        assert.equal(q.current, 'Heart rate signal lost. Motors stopped.');
        assert.deepEqual(q.queued, []);
        assert.equal(q.next(), null);
    });

    it('clear silences everything', () => {
        const q = createCueQueue();
        q.enqueue('one');
        q.next();
        q.enqueue('two');
        q.clear();
        assert.equal(q.isIdle(), true);
        assert.deepEqual(q.queued, []);
        assert.equal(q.next(), null);
    });

    it('ignores empty or non-string cues and falls back to the default cap', () => {
        const q = createCueQueue({ maxQueued: 0 });
        assert.equal(q.enqueue(''), false);
        assert.equal(q.enqueue(null), false);
        assert.equal(q.jump(''), null);
        for (let i = 0; i < 10; i++) q.enqueue(`cue ${i}`);
        assert.equal(q.queued.length, DEFAULT_MAX_QUEUED);
    });
});
