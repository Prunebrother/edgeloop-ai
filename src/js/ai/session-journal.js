// SPDX-License-Identifier: AGPL-3.0-only
// Local factual history presentation only. No original engine imports or commands.
export function journalCells(r){
    const ranges=Object.entries(r.heart_rate||{}).map(([source,h])=>`${h.minimum}–${h.maximum} (${source}; n=${h.samples})`).join('; ');
    return [r.start_at||((r.first_observed_at||'Unknown')+' (first observed)'),r.companion||'Unknown',r.active_running_seconds==null?'Unknown':r.active_running_seconds+' s',r.edges??'Unknown',r.completion_status.replaceAll('_',' '),ranges||'Unavailable',r.experience||'Unknown',r.goal||'Unknown'];
}
export function mountSessionJournal(host,{send}){
    const button=document.createElement('button');button.type='button';button.textContent='Session Journal';button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','session-journal');host.querySelector('.character-toolbar').append(button);
    const d=document.createElement('dialog');d.id='session-journal';d.className='character-drawer';d.setAttribute('aria-label','Session Journal');
    d.innerHTML='<header><h3>Session Journal</h3><button type="button" data-close aria-label="Close Session Journal">×</button></header><div class="drawer-content"><p>Verified local history, separate from Story Memory. Up to 100 sessions. Settings describe engine configuration, not confirmed hardware actions. Disabling recording keeps existing history.</p><label><input type="checkbox" data-record> Record future sessions locally (opt-in)</label><label><input type="checkbox" data-access> Allow AI access to relevant historical sessions</label><p>Other companions’ records are shared with AI only when explicitly named. No cloud upload.</p><button type="button" data-clear>Clear all history</button><div class="journal-table"><table><thead><tr></tr></thead><tbody></tbody></table></div><button type="button" data-prev>Previous page</button><span data-page></span><button type="button" data-next>Next page</button><section data-detail></section><p role="status" data-notice></p></div>';
    host.append(d);let connected=false,offset=0,sort='date',descending=true,selected=null,clearing=false;
    const notice=text=>{d.querySelector('[data-notice]').textContent=text;};
    function request(action='get',fields={}){return connected&&send({version:1,type:'session_journal',action,offset,sort,descending,...(selected?{session_id:selected}:{}),...fields});}
    function close(){clearing=false;d.querySelector('[data-clear]').textContent='Clear all history';d.close();button.setAttribute('aria-expanded','false');button.focus();}
    button.onclick=()=>{if(d.open){close();return;}d.style.top='0px';d.show();button.setAttribute('aria-expanded','true');request();};d.querySelector('[data-close]').onclick=close;
    d.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();close();}});
    for(const [key,label] of [['date','Date'],['companion','Companion'],['duration','Duration'],['edges','Edges'],['completion','Completion'],['hr','HR min/max'],['experience','Experience'],['goal','Goal']]){
        const th=document.createElement('th'),b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=()=>{descending=sort===key?!descending:true;sort=key;offset=0;request();};th.append(b);d.querySelector('thead tr').append(th);
    }
    for(const [selector,key] of [['data-record','recording'],['data-access','ai_access']])d.querySelector('['+selector+']').onchange=e=>{notice('Saving privacy setting…');request('configure',{[key]:e.target.checked});};
    d.querySelector('[data-clear]').onclick=e=>{if(!clearing){clearing=true;e.target.textContent='Confirm clear all history';return;}clearing=false;e.target.textContent='Clear all history';selected=null;offset=0;request('clear');};
    d.querySelector('[data-prev]').onclick=()=>{offset=Math.max(0,offset-10);request();};d.querySelector('[data-next]').onclick=()=>{offset+=10;request();};
    return {scope(_model,paired){connected=paired;button.disabled=!paired;if(!paired){d.close();button.setAttribute('aria-expanded','false');d.querySelector('tbody').replaceChildren();d.querySelector('[data-detail]').replaceChildren();}},refresh(){if(d.open)request();},receive(m){
        if(m.type!=='session_journal')return;const j=m.journal;if(!j)return;notice(m.error||j.error||'Saved locally. No raw telemetry or conversation text is recorded.');
        d.querySelector('[data-record]').checked=j.recording;d.querySelector('[data-access]').checked=j.ai_access;
        const body=d.querySelector('tbody');body.replaceChildren();
        for(const r of j.records){const row=document.createElement('tr');journalCells(r).forEach((v,i)=>{const td=document.createElement('td');if(i===0){const b=document.createElement('button');b.type='button';b.textContent=String(v);b.onclick=()=>{selected=r.session_id;request();};td.append(b);}else td.textContent=String(v);row.append(td);});body.append(row);}
        d.querySelector('[data-page]').textContent=` ${j.total?offset+1:0}–${Math.min(offset+10,j.total)} of ${j.total} `;d.querySelector('[data-prev]').disabled=offset===0;d.querySelector('[data-next]').disabled=offset+10>=j.total;
        const detail=d.querySelector('[data-detail]');detail.replaceChildren();if(j.detail){const r=j.detail,human=v=>String(v??'Unknown').replaceAll('_',' ');
            function section(title,items){const h=document.createElement('h4');h.textContent=title;const ul=document.createElement('ul');for(const text of items){const li=document.createElement('li');li.textContent=text;ul.append(li);}detail.append(h,ul);}
            section('Session observations',[`Session: ${r.session_id}`,`Started: ${r.start_at||'Unknown'}`,`First observed: ${r.first_observed_at||'Unknown'}`,`Active running duration: ${r.active_running_seconds==null?'Unknown':r.active_running_seconds+' s'}`,`Final verified edges: ${r.edges??'Unknown'}`,`Completion: ${human(r.completion_status)}`,`Completion evidence: ${r.completion_source||'Unknown'}`,`Stop reason: ${human(r.stop_reason)}`]);
            section('Companions',r.companions.map(c=>`${c.companion} · ${c.model||'Unknown model'}`));
            section('Selected engine settings',Object.entries(r.settings).map(([k,v])=>`${human(k)}: ${v}`));
            section('Setting changes',r.setting_changes.length?r.setting_changes.map(c=>`${c.at||'Unknown time'} · ${human(c.setting)}: ${c.from} → ${c.to}`):['None observed.']);
            section('Data quality',[human(r.completeness),human(r.confidence),...Object.entries(r.quality).filter(([,v])=>v).map(([k])=>human(k)),...Object.entries(r.heart_rate).map(([source,h])=>`${source}: ${h.minimum}–${h.maximum} BPM · ${h.samples} distinct samples · ${h.quality}`),r.settings_authority]);
            section('Verified session events',r.events.length?r.events.map(e=>`${e.at_ms==null?'Unknown time':new Date(e.at_ms).toISOString()} · ${human(e.kind)}`):['None retained.']);
            for(const [action,label] of [['report_completion','Report completion myself'],['delete','Delete this record']]){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=()=>{const id=selected;if(action==='delete')selected=null;request(action,{session_id:id});};detail.append(b);}}
    },destroy(){d.remove();button.remove();}};
}
