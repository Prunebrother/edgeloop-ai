# SPDX-License-Identifier: AGPL-3.0-only
"""Synthetic journal selection/token/CPU benchmark; optional sequential existing Ollama."""
import argparse,asyncio,json,re,statistics,subprocess,sys,tempfile,time,types
from pathlib import Path
from companion_ai.context_compiler import ContextCompiler
from companion_ai.models import AIConfig
from companion_ai.llm import OllamaProvider,LLMRequest,ChatMessage,collect_reply
from tests.ai.test_f284 import setup,stop,SCOPE
from tests.fork.context_retention_fixture import fixture,MODELS
ROOT=Path(__file__).resolve().parents[2]

def baseline():
    module=types.ModuleType('companion_ai._f284_baseline');module.__package__='companion_ai';sys.modules[module.__name__]=module
    exec(compile((ROOT/'tests/fixtures/historical/journal/context_compiler.py').read_text(),'<f283>', 'exec'),module.__dict__)
    return module.ContextCompiler()

async def evaluate(live=False):
    rows=[];providers=[]
    with tempfile.TemporaryDirectory(prefix='edgeloop-journal-eval-') as directory:
        c,o,s,j=setup(Path(directory));s['seconds']=o.report['seconds']=120;stop(c,o,s)
        record=j.data['records'][0]
        for model in MODELS:
            summary,history,native=fixture(model);scope=SCOPE.replace('evelyn-narrative-v1',model)
            selected_record=json.loads(json.dumps(record));selected_record['companions']=[{'model_scope':scope,'model':model+':latest','companion':model.split('-')[0]}]
            j.data['records']=[selected_record]
            for prompt in ['Hello there.','How long was my previous session?','Which settings did we use last time?']:
                current=summary|{'journal_context':j.retrieve(prompt,scope)};config=AIConfig(model=model+':latest',thinking=False)
                for arm,compiler in [('f283',baseline()),('f284',ContextCompiler())]:
                    timings=[]
                    for _ in range(30):
                        start=time.perf_counter();messages,_,diag=compiler.compile(current,prompt,history,config,reserve_characters=max(len(native),len(native.encode())))
                        timings.append((time.perf_counter()-start)*1000)
                    rows.append({'model':model,'scenario':prompt,'arm':arm,'estimated_prompt_tokens':diag['estimated_prompt_tokens'],'compile_median_ms':round(statistics.median(timings),4),'history_retained':diag['allocation']['retained_history_messages'],'story_retained':diag['allocation']['retained_story_items'],'journal_selected':bool(diag.get('journal_session_ids'))})
                if live and 'How long' in prompt:
                    import httpx
                    provider=OllamaProvider(config.model,base_url='http://127.0.0.1:11435',config=config.model_copy(update={'max_tokens':256,'thinking':False}))
                    try:
                        start=time.perf_counter();reply=await collect_reply(provider,LLMRequest(config,tuple(ChatMessage(**m) for m in messages)))
                        providers.append({'model':model,'think':False,'status':'completed','seconds':round(time.perf_counter()-start,3),'metrics':provider.metrics.samples[-1] if provider.metrics.samples else {},'synthetic_response':reply})
                    except (httpx.HTTPError,ValueError,TimeoutError) as exc:providers.append({'model':model,'think':False,'status':'blocked','reason':type(exc).__name__})
        writes=[]
        for _ in range(20):
            start=time.perf_counter();j.command('configure',ai_access=True);writes.append((time.perf_counter()-start)*1000)
    return {'physical_hardware':False,'rows':rows,'atomic_write_median_ms':round(statistics.median(writes),4),'live':providers,'token_method':'Conservative UTF-8/character estimate, not provider tokens'}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--output',required=True);args=parser.parse_args()
    result=asyncio.run(evaluate(args.live));Path(args.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
