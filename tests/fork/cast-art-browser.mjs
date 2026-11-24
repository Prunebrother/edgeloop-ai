// SPDX-License-Identifier: AGPL-3.0-only
// Real UI + curated cast, owned fixture with mocked model transport. No inference/hardware.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {claimPorts,ownedReady,isolatedEnv,guardBrowser} from './fixture-isolation.mjs';

const root=path.resolve(new URL('../..',import.meta.url).pathname);
const out=process.env.CAST_ART_BROWSER_REPORT||'/tmp/edgeloop-cast-art-browser';
const uiPort=8990,aiPort=8998,ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`;
const cast=['celeste','evelyn','daisy','nova','mira'];
const catalog=JSON.parse(await readFile(path.join(root,'src/assets/characters/manifest.json'),'utf8'));
const report={passed:false,expressions:[],screenshots:[],framing:[],errors:[],missing:[],external:[],responses:[],
    method:'Existing menu host chips select the real model; existing local expression preview drives the session renderer. PNG via reduced motion; first playing video frame frozen only for the handoff screenshot. Real playback then resumes and seeks near the end to verify a natural loop wrap.',
    limitations:['No physical hardware or live inference. Menu hosts and board figures use independent src/assets/menu cutouts.']};
const children=[];let browser,page;
const shot=async name=>{const file=path.join(out,name);await page.screenshot({path:file});report.screenshots.push(file);return file;};
async function media(type,id,expression){
    await page.waitForFunction(({type,id,expression})=>{
        const h=document.querySelector('#character-panel'),nodes=h.querySelectorAll('.character-art'),m=nodes[0];
        return h.dataset.character===id&&h.dataset.expression===expression&&h.dataset.artworkStatus==='intended'&&
            h.dataset.artworkType===type&&nodes.length===1&&getComputedStyle(m).opacity==='1'&&
            (type==='video'?m.readyState>=2&&m.videoWidth===1024&&m.videoHeight===1536:m.naturalWidth===1024&&m.naturalHeight===1536);
    },{type,id,expression});
}
async function compareScreenshots(still,clip){
    return page.evaluate(async urls=>{
        const images=await Promise.all(urls.map(src=>new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src=src;})));
        const [a,b]=images;if(a.width!==b.width||a.height!==b.height)throw Error('Portrait screenshot geometry changed');
        const c=document.createElement('canvas');c.width=a.width;c.height=a.height;const ctx=c.getContext('2d',{willReadFrequently:true});
        ctx.drawImage(a,0,0);const x=ctx.getImageData(0,0,c.width,c.height).data;ctx.clearRect(0,0,c.width,c.height);ctx.drawImage(b,0,0);
        const y=ctx.getImageData(0,0,c.width,c.height).data;let total=0,max=0,large=0;
        for(let i=0;i<x.length;i++){if(i%4===3)continue;const d=Math.abs(x[i]-y[i]);total+=d;max=Math.max(max,d);if(d>12)large++;}
        const count=c.width*c.height*3;return {mean:total/count,max,large_difference_fraction:large/count,width:c.width,height:c.height};
    },[still,clip].map(buffer=>'data:image/png;base64,'+buffer.toString('base64')));
}
async function contactSheet(){
    const data=await page.evaluate(async({cast,catalog})=>{
        const cellW=180,cellH=296,canvas=document.createElement('canvas');canvas.width=12*cellW;canvas.height=5*cellH;
        const ctx=canvas.getContext('2d');ctx.fillStyle='#101420';ctx.fillRect(0,0,canvas.width,canvas.height);
        for(let row=0;row<cast.length;row++)for(let col=0;col<catalog.expressions.length;col++){
            const id=cast[row],expression=catalog.expressions[col],image=new Image();image.src=catalog.characters[id].expressions[expression];await image.decode();
            ctx.drawImage(image,col*cellW+4,row*cellH+24,172,258);
            ctx.fillStyle='#ffffff';ctx.font='12px sans-serif';ctx.fillText(`${catalog.characters[id].name} · ${expression}`,col*cellW+4,row*cellH+16);
        }
        return canvas.toDataURL('image/png').split(',')[1];
    },{cast,catalog});
    const file=path.join(out,'cast_contact_sheet.png');await writeFile(file,Buffer.from(data,'base64'));report.contact_sheet=file;
}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function framing(place,selector){
    const image=page.locator(selector).first();await image.waitFor();await image.scrollIntoViewIfNeeded();
    await image.evaluate(async el=>{await el.decode();});
    const geometry=await image.evaluate(el=>{
        const rect=el.getBoundingClientRect(),css=getComputedStyle(el),nw=el.naturalWidth,nh=el.naturalHeight;
        const scale=css.objectFit==='cover'?Math.max(rect.width/nw,rect.height/nh):Math.min(rect.width/nw,rect.height/nh);
        return {src:el.getAttribute('src'),natural:[nw,nh],box:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},
            fit:css.objectFit,position:css.objectPosition,
            cropped:css.objectFit==='cover'&&(nw*scale>rect.width+1||nh*scale>rect.height+1),
            cropped_height_fraction:css.objectFit==='cover'?Math.max(0,1-rect.height/(nh*scale)):0,
            stretched:css.objectFit==='fill'&&Math.abs(rect.width/rect.height-nw/nh)>.01,
            outside_viewport:rect.x< -1||rect.y< -1||rect.right>innerWidth+1||rect.bottom>innerHeight+1};
    });
    const viewport=page.viewportSize(),screenshot=await shot(`evelyn-${place}-${viewport.width}x${viewport.height}.png`);
    report.framing.push({place,viewport,...geometry,screenshot});
}
const viewports=[{width:1280,height:720},{width:1920,height:1080},{width:390,height:844}];
async function frameAtAllSizes(place,selector){for(const size of viewports){await page.setViewportSize(size);await framing(place,selector);}}
async function call(endpoint,body){const response=await fetch(ai+endpoint,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});assert.equal(response.status,200);return response.json();}
try{
    await mkdir(out,{recursive:true});await claimPorts(uiPort,aiPort);
    const env=isolatedEnv({EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(aiPort),
        EDGELOOP_FIXTURE_EXTRA_MODELS:Object.entries(catalog.models).filter(([,id])=>cast.includes(id)).map(([m])=>m).join(',')});
    delete env.PYTHONPATH;env.EDGELOOP_CAMPAIGN_FIXTURE_DATA=path.join(env.XDG_RUNTIME_DIR,'campaign');
    children.push(spawn('python3',['tools/serve_local.py',String(uiPort)],{cwd:root,env,stdio:'ignore'}));
    children.push(spawn(path.join(root,'.venv/bin/python'),['-m','tests.fork.campaign_browser_service'],{cwd:root,env,stdio:'ignore'}));
    await ownedReady(ui,children);await ownedReady(ai+'/health',children);
    browser=guardBrowser(await chromium.launch(),[uiPort,aiPort]);
    const context=await browser.newContext({viewport:{width:1920,height:1080},serviceWorkers:'block',reducedMotion:'reduce'});
    await context.route('**/*',route=>{
        const url=new URL(route.request().url());
        if(![ui,ai].includes(url.origin)){report.external.push(url.href);return route.abort();}
        return route.fallback();
    });
    await context.routeWebSocket(url=>![ui.replace('http:','ws:'),ai.replace('http:','ws:')].includes(url.origin),ws=>{report.external.push(ws.url());ws.close();});
    await context.addInitScript(()=>{
        const no=()=>Promise.reject(new DOMException('Cast-art fixture has no hardware','NotFoundError'));
        Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:no},configurable:true});
        Object.defineProperty(navigator,'serial',{value:{requestPort:no,getPorts:async()=>[]},configurable:true});
        if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=no;
        const play=HTMLMediaElement.prototype.play;
        // Keep the first successful decoded frame still while the real renderer
        // commits it and finishes its fade. Restore actual playback below.
        HTMLMediaElement.prototype.play=function(...args){return play.apply(this,args).then(result=>{
            if(window.freezeCastStart&&this.classList.contains('character-art'))this.pause();return result;
        });};
    });
    page=await context.newPage();
    page.on('pageerror',error=>report.errors.push(error.message));
    page.on('console',message=>{if(message.type()==='error')report.errors.push(message.text());});
    page.on('response',response=>{
        const url=new URL(response.url());if(response.status()>=400)report.missing.push({url:url.pathname,status:response.status()});
        if(url.pathname.startsWith('/Character_Art/'))report.responses.push({path:url.pathname,status:response.status()});
    });
    page.on('requestfailed',request=>{if(request.failure()?.errorText!=='net::ERR_ABORTED')report.errors.push(request.url()+': '+request.failure()?.errorText);});
    await page.goto(ui+'/?characterPreview=1');await page.locator('#ageConfirmBtn').click();await page.locator('#wizardSkipBtn').click();
    await page.locator('[data-menu-tile=freeplay]').click();
    await page.locator('[data-url]').fill(ai.replace('http:','ws:')+'/observe');await page.locator('[data-token]').fill('browser-fixture-token-'+'x'.repeat(32));
    await page.locator('[data-connect]').click();await page.locator('[data-model] option[value="nova-narrative-v1:latest"]').waitFor({state:'attached'});
    for(const id of cast){
        await page.emulateMedia({reducedMotion:'reduce'});
        await page.locator('[data-main-menu]').click();await page.locator(`.menu-host-chips [data-host=${id}]`).click();
        await page.waitForFunction(id=>document.querySelector('[data-selected]').textContent.toLowerCase().includes(id),id);
        await page.locator('[data-menu-tile=freeplay]').click();await media('image',id,'neutral');
        await shot(`${id}-neutral-session.png`);
        await page.locator('.character-preview summary').click();await page.locator('[data-preview-character]').selectOption(id);
        for(const expression of catalog.expressions){
            const record={character:id,expression,png:catalog.characters[id].expressions[expression],webm:catalog.characters[id].animations[expression].webm};
            report.expressions.push(record);
            await page.emulateMedia({reducedMotion:'reduce'});await page.locator('[data-preview-expression]').selectOption(expression);await media('image',id,expression);
            record.png_screenshot=path.join(out,`${id}-${expression}-png.png`);
            const still=await page.locator('#character-panel .portrait-stage').screenshot({path:record.png_screenshot});
            assert(report.responses.some(r=>r.path===record.png&&r.status===200),`PNG not served with 200: ${record.png}`);
            record.png_size=await page.locator('#character-panel img.character-art').evaluate(im=>[im.naturalWidth,im.naturalHeight]);
            await page.evaluate(()=>{window.freezeCastStart=true;});await page.emulateMedia({reducedMotion:'no-preference'});await media('video',id,expression);
            record.video_screenshot=path.join(out,`${id}-${expression}-video.png`);
            const clip=await page.locator('#character-panel .portrait-stage').screenshot({path:record.video_screenshot});
            record.handoff=await compareScreenshots(still,clip);
            assert(record.handoff.mean<=3,`Visible PNG/video jump: ${id}/${expression}, mean ${record.handoff.mean}`);
            assert(report.responses.some(r=>r.path===record.webm&&[200,206].includes(r.status)),`WebM request failed: ${record.webm}`);
            record.video=await page.locator('#character-panel video').evaluate(async(video,checkWrap)=>{
                window.freezeCastStart=false;await video.play();
                const start=video.currentTime;await new Promise(resolve=>setTimeout(resolve,180));
                const advanced=video.currentTime>start&&!video.paused;
                if(!Number.isFinite(video.duration))throw Error('Clip has no finite duration');
                // tools/serve_local.py (also the shipped web server) has no HTTP Range support, so Chromium cannot
                // seek inside a clip: a seek restarts it at 0. Check the real, natural loop instead: once per
                // companion (neutral) the clip must play past 7 s and come back to the start by itself.
                if(!checkWrap)return {readyState:video.readyState,width:video.videoWidth,height:video.videoHeight,advanced,loop:video.loop,wrapped:null,duration:video.duration};
                const wrapped=await new Promise(resolve=>{
                    let peak=0;const timer=setTimeout(()=>finish(false),video.duration*1000+4000);
                    const check=()=>{peak=Math.max(peak,video.currentTime);if(peak>video.duration-1&&video.currentTime<1)finish(true);};
                    const finish=value=>{clearTimeout(timer);video.removeEventListener('timeupdate',check);resolve(value);};
                    video.addEventListener('timeupdate',check);check();
                });
                return {readyState:video.readyState,width:video.videoWidth,height:video.videoHeight,advanced,loop:video.loop,wrapped,duration:video.duration};
            },expression==='neutral');
            assert(record.video.readyState>=2&&record.video.width===1024&&record.video.height===1536&&record.video.advanced&&record.video.loop&&record.video.wrapped!==false,JSON.stringify(record));
            record.passed=true;
        }
        await page.emulateMedia({reducedMotion:'reduce'});await page.locator('[data-preview-reset]').click();
    }
    await contactSheet();
    // Select Evelyn in the actual menu and inspect every UI surface that uses her.
    await page.locator('[data-main-menu]').click();await page.locator('.menu-host-chips [data-host=evelyn]').click();
    await page.waitForFunction(()=>document.querySelector('.menu-host-figure').dataset.host==='evelyn');
    await frameAtAllSizes('character-select-menu-host','.menu-host-figure');
    await page.locator('[data-menu-tile=freeplay]').click();
    for(const size of viewports){
        await page.setViewportSize(size);await sleep(300);if(!(await page.locator('#character-panel').isVisible()))await page.locator('button[data-view=character]').click();// the layout folds the portrait into a tab below ~1400 px, not only on phones
        await media('image','evelyn','neutral');await framing('session','#character-panel .character-art >> visible=true');
    }
    await call('/fixture/campaign/progress',{campaign:'asterion_initiative',mission:'first_assessment'});
    await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').click();await page.locator('[data-campaign=asterion_initiative]').click();
    await frameAtAllSizes('mission-board','.mission-card[data-mission=first_assessment] .board-figure');
    await page.locator('.mission-card[data-mission=first_assessment] button').click();await page.locator('.mission-detail').getByRole('button',{name:'Start mission',exact:true}).click();
    await page.locator('.mission-speech img[alt=Evelyn]').waitFor();await frameAtAllSizes('mission-briefing','.mission-speech img[alt=Evelyn]');
    await page.getByRole('button',{name:'Begin with Evelyn',exact:true}).click();await page.locator('#main-menu').waitFor({state:'hidden'});
    const evidence=edges=>({session_id:'5e3d0c3a-0000-4000-8000-00000000c076',status:'RUNNING',edges,active_mode:'classic',goal:'tease',
        devices:{hr_ready:true,ble:true,simulated_hr:false,toy_ready:true},details:{orgasm_count:0,calibration_pass:'none'}});
    await call('/fixture/campaign/evidence',{reports:[evidence(0),evidence(5)]});
    await page.waitForFunction(()=>document.querySelector('#main-menu').dataset.view==='results');
    await frameAtAllSizes('mission-results','.mission-speech img[alt=Evelyn]');
    report.framing_problems=report.framing.filter(f=>f.cropped||f.stretched||f.outside_viewport);
    assert.equal(report.framing_problems.length,0,'Evelyn framing problems; see report.framing_problems and screenshots (art/app left unchanged)');
    // Optional probes the app makes and handles when absent: the desktop build's app file, desktop auto-pairing
    // (manual WebSocket pairing is used here) and the per-campaign story art registry (Asterion has none).
    const OPTIONAL=new Set(['/edgeloop-app.json','/ai/pair','/src/assets/story/asterion_initiative/ASSETS.json']);
    report.missing=report.missing.filter(m=>!OPTIONAL.has(m.url));
    // Resource failures are already checked through report.missing (by path); the console line has no URL.
    report.errors=report.errors.filter(e=>!e.startsWith('Failed to load resource:'));
    assert.deepEqual(report.errors,[]);assert.deepEqual(report.missing,[]);assert.deepEqual(report.external,[]);assert.deepEqual(browser.isolationViolations,[]);
    report.passed=true;
}catch(error){report.error=String(error.stack||error);if(page)await shot('failure.png').catch(()=>{});process.exitCode=1;}
finally{
    await browser?.close();for(const child of children)child.kill();await mkdir(out,{recursive:true});
    await writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify({passed:report.passed,expressions:report.expressions.length,error:report.error,output:out}));
}
