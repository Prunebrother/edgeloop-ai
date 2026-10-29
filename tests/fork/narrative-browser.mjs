// SPDX-License-Identifier: AGPL-3.0-only
// Real UI and authenticated backend; mocked Ollama, no device connection.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve(new URL('../..',import.meta.url).pathname),out=process.env.NARRATIVE_BROWSER_REPORT||'/tmp/f26-narrative-browser';
const ui='http://127.0.0.1:8850',ai='http://127.0.0.1:8858',children=[],report={passed:false,physical_hardware:false,steps:[],screenshots:[]};let browser,page;
const assert=(x,m)=>{if(!x)throw Error(m);},sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(url){for(let i=0;i<100;i++){try{if((await fetch(url)).ok)return;}catch{}await sleep(100);}throw Error('Fixture unavailable');}
async function state(){return (await fetch(ai+'/fixture/narrative')).json();}
async function select(model){await page.locator('[data-model]').selectOption(model);await page.locator('[data-select]').click();await page.waitForFunction(m=>document.querySelector('[data-selected]').textContent==='Active: '+m,model);}
async function chat(text){await page.locator('[data-text]').fill(text);await page.locator('[data-text]').press('Enter');await page.waitForFunction(()=>document.querySelector('[data-text]').value==='');await page.waitForFunction(()=>document.querySelector('[data-cancel]').hidden);assert(!(await page.locator('[data-error]').textContent()),'Chat failed');}
async function shot(name,width,height){await page.setViewportSize({width,height});await page.waitForFunction(()=>document.querySelector('#character-panel').dataset.artworkStatus!=='loading');await page.screenshot({path:path.join(out,name)});report.screenshots.push(name);}
try{
 await mkdir(out,{recursive:true});
 children.push(spawn('python3',['tools/serve_local.py','8850'],{cwd:root,stdio:'ignore'}));
 children.push(spawn(path.join(root,'.venv/bin/python'),['-m','tests.fork.narrative_browser_service'],{cwd:root,stdio:'ignore',env:{...process.env,EDGELOOP_LIVE_ACCEPTANCE:'0',EDGELOOP_FIXTURE_UI_PORT:'8850',EDGELOOP_FIXTURE_OBSERVER_PORT:'8858'}}));
 await wait(ui);await wait(ai+'/health');browser=await chromium.launch();const context=await browser.newContext({viewport:{width:1920,height:1080}});
 await context.addInitScript(()=>{const no=()=>Promise.reject(new DOMException('No physical hardware','NotFoundError'));Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:no},configurable:true});Object.defineProperty(navigator,'serial',{value:{requestPort:no,getPorts:async()=>[]},configurable:true});if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=no;});
 page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(ui+'/?characterPreview=1');await page.locator('#ageConfirmBtn').click();await page.locator('#wizardSkipBtn').click();
 await page.locator('[data-url]').fill('ws://127.0.0.1:8858/observe');await page.locator('[data-token]').fill('event-reliability-fixture-'+'x'.repeat(32));await page.locator('[data-connect]').click();await page.waitForFunction(()=>document.querySelector('[data-model] option[value="evelyn-narrative-v1:latest"]'));
 await select('evelyn-narrative-v1:latest');await chat('Imagine an observatory mystery. I choose the blue envelope.');
 assert((await state()).context.premise.includes('blue envelope'),'Premise not recorded');await chat('I choose to keep the brass key for later.');
 const before=await state();assert(before.requests.at(-1).messages.some(m=>m.content.includes('blue envelope')),'Callback context missing');assert(before.requests.every(r=>r.think===false),'Thinking enabled');
 await page.getByText('Runtime diagnostics · development',{exact:true}).click();await shot('evelyn-narrative-1920.png',1920,1080);assert(await page.locator('#character-panel').getAttribute('data-character')==='evelyn','Wrong Evelyn artwork');
 await select('daisy-narrative-v1:latest');assert((await state()).context.premise===null,'Narrative leaked between models');await chat('Imagine a Cloverfield mystery. I choose the violet letter.');assert(await page.locator('#character-panel').getAttribute('data-character')==='daisy','Wrong Daisy artwork');await shot('daisy-narrative-2560.png',2560,1440);
 await select('evelyn-narrative-v1:latest');assert((await state()).context.premise.includes('blue envelope'),'Story not restored');assert((await page.locator('[data-history]').textContent()).includes('brass key'),'Dialogue not restored');
 report.steps.push('Candidate identities, thinking OFF, bounded callback context and independent story/dialogue restoration');
 await page.locator('[data-menu-story]').click();await page.locator('[data-start-story]').click();await page.locator('[data-narrative-reset]').click();await page.getByText('New storyline started. Transcript retained.',{exact:true}).waitFor();await page.locator('#character-story [data-close]').click();assert((await state()).context.premise===null,'Reset failed');assert((await page.locator('[data-history]').textContent()).includes('brass key'),'Reset erased dialogue');
 await page.locator('[data-text]').fill('long streaming response');await page.locator('[data-text]').press('Enter');await page.waitForFunction(()=>!document.querySelector('[data-cancel]').hidden);await page.locator('[data-menu-story]').click();await page.locator('[data-start-story]').click();await page.locator('[data-narrative-reset]').click();await page.getByText('New storyline started. Transcript retained.',{exact:true}).waitFor();await page.locator('#character-story [data-close]').click();await sleep(500);assert(!(await state()).history.some(m=>m.content==='long streaming response'),'Cancelled partial response saved');
 report.steps.push('Independent story reset, reset during generation and incomplete-response exclusion');
 await shot('narrative-1366.png',1366,768);await page.setViewportSize({width:390,height:844});await page.locator('button[data-view=character]').click();await shot('narrative-mobile-390.png',390,844);assert(await page.locator('[data-emergency]').isVisible(),'Safety control hidden');assert(!(await page.locator('[data-history]').textContent()).includes('[[expression:'),'Metadata leaked');assert(errors.length===0,errors.join('; '));
 report.steps.push('Desktop/mobile artwork and independent emergency control remain accessible');report.passed=true;
}catch(e){report.error=e.stack;throw e;}finally{await writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));await browser?.close();for(const child of children)child.kill('SIGTERM');console.log(JSON.stringify(report));}
