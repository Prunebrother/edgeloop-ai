// SPDX-License-Identifier: AGPL-3.0-only
// Owned isolated servers and nonpersistent browser only; fake Handy, mocked inference.
import {chromium} from 'playwright';
import {spawn,execFileSync} from 'node:child_process';
import {claimPorts,ownedReady,isolatedEnv,guardBrowser} from './fixture-isolation.mjs';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve(new URL('../..',import.meta.url).pathname);
const uiPort=8793,observerPort=8794,uiUrl=`http://127.0.0.1:${uiPort}`,observerUrl=`http://127.0.0.1:${observerPort}`;
const output=process.env.FORK_BROWSER_REPORT||'/tmp/edgeloop-player-interactions-browser';
const children=[];let browser;const report={passed:false,steps:[],fixture:'owned servers, temporary data, fake Handy, mocked Ollama'};
const assert=(x,m)=>{if(!x)throw Error(m);};const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function waitServer(url){return ownedReady(url,children);}
const fixture=async()=>await (await fetch(observerUrl+'/fixture/state')).json();
const requests=async()=>(await fixture()).player_requests;
async function waitRequests(n){for(let i=0;i<100;i++){const r=await requests();if(r.length>=n)return r;await sleep(100);}throw Error('Missing Player request '+n);}
try{
 await mkdir(output,{recursive:true});await claimPorts(uiPort,observerPort);
 children.push(spawn('python3',['tools/serve_local.py',String(uiPort)],{cwd:root,env:isolatedEnv(),stdio:'ignore'}));
 children.push(spawn(path.join(root,'.venv/bin/python'),['tests/fork/browser_service.py'],{cwd:root,env:isolatedEnv({PYTHONPATH:root,EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(observerPort)}),stdio:'ignore'}));
 await waitServer(uiUrl+'/');await waitServer(observerUrl+'/health');
 browser=guardBrowser(await chromium.launch(),[uiPort,observerPort]);
 const ctx=await browser.newContext({viewport:{width:1920,height:1080}});
 await ctx.addInitScript(()=>{
  Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:()=>Promise.reject(Error('No physical devices in fixture'))},configurable:true});
  Object.defineProperty(navigator,'serial',{value:{requestPort:()=>Promise.reject(Error('No physical devices in fixture')),getPorts:async()=>[]},configurable:true});
  if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=()=>Promise.reject(Error('No physical devices in fixture'));
 });
 const page=await ctx.newPage(),errors=[],frames=[],hardware=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('websocket',ws=>ws.on('framesent',e=>{try{const x=JSON.parse(e.payload);if(x.type==='observation')frames.push(x);}catch{}}));
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());
  if(u.hostname.endsWith('handyfeeling.com')){hardware.push(u.pathname);return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(u.pathname.endsWith('/connected')?{connected:true}:u.pathname.endsWith('/info')?{fwVersion:'3.2.3',model:'Handy 1.1'}:{result:0})});}
  if(!['127.0.0.1','localhost'].includes(u.hostname))return route.abort();return route.continue();
 });
 await page.goto(uiUrl+'/',{waitUntil:'load'});await page.locator('#ageConfirmBtn').click();await page.locator('#wizardSkipBtn').click();
 await page.locator('#companion-dashboard').waitFor();
 await page.locator('[data-url]').fill(observerUrl.replace('http:','ws:')+'/observe');await page.locator('[data-token]').fill('browser-fixture-token-'+'x'.repeat(32));await page.locator('[data-connect]').click();
 await page.waitForFunction(()=>document.querySelector('[data-telemetry]').textContent.includes('Authoritative telemetry connected'));
 await page.locator('[data-model] option[value="evelyn-lite-v1:latest"]').waitFor({state:'attached'});await page.locator('[data-model]').selectOption('evelyn-lite-v1:latest');await page.locator('[data-select]').click();
 await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.includes('Active: evelyn-lite-v1:latest'));
 await sleep(2500);assert((await requests()).length===0,'Initialization generated a Player reaction');
 await page.locator('#playerHeaderBtn').click();let r=await waitRequests(1);assert(r[0].kind==='player_opened','Opening not observed');
 const clip=path.join(output,'long-clip.webm');
 execFileSync('ffmpeg',['-v','error','-y','-stream_loop','9','-i',path.join(root,'tools/fixtures/smoke-clip.webm'),'-c','copy',clip]);
 const data=await readFile(clip);
 // Open/select/start burst, with real playback through the existing simulator + mocked toy gate.
 await page.locator('#cardBle').click();await page.getByRole('button',{name:/manual simulator/i}).click();await page.locator('#modalSimHrSlider').evaluate(el=>{el.value='90';el.dispatchEvent(new Event('input',{bubbles:true}));});await page.locator('#modalEngageSimBtn').click();
 if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').evaluate(el=>el.click());
 await page.locator('#cardHandy').click();await page.locator('#modalHandyInput').fill('FIXTURE-ONLY');await page.locator('#modalHandyConnectBtn').click();
 if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').evaluate(el=>el.click());
 await page.locator('#playerFileInput').setInputFiles({name:'Aladdin.webm',mimeType:'video/webm',buffer:data});
 r=await waitRequests(2);assert(r[1].kind==='video_selected','Selection not observed');
 const current=r[1].messages.at(-1).content;assert(current.includes('Aladdin')&&current.includes('Source: filename'),'Missing title/provenance');assert(!current.includes('/home/')&&!current.includes('blob:'),'Private source leaked');
 const selections=(await fixture()).selection_replies.length;
 // A file-loaded funscript changes mode without a play-style acknowledgement.
 await page.locator('#playerFileInput').setInputFiles({name:'Aladdin.funscript',mimeType:'application/json',buffer:Buffer.from('{"actions":[{"at":0,"pos":0},{"at":60000,"pos":100}]}')});
 await sleep(2500);assert((await fixture()).selection_replies.length===selections,'Spurious Script selection acknowledgement');
 await page.locator('#scriptContinueAfterVideo').evaluate(el=>{el.checked=true;el.dispatchEvent(new Event('change',{bubbles:true}));});
 await page.evaluate(()=>{document.getElementById('playerVideo').loop=true;});
 await page.locator('#sessionPlayPauseBtn').evaluate(el=>el.click());
 await page.evaluate(()=>{const v=document.getElementById('playerVideo');v.muted=true;return v.play().catch(()=>{});});
 await page.waitForFunction(()=>{const v=document.getElementById('playerVideo');return !v.paused&&v.currentTime>0.1;});
 r=await waitRequests(3);assert(r[2].kind==='video_started','Confirmed playback not observed');
 const started=frames.filter(f=>f.events.some(e=>e.kind==='video_started')).length;
 await page.evaluate(()=>{const v=document.getElementById('playerVideo');v.currentTime=.2;});await sleep(500);
 await page.locator('#sessionPlayPauseBtn').click().catch(()=>{});
 // Exercise the media lifecycle directly; the engine retains its own pause/resume gate.
 await page.evaluate(async()=>{const v=document.getElementById('playerVideo');v.pause();await v.play().catch(()=>{});});await sleep(3000);
 assert(frames.filter(f=>f.events.some(e=>e.kind==='video_started')).length===started,'Seek/resume retriggered start');
 await page.locator('[data-close-player]').click();await page.locator('#playerHeaderBtn').click();await sleep(3500);
 assert(frames.filter(f=>f.events.some(e=>e.kind==='player_opened')).length===2,'Close/reopen not observed exactly once');
 report.steps.push('Explicit opening only; selection title/provenance; confirmed playback; seek/resume deduplication; reopen; no media-caused Script acknowledgement');
 // Rapid new selection/start, then inspect the final relevant request and count.
 await page.locator('#sessionStopBtn').evaluate(el=>el.click());
 await page.waitForFunction(async()=>(await import('/src/js/state.js')).state.sessionStatus==='IDLE');
 await sleep(3000);
 const before=(await requests()).length;
 await page.locator('[data-close-player]').click();await page.locator('#playerHeaderBtn').click();
 await page.locator('#playerFileInput').setInputFiles([{name:'Second.webm',mimeType:'video/webm',buffer:data},{name:'Second.funscript',mimeType:'application/json',buffer:Buffer.from('{"actions":[{"at":0,"pos":0},{"at":60000,"pos":100}]}')}]);
 await page.waitForFunction(()=>document.getElementById('playerVideo').readyState>=2);
 await sleep(200);
 await page.evaluate(async()=>{document.getElementById('playerVideo').loop=true;const {state}=await import('/src/js/state.js');if(state.sessionStatus!=='RUNNING')document.getElementById('sessionPlayPauseBtn').click();});
 await page.waitForFunction(async()=>(await import('/src/js/state.js')).state.sessionStatus==='RUNNING');
 const playResult=await page.evaluate(async()=>{const v=document.getElementById('playerVideo');v.loop=true;try{await v.play();return {paused:v.paused,ready:v.readyState};}catch(e){return {error:e.message};}});
 await sleep(5000);r=await requests();const burst=r.slice(before).filter(x=>!x.retry);
 report.burst={playResult,status:(await fixture()).state?.status,kinds:burst.map(x=>x.kind),observed:(await fixture()).state?.details?.player,events:frames.slice(-8).flatMap(f=>f.events.map(e=>e.kind))};
 const confirmed=report.burst.observed.started>started;
 assert(burst.length===1&&burst[0].kind===(confirmed?'video_started':'video_selected')&&burst[0].messages.at(-1).content.includes('Second'),'New selection did not use the most relevant confirmed event: '+JSON.stringify(burst.map(x=>x.kind)));
 if(!confirmed)report.steps.push('The engine declined the immediate replay: no false video_started was emitted, and selection was acknowledged instead.');
 await page.screenshot({path:path.join(output,'player-interactions.png')});
 assert(!errors.length,'Browser errors: '+JSON.stringify(errors));assert(!browser.isolationViolations.length,'Fixture escaped its owned ports');
 report.steps.push('New media burst coalesces in the existing Director queue; all local traffic stayed inside fixture ports');
 report.passed=true;report.playerRequests=r.map(x=>({kind:x.kind,current:x.messages.at(-1).content}));report.observedEvents=frames.flatMap(f=>f.events.map(e=>e.kind)).filter(x=>x.startsWith('video_')||x==='player_opened');

}catch(e){report.error=e.stack;process.exitCode=1;}finally{if(browser)await browser.close();for(const child of children)child.kill('SIGTERM');await writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));}
