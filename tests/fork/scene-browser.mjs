// SPDX-License-Identifier: AGPL-3.0-only
// Scene playback against the real menu/observer; test-only art and synthetic hardware evidence.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,mkdtemp,readFile,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {claimPorts,ownedReady,isolatedEnv,guardBrowser} from './fixture-isolation.mjs';
const root=path.resolve(new URL('../..',import.meta.url).pathname);
const out=process.env.SCENE_BROWSER_REPORT||path.join(tmpdir(),'edgeloop-scene-browser');
const uiPort=Number(process.env.EDGELOOP_SCENE_UI_PORT||8872),aiPort=Number(process.env.EDGELOOP_SCENE_AI_PORT||8878);
const ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`,children=[];
const report={passed:false,physical_hardware:false,steps:[],screenshots:[]},errors=[],sent=[];
const assert=(x,m)=>{if(!x)throw Error(m);};
const step=async(name,fn)=>{await fn();report.steps.push(name);};
let browser,page;
const shot=async name=>{await page.screenshot({path:path.join(out,name)});report.screenshots.push(name);};
const view=()=>page.locator('#main-menu').getAttribute('data-view');
const play=()=>page.locator('[data-play-scene]');
const button=name=>page.locator('#main-menu').getByRole('button',{name,exact:true});
// Periodic observation telemetry is independent of scene playback. Every other WebSocket
// send is captured, including any accidental session/start action from an engine shortcut.
const commands=()=>sent.filter(m=>m.type!=='observation');
const assertQuiet=async(fn)=>{
    const before=commands().length,lines=await page.locator('.message-mission').count();
    await fn();
    assert(commands().length===before,'Scene sent a WebSocket command: '+JSON.stringify(commands().slice(before)));
    assert(await page.locator('.message-mission').count()===lines,'Scene posted duplicate conversation lines');
};
try{
    await mkdir(out,{recursive:true});
    const data=await mkdtemp(path.join(tmpdir(),'edgeloop-scene-data-'));
    const env=isolatedEnv({PYTHONPATH:root,EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(aiPort),EDGELOOP_CAMPAIGN_FIXTURE_DATA:data,EDGELOOP_SCENE_FIXTURE:'1'});
    await claimPorts(uiPort,aiPort);
    children.push(spawn('python3',['tools/serve_local.py',String(uiPort)],{cwd:root,stdio:'ignore',env}));
    children.push(spawn(path.join(root,'.venv/bin/python'),['-m','tests.fork.campaign_browser_service'],{cwd:root,stdio:'ignore',env}));
    await ownedReady(ui,children);await ownedReady(ai+'/health',children);
    browser=guardBrowser(await chromium.launch(),[uiPort,aiPort]);
    const context=await browser.newContext({viewport:{width:1600,height:1000},reducedMotion:'reduce',serviceWorkers:'block'});
    // Asterion has no story registry in production. Reuse labelled Helix placeholder assets
    // under a fixture registry, leaving all shipped campaigns and registry files untouched.
    const folder=path.join(root,'src/assets/story/rise_of_helix');
    const registry=JSON.parse(await readFile(path.join(folder,'ASSETS.json'),'utf8'));registry.campaign='asterion_initiative';
    await context.route('**/src/assets/story/asterion_initiative/**',async route=>{
        const file=new URL(route.request().url()).pathname.split('/').at(-1);
        if(file==='ASSETS.json')return route.fulfill({json:registry});
        if(file==='h_breach.webp')return route.fulfill({status:404,body:''});
        if(Object.values(registry.slots).some(s=>s.file===file))return route.fulfill({contentType:'image/webp',body:await readFile(path.join(folder,file))});
        return route.fulfill({status:404,body:''});
    });
    page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    page.on('websocket',ws=>ws.on('framesent',frame=>{try{sent.push(JSON.parse(frame.payload));}catch{}}));
    await page.goto(ui+'/');await page.locator('#ageConfirmBtn').click();await page.locator('#wizardSkipBtn').click();
    await page.locator('[data-menu-tile=freeplay]').click();
    await page.locator('[data-url]').fill(ai.replace('http:','ws:')+'/observe');
    await page.locator('[data-token]').fill('browser-fixture-token-'+'x'.repeat(32));await page.locator('[data-connect]').click();
    await page.waitForFunction(()=>document.querySelector('[data-model] option[value="nova-narrative-v1:latest"]'));
    await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').click();
    await page.locator('[data-campaign=asterion_initiative]').click();
    await page.locator('.mission-detail').getByRole('button',{name:'Start mission'}).click();
    await play().waitFor();
    await step('Expression portrait appears in briefing; illustration scene has accessible stage and placeholder badge',async()=>{
        const src=await page.locator('.mission-speech img').getAttribute('src');
        assert(src.includes('concerned'),'Briefing expression ignored: '+src);
        await assertQuiet(async()=>{
            await play().click();assert(await view()==='scene','Scene did not open');
            const stage=page.getByRole('group',{name:'Orientation, part 1 of 1'});
            assert(await stage.getAttribute('aria-roledescription')==='scene','Stage role');
            assert(await page.locator('.scene-text').getAttribute('aria-live')==='polite','Live text');
            assert(await page.locator('.scene-art').getAttribute('alt')==='','Image must be decorative');
            await page.waitForFunction(()=>document.querySelector('.scene-art')?.naturalWidth>0);
            assert(await button('Back').isDisabled(),'First Back must be disabled');
            assert(await button('Next').evaluate(e=>e===document.activeElement),'Next not focused');
            assert(await page.locator('.scene-text [data-state=placeholder]').count()===1,'Placeholder badge');
            await shot('scene-briefing-image.png');
            await page.keyboard.press('Escape');assert(await view()==='briefing','Escape skipped briefing');
            assert(await play().evaluate(e=>e===document.activeElement),'Play focus not restored');
        });
    });
    await step('Space on stage ends briefing without sending a command or posting conversation text',async()=>{
        await assertQuiet(async()=>{await play().click();await page.locator('.scene-stage').focus();await page.keyboard.press('Space');assert(await view()==='briefing','Space did not advance');});
        assert(!commands().some(m=>m.type==='session'||m.action==='session'||m.action==='session_start'),'Engine session shortcut leaked');
        const before=await page.locator('.message-mission').count();
        await button('Begin with Nova').click();await page.locator('#main-menu').waitFor({state:'hidden'});
        // The briefing is queued until the companion switch finishes (companion.js postMissionLines).
        await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.includes('nova-narrative-v1:latest'));
        await page.waitForFunction(n=>document.querySelectorAll('.message-mission').length>n,before);
        await page.waitForTimeout(300);
        assert(await page.locator('.message-mission').count()===before+1,'Begin must post briefing exactly once');
    });
    const real=edges=>({session_id:'5e3d0c3a-0000-4000-8000-00000000c020',status:'RUNNING',edges,active_mode:'classic',goal:'tease',devices:{hr_ready:true,ble:true,simulated_hr:false,toy_ready:true},details:{orgasm_count:0,calibration_pass:'none'}});
    for(const edges of [0,1])await fetch(ai+'/fixture/campaign/evidence',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({report:real(edges)})});
    await play().waitFor();
    await step('Results show neutral fallback without expression; scene Next/Back, illustration, missing slot and failed image',async()=>{
        const portraits=await page.locator('.mission-speech img').evaluateAll(es=>es.map(e=>e.getAttribute('src')));
        assert(portraits[0].includes('concerned')&&portraits.slice(1).every(p=>p.includes('neutral')),'Expression/default neutral: '+portraits);
        await assertQuiet(async()=>{
            await play().click();
            await page.waitForFunction(()=>document.querySelector('.scene-art')?.naturalWidth>0);
            assert((await page.locator('.scene-portrait').getAttribute('src')).includes('concerned'),'Scene expression portrait');
            await shot('scene-background-portrait.png');
            await button('Next').click();assert(await page.locator('.scene-position').textContent()==='2 / 5','Next');
            await button('Back').click();assert(await page.locator('.scene-position').textContent()==='1 / 5','Back');
            await page.keyboard.press('ArrowRight');assert(await page.locator('.scene-position').textContent()==='2 / 5','Right');
            await page.keyboard.press('ArrowLeft');assert(await page.locator('.scene-position').textContent()==='1 / 5','Left');
            await page.locator('.scene-stage').focus();await page.keyboard.press('Enter');
            assert(await page.locator('.scene-position').textContent()==='2 / 5','Stage Enter');
            await button('Next').click();assert(await page.locator('.scene-stage.scene-plain').count()===1,'Missing slot fallback');
            assert(await page.locator('.scene-art').count()===0,'Missing slot should have no image');
            await button('Next').click();await page.locator('.scene-stage.scene-plain').waitFor();
            assert(await page.locator('.scene-art').count()===0,'Broken image not removed');
            assert(await page.locator('.scene-portrait').count()===1,'Broken image should fall back to portrait');
            await button('Next').click();assert(await page.locator('.scene-position').textContent()==='5 / 5','Plain block');
            await button('Next').click();assert(await view()==='results','Final Next must end');
            assert(await play().evaluate(e=>e===document.activeElement),'Results focus not restored');
        });
    });
    await step('Skip, Space on buttons, Tab trap, and 390×844 phone layout',async()=>{
        await assertQuiet(async()=>{
            await play().click();await button('Skip').click();assert(await view()==='results','Skip');
            await page.setViewportSize({width:390,height:844});await play().click();
            await page.waitForFunction(()=>document.querySelector('.scene-art')?.naturalWidth>0);
            await shot('scene-phone-390.png');
            const geometry=await page.evaluate(()=>{const s=document.querySelector('.scene-stage').getBoundingClientRect(),t=document.querySelector('.scene-text').getBoundingClientRect(),m=document.querySelector('#main-menu'),b=document.querySelector('.scene-controls').getBoundingClientRect();return {ratio:t.height/s.height,scroll:m.scrollWidth>m.clientWidth,buttons:b.bottom,viewport:innerHeight};});
            assert(geometry.ratio<=.46&&!geometry.scroll&&geometry.buttons<=geometry.viewport,'Phone layout '+JSON.stringify(geometry));
            await button('Skip').focus();await page.keyboard.press('Tab');assert(await page.locator('.scene-stage').evaluate(e=>e===document.activeElement),'Tab trap forward');
            await page.keyboard.press('Shift+Tab');assert(await button('Skip').evaluate(e=>e===document.activeElement),'Tab trap reverse');
            await button('Next').focus();await page.keyboard.press('Space');assert(await page.locator('.scene-position').textContent()==='2 / 5','Space on Next');
            await page.keyboard.press('Escape');assert(await view()==='results','Phone Escape');
        });
    });
    // A fresh non-scene fixture instance covers a briefing whose narrative has no art.
    await step('No Play scene entry for plain briefing; unknown expression uses neutral',async()=>{
        await page.route('**/scene-fixture.html',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><body></body></html>'}));
        await page.goto(ui+'/scene-fixture.html');
        await page.evaluate(async()=>{
            const {mountMainMenu}=await import('/src/js/ai/main-menu.js');
            const host=document.createElement('div');document.body.append(host);
            const menu=mountMainMenu({send:()=>true,status:()=> 'IDLE',selectCompanion:()=>true,bannerHost:host});
            const m={id:'plain',order:1,title:'Plain mission',companion:'mira',state:'available',objectives:[],rewards:[],prerequisites:[],summary:'Fixture'};
            menu.receive({type:'campaign_state',campaigns:[{id:'plain',title:'Plain campaign',available:true,description:'Fixture',progress:{completed:0,total:1},missions:[m]}],active:null});
            document.querySelector('[data-menu-tile=campaign]').click();document.querySelector('[data-campaign=plain]').click();document.querySelector('.mission-detail button').click();
            menu.receive({type:'campaign_state',campaigns:[{id:'plain',title:'Plain campaign',available:true,progress:{completed:0,total:1},missions:[{...m,state:'active'}]}],active:{campaign:'plain',mission:'plain'}});
            menu.receive({type:'mission_text',campaign:'plain',mission:'plain',briefing:{speaker:'mira',lines:['No artwork'],expression:'not-an-expression'},hints:[]});
            window.fixtureMenu=menu;
        });
        assert(await play().count()===0,'Play scene without art');
        assert((await page.locator('#main-menu .mission-speech img').getAttribute('src')).includes('neutral'),'Unknown expression must fall back to neutral');
        await page.evaluate(()=>window.fixtureMenu.destroy());
    });
    assert(errors.length===0,'Page errors: '+errors.join(' | '));
    report.passed=true;
}catch(error){report.error=String(error?.stack||error);report.page_errors=errors;try{await shot('scene-failure.png');}catch{}}
finally{await browser?.close();for(const child of children)child.kill('SIGTERM');await writeFile(path.join(out,'scene-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));process.exitCode=report.passed?0:1;}
