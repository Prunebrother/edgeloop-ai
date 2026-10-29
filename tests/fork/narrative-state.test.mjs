// SPDX-License-Identifier: AGPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import {NarrativeStateGate} from '../../src/js/ai/character-menus.js';
const state=(model,epoch,sequence,revision=0)=>({model,narrative_epoch:epoch,state_sequence:sequence,narrative_revision:revision});
test('reset rejects a delayed abandoned-epoch state, preserving the active display',()=>{
 const gate=new NarrativeStateGate();assert.equal(gate.accept(state('evelyn','old',5,3)),true);
 gate.reset('evelyn','new');assert.equal(gate.accept(state('evelyn','old',6,3)),false);
 assert.equal(gate.accept(state('evelyn','new',7)),true);
 assert.equal(gate.accept(state('evelyn','old',20,8)),false);
});
test('same-epoch sequence and revision reject stale snapshots',()=>{
 const gate=new NarrativeStateGate();assert.equal(gate.accept(state('e','epoch',10,3)),true);
 assert.equal(gate.accept(state('e','epoch',9,3)),false);
 assert.equal(gate.accept(state('e','epoch',11,2)),false);
 assert.equal(gate.accept(state('e','epoch',11,4)),true);
});
test('model switching preserves separate epoch gates and reconnect permits a new process',()=>{
 const gate=new NarrativeStateGate();gate.accept(state('e','e1',10));gate.accept(state('d','d1',4));
 gate.reset('d','d2');assert.equal(gate.accept(state('e','e1',11)),true);
 assert.equal(gate.accept(state('d','d1',5)),false);gate.clear();
 assert.equal(gate.accept(state('e','e1',1)),true);
});
test('legacy snapshots are accepted only until a versioned epoch is known',()=>{
 const gate=new NarrativeStateGate();assert.equal(gate.accept({model:'legacy'}),true);
 assert.equal(gate.accept(state('legacy','active',2)),true);
 assert.equal(gate.accept({model:'legacy'}),false);
});
test('monotonic sequence still rejects a stale epoch after the retired-epoch bound',()=>{
 const gate=new NarrativeStateGate();gate.accept(state('e','oldest',1));
 for(let i=0;i<24;i++){gate.reset('e','epoch-'+i);gate.accept(state('e','epoch-'+i,i+2));}
 assert.equal(gate.accept(state('e','oldest',1)),false);
});
