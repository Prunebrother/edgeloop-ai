// SPDX-License-Identifier: AGPL-3.0-only
import test from 'node:test';import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';import {tmpdir} from 'node:os';import path from 'node:path';import {EventEmitter} from 'node:events';
import {Progress,deadline,timeoutSettings,redact,stopOwnedChildren,stopOwnedBrowser} from './memory-browser-support.mjs';
test('deadline aborts the request and retains exact failing step',async()=>{
 let aborted=false;await assert.rejects(deadline('wait for Evelyn reply',10,signal=>new Promise(()=>signal.addEventListener('abort',()=>{aborted=true;}))),error=>error.step==='wait for Evelyn reply'&&error.timeout_ms===10);
 assert(aborted);
});
test('SIGINT-style abort interrupts an active wait and releases timer',async()=>{
 const controller=new AbortController();const pending=deadline('model selection',5000,()=>new Promise(()=>{}),controller.signal);controller.abort(new Error('Runner interrupted by SIGINT'));
 await assert.rejects(pending,/SIGINT/);
});
test('progress contains arm, character, turn and exact failing browser step without tokens',async()=>{
 const dir=await mkdtemp(path.join(tmpdir(),'memory-progress-'));try{
  const output=[],p=new Progress(path.join(dir,'events.jsonl'),line=>output.push(line));p.set({arm:'C',character:'Evelyn',turn:7});
  await assert.rejects(p.step('recall inference',10,()=>new Promise(()=>{})),error=>error.browser_context.turn===7);
  p.log('fixture_log',{message:'token '+ 'a'.repeat(64)});
  const data=await readFile(path.join(dir,'events.jsonl'),'utf8');assert(!data.includes('a'.repeat(64)));assert(data.includes('step_failed'));assert(output.some(s=>s.includes('C | Evelyn | turn 7 | recall inference')));
 }finally{await rm(dir,{recursive:true,force:true});}
});
test('timeout environment is validated and independently configurable',()=>{
 const t=timeoutSettings({MEMORY_ACTION_TIMEOUT_MS:'800',MEMORY_OLLAMA_TIMEOUT_MS:'1500'},true);assert.equal(t.action,800);assert.equal(t.ollama,1500);assert.equal(t.reply,31500);
 assert.throws(()=>timeoutSettings({MEMORY_OLLAMA_TIMEOUT_MS:'Infinity'}));assert.throws(()=>timeoutSettings({MEMORY_ACTION_TIMEOUT_MS:'0'}));assert.throws(()=>timeoutSettings({MEMORY_OLLAMA_TIMEOUT_MS:'300001'}));
 assert.equal(redact('Bearer confidential'), 'Bearer [redacted]');
});
test('cleanup escalates only supplied owned child handles and awaits their exit',async()=>{
 const signals=[];class Child extends EventEmitter{pid=987654;exitCode=null;signalCode=null;kill(signal){signals.push(signal);if(signal==='SIGKILL'){this.signalCode=signal;this.emit('exit');this.emit('close');}}}
 const owned=new Child(),external=new Child();external.kill=()=>assert.fail('external process touched');
 await stopOwnedChildren([owned],10);assert.deepEqual(signals,['SIGTERM','SIGKILL']);assert.equal(external.signalCode,null);
});
test('cleanup handles browser-close timeout using only its owned browser server',async()=>{
 let killed=false;await stopOwnedBrowser({close:()=>new Promise(()=>{})},{process:()=>({pid:123}),close:()=>new Promise(()=>{}),kill:async()=>{killed=true;}},10);
 assert(killed);
});
