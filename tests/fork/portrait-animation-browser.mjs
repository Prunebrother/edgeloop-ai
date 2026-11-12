// SPDX-License-Identifier: AGPL-3.0-only
// Real browser decoder + existing renderer and Player; synthetic silent clips only.
// No observer, model, live server, hardware, or external request is used.
import {chromium} from 'playwright';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=path.resolve(new URL('../..',import.meta.url).pathname);
const reportDir=process.env.PORTRAIT_BROWSER_REPORT||'/tmp/edgeloop-portrait-animation-browser';
const report={passed:false,steps:[],requests:[],limits:'Synthetic media, mocked visibility event, no AI inference or hardware. Existing Player is real.'};
await mkdir(reportDir,{recursive:true});
let browser;
try{
 browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());if(url.origin!=='http://localhost:9')return route.abort();
  const p=url.pathname;report.requests.push(p);
  if(p==='/')return route.fulfill({contentType:'text/html',body:'<link rel="stylesheet" href="/src/css/companion.css"><style>body{margin:0}#character-panel{position:relative;width:400px;height:650px;display:flex;flex-direction:column}.portrait-stage{min-height:400px}</style><section id="character-panel"></section><video id="ordinary-player" muted></video>'});
  if(p.endsWith('/missing.webm'))return route.fulfill({status:404,body:'missing'});
  if(p.endsWith('/invalid.webm'))return route.fulfill({contentType:'video/webm',body:'invalid container'});
  const file=p.endsWith('/idle.webm')?'tests/fixtures/portrait-animation/idle.webm':p.endsWith('/idle.mp4')?'tests/fixtures/portrait-animation/idle.mp4':p.slice(1);
  if(!/^(src\/|Character_Art\/|tests\/fixtures\/portrait-animation\/)/.test(file)||file.includes('..'))return route.abort();
  try{return route.fulfill({body:await readFile(path.join(root,file)),contentType:p.endsWith('.js')?'text/javascript':p.endsWith('.json')?'application/json':p.endsWith('.css')?'text/css':p.endsWith('.webm')?'video/webm':p.endsWith('.mp4')?'video/mp4':'image/png'});}catch{return route.fulfill({status:404,body:'not found'});}
 });
 await page.goto('http://localhost:9/');
 await page.evaluate(async()=>{
  const {CharacterPresentation}=await import('/src/js/ai/character.js');
  const {CHARACTER_MANIFEST}=await import('/src/js/ai/artwork-manifest.js');
  const {createPlayer}=await import('/src/js/player/player.js');
  window.portraitVideos=[];const create=document.createElement.bind(document);document.createElement=(tag,...args)=>{const el=create(tag,...args);if(tag==='video')portraitVideos.push(el);return el;};
  // Start from the default-off contract whatever the shipped catalog declares.
  window.catalog=structuredClone(CHARACTER_MANIFEST);catalog.presentation.animated_characters_enabled=false;
  for(const c of Object.values(catalog.characters))delete c.animations;
  window.character=new CharacterPresentation(document.querySelector('#character-panel'),catalog);
  window.playerEvents=[];
  window.player=createPlayer({els:{video:document.querySelector('#ordinary-player')},handlers:{transport:()=>({coupled:false,sessionStatus:'IDLE'}),onInteraction:e=>playerEvents.push(e)}});
  window.alias=id=>Object.keys(catalog.models).find(m=>catalog.models[m]===id);
 });
 const select=(id,expression='neutral')=>page.evaluate(([id,expression])=>character.setState({model:alias(id),expression}),[id,expression]);
 const rendered=async(type,expression)=>page.waitForFunction(([type,expression])=>{
  const h=document.querySelector('#character-panel');return h.dataset.artworkType===type&&h.dataset.artworkStatus==='intended'&&h.dataset.expression===expression&&character.pending===null;
 },[type,expression]);
 for(const id of ['nova','celeste','evelyn','daisy'])for(const expression of await page.evaluate(()=>catalog.expressions)){await select(id,expression);await rendered('image',expression);}
 assert(!report.requests.some(p=>/\.(webm|mp4)$/.test(p)));
 report.steps.push('Default off: all 48 PNG expressions, no clip requests');
 await page.evaluate(()=>{catalog.presentation.animated_characters_enabled=true;catalog.characters.nova.animations={neutral:{webm:'/Character_Art/Nova/idle.webm',mp4:'/Character_Art/Nova/idle.mp4'},happy:{webm:'/Character_Art/Nova/missing.webm'}};});
 await select('nova');await rendered('video','neutral');
 assert(await page.evaluate(()=>{const v=character.displayed;return !v.paused&&v.muted&&v.loop&&v.playsInline&&v.videoWidth===64&&v.videoHeight===96;}));
 await page.waitForTimeout(1400);assert.deepEqual(await page.evaluate(()=>playerEvents),[]);
 report.steps.push('Synthetic VP9 decodes and loops; idle Player receives no portrait events');
 await select('nova','happy');await rendered('image','happy');assert((await page.evaluate(()=>character.displayed.src)).endsWith('nova_happy.png'));
 report.steps.push('Missing exact-expression video retains Happy PNG and selected emotion');
 await page.evaluate(()=>{catalog.characters.nova.animations.focused={webm:'/Character_Art/Nova/invalid.webm',mp4:'/Character_Art/Nova/idle.mp4'};});
 await select('nova','focused');await rendered('video','focused');assert((await page.evaluate(()=>character.displayed.src)).endsWith('.mp4'));
 report.steps.push('Invalid WebM falls back to real H.264 MP4');
 await page.evaluate(()=>{window.realPlay=HTMLMediaElement.prototype.play;HTMLMediaElement.prototype.play=function(){return Promise.reject(new DOMException('fixture autoplay denial','NotAllowedError'));};catalog.characters.nova.animations.proud={webm:'/Character_Art/Nova/idle.webm',mp4:'/Character_Art/Nova/idle.mp4'};});
 await select('nova','proud');await rendered('image','proud');await page.evaluate(()=>{HTMLMediaElement.prototype.play=realPlay;});
 report.steps.push('Autoplay rejection falls back to the selected Proud PNG');
 await page.evaluate(()=>{for(let i=0;i<30;i++)character.setState({model:alias(i%2?'nova':'daisy'),expression:i%3?'neutral':'happy'});character.setState({model:alias('celeste'),expression:'concerned'});});
 await rendered('image','concerned');assert.equal(await page.locator('#character-panel').getAttribute('data-character'),'celeste');
 report.steps.push('Rapid identity/expression changes settle on the latest character and emotion');
 await select('nova');await rendered('video','neutral');
 await page.locator('#character-panel').evaluate(el=>{el.style.display='none';});
 await page.waitForFunction(()=>character.displayed?.tagName==='IMG'&&character.pending===null);
 await page.locator('#character-panel').evaluate(el=>{el.style.display='flex';});await rendered('video','neutral');
 await page.locator('#character-panel').evaluate(el=>{el.dataset.presentationOccluded='true';});await rendered('image','neutral');
 await page.locator('#character-panel').evaluate(el=>{el.dataset.presentationOccluded='false';});await rendered('video','neutral');
 await page.emulateMedia({reducedMotion:'reduce'});await rendered('image','neutral');
 await page.emulateMedia({reducedMotion:'no-preference'});await rendered('video','neutral');
 // Controlled visibility input: headless foreground state does not model OS tabs.
 await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});
 await rendered('image','neutral');await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));});await rendered('video','neutral');
 report.steps.push('CSS-hidden panel, reduced motion and controlled document-hidden event stop/release video; visible state resumes');
 await page.evaluate(async()=>{const bytes=await(await fetch('/Character_Art/Nova/idle.mp4')).arrayBuffer();await player.addFiles([new File([bytes],'Synthetic.mp4',{type:'video/mp4'})]);player.workspaceChanged(true,true);await player.play();document.querySelector('#ordinary-player').loop=true;});
 await page.waitForFunction(()=>player.interactionState().started===1);const state=await page.evaluate(()=>player.interactionState());
 for(let i=0;i<8;i++){await select('nova',i%2?'neutral':'focused');await rendered('video',i%2?'neutral':'focused');assert((await page.evaluate(()=>portraitVideos.filter(v=>v.hasAttribute('src')).length))<=2);}
 await page.waitForTimeout(1400);assert.deepEqual(await page.evaluate(()=>player.interactionState()),state);
 report.steps.push('Existing Player open/select/start still work; portrait playback/switches do not change its counters');
 await page.evaluate(()=>{catalog.presentation.animated_characters_enabled=false;character.setState({});});await rendered('image','neutral');
 await page.evaluate(()=>character.destroy());assert.equal(await page.locator('#character-panel video').count(),0);assert.equal(await page.evaluate(()=>portraitVideos.filter(v=>v.hasAttribute('src')).length),0);assert.deepEqual(errors,[]);
 report.steps.push('Live flag disable returns to PNG; destroy leaves no portrait video or page errors');
 report.passed=true;
}catch(error){report.error=String(error);throw error;}
finally{await browser?.close();await writeFile(path.join(reportDir,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));}
