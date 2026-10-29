// SPDX-License-Identifier: AGPL-3.0-only
// Supplemental lexical factual coverage, not an LLM judge or a replacement for strict scores.
const actions=[['tend','tending','care','caring','nurture','nurturing','cultivate','cultivating','grow','growing'],['restore','restoring','restoration','repair','repairing','refurbish','refurbishing'],['press','pressing','dry','drying','preserve','preserving'],['paint','painting'],['sketch','sketching','draw','drawing'],['play','playing'],['read','reading'],['bake','baking'],['collect','collecting'],['watch','watching']];
const stop=new Set('a an the to of in on for and my your is are hobby hobbies personal old vintage overgrown little really carefully spare free time'.split(' '));
function stem(word){
 const forms=[word];
 if(word.endsWith('ies')||word.endsWith('ied'))forms.push(word.slice(0,-3)+'y');
 if(word.endsWith('s')&&word.length>3)forms.push(word.slice(0,-1));
 if(word.endsWith('ing')&&word.length>5){const root=word.slice(0,-3);forms.push(root,root+'e');if(root.at(-1)===root.at(-2))forms.push(root.slice(0,-1));}
 if(word.endsWith('ed')&&word.length>4)forms.push(word.slice(0,-2),word.slice(0,-1));
 const family=actions.find(values=>forms.some(form=>values.includes(form)));
 return family?family[0]:forms.length>1?forms[1]:word;
}
function tokens(text){return (text.toLowerCase().match(/[a-z]+|\d+/g)||[]).map(stem);}
export function factualCoverage(expected,answer,kind='fact'){
 if(kind==='identifier'){
  const code=expected.toUpperCase(),observed=answer.match(/\b[a-z][a-z0-9]+[-_]\d+[a-z0-9_-]*\b/gi)||[];
  return {covered:observed.some(v=>v.toUpperCase()===code),method:'case-insensitive exact identifier',unsupported_addition_candidates:observed.filter(v=>v.toUpperCase()!==code)};
 }
 const expectedTokens=tokens(expected).filter(v=>!stop.has(v)),answerTokens=new Set(tokens(answer)),groups=[];
 for(const token of expectedTokens){const family=actions.find(values=>values.includes(token));if(family){if(!groups.some(g=>g.name===family[0]))groups.push({name:family[0],values:family.map(stem)});}else groups.push({name:token,values:[token]});}
 const matched=groups.filter(g=>g.values.some(v=>answerTokens.has(v))).map(g=>g.name),missing=groups.filter(g=>!matched.includes(g.name)).map(g=>g.name);
 const uncertain=/\b(?:cannot recall|can't recall|not sure|unknown|unavailable|do not know|don't know)\b/i.test(answer);
 const negated=answer.split(/[.!?;]/).some(clause=>/\b(?:not (?!only\b|just\b)|never\b|no longer\b|don.t\b|do not\b)/i.test(clause)&&groups.every(g=>g.values.some(v=>tokens(clause).includes(v))));
 return {covered:groups.length>0&&missing.length===0&&!uncertain&&!negated,negated,method:'lexical source concepts; optional modifiers omitted; not an entailment judge',matched,missing,uncertain};
}
export function unsupportedAdditions(expected,answer,evidence,kind='fact'){
 const result=[];const type=expected.match(/^[A-Z]+-\d+$/)?'identifier':kind;
 if(type==='identifier'){const additions=factualCoverage(expected,answer,type).unsupported_addition_candidates.map(value=>({kind:'replacement_identifier',value,review_required:true}));for(const m of answer.matchAll(/\b(?:identifier|code)\s+(?:(?:is|was)\s+)?(\d+)\b/gi))additions.push({kind:'replacement_identifier',value:m[1],review_required:true});return additions;}
 if(!answer.trim()||/\b(?:cannot recall|can't recall|not sure|unknown|do not know|don't know)\b/i.test(answer))return result;
 if(!factualCoverage(expected,answer).covered)result.push({kind:'unsupported_or_incomplete_'+type+'_answer',review_required:true});
 // Additional explicit personal pursuits require source support too. These checks
 // deliberately report candidates: they do not judge metaphors or every biographical claim.
 const clauses=answer.match(/\b(?:I (?:also )?(?:collect|paint|sketch|play|restore|grow|tend|bake|read)|my (?:other |real )?hobby is)\b[^.!?;]*/gi)||[];
 for(const clause of clauses){
  const objects=tokens(clause).filter(t=>!stop.has(t)&&!['also','other','real','i'].includes(t)&&!actions.some(a=>a.map(stem).includes(t)));
  const known=new Set(tokens(evidence||''));
  if(objects.length&&objects.some(t=>!known.has(t))&&!factualCoverage(expected,clause).covered)result.push({kind:'additional_personal_activity',claim:clause.slice(0,200),review_required:true});
 }
 return result;
}
export function memorySnapshot(stage,audit,{expected,sourceReply='',sourceError=null,previous=null,sourceSnapshot=null,sourceSpeaker='assistant'}={}){
 const n=audit.state.narrative||{},d=audit.state.context_intelligence||{},recall=d.narrative_recall||{};
 const facts=(n.facts||[]).slice(0,16).map(r=>Object.fromEntries(['id','slot','category','status','speaker','source','model_scope','epoch','text','value','cue','reason','importance'].filter(k=>r[k]!==undefined).map(k=>[k,r[k]])));
 const relevant=facts.filter(r=>r.status==='active'&&r.speaker===sourceSpeaker&&factualCoverage(expected,r.text).covered);
 const extraction=(audit.last_extraction?.candidates||[]).slice(0,16);
 const previousIds=previous?.target_fact_ids||previous?.hobby_fact_ids||[],source=sourceSnapshot||previous;
 const sourceEstablished=sourceReply?factualCoverage(expected,sourceReply).covered:source?.source_established??null;
 const extracted=extraction.some(r=>r.speaker===sourceSpeaker&&factualCoverage(expected,r.text).covered);
 let outcome='stored';
 if(stage==='after_establishment'&&!sourceEstablished)outcome='never_established';
 else if(stage==='after_establishment'&&!relevant.length&&audit.last_extraction?.source_truncated)outcome='diagnostic_truncated';
 else if(stage==='after_establishment'&&!relevant.length)outcome=extracted?'evicted_on_merge':'missed_during_extraction';
 else if(previousIds.length&&!relevant.length)outcome='evicted';
 else if(stage!=='after_establishment'&&!relevant.length)outcome=previous?.outcome||source?.outcome||'no_stored_evidence';
 else if(stage==='at_recall'){
  const ids=relevant.map(r=>r.id),selected=recall.selected_fact_ids||[],matched=recall.matched_fact_ids||[];
  outcome=ids.some(id=>selected.includes(id))?'selected':ids.some(id=>matched.includes(id))?((d.memory_decisions||[]).some(decision=>ids.includes(decision.id)&&decision.reason==='budget')?'excluded_by_budget':'excluded_by_context'):'unmatched';
 }
 return {stage,outcome,source_error:sourceError,curator:audit.state.memory_curator,source_established:sourceEstablished,source_reply:sourceReply.slice(0,4096),source_reply_truncated:sourceReply.length>4096,model:audit.state.model,model_scope:n.model_scope,epoch:n.epoch,revision:audit.state.narrative_revision,fact_count:facts.length,target_fact_ids:relevant.map(r=>r.id),hobby_fact_ids:relevant.map(r=>r.id),facts,storage_decisions:(n.fact_updates||[]).slice(-8),last_extraction:stage==='after_establishment'?audit.last_extraction:undefined,recall,decisions:(d.memory_decisions||[]).slice(0,16),budget:d.budget,omissions:d.omissions};
}
