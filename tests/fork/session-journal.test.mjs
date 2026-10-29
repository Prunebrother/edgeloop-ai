// SPDX-License-Identifier: AGPL-3.0-only
import test from 'node:test';import assert from 'node:assert/strict';
import {journalCells} from '../../src/js/ai/session-journal.js';
test('journal shows unknown duration separately from zero and labels simulated samples',()=>{
 const record={first_observed_at:'2026-10-29T15:00:00+00:00',completion_status:'unknown',heart_rate:{simulator:{minimum:80,maximum:100,samples:2}}};
 const cells=journalCells(record);assert.match(cells[0],/first observed/);assert.equal(cells[2],'Unknown');assert.match(cells[5],/simulator; n=2/);
 assert.equal(journalCells({...record,active_running_seconds:0})[2],'0 s');
});
test('journal preserves literal untrusted text for textContent rendering',()=>{
 assert.equal(journalCells({completion_status:'user_reported',companion:'<img src=x onerror=alert(1)>',heart_rate:{}})[1],'<img src=x onerror=alert(1)>');
});
