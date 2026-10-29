// SPDX-License-Identifier: AGPL-3.0-only
// Presentation only. No telemetry values, prompts, memory, audio or device imports.
import {CHARACTER_MANIFEST,EXPRESSIONS,ACTIVITIES,resolveArtwork} from './artwork-manifest.js';
export const SESSION_REACTIONS=Object.freeze({...CHARACTER_MANIFEST.presentation.session_reactions});
// Explicit self-description plus compound conversational tone cues; never
// isolated sentiment words, user feelings or physiological measurements.
const CUES={
    neutral:/\b(?:I settle back (?:comfortably|into a relaxed stance)|settles? back comfortably)\b/i,
    happy:/\b(?:I smile (?:warmly|brightly|genuinely)|smiles? (?:warmly|brightly|genuinely)|I'm delighted to (?:see|hear)|I(?:'m| am) (?:beaming(?! with excitement)|smiling (?:warmly|brightly)))\b/i,
    playful:/\b(?:I give you a playful wink|winks? playfully|I raise an eyebrow playfully)\b/i,
    flirty:/\b(?:I give you a flirtatious smile|smiles? flirtatiously|I twirl a strand of hair with a soft gaze)\b/i,
    mischievous:/\b(?:I (?:smirk slyly|grin mischievously)|smirks? slyly|grins? mischievously)\b/i,
    focused:/\b(?:I (?:study the checklist|examine (?:my|the) checklist|consider (?:that|this) carefully|adopt a focused expression)|examines? (?:her|my|the) checklist)\b/i,
    excited:/\b(?:I beam with excitement|beams? with excitement|I(?:'m| am) beaming with excitement|I can hardly contain my excitement)\b/i,
    surprised:/\b(?:I raise my eyebrows in surprise|raises? (?:her|my) eyebrows in surprise)\b/i,
    disappointed:/\b(?:I (?:frown in disappointment|give a small disappointed frown)|(?:my|her) shoulders slump in disappointment)\b/i,
    concerned:/\b(?:I frown with concern|frowns? with concern|I give you a concerned look)\b/i,
    proud:/\b(?:I smile proudly|smiles? proudly|I rest my hands on my hips with a proud smile)\b/i,
    comforting:/\b(?:I (?:offer a reassuring smile|give you a comforting smile|extend an open hand reassuringly)|offers? a reassuring smile)\b/i
};
// Compound conversational cues also work when the reply narrates no facial gesture.
// Each family includes a stance/context, never an isolated emotion word or BPM.
const TONE_CUES={
    neutral:/\b(?:we can (?:just )?sit (?:here )?quietly|let's take (?:our|a little) time)[\s\S]{0,90}\b(?:no rush|whenever you're ready)\b/i,
    happy:/\b(?:glad|delighted|wonderful|lovely)[\s\S]{0,45}\b(?:you're here|see you|hear from you|news|welcome)\b|\bthat(?:'s| is) (?:such )?(?:wonderful|great) news\b/i,
    playful:/\b(?:you cheeky (?:thing|rascal)|you're asking for trouble,? aren't you|I might tease you (?:a little|about that))\b/i,
    flirty:/\b(?:come|lean) a little closer,? (?:darling|sweetheart)\b|\byou know (?:just |exactly )?how to charm me\b|\byou're making it (?:very |so )?hard to behave\b/i,
    mischievous:/\bI(?:'ve| have) got a little secret (?:for you|up my sleeve)\b|\ba (?:little )?trick up my sleeve\b|\bI have a plan[\s\S]{0,35}\bnot telling you yet\b/i,
    focused:/\b(?:let's|we can|we should)[\s\S]{0,30}\b(?:work|look|take|break)[\s\S]{0,40}\b(?:step by step|one step at a time|each detail|the details carefully)\b/i,
    excited:/\b(?:can't wait|so excited|thrilled)[\s\S]{0,45}\b(?:begin(?:ning)?|start(?:ed|ing)?|try|see|show)\b/i,
    surprised:/\b(?:I didn't expect that|I did not expect that|that (?:really )?caught me off guard|well,? that was unexpected)\b/i,
    disappointed:/\b(?:I was hoping|I had hoped)[\s\S]{0,65}\b(?:letdown|shame|disappoint|not how|didn't|did not)\b|\bthat(?:'s| is) (?:a real|such a|a bit of a) (?:letdown|shame)\b/i,
    concerned:/\bI(?:'m| am) (?:a little |really )?(?:concerned|worried) (?:about|for)\b/i,
    proud:/\bI(?:'m| am) (?:so |really )?proud of (?:you|us|that)\b|\byou (?:really )?did it[\s\S]{0,35}\b(?:well done|bravo)\b/i,
    comforting:/\b(?:I'm here (?:for|with) you|I am here (?:for|with) you|you don't have to face this alone)[\s\S]{0,90}\b(?:take your time|no rush|one step|we'll|we will|not alone)\b/i
};
function affirmativeCue(pattern,text){
    for(const match of text.matchAll(new RegExp(pattern.source,'gi'))){
        const prefix=text.slice(Math.max(0,match.index-45),match.index).split(/[.!?;\n]/).at(-1);
        if(!/\b(?:not|never|isn't|wasn't|aren't|weren't|don't|doesn't|didn't|if|suppose|imagine|example)\b/i.test(prefix))return true;
    }
    return false;
}
export function classifyDialogue(text) {
    if(typeof text!=='string'||text.length>16000||/<think\b/i.test(text))return null;
    const safe=text.replace(/’/g,"'").replace(/```[\s\S]*?```/g,'').replace(/"[^"\n]*"|“[^”\n]*”/g,'').slice(0,4000);
    const tones=Object.entries(CUES).filter(([expression,pattern])=>affirmativeCue(pattern,safe)||affirmativeCue(TONE_CUES[expression],safe));
    return tones.length===1?tones[0][0]:null;
}
export class CharacterPresentationController {
    constructor(render,{now=()=>Date.now(),sessionReactions=SESSION_REACTIONS,cooldownMs=CHARACTER_MANIFEST.presentation.cooldown_ms,chatHoldMs=CHARACTER_MANIFEST.presentation.chat_hold_ms}={}) {
        Object.assign(this,{render,now,sessionReactions,cooldownMs,chatHoldMs});
        this.expressionSource='fallback';this.model=null;this.identity='generic';this.expression='neutral';this.activity='disconnected';this.connected=false;
        this.active=null;this.allowStarts=false;this.cancelled=new Set();this.seen=new Set();this.session=null;this.sequence=-1;
        this.chatUntil=0;this.lastReaction=-Infinity;this.previewState=null;this.emit();
    }
    emit(){this.render(this.previewState||{model:this.model,expression:this.expression,activity:this.activity,expressionSource:this.expressionSource});}
    bounded(set,value){set.add(value);if(set.size>128)set.delete(set.values().next().value);}
    select(model,history=[]) {
        this.cancel();const identity=resolveArtwork(model).id;
        if(identity!==this.identity){this.expression='neutral';this.expressionSource='fallback';}
        this.model=model;this.identity=identity;this.lastRequest=null;
        const last=history.filter(m=>m.role==='assistant').at(-1);
        const tone=last&&(EXPRESSIONS.includes(last.expression)?last.expression:classifyDialogue(last.content));if(tone){this.expression=tone;this.expressionSource=EXPRESSIONS.includes(last.expression)?'memory':'fallback';}
        this.activity=this.connected?'idle':'disconnected';this.chatUntil=this.now()+this.chatHoldMs;this.emit();
    }
    connection(connected){this.connected=Boolean(connected);if(!connected){this.cancel();this.session=null;this.sequence=-1;this.seen.clear();}this.activity=connected?'idle':'disconnected';this.emit();}
    userMessage(){if(!this.connected)return;this.allowStarts=true;this.activity='generating';this.chatUntil=this.now()+this.chatHoldMs;this.emit();}
    start(id,model=this.model){
        if(!this.connected||!this.allowStarts||model!==this.model||typeof id!=='string'||this.cancelled.has(id)){if(typeof id==='string')this.bounded(this.cancelled,id);return false;}
        this.lastRequest={id,model};this.active={id,model,expression:null};this.activity='generating';this.emit();return true;
    }
    expressionUpdate(id,expression,model=this.model){
        if(!this.connected||!this.active||this.active.id!==id||model!==this.model||this.active.model!==model||this.cancelled.has(id)||!EXPRESSIONS.includes(expression))return false;
        this.active.expression=expression;this.expression=expression;this.expressionSource='model';this.emit();return true;
    }
    complete(id,text,model=this.model,metadata=null){
        if(!this.connected||!this.active||this.active.id!==id||model!==this.model||this.active.model!==model||this.cancelled.has(id))return false;
        const intended=this.active.expression||(metadata&&EXPRESSIONS.includes(metadata.expression)?metadata.expression:null);
        const expression=intended||classifyDialogue(text);
        if(expression){this.expression=expression;this.expressionSource=intended?'model':'fallback';}else this.expressionSource='retained';
        this.active=null;this.allowStarts=false;this.activity='idle';this.chatUntil=this.now()+this.chatHoldMs;this.emit();return true;
    }
    cancel(){this.allowStarts=false;if(this.active)this.bounded(this.cancelled,this.active.id);this.active=null;this.activity=this.connected?'idle':'disconnected';this.emit();}
    // Only server-acknowledged F2.3 observed changes; no HR/speed input is read.
    sessionEvents(events,sequence,session){
        if(!this.connected||!Number.isSafeInteger(sequence)||!Array.isArray(events)||events.length>16||typeof session!=='string')return;
        if(this.session!==session){this.session=session;this.sequence=-1;this.seen.clear();}
        if(sequence<=this.sequence)return;this.sequence=sequence;
        for(const event of events){
            if(typeof event.id!=='string'||event.session_id!==session||this.seen.has(event.id))continue;
            this.bounded(this.seen,event.id);
            if(event.kind==='stop'&&event.preserve_reaction!==true)this.cancel();
        }
    }
    // Voice activities are explicit indicators only; never inferred or animated.
    setActivity(activity){if(ACTIVITIES.includes(activity)){this.activity=activity;this.emit();}}
    preview(value=null){this.previewState=value;this.emit();}
}
