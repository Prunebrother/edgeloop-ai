// SPDX-License-Identifier: AGPL-3.0-only
// Read-only projection. Never import a controller or expose keys/hidden targets/history.
const modes=['classic','finisher','milker','shortener','headplay','ultimate','bratty','ruin','script'];
const goals=['tease','survival','edgetrain','oracle','calibrate','nnn'];
const integer=(n,min,max)=>{if(!Number.isFinite(n)||n<min||n>max)throw new Error('Invalid observation');return Math.round(n);};
const optional=(n,min,max)=>Number.isFinite(n)&&n>=min&&n<=max?Math.round(n):null;
// Bounded categories for the engine's state.pauseReason (upstream PAUSE_REASONS); unknown sources stay null.
const pauseReasons={button:'user',ai:'ai',edged:'edged',relube:'relube',player:'player',video:'player','beat-sync':'player',remote:'remote',
    'hr-signal':'hr_signal','hr-link':'hr_signal',handy:'device','handy-stop':'device',vacuglide:'device',intiface:'device',tcode:'device',device:'device'};
export class Capture {
    constructor({uuid=()=>crypto.randomUUID(),now=()=>Date.now()}={}) {
        this.uuid=uuid;this.now=now;this.sessionId=uuid();this.previous=null;this.samples=[];
        this.lastHrTimestamp=null;this.verifiedReading=null;this.source=null;this.segmentAt=this.now();this.selectionSource='selection';this.mediaSeen=null;this.intensitySource='user';
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
        // A play-style/goal change made by the player itself (loading or clearing a funscript)
        // is labelled 'media' once; any other transition is the participant's selection.
        // The record is set in the same task as the change, so it counts only for the projection that first sees it.
        const experience=state.teaseMode,goal=state.gameMode||'tease',media=state.mediaSelection,fresh=Boolean(media)&&media!==this.mediaSeen;
        this.mediaSeen=media??null;
        // AI Settings Control marks the projection taken while it applies a change; the label stays until the next change.
        const ai=settings.ai_settings&&typeof settings.ai_settings==='object'?settings.ai_settings:null;
        const aiApplying=typeof ai?.applying_id==='string';
        if(p&&(experience!==p.experience||goal!==p.goal))
            this.selectionSource=aiApplying?'ai':fresh&&media.experience===experience&&media.goal===goal?'media':'selection';
        const intensity=integer(50+state.intensityValue,50,150);
        if(p&&intensity!==p.intensity)this.intensitySource=aiApplying?'ai':'user';
        const snapshot={session_id:this.sessionId,status:state.sessionStatus,seconds:integer(state.sessionSeconds,0,31536000),
            experience:state.teaseMode,active_mode:state.activeMode,goal:state.gameMode||'tease',hr,
            effective_max:integer(state.effectiveMaxHr,30,400),pullback:optional(state.edgeTriggerHr,1,400),
            trend,edges:integer(state.edges,0,1000000),intensity,
            movement:{primary:integer(state.strokerSpeed,0,100),secondary:integer(state.prostateSpeed,0,100),
                stroke_min:integer(state.strokeMin,0,100),stroke_max:integer(state.strokeMax,0,100)},
            devices:Object.fromEntries(['simulated_hr','hr_ready','toy_ready','ble','handy','intiface','tcode','vacuglide'].map(k=>[k,Boolean(devices[k])])),safety,
            details:{...(state.playerObservation?{player:Object.fromEntries(['instance_id','opened','selected','started','workspace_open','has_video','playing','title','title_source'].map(k=>[k,state.playerObservation[k]]))}:{}),captured_at_ms:Math.round(now),selection_source:this.selectionSource||'selection',intensity_source:this.intensitySource,
                endgame:['orgasm','rampdown','denial'].includes(settings.endgame)?settings.endgame:null,
                orgasm_mode:typeof settings.orgasm_mode==='boolean'?settings.orgasm_mode:null,
                ai_settings:ai?{enabled:Boolean(ai.enabled),revoked:Boolean(ai.revoked),applied:optional(ai.applied,0,1000000)??0,
                    last_id:typeof ai.last_id==='string'?ai.last_id.slice(0,64):null,last_setting:typeof ai.last_setting==='string'?ai.last_setting.slice(0,32):null,
                    pacing:['never','rarely','sometimes','often'].includes(ai.pacing)?ai.pacing:'sometimes',own_ready:Boolean(ai.own_ready),
                    recovery_seconds:optional(ai.recovery_seconds,30,300)??90,round_rest_seconds:optional(ai.round_rest_seconds,0,600)??180}:null,hr_recorded_at_ms:hr===null?null:this.verifiedReading,
                hr_live:typeof settings.hr_live==='boolean'?settings.hr_live:null,
                resting_bpm:optional(settings.resting_bpm,30,250),single_max_bpm:optional(settings.single_max_bpm,30,250),dual_max_bpm:optional(settings.dual_max_bpm,30,250),
                pauses:optional(state.pauses,0,1000000),
                pause_reason:state.sessionStatus==='PAUSED'&&Object.hasOwn(pauseReasons,state.pauseReason)?pauseReasons[state.pauseReason]:null,calibration_pass:['primary','dual'].includes(state.calibrationPass)?state.calibrationPass:'none',
                warmup_active:warmupActive,warmup_remaining_seconds:warmupActive?Math.ceil(warmup-elapsed):null,
                completion_reported:Boolean(settings.completion_reported),
                orgasm_count:optional(settings.orgasm_count,0,1000)??0,last_orgasm_seconds:optional(settings.last_orgasm_seconds,0,31536000),
                learning_release_count:optional(settings.learning_release_count,0,1000000),
                settle_outcome:state.settleOutcome==='Premature Release'?'premature_release':null,
                terminal_outcome:({'Calibration':'calibration_completed','Premature Release':'premature_release','Survival Restart':'survival_restart','Stopped':'manual_stop','Cancelled':'cancelled','Emergency Stop':'safety_stop'})[settings.terminal_outcome]|| (settings.terminal_outcome?'other_stop':null),
                ease_down_seconds:optional(state.settleSecondsLeft,0,3600),
                rampdown_seconds:state.sessionStatus==='RAMPDOWN'||state.resumeStatus==='RAMPDOWN'?optional(state.rampdownSecondsLeft,0,3600):null}};
        const kinds=[];
        if(p){
            if(snapshot.details.terminal_outcome==='calibration_completed'&&p.status!=='IDLE'&&snapshot.status==='IDLE')kinds.push('completion_accepted');
            if(snapshot.details.terminal_outcome==='survival_restart'&&p.details?.terminal_outcome!=='survival_restart'&&p.status!=='IDLE'&&p.active_mode==='survival')kinds.push('completion_accepted');
            if(snapshot.status!==p.status){
                if(snapshot.status==='IDLE')kinds.push('stop');
                // An Edged stop is reported as its edge, not as an ordinary pause.
                else if(snapshot.status==='PAUSED'){if(snapshot.details.pause_reason!=='edged')kinds.push('pause');}
                else if(p.status==='IDLE')kinds.push('session_started');
                else if(p.status==='PAUSED')kinds.push('session_resumed');
            }
            const releases=snapshot.details.learning_release_count,prior=p.details?.learning_release_count;
            if(snapshot.session_id===p.session_id&&Number.isInteger(releases)&&Number.isInteger(prior)&&releases>prior&&
                ['RUNNING','PAUSED'].includes(p.status)&&!['survival','calibrate'].includes(p.active_mode)&&
                (snapshot.details.settle_outcome==='premature_release'||snapshot.status==='IDLE'))kinds.push('came_early');
            if(snapshot.session_id===p.session_id&&snapshot.details.orgasm_count>(p.details?.orgasm_count??0)&&!kinds.includes('completion_accepted'))kinds.push('orgasm_reported');
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
        const before=p?.details?.player,after=snapshot.details.player;
        if(before&&after&&before.instance_id===after.instance_id){
            if(after.opened>before.opened&&after.workspace_open)kinds.push('player_opened');
            if(after.selected>before.selected&&after.has_video)kinds.push('video_selected');
            if(after.started>before.started&&after.has_video&&after.playing)kinds.push('video_started');
        }
        this.previous=snapshot;
        return {snapshot,events:kinds.filter(Boolean).map(kind=>({id:this.uuid(),kind,at_ms:Math.round(now),session_id:this.sessionId}))};
    }
}
