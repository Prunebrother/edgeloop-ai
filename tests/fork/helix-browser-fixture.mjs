// SPDX-License-Identifier: AGPL-3.0-only
// Shared test harness: owned loopback fixtures, synthetic hardware, captured messages and explicit defect skips.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,mkdtemp,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {claimPorts,ownedReady,isolatedEnv,guardBrowser} from './fixture-isolation.mjs';
export const assert=(value,message)=>{if(!value){const error=Error(message);error.name='AssertionError';throw error;}};
export const until=async(check,message,ms=5000)=>{const end=Date.now()+ms;do{if(await check())return;await new Promise(r=>setTimeout(r,50));}while(Date.now()<end);assert(false,message);};
export async function suite({name,uiPort,aiPort,env:extra={}},run){
    const root=path.resolve(new URL('../..',import.meta.url).pathname),out=process.env.HELIX_BROWSER_REPORT?path.join(process.env.HELIX_BROWSER_REPORT,name):path.join(tmpdir(),'edgeloop-'+name);
    const ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`,children=[],sent=[],received=[],errors=[];
    const report={passed:false,physical_hardware:false,steps:[],skipped:[],screenshots:[]};let browser;
    try{
        await mkdir(out,{recursive:true});await claimPorts(uiPort,aiPort);
        const data=await mkdtemp(path.join(tmpdir(),name+'-'));
        const env=isolatedEnv({PYTHONPATH:root,EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(aiPort),EDGELOOP_CAMPAIGN_FIXTURE_DATA:data,...extra});
        children.push(spawn('python3',['tools/serve_local.py',String(uiPort)],{cwd:root,stdio:'ignore',env}));
        children.push(spawn(path.join(root,'.venv/bin/python'),['-m','tests.fork.helix_browser_service'],{cwd:root,stdio:'ignore',env}));
        await ownedReady(ui,children);await ownedReady(ai+'/health',children);
        browser=guardBrowser(await chromium.launch(),[uiPort,aiPort]);
        const context=await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block',reducedMotion:'reduce'});
        await context.addInitScript(()=>{
            const no=()=>Promise.reject(new DOMException('No physical hardware','NotFoundError'));
            Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:no},configurable:true});Object.defineProperty(navigator,'serial',{value:{requestPort:no,getPorts:async()=>[]},configurable:true});
            window.fixturePad={index:0,buttons:Array.from({length:16},()=>({pressed:false,value:0}))};Object.defineProperty(navigator,'getGamepads',{value:()=>[window.fixturePad]});
        });
        const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
        page.on('websocket',ws=>{for(const [event,list] of [['framesent',sent],['framereceived',received]])ws.on(event,f=>{try{list.push(JSON.parse(f.payload));}catch{}});});
        await page.route('**/api/handy/v2/**',route=>{const p=new URL(route.request().url()).pathname;return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(p.endsWith('/connected')?{connected:true}:p.endsWith('/info')?{fwVersion:'3.2.3',model:'Handy 1.1'}:{result:0})});});
        const call=async(endpoint,body)=>{const response=await fetch(ai+endpoint,body===undefined?{}:{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});assert(response.ok,'Fixture failed: '+endpoint);return response.json();};
        const engine=()=>page.evaluate(async()=>{const {state}=await import('/src/js/state.js');return {status:state.sessionStatus,intensity:state.intensityValue,percent:state.intensityValue+50};});
        const view=target=>page.waitForFunction(v=>document.querySelector('#main-menu')?.dataset.view===v,target);
        const shot=async file=>{const target=path.join(out,file);await page.screenshot({path:target});report.screenshots.push(target);};
        const defect=async(name,test)=>{try{await test();report.steps.push(name);}catch(error){if(!['AssertionError','TimeoutError'].includes(error.name))throw error;report.skipped.push({name,reason:'DEFECT: '+String(error.message||error)});}};
        const connect=async()=>{
            const dismiss=async selector=>{try{await page.locator(selector).click({timeout:5000});}catch{}};
            await dismiss('#ageConfirmBtn');await dismiss('#wizardSkipBtn');await page.locator('[data-menu-tile=freeplay]').click();
            await page.locator('[data-url]').fill(ai.replace('http:','ws:')+'/observe');await page.locator('[data-token]').fill('browser-fixture-token-'+'x'.repeat(32));
            await page.locator('[data-connect]').click();await page.waitForFunction(()=>document.querySelector('[data-model] option[value="nova-narrative-v1:latest"]'));
        };
        const hardware=async()=>{
            await page.locator('#cardBle').click();await page.getByRole('button',{name:/manual simulator/i}).click();
            await page.locator('#modalSimHrSlider').evaluate(el=>{el.value='90';el.dispatchEvent(new Event('input',{bubbles:true}));});await page.locator('#modalEngageSimBtn').click();
            if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
            await page.locator('#cardHandy').click();await page.locator('#modalHandyInput').fill('FIXTURE-ONLY');await page.locator('#modalHandyConnectBtn').click();
            await page.waitForTimeout(900);if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
            await page.waitForFunction(()=>!document.querySelector('#sessionPlayPauseBtn').disabled);
        };
        const openCampaign=async cid=>{await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').click();await page.locator(`[data-campaign="${cid}"]`).click();await view('missions');};
        const start=async id=>{await page.locator(`.mission-card[data-mission="${id}"] button`).click();await page.locator('.mission-detail').getByRole('button',{name:'Start mission',exact:true}).click();await view('briefing');};
        const begin=async()=>{const state=received.findLast(m=>m.type==='campaign_state'&&m.active),active=state?.active;const companion=state?.campaigns.find(c=>c.id===active.campaign)?.missions.find(m=>m.id===active.mission)?.companion;await page.locator('#main-menu').getByRole('button',{name:/^Begin with /}).click();await page.locator('#main-menu').waitFor({state:'hidden'});if(companion)await page.waitForFunction(id=>document.querySelector('[data-selected]')?.textContent.toLowerCase().includes(id),companion);};
        const snapshot=async()=>{await until(()=>sent.some(m=>m.type==='observation'&&m.snapshot?.status==='RUNNING'),'Missing running browser snapshot');return structuredClone(sent.findLast(m=>m.type==='observation'&&m.snapshot?.status==='RUNNING').snapshot);};
        const startEngine=async()=>{const before=sent.length;await page.locator('#sessionPlayPauseBtn').click();await page.waitForFunction(async()=>(await import('/src/js/state.js')).state.sessionStatus==='RUNNING');await until(()=>sent.slice(before).some(m=>m.type==='observation'&&m.snapshot?.status==='RUNNING'),'Missing new session telemetry');const observation=sent.findLast(m=>m.type==='observation'&&m.snapshot?.status==='RUNNING');await until(()=>received.some(m=>m.type==='observation_ack'&&m.accepted&&m.sequence===observation.sequence&&m.session_id===observation.snapshot.session_id),'Running telemetry not acknowledged');return snapshot();};
        const pad=async(button,check)=>{await page.evaluate(b=>{window.fixturePad.buttons[b]={pressed:true,value:1};},button);try{if(check)await check();else await page.waitForTimeout(150);}finally{await page.evaluate(b=>{window.fixturePad.buttons[b]={pressed:false,value:0};},button);}};
        await page.goto(ui);await connect();
        await run({page,report,call,engine,view,shot,defect,hardware,openCampaign,start,begin,snapshot,startEngine,pad,sent,received,errors,connect,ui,ai});
        assert(errors.length===0,'Page errors: '+errors.join(' | '));report.passed=true;
    }catch(error){report.error=String(error.stack||error);}
    finally{await browser?.close();for(const child of children)child.kill('SIGTERM');await writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));process.exitCode=report.passed?0:1;}
}
