// SPDX-License-Identifier: AGPL-3.0-only
import test from 'node:test';import assert from 'node:assert/strict';
import {factualCoverage,unsupportedAdditions,memorySnapshot} from './memory-recall-evaluation.mjs';
test('semantic factual coverage is separate from strict phrase matching',()=>{
 for(const [expected,reply] of [['tending an overgrown succulent','I enjoy caring for a succulent.'],['pressing wildflowers','Wildflowers preserved by pressing are my quiet pastime.'],['restoring fountain pens','I like repairing vintage fountain pens.']]){
  assert(!reply.includes(expected));assert(factualCoverage(expected,reply).covered);
 }
 assert(!factualCoverage('pressing wildflowers','I enjoy pruning hydrangeas.').covered);
 assert(factualCoverage('pressing wildflowers','I pressed wildflowers.').covered);
 assert(factualCoverage('restoring fountain pens','I restored fountain pens.').covered);
 assert(factualCoverage('tending an overgrown succulent','She tends a succulent.').covered);
 assert(factualCoverage('ORCHID-17','It was Orchid-17.','identifier').covered);
});
test('unsupported additions flag a changed identifier and an extra personal pursuit',()=>{
 assert.equal(unsupportedAdditions('ORCHID-17','It was ORCHID-99.','ORCHID-17')[0].kind,'replacement_identifier');
 const result=unsupportedAdditions('pressing wildflowers','My hobby is pressing wildflowers. I also collect rare stamps.','My hobby is pressing wildflowers.');
 assert(result.some(r=>r.kind==='additional_personal_activity'));
});
const fact={id:'f1',status:'active',speaker:'assistant',slot:'detail:legacy',category:'character_detail',text:'I enjoy pressing wildflowers.'};
function audit(facts=[],matched=[],selected=[]){return {state:{model:'daisy',narrative:{facts,model_scope:'daisy',epoch:'e'},context_intelligence:{narrative_recall:{matched_fact_ids:matched,selected_fact_ids:selected}}},last_extraction:{candidates:[]}};}
test('stage snapshots distinguish establishment, extraction, eviction, matching and budget',()=>{
 const expected='pressing wildflowers';
 assert.equal(memorySnapshot('after_establishment',audit(),{expected,sourceReply:'I enjoy painting.'}).outcome,'never_established');
 assert.equal(memorySnapshot('after_establishment',audit(),{expected,sourceReply:fact.text}).outcome,'missed_during_extraction');
 const established=memorySnapshot('after_establishment',audit([fact]),{expected,sourceReply:fact.text});assert.equal(established.outcome,'stored');
 assert.equal(memorySnapshot('after_detours',audit(),{expected,previous:established}).outcome,'evicted');
 assert.equal(memorySnapshot('at_recall',audit([fact]),{expected,previous:established}).outcome,'unmatched');
 const budget=audit([fact],['f1']);budget.state.context_intelligence.memory_decisions=[{id:'f1',reason:'budget'}];
 assert.equal(memorySnapshot('at_recall',budget,{expected,previous:established}).outcome,'excluded_by_budget');
 assert.equal(memorySnapshot('at_recall',audit([fact],['f1'],['f1']),{expected,previous:established}).outcome,'selected');
});
test('coverage and bounded source snapshots apply to user facts outside personal activities',()=>{
 const expected='chamomile tea',reply='You prefer chamomile tea.';
 assert(factualCoverage(expected,reply,'fact').covered);
 assert(unsupportedAdditions(expected,'You prefer peppermint tea.','My preferred drink is chamomile tea.','fact').some(r=>r.kind==='unsupported_or_incomplete_fact_answer'));
 const userFact={...fact,id:'user1',speaker:'user',slot:'preference:participant:drink',text:'My preferred drink is chamomile tea.'};
 const snapshot=memorySnapshot('after_establishment',audit([userFact]),{expected,sourceReply:userFact.text,sourceSpeaker:'user'});
 assert.equal(snapshot.outcome,'stored');assert.deepEqual(snapshot.target_fact_ids,['user1']);
});
test('coverage does not credit explicit denial of the expected fact',()=>{
 assert(!factualCoverage('pressing wildflowers',"I don't enjoy pressing wildflowers.").covered);
 assert(!factualCoverage('chamomile tea','Not chamomile tea; peppermint.','fact').covered);
 assert(!factualCoverage('restoring fountain pens','I cannot recall my hobby.','fact').covered);
});
