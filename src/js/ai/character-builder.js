// SPDX-License-Identifier: AGPL-3.0-only
// Character Builder workspace: world, character, portrait and card deck. It opens in the centre
// column in place of the conversation, which stays mounted (hidden) so nothing in it is lost.
// The observer validates, composes and activates; this panel only edits sources and shows
// results. All server and authored text is assigned with textContent.
import {MESSAGE_LIMIT_BYTES,messageBytes} from './connection.js';
export const MAX_CARDS=16;
const KIB=n=>(n/1024).toFixed(1)+' KiB';
const blankWorld=()=>({schema_version:1,id:'',name:'',setting:'',lore:'',rules:[]});
const blankCard=n=>({id:'card-'+n,theme:'',brief:'',when:{},repeat:true,enabled:true});
const blankCharacter=()=>({schema_version:1,id:'',world:'',name:'',short_name:'',personality:'',voice:'',relationship:'',
    model:'huihui_ai/qwen3.5-abliterated:9b',portrait:null,deck:{shared:'lifecycle',cards:[blankCard(1)]}});
const WHEN=[['min_seconds','From second'],['max_seconds','Until second'],['min_edges','From edge'],['max_edges','Up to edge']];
// Conditions that the data format supports but this editor does not edit yet. They are shown,
// and kept exactly as they are when the card is saved again.
export function preservedConditions(when={}){
    const words=[];
    if(when.requires_hr)words.push('needs a live heart rate'+(when.hr_trends?.length?' ('+when.hr_trends.join(', ')+')':''));
    if(when.requires_story_welcome)words.push('only when story is welcome');
    if(Array.isArray(when.statuses)&&when.statuses.join()!=='RUNNING,RAMPDOWN')words.push('only while '+when.statuses.map(s=>s.toLowerCase()).join(' or '));
    return words;
}
export const SIZE_HELP='World and character are each sent as one message of at most 16 KiB, and the character message carries the whole deck. '
    +'Long descriptions or briefs can reach that limit before the deck has 16 cards; shorten some text or remove a card.';

export function mountCharacterBuilder(host,{send,models=()=>[],onClose=()=>{}}){
    const root=document.createElement('section');root.className='builder-workspace';root.dataset.characterBuilder='';root.hidden=true;
    root.setAttribute('aria-label','Character Builder');
    root.innerHTML=`<header class="builder-bar"><span class="eyebrow">Character Builder</span><span class="builder-bar-hint">Your conversation and active character stay as they are.</span>
        <button type="button" data-b-close>← Back to chat</button></header>
      <div class="builder-scroll">
      <p class="builder-note">Create your own world and companion. Cards are dialogue and story briefs only; EdgeLoop keeps control of the session, device and emergency stop.</p>
      <div class="builder-row"><label>Open<select data-b-open><option value="">New character</option></select></label><button type="button" data-b-load>Open</button></div>
      <div class="builder-grid">
      <fieldset data-b-world><legend>World</legend>
        <label>Reuse world<select data-b-worlds><option value="">New world</option></select></label>
        <label>World ID<input data-w="id" maxlength="24" placeholder="saltglass" spellcheck="false"></label>
        <label>Name<input data-w="name" maxlength="60"></label>
        <label>Setting<textarea data-w="setting" rows="4" maxlength="1200"></textarea></label>
        <label>Lore<textarea data-w="lore" rows="6" maxlength="3000"></textarea></label>
        <label>Ground rules (one per line)<textarea data-w="rules" rows="3"></textarea></label>
        <p class="builder-meter" data-b-world-size></p></fieldset>
      <fieldset data-b-character><legend>Character</legend>
        <label>Character ID<input data-c="id" maxlength="24" placeholder="wren-calloway" spellcheck="false"></label>
        <label>Full name<input data-c="name" maxlength="60"></label>
        <label>Short name<input data-c="short_name" maxlength="24"></label>
        <label>Age (adult, optional)<input data-c="age" type="number" min="18" max="1000"></label>
        <label>Personality<textarea data-c="personality" rows="3" maxlength="1200"></textarea></label>
        <label>Voice<textarea data-c="voice" rows="2" maxlength="800"></textarea></label>
        <label>Relationship to you<textarea data-c="relationship" rows="2" maxlength="600"></textarea></label>
        <label>Model<input data-c="model" list="builder-models" maxlength="120" spellcheck="false"><datalist id="builder-models" data-b-models></datalist></label></fieldset>
      <fieldset data-b-art-set><legend>Portrait</legend>
        <label>Image<select data-b-art><option value="">No portrait</option></select></label>
        <p class="builder-hint" data-b-art-folder></p>
        <p class="builder-hint">One portrait is used for every expression in this release.</p></fieldset>
      </div>
      <fieldset data-b-deck><legend>Card deck</legend>
        <label>Shared cards<select data-b-shared><option value="lifecycle">Lifecycle only (start, closing, arrival, milestones)</option><option value="lifecycle+routine">Lifecycle and routine (counts, time, heart rate)</option></select></label>
        <p class="builder-meter" data-b-count></p>
        <div data-b-cards></div><button type="button" data-b-add>Add card</button>
        <p class="builder-meter" data-b-character-size></p></fieldset>
      <div class="builder-actions"><button type="button" data-b-save>Save</button><button type="button" data-b-preview>Preview</button><button type="button" class="accent-button" data-b-activate disabled>Activate</button></div>
      <p class="builder-status" role="status" data-b-status></p>
      <ul class="builder-errors" role="alert" data-b-errors hidden></ul>
      <section class="builder-preview" data-b-preview-out hidden></section>
      <p class="builder-hint">To return to a built-in companion, go back to chat, choose its model and press Switch model.</p>
      </div>`;
    host.append(root);
    const q=s=>root.querySelector(s);
    // Only one save (a world + character message pair) is in flight at a time. edits counts every
    // change on screen and savedAt is its value when that save was sent, so its response can tell
    // whether the player kept editing meanwhile. A save or preview asked for while one is in flight
    // is queued and sent when it completes, with whatever is on screen then.
    let world=blankWorld(),character=blankCharacter(),previewed=null,saving=0,previewAfterSave=false,edits=0,savedAt=0,queued=null;
    const status=t=>{q('[data-b-status]').textContent=t;};
    const showErrors=errors=>{const list=q('[data-b-errors]');list.replaceChildren();list.hidden=!errors?.length;
        for(const e of errors||[]){const li=document.createElement('li');li.textContent=(e.path||[]).join(' › ')+': '+e.message;list.append(li);}};
    const option=(select,value,label)=>{const o=document.createElement('option');o.value=value;o.textContent=label;select.append(o);};
    const fillSelect=(select,values,first)=>{const keep=select.value;select.replaceChildren();option(select,'',first);for(const v of values)option(select,v,v);select.value=values.includes(keep)?keep:'';};
    const num=v=>v===''||v==null?undefined:Number(v);
    const message=(action,body)=>({version:1,type:'character_builder',action,...body});
    const sizeOf=m=>messageBytes(JSON.stringify(m));

    function meters(){
        collect();
        const n=character.deck.cards.length;
        q('[data-b-count]').textContent=n+' of '+MAX_CARDS+' cards'+(n>=MAX_CARDS?' · the deck is full':'');
        q('[data-b-add]').disabled=n>=MAX_CARDS;
        for(const [selector,label,m] of [['[data-b-world-size]','World message',message('save_world',{world})],['[data-b-character-size]','Character and deck message',message('save_character',{character})]]){
            const bytes=sizeOf(m),el=q(selector);el.dataset.over=String(bytes>MESSAGE_LIMIT_BYTES);
            el.textContent=label+': '+KIB(bytes)+' of '+KIB(MESSAGE_LIMIT_BYTES)+(bytes>MESSAGE_LIMIT_BYTES?' · too large to save. '+SIZE_HELP:'');
        }
    }
    function renderCards(){
        const box=q('[data-b-cards]');box.replaceChildren();
        character.deck.cards.forEach((card,index)=>{
            const item=document.createElement('fieldset');item.className='builder-card';
            const legend=document.createElement('legend');legend.textContent='Card '+(index+1);item.append(legend);
            const field=(label,el)=>{const l=document.createElement('label');l.textContent=label;l.append(el);item.append(l);return el;};
            const input=(key,attrs={})=>{const el=document.createElement('input');Object.assign(el,attrs);el.value=card[key]??'';el.oninput=()=>{card[key]=el.value||(key==='occasion'?undefined:'');dirty();};return el;};
            field('Card ID',input('id',{maxLength:32,spellcheck:false}));
            field('Theme',input('theme',{maxLength:32,placeholder:'tide-lore',spellcheck:false}));
            const brief=document.createElement('textarea');brief.rows=2;brief.maxLength=400;brief.value=card.brief;brief.oninput=()=>{card.brief=brief.value;dirty();};field('Brief for the model',brief);
            field('Occasion (optional)',input('occasion',{maxLength:160}));
            for(const [key,label] of WHEN){const el=document.createElement('input');el.type='number';el.min='0';el.value=card.when?.[key]??'';
                el.oninput=()=>{card.when={...card.when,[key]:num(el.value)};if(card.when[key]===undefined)delete card.when[key];dirty();};field(label,el);}
            const talk=document.createElement('input');talk.type='checkbox';talk.checked=!!card.when?.requires_conversation;
            talk.onchange=()=>{card.when={...card.when,requires_conversation:talk.checked||undefined};if(!talk.checked)delete card.when.requires_conversation;dirty();};field('Only after you have talked',talk);
            const on=document.createElement('input');on.type='checkbox';on.checked=card.enabled!==false;on.onchange=()=>{card.enabled=on.checked;dirty();};field('Enabled',on);
            const kept=preservedConditions(card.when);
            if(kept.length){const p=document.createElement('p');p.className='builder-hint builder-kept';p.dataset.bKept='';p.textContent='Also '+kept.join('; ')+'. Kept as written; edit these in the character file.';item.append(p);}
            const remove=document.createElement('button');remove.type='button';remove.textContent='Remove card';remove.onclick=()=>{character.deck.cards.splice(index,1);renderCards();dirty();};item.append(remove);
            box.append(item);
        });
        meters();
    }
    function render(){
        for(const el of root.querySelectorAll('[data-w]'))el.value=el.dataset.w==='rules'?(world.rules||[]).join('\n'):world[el.dataset.w]??'';
        for(const el of root.querySelectorAll('[data-c]'))el.value=character[el.dataset.c]??'';
        q('[data-b-art]').value=character.portrait?.file||'';q('[data-b-shared]').value=character.deck.shared;renderCards();
    }
    function collect(){
        for(const el of root.querySelectorAll('[data-w]'))world[el.dataset.w]=el.dataset.w==='rules'?el.value.split('\n').map(s=>s.trim()).filter(Boolean):el.value;
        for(const el of root.querySelectorAll('[data-c]')){const v=el.value;if(el.dataset.c==='age'){if(v)character.age=Number(v);else delete character.age;}else character[el.dataset.c]=v;}
        character.world=world.id;
        // Fit and position are kept from the source; this release has no editor for them.
        const art=q('[data-b-art]').value;character.portrait=art?{...(character.portrait||{fit:'contain',position:'50% 50%'}),file:art}:null;
        character.deck.shared=q('[data-b-shared]').value;
        // Optional fields the player left empty are omitted; every other card field, including
        // conditions this editor cannot show, is sent back exactly as it was loaded.
        // Edited in place: the card editors hold these objects, so they must never be replaced here.
        for(const card of character.deck.cards)if(!card.occasion)delete card.occasion;
    }
    function dirty(){edits++;previewed=null;q('[data-b-activate]').disabled=true;q('[data-b-preview-out]').hidden=true;meters();}
    root.addEventListener('input',e=>{if(e.target.matches('[data-w],[data-c]'))dirty();});
    q('[data-b-art]').onchange=dirty;q('[data-b-shared]').onchange=dirty;
    const request=(action,body={})=>{const m=message(action,body),bytes=sizeOf(m);
        if(bytes>MESSAGE_LIMIT_BYTES){showErrors([{path:[action==='save_world'?'world':'character'],message:'This message is '+KIB(bytes)+', over the '+KIB(MESSAGE_LIMIT_BYTES)+' limit. '+SIZE_HELP}]);return false;}
        if(!send(m)){showErrors([{path:[action],message:'Not sent: the AI connection is not ready.'}]);return false;}
        return true;};
    q('[data-b-add]').onclick=()=>{if(character.deck.cards.length>=MAX_CARDS)return;character.deck.cards.push(blankCard(character.deck.cards.length+1));renderCards();dirty();};
    const save=preview=>{
        if(saving){queued={preview:preview||!!queued?.preview};status('Saving… your newer changes will be saved next.');return;}
        previewAfterSave=preview;collect();showErrors([]);saving=2;savedAt=edits;status('Saving…');
        // Check both sizes first, so a too-large character never leaves a half-saved pair.
        const pair=[['save_world',{world}],['save_character',{character}]];
        const over=pair.find(([action,body])=>sizeOf(message(action,body))>MESSAGE_LIMIT_BYTES);
        if(over){request(...over);saving=0;previewAfterSave=false;status('Not saved.');return;}
        if(!pair.every(([action,body])=>request(action,body))){saving=0;previewAfterSave=false;}};
    q('[data-b-save]').onclick=()=>save(false);
    // Preview always composes what is on screen: it saves first and composes only if both saves succeed.
    q('[data-b-preview]').onclick=()=>save(true);
    q('[data-b-activate]').onclick=()=>{if(previewed&&request('activate',{id:previewed.id}))status('Activating '+previewed.name+'…');};
    q('[data-b-load]').onclick=()=>{const id=q('[data-b-open]').value;if(!id){world=blankWorld();character=blankCharacter();render();dirty();return;}request('get',{kind:'character',id});};
    q('[data-b-worlds]').onchange=e=>{if(e.target.value)request('get',{kind:'world',id:e.target.value});};
    q('[data-b-close]').onclick=()=>close();
    function refresh(){request('list');const list=q('[data-b-models]');list.replaceChildren();for(const m of models())option(list,m,m);}
    function open(){root.hidden=false;host.dataset.builder='on';refresh();meters();q('.builder-scroll').focus?.();}
    function close(){root.hidden=true;host.dataset.builder='off';onClose();}

    function showPreview(p){
        const out=q('[data-b-preview-out]');out.replaceChildren();out.hidden=false;
        const h=document.createElement('h4');h.textContent=p.name+' · '+p.world+' · revision '+p.revision+' · '+p.content_sha256.slice(0,12);out.append(h);
        const meta=document.createElement('p');meta.textContent='Runs on '+p.model+'. Its persona replaces the model\'s built-in identity ('+p.persona_characters+' characters).';out.append(meta);
        if(p.portrait&&origin()){const img=document.createElement('img');img.alt=p.name+' portrait';img.className='builder-portrait';img.src=origin()+'/character-art/'+p.portrait.file;out.append(img);}
        const themes=document.createElement('p');themes.textContent='Themes in the shuffle: '+Object.entries(p.themes).map(([t,n])=>t+' ×'+n).join(', ');out.append(themes);
        const table=document.createElement('table');const head=table.createTHead().insertRow();for(const t of ['Card','Theme','When','Brief'])head.insertCell().textContent=t;
        const body=table.createTBody();for(const c of p.cards){const row=body.insertRow();row.insertCell().textContent=c.id+(c.custom?'':' (shared)');row.insertCell().textContent=c.theme;row.insertCell().textContent=c.when;row.insertCell().textContent=c.brief;}
        out.append(table);
        const life=document.createElement('p');life.textContent='Shared lifecycle cards: '+[...p.shared_lifecycle.session_start,...p.shared_lifecycle.session_end,...p.shared_lifecycle.arrival,...p.shared_lifecycle.milestones].join(', ');out.append(life);
        const persona=document.createElement('details');const s=document.createElement('summary');s.textContent='Persona prompt';const pre=document.createElement('pre');pre.textContent=p.persona_system;persona.append(s,pre);out.append(persona);
    }
    let originValue=null;const origin=()=>originValue;
    renderCards();
    return {
        open,close,isOpen:()=>!root.hidden,
        setOrigin(value){originValue=value;},
        receive(m){
            if(m.type!=='character_builder')return;
            if(!m.ok){showErrors(m.errors);status(m.action==='activate'?'Not activated.':'Fix the problems listed below.');if(m.action.startsWith('save')){saving=0;previewAfterSave=false;queued=null;}return;}
            if(m.action==='list'){fillSelect(q('[data-b-open]'),m.characters,'New character');fillSelect(q('[data-b-worlds]'),m.worlds,'New world');
                const art=q('[data-b-art]'),want=character.portrait?.file||art.value;fillSelect(art,m.art,'No portrait');art.value=m.art.includes(want)?want:'';
                q('[data-b-art-folder]').textContent='Put portrait images (PNG, JPEG or WebP, up to 8 MB) in '+m.art_folder+', then reopen Character Builder. Direct upload is not available yet.';}
            else if(m.action==='get'&&m.kind==='character'){character=m.value;if(!character.deck.cards.length)character.deck.cards.push(blankCard(1));request('get',{kind:'world',id:character.world});render();dirty();status('Opened '+character.name+'.');}
            else if(m.action==='get'&&m.kind==='world'){world=m.value;render();dirty();}
            else if(m.action==='save_world'||m.action==='save_character'){
                if(!saving)return; // a late reply to a save that already failed
                // The card editors close over the card objects, so the saved (canonical) character
                // is only adopted together with a re-render that rebinds them. If the player edited
                // while the save was in flight, the newer on-screen work wins and only the revision
                // is taken; it is sent with the next save.
                const current=edits===savedAt;
                if(m.action==='save_character'){if(current){character=m.value;render();}else character.revision=m.value.revision;}
                if(--saving===0){status(current?'Saved locally · revision '+character.revision+'.':'Saved revision '+character.revision+'; newer edits are not saved yet.');refresh();
                    const next=queued;queued=null;
                    if(next)save(next.preview||previewAfterSave);
                    else if(current&&previewAfterSave&&request('preview',{id:character.id}))status('Composing preview…');
                    if(!next)previewAfterSave=false;}}
            else if(m.action==='preview'){previewed=m.preview;showPreview(m.preview);q('[data-b-activate]').disabled=false;status('Preview ready. Activate to start talking with '+m.preview.short_name+'.');}
            else if(m.action==='activate'){status(m.character.name+' is active. Go back to chat to talk.');refresh();}
        },
    };
}
