// SPDX-License-Identifier: AGPL-3.0-only
// Read-only presentation and validated companion settings. No engine imports.
import {mountSessionJournal} from './session-journal.js';
import {mountContextIntelligence} from './context-intelligence.js';
import {mountEventSettings} from './event-settings.js';
// Version gate for presentation snapshots; transcript and memory live elsewhere.
export class NarrativeStateGate {
    constructor(){this.models=new Map();}
    clear(){this.models.clear();}
    reset(model,epoch){
        const old=this.models.get(model)||{retired:new Set()};
        if(old.epoch&&old.epoch!==epoch)old.retired.add(old.epoch);
        while(old.retired.size>16)old.retired.delete(old.retired.values().next().value);
        this.models.set(model,{epoch,revision:0,sequence:old.sequence??-1,retired:old.retired});
        while(this.models.size>32)this.models.delete(this.models.keys().next().value);
    }
    accept(state){
        const model=state.model,epoch=state.narrative_epoch,old=this.models.get(model);
        if(old?.retired.has(epoch)||old?.epoch&&!epoch)return false;
        if(old&&Number.isSafeInteger(state.state_sequence)&&state.state_sequence<old.sequence)return false;
        if(old&&old.epoch===epoch&&Number.isSafeInteger(state.narrative_revision)&&state.narrative_revision<old.revision)return false;
        if(!old||old.epoch!==epoch)this.reset(model,epoch);
        const current=this.models.get(model);
        current.revision=state.narrative_revision??current.revision;current.sequence=state.state_sequence??current.sequence;return true;
    }
}
export function mountCharacterMenus(host,{send,onReset=()=>{}}) {
    const toolbar=document.createElement('nav');toolbar.className='character-toolbar';toolbar.setAttribute('aria-label','Character management');
    toolbar.innerHTML='<button type="button" data-menu-director aria-controls="character-director" aria-expanded="false">Director</button><button type="button" data-menu-story aria-controls="character-story" aria-expanded="false">Story Memory</button>';
    host.querySelector('header').after(toolbar);
    const summary=document.createElement('details');summary.className='story-summary';summary.hidden=true;
    summary.innerHTML='<summary></summary><p></p>';toolbar.after(summary);
    const stateGate=new NarrativeStateGate();
    const dialogs={};let model=null,connected=false,state=null,opener=null,open=null,saving=false,resetting=false,dirty=false,storyKey=null;
    for(const [key,title] of [['director','Conversation Director'],['story','Story Memory']]){
        const d=document.createElement('dialog');d.id='character-'+key;d.className='character-drawer';d.setAttribute('aria-labelledby',d.id+'-title');
        d.innerHTML='<header><div><p class="eyebrow">Character management</p><h3 id="'+d.id+'-title">'+title+'</h3></div><button type="button" data-close aria-label="Close '+title+'">×</button></header><div class="drawer-content"></div><p data-menu-notice role="status"></p>';
        host.append(d);dialogs[key]=d;d.querySelector('[data-close]').onclick=()=>close();
        toolbar.querySelector('[data-menu-'+key+']').onclick=()=>show(key);
    }
    const director=dialogs.director,story=dialogs.story;
    director.querySelector('.drawer-content').innerHTML=`
        <section class="director-overview" data-director-status aria-labelledby="director-status-title">
            <h4 id="director-status-title">Director now</h4>
            <p class="director-state" data-director-summary></p>
            <dl data-director-live></dl>
            <p class="menu-help">Live status reflects saved settings. Cooldowns are pacing limits, not a promise of a scheduled reply.</p>
            <details data-director-diagnostics><summary>Director diagnostics</summary><dl data-director-diagnostic-fields></dl></details>
        </section>
        <section class="menu-setting">
            <h4>Conversation pacing</h4>
            <label class="director-toggle"><input type="checkbox" data-proactive checked> Enable proactive dialogue</label>
            <p data-director-scope>Connect and select a model to configure conversation pacing.</p>
            <div data-director-pacing>
                <details data-director-advanced>
                    <summary>Advanced pacing</summary>
                    <p>Proactive dialogue comes only from Director 2.0 cards for models that have it enabled. Response length is unchanged.</p>
                    <label class="director-number">Selection reaction cooldown (seconds)<input type="number" data-director-field="reaction_interval_seconds" min="0" max="60" value="4" step="1"></label>
                    <label class="director-toggle"><input type="checkbox" data-director-field="unlimited_unsolicited" checked> Unlimited unsolicited replies</label>
                    <label class="director-number">Maximum consecutive unsolicited replies<input type="number" data-director-field="max_consecutive_unsolicited" min="1" max="50" value="50" step="1"></label>
                </details>
            </div>
            <div class="director-save"><button type="button" data-save-director>Save pacing settings</button></div>
        </section>`;
    story.querySelector('.drawer-content').innerHTML='<p class="menu-help">Fictional and conversational context for the selected model. These excerpts are fallible and are not verified EdgeLoop session facts.</p><p data-story-model></p><div data-story-content></div><section class="story-reset"><button type="button" data-start-story>Start New Storyline</button><p>Clears this model’s story context and cancels its pending response. Your transcript and EdgeLoop history are retained.</p><div data-story-confirm role="group" aria-label="Confirm new storyline" hidden><p>Start a new storyline for this model? The previous story will be excluded from future context.</p><button type="button" data-story-keep>Keep current storyline</button><button type="button" data-narrative-reset>Confirm new storyline</button></div></section>';
    const journal=mountSessionJournal(host,{send});
    let curatorDirty=false,curatorWanted=null;
    const curator=document.createElement('section');curator.innerHTML='<h4>Experimental memory curator</h4><label><input type="checkbox" data-curator-enabled> Use the selected model to curate fictional memory when idle</label><label>Turns between attempts <input type="number" data-curator-interval min="8" max="12" value="10"></label><button type="button" data-curator-save>Save curator setting</button><p>Off by default. Adds a bounded inference after 8–12 replies, only while EdgeLoop is idle. User replies and session events cancel it. The deterministic memory remains active.</p><p data-curator-status role="status"></p>';story.querySelector('.drawer-content').append(curator);
    curator.oninput=()=>{curatorDirty=true;};
    curator.querySelector('[data-curator-save]').onclick=()=>{const interval=curator.querySelector('[data-curator-interval]');if(!interval.reportValidity())return;curatorWanted={enabled:curator.querySelector('[data-curator-enabled]').checked,interval_turns:Number(interval.value),timeout_seconds:20};send({version:1,type:'configure_curator',config:curatorWanted});};
    const eventSettings=mountEventSettings(director,{send});
    const contextIntelligence=mountContextIntelligence(director,story,{send,getModel:()=>model});
    const human=value=>String(value||'None recorded').replaceAll('_',' ').replace(/^./,s=>s.toUpperCase());
    const decisionText=value=>({
        user_requested_quiet:'You requested quiet.',
        user_typing:'Waiting while you type.',
        unavailable_observation:'Waiting for a fresh session observation.',
        unsolicited_limit:'Waiting for your reply before more unsolicited dialogue.',
        active_conversation:'Giving the current conversation time.',
        reaction_cooldown:'Waiting between event reactions.',
        spontaneous_disabled:'Proactive dialogue is off.',
    })[value]||human(value);
    const notice=(key,text)=>{dialogs[key].querySelector('[data-menu-notice]').textContent=text;};
    function request(){journal.refresh();if(connected&&model)send({version:1,type:'get_character_state',model});}
    function close(restore=true){
        if(!open)return;dialogs[open].close();toolbar.querySelector('[data-menu-'+open+']').setAttribute('aria-expanded','false');open=null;
        story.querySelector('[data-story-confirm]').hidden=true;if(restore&&opener?.isConnected)opener.focus();
    }
    function show(key){
        if(open===key){close();return;}close(false);open=key;opener=toolbar.querySelector('[data-menu-'+key+']');opener.setAttribute('aria-expanded','true');
        const d=dialogs[key];d.style.top=(toolbar.getBoundingClientRect().bottom-host.getBoundingClientRect().top+8)+'px';d.show();d.querySelector('[data-close]').focus();if(key==='director')d.querySelector('.drawer-content').scrollTop=0;request();render();
    }
    function field(dl,label,text){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=text;dl.append(dt,dd);}
    function list(parent,title,items,empty='Nothing recorded yet.'){
        const section=document.createElement('section'),h=document.createElement('h4');h.textContent=title;section.append(h);
        if(items?.length){const ul=document.createElement('ul');for(const value of items){const li=document.createElement('li');li.textContent=value;ul.append(li);}section.append(ul);}
        else{const p=document.createElement('p');p.className='menu-empty';p.textContent=empty;section.append(p);}parent.append(section);
    }
    function render(){
        const available=connected&&model&&state?.model===model,d=available?state.director:null,n=available?state.narrative:null;
        eventSettings.update(available?state.event_intelligence:null,state?.events_saved===true);
        contextIntelligence.update(available?state:null);
        const cc=available?state.memory_curator:null;
        for(const input of curator.querySelectorAll('input,button'))input.disabled=!cc;
        if(cc){if(curatorWanted&&JSON.stringify(cc.config)===JSON.stringify(curatorWanted)){curatorDirty=false;curatorWanted=null;}if(!curatorDirty&&document.activeElement!==curator.querySelector('[data-curator-enabled]'))curator.querySelector('[data-curator-enabled]').checked=cc.config.enabled;if(!curatorDirty&&document.activeElement!==curator.querySelector('[data-curator-interval]'))curator.querySelector('[data-curator-interval]').value=cc.config.interval_turns;curator.querySelector('[data-curator-status]').textContent=cc.status+' · '+(cc.attempts||0)+' attempts'+(cc.reason?' · '+cc.reason:'');}
        if(state){state.context_saved=false;state.objective_saved=false;}
        if(state?.events_saved)state.events_saved=false;
        const dl=director.querySelector('[data-director-live]'),diagnostics=director.querySelector('[data-director-diagnostic-fields]');dl.replaceChildren();diagnostics.replaceChildren();
        const status=director.querySelector('[data-director-summary]');
        status.textContent=!d?(connected?'Select a model to view live status.':'Connect the companion to view live status.'):d.quiet_requested?'Quiet requested · autonomous dialogue is muted.':!d.proactive_enabled?'Proactive dialogue is off.':d.active_response?'Responding · '+human(d.active_response):'Proactive dialogue is on · waiting for an eligible opportunity.';
        const toggle=director.querySelector('[data-proactive]');toggle.disabled=!d||saving;
        if(!saving&&!dirty)toggle.checked=!!d?.proactive_enabled;
        director.querySelector('[data-save-director]').disabled=!d||saving;
        director.querySelector('[data-director-scope]').textContent=d?.settings?'Settings apply to the selected model. User replies and EdgeLoop safety notices remain independent.':'The existing proactive toggle applies to this running service. Load the updated observer for model-scoped pacing controls.';
        const pacing=director.querySelector('[data-director-pacing]');pacing.hidden=!d?.settings;
        for(const input of pacing.querySelectorAll('input')){input.disabled=!d?.settings||saving;if(!saving&&!dirty&&d?.settings){const v=d.settings[input.dataset.directorField];if(input.type==='checkbox')input.checked=v!==false;else input.value=v;}}
        syncCap();
        if(d){
            field(diagnostics,'Director',d.enabled?'Enabled':'Disabled · baseline scheduler');
            field(diagnostics,'Proactive dialogue',d.proactive_enabled?'Enabled':'Disabled');
            if(d.settings_error)field(dl,'Pacing settings',d.settings_error);
            field(diagnostics,'Autonomous quiet mode',d.quiet_requested?'User requested quiet':'Not muted');
            field(diagnostics,'Recent initiative intents',(d.initiative_intents||[]).map(human).join(', ')||'None yet');
            const decisions=(d.recent_decisions||[]).slice(-5).reverse();
            if(!decisions.length)field(diagnostics,'Recent decisions','None yet');
            for(const [index,v] of decisions.entries())field(diagnostics,index===0?'Latest decision':'Earlier decision',[human(v.reason),v.intent,v.kind,v.event_id,v.topic_key].filter(Boolean).join(' · '));
            field(diagnostics,'Recent significant event',d.last_event?human(d.last_event.kind)+' · '+d.last_event.age_seconds+'s ago':'None recorded in this session');
            field(diagnostics,'Event significance',d.last_event?human(d.last_event.significance):'Not available');
            field(dl,'Last reported decision',decisionText(d.last_decision));
            field(diagnostics,'Selection reaction cooldown',d.reaction_cooldown_seconds>0?d.reaction_cooldown_seconds+'s remaining':'No reaction cooldown');
            field(diagnostics,'Pending commentary',d.pending.length?d.pending.map(e=>human(e.kind)).join(', '):'None');
            field(diagnostics,'Suppressed since service start',String(d.suppressed_count));field(diagnostics,'Active response',d.active_response?human(d.active_response):'None');
        }else field(dl,'Connection',connected?'Select a model to inspect the Director.':'Pair the companion to inspect the Director.');
        story.querySelector('[data-story-model]').textContent=model?'Model: '+model:'No model selected';
        const body=story.querySelector('[data-story-content]'),nextStoryKey=JSON.stringify([model,available,n]);
        if(storyKey!==nextStoryKey){storyKey=nextStoryKey;body.replaceChildren();
        if(n){
        list(body,'Active narrative epoch',[n.epoch||state.narrative_epoch||'Unavailable']);
        const audit=state.context_intelligence?.memory_epoch===n.epoch?state.context_intelligence?.memory_decisions||[]:[];
        list(body,'Established details and sources',(n.facts||[]).map(f=>{const decision=audit.find(d=>d.id===f.id);return human(f.category)+' · importance '+(f.importance??2)+(f.curator_source_ref?' · curated source '+f.curator_source_ref+' · '+f.curator_reason:'')+' · '+f.speaker+' · '+human(f.status)+' · '+f.text+' · '+(decision?(decision.selected?'Selected for current prompt':'Excluded: '+human(decision.reason)):'Not yet evaluated for this prompt');}));
        if(n.objective)list(body,'Fictional objective',[human(n.objective.status)+' · '+n.objective.premise,n.objective.motivation,n.objective.next_development].filter(Boolean));list(body,'Current premise',n.premise?[n.premise]:[],'No premise established.');list(body,'Narrative phase',[human(n.phase)]);list(body,'Story developments',n.developments);list(body,'User choices',n.choices);list(body,'Unresolved threads',n.threads);list(body,'Character commitments',n.commitments);list(body,'Recent narrative updates',n.recent_updates||n.developments?.slice(-3));}
        else list(body,'Story memory',[],available?'Narrative memory is disabled.':'Connect and select a model to view its story.');}
        story.querySelector('[data-start-story]').disabled=!available||resetting;
        story.querySelector('[data-narrative-reset]').disabled=!available||resetting;
        summary.hidden=!n?.premise;
        summary.querySelector('summary').textContent=n?.premise?human(n.phase)+' · '+n.premise:'';
        summary.querySelector('p').textContent=d?.last_event?'Last significant event: '+human(d.last_event.kind)+' ('+human(d.last_event.significance)+')':'No verified session event recorded.';
    }
    director.querySelector('[data-proactive]').onchange=()=>{dirty=true;notice('director','Unsaved change');};
    // The cap only applies while unlimited is off.
    function syncCap(){const pacing=director.querySelector('[data-director-pacing]');pacing.querySelector('[data-director-field="max_consecutive_unsolicited"]').disabled=pacing.querySelector('[data-director-field="unlimited_unsolicited"]').checked||!state?.director?.settings||saving;}
    director.querySelector('[data-director-pacing]').oninput=()=>{dirty=true;syncCap();notice('director','Unsaved change');};
    director.querySelector('[data-save-director]').onclick=()=>{
        const value=director.querySelector('[data-proactive]').checked;
        const settings={};if(state?.director?.settings){settings.model=model;for(const input of director.querySelectorAll('[data-director-field]')){if(input.disabled)continue;if(!input.validity.valid){const advanced=input.closest('details');if(advanced)advanced.open=true;input.reportValidity();return;}settings[input.dataset.directorField]=input.type==='checkbox'?input.checked:Number(input.value);}}
        if(send({version:1,type:'configure_director',proactive_enabled:value,...settings})){saving=true;notice('director','Saving…');render();}
    };
    story.querySelector('[data-start-story]').onclick=()=>{story.querySelector('[data-story-confirm]').hidden=false;story.querySelector('[data-story-keep]').focus();};
    story.querySelector('[data-story-keep]').onclick=()=>{story.querySelector('[data-story-confirm]').hidden=true;story.querySelector('[data-start-story]').focus();};
    story.querySelector('[data-narrative-reset]').onclick=()=>{
        if(connected&&model&&send({version:1,type:'reset_narrative',model})){resetting=true;notice('story','Starting a new storyline…');onReset();render();}
    };
    const escape=e=>{if(e.key==='Escape'&&open){e.preventDefault();close();}};
    const outside=e=>{if(open&&!dialogs[open].contains(e.target)&&!toolbar.contains(e.target))close(false);};
    document.addEventListener('keydown',escape);document.addEventListener('pointerdown',outside);
    const timer=setInterval(()=>{if(open)request();},2000);
    return {
        scope(next,paired){if(next!==model||!paired){curatorDirty=false;curatorWanted=null;}journal.scope(next,paired);if(!paired)stateGate.clear();if(next!==model||connected!==paired){close(false);state=null;saving=resetting=dirty=false;for(const key of Object.keys(dialogs))notice(key,'');}model=next;connected=paired;render();},
        receive(message){
            if(message.type==='session_journal'){journal.receive(message);return;}
            if(message.model&&message.model!==model)return;
            if(message.type==='character_state'){if(!stateGate.accept(message))return;state=message;if(saving&&message.director_saved){saving=dirty=false;notice('director','Saved to the companion service.');}render();}
            else if(message.type==='narrative_reset'){stateGate.reset(message.model,message.narrative_epoch);contextIntelligence.reset();resetting=false;story.querySelector('[data-story-confirm]').hidden=true;if(state)state={...state,narrative:null,narrative_epoch:message.narrative_epoch};notice('story','New storyline started. Transcript retained.');request();render();story.querySelector('[data-start-story]').focus();}
            else if(message.type==='character_menu_error'){saving=resetting=false;notice(open||'director',message.detail);eventSettings.error(message.detail);contextIntelligence.error(message.detail);render();}
        },
        refresh:request,
        destroy(){journal.destroy();clearInterval(timer);document.removeEventListener('keydown',escape);document.removeEventListener('pointerdown',outside);close(false);}
    };
}
