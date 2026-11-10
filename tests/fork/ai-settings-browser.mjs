// SPDX-License-Identifier: AGPL-3.0-only
// AI Settings Control acceptance: owned isolated servers, nonpersistent browser, fake Handy, mocked inference.
// The mocked model proposes changes; the engine-side gate decides; the snapshot confirms; a card announces.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {claimPorts,ownedReady,isolatedEnv,guardBrowser} from './fixture-isolation.mjs';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve(new URL('../..',import.meta.url).pathname);
const uiPort=8801,observerPort=8802,uiUrl=`http://127.0.0.1:${uiPort}`,observerUrl=`http://127.0.0.1:${observerPort}`;
const output=process.env.FORK_BROWSER_REPORT||'/tmp/edgeloop-ai-settings-browser';
const children=[];let browser;const report={passed:false,steps:[],fixture:'owned servers, temporary data, fake Handy, mocked Ollama'};
const assert=(x,m)=>{if(!x)throw Error(m);};const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const fixture=async()=>await (await fetch(observerUrl+'/fixture/state')).json();
const propose=async proposal=>fetch(observerUrl+'/fixture/settings-proposal',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(proposal)});
async function until(check,message,tries=150){for(let i=0;i<tries;i++){if(await check())return;await sleep(100);}throw Error(message);}
try{
 await mkdir(output,{recursive:true});await claimPorts(uiPort,observerPort);
 children.push(spawn('python3',['tools/serve_local.py',String(uiPort)],{cwd:root,env:isolatedEnv(),stdio:'ignore'}));
 children.push(spawn(path.join(root,'.venv/bin/python'),['tests/fork/browser_service.py'],{cwd:root,env:isolatedEnv({PYTHONPATH:root,EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(observerPort)}),stdio:'ignore'}));
 await ownedReady(uiUrl+'/',children);await ownedReady(observerUrl+'/health',children);
 browser=guardBrowser(await chromium.launch(),[uiPort,observerPort]);
 const ctx=await browser.newContext({viewport:{width:1920,height:1080}});
 await ctx.addInitScript(()=>{
  Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:()=>Promise.reject(Error('No physical devices in fixture'))},configurable:true});
  Object.defineProperty(navigator,'serial',{value:{requestPort:()=>Promise.reject(Error('No physical devices in fixture')),getPorts:async()=>[]},configurable:true});
  if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=()=>Promise.reject(Error('No physical devices in fixture'));
 });
 const page=await ctx.newPage(),errors=[],outcomes=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('websocket',ws=>{
  ws.on('framesent',e=>{try{const x=JSON.parse(e.payload);if(x.type==='settings_outcome')outcomes.push(x);}catch{}});
  ws.on('framereceived',e=>{try{const x=JSON.parse(e.payload);if(x.type==='settings_request')requests.push(x);}catch{}});
 });
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());
  if(u.hostname.endsWith('handyfeeling.com'))return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(u.pathname.endsWith('/connected')?{connected:true}:u.pathname.endsWith('/info')?{fwVersion:'3.2.3',model:'Handy 1.1'}:{result:0})});
  if(!['127.0.0.1','localhost'].includes(u.hostname))return route.abort();return route.continue();
 });
 const engine=()=>page.evaluate(async()=>{const {state}=await import('/src/js/state.js');return {status:state.sessionStatus,style:state.teaseMode,game:state.gameMode,endgame:state.endgameType,orgasm:Boolean(state.orgasmMode),intensity:state.intensityValue};});
 await page.goto(uiUrl+'/',{waitUntil:'load'});await page.locator('#ageConfirmBtn').click();await page.locator('#wizardSkipBtn').click();
 await page.locator('#companion-dashboard').waitFor();
 await page.locator('[data-url]').fill(observerUrl.replace('http:','ws:')+'/observe');await page.locator('[data-token]').fill('browser-fixture-token-'+'x'.repeat(32));await page.locator('[data-connect]').click();
 await page.waitForFunction(()=>document.querySelector('[data-telemetry]').textContent.includes('Authoritative telemetry connected'));
 await page.locator('[data-model] option[value="evelyn-lite-v1:latest"]').waitFor({state:'attached'});await page.locator('[data-model]').selectOption('evelyn-lite-v1:latest');await page.locator('[data-select]').click();
 await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.includes('Active: evelyn-lite-v1:latest'));
 await page.locator('#cardBle').click();await page.getByRole('button',{name:/manual simulator/i}).click();await page.locator('#modalSimHrSlider').evaluate(el=>{el.value='90';el.dispatchEvent(new Event('input',{bubbles:true}));});await page.locator('#modalEngageSimBtn').click();
 if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').evaluate(el=>el.click());
 await page.locator('#cardHandy').click();await page.locator('#modalHandyInput').fill('FIXTURE-ONLY');await page.locator('#modalHandyConnectBtn').click();await page.waitForTimeout(900);
 if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
 await page.locator('#sessionPlayPauseBtn').click();
 await until(async()=>(await engine()).status==='RUNNING','Session did not start');

 const chat=async text=>{await page.locator('[data-text]').fill(text);await page.locator('[data-send]').click();};
 const replies=async()=>(await fixture()).settings_replies;
 const waitIdle=()=>page.waitForFunction(()=>!document.querySelector('[data-send]').disabled||document.querySelector('[data-text]').value==='',null,{timeout:30000});

 // 1. Off by default: neither chat nor the companion's own ideas lead to a decision.
 const panel=page.locator('[data-ai-settings]');await panel.locator('summary').click();
 assert(!(await page.locator('[data-ai-settings-enabled]').isChecked()),'AI Settings Control is on by default');
 assert(await page.locator('[data-ai-settings-mode]').inputValue()==='auto','Default mode is not auto');
 assert(await page.locator('[data-ai-settings-pacing]').inputValue()==='sometimes','Default pacing is not every 5 minutes');
 await propose({change:'play_style',value:'bratty',reason:'You look far too comfortable.'});
 await chat('Make it harder, surprise me.');await sleep(3000);
 assert((await fixture()).settings_decisions===0&&requests.length===0,'Decision ran while disabled');
 assert((await engine()).style==='classic','Setting changed while disabled');
 report.steps.push('Off by default (auto mode, 5-minute pacing preset); no decision from chat or own initiative while off');

 // 2. Enabled: pacing holds back the companion's own ideas; a chat request is decided before the reply.
 await page.locator('[data-ai-settings-field="min_interval_seconds"]').fill('15');await page.locator('[data-ai-settings-field="min_interval_seconds"]').dispatchEvent('change');
 await page.locator('[data-ai-settings-enabled]').check();await sleep(3000);
 assert((await fixture()).settings_decisions===0,'An unprompted decision ran inside the pacing interval');
 assert((await fixture()).state.details.ai_settings.own_ready===false,'Snapshot claims an unprompted change is allowed');
 await chat('Switch it up, surprise me.');
 await until(async()=>(await engine()).style==='bratty','Chat-requested change not applied');
 await until(async()=>(await replies()).length>=1,'Reply did not get the verified change');
 let f=await fixture();
 assert(f.settings_replies[0].applied&&f.settings_replies[0].content.includes('from Classic to Bratty')&&f.settings_replies[0].content.includes('You look far too comfortable.'),'Reply instruction lacks the change or reason');
 assert(f.settings_formatted,'Decision was not schema-constrained');
 assert(requests.at(-1).trigger==='user','Chat request not marked as the user\'s');
 await sleep(2000);f=await fixture();
 assert(f.settings_cards.length===0,'A separate card repeated what the reply already said');
 assert(f.selection_replies.length===0,'The Director acknowledged the AI change as the user\'s selection');
 assert(f.state.details.selection_source==='ai','Snapshot does not label the change as the AI\'s');
 await page.locator('[data-ai-settings-chip="applied"]').first().waitFor();
 assert((await page.locator('[data-ai-settings-chip="applied"]').first().textContent()).includes('Play style: Classic → Bratty'),'Chip text wrong');
 await page.locator('.read-only-note').filter({hasText:'AI Settings Control on'}).waitFor();
 await sleep(1500);await page.screenshot({path:path.join(output,'ai-settings-change.png')});
 report.steps.push('Enabled: pacing blocked own changes; chat request decided first, applied, labelled ai and announced in the reply itself (no duplicate card)');

 // 3. Undo is the user's own change.
 await page.locator('[data-ai-settings-chip="applied"] .ai-settings-undo').first().click();
 await until(async()=>(await engine()).style==='classic','Undo did not restore Classic');
 report.steps.push('Undo restored Classic');

 // 4. Malformed output requests nothing; a refused change is not claimed in the reply.
 const sent=requests.length;
 await propose({change:'SESSION_STATE',value:'RUNNING'});await chat('Make it harder.');
 await until(async()=>(await fixture()).settings_proposals_left===0,'Proposal not consumed');await sleep(1500);
 assert(requests.length===sent,'Malformed proposal reached the browser');
 await propose({change:'endgame',value:'denial',reason:'Not today.'});await chat("Don't let me finish tonight.");
 await until(async()=>outcomes.some(o=>o.reason==='rate_limited'),'Rate limit not enforced');
 await until(async()=>(await replies()).some(r=>!r.applied),'Reply was not told the change was refused');
 assert((await engine()).endgame!=='denial','Rate-limited change applied');
 report.steps.push('Malformed output requested nothing; a rate-limited request was refused and the reply was told nothing changed');

 // 5. Intensity clamped; endgame and Force Orgasm on request.
 await sleep(15500);
 await propose({change:'intensity',value:100,reason:'Harder.'});await chat('Harder, I can take more.');
 await until(async()=>(await engine()).intensity===80,'Intensity not clamped to the band');
 assert(outcomes.some(o=>o.setting==='intensity'&&o.status==='applied'&&o.clamped===true),'Clamp not reported');
 await sleep(15500);
 await propose({change:'endgame',value:'denial',reason:'Not today.'});await chat("Don't let me finish tonight.");
 await until(async()=>(await engine()).endgame==='denial','Endgame not applied');
 await sleep(15500);
 await propose({change:'orgasm',value:true,reason:'Now.'});await chat('I want to finish now.');
 await until(async()=>(await engine()).orgasm===true,'Force Orgasm not applied');
 report.steps.push('Intensity clamped to 80 and reported; endgame Denial and Force Orgasm applied on request');

 // 6. Pause on request, labelled ai; nothing else changes while paused and the AI cannot resume.
 await propose({change:'pause',reason:'Breathe.'});await chat('Can we take a short break?');
 await until(async()=>(await engine()).status==='PAUSED','AI pause not applied');
 await until(async()=>(await fixture()).state.details.pause_reason==='ai','Pause not labelled ai');
 await propose({change:'play_style',value:'milker',reason:'x'});await chat('Switch it up.');
 await until(async()=>outcomes.some(o=>o.reason==='not_running'),'Paused session did not refuse the change');
 assert((await engine()).status==='PAUSED'&&(await engine()).style==='classic','AI acted on a paused session');
 report.steps.push('Pause applied and labelled ai; a change requested while paused was refused, no resume');

 // 7. Emergency stop revokes until the user starts a new session.
 await page.locator('#sessionPlayPauseBtn').evaluate(el=>el.click());
 await until(async()=>(await engine()).status==='RUNNING','User resume failed');
 await page.locator('[data-emergency]').first().click();
 await until(async()=>(await engine()).status==='IDLE','Emergency stop failed');
 await until(async()=>(await fixture()).state.details.ai_settings.revoked===true,'Revocation not projected');
 await page.locator('[data-ai-settings]').filter({hasText:'Paused after emergency stop'}).waitFor();
 await page.locator('#sessionPlayPauseBtn').evaluate(el=>el.click());
 await until(async()=>(await engine()).status==='RUNNING','New session did not start');
 await until(async()=>(await fixture()).state.details.ai_settings.revoked===false,'A new user-started session did not clear revocation');
 report.steps.push('Emergency stop revoked AI control; a user-started session cleared it');

 // 8. Never: chat requests still work, the companion never acts on its own.
 await page.locator('[data-ai-settings-pacing]').selectOption('never');
 await until(async()=>(await fixture()).state.details.ai_settings.pacing==='never','Pacing not projected');
 assert((await fixture()).state.details.ai_settings.own_ready===false,'Never still allows own changes');
 report.steps.push('Pacing Never projected; own changes disabled');

 await page.locator('#sessionStopBtn').evaluate(el=>el.click());
 await page.screenshot({path:path.join(output,'ai-settings.png')});
 assert(!errors.length,'Browser errors: '+JSON.stringify(errors));assert(!browser.isolationViolations.length,'Fixture escaped its owned ports');
 report.outcomes=outcomes;report.cards=(await fixture()).settings_cards.length;report.passed=true;
}catch(e){report.error=e.stack;process.exitCode=1;try{const f=await fixture();report.debug={cards:f.settings_cards.map(c=>c.content.slice(-600)),replies:f.settings_replies.length,decisions:f.settings_decisions,director:f.director};}catch(x){report.debug=String(x);}}finally{if(browser)await browser.close();for(const child of children)child.kill('SIGTERM');await writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({passed:report.passed,steps:report.steps,error:report.error,debug:report.debug},null,1));}
