// SPDX-License-Identifier: AGPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import {authorize} from '../../src/js/ai-settings/gate.js';
const request={version:1,type:'settings_request',id:'mission_00001',session_id:'s',setting:'intensity',value:40,reason:'Protocol: Compliance stage, 90%.',trigger:'mission'};
const context={settings:{enabled:true},revoked:false,remotePage:false,sessionId:'s',status:'RUNNING',signal:'ok',toyReady:true,now:100000,lastAppliedAt:null,current:{intensity:20}};
test('scripted campaign request obeys the existing off, emergency, signal and session gates',()=>{
    assert.equal(authorize(request,context).ok,true);
    for(const update of [{settings:{enabled:false}},{revoked:true},{status:'PAUSED'},{signal:'lost'},{toyReady:false}])assert.equal(authorize(request,{...context,...update}).ok,false);
    for(const setting of ['pause','stop'])assert.equal(authorize({...request,setting,value:true},context).ok,false);
});
test('the existing intensity-band rule remains authoritative for campaign stages',()=>{
    const result=authorize(request,{...context,settings:{enabled:true,intensity_min:20,intensity_max:30}});
    assert.equal(result.ok,true);assert.equal(result.change.to,30);assert.equal(result.change.clamped,true);
});
