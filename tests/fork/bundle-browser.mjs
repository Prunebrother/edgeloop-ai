// SPDX-License-Identifier: AGPL-3.0-only
// Explicit real-model acceptance for an installed complete bundle. No hardware.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {createServer} from 'node:net';
import {createWriteStream} from 'node:fs';
import path from 'node:path';
const root=process.env.EDGELOOP_BUNDLE_ROOT;
if(!root)throw Error('Set EDGELOOP_BUNDLE_ROOT to an installed bundle to opt into real inference.');
const temp=await mkdtemp('/tmp/edgeloop-bundle-acceptance-');
const report={passed:false,external_requests:[],hardware:'Denied',portraits:0,model:null,reply:false};
const children=[];let browser,page;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const assert=(condition,message)=>{if(!condition)throw Error(message);};
async function free(port){await new Promise((resolve,reject)=>{const server=createServer();server.once('error',reject);server.listen(port,'127.0.0.1',()=>server.close(resolve));});}
async function ready(url){for(let i=0;i<120;i++){try{if((await fetch(url)).ok)return;}catch{}await pause(250);}throw Error('Startup timeout: '+url);}
const env={...process.env,OLLAMA_HOST:'127.0.0.1:11435',OLLAMA_MODELS:path.join(root,'models'),OLLAMA_NO_CLOUD:'1',OLLAMA_NUM_PARALLEL:'1',OLLAMA_MAX_LOADED_MODELS:'1',OLLAMA_FLASH_ATTENTION:'1',EDGELOOP_OLLAMA_URL:'http://127.0.0.1:11435',EDGELOOP_OBSERVER_PORT:'8768',EDGELOOP_FORK_AI_DATA:path.join(temp,'data'),EDGELOOP_PAIRING_FILE:path.join(temp,'runtime/pairing.json')};
try{
 for(const port of [11435,8768,8770])await free(port);
 const python=path.join(root,'.venv/bin/python');
 const configure=spawn(python,['tools/bundle.py','configure','--home',path.join(temp,'user'),'--no-desktop','--no-start'],{cwd:root,env,stdio:'ignore'});
 await new Promise((resolve,reject)=>configure.on('exit',code=>code===0?resolve():reject(Error('Configure failed'))));
 env.EDGELOOP_FORK_AI_DATA=path.join(temp,'user/.local/share/edgeloop-ai/data');
 for(const [binary,args] of [[path.join(root,'runtime/ollama/bin/ollama'),['serve']],[python,['-I','-m','ai_observer.server']],[python,['tools/serve_local.py','8770']]]){
  const child=spawn(binary,args,{cwd:root,env,stdio:['ignore','pipe','pipe']});
  const log=createWriteStream(path.join(temp,'service-'+children.length+'.log'));
  child.stdout.pipe(log);child.stderr.pipe(log);children.push(child);
 }
 await ready('http://127.0.0.1:11435/api/tags');await ready('http://127.0.0.1:8768/health');await ready('http://127.0.0.1:8770/');
 const inputs=JSON.parse(await readFile(path.join(root,'release-inputs.json'),'utf8'));
 const tags=await (await fetch('http://127.0.0.1:11435/api/tags')).json();
 for(const name of inputs.characters){
  assert(tags.models.some(m=>m.name===name+':latest'),'Missing installed character: '+name);
  const metadata=await (await fetch('http://127.0.0.1:11435/api/show',{method:'POST',body:JSON.stringify({model:name}),headers:{'Content-Type':'application/json'}})).json();
  const source=await readFile(path.join(root,'characters/models',name,'Modelfile'),'utf8');
  const expected=source.split('SYSTEM """')[1].split('"""')[0].trim();
  assert(metadata.system.trim()===expected,'Character prompt differs: '+name);
 }
 browser=await chromium.launch();const context=await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block'});
 await context.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(['127.0.0.1','localhost'].includes(url.hostname))return route.continue();
  report.external_requests.push(url.origin);return route.abort();
 });
 await context.addInitScript(()=>{
  const denied=()=>Promise.reject(Error('Hardware disabled during bundle verification'));
  Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:denied},configurable:true});
  Object.defineProperty(navigator,'serial',{value:{requestPort:denied,getPorts:async()=>[]},configurable:true});
  if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=denied;
 });
 page=await context.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto('http://127.0.0.1:8770/');
 await page.locator('#ageConfirmBtn').click();await page.locator('#wizardSkipBtn').click();
 await page.waitForFunction(()=>document.querySelector('[data-selected]')?.textContent==='Active: nova-narrative-v1:latest',null,{timeout:180000});
 await page.waitForFunction(()=>document.querySelector('#character-panel img:last-child')?.naturalWidth>0);
 report.model=await page.locator('[data-selected]').textContent();
 console.log('Automatic pairing and Nova selection passed.');
 const manifest=JSON.parse(await readFile(path.join(root,'src/assets/characters/manifest.json'),'utf8'));
 for(const c of Object.values(manifest.characters))for(const source of Object.values(c.expressions)){
  const response=await page.request.get('http://127.0.0.1:8770'+source);assert(response.ok(),'Portrait unavailable: '+source);report.portraits++;
 }
 for(const secret of ['/.git/config','/models/manifests/registry.ollama.ai/library/qwen3/8b','/runtime/python/bin/python3','/wheelhouse/','/BUNDLE.json','/.ai-data/selection.json'])assert((await page.request.get('http://127.0.0.1:8770'+secret)).status()===404,'Private file exposed: '+secret);
 await page.locator('[data-text]').fill('Hello Nova. Please introduce yourself in one short sentence. This is a fictional offline setup test.');await page.locator('[data-text]').press('Enter');
 await page.waitForFunction(()=>document.querySelectorAll('.message-assistant').length>0&&document.querySelector('[data-cancel]').hidden,null,{timeout:240000});
 assert(!(await page.locator('[data-error]').textContent()),'Companion reported an error');
 report.reply=(await page.locator('.message-assistant').last().textContent()).trim().length>0;
 assert(report.reply,'No real model reply');assert(!errors.length,errors.join('\n'));assert(!report.external_requests.length,'UI attempted external downloads');
 await page.screenshot({path:path.join(temp,'first-run.png'),fullPage:true});
 await page.reload();await page.waitForFunction(()=>document.querySelector('[data-selected]')?.textContent==='Active: nova-narrative-v1:latest',null,{timeout:180000});
 report.passed=true;console.log(JSON.stringify({...report,evidence_directory:temp}));
}catch(error){
 if(page){await page.screenshot({path:path.join(temp,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(path.join(temp,'failure.txt'),await page.locator('#ai-companion').innerText().catch(()=>''));}
 throw error;
}finally{
 if(browser)await browser.close();
 for(const child of children.reverse()){
  child.kill('SIGTERM');await Promise.race([new Promise(resolve=>child.once('exit',resolve)),pause(10000)]);if(child.exitCode===null)child.kill('SIGKILL');
 }
 await writeFile(path.join(temp,'report.json'),JSON.stringify(report,null,2));
}
