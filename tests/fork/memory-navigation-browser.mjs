// SPDX-License-Identifier: AGPL-3.0-only
// Real DOM regression: actual layout/menu modules and CSS, no engine, network, observer or Ollama.
import {chromium} from 'playwright';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createMemoryNavigation,inspectManagementDOM,curatorMatches} from './memory-browser-navigation.mjs';
import {stopOwnedBrowser} from './memory-browser-support.mjs';
const root=path.resolve(new URL('../..',import.meta.url).pathname),out=process.env.MEMORY_NAVIGATION_REPORT||'/tmp/memory-navigation';
const report={passed:false,physical_hardware:false,cases:[]};let server,browser,phase='load actual UI source';
const cache=new Map();
async function moduleURL(file){
 if(cache.has(file))return cache.get(file);
 let source=file.endsWith('.json')?'export default '+await readFile(file,'utf8'):await readFile(file,'utf8');
 for(const match of [...source.matchAll(/import\s+([^;]+?)\s+from\s+['"]([^'"]+)['"](?:\s+with\s*\{[^}]+\})?;/g)]){
  const target=await moduleURL(path.resolve(path.dirname(file),match[2]));source=source.replace(match[0],`import ${match[1]} from '${target}';`);
 }
 const url='data:text/javascript;base64,'+Buffer.from(source).toString('base64');cache.set(file,url);return url;
}
await mkdir(out,{recursive:true});
try{
 const layout=await moduleURL(path.join(root,'src/js/ai/layout.js')),menus=await moduleURL(path.join(root,'src/js/ai/character-menus.js'));
 const html=(await readFile(path.join(root,'index.html'),'utf8')).replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*>/gi,'');
 const css=await readFile(path.join(root,'src/css/companion.css'),'utf8');
 const state={model:'evelyn-narrative-v1:latest',state_sequence:1,narrative_epoch:'1'.repeat(32),narrative_revision:0,narrative:{epoch:'1'.repeat(32),phase:'opening',premise:null,objective:null,facts:[],choices:[],commitments:[],threads:[],developments:[]},memory_curator:{status:'disabled',attempts:0,config:{enabled:false,interval_turns:8,timeout_seconds:20}}};
 phase='launch isolated Chromium';server=await chromium.launchServer({timeout:10000});browser=await chromium.connect(server.wsEndpoint());
 for(const viewport of [{width:1920,height:1080},{width:1440,height:1000},{width:390,height:844}]){
  phase=`actual DOM at ${viewport.width}x${viewport.height}`;const context=await browser.newContext({viewport});await context.route('**/*',route=>route.abort());
  const page=await context.newPage();page.setDefaultTimeout(1500);await page.setContent(html);await page.addStyleTag({content:css+'\n.hidden{display:none!important}'});
  await page.evaluate(async({layout,menus,state})=>{
   const chat=document.createElement('section');chat.id='ai-companion';chat.innerHTML='<header class="companion-heading"><h2>Chat</h2></header><textarea data-text aria-label="Synthetic chat"></textarea>';
   const character=document.createElement('aside');character.id='character-panel';character.setAttribute('aria-label','Character artwork');character.innerHTML='<header class="companion-heading"><h2>Evelyn</h2></header><div class="portrait-stage"></div>';
   (await import(layout)).mountLayout(chat,character);
   window.managementState=state;window.managementSends=[];
   const send=message=>{window.managementSends.push(message);if(message.type==='configure_curator')state.memory_curator.config=message.config;state.state_sequence++;setTimeout(()=>window.managementMenus.receive(structuredClone(state)),0);return true;};
   window.managementMenus=(await import(menus)).mountCharacterMenus(character,{send});window.managementMenus.scope(state.model,true);window.managementMenus.receive(structuredClone(state));
  },{layout,menus,state:structuredClone(state)});
  const navigation=createMemoryNavigation(page,{timeout:500}),before=await inspectManagementDOM(page);
  assert.equal(await page.locator('#character-panel [data-menu-story]').count(),1);
  assert.equal(await page.locator('#character-panel [data-menu-story]').isVisible(),viewport.width>=1500);
  if(viewport.width<1500)await assert.rejects(page.locator('[data-menu-story]').click({timeout:100}),/not visible|Timeout/);
  const story=await navigation.openStory();assert(await story.isVisible());await navigation.openStory();assert(await story.isVisible(),'reopening an open drawer must not toggle it closed');
  await navigation.showChat();assert(await page.locator('#ai-companion [data-text]').isVisible());
  assert(curatorMatches(state.memory_curator.config,'A'));assert(curatorMatches(state.memory_curator.config,'B'));
  assert.equal(await page.evaluate(()=>window.managementSends.filter(m=>m.type==='configure_curator').length),0,'A/B need no curator control interaction');
  const drawer=await navigation.openCurator();assert.equal(await drawer.locator('[data-curator-enabled]').evaluate(el=>!!el.closest('details')),false,'curator is a section, not the objective accordion');
  await drawer.locator('[data-curator-enabled]').setChecked(true);await drawer.locator('[data-curator-interval]').fill('8');await navigation.click(drawer.locator('[data-curator-save]'),'Save curator setting');
  await page.waitForFunction(()=>window.managementState.memory_curator.config.enabled&&window.managementState.memory_curator.config.interval_turns===8);
  assert(curatorMatches(await page.evaluate(()=>window.managementState.memory_curator.config),'C'));
  await navigation.showChat();const director=await navigation.openDirector();assert(await director.isVisible());await navigation.showChat();
  const shot=`navigation-${viewport.width}.png`;await page.screenshot({path:path.join(out,shot)});
  await page.locator('[data-menu-story]').evaluate(el=>el.style.display='none');
  await assert.rejects(navigation.openStory(),error=>error.message.includes('hidden')&&error.message.includes('Story Memory')&&!!error.navigation);
  await page.locator('[data-menu-story]').evaluate(el=>el.remove());
  await assert.rejects(navigation.openStory(),/Story Memory drawer button: missing element/);
  report.cases.push({viewport,before,after:await inspectManagementDOM(page),screenshot:shot,passed:true});await context.close();
 }
 report.passed=true;
}catch(error){const full=String(error.stack||error.message);await writeFile(path.join(out,'failure.txt'),full.slice(-32768));report.phase=phase;report.error=full.split('\n').filter(line=>/Protocol error|EPERM|EACCES|Operation not permitted|Permission denied|Failed to launch|ERROR:/.test(line)).slice(-8).join('\n').slice(0,2000)||String(error.message).slice(0,1000);report.blocked=/EPERM|EACCES|Operation not permitted|Permission denied/.test(full);report.evidence='failure.txt';process.exitCode=1;}
finally{await stopOwnedBrowser(browser,server,3000);await writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));}
