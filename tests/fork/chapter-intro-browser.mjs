// SPDX-License-Identifier: AGPL-3.0-only
// Shipped chapter data and real observer persistence, with isolated fixtures and mocked model transport.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,mkdtemp,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {claimPorts,ownedReady,isolatedEnv,guardBrowser} from './fixture-isolation.mjs';
const root=path.resolve(new URL('../..',import.meta.url).pathname),out=process.env.CHAPTER_BROWSER_REPORT||path.join(tmpdir(),'edgeloop-chapter-browser');
const uiPort=Number(process.env.EDGELOOP_CHAPTER_UI_PORT||8902),aiPort=Number(process.env.EDGELOOP_CHAPTER_AI_PORT||8908);
const ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`,children=[],report={passed:false,physical_hardware:false,steps:[],screenshots:[]};
const assert=(x,m)=>{if(!x)throw Error(m);};
let browser,page;
const shot=async name=>{await page.screenshot({path:path.join(out,name)});report.screenshots.push(name);};
try{
    await mkdir(out,{recursive:true});await claimPorts(uiPort,aiPort);
    const data=await mkdtemp(path.join(tmpdir(),'edgeloop-chapter-data-'));
    const env=isolatedEnv({PYTHONPATH:root,EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(aiPort),EDGELOOP_CAMPAIGN_FIXTURE_DATA:data});
    children.push(spawn('python3',['tools/serve_local.py',String(uiPort)],{cwd:root,stdio:'ignore',env}));
    children.push(spawn(path.join(root,'.venv/bin/python'),['-m','tests.fork.campaign_browser_service'],{cwd:root,stdio:'ignore',env}));
    await ownedReady(ui,children);await ownedReady(ai+'/health',children);
    browser=guardBrowser(await chromium.launch(),[uiPort,aiPort]);
    const context=await browser.newContext({viewport:{width:1440,height:960},serviceWorkers:'block',reducedMotion:'reduce'});
    await context.addInitScript(()=>{window.fixturePad={index:0,buttons:Array.from({length:16},()=>({pressed:false,value:0}))};Object.defineProperty(navigator,'getGamepads',{value:()=>[window.fixturePad]});});
    page=await context.newPage();const sent=[],errors=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('websocket',ws=>ws.on('framesent',f=>{try{sent.push(JSON.parse(f.payload));}catch{}}));
    // The board re-renders when the save is acknowledged, so compare against whichever heading is current.
    const focusHeading=async message=>{try{await page.waitForFunction(()=>document.activeElement?.matches?.('[data-board-heading]'),null,{timeout:5000});}
        catch{throw Error(message+': '+await page.evaluate(()=>document.activeElement?.outerHTML.slice(0,120)));}};
    const commands=action=>sent.filter(m=>m.type==='campaign'&&m.action===action);
    const connect=async()=>{
        // The age gate and setup wizard appear a moment after load on a fresh profile only; wait briefly for each.
        const dismiss=async sel=>{try{await page.locator(sel).click({timeout:5000});}catch{}};
        await dismiss('#ageConfirmBtn');await dismiss('#wizardSkipBtn');
        await page.locator('[data-menu-tile=freeplay]').click();
        if(await page.locator('[data-connect]').isVisible()){
            await page.locator('[data-url]').fill(ai.replace('http:','ws:')+'/observe');await page.locator('[data-token]').fill('browser-fixture-token-'+'x'.repeat(32));await page.locator('[data-connect]').click();
        }
        await page.waitForFunction(()=>document.querySelector('[data-model] option[value="nova-narrative-v1:latest"]'));
    };
    const openHelix=async()=>{
        await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').click();
        await page.waitForFunction(()=>document.querySelector('[data-campaign=rise_of_helix]')?.getAttribute('aria-disabled')===null);
        await page.locator('[data-campaign=rise_of_helix]').click();
    };
    const view=target=>page.waitForFunction(v=>document.querySelector('#main-menu')?.dataset.view===v,target);
    await page.goto(ui);await connect();
    // The fixture's sentinel misses every mission id, seeding all Asterion completions and rewards.
    const seed=await fetch(ai+'/fixture/campaign/progress',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({campaign:'asterion_initiative',mission:'__all__'})});assert(seed.ok,'Completion seed');
    await openHelix();await view('scene');
    assert(await page.locator('.scene-text [data-state=placeholder]').count()===1,'Intro placeholder badge');
    assert(await page.locator('.scene-position').textContent()==='1 / 2','Expected two-block intro');
    assert(await page.locator('#main-menu').getByRole('button',{name:'Next',exact:true}).evaluate(e=>e===document.activeElement),'Scene focus');
    await page.waitForFunction(()=>document.querySelector('.scene-art')?.naturalWidth>0);await shot('chapter-intro-first.png');
    // A is unbound in the default bindings and advances the scene; bound actions remain owned by app.js.
    await page.evaluate(()=>{window.fixturePad.buttons[0]={pressed:true,value:1};});
    await page.waitForFunction(()=>document.querySelector('.scene-position')?.textContent==='2 / 2');
    await page.evaluate(()=>{window.fixturePad.buttons[0]={pressed:false,value:0};});
    await page.keyboard.press('Escape');await view('missions');
    await focusHeading('Auto intro did not return focus to board heading: ');
    let persisted=false;
    for(let i=0;i<40;i++){
        const snapshot=await (await fetch(ai+'/fixture/campaign')).json();
        if(snapshot.saved&&JSON.parse(snapshot.saved).campaigns.rise_of_helix?.intros_seen?.undercover){persisted=true;break;}
        await page.waitForTimeout(50);
    }
    assert(persisted&&commands('intro_seen').length===1,'Intro seen was not saved exactly once');
    await focusHeading('Save acknowledgement stole board focus');
    report.steps.push('Unlocked Helix auto-plays its placeholder intro; unbound A advances and Escape saves once');
    await page.reload();await connect();const beforeReloadBoard=commands('chapter_text').length;
    await openHelix();await view('missions');await page.waitForTimeout(150);
    assert(commands('chapter_text').length===beforeReloadBoard,'Reload auto-replayed a seen intro');
    report.steps.push('Persisted intro_seen survives reload without another automatic request');
    const beforeReplaySeen=commands('intro_seen').length;
    await page.getByRole('button',{name:'Play intro',exact:true}).click();await view('scene');
    await page.locator('#main-menu').getByRole('button',{name:'Skip',exact:true}).click();await view('missions');
    assert(await page.getByRole('button',{name:'Play intro',exact:true}).evaluate(e=>e===document.activeElement),'Replay focus did not return to Play intro');
    assert(commands('intro_seen').length===beforeReplaySeen,'Replay marked intro seen again');
    report.steps.push('Play intro fetches a replay; Skip returns focus without another intro_seen');
    await page.setViewportSize({width:390,height:844});
    const fits=()=>page.evaluate(()=>{const menu=document.querySelector('#main-menu');return menu.scrollWidth<=menu.clientWidth;});
    assert(await fits(),'Board overflow at 390px');
    await page.getByRole('button',{name:'Play intro',exact:true}).click();await view('scene');await page.waitForFunction(()=>document.querySelector('.scene-art')?.naturalWidth>0);
    assert(await fits(),'Intro overflow at 390px');await shot('chapter-intro-phone.png');
    await page.locator('#main-menu').getByRole('button',{name:'Skip',exact:true}).click();await view('missions');
    report.steps.push('Board and intro have no horizontal overflow at 390×844');
    await page.locator('.board-hero .game-menu-back').click();await page.locator('[data-campaign=asterion_initiative]').click();await view('missions');
    await page.getByRole('button',{name:'Play chapter close',exact:true}).click();await view('scene');
    assert(await page.locator('.scene-position').textContent()==='1 / 1','Chapter close must play only its close block');
    await page.locator('#main-menu').getByRole('button',{name:'Next',exact:true}).click();await view('missions');
    assert(await page.getByRole('button',{name:'Play chapter close',exact:true}).evaluate(e=>e===document.activeElement),'Close replay focus');
    assert(commands('intro_seen').length===beforeReplaySeen,'Chapter close marked an intro seen');await shot('chapter-close-board.png');
    report.steps.push('Completed chapter close replays from its board control without marking an intro');
    assert(errors.length===0,'Page errors: '+errors.join(' | '));report.passed=true;
}catch(error){report.error=String(error?.stack||error);try{await shot('chapter-failure.png');}catch{}}
finally{await browser?.close();for(const p of children)p.kill('SIGTERM');await writeFile(path.join(out,'chapter-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));process.exitCode=report.passed?0:1;}
