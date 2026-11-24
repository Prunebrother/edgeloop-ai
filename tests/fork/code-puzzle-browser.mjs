// SPDX-License-Identifier: AGPL-3.0-only
// The real banner and observer with fixture-only code puzzles, hardware evidence and model transport.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,mkdtemp,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {claimPorts,ownedReady,isolatedEnv,guardBrowser} from './fixture-isolation.mjs';
const root=path.resolve(new URL('../..',import.meta.url).pathname),out=process.env.CODE_PUZZLE_BROWSER_REPORT||path.join(tmpdir(),'edgeloop-code-puzzle-browser');
const uiPort=Number(process.env.EDGELOOP_CODE_UI_PORT||8892),aiPort=Number(process.env.EDGELOOP_CODE_AI_PORT||8898);
const ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`,children=[],report={passed:false,physical_hardware:false,steps:[]};
const assert=(x,m)=>{if(!x)throw Error(m);};
let browser,page;
try{
    await mkdir(out,{recursive:true});await claimPorts(uiPort,aiPort);
    const data=await mkdtemp(path.join(tmpdir(),'edgeloop-code-data-'));
    const env=isolatedEnv({PYTHONPATH:root,EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(aiPort),EDGELOOP_CAMPAIGN_FIXTURE_DATA:data,EDGELOOP_CODE_PUZZLE_FIXTURE:'1'});
    children.push(spawn('python3',['tools/serve_local.py',String(uiPort)],{cwd:root,stdio:'ignore',env}));
    children.push(spawn(path.join(root,'.venv/bin/python'),['-m','tests.fork.campaign_browser_service'],{cwd:root,stdio:'ignore',env}));
    await ownedReady(ui,children);await ownedReady(ai+'/health',children);
    browser=guardBrowser(await chromium.launch(),[uiPort,aiPort]);
    const context=await browser.newContext({viewport:{width:1280,height:900},serviceWorkers:'block'});
    await context.addInitScript(()=>{window.fixturePad={index:0,buttons:Array.from({length:16},()=>({pressed:false,value:0}))};Object.defineProperty(navigator,'getGamepads',{value:()=>[window.fixturePad]});});
    page=await context.newPage();const incoming=[],errors=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('websocket',ws=>ws.on('framereceived',f=>incoming.push(String(f.payload))));
    await page.goto(ui);await page.locator('#ageConfirmBtn').click();await page.locator('#wizardSkipBtn').click();await page.locator('[data-menu-tile=freeplay]').click();
    await page.locator('[data-url]').fill(ai.replace('http:','ws:')+'/observe');await page.locator('[data-token]').fill('browser-fixture-token-'+'x'.repeat(32));await page.locator('[data-connect]').click();
    await page.waitForFunction(()=>document.querySelector('[data-model] option[value="nova-narrative-v1:latest"]'));
    await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').click();await page.locator('[data-campaign=fixture_choice]').click();await page.locator('.mission-detail').getByRole('button',{name:'Start mission'}).click();
    await page.getByRole('button',{name:'Begin with Nova'}).click();await page.locator('#main-menu').waitFor({state:'hidden'});
    const evidence=async reports=>{const r=await fetch(ai+'/fixture/campaign/evidence',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({reports})});assert(r.ok,'Evidence fixture');};
    const tick=(seconds,intensity=70,edges=0)=>({session_id:'5e3d0c3a-0000-4000-8000-00000000c011',status:'RUNNING',seconds,experience:'classic',intensity,edges,active_mode:'classic',goal:'tease',devices:{hr_ready:true,ble:true,simulated_hr:false,toy_ready:true},details:{orgasm_count:0,captured_at_ms:1793000000000+seconds*1000}});
    await evidence([tick(0)]);const input=page.getByLabel('Code for Vault',{exact:true});await input.waitFor();
    assert(await input.getAttribute('maxlength')==='12','Code maxlength');
    assert(!(await page.locator('.mission-puzzle').textContent()).includes('Compliance clue'),'Hidden clue leaked');
    assert((await page.locator('.mission-code-form').textContent()).includes('Use the keyboard to enter the code.'),'Missing gamepad note');
    // A is unbound: its only effect here is to focus the code input.
    await page.getByRole('button',{name:'Submit',exact:true}).focus();
    await page.evaluate(()=>{window.fixturePad.buttons[0]={pressed:true,value:1};});await page.waitForTimeout(75);
    await page.evaluate(()=>{window.fixturePad.buttons[0]={pressed:false,value:0};});
    assert(await input.evaluate(e=>e===document.activeElement),'Unbound A did not focus input');
    await page.evaluate(()=>{window.bannerKeys=[];document.addEventListener('keydown',e=>window.bannerKeys.push(e.code));});
    await input.press('c');await input.press('Space');await input.press('a');
    assert(await input.inputValue()==='c a','Space did not type normally');
    await input.press('Enter');await page.waitForFunction(()=>document.querySelector('.mission-puzzle .mission-note[role=status]')?.textContent.includes('Not quite.'));
    assert(await input.inputValue()==='c a','Wrong submission was not retained');
    assert(await input.evaluate(e=>e===document.activeElement&&e.selectionStart===0&&e.selectionEnd===e.value.length),'Wrong submission was not selected');
    assert((await page.evaluate(()=>window.bannerKeys)).length===0,'Input key reached document shortcuts');
    assert(await page.evaluate(async()=>(await import('/src/js/state.js')).state.sessionStatus)==='IDLE','Typing C/Space/Enter triggered the engine');
    assert(await page.locator('.mission-stages [role=status]').count()===0,'Answer did not acknowledge initial clues');
    report.steps.push('Code entry isolates C, Space and Enter; wrong code shows hint, retaining selected text');
    await input.evaluate(e=>e.setSelectionRange(1,1));await evidence([tick(5),tick(10)]);
    await page.waitForFunction(()=>document.querySelector('.mission-puzzle').textContent.includes('Compliance clue'));
    assert((await page.locator('.mission-stages [role=status]').allTextContents()).includes('New clue'),'New clue marker');
    assert(await input.inputValue()==='c a'&&await input.evaluate(e=>e===document.activeElement&&e.selectionStart===1&&e.selectionEnd===1),'Progress redraw lost draft or caret');
    report.steps.push('Progressive clue arrives after Compliance and preserves the active input');
    await page.locator('[data-choice-option=analyst]').click();await page.waitForFunction(()=>document.querySelector('.mission-choice').textContent.includes('Chosen:'));
    await evidence([tick(11,90,2),tick(16,90,2),tick(21,90,2)]);
    await page.waitForFunction(()=>document.querySelector('.mission-puzzle').textContent.includes('Goal clue'));
    await input.fill(' Ｈｅｌｉｘ　７ ');await input.press('Enter');
    await page.waitForFunction(()=>document.querySelector('#main-menu')?.dataset.view==='results');
    const saved=JSON.parse((await (await fetch(ai+'/fixture/campaign')).json()).saved);
    assert(saved.campaigns.fixture_choice.missions.intake.completions===1,'Correct normalised code did not complete mission');
    assert(!incoming.some(m=>m.includes('Helix 7')||m.includes('answer_code')),'Secret code leaked in an observer message');
    assert(errors.length===0,'Page errors: '+errors.join(' | '));
    report.steps.push('NFKC/casefold answer completes; incoming WebSocket messages contain no secret');report.passed=true;
}catch(error){report.error=String(error?.stack||error);}
finally{await browser?.close();for(const p of children)p.kill('SIGTERM');await writeFile(path.join(out,'code-puzzle-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));process.exitCode=report.passed?0:1;}
