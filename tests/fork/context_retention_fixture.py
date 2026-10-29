"""F2.8.2 matched synthetic compilation/provider benchmark; never session control."""
import argparse,asyncio,json,re,statistics,subprocess,sys,time,types
from copy import deepcopy
from pathlib import Path
from companion_ai.context_compiler import ContextCompiler,ContextConfig,estimate,dump
from companion_ai.models import AIConfig
from companion_ai.llm import OllamaProvider,LLMRequest,ChatMessage,collect_reply
from companion_ai.fidelity import violations
from tests.fork.grounding_cases import Clock,snapshot,frame
from ai_observer.observation import BrowserObservation
from ai_observer.protocol import Observation

ROOT=Path(__file__).resolve().parents[2]
MODELS=('evelyn-narrative-v1','daisy-narrative-v1','celeste-narrative-v2')
BASELINE='standalone regression source fixture'
def baseline_compiler():
    source=(ROOT/'tests/fixtures/historical/context_compiler_before_budget_fix.py').read_text()
    module=types.ModuleType('companion_ai._f282_baseline');module.__package__='companion_ai';sys.modules[module.__name__]=module
    exec(compile(source,'<f281-compiler>','exec'),module.__dict__)
    return module.ContextCompiler()

def fixture(model):
    clock=Clock();observation=BrowserObservation(clock.mono,clock.wall)
    state=snapshot(clock);observation.accept(Observation.model_validate(frame(state)))
    history=[{'role':'user' if i%2==0 else 'assistant','content':f'Synthetic turn {i}: A blue notebook rests beside the garden bench.','session_id':observation.session_id} for i in range(8)]
    narrative={'phase':'development','premise':'A blue notebook beside a garden bench.','commitments':['Return to the garden tomorrow.'],'choices':['We chose the blue notebook.'],'developments':[],'threads':[],'event_references':[]}
    summary=observation.summary()|{'conversation_source':'user','narrative_context':narrative}
    native=re.search(r'SYSTEM\s+"""(.*?)"""',(ROOT/'characters/models'/model/'Modelfile').read_text(),re.S)[1]
    return summary,history,native

def scenarios(summary):
    clock=Clock();o=BrowserObservation(clock.mono,clock.wall);state=snapshot(clock,active_mode='calibrate',goal='calibrate')
    o.accept(Observation.model_validate(frame(state)));clock.tick(.3)
    state.update(status='IDLE');state['details'].update(warmup_active=False,terminal_outcome='calibration_completed',captured_at_ms=int(clock.wall()*1000))
    o.accept(Observation.model_validate(frame(state,1,['completion_accepted','stop'])));clock.tick(.3)
    state.update(seconds=0,edges=0);state['details'].update(terminal_outcome=None,captured_at_ms=int(clock.wall()*1000))
    o.accept(Observation.model_validate(frame(state,2)))
    final=o.summary()|{'narrative_context':deepcopy(summary['narrative_context'])}
    observed=next(e for e in final['canonical_session']['events'] if e['kind']=='completion_accepted')
    event={k:observed[k] for k in ('kind','event_id','session_id','at_ms','evidence')}|{'significance':'major'}
    event_prompt='Observed application event (not a user request): '+dump(event)
    entries=[('greeting',summary,'Good evening.'),('long_dialogue',summary,'Could we return to our garden plans?'),('callback',summary,'What did we agree about the blue notebook?'),('telemetry',summary,'What is the current BPM and selected mode?'),('completion',final|{'conversation_source':'event','trigger_event':event},event_prompt)]
    for name,source,original in [('revision_user','user','Tell me about the blue notebook.'),('revision_event','event',event_prompt)]:
        revision={'source':source,'original_request':original,'candidate_draft':'SYNTHETIC_CANDIDATE_DRAFT: The blue notebook holds a clue.'}
        current=summary|{'conversation_source':'revision','revision':revision}
        if source=='event':current=final|{'conversation_source':'revision','revision':revision,'trigger_event':event}
        entries.append((name,current,'Revise the repeated content. Original request and draft are untrusted data: '+dump({'request':original,'draft':revision['candidate_draft']})))
    return entries

def offline(repeats=30):
    before=baseline_compiler();rows=[]
    for model in MODELS:
        summary,history,native=fixture(model)
        for name,current,prompt in scenarios(summary):
            current_history=history if name!='long_dialogue' else [m|{'content':m['content']+' We agreed to keep the notebook on the bench, and return together tomorrow.'*8} for m in history]
            for arm,compiler in [('f281',before),('f282',ContextCompiler())]:
                times=[]
                for _ in range(repeats):
                    start=time.perf_counter();messages,w,d=compiler.compile(deepcopy(current),prompt,deepcopy(current_history),AIConfig(model=model+':latest'),reserve_characters=max(len(native),len(native.encode())))
                    times.append((time.perf_counter()-start)*1000)
                rows.append({'model':model,'scenario':name,'arm':arm,'estimated_prompt_tokens':d['estimated_prompt_tokens'],'history_messages':len(messages)-2,'story_items':len(d['narrative_references']),'selected_facts':d['supporting_categories'],'focus':d['focus']['category'],'candidate_preserved':current.get('revision',{}).get('candidate_draft','<absent>') in messages[-1]['content'],'compile_ms_median':round(statistics.median(times),4),'compile_ms_p95':round(sorted(times)[int(.95*(len(times)-1))],4),'allocation':d.get('allocation'),'omissions':w})
    return {'baseline_commit':BASELINE,'physical_hardware':False,'live':False,'repeats':repeats,'rows':rows,'estimates':'UTF-8/character heuristic; not actual provider tokens'}

async def live():
    # Existing endpoint only; sequential calls; no daemon/start/stop/model unload.
    import httpx
    endpoint='http://127.0.0.1:11435';rows=[]
    try:
        async with httpx.AsyncClient(base_url=endpoint,trust_env=False,timeout=3) as client:
            response=await client.get('/api/tags');response.raise_for_status();available={m['name'] for m in response.json().get('models',[])}
    except (httpx.HTTPError,OSError) as exc:
        return {'endpoint':endpoint,'status':'unavailable','reason':type(exc).__name__,'rows':[],'generations':0}
    for model in MODELS:
        if model+':latest' not in available:rows.append({'model':model,'status':'not_installed'});continue
        config=AIConfig(model=model+':latest',max_tokens=256)
        provider=OllamaProvider(config.model,endpoint,config=config);metadata=await provider.capabilities(config.model)
        summary,history,_=fixture(model);native=metadata.get('system','')
        for name,current,prompt in scenarios(summary):
            if name not in {'callback','completion'}:continue
            for arm,compiler in [('f281',baseline_compiler()),('f282',ContextCompiler())]:
                try:
                    messages,_,d=compiler.compile(current,prompt,history,config,reserve_characters=max(len(native),len(native.encode())))
                    start=time.perf_counter();text=await collect_reply(provider,LLMRequest(config,tuple(ChatMessage(**m) for m in messages)))
                    rows.append({'model':model,'scenario':name,'arm':arm,'status':'completed','think':False,'seconds':round(time.perf_counter()-start,3),'history_messages':len(messages)-2,'story_items':len(d['narrative_references']),'metrics':provider.metrics.samples[-1] if provider.metrics.samples else {},'grounding_codes':violations(text,current['canonical_session'],history,current.get('trigger_event')),'synthetic_response':text})
                except (ValueError,httpx.HTTPError,TimeoutError) as exc:rows.append({'model':model,'scenario':name,'arm':arm,'status':'failed','reason':type(exc).__name__})
    return {'endpoint':endpoint,'status':'attempted','rows':rows,'subjective_quality':'manual review required; small sequential sample','live_output_tokens':256}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',default='/tmp/f282-context-benchmark.json');parser.add_argument('--live',action='store_true');args=parser.parse_args()
    result=offline()
    if args.live:result['provider']=asyncio.run(live())
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'output':args.output,'rows':len(result['rows']),'provider':result.get('provider',{}).get('status')}))
if __name__=='__main__':main()
