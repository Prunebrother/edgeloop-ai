// SPDX-License-Identifier: AGPL-3.0-only
// Regression guards for upstream integration: the AI layer stays a read-only
// observer, the deterministic engine keeps sole control of hardware, and no
// agent command channel arrives silently with an upstream sync.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,readdirSync,existsSync} from 'node:fs';
import path from 'node:path';

const root=path.resolve(new URL('../..',import.meta.url).pathname);
const read=name=>readFileSync(path.join(root,name),'utf8');
const aiFiles=readdirSync(path.join(root,'src/js/ai')).filter(f=>f.endsWith('.js')).map(f=>'src/js/ai/'+f);

test('AI modules import only AI modules and the character manifest, never engine, drivers or transports',()=>{
    for(const file of aiFiles){
        const source=read(file);
        const specifiers=[...source.matchAll(/(?:^|\n)\s*import\s[^;]*?from\s*'([^']+)'|import\(\s*'([^']+)'\s*\)/g)].map(m=>m[1]||m[2]);
        for(const spec of specifiers){
            const allowed=/^\.\/[a-z-]+\.js$/.test(spec)||/^\.\.\/\.\.\/assets\/characters\/manifest\.json(\?[\w=-]+)?$/.test(spec);
            assert.ok(allowed,`${file} imports ${spec}`);
        }
    }
});

test('AI modules contain no hardware, peer, session-command or agent primitives',()=>{
    const forbidden=[/dispatchHardware/,/sendPeerCommand/,/sendControllerCommand/,/navigator\.(bluetooth|serial|usb|hid)/,
        /handyfeeling/i,/\/api\/handy/,/:12345\b/,/buttplug/i,/agent-api/,/\/api\/agent/,/\/api\/room/,
        /SESSION_STATE|MODE_CHANGE|ORGASM_TOGGLE|MANUAL_PATTERN|EDGE_MARK|INTENSITY_CHANGE/];
    for(const file of aiFiles){
        const source=read(file);
        for(const pattern of forbidden)assert.ok(!pattern.test(source),`${file} matches ${pattern}`);
    }
});

test('the AI layer presses only the user-clicked emergency stop and the close-only Player toggle',()=>{
    const clicks=aiFiles.flatMap(file=>[...read(file).matchAll(/\.click\(\)/g)].map(()=>file));
    assert.deepEqual(clicks,['src/js/ai/layout.js','src/js/ai/layout.js']);
    const layout=read('src/js/ai/layout.js');
    // 1. Emergency stop: the original engine Stop, used by the header and the in-stage button alike.
    assert.match(layout,/const emergencyStop=\(\)=>\{const stop=document\.getElementById\('sessionStopBtn'\);stop\.dataset\.safetyStop='true';stop\.click\(\);\};/);
    assert.match(layout,/\[data-emergency\]'\)\.onclick=emergencyStop;/);
    assert.match(layout,/addEventListener\('click',event=>\{event\.stopPropagation\(\);emergencyStop\(\);\}\)/);
    // 2. Close player: the upstream Player toggle (#playerHeaderBtn), pressed only to close an open player.
    //    It changes layout only; it never plays, pauses, loads media or changes the session.
    assert.match(layout,/const toggle=document\.getElementById\('playerHeaderBtn'\);/);
    assert.match(layout,/\[data-close-player\]'\)\.addEventListener\('click',\(\)=>\{if\(body\.dataset\.player==='on'\)toggle\.click\(\);\}\);/);
});

test('the engine mounts the companion with a refresh callback and the AI Settings gate only, and keeps its own stop authority',()=>{
    const app=read('src/js/app.js');
    const mounts=[...app.matchAll(/mountCompanion\((\{[^}]*\})\)/g)].map(m=>m[1].trim());
    assert.deepEqual(mounts,['{refreshObservation: syncAiObservation, settingsControl: withAiSettingsPanel(aiSettingsControl)}']);
    // The AI observation is wrapped so a failing projection can never alter the control path.
    assert.match(app,/function syncAiObservation[\s\S]*?try \{[\s\S]*?\} catch \{ \/\* AI is optional/);
    // Emergency stop is an ordinary engine stop with a distinct outcome label.
    assert.match(app,/const safetyStop = stopBtn\.dataset\.safetyStop === 'true';\s*delete stopBtn\.dataset\.safetyStop;\s*stopSession\(safetyStop \? "Emergency Stop" : "Stopped"\);/);
    const stop=app.slice(app.indexOf('function stopSession('));
    const body=stop.slice(0,stop.indexOf('\n}\n'));
    assert.ok(body.indexOf('dispatchHardware(0')>=0,'stopSession no longer zeroes hardware');
    assert.ok(body.indexOf('dispatchHardware(0')<body.indexOf('syncAiObservation'),'AI is notified before motors stop');
});

test('no agent command link is present in this build (see docs/fork/dev/AGENT_LINK_BOUNDARY.md)',()=>{
    assert.ok(!existsSync(path.join(root,'src/js/agent-api.js')),'agent-api.js arrived with a sync');
    assert.ok(!existsSync(path.join(root,'worker')),'Cloudflare worker arrived with a sync');
    assert.ok(!existsSync(path.join(root,'tools/edgeloop_openwebui.py')),'Open WebUI control tool arrived with a sync');
    for(const file of ['src/js/app.js','index.html','sw.js'])
        assert.ok(!/\/api\/agent|agentHttpToken|AgentRoom/.test(read(file)),`${file} contains agent link code`);
});

test('the service worker never caches AI, observer or loopback traffic',()=>{
    const sw=read('sw.js');
    assert.match(sw,/port === '8768' \|\| new URL\(request\.url\)\.pathname\.startsWith\('\/ai\/'\)\) return;/);
    assert.match(sw,/url\.origin !== self\.location\.origin && \['127\.0\.0\.1','localhost','\[::1\]'\]\.includes\(url\.hostname\)\) return;/);
    assert.match(sw,/pathname\.startsWith\('\/Character_Art\/'\)\) return;/);
    // Same-origin files revalidate, so a stale stylesheet never meets newer scripts.
    assert.match(sw,/url\.origin === self\.location\.origin && request\.mode !== 'navigate' \? new Request\(request, \{ cache: 'no-cache' \}\) : request;/);
    assert.match(sw,/fetch\(fresh\)/);
});

test('Bratty Tease and script mode project with experience-change events instead of failing closed',async()=>{
    const {Capture}=await import('../../src/js/ai/snapshot.js');
    const devices={simulated_hr:true,hr_ready:true,toy_ready:true,ble:false,handy:true,intiface:false,tcode:false,vacuglide:false};
    const s={sessionStatus:'RUNNING',sessionSeconds:30,teaseMode:'classic',activeMode:'classic',gameMode:null,sensorHr:90,effectiveMaxHr:140,
        edgeTriggerHr:133,lastHrTimestamp:1,edges:0,intensityValue:50,strokerSpeed:20,prostateSpeed:10,strokeMin:0,strokeMax:100,
        simEngaged:true,hrSignalState:'ok',hrNoContact:false,hrSignalPaused:false};
    const c=new Capture();c.project(s,devices);
    for(const mode of ['bratty','script']){
        Object.assign(s,{teaseMode:mode,activeMode:mode});
        const {snapshot,events}=c.project(s,devices);
        assert.equal(snapshot.experience,mode);assert.equal(snapshot.active_mode,mode);
        assert.deepEqual(events.map(e=>e.kind),['experience_changed']);
    }
    Object.assign(s,{teaseMode:'unknown-upstream-style',activeMode:'unknown-upstream-style'});
    assert.throws(()=>c.project(s,devices),/Unknown upstream state/);
});

test('pause reasons are bounded categories; an Edged stop is reported as its edge, not as a pause',async()=>{
    const {Capture}=await import('../../src/js/ai/snapshot.js');
    const devices={simulated_hr:true,hr_ready:true,toy_ready:true,ble:false,handy:true,intiface:false,tcode:false,vacuglide:false};
    const s={sessionStatus:'RUNNING',sessionSeconds:30,teaseMode:'classic',activeMode:'classic',gameMode:null,sensorHr:90,effectiveMaxHr:140,
        edgeTriggerHr:133,lastHrTimestamp:1,edges:0,pauses:0,intensityValue:50,strokerSpeed:20,prostateSpeed:10,strokeMin:0,strokeMax:100,
        simEngaged:true,hrSignalState:'ok',hrNoContact:false,hrSignalPaused:false,pauseReason:''};
    const c=new Capture();c.project(s,devices);
    // Upstream order: countManualEdge() syncs first, then pauseSession(null,'edged').
    s.edges=1;assert.deepEqual(c.project(s,devices).events.map(e=>e.kind),['edge']);
    Object.assign(s,{sessionStatus:'PAUSED',pauseReason:'edged'});
    let p=c.project(s,devices);assert.equal(p.snapshot.details.pause_reason,'edged');assert.deepEqual(p.events.map(e=>e.kind),[]);
    Object.assign(s,{sessionStatus:'RUNNING',pauseReason:''});
    p=c.project(s,devices);assert.equal(p.snapshot.details.pause_reason,null);assert.deepEqual(p.events.map(e=>e.kind),['session_resumed']);
    for(const [source,reason] of [['button','user'],['relube','relube'],['player','player'],['video','player'],['remote','remote'],
        ['hr-signal','hr_signal'],['handy-stop','device'],['intiface','device'],[['AA','BB','CC','DD','EE','FF'].join(':'),null],['__proto__',null]]){
        Object.assign(s,{sessionStatus:'PAUSED',pauseReason:source,pauses:s.pauses+1});
        p=c.project(s,devices);assert.equal(p.snapshot.details.pause_reason,reason,source);assert.ok(p.events.some(e=>e.kind==='pause'),source);
        Object.assign(s,{sessionStatus:'RUNNING',pauseReason:''});c.project(s,devices);
    }
});

test('a play-style change made by loading or clearing a funscript is labelled media once; every other change is a selection',async()=>{
    const {Capture}=await import('../../src/js/ai/snapshot.js');
    const devices={simulated_hr:true,hr_ready:true,toy_ready:false,ble:false,handy:false,intiface:false,tcode:false,vacuglide:false};
    const s={sessionStatus:'IDLE',sessionSeconds:0,teaseMode:'classic',activeMode:'classic',gameMode:null,sensorHr:90,effectiveMaxHr:140,
        edgeTriggerHr:133,lastHrTimestamp:1,edges:0,pauses:0,intensityValue:50,strokerSpeed:0,prostateSpeed:0,strokeMin:0,strokeMax:100,
        simEngaged:true,hrSignalState:'ok',hrNoContact:false,hrSignalPaused:false,pauseReason:''};
    const c=new Capture();assert.equal(c.project(s,devices).snapshot.details.selection_source,'selection');
    const step=(changes)=>{Object.assign(s,changes);const p=c.project(s,devices);return [p.snapshot.details.selection_source,p.events.map(e=>e.kind)];};
    // app.js onScript: the record is written before applyModeSelection('script').
    assert.deepEqual(step({mediaSelection:{experience:'script',goal:'tease'},teaseMode:'script',activeMode:'script'}),['media',['experience_changed']]);
    // A later participant selection is not taken for media, although the record is still on the state object.
    assert.deepEqual(step({teaseMode:'classic',activeMode:'classic'}),['selection',['experience_changed']]);
    assert.deepEqual(step({teaseMode:'script',activeMode:'script'}),['selection',['experience_changed']]);
    // A goal picked together with a media-caused change keeps media only if it matches the record exactly.
    assert.deepEqual(step({mediaSelection:{experience:'classic',goal:'tease'},teaseMode:'classic',activeMode:'oracle',gameMode:'oracle'}),['selection',['experience_changed','goal_changed']]);
    // Clearing the funscript restores the earlier style by itself.
    step({gameMode:null,activeMode:'script',teaseMode:'script'});
    assert.deepEqual(step({mediaSelection:{experience:'bratty',goal:'tease'},teaseMode:'bratty',activeMode:'bratty'}),['media',['experience_changed']]);
    // A record seen without a change (same style reloaded) is spent and cannot label a later selection.
    step({mediaSelection:{experience:'bratty',goal:'tease'}});
    step({teaseMode:'classic',activeMode:'classic'});
    assert.deepEqual(step({teaseMode:'bratty',activeMode:'bratty'}),['selection',['experience_changed']]);
});

test('the player hook only labels the change: it runs before upstream applies the same selection',()=>{
    const app=read('src/js/app.js');
    assert.match(app,/state\.mediaSelection = \{ experience: 'script', goal: 'tease' \};\n\s*applyModeSelection\('script'\);/);
    assert.match(app,/state\.mediaSelection = \{ experience: restored, goal: state\.gameMode \|\| 'tease' \};\n\s*applyModeSelection\(restored\);/);
    assert.equal([...app.matchAll(/mediaSelection/g)].length,2);
});

// AI Settings Control (docs/fork/dev/AI_SETTINGS_CONTROL.md): replaces the old "AI is strictly read-only" guard
// with the approved boundary. The AI layer forwards a request; the engine-side gate decides.
const settingsFiles=readdirSync(path.join(root,'src/js/ai-settings')).filter(f=>f.endsWith('.js')&&!f.endsWith('.test.js')).map(f=>'src/js/ai-settings/'+f);

test('the AI layer forwards settings requests only to the engine-side gate it was handed',()=>{
    const companion=read('src/js/ai/companion.js');
    assert.deepEqual([...new Set([...companion.matchAll(/settingsControl\??\.(\w+)/g)].map(m=>m[1]))].sort(),['chip','mountPanel','request','selectProfile','settings','subscribe']);
    assert.match(companion,/settingsControl\?\.mountPanel\?\.\(settingsSlot\)/);
    // character_builder (Character Builder editor results) is display data only; it carries no settings or engine command.
    assert.match(read('src/js/ai/connection.js'),/'settings_request','character_builder'\]\.includes\(m\.type\)\)this\.onMessage\(m\)/);
});

test('AI Settings modules import only the gate, the engine mode lists and session rules',()=>{
    for(const file of settingsFiles){
        const specifiers=[...read(file).matchAll(/import\s[^;]*?from\s*'([^']+)'/g)].map(m=>m[1]);
        for(const spec of specifiers)assert.ok(['./gate.js','./control.js','../engine.js','../session-rules.js'].includes(spec),`${file} imports ${spec}`);
        assert.ok(!/dispatchHardware|sendPeerCommand|navigator\.(bluetooth|serial|usb|hid)|fetch\(|WebSocket|localStorage/.test(read(file)),`${file} reaches hardware, network or storage`);
    }
});

test('the engine applies an AI change only through the on-page control handlers',()=>{
    const app=read('src/js/app.js');
    const start=app.indexOf('function applyAiSettingsChange(');
    const body=app.slice(start,app.indexOf('\n}\n',start));
    for(const forbidden of [/dispatchHardware/,/maxHr|minHr|dualMaxHr|edgeTriggerHr|effectiveMaxHr/,/speedSlowest|speedFastest|strokeMin|strokeMax/,
        /startOrResumeSession|resetBtn|sessionStatus\s*=/,/handy|intiface|tcode|vacuglide/i,/chosenTargetSeconds|duration/i])
        assert.ok(!forbidden.test(body),`applyAiSettingsChange matches ${forbidden}`);
    assert.match(body,/applyModeSelection\(change\.to\)/);
    assert.match(body,/pendingPauseReason = 'ai';\s*playPauseBtn\?\.click\(\);/);
    // Emergency stop revokes; only a user-started session clears it.
    assert.match(app,/stopSession\(safetyStop \? "Emergency Stop" : "Stopped"\);\s*if \(safetyStop\) aiSettingsControl\?\.revoke\(\);/);
    assert.equal([...app.matchAll(/aiSettingsControl\?\.newSession\(\)/g)].length,1);
    assert.match(app,/if \(started && fromIdle\) aiSettingsControl\?\.newSession\(\);/);
});

test('AI Settings Control is off by default',async()=>{
    const {AI_SETTINGS_DEFAULTS}=await import('../../src/js/ai-settings/gate.js');
    assert.equal(AI_SETTINGS_DEFAULTS.enabled,false);
});
