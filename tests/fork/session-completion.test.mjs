// SPDX-License-Identifier: AGPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {Capture} from '../../src/js/ai/snapshot.js';
import {ReadOnlyConnection} from '../../src/js/ai/connection.js';
const source=readFileSync(new URL('../../src/js/app.js',import.meta.url),'utf8');
function rig({accept=false,hr=110}={}){
 const state={sessionStatus:'RUNNING',activeMode:'calibrate',teaseMode:'headplay',gameMode:'calibrate',sessionSeconds:321,edges:7,pauses:2,peakHr:115,hrCurrent:110};
 const calls=[],stored=[];let click;
 const context={state,console,isRemotePage:false,isRemoteViewer:false,advancedSettings:{},funscriptSamples:[],sessionLogWanted:()=>false,
  cameEarlyBtn:{addEventListener:(_type,fn)=>click=fn},safeParse:()=>structuredClone(stored),
  saveHistoryTrimmed:(_key,rows)=>{stored.splice(0,stored.length,...structuredClone(rows));calls.push('persist');return {saved:true,dropped:0};},
  syncAiObservation:()=>{calls.push('observe');assert.equal(stored[0].completion_status,'user_reported');},
  finishHr:()=>hr,calibrationReading:()=>null,stimulationRoles:()=>({dual:false}),readHrLimits:()=>({maxHr:140}),
  confirm:()=>{calls.push('calibration');assert.equal(stored[0].duration,321);assert.equal(stored[0].completion_status,'user_reported');return accept;},
  savePrimaryClimax:()=>calls.push('calibrate'),beginSettle:options=>{state.settleEndsSession=options.endsSession;calls.push('settle');}};
 const handler=source.slice(source.indexOf("cameEarlyBtn?.addEventListener('click', () => {"),source.indexOf("\ndocument.getElementById('wipeLearningBtn')"));
 const save=source.slice(source.indexOf('function saveSessionToHistory(outcome)'),source.indexOf('// Build the requested channel script'));
 // Upstream 1.1.4.26+ moved the calibration save into a shared function used by Finished me and Edged.
 const commit=source.slice(source.indexOf('function commitCalibrationReading('),source.indexOf('\nfunction markCalibrationEdge('));
 const count=source.slice(source.indexOf('function countOrgasm()'),source.indexOf('\n// A repeat inside this window'));
 vm.runInNewContext('let completionHistoryId=null;\n'+save+'\n'+count+'\n'+commit+'\n'+handler,context);
 return {click,calls,state,stored,save:outcome=>context.saveSessionToHistory(outcome)};
}
test('Finished me persists exact counters and explicit completion before calibration; cancelling retains it',()=>{
 const r=rig();r.click();assert.deepEqual(r.calls,['persist','observe','calibration']);assert.equal(r.state.orgasmCount,undefined);
 assert.equal(r.stored[0].duration,321);assert.equal(r.stored[0].edges,7);assert.equal(r.stored[0].experience,'headplay');assert.equal(r.stored[0].goal,'calibrate');
 assert.equal(r.stored[0].completion_status,'user_reported');assert(!r.calls.includes('calibrate'));assert(!r.calls.includes('settle'));
});
test('duplicate click and later stop update one history record',()=>{
 const r=rig({accept:true});r.click();r.click();assert.equal(r.calls.filter(c=>c==='persist').length,1);assert.equal(r.calls.filter(c=>c==='settle').length,1);
 assert.equal(r.state.orgasmCount,1);assert.equal(r.state.lastOrgasmSeconds,321);  // Finished me is one counted orgasm
 r.state.sessionSeconds=325;r.save('Calibration');assert.equal(r.stored.length,1);assert.equal(r.stored[0].duration,325);assert.equal(r.stored[0].completion_status,'user_reported');
});
test('completion is recorded even when no HR reading is available for calibration',()=>{
 const r=rig({hr:null});r.click();assert.deepEqual(r.calls,['persist','observe']);assert.equal(r.stored[0].completion_status,'user_reported');
});
test('read-only projection includes user report and distinguishes emergency termination',()=>{
 const capture=new Capture(),state={sessionStatus:'RUNNING',sessionSeconds:321,edges:7,teaseMode:'headplay',activeMode:'calibrate',gameMode:'calibrate',sensorHr:null,effectiveMaxHr:140,edgeTriggerHr:133,intensityValue:0,strokerSpeed:0,prostateSpeed:0,strokeMin:0,strokeMax:100,hrSignalState:'ok'};
 const devices={hr_ready:false,toy_ready:true};capture.project(state,devices);
 const result=capture.project(state,devices,{completion_reported:true});assert.equal(result.snapshot.details.completion_reported,true);assert.equal(result.snapshot.hr,null);
 state.sessionStatus='IDLE';assert.equal(capture.project(state,devices,{terminal_outcome:'Emergency Stop'}).snapshot.details.terminal_outcome,'safety_stop');
});

test('completion checkpoint bypasses observation throttling once',()=>{
 const sent=[],connection=new ReadOnlyConnection({schedule:()=>1});
 connection.enabled=true;connection.epoch=crypto.randomUUID();connection.socket={readyState:1,bufferedAmount:0,send:raw=>sent.push(JSON.parse(raw))};connection.lastSent=Date.now();
 connection.latest={session_id:'same',details:{completion_reported:false}};
 const snapshot={session_id:'same',details:{completion_reported:true}};
 connection.observe({snapshot,events:[]});assert.equal(sent.length,1);assert.equal(sent[0].snapshot.details.completion_reported,true);
 connection.observe({snapshot,events:[]});assert.equal(sent.length,1);
});
