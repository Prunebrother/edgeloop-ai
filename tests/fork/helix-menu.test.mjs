// SPDX-License-Identifier: AGPL-3.0-only
// The real menu with a small DOM stand-in: no browser, sockets or live application state.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mountMainMenu} from '../../src/js/ai/main-menu.js';

const all=n=>[n,...n.children.flatMap(all)];
class Element{
    constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.attrs={};this.dataset={};this.hidden=false;this.listeners={};this._text='';
        this.classList={add:()=>{},remove:()=>{},contains:()=>false};}
    set textContent(value){this._text=String(value);this.children=[];}
    get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
    setAttribute(k,v){this.attrs[k]=String(v);if(k==='disabled')this.disabled=true;}
    append(...children){for(const child of children){const n=child instanceof Element?child:Object.assign(new Element('text'),{textContent:child});n.parentElement=this;this.children.push(n);}}
    prepend(...children){for(const child of children.reverse()){child.parentElement=this;this.children.unshift(child);}}
    replaceChildren(...children){this.children=[];this.append(...children);}
    remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);}
    addEventListener(kind,fn){if(fn)(this.listeners[kind]??=[]).push(fn);}
    removeEventListener(){}
    contains(target){return all(this).includes(target);}
    focus(){document.activeElement=this;}
    closest(selector){for(let el=this;el;el=el.parentElement)if(selector==='[data-menu-list]'&&el.attrs['data-menu-list']!==undefined)return el;return null;}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    querySelectorAll(selector){
        const nodes=all(this).slice(1),buttons=nodes.filter(n=>n.tagName==='BUTTON'&&!n.disabled);
        if(selector.includes(':scope > li > button'))return buttons;
        if(selector.includes('button:not([disabled])'))return buttons.filter(n=>!selector.includes(':not([aria-disabled])')||!n.attrs['aria-disabled']);
        if(selector==='[data-autofocus]')return nodes.filter(n=>Object.hasOwn(n.attrs,'data-autofocus'));
        if(selector==='.game-menu-back')return nodes.filter(n=>n.className==='game-menu-back');
        if(selector==='button')return buttons;
        return [];
    }
    click(){for(const fn of this.listeners.click||[])fn();}
}
const flush=async()=>{for(let i=0;i<6;i++)await Promise.resolve();};
const find=(root,predicate)=>all(root).find(predicate);
const button=(root,text)=>find(root,n=>n.tagName==='BUTTON'&&n.textContent===text);
const klass=(root,value)=>find(root,n=>n.className===value);
const key=(root,key,target=document.activeElement)=>{for(const fn of root.listeners.keydown||[])fn({key,target,preventDefault(){},stopPropagation(){}});};
const mission={id:'h1_entry_protocol',order:1,title:'Entry Protocol',summary:'PLACEHOLDER mission',companion:'iris',state:'available',
    prerequisites:[],objectives:[],rewards:[],completions:0,chapter:1,replay:'allowed',narrative_status:'placeholder',narrative_draft:false};
const campaign={id:'rise_of_helix',title:'Rise of Helix',description:'PLACEHOLDER campaign',available:false,completed:false,
    locked_reason:'Complete The Asterion Initiative to unlock.',narrative_status:'placeholder',progress:{completed:0,total:5},
    chapters:[{id:'undercover',number:1,title:'Chapter 1 (placeholder)',summary:'PLACEHOLDER chapter',available:true,progress:{completed:0,total:1}},
        {id:'helix_ch2',number:2,title:'Chapter 2',summary:'PLACEHOLDER chapter',teaser:true,progress:{completed:0,total:0}}],missions:[mission]};

function mount(t){
    const saved=Object.fromEntries(['document','window','getComputedStyle','fetch'].map(k=>[k,globalThis[k]]));
    const body=new Element('body'),banner=new Element('section');body.append(banner);
    globalThis.document={body,activeElement:null,createElement:tag=>new Element(tag),getElementById:id=>find(body,n=>n.attrs.id===id),querySelector:()=>null,addEventListener(){},removeEventListener(){}};
    globalThis.window={addEventListener(){},removeEventListener(){}};globalThis.getComputedStyle=()=>({display:'block'});
    const requests=[];globalThis.fetch=async()=>({ok:false});
    const menu=mountMainMenu({send:m=>{requests.push(m);return true;},status:()=> 'IDLE',selectCompanion:()=> 'This companion is not installed.',bannerHost:banner});
    const root=find(body,n=>n.attrs.id==='main-menu');
    t.after(()=>{menu.destroy();for(const [k,v] of Object.entries(saved)){if(v===undefined)delete globalThis[k];else globalThis[k]=v;}});
    return {body,banner,menu,root,requests};
}

test('locked card is focusable with arrows/Tab, states its reason and cannot activate',async t=>{
    const {menu,root,requests}=mount(t);
    const first={...campaign,id:'asterion_initiative',title:'The Asterion Initiative',available:true,narrative_status:'approved',locked_reason:null};
    menu.receive({type:'campaign_state',campaigns:[first,campaign],active:null});
    // Find the home tile by dataset: its detail changes with available mission data.
    find(root,n=>n.dataset.menuTile==='campaign').click();await flush();
    const cards=all(root).filter(n=>n.className==='game-menu-card'),locked=cards[1];
    assert.equal(locked.attrs['aria-disabled'],'true');assert.equal(locked.disabled,undefined);
    assert.match(locked.textContent,/Complete The Asterion Initiative to unlock\./);
    assert.match(locked.textContent,/Locked.*Placeholder/);
    cards[0].focus();key(root,'ArrowDown');assert.equal(document.activeElement,locked);
    // The Tab trap includes aria-disabled cards; it wraps only at the actual final focusable control.
    key(root,'Tab',locked);assert.equal(document.activeElement.className,'game-menu-back');
    const before=requests.length;locked.click();assert.equal(root.dataset.view,'campaigns');assert.equal(requests.length,before);
});

test('placeholder badges, teaser, unknown companion install gate and Escape use the real menu',async t=>{
    const {menu,root,requests}=mount(t);
    menu.receive({type:'campaign_state',campaigns:[{...campaign,available:true,locked_reason:null}],active:null});
    find(root,n=>n.dataset.menuTile==='campaign').click();await flush();klass(root,'game-menu-card').click();await flush();
    assert.equal(root.dataset.view,'missions');
    assert.equal(all(root).filter(n=>n.attrs['data-state']==='placeholder').length,3);
    assert.match(klass(root,'mission-detail').textContent,/Iris Vale/);assert.doesNotMatch(klass(root,'mission-detail').textContent,/Iris Vale \(placeholder\)/);
    // Iris is a menu host since 2026-11-20, so her approved cut-out stands on the board.
    assert.deepEqual(all(root).filter(n=>n.tagName==='IMG'&&n.className==='board-figure').map(n=>n.attrs.src),['/src/assets/menu/companions/iris.webp']);
    find(root,n=>n.dataset.chapter===2).click();assert.match(root.textContent,/Coming soon/);
    find(root,n=>n.dataset.chapter===1).click();button(root,'Start mission').click();
    assert.equal(requests.at(-1).action,'start');
    menu.receive({type:'campaign_state',campaigns:[{...campaign,available:true}],active:{campaign:campaign.id,mission:mission.id}});
    menu.receive({type:'mission_text',campaign:campaign.id,mission:mission.id,narrative_status:'placeholder',hints:[],briefing:{speaker:'iris',lines:['PLACEHOLDER briefing']}});
    await flush();assert.equal(root.dataset.view,'briefing');assert.match(root.textContent,/Placeholder.*PLACEHOLDER briefing/);
    button(root,'Begin with Iris Vale').click();assert.match(root.textContent,/not installed/);assert.equal(root.hidden,false);
    key(root,'Escape');assert.equal(root.dataset.view,'missions');key(root,'Escape');assert.equal(root.dataset.view,'campaigns');
});

test('new campaign is listed in completion toast and results',async t=>{
    const {menu,root,banner}=mount(t);
    menu.receive({type:'campaign_state',campaigns:[campaign],active:null});root.hidden=true;
    menu.receive({type:'mission_result',campaign:'asterion_initiative',mission:'final',title:'Final mission',campaign_complete:true,
        earned:[],objectives:[],unlocked_campaigns:[{id:'rise_of_helix',title:'Rise of Helix'}]});
    await flush();assert.equal(root.dataset.view,'results');assert.match(root.textContent,/New campaign: Rise of Helix/);
    assert.match(banner.textContent,/New campaign: Rise of Helix/);
});
