// SPDX-License-Identifier: AGPL-3.0-only
// Real high-resolution originals, isolated observer, mocked Ollama/Handy only.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve(new URL('../..',import.meta.url).pathname),output=process.env.CHARACTER_BROWSER_REPORT||'/tmp/edgeloop-f24-character-browser';
const uiPort=8810,aiPort=8818,ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`;
const report={passed:false,steps:[],rendered_portraits:[],art_requests:[],max_image_layers:0,physical_devices:'Denied; Handy HTTP intercepted',screenshots:[]};
const children=[];let browser,page;const errors=[];
const assert=(v,m)=>{if(!v)throw Error(m);},sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(url){for(let i=0;i<70;i++){try{if((await fetch(url)).ok)return;}catch{}await sleep(100);}throw Error('Fixture did not start');}
async function boot(p,url,knownProfile=false){await p.goto(url);if(!knownProfile){await p.locator('#ageConfirmBtn').click();await p.locator('#wizardOverlay').waitFor({state:'visible'});await p.locator('#wizardSkipBtn').click();}await p.locator('#companion-dashboard').waitFor();}
async function select(model){await page.locator('[data-model]').selectOption(model);await page.locator('[data-select]').click();await page.waitForFunction(m=>document.querySelector('[data-selected]').textContent==='Active: '+m,model);}
async function portrait(p,id,expression){await p.waitForFunction(({id,expression})=>{const h=document.querySelector('#character-panel');return h.dataset.character===id&&(!expression||h.dataset.expression===expression)&&!h.querySelector('[data-art-status]').textContent.includes('Loading')&&h.querySelector('img:last-child.visible')?.naturalWidth>0;},{id,expression});}
async function chat(text){await page.locator('[data-text]').fill(text);await page.locator('[data-text]').press('Enter');await page.waitForFunction(()=>document.querySelector('[data-text]').value==='');await page.waitForFunction(()=>document.querySelector('[data-cancel]').hidden||document.querySelector('[data-error]').textContent);assert(!(await page.locator('[data-error]').textContent()),'Chat error: '+await page.locator('[data-error]').textContent());}
async function capture(p,name){await p.waitForFunction(()=>{const h=document.querySelector('#character-panel');const images=h.querySelectorAll('img');return images.length===0||images.length===1&&getComputedStyle(images[0]).opacity==='1';});await p.screenshot({path:path.join(output,name)});report.screenshots.push(name);}
try{
 await mkdir(output,{recursive:true});
 for(const [command,args,env]of [['python3',['tools/serve_local.py',String(uiPort)],{}],[path.join(root,'.venv/bin/python'),['tests/fork/browser_service.py'],{EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(aiPort)}]])children.push(spawn(command,args,{cwd:root,env:{...process.env,...env},stdio:'ignore'}));
 await wait(ui+'/?characterPreview=1');await wait(ai+'/health');browser=await chromium.launch();const context=await browser.newContext({viewport:{width:1920,height:1080}});
 await context.addInitScript(()=>{const no=()=>Promise.reject(new DOMException('Mocked-device test','NotFoundError'));Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:no},configurable:true});Object.defineProperty(navigator,'serial',{value:{requestPort:no,getPorts:async()=>[]},configurable:true});if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=no;});
 await context.route('**/api/handy/v2/**',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(route.request().url().endsWith('/connected')?{connected:true}:route.request().url().endsWith('/info')?{fwVersion:'3.2.3',model:'Handy 1.1'}:{result:0})}));
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().includes('/Character_Art/'))report.art_requests.push(r.url());});
 await boot(page,ui+'/?characterPreview=1');assert(await page.locator('[data-ai-diagnostics]').count()===1,'Development diagnostics absent');
 // Run the original engine with explicit simulator and intercepted mock Handy.
 await page.locator('#cardBle').click();await page.getByRole('button',{name:/manual simulator/i}).click();await page.locator('#modalSimHrSlider').evaluate(el=>{el.value='98';el.dispatchEvent(new Event('input',{bubbles:true}));});await page.locator('#modalEngageSimBtn').click();if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
 await page.locator('#cardHandy').click();await page.locator('#modalHandyInput').fill('F24-MOCK-ONLY');await page.locator('#modalHandyConnectBtn').click();await sleep(600);if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();await page.locator('#sessionPlayPauseBtn').click();
 await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';});
 await page.locator('[data-url]').fill(`ws://127.0.0.1:${aiPort}/observe`);await page.locator('[data-token]').fill('browser-fixture-token-'+'x'.repeat(32));await page.locator('[data-connect]').click();await page.locator('[data-model] option[value="evelyn-lite-v1:latest"]').waitFor({state:'attached'});
 await select('evelyn-lite-v1:latest');await portrait(page,'evelyn','neutral');await capture(page,'evelyn-1920.png');
 const image=await page.locator('#character-panel img').elementHandle(),requests=report.art_requests.length;
 await select('evelyn-lite-candidate:latest');await portrait(page,'evelyn','neutral');assert(await image.evaluate(el=>el===document.querySelector('#character-panel img')),'Same-character model unnecessarily replaced portrait');assert(report.art_requests.length===requests,'Same-character switch reloaded high-resolution art');
 report.steps.push('Exact aliases share identity and retain the same loaded portrait node');
 await chat('portrait playful test');await portrait(page,'evelyn','playful');assert((await page.locator('#character-panel').getAttribute('data-activity'))==='idle','Completed reply left generating active');
 assert(await page.locator('.message-assistant').count()===1,'Duplicate conversation message');
 await chat('portrait flirty tone test');await portrait(page,'evelyn','flirty');report.steps.push('Ordinary conversational tone selects Flirty without facial narration');
 await page.locator('[data-text]').fill('long streaming response');await page.locator('[data-text]').press('Enter');await page.waitForFunction(()=>document.querySelector('#character-panel').dataset.activity==='generating');await portrait(page,'evelyn','mischievous');assert(!(await page.locator('[data-history]').textContent()).includes('[[expression:'),'Metadata leaked during streaming');await capture(page,'expression-streaming.png');await page.locator('[data-cancel]').click();await sleep(600);assert(await page.locator('#character-panel').getAttribute('data-activity')==='idle','Cancelled generation still active');
 await fetch(ai+'/fixture/event-policy/fast',{method:'POST'});
 await page.evaluate(async()=>{const {state}=await import('/src/js/state.js');state.sessionSeconds=299;});
 await page.waitForFunction(()=>document.querySelector('[data-history]').textContent.includes('Five minutes are recorded'),null,{timeout:15000});
 await portrait(page,'evelyn','proud');assert(!(await page.locator('[data-history]').textContent()).includes('[[expression:'),'Event metadata leaked');
 await page.getByText('Runtime diagnostics · development',{exact:true}).click();await capture(page,'verified-event-diagnostics.png');
 report.steps.push('Original simulated elapsed counter crosses milestone; validated event reaches Director and model expression');
 await fetch(ai+'/fixture/event-policy/normal',{method:'POST'});
 await select('daisy-qwen35:latest');await portrait(page,'daisy','neutral');await chat('portrait concerned test');await portrait(page,'daisy','concerned');
 await page.setViewportSize({width:2560,height:1440});await capture(page,'daisy-2560.png');
 await select('evelyn-lite-candidate:latest');await portrait(page,'evelyn','proud');assert((await page.locator('[data-history]').textContent()).includes('cheeky rascal'),'History did not restore');
 report.steps.push('Completed reply tone, cancellation, character switching and model history restoration');
 for(const model of ['celeste-narrative-v1:latest','celeste-narrative-v2:latest']){
  await select(model);await portrait(page,'celeste');
  if(model==='celeste-narrative-v2:latest')assert(!(await page.locator('[data-history]').textContent()).includes('Celeste v1 private note'),'Celeste versions share dialogue');
  assert(await page.locator('[data-name]').textContent()==='Celeste','Celeste identity missing');
  await chat('portrait concerned test');await portrait(page,'celeste','concerned');
  if(model==='celeste-narrative-v1:latest')await chat('Celeste v1 private note');
 }
 await page.setViewportSize({width:1920,height:1080});await capture(page,'celeste-1920.png');
 await page.setViewportSize({width:390,height:844});await page.locator('button[data-view=character]').click();await capture(page,'celeste-390.png');
 assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)),'Celeste mobile overflow');
 assert(await page.locator('[data-emergency]').isVisible(),'Celeste hides emergency stop');
 await page.setViewportSize({width:1920,height:1080});
 report.steps.push('Both Celeste versions select with distinct identity and model-driven expression; desktop/mobile portraits fit');
 await select('nova-narrative-v1:latest');await portrait(page,'nova','neutral');
 assert(!(await page.locator('[data-history]').textContent()).includes('Celeste v1 private note'),'Nova received Celeste history');
 assert(await page.locator('[data-name]').textContent()==='Nova','Nova chat identity missing');
 await chat('portrait concerned test');await portrait(page,'nova','concerned');await capture(page,'nova-1920.png');
 await page.setViewportSize({width:390,height:844});await page.locator('button[data-view=character]').click();await capture(page,'nova-390.png');
 assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)),'Nova mobile overflow');
 assert(await page.locator('[data-emergency]').isVisible(),'Nova hides emergency stop');await page.setViewportSize({width:1920,height:1080});
 report.steps.push('Nova model selection, expression, isolated history and desktop/mobile portrait');
 await select('qwen3:8b');assert(await page.locator('#character-panel').getAttribute('data-character')==='generic','Unknown model borrowed named character');assert(await page.locator('#character-panel img').count()===0,'Unknown model retained another portrait');
 await select('daisy-qwen35:latest');await portrait(page,'daisy','concerned');
 await page.setViewportSize({width:1366,height:768});await page.locator('button[data-view=character]').click();await capture(page,'daisy-1366.png');
 await page.setViewportSize({width:390,height:844});await capture(page,'daisy-390.png');
 assert(await page.locator('[data-emergency]').isVisible(),'Emergency stop hidden by portrait');const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);assert(!overflow,'Mobile overflow');
 await page.locator('[data-emergency]').click();await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='IDLE';});await portrait(page,'daisy','concerned');report.steps.push('Verified stop preserves emotion while original emergency control stops mocked session');
 await page.emulateMedia({reducedMotion:'reduce'});assert(await page.locator('#character-panel img').last().evaluate(el=>getComputedStyle(el).transitionDuration)==='0s','Reduced motion ignored');report.steps.push('Desktop/tablet/mobile artwork, contain scaling, reduced motion and emergency accessibility');
 await page.locator('[data-disconnect]').evaluate(el=>el.click());assert(await page.locator('#character-panel').getAttribute('data-activity')==='disconnected','Disconnect activity missing');await page.waitForFunction(()=>document.querySelectorAll('#character-panel img').length===1);assert(await page.locator('#character-panel img').count()===1,'Disconnect removed artwork');
 // Separate local-only preview: all twelve states without AI/model requests.
 const preview=await context.newPage();preview.on('pageerror',e=>errors.push(e.message));await boot(preview,ui+'/?characterPreview=1',true);await preview.locator('.character-preview summary').click();
 const expressions=await preview.locator('[data-preview-expression] option').evaluateAll(nodes=>nodes.map(n=>n.value));assert(expressions.length===12,'Preview lacks twelve states');
 for(const character of ['evelyn','daisy','celeste','nova']){
  await preview.locator('[data-preview-character]').selectOption(character);
  for(const expression of expressions){await preview.locator('[data-preview-expression]').selectOption(expression);await portrait(preview,character,expression);assert((await preview.locator('#character-panel').getAttribute('data-artwork-status'))==='intended','Unexpected portrait resolution: '+character+'/'+expression);assert((await preview.locator('[data-preview-result]').textContent()).includes('Intended portrait'),'Preview did not label artwork resolution');report.rendered_portraits.push(await preview.locator('#character-panel').evaluate(host=>({character:host.dataset.character,requested:host.dataset.expression,rendered:host.dataset.renderedExpression,status:host.dataset.artworkStatus,source:host.querySelector('img:last-child').getAttribute('src'),width:host.querySelector('img:last-child').naturalWidth,height:host.querySelector('img:last-child').naturalHeight})));const count=await preview.locator('#character-panel img').count();report.max_image_layers=Math.max(report.max_image_layers,count);assert(count<=2,'Unbounded decoded image layers');}
 }
 await preview.locator('[data-preview-character]').selectOption('evelyn');await preview.locator('[data-preview-expression]').selectOption('proud');await portrait(preview,'evelyn','proud');await capture(preview,'evelyn-proud-preview.png');
 await preview.locator('[data-preview-character]').selectOption('daisy');await preview.locator('[data-preview-expression]').selectOption('happy');await portrait(preview,'daisy','happy');await preview.setViewportSize({width:1920,height:1080});await capture(preview,'daisy-happy-1920.png');
 assert(await preview.locator('[data-selected]').textContent()==='No AI model active','Preview changed model selection');
 report.steps.push('All 48 supplied character/expression portraits load directly; no model inference');
 // Force expression failure, neutral fallback, total failure, and stale in-flight identity changes.
 const failures=await preview.evaluate(async()=>{
  const {CharacterPresentation}=await import('/src/js/ai/character.js');const host=document.createElement('aside');document.body.append(host);
  const catalog={models:{'test:tag':'test','other:tag':'other'},characters:{test:{name:'Test',expressions:{neutral:'/Character_Art/Daisy/expressions/daisy_neutral.png',playful:'/src/assets/characters/not-found.webp'}},other:{name:'Other',expressions:{neutral:'/src/assets/characters/no-neutral.webp'}}}};
  const view=new CharacterPresentation(host,catalog);view.setState({model:'test:tag',expression:'playful'});await new Promise(r=>setTimeout(r,1000));
  const fallback=host.dataset.artworkStatus==='fallback'&&host.dataset.renderedExpression==='neutral'&&host.querySelector('img')?.naturalWidth>0&&host.querySelector('[data-art-status]').textContent.includes('Neutral portrait');
  view.setModel('other:tag');await new Promise(r=>setTimeout(r,400));const placeholder=!host.querySelector('.portrait-placeholder').hidden&&host.querySelectorAll('img').length===0;
  view.setModel('test:tag');view.setModel('other:tag');await new Promise(r=>setTimeout(r,600));const stale=host.dataset.character==='other'&&host.querySelectorAll('img').length===0;
  view.destroy();host.remove();return {fallback,placeholder,stale};
 });assert(Object.values(failures).every(Boolean),'Failed image fallback/revision: '+JSON.stringify(failures));report.steps.push('Image error fallback, total failure placeholder and stale image-load fencing');
 await preview.evaluate(async()=>{
  const {CharacterPresentation}=await import('/src/js/ai/character.js');const old=document.querySelector('#character-panel'),host=document.createElement('aside');host.id='character-panel';old.replaceWith(host);
  const catalog={models:{'fallback:tag':'test'},characters:{test:{name:'Fallback preview',expressions:{neutral:'/Character_Art/Evelyn/Expressions/evelyn_neutral.png',proud:'/src/assets/characters/missing.png'}}}};
  const view=new CharacterPresentation(host,catalog);view.setState({model:'fallback:tag',expression:'proud',activity:'idle'});
 });
 await preview.waitForFunction(()=>document.querySelector('#character-panel').dataset.artworkStatus==='fallback');await capture(preview,'missing-artwork-fallback.png');
 assert(errors.length===0,errors.join('\n'));report.passed=true;
}catch(error){report.error=String(error);if(page)await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});process.exitCode=1;}
finally{for(const child of children)child.kill();if(browser)await browser.close();await mkdir(output,{recursive:true});await writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({passed:report.passed,steps:report.steps,error:report.error,output}));}
