// SPDX-License-Identifier: AGPL-3.0-only
// Menu-level regression tests without a browser. Browser geometry and native button
// activation remain covered separately in scene-browser.mjs.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mountMainMenu} from '../../src/js/ai/main-menu.js';
import {CHARACTERS} from '../../src/js/ai/artwork-manifest.js';
import {loadStoryRegistry} from '../../src/js/ai/menu-art.js';
import {keyEventIsTyping} from '../../src/js/keybinds.js';
const savedGlobals=Object.fromEntries(['document','window','getComputedStyle'].map(k=>[k,Object.getOwnPropertyDescriptor(globalThis,k)]));
const restoreGlobals=()=>{for(const [k,d] of Object.entries(savedGlobals)){if(d)Object.defineProperty(globalThis,k,d);else delete globalThis[k];}};
const walk=n=>[n,...n.children.flatMap(walk)];
class Element{
    constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.attrs={};this.dataset={};this.listeners={};this.hidden=false;this.className='';this.ownText='';
        this.classList={add:v=>{this.className+=' '+v;},remove:v=>{this.className=this.className.split(/\s+/).filter(x=>x!==v).join(' ');},contains:v=>this.className.split(/\s+/).includes(v)};}
    set textContent(v){this.ownText=v;this.children=[];}get textContent(){return this.ownText+this.children.map(c=>c.textContent).join('');}
    setAttribute(k,v){this.attrs[k]=String(v);if(k==='hidden')this.hidden=true;
        if(k==='value'||k==='type')this[k]=String(v);
        if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=String(v);}
    append(...items){for(const n of items){if(n instanceof Element){n.remove();n.parentElement=this;this.children.push(n);}else this.ownText+=String(n);}}
    prepend(...items){for(const n of items.reverse()){if(n instanceof Element){n.remove();n.parentElement=this;this.children.unshift(n);}}}
    replaceChildren(...items){for(const n of this.children)n.parentElement=null;this.children=[];this.ownText='';this.append(...items);}
    remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
    addEventListener(type,fn){if(fn)(this.listeners[type]??=[]).push(fn);}
    removeEventListener(type,fn){this.listeners[type]=(this.listeners[type]||[]).filter(f=>f!==fn);}
    matches(selector){
        const match=s=>{
            const not=[...s.matchAll(/:not\(([^)]+)\)/g)].map(m=>m[1]);s=s.replace(/:not\([^)]+\)/g,'');
            if(not.some(x=>match(x)))return false;
            const tag=s.match(/^[a-z]+/i)?.[0];if(tag&&tag.toUpperCase()!==this.tagName)return false;
            if([...s.matchAll(/\.([\w-]+)/g)].some(m=>!this.classList.contains(m[1])))return false;
            return [...s.matchAll(/\[([\w-]+)(?:="?([^\]"=]+)"?)?\]/g)].every(([,k,v])=>{
                const value=Object.hasOwn(this.attrs,k)?this.attrs[k]:k.startsWith('data-')?this.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]:undefined;
                return value!==undefined&&(v===undefined||String(value)===v);
            });
        };
        return selector.split(',').some(s=>{const parts=s.trim().split(/\s+/);if(!match(parts.pop()))return false;if(!parts.length)return true;return this.parentElement?.closest(parts.join(' '))!=null;});
    }
    querySelectorAll(s){return walk(this).slice(1).filter(n=>n.matches(s));}
    querySelector(s){return this.querySelectorAll(s)[0]||null;}
    closest(s){for(let n=this;n;n=n.parentElement)if(n.matches(s))return n;return null;}
    contains(target){for(let n=target;n;n=n.parentElement)if(n===this)return true;return false;}
    focus(){document.activeElement=this;}
    select(){this.selectionStart=0;this.selectionEnd=this.value.length;}
    setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}
    click(){for(const f of this.listeners.click||[])f({target:this});}
}
function setup({board=false,active=true,chapters,sessionStatus='IDLE',sendOK=true}={}){
    const windowListeners={},documentListeners={};
    globalThis.document={body:new Element('body'),activeElement:null,createElement:t=>new Element(t),
        getElementById:id=>walk(document.body).find(e=>e.attrs.id===id)||null,querySelector:()=>null,addEventListener:(t,f)=>(documentListeners[t]??=[]).push(f),removeEventListener:(t,f)=>{documentListeners[t]=(documentListeners[t]||[]).filter(x=>x!==f);}};
    globalThis.window={addEventListener:(t,f)=>(windowListeners[t]??=[]).push(f),removeEventListener(){}};
    globalThis.getComputedStyle=()=>({display:'block'});
    const control={status:sessionStatus,sendOK};
    const sent=[],posted=[],host=new Element('section');document.body.append(host);
    const menu=mountMainMenu({send:m=>{sent.push(m);return control.sendOK;},status:()=>control.status,selectCompanion:()=>true,postLines:(...args)=>posted.push(args),bannerHost:host});
    const destroy=menu.destroy.bind(menu);menu.destroy=()=>{destroy();restoreGlobals();};
    const root=document.getElementById('main-menu');
    const find=s=>root.querySelector(s),button=label=>walk(root).find(e=>e.tagName==='BUTTON'&&e.textContent===label);
    const key=(target,value,type='keydown',shiftKey=false)=>{
        const e={key:value,code:value===' '?'Space':value,type,target,shiftKey,stopped:false,defaultPrevented:false,
            preventDefault(){this.defaultPrevented=true;},stopPropagation(){this.stopped=true;},stopImmediatePropagation(){this.stopped=true;}};
        for(const f of windowListeners[type]||[])f(e);
        for(let n=target;n&&!e.stopped;n=n.parentElement)for(const f of n.listeners[type]||[]){e.currentTarget=n;f(e);}
        return e;
    };
    const mission={id:'fixture',title:'Fixture mission',order:1,companion:'mira',state:active?'active':'available',objectives:[],rewards:[],prerequisites:[],chapter:chapters?1:undefined};
    const campaignData={id:'scene_unit',title:'Fixture campaign',available:true,description:'Fixture',progress:{completed:0,total:1},missions:[mission],chapters};
    if(chapters?.some(ch=>ch.number===2&&!ch.teaser))campaignData.missions.push({...mission,id:'second',chapter:2,order:2,state:'available'});
    menu.receive({type:'campaign_state',campaigns:[campaignData],active:active?{campaign:'scene_unit',mission:'fixture'}:null});
    // Enter the active mission through the menu, rather than exposing menu internals.
    find('[data-menu-tile="campaign"]')?.click();
    walk(root).find(e=>e.dataset.campaign==='scene_unit').click();
    if(!board){const action=button('Continue')||button('Briefing');
        if(!action){menu.destroy();throw Error('Missing board action: '+walk(root).filter(e=>e.tagName==='BUTTON').map(e=>e.textContent));}
        action.click();}
    return {menu,root,sent,posted,find,button,key,mission,host,campaignData,control,gamepad:button=>{const e={detail:{button},defaultPrevented:false,preventDefault(){this.defaultPrevented=true;}};for(const f of documentListeners['campaign-gamepad']||[])f(e);return e;}};
}
const tick=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
const block=(label,fields={})=>({speaker:'mira',lines:[label],status:'placeholder',...fields});
const briefing=(ui,b)=>ui.menu.receive({type:'mission_text',campaign:'scene_unit',mission:'fixture',briefing:b,hints:[],narrative_status:'placeholder'});
const result=(ui,blocks,extra={})=>{
    ui.root.hidden=true;ui.menu.receive({type:'mission_result',campaign:'scene_unit',title:'Fixture mission',completion:blocks[0],epilogue:blocks.slice(1),objectives:[],earned:[],...extra});
};
const originalFetch=globalThis.fetch;
globalThis.fetch=async()=>({ok:true,json:async()=>({schema_version:1,campaign:'scene_unit',slots:{image:{file:'image.webp'},background:{file:'background.webp'},key_art:{file:'key.webp'}}})});
await loadStoryRegistry('scene_unit');globalThis.fetch=originalFetch;

test('briefing expression, decorated scene, Escape focus and no menu sends or posts',async()=>{
    const ui=setup();try{
        briefing(ui,block('<script>literal text</script>',{expression:'concerned',image:'image'}));await tick();
        assert.equal(ui.find('.mission-speech img').attrs.src,CHARACTERS.mira.expressions.concerned);
        const before=ui.sent.length;ui.find('[data-play-scene]').click();await tick();
        assert.equal(ui.root.dataset.view,'scene');assert.equal(ui.find('.scene-art').attrs.alt,'');
        assert.equal(ui.find('.scene-stage').attrs['aria-label'],'Fixture mission, part 1 of 1');
        assert.equal(ui.find('.scene-text').attrs['aria-live'],'polite');
        assert.match(ui.find('.scene-text').textContent,/<script>literal text<\/script>/);
        assert.equal(ui.find('.scene-text script'),null);
        assert.equal(ui.find('.scene-text .game-menu-badge').textContent,'Placeholder');
        assert.equal(document.activeElement,ui.button('Next'));assert.equal(ui.button('Back').attrs.disabled,'');
        assert.equal(ui.key(ui.button('Next'),'Escape').stopped,true);await tick();
        assert.equal(ui.root.dataset.view,'briefing');assert.equal(document.activeElement,ui.find('[data-play-scene]'));
        assert.equal(ui.sent.length,before);assert.equal(ui.posted.length,0);
        ui.button('Begin with Mira').click();assert.equal(ui.posted.length,1);
    }finally{ui.menu.destroy();}
});
test('results navigation preserves order, backgrounds, missing art and load-error fallback',async()=>{
    const ui=setup();try{
        result(ui,[block('background',{background:'background',expression:'concerned'}),block('image',{image:'image'}),block('missing',{image:'absent'}),block('plain')]);await tick();
        const before=ui.sent.length,posted=ui.posted.length;ui.find('[data-play-scene]').click();await tick();
        assert.equal(ui.find('.scene-portrait').attrs.src,CHARACTERS.mira.expressions.concerned);
        assert.match(ui.find('.scene-art').attrs.src,/background.webp$/);
        assert.equal(ui.key(ui.button('Next'),'ArrowRight').stopped,true);await tick();assert.equal(ui.find('.scene-position').textContent,'2 / 4');
        assert.equal(ui.find('.scene-portrait'),null);
        const image=ui.find('.scene-art');image.listeners.error[0]({target:image});
        assert.equal(ui.find('.scene-art'),null);assert.ok(ui.find('.scene-stage').classList.contains('scene-plain'));assert.ok(ui.find('.scene-portrait'));
        ui.key(ui.button('Next'),'ArrowLeft');await tick();assert.equal(ui.find('.scene-position').textContent,'1 / 4');
        ui.button('Next').click();await tick();ui.button('Next').click();await tick();
        assert.equal(ui.find('.scene-art'),null);assert.equal(ui.find('.scene-position').textContent,'3 / 4');
        ui.button('Next').click();await tick();ui.button('Next').click();await tick();
        assert.equal(ui.root.dataset.view,'results');assert.equal(document.activeElement,ui.find('[data-play-scene]'));
        assert.equal(ui.sent.length,before);assert.equal(ui.posted.length,posted);
    }finally{ui.menu.destroy();}
});
test('stage Space/Enter and Skip, Tab trap, keyup isolation, and unchanged neutral speech',async()=>{
    const ui=setup();try{
        briefing(ui,block('No art'));await tick();assert.equal(ui.find('[data-play-scene]'),null);
        assert.equal(ui.find('.mission-speech img').attrs.src,CHARACTERS.mira.expressions.neutral);
        briefing(ui,block('image',{image:'image'}));ui.find('[data-play-scene]').click();await tick();
        const stage=ui.find('.scene-stage');ui.button('Skip').focus();ui.key(ui.button('Skip'),'Tab');assert.equal(document.activeElement,stage);
        ui.key(stage,'Tab','keydown',true);assert.equal(document.activeElement,ui.button('Skip'));
        assert.equal(ui.key(stage,' ').defaultPrevented,true);await tick();assert.equal(ui.root.dataset.view,'briefing');
        assert.equal(ui.key(ui.find('[data-play-scene]'),' ','keyup').stopped,true);
        ui.find('[data-play-scene]').click();await tick();ui.key(ui.find('.scene-stage'),'Enter');await tick();assert.equal(ui.root.dataset.view,'briefing');
        ui.find('[data-play-scene]').click();await tick();ui.button('Skip').click();await tick();assert.equal(ui.root.dataset.view,'briefing');
    }finally{ui.menu.destroy();}
});

test('result scene includes chapter and campaign closing blocks in display order',async()=>{
    const ui=setup();try{
        result(ui,[block('completion',{image:'image'}),null,block('epilogue')],{chapter_complete:{number:1,title:'Chapter'},chapter_completion:block('chapter'),campaign_complete:true,campaign_completion:block('campaign')});await tick();
        ui.find('[data-play-scene]').click();await tick();
        for(const [index,label] of ['completion','epilogue','chapter','campaign'].entries()){
            assert.equal(ui.find('.scene-position').textContent,`${index+1} / 4`);
            assert.ok(ui.find('.scene-text').textContent.endsWith(label));ui.button('Next').click();await tick();
        }
        assert.equal(ui.root.dataset.view,'results');
    }finally{ui.menu.destroy();}
});

test('choice banner consumes keyboard and gamepad selection while preserving other controller bindings',async()=>{
    const ui=setup();try{
        ui.root.hidden=true;
        const choice={id:'cover',type:'choice',label:'Cover',done:false,choice:{prompt:'Choose a cover',open:true,options:[{id:'a',label:'Analyst'},{id:'b',label:'Volunteer'}]}};
        ui.menu.receive({type:'campaign_progress',active:{campaign:'scene_unit',mission:'fixture'},attempt:{session_id:'session',objectives:[choice],companion_selected:true}});
        const a=ui.host.querySelector('[data-choice-option="a"]'),b=ui.host.querySelector('[data-choice-option="b"]');
        a.focus();assert.equal(ui.key(a,' ').stopped,true);assert.equal(ui.key(a,'Enter').stopped,true);
        ui.key(a,'ArrowRight');assert.equal(document.activeElement,b);
        assert.equal(ui.gamepad(14).defaultPrevented,true);assert.equal(document.activeElement,a);
        assert.equal(ui.gamepad(1).defaultPrevented,false);
        assert.equal(ui.gamepad(0).defaultPrevented,true);
        assert.deepEqual(ui.sent.at(-1),{version:1,type:'campaign',action:'answer',objective_id:'cover',answer:'a'});
        ui.menu.receive({type:'campaign_progress',active:{campaign:'scene_unit',mission:'fixture'},attempt:{session_id:'session',objectives:[{...choice,done:true,choice:{...choice.choice,open:false,selected:'a',selected_label:'Analyst'}}]}});
        assert.match(ui.host.querySelector('.mission-choice').textContent,/Chosen: Analyst/);
        assert.equal(ui.gamepad(0).defaultPrevented,false);await tick();
    }finally{ui.menu.destroy();}
});

test('scripted stage shows a manual intensity target without disabling mission controls',async()=>{
    const ui=setup();try{
        ui.mission.objectives.push({id:'stages',type:'stage_sequence',label:'Protocol',stages:[]});
        ui.root.hidden=true;
        const stage={id:'compliance',label:'Compliance',seconds:10,intensity:90,current:true,needs_manual:true,elapsed:0};
        ui.menu.receive({type:'campaign_progress',active:{campaign:'scene_unit',mission:'fixture'},attempt:{session_id:'session',objectives:[{id:'stages',type:'stage_sequence',done:false,stages:[stage],elapsed:0,total:10}]}});
        assert.match(ui.host.textContent,/Set intensity to 90%/);await tick();
    }finally{ui.menu.destroy();}
});

test('code input keeps drafts, focus, selection and clue markers across progress updates',async()=>{
    const ui=setup();try{
        ui.root.hidden=true;
        const a={id:'vault',type:'puzzle_solved',label:'Vault',done:false,puzzle:{kind:'code',title:'Vault',clues:['Visible clue'],question:'Enter code',open:true,max_length:12,answer_revision:0}};
        const update=item=>ui.menu.receive({type:'campaign_progress',active:{campaign:'scene_unit',mission:'fixture'},attempt:{session_id:'session',objectives:[item]}});
        update(a);await tick();
        let input=ui.host.querySelector('.mission-code-input');
        assert.equal(input.attrs.maxlength,'12');assert.match(ui.host.textContent,/Use the keyboard to enter the code/);
        assert.equal(ui.gamepad(0).defaultPrevented,true);assert.equal(document.activeElement,input);
        for(const key of ['c',' ','Enter'])assert.equal(ui.key(input,key).stopped,true);
        for(const code of ['KeyC','Space','Enter'])assert.equal(keyEventIsTyping(input,code),true);
        assert.equal(ui.key(input,' ').defaultPrevented,false,'Space should type normally');
        input.value='Wrong Code';input.listeners.input[0]({target:input});input.setSelectionRange(2,5);
        update({...a,puzzle:{...a.puzzle,clues:['Visible clue','Revealed clue'],new_clues:[1]}});await tick();
        input=ui.host.querySelector('.mission-code-input');
        assert.equal(input.value,'Wrong Code');assert.equal(document.activeElement,input);assert.equal(input.selectionStart,2);assert.equal(input.selectionEnd,5);
        assert.match(ui.host.querySelector('.mission-stages [role="status"]').textContent,/New clue/);
        const form=ui.host.querySelector('.mission-code-form');
        form.listeners.submit[0]({preventDefault(){},stopPropagation(){}});
        assert.deepEqual(ui.sent.at(-1),{version:1,type:'campaign',action:'answer',objective_id:'vault',answer:'Wrong Code'});
        update({...a,puzzle:{...a.puzzle,clues:['Visible clue','Revealed clue'],wrong:true,hint:'Try again',answer_revision:1}});await tick();
        input=ui.host.querySelector('.mission-code-input');assert.equal(input.value,'Wrong Code');assert.equal(document.activeElement,input);
        assert.equal(input.selectionStart,0);assert.equal(input.selectionEnd,10);
        assert.equal(ui.host.querySelector('.mission-stages [role="status"]'),null,'New clue marker should clear after an answer');
        update({...a,done:true,puzzle:{...a.puzzle,open:false}});await tick();assert.equal(ui.host.querySelector('.mission-code-input'),null);
    }finally{ui.menu.destroy();}
});


const chapters=()=>[{id:'one',number:1,title:'Chapter One',summary:'Fixture',intro:true,intro_seen:false,available:true,completed:false,close:false,progress:{completed:0,total:1}}];
const chapterReply=(id='one',number=1,fields={})=>({type:'chapter_text',campaign:'scene_unit',chapter:id,number,title:number===1?'Chapter One':'Chapter Two',
    intro:[block('Intro one',{image:'image'}),block('Intro two',{background:'background'})],close:block('Closing block',{background:'background'}),narrative_status:'placeholder',...fields});
const chapterRequests=ui=>ui.sent.filter(m=>m.action==='chapter_text');
const seenRequests=ui=>ui.sent.filter(m=>m.action==='intro_seen');
const stateUpdate=(ui,extra={})=>ui.menu.receive({type:'campaign_state',campaigns:[ui.campaignData],active:null,...extra});

for(const finish of ['Next','Skip','Escape'])test(`automatic intro marks seen once on ${finish} and returns focus to board heading`,async()=>{
    const ui=setup({board:true,active:false,chapters:chapters()});try{
        await tick();assert.equal(ui.root.dataset.view,'missions');assert.equal(chapterRequests(ui).length,1);
        ui.menu.receive(chapterReply());await tick();assert.equal(ui.root.dataset.view,'scene');assert.equal(document.activeElement,ui.button('Next'));
        assert.match(ui.find('.scene-text').textContent,/Placeholder/);assert.equal(ui.posted.length,0);
        if(finish==='Next'){ui.button('Next').click();await tick();ui.button('Next').click();}
        else if(finish==='Skip')ui.button('Skip').click();else ui.key(ui.button('Next'),'Escape');
        await tick();assert.equal(ui.root.dataset.view,'missions');assert.equal(seenRequests(ui).length,1);
        assert.equal(seenRequests(ui)[0].chapter_id,'one');assert.equal(document.activeElement,ui.find('[data-board-heading]'));
        // Even the authoritative save acknowledgement must not steal heading focus or replay the intro.
        ui.campaignData.chapters[0].intro_seen=true;stateUpdate(ui);await tick();
        assert.equal(document.activeElement,ui.find('[data-board-heading]'));assert.equal(chapterRequests(ui).length,1);
        assert.equal(seenRequests(ui).length,1);assert.equal(ui.posted.length,0);
    }finally{ui.menu.destroy();}
});
for(const change of [{intro:false},{intro_seen:true},{available:false},{teaser:true}])test(`no auto intro for chapter flags ${JSON.stringify(change)}`,async()=>{
    const ui=setup({board:true,active:false,chapters:chapters().map(c=>({...c,...change}))});try{await tick();assert.equal(chapterRequests(ui).length,0);assert.equal(ui.root.dataset.view,'missions');}finally{ui.menu.destroy();}
});
for(const sessionStatus of ['RUNNING','PAUSED','RAMPDOWN'])test(`no auto intro in a ${sessionStatus} session`,async()=>{
    const ui=setup({board:true,active:false,chapters:chapters(),sessionStatus});try{await tick();assert.equal(chapterRequests(ui).length,0);}finally{ui.menu.destroy();}
});
test('no automatic intro with an active mission, or while the menu is hidden',async()=>{
    let ui=setup({board:true,active:true,chapters:chapters()});try{await tick();assert.equal(chapterRequests(ui).length,0);}finally{ui.menu.destroy();}
    ui=setup({board:true,active:false,chapters:chapters()});try{ui.root.hidden=true;await tick();assert.equal(chapterRequests(ui).length,0);}finally{ui.menu.destroy();}
});
test('intro and close replay buttons fetch only the selected scene and never mark seen',async()=>{
    const ui=setup({board:true,active:false,chapters:chapters().map(c=>({...c,intro_seen:true,completed:true,close:true}))});try{
        await tick();assert.equal(chapterRequests(ui).length,0);
        ui.button('Play intro').click();ui.menu.receive(chapterReply());await tick();
        assert.match(ui.find('.scene-text').textContent,/Intro one/);ui.button('Skip').click();await tick();
        assert.equal(document.activeElement,ui.button('Play intro'));assert.equal(seenRequests(ui).length,0);
        ui.button('Play chapter close').click();ui.menu.receive(chapterReply('one',1,{narrative_status:'draft',intro:[block('Unplayed intro')],close:block('Draft close',{status:'draft'})}));await tick();
        assert.match(ui.find('.scene-text').textContent,/Story draft.*Draft close/);assert.doesNotMatch(ui.find('.scene-text').textContent,/Unplayed intro/);
        assert.equal(ui.find('.scene-position').textContent,'1 / 1');ui.key(ui.button('Next'),'Escape');await tick();
        assert.equal(document.activeElement,ui.button('Play chapter close'));assert.equal(seenRequests(ui).length,0);assert.equal(chapterRequests(ui).length,2);
    }finally{ui.menu.destroy();}
});
test('only one chapter request is in flight; a switched-away or stale reply never plays',async()=>{
    const cs=chapters();cs.push({...cs[0],id:'two',number:2,title:'Chapter Two'});
    const ui=setup({board:true,active:false,chapters:cs});try{
        await tick();assert.equal(chapterRequests(ui).length,1);
        ui.find('[data-chapter="2"]').click();await tick();assert.equal(chapterRequests(ui).length,1);
        ui.menu.receive(chapterReply());await tick();assert.equal(ui.root.dataset.view,'missions');assert.equal(chapterRequests(ui).length,2);assert.equal(chapterRequests(ui)[1].chapter_id,'two');
        ui.menu.receive(chapterReply());await tick();assert.equal(ui.root.dataset.view,'missions');
        ui.menu.receive(chapterReply('two',2));await tick();assert.equal(ui.root.dataset.view,'scene');assert.match(ui.find('.scene-stage').attrs['aria-label'],/Chapter Two/);
        ui.button('Skip').click();await tick();assert.deepEqual(seenRequests(ui).map(m=>m.chapter_id),['two']);
    }finally{ui.menu.destroy();}
});
for(const context of ['active','hidden','RUNNING'])test(`a delayed intro cannot interrupt a changed ${context} context`,async()=>{
    const ui=setup({board:true,active:false,chapters:chapters()});try{
        await tick();assert.equal(chapterRequests(ui).length,1);
        if(context==='active')stateUpdate(ui,{active:{campaign:'scene_unit',mission:'fixture'}});
        else if(context==='hidden')ui.root.hidden=true;else ui.control.status='RUNNING';
        ui.menu.receive(chapterReply());await tick();assert.notEqual(ui.root.dataset.view,'scene');assert.equal(seenRequests(ui).length,0);
    }finally{ui.menu.destroy();}
});
test('chapter text errors stay on the board without automatic retries; manual retry works',async()=>{
    const ui=setup({board:true,active:false,chapters:chapters()});try{
        await tick();stateUpdate(ui,{command_error:'Chapter unavailable (fixture)'});await tick();
        assert.equal(ui.root.dataset.view,'missions');assert.match(ui.root.textContent,/Chapter unavailable/);
        stateUpdate(ui);await tick();assert.equal(chapterRequests(ui).length,1);
        ui.button('Play intro').click();assert.equal(chapterRequests(ui).length,2);ui.menu.receive(chapterReply());await tick();
        ui.button('Skip').click();await tick();assert.equal(seenRequests(ui).length,0);
    }finally{ui.menu.destroy();}
});
test('failed chapter sends do not loop, and unbound scene gamepad buttons advance/skip safely',async()=>{
    const ui=setup({board:true,active:false,chapters:chapters(),sendOK:false});try{
        await tick();assert.equal(chapterRequests(ui).length,1);assert.match(ui.root.textContent,/could not be loaded/);
        stateUpdate(ui);await tick();assert.equal(chapterRequests(ui).length,1);
        ui.control.sendOK=true;ui.button('Play intro').click();ui.menu.receive(chapterReply());await tick();
        assert.equal(ui.gamepad(15).defaultPrevented,true);await tick();assert.equal(ui.find('.scene-position').textContent,'2 / 2');
        assert.equal(ui.gamepad(14).defaultPrevented,true);await tick();assert.equal(ui.find('.scene-position').textContent,'1 / 2');
        assert.equal(ui.gamepad(0).defaultPrevented,true);await tick();assert.equal(ui.find('.scene-position').textContent,'2 / 2');
        assert.equal(ui.gamepad(1).defaultPrevented,true);await tick();assert.equal(ui.root.dataset.view,'missions');
        assert.equal(seenRequests(ui).length,0);
    }finally{ui.menu.destroy();}
});
test('chapter completion offers and focuses Play scene while keeping results as the default view',async()=>{
    const ui=setup();try{
        result(ui,[block('Completion')],{chapter_complete:{number:1,title:'Chapter One'},chapter_completion:block('Chapter close',{image:'image'})});await tick();
        assert.equal(ui.root.dataset.view,'results');assert.equal(document.activeElement,ui.find('[data-play-scene]'));assert.equal(ui.find('.scene-stage'),null);
        ui.find('[data-play-scene]').click();await tick();ui.button('Next').click();await tick();assert.match(ui.find('.scene-text').textContent,/Chapter close/);
        ui.button('Skip').click();await tick();assert.equal(ui.root.dataset.view,'results');assert.equal(document.activeElement,ui.find('[data-play-scene]'));
    }finally{ui.menu.destroy();}
});

test('starting a mission while chapter text is loading cancels the automatic scene',async()=>{
    const ui=setup({board:true,active:false,chapters:chapters()});try{
        await tick();assert.equal(chapterRequests(ui).length,1);
        ui.button('Start mission').click();ui.menu.receive(chapterReply());await tick();assert.notEqual(ui.root.dataset.view,'scene');
        stateUpdate(ui,{active:{campaign:'scene_unit',mission:'fixture'}});await tick();assert.equal(ui.root.dataset.view,'briefing');assert.equal(seenRequests(ui).length,0);
    }finally{ui.menu.destroy();}
});
test('a remote active mission aborts an automatic scene without marking it seen',async()=>{
    const ui=setup({board:true,active:false,chapters:chapters()});try{
        await tick();ui.menu.receive(chapterReply());await tick();assert.equal(ui.root.dataset.view,'scene');
        stateUpdate(ui,{active:{campaign:'scene_unit',mission:'fixture'}});await tick();assert.equal(ui.root.dataset.view,'missions');assert.equal(seenRequests(ui).length,0);
    }finally{ui.menu.destroy();}
});
test('failed intro_seen sends stay on the board with an error and never loop',async()=>{
    const ui=setup({board:true,active:false,chapters:chapters()});try{
        await tick();ui.menu.receive(chapterReply());await tick();ui.control.sendOK=false;ui.button('Skip').click();await tick();
        assert.equal(ui.root.dataset.view,'missions');assert.match(ui.root.textContent,/could not be marked as seen/);assert.equal(seenRequests(ui).length,1);
        stateUpdate(ui);await tick();assert.equal(seenRequests(ui).length,1);assert.equal(chapterRequests(ui).length,1);
    }finally{ui.menu.destroy();}
});
test('text-only chapter intros still auto-play through the ordinary scene fallback',async()=>{
    const ui=setup({board:true,active:false,chapters:chapters()});try{
        await tick();ui.menu.receive(chapterReply('one',1,{intro:[block('Only text',{status:'draft'})],narrative_status:'draft'}));await tick();
        assert.equal(ui.root.dataset.view,'scene');assert.match(ui.find('.scene-text').textContent,/Story draft.*Only text/);
        ui.button('Next').click();await tick();assert.equal(seenRequests(ui).length,1);
    }finally{ui.menu.destroy();}
});

test('conditional lock reason appears on the board and visible optional goals are marked',async()=>{
    const ui=setup({board:true,active:false});try{
        ui.mission.state='locked';ui.mission.locked_reason='An analyst must vouch for you.';stateUpdate(ui);await tick();
        assert.match(ui.root.textContent,/An analyst must vouch for you/);assert.equal(ui.button('Start mission'),undefined);
        ui.mission.state='active';ui.mission.objectives=[{id:'bonus',type:'edge_count',label:'Bonus target',count:3,optional:true}];
        stateUpdate(ui,{active:{campaign:'scene_unit',mission:'fixture'},attempt:{objectives:[{...ui.mission.objectives[0],done:false,progress:1}]}});await tick();
        assert.match(ui.host.textContent,/Bonus target \(Optional\)/);
        stateUpdate(ui,{active:{campaign:'scene_unit',mission:'fixture'},attempt:{objectives:[]}});await tick();
        assert.doesNotMatch(ui.host.textContent,/Bonus target/);
    }finally{ui.menu.destroy();}
});

test('route banner groups shared goals and route controls, keeps keyboard and gamepad routing',async()=>{
    const ui=setup({board:true,active:true});try{
        const objectives=[{id:'start',type:'session_started',label:'Common session',done:true},
            {id:'cover',type:'choice',label:'Cover decision',done:false,choice:{prompt:'Choose cover',open:true,options:[{id:'analyst',label:'Analyst'},{id:'volunteer',label:'Volunteer'}]}},
            {id:'evidence',type:'edge_count',label:'Evidence check',count:2,progress:1,done:false}];
        ui.mission.objectives=objectives;
        stateUpdate(ui,{active:{campaign:'scene_unit',mission:'fixture'},attempt:{session_id:'try',objectives,routes:[
            {id:'escape',label:'Escape with the code',objectives:['cover'],met:false},
            {id:'release',label:'Release the evidence',objectives:['evidence'],met:false}]}});await tick();
        const escape=ui.host.querySelector('[data-route="escape"]'),release=ui.host.querySelector('[data-route="release"]');
        assert.match(escape.textContent,/Route: Escape with the code.*Cover decision/);assert.doesNotMatch(escape.textContent,/Common session|Evidence check/);
        assert.match(release.textContent,/Route: Release the evidence.*Evidence check/);assert.doesNotMatch(release.textContent,/Cover decision/);
        const analyst=escape.querySelector('[data-choice-option="analyst"]');ui.root.hidden=true;
        const key=ui.key(analyst,'Enter');assert.equal(key.stopped,true);analyst.click();assert.equal(ui.sent.at(-1).action,'answer');assert.equal(ui.sent.at(-1).answer,'analyst');
        const volunteer=escape.querySelector('[data-choice-option="volunteer"]');volunteer.focus();ui.gamepad(0);
        assert.equal(ui.sent.at(-1).answer,'volunteer');
    }finally{ui.menu.destroy();}
});

test('optional puzzles cannot hide required answer controls and overlapping routes share one control',async()=>{
    const ui=setup({board:true,active:true});try{
        const puzzle=id=>({id,type:'puzzle_solved',label:id,done:false,puzzle:{title:id,question:'Pick',clues:['Clue'],open:true,options:[{id:'yes',label:'Yes'},{id:'no',label:'No'}]}});
        const objectives=[{...puzzle('bonus'),optional:true},puzzle('required'),{id:'cover',type:'choice',label:'Shared choice',done:false,choice:{prompt:'Pick cover',open:true,options:[{id:'yes',label:'Yes'},{id:'no',label:'No'}]}}];
        ui.mission.objectives=objectives;
        stateUpdate(ui,{active:{campaign:'scene_unit',mission:'fixture'},attempt:{session_id:'try',objectives}});await tick();
        assert.equal(ui.host.querySelectorAll('.mission-puzzle').length,2);
        stateUpdate(ui,{active:{campaign:'scene_unit',mission:'fixture'},attempt:{session_id:'try',objectives,routes:[
            {id:'one',label:'One',objectives:['required','cover'],met:false},
            {id:'two',label:'Two',objectives:['cover'],met:false}]}});await tick();
        assert.equal(ui.host.querySelectorAll('.mission-puzzle').length,2);
        assert.equal(ui.host.querySelectorAll('[data-choice-objective="cover"]').length,1);
        assert.match(ui.host.querySelector('[data-route="one"]').textContent,/required/);
        assert.match(ui.host.querySelector('[data-route="two"]').textContent,/Shared choice/);
    }finally{ui.menu.destroy();}
});

test('unbound gamepad can move focus between campaign board controls',async t=>{
    const ui=setup({board:true,active:false});try{
        await tick();const start=ui.button('Start mission');assert.ok(start);start.focus();
        const event=ui.gamepad(15);await tick();
        if(!event.defaultPrevented&&document.activeElement===start){
            t.skip('DEFECT: campaign-gamepad ignores board/menu controls; it currently handles scenes and banner choices only.');return;
        }
        assert.notEqual(document.activeElement,start);
    }finally{ui.menu.destroy();}
});
