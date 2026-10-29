// SPDX-License-Identifier: AGPL-3.0-only
// Explicit live character-model smoke; requires manually running loopback UI, observer and Ollama.
import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
if(!process.env.EDGELOOP_ACCEPT_TOKEN)throw Error('Set EDGELOOP_ACCEPT_TOKEN to the local observer pairing token');
const model=process.env.EDGELOOP_ACCEPT_MODEL||'evelyn-lite-v1:latest';
const uiUrl=process.env.LIVE_BROWSER_URL||'http://127.0.0.1:8770';
const observerUrl=process.env.LIVE_OBSERVER_URL||'http://127.0.0.1:8768';
const output=process.env.LIVE_BROWSER_REPORT||'/tmp/edgeloop-f21-live-acceptance';await mkdir(output,{recursive:true});
const report={passed:false,hardware:'No hardware; native requests denied; device HTTP blocked',steps:[]};
const browser=await chromium.launch();const context=await browser.newContext({viewport:{width:1920,height:1080}});
await context.addInitScript(()=>{const denied=()=>Promise.reject(new DOMException('Acceptance test: hardware disabled','NotAllowedError'));
 Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:denied},configurable:true});
 Object.defineProperty(navigator,'serial',{value:{requestPort:denied,getPorts:async()=>[]},configurable:true});
 if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=denied;});
const page=await context.newPage();const errors=[];report.frames=[];page.on('websocket',ws=>ws.on('framesent',event=>{try{const m=JSON.parse(event.payload);if(m.type!=='auth')report.frames.push({type:m.type,sequence:m.sequence,status:m.snapshot?.status});}catch{}}));page.on('pageerror',e=>errors.push(e.message));
await page.route('**/handyfeeling.com/**',r=>r.abort());
await page.route('**/api/handy/**',r=>r.abort());
try {
 await page.goto(uiUrl+'/');await page.locator('#ageConfirmBtn').click();
 await page.locator('#wizardOverlay').waitFor({state:'visible'});await page.locator('#wizardSkipBtn').click();
 await page.locator('#companion-dashboard').waitFor();report.steps.push('Dashboard loads');
 await page.locator('#cardBle').click();await page.locator('#bleTabSimBtn').click();
 await page.locator('#modalSimHrSlider').fill('98');await page.locator('#modalEngageSimBtn').click();
 if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
 await page.locator('[data-url]').fill(observerUrl.replace('http:','ws:')+'/observe');
 await page.locator('[data-token]').fill(process.env.EDGELOOP_ACCEPT_TOKEN);await page.locator('[data-connect]').click();
 await page.waitForFunction(model=>[...document.querySelector('[data-model]').options].some(o=>o.value===model),model,{timeout:20000});
 await page.locator('[data-model]').selectOption(model);await page.locator('[data-select]').click();
 await page.waitForFunction(model=>document.querySelector('[data-selected]').textContent.includes('Active: '+model),model,{timeout:90000});
 report.model=model;
 report.steps.push('Authenticated pairing and live character selection');
 await page.waitForTimeout(6500);
 const health=await(await fetch(observerUrl+'/health')).json();
 if(!health.observation_fresh)throw Error('Idle observation expired');
 report.steps.push('Idle observation stays fresh beyond the five-second lease');
 await page.locator('[data-text]').fill('Quick acceptance check: what BPM is reported, is it simulated, and is the session running or idle? Answer briefly using only the current telemetry.');
 await page.locator('[data-text]').press('Enter');
 await page.waitForFunction(()=>document.querySelectorAll('.message-assistant .message-content').length&&document.querySelector('.message-assistant .message-content').textContent.length>5,{},{timeout:90000});
 await page.waitForFunction(()=>document.querySelector('[data-cancel]').hidden,{},{timeout:90000});
 report.reply=await page.locator('.message-assistant .message-content').last().textContent();
 if(!/\b98\b/.test(report.reply)||!/simulat/i.test(report.reply)||!/idle/i.test(report.reply))throw Error('Live reply did not report the expected telemetry facts');
 report.steps.push('Real Ollama response streamed into conversation');
 report.telemetry=await page.locator('[data-telemetry]').textContent();
 if(!report.telemetry.includes('Authoritative telemetry connected'))throw Error('Telemetry not connected');
 const state=await page.evaluate(async()=>{const{state}=await import('/src/js/state.js');return {status:state.sessionStatus,hr:state.sensorHr};});
 report.state=state;if(state.status!=='IDLE')throw Error('Unexpected session start');
 await page.screenshot({path:output+'/desktop.png'});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:output+'/mobile.png'});
 await page.locator('[data-disconnect]').click();
 if(errors.length)throw Error(errors.join('\n'));report.passed=true;
} catch(e){report.error=String(e);await page.screenshot({path:output+'/failure.png'}).catch(()=>{});process.exitCode=1;}
finally {await browser.close();await writeFile(output+'/report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));}
