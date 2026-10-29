// SPDX-License-Identifier: AGPL-3.0-only
// Actual UI + authenticated observer + synthetic dialogue. Mocks measure plumbing only.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import net from 'node:net';
import {randomBytes} from 'node:crypto';
import {memorySnapshot,factualCoverage,unsupportedAdditions} from './memory-recall-evaluation.mjs';
import {createMemoryNavigation,inspectManagementDOM,curatorMatches} from './memory-browser-navigation.mjs';
import {Progress,deadline,redact,timeoutSettings,stopOwnedBrowser,stopOwnedChildren} from './memory-browser-support.mjs';
const root=path.resolve(new URL('../..',import.meta.url).pathname),out=process.env.MEMORY_REPORT||'/tmp/f2841-browser',live=process.argv.includes('--live');
const timeouts=timeoutSettings(process.env,live);
const setupOnly=process.argv.includes('--setup-only'),deterministicOnly=process.argv.includes('--deterministic-only');
const comparisonArms=deterministicOnly?['A','B']:['A','B','C'];
const viewport={width:Number(process.env.MEMORY_VIEWPORT_WIDTH||1920),height:Number(process.env.MEMORY_VIEWPORT_HEIGHT||1080)};
if(!Number.isInteger(viewport.width)||!Number.isInteger(viewport.height)||viewport.width<320||viewport.width>7680||viewport.height<320||viewport.height>4320)throw Error('Invalid MEMORY_VIEWPORT_WIDTH/HEIGHT');
const report={live,comparison_arms:comparisonArms,curator_disabled_for_investigation:deterministicOnly,memory_snapshots:[],setup_only:setupOnly,viewport,setup_checks:[],pairing_attempts:[],physical_hardware:false,rows:[],blocked:[],failures:[],screenshots:[],evidence:[],timeouts,wait_timeouts:[]},detours=Number(process.env.MEMORY_DETOURS||8);
const models=['evelyn-narrative-v1:latest','daisy-narrative-v1:latest','celeste-narrative-v2:latest'];
const hobbies=['tending an overgrown succulent','pressing wildflowers','restoring fountain pens'];
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function assert(ok,message){if(!ok)throw Error(message);}
await mkdir(out,{recursive:true});await writeFile(path.join(out,'progress.jsonl'),'');
const progress=new Progress(path.join(out,'progress.jsonl')),run=new AbortController();let owned=null,signalExit=null,evidenceSequence=0;
for(const [signal,code] of [['SIGINT',130],['SIGTERM',143]])process.on(signal,()=>{if(signalExit!==null)return;signalExit=code;progress.log('interrupted',{signal});run.abort(new Error(`Runner interrupted by ${signal}`));});
const step=(label,fn,ms=timeouts.action)=>progress.step(label,ms,fn,run.signal);
async function local(url,options={},parent=run.signal){
 return deadline(`HTTP ${new URL(url).pathname}`,timeouts.http,async signal=>{
  const response=await fetch(url,{...options,signal});if(!response.ok)throw Error(`HTTP ${response.status}: ${new URL(url).pathname}`);return response.json();
 },parent);
}
async function port(signal){return new Promise((resolve,reject)=>{
 const server=net.createServer(),abort=()=>{server.close(()=>{});reject(signal.reason);};
 server.once('error',reject);signal.addEventListener('abort',abort,{once:true});
 server.listen(0,'127.0.0.1',()=>{const value=server.address().port;server.close(()=>{signal.removeEventListener('abort',abort);resolve(value);});});
});}
async function ready(url,signal){
 // The enclosing startup deadline aborts an in-flight fetch too.
 while(true){signal.throwIfAborted();try{await deadline('fixture health request',timeouts.http,async requestSignal=>{const response=await fetch(url,{signal:requestSignal});if(!response.ok)throw Error(`HTTP ${response.status}`);},signal);return;}catch(error){if(signal.aborted)throw error;}await sleep(100);}
}
function launch(label,command,args,env){
 const owner=owned;
 const child=spawn(command,args,{cwd:root,stdio:['ignore','pipe','pipe'],env});owner.children.push(child);owner.logs[label]='';
 for(const stream of [child.stdout,child.stderr]){
  let pending='';stream.setEncoding('utf8');stream.on('data',chunk=>{
   owner.logs[label]=redact((owner.logs[label]+chunk).slice(-32768));pending+=chunk;
   const lines=pending.split('\n');pending=lines.pop().slice(-8192);
   for(const line of lines){
    try{const value=JSON.parse(line);if(value.type==='memory_inference'){
     if(value.event==='inference_started')owner.requestContexts.set(value.request,{...progress.context,arm:owner.arm,character:value.model});
     const requestContext=owner.requestContexts.get(value.request)||{...progress.context};
     progress.log(value.event,{...requestContext,...value,character:value.model,process:label});
     if(value.event==='inference_timeout'){const timeoutContext={...requestContext,browser_step:requestContext.step,step:`Ollama ${value.curator?'curator':'conversation'} request #${value.request}`};const error=new Error(`Ollama request #${value.request} timed out after ${value.timeout_ms} ms`);error.browser_context=timeoutContext;report.wait_timeouts.push({...timeoutContext,request:value.request,timeout_ms:value.timeout_ms});owner.evidenceTasks.push(evidence(error,owner).catch(failure=>progress.log('diagnostics_error',{error:redact(failure.message)})));}
     continue;}}catch{}
    if(line.trim())progress.log('fixture_log',{arm:owner.arm,process:label,message:redact(line).slice(0,1000)});
   }
  });
 }
 child.on('error',error=>{owner.logs[label]+=redact(error.message);progress.log('fixture_spawn_error',{arm:owner.arm,process:label,error:redact(error.message)});});
 child.on('exit',(code,signal)=>progress.log('fixture_exit',{arm:owner.arm,process:label,pid:child.pid,code,signal}));return child;
}
async function evidence(error,owner=owned){
 const context=error.browser_context||{...progress.context};
 const prefix=`failure-${++evidenceSequence}-${context.arm||'preflight'}-${String(context.character||'setup').replace(/[^a-z0-9-]/gi,'-')}-t${context.turn}`;
 const data={context,error:redact(error.stack||error.message),cause:error.cause?redact(error.cause.stack||error.cause.message):null,navigation_error:error.navigation||null,timeouts,process_logs:owner?.logs||{},browser_errors:owner?.errors||[]};
 if(owner?.page){
  const page=owner.page;
  const results=await Promise.allSettled([
   deadline('failure screenshot',timeouts.evidence,()=>page.screenshot({path:path.join(out,prefix+'.png'),timeout:timeouts.evidence,mask:[page.locator('[data-token]')]})),
   deadline('failure DOM snapshot',timeouts.evidence,()=>page.evaluate(()=>({url:location.href,title:document.title,selected:document.querySelector('[data-selected]')?.textContent,status:document.querySelector('[data-status]')?.textContent,error:document.querySelector('[data-error]')?.textContent,dialogs:[...document.querySelectorAll('dialog[open]')].map(d=>d.id),activity:document.querySelector('[data-activity-label]')?.textContent}))),
  ]);
  if(results[0].status==='fulfilled')data.screenshot=prefix+'.png';else data.screenshot_error=redact(results[0].reason.message);
  if(results[1].status==='fulfilled')data.dom=results[1].value;else data.dom_error=redact(results[1].reason.message);
  try{data.management_dom=await deadline('management DOM snapshot',timeouts.evidence,()=>inspectManagementDOM(page));}catch(failure){data.management_dom_error=redact(failure.message);}
 }
 if(owner?.ai){try{
  const a=await deadline('failure audit snapshot',timeouts.evidence,signal=>local(owner.ai+'/fixture/audit',{},signal));
  data.audit={arm:a.arm,requests:a.requests.slice(-10),metrics:a.metrics.slice(-5),model:a.state.model,context_intelligence:a.state.context_intelligence,memory_curator:a.state.memory_curator,narrative:a.state.narrative};
 }catch(failure){data.audit_error=redact(failure.message);}}
 await writeFile(path.join(out,prefix+'.json'),redact(JSON.stringify(data,null,2)));
 report.evidence.push(prefix+'.json');progress.log('diagnostics_saved',{...context,file:prefix+'.json',screenshot:data.screenshot||null});return prefix+'.json';
}
async function boundedPoll(label,count,interval,predicate){
 // Keep the original polling counts and fall-through behavior; expose exhaustion without changing scoring.
 await step(label,async()=>{
  for(let n=0;n<count;n++){if(await predicate())return;await sleep(interval);}
  const error=new Error(`Existing polling budget exhausted: ${label}`);error.browser_context={...progress.context};
  report.wait_timeouts.push({...progress.context,polls:count});progress.log('wait_budget_exhausted',{polls:count});await evidence(error);
 },count*interval+timeouts.http+timeouts.evidence*3);
}
progress.log('run_start',{live,setup_only:setupOnly,viewport,detours,timeouts,report_directory:out});
let liveReady=true;
if(live){try{
 await step('Ollama preflight',async signal=>{
  const response=await fetch('http://127.0.0.1:11435/api/tags',{signal});if(!response.ok)throw Error('HTTP '+response.status);
  const installed=new Set((await response.json()).models.map(m=>m.name)),missing=(setupOnly?models.slice(0,1):models).filter(m=>!installed.has(m));if(missing.length)throw Error('Missing installed models: '+missing.join(', '));
 },timeouts.http);
}catch(error){liveReady=false;await evidence(error);for(const arm of comparisonArms)report.blocked.push({arm,phase:'Ollama preflight',step:error.browser_context?.step,error:'http://127.0.0.1:11435: '+redact(error.cause?.message||error.message)});}}
for(const arm of (liveReady?comparisonArms:[])){
 if(run.signal.aborted)break;
 owned={arm,children:[],logs:{},requestContexts:new Map(),evidenceTasks:[],errors:[],page:null,browser:null,server:null,ai:null};progress.set({arm,character:null,turn:0});progress.log('arm_start');
 try{
  const uiPort=await step('allocate UI port',port);let aiPort=await step('allocate observer port',port);while(aiPort===uiPort)aiPort=await step('allocate distinct observer port',port);
  const ui=`http://127.0.0.1:${uiPort}`,ai=`http://127.0.0.1:${aiPort}`,token=randomBytes(32).toString('hex');owned.ai=ai;
  await step('launch isolated fixtures',async()=>{
   const uiEnv={...process.env};delete uiEnv.EDGELOOP_PAIRING_FILE;
   launch('ui','python3',['tools/serve_local.py',String(uiPort)],uiEnv);
   launch('backend',path.join(root,'.venv/bin/python'),['-m','tests.fork.intelligent_memory_service'],{...process.env,EDGELOOP_MEMORY_ARM:arm,EDGELOOP_LIVE_ACCEPTANCE:live?'1':'0',EDGELOOP_FIXTURE_TOKEN:token,EDGELOOP_FIXTURE_UI_PORT:String(uiPort),EDGELOOP_FIXTURE_OBSERVER_PORT:String(aiPort),EDGELOOP_FIXTURE_OLLAMA_TIMEOUT_MS:String(timeouts.ollama)});
  });
  await step('wait for isolated UI',signal=>ready(ui,signal),timeouts.startup);
  await step('wait for isolated observer',signal=>ready(ai+'/health',signal),timeouts.startup);
  await step('launch owned Chromium',async signal=>{
   const owner=owned,server=await chromium.launchServer({timeout:timeouts.action});
   if(signal.aborted){await server.kill();throw signal.reason;}owner.server=server;
   const browser=await chromium.connect(server.wsEndpoint(),{timeout:timeouts.action});
   if(signal.aborted){await browser.close();throw signal.reason;}owner.browser=browser;
  });
  const context=await step('create browser context',()=>owned.browser.newContext({viewport}));
  await step('disable physical hardware APIs',()=>context.addInitScript(()=>{const no=()=>Promise.reject(new DOMException('Synthetic testing only','NotFoundError'));Object.defineProperty(navigator,'bluetooth',{value:{requestDevice:no},configurable:true});Object.defineProperty(navigator,'serial',{value:{requestPort:no,getPorts:async()=>[]},configurable:true});if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=no;}));
  const page=await step('open browser page',()=>context.newPage());owned.page=page;page.setDefaultTimeout(timeouts.action);page.setDefaultNavigationTimeout(timeouts.action);
  const errors=owned.errors;page.on('pageerror',error=>{errors.push(redact(error.message));progress.log('browser_error',{error:redact(error.message)});});
  page.on('console',message=>{if(message.type()==='error')progress.log('browser_console_error',{message:redact(message.text()).slice(0,1000)});});
  const audit=()=>local(ai+'/fixture/audit'),navigation=createMemoryNavigation(page,{timeout:timeouts.action});
  page.on('response',response=>{if(new URL(response.url()).pathname==='/ai/pair'){const value={arm,status:response.status(),purpose:'optional desktop auto-pair; manual WebSocket pairing is separate'};report.pairing_attempts.push(value);progress.log('desktop_pair_response',value);}});
  async function closeMenus(){await step('return to Chat',()=>navigation.showChat());}
  async function chat(text,label){
   progress.set({turn:progress.context.turn+1});progress.log('conversation_turn',{purpose:label});
   await closeMenus();await step('advance fixture clock',()=>local(ai+'/fixture/advance',{method:'POST'}));
   const before=(await step('read inference baseline',audit)).requests.length,start=Date.now();
   await step('enter conversation message',()=>page.locator('[data-text]').fill(text));
   await step('submit conversation message',()=>page.locator('[data-text]').press('Enter'));
   await step('wait for message submission',()=>page.waitForFunction(()=>document.querySelector('[data-text]').value===''));
   await step('wait for conversation inference/reply',()=>page.waitForFunction(()=>document.querySelector('[data-cancel]').hidden,null,{timeout:timeouts.reply}),timeouts.reply);
   const state=await step('read completed inference and response',audit);assert(state.requests.length>before,'No model generation reached the provider');
   const lastUser=state.history.filter(r=>r.role==='user').at(-1)?.content,reply=lastUser===text?state.history.filter(r=>r.role==='assistant').at(-1)?.content||'':'';
   const result={reply,error:lastUser===text?null:'No completed reply for the current request',seconds:(Date.now()-start)/1000,state};
   progress.log('conversation_result',{purpose:label,seconds:result.seconds,error:result.error,inference_requests:state.requests.length-before});return result;
  }
  async function reset(){
   const drawer=await step('open Story Memory for reset',()=>navigation.openStory());
   await step('start new storyline',()=>navigation.click(drawer.locator('[data-start-story]'),'Start New Storyline'));
   await step('confirm new storyline',()=>navigation.click(drawer.locator('[data-narrative-reset]'),'Confirm new storyline'));
   await step('wait for storyline reset',()=>page.waitForFunction(()=>{const d=document.querySelector('#character-story');return d?.querySelector('[data-menu-notice]')?.textContent==='New storyline started. Transcript retained.';}));await closeMenus();
  }
  await step('navigate to EdgeLoop',()=>page.goto(ui+'/?characterPreview=1'));
  await step('confirm age gate',()=>page.locator('#ageConfirmBtn').click());await step('skip device wizard',()=>page.locator('#wizardSkipBtn').click());
  await step('enter isolated observer URL',()=>page.locator('[data-url]').fill(`ws://127.0.0.1:${aiPort}/observe`));
  await step('enter ephemeral pairing credential',()=>page.locator('[data-token]').fill(token));await step('connect isolated observer',()=>page.locator('[data-connect]').click());
  for(let i=0;i<(setupOnly?1:models.length);i++){
   const model=models[i];progress.set({character:model,turn:0});progress.log('character_start');
   await step('wait for character model option',()=>page.waitForFunction(m=>!!document.querySelector(`[data-model] option[value="${m}"]`),model));
   await step('clear pairing input',()=>page.locator('[data-token]').evaluate(el=>{el.value='';}));
   await step('choose character model',()=>page.locator('[data-model]').selectOption(model));await step('apply character model',()=>page.locator('[data-select]').click());
   await step('wait for model selection',()=>page.waitForFunction(m=>document.querySelector('[data-selected]').textContent==='Active: '+m,model));
   const selectedState=(await step('check character memory scope',audit)).state;assert((selectedState.narrative.facts||[]).every(r=>r.model_scope.endsWith(model)),'Cross-character memory leakage');
   progress.log('management_layout',await inspectManagementDOM(page));
   if(arm==='C'){
    const drawer=await step('open curator controls',()=>navigation.openCurator());
    await step('set comparison curator mode',()=>drawer.locator('[data-curator-enabled]').setChecked(true));
    await step('set curator interval',()=>drawer.locator('[data-curator-interval]').fill('8'));
    await step('save curator setting',()=>navigation.click(drawer.locator('[data-curator-save]'),'Save curator setting'));
    await boundedPoll('wait for curator setting acknowledgement',30,100,async()=>curatorMatches((await audit()).state.memory_curator.config,arm));
   }
   await step('verify comparison curator state',async()=>{const cfg=(await audit()).state.memory_curator.config;assert(curatorMatches(cfg,arm),`Arm ${arm} curator state not applied: ${JSON.stringify(cfg)}`);progress.log('curator_state_verified',{config:cfg,controls_required:arm==='C'});});
   await closeMenus();await reset();const empty=(await step('check empty storyline',audit)).state.narrative;assert(!empty.facts?.length,'Model/reset memory leaked');
   await step('verify curator state after storyline reset',async()=>{const cfg=(await audit()).state.memory_curator.config;assert(curatorMatches(cfg,arm),`Arm ${arm} curator state changed during reset: ${JSON.stringify(cfg)}`);});
   const first=await chat('Imagine a laboratory mystery. Open with one brief observation.','open storyline');
   report.setup_checks.push({arm,model,conversation_turn:1,reply_completed:!first.error&&!!first.reply,inference_requests:first.state.requests.length,seconds:first.seconds,provider_metrics:first.state.metrics.at(-1),synthetic_reply:first.reply.slice(0,160)});
   assert(!first.error&&!!first.reply,`Arm ${arm} did not complete conversation turn 1`);
   if(setupOnly){progress.log('setup_only_done',report.setup_checks.at(-1));break;}
   const established=await chat(`Establish our scene as a fictional mystery. A blue laboratory door is marked ORCHID-17. In your reply, introduce your personal hobby as ${hobbies[i]}.`,'establish clue and hobby');
   const setupAudit=await step('read established premise',audit),setup=setupAudit.state.narrative,originalPremise=setup.premise;
   const establishmentSnapshot=memorySnapshot('after_establishment',setupAudit,{expected:hobbies[i],sourceReply:established.reply,sourceError:established.error});
   report.memory_snapshots.push({arm,model,...establishmentSnapshot});
   await writeFile(path.join(out,`${arm}-${i}-establishment.json`),redact(JSON.stringify(establishmentSnapshot,null,2)));
   progress.log('hobby_memory_snapshot',{stage:'after_establishment',outcome:establishmentSnapshot.outcome,fact_ids:establishmentSnapshot.hobby_fact_ids});
   for(let n=0;n<detours;n++)await chat(`A visitor leaves parcel number ${n} on the table. Reply with one brief unrelated observation.`,`detour ${n+1}/${detours}`);
   const detourSnapshot=memorySnapshot('after_detours',await audit(),{expected:hobbies[i],previous:establishmentSnapshot});
   report.memory_snapshots.push({arm,model,...detourSnapshot});
   await writeFile(path.join(out,`${arm}-${i}-detours.json`),redact(JSON.stringify(detourSnapshot,null,2)));
   progress.log('hobby_memory_snapshot',{stage:'after_detours',outcome:detourSnapshot.outcome,fact_ids:detourSnapshot.hobby_fact_ids});
   if(arm==='C'){
    await step('advance curator quiet window',async()=>{await local(ai+'/fixture/advance',{method:'POST'});await local(ai+'/fixture/advance',{method:'POST'});});
    await boundedPoll('wait for curator result',200,200,async()=>['applied','rejected'].includes((await audit()).state.memory_curator.status));
   }
   const recalls=[];
   for(const [query,expected] of [['What was the identifier on the blue laboratory door?','ORCHID-17'],['What is your hobby?',hobbies[i]]]){
    const beforeRecall=query.includes('hobby')?await audit():null;
    const result=await chat(query,query.includes('hobby')?'recall hobby':'recall identifier');const d=result.state.state.context_intelligence;
    const inventedIdentifiers=(result.reply.match(/\b[A-Z]+-\d+\b/g)||[]).filter(x=>x!=='ORCHID-17');
    const anchors=[['succulent'],['wildflowers'],['fountain','pens']][i];const hobbyAnchor=query.includes('hobby')&&anchors.every(x=>result.reply.toLowerCase().includes(x));
    recalls.push({query,expected,error:result.error,hobby_anchor_present:query.includes('hobby')?hobbyAnchor:null,unsupported_hobby_candidate:query.includes('hobby')&&!!result.reply&&!hobbyAnchor&&!/cannot|can't|unknown|uncertain|not sure|could/i.test(result.reply),exact:result.reply.includes(expected),unsupported_identifiers:inventedIdentifiers,reply:result.reply.slice(0,300),seconds:result.seconds,selected_fact_ids:d.narrative_recall?.selected_fact_ids||[],estimated_prompt_tokens:d.estimated_prompt_tokens,provider_metrics:result.state.metrics.at(-1)});
    const coverage=factualCoverage(expected,result.reply,query.includes('hobby')?'hobby':'identifier');
    recalls.at(-1).semantic_factual_coverage=coverage;
    recalls.at(-1).unsupported_addition_checks=unsupportedAdditions(expected,result.reply,established.reply,query.includes('hobby')?'hobby':'identifier');
    if(query.includes('hobby')){const snapshot=memorySnapshot('at_recall',{...beforeRecall,state:{...beforeRecall.state,context_intelligence:result.state.state.context_intelligence}},{expected,previous:detourSnapshot,sourceSnapshot:establishmentSnapshot});report.memory_snapshots.push({arm,model,...snapshot});await writeFile(path.join(out,`${arm}-${i}-recall.json`),redact(JSON.stringify(snapshot,null,2)));recalls.at(-1).memory_outcome=snapshot.outcome;}
    progress.log('recall_result',{expected,exact:recalls.at(-1).exact,hobby_anchor_present:recalls.at(-1).hobby_anchor_present,unsupported_identifiers:inventedIdentifiers,error:result.error});
   }
   await chat('Actually, the blue laboratory door is marked ORCHID-18. Remember this correction.','correct identifier');const corrected=await chat('What was the identifier on the blue laboratory door?','recall corrected identifier');
   progress.log('correction_result',{expected:'ORCHID-18',exact:corrected.reply.includes('ORCHID-18')});
   await step('inspect Story Memory',()=>navigation.openStory());await step('wait for visible clue memory',()=>page.waitForFunction(()=>document.querySelector('#character-story [data-story-content]').textContent.includes('ORCHID')));
   const shot=`${arm}-${i}-story.png`;await step('save Story Memory screenshot',()=>page.screenshot({path:path.join(out,shot),mask:[page.locator('[data-token]')]}));report.screenshots.push(shot);await closeMenus();
   const director=await step('open Director diagnostics',()=>navigation.openDirector());await step('inspect Context Intelligence',async()=>{const disclosure=director.locator('[data-context-intelligence]');if(await disclosure.getAttribute('open')===null)await navigation.click(disclosure.locator(':scope > summary'),'Context Intelligence disclosure');});await step('save Context Intelligence screenshot',()=>page.screenshot({path:path.join(out,`${arm}-${i}-context.png`),mask:[page.locator('[data-token]')]}));await closeMenus();
   const state=(await step('check premise continuity',audit)).state;assert(state.narrative.premise===originalPremise,'Temporary topic replaced premise');
   const audited=await step('collect evaluation metrics',audit);const calls=audited.requests.filter(r=>r.model===model),metrics=audited.metrics.filter(r=>r.model===model);
   report.rows.push({arm,model,recalls,inference_calls:calls.length,curator_calls:calls.filter(r=>r.curator).length,provider_prompt_tokens:metrics.reduce((sum,m)=>sum+(m.prompt_tokens||0),0),provider_latency_seconds:metrics.reduce((sum,m)=>sum+(m.response_latency_seconds||0),0),memory_bytes:JSON.stringify(state.narrative).length,correction_exact:corrected.reply.includes('ORCHID-18'),memory_size:state.narrative.facts?.length||0,curation:state.memory_curator,premise_stable:true,personality_review:'Synthetic responses saved; manual character consistency review required'});
   await reset();const missing=await chat('What was the identifier on the blue laboratory door?','check recall after reset');assert(!/ORCHID-\d+/.test(missing.reply),'Reset leaked or invented old identifier');report.rows.at(-1).reset_check={passed:true};report.rows.at(-1).character_scope_check={passed:true};progress.log('character_done');
  }
  assert(errors.length===0,errors.join('; '));
 }catch(error){
  const context=error.browser_context||{...progress.context},file=await evidence(error);
  const target=/EPERM|EACCES|Isolated fixture unavailable|browserType.launch/.test(String(error.message))?report.blocked:report.failures;
  target.push({...context,error:redact(error.message).slice(0,350),evidence:file});
 }finally{
  progress.log('cleanup_start');
  await Promise.allSettled(owned.evidenceTasks);
  await stopOwnedBrowser(owned.browser,owned.server,timeouts.cleanup,(event,fields)=>progress.log(event,fields));
  await stopOwnedChildren(owned.children,timeouts.cleanup,(event,fields)=>progress.log(event,fields));
  await Promise.allSettled(owned.evidenceTasks);
  progress.log('cleanup_done');owned=null;
 }
}
report.setup_completed=comparisonArms.every(arm=>report.setup_checks.some(r=>r.arm===arm&&r.model===models[0]&&r.reply_completed))&&report.blocked.length===0&&report.failures.length===0;
// Full-comparison evaluation and success criteria remain unchanged; setup-only never claims recall acceptance.
report.completed=report.rows.length===comparisonArms.length*models.length&&report.blocked.length===0&&report.failures.length===0;
report.recall_accuracy=Object.fromEntries(comparisonArms.map(arm=>{const answers=report.rows.filter(r=>r.arm===arm).flatMap(r=>r.recalls);return [arm,{exact:answers.filter(r=>r.exact).length,total:answers.length}];}));
report.improved_recall_pass=report.completed&&report.rows.filter(r=>r.arm!=='A').every(r=>r.correction_exact&&r.recalls.every(a=>a.query.includes('hobby')?a.hobby_anchor_present:a.exact));
report.semantic_factual_coverage=Object.fromEntries(comparisonArms.map(arm=>{const replies=report.rows.filter(r=>r.arm===arm).flatMap(r=>r.recalls);return [arm,{covered:replies.filter(r=>r.semantic_factual_coverage?.covered).length,total:replies.length,unsupported_addition_candidates:replies.reduce((count,r)=>count+(r.unsupported_addition_checks?.length||0),0)}];}));
report.curator_disabled_verified=deterministicOnly&&report.rows.length?report.rows.every(r=>r.curator_calls===0&&!r.curation.config.enabled):null;
report.curator_applied_models=report.rows.filter(r=>r.arm==='C'&&r.curation.status==='applied').length;
await writeFile(path.join(out,'report.json'),redact(JSON.stringify(report,null,2)));progress.log('run_done',{completed:report.completed,report:path.join(out,'report.json')});console.log(JSON.stringify(report));
if(signalExit)process.exitCode=signalExit;else if(setupOnly){if(!report.setup_completed)process.exitCode=1;}else if(!report.completed||!report.improved_recall_pass||(!deterministicOnly&&report.curator_applied_models!==3))process.exitCode=1;
