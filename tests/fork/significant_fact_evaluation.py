# SPDX-License-Identifier: AGPL-3.0-only
"""Matched CPU replay of diverse significant facts; never generated-answer accuracy."""
import argparse,json,subprocess,sys,types,time,statistics
from pathlib import Path
from companion_ai.narrative import NarrativeMemory
from companion_ai.context_compiler import ContextCompiler
from companion_ai.models import AIConfig
from tests.ai.test_hobby_recall import CASES as ACTIVITIES,ESTABLISH
from tests.ai.test_significant_facts import CASES,MODELS
from tests.fork.context_retention_fixture import fixture
ROOT=Path(__file__).resolve().parents[2]

def frozen(revision):
 modules={}
 for name in ('narrative_facts','narrative','context_compiler'):
  full='companion_ai._fact_replay_'+revision+'_'+name;module=types.ModuleType(full);module.__package__='companion_ai';sys.modules[full]=module
  source=(ROOT/'tests/fixtures/historical/significant'/(name+'.py')).read_text()
  for dependency in ('narrative_facts','narrative'):source=source.replace('from .'+dependency+' import','from ._fact_replay_'+revision+'_'+dependency+' import')
  exec(compile(source,'<fact-replay-'+revision+'-'+name+'>','exec'),module.__dict__);modules[name]=module
 return modules

def evaluate():
 old=frozen('source_fixture');rows=[]
 scenarios=[(model,speaker,source,question,value,correction,replacement,'diverse') for model in MODELS for speaker,source,question,value,correction,replacement in CASES]
 scenarios.extend((model,'assistant',reply,'What is your hobby?',hobby,'Actually, your hobby is sketching cityscapes.','sketching cityscapes','activity') for model,hobby,reply in ACTIVITIES)
 for model,speaker,source,question,value,correction,replacement,kind in scenarios:
  for arm,nclass,cclass in [('checkpoint_B',old['narrative'].NarrativeMemory,old['context_compiler'].ContextCompiler),('fixed_B',NarrativeMemory,ContextCompiler)]:
   n=nclass();n.activate(model,'synthetic')
   prompt=source if speaker=='user' else ESTABLISH.format(hobby=value) if kind=='activity' else 'Tell me something established.'
   n.accepted(prompt,source if speaker=='assistant' else 'Understood.',True)
   original=[r['id'] for r in n.state['facts'] if r['text']==source]
   summary,history,native=fixture(model)
   for stage in ('after_establishment','after_detours','after_correction'):
    if stage=='after_correction':
     if not correction:continue
     n.accepted(correction,'Understood.',True)
    if stage=='after_detours':
     for i in range(40):n.accepted(f'A visitor leaves parcel number {i} on the table.',f"I'll leave that parcel unresolved for a moment in room {i}.",True)
    current=summary|{'narrative_context':n.context(),'narrative_scope':[model]};times=[]
    for _ in range(10):
     start=time.perf_counter();messages,_,d=cclass().compile(current,question,history,AIConfig(model=model+':latest'),reserve_characters=len(native));times.append((time.perf_counter()-start)*1000)
    selected=set(d['narrative_recall']['selected_fact_ids']);matched=set(d['narrative_recall']['matched_fact_ids']);expected=correction if stage=='after_correction' else source
    correct_ids={r['id'] for r in n.state['facts'] if r['text']==expected and r['status']=='active'}
    present=[r for r in n.state['facts'] if r['text']==expected]
    outcome='selected' if correct_ids&selected else 'unmatched' if correct_ids and not correct_ids&matched else 'budget_or_context' if correct_ids else 'conflicting_update' if present else 'evicted' if original else 'missed_extraction'
    rows.append({'outcome':outcome,'matched_ids':sorted(matched),'arm':arm,'model':model,'fixture_kind':kind,'source':source,'question':question,'stage':stage,'source_stored':bool(original),'source_ids':original,'original_ids_retained':[r['id'] for r in n.state['facts'] if r['id'] in original],'selected_ids':sorted(selected),'expected_evidence_selected':bool(correct_ids&selected),'source_wording_in_prompt':expected in json.dumps(messages),'fact_count':len(n.state['facts']),'estimated_prompt_tokens':d['estimated_prompt_tokens'],'hard_prompt_tokens':d['budget']['hard_prompt_tokens'],'compile_median_ms':round(statistics.median(times),4)})
 totals={}
 for arm in ('checkpoint_B','fixed_B'):
  totals[arm]={}
  for stage in ('after_establishment','after_detours','after_correction'):
   group=[r for r in rows if r['arm']==arm and r['stage']==stage]
   totals[arm][stage]={'evidence_selected':sum(r['expected_evidence_selected'] for r in group),'verbatim_in_prompt':sum(r['source_wording_in_prompt'] for r in group),'source_retained':sum(bool(r['original_ids_retained']) for r in group),'outcomes':{outcome:sum(r['outcome']==outcome for r in group) for outcome in sorted({r['outcome'] for r in group})},'median_estimated_prompt_tokens':statistics.median(r['estimated_prompt_tokens'] for r in group),'total':len(group),'median_compile_ms':round(statistics.median(r['compile_median_ms'] for r in group),4),'max_estimated_prompt_tokens':max(r['estimated_prompt_tokens'] for r in group)}
 ordinary=[]
 for model in MODELS:
  summary,history,native=fixture(model);summary['narrative_context']={'facts':[]};summary['narrative_scope']=[model];versions=[]
  for compiler in (old['context_compiler'].ContextCompiler,ContextCompiler):
   messages,_,d=compiler().compile(summary,'Hello.',history,AIConfig(model=model+':latest'),reserve_characters=len(native));versions.append((messages,d['estimated_prompt_tokens']))
  ordinary.append({'model':model,'messages_identical':versions[0][0]==versions[1][0],'baseline_estimated_tokens':versions[0][1],'fixed_estimated_tokens':versions[1][1]})
 return {'ordinary_greetings':ordinary,'kind':'Matched synthetic source extraction, retention and prompt evidence; not live generated answers','baseline':'710b81e','curator_enabled':False,'detours':40,'summary':totals,'rows':rows}
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args();result=evaluate();Path(args.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['summary']))
