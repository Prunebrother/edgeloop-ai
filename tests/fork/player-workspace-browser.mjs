// SPDX-License-Identifier: AGPL-3.0-only
// Player workspace regression (browser). The video stage opens in the conversation column only
// when the participant clicks Player; closing it restores the conversation view. Visibility is
// separate from playback and the session. Theater and Fullscreen keep an engine emergency stop
// reachable. Loading media is not acknowledged as the participant's play-style selection.
// Fixtures only: simulated heart rate, mocked Handy cloud API, mocked Ollama. No real hardware.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';import {claimPorts,ownedReady,isolatedEnv,guardBrowser} from './fixture-isolation.mjs';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve(new URL('../..',import.meta.url).pathname);
const output=process.env.FORK_BROWSER_REPORT||'/tmp/edgeloop-player-workspace-browser';
const python=process.env.EDGELOOP_TEST_PYTHON||path.join(root,'.venv/bin/python');
const uiPort=process.env.FORK_BROWSER_PORT||'8781',observerPort=process.env.FORK_OBSERVER_PORT||'8789';
const uiUrl='http://127.0.0.1:'+uiPort,observerUrl='http://127.0.0.1:'+observerPort;
const token='browser-fixture-token-'+'x'.repeat(32);
const report={passed:false,steps:[],screenshots:[],fixture:'simulated HR, mocked Handy and Ollama; no real hardware'};
const children=[];let browser,page;
const assert=(x,m)=>{if(!x)throw new Error(m);};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function waitServer(url){return ownedReady(url,children);}
const engine=fn=>page.evaluate(async source=>{const{state}=await import('/src/js/state.js');return new Function('state','return ('+source+')(state)')(state);},fn.toString());
const status=()=>engine(new Function('return state=>({status:state.sessionStatus,primary:state.strokerSpeed,secondary:state.prostateSpeed,mode:state.teaseMode})')());
async function shot(name,opts={}){const file=path.join(output,name);await page.screenshot({path:file,...opts});report.screenshots.push(name);}
// What the participant can actually click at the centre of an element.
const hit=selector=>page.evaluate(s=>{const e=document.querySelector(s);if(!e)return 'missing';const r=e.getBoundingClientRect();
    if(!r.width||!r.height)return 'not rendered';const h=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
    return h&&(h===e||e.contains(h))?'clickable':'covered by '+(h?(h.id||h.className||h.tagName):'nothing');},selector);
const layout=()=>page.evaluate(()=>{const box=s=>{const r=document.querySelector(s)?.getBoundingClientRect();return r?{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}:null;};
    const history=document.querySelector('[data-history]'),bubble=document.querySelector('[data-history] .message-content');
    return {player:document.getElementById('companion-dashboard').dataset.player,workspaceHidden:document.getElementById('player-workspace').hidden,
        stage:box('#playerStage'),picture:box('#playerPicture'),center:box('#companion-center'),session:box('#session-panel'),history:box('[data-history]'),composer:box('[data-chat]'),
        historyHeight:history.clientHeight,fontSize:bubble?parseFloat(getComputedStyle(bubble).fontSize):null,
        textareaUsable:!document.querySelector('[data-text]').disabled&&document.querySelector('[data-text]').getBoundingClientRect().height>20,
        overflowX:document.documentElement.scrollWidth>innerWidth+1};});
try {
    await mkdir(output,{recursive:true});
    browser=guardBrowser(await chromium.launch(),[uiPort,observerPort]);
    await claimPorts(uiPort,observerPort);children.push(spawn('python3',['tools/serve_local.py',uiPort],{cwd:root,stdio:'ignore',env:isolatedEnv()}));
    children.push(spawn(python,['tests/fork/browser_service.py'],{cwd:root,stdio:'ignore',env:{...isolatedEnv(),PYTHONPATH:root,EDGELOOP_FIXTURE_UI_PORT:uiPort,EDGELOOP_FIXTURE_OBSERVER_PORT:observerPort}}));
    await waitServer(uiUrl+'/');await waitServer(observerUrl+'/health');
    const ctx=await browser.newContext({viewport:{width:1920,height:1080}});
    await ctx.addInitScript(()=>{
        const denied=()=>Promise.reject(new DOMException('Fixture: no real devices','NotFoundError'));
        Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:denied},configurable:true});
        Object.defineProperty(navigator,'serial',{value:{requestPort:denied,getPorts:async()=>[]},configurable:true});
        if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=denied;
    });
    page=await ctx.newPage();
    const errors=[],handy=[],external=[],frames=[];
    page.on('websocket',ws=>ws.on('framesent',event=>{try{const m=JSON.parse(event.payload);if(m.type==='observation')frames.push(m);}catch{}}));
    const diagnostics=[];page.on('websocket',ws=>ws.on('framereceived',event=>{try{const m=JSON.parse(event.payload);if(m.type==='ai_diagnostics')diagnostics.push({t:Date.now(),...m});}catch{}}));
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',async route=>{
        const url=new URL(route.request().url());
        if(url.hostname.endsWith('handyfeeling.com')){
            handy.push(url.pathname);
            return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(url.pathname.endsWith('/connected')?{connected:true}:url.pathname.endsWith('/info')?{fwVersion:'3.2.3',model:'Handy 1.1'}:{result:0})});
        }
        if(!['127.0.0.1','localhost'].includes(url.hostname)){external.push(url.href);return route.abort();}
        return route.continue();
    });
    await page.goto(uiUrl+'/',{waitUntil:'load'});
    await page.locator('#ageConfirmBtn').click();
    await page.locator('#wizardOverlay').waitFor({state:'visible'});await page.locator('#wizardSkipBtn').click();
    await page.locator('#companion-dashboard').waitFor({timeout:8000});

    // 1. Closed by default; the stage lives in the workspace, created once.
    let l=await layout();
    assert(l.player==='off'&&l.workspaceHidden,'Player is open by default: '+JSON.stringify(l));
    assert(await page.evaluate(()=>document.getElementById('playerColumn').parentElement.id==='player-workspace'&&!document.getElementById('ai-companion').contains(document.getElementById('playerStage'))),'Video stage not mounted in its own workspace');
    assert(await page.evaluate(()=>document.getElementById('playerBody').dataset.player==='off'),'Upstream player state not off by default');
    await page.evaluate(()=>{window.__video=document.getElementById('playerVideo');window.__stage=document.getElementById('playerStage');});
    report.steps.push('Player is closed by default; the upstream video stage is mounted once in the conversation column');

    // Companion: simulated HR, paired, a model and a short conversation.
    await page.locator('#cardBle').click();await page.getByRole('button',{name:/manual simulator/i}).click();
    await page.locator('#modalSimHrSlider').evaluate(el=>{el.value='98';el.dispatchEvent(new Event('input',{bubbles:true}));});
    await page.locator('#modalEngageSimBtn').click();
    if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
    await page.locator('[data-url]').fill('ws://127.0.0.1:'+observerPort+'/observe');
    await page.locator('[data-token]').fill(token);await page.locator('[data-connect]').click();
    await page.waitForFunction(()=>document.querySelector('[data-telemetry]').textContent.includes('Authoritative telemetry connected'));
    await page.locator('[data-model] option[value="evelyn-lite-v1:latest"]').waitFor({state:'attached'});
    await page.locator('[data-model]').selectOption('evelyn-lite-v1:latest');await page.locator('[data-select]').click();
    await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.includes('Active: evelyn-lite-v1:latest'));
    const chat=async text=>{const before=await page.locator('[data-history] .message-assistant').count();
        await page.locator('[data-text]').fill(text);await page.locator('[data-chat]').evaluate(el=>el.requestSubmit());
        await page.waitForFunction(n=>document.querySelectorAll('[data-history] .message-assistant').length>n&&document.querySelector('[data-cancel]').hidden,before,{timeout:15000});};
    for(const text of ['What is my heart rate?','And how long have we been at it?','Tell me something calm.'])await chat(text);
    const identity=async()=>({history:await page.locator('[data-history]').innerText(),model:await page.locator('[data-selected]').textContent(),
        character:await page.locator('#character-panel').getAttribute('data-character'),name:await page.locator('#ai-companion [data-name]').textContent()});
    const baseline=await identity();
    await shot('closed-1920.png');

    // 2. Loading media opens nothing, and is not acknowledged as the participant's selection.
    await fetch(observerUrl+'/fixture/event-policy/fast',{method:'POST'});
    const assistantBefore=await page.locator('[data-history] .message-assistant').count(),frameFrom=frames.length;
    const selectionRepliesBefore=(await (await fetch(observerUrl+'/fixture/state')).json()).selection_replies.length;
    await page.locator('#playerFileInput').setInputFiles([path.join(root,'tools/fixtures/smoke-clip.webm'),path.join(root,'tools/fixtures/smoke-clip.funscript')]);
    await page.waitForFunction(()=>!document.getElementById('playerFollowRow')?.classList.contains('hidden'),null,{timeout:8000});
    assert((await status()).mode==='script','Loading a funscript did not select Script (upstream behaviour)');
    const deadline=Date.now()+6000;let media=null;
    while(Date.now()<deadline&&!media){media=frames.slice(frameFrom).find(f=>(f.events||[]).some(e=>e.kind==='experience_changed'));if(!media)await sleep(100);}
    assert(media&&media.snapshot.details.selection_source==='media','Media-caused play-style change not labelled media: '+JSON.stringify(media?.snapshot?.details));
    await sleep(4000);
    assert((await (await fetch(observerUrl+'/fixture/state')).json()).selection_replies.length===selectionRepliesBefore,'Director acknowledged loading media as a play-style selection');
    l=await layout();assert(l.player==='off'&&l.workspaceHidden,'Loading media opened the player');
    report.steps.push('Loading video + funscript keeps the player closed; the Script change is labelled media and gets no selection acknowledgement');
    // A genuine selection is still acknowledged.
    const selectionFrom=frames.length,selectionBaseline=await page.locator('[data-history] .message-assistant').count();
    await page.locator('#playerFollowScript').evaluate(el=>{el.checked=false;el.dispatchEvent(new Event('change',{bubbles:true}));});
    await page.waitForFunction(n=>document.querySelectorAll('[data-history] .message-assistant').length>n,selectionBaseline,{timeout:15000})
        .catch(()=>{throw new Error('A genuine play-style selection was not acknowledged');});
    const selected=frames.slice(selectionFrom).find(f=>(f.events||[]).some(e=>e.kind==='experience_changed'));
    assert(selected?.snapshot.details.selection_source==='selection','Participant selection not labelled selection');
    await page.locator('#playerFollowScript').evaluate(el=>{el.checked=true;el.dispatchEvent(new Event('change',{bubbles:true}));});
    assert((await status()).mode==='script','Follow the script did not return to Script');
    // Manual Play Style and Session Endgame choices keep their normal Director events.
    const pickCard=async sel=>{const card=page.locator(sel);if(await card.isHidden())await page.locator('#playStyleToggle').click();await card.click();};
    const manual=async(sel,kind,check)=>{
        const from=frames.length,count=await page.locator('[data-history] .message-assistant').count();
        await pickCard(sel);assert(await check(),'Manual '+sel+' did not apply');
        await page.waitForFunction(n=>document.querySelectorAll('[data-history] .message-assistant').length>n,count,{timeout:15000})
            .catch(()=>{throw new Error('Manual '+sel+' was not acknowledged by the Director; diag='+JSON.stringify(diagnostics.slice(-8).map(d=>[d.last_event,d.event_priority,d.director_decision,d.pending_events]))+' frames='+JSON.stringify(frames.slice(from).filter(f=>(f.events||[]).length).map(f=>({ev:f.events.map(e=>e.kind),src:f.snapshot?.details?.selection_source,exp:f.snapshot?.experience}))));});
        const event=frames.slice(from).find(f=>(f.events||[]).some(e=>e.kind===kind));
        assert(event?.snapshot.details.selection_source==='selection','Manual '+sel+' not labelled selection: '+JSON.stringify(event?.snapshot?.details));
    };
    const engine=()=>page.evaluate(async()=>{const{state}=await import('/src/js/state.js');return {mode:state.teaseMode,goal:state.gameMode};});
    const goalBefore=(await engine()).goal;
    await manual('[data-mode="headplay"]','experience_changed',async()=>(await engine()).mode==='headplay');
    await manual('[data-mode="survival"]','goal_changed',async()=>(await engine()).goal!==goalBefore);
    await manual('[data-mode="goal-off"][data-endgame="orgasm"]','goal_changed',async()=>(await engine()).goal===goalBefore);
    await page.locator('#playerFollowScript').evaluate(el=>{el.checked=true;el.dispatchEvent(new Event('change',{bubbles:true}));});
    assert((await status()).mode==='script','Follow the script did not return to Script after manual choices');
    report.steps.push('Manual Play Style (Head Play) and Session Endgame (Survival, back to Orgasm) choices are labelled selection and acknowledged by the Director');
    await fetch(observerUrl+'/fixture/event-policy/normal',{method:'POST'});
    report.steps.push('A participant play-style selection is still labelled selection and acknowledged by the Director');

    // 3. Session and playback start with the player closed; nothing opens it.
    await page.locator('#cardHandy').click();await page.locator('#modalHandyInput').fill('F2-MOCK-KEY');
    await page.locator('#modalHandyConnectBtn').click();await page.waitForTimeout(900);
    if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
    await page.locator('#sessionPlayPauseBtn').evaluate(el=>el.click());
    await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';});
    await page.evaluate(()=>{const v=document.getElementById('playerVideo');v.muted=true;return v.play().catch(()=>{});});
    await sleep(1200);
    l=await layout();assert(l.player==='off'&&l.workspaceHidden,'Starting the session or playback opened the player');
    report.steps.push('Starting the session and video playback leaves the player closed');

    const media0=()=>page.evaluate(async()=>{const v=document.getElementById('playerVideo');const{state}=await import('/src/js/state.js');
        return {same:v===window.__video&&document.getElementById('playerStage')===window.__stage,src:v.currentSrc,paused:v.paused,time:v.currentTime,
            follow:document.getElementById('playerFollowScript').checked,mode:state.teaseMode,primary:document.getElementById('playerPrimaryConfigName')?.textContent};});
    const stopsBefore=handy.filter(p=>p.endsWith('/hamp/stop')).length;
    // 4. Open with Player, close with Close player, several times; nothing else changes.
    for(let cycle=0;cycle<3;cycle++){
        const before=await media0();
        await page.locator('#playerHeaderBtn').click();
        l=await layout();
        assert(l.player==='on'&&!l.workspaceHidden,'Player did not open from the Player button');
        assert(l.stage&&l.center&&l.stage.x>=l.center.x-1&&l.stage.x+l.stage.w<=l.center.x+l.center.w+1,'Video is not inside the conversation column: '+JSON.stringify(l));
        assert(l.stage.x>=l.session.x+l.session.w,'Video overlaps the Session column');
        assert(l.picture.h>=300&&Math.abs(l.picture.w/l.picture.h-16/9)<0.05,'Video area too small or wrong aspect: '+JSON.stringify(l.picture));
        assert(l.historyHeight>=96&&l.fontSize>=14&&l.textareaUsable,'Conversation not usable under the video: '+JSON.stringify(l));
        assert(await hit('[data-send]')==='clickable','Send not reachable under the video');
        if(cycle===0){await shot('open-1920.png');await chat('Can you still hear me while I watch?');
            assert(await page.evaluate(()=>{const h=document.querySelector('[data-history]'),m=[...h.querySelectorAll('.message')].at(-1).getBoundingClientRect(),r=h.getBoundingClientRect();return m.bottom<=r.bottom+2&&m.top>=r.top-2;}),'Newest message not visible under the video');
            }
        const during=await media0();
        assert(during.same&&during.src===before.src&&during.paused===before.paused&&during.follow===before.follow&&during.mode===before.mode&&during.primary===before.primary,'Opening changed media state: '+JSON.stringify({before,during}));
        if(cycle%2===0)await page.locator('[data-close-player]').click();else await page.locator('#playerHeaderBtn').click();
        l=await layout();assert(l.player==='off'&&l.workspaceHidden,'Player did not close');
        const after=await media0();
        assert(after.same&&after.src===before.src&&after.paused===before.paused&&after.follow===before.follow&&after.mode===before.mode,'Closing changed media state: '+JSON.stringify({before,after}));
        assert((await status()).status==='RUNNING','Opening/closing the player changed the session');
    }
    assert(handy.filter(p=>p.endsWith('/hamp/stop')).length===stopsBefore,'Opening/closing the player sent a hardware stop');
    const now=await identity();
    assert(now.model===baseline.model&&now.character===baseline.character&&now.name===baseline.name&&now.history.startsWith(baseline.history.trim().slice(0,200))&&now.history.includes('Can you still hear me while I watch?'),'Conversation or companion changed across open/close');
    l=await layout();assert(l.historyHeight>=400,'Conversation did not return to full height: '+l.historyHeight);
    await shot('closed-after-cycles-1920.png');
    report.steps.push('Three open/close cycles (Player button and Close player): same video element, media, script, companion, model and history; session keeps running; no hardware stop');
    // 4b. Playback itself continues across open/close: still playing, position never reset.
    await page.evaluate(()=>{const v=document.getElementById('playerVideo');v.currentTime=0;return v.play().catch(()=>{});});
    await page.waitForFunction(()=>{const v=document.getElementById('playerVideo');return !v.paused&&v.currentTime>0.1;});
    const p0=await media0();await page.locator('#playerHeaderBtn').click();await sleep(250);
    const p1=await media0();await page.locator('[data-close-player]').click();await sleep(250);const p2=await media0();
    assert(p1.same&&p2.same&&!p0.paused&&!p1.paused&&!p2.paused&&p1.time>p0.time&&p2.time>p1.time&&p2.src===p0.src,'Open/close interrupted playback: '+JSON.stringify({p0,p1,p2}));
    assert((await status()).status==='RUNNING','Playback open/close changed the session');
    report.steps.push(`Playback continues across open/close: playing throughout, position ${p0.time.toFixed(2)}s -> ${p1.time.toFixed(2)}s -> ${p2.time.toFixed(2)}s, same element and source`);

    // 5. Theater: over the columns, under the header; Escape returns to the open player.
    await page.locator('#playerHeaderBtn').click();
    await page.locator('#playerTheaterBtn').click();await sleep(400);
    const theater=await page.evaluate(()=>{const r=document.getElementById('playerStage').getBoundingClientRect(),nav=document.querySelector('.companion-nav').getBoundingClientRect();
        return {theater:document.getElementById('playerStage').dataset.theater,w:r.width,h:r.height,top:r.top,navBottom:nav.bottom,vw:innerWidth,vh:innerHeight};});
    assert(theater.theater==='on'&&theater.w>=theater.vw*0.95&&theater.h>=theater.vh*0.75&&theater.top>=theater.navBottom,'Theater is confined or covers the header: '+JSON.stringify(theater));
    assert(await hit('#playerPicture')==='clickable','Companion panels overlap the theater picture');
    assert(await hit('#companion-dashboard [data-emergency]')==='clickable','Header Emergency stop not reachable in theater');
    assert(await hit('[data-stage-emergency]')==='clickable','In-stage Emergency stop not reachable in theater');
    assert(await hit('#sessionStopBtn')==='clickable','Engine Stop not reachable in theater');
    await shot('theater-1920.png');
    await page.keyboard.press('Escape');await sleep(300);
    l=await layout();assert(await page.locator('#playerStage').getAttribute('data-theater')==='off'&&l.player==='on','Escape did not return to the open player');
    assert((await media0()).follow&&(await status()).status==='RUNNING','Theater changed script or session state');
    report.steps.push('Theater covers the three columns below the header; header, in-stage and engine stops are clickable; Escape returns to the open player');

    // 6. Fullscreen: only the stage is rendered; its own Emergency stop must work.
    await page.locator('#playerFullscreenBtn').click();await sleep(600);
    assert(await page.evaluate(()=>document.fullscreenElement?.id)==='playerStage','Fullscreen did not take the stage');
    assert(await hit('[data-stage-emergency]')==='clickable','In-stage Emergency stop not reachable in fullscreen');
    await shot('fullscreen-1920.png');
    const stopFrom=frames.length,handyFrom=handy.length;
    await page.locator('[data-stage-emergency]').click();
    const stopped=await status();
    assert(stopped.status==='IDLE'&&stopped.primary===0&&stopped.secondary===0,'Fullscreen emergency stop did not stop the engine: '+JSON.stringify(stopped));
    await sleep(500);
    assert(handy.slice(handyFrom).some(p=>p.endsWith('/hamp/stop')),'Fullscreen emergency stop did not reach the mocked Handy');
    const deadline2=Date.now()+4000;while(Date.now()<deadline2&&!frames.slice(stopFrom).some(f=>f.snapshot?.details?.terminal_outcome==='safety_stop'))await sleep(100);
    assert(frames.slice(stopFrom).some(f=>f.snapshot?.details?.terminal_outcome==='safety_stop'),'Fullscreen emergency stop not reported as a safety stop');
    await page.evaluate(()=>document.exitFullscreen?.().catch(()=>{}));await sleep(400);
    report.steps.push('Fullscreen renders the in-stage Emergency stop; it stops the engine (IDLE, motors 0, mocked Handy stopped, safety_stop observed)');

    // 7. Theater emergency stop during a running session.
    await page.locator('#sessionPlayPauseBtn').evaluate(el=>el.click());
    await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';});
    await page.locator('#playerTheaterBtn').click();await sleep(300);
    await page.locator('[data-stage-emergency]').click();
    const theaterStop=await status();
    assert(theaterStop.status==='IDLE'&&theaterStop.primary===0,'Theater emergency stop did not stop the engine');
    await page.keyboard.press('Escape');await sleep(200);
    report.steps.push('Theater in-stage Emergency stop stops a running session');
    // Reading back is respected: an unsolicited line (the safety notice) does not pull the participant down.
    await page.locator('#sessionPlayPauseBtn').evaluate(el=>el.click());
    await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';});
    const hb=await page.locator('[data-history]').boundingBox();await page.mouse.move(hb.x+hb.width/2,hb.y+hb.height/2);await page.mouse.wheel(0,-3000);await sleep(300);
    const up=await page.evaluate(()=>document.querySelector('[data-history]').scrollTop),count=await page.locator('[data-history] .message-assistant').count();
    await page.locator('#companion-dashboard [data-emergency]').click();
    await page.waitForFunction(n=>document.querySelectorAll('[data-history] .message-assistant').length>n,count,{timeout:10000});await sleep(300);
    assert(await page.evaluate(()=>document.querySelector('[data-history]').scrollTop)===up&&await page.locator('[data-latest]').isVisible(),'A new line pulled the participant away from earlier messages');
    await page.locator('[data-latest]').click();await sleep(300);
    assert(await page.locator('[data-latest]').isHidden(),'Jump to latest did not return to the newest message');
    report.steps.push('With the player open, a participant reading back is not pulled down by a new line; Jump to latest returns');

    // 8. Responsive: laptop and phone, open and closed; no horizontal overflow, stops reachable.
    for(const [w,h] of [[1366,768],[390,844]]){
        await page.setViewportSize({width:w,height:h});await sleep(300);
        if(w===390)await page.locator('.companion-nav [data-view=chat]').click();
        l=await layout();assert(!l.overflowX,'Horizontal overflow at '+w);
        assert(await hit('#companion-dashboard [data-emergency]')==='clickable','Emergency stop hidden at '+w+' (open)');
        assert(l.player==='on'&&l.picture.h>=140&&l.historyHeight>=90&&l.textareaUsable,'Open player unusable at '+w+': '+JSON.stringify(l));
        assert(await hit('[data-send]')==='clickable'&&await hit('[data-text]')==='clickable','Message box clipped under the video at '+w+': '+await hit('[data-send]'));
        await sleep(300);assert(await page.locator('[data-latest]').isHidden(),'Conversation stopped following the newest message at '+w);
        await shot(`open-${w}.png`);
        await page.locator('[data-close-player]').click();await sleep(200);
        l=await layout();assert(l.player==='off'&&!l.overflowX,'Close failed at '+w);
        assert(await hit('[data-send]')==='clickable','Message box not reachable after closing at '+w);
        await shot(`closed-${w}.png`);
        if(w===390){await page.locator('.companion-nav [data-view=session]').click();await page.locator('#playerHeaderBtn').click();await sleep(200);
            assert(await page.locator('#companion-dashboard').getAttribute('data-view')==='chat','Opening the player on a phone did not show the video view');}
        else await page.locator('#playerHeaderBtn').click();
    }
    await page.setViewportSize({width:1920,height:1080});
    report.steps.push('1366x768 and 390x844: open and closed layouts usable, no horizontal overflow, Emergency stop reachable');

    assert(!errors.length,'Page errors: '+errors.join('\n'));
    report.steps.push('No page errors; external requests blocked: '+[...new Set(external.map(u=>new URL(u).hostname))].join(', '));
    report.passed=true;
} catch(error){report.error=String(error);if(page)await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});process.exitCode=1;}
finally {
    for(const p of children)p.kill();if(browser)await browser.close();
    await mkdir(output,{recursive:true});await writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
}
