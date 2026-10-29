// SPDX-License-Identifier: AGPL-3.0-only
import test from 'node:test';import assert from 'node:assert/strict';
import {curatorMatches} from './memory-browser-navigation.mjs';
test('A/B require verified disabled curation, with no irrelevant interval changes',()=>{
 for(const arm of ['A','B']){assert(curatorMatches({enabled:false,interval_turns:10},arm));assert(!curatorMatches({enabled:true,interval_turns:8},arm));assert(!curatorMatches(undefined,arm));}
});
test('C must acknowledge enabled curation and the intended interval/timeout',()=>{
 assert(curatorMatches({enabled:true,interval_turns:8,timeout_seconds:20},'C'));
 assert(!curatorMatches({enabled:false,interval_turns:8,timeout_seconds:20},'C'));
 assert(!curatorMatches({enabled:true,interval_turns:10,timeout_seconds:20},'C'));
 assert(!curatorMatches({enabled:true,interval_turns:8,timeout_seconds:5},'C'));
});

// Locator contract tests complement the actual CSS/DOM Playwright regression.
function responsivePage(width=1440){
 const state={width,view:'chat',story:false,director:false,missing:false,hideStory:false,actions:[]};
 const panelVisible=()=>width>=1500||state.view==='character';
 function locator(key){return {
  async count(){if(key==='story-button'&&state.missing)return 0;if(key==='dialogs')return Number(state.story||state.director);return 1;},
  async isVisible(){if(key==='character-tab')return width<1500;if(key==='chat-tab')return width<=760;if(key==='panel')return panelVisible();if(key==='chat')return width>760||state.view==='chat';if(key==='story-button')return panelVisible()&&!state.hideStory;if(key==='story'||key==='director')return panelVisible()&&state[key];return panelVisible();},
  async isEnabled(){return true;},
  async getAttribute(name){if(name==='open')return state[key]?'':null;if(name==='aria-pressed')return String(state.view===(key==='character-tab'?'character':'chat'));return null;},
  async click(){assert(await this.isVisible(),key+' is hidden');state.actions.push(key);if(key==='character-tab')state.view=state.view==='character'?'chat':'character';if(key==='chat-tab')state.view='chat';if(key==='story-button'){state.story=!state.story;state.director=false;}if(key==='close'){state.story=false;state.director=false;}},
  locator(selector){return locator(selector==='#character-story'?'story':selector==='#character-director'?'director':selector==='dialog[open]'?'dialogs':selector);},
  getByRole(_role,options){return locator(options.name==='Story Memory'?'story-button':options.name instanceof RegExp?'close':'director-button');},
  first(){return locator(state.story?'story':'director');},
 };}
 return {state,locator(selector){return locator(selector==='#character-panel'?'panel':selector==='#ai-companion'?'chat':selector.includes('[data-view="character"]')?'character-tab':'chat-tab');},async evaluate(){return {viewport:{width},view:state.view,hidden:!panelVisible()};}};
}
test('two-column navigation opens Character before Story Memory and restores unobstructed Chat',async()=>{
 const {createMemoryNavigation}=await import('./memory-browser-navigation.mjs');const page=responsivePage(),nav=createMemoryNavigation(page);
 await nav.openStory();assert.deepEqual(page.state.actions,['character-tab','story-button']);await nav.showChat();assert.equal(page.state.view,'chat');assert.equal(page.state.story,false);
});
test('mobile navigation returns through the accessible Chat tab',async()=>{
 const {createMemoryNavigation}=await import('./memory-browser-navigation.mjs');const page=responsivePage(390),nav=createMemoryNavigation(page);
 await nav.openStory();await nav.showChat();assert.equal(page.state.actions.at(-1),'chat-tab');assert.equal(page.state.view,'chat');
});
test('three-column navigation avoids hidden view toggles and does not close an already-open drawer',async()=>{
 const {createMemoryNavigation}=await import('./memory-browser-navigation.mjs');const page=responsivePage(1920),nav=createMemoryNavigation(page);
 await nav.openStory();await nav.openStory();assert.deepEqual(page.state.actions,['story-button']);
});
test('navigation errors distinguish missing and hidden Story Memory controls',async()=>{
 const {createMemoryNavigation}=await import('./memory-browser-navigation.mjs');const page=responsivePage(1920),nav=createMemoryNavigation(page);
 page.state.missing=true;await assert.rejects(nav.openStory(),error=>/Story Memory.*missing element/.test(error.message)&&!!error.navigation);
 page.state.missing=false;page.state.hideStory=true;await assert.rejects(nav.openStory(),/Story Memory.*hidden/);
});
