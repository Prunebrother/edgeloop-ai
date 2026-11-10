// SPDX-License-Identifier: AGPL-3.0-only
// Character Builder end to end in the real app: isolated observer, mocked Ollama and Handy,
// the app's Manual Simulator for heart rate. Open the builder workspace, create, validate,
// preview, activate, talk, let the Director draw a custom card, check the per-persona AI
// Settings and event preferences, the visible limits, condition round-trips, and switch back.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {copyFile,mkdir,readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {claimPorts,ownedReady,isolatedEnv,guardBrowser} from './fixture-isolation.mjs';
const root=path.resolve(new URL('../..',import.meta.url).pathname);
const output=process.env.CHARACTER_BUILDER_BROWSER_REPORT||'/tmp/edgeloop-character-builder-browser';
const uiPort=8840,aiPort=8848,ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`;
const python=process.env.EDGELOOP_TEST_PYTHON||path.join(root,'.venv/bin/python');
const fixture=path.join(root,'tests/fixtures/character-builder');
const BASE='huihui_ai/qwen3.5-abliterated:9b',DAISY='daisy-narrative-f29-v014:latest';
const report={passed:false,steps:[],screenshots:[],physical_devices:'Denied; Handy HTTP intercepted'};
const children=[];const errors=[];let browser,page;
const assert=(v,m)=>{if(!v)throw Error(m);};
const json=async url=>(await fetch(ai+url)).json();
async function shot(name){await page.screenshot({path:path.join(output,name),fullPage:false});report.screenshots.push(name);}
try{
 await mkdir(output,{recursive:true});
 const world=JSON.parse(await readFile(path.join(fixture,'world-saltglass.json'),'utf8'));
 const wren=JSON.parse(await readFile(path.join(fixture,'character-wren.json'),'utf8'));
 await claimPorts(uiPort,aiPort);
 const env={EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(aiPort),PYTHONPATH:root};
 for(const [command,args,extra] of [['python3',['tools/serve_local.py',String(uiPort)],{}],[python,['tests/fork/character_builder_browser_service.py'],env]])
  children.push(spawn(command,args,{cwd:root,env:{...isolatedEnv(),...extra},stdio:'ignore'}));
 await ownedReady(ui+'/',children);await ownedReady(ai+'/health',children);
 browser=guardBrowser(await chromium.launch(),[uiPort,aiPort]);
 const context=await browser.newContext({viewport:{width:1600,height:1000}});
 await context.addInitScript(()=>{const no=()=>Promise.reject(new DOMException('Mocked-device test','NotFoundError'));Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:no},configurable:true});Object.defineProperty(navigator,'serial',{value:{requestPort:no,getPorts:async()=>[]},configurable:true});});
 await context.route('**/api/handy/v2/**',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(route.request().url().endsWith('/connected')?{connected:true}:route.request().url().endsWith('/info')?{fwVersion:'3.2.3',model:'Handy 1.1'}:{result:0})}));
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(ui+'/');await page.locator('#ageConfirmBtn').click();await page.locator('#wizardOverlay').waitFor({state:'visible'});await page.locator('#wizardSkipBtn').click();await page.locator('#companion-dashboard').waitFor();
 // A running simulated session: Manual Simulator heart rate and a mocked Handy.
 await page.locator('#cardBle').click();await page.getByRole('button',{name:/manual simulator/i}).click();await page.locator('#modalSimHrSlider').evaluate(el=>{el.value='96';el.dispatchEvent(new Event('input',{bubbles:true}));});await page.locator('#modalEngageSimBtn').click();if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
 await page.locator('#cardHandy').click();await page.locator('#modalHandyInput').fill('BUILDER-MOCK-ONLY');await page.locator('#modalHandyConnectBtn').click();await page.waitForTimeout(600);if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
 await page.locator('#sessionPlayPauseBtn').click();
 await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';});
 await page.locator('[data-url]').fill(`ws://127.0.0.1:${aiPort}/observe`);await page.locator('[data-token]').fill('browser-fixture-token-'+'x'.repeat(32));await page.locator('[data-connect]').click();
 await page.locator(`[data-model] option[value="${DAISY}"]`).waitFor({state:'attached'});
 // The built-in companions have AI Settings Control on, so the persona's own "off" is meaningful.
 const settingsPanel=page.locator('[data-ai-settings]');await settingsPanel.locator('summary').click();
 await page.locator('[data-ai-settings-enabled]').check();
 assert((await page.locator('[data-ai-settings-profile]').textContent()).includes('built-in companions'),'Built-in profile label missing');
 report.steps.push('Simulated session running; paired; AI Settings Control enabled for the built-in companions');

 // 1. The builder opens in its own workspace from the model picker.
 const chatPanel=page.locator('#ai-companion'),builder=page.locator('[data-character-builder]');
 const openBuilder=async()=>{await page.locator('[data-open-builder]').click();await builder.waitFor({state:'visible'});assert(!(await chatPanel.isVisible()),'Conversation still visible over the builder');};
 const backToChat=async()=>{await builder.locator('[data-b-close]').click();await chatPanel.waitFor({state:'visible'});assert(!(await builder.isVisible()),'Builder still visible');};
 await openBuilder();
 const folderText=await builder.locator('[data-b-art-folder]').filter({hasText:'Put portrait'}).textContent();
 const folder=folderText.match(/ in (.+), then reopen/)[1],library=path.dirname(folder);
 assert(folderText.includes('Direct upload is not available yet'),'Art folder limitation not explained');
 await copyFile(path.join(fixture,'wren.png'),path.join(folder,'wren.png'));
 await backToChat();await openBuilder();
 await builder.locator('[data-b-art] option[value="wren.png"]').waitFor({state:'attached'});
 await shot('workspace.png');report.steps.push('Character Builder opens as its own workspace from the model picker; the conversation is hidden, not removed');
 for(const key of ['id','name','setting','lore'])await builder.locator(`[data-w="${key}"]`).fill(world[key]);
 await builder.locator('[data-w="rules"]').fill(world.rules.join('\n'));
 for(const key of ['id','name','short_name','personality','voice','relationship','model'])await builder.locator(`[data-c="${key}"]`).fill(String(wren[key]));
 await builder.locator('[data-c="age"]').fill(String(wren.age));
 await builder.locator('[data-b-art]').selectOption('wren.png');
 // A small deck: two tide-lore cards against one dry-tease card, and one malformed card.
 const cards=[wren.deck.cards[0],wren.deck.cards[1],wren.deck.cards[4],{id:'bad-card',theme:'oops',brief:'Raise the speed now and tell them.',when:{}}];
 for(let i=1;i<cards.length;i++)await builder.locator('[data-b-add]').click();
 const cardBoxes=builder.locator('.builder-card');
 for(const [i,card] of cards.entries()){
  const box=cardBoxes.nth(i);
  await box.getByLabel('Card ID').fill(card.id);await box.getByLabel('Theme').fill(card.theme);await box.getByLabel('Brief for the model').fill(card.brief);
  if(card.when.min_seconds!=null)await box.getByLabel('From second').fill(String(card.when.min_seconds));
 }
 assert((await builder.locator('[data-b-count]').textContent())==='4 of 16 cards','Card count not shown');
 assert(/Character and deck message: \d+\.\d KiB of 16\.0 KiB$/.test(await builder.locator('[data-b-character-size]').textContent()),'Message size not shown');
 await builder.locator('[data-b-preview]').click();
 await builder.locator('[data-b-errors] li').first().waitFor();
 const shown=await builder.locator('[data-b-errors]').textContent();
 assert(/cards › 3 › brief: Cards are dialogue and story briefs/.test(shown),'Malformed card error not shown: '+shown);
 assert(await builder.locator('[data-b-activate]').isDisabled(),'Activate enabled with errors');
 report.steps.push('Card count and message size are shown; a card asking to change the speed is rejected with its path');
 await cardBoxes.nth(3).getByRole('button',{name:'Remove card'}).click();
 await builder.locator('[data-b-preview]').click();
 await builder.locator('[data-b-preview-out] h4').waitFor();
 const heading=await builder.locator('[data-b-preview-out] h4').textContent();
 assert(heading.startsWith('Wren Calloway · The Saltglass Reach · revision 1'),'Preview heading: '+heading);
 await page.waitForFunction(()=>document.querySelector('.builder-portrait')?.naturalWidth>0);
 await shot('preview.png');report.steps.push('Saved locally (revision 1); preview shows persona, deck, theme weights, shared lifecycle and portrait');

 await builder.locator('[data-b-activate]').click();
 await builder.locator('[data-b-status]').filter({hasText:'is active'}).waitFor();
 await backToChat();
 await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.startsWith('Active: Wren Calloway (custom)'));
 await page.waitForFunction(()=>{const h=document.querySelector('#character-panel');return h.dataset.character==='custom.wren-calloway'&&h.querySelector('img')?.naturalWidth>0;});
 const scope=await json('/fixture/scope');assert(scope.scope.endsWith(`${BASE}#character=wren-calloway`),'Scope: '+scope.scope);
 report.steps.push('Activated: portrait, name and a separate memory scope for the custom character');

 // 2. Per-persona preferences: AI Settings Control starts off for Wren; the event entry is Wren's own.
 assert(!(await page.locator('[data-ai-settings-enabled]').isChecked()),'AI Settings Control inherited the built-in setting');
 assert((await page.locator('[data-ai-settings-profile]').textContent()).includes('Applies to Wren Calloway only'),'Persona profile label missing');
 await page.locator('[data-ai-settings-enabled]').check();
 assert(await page.evaluate(()=>JSON.parse(localStorage.getItem('edgeloop_ai_settings:custom.wren-calloway')).enabled===true),'Opt-in not stored for Wren');
 await page.locator('[data-menu-director]').click();await page.locator('[data-event-config]>summary').click();
 const wrenPrefs=page.locator('[data-event-preferences] details[data-identity="custom.wren-calloway"]');
 await wrenPrefs.waitFor({state:'attached'});
 assert((await wrenPrefs.locator('summary').textContent())==='Custom character: wren-calloway','Custom event entry label');
 for(const category of ['physiology','session','configuration','story'])assert(await wrenPrefs.locator(`[name="preferences.custom.wren-calloway.${category}"]`).inputValue()==='1','Wren did not start at normal defaults: '+category);
 // Escape is the app's Stop key, so the menu is closed by clicking outside it.
 await page.locator('[data-text]').click();await page.locator('#character-director').waitFor({state:'hidden'});
 report.steps.push('Wren starts with AI Settings Control off and opts in for herself; her event preferences have their own entry at normal defaults');

 await page.locator('[data-text]').fill('Where am I?');await page.locator('[data-text]').press('Enter');
 await page.waitForFunction(()=>document.querySelector('[data-history]').textContent.includes('Stillwater light, Saltglass Reach'));
 let last=(await json('/fixture/chats')).at(-1);
 assert(last.system.startsWith('You are Wren Calloway')&&!/Daisy|Cloverfield/.test(last.system),'Persona did not replace the model identity');
 report.steps.push('User chat runs on the custom persona; the model\'s built-in Daisy identity never reaches the request');

 // Returning from the workspace keeps the conversation and the active character.
 const before=await page.locator('[data-history]').innerHTML();
 await openBuilder();await backToChat();
 assert(await page.locator('[data-history]').innerHTML()===before,'Conversation changed while the builder was open');
 assert((await page.locator('[data-selected]').textContent()).startsWith('Active: Wren Calloway (custom)'),'Active character lost');
 report.steps.push('Opening the builder and returning to chat keeps the conversation and the active character');

 await fetch(ai+'/fixture/fast-deck',{method:'POST'});
 await page.waitForFunction(()=>document.querySelector('[data-history]').textContent.includes('Logged:'),null,{timeout:30000});
 await page.evaluate(async()=>{const {state}=await import('/src/js/state.js');state.sessionSeconds=Math.max(state.sessionSeconds,120);});
 let card=null;
 for(let i=0;i<60&&!card;i++){await page.waitForTimeout(500);card=(await json('/fixture/chats')).find(c=>c.last.includes('A MOMENT TO SPEAK')&&cards.slice(0,3).some(x=>c.last.includes(x.brief)));}
 if(!card)throw Error('No custom card brief reached the model; prompts: '+JSON.stringify((await json('/fixture/chats')).map(c=>c.last.slice(-300))));
 const used=cards.slice(0,3).find(x=>card.last.includes(x.brief));
 report.steps.push(`Director drew custom card "${used.id}" (${used.theme}) in the simulated session`);
 await shot('custom-card-dialogue.png');

 // 3. Limits: the 16-card cap and the 16 KiB message limit are visible and explained.
 await openBuilder();
 for(let i=3;i<16;i++)await builder.locator('[data-b-add]').click();
 assert((await builder.locator('[data-b-count]').textContent())==='16 of 16 cards · the deck is full','Full deck not shown');
 assert(await builder.locator('[data-b-add]').isDisabled(),'Add card enabled at 16');
 const wide='ž'.repeat(400),occasion='ž'.repeat(160);
 for(let i=0;i<16;i++){const box=builder.locator('.builder-card').nth(i);await box.getByLabel('Card ID').fill('c'+i);await box.getByLabel('Theme').fill('t');await box.getByLabel('Brief for the model').fill(wide);await box.getByLabel('Occasion (optional)').fill(occasion);}
 assert((await builder.locator('[data-b-character-size]').getAttribute('data-over'))==='true','Oversize not flagged');
 await builder.locator('[data-b-save]').click();
 const tooBig=await builder.locator('[data-b-errors]').textContent();
 assert(/over the 16\.0 KiB limit\. .*before the deck has 16 cards/.test(tooBig),'Payload error not explained: '+tooBig);
 assert((await builder.locator('[data-b-status]').textContent())==='Not saved.','Oversize save not refused');
 await shot('size-limit.png');
 const saved=JSON.parse(await readFile(path.join(library,'characters/wren-calloway.json'),'utf8'));
 assert(saved.deck.cards.length===3,'An oversize deck reached the library');
 report.steps.push('16-card cap and the 16 KiB message limit are shown; an oversize multi-byte deck is refused with an explanation and nothing is saved');

 // Conditions written in the data format survive opening and saving in the editor.
 const hr=structuredClone(saved);hr.id='wren-hr';hr.name='Wren Harrow';
 hr.deck.cards[0].when={...hr.deck.cards[0].when,requires_hr:true,hr_trends:['rising'],statuses:['RAMPDOWN']};
 hr.deck.cards[1].when={...hr.deck.cards[1].when,requires_story_welcome:true};
 await writeFile(path.join(library,'characters/wren-hr.json'),JSON.stringify(hr,null,2));
 await backToChat();await openBuilder();
 await builder.locator('[data-b-open] option[value="wren-hr"]').waitFor({state:'attached'});
 await builder.locator('[data-b-open]').selectOption('wren-hr');await builder.locator('[data-b-load]').click();
 await page.waitForFunction(()=>document.querySelector('[data-c="name"]').value==='Wren Harrow');
 assert(await builder.locator('[data-b-kept]').count()===2,'Kept conditions not shown');
 assert((await builder.locator('[data-b-kept]').first().textContent()).includes('needs a live heart rate (rising)'),'HR condition not named');
 await builder.locator('.builder-card').nth(2).getByLabel('Brief for the model').fill('Give a deadpan compliment that sounds like a shipping forecast.');
 await builder.locator('[data-b-save]').click();await builder.locator('[data-b-status]').filter({hasText:'Saved locally'}).waitFor();
 const resaved=JSON.parse(await readFile(path.join(library,'characters/wren-hr.json'),'utf8'));
 const w0=resaved.deck.cards.find(c=>c.id===hr.deck.cards[0].id).when,w1=resaved.deck.cards.find(c=>c.id===hr.deck.cards[1].id).when;
 assert(w0.requires_hr===true&&w0.hr_trends.join()==='rising'&&w0.statuses.join()==='RAMPDOWN'&&w1.requires_story_welcome===true,'Conditions lost on resave: '+JSON.stringify([w0,w1]));
 assert(resaved.revision===2,'Edited resave did not bump the revision');
 report.steps.push('Opening and resaving a deck keeps heart-rate, story and status conditions written in the data format');
 await backToChat();

 // Back to a built-in companion through the normal model picker: its own AI Settings return.
 await page.locator('[data-model]').selectOption(DAISY);await page.locator('[data-select]').click();
 await page.waitForFunction(m=>document.querySelector('[data-selected]').textContent==='Active: '+m,DAISY);
 await page.waitForFunction(()=>document.querySelector('#character-panel').dataset.character==='daisy');
 assert(await page.locator('[data-ai-settings-enabled]').isChecked(),'Built-in AI Settings preference not restored');
 assert((await page.locator('[data-ai-settings-profile]').textContent()).includes('built-in companions'),'Built-in profile label not restored');
 await page.locator('[data-text]').fill('Hello again');await page.locator('[data-text]').press('Enter');
 await page.waitForFunction(()=>document.querySelector('[data-history]').textContent.includes('Cloverfield Farm says hello.'));
 last=(await json('/fixture/chats')).at(-1);
 assert(last.system.startsWith('You are Daisy Mae Harper')&&!last.system.includes('Wren'),'Built-in identity not restored');
 assert(!(await page.locator('[data-history]').textContent()).includes('Stillwater'),'Custom character history leaked into the built-in companion');
 await shot('back-to-builtin.png');report.steps.push('Switched back to Daisy: built-in identity, portrait, AI Settings preference and a separate history');
 assert(errors.length===0,errors.join('\n'));report.passed=true;
}catch(error){report.error=String(error);if(page)await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});process.exitCode=1;}
finally{for(const child of children)child.kill();if(browser)await browser.close();await mkdir(output,{recursive:true});await writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({passed:report.passed,steps:report.steps,error:report.error,output}));}
