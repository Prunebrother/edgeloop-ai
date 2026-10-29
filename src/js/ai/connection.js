// SPDX-License-Identifier: AGPL-3.0-only
// Client sends observations/chat only. Server replies never dispatch controls.
export class ReadOnlyConnection {
    constructor({WebSocketImpl=globalThis.WebSocket,uuid=()=>crypto.randomUUID(),now=()=>Date.now(),
        schedule=(fn,ms)=>setTimeout(fn,ms),cancel=id=>clearTimeout(id),onMessage=()=>{},onStatus=()=>{}}={}) {
        Object.assign(this,{WebSocketImpl,uuid,now,schedule,cancel,onMessage,onStatus});
        this.browserId=uuid();this.enabled=false;this.socket=null;this.epoch=null;this.latest=null;
        this.pendingEvents=new Map();this.lastSent=-Infinity;this.sequence=0;this.retry=0;this.timer=null;this.flushTimer=null;
    }
    connect(url,token) {
        const parsed=new URL(url);
        if(!['ws:','wss:'].includes(parsed.protocol)||!['127.0.0.1','localhost'].includes(parsed.hostname)||
            parsed.username||parsed.password||parsed.search||parsed.hash||parsed.pathname!=='/observe'||token.length<32||token.length>128)
            throw new Error('Use a localhost /observe URL and a valid pairing token');
        this.disconnect();this.superseded=false;this.url=parsed.href;this.token=token;this.enabled=true;this.open();
    }
    open() {
        if(!this.enabled)return;
        const socket=new this.WebSocketImpl(this.url);this.socket=socket;this.epoch=null;this.sequence=0;
        this.pendingEvents.clear();this.onStatus('Connecting (read-only)');
        socket.onopen=()=>{if(this.socket===socket)socket.send(JSON.stringify({version:1,type:'auth',token:this.token,browser_id:this.browserId}));};
        socket.onmessage=e=>{
            if(this.socket!==socket||typeof e.data!=='string'||e.data.length>65536)return;
            let m;try{m=JSON.parse(e.data);}catch{return;}
            if(m.type==='ready'&&m.version===1&&m.read_only===true) {
                this.epoch=m.epoch;this.retry=0;this.pendingEvents.clear();this.lastSent=-Infinity;
                this.onStatus('Connected · read-only · no AI controls');this.flush();
                this.send({version:1,type:'list_models'});
            } else if(['ai_diagnostics','response_expression','models','model_selected','response_start','response_delta','speech','speech_cancel','conversation_error',
                'session_journal','character_state','character_menu_error','narrative_reset','response_suppressed','response_cancel','observation_ack','telemetry_status','ai_error','protocol_error'].includes(m.type))this.onMessage(m);
            else if(m.type==='resync_required')socket.close();
            // Unrecognized output, including command/action objects, is ignored.
        };
        socket.onerror=()=>this.onStatus('AI unavailable; EdgeLoop continues');
        socket.onclose=e=>{
            if(this.socket!==socket)return;
            this.socket=null;this.epoch=null;this.pendingEvents.clear();
            this.onStatus('AI disconnected; EdgeLoop continues');
            if(e.code===4001){this.enabled=false;this.token='';this.superseded=true;this.onStatus('AI connected in another EdgeLoop tab');return;}
            if(e.code===1008){this.enabled=false;this.token='';return;}
            if(this.enabled)this.timer=this.schedule(()=>this.open(),Math.min(1000*2**this.retry++,10000));
        };
    }
    observe({snapshot,events}) {
        const followsTerminal=Boolean(this.latest?.details?.terminal_outcome&&snapshot.status==='IDLE');
        this.latest=snapshot;
        if(!this.enabled||!this.epoch)return;
        for(const e of events){this.pendingEvents.set(e.kind,e);if(this.pendingEvents.size>16)this.pendingEvents.delete(this.pendingEvents.keys().next().value);}
        if(followsTerminal||snapshot.details?.terminal_outcome||events.some(e=>['stop','pause','signal_lost','came_early','completion_accepted'].includes(e.kind)))this.flush(true);
        else if(!this.flushTimer)this.flushTimer=this.schedule(()=>{this.flushTimer=null;this.flush();},Math.max(0,1000-(this.now()-this.lastSent)));
    }
    flush(urgent=false) {
        if(!this.latest||!this.epoch||!this.socket||this.socket.readyState!==1)return;
        if(this.socket.bufferedAmount>32768){this.pendingEvents.clear();this.socket.close();return;}
        if(!urgent&&this.now()-this.lastSent<1000)return;
        const message={version:1,type:'observation',epoch:this.epoch,sequence:this.sequence++,snapshot:this.latest,events:[...this.pendingEvents.values()].sort((a,b)=>(a.at_ms??0)-(b.at_ms??0))};
        this.pendingEvents.clear();this.lastSent=this.now();this.send(message);
    }
    send(message) {
        if(!this.epoch||!this.socket||this.socket.readyState!==1)return false;
        const raw=JSON.stringify(message);if(raw.length>16384)return false;
        this.socket.send(raw);return true;
    }
    disconnect() {
        this.enabled=false;this.token='';this.epoch=null;this.pendingEvents.clear();
        if(this.timer)this.cancel(this.timer);if(this.flushTimer)this.cancel(this.flushTimer);
        this.timer=this.flushTimer=null;
        const socket=this.socket;this.socket=null;if(socket)socket.close();
        this.onStatus('AI disabled; EdgeLoop controls remain independent');
    }
}

// Presentation freshness only; source is the existing original-engine projection.
export function reactionMatchesLatest(scope,snapshot){
    if(!scope)return true;
    return Boolean(snapshot&&['session_id','experience','goal'].every(key=>typeof scope[key]==='string'&&scope[key]===snapshot[key]));
}
