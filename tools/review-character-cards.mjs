// SPDX-License-Identifier: AGPL-3.0-only
// Interactive simulator review on the integrated source: real local F29 models,
// intercepted device HTTP, denied native devices and non-observer sockets.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {createServer} from 'node:net';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve(new URL('..',import.meta.url).pathname);
const smoke=process.argv.includes('--smoke');
const uiPort=process.env.EDGELOOP_REVIEW_UI_PORT||'18970';
const aiPort=process.env.EDGELOOP_REVIEW_AI_PORT||'18968';
const ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`;
const report={passed:false,simulator_only:true,real_ollama:'http://127.0.0.1:11435',
  mocked_device_requests:0,blocked_requests:[],agent_requests:[],steps:[]};
const children=[];let browser,page,fixtureLog='';
const check=(ok,message)=>{if(!ok)throw Error(message);};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function free(port){await new Promise((resolve,reject)=>{const s=createServer();s.once('error',reject);s.listen(Number(port),'127.0.0.1',()=>s.close(resolve));});}
async function ready(url){for(let n=0;n<100;n++){try{if((await fetch(url)).ok)return;}catch{}await sleep(100);}throw Error('Fixture not ready: '+url+' '+fixtureLog);}
function child(args){const p=spawn(path.join(root,'.venv/bin/python'),args,{cwd:root,env:{...process.env,EDGELOOP_FIXTURE_UI_PORT:uiPort,EDGELOOP_FIXTURE_OBSERVER_PORT:aiPort},stdio:['ignore','ignore','pipe']});p.stderr.on('data',d=>fixtureLog+=d);children.push(p);}
try{
  const installed=await(await fetch('http://127.0.0.1:11435/api/tags')).json();
  const models=['nova-narrative-f29-v011:latest','daisy-narrative-f29-v014:latest','evelyn-narrative-f29-v013:latest','celeste-narrative-f29-v012:latest'];
  check(models.every(m=>installed.models.some(x=>x.name===m)),'The four installed F29 models must be available on port 11435.');
  await free(uiPort);await free(aiPort);
  child(['tools/serve_local.py',uiPort]);child(['-m','tests.fork.f29_review_service']);
  await ready(ui+'/');await ready(ai+'/health');
  check((await(await fetch(ai+'/health')).json()).read_only,'Observer is not read-only');
  browser=await chromium.launch({headless:smoke});
  process.once('SIGINT',()=>browser?.close());process.once('SIGTERM',()=>browser?.close());
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.addInitScript(()=>{
    const no=()=>Promise.reject(new DOMException('Simulator review: physical devices disabled','NotAllowedError'));
    Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:no,getDevices:async()=>[]},configurable:true});
    Object.defineProperty(navigator,'serial',{value:{requestPort:no,getPorts:async()=>[]},configurable:true});
    Object.defineProperty(navigator,'usb',{value:{requestDevice:no,getDevices:async()=>[]},configurable:true});
    Object.defineProperty(navigator,'hid',{value:{requestDevice:no,getDevices:async()=>[]},configurable:true});
    if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=no;
  });
  await context.routeWebSocket('**/*',ws=>{
    if(ws.url()===ai.replace('http:','ws:')+'/observe')ws.connectToServer();
    else{report.blocked_requests.push(ws.url());ws.close();}
  });
  await context.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(/\/api\/(agent|room)\b/.test(url.pathname)){report.agent_requests.push(url.href);return route.abort();}
    if(url.hostname.endsWith('handyfeeling.com')){
      report.mocked_device_requests++;
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(url.pathname.endsWith('/connected')?{connected:true}:url.pathname.endsWith('/info')?{fwVersion:'3.2.3',model:'Handy 1.1'}:{result:0})});
    }
    if([ui,ai].includes(url.origin))return route.continue();
    report.blocked_requests.push(url.href);return route.abort();
  });
  page=await context.newPage();const replies=[];
  page.on('websocket',ws=>ws.on('framereceived',event=>{try{const m=JSON.parse(event.payload);if(m.type==='speech'&&m.source==='user')replies.push(m.text);}catch{}}));
  await page.goto(ui+'/');
  await page.locator('#ageConfirmBtn').click();await page.locator('#wizardOverlay').waitFor({state:'visible'});await page.locator('#wizardSkipBtn').click();
  await page.locator('#companion-dashboard').waitFor();
  await page.locator('#cardBle').click();await page.getByRole('button',{name:/manual simulator/i}).click();
  await page.locator('#modalSimHrSlider').fill('98');await page.locator('#modalEngageSimBtn').click();
  if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
  await page.locator('#cardHandy').click();await page.locator('#modalHandyInput').fill('SIMULATOR-ONLY-NOT-A-DEVICE');await page.locator('#modalHandyConnectBtn').click();await sleep(700);
  if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
  await page.locator('[data-url]').fill(ai.replace('http:','ws:')+'/observe');
  await page.locator('[data-token]').fill('f29-local-review-'+'x'.repeat(32));await page.locator('[data-connect]').click();
  await page.locator('[data-model] option[value="nova-narrative-f29-v011:latest"]').waitFor({state:'attached'});
  await page.locator('[data-model]').selectOption(models[0]);await page.locator('[data-select]').click();
  await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.includes('Active: nova-narrative-f29-v011:latest'));
  report.steps.push('Integrated UI, read-only observer, four installed F29 aliases, simulated HR and mocked device readiness');
  if(smoke){
    await page.locator('#sessionPlayPauseBtn').evaluate(el=>el.click());
    await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';});
    const replyCount=replies.length;
    await page.locator('[data-text]').fill('Please identify yourself briefly.');await page.locator('[data-chat]').evaluate(el=>el.requestSubmit());
    const deadline=Date.now()+125000;
    while(replies.length===replyCount){
      const error=await page.locator('[data-error]').textContent();check(!error,error);
      check(Date.now()<deadline,'No completed user reply received');await sleep(50);
    }
    report.reply=replies.at(-1);
    check(await page.evaluate(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';}),'Dialogue changed the engine session');
    report.fixture=await(await fetch(ai+'/fixture/state')).json();
    check(report.fixture.read_only&&report.fixture.calls.length>0,'Real F29 inference or read-only boundary missing');
    check(report.fixture.calls.every(c=>!c.thinking&&!c.tools),'Thinking or tools enabled');
    report.steps.push('Real F29 reply delivered to a running simulated browser session');
    await page.locator('[data-emergency]').click();
    await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='IDLE'&&state.strokerSpeed===0&&state.prostateSpeed===0;});
    report.steps.push('User emergency control stops the simulated engine');
    check(!report.agent_requests.length,'Agent endpoint requested');report.passed=true;
  }else{
    console.log(`Simulator-only review ready at ${ui}. The opened Chromium window intercepts all device traffic.\nUse Play to start; choose any F29 companion. Close that window or press Ctrl+C to stop.\nDo not open a separate ordinary browser tab: interception belongs to this review window.`);
    await new Promise(resolve=>browser.once('disconnected',resolve));report.passed=true;
  }
}catch(error){report.error=String(error);process.exitCode=1;}
finally{
  if(browser)await browser.close();for(const p of children)p.kill('SIGTERM');
  if(process.env.EDGELOOP_REVIEW_REPORT){await mkdir(process.env.EDGELOOP_REVIEW_REPORT,{recursive:true});await writeFile(path.join(process.env.EDGELOOP_REVIEW_REPORT,'report.json'),JSON.stringify(report,null,2));await writeFile(path.join(process.env.EDGELOOP_REVIEW_REPORT,'fixture.log'),fixtureLog);}
  console.log(JSON.stringify({passed:report.passed,error:report.error,steps:report.steps}));
}
