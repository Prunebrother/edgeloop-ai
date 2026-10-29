// SPDX-License-Identifier: AGPL-3.0-only
// Existing isolated authenticated observer fixture; hardware APIs denied.
import {chromium} from 'playwright';import {spawn} from 'node:child_process';import {mkdir,writeFile} from 'node:fs/promises';import path from 'node:path';
const root=path.resolve(new URL('../..',import.meta.url).pathname),out=process.env.CONTEXT_BROWSER_REPORT||'/tmp/f284-journal-browser',ui='http://127.0.0.1:8850',ai='http://127.0.0.1:8858',children=[],report={passed:false,physical_hardware:false,steps:[],screenshots:[]};let browser,page;
const assert=(x,m)=>{if(!x)throw Error(m);},sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function ready(url){for(let i=0;i<100;i++){try{if((await fetch(url)).ok)return;}catch{}await sleep(100);}throw Error('Fixture unavailable');}
async function state(){return(await fetch(ai+'/fixture/context')).json();}async function narrative(){return(await fetch(ai+'/fixture/narrative')).json();}
async function until(test){for(let i=0;i<100;i++){if(await test(await state()))return;await sleep(100);}throw Error('State timeout');}
async function select(model){await page.locator('[data-model]').selectOption(model);await page.locator('[data-select]').click();await page.waitForFunction(m=>document.querySelector('[data-selected]').textContent==='Active: '+m,model);}
async function chat(text){await page.locator('[data-text]').fill(text);await page.locator('[data-text]').press('Enter');await page.waitForFunction(()=>document.querySelector('[data-text]').value==='');await page.waitForFunction(()=>document.querySelector('[data-cancel]').hidden);}
async function shot(name,w,h){await page.setViewportSize({width:w,height:h});await page.screenshot({path:path.join(out,name)});report.screenshots.push(name);}
try{
 await mkdir(out,{recursive:true});children.push(spawn('python3',['tools/serve_local.py','8850'],{cwd:root,stdio:'ignore'}));children.push(spawn(path.join(root,'.venv/bin/python'),['-m','tests.fork.journal_browser_service'],{cwd:root,stdio:'ignore',env:{...process.env,EDGELOOP_LIVE_ACCEPTANCE:'0',EDGELOOP_FIXTURE_UI_PORT:'8850',EDGELOOP_FIXTURE_OBSERVER_PORT:'8858'}}));await ready(ui);await ready(ai+'/health');browser=await chromium.launch();const context=await browser.newContext({viewport:{width:1920,height:1080}});await context.addInitScript(()=>{const no=()=>Promise.reject(new DOMException('Mock only','NotFoundError'));Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:no},configurable:true});Object.defineProperty(navigator,'serial',{value:{requestPort:no,getPorts:async()=>[]},configurable:true});if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=no;});
 page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(ui+'/?characterPreview=1');await page.locator('#ageConfirmBtn').click();await page.locator('#wizardSkipBtn').click();await page.locator('[data-url]').fill('ws://127.0.0.1:8858/observe');await page.locator('[data-token]').fill('event-reliability-fixture-'+'x'.repeat(32));await page.locator('[data-connect]').click();await page.waitForFunction(()=>document.querySelector('[data-model] option[value="evelyn-narrative-v1:latest"]'));await select('evelyn-narrative-v1:latest');await page.getByRole('button',{name:'Session Journal',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#session-journal [data-notice]').textContent.length>0);
 assert(!(await page.locator('#session-journal [data-record]').isChecked()),'Recording must default off');
 await page.locator('#session-journal [data-record]').check();await page.waitForTimeout(200);
 await page.locator('#session-journal [data-access]').check();await page.waitForTimeout(200);
 assert((await (await fetch(ai+'/fixture/journal-session',{method:'POST'})).json()).recorded===1,'No durable session');
 await page.getByRole('button',{name:'Close Session Journal'}).click();await page.getByRole('button',{name:'Session Journal',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#session-journal tbody').textContent.includes('120 s'));
 await page.locator('#session-journal tbody button').first().click();await page.waitForFunction(()=>document.querySelector('#session-journal [data-detail]').textContent.includes('selected/applied engine'));
 await page.locator('#session-journal [data-access]').uncheck();await page.waitForTimeout(200);
 await shot('journal-desktop.png',1920,1080);await shot('journal-mobile.png',390,844);
 assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)),'Mobile overflow');
 await page.getByRole('button',{name:'Delete this record'}).click();await page.waitForFunction(()=>document.querySelector('#session-journal [data-page]').textContent.includes('of 0'));
 assert(errors.length===0,errors.join('; '));report.steps.push('Opt-in privacy, observer-captured record, table, detail, AI access toggle, deletion, desktop/mobile layout');report.passed=true;

}catch(e){report.error=e.stack;throw e;}finally{await writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));await browser?.close();for(const child of children)child.kill('SIGTERM');console.log(JSON.stringify(report));}
