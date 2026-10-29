// SPDX-License-Identifier: AGPL-3.0-only
// Test-only deadlines, progress and owned-process cleanup. No service discovery or process-name kills.
import {appendFileSync} from 'node:fs';

export function timeoutSettings(env,live=false){
 const read=(key,fallback,max=600000)=>{const value=Number(env[key]??fallback);if(!Number.isFinite(value)||value<1||value>max)throw Error(`${key} must be between 1 and ${max} milliseconds`);return value;};
 const action=read('MEMORY_ACTION_TIMEOUT_MS',live?180000:20000),ollama=read('MEMORY_OLLAMA_TIMEOUT_MS',120000,300000);
 return {action,ollama,reply:read('MEMORY_REPLY_TIMEOUT_MS',live?Math.max(action,ollama+30000):action),http:read('MEMORY_HTTP_TIMEOUT_MS',5000),startup:read('MEMORY_STARTUP_TIMEOUT_MS',10000),evidence:read('MEMORY_EVIDENCE_TIMEOUT_MS',5000),cleanup:read('MEMORY_CLEANUP_TIMEOUT_MS',5000)};
}
export function redact(value){return String(value).replace(/\b[a-f0-9]{64}\b/gi,'[redacted]').replace(/(bearer\s+)[^\s"']+/gi,'$1[redacted]');}
export class StepTimeout extends Error {
 constructor(label,ms){super(`Timeout after ${ms} ms: ${label}`);this.name='StepTimeout';this.step=label;this.timeout_ms=ms;}
}
export async function deadline(label,ms,operation,signal){
 const controller=new AbortController();let timer,onAbort;
 const expiry=new Promise((_,reject)=>{
  const fail=reason=>{controller.abort(reason);reject(reason);};
  timer=setTimeout(()=>fail(new StepTimeout(label,ms)),ms);
  onAbort=()=>fail(signal.reason||new Error('Run interrupted'));
  if(signal?.aborted)onAbort();else signal?.addEventListener('abort',onAbort,{once:true});
 });
 try{return await Promise.race([expiry,Promise.resolve().then(()=>{controller.signal.throwIfAborted();return operation(controller.signal);})]);}
 finally{clearTimeout(timer);signal?.removeEventListener('abort',onAbort);}
}
export class Progress {
 constructor(file,write=line=>console.log(line)){this.file=file;this.write=write;this.context={arm:null,character:null,turn:0,step:'initialization'};this.sequence=0;}
 set(fields){Object.assign(this.context,fields);}
 log(event,fields={}){
  const record=JSON.parse(redact(JSON.stringify({at:new Date().toISOString(),sequence:++this.sequence,...this.context,event,...fields})));
  appendFileSync(this.file,JSON.stringify(record)+'\n');
  this.write(`[memory ${record.arm||'-'} | ${record.character||'-'} | turn ${record.turn} | ${record.step}] ${event} ${JSON.stringify(fields,(key,value)=>typeof value==='string'?redact(value):value)}`);
 }
 async step(label,ms,operation,signal){
  this.set({step:label});const context={...this.context},start=Date.now();this.log('step_start',{timeout_ms:ms});
  const heartbeat=setInterval(()=>this.log('waiting',{...context,elapsed_ms:Date.now()-start}),10000);
  try{const result=await deadline(label,ms,operation,signal);this.log('step_done',{...context,elapsed_ms:Date.now()-start});return result;}
  catch(error){error.browser_context??=context;this.log('step_failed',{...context,elapsed_ms:Date.now()-start,error:redact(error.message),cause:error.cause?redact(error.cause.message):undefined});throw error;}
  finally{clearInterval(heartbeat);}
 }
}
// Only ChildProcess objects returned by this runner's spawn calls are accepted here.
export async function stopOwnedChildren(children,ms,log=()=>{}){
 await Promise.all(children.map(async child=>{
  if(!child.pid||child.exitCode!==null||child.signalCode!==null)return;
  const exited=new Promise(resolve=>child.once('close',resolve));
  log('cleanup_process',{pid:child.pid,signal:'SIGTERM'});child.kill('SIGTERM');
  try{await deadline('owned child exit',ms,()=>exited);}
  catch(error){
   if(child.exitCode===null&&child.signalCode===null){log('cleanup_process',{pid:child.pid,signal:'SIGKILL'});child.kill('SIGKILL');}
   try{await deadline('owned child kill exit',ms,()=>exited);}catch{log('cleanup_incomplete',{pid:child.pid});}
  }
 }));
}
export async function stopOwnedBrowser(browser,server,ms,log=()=>{}){
 try{if(browser)await deadline('owned browser close',ms,()=>browser.close());}
 catch(error){log('cleanup_browser_error',{error:redact(error.message)});}
 try{if(server)await deadline('owned browser server close',ms,()=>server.close());}
 catch(error){
  log('cleanup_browser_force',{pid:server.process()?.pid,error:redact(error.message)});
  try{await deadline('owned browser server kill',ms,()=>server.kill());}catch{log('cleanup_browser_incomplete',{});}
 }
}
