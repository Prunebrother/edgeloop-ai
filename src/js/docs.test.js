// Documentation guard. README.md said "about 290 tests at the time of
// writing" and CHANGELOG.md said "about 330" while the suite was really well
// past 460: a number written into a document nobody re-counts is wrong within
// a week, and a document that is wrong about something checkable is not
// trusted about anything else. Neither file quotes a count now - the run
// prints its own - and this test fails if one creeps back in.
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const DOCS = ['README.md', 'CHANGELOG.md'];

// "about 290 tests", "290 tests", "290 unit tests", "~330 tests", "330 passing
// tests". The word may be plural or not and the number may carry a separator.
const PINNED_COUNT = /(?:about|around|roughly|approx\.?|approximately|~)?\s*\d[\d,]*\s+(?:unit\s+|passing\s+|node\s+)?tests?\b/i;

// The CHANGELOG's own wording put the noun before the number - "runs the unit
// tests (about 330 at the time of writing)" - which the pattern above does not
// see. Any number hedged as a snapshot is the same staleness either way.
const DATED_COUNT = /\d[\d,]*\s+(?:or so\s+)?(?:at the time of writing|and counting|at last count)/i;

const PATTERNS = [PINNED_COUNT, DATED_COUNT];
const quotesACount = (line) => PATTERNS.some((re) => re.test(line));

describe('the documentation does not quote a test count', () => {
    for (const name of DOCS) {
        it(`${name} names no fixed number of tests`, () => {
            const text = readFileSync(new URL(`../../${name}`, import.meta.url), 'utf8');
            const lines = text.split('\n');
            const offenders = lines
                .map((line, i) => ({ line, n: i + 1 }))
                .filter(({ line }) => quotesACount(line));
            // The pattern is deliberately broad - it also matches innocent
            // prose like "ran 3 tests by hand" - so this message says what to
            // do about a hit. A line listed here is a line to REPHRASE; it
            // does not mean the documentation is broken or the suite failed.
            assert.deepEqual(
                offenders.map(({ line, n }) => `${name}:${n}: ${line.trim()}`),
                [],
                `rephrase the line(s) above so they name no number of tests - \`npm test\` prints the real count on its own last lines. This guard is deliberately broad and will also flag prose like "ran 3 tests by hand"; nothing is broken, the sentence just needs rewording.`
            );
        });
    }

    it('the guard would catch the sentences that were wrong', () => {
        // The two real ones, verbatim, so a loosened pattern cannot pass
        // silently. The CHANGELOG line is the reason DATED_COUNT exists: it
        // says "about 330 at the time of writing", with the noun before the
        // number, and PINNED_COUNT alone walked straight past it.
        assert.ok(quotesACount("Node's built-in test runner (about 290 tests at the time of writing)."));
        assert.ok(quotesACount('- `npm test` runs the unit tests (about 330 at the time of writing) and a GitHub'));
        assert.ok(quotesACount('runs 469 tests'));
        assert.ok(quotesACount('~1,200 passing tests'));
        assert.ok(quotesACount('the suite is 495 and counting'));
        // And prose that is not a count must still be allowed.
        assert.ok(!quotesACount('Run it before opening a pull request that touches index.html.'));
        assert.ok(!quotesACount('the test workflow runs on every PR'));
        assert.ok(!quotesACount('Node 22 or newer, no browser'));
    });
});
