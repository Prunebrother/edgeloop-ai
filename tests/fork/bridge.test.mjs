// SPDX-License-Identifier: AGPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Capture} from '../../src/js/ai/snapshot.js';
import {ReadOnlyConnection,reactionMatchesLatest} from '../../src/js/ai/connection.js';
const uuid=()=>crypto.randomUUID();
function raw(){return {sessionStatus:'IDLE',sessionSeconds:0,teaseMode:'classic',activeMode:'classic',gameMode:null,
    sensorHr:90,effectiveMaxHr:140,edgeTriggerHr:133,history:[90],lastHrTimestamp:1,edges:0,intensityValue:50,
    strokerSpeed:0,prostateSpeed:0,strokeMin:0,strokeMax:100,simEngaged:true,hrSignalState:'ok',hrNoContact:false,hrSignalPaused:false,
    chosenTargetSeconds:12345,durationMinSeconds:10000,handyKey:'PRIVATE_KEY',configuration:{secret:'PRIVATE_CONFIG'}};}
const devices={simulated_hr:true,hr_ready:true,toy_ready:true,ble:false,handy:false,intiface:false,tcode:false,vacuglide:false};

test('projection is read-only, redacts targets/keys/history and uses original values',()=>{
    const s=raw();Object.freeze(s.configuration);Object.freeze(s.history);Object.freeze(s);
    const c=new Capture();const {snapshot,events}=c.project(s,{...devices,key:'PRIVATE_DEVICE_KEY'});
    assert.equal(snapshot.effective_max,140);assert.equal(snapshot.pullback,133);assert.equal(snapshot.intensity,100);
    assert.equal(snapshot.hr,90);assert.equal(snapshot.seconds,0);assert.deepEqual(events,[]);
    const json=JSON.stringify(snapshot);
    for(const forbidden of ['PRIVATE','chosenTarget','12345','history','configuration','durationMin'])assert.ok(!json.includes(forbidden));
});

test('session ID survives model/connection changes; significant events emitted once',()=>{
    const c=new Capture();const s=raw();const idle=c.project(s,devices).snapshot.session_id;
    s.sessionStatus='RUNNING';s.sessionSeconds=17;s.strokerSpeed=20;
    let p=c.project(s,devices);assert.notEqual(p.snapshot.session_id,idle);const active=p.snapshot.session_id;
    assert.equal(p.events[0].kind,'session_started');assert.deepEqual(c.project(s,devices).events,[]);
    s.edges=1;assert.equal(c.project(s,devices).events[0].kind,'edge');assert.deepEqual(c.project(s,devices).events,[]);
    s.sessionStatus='PAUSED';assert.equal(c.project(s,devices).events[0].kind,'pause');
    s.sessionStatus='RUNNING';assert.equal(c.project(s,devices).snapshot.session_id,active);
    s.sessionStatus='IDLE';assert.equal(c.project(s,devices).events[0].kind,'stop');
    s.sessionStatus='RUNNING';assert.notEqual(c.project(s,devices).snapshot.session_id,active);
});

test('trend is presentation only, expires and never writes measured/effective HR',()=>{
    let now=0;const c=new Capture({now:()=>now});const s=raw();
    for(const bpm of [90,93,96,98]){s.sensorHr=bpm;s.lastHrTimestamp=now;c.project(s,devices);now+=1000;}
    assert.equal(c.project(s,devices).snapshot.trend,'rising');assert.equal(s.sensorHr,98);assert.equal(s.effectiveMaxHr,140);
    now=20000;assert.equal(c.project(s,devices).snapshot.trend,'unknown');
    assert.equal(c.project(s,{...devices,hr_ready:false}).snapshot.hr,null);
});

class Socket {
    static sockets=[];
    constructor(url){this.url=url;this.readyState=1;this.bufferedAmount=0;this.messages=[];Socket.sockets.push(this);}
    send(m){this.messages.push(JSON.parse(m));}
    receive(m){this.onmessage({data:JSON.stringify(m)});}
    close(){this.readyState=3;this.onclose?.({code:1000});}
}
function setup(){let now=0;const scheduled=[];const seen=[];
    const c=new ReadOnlyConnection({WebSocketImpl:Socket,now:()=>now,onMessage:m=>seen.push(m),schedule:fn=>{scheduled.push(fn);return fn;},cancel:fn=>{const i=scheduled.indexOf(fn);if(i>=0)scheduled.splice(i,1);}});
    return {c,scheduled,seen,setTime:t=>{now=t;}};
}
test('disabled/unavailable AI never affects observed source, and commands are ignored',()=>{
    const {c,seen}=setup();const s=raw(),capture=new Capture();const p=capture.project(s,devices);
    c.observe(p);assert.equal(c.socket,null);
    c.connect('ws://127.0.0.1:8768/observe','x'.repeat(32));const socket=c.socket;socket.onopen();
    assert.equal(socket.messages[0].type,'auth');socket.receive({type:'ready',version:1,epoch:uuid(),read_only:true});
    assert.ok(socket.messages.some(m=>m.type==='observation'));
    socket.receive({type:'command',action:'stop'});socket.receive({type:'control',action:'start'});
    assert.deepEqual(seen,[]);assert.equal(s.sessionStatus,'IDLE');
    assert.ok(socket.messages.every(m=>['auth','observation','list_models'].includes(m.type)));
    c.disconnect();assert.equal(c.token,'');assert.equal(c.epoch,null);
});

test('reconnect sends newest snapshot with fresh epoch and drops offline events',()=>{
    const {c,scheduled,setTime}=setup();const capture=new Capture(),s=raw();
    c.observe(capture.project(s,devices));c.connect('ws://localhost:8768/observe','x'.repeat(32));
    let ws=c.socket;ws.onopen();const epoch=uuid();ws.receive({type:'ready',version:1,epoch,read_only:true});
    ws.close();s.sessionStatus='RUNNING';s.sessionSeconds=99;c.observe(capture.project(s,devices));
    scheduled.shift()();ws=c.socket;ws.onopen();const next=uuid();setTime(2000);
    ws.receive({type:'ready',version:1,epoch:next,read_only:true});
    const frame=ws.messages.find(m=>m.type==='observation');assert.equal(frame.epoch,next);assert.notEqual(frame.epoch,epoch);
    assert.equal(frame.sequence,0);assert.equal(frame.snapshot.seconds,99);assert.deepEqual(frame.events,[]);
});

test('bounded latest-state/events, urgent stop and backpressure never replay stale batches',()=>{
    const {c,scheduled}=setup();const capture=new Capture(),s=raw();c.connect('ws://127.0.0.1:8768/observe','x'.repeat(32));
    const ws=c.socket;ws.onopen();ws.receive({type:'ready',version:1,epoch:uuid(),read_only:true});
    for(let i=0;i<100;i++){s.edges=i;c.observe(capture.project(s,devices));}
    assert.ok(c.pendingEvents.size<=16);assert.ok(scheduled.length<=1);
    s.sessionStatus='RUNNING';c.observe(capture.project(s,devices));s.sessionStatus='IDLE';c.observe(capture.project(s,devices));
    assert.equal(ws.messages.at(-1).snapshot.status,'IDLE');
    ws.bufferedAmount=40000;s.sessionStatus='PAUSED';c.observe(capture.project(s,devices));assert.equal(c.socket,null);
});

test('only localhost URLs, no credential queries; original controls have no model callback',()=>{
    const {c}=setup();for(const url of ['ws://evil.test/observe','ws://127.0.0.1:8768/observe?token=x','ws://u:p@localhost/observe'])
        assert.throws(()=>c.connect(url,'x'.repeat(32)));
    const app=readFileSync(new URL('../../src/js/app.js',import.meta.url),'utf8');
    assert.ok(app.includes('aiObservation?.(state,'));
    assert.ok(app.includes("import('./ai/companion.js')"));
    const panel=readFileSync(new URL('../../src/js/ai/companion.js',import.meta.url),'utf8');
    assert.ok(!panel.includes('dispatchHardware'));assert.ok(!panel.includes('sendPeerCommand'));
    assert.ok(!panel.includes('eval('));assert.ok(!panel.includes('localStorage'));
    const sw=readFileSync(new URL('../../sw.js',import.meta.url),'utf8');assert.ok(sw.includes("port === '8768'"));
});


test('default browser timers are called without the connection as receiver',t=>{
    const queued=[];let now=0;
    t.mock.method(globalThis,'setTimeout',function(fn){assert.equal(this,undefined);queued.push(fn);return 77;});
    const cleared=[];
    t.mock.method(globalThis,'clearTimeout',function(id){assert.equal(this,undefined);cleared.push(id);});
    const c=new ReadOnlyConnection({WebSocketImpl:Socket,now:()=>now});
    const capture=new Capture(),s=raw();c.observe(capture.project(s,devices));
    c.connect('ws://localhost:8768/observe','x'.repeat(32));const ws=c.socket;
    ws.onopen();ws.receive({type:'ready',version:1,epoch:uuid(),read_only:true});
    now=2000;c.observe(capture.project(s,devices));queued.shift()();
    assert.equal(ws.messages.filter(m=>m.type==='observation').length,2);
    c.observe(capture.project(s,devices));c.disconnect();assert.deepEqual(cleared,[77]);
});

test('settings, phase and capture metadata are allowlisted; missing pullback remains unknown',()=>{
 let now=1000;const c=new Capture({now:()=>now}),s=raw();s.lastHrTimestamp=now;s.edgeTriggerHr=null;s.pauses=2;s.warmupOriginSeconds=0;s.sessionSeconds=10;s.sessionStatus='RUNNING';s.calibrationPass='primary';
 const result=c.project(s,devices,{resting_bpm:70,single_max_bpm:140,dual_max_bpm:125,warmup_minutes:5,token:'PRIVATE'});
 assert.equal(result.snapshot.pullback,null);assert.equal(result.snapshot.details.resting_bpm,70);
 assert.equal(result.snapshot.details.pauses,2);assert.equal(result.snapshot.details.warmup_remaining_seconds,290);
 assert.equal(result.snapshot.details.calibration_pass,'primary');assert.equal(result.snapshot.details.captured_at_ms,1000);
 assert.ok(!JSON.stringify(result).includes('PRIVATE'));
});

test('BLE connection is not a measurement; source changes and unique timestamps segment trend evidence',()=>{
 let now=1000;const c=new Capture({now:()=>now}),s=raw();s.simEngaged=false;s.lastHrTimestamp=900;
 const ble={...devices,simulated_hr:false,ble:true};assert.equal(c.project(s,ble).snapshot.hr,null);
 now+=1000;s.lastHrTimestamp=now;assert.equal(c.project(s,ble).snapshot.hr,90);
 for(let i=0;i<8;i++){now+=100;c.project(s,ble);}
 assert.equal(c.samples.length,1);assert.equal(c.project(s,ble).snapshot.trend,'unknown');
 s.simEngaged=true;assert.equal(c.project(s,devices).snapshot.trend,'unknown');
});

test('configuration changes are not HR changes and paused state is not a resume event',()=>{
 let now=1000;const c=new Capture({now:()=>now}),s=raw();s.lastHrTimestamp=now;s.sessionStatus='RUNNING';
 c.project(s,devices,{single_max_bpm:140});now+=1000;
 const changed=c.project(s,devices,{single_max_bpm:150});assert.equal(changed.snapshot.hr,90);
 assert.ok(changed.events.some(e=>e.kind==='threshold_changed'));assert.equal(changed.snapshot.trend,'unknown');
 s.sessionStatus='RAMPDOWN';const phase=c.project(s,devices);assert.ok(!phase.events.some(e=>e.kind==='session_resumed'));
 s.sessionStatus='PAUSED';assert.ok(c.project(s,devices).events.some(e=>e.kind==='pause'));
});

test('Came Early requires a source counter delta and original accepted ending, never a click or idle write',()=>{
 let now=1000;const c=new Capture({now:()=>now}),s=raw();s.sessionStatus='RUNNING';s.settleOutcome=null;
 c.project(s,devices,{learning_release_count:0});now+=500;s.settleOutcome='Premature Release';
 let projection=c.project(s,devices,{learning_release_count:1});assert(projection.events.some(e=>e.kind==='came_early'));
 now+=500;assert(!c.project(s,devices,{learning_release_count:1}).events.some(e=>e.kind==='came_early'));
 s.sessionStatus='IDLE';s.settleOutcome=null;now+=500;c.project(s,devices,{learning_release_count:1});
 now+=500;assert(!c.project(s,devices,{learning_release_count:2}).events.some(e=>e.kind==='came_early'));
});

test('I came: every orgasm count increase is one orgasm_reported event; the session keeps running',()=>{
 let now=1000;const c=new Capture({now:()=>now}),s=raw();s.sessionStatus='RUNNING';s.sessionSeconds=200;
 assert.equal(c.project(s,devices,{orgasm_count:0}).snapshot.details.orgasm_count,0);
 for(const n of [1,2]){
  now+=500;s.sessionSeconds+=100;const p=c.project(s,devices,{orgasm_count:n,last_orgasm_seconds:s.sessionSeconds});
  assert.equal(p.events.filter(e=>e.kind==='orgasm_reported').length,1);assert.equal(p.snapshot.details.orgasm_count,n);
  assert.equal(p.snapshot.details.last_orgasm_seconds,s.sessionSeconds);assert.equal(p.snapshot.status,'RUNNING');
  now+=500;assert(!c.project(s,devices,{orgasm_count:n,last_orgasm_seconds:s.sessionSeconds}).events.some(e=>e.kind==='orgasm_reported'));
 }
 const src=readFileSync(new URL('../../src/js/app.js',import.meta.url),'utf8'),html=readFileSync(new URL('../../index.html',import.meta.url),'utf8');
 // Its own button, open the whole running session with or without Force Orgasm; Came Early stays accidental.
 assert.match(html,/id="iCameBtn"/);
 assert.match(src,/iCameBtn\?\.addEventListener\('click', \(\) => reportOrgasm\(\)\)/);
 assert.doesNotMatch(src,/function orgasmReportOpen\(\) \{[^}]*orgasmMode/);
 assert.match(src,/beginSettle\(survival \? \{ restartSurvival: true \} : \{ restartWarmup: true \}\)/);
 assert.doesNotMatch(src,/label\.textContent = coming/);
});

// Codex review 2026-11-10: run the real reportOrgasm with the app's helpers stubbed.
function orgasmReporter(state){
 const src=readFileSync(new URL('../../src/js/app.js',import.meta.url),'utf8');
 const start=src.indexOf('const ORGASM_REPORT_GAP_MS'),end=src.indexOf('\n}\n',src.indexOf('function reportOrgasm()'))+3;
 assert(start>0&&end>start);
 const calls=[];let now=0;
 const env={state,calls,Date:{now:()=>now},
  orgasmReportOpen:()=>['RUNNING','PAUSED'].includes(state.sessionStatus),
  countOrgasm:()=>{state.orgasmCount=(state.orgasmCount||0)+1;calls.push('count');},
  beginSettle:o=>{calls.push(['settle',o]);if(state.sessionStatus==='PAUSED')state.sessionStatus='RUNNING';},
  setOrgasmMode:on=>{state.orgasmMode=on;calls.push(['orgasmMode',on]);},
  restartWarmupAfterOrgasm:()=>calls.push('warmup'),restartSurvivalAfterOrgasm:()=>calls.push('survival'),
  renderICameButton:()=>{},syncAiObservation:()=>{},syncTelemetry:()=>{}};
 const report=new Function(...Object.keys(env),src.slice(start,end)+'\nreturn reportOrgasm;')(...Object.values(env));
 return {report,calls,advance:ms=>{now+=ms;}};
}

test('I came while paused counts, resets the warm-up and stays paused: the toys never resume on their own',()=>{
 for(const [mode,restart] of [['classic','warmup'],['survival','survival']]){
  const state={sessionStatus:'PAUSED',activeMode:mode,orgasmMode:true},r=orgasmReporter(state);
  r.report();
  assert.equal(state.sessionStatus,'PAUSED');assert.equal(state.orgasmCount,1);assert.equal(state.orgasmMode,false);
  assert(r.calls.includes(restart));assert(!r.calls.some(c=>c[0]==='settle'));
 }
 const state={sessionStatus:'RUNNING',activeMode:'classic'},r=orgasmReporter(state);
 r.report();assert.deepEqual(r.calls.at(-1),['settle',{restartWarmup:true}]);
});

test('a double tap or held C counts one orgasm, whatever the ease-down time; a later report counts again',()=>{
 const state={sessionStatus:'RUNNING',activeMode:'classic'},r=orgasmReporter(state);
 r.report();r.advance(200);r.report();r.advance(2000);r.report();
 assert.equal(state.orgasmCount,1);
 r.advance(1000);r.report();assert.equal(state.orgasmCount,2);
});

test('a selection reaction cannot update the UI after a newer local engine projection, even before network acknowledgement',()=>{
 const old={session_id:'s',experience:'headplay',goal:'tease'};
 assert(reactionMatchesLatest(old,{...old}));
 assert(!reactionMatchesLatest(old,{...old,experience:'ruin'}));
 assert(!reactionMatchesLatest(old,{...old,goal:'oracle'}));
 assert(!reactionMatchesLatest(old,{...old,session_id:'next'}));
 assert(!reactionMatchesLatest(old,null));assert(reactionMatchesLatest(null,null));
});


test('story reset acknowledgement is presentation data and control messages remain ignored',()=>{
    let socket;const messages=[];
    class Socket {constructor(){socket=this;this.readyState=1;this.bufferedAmount=0;}send(){}close(){}}
    const c=new ReadOnlyConnection({WebSocketImpl:Socket,uuid:()=>"fixture-browser",onMessage:m=>messages.push(m)});
    c.connect('ws://127.0.0.1:8768/observe','x'.repeat(32));
    socket.onmessage({data:JSON.stringify({type:'narrative_reset',model:'evelyn-narrative-v1:latest'})});
    socket.onmessage({data:JSON.stringify({type:'command',action:'start'})});
    assert.deepEqual(messages,[{type:'narrative_reset',model:'evelyn-narrative-v1:latest'}]);c.disconnect();
});


test('a replaced tab yields ownership without reconnecting',()=>{
 const scheduled=[];const c=new ReadOnlyConnection({WebSocketImpl:Socket,schedule:fn=>scheduled.push(fn)});
 c.connect('ws://127.0.0.1:8768/observe','x'.repeat(43));
 c.socket.onclose({code:4001});
 assert.equal(c.superseded,true);assert.equal(c.enabled,false);assert.equal(c.token,'');assert.equal(scheduled.length,0);
 c.connect('ws://127.0.0.1:8768/observe','y'.repeat(43));assert.equal(c.superseded,false);c.disconnect();
});

test('F281 accepted terminal projection preserves final ticks before reset without inventing successful completion',()=>{
 const capture=new Capture(),s=raw();capture.project(s,devices);s.sessionStatus='RUNNING';s.activeMode='calibrate';s.gameMode='calibrate';s.sessionSeconds=937;capture.project(s,devices);
 s.sessionStatus='IDLE';const final=capture.project(s,devices,{terminal_outcome:'Calibration'});
 assert.equal(final.snapshot.seconds,937);assert.deepEqual(final.events.map(e=>e.kind),['completion_accepted','stop']);
 s.sessionSeconds=0;s.edges=0;const reset=capture.project(s,devices);assert.equal(reset.snapshot.session_id,final.snapshot.session_id);assert.equal(reset.snapshot.seconds,0);assert.deepEqual(reset.events,[]);
 s.sessionStatus='RUNNING';s.activeMode='classic';s.gameMode='tease';capture.project(s,devices);s.sessionStatus='IDLE';const manual=capture.project(s,devices,{terminal_outcome:'Stopped'});assert.deepEqual(manual.events.map(e=>e.kind),['stop']);
});

test('F281 Survival acknowledgment requires a new accepted restart marker; session continues',()=>{
 const capture=new Capture(),s=raw();s.activeMode='survival';s.gameMode='survival';s.sessionStatus='RUNNING';s.sessionSeconds=90;capture.project(s,devices);
 let p=capture.project(s,devices,{terminal_outcome:'Survival Restart'});assert.deepEqual(p.events.map(e=>e.kind),['completion_accepted']);assert.equal(p.snapshot.status,'RUNNING');assert.equal(p.snapshot.seconds,90);
 assert.deepEqual(capture.project(s,devices,{terminal_outcome:'Survival Restart'}).events,[]);
});

test('F281 terminal observation is sent before a coalesced counter reset',()=>{
 const {c}=setup(),capture=new Capture(),s=raw();c.observe(capture.project(s,devices));c.connect('ws://127.0.0.1:8768/observe','x'.repeat(32));const ws=c.socket;ws.onopen();ws.receive({type:'ready',version:1,epoch:uuid(),read_only:true});
 s.sessionStatus='RUNNING';s.sessionSeconds=937;c.observe(capture.project(s,devices));s.sessionStatus='IDLE';c.observe(capture.project(s,devices,{terminal_outcome:'Stopped'}));
 assert.equal(ws.messages.at(-1).snapshot.seconds,937);assert.equal(ws.messages.at(-1).snapshot.details.terminal_outcome,'manual_stop');
 s.sessionSeconds=0;c.observe(capture.project(s,devices));assert.equal(c.latest.seconds,0);assert.equal(ws.messages.at(-1).snapshot.seconds,0);assert.equal(ws.messages.at(-2).snapshot.seconds,937);
});

test('F281 reset projects cancellation without manufacturing a completion',()=>{
 const c=new Capture(),s=raw();c.project(s,devices);s.sessionStatus='RUNNING';s.sessionSeconds=90;c.project(s,devices);s.sessionStatus='IDLE';
 const p=c.project(s,devices,{terminal_outcome:'Cancelled'});assert.equal(p.snapshot.details.terminal_outcome,'cancelled');assert.deepEqual(p.events.map(e=>e.kind),['stop']);
});

test('Player projection is allowlisted and emits only proven new interaction counters',()=>{
 const s=raw(),c=new Capture(),id=crypto.randomUUID();
 s.playerObservation={instance_id:id,opened:0,selected:0,started:0,workspace_open:false,has_video:false,playing:false,title:null,title_source:'unknown',private_path:'/PRIVATE/media.mp4'};
 assert.equal(c.project(s,devices).events.length,0);
 s.playerObservation.opened=1;s.playerObservation.workspace_open=true;
 assert.deepEqual(c.project(s,devices).events.map(e=>e.kind),['player_opened']);
 assert.equal(c.project(s,devices).events.length,0);
 s.playerObservation.selected=1;s.playerObservation.has_video=true;s.playerObservation.title='Aladdin';s.playerObservation.title_source='filename';
 assert.deepEqual(c.project(s,devices).events.map(e=>e.kind),['video_selected']);
 s.playerObservation.started=1;s.playerObservation.playing=true;
 assert.deepEqual(c.project(s,devices).events.map(e=>e.kind),['video_started']);
 assert.equal(c.project(s,devices).events.length,0);
 assert.ok(!JSON.stringify(c.previous).includes('PRIVATE'));
 s.playerObservation.instance_id=crypto.randomUUID();s.playerObservation.opened=7;
 assert.equal(c.project(s,devices).events.length,0);
});

test('optional Player events cannot evict stop or engine events from a full observation batch',()=>{
 const sent=[],c=new ReadOnlyConnection();c.enabled=true;c.epoch=uuid();
 c.socket={readyState:1,bufferedAmount:0,send:raw=>sent.push(JSON.parse(raw))};
 const kinds=['stop','pause','session_started','session_resumed','mode_changed','edge','signal_lost','signal_restored','no_contact','device_changed','milestone','experience_changed','goal_changed','intensity_changed','threshold_changed','came_early'];
 c.observe({snapshot:{status:'IDLE',details:{}},events:[...kinds,'player_opened','video_selected','video_started'].map(kind=>({kind,id:uuid()}))});
 assert.deepEqual(sent[0].events.map(e=>e.kind),kinds);
});
