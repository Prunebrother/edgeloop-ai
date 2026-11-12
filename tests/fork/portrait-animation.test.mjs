// SPDX-License-Identifier: AGPL-3.0-only
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {CharacterPresentation} from '../../src/js/ai/character.js';
import {CHARACTER_MANIFEST,resolveArtwork,animationPath,setCustomCharacter} from '../../src/js/ai/artwork-manifest.js';
import {createPlayerInteractions} from '../../src/js/player/interactions.js';

const catalog=()=>({models:{'a:latest':'a','b:latest':'b'},characters:{a:{name:'A',expressions:{neutral:'/a.png',happy:'/a-happy.png'},animations:{neutral:{webm:'/Character_Art/A/idle.webm',mp4:'/Character_Art/A/idle.mp4'}}},b:{name:'B',expressions:{neutral:'/b.png'}}},presentation:{animated_characters_enabled:true}});
const flush=async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve();};
function rig(c=catalog()){
 const saved=new Map(),nodes=[],listeners=new Map(),observers=[],frames=[];
 const globals={};
 class Node {
  constructor(tag='DIV'){this.tagName=tag;this.dataset={};this.style={};this.attributes={};this.children=[];this.classList={add:()=>{}};this.paused=true;this.readyState=2;nodes.push(this);}
  set innerHTML(v){this.html=v;}
  set src(v){this.attributes.src=v;}get src(){return this.attributes.src;}
  getAttribute(k){return this.attributes[k]??null;}setAttribute(k,v){this.attributes[k]=v;}
  removeAttribute(k){delete this.attributes[k];}
  append(n){n.remove();this.children.push(n);n.parent=this;}
  replaceChildren(...ns){for(const n of [...this.children])n.remove();for(const n of ns)this.append(n);}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);this.parent=null;}
  getBoundingClientRect(){return {width:100,height:150,bottom:150,right:100,top:0,left:0};}
  getClientRects(){return globals.hiddenPanel?[]:[{}];}
  canPlayType(mime){return globals.unsupported?.includes(mime)?'':'probably';}
  play(){this.playCalls=(this.playCalls||0)+1;if(globals.rejectPlay)return Promise.reject(Error('autoplay'));this.paused=false;return globals.playPromise||Promise.resolve();}
  pause(){this.paused=true;}
  load(){this.loads=(this.loads||0)+1;}
  decode(){return globals.decodePromise||Promise.resolve();}
  requestVideoFrameCallback(fn){this.frame=fn;return 1;}cancelVideoFrameCallback(){this.frame=null;}
 }
 const host=new Node(),queries=new Map();host.querySelector=s=>{if(!queries.has(s))queries.set(s,new Node());return queries.get(s);};
 const on=(k,fn)=>listeners.set(k,fn),off=k=>listeners.delete(k);
 const motion={matches:false,addEventListener:(k,fn)=>on('motion',fn),removeEventListener:()=>off('motion')};
 class Observer{constructor(cb){this.cb=cb;observers.push(this);}observe(){}disconnect(){this.disconnected=true;}}
 const env={document:{hidden:false,addEventListener:on,removeEventListener:off,createElement:t=>new Node(t.toUpperCase())},window:{addEventListener:on,removeEventListener:off},Image:class extends Node{constructor(){super('IMG');}},matchMedia:()=>motion,IntersectionObserver:Observer,ResizeObserver:Observer,MutationObserver:Observer,getComputedStyle:()=>({visibility:'visible'}),innerWidth:1000,innerHeight:1000,requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},cancelAnimationFrame:id=>{frames[id-1]=()=>{};}};
 for(const [k,v]of Object.entries(env)){saved.set(k,Object.getOwnPropertyDescriptor(globalThis,k));Object.defineProperty(globalThis,k,{configurable:true,writable:true,value:v});}
 const renderer=new CharacterPresentation(host,c);
 const restore=()=>{renderer.destroy();for(const [k,v]of saved){if(v)Object.defineProperty(globalThis,k,v);else delete globalThis[k];}};
 return {renderer,host,nodes,globals,motion,listeners,observers,frames,env,restore,async image(){const n=renderer.pending;assert.equal(n?.tagName,'IMG');n.onload();await flush();return n;},async video(){const n=renderer.pending;assert.equal(n?.tagName,'VIDEO');n.onloadeddata();await flush();n.frame?.();return n;}};
}

test('optional catalog clips are exact-expression, default off and curated paths only',()=>{
 const c=catalog();assert.equal(resolveArtwork('a:latest','happy',c).animations.length,0);
 assert.deepEqual(resolveArtwork('a:latest','neutral',c).animations.map(x=>x.format),['webm','mp4']);
 c.presentation.animated_characters_enabled=false;assert.deepEqual(resolveArtwork('a:latest','neutral',c).animations,[]);
 delete c.presentation;assert.deepEqual(resolveArtwork('a:latest','neutral',c).animations,[]);
 for(const src of ['https://other/idle.webm','//other/idle.webm','/Character_Art/A/../idle.webm','/Character_Art/A/%2e.webm','/Character_Art/A/x.webm?q=1','/Character_Art/A/x.mp4'])assert.equal(animationPath(src,'webm'),null,src);
});
test('custom portrait on an animated built-in model never inherits its clips or requires a new schema',()=>{
 const c=CHARACTER_MANIFEST,old=c.presentation.animated_characters_enabled;
 const character=c.characters.nova,animations=character.animations;
 try{
  c.presentation.animated_characters_enabled=true;character.animations={neutral:{webm:'/Character_Art/Nova/idle.webm'}};
  const model=Object.keys(c.models).find(m=>c.models[m]==='nova');
  setCustomCharacter(model,{identity:'custom.wren',name:'Wren',portrait:{file:'a'.repeat(64)+'.png'}},'http://127.0.0.1:8768');
  for(const e of c.expressions){const view=resolveArtwork(model,e);assert.equal(view.id,'custom.wren');assert.equal(view.animations.length,0);assert.equal(view.candidates[0].expression,e);}
 }finally{setCustomCharacter(null);c.presentation.animated_characters_enabled=old;if(animations)character.animations=animations;else delete character.animations;}
});
test('disabled rendering preserves image-only loading, fallback, reuse and teardown',async()=>{
 const c=catalog();c.presentation.animated_characters_enabled=false;const r=rig(c);
 try{
  r.renderer.setState({model:'a:latest'});const img=await r.image();
  r.renderer.setState({activity:'generating'});assert.equal(r.renderer.displayed,img);assert.equal(r.renderer.pending,null);
  r.renderer.setState({expression:'happy'});assert.equal(r.renderer.displayed,img);r.renderer.pending.onerror();
  assert.equal(r.renderer.pending.src,'/a.png');await r.image();assert.equal(r.host.dataset.expression,'happy');assert.equal(r.host.dataset.renderedExpression,'neutral');
  assert.equal(r.nodes.filter(n=>n.tagName==='VIDEO').length,0);
 }finally{r.restore();}assert(r.observers.every(o=>o.disconnected));assert.equal(r.listeners.size,0);
});
test('first-frame readiness retains PNG, looping is local, activity does not restart playback',async()=>{
 const r=rig();const events=[];const player=createPlayerInteractions({uuid:()=> 'fixture',notify:e=>events.push(e)});const baseline=player.snapshot();
 try{
  r.renderer.setState({model:'a:latest',expression:'happy'});const png=await r.image();
  r.renderer.setState({expression:'neutral'});const video=r.renderer.pending;
  video.onloadeddata();await flush();assert.equal(r.renderer.displayed,png,'play promise alone is not a displayed frame');
  video.frame();assert.equal(r.renderer.displayed,video);assert(video.muted&&video.loop&&video.playsInline);assert.equal(video.controls,undefined);
  r.renderer.setState({activity:'generating'});assert.equal(video.playCalls,1);assert.equal(r.renderer.pending,null);
  assert.deepEqual(player.snapshot(),baseline);assert.equal(events.length,0);
 }finally{r.restore();}
});
test('invalid videos and autoplay rejection fall through once to exact-expression PNG',async()=>{
 const r=rig();try{
  r.globals.rejectPlay=true;r.renderer.setModel('a:latest');const webm=r.renderer.pending;webm.onloadeddata();await flush();
  assert.equal(r.renderer.pending.src,'/Character_Art/A/idle.mp4');const mp4=r.renderer.pending;mp4.onerror();await r.image();
  assert.equal(r.renderer.displayed.src,'/a.png');assert.equal(r.host.dataset.expression,'neutral');assert(webm.paused&&mp4.paused);
  r.renderer.setState({activity:'idle'});assert.equal(r.renderer.pending,null);
  r.renderer.setState({expression:'happy'});await r.image();r.renderer.setState({expression:'neutral'});assert.equal(r.renderer.pending.tagName,'IMG');
 }finally{r.restore();}
});
test('unsupported VP9 uses MP4; later video failure recovers without changing expression',async()=>{
 const r=rig();try{
  r.globals.unsupported=['video/webm; codecs="vp9"'];r.renderer.setModel('a:latest');assert.equal(r.renderer.pending.src,'/Character_Art/A/idle.mp4');
  const video=await r.video();video.onerror();await r.image();assert.equal(r.host.dataset.expression,'neutral');assert.equal(r.renderer.displayed.src,'/a.png');assert(video.paused);
  await new Promise(resolve=>setTimeout(resolve,400));assert.equal(video.src,undefined);
 }finally{r.restore();}
});
test('late video and image results cannot replace a newer character or emotion',async()=>{
 const r=rig();try{
  r.renderer.setModel('a:latest');const old=r.renderer.pending;const loaded=old.onloadeddata;
  loaded();await flush();const frame=old.frame;
  r.renderer.setState({model:'b:latest'});assert.equal(r.renderer.displayed,null);const b=await r.image();frame();assert.equal(r.renderer.displayed,b);assert(old.paused);assert.equal(old.src,undefined);
  r.renderer.setState({model:'a:latest',expression:'happy'});const img=r.renderer.pending;const onload=img.onload;
  r.renderer.setState({expression:'neutral'});const video=await r.video();await onload();assert.equal(r.renderer.displayed,video);
 }finally{r.restore();}
});
test('hidden panel, document visibility, page lifecycle and reduced motion stop clips and retain latest state',async()=>{
 const r=rig();try{
  r.renderer.setModel('a:latest');const video=await r.video();
  r.globals.hiddenPanel=true;r.renderer.policyChanged();assert(video.paused);await r.image();assert.equal(video.src,undefined);
  r.renderer.setState({expression:'happy'});await r.image();r.globals.hiddenPanel=false;r.renderer.policyChanged();assert.equal(r.renderer.pending,null,'happy has no clip');
  r.renderer.setState({expression:'neutral'});await r.video();r.motion.matches=true;r.listeners.get('motion')();await r.image();assert.equal(r.renderer.displayed.tagName,'IMG');
  r.motion.matches=false;r.listeners.get('motion')();await r.video();r.env.document.hidden=true;r.listeners.get('visibilitychange')();await r.image();
  r.env.document.hidden=false;r.listeners.get('visibilitychange')();await r.video();r.listeners.get('pagehide')();await r.image();r.listeners.get('pageshow')();await r.video();
  r.host.dataset.presentationOccluded='true';r.renderer.policyChanged();await r.image();r.host.dataset.presentationOccluded='false';r.renderer.policyChanged();await r.video();
 }finally{r.restore();}
});
test('video handoffs and repeated switches cap decoders at two and dispose outgoing media',async()=>{
 const c=catalog();c.characters.a.animations.happy={webm:'/Character_Art/A/happy.webm'};const r=rig(c);
 try{
  r.renderer.setModel('a:latest');await r.video();
  for(let i=0;i<12;i++){
   r.renderer.setState({expression:i%2?'neutral':'happy'});await r.video();
   assert(r.nodes.filter(n=>n.tagName==='VIDEO'&&n.src).length<=2);
  }
  await new Promise(resolve=>setTimeout(resolve,400));assert.equal(r.nodes.filter(n=>n.tagName==='VIDEO'&&n.src).length,1);
 }finally{r.restore();}assert.equal(r.nodes.filter(n=>n.tagName==='VIDEO'&&n.src).length,0);
});
test('readiness timeout is bounded, tries MP4 once and returns to PNG',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const r=rig();try{
  r.renderer.setModel('a:latest');const webm=r.renderer.pending;t.mock.timers.tick(6001);
  assert.equal(r.renderer.pending.src,'/Character_Art/A/idle.mp4');assert.equal(webm.src,undefined);
  t.mock.timers.tick(6001);await r.image();assert.equal(r.renderer.displayed.src,'/a.png');
 }finally{r.restore();t.mock.timers.reset();}
});
test('a late autoplay promise and a late image decode cannot resurrect disposed media',async()=>{
 const r=rig();try{
  let resolvePlay;r.globals.playPromise=new Promise(resolve=>{resolvePlay=resolve;});
  r.renderer.setModel('a:latest');const old=r.renderer.pending;old.onloadeddata();
  r.renderer.setModel('b:latest');await r.image();resolvePlay();await flush();assert(!old.frame);assert.equal(r.renderer.displayed.src,'/b.png');
  let decode;r.globals.decodePromise=new Promise(resolve=>{decode=resolve;});
  r.renderer.setState({model:'a:latest',expression:'happy'});const stale=r.renderer.pending;stale.onload();
  r.renderer.setModel('b:latest');decode();await flush();await r.image();assert.equal(r.renderer.displayed.src,'/b.png');
 }finally{r.restore();}
});
test('one shared custom portrait changes expression without repeated image loading',async()=>{
 const c=catalog();c.characters.a.expressions.happy='/a.png';const r=rig(c);try{
  r.renderer.setState({model:'a:latest',expression:'happy'});const img=await r.image();
  c.presentation.animated_characters_enabled=false;r.renderer.setState({expression:'neutral'});
  assert.equal(r.renderer.displayed,img);assert.equal(r.renderer.pending,null);assert.equal(r.host.dataset.renderedExpression,'neutral');
 }finally{r.restore();}
});
test('failure during a video fade releases the older layer before starting MP4',async()=>{
 const c=catalog();c.characters.a.animations.happy={webm:'/Character_Art/A/happy.webm',mp4:'/Character_Art/A/happy.mp4'};const r=rig(c);
 try{
  r.renderer.setModel('a:latest');const neutral=await r.video();r.renderer.setState({expression:'happy'});const happy=await r.video();
  assert.equal(r.nodes.filter(n=>n.tagName==='VIDEO'&&n.src).length,2);
  happy.onerror();assert.equal(neutral.src,undefined);assert(happy.paused);assert.equal(r.renderer.displayed,happy);
  assert.equal(r.nodes.filter(n=>n.tagName==='VIDEO'&&n.src).length,2);const mp4=await r.video();
  await new Promise(resolve=>setTimeout(resolve,400));assert.equal(r.renderer.displayed,mp4);assert.equal(r.renderer.layers.children.length,1);assert.equal(happy.src,undefined);
  c.presentation.animated_characters_enabled=false;r.renderer.setState({});assert(mp4.paused);await r.image();assert.equal(mp4.src,undefined);assert.equal(r.renderer.displayed.src,'/a-happy.png');
 }finally{r.restore();}
});

test('a decoded detached video can be admitted even if its compositor callback never fires',async()=>{
 const r=rig();try{
  r.renderer.setModel('a:latest');const v=r.renderer.pending;v.onloadeddata();await flush();
  assert.equal(r.renderer.displayed,null);r.frames.at(-1)();assert.equal(r.renderer.displayed,v);assert.equal(v.frame,null);
 }finally{r.restore();}
});
