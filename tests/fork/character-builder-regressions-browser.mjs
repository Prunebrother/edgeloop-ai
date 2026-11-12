// SPDX-License-Identifier: AGPL-3.0-only
// Regression checks from the v0.7.0-rc1/rc2 reviews: card edits after a save, overlapping saves, and dotted custom
// identities in Event Intelligence preferences. Modules are served from this checkout through
// request interception; no observer, network or device is used.
import {chromium} from 'playwright';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve(new URL('../..',import.meta.url).pathname);
const assert=(x,m)=>{if(!x)throw Error(m);};
const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('http://fixture.local/**',async route=>{
  const pathname=new URL(route.request().url()).pathname;
  if(pathname==='/')return route.fulfill({contentType:'text/html',body:'<div id="host"></div><div id="dialog"><div class="drawer-content"></div></div>'});
  return route.fulfill({contentType:pathname.endsWith('.json')?'application/json':'text/javascript',body:await readFile(path.join(root,pathname),'utf8')});
 });
 await page.goto('http://fixture.local/');

 const builder=await page.evaluate(async()=>{
  const {mountCharacterBuilder}=await import('/src/js/ai/character-builder.js');
  const sent=[];const b=mountCharacterBuilder(document.querySelector('#host'),{send:m=>{sent.push(structuredClone(m));return true;}});
  const world={id:'world',name:'World',setting:'An island',lore:'',rules:[]};
  const character={id:'wren',world:'world',name:'Wren',short_name:'Wren',personality:'Calm',voice:'Warm',relationship:'Friend',model:'example',deck:{shared:'lifecycle',cards:[{id:'one',theme:'story',brief:'Original brief',when:{},enabled:true}]}};
  const ok=(action,value)=>b.receive({type:'character_builder',action,ok:true,value:structuredClone(value)});
  b.receive({type:'character_builder',action:'get',kind:'character',ok:true,value:structuredClone(character)});
  b.receive({type:'character_builder',action:'get',kind:'world',ok:true,value:world});
  const lastSaved=()=>sent.filter(m=>m.action==='save_character').at(-1).character;
  const edit=(el,value)=>{if(el.type==='checkbox'){el.checked=value;el.dispatchEvent(new Event('change',{bubbles:true}));}else{el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));}};
  const enabledBox=()=>[...document.querySelectorAll('.builder-card input[type=checkbox]')].at(-1);
  // 1. Edits after a successful save reach the next save (brief and the Enabled checkbox).
  document.querySelector('[data-b-save]').click();ok('save_world',world);ok('save_character',{...character,revision:2});
  edit(document.querySelector('.builder-card textarea'),'Edited after save');edit(enabledBox(),false);
  document.querySelector('[data-b-save]').click();
  const afterSave=lastSaved();
  // 2. Edits made while a save is in flight are not overwritten by its response.
  edit(document.querySelector('.builder-card textarea'),'Typed during save');
  ok('save_world',world);ok('save_character',{...afterSave,revision:3});
  const visible=document.querySelector('.builder-card textarea').value;
  document.querySelector('[data-b-save]').click();
  const inFlight=lastSaved();
  return {afterSave:afterSave.deck.cards[0].brief,afterEnabled:afterSave.deck.cards[0].enabled,afterRevision:afterSave.revision,visible,
   inFlight:inFlight.deck.cards[0].brief,inFlightRevision:inFlight.revision};
 });
 assert(builder.afterSave==='Edited after save'&&builder.afterEnabled===false,'Card edits after a save were not sent: '+JSON.stringify(builder));
 assert(builder.afterRevision===2,'Saved revision was not adopted');
 assert(builder.visible==='Typed during save','Save response overwrote newer on-screen edits');
 assert(builder.inFlight==='Typed during save'&&builder.inFlightRevision===3,'Edit made during a save was lost: '+JSON.stringify(builder));

 // rc2 review: overlapping saves. Only one save is in flight; a second one is queued and sent
 // after the first completes with what is on screen then, so an older reply never wins.
 const overlap=await page.evaluate(async()=>{
  const {mountCharacterBuilder}=await import('/src/js/ai/character-builder.js');
  const host=document.createElement('div');document.body.append(host);
  const sent=[];const b=mountCharacterBuilder(host,{send:m=>{sent.push(structuredClone(m));return true;}});
  const world={id:'world',name:'World',setting:'An island',lore:'',rules:[]};
  const character={id:'wren',world:'world',name:'Wren',short_name:'Wren',personality:'Calm',voice:'Warm',relationship:'Friend',model:'example',deck:{shared:'lifecycle',cards:[{id:'one',theme:'story',brief:'Original brief',when:{},enabled:true}]}};
  const ok=(action,value)=>b.receive({type:'character_builder',action,ok:true,value:structuredClone(value)});
  b.receive({type:'character_builder',action:'get',kind:'character',ok:true,value:structuredClone(character)});
  b.receive({type:'character_builder',action:'get',kind:'world',ok:true,value:world});
  const q=s=>host.querySelector(s),saves=()=>sent.filter(m=>m.action==='save_character');
  const edit=(el,text)=>{el.value=text;el.dispatchEvent(new Event('input',{bubbles:true}));};
  q('[data-b-save]').click();
  edit(q('.builder-card textarea'),'Brief saved by second request');
  q('[data-b-preview]').click();
  const sentWhileBusy=saves().length;
  ok('save_world',world);ok('save_character',{...saves()[0].character,revision:1});
  const afterFirstReply=q('.builder-card textarea').value,second=saves().at(-1).character;
  edit(host.querySelectorAll('.builder-card input')[1],'new-theme');
  ok('save_world',world);ok('save_character',{...second,revision:2});
  const previews=sent.filter(m=>m.action==='preview').length;
  q('[data-b-save]').click();const third=saves().at(-1).character;
  // A late reply after a failed save is ignored rather than driving the counter negative.
  b.receive({type:'character_builder',action:'save_world',ok:false,errors:[{path:['world'],message:'x'}]});
  ok('save_character',{...third,revision:9});
  q('[data-b-save]').click();
  return {sentWhileBusy,afterFirstReply,secondBrief:second.deck.cards[0].brief,previews,
   thirdBrief:third.deck.cards[0].brief,thirdTheme:third.deck.cards[0].theme,savesAfterFailure:saves().length};
 });
 assert(overlap.sentWhileBusy===1,'A second save was sent while one was in flight: '+JSON.stringify(overlap));
 assert(overlap.afterFirstReply==='Brief saved by second request','An older save reply replaced newer edits: '+JSON.stringify(overlap));
 assert(overlap.secondBrief==='Brief saved by second request','The queued save did not carry the newer edit: '+JSON.stringify(overlap));
 assert(overlap.previews===0,'Preview was composed although the screen changed after the save was sent: '+JSON.stringify(overlap));
 assert(overlap.thirdBrief==='Brief saved by second request'&&overlap.thirdTheme==='new-theme','Edits lost across overlapping saves: '+JSON.stringify(overlap));
 assert(overlap.savesAfterFailure===4,'Saving got stuck after a failed save: '+JSON.stringify(overlap));

 const events=await page.evaluate(async()=>{
  const {mountEventSettings}=await import('/src/js/ai/event-settings.js');
  const sent=[];const s=mountEventSettings(document.querySelector('#dialog'),{send:m=>{sent.push(m);return true;}});
  const config={enabled:true,preset:'custom',proactive_interval_seconds:120,max_gap_seconds:12,detectors:{},preferences:{generic:{physiology:1,session:1,configuration:1,story:1},'custom.wren':{physiology:0,session:2,configuration:1,story:0}}};
  s.update({config,detectors:[],recent_events:[],active_identity:'custom.wren'});
  const field=k=>document.querySelector('[name="preferences.custom.wren.'+k+'"]');
  const shown={physiology:field('physiology').value,session:field('session').value,story:field('story').value};
  field('configuration').value='2';field('configuration').dispatchEvent(new Event('input',{bubbles:true}));
  document.querySelector('[data-event-form]').dispatchEvent(new Event('submit',{cancelable:true}));
  return {shown,preferences:sent.at(-1)?.config.preferences};
 });
 assert(JSON.stringify(events.shown)==='{"physiology":"0","session":"2","story":"0"}','Custom preferences were not reloaded: '+JSON.stringify(events.shown));
 assert(JSON.stringify(Object.keys(events.preferences).sort())==='["custom.wren","generic"]','Malformed preference identities: '+JSON.stringify(events.preferences));
 assert(JSON.stringify(events.preferences['custom.wren'])==='{"physiology":0,"session":2,"configuration":2,"story":0}','Custom preference not saved: '+JSON.stringify(events.preferences));

 // Personal opening/closing briefs must survive normal-card editing and count
 // toward the existing sixteen-card limit. No server or activation is used.
 const lifecycle=await page.evaluate(async()=>{
  const {mountCharacterBuilder}=await import('/src/js/ai/character-builder.js');
  const host=document.createElement('div');document.body.append(host);const sent=[];
  const builder=mountCharacterBuilder(host,{send:m=>{sent.push(structuredClone(m));return true;}});
  const world={id:'test-world',name:'World',setting:'A fictional world',lore:'',rules:[]};
  const opening={id:'opening',theme:'greeting',brief:'Greet in character.'};
  const closing={id:'closing',theme:'farewell',brief:'Say farewell in character.'};
  const character={id:'mira',world:world.id,name:'Mira',short_name:'Mira',personality:'Witty',voice:'Concise',relationship:'Companion',model:'mira-narrative-v1:latest',deck:{shared:'lifecycle',session_start:opening,session_end:closing,cards:Array.from({length:10},(_,i)=>({id:'card-'+i,theme:'banter',brief:'Offer a fresh remark.',when:{},enabled:true}))}};
  builder.receive({type:'character_builder',action:'get',kind:'character',ok:true,value:character});
  builder.receive({type:'character_builder',action:'get',kind:'world',ok:true,value:world});
  const count=host.querySelector('[data-b-count]').textContent;
  const add=host.querySelector('[data-b-add]');for(let i=0;i<4;i++)add.click();
  const full=add.disabled;
  host.querySelector('[data-b-save]').click();
  const saved=sent.filter(m=>m.action==='save_character').at(-1).character;
  return {count,full,cards:saved.deck.cards.length,opening:saved.deck.session_start,closing:saved.deck.session_end};
 });
 assert(lifecycle.count.startsWith('12 of 16'),'Lifecycle overrides missing from card count: '+JSON.stringify(lifecycle));
 assert(lifecycle.full&&lifecycle.cards===14,'Lifecycle overrides exceeded the authored-card limit: '+JSON.stringify(lifecycle));
 assert(lifecycle.opening.brief==='Greet in character.'&&lifecycle.closing.brief==='Say farewell in character.','Lifecycle briefs lost during save');
 assert(!errors.length,'Page errors: '+errors.join('; '));
 console.log('character-builder-regressions-browser: passed');
}finally{await browser.close();}
