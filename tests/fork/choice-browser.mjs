// SPDX-License-Identifier: AGPL-3.0-only
// Fixture-only mission data, real observer answer routing, synthetic evidence and gamepad.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,mkdtemp,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {claimPorts,ownedReady,isolatedEnv,guardBrowser} from './fixture-isolation.mjs';
const root=path.resolve(new URL('../..',import.meta.url).pathname),out=process.env.CHOICE_BROWSER_REPORT||path.join(tmpdir(),'edgeloop-choice-browser');
const uiPort=Number(process.env.EDGELOOP_CHOICE_UI_PORT||8882),aiPort=Number(process.env.EDGELOOP_CHOICE_AI_PORT||8888);
const ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`,children=[],report={passed:false,steps:[]};
const assert=(x,m)=>{if(!x)throw Error(m);};
let browser,page;
try{
    await mkdir(out,{recursive:true});await claimPorts(uiPort,aiPort);
    const data=await mkdtemp(path.join(tmpdir(),'edgeloop-choice-data-'));
    const env=isolatedEnv({PYTHONPATH:root,EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(aiPort),EDGELOOP_CAMPAIGN_FIXTURE_DATA:data,EDGELOOP_CHOICE_FIXTURE:'1'});
    children.push(spawn('python3',['tools/serve_local.py',String(uiPort)],{cwd:root,stdio:'ignore',env}));
    children.push(spawn(path.join(root,'.venv/bin/python'),['-m','tests.fork.campaign_browser_service'],{cwd:root,stdio:'ignore',env}));
    await ownedReady(ui,children);await ownedReady(ai+'/health',children);
    browser=guardBrowser(await chromium.launch(),[uiPort,aiPort]);
    const context=await browser.newContext({viewport:{width:1280,height:900},serviceWorkers:'block'});
    await context.addInitScript(()=>{window.fixturePad={index:0,buttons:Array.from({length:16},()=>({pressed:false,value:0}))};Object.defineProperty(navigator,'getGamepads',{value:()=>[window.fixturePad]});});
    page=await context.newPage();const sent=[],errors=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('websocket',ws=>ws.on('framesent',f=>{try{sent.push(JSON.parse(f.payload));}catch{}}));
    await page.goto(ui);await page.locator('#ageConfirmBtn').click();await page.locator('#wizardSkipBtn').click();await page.locator('[data-menu-tile=freeplay]').click();
    await page.locator('[data-url]').fill(ai.replace('http:','ws:')+'/observe');await page.locator('[data-token]').fill('browser-fixture-token-'+'x'.repeat(32));await page.locator('[data-connect]').click();
    await page.waitForFunction(()=>document.querySelector('[data-model] option[value="nova-narrative-v1:latest"]'));
    await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').click();await page.locator('[data-campaign=fixture_choice]').click();await page.locator('.mission-detail').getByRole('button',{name:'Start mission'}).click();
    await page.getByRole('button',{name:'Begin with Nova'}).click();
    const evidence=async reports=>{const r=await fetch(ai+'/fixture/campaign/evidence',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({reports})});assert(r.ok,'Evidence fixture');};
    const tick=seconds=>({session_id:'5e3d0c3a-0000-4000-8000-00000000c010',status:'RUNNING',seconds,experience:'classic',intensity:70,edges:0,active_mode:'classic',goal:'tease',devices:{hr_ready:true,ble:true,simulated_hr:false,toy_ready:true},details:{orgasm_count:0,captured_at_ms:1793000000000+seconds*1000}});
    const row=id=>page.locator(`[data-choice-objective=${id}]`);
    const option=(id,pick)=>row(id).locator(`[data-choice-option=${pick}]`);
    await evidence([tick(0)]);await row('cover').waitFor();
    assert(await option('cover','analyst').isDisabled(),'Locked choice enabled');await page.waitForFunction(()=>document.querySelector('[data-choice-objective=cover]')?.textContent.includes('Available during Compliance'),null,{timeout:5000}).catch(()=>{throw Error('Missing stage lock reason');});
    report.steps.push('Choice visible but locked before Compliance');
    await evidence([tick(5),tick(10)]);await page.waitForFunction(()=>!document.querySelector('[data-choice-option=analyst]').disabled);
    await option('cover','analyst').focus();await page.keyboard.press('ArrowRight');assert(await option('cover','volunteer').evaluate(e=>e===document.activeElement),'Choice arrow navigation');
    await page.keyboard.press('Enter');await page.waitForFunction(()=>document.querySelector('[data-choice-objective=cover]').textContent.includes('Chosen: I volunteered'));
    assert((await (await fetch(ai+'/fixture/campaign')).json()).saved.includes('volunteer'),'Choice not saved immediately');report.steps.push('Keyboard choice answered and label shown');
    await option('cover_space','analyst').focus();await page.keyboard.press('Space');
    await page.waitForFunction(()=>document.querySelector('[data-choice-objective=cover_space]').textContent.includes('Chosen: I am an analyst'));
    report.steps.push('Space answers without reaching engine shortcuts');
    await option('cover_pad','analyst').focus();
    const pad=async button=>{
        await page.evaluate(b=>{window.fixturePad.buttons[b]={pressed:true,value:1};},button);
        await page.waitForTimeout(75);
        await page.evaluate(b=>{window.fixturePad.buttons[b]={pressed:false,value:0};},button);
        await page.waitForTimeout(75);
    };
    await pad(15);assert(await option('cover_pad','volunteer').evaluate(e=>e===document.activeElement),'Gamepad D-pad focus');
    await pad(0);await page.waitForFunction(()=>document.querySelector('[data-choice-objective=cover_pad]').textContent.includes('Chosen: I volunteered'));
    report.steps.push('Gamepad D-pad and A answer the choice');
    assert(!sent.some(m=>m.type==='session'||m.action==='session_start'),'Engine shortcut message');
    assert(await page.evaluate(async()=>(await import('/src/js/state.js')).state.sessionStatus)==='IDLE','Choice input started engine session');
    assert(errors.length===0,'Page errors: '+errors.join(' | '));
    await page.screenshot({path:path.join(out,'choice-selected.png')});report.passed=true;
}catch(error){report.error=String(error?.stack||error);}
finally{await browser?.close();for(const p of children)p.kill('SIGTERM');await writeFile(path.join(out,'choice-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));process.exitCode=report.passed?0:1;}
