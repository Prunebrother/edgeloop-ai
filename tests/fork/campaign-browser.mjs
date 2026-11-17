// SPDX-License-Identifier: AGPL-3.0-only
// Main menu, Freeplay, Campaign and Mission screens against the real observer (mocked Ollama, no hardware).
// Mission evidence comes from tests/fork/campaign_browser_service.py, standing in for a real strap and toy.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,mkdtemp,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {claimPorts,ownedReady,isolatedEnv,guardBrowser} from './fixture-isolation.mjs';
const root=path.resolve(new URL('../..',import.meta.url).pathname),out=process.env.CAMPAIGN_BROWSER_REPORT||path.join(tmpdir(),'edgeloop-campaign-browser');
const uiPort=Number(process.env.EDGELOOP_CAMPAIGN_UI_PORT||8862),aiPort=Number(process.env.EDGELOOP_CAMPAIGN_AI_PORT||8868);
const ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`,children=[],report={passed:false,physical_hardware:false,steps:[],screenshots:[]};
const TOKEN='browser-fixture-token-'+'x'.repeat(32),CID='asterion_initiative';
const assert=(x,m)=>{if(!x)throw Error(m);};
let browser,page,errors=[];
const step=async(name,fn)=>{await fn();report.steps.push(name);};
const shot=async name=>{await page.screenshot({path:path.join(out,name)});report.screenshots.push(name);};
const evidence=async(report,events=[])=>(await fetch(ai+'/fixture/campaign/evidence',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({report,events})})).json();
const progress=async()=>(await fetch(ai+'/fixture/campaign')).json();
const saves=async ok=>(await fetch(ai+'/fixture/campaign/saves',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({ok})})).json();
const real=(edges,status='RUNNING')=>({session_id:'5e3d0c3a-0000-4000-8000-00000000c001',status,edges,active_mode:'classic',goal:'tease',
    devices:{hr_ready:true,ble:true,simulated_hr:false,toy_ready:true},details:{orgasm_count:0,calibration_pass:'none'}});
const batch=async reports=>(await fetch(ai+'/fixture/campaign/evidence',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({reports})})).json();
const span=(from,to,intensity)=>Array.from({length:Math.floor((to-from)/5)+1},(_,i)=>tick(from+5*i,intensity));
const seed=async mission=>(await fetch(ai+'/fixture/campaign/progress',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({campaign:CID,mission})})).json();
const tick=(seconds,intensity,orgasms=0)=>({...real(0),session_id:'5e3d0c3a-0000-4000-8000-00000000c009',seconds,experience:'classic',intensity,details:{orgasm_count:orgasms,calibration_pass:'none',captured_at_ms:1793000000000+seconds*1000}});
const menuView=()=>page.locator('#main-menu .game-menu-panel').getAttribute('data-view');
try{
    await mkdir(out,{recursive:true});
    const data=await mkdtemp(path.join(tmpdir(),'edgeloop-campaign-data-'));
    const env={...isolatedEnv(),PYTHONPATH:root,EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(aiPort),EDGELOOP_CAMPAIGN_FIXTURE_DATA:data};
    await claimPorts(uiPort,aiPort);
    children.push(spawn('python3',['tools/serve_local.py',String(uiPort)],{cwd:root,stdio:'ignore',env}));
    children.push(spawn(path.join(root,'.venv/bin/python'),['-m','tests.fork.campaign_browser_service'],{cwd:root,stdio:'ignore',env}));
    await ownedReady(ui,children);await ownedReady(ai+'/health',children);
    browser=guardBrowser(await chromium.launch(),[uiPort,aiPort]);
    const context=await browser.newContext({viewport:{width:1600,height:1000}});
    await context.addInitScript(()=>{const no=()=>Promise.reject(new DOMException('No physical hardware','NotFoundError'));
        Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:no},configurable:true});Object.defineProperty(navigator,'serial',{value:{requestPort:no,getPorts:async()=>[]},configurable:true});});
    page=await context.newPage();errors=[];page.on('pageerror',e=>errors.push(e.message));
    const handy=[];
    await page.route('**/api/handy/v2/**',async route=>{const p=new URL(route.request().url()).pathname;handy.push(p);
        await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(p.endsWith('/connected')?{connected:true}:p.endsWith('/info')?{fwVersion:'3.2.3',model:'Handy 1.1'}:{result:0})});});
    await page.goto(ui+'/');
    await page.locator('#ageConfirmBtn').click();await page.locator('#wizardSkipBtn').click();

    // The board shows one chapter (by default the one with the mission to play): pick the card, then start it.
    const startFromBoard=async id=>{
        await page.locator(`.mission-card[data-mission=${id}] button`).click();
        await page.locator(`.mission-detail[data-mission=${id}]`).getByRole('button',{name:'Start mission'}).click();
    };
    await step('1. Main menu is the entry point with three options',async()=>{
        await page.locator('#main-menu').waitFor({state:'visible'});
        const tiles=await page.locator('#main-menu .game-menu-tile').allTextContents();
        assert(tiles.length===3&&/Campaign/.test(tiles[0])&&/Freeplay/.test(tiles[1])&&/Companion Builder/.test(tiles[2])&&/Coming soon/.test(tiles[2]),'Menu tiles '+tiles);
        await shot('menu-home.png');
    });
    await step('3. Companion Builder is greyed out and goes nowhere',async()=>{
        const builder=page.locator('[data-menu-tile=companion-builder]');
        assert(await builder.getAttribute('aria-disabled')==='true','Builder not aria-disabled');
        await builder.click({force:true});assert(await menuView()==='home','Builder navigated');
    });
    await step('1. Keyboard: arrows move between enabled tiles and skip the disabled one',async()=>{
        await page.locator('[data-menu-tile=campaign]').focus();
        await page.keyboard.press('ArrowDown');assert(await page.evaluate(()=>document.activeElement.dataset.menuTile)==='freeplay','ArrowDown');
        await page.keyboard.press('ArrowDown');assert(await page.evaluate(()=>document.activeElement.dataset.menuTile)==='campaign','Wrap skips builder');
        await page.keyboard.press('Space');await page.waitForFunction(()=>document.querySelector('#main-menu .game-menu-panel').dataset.view==='campaigns');
        assert(await page.evaluate(async()=>(await import('/src/js/state.js')).state.sessionStatus)==='IDLE','Space behind the menu started a session');
        await page.keyboard.press('Escape');await page.waitForFunction(()=>document.querySelector('#main-menu .game-menu-panel').dataset.view==='home');
    });
    await step('Codex 11: with focus outside the menu, Space still cannot reach the engine',async()=>{
        await page.evaluate(()=>document.activeElement?.blur());  // like the wizard closing: focus falls to the page, no focus event
        assert(await page.evaluate(()=>!document.getElementById('main-menu').contains(document.activeElement)),'focus did not leave the menu');
        await page.evaluate(()=>{window.__leaked=0;document.addEventListener('keydown',()=>window.__leaked++);});  // where the engine listens
        await page.keyboard.press('Space');await page.waitForTimeout(300);
        assert(await page.evaluate(()=>window.__leaked)===0,'a key from outside the menu reached the document');
        assert(await page.evaluate(async()=>(await import('/src/js/state.js')).state.sessionStatus)==='IDLE','Space from outside the menu started a session');
        assert(await page.evaluate(()=>document.getElementById('main-menu').contains(document.activeElement)),'focus not returned to the menu');
    });
    await step('2. Freeplay opens the existing app with its Character Builder',async()=>{
        await page.locator('[data-menu-tile=freeplay]').click();
        await page.locator('#main-menu').waitFor({state:'hidden'});
        assert(await page.locator('#companion-dashboard').isVisible(),'Dashboard hidden');
        await page.locator('[data-url]').fill(ai.replace('http:','ws:')+'/observe');await page.locator('[data-token]').fill(TOKEN);await page.locator('[data-connect]').click();
        await page.waitForFunction(()=>document.querySelector('[data-model] option[value="nova-narrative-v1:latest"]'));
        assert(await page.locator('.mission-banner').isHidden(),'Mission banner in Freeplay');
        assert(await page.locator('[data-open-builder]').isVisible(),'Character Builder missing from Freeplay');
    });
    await step('Main menu: the host follows the selected companion, and a chip switches her',async()=>{
        await page.locator('[data-main-menu]').click();
        await page.locator('.menu-host-figure').waitFor();
        const selected=await page.locator('[data-selected]').textContent();
        const host=await page.locator('.menu-host-figure').getAttribute('data-host');
        assert(selected.includes('Active:')?selected.includes(host):host==='nova','Host '+host+' vs '+selected);
        await page.locator('.menu-host-chips [data-host=daisy]').click();
        await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.includes('daisy'));
        await page.waitForFunction(()=>document.querySelector('.menu-host-figure')?.dataset.host==='daisy');
        assert(await page.locator('.menu-host-chips [data-host=daisy]').getAttribute('aria-pressed')==='true','Chip not pressed');
        const line=await page.locator('.menu-host-bubble p').textContent();
        const greetings=await page.evaluate(async()=>(await import('/src/js/ai/menu-art.js')).GREETINGS.daisy);
        assert(greetings.includes(line),'Greeting '+line);
        assert((await page.locator('[data-menu-tile=campaign]').textContent()).includes('Mission 1 · Orientation'),'Campaign tile does not name the next mission');
        await shot('menu-home-host.png');
        await page.locator('[data-menu-tile=freeplay]').click();await page.locator('#main-menu').waitFor({state:'hidden'});
    });
    await step('4. Campaign selection lists The Asterion Initiative',async()=>{
        await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').click();
        const card=page.locator('#main-menu .game-menu-card').first();
        await card.waitFor();const text=await card.textContent();
        assert(text.includes('The Asterion Initiative')&&text.includes('0 of 14 missions completed'),'Campaign card '+text);
        await shot('menu-campaigns.png');await card.click();
        // The mission board shows one chapter at a time: Chapter 1, with Orientation picked.
        const states=await page.locator('.mission-board .mission-card').evaluateAll(cards=>cards.map(c=>c.dataset.state));
        assert(JSON.stringify(states)===JSON.stringify(['available',...Array(4).fill('locked')]),'Mission states '+states);
        const chapters=await page.locator('.board-chapters .mission-chapter').evaluateAll(cs=>cs.map(c=>c.querySelector('h2').textContent+':'+c.dataset.state));
        assert(JSON.stringify(chapters)===JSON.stringify(['Introduction:available','Advanced Research:locked','Shadows of Helix:locked','Rise of Helix:teaser']),'Chapters '+chapters);
        assert((await page.locator('#main-title, .board-hero h1').first().textContent())==='Introduction','Board title');
        assert(await page.locator('.mission-card[data-mission=orientation] button').getAttribute('aria-pressed')==='true','Orientation not picked');
        assert(await page.evaluate(()=>document.activeElement?.closest('.mission-card')?.dataset.mission)==='orientation','Focus not on the picked mission');
        await shot('menu-missions.png');
        await page.locator('.mission-card[data-mission=first_assessment] button').click();
        assert((await page.locator('.mission-detail').textContent()).includes('Complete Orientation first'),'Lock reason');
        assert(await page.locator('.mission-card[data-mission=first_assessment] .board-figure').evaluate(e=>getComputedStyle(e).filter.includes('brightness(0)')),'Locked figure is not a silhouette');
        await page.locator('.board-chapters [data-chapter="4"]').click();
        assert((await page.locator('.board-teaser').textContent()).includes('Coming soon'),'Teaser board');
        await page.locator('.board-chapters [data-chapter="1"]').click();
    });
    await step('Mission start shows Nova\'s briefing and Begin selects Nova',async()=>{
        await startFromBoard('orientation');
        await page.waitForFunction(()=>document.querySelector('#main-menu .game-menu-panel').dataset.view==='briefing');
        assert((await page.locator('.mission-speech').textContent()).includes('ASTERION-SYN/07'),'Briefing text');
        await shot('menu-briefing.png');
        await page.getByRole('button',{name:'Begin with Nova'}).click();
        await page.locator('#main-menu').waitFor({state:'hidden'});
        await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.includes('nova-narrative-v1:latest'));
        assert(await page.locator('.message-mission').first().textContent().then(t=>t.includes('Nova · Mission briefing')),'Briefing not in chat');
        const banner=await page.locator('.mission-banner').textContent();
        assert(banner.includes('Orientation')&&banner.includes('Reach 1 edge'),'Banner '+banner);
        // Campaign mode: the companion is the mission's; switching waits for Freeplay.
        assert(await page.locator('[data-model]').isDisabled()&&await page.locator('[data-select]').isDisabled(),'Model picker not locked during a mission');
        assert(await page.locator('[data-campaign-lock]').isVisible(),'No lock note during a mission');
    });
    await step('6, 7, 8. One verified edge completes Orientation and unlocks Evelyn and Mission 2',async()=>{
        let sent=await evidence(real(0));assert(sent.model==='nova-narrative-v1:latest','Fixture model '+sent.model);
        sent=await evidence(real(1));assert(sent.sent.includes('mission_result'),'No result '+sent.sent);
        await page.locator('.mission-toast').waitFor();
        assert((await page.locator('.mission-toast').textContent()).includes('Dr. Evelyn Voss joins the campaign'),'Toast');
        await page.waitForFunction(()=>document.querySelector('#main-menu .game-menu-panel').dataset.view==='results');
        const results=await page.locator('#main-menu').textContent();
        assert(results.includes('Mission complete')&&results.includes('Next: First Assessment'),'Results '+results.slice(0,300));
        await shot('menu-results.png');
        assert(await page.locator('.message-mission').last().textContent().then(t=>t.includes('Mission complete')),'Completion line not in chat');
        await page.getByRole('button',{name:'Next: First Assessment'}).click();
        const states=await page.locator('.mission-card').evaluateAll(cards=>cards.map(c=>c.dataset.state));
        assert(states[0]==='completed'&&states[1]==='available'&&states[2]==='locked','After completion '+states);
    });
    await step('10, 12. Repeated evidence after completion is ignored',async()=>{
        const sent=await evidence(real(2));assert(!sent.sent.includes('mission_result'),'Second result');
    });
    await step('9. Progress survives a reload',async()=>{
        const saved=JSON.parse((await progress()).saved);
        assert(saved.schema_version===3&&saved.campaigns[CID].missions.orientation.completions===1,'Saved progress');
        await page.reload();
        await page.locator('#main-menu').waitFor({state:'visible'});
        await page.locator('[data-menu-tile=freeplay]').click();
        await page.locator('[data-url]').fill(ai.replace('http:','ws:')+'/observe');await page.locator('[data-token]').fill(TOKEN);await page.locator('[data-connect]').click();
        await page.waitForFunction(()=>document.querySelector('[data-model] option[value="evelyn:latest"]'));
        await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').click();
        assert((await page.locator('#main-menu .game-menu-card').first().textContent()).includes('1 of 14'),'Reloaded progress');
    });
    await step('14. Freeplay leaves an active mission without losing completed ones',async()=>{
        await page.locator('#main-menu .game-menu-card').first().click();
        await startFromBoard('first_assessment');
        await page.waitForFunction(()=>document.querySelector('#main-menu .game-menu-panel').dataset.view==='briefing');
        await page.keyboard.press('Escape');await page.keyboard.press('Escape');await page.keyboard.press('Escape');
        await page.waitForFunction(()=>document.querySelector('#main-menu .game-menu-panel').dataset.view==='home');
        // During a mission the host chips cannot switch companions; only the current one stays enabled.
        assert(await page.locator('.menu-host-chips button:disabled').count()===4,'Host chips not locked during a mission');
        // Codex 12: if leaving cannot be saved, the menu stays and says so; the mission's rules still apply.
        await saves(false);
        page.once('dialog',d=>d.accept());await page.locator('[data-menu-tile=freeplay]').click();
        await page.waitForFunction(()=>/could not be saved/.test(document.querySelector('#main-menu .game-menu-status')?.textContent||''));
        assert(await page.locator('#main-menu').isVisible(),'Freeplay opened before the mission was left');
        assert(JSON.parse((await progress()).saved).active?.mission==='first_assessment','mission changed despite the failed save');
        await saves(true);
        page.once('dialog',d=>d.accept());await page.locator('[data-menu-tile=freeplay]').click();
        await page.locator('#main-menu').waitFor({state:'hidden'});
        for(let i=0;i<30&&JSON.parse((await progress()).saved).active;i++)await page.waitForTimeout(100);
        const saved=JSON.parse((await progress()).saved);
        assert(saved.active===null&&saved.campaigns[CID].missions.orientation,'Freeplay did not leave the mission cleanly');
        await page.waitForFunction(()=>!document.querySelector('[data-model]').disabled);
        assert(await page.locator('[data-campaign-lock]').isHidden(),'Lock note still shown in Freeplay');
    });
    await step('14. The menu cannot cover a running session',async()=>{
        await page.locator('#cardBle').click();await page.getByRole('button',{name:/manual simulator/i}).click();
        await page.locator('#modalSimHrSlider').evaluate(el=>{el.value='98';el.dispatchEvent(new Event('input',{bubbles:true}));});
        await page.locator('#modalEngageSimBtn').click();if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
        await page.locator('#cardHandy').click();await page.locator('#modalHandyInput').fill('F2-MOCK-KEY');
        await page.locator('#modalHandyConnectBtn').click();await page.waitForTimeout(900);
        if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
        await page.locator('#sessionPlayPauseBtn').click();
        await page.waitForFunction(async()=>(await import('/src/js/state.js')).state.sessionStatus==='RUNNING');
        await page.waitForFunction(()=>document.querySelector('[data-main-menu]').disabled);
        await page.locator('#sessionStopBtn').click();
        await page.waitForFunction(()=>!document.querySelector('[data-main-menu]').disabled);
    });
    await step('Chapter 2: chapter progress, the staged assessment tracker, milestone lines and chapter completion',async()=>{
        await seed('directors_reassessment');
        await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').click();
        const card=await page.locator('#main-menu .game-menu-card').first().textContent();
        assert(card.includes('Chapter 1: Introduction · Complete')&&card.includes('Chapter 2: Advanced Research · 75%'),'Campaign card '+card);
        await page.locator('#main-menu .game-menu-card').first().click();
        const chapters=await page.locator('.mission-chapter').allTextContents();
        assert(chapters[0].includes('Chapter complete · 100%')&&chapters[1].includes('3 of 4 missions · 75%'),'Chapter headings '+chapters);
        await startFromBoard('directors_reassessment');
        await page.waitForFunction(()=>document.querySelector('#main-menu .game-menu-panel').dataset.view==='briefing');
        const briefing=await page.locator('#main-menu').textContent();
        assert(!briefing.includes('Story draft')&&briefing.includes('○ Baseline: 75% · 0:00 / 10:00')&&briefing.includes('Final Assessment: 125%')&&briefing.includes('Celeste changes only what the mission needs, at its own steps (intensity, Force Orgasm)'),'Briefing '+briefing.slice(900,2400));
        await shot('chapter2-briefing.png');
        await page.getByRole('button',{name:'Begin with Celeste'}).click();
        await page.locator('#main-menu').waitFor({state:'hidden'});
        await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.includes('celeste'));
        const first=await batch([...span(0,600,75),...span(605,700,100)]);assert(first.sent.filter(t=>t==='mission_milestone').length===2,'First batch '+JSON.stringify(first));
        await page.waitForFunction(()=>[...document.querySelectorAll('.message-mission')].some(m=>m.textContent.includes('Baseline established')));
        // The milestone line and the progress update are separate messages: wait for the banner to catch up.
        await page.waitForFunction(()=>document.querySelector('.mission-banner')?.textContent.includes('11:35 of 30:00'),null,{timeout:5000}).catch(()=>{});
        const banner=await page.locator('.mission-banner').textContent();
        assert(banner.includes('✓ Baseline: 75% · 10:00 / 10:00')&&banner.includes('▸ Development: 100% · 1:35 / 10:00 (current)')&&banner.includes('11:35 of 30:00'),'Banner '+banner);
        await shot('chapter2-banner.png');
        await batch([...span(0,600,75),...span(605,1205,100),...span(1210,1810,125)]);
        await page.waitForFunction(()=>[...document.querySelectorAll('.message-mission')].some(m=>m.textContent.includes('The assessment is complete')));
        const sent=await batch([...span(0,600,75),...span(605,1205,100),...span(1210,1810,125),tick(1815,125,1)]);assert(sent.sent.includes('mission_result'),'No result '+sent.sent);
        await page.waitForFunction(()=>document.querySelector('#main-menu .game-menu-panel').dataset.view==='results');
        const results=await page.locator('#main-menu').textContent();
        assert(results.includes('Chapter 2 complete')&&!results.includes('Campaign complete')&&results.includes('unknown agents')&&results.includes("That's Advanced Research done"),'Results '+results.slice(0,600));
        await shot('chapter2-results.png');
        const saved=JSON.parse((await progress()).saved).campaigns[CID];
        assert(saved.chapters.advanced_research&&saved.chapters.introduction&&!saved.completed_at,'Saved chapters');
        await page.getByRole('button',{name:'Back to the session'}).click();
    });
    await step('Chapter 3: the Chapter 4 teaser, the countdown, and Nova\'s puzzles answered in the banner',async()=>{
        await seed('the_empty_vault');
        await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').click();
        const card=await page.locator('#main-menu .game-menu-card').first().textContent();
        assert(card.includes('Chapter 3: Shadows of Helix · 20%')&&card.includes('Chapter 4: Rise of Helix · Coming soon'),'Campaign card '+card);
        await page.locator('#main-menu .game-menu-card').first().click();
        assert((await page.locator('.mission-chapter[data-state=teaser]').textContent()).includes('Coming soon'),'Teaser chapter');
        await startFromBoard('the_empty_vault');
        await page.waitForFunction(()=>document.querySelector('#main-menu .game-menu-panel').dataset.view==='briefing');
        const briefing=await page.locator('#main-menu').textContent();
        assert(!briefing.includes('Story draft')&&briefing.includes('Time left: 15:00 of 15:00'),'Vault briefing '+briefing.slice(0,1500));
        await shot('chapter3-vault-briefing.png');
        await page.getByRole('button',{name:'Begin with Daisy'}).click();
        await page.locator('#main-menu').waitFor({state:'hidden'});
        await batch([tick(100,100),...span(105,400,100)]);
        await page.waitForFunction(()=>document.querySelector('.mission-banner')?.textContent.includes('Time left: 10:00 of 15:00'));
        await page.locator('#sessionStopBtn').click().catch(()=>{});
        await seed('ghost_in_the_machine');
        await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').click();
        await page.locator('#main-menu .game-menu-card').first().click();
        await startFromBoard('ghost_in_the_machine');
        await page.waitForFunction(()=>document.querySelector('#main-menu .game-menu-panel').dataset.view==='briefing');
        await page.getByRole('button',{name:'Begin with Nova'}).click();
        await page.locator('#main-menu').waitFor({state:'hidden'});
        await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.includes('nova'));
        await batch([tick(0,100),tick(5,100)]);
        await page.locator('.mission-puzzle').waitFor();
        assert((await page.locator('.mission-puzzle').textContent()).includes('Badge ASR-0413 is registered to you'),'Puzzle 1 clues');
        await page.locator('[data-puzzle-option=carried]').click();
        await page.waitForFunction(()=>document.querySelector('.mission-puzzle')?.textContent.includes('Not quite.'));
        assert(await page.locator('[data-puzzle-option=carried]').getAttribute('class')==='wrong','Wrong pick marked');
        await shot('chapter3-puzzle-hint.png');
        await page.locator('[data-puzzle-option=internal]').click();
        await page.waitForFunction(()=>document.querySelector('.mission-puzzle strong')?.textContent==='Follow the money');
        await page.waitForFunction(()=>[...document.querySelectorAll('.message-mission')].some(m=>m.textContent.includes('internal Asterion badge')));
        const saved=JSON.parse((await progress()).saved);assert(JSON.stringify(saved.campaigns[CID].solved)==='{"ghost_in_the_machine":["log"]}','Saved puzzle '+JSON.stringify(saved.campaigns[CID].solved));
        await page.locator('[data-puzzle-option=helix]').focus();await page.keyboard.press('Enter');
        await page.waitForFunction(()=>document.querySelector('.mission-puzzle strong')?.textContent==='The edited record');
        // Space presses the answer button only; the engine's Space shortcut (start or pause) must not fire.
        const startDisabled=await page.locator('#sessionStopBtn').isDisabled().catch(()=>null);
        await page.locator('[data-puzzle-option=inside]').focus();await page.keyboard.press('Space');
        await page.waitForFunction(()=>document.querySelector('#main-menu .game-menu-panel').dataset.view==='results');
        assert(await page.locator('#sessionStopBtn').isDisabled().catch(()=>null)===startDisabled,'Space on a puzzle button reached the engine');
        const results=await page.locator('#main-menu').textContent();
        assert(results.includes('Chapter 3 complete')&&results.includes('You are cleared of suspicion')&&results.includes('come to Helix'),'Results '+results.slice(0,800));
        assert(!(await page.content()).includes('Follow each owner up the chain'),'Hint leaked before a wrong answer');
        await shot('chapter3-results.png');
        await page.getByRole('button',{name:'Back to the session'}).click();
    });
    await step('Phone width: no horizontal scroll',async()=>{
        await page.setViewportSize({width:390,height:844});
        await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').click();
        await page.locator('#main-menu .game-menu-card').first().click();
        assert(await page.evaluate(()=>{const m=document.querySelector('#main-menu');return m.scrollWidth<=m.clientWidth;}),'Horizontal scroll at 390px');
        await shot('menu-missions-390.png');
        await page.keyboard.press('Escape');await page.keyboard.press('Escape');
        await page.waitForFunction(()=>document.querySelector('#main-menu .game-menu-panel').dataset.view==='home');
        assert(await page.evaluate(()=>{const m=document.querySelector('#main-menu');return m.scrollWidth<=m.clientWidth;}),'Home: horizontal scroll at 390px');
        await shot('menu-home-390.png');
    });
    assert(errors.length===0,'Page errors: '+errors.join(' | '));
    report.passed=true;
}catch(error){report.error=String(error?.stack||error);report.page_errors=errors;try{await page?.screenshot({path:path.join(out,'failure.png')});}catch{}}
finally{
    await browser?.close();for(const child of children)child.kill('SIGTERM');
    await writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));process.exitCode=report.passed?0:1;
}
