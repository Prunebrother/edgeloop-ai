// SPDX-License-Identifier: AGPL-3.0-only
// Reparent existing controls, preserving their IDs, listeners and engine ownership.
export function mountLayout(chat,character) {
    // Stable upstream targets only. Upstream moves #sessionControlBar between
    // #sessionControlHome and the video HUD, and the Play Style/Endgame panels
    // between #sessionSetupHome and the player; those inner homes are never moved here.
    const need=id=>{const el=document.getElementById(id);if(!el)throw new Error('Companion layout target missing: #'+id);return el;};
    const devices=need('deviceBar'),player=need('playerSection'),cockpit=need('cockpit'),controls=need('sessionControlHome');
    const banner=need('disconnectBanner'),original=banner.parentElement;
    const heading=original.querySelector(':scope > header'),footer=original.querySelector(':scope > footer');
    if(!heading||!footer)throw new Error('Companion layout target missing: page header/footer');
    need('cockpitMain').firstElementChild?.classList.add('session-monitor');
    const shell=document.createElement('main');shell.id='companion-dashboard';shell.dataset.view='chat';
    shell.innerHTML=`<nav class="companion-nav" aria-label="Dashboard views"><span class="companion-brand">EDGE<span>LOOP</span> <small>COMPANION</small></span>
       <div role="group" aria-label="Views"><button data-view="session" aria-controls="session-panel">Session</button><button data-view="chat" aria-controls="ai-companion" aria-pressed="true">Chat</button><button data-view="character" aria-controls="character-panel">Character</button></div>
       <button data-emergency class="emergency">Emergency stop</button></nav>
       <div class="companion-columns"><section id="session-panel" aria-label="EdgeLoop session"><div class="session-scroll"></div><div class="session-transport"></div></section></div>`;
    const scroll=shell.querySelector('.session-scroll'),dock=shell.querySelector('.session-transport');
    const group=(title,nodes,open=false)=>{const d=document.createElement('details');d.className='session-group';d.open=open;
        const s=document.createElement('summary');s.textContent=title;d.append(s,...nodes);return d;};
    heading.classList.add('session-heading');
    scroll.append(heading,devices,player,cockpit,group('About EdgeLoop',[footer]));
    // The session buttons stay docked; upstream still re-homes the bar inside this container.
    dock.append(controls);
    // The centre column stacks the (optional) video workspace above the conversation panel.
    // They are siblings: the conversation panel's own queries and styles never reach the player.
    const center=document.createElement('div');center.className='companion-center';center.id='companion-center';center.append(chat);
    const columns=shell.querySelector('.companion-columns');columns.append(center,character);
    banner.setAttribute('role','alert');
    shell.insertBefore(banner,columns);
    // Anything upstream adds later at the top level stays reachable rather than lost.
    const rest=[...original.children];if(rest.length)scroll.append(group('More EdgeLoop controls',rest));
    original.replaceWith(shell);document.body.classList.add('companion-app');
    // Every emergency control uses the original engine Stop; the flag only labels the outcome for the observer.
    const emergencyStop=()=>{const stop=document.getElementById('sessionStopBtn');stop.dataset.safetyStop='true';stop.click();};
    shell.querySelector('[data-emergency]').onclick=emergencyStop;
    // Theater starts under the dashboard header, so the global Emergency stop stays uncovered.
    const nav=shell.querySelector('.companion-nav');
    const navEdge=()=>shell.style.setProperty('--companion-nav-bottom',Math.round(nav.getBoundingClientRect().bottom+8)+'px');
    new ResizeObserver(navEdge).observe(nav);navEdge();
    const buttons=[...shell.querySelectorAll('[data-view]')];
    const setView=view=>{shell.dataset.view=view;for(const b of buttons)b.setAttribute('aria-pressed',String(b.dataset.view===view));};
    for(const button of buttons)button.onclick=()=>{const same=shell.dataset.view===button.dataset.view;
        setView(button.dataset.view==='character'&&same?'chat':button.dataset.view);
    };
    mountPlayerWorkspace(shell,center,chat,emergencyStop,setView);
    // Layout-only request from a workspace (Character Builder) to show the centre column on a phone.
    shell.addEventListener('companion-view',event=>{if(['session','chat','character'].includes(event.detail))setView(event.detail);});
    // Keyboard-adjustable splitters are optional at wide desktop sizes.
    for(const [label,property,initial,min,max] of [['Session width','--session-width',27,23,34],['Character width','--character-width',33,25,36]]) {
        const input=document.createElement('input');input.type='range';input.min=min;input.max=max;input.value=initial;
        input.setAttribute('aria-label',label);input.className='column-width';
        input.oninput=()=>shell.style.setProperty(property,input.value+'%');
        const control=document.createElement('label');control.className='column-tuning';control.textContent=label.replace(' width','');control.append(input);shell.querySelector('.companion-nav').append(control);
    }
    // Recalculate canvas dimensions after structural movement or panel visibility changes.
    new ResizeObserver(()=>window.dispatchEvent(new Event('resize'))).observe(scroll);
    return shell;
}

// The video stage moves once into the conversation column. Upstream still owns it:
// #playerHeaderBtn and togglePlayer() decide whether the Player is open (#playerBody
// data-player), and the workspace only mirrors that. Nothing here plays, pauses,
// loads media or changes the session.
function mountPlayerWorkspace(shell,center,chat,emergencyStop,setView){
    const body=document.getElementById('playerBody'),column=document.getElementById('playerColumn'),stage=document.getElementById('playerStage');
    const toggle=document.getElementById('playerHeaderBtn');
    if(!body||!column||!stage||!toggle)return;
    const workspace=document.createElement('section');workspace.className='player-workspace';workspace.id='player-workspace';
    workspace.setAttribute('aria-label','Video player');workspace.hidden=true;
    workspace.innerHTML=`<header class="player-workspace-bar"><span class="eyebrow">Player</span><span class="player-workspace-hint">Load a video and funscript in the Session column.</span>
       <button type="button" data-close-player aria-label="Close player">✕ Close player</button></header>`;
    workspace.append(column);center.prepend(workspace);
    // Inside the stage, so that it is rendered in browser fullscreen too. Shown in Theater and Fullscreen.
    const inStage=document.createElement('button');inStage.type='button';inStage.className='stage-emergency';inStage.dataset.stageEmergency='';
    inStage.textContent='Emergency stop';inStage.addEventListener('click',event=>{event.stopPropagation();emergencyStop();});
    stage.append(inStage);
    const history=chat.querySelector('[data-history]');let pinned=true;
    // Only the participant scrolling up unpins; layout changes (resizes, hidden phone views,
    // scroll anchoring) also move scrollTop and must not.
    let userScrollAt=-Infinity;
    for(const type of ['wheel','touchmove','pointerdown','keydown'])history?.addEventListener(type,()=>{userScrollAt=performance.now();},{passive:true});
    history?.addEventListener('scroll',()=>{if(!history.clientHeight)return;const atEnd=history.scrollHeight-history.clientHeight-history.scrollTop<60;
        if(atEnd)pinned=true;else if(performance.now()-userScrollAt<1500)pinned=false;},{passive:true});
    // A smaller conversation keeps showing the newest line if it was showing it before.
    const follow=()=>{if(pinned&&history.clientHeight)history.scrollTop=history.scrollHeight;};
    if(history){new ResizeObserver(follow).observe(history);new MutationObserver(follow).observe(history,{childList:true,subtree:true,characterData:true});}
    const sync=()=>{const open=body.dataset.player==='on',opened=open&&shell.dataset.player!=='on';
        shell.dataset.player=open?'on':'off';workspace.hidden=!open;
        // On a phone the Player button lives in the Session view; the video is in the Chat view.
        if(opened&&shell.dataset.view==='session'&&matchMedia('(max-width:760px)').matches)setView('chat');};
    new MutationObserver(sync).observe(body,{attributes:true,attributeFilter:['data-player']});sync();
    // Closing uses the same upstream toggle as the Player button; it never stops media or the session.
    workspace.querySelector('[data-close-player]').addEventListener('click',()=>{if(body.dataset.player==='on')toggle.click();});
}
