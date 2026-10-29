// SPDX-License-Identifier: AGPL-3.0-only
// Host acceptance: original UI/engine, fake Handy, real observer, mocked Ollama.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve(new URL('../..',import.meta.url).pathname);
const output=process.env.FORK_BROWSER_REPORT||'/tmp/edgeloop-f21-browser';
const python=process.env.EDGELOOP_TEST_PYTHON||path.join(root,'.venv/bin/python');
const uiPort=process.env.FORK_BROWSER_PORT||'8770',observerPort=process.env.FORK_OBSERVER_PORT||'8768';
const uiUrl='http://127.0.0.1:'+uiPort,observerUrl='http://127.0.0.1:'+observerPort;
const token='browser-fixture-token-'+'x'.repeat(32);
const report={passed:false,steps:[],fixture:'mocked Ollama and Handy; no real hardware'};
const children=[];let browser,page;
const assert=(x,m)=>{if(!x)throw new Error(m);};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function waitServer(url){for(let i=0;i<50;i++){try{if((await fetch(url)).ok)return;}catch{}await sleep(100);}throw new Error('Local fixture server unavailable: '+url);}
try {
    await mkdir(output,{recursive:true});
    browser=await chromium.launch();
    children.push(spawn('python3',['tools/serve_local.py',uiPort],{cwd:root,stdio:'ignore'}));
    children.push(spawn(python,['tests/fork/browser_service.py'],{cwd:root,stdio:'ignore',env:{...process.env,EDGELOOP_FIXTURE_UI_PORT:uiPort,EDGELOOP_FIXTURE_OBSERVER_PORT:observerPort}}));
    await waitServer(uiUrl+'/');await waitServer(observerUrl+'/health');
    const ctx=await browser.newContext({viewport:{width:1920,height:1080}});
    await ctx.addInitScript(()=>{
        const denied=()=>Promise.reject(new DOMException('Fake-only test: permission denied','NotFoundError'));
        Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:denied},configurable:true});
        Object.defineProperty(navigator,'serial',{value:{requestPort:denied,getPorts:async()=>[]},configurable:true});
        if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=denied;
    });
    page=await ctx.newPage();const errors=[],selections=[];page.on('websocket',ws=>ws.on('framesent',event=>{try{const m=JSON.parse(event.payload);if(m.type==='select_model')selections.push(m);}catch{}}));
    page.on('pageerror',e=>errors.push(e.message));
    const handy=[];
    await page.route('**/api/handy/v2/**',async route=>{
        const p=new URL(route.request().url()).pathname;handy.push(p);
        await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(p.endsWith('/connected')?{connected:true}:p.endsWith('/info')?{fwVersion:'3.2.3',model:'Handy 1.1'}:{result:0})});
    });
    await page.goto(uiUrl+'/',{waitUntil:'load'});
    await page.locator('#ageConfirmBtn').click();
    await page.locator('#wizardOverlay').waitFor({state:'visible'});await page.locator('#wizardSkipBtn').click();
    await page.locator('#companion-dashboard').waitFor();
    assert(handy.length===0,'Hardware connected automatically');
    const missingIds=await page.evaluate(async()=>{
        const markup=await(await fetch('/index.html')).text();
        const original=new DOMParser().parseFromString(markup,'text/html');
        return [...original.querySelectorAll('[id]')].map(el=>el.id).filter(id=>!document.getElementById(id));
    });
    assert(!missingIds.length,'Original elements lost during layout: '+missingIds.join(', '));
    assert(await page.locator('#disconnectBanner').count()===1,'Original safety banner missing');
    // All original mode/goal controls retain their original listeners after reparenting.
    await page.locator('[data-mode="headplay"]').click();
    assert(await page.evaluate(async()=>{const{state}=await import('/src/js/state.js');return state.teaseMode==='headplay';}),'Experience listener lost');
    await page.locator('[data-mode="classic"]').click();
    await page.locator('[data-mode="survival"]').click();
    await page.locator('[data-mode="goal-off"]').click();
    await page.locator('#cardBle').click();await page.getByRole('button',{name:/manual simulator/i}).click();
    await page.locator('#modalSimHrSlider').evaluate(el=>{el.value='98';el.dispatchEvent(new Event('input',{bubbles:true}));});
    await page.locator('#modalEngageSimBtn').click();
    if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
    await page.locator('#cardHandy').click();await page.locator('#modalHandyInput').fill('F2-MOCK-KEY');
    await page.locator('#modalHandyConnectBtn').click();await page.waitForTimeout(900);
    if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
    await page.locator('#sessionPlayPauseBtn').click();
    await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';});
    report.steps.push('Original simulated session starts before AI');
    await page.locator('[data-url]').fill('ws://127.0.0.1:'+observerPort+'/observe');
    await page.locator('[data-token]').fill(token);await page.locator('[data-connect]').click();
    await page.waitForFunction(()=>document.querySelector('[data-telemetry]').textContent.includes('Authoritative telemetry connected'));
    await page.locator('[data-model] option[value="evelyn-lite-v1:latest"]').waitFor({state:'attached'});
    await page.locator('[data-model]').selectOption('evelyn-lite-v1:latest');await page.locator('[data-select]').click();
    await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.includes('Active: evelyn-lite-v1:latest'));
    assert(await page.locator('[data-activity-label]').textContent()==='Ready','Model readiness missing');
    assert(await page.locator('[data-thinking]').getAttribute('aria-pressed')==='false','Thinking OFF default missing');
    assert(await page.locator('.model-controls').isHidden(),'Thinking controls exposed in normal UI');
    await page.locator('[data-text]').fill('What is the current BPM?');await page.locator('[data-chat]').evaluate(el=>el.requestSubmit());
    await page.waitForFunction(()=>document.querySelector('[data-history]').textContent.includes('98 BPM'));
    assert(await page.locator('[data-setup]').isHidden(),'Pairing form remained visible');
    assert(await page.locator('[data-token]').inputValue()==='','Pairing credential retained in DOM');
    await page.screenshot({path:path.join(output,'desktop-1920.png')});
    let observed=await(await fetch(observerUrl+'/fixture/state')).json();
    assert(observed.state.hr===98&&observed.state.status==='RUNNING','Incorrect observed original state');
    assert(observed.thinking===false&&observed.last_thinking===false,'Thinking OFF missing from payload');
    report.steps.push('Thinking OFF is enforced in payloads; credentials cleared and observation accurate');
    // A bad dual field must not make a separately valid single maximum stale.
    await page.locator('#maxHr').fill('150');await page.locator('#maxHr').dispatchEvent('input');
    await page.locator('#dualMaxHr').fill('');await page.locator('#dualMaxHr').dispatchEvent('input');
    // Wait for both projection and bounded transport timers, rather than racing a fixed sleep.
    let configured;const settingsDeadline=Date.now()+6000;
    do {
        configured=await(await fetch(observerUrl+'/fixture/state')).json();
        if(configured.state?.details?.single_max_bpm===150 && configured.state?.details?.dual_max_bpm===null)break;
        await sleep(100);
    } while(Date.now()<settingsDeadline);
    assert(configured.state.details.single_max_bpm===150,'Valid setting was replaced by stale last-good limits');
    assert(configured.state.details.dual_max_bpm===null,'Invalid setting was represented as a validated value');
    await page.locator('#maxHr').fill('140');await page.locator('#maxHr').dispatchEvent('input');
    await page.locator('#dualMaxHr').fill('125');await page.locator('#dualMaxHr').dispatchEvent('input');
    report.steps.push('Current validated settings stay distinct from invalid inputs and engine fallbacks');

    assert(!JSON.stringify(observed).includes('F2-MOCK-KEY'),'Credential leak');
    assert(!JSON.stringify(observed).includes('chosenTargetSeconds'),'Hidden target leak');
    assert(observed.read_only,'Tool executor attached');report.steps.push('Contextual user response and redacted authoritative state');
    await page.locator('[data-text]').fill('thinking cutoff test');await page.locator('[data-text]').press('Enter');
    await page.waitForFunction(()=>document.querySelector('[data-history]').textContent.includes('Finished after reasoning.')&&document.querySelector('[data-cancel]').hidden);
    assert(!(await page.locator('[data-history]').textContent()).includes('UNFINISHED_DRAFT'),'Budget retry retained partial draft');
    assert(await page.locator('.message-assistant').count()===2,'Budget retry duplicated assistant bubbles');
    report.steps.push('Thinking budget retry replaces incomplete draft with one finished reply');
    await page.locator('[data-text]').fill('grounding conflict test');await page.locator('[data-text]').press('Enter');
    await page.waitForFunction(()=>document.querySelector('[data-error]').textContent.includes('conflicted'));
    assert(!(await page.locator('[data-history]').textContent()).includes('210 BPM'),'Conflicting draft remained visible');
    assert(await page.locator('.message-assistant').count()===2,'Rejected reply was committed as a bubble');
    assert(await page.evaluate(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';}),'Factual guard changed session');
    report.steps.push('Factual guard retries once and removes conflicting draft without changing session');
    // Exercise real streamed chunks and scroll anchoring using the local fixture transport.
    await page.locator('[data-text]').fill('long streaming response');
    await page.locator('[data-text]').press('Enter');
    await page.waitForFunction(()=>document.querySelector('[data-history]').scrollHeight>document.querySelector('[data-history]').clientHeight+200);
    assert(await page.locator('[data-activity-label]').textContent()==='Responding','Streaming activity not visible');
    assert(await page.locator('[data-thinking]').isDisabled(),'Thinking changed during generation');
    await page.screenshot({path:path.join(output,'responding-1920.png')});
    await page.locator('[data-history]').evaluate(el=>{el.scrollTop=0;el.dispatchEvent(new Event('scroll'));});
    await page.waitForTimeout(250);
    assert(await page.locator('[data-history]').evaluate(el=>el.scrollTop<10),'Streaming stole manual scroll position');
    await page.locator('[data-latest]').click();
    await page.locator('[data-cancel]').click();
    await page.waitForTimeout(100);
    assert(await page.locator('[data-cancel]').isHidden(),'Cancel did not complete');
    assert(await page.locator('[data-activity-label]').textContent()==='Ready','Cancel did not restore readiness');
    assert(await page.evaluate(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';}),'Cancel changed session');
    // Multiline editing and model memory are kept per model.
    await page.locator('[data-text]').fill('First line');await page.locator('[data-text]').press('Shift+Enter');
    await page.locator('[data-text]').press('x');
    assert((await page.locator('[data-text]').inputValue()).includes('\n'),'Shift+Enter did not insert newline');
    await page.locator('[data-text]').fill('');
    report.steps.push('Streaming, manual scroll preservation, jump-to-latest, cancel and multiline editing');
    for(const [width,height] of [[2560,1440],[1366,768],[768,1024],[390,844],[360,800],[375,667]]) {
        await page.setViewportSize({width,height});
        await page.waitForTimeout(100);
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Horizontal overflow at '+width);
        const composer=await page.locator('[data-chat]').boundingBox();
        assert(composer&&composer.y+composer.height<=height,'Composer outside viewport at '+width);
        await page.screenshot({path:path.join(output,'chat-'+width+'.png')});
        if(width<1500){
            await page.locator('button[data-view="character"]').click();
            assert(await page.locator('#character-panel').isVisible(),'Character not accessible');
            await page.screenshot({path:path.join(output,'character-'+width+'.png')});
            await page.locator('button[data-view="character"]').click();
        }
        if(width<=760){
            await page.locator('button[data-view="session"]').click();
            assert(await page.locator('#sessionStopBtn').isVisible(),'Session controls not accessible');
            await page.screenshot({path:path.join(output,'session-'+width+'.png')});
            await page.locator('button[data-view="chat"]').click();
        }
    }
    await page.setViewportSize({width:1920,height:1080});
    await page.locator('[data-model]').selectOption('evelyn:latest');await page.locator('[data-select]').click();
    await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.includes('Active: evelyn:latest'));
    assert(await page.evaluate(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';}),'Model selection changed original session');
    assert(await page.locator('[data-history] .message').count()===0,'Model history leaked across models');
    await page.locator('[data-model]').selectOption('evelyn-lite-v1:latest');await page.locator('[data-select]').click();
    await page.waitForFunction(()=>document.querySelector('[data-selected]').textContent.includes('Active: evelyn-lite-v1:latest'));
    assert((await page.locator('[data-history]').textContent()).includes('98 BPM'),'Conversation memory not restored');
    await page.locator('#sessionPlayPauseBtn').click();
    await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='PAUSED';});
    const pausedSeconds=await page.evaluate(async()=>{const{state}=await import('/src/js/state.js');return state.sessionSeconds;});
    await page.waitForTimeout(5500);
    const pausedObservation=await(await fetch(observerUrl+'/fixture/state')).json();
    assert(pausedObservation.state.status==='PAUSED'&&pausedObservation.state.seconds===pausedSeconds,'Observation heartbeat advanced paused session');
    assert((await(await fetch(observerUrl+'/health')).json()).observation_fresh,'Paused observation expired');
    await page.locator('#sessionPlayPauseBtn').click();
    await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';});
    await page.waitForFunction(async old=>{const{state}=await import('/src/js/state.js');return state.sessionSeconds>old;},pausedSeconds);
    await page.locator('#sessionStopBtn').click();
    assert(await page.evaluate(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='IDLE'&&state.sessionSeconds===0;}),'Stop did not reset original active counter');
    await page.locator('#sessionPlayPauseBtn').click();
    await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING'&&state.sessionSeconds<=2;});
    report.steps.push('Original timing: running ticks, frozen pause, resumed ticks, stop zero and fresh restart');
    await fetch(observerUrl+'/fixture/ollama-down',{method:'POST'});
    await page.locator('[data-refresh]').click();
    await page.waitForFunction(()=>document.querySelector('[data-error]').textContent.includes('discovery unavailable'));
    assert(await page.locator('[data-select]').isDisabled(),'Discovery failure leaves invalid model selectable');
    assert(await page.locator('[data-model]').inputValue()==='','Discovery placeholder is a model value');
    const before=selections.length;await page.locator('[data-select]').evaluate(el=>el.dispatchEvent(new Event('click')));
    await page.waitForTimeout(100);assert(selections.length===before,'Invalid placeholder model request escaped guard');
    report.steps.push('Disconnected Ollama cannot produce a placeholder model request');
    await page.locator('[data-disconnect]').click();children[1].kill();
    const seconds=await page.evaluate(async()=>{const{state}=await import('/src/js/state.js');return state.sessionSeconds;});
    await page.waitForTimeout(1500);
    assert(await page.evaluate(async old=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING'&&state.sessionSeconds>old;},seconds),'Backend outage interrupted original clock');
    await page.locator('[data-emergency]').click();
    assert(await page.evaluate(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='IDLE'&&state.strokerSpeed===0;}),'Original stop failed');
    assert(handy.includes('/api/handy/v2/hamp/stop'),'Original driver did not stop mocked Handy');
    assert(errors.length===0,errors.join('\n'));report.steps.push('Model switch, backend disconnect and original Stop remain independent');
    await page.screenshot({path:path.join(output,'companion.png'),fullPage:true});
    // Warnings remain visible in the companion's mobile Chat view.
    await page.locator('#disconnectBanner').evaluate(el=>el.classList.remove('hidden'));
    await page.setViewportSize({width:390,height:844});
    assert(await page.locator('#disconnectBanner').isVisible(),'Safety banner hidden in Chat');
    await page.screenshot({path:path.join(output,'safety-banner-390.png')});
    await page.locator('#dismissBannerBtn').click();
    assert(await page.locator('#disconnectBanner').isHidden(),'Original warning dismiss listener lost');
    await page.setViewportSize({width:375,height:667});
    await page.waitForTimeout(100);
    const setup=await page.locator('[data-setup]').boundingBox();
    const composer=await page.locator('[data-chat]').boundingBox();
    assert(setup&&setup.height>150&&composer.y+composer.height<=667,'Mobile pairing is clipped');
    await page.screenshot({path:path.join(output,'pairing-375.png')});
    // Portrait renderer: local test pixels only, no generated character artwork.
    const portrait=await page.evaluate(async()=>{
        const {CharacterPresentation}=await import('/src/js/ai/character.js');
        const host=document.createElement('div');host.style.cssText='width:300px;height:400px';document.body.append(host);
        const pixel='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="400"><rect width="200" height="400" fill="purple"/></svg>');
        const view=new CharacterPresentation(host,{models:{'test:tag':'test'},characters:{test:{name:'Test character',expressions:{neutral:pixel,happy:'/src/assets/characters/missing.webp'}}}});
        view.setModel('test:tag');view.setState({expression:'happy',activity:'listening'});
        await new Promise(resolve=>setTimeout(resolve,350));
        const img=host.querySelector('img');
        const result={loaded:img?.naturalWidth===200,fit:img&&getComputedStyle(img).objectFit,placeholderHidden:host.querySelector('.portrait-placeholder').hidden,name:host.querySelector('[data-character-name]').textContent};host.remove();return result;
    });
    assert(portrait.loaded&&portrait.placeholderHidden&&portrait.fit==='contain'&&portrait.name==='Test character','Portrait fallback or sizing failed');
    report.steps.push('Mobile pairing and independent portrait asset fallback');report.passed=true;
} catch(error){report.error=String(error);if(page)await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});process.exitCode=1;}
finally {
    for(const p of children)p.kill();if(browser)await browser.close();
    await mkdir(output,{recursive:true});await writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
}
