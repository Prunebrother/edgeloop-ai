// SPDX-License-Identifier: AGPL-3.0-only
// Read-only projection. Never import a controller or expose keys/hidden targets/history.
const modes=['classic','finisher','milker','shortener','headplay','ultimate','ruin'];
const goals=['tease','survival','edgetrain','oracle','calibrate','nnn'];
const integer=(n,min,max)=>{if(!Number.isFinite(n)||n<min||n>max)throw new Error('Invalid observation');return Math.round(n);};
const optional=(n,min,max)=>Number.isFinite(n)&&n>=min&&n<=max?Math.round(n):null;
export class Capture {
    constructor({uuid=()=>crypto.randomUUID(),now=()=>Date.now()}={}) {
        this.uuid=uuid;this.now=now;this.sessionId=uuid();this.previous=null;this.samples=[];
        this.lastHrTimestamp=null;this.verifiedReading=null;this.source=null;this.segmentAt=this.now();
    }
    project(state,devices,settings={}) {
        if(!modes.includes(state.teaseMode)||!goals.includes(state.gameMode||'tease')||
            ![...modes,'survival','oracle','edgetrain','calibrate'].includes(state.activeMode)||
            !['IDLE','RUNNING','PAUSED','RAMPDOWN'].includes(state.sessionStatus))throw new Error('Unknown upstream state');
        const now=this.now(),p=this.previous;
        if(p&&((p.status==='IDLE'&&state.sessionStatus==='RUNNING')||
            (state.sessionStatus!=='IDLE'&&state.sessionSeconds<p.seconds))){this.sessionId=this.uuid();this.samples=[];this.segmentAt=now;}
        const source=devices.simulated_hr?'simulator':devices.ble?'ble':'unavailable';
        const stamp=optional(state.lastHrTimestamp,0,now);
        if(source!==this.source){this.samples=[];this.verifiedReading=null;this.lastHrTimestamp=stamp;this.source=source;this.segmentAt=now;}
        // A BLE connection/watchdog reset is not a sample. A subsequent valid
        // reading timestamp establishes measurement provenance conservatively.
        if(source==='simulator')this.verifiedReading=stamp;
        else if(source==='ble'&&stamp!==this.lastHrTimestamp){this.verifiedReading=stamp;this.lastHrTimestamp=stamp;}
        const signal=!devices.hr_ready?'missing':source==='simulator'?'ok':state.hrSignalState;
        const valid=devices.hr_ready&&optional(state.sensorHr,35,250)!==null;
        const hr=valid&&(source==='simulator'||this.verifiedReading!==null)?Math.round(state.sensorHr):null;
        if(signal!=='ok'||state.hrNoContact||source==='unavailable')this.samples=[];
        else if(hr!==null&&this.verifiedReading!==null&&this.verifiedReading>=this.segmentAt&&this.samples.at(-1)?.stamp!==this.verifiedReading){
            if(this.samples.length&&this.verifiedReading-this.samples.at(-1).stamp>5000)this.samples=[];
            this.samples.push({stamp:this.verifiedReading,bpm:hr});this.samples=this.samples.slice(-12);
        }
        this.samples=this.samples.filter(s=>now-s.stamp<=15000);
        let trend='unknown';
        if(this.samples.length>=4&&this.samples.at(-1).stamp-this.samples[0].stamp>=3000){
            const values=this.samples.map(s=>s.bpm),delta=values.at(-1)-values[0];
            const differences=values.slice(1).map((v,i)=>v-values[i]);
            if(delta>=3&&differences.every(d=>d>=0))trend='rising';
            else if(delta<=-3&&differences.every(d=>d<=0))trend='falling';
            else if(Math.max(...values)-Math.min(...values)<=2)trend='steady';
        }
        const safety={signal,no_contact:Boolean(state.hrNoContact),watchdog_paused:Boolean(state.hrSignalPaused),
            fault:state.hrNoContact?'no_contact':signal==='stale'?'signal_lost':!devices.toy_ready?'device_unready':'none'};
        const warmup=Number.isFinite(settings.warmup_minutes)?Math.max(0,settings.warmup_minutes)*60:null;
        const elapsed=Math.max(0,state.sessionSeconds-(state.warmupOriginSeconds||0));
        const warmupActive=warmup===null?null:state.sessionStatus==='RUNNING'&&warmup>0&&elapsed<warmup;
        const snapshot={session_id:this.sessionId,status:state.sessionStatus,seconds:integer(state.sessionSeconds,0,31536000),
            experience:state.teaseMode,active_mode:state.activeMode,goal:state.gameMode||'tease',hr,
            effective_max:integer(state.effectiveMaxHr,30,400),pullback:optional(state.edgeTriggerHr,1,400),
            trend,edges:integer(state.edges,0,1000000),intensity:integer(50+state.intensityValue,50,150),
            movement:{primary:integer(state.strokerSpeed,0,100),secondary:integer(state.prostateSpeed,0,100),
                stroke_min:integer(state.strokeMin,0,100),stroke_max:integer(state.strokeMax,0,100)},
            devices:Object.fromEntries(['simulated_hr','hr_ready','toy_ready','ble','handy','intiface','tcode','vacuglide'].map(k=>[k,Boolean(devices[k])])),safety,
            details:{captured_at_ms:Math.round(now),hr_recorded_at_ms:hr===null?null:this.verifiedReading,
                hr_live:typeof settings.hr_live==='boolean'?settings.hr_live:null,
                resting_bpm:optional(settings.resting_bpm,30,250),single_max_bpm:optional(settings.single_max_bpm,30,250),dual_max_bpm:optional(settings.dual_max_bpm,30,250),
                pauses:optional(state.pauses,0,1000000),calibration_pass:['primary','dual'].includes(state.calibrationPass)?state.calibrationPass:'none',
                warmup_active:warmupActive,warmup_remaining_seconds:warmupActive?Math.ceil(warmup-elapsed):null,
                learning_release_count:optional(settings.learning_release_count,0,1000000),
                settle_outcome:state.settleOutcome==='Premature Release'?'premature_release':null,
                terminal_outcome:({'Calibration':'calibration_completed','Premature Release':'premature_release','Survival Restart':'survival_restart','Stopped':'manual_stop','Cancelled':'cancelled'})[settings.terminal_outcome]|| (settings.terminal_outcome?'other_stop':null),
                ease_down_seconds:optional(state.settleSecondsLeft,0,3600),
                rampdown_seconds:state.sessionStatus==='RAMPDOWN'||state.resumeStatus==='RAMPDOWN'?optional(state.rampdownSecondsLeft,0,3600):null}};
        const kinds=[];
        if(p){
            if(snapshot.details.terminal_outcome==='calibration_completed'&&p.status!=='IDLE'&&snapshot.status==='IDLE')kinds.push('completion_accepted');
            if(snapshot.details.terminal_outcome==='survival_restart'&&p.details?.terminal_outcome!=='survival_restart'&&p.status!=='IDLE'&&p.active_mode==='survival')kinds.push('completion_accepted');
            if(snapshot.status!==p.status){
                if(snapshot.status==='IDLE')kinds.push('stop');
                else if(snapshot.status==='PAUSED')kinds.push('pause');
                else if(p.status==='IDLE')kinds.push('session_started');
                else if(p.status==='PAUSED')kinds.push('session_resumed');
            }
            const releases=snapshot.details.learning_release_count,prior=p.details?.learning_release_count;
            if(snapshot.session_id===p.session_id&&Number.isInteger(releases)&&Number.isInteger(prior)&&releases>prior&&
                ['RUNNING','PAUSED'].includes(p.status)&&!['survival','calibrate'].includes(p.active_mode)&&
                (snapshot.details.settle_outcome==='premature_release'||snapshot.status==='IDLE'))kinds.push('came_early');
            if(snapshot.session_id===p.session_id&&snapshot.edges>p.edges)kinds.push('edge');
            if(snapshot.experience!==p.experience)kinds.push('experience_changed');
            if(snapshot.goal!==p.goal)kinds.push('goal_changed');
            if(snapshot.intensity!==p.intensity)kinds.push('intensity_changed');
            if(snapshot.details.single_max_bpm!==p.details?.single_max_bpm||snapshot.details.dual_max_bpm!==p.details?.dual_max_bpm)kinds.push('threshold_changed');
            if(signal!==p.safety.signal)kinds.push(signal==='stale'?'signal_lost':p.safety.signal==='stale'?'signal_restored':null);
            if(safety.no_contact&&!p.safety.no_contact)kinds.push('no_contact');
            if(JSON.stringify(snapshot.devices)!==JSON.stringify(p.devices))kinds.push('device_changed');
            if(snapshot.session_id===p.session_id&&snapshot.seconds>=300&&Math.floor(snapshot.seconds/300)>Math.floor(p.seconds/300))kinds.push('milestone');
        }
        this.previous=snapshot;
        return {snapshot,events:kinds.filter(Boolean).map(kind=>({id:this.uuid(),kind,at_ms:Math.round(now),session_id:this.sessionId}))};
    }
}
