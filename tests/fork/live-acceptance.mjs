// SPDX-License-Identifier: AGPL-3.0-only
// Explicit opt-in: real 11435 inference; isolated fork UI/observer; mocked devices only.
import {chromium} from 'playwright';
import {spawn,execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {createServer} from 'node:net';
import path from 'node:path';
import {classifyDialogue} from '../../src/js/ai/presentation-controller.js';
const exec=promisify(execFile);
if(process.env.EDGELOOP_LIVE_ACCEPTANCE!=='1')throw Error('Set EDGELOOP_LIVE_ACCEPTANCE=1 to opt into real local inference');
const root=path.resolve(new URL('../..',import.meta.url).pathname);
const output=process.env.LIVE_ACCEPTANCE_REPORT||('/tmp/edgeloop-live-'+Date.now());
const uiPort=Number(process.env.FORK_BROWSER_PORT||8780),observerPort=Number(process.env.FORK_OBSERVER_PORT||8788);
const ui=`http://127.0.0.1:${uiPort}`,observer=`http://127.0.0.1:${observerPort}`,ollama='http://127.0.0.1:11435';
const models=['evelyn-lite-v1:latest','evelyn-qwen35-stable:latest','daisy-qwen35:latest'];
const markers=['F22_ALPHA','F22_BETA','F22_GAMMA'];
const report={passed:false,models:[],steps:[],gpu_samples:[],hardware:'Simulated HR and intercepted Handy HTTP; native device permissions denied',ollama_url:ollama,thinking:false,max_tokens:256,keep_alive_seconds:60};
let ollamaPid;
let page,browser,timer,polling=null;const children=[];const errors=[];const streams=[];let currentStream=null;let serverLog='';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function assert(ok,message){if(!ok)throw Error(message);}
async function json(url,options){const r=await fetch(url,options);assert(r.ok,'HTTP '+r.status+' at '+url);return r.json();}
async function freePort(port){await new Promise((resolve,reject)=>{const server=createServer();server.once('error',reject);server.listen(port,'127.0.0.1',()=>server.close(resolve));});}
async function waitServer(url){for(let i=0;i<80;i++){try{if((await fetch(url)).ok)return;}catch{}await sleep(100);}throw Error('Fixture startup failed: '+serverLog);}
async function belongsToServer(pid){
 for(let i=0;i<5&&pid>1;i++){
  if(pid===ollamaPid)return true;
  try{const stat=await readFile(`/proc/${pid}/stat`,'utf8');pid=Number(stat.slice(stat.lastIndexOf(')')+2).split(' ')[1]);}catch{return false;}
 }
 return false;
}
async function sample(){
 const [{stdout},loaded,compute]=await Promise.all([exec('nvidia-smi',['--query-gpu=memory.used,memory.total','--format=csv,noheader,nounits'],{timeout:5000}),json(ollama+'/api/ps'),exec('nvidia-smi',['--query-compute-apps=pid,used_gpu_memory','--format=csv,noheader,nounits'],{timeout:5000})]);
 const [used,total]=stdout.trim().split('\n')[0].split(',').map(Number);
 const runners=[];
 for(const row of compute.stdout.trim().split('\n')){const [pid,mib]=row.split(',').map(Number);if(Number.isFinite(mib)&&await belongsToServer(pid))runners.push({pid,used_mib:mib});}
 report.gpu_samples.push({at:Date.now(),used_mib:used,total_mib:total,runner_used_mib:runners.reduce((n,p)=>n+p.used_mib,0),runners,loaded:loaded.models.map(m=>({name:m.name,vram_mib:Math.round(m.size_vram/1048576),context_length:m.context_length}))});
}
function spawnFixture(command,args,env={}){const child=spawn(command,args,{cwd:root,env:{...process.env,...env},stdio:['ignore','ignore','pipe']});children.push(child);child.stderr.on('data',data=>{serverLog+=data;});}
async function state(){return page.evaluate(async()=>{const{state:s}=await import('/src/js/state.js');return {status:s.sessionStatus,seconds:s.sessionSeconds,hr:s.sensorHr,edges:s.edges,intensity:s.intensityValue};});}
async function select(model){
 await page.locator('[data-model]').selectOption(model);await page.locator('[data-select]').click();
 await page.waitForFunction(m=>document.querySelector('[data-selected]').textContent==='Active: '+m,model,{timeout:30000});
 assert(await page.locator('[data-thinking]').getAttribute('aria-pressed')==='false','Thinking off not acknowledged');
 assert((await state()).status==='RUNNING','Model switching interrupted session');
}
async function chat(prompt){
 const count=streams.length;const started=Date.now();
 await page.locator('[data-text]').fill(prompt);await page.locator('[data-text]').press('Enter');
 const deadline=Date.now()+125000;
 while(!(streams.length>count&&streams.at(-1).done)){
  const error=await page.locator('[data-error]').textContent();
  if(error)throw Error(error);
  if(Date.now()>deadline)throw Error('Timed out waiting for completed response frame');
  await sleep(25);
 }
 await page.waitForFunction(()=>document.querySelector('[data-cancel]').hidden,null,{timeout:5000});
 assert(streams.length>count,'No response-start frame');
 const stream=streams.at(-1);
 assert(stream.done&&stream.deltas>0,'Missing visible streamed completion');
 assert(stream.text.trim()===stream.final,'Visible deltas differ from completed response');
 const fixture=await json(observer+'/fixture/state');const metrics=fixture.metrics.at(-1),wire=fixture.requests.at(-1);
 assert(metrics.done_reason==='stop','Reply did not finish naturally: '+metrics.done_reason);
 assert(metrics.thinking_enabled===false&&metrics.thinking_characters===0,'Thinking leaked or was not disabled');
 assert(wire.thinking===false&&wire.stream&&wire.tools_absent&&wire.embedded_system_preserved,'Native request violated text-only/identity settings');
 return {reply:stream.final,expression:stream.expression,chunks:stream.deltas,total_seconds:(Date.now()-started)/1000,first_visible_seconds:(stream.first-started)/1000,metrics,wire};
}
try {
 await mkdir(output,{recursive:true});await freePort(uiPort);await freePort(observerPort);
 const tags=await json(ollama+'/api/tags');report.installed_models=tags.models.map(m=>m.name);for(const m of models)assert(report.installed_models.includes(m),'Missing '+m);
 const discovery=await exec(path.join(root,'.venv/bin/python'),['-I','-c',"import json;from ai_observer.diagnostics import local_model_directories;print(json.dumps(local_model_directories('http://127.0.0.1:11435')))"]);
 const processes=JSON.parse(discovery.stdout);assert(processes.length===1,'Expected one existing character Ollama process');ollamaPid=processes[0].pid;report.ollama_process=processes[0];
 await sample();timer=setInterval(()=>{if(!polling)polling=sample().catch(e=>errors.push('GPU monitor: '+String(e))).finally(()=>{polling=null;});},500);
 spawnFixture('python3',['tools/serve_local.py',String(uiPort)]);
 spawnFixture(path.join(root,'.venv/bin/python'),['tests/fork/live_acceptance_service.py'],{EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(observerPort)});
 await waitServer(ui+'/');await waitServer(observer+'/health');
 browser=await chromium.launch();const context=await browser.newContext({viewport:{width:1920,height:1080}});
 await context.addInitScript(()=>{const denied=()=>Promise.reject(new DOMException('Live acceptance: no physical hardware','NotAllowedError'));
  Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:denied},configurable:true});
  Object.defineProperty(navigator,'serial',{value:{requestPort:denied,getPorts:async()=>[]},configurable:true});
  if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=denied;
 });
 let deviceCalls=0,deniedRequests=0;
 await context.route('**/*',async route=>{const url=new URL(route.request().url());
  if(url.pathname.startsWith('/api/handy/v2/')){deviceCalls++;const result=url.pathname.endsWith('/connected')?{connected:true}:url.pathname.endsWith('/info')?{fwVersion:'3.2.3',model:'Handy 1.1'}:{result:0};return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(result)});}
  if(url.origin===ui||url.origin===observer)return route.continue();
  if(route.request().method()==='GET'&&route.request().resourceType()==='script'&&['https://cdn.tailwindcss.com/','https://unpkg.com/peerjs@1.5.4/dist/peerjs.min.js'].includes(url.href))return route.continue();
  deniedRequests++;return route.abort();
 });
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 page.on('websocket',ws=>ws.on('framereceived',event=>{let m;try{m=JSON.parse(event.payload);}catch{return;}
  if(m.type==='response_start'){currentStream={id:m.id,deltas:0,text:'',done:false};streams.push(currentStream);}
  if(m.type==='response_delta'&&currentStream?.id===m.id){currentStream.first??=Date.now();currentStream.text+=m.text;currentStream.deltas++;}
  if(m.type==='speech'&&currentStream?.id===m.id){currentStream.done=true;currentStream.final=m.text;currentStream.expression=m.expression;}
 }));
 await page.goto(ui+'/');await page.locator('#ageConfirmBtn').click();await page.locator('#wizardOverlay').waitFor({state:'visible'});await page.locator('#wizardSkipBtn').click();await page.locator('#companion-dashboard').waitFor();
 assert(deviceCalls===0,'Hardware attempted automatically');
 await page.locator('#cardBle').click();await page.getByRole('button',{name:/manual simulator/i}).click();await page.locator('#modalSimHrSlider').fill('98');await page.locator('#modalEngageSimBtn').click();
 if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
 await page.locator('#cardHandy').click();await page.locator('#modalHandyInput').fill('ACCEPTANCE_MOCK_DEVICE');await page.locator('#modalHandyConnectBtn').click();await sleep(900);
 if(await page.locator('#modalCloseBtn').isVisible())await page.locator('#modalCloseBtn').click();
 await page.locator('#sessionPlayPauseBtn').click();await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';});
 report.steps.push('Original EdgeLoop starts with simulated HR and mocked Handy; no physical hardware');
 await page.locator('[data-url]').fill(observer.replace('http:','ws:')+'/observe');await page.locator('[data-token]').fill('live-fixture-token-'+'x'.repeat(32));await page.locator('[data-connect]').click();
 await page.waitForFunction(()=>document.querySelector('[data-model]').options.length>=3);
 for(let i=0;i<models.length;i++){
  const model=models[i];await select(model);assert(await page.locator('[data-history] .message').count()===0,'Cross-model history exposed');
  const cold=await chat(markers[i]+': Briefly state the reported BPM, whether it is simulated, and whether the session is running or idle.');
  assert(JSON.stringify(cold.wire.history_markers)===JSON.stringify([markers[i]]),'Cross-model context in first inference');
  const warm=await chat('In one short sentence, confirm whether this companion can control a device or only observe.');
  assert(warm.wire.history_markers.every(marker=>marker===markers[i]),'Another model history contaminated inference');
  assert((await json(observer+'/fixture/state')).active_history.some(m=>m.role==='user'&&m.content.includes(markers[i])),'Model-specific stored memory missing');
  const ps=await json(ollama+'/api/ps');assert(ps.models.length<=1,'More than one model resident');
  cold.telemetry_facts={bpm:/\b98\b/.test(cold.reply),simulated:/simulat/i.test(cold.reply),running:/running/i.test(cold.reply)};
  const precedingExpression=await page.locator('#character-panel').getAttribute('data-expression');
  const expressionReply=await chat('Say hello in your own style in one or two sentences.');
  const expectedExpression=expressionReply.expression||classifyDialogue(expressionReply.reply)||precedingExpression;
  await page.waitForFunction(({identity,expression})=>{const panel=document.querySelector('#character-panel');return panel.dataset.character===identity&&panel.dataset.expression===expression&&panel.dataset.activity==='idle'&&panel.querySelector('img:last-child.visible')?.naturalWidth>0&&!panel.querySelector('[data-art-status]').textContent.includes('Loading');},{identity:model.startsWith('daisy-')?'daisy':'evelyn',expression:expectedExpression});
  const presentation=await page.locator('#character-panel').evaluate(panel=>({character:panel.dataset.character,expression:panel.dataset.expression,activity:panel.dataset.activity,source:panel.querySelector('img:last-child').getAttribute('src')}));
  assert(!/\[\[(?:expression|happy|neutral|playful):/i.test(await page.locator('[data-history]').textContent()),'Metadata leaked');
  assert(!/<think[> ]/i.test(await page.locator('[data-history]').textContent()),'Reasoning exposed in UI');
  report.models.push({model,first_request:cold,second_request:warm,expression_request:expressionReply,presentation,residency:ps.models.map(m=>({name:m.name,size_vram:m.size_vram,context_length:m.context_length})),memory_isolated:true});
  await page.screenshot({path:path.join(output,model.split(':')[0]+'.png')});console.log('Passed real streaming, thinking off and isolated history: '+model);
 }
 for(let i=0;i<models.length;i++){await select(models[i]);const text=await page.locator('[data-history]').textContent();assert(text.includes(markers[i]),'Model history not restored');for(let j=0;j<markers.length;j++)if(j!==i)assert(!text.includes(markers[j]),'Restored history leaked another model');}
 report.memory_restoration=true;report.steps.push('All three model histories isolate and restore; accepted visible replies drive isolated character presentation with no reasoning text or extra classification inference');
 const before=await state();
 const historyBefore=(await json(observer+'/fixture/state')).active_history;
 await json(observer+'/fixture/connection/cut-stream',{method:'POST'});
 await page.locator('[data-text]').fill('Briefly describe the current session status.');await page.locator('[data-text]').press('Enter');
 await page.waitForFunction(()=>document.querySelector('[data-error]').textContent.includes('response unavailable'),null,{timeout:20000});
 const interrupted=await json(observer+'/fixture/state');
 assert(interrupted.stream_interruptions===1,'Real inference connection was not interrupted');
 assert(JSON.stringify(interrupted.active_history)===JSON.stringify(historyBefore),'Interrupted response entered memory');
 report.midstream_interruption={real_inference_socket_closed:true,history_preserved:true,session:await state()};
 assert(report.midstream_interruption.session.status==='RUNNING','Streaming interruption changed EdgeLoop');
 await json(observer+'/fixture/connection/down',{method:'POST'});await page.locator('[data-refresh]').click();await page.waitForFunction(()=>document.querySelector('[data-error]').textContent.includes('discovery unavailable'));
 await page.locator('[data-text]').fill('Connection interruption acceptance check.');await page.locator('[data-text]').press('Enter');
 await page.waitForFunction(()=>document.querySelector('[data-error]').textContent.includes('response unavailable'),null,{timeout:15000});
 await sleep(2200);const during=await state();assert(during.status==='RUNNING'&&during.seconds>before.seconds,'Ollama interruption stopped original session');
 await page.locator('#sessionPlayPauseBtn').click();await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='PAUSED';});
 await page.locator('#sessionPlayPauseBtn').click();await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='RUNNING';});
 await page.screenshot({path:path.join(output,'ollama-unavailable-session-running.png')});
 report.outage={method:'Close only the test real-inference socket midstream, then raise ConnectError for further test requests; both daemons stay running',before,during,pause_resume:true};
 await json(observer+'/fixture/connection/up',{method:'POST'});await page.locator('[data-refresh]').click();await page.waitForFunction(()=>document.querySelector('[data-model]').options.length>=3);await select(models[0]);
 const telemetryDeadline=Date.now()+5000;
 while((await json(observer+'/fixture/state')).observation?.status!=='RUNNING'){assert(Date.now()<telemetryDeadline,'Resumed observation did not propagate');await sleep(100);}
 report.recovery_observation=(await json(observer+'/fixture/state')).observation;
 report.recovery=await chat('Briefly confirm the session is still running from current telemetry.');assert((await state()).status==='RUNNING','Recovery changed session');
 await page.locator('#sessionStopBtn').click();await page.waitForFunction(async()=>{const{state}=await import('/src/js/state.js');return state.sessionStatus==='IDLE'&&state.strokerSpeed===0;});
 report.outage.stop=true;report.steps.push('Disconnected Ollama leaves timer, pause/resume and stop operational; real transport recovery succeeds');
 const fixture=await json(observer+'/fixture/state');report.connection_failures=fixture.connection_failures;report.stream_interruptions=fixture.stream_interruptions;assert(fixture.connection_failures>=2,'Outage was not exercised');assert(fixture.read_only,'Control executor unexpectedly enabled');
 report.read_only=true;report.device_http_intercepted=deviceCalls;report.external_requests_denied=deniedRequests;
 await page.screenshot({path:path.join(output,'complete-desktop.png')});await page.setViewportSize({width:390,height:844});await page.locator('button[data-view="chat"]').click();await page.screenshot({path:path.join(output,'complete-mobile.png')});
 assert(!errors.length,errors.join('\n'));report.passed=true;
} catch(e){report.error=String(e);report.failure_fixture=await json(observer+'/fixture/state').catch(()=>null);process.exitCode=1;if(page)await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});}
finally {
 if(timer)clearInterval(timer);if(polling)await polling;await sample().catch(e=>errors.push(String(e)));
 report.gpu_summary={baseline_used_mib:report.gpu_samples[0]?.used_mib,peak_used_mib:Math.max(...report.gpu_samples.map(s=>s.used_mib)),total_mib:report.gpu_samples[0]?.total_mib,max_resident_models:Math.max(...report.gpu_samples.map(s=>s.loaded.length)),peak_runner_mib:Math.max(...report.gpu_samples.map(s=>s.runner_used_mib))};
 if(report.gpu_summary.max_resident_models>1){report.passed=false;report.error='Multiple resident models detected; no process was terminated';process.exitCode=1;}
 if(errors.length){report.passed=false;report.error??=errors.join('\n');process.exitCode=1;}
 report.monitor_errors=errors;
 if(browser)await browser.close();for(const child of children){if(child.exitCode===null)child.kill('SIGTERM');}
 await writeFile(path.join(output,'browser-report.json'),JSON.stringify(report,null,2));await writeFile(path.join(output,'fixture.log'),serverLog);
 console.log(JSON.stringify({passed:report.passed,error:report.error,models:report.models.map(m=>({model:m.model,first_seconds:m.first_request.total_seconds,second_seconds:m.second_request.total_seconds})),gpu:report.gpu_summary,output}));
}
