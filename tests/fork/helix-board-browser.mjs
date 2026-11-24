// SPDX-License-Identifier: AGPL-3.0-only
// Remaining HELIX-070 gaps: campaign identity/reload, unlock notice, conditions, optional goals and floor presentation.
import {suite,assert,until} from './helix-browser-fixture.mjs';
await suite({name:'helix-board-browser',uiPort:8932,aiPort:8938,env:{EDGELOOP_HELIX_BOARD_FIXTURE:'1'}},async h=>{
    const {page}=h,book=await h.call('/fixture/helix/book'),HID='rise_of_helix',CID='asterion_initiative',BID='fixture_helix_board';
    const helix=book.campaigns.find(c=>c.id===HID),asterion=book.campaigns.find(c=>c.id===CID);
    const first=min=>min.missions.reduce((a,b)=>a.order<b.order?a:b),last=asterion.missions.reduce((a,b)=>a.order>b.order?a:b);
    const seed=(campaign,mission,flags={})=>h.call('/fixture/helix/seed',{campaign,mission,flags});
    const closeMenu=async()=>{
        for(let i=0;i<5&&await page.locator('#main-menu').isVisible()&&(await page.locator('#main-menu').getAttribute('data-view'))!=='home';i++)await page.keyboard.press('Escape');
        if(await page.locator('#main-menu').isVisible()){
            const active=JSON.parse((await h.call('/fixture/campaign')).saved).active;
            if(active)page.once('dialog',dialog=>dialog.accept());
            await page.locator('[data-menu-tile=freeplay]').focus();await page.keyboard.press('Enter');await page.locator('#main-menu').waitFor({state:'hidden'});
        }
    };
    const photo=async name=>{await h.shot(name);};
    const fits=async()=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('#main-menu,.mission-banner')].filter(e=>!e.hidden).every(e=>e.scrollWidth<=e.clientWidth)),'Horizontal overflow at 390px');
    await seed(HID,first(helix).id);
    await page.locator('[data-main-menu]').click();await page.locator('[data-menu-tile=campaign]').focus();await page.keyboard.press('Enter');await h.view('campaigns');
    assert(await page.locator(`[data-campaign="${CID}"]`).count()===1&&await page.locator(`[data-campaign="${HID}"]`).count()===1,'Two real campaign cards are not present together');
    await photo('two-campaigns.png');
    await h.defect('Gamepad campaign selection',async()=>{
        await page.locator(`[data-campaign="${CID}"]`).focus();
        await h.pad(15,()=>page.waitForFunction(id=>document.activeElement?.dataset.campaign===id,HID,{timeout:1000}));
    });
    await page.locator(`[data-campaign="${CID}"]`).focus();await page.keyboard.press('Enter');await h.view('missions');
    const astIds=await page.locator('.mission-card[data-mission]').evaluateAll(es=>es.map(e=>e.dataset.mission));
    assert(astIds.length>0&&astIds.every(id=>asterion.missions.some(m=>m.id===id)),'Asterion opened another campaign board');await photo('asterion-board.png');
    await page.locator('.board-hero .game-menu-back').click();await page.locator(`[data-campaign="${HID}"]`).focus();await page.keyboard.press('Enter');await h.view('missions');
    const helixIds=await page.locator('.mission-card[data-mission]').evaluateAll(es=>es.map(e=>e.dataset.mission));
    assert(helixIds.length>0&&helixIds.every(id=>helix.missions.some(m=>m.id===id)),'Helix opened another campaign board');await photo('helix-board.png');
    await page.locator(`.mission-card[data-mission="${first(helix).id}"] button`).focus();await page.keyboard.press('Enter');
    await page.locator('.mission-detail').getByRole('button',{name:'Start mission',exact:true}).focus();await page.keyboard.press('Enter');await h.view('briefing');
    const beforeReload=h.received.length;await page.reload();await h.connect();
    await until(()=>h.received.slice(beforeReload).some(m=>m.type==='campaign_state'&&m.active?.campaign===HID&&m.active?.mission===first(helix).id),'Active campaign/mission did not survive reload');
    await h.openCampaign(HID);await page.locator('.mission-detail').getByRole('button',{name:'Continue',exact:true}).focus();await page.keyboard.press('Enter');await h.view('briefing');
    await photo('active-campaign-after-reload.png');await closeMenu();
    h.report.steps.push('Two real campaigns open their own boards; keyboard start and active mission survive reload');

    await seed(CID,last.id);await h.openCampaign(CID);await h.start(last.id);await h.begin();
    const tick=(seconds,edges=0)=>({session_id:'5e3d0c3a-0000-4000-8000-00000000c070',status:'RUNNING',seconds,edges,active_mode:'classic',experience:'classic',intensity:60,goal:'tease',devices:{hr_ready:true,ble:true,simulated_hr:false,toy_ready:true},details:{orgasm_count:0,captured_at_ms:1793000000000+seconds*1000}});
    await h.call('/fixture/campaign/evidence',{reports:[tick(0),tick(1,1)]});await h.view('results');
    await h.defect('Asterion completion offers the Helix unlock notice',async()=>{
        await page.waitForFunction(()=>[...document.querySelectorAll('.mission-toast,#main-menu')].some(e=>e.textContent.includes('New campaign: Rise of Helix')),null,{timeout:3000});
        assert(h.received.some(m=>m.type==='mission_result'&&m.unlocked_campaigns?.some(c=>c.id===HID)),'Completion did not unlock Helix');
    });
    await photo('helix-unlock-notice.png');await closeMenu();

    await seed(BID,'floor_path',{bonus:'shown'});await h.openCampaign(BID);
    for(const [id,reason] of [['locked_path','An analyst must vouch for you.'],['generic_path','Not available on this story path.']]){
        const starts=h.sent.filter(m=>m.type==='campaign'&&m.action==='start').length;
        await page.locator(`.mission-card[data-mission="${id}"] button`).focus();await page.keyboard.press('Enter');
        assert((await page.locator('.mission-detail').textContent()).includes(reason),'Missing when lock reason for '+id);
        assert(await page.locator('.mission-detail').getByRole('button',{name:'Start mission',exact:true}).count()===0,'Locked mission offers Start');
        await page.keyboard.press('Enter');assert(h.sent.filter(m=>m.type==='campaign'&&m.action==='start').length===starts,'Keyboard started a when-locked mission');
        await photo(id+'-reason.png');
    }
    await h.defect('Gamepad board controls',async()=>{
        await page.locator('.mission-card[data-mission="floor_path"] button').focus();
        await h.pad(15,()=>page.waitForFunction(()=>document.activeElement?.closest('.mission-card')?.dataset.mission==='locked_path',null,{timeout:1000}));
    });
    await page.setViewportSize({width:390,height:844});await h.defect('When-locked board fits 390px',fits);await photo('when-locked-board-phone.png');
    await h.start('floor_path');await h.begin();await h.call('/fixture/helix/advance',{session_id:tick(0).session_id});
    await page.waitForFunction(()=>document.querySelector('.mission-banner')?.textContent.includes('Fixture bonus sample (Optional)'));
    assert((await page.locator('.mission-banner').textContent()).includes('Floor baseline'),'Floor stage name missing');
    assert(/0:00\s*\/\s*0:10/.test(await page.locator('.mission-banner').textContent()),'Floor stage time missing');
    assert(!(await page.locator('.mission-banner').textContent()).includes('Set intensity to'),'A floor stage incorrectly asks for a fixed manual intensity');
    await h.defect('Optional/floor banner fits 390px',fits);await photo('optional-floor-banner-phone.png');
    await page.locator('[data-choice-objective=cover] [data-choice-option=shown]').focus();await page.keyboard.press('ArrowRight');await page.keyboard.press('Enter');
    await page.waitForFunction(()=>document.querySelector('[data-choice-objective=cover]')?.textContent.includes('Chosen: Hide bonus'));
    await page.locator('[data-main-menu]').click();await closeMenu();

    await seed(BID,'floor_path',{bonus:'hidden'});await h.openCampaign(BID);await h.start('floor_path');await h.begin();
    await h.call('/fixture/helix/advance',{session_id:'5e3d0c3a-0000-4000-8000-00000000c071'});
    await page.waitForFunction(()=>document.querySelector('[data-choice-objective=cover] button:not([disabled])'));
    assert(!(await page.locator('.mission-banner').textContent()).includes('Fixture bonus sample'),'False when optional objective leaked into banner');
    await photo('hidden-optional-floor-banner-phone.png');
    await page.locator('[data-choice-objective=cover] [data-choice-option=shown]').focus();
    await h.pad(15,()=>page.waitForFunction(()=>document.activeElement?.dataset.choiceOption==='hidden'));
    await h.pad(0,()=>page.waitForFunction(()=>document.querySelector('[data-choice-objective=cover]')?.textContent.includes('Chosen: Hide bonus')));
    assert((await h.engine()).status==='IDLE','Banner keyboard or unbound gamepad started the engine');
    await h.defect('Hidden optional banner fits 390px',fits);
    h.report.steps.push('Authored/generic when lock reasons prevent starting; Optional visibility follows flags; floor stages show time without a fixed-intensity prompt; keyboard/gamepad answer safely');
});
