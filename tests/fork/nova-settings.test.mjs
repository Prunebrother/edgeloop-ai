// SPDX-License-Identifier: AGPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import {relevanceIdentities} from '../../src/js/ai/event-settings.js';
test('new UI remains compatible with the running observer before Nova activation',()=>{
 const old={preferences:{generic:{},evelyn:{},daisy:{},celeste:{}}};
 assert.deepEqual(relevanceIdentities(old),['generic','evelyn','daisy','celeste']);
 assert.deepEqual(relevanceIdentities({...old,preferences:{...old.preferences,nova:{}}}),['generic','evelyn','daisy','celeste','nova']);
 assert.deepEqual(relevanceIdentities(null),[]);
});
