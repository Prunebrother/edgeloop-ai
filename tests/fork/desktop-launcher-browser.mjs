// SPDX-License-Identifier: AGPL-3.0-only
// Isolated automatic pairing acceptance. Mocked Ollama; no hardware or inference.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import path from 'node:path';
const root=path.resolve(new URL('../..',import.meta.url).pathname);
const temp=await mkdtemp('/tmp/edgeloop-launcher-browser-');
const credentials={token:'browser-fixture-token-'+'x'.repeat(32),url:'ws://127.0.0.1:8788/observe',browser_id:randomUUID()};
const file=path.join(temp,'pairing.json');await writeFile(file,JSON.stringify(credentials),{mode:0o600});
const env={...process.env,EDGELOOP_PAIRING_FILE:file,EDGELOOP_FIXTURE_UI_PORT:'8780',EDGELOOP_FIXTURE_OBSERVER_PORT:'8788'};
const processes=[];let browser;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const assert=(v,m)=>{if(!v)throw Error(m);};
async function ready(url){for(let n=0;n<60;n++){try{if((await fetch(url)).ok)return;}catch{}await pause(100);}throw Error('Fixture unavailable: '+url);}
try {
 processes.push(spawn('python3',['tools/serve_local.py','8780'],{cwd:root,env,stdio:'ignore'}));
 processes.push(spawn(path.join(root,'.venv/bin/python'),['tests/fork/browser_service.py'],{cwd:root,env,stdio:'ignore'}));
 await ready('http://127.0.0.1:8780');await ready('http://127.0.0.1:8788/health');
 browser=await chromium.launch();const context=await browser.newContext({serviceWorkers:'block'});
 await context.addInitScript(()=>{
  const denied=()=>Promise.reject(Error('Hardware disabled in acceptance'));
  Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:denied},configurable:true});
  Object.defineProperty(navigator,'serial',{value:{requestPort:denied,getPorts:async()=>[]},configurable:true});
 });
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8780/');
 await page.locator('#ageConfirmBtn').click();
 await page.locator('#wizardSkipBtn').click();
 const connected=()=>page.waitForFunction(()=>document.querySelector('#ai-companion')?.dataset.paired==='true');
 await connected();
 await page.locator('[data-model] option[value="evelyn-lite-v1:latest"]').waitFor({state:'attached'});
 const storage=await page.evaluate(()=>JSON.stringify({local:{...localStorage},session:{...sessionStorage}}));
 assert(!storage.includes(credentials.token),'Pairing token leaked into browser storage');
 assert(!page.url().includes(credentials.token),'Pairing token leaked into URL');
 await page.reload();await connected();
 // A reopened tab shares desktop identity and can take over safely.
 const reopened=await context.newPage();await reopened.goto('http://127.0.0.1:8780/');
 await reopened.waitForFunction(()=>document.querySelector('#ai-companion')?.dataset.paired==='true');
 await reopened.locator('[data-disconnect]').click();await pause(5500);
 assert(await reopened.locator('#ai-companion').getAttribute('data-paired')==='false','Disconnect was undone by automatic pairing');
 assert(!errors.length,errors.join('\n'));
 console.log('PASS: automatic pairing, model discovery, reload, reopened tab, no credential storage, explicit Disconnect; mocked Ollama, no hardware.');
} finally {
 if(browser)await browser.close();
 for(const proc of processes)proc.kill('SIGTERM');
 await Promise.all(processes.map(proc=>new Promise(resolve=>{if(proc.exitCode!==null||proc.signalCode!==null)resolve();else proc.once('exit',resolve);})));await rm(temp,{recursive:true,force:true});
}
