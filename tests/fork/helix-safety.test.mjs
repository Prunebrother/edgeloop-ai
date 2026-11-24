// SPDX-License-Identifier: AGPL-3.0-only
// Data-driven gate checks for the real shipped scripted stages, even when browser sockets are unavailable.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {authorize} from '../../src/js/ai-settings/gate.js';
const campaign=JSON.parse(readFileSync(new URL('../../config/campaigns/rise_of_helix/campaign.json',import.meta.url)));
const stages=campaign.missions.flatMap(m=>m.objectives.flatMap(o=>(o.stages||[]).filter(s=>s.set_to).map(s=>({mission:m.id,objective:o.id,stage:s}))));
assert.ok(stages.some(x=>x.stage.intensity)&&stages.some(x=>x.stage.raise_to),'Need both fixed and floor steps');
for(const {mission,objective,stage} of stages)test(`${mission} ${objective}:${stage.id}: actual gate clamps to 60–90 percent and honors revocation`,()=>{
    const request={version:1,type:'settings_request',id:'fixture_'+stage.id,session_id:'s',setting:'intensity',value:(stage.intensity??stage.raise_to)-50,trigger:'mission',reason:'Fixture step'};
    const context={settings:{enabled:true,intensity_min:10,intensity_max:40},status:'RUNNING',sessionId:'s',signal:'ok',toyReady:true,now:1e6,lastAppliedAt:null,lastAiAt:null,current:{intensity:0}};
    const result=authorize(request,context);
    assert.equal(result.ok,true);assert.ok(result.change.to+50>=60&&result.change.to+50<=90);
    assert.equal(result.change.to,Math.max(10,Math.min(40,request.value)));
    assert.equal(result.change.clamped,request.value>40||request.value<10);
    assert.equal(authorize(request,{...context,revoked:true}).ok,false);
    assert.equal(authorize(request,{...context,settings:{...context.settings,enabled:false}}).ok,false);
    for(const status of ['PAUSED','IDLE'])assert.equal(authorize(request,{...context,status}).ok,false);
    for(const setting of ['pause','stop','emergency'])assert.equal(authorize({...request,setting,value:true},context).ok,false);
});
