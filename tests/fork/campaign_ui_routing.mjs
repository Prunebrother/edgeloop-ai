// SPDX-License-Identifier: AGPL-3.0-only
// Minimal-DOM harness (from the Codex Chapter 3 review): feeds observer messages to the real main-menu module and
// routes one key press from a puzzle button the way the browser would, reporting conversation lines and engine actions.
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
class Element {
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.parentElement=null;this.attrs={};this.dataset={};this.hidden=false;this.listeners={};const values=new Set();this.classList={add:v=>values.add(v),remove:v=>values.delete(v),contains:v=>values.has(v)};}
  setAttribute(k,v){this.attrs[k]=String(v);if(k==='hidden')this.hidden=true;}
  append(...items){for(const n of items)if(n instanceof Element){n.parentElement=this;this.children.push(n);}}
  prepend(...items){for(const n of items.reverse())if(n instanceof Element){n.parentElement=this;this.children.unshift(n);}}
  replaceChildren(...items){for(const n of this.children)n.parentElement=null;this.children=[];this.append(...items);}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);}
  addEventListener(type,fn){if(fn)(this.listeners[type]??=[]).push(fn);}
  removeEventListener(type,fn){this.listeners[type]=(this.listeners[type]||[]).filter(f=>f!==fn);}
  querySelector(){return null;}
  querySelectorAll(){return [];}
  closest(){return null;}
  contains(target){for(let n=target;n;n=n.parentElement)if(n===this)return true;return false;}
  focus(){document.activeElement=this;}
}
const all=(n)=>[n,...n.children.flatMap(all)];
const docListeners={};const windowListeners={};
globalThis.document={body:new Element('body'),createElement:t=>new Element(t),activeElement:null,
 getElementById:id=>all(document.body).find(n=>n.attrs.id===id)||null,querySelector:()=>null,
 addEventListener:(type,fn)=>(docListeners[type]??=[]).push(fn),removeEventListener:()=>{}};
globalThis.window={addEventListener:(type,fn)=>(windowListeners[type]??=[]).push(fn),removeEventListener:()=>{}};
globalThis.getComputedStyle=()=>({display:'block'});globalThis.confirm=()=>true;
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const {mountMainMenu}=await import(pathToFileURL(input.repo+'/src/js/ai/main-menu.js').href);
const {keyEventIsTyping,actionForKey,defaultKeybinds}=await import(pathToFileURL(input.repo+'/src/js/keybinds.js').href);
const host=new Element('section');document.body.append(host);const lines=[];const sent=[];
const menu=mountMainMenu({send:m=>{sent.push(m);return true;},status:()=> 'RUNNING',selectCompanion:()=>true,postLines:(block,label)=>lines.push({block,label}),bannerHost:host});
document.getElementById('main-menu').hidden=true;
for(const message of input.messages)menu.receive(message);
let engineActions=[];
if(input.key){
 const button=all(host).find(n=>Object.hasOwn(n.attrs,'data-puzzle-option'));
 if(!button)throw new Error('No puzzle option rendered');
 const e={type:'keydown',key:input.key==='Space'?' ':input.key,code:input.key,target:button,defaultPrevented:false,stopped:false,preventDefault(){this.defaultPrevented=true;},stopPropagation(){this.stopped=true;},stopImmediatePropagation(){this.stopped=true;}};
 for(const f of windowListeners.keydown||[])f(e);
 for(let n=button;n&&!e.stopped;n=n.parentElement)for(const f of n.listeners.keydown||[])f(e);
 if(!e.stopped){
  for(const f of docListeners.keydown||[])f(e);
  if(!keyEventIsTyping(e.target,e.code)){const action=actionForKey(defaultKeybinds(),e.code);if(action){e.preventDefault();engineActions.push(action);}}
 }
}
menu.destroy();
process.stdout.write(JSON.stringify({lines,sent,engineActions}));
