// SPDX-License-Identifier: AGPL-3.0-only
// Backend-validated narrative sensitivity controls; no engine or device imports.
import {CHARACTERS} from './artwork-manifest.js';
const PHYS=['rapid_rise','rapid_fall','sustained_elevation','recovery','fluctuations','stable'];
const human=s=>String(s||'Not available').replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
// A reloaded UI may still be connected to an older running observer.
export const relevanceIdentities=config=>['generic',...Object.keys(CHARACTERS)].filter(id=>Object.hasOwn(config?.preferences||{},id));
const spec={threshold_bpm:['Change / range (BPM)',2,60,.5],window_seconds:['Window (seconds)',5,120,1],duration_seconds:['Minimum duration (seconds)',3,120,1],min_samples:['Minimum distinct samples',5,128,1],cooldown_seconds:['Cooldown (seconds)',5,1800,1],hysteresis_bpm:['Hysteresis (BPM)',1,15,.5],reference_bpm:['Narrative reference (BPM)',35,220,.5],reversals:['Minimum reversals',2,6,1]};
export function mountEventSettings(dialog,{send}) {
 const host=document.createElement('section');host.className='event-intelligence';
 host.innerHTML='<details data-event-config><summary>Event Intelligence settings</summary><p class="event-boundary">Narrative observations only. These controls do not change EdgeLoop safety limits, hardware output or emergency behavior.</p><form data-event-form><fieldset data-event-fields disabled><label><input type="checkbox" data-events-enabled> Enable Event Intelligence</label><div class="event-presets"><label>Sensitivity preset<select data-event-preset><option value="quiet">Quiet</option><option value="balanced">Balanced</option><option value="observant">Observant</option><option value="custom">Custom</option></select></label><button type="button" data-apply-preset>Apply preset</button><button type="button" data-event-defaults>Restore defaults</button></div><div data-event-globals></div><div data-detector-controls></div><details><summary>Character relevance</summary><p>Same facts for every character. Preferences affect commentary only; safety notices retain priority.</p><div data-event-preferences></div></details><button type="submit" data-event-save>Save event settings</button></fieldset></form><p data-event-status role="status"></p></details><details data-event-diagnostics><summary>Event diagnostics</summary><p>Original verified events, derived observations and scheduling opportunities remain separate.</p><div data-detector-health></div><div data-recent-events></div></details>';
 dialog.querySelector('.drawer-content').append(host);
 let snapshot=null,config=null,dirty=false,saving=false,built=false,diagnosticKey=null;
 const form=host.querySelector('[data-event-form]'),fields=host.querySelector('[data-event-fields]'),status=host.querySelector('[data-event-status]');
 function number(parent,key,label,min,max,step){const l=document.createElement('label');l.textContent=label;const input=document.createElement('input');input.type='number';input.name=key;input.required=true;input.min=min;input.max=max;input.step=step;input.dataset.eventField=key;l.append(input);parent.append(l);return input;}
 function select(parent,key,label,values){const l=document.createElement('label');l.textContent=label;const input=document.createElement('select');input.name=key;for(const [value,text] of values){const option=document.createElement('option');option.value=value;option.textContent=text;input.append(option);}l.append(input);parent.append(l);return input;}
 function build(){
  const globals=host.querySelector('[data-event-globals]');number(globals,'proactive_interval_seconds','Event commentary / legacy initiative interval (seconds)',15,1800,1);number(globals,'max_gap_seconds','Maximum sample gap (seconds)',2,15,1);
  for(const detector of snapshot.detectors){
   const d=document.createElement('details');d.dataset.detector=detector.id;const summary=document.createElement('summary');summary.textContent=detector.name;d.append(summary);const description=document.createElement('p');description.textContent=detector.description;d.append(description);
   const label=document.createElement('label'),enabled=document.createElement('input');enabled.type='checkbox';enabled.name=detector.id+'.enabled';label.append(enabled,document.createTextNode(' Enable detector'));d.append(label);
   select(d,detector.id+'.significance','Narrative significance',[['routine','Routine · context only'],['major','Major · eligible for commentary']]);
   const keys=PHYS.includes(detector.id)?['threshold_bpm','window_seconds','duration_seconds','min_samples','cooldown_seconds','hysteresis_bpm']:detector.id==='quiet'?['window_seconds','cooldown_seconds']:['cooldown_seconds'];
   for(const key of keys){const [name,min,max,step]=spec[key];number(d,detector.id+'.'+key,name,detector.id==='quiet'&&key==='window_seconds'?30:min,detector.id==='quiet'&&key==='window_seconds'?1800:max,step);}
   if(detector.id==='sustained_elevation'){select(d,detector.id+'.reference','Elevation reference',[['resting_setting','Configured resting setting · not measured baseline'],['recent_measured','Earlier measured reference'],['narrative_threshold','Narrative-only reference threshold']]);number(d,detector.id+'.reference_bpm',...spec.reference_bpm);}
   if(detector.id==='fluctuations')number(d,detector.id+'.reversals',...spec.reversals);
   host.querySelector('[data-detector-controls]').append(d);
  }
  for(const identity of relevanceIdentities(snapshot.config)){
   const section=document.createElement('details'),title=document.createElement('summary');title.textContent=human(identity);section.append(title);
   for(const category of ['physiology','session','configuration','story'])select(section,'preferences.'+identity+'.'+category,human(category),category==='story'?[['0','Context only'],['1','Eligible for initiative']]:[['0','Context only'],['1','Normal'],['2','Greater relevance']]);
   host.querySelector('[data-event-preferences]').append(section);
  }
  built=true;
 }
 function fill(){
  host.querySelector('[data-events-enabled]').checked=config.enabled;host.querySelector('[data-event-preset]').value=config.preset;
  for(const input of fields.querySelectorAll('[name]')){const path=input.name.split('.');let value;
   if(path[0]==='preferences')value=config.preferences[path[1]][path[2]];
   else if(path.length===2)value=config.detectors[path[0]][path[1]];else value=config[path[0]];
   if(input.type==='checkbox')input.checked=value;else input.value=value;
  }
 }
 function read(){
  const next=structuredClone(config);next.preset='custom';next.enabled=host.querySelector('[data-events-enabled]').checked;
  for(const input of fields.querySelectorAll('[name]')){const path=input.name.split('.');const value=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;
   if(path[0]==='preferences')next.preferences[path[1]][path[2]]=Number(value);
   else if(path.length===2)next.detectors[path[0]][path[1]]=value;else next[path[0]]=value;
  }return next;
 }
 function configure(message){if(send({version:1,type:'configure_events',...message})){saving=true;fields.disabled=true;status.textContent='Saving event settings…';}}
 form.onsubmit=e=>{e.preventDefault();for(const input of form.querySelectorAll('input'))input.setCustomValidity('');if(!form.reportValidity())return;const next=read();
  for(const [key,rule]of Object.entries(next.detectors)){if(PHYS.includes(key)&&(rule.duration_seconds>rule.window_seconds||rule.hysteresis_bpm>=rule.threshold_bpm)){status.textContent=human(key)+': duration must fit the window, and hysteresis must be smaller than the threshold.';return;}}
  configure({config:next});
 };
 form.oninput=e=>{if(e.target.matches('[data-event-preset]'))return;dirty=true;status.textContent='Unsaved event settings';host.querySelector('[data-event-preset]').value='custom';};
 host.querySelector('[data-apply-preset]').onclick=()=>{const name=host.querySelector('[data-event-preset]').value;if(name==='custom'){status.textContent='Edit values and save to use a custom configuration.';return;}configure({preset:name});};
 host.querySelector('[data-event-defaults]').onclick=()=>configure({preset:'balanced'});
 function diagnostics(data){
  const key=JSON.stringify([data.detectors,data.recent_events]);if(key===diagnosticKey)return;diagnosticKey=key;
  const health=host.querySelector('[data-detector-health]');health.replaceChildren();
  for(const detector of data.detectors){const p=document.createElement('p');p.textContent=detector.name+' · '+(data.config.detectors[detector.id].enabled?'Enabled':'Disabled')+' · '+human(detector.last_suppression||'ready')+(detector.cooldown_remaining_seconds?' · '+detector.cooldown_remaining_seconds+'s cooldown':'');health.append(p);}
  const events=host.querySelector('[data-recent-events]');events.replaceChildren();
  if(!data.recent_events.length){const p=document.createElement('p');p.textContent='No detected events in this observer process.';events.append(p);}
  for(const record of [...data.recent_events].reverse()){
   const event=record.event,article=document.createElement('article');article.className='event-record';const title=document.createElement('h4');title.textContent=human(event.kind)+' · '+human(event.significance);article.append(title);
   for(const text of [human(event.category)+' · '+event.source+(event.category==='derived'?(event.simulated?' · simulated':' · physical sensor'):''),new Date(event.created_at_ms).toLocaleTimeString()+' · '+event.sample_count+' supporting samples · '+event.window_seconds+'s span',event.change_bpm!==null?'Endpoint medians: '+event.first_bpm+' → '+event.last_bpm+' BPM; change '+event.change_bpm+' BPM':event.evidence,event.reference_bpm!==null?'Reference: '+event.reference_bpm+' BPM · '+human(event.reference_kind):'',event.evidence,event.rule?'Rule: '+event.rule.threshold_bpm+' BPM threshold; '+event.rule.window_seconds+'s window; '+event.rule.duration_seconds+'s duration; '+event.rule.min_samples+' minimum samples':'','Director: '+human(record.decision)+(record.cooldown_remaining_seconds?' · '+record.cooldown_remaining_seconds+'s remaining':'')]){
    if(!text)continue;const p=document.createElement('p');p.textContent=text;article.append(p);
   }events.append(article);
  }
 }
 return {update(data,saved=false){
   snapshot=data;if(!data){fields.disabled=true;status.textContent='Connect and select a model to configure events.';return;}
   if(!built)build();
   if(saved){saving=dirty=false;status.textContent='Event settings saved locally. Future observations use the new rules.';}
   if(!dirty&&!saving){config=structuredClone(data.config);fill();}
   fields.disabled=saving;diagnostics(data);if(data.error)status.textContent=data.error;
  },error(detail){saving=false;fields.disabled=!snapshot;status.textContent=detail;}};
}
