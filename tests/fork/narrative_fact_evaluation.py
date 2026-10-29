"""F2.8.3 evidence-recall comparison against F2.8.2; synthetic conversation only."""
import argparse,asyncio,json,re,statistics,subprocess,sys,time,types
from copy import deepcopy
from pathlib import Path
import httpx
from companion_ai.narrative import NarrativeMemory
from companion_ai.context_compiler import ContextCompiler
from companion_ai.models import AIConfig
from companion_ai.llm import OllamaProvider,LLMRequest,ChatMessage,collect_reply
from tests.fork.context_retention_fixture import MODELS,fixture as context_fixture

BASELINE='standalone source fixture';ROOT=Path(__file__).resolve().parents[2]
QUOTE='The truth was hidden in plain sight.';POTS='vintage, slightly dented teapots'
def frozen(name):
    source=(ROOT/'tests/fixtures/historical/narrative'/(name+'.py')).read_text()
    module=types.ModuleType('companion_ai._f283_baseline_'+name);module.__package__='companion_ai';sys.modules[module.__name__]=module
    exec(compile(source,'<f282-'+name+'>','exec'),module.__dict__);return module

def memory(cls,model,scenario):
    n=cls();n.activate(model,'synthetic-story')
    if scenario=='missing':return n
    n.accepted('The Glasshouse page says "'+QUOTE+'"','I have a collection of '+POTS+'.',True)
    # Same legacy drawer state in both arms, reproducing "present but not selected".
    n.state.update(premise='The Glasshouse mystery.',developments=[QUOTE,'I have a collection of '+POTS+'.'],commitments=['I will bring a lantern tomorrow.'],threads=['Shall we visit the garden?'])
    if scenario=='long_detour':
        for i in range(40):n.accepted('Could we discuss the garden?','A quiet breeze crosses the garden '+str(i)+'.',True)
    if scenario=='contradiction':
        n.accepted('What do you collect?','I collect embroidered handkerchiefs.',True)
        n.accepted('What did the page say?','The page said "The answer sleeps beneath the roses."',True)
    return n

def report(repeats=30):
    old_n=frozen('narrative').NarrativeMemory;old_c=frozen('context_compiler').ContextCompiler;rows=[]
    for model in MODELS:
        base,history,native=context_fixture(model)
        for scenario in ('stored','long_detour','contradiction','missing'):
            for question,expected in [('What did the page say?',QUOTE),('What do you collect?',POTS)]:
                for arm,nclass,cclass in [('f282',old_n,old_c),('f283',NarrativeMemory,ContextCompiler)]:
                    n=memory(nclass,model,scenario);summary=base|{'narrative_context':n.context(True)};times=[]
                    for _ in range(repeats):
                        start=time.perf_counter();m,w,d=cclass().compile(deepcopy(summary),question,deepcopy(history),AIConfig(model=model+':latest'),reserve_characters=len(native));times.append((time.perf_counter()-start)*1000)
                    rows.append({'model':model,'scenario':scenario,'question':question,'arm':arm,'expected':None if scenario=='missing' else expected,'evidence_present':expected in json.dumps(m,ensure_ascii=False),'uncertainty_instruction':'acknowledge uncertainty' in m[-1]['content'],'estimated_prompt_tokens':d['estimated_prompt_tokens'],'memory_items':len(d['narrative_references']),'history_messages':len(m)-2,'compile_ms_median':round(statistics.median(times),4),'compile_ms_p95':round(sorted(times)[int(.95*(len(times)-1))],4),'recall':d.get('narrative_recall'),'memory_decisions':d.get('memory_decisions',[])})
    return {'baseline':BASELINE,'physical_hardware':False,'repetitions':repeats,'metric':'evidence present in outgoing context, NOT generated-response recall accuracy','rows':rows}

async def live():
    endpoint='http://127.0.0.1:11435';rows=[]
    try:
        async with httpx.AsyncClient(base_url=endpoint,timeout=3,trust_env=False) as client:
            r=await client.get('/api/tags');r.raise_for_status();available={m['name'] for m in r.json().get('models',[])}
    except (httpx.HTTPError,OSError) as exc:return {'status':'unavailable','reason':type(exc).__name__,'endpoint':endpoint,'generations':0,'rows':[]}
    old_n=frozen('narrative').NarrativeMemory;old_c=frozen('context_compiler').ContextCompiler
    for model in MODELS:
        if model+':latest' not in available:rows.append({'model':model,'status':'not_installed'});continue
        config=AIConfig(model=model+':latest',max_tokens=256);provider=OllamaProvider(config.model,endpoint,config=config)
        meta=await provider.capabilities(config.model);native=meta.get('system','');base,history,_=context_fixture(model)
        for question,expected in [('What did the page say?',QUOTE),('What do you collect?',POTS)]:
            for arm,nclass,cclass in [('f282',old_n,old_c),('f283',NarrativeMemory,ContextCompiler)]:
                n=memory(nclass,model,'stored');summary=base|{'narrative_context':n.context(True)}
                try:
                    m,_,d=cclass().compile(summary,question,history,config,reserve_characters=len(native));start=time.perf_counter()
                    text=await collect_reply(provider,LLMRequest(config,tuple(ChatMessage(**msg) for msg in m)))
                    rows.append({'model':model,'arm':arm,'question':question,'status':'completed','think':False,'exact_expected_substring':expected in text,'seconds':round(time.perf_counter()-start,3),'metrics':provider.metrics.samples[-1] if provider.metrics.samples else {},'synthetic_reply':text})
                except (ValueError,httpx.HTTPError,TimeoutError) as exc:rows.append({'model':model,'arm':arm,'status':'failed','reason':type(exc).__name__})
    return {'status':'attempted','endpoint':endpoint,'rows':rows,'quality_rubric':'exact substring only; small sequential sample, human review still required'}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--output',default='/tmp/f283/evaluation.json');args=parser.parse_args();result=report()
    if args.live:result['provider']=asyncio.run(live())
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'output':args.output,'rows':len(result['rows']),'provider':result.get('provider',{}).get('status')}))
if __name__=='__main__':main()
