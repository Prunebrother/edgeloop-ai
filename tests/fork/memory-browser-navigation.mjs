// SPDX-License-Identifier: AGPL-3.0-only
// UI-only navigation over the real responsive layout; never mutates application state with evaluate().
export async function inspectManagementDOM(page){
 return page.evaluate(()=>{
  const describe=selector=>{
   const elements=[...document.querySelectorAll(selector)];
   return {selector,count:elements.length,elements:elements.map(el=>{
    const style=getComputedStyle(el),bounds=el.getBoundingClientRect(),ancestors=[];
    for(let node=el;node&&ancestors.length<8;node=node.parentElement){const css=getComputedStyle(node);if(css.display==='none'||css.visibility==='hidden'||node.hidden||node.matches('details:not([open])'))ancestors.push({tag:node.tagName,id:node.id,display:css.display,visibility:css.visibility,hidden:node.hidden,open:node.getAttribute('open')});}
    return {tag:el.tagName,id:el.id,role:el.getAttribute('role'),open:el.getAttribute('open'),expanded:el.getAttribute('aria-expanded'),disabled:!!el.disabled,display:style.display,visibility:style.visibility,width:bounds.width,height:bounds.height,ancestors};
   })};
  };
  return {viewport:{width:innerWidth,height:innerHeight},three_columns:matchMedia('(min-width:1500px)').matches,view:document.querySelector('#companion-dashboard')?.dataset.view,targets:['#character-panel','[data-view="character"]','[data-view="chat"]','#character-panel [data-menu-story]','#character-story','#character-story [data-curator-enabled]','#character-director'].map(describe)};
 });
}
export function curatorMatches(config,arm){return config?.enabled===(arm==='C')&&(arm!=='C'||config.interval_turns===8&&config.timeout_seconds===20);}
export function createMemoryNavigation(page,{timeout=30000}={}){
 const panel=page.locator('#character-panel'),chat=page.locator('#ai-companion');
 async function fail(label,reason,cause){
  const error=new Error(`${label}: ${reason}`);error.cause=cause;
  try{error.navigation=await inspectManagementDOM(page);}catch{}
  return error;
 }
 async function required(locator,label){
  const count=await locator.count();if(count!==1)throw await fail(label,count===0?'missing element':`ambiguous locator (${count} elements)`);
  if(!await locator.isVisible())throw await fail(label,'element is hidden; inspect navigation visibility/closed ancestors');
  return locator;
 }
 async function click(locator,label){
  await required(locator,label);
  try{await locator.click({timeout});}catch(cause){throw await fail(label,await locator.isEnabled()?'element is obstructed or not actionable':'element is disabled',cause);}
 }
 async function character(){
  if(await panel.count()!==1)throw await fail('Character management','missing #character-panel');
  if(!await panel.isVisible())await click(page.locator('[data-view="character"][aria-controls="character-panel"]'),'Character view button');
  await required(panel,'Character panel');
 }
 async function open(kind){
  await character();
  const drawer=panel.locator(`#character-${kind}`),button=panel.getByRole('button',{name:kind==='story'?'Story Memory':'Director',exact:true,includeHidden:true});
  if(!await drawer.isVisible())await click(button,kind==='story'?'Story Memory drawer button':'Director drawer button');
  await required(drawer,`${kind} drawer`);
  if(await drawer.getAttribute('open')===null)throw await fail(`${kind} drawer`,'dialog is not open');
  return drawer;
 }
 async function close(){
  const dialogs=panel.locator('dialog[open]');
  while(await dialogs.count())await click(dialogs.first().getByRole('button',{name:/^Close /}),'Close character drawer');
 }
 async function showChat(){
  await close();const chatTab=page.locator('[data-view="chat"][aria-controls="ai-companion"]'),characterTab=page.locator('[data-view="character"][aria-controls="character-panel"]');
  if(await chatTab.isVisible()){
   if(await chatTab.getAttribute('aria-pressed')!=='true')await click(chatTab,'Chat view button');
  }else if(await characterTab.isVisible()&&await characterTab.getAttribute('aria-pressed')==='true')await click(characterTab,'Close responsive Character overlay');
  await required(chat,'Chat panel');
 }
 async function curator(){
  const drawer=await open('story');
  // The current UI uses a section, not an accordion. If an accessible disclosure is added,
  // open only ancestors of the actual controls, never an unrelated objective accordion.
  const control=drawer.locator('[data-curator-enabled]');
  if(await control.count()!==1)throw await fail('Experimental memory curator','missing [data-curator-enabled] in Story Memory');
  const closed=drawer.locator('details:not([open])').filter({has:page.locator('[data-curator-enabled]')});
  while(await closed.count())await click(closed.first().locator(':scope > summary'),'Curator disclosure');
  await required(control,'Curator enable checkbox');return drawer;
 }
 return {openStory:()=>open('story'),openDirector:()=>open('director'),openCurator:curator,close,showChat,required,click};
}
