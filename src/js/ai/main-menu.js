// SPDX-License-Identifier: AGPL-3.0-only
// Main menu, Campaign and Mission screens, and the in-session mission banner.
// Presentation only: the observer owns campaign rules, evidence and saved progress
// (companion_ai/campaign.py). Text from the observer is always assigned with textContent.
import {CHARACTERS} from './artwork-manifest.js';
import {MENU_ART,COMPANION_ORDER,GREETINGS,figure,face,campaignArt,chapterArt} from './menu-art.js';

const LIVE=new Set(['RUNNING','PAUSED','RAMPDOWN']);
const STATE_LABEL={completed:'Completed',active:'In progress',available:'Available',locked:'Locked'};

function node(tag,attrs={},...children){
    const el=document.createElement(tag);
    for(const [k,v] of Object.entries(attrs)){
        if(v===null||v===undefined||v===false)continue;
        if(k==='class')el.className=v;else if(k==='text')el.textContent=v;else if(k.startsWith('on'))el.addEventListener(k.slice(2),v);
        else if(k==='dataset')Object.assign(el.dataset,v);else el.setAttribute(k,v===true?'':String(v));
    }
    el.append(...children.filter(c=>c!==null&&c!==undefined&&c!==false));
    return el;
}
const name=id=>CHARACTERS[id]?.name||id;
const clock=n=>`${Math.floor(n/60)}:${String(n%60).padStart(2,'0')}`;
const percent=(done,total)=>total?Math.round(100*done/total):0;
const SETTING_WORDS={intensity:'intensity',orgasm:'Force Orgasm',play_style:'play style',game:'game',endgame:'endgame',pause:'pause',stop:'stop'};
const portrait=(id,expression='neutral')=>CHARACTERS[id]?.expressions?.[expression]||CHARACTERS[id]?.expressions?.neutral||null;

export function mountMainMenu({send,status,selectCompanion,postLines,bannerHost,currentCompanion=()=>null,onMissionChange=()=>{}}){
    let data=null,paired=false,view='home',campaignId=null,missionId=null,pendingStart=null,pendingLeave=false,result=null,commandError=null,lastFocus=null;
    // Main menu host: the selected companion, else the one picked last on this device, else Nova.
    let hostChoice=null,lastHost=null,greeting=0,chapterNo=null,boardPick=null;
    const HOST_KEY='edgeloop.menu.host';
    try{const saved=localStorage.getItem(HOST_KEY);if(COMPANION_ORDER.includes(saved))lastHost=saved;}catch{}
    // During a mission the host is the companion actually selected (switching waits for Freeplay).
    const missionLocked=()=>!!data?.active;
    const host=()=>{const c=currentCompanion();if(missionLocked()&&COMPANION_ORDER.includes(c))return c;return hostChoice||(COMPANION_ORDER.includes(c)?c:lastHost||'nova');};
    const greet=()=>{greeting=Math.floor(Math.random()*3);};greet();
    const live=()=>LIVE.has(status());
    const root=node('div',{id:'main-menu',class:'game-menu',role:'dialog','aria-modal':'true','aria-labelledby':'main-menu-title'});
    const panel=node('div',{class:'game-menu-panel'});root.append(panel);
    document.body.prepend(root);
    // The engine's shortcuts (Space starts a session) must not fire behind the menu.
    root.addEventListener('keydown',e=>{
        if(e.key==='Escape'&&view!=='home'){e.preventDefault();back();}
        else if(e.key==='Tab'){const items=[...root.querySelectorAll('button:not([disabled]),[href],[tabindex="0"]')];
            if(items.length){const first=items[0],last=items.at(-1);
                if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
                else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}}
        else if(['ArrowDown','ArrowUp','ArrowRight','ArrowLeft'].includes(e.key)&&e.target.closest?.('[data-menu-list]')){
            const items=[...e.target.closest('[data-menu-list]').querySelectorAll(':scope > li > button:not([disabled]), :scope > button:not([aria-disabled])')];
            const i=items.indexOf(document.activeElement);
            if(i>=0){e.preventDefault();items[(i+(['ArrowDown','ArrowRight'].includes(e.key)?1:-1)+items.length)%items.length].focus();}
        }
        e.stopPropagation();
    });
    // The age gate and the setup wizard sit above the menu and keep their own keys and focus.
    const above=()=>['ageOverlay','wizardOverlay'].some(id=>{const e=document.getElementById(id);return e&&!e.classList.contains('hidden')&&getComputedStyle(e).display!=='none';});
    const focusMenu=()=>(panel.querySelector('[data-menu-list] button:not([disabled]):not([aria-disabled]), .game-menu-actions button:not([disabled]), .game-menu-back')||panel.querySelector('button'))?.focus({preventScroll:true});
    // Focus can sit outside the menu (after the wizard closes, or a click on the page behind): a key from there
    // must not reach the engine's document-level shortcuts. Capture on window runs before every other listener.
    const guard=e=>{
        if(root.hidden||above()||root.contains(e.target))return;
        e.stopImmediatePropagation();e.preventDefault();
        if(e.type==='keydown')focusMenu();
    };
    for(const type of ['keydown','keyup','keypress'])window.addEventListener(type,guard,true);
    const refocus=e=>{if(!root.hidden&&!above()&&!root.contains(e.target))queueMicrotask(focusMenu);};
    document.addEventListener('focusin',refocus);

    const campaign=()=>data?.campaigns?.find(c=>c.id===campaignId)||null;
    const mission=()=>campaign()?.missions.find(m=>m.id===missionId)||null;
    const open=(next=view)=>{if(next==='home'&&root.hidden)greet();view=next;root.hidden=false;document.body.classList.add('game-menu-open');render();};
    const close=()=>{root.hidden=true;document.body.classList.remove('game-menu-open');menuButton.disabled=false;(lastFocus||document.getElementById('companion-message'))?.focus?.();};
    const go=next=>{commandError=null;if(next==='missions'&&view==='campaigns'){chapterNo=null;boardPick=null;}view=next;render();};
    const back=()=>go(view==='missions'?'campaigns':view==='briefing'||view==='results'?(campaignId?'missions':'home'):'home');

    function header(title,subtitle,backLabel){
        return node('header',{class:'game-menu-header'},
            backLabel?node('button',{type:'button',class:'game-menu-back',onclick:back},'← '+backLabel):null,
            node('p',{class:'eyebrow',text:'EdgeLoop AI'}),
            node('h1',{id:'main-menu-title',text:title}),
            subtitle?node('p',{class:'game-menu-sub',text:subtitle}):null);
    }
    function statusLine(){
        const text=commandError||(pendingLeave?'Leaving the mission…':null)||data?.error||data?.notice||(!paired?'Connecting to the companion service… Campaign needs it; Freeplay works without it.':null);
        return text?node('p',{class:'game-menu-status',role:'status',text}):null;
    }
    // Where the campaign continues: the mission in progress, else the next one to play.
    function campaignHint(){
        const a=data?.active,m=a&&data.campaigns.find(c=>c.id===a.campaign)?.missions.find(x=>x.id===a.mission);
        if(m)return ['Continue',`Mission ${m.order} · ${m.title}`];
        for(const c of data?.campaigns||[]){const next=c.available&&c.missions.find(x=>x.state==='available');if(next)return ['Next mission',`Mission ${next.order} · ${next.title}`];}
        return [null,'Story missions with the companions of Project EdgeLoop.'];
    }
    function chooseHost(id){
        commandError=null;
        // Picking a host also selects her as your companion, as the model picker would. If the app refuses
        // (a reply or switch in progress), the host stays as she was, so host and companion never disagree.
        if(paired&&currentCompanion()!==id){const r=selectCompanion(id);if(r!==true){commandError=r;render();return;}}
        hostChoice=id;lastHost=id;greet();
        try{localStorage.setItem(HOST_KEY,id);}catch{}
        render();
    }
    function renderHome(){
        const tile=(label,detail,onclick,disabled,kicker)=>node('button',{type:'button',class:'game-menu-tile',onclick:disabled?null:onclick,
            'aria-disabled':disabled?'true':null,dataset:{menuTile:label.toLowerCase().replace(/\s+/g,'-')}},kicker?node('small',{text:kicker}):null,node('strong',{text:label}),node('span',{text:detail}));
        const [kicker,detail]=campaignHint();
        const list=node('div',{class:'game-menu-tiles','data-menu-list':true},
            tile('Campaign',detail,()=>go('campaigns'),false,kicker),
            tile('Freeplay','Every companion, every setting. EdgeLoop AI as you know it.',freeplay),
            tile('Companion Builder','Coming soon',null,true));
        const h=host(),lines=GREETINGS[h]||[],locked=missionLocked();
        return [node('img',{class:'menu-backdrop',src:MENU_ART.backdrop,alt:''}),
            node('div',{class:'menu-shade','aria-hidden':'true'}),
            node('img',{class:'menu-host-figure',src:figure(h),alt:'',dataset:{host:h}}),
            lines.length?node('figure',{class:'menu-host-bubble'},node('figcaption',{text:name(h)}),node('p',{text:lines[greeting%lines.length]})):null,
            node('div',{class:'menu-home-side'},
                node('h1',{id:'main-menu-title',class:'menu-logo'},node('img',{src:MENU_ART.mark,alt:''}),node('img',{class:'menu-wordmark',src:MENU_ART.wordmark,alt:'EdgeLoop'}),node('span',{text:'AI'})),
                // Only an error or a pending leave shows here; the connecting notice belongs to the Campaign screens.
                commandError||pendingLeave?statusLine():null,list),
            node('ul',{class:'menu-host-chips','data-menu-list':true,'aria-label':'Choose your companion'},...COMPANION_ORDER.map(id=>node('li',{},
                node('button',{type:'button','aria-pressed':String(id===h),title:locked?`${name(id)} · switching is locked during a mission (Freeplay unlocks it)`:name(id),'aria-label':name(id),disabled:locked&&id!==h,dataset:{host:id},onclick:()=>chooseHost(id)},node('img',{src:face(id),alt:''})))))];
    }
    // Freeplay carries no campaign rules: a mission in progress is left first (completed missions and rewards stay).
    function freeplay(){
        const active=data?.active,m=active&&data.campaigns.find(c=>c.id===active.campaign)?.missions.find(x=>x.id===active.mission);
        if(m){if(!confirm(`Freeplay leaves the mission in progress (${m.title}). Completed missions and rewards are kept. Continue?`))return;
            // The menu stays until the observer confirms the mission was left: until then its rules still apply.
            if(!send({version:1,type:'campaign',action:'abandon'})){commandError='The companion service could not be reached, so the mission is still in progress.';render();return;}
            pendingLeave=true;commandError=null;render();return;}
        close();
    }
    function renderCampaigns(){
        const items=(data?.campaigns||[]).map(c=>node('li',{},node('button',{type:'button',class:'game-menu-card',disabled:!c.available||!!data?.error,
            onclick:()=>{campaignId=c.id;go('missions');}},
            campaignArt(c.id)?node('img',{class:'game-menu-card-art',src:campaignArt(c.id),alt:''}):null,
            node('strong',{text:c.title}),node('span',{text:c.description}),
            node('span',{class:'game-menu-meta',text:c.completed?'Completed':`${c.progress.completed} of ${c.progress.total} missions completed`}),
            ...(c.chapters||[]).map(ch=>node('span',{class:'game-menu-meta',text:`Chapter ${ch.number}: ${ch.title} · `+(ch.teaser?'Coming soon':ch.completed?'Complete':ch.available?`${percent(ch.progress.completed,ch.progress.total)}%`:'Locked')})),
            c.narrative_status==='draft'?node('span',{class:'game-menu-badge',text:'Story draft'}):null)));
        const list=items.length?node('ul',{class:'game-menu-list','data-menu-list':true},...items):node('p',{class:'game-menu-empty',text:paired?'No campaigns are installed.':'Campaigns appear once the companion service is connected.'});
        return [header('Campaigns',null,'Main menu'),statusLine(),list];
    }
    // Progress detail under an objective: milestones, play-style stages or the stages of a sequence.
    function objectiveDetail(o,a){
        const lines=[];
        if(o.milestones?.length)lines.push('Milestones: '+[...o.milestones,o.count].map(n=>(a&&a.progress>=n?'✓ ':'')+n).join(' · '));
        if(o.type==='style_stages'){
            if(a){
                for(const st of a.stages||[])lines.push(`${st.done?'✓':st.current?'▸':'○'} ${st.label} ${clock(st.seconds)} / ${clock(a.stage_seconds)}`+(st.current?' (current)':''));
                const left=Math.max(0,a.count*a.stage_seconds-a.elapsed);
                lines.push(`Stages ${a.progress} of ${a.count} · ${clock(a.elapsed)} done, ${clock(left)} to go · ${percent(a.elapsed,a.count*a.stage_seconds)}%`);
            } else lines.push(`${o.count} different play styles, ${clock(o.seconds)} each, no game on.`);
        }
        if(o.type==='stage_sequence'){
            for(const st of (a?.stages||o.stages)){
                const elapsed=a?st.elapsed:0;
                const level=st.intensity?`: ${st.intensity}%`:'';
                lines.push(`${st.done?'✓':st.current?'▸':'○'} ${st.label}${level} · ${a?clock(elapsed)+' / ':''}${clock(st.seconds)}`+(st.current?' (current)':''));
            }
            if(a)lines.push(`${clock(a.elapsed)} of ${clock(a.total)} · ${clock(Math.max(0,a.total-a.elapsed))} to go · ${percent(a.elapsed,a.total)}%`);
        }
        if(o.after&&a&&!a.done)lines.push('Counts once the step above is done.');
        if(o.within_seconds&&!a?.done){
            if(a?.expired)lines.push('Time ran out for this try. Start a new session to try again with a fresh clock.');
            else lines.push(`Time left: ${clock(a?a.remaining:o.within_seconds)} of ${clock(o.within_seconds)}`+(a?.remaining<o.within_seconds?' (pausing stops the clock)':''));
        }
        return lines.length?node('ul',{class:'mission-stages'},...lines.map(t=>node('li',{text:t}))):null;
    }
    // A puzzle in the in-session banner: its clues and the answer buttons. The observer checks the answer.
    function puzzlePanel(a){
        const z=a.puzzle;
        return node('section',{class:'mission-puzzle','aria-label':z.title},
            node('strong',{text:z.title}),
            node('ul',{class:'mission-stages'},...z.clues.map(t=>node('li',{text:t}))),
            node('p',{text:z.question}),
            // Space and Enter press the answer button and stop there: the engine's own shortcuts (Space: start or
            // pause the session) must not see them. The button's native activation still happens.
            node('div',{class:'mission-puzzle-options',onkeydown:e=>{if(e.code==='Space'||e.code==='Enter'||e.key===' '||e.key==='Enter')e.stopPropagation();},
                onkeyup:e=>{if(e.code==='Space'||e.key===' ')e.stopPropagation();}},...z.options.map(x=>node('button',{type:'button','data-puzzle-option':x.id,
                class:z.wrong===x.id?'wrong':null,onclick:()=>{if(!send({version:1,type:'campaign',action:'answer',objective_id:a.id,answer:x.id})){puzzleError='The companion service is not connected.';renderBanner();}}},x.label))),
            z.hint?node('p',{class:'mission-note',role:'status',text:'Not quite. '+z.hint}):null);
    }
    function objectiveList(objectives,attempt){
        const live=attempt?Object.fromEntries(attempt.objectives.map(o=>[o.id,o])):{};
        return node('ul',{class:'mission-objectives'},...objectives.map(o=>{const a=live[o.id];const done=!!a?.done;
            return node('li',{class:done?'done':null},node('span',{'aria-hidden':'true',text:done?'✓':'○'}),
                node('div',{},node('span',{text:o.label+(a&&a.count?` (${a.progress}/${a.count})`:'')}),objectiveDetail(o,a)),
                node('span',{class:'sr-only',text:done?' — done':' — not done'}));}));
    }
    const chapterState=ch=>ch.teaser?'teaser':ch.completed?'completed':ch.available?'available':'locked';
    const chapterProgress=(ch,short)=>ch.teaser?'Coming soon':ch.completed?'Chapter complete · 100%':ch.available?`${ch.progress.completed} of ${ch.progress.total} missions · ${percent(ch.progress.completed,ch.progress.total)}%`:short?'Locked':'Locked until the previous chapter is complete';
    // The board shows one chapter: the one picked, else the one with the mission in progress or next to play.
    function boardChapter(c){
        const chs=c.chapters||[];
        if(chs.some(ch=>ch.number===chapterNo))return chapterNo;
        const m=c.missions.find(x=>x.state==='active')||c.missions.find(x=>x.state==='available');
        return m?.chapter??chs.filter(ch=>ch.available&&!ch.teaser).at(-1)?.number??chs[0]?.number??null;
    }
    function renderMissions(){
        const c=campaign();if(!c)return renderCampaigns();
        const byId=Object.fromEntries(c.missions.map(m=>[m.id,m]));
        const chs=c.chapters||[];
        chapterNo=boardChapter(c);
        const ch=chs.find(x=>x.number===chapterNo)||null;
        const missions=ch?c.missions.filter(m=>m.chapter===ch.number):c.missions;
        const pick=missions.find(m=>m.id===boardPick)||missions.find(m=>m.state==='active')||missions.find(m=>m.state==='available')||missions[0]||null;
        boardPick=pick?.id??null;
        const art=ch?chapterArt(c.id,ch.number):campaignArt(c.id);
        const hero=node('section',{class:'board-hero','data-state':ch?chapterState(ch):'available'},
            art?node('img',{class:'board-art',src:art,alt:''}):null,
            node('div',{class:'board-hero-text'},
                node('button',{type:'button',class:'game-menu-back',onclick:back},'← Campaigns'),
                node('p',{class:'eyebrow',text:c.title+(ch?` · Chapter ${ch.number}`:'')}),
                node('h1',{id:'main-menu-title',class:'story-title',text:ch?ch.title:c.title}),
                node('p',{class:'game-menu-sub',text:ch?ch.summary:c.description}),
                ch?node('p',{class:'game-menu-meta board-progress',text:chapterProgress(ch)}):null));
        const tabs=chs.length>1?node('ul',{class:'board-chapters','data-menu-list':true,'aria-label':'Chapters'},...chs.map(x=>node('li',{class:'mission-chapter','data-state':chapterState(x)},
            node('button',{type:'button','aria-pressed':String(x.number===chapterNo),dataset:{chapter:x.number},onclick:()=>{chapterNo=x.number;boardPick=null;render();}},
                node('span',{class:'board-chapter-no',text:`Chapter ${x.number}`}),node('h2',{text:x.title}),node('span',{class:'game-menu-meta',text:chapterProgress(x,true)}))))):null;
        const board=ch?.teaser?node('p',{class:'board-teaser',text:'Coming soon. These missions arrive in a later update.'}):
            node('ul',{class:'mission-board','data-menu-list':true,'aria-label':'Missions'},...missions.map(m=>boardCard(m,m.id===pick?.id)));
        return [hero,tabs,statusLine(),
            live()?node('p',{class:'game-menu-status',text:'Stop the running session to start or switch missions.'}):null,
            board,pick&&!ch?.teaser?missionDetail(pick,byId):null];
    }
    // A mission on the board: the companion's figure (a silhouette while locked), its number, title and state.
    function boardCard(m,picked){
        const locked=m.state==='locked',src=figure(m.companion);
        return node('li',{class:'mission-card','data-state':m.state,dataset:{mission:m.id}},
            node('button',{type:'button','aria-pressed':String(picked),'data-autofocus':picked?'':null,
                onclick:()=>{if(boardPick===m.id){panel.querySelector('.mission-detail .accent-button:not([disabled])')?.focus();return;}boardPick=m.id;render();}},
                src?node('img',{class:'board-figure',src,alt:''}):node('span',{class:'board-figure board-figure-empty','aria-hidden':'true',text:locked?'🔒':'✦'}),
                node('span',{class:'mission-card-kicker',text:`Mission ${m.order}`+(locked?'':` · ${name(m.companion)}`)}),
                node('strong',{text:m.title}),
                node('span',{class:'game-menu-badge','data-state':m.state,text:STATE_LABEL[m.state]+(m.completions>1?` ×${m.completions}`:'')})));
    }
    // The picked mission's details and its action; objectives and rewards live here, not on the card.
    function missionDetail(m,byId){
        const locked=m.state==='locked';
        const needs=m.prerequisites.filter(p=>byId[p]?.state!=='completed').map(p=>byId[p]?.title||p);
        const action=m.state==='active'?'Continue':m.state==='completed'?(m.replay==='allowed'?'Replay':null):m.state==='available'?'Start mission':null;
        return node('section',{class:'mission-detail','data-state':m.state,dataset:{mission:m.id},'aria-label':m.title},
            node('p',{class:'mission-card-kicker',text:`Mission ${m.order}`+(locked?'':` · ${name(m.companion)}`)}),
            node('h2',{text:m.title}),
            node('span',{class:'game-menu-badge','data-state':m.state,text:STATE_LABEL[m.state]+(m.completions>1?` ×${m.completions}`:'')}),
            m.narrative_draft&&!locked?node('span',{class:'game-menu-badge',text:'Story draft'}):null,
            m.prerequisites.length&&!locked&&m.state!=='completed'?node('p',{class:'game-menu-meta',text:'After: '+m.prerequisites.map(p=>byId[p]?.title||p).join(', ')}):null,
            node('p',{text:locked&&needs.length?`Complete ${needs.join(', ')} first.`:m.summary}),
            locked?null:objectiveList(m.objectives,m.state==='active'?data.attempt:null),
            m.rewards.length?node('p',{class:'mission-rewards',text:'Rewards: '+m.rewards.map(r=>(r.earned?'✓ ':'')+r.label).join(' · ')}):null,
            action?node('div',{class:'game-menu-actions'},node('button',{type:'button',class:'accent-button',disabled:live()||!!data?.error,onclick:()=>startMission(m)},action)):null);
    }
    function speech(block){
        if(!block)return null;
        const src=portrait(block.speaker);
        return node('figure',{class:'mission-speech'},src?node('img',{src,alt:name(block.speaker)}):null,
            node('figcaption',{},node('strong',{text:name(block.speaker)}),...block.lines.map(line=>node('p',{text:line}))));
    }
    function renderBriefing(){
        const m=mission();if(!m)return renderMissions();
        return [header(m.title,`Mission ${m.order} · ${name(m.companion)}`,'Missions'),statusLine(),
            m.narrative_draft?node('p',{class:'game-menu-badge',text:'Story draft: this text is awaiting review.'}):null,speech(m.briefing),
            node('section',{class:'mission-brief'},node('h2',{text:'Objectives'}),objectiveList(m.objectives,data?.attempt),
                m.hints.length?node('ul',{class:'mission-hints'},...m.hints.map(h=>node('li',{text:h}))):null,
                m.settings_control?.directed?node('p',{class:'mission-hints',text:`AI Settings Control during this mission: ${name(m.companion)} changes only what the mission needs, at its own steps (`+[...new Set([...m.settings_control.allowed,...(m.settings_control.then_allowed||[])])].map(k=>SETTING_WORDS[k]||k).join(', ')+').'}):
                m.settings_control?node('p',{class:'mission-hints',text:'AI Settings Control during this mission: '+m.settings_control.allowed.map(k=>SETTING_WORDS[k]||k).join(', ')+' only'
                    +(m.settings_control.then_allowed?`; later: ${m.settings_control.then_allowed.map(k=>SETTING_WORDS[k]||k).join(', ')}.`:'.')}):null,
                m.rewards.length?node('p',{class:'mission-rewards',text:'Rewards: '+m.rewards.map(r=>(r.earned?'✓ ':'')+r.label).join(' · ')}):null),
            node('div',{class:'game-menu-actions'},
                node('button',{type:'button',class:'accent-button',onclick:()=>{const r=selectCompanion(m.companion);if(r!==true){commandError=r||`Install ${name(m.companion)} first.`;render();return;}
                    postLines?.(m.briefing,'Mission briefing');close();}},`Begin with ${name(m.companion)}`),
                node('button',{type:'button',onclick:()=>{if(confirm(`Abandon ${m.title}? Completed missions and rewards are kept.`))send({version:1,type:'campaign',action:'abandon'});}},'Abandon mission'))];
    }
    function renderResults(){
        if(!result)return renderHome();
        const c=data?.campaigns?.find(x=>x.id===result.campaign);
        const next=(result.unlocked_missions||[]).map(id=>c?.missions.find(m=>m.id===id)).filter(Boolean);
        const chapter=result.chapter_complete;
        return [header(result.campaign_complete?'Campaign complete':chapter?`Chapter ${chapter.number} complete`:'Mission complete',chapter?`${result.title} · ${chapter.title}`:result.title,null),
            speech(result.completion),
            ...(result.epilogue||[]).map(speech),
            result.chapter_completion?speech(result.chapter_completion):null,
            result.campaign_complete&&result.campaign_completion?speech(result.campaign_completion):null,
            node('section',{class:'mission-brief'},node('h2',{text:'Objectives'}),objectiveList(result.objectives,{objectives:result.objectives}),
                node('h2',{text:result.earned.length?'Unlocked':'Rewards'}),
                node('ul',{class:'mission-hints'},...(result.earned.length?result.earned.map(r=>node('li',{text:r.label})):[node('li',{text:result.replay?'Replay: rewards were already earned.':'No new rewards.'})]),
                    ...next.map(m=>node('li',{text:`New mission: ${m.title}`}))),
                result.records?.calibrated_max_bpm?node('p',{text:`Saved maximum heart rate: ${result.records.calibrated_max_bpm} bpm`}):null),
            node('div',{class:'game-menu-actions'},
                node('button',{type:'button',class:'accent-button',disabled:live(),onclick:()=>{campaignId=result.campaign;go('missions');}},next[0]?`Next: ${next[0].title}`:'Campaign'),
                node('button',{type:'button',onclick:close},'Back to the session'))];
    }
    function render(){
        if(root.hidden)return;
        const parts={home:renderHome,campaigns:renderCampaigns,missions:renderMissions,briefing:renderBriefing,results:renderResults}[view]();
        panel.replaceChildren(...parts.filter(Boolean));
        panel.dataset.view=view;root.dataset.view=view;
        queueMicrotask(()=>(panel.querySelector('[data-autofocus]')||panel.querySelector('[data-menu-list] button:not([disabled]):not([aria-disabled]), .game-menu-actions button:not([disabled]), .game-menu-back')||panel.querySelector('button'))?.focus({preventScroll:true}));
    }
    function startMission(m){
        if(m.state==='active'){missionId=m.id;go('briefing');return;}
        pendingStart={campaign:campaignId,mission:m.id};commandError=null;
        send({version:1,type:'campaign',action:'start',campaign_id:campaignId,mission_id:m.id});
    }

    // ---- In-session banner
    const banner=node('section',{class:'mission-banner','aria-label':'Mission',hidden:true});
    const anchor=bannerHost.querySelector('.model-picker');if(anchor)anchor.after(banner);else bannerHost.prepend(banner);
    let toast=null,puzzleError=null;
    function renderBanner(){
        const active=data?.active,c=active&&data.campaigns.find(x=>x.id===active.campaign),m=c?.missions.find(x=>x.id===active.mission);
        if(!m&&!toast){banner.hidden=true;banner.replaceChildren();return;}
        banner.hidden=false;
        const parts=[];
        if(toast){
            const c2=data?.campaigns?.find(x=>x.id===toast.campaign);
            const next=(toast.unlocked_missions||[]).map(id=>c2?.missions.find(x=>x.id===id)?.title).filter(Boolean);
            parts.push(node('div',{class:'mission-toast',role:'status'},
                node('strong',{text:(toast.campaign_complete?'Campaign complete: ':toast.chapter_complete?`Chapter ${toast.chapter_complete.number} complete: `:'Mission complete: ')+toast.title}),
                node('span',{text:[...toast.earned.map(r=>r.label),...next.map(t=>'New mission: '+t)].join(' · ')||'Rewards were already earned.'}),
                node('span',{class:'game-menu-meta',text:live()?'Keep going as long as you like. Stop the session when you want to continue the campaign.':'Ready for what comes next.'}),
                node('div',{class:'game-menu-actions'},
                    node('button',{type:'button',disabled:live(),title:live()?'Stop the session first':null,onclick:()=>{result=toast;open('results');}},'Results'),
                    node('button',{type:'button',onclick:()=>{toast=null;renderBanner();}},'Dismiss'))));
        }
        if(m){
            const a=data.attempt;
            const notes=[];
            if(a&&!a.companion_selected)notes.push(`Progress counts with ${name(m.companion)} selected.`);
            if(a?.reset_reason==='session_ended')notes.push('The session ended before the mission was done. Counts start again with your next session.');
            if(data.notice)notes.push(data.notice);
            if(puzzleError)notes.push(puzzleError);
            const puzzle=a?.objectives?.find(o=>o.puzzle?.open);
            parts.push(node('div',{class:'mission-current'},
                node('p',{class:'eyebrow',text:`Mission ${m.order} · ${name(m.companion)}`}),node('strong',{text:m.title}),
                objectiveList(m.objectives,a),
                puzzle&&a.session_id?puzzlePanel(puzzle):puzzle?node('p',{class:'mission-note',text:`Start your session with ${name(m.companion)} to work on the puzzles.`}):null,
                ...notes.map(t=>node('p',{class:'mission-note',text:t})),
                node('div',{class:'game-menu-actions'},
                    a&&!a.companion_selected?node('button',{type:'button',disabled:live(),onclick:()=>{const r=selectCompanion(m.companion);if(r!==true)alert(r);}},`Switch to ${name(m.companion)}`):null,
                    node('button',{type:'button',disabled:live(),title:live()?'Stop the session first':null,onclick:()=>{campaignId=active.campaign;missionId=m.id;open('briefing');}},'Briefing'))));
        }
        banner.replaceChildren(...parts);
    }

    // ---- Menu button in the dashboard bar
    const menuButton=node('button',{type:'button',class:'menu-button','data-main-menu':true,onclick:()=>{if(live())return;lastFocus=document.activeElement;open('home');}},'☰ Menu');
    const nav=document.querySelector('#companion-dashboard .companion-nav');
    nav?.querySelector('.companion-brand')?.after(menuButton);
    const syncLive=()=>{
        const isLive=live();
        menuButton.disabled=isLive;menuButton.title=isLive?'Stop the session to open the menu':'Main menu';
        // A session started some other way (gamepad, remote) is never hidden behind the menu.
        if(isLive&&!root.hidden)close();
    };
    const liveTimer=setInterval(()=>{const before=menuButton.disabled;syncLive();if(before!==menuButton.disabled)renderBanner();},500);

    open('home');
    return {
        connected(value){paired=value;if(!value&&pendingLeave){pendingLeave=false;commandError='The companion service disconnected, so the mission may still be in progress.';}if(value)send({version:1,type:'campaign',action:'get'});render();},
        receive(m){
            if(m.type==='campaign_state'){
                const before=data?.active?.mission||null;data=m;commandError=m.command_error||null;
                if((m.active?.mission||null)!==before)onMissionChange(m.active?.mission||null);puzzleError=root.hidden?m.command_error||null:null;
                if(pendingStart&&m.active?.mission===pendingStart.mission&&!m.command_error){campaignId=pendingStart.campaign;missionId=pendingStart.mission;pendingStart=null;view='briefing';}
                else if(pendingStart&&m.command_error)pendingStart=null;
                if(view==='briefing'&&!m.active&&!m.command_error)view='missions';
                if(pendingLeave){pendingLeave=false;if(!m.active&&!m.command_error){render();renderBanner();close();return;}}
                render();renderBanner();
            } else if(m.type==='mission_result'){
                result=m;toast=m;
                postLines?.(m.completion,'Mission complete');
                for(const block of m.epilogue||[])postLines?.(block,'Mission complete');
                if(m.chapter_completion)postLines?.(m.chapter_completion,`Chapter ${m.chapter_complete.number} complete`);
                if(m.campaign_complete&&m.campaign_completion)postLines?.(m.campaign_completion,'Campaign complete');
                renderBanner();
                if(!live()&&root.hidden){open('results');}
            } else if(m.type==='campaign_progress'){
                // The try's counts and stage clocks; the rest of the campaign view is unchanged.
                if(data&&m.active?.mission===data.active?.mission){data={...data,attempt:m.attempt,notice:m.notice};puzzleError=null;render();renderBanner();}
            } else if(m.type==='mission_milestone'){
                // A scripted progress line for the mission in progress (the observer sends each once per try).
                if(data?.active?.mission===m.mission)postLines?.(m.line,'Mission update');
            }
        },
        // The selected companion changed (model picker, a host chip, a mission): the host follows her.
        companionChanged(){const c=currentCompanion();if(COMPANION_ORDER.includes(c)){hostChoice=null;lastHost=c;try{localStorage.setItem(HOST_KEY,c);}catch{}}if(view==='home')render();},
        isOpen:()=>!root.hidden,
        missionLocked,
        destroy(){clearInterval(liveTimer);for(const type of ['keydown','keyup','keypress'])window.removeEventListener(type,guard,true);document.removeEventListener('focusin',refocus);root.remove();banner.remove();menuButton.remove();}
    };
}
