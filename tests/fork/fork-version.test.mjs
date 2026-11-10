// AGPL-3.0-only. The footer names the fork version from the top CHANGELOG.md
// heading, so a running build can be told apart from the upstream engine label.
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (name) => readFileSync(new URL(`../../${name}`, import.meta.url), 'utf8');

export function forkVersionLabel(changelog) {
    const heading = changelog.split(/\r?\n/).find((line) => line.startsWith('## '));
    const match = heading?.match(/^## (v\d+\.\d+\.\d+(?:-[\w.]+)?)(.*)$/);
    assert.ok(match, `unexpected top CHANGELOG heading: ${heading}`);
    return /draft|unreleased/i.test(match[2]) ? `${match[1]}-dev` : match[1];
}

describe('fork version label', () => {
    it('the footer shows the top CHANGELOG version beside the engine version', () => {
        const html = read('index.html');
        const label = forkVersionLabel(read('CHANGELOG.md'));
        assert.match(html, new RegExp(`id="forkVersion"[^>]*>EdgeLoop AI ${label.replace(/\./g, '\\.')}<`));
        assert.match(html, /engine <span id="appVersion"/);
    });

    it('marks a draft release as -dev', () => {
        assert.equal(forkVersionLabel('# Changelog\n\n## v0.7.0 — draft, unreleased\n'), 'v0.7.0-dev');
        assert.equal(forkVersionLabel('## v0.6.0-rc3 — fixes (pre-release)\n'), 'v0.6.0-rc3');
    });
});
