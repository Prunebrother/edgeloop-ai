// SPDX-License-Identifier: AGPL-3.0-only
// Route groups, real campaign completion and replay saves, with isolated synthetic device evidence.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,mkdtemp,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {claimPorts,ownedReady,isolatedEnv,guardBrowser} from './fixture-isolation.mjs';
const root=path.resolve(new URL('../..',import.meta.url).pathname),out=process.env.ROUTE_BROWSER_REPORT||path.join(tmpdir(),'edgeloop-route-browser');
const uiPort=Number(process.env.EDGELOOP_ROUTE_UI_PORT||8912),aiPort=Number(process.env.EDGELOOP_ROUTE_AI_PORT||8918);
const ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`,children=[],report={passed:false,physical_hardware:false,steps:[],screenshots:[]};
const assert=(x,m)=>{if(!x)throw Error(m);};
let browser,page;
try{
    await mkdir(out,{recursive:true});await claimPorts(uiPort,aiPort);
    const data=await mkdtemp(path.join(tmpdir(),'edgeloop-route-data-'));
    const env=isolatedEnv({PYTHONPATH:root,EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(aiPort),EDGELOOP_CAMPAIGN_FIXTURE_DATA:data,EDGELOOP_ROUTE_FIXTURE:'1'});
    children.push(spawn('python3',['tools/serve_local.py',String(uiPort)],{cwd:root,stdio:'ignore',env}));
    children.push(spawn(path.join(root,'.venv/bin/python'),['-m','tests.fork.campaign_browser_service'],{cwd:root,stdio:'ignore',env}));
    await ownedReady(ui,children);await ownedReady(ai+'/health',children);
    browser=guardBrowser(await chromium.launch(),[uiPort,aiPort]);
    const context=await browser.newContext({viewport:{width:1440,height:960},serviceWorkers:'block',reducedMotion:'reduce'});
    await context.addInitScript(()=>{window.fixturePad={index:0,buttons:Array.from({length:16},()=>({pressed:false,value:0}))};Object.defineProperty(navigator,'getGamepads',{value:()=>[window.fixturePad]});});
    page=await context.newPage();const sent=[],errors=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('websocket',ws=>ws.on('framesent',f=>{try{sent.push(JSON.parse(f.payload));}catch{}}));
    await page.goto(ui);
    const dismiss=async selector=>{try{await page.locator(selector).click({timeout:5000});}catch{}};
    await dismiss('#ageConfirmBtn');await dismiss('#wizardSkipBtn');await page.locator('[data-menu-tile=freeplay]').click();
    await page.locator('[data-url]').fill(ai.replace('http:','ws:')+'/observe');await page.locator('[data-token]').fill('browser-fixture-token-'+'x'.repeat(32));await page.locator('[data-connect]').click();
    await page.waitForFunction(()=>document.querySelector('[data-model] option[value="nova-narrative-v1:latest"]'));
    await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').click();await page.locator('[data-campaign=fixture_when]').click();
    const missionStart=async label=>{
        await page.locator('.mission-detail').getByRole('button',{name:label,exact:true}).click();
        await page.getByRole('button',{name:'Begin with Nova',exact:true}).click();
        await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.includes('nova-narrative-v1:latest'));
    };
    await missionStart('Start mission');
    const tick=(run,seconds,edges=0,orgasms=0)=>({session_id:`5e3d0c3a-0000-4000-8000-${String(run).padStart(12,'0')}`,status:'RUNNING',seconds,experience:'classic',intensity:100,edges,active_mode:'classic',goal:'tease',devices:{hr_ready:true,ble:true,simulated_hr:false,toy_ready:true},details:{orgasm_count:orgasms,captured_at_ms:1793000000000+seconds*1000}});
    const evidence=async report=>{const response=await fetch(ai+'/fixture/campaign/evidence',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({report})});assert(response.ok,'Fixture evidence');};
    const selected=()=>page.waitForFunction(()=>document.querySelector('[data-route=escape] [data-choice-objective=cover]')?.textContent.includes('Chosen:'));
    const done=id=>page.waitForFunction(route=>document.querySelector('#main-menu')?.dataset.view==='results'&&document.querySelector('[data-completion-route]')?.dataset.completionRoute===route,id);
    const replay=async()=>{await page.locator('#main-menu').getByRole('button',{name:'Campaign',exact:true}).click();await missionStart('Replay');};
    await evidence(tick(1,0));await page.locator('[data-route=escape]').waitFor();
    assert(await page.locator('.mission-route').count()===2,'Expected two route groups');
    assert((await page.locator('[data-route=escape]').textContent()).includes('Cover'),'Missing escape objectives');
    assert((await page.locator('[data-route=release]').textContent()).includes('Evidence target'),'Missing release objective');
    assert(!(await page.locator('[data-route=escape]').textContent()).includes('Common check'),'Common goal duplicated into route');
    report.steps.push('Common objectives precede two labelled route groups with their own controls');
    await page.setViewportSize({width:390,height:844});
    assert(await page.locator('.mission-banner').evaluate(e=>e.scrollWidth<=e.clientWidth),'Route banner overflow at 390px');
    await page.screenshot({path:path.join(out,'routes-phone.png')});report.screenshots.push('routes-phone.png');
    await page.locator('[data-route=escape] [data-choice-option=analyst]').focus();await page.keyboard.press('Space');await selected();
    await evidence(tick(1,1,2));await done('escape');report.steps.push('Space selects a choice and the escape route completes');
    await replay();await evidence(tick(2,0));
    // The answer buttons enable once the browser has the session start; wait for that instead of racing it.
    await page.waitForFunction(()=>document.querySelector('[data-route=escape] [data-choice-option=volunteer]')?.matches(':enabled'));
    await page.locator('[data-route=escape] [data-choice-option=volunteer]').focus();
    // A progress update rebuilds the banner; the focused answer must stay focused for the controller.
    await page.evaluate(()=>{window.__rebuilt=false;new MutationObserver(()=>{window.__rebuilt=true;}).observe(document.querySelector(".mission-banner"),{childList:true});});
    await evidence(tick(2,1,1));await page.waitForFunction(()=>window.__rebuilt);
    assert(await page.evaluate(()=>document.activeElement?.dataset?.choiceOption)==='volunteer','Banner rebuild dropped choice focus');
    await page.evaluate(()=>{window.fixturePad.buttons[0]={pressed:true,value:1};});await selected();
    await page.evaluate(()=>{window.fixturePad.buttons[0]={pressed:false,value:0};});
    await evidence(tick(2,2,2));await done('escape');report.steps.push('Unbound gamepad A answers inside a route group');
    await replay();await evidence(tick(3,0));await evidence(tick(3,1,1,1));await done('release');
    const saved=JSON.parse((await (await fetch(ai+'/fixture/campaign')).json()).saved).campaigns.fixture_when;
    assert(saved.routes.intake==='release'&&saved.flags.route==='escape'&&saved.flags.cover==='analyst','Replay rewound first-completion flags');
    assert(!sent.some(m=>m.type==='session'||m.action==='session_start'),'Input reached engine shortcut');
    assert(await page.evaluate(async()=>(await import('/src/js/state.js')).state.sessionStatus)==='IDLE','Route input started engine session');
    assert(errors.length===0,'Page errors: '+errors.join(' | '));
    report.steps.push('The other route completes on replay, updates its record, and preserves saved story flags');report.passed=true;
}catch(error){report.error=String(error?.stack||error);}
finally{await browser?.close();for(const p of children)p.kill('SIGTERM');await writeFile(path.join(out,'route-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));process.exitCode=report.passed?0:1;}
