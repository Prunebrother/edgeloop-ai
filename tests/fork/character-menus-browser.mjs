// SPDX-License-Identifier: AGPL-3.0-only
// Real UI and authenticated backend; mocked Ollama, no device connection.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import net from 'node:net';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve(new URL('../..',import.meta.url).pathname),out=process.env.NARRATIVE_BROWSER_REPORT||'/tmp/f261-character-menus';
const uiPort=Number(process.env.EDGELOOP_MENU_UI_PORT||8850),aiPort=Number(process.env.EDGELOOP_MENU_AI_PORT||8858);
const ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`,children=[],report={passed:false,physical_hardware:false,steps:[],screenshots:[]};let browser,page;
const assert=(x,m)=>{if(!x)throw Error(m);},sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function requireFreePort(port){
 const probe=net.createServer();await new Promise((resolve,reject)=>{probe.once('error',reject);probe.listen(port,'127.0.0.1',resolve);});
 await new Promise((resolve,reject)=>probe.close(error=>error?reject(error):resolve()));
}
async function wait(url){for(let i=0;i<100;i++){try{if((await fetch(url)).ok)return;}catch{}await sleep(100);}throw Error('Fixture unavailable');}
async function state(){return (await fetch(ai+'/fixture/narrative')).json();}
async function select(model){await page.locator('[data-model]').selectOption(model);await page.locator('[data-select]').click();await page.waitForFunction(m=>document.querySelector('[data-selected]').textContent==='Active: '+m,model);}
async function chat(text){await page.locator('[data-text]').fill(text);await page.locator('[data-text]').press('Enter');await page.waitForFunction(()=>document.querySelector('[data-text]').value==='');await page.waitForFunction(()=>document.querySelector('[data-cancel]').hidden);assert(!(await page.locator('[data-error]').textContent()),'Chat failed');}
async function shot(name,width,height){await page.setViewportSize({width,height});await page.waitForFunction(()=>document.querySelector('#character-panel').dataset.artworkStatus!=='loading');await page.screenshot({path:path.join(out,name)});report.screenshots.push(name);}
try{
 await mkdir(out,{recursive:true});
 await requireFreePort(uiPort);await requireFreePort(aiPort);
 const testEnv={...process.env,EDGELOOP_LIVE_ACCEPTANCE:'0',EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(aiPort)};delete testEnv.EDGELOOP_PAIRING_FILE;
 children.push(spawn('python3',['tools/serve_local.py',String(uiPort)],{cwd:root,stdio:'ignore',env:testEnv}));
 children.push(spawn(path.join(root,'.venv/bin/python'),['-m','tests.fork.narrative_browser_service'],{cwd:root,stdio:'ignore',env:testEnv}));
 await wait(ui);await wait(ai+'/health');browser=await chromium.launch();const context=await browser.newContext({viewport:{width:1920,height:1080}});
 await context.addInitScript(()=>{const no=()=>Promise.reject(new DOMException('No physical hardware','NotFoundError'));Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:no},configurable:true});Object.defineProperty(navigator,'serial',{value:{requestPort:no,getPorts:async()=>[]},configurable:true});if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=no;});
 page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(ui+'/?characterPreview=1');await page.locator('#ageConfirmBtn').click();await page.locator('#wizardSkipBtn').click();
 await page.locator('[data-url]').fill('ws://127.0.0.1:8858/observe');await page.locator('[data-token]').fill('event-reliability-fixture-'+'x'.repeat(32));await page.locator('[data-connect]').click();await page.waitForFunction(()=>document.querySelector('[data-model] option[value="evelyn-narrative-v1:latest"]'));
 await select('evelyn-narrative-v1:latest');await chat('Imagine an observatory mystery. I choose the blue envelope.');
 assert((await state()).context.premise.includes('blue envelope'),'Premise not recorded');await chat('I choose to keep the brass key for later.');
 assert(await page.locator('#ai-companion [data-narrative-reset]').count()===0,'Story control remains under composer');
 const requestCount=(await state()).requests.length;
 await page.locator('#character-panel img').last().evaluate(el=>{el.dataset.menuProbe='retained';});
 await page.locator('[data-menu-director]').click();
 await page.getByRole('heading',{name:'Conversation Director',exact:true}).waitFor();
 await page.waitForFunction(()=>document.querySelector('[data-director-status]').textContent.includes('Proactive dialogue'));
 assert(await page.locator('[data-emergency]').isVisible(),'Director obscures emergency control');
 await page.keyboard.press('Escape');assert(await page.locator('[data-menu-director]').evaluate(el=>el===document.activeElement),'Escape did not restore focus');
 await page.locator('[data-menu-director]').click();await page.locator('[data-proactive]').uncheck();
 await sleep(2200);assert(!(await page.locator('[data-proactive]').isChecked()),'Status polling erased an unsaved edit');
 await page.locator('[data-save-director]').click();await page.getByText('Saved to the companion service.',{exact:true}).waitFor();
 await page.waitForFunction(()=>document.querySelector('[data-director-status]').textContent.includes('Proactive dialogueDisabled'));
 assert((await state()).requests.length===requestCount,'Opening/configuring menus triggered inference');
 await page.locator('#character-director [data-close]').click();await page.locator('[data-menu-director]').click();
 assert(!(await page.locator('[data-proactive]').isChecked()),'Saved setting was not restored');
 await page.keyboard.press('Escape');await page.locator('[data-mode="oracle"]').click();
 await page.locator('[data-menu-director]').click();await page.waitForFunction(()=>document.querySelector('[data-director-status]').textContent.includes('Goal changed'));
 assert((await page.locator('[data-director-status]').textContent()).includes('Major'),'Validated event significance missing');
 assert((await state()).requests.length===requestCount,'Disabled event generated commentary');
 await page.locator('[data-proactive]').check();await page.locator('[data-save-director]').click();await page.getByText('Saved to the companion service.',{exact:true}).waitFor();
 await sleep(2200);assert((await state()).requests.length===requestCount,'Re-enabling proactive replayed disabled events');
 await page.getByLabel('Experimental idle initiative',{exact:true}).check();
 await page.getByLabel('Initiative interval (seconds)',{exact:true}).fill('50');
 await page.getByLabel('Idle response cooldown (seconds)',{exact:true}).fill('40');
 await page.getByLabel('Event reaction cooldown (seconds)',{exact:true}).fill('4');
 await page.getByLabel('Topic repetition cooldown (seconds)',{exact:true}).fill('180');
 await page.locator('[data-save-director]').click();await page.getByText('Saved to the companion service.',{exact:true}).waitFor();
 const pacing=(await (await fetch(ai+'/fixture/context')).json()).director.settings;
 assert(pacing.experimental_idle_enabled&&pacing.idle_interval_seconds===50&&pacing.topic_cooldown_seconds===180,'Director pacing not applied');
 assert((await state()).requests.length===requestCount,'Saving initiative settings caused inference');
 await page.getByLabel('Experimental idle initiative',{exact:true}).uncheck();await page.locator('[data-save-director]').click();await page.getByText('Saved to the companion service.',{exact:true}).waitFor();
 report.steps.push('Character-scoped idle/event/topic pacing validates and saves without inference');
 await shot('director-1920.png',1920,1080);await page.keyboard.press('Escape');
 await page.locator('[data-menu-story]').click();await page.getByRole('heading',{name:'Current premise',exact:true}).waitFor();
 assert((await page.locator('[data-story-content]').textContent()).includes('blue envelope'),'Story premise not displayed');
 await page.locator('[data-start-story]').click();await page.locator('[data-story-keep]').click();
 assert((await state()).context.premise.includes('blue envelope'),'Cancel confirmation reset story');
 await shot('story-memory-1920.png',1920,1080);await page.keyboard.press('Escape');
 assert(await page.locator('#character-panel img[data-menu-probe=retained]').count()===1,'Menus reloaded the portrait');
 report.steps.push('Both character menus, keyboard/Escape focus restoration, backend settings, no inference, readable story and cancelled reset');
 const before=await state();assert(before.requests.at(-1).messages.some(m=>m.content.includes('blue envelope')),'Callback context missing');assert(before.requests.every(r=>r.think===false),'Thinking enabled');
 await page.getByText('Runtime diagnostics · development',{exact:true}).click();await shot('evelyn-narrative-1920.png',1920,1080);assert(await page.locator('#character-panel').getAttribute('data-character')==='evelyn','Wrong Evelyn artwork');
 await select('daisy-narrative-v1:latest');assert((await state()).context.premise===null,'Narrative leaked between models');await chat('Imagine a Cloverfield mystery. I choose the violet letter.');assert(await page.locator('#character-panel').getAttribute('data-character')==='daisy','Wrong Daisy artwork');await shot('daisy-narrative-2560.png',2560,1440);
 await select('evelyn-narrative-v1:latest');assert((await state()).context.premise.includes('blue envelope'),'Story not restored');assert((await page.locator('[data-history]').textContent()).includes('brass key'),'Dialogue not restored');
 report.steps.push('Candidate identities, thinking OFF, bounded callback context and independent story/dialogue restoration');
 await page.locator('[data-menu-story]').click();await page.locator('[data-start-story]').click();await page.locator('[data-narrative-reset]').click();await page.getByText('New storyline started. Transcript retained.',{exact:true}).waitFor();await page.locator('#character-story [data-close]').click();assert((await state()).context.premise===null,'Reset failed');assert((await page.locator('[data-history]').textContent()).includes('brass key'),'Reset erased dialogue');
 await chat('Imagine a fresh garden scene.');const fresh=await state();
 assert(!fresh.requests.at(-1).messages.some(m=>m.content.includes('blue envelope')||m.content.includes('brass key')),'Abandoned story leaked into new inference');
 await page.locator('[data-menu-story]').click();await shot('fresh-story-2560.png',2560,1440);await page.keyboard.press('Escape');
 await page.locator('[data-text]').fill('long streaming response');await page.locator('[data-text]').press('Enter');await page.waitForFunction(()=>!document.querySelector('[data-cancel]').hidden);await page.locator('[data-menu-story]').click();await page.locator('[data-start-story]').click();await page.locator('[data-narrative-reset]').click();await page.getByText('New storyline started. Transcript retained.',{exact:true}).waitFor();await page.locator('#character-story [data-close]').click();await sleep(500);assert(!(await state()).history.some(m=>m.content==='long streaming response'),'Cancelled partial response saved');
 report.steps.push('Independent story reset, reset during generation and incomplete-response exclusion');
 await shot('narrative-1366.png',1366,768);await page.setViewportSize({width:390,height:844});await page.locator('button[data-view=character]').click();await shot('narrative-mobile-390.png',390,844);
 await page.locator('[data-menu-story]').click();await shot('story-mobile-390.png',390,844);
 assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)),'Story drawer overflows mobile viewport');
 assert(await page.locator('[data-emergency]').isVisible(),'Story drawer blocks emergency control');
 await page.keyboard.press('Escape');await page.locator('[data-menu-director]').click();await shot('director-mobile-390.png',390,844);
 await page.keyboard.press('Escape');assert(await page.locator('[data-emergency]').isVisible(),'Safety control hidden');assert(!(await page.locator('[data-history]').textContent()).includes('[[expression:'),'Metadata leaked');assert(errors.length===0,errors.join('; '));
 report.steps.push('Desktop/mobile artwork and independent emergency control remain accessible');report.passed=true;
}catch(e){report.error=e.stack;throw e;}finally{await writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));await browser?.close();for(const child of children)child.kill('SIGTERM');console.log(JSON.stringify(report));}
