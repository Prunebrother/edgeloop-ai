// SPDX-License-Identifier: AGPL-3.0-only
// Every rendered Helix mission keeps the player's controls; real scripted steps use the ordinary browser gate.
import {suite,assert,until} from './helix-browser-fixture.mjs';
await suite({name:'helix-safety-browser',uiPort:8922,aiPort:8928},async h=>{
    const {page}=h,book=await h.call('/fixture/helix/book'),helix=book.campaigns.find(c=>c.id==='rise_of_helix');
    assert(helix?.missions.length,'No shipped Helix missions');await h.hardware();
    const seed=id=>h.call('/fixture/helix/seed',{mission:id});
    await seed(helix.missions[0].id);await h.openCampaign(helix.id);
    const rendered=new Map(),tabs=await page.locator('.board-chapters button[data-chapter]').evaluateAll(es=>es.map(e=>e.dataset.chapter));
    for(const chapter of tabs.length?tabs:[null]){
        if(chapter)await page.locator(`.board-chapters button[data-chapter="${chapter}"]`).click();
        for(const id of await page.locator('.mission-card[data-mission]').evaluateAll(es=>es.map(e=>e.dataset.mission)))rendered.set(id,chapter);
    }
    assert(rendered.size===helix.missions.length,'Rendered board omitted a shipped mission');
    await page.locator('.board-hero .game-menu-back').click();await page.locator('.game-menu-back').click();await page.locator('[data-menu-tile=freeplay]').click();
    const controls=async label=>{
        for(const selector of ['#sessionStopBtn','#sessionPlayPauseBtn','[data-emergency]']){
            assert(await page.locator(selector).count()>0,label+': missing '+selector);
            assert(await page.locator(selector).first().isEnabled(),label+': disabled '+selector);
        }
    };
    const engineStatus=status=>page.waitForFunction(async target=>(await import('/src/js/state.js')).state.sessionStatus===target,status);
    const prepare=async id=>{await seed(id);await h.openCampaign(helix.id);const chapter=rendered.get(id);if(chapter)await page.locator(`.board-chapters button[data-chapter="${chapter}"]`).click();await h.start(id);};
    let photographed=false;
    for(const [id] of rendered){
        const mission=helix.missions.find(m=>m.id===id);await prepare(id);
        await h.defect(id+' briefing controls',()=>controls(id+' briefing'));
        if(await page.locator('[data-play-scene]').count()){
            await page.locator('[data-play-scene]').click();await h.view('scene');
            await h.defect(id+' scene controls',()=>controls(id+' scene'));await page.keyboard.press('Escape');await h.view('briefing');
        }
        await h.begin();const snapshot=await h.startEngine();await controls(id+' active banner');
        const choice=mission.objectives.find(o=>o.choice);
        if(choice){
            await h.call('/fixture/helix/advance',{session_id:snapshot.session_id,choice:choice.id});
            await page.waitForFunction(oid=>document.querySelector(`[data-choice-objective="${oid}"] button:not([disabled])`),choice.id);
            await controls(id+' waiting choice');
        }
        if(!photographed){
            await h.shot('helix-active-controls.png');await page.setViewportSize({width:390,height:844});
            await h.shot('helix-active-controls-phone.png');await page.setViewportSize({width:1440,height:1000});photographed=true;
        }
        await page.locator('#sessionPlayPauseBtn').click();await engineStatus('PAUSED');await controls(id+' paused');
        await page.locator('#sessionPlayPauseBtn').click();await engineStatus('RUNNING');
        await page.locator('[data-emergency]').first().click();await engineStatus('IDLE');
        await h.startEngine();await page.locator('#sessionStopBtn').click();await engineStatus('IDLE');
        const before=JSON.parse((await h.call('/fixture/campaign')).saved).campaigns;
        await page.waitForFunction(()=>!document.querySelector('[data-main-menu]').disabled);await page.locator('[data-main-menu]').click();
        page.once('dialog',dialog=>dialog.accept());await page.locator('[data-menu-tile=freeplay]').click();await page.locator('#main-menu').waitFor({state:'hidden'});
        await until(async()=>JSON.parse((await h.call('/fixture/campaign')).saved).active===null,'Freeplay did not leave '+id);
        const after=JSON.parse((await h.call('/fixture/campaign')).saved).campaigns;
        for(const [cid,record] of Object.entries(before))assert(JSON.stringify(after[cid].missions)===JSON.stringify(record.missions),'Freeplay lost completed missions in '+cid);
        h.report.steps.push(id+': briefing/scene controls checked, Pause/Resume/Emergency/Stop work, Freeplay preserves completions');
    }
    // Values in the settings panel are slider points: 10–40 is the reported 60–90 percent band.
    for(const kind of ['fixed','floor']){
        const mission=helix.missions.find(m=>m.objectives.some(o=>o.stages.some(s=>s.set_to&&(kind==='fixed'?s.intensity:s.raise_to)>90)));
        assert(mission,'No shipped '+kind+' step above the test band');
        const objective=mission.objectives.find(o=>o.stages.some(s=>s.set_to&&(kind==='fixed'?s.intensity:s.raise_to)>90));
        const stage=objective.stages.find(s=>s.set_to&&(kind==='fixed'?s.intensity:s.raise_to)>90),key=objective.id+':'+stage.id;
        await prepare(mission.id);await h.begin();
        if(!await page.locator('[data-ai-settings-enabled]').isVisible())await page.locator('[data-ai-settings] summary').first().click();
        for(const [field,value] of [['intensity_min','10'],['intensity_max','40']]){await page.locator(`[data-ai-settings-field="${field}"]`).fill(value);await page.locator(`[data-ai-settings-field="${field}"]`).dispatchEvent('change');}
        await page.locator('[data-ai-settings-enabled]').check();
        await page.locator('#intensitySlider').evaluate(el=>{el.value='10';el.dispatchEvent(new Event('input',{bubbles:true}));});
        const snapshot=await h.startEngine(),before=h.sent.length;
        const result=await h.call('/fixture/helix/advance',{session_id:snapshot.session_id,step:key});
        assert(result.delivered.some(d=>d.scripted&&d.key===key),'Fixture never reached scripted '+key);
        await h.defect(kind+' step honors 60–90 percent band',async()=>{
            await until(()=>h.sent.slice(before).some(m=>m.type==='settings_outcome'&&m.status==='applied'),'No applied outcome for '+key);
            const applied=h.sent.slice(before).filter(m=>m.type==='settings_outcome'&&m.status==='applied');
            assert(applied.length>0&&applied.every(m=>m.to>=10&&m.to<=40),'Applied step left the user band: '+JSON.stringify(applied));
            assert(applied.some(m=>m.clamped===true),'Step was not reported as clamped');
            assert((await h.engine()).percent>=60&&(await h.engine()).percent<=90,'Engine left 60–90 percent band');
        });
        await page.locator('#sessionStopBtn').click();await engineStatus('IDLE');
    }
});
