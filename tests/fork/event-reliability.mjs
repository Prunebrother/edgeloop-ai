// SPDX-License-Identifier: AGPL-3.0-only
// Real original controls and source transitions; only simulator + intercepted Handy.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve(new URL('../..',import.meta.url).pathname),live=process.env.EDGELOOP_LIVE_ACCEPTANCE==='1';
const uiPort=Number(process.env.FORK_BROWSER_PORT||8820),aiPort=Number(process.env.FORK_OBSERVER_PORT||8828),ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`;
const out=process.env.EVENT_BROWSER_REPORT||'/tmp/f251-events-'+(live?'live':'mock');
const report={passed:false,live,steps:[],frames:[],actions:[],errors:[],hardware:'Simulator and intercepted Handy only'};
const children=[];let browser,page,dialogAccept=true;const assert=(ok,msg)=>{if(!ok)throw Error(msg);};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const fixture=async()=>await(await fetch(ai+'/fixture/state')).json();
async function wait(url){for(let i=0;i<80;i++){try{if((await fetch(url)).ok)return;}catch{}await sleep(100);}throw Error('Fixture unavailable');}
async function source(){return page.evaluate(async()=>{const {state}=await import('/src/js/state.js');return {status:state.sessionStatus,experience:state.teaseMode,goal:state.gameMode||'tease',active_mode:state.activeMode,settle_outcome:state.settleOutcome,seconds:state.sessionSeconds};});}
async function waitStatus(status){const deadline=Date.now()+45000;while((await source()).status!==status){if(Date.now()>deadline)throw Error('Engine did not reach '+status);await sleep(100);}assert((await source()).status===status,'Unconfirmed engine status');}
async function select(model){await page.locator('[data-model]').selectOption(model);await page.locator('[data-select]').click();await page.waitForFunction(m=>document.querySelector('[data-selected]').textContent==='Active: '+m,model);}
async function finishAfter(index,label,allowSuppressed=false){
 const until=Date.now()+125000;
 while(Date.now()<until){
  const frames=report.frames.slice(index),err=frames.find(m=>m.type==='conversation_error');
  if(err)throw Error(label+': '+err.detail);
  const result=frames.find(m=>m.type==='speech'&&m.source==='event');
  const suppressed=frames.find(m=>m.type==='response_suppressed');
  if(result){await page.waitForFunction(()=>document.querySelector('[data-cancel]').hidden);return result;}
  if(suppressed){if(allowSuppressed){report.steps.push(label+': validated event generated a reply suppressed for '+suppressed.reason+' (model-quality result)');return {suppressed:true,reason:suppressed.reason};}throw Error(label+': suppressed '+suppressed.reason);}
  await sleep(50);
 }
 throw Error('No completed reaction for '+label);
}
async function action(label,fn,expectedKind){
 const index=report.frames.length;await fn();const engine=await source();const response=await finishAfter(index,label);
 const evidence=await fixture();assert(evidence.events.some(e=>e.kind===expectedKind),'No validated '+expectedKind);
 const request=evidence.requests.at(-1);assert(request.think===false&&request.last_turn.role==='user'&&request.last_turn.content.includes('APPLICATION EVENT'),'Invalid event request');
 assert(request.last_turn.content.includes(engine.experience)&&request.last_turn.content.includes(engine.goal),'Stale selections in request');
 await page.waitForFunction(()=>document.querySelector('#character-panel').dataset.artworkStatus!=='loading');
 const stage=await page.locator('#character-panel').evaluate(h=>({identity:h.dataset.character,applied:h.dataset.expression,rendered:h.dataset.renderedExpression,asset:h.querySelector('img:last-child')?.getAttribute('src'),fallback:h.dataset.artworkStatus}));
 if(response.expression){assert(stage.applied===response.expression,'Valid expression not applied');if(stage.fallback==='intended')assert(stage.rendered===response.expression,'Valid expression not rendered');}
 await page.waitForFunction(()=>document.querySelector('#character-panel').dataset.artworkStatus!=='loading');
 assert(!(await page.locator('[data-history]').textContent()).includes('[[expression:'),'Metadata leak');
 report.actions.push({label,engine,response,presentation:stage,last_request:request,validated:evidence.events.filter(e=>e.kind===expectedKind).at(-1),director:evidence.speech.director.most_recent_reason_for_speaking});
 await page.screenshot({path:path.join(out,label+'.png')});console.log('Accepted '+label,JSON.stringify({engine,response:response.text,expression:response.expression}));return response;
}
try{
 await mkdir(out,{recursive:true});
 children.push(spawn('python3',['tools/serve_local.py',String(uiPort)],{cwd:root,stdio:'ignore'}));
 children.push(spawn(path.join(root,'.venv/bin/python'),['tests/fork/event_reliability_service.py'],{cwd:root,stdio:'ignore',env:{...process.env,EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(aiPort)}}));
 await wait(ui+'/');await wait(ai+'/health');browser=await chromium.launch();const context=await browser.newContext({viewport:{width:1920,height:1080}});
 await context.addInitScript(()=>{const no=()=>Promise.reject(new DOMException('No physical hardware','NotAllowedError'));Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:no},configurable:true});Object.defineProperty(navigator,'serial',{value:{requestPort:no,getPorts:async()=>[]},configurable:true});if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=no;});
 await context.route('**/api/handy/v2/**',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(r.request().url().endsWith('/connected')?{connected:true}:r.request().url().endsWith('/info')?{fwVersion:'3.2.3',model:'Handy 1.1'}:{result:0})}));
 page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));page.on('dialog',d=>dialogAccept?d.accept():d.dismiss());
 page.on('websocket',ws=>{ws.on('framereceived',e=>{try{const m=JSON.parse(e.payload);if(!['models','ready'].includes(m.type))report.frames.push(m);}catch{}});});
 await page.goto(ui+'/?characterPreview=1');await page.locator('#ageConfirmBtn').click();await page.locator('#wizardSkipBtn').click();await page.locator('#companion-dashboard').waitFor();
 assert((await source()).status==='IDLE','Not idle');
 await page.locator('#openParamsBtn').click();await page.locator('#paramsTabGuardsBtn').click();await page.locator('#orgasmSettleSecondsInput').fill('10');await page.locator('#applyParamsBtn').click();
 await page.locator('[data-url]').fill(`ws://127.0.0.1:${aiPort}/observe`);await page.locator('[data-token]').fill('event-reliability-fixture-'+'x'.repeat(32));await page.locator('[data-connect]').click();
 await page.locator('[data-model] option[value="evelyn-lite-v1:latest"]').waitFor({state:'attached'});
 await page.getByText('Runtime diagnostics · development',{exact:true}).click();
 for(const [model,id,experience,goal]of [['evelyn-lite-v1:latest','evelyn','headplay','edgetrain'],['daisy-qwen35:latest','daisy','milker','oracle']]){
  assert((await source()).status==='IDLE','Model sequence must start idle');await select(model);await sleep(1100); // establish baseline projection before a source change
  await action(id+'-idle-mode',()=>page.locator(`[data-mode="${experience}"]`).click(),'experience_changed');
  await action(id+'-idle-goal',()=>page.locator(`[data-mode="${goal}"]`).click(),'goal_changed');
  const index=report.frames.length;
  for(const mode of ['classic','shortener',experience])await page.locator(`[data-mode="${mode}"]`).click();
  // Final selection equals original: should be silent, not narrate browsing.
  await sleep(4500);assert(!report.frames.slice(index).some(m=>m.type==='response_start'),'Returned selection generated chatter');
  const burstIndex=report.frames.length,dispatchBefore=(await fixture()).speech.director.counts.opportunities_dispatched||0;
  for(const mode of ['classic','shortener','ruin'])await page.locator(`[data-mode="${mode}"]`).click();
  await finishAfter(burstIndex,'burst',true);await sleep(1000);assert(report.frames.slice(burstIndex).filter(m=>m.type==='speech'&&m.source==='event').length<=1,'Selection burst not coalesced');
  assert(((await fixture()).speech.director.counts.opportunities_dispatched||0)===dispatchBefore+1,'Burst scheduled more than one opportunity');
  report.steps.push(id+': idle mode/goal reactions and final-selection debouncing');
  // Clear goal using original controls; Came Early must use its accidental-release branch.
  await action(id+'-clear-goal',()=>page.locator('[data-mode="goal-off"]').click(),'goal_changed');
  if(id==='evelyn'){
   const before=(await fixture()).requests.length;await page.locator('#cameEarlyBtn').click();await page.locator('[data-release-feedback]').waitFor({state:'visible'});
   assert((await page.locator('[data-release-feedback]').textContent()).includes('while idle'),'Idle learning update falsely implied session action');
   await sleep(1300);assert((await fixture()).requests.length===before,'Idle Came Early caused model reaction');
   await page.locator('#cardBle').click();await page.getByRole('button',{name:/manual simulator/i}).click();await page.locator('#modalSimHrSlider').fill('98');await page.locator('#modalEngageSimBtn').click();if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
   await page.locator('#cardHandy').click();await page.locator('#modalHandyInput').fill('F251-MOCK');await page.locator('#modalHandyConnectBtn').click();await sleep(700);if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
  }
  await page.locator('#sessionPlayPauseBtn').click();await waitStatus('RUNNING');
  await sleep(1200);
  if(id==='daisy'){await page.locator('#sessionPlayPauseBtn').click();await waitStatus('PAUSED');await sleep(1100);}
  dialogAccept=false;const previous=(await fixture()).events.filter(e=>e.kind==='came_early').length;await page.locator('#cameEarlyBtn').click();await sleep(1200);assert((await fixture()).events.filter(e=>e.kind==='came_early').length===previous,'Rejected action accepted');dialogAccept=true;
  await action(id+'-came-early',()=>page.locator('#cameEarlyBtn').click(),'came_early');
  await waitStatus('IDLE');
  report.steps.push(id+': rejected dialog creates no action; accepted '+(id==='daisy'?'paused':'running')+' Came Early reaches Director');
 }
 // Cancellation and switching after a generation; no stale request can select the old portrait.
 await select('evelyn-lite-v1:latest');await page.locator('[data-text]').fill(live?'Tell me a long story about a rainy library.':'long streaming');await page.locator('[data-send]').click();
 await page.locator('[data-cancel]').waitFor({state:'visible'});await page.locator('[data-cancel]').click();await select('daisy-qwen35:latest');await sleep(1000);
 assert(await page.locator('#character-panel').getAttribute('data-character')==='daisy','Stale identity after cancellation/switch');
 await page.locator('#sessionPlayPauseBtn').click();await waitStatus('RUNNING');
 await page.locator('[data-disconnect]').click();assert((await source()).status==='RUNNING','Observer disconnect changed engine state');
 await page.locator('#sessionStopBtn').click();await waitStatus('IDLE');
 report.steps.push('Cancellation, model switching and observer disconnection preserve engine independence');
 const data=await fixture();report.final_fixture=data;assert(data.read_only&&data.requests.every(r=>r.think===false),'Read-only/thinking policy broken');assert(!report.errors.length,report.errors.join(';'));report.passed=true;
}catch(e){report.error=String(e);report.failure_fixture=await fixture().catch(()=>null);if(page)await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});process.exitCode=1;}
finally{if(browser)await browser.close();for(const c of children)c.kill();await writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({passed:report.passed,error:report.error,steps:report.steps,out}));}
