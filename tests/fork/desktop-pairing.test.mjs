// SPDX-License-Identifier: AGPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import {pairDesktop} from '../../src/js/ai/desktop-pairing.js';
const pair={browser_id:'12345678-1234-1234-1234-123456789abc',token:'x'.repeat(43),url:'ws://127.0.0.1:8768/observe'};
test('desktop pairing sends same-origin POST and hands credentials directly to connection',async()=>{
 const connection={connect(url,token){this.url=url;this.token=token;}};
 const fetch=async(url,options)=>{assert.equal(url,'/ai/pair');assert.equal(options.method,'POST');assert.equal(options.cache,'no-store');assert.equal(options.headers['X-EdgeLoop-Pair'],'1');return {ok:true,json:async()=>pair};};
 assert.equal(await pairDesktop(connection,()=>true,fetch),true);
 assert.equal(connection.browserId,pair.browser_id);assert.equal(connection.token,pair.token);
});
test('late pairing cannot undo Disconnect or replace a live connection',async()=>{
 const connection={connect(){throw Error('must not connect');}};
 const fetch=async()=>({ok:true,json:async()=>pair});
 assert.equal(await pairDesktop(connection,()=>false,fetch),false);
 assert.equal(await pairDesktop({...connection,socket:{}},()=>true,fetch),false);
 assert.equal(await pairDesktop(connection,()=>true,async()=>({ok:false})),false);
});
