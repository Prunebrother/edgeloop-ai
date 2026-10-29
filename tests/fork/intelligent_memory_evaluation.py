# SPDX-License-Identifier: AGPL-3.0-only
"""Matched A/B/C evidence benchmark; optionally real, sequential Ollama recall calls."""
import argparse,asyncio,json,re,statistics,subprocess,sys,tempfile,time,types
from pathlib import Path
from companion_ai.narrative import NarrativeMemory
from companion_ai.context_compiler import ContextCompiler,estimate
from companion_ai.memory_curator import MemoryCurator,CuratorConfig,INSTRUCTION
from companion_ai.models import AIConfig
from companion_ai.llm import OllamaProvider,LLMRequest,ChatMessage,collect_reply
from tests.fork.context_retention_fixture import fixture,MODELS
ROOT=Path(__file__).resolve().parents[2]
HOBBIES=('tending an overgrown succulent','pressing wildflowers','restoring fountain pens')

def frozen():
    modules={}
    for name in ('narrative_facts','narrative','context_compiler'):
        full='companion_ai._f2841_a_'+name;m=types.ModuleType(full);m.__package__='companion_ai';sys.modules[full]=m
        source=(ROOT/'tests/fixtures/historical/curation'/(name+'.py')).read_text()
        source=source.replace('from .narrative_facts import','from ._f2841_a_narrative_facts import').replace('from .narrative import','from ._f2841_a_narrative import')
        exec(compile(source,'<f284-'+name+'>','exec'),m.__dict__);modules[name]=m
    return modules

async def evaluate(live=False):
    old=frozen();rows=[];live_rows=[];curation_inputs=[]
    for model,hobby in zip(MODELS,HOBBIES):
        summary,history,native=fixture(model)
        for arm in ('A','B','C'):
            n=(old['narrative'].NarrativeMemory if arm=='A' else NarrativeMemory)();n.activate(model,'synthetic')
            n.accepted('Imagine a laboratory mystery.','A quiet room awaits our investigation.',True)
            n.accepted('The blue laboratory door is marked ORCHID-17.',f'My hobby is {hobby}.',True)
            curator=MemoryCurator();curator.configure(CuratorConfig(enabled=arm=='C',interval_turns=8))
            for i in range(24):
                user=f'The visitor leaves parcel number {i} on the table.';assistant=f'A curtain moves in room {i}.'
                n.accepted(user,assistant,True);curator.note(n,user,assistant,True)
                if curator.due(n):
                    p=curator.payload(n)
                    # Deterministic proposal fixture measures validation/application, not LLM intelligence.
                    important=[r for r in p['memories'] if 'ORCHID' in r['text'] or hobby in r['text']]
                    start=time.perf_counter()
                    curator.apply(n,p,json.dumps({'proposals':[{'source_ref':r['id'],'quote':r['text'],'category':r['category'],'importance':5,'action':'retain','justification':'Synthetic sourced importance fixture'} for r in important]}))
                    curation_inputs.append({'model':model,'estimated_input_tokens':estimate(native+INSTRUCTION+json.dumps(p))+96,'payload_bytes':len(json.dumps(p).encode()),'validation_apply_ms':round((time.perf_counter()-start)*1000,4),'inference_latency_seconds':None})
            for query,expected in [('What was the identifier on the blue laboratory door?','ORCHID-17'),('What is your hobby?',hobby),('Hello there.',None)]:
                compiler=old['context_compiler'].ContextCompiler() if arm=='A' else ContextCompiler()
                config=AIConfig(model=model+':latest',thinking=False,max_tokens=256)
                current=summary|{'narrative_context':n.context(),'narrative_scope':[model]};times=[]
                for _ in range(30):
                    start=time.perf_counter();messages,_,d=compiler.compile(current,query,history,config,reserve_characters=max(len(native),len(native.encode())))
                    times.append((time.perf_counter()-start)*1000)
                rows.append({'arm':arm,'model':model,'query':query,'expected_evidence':expected,'evidence_in_prompt':expected in json.dumps(messages) if expected else None,'selected_fact_ids':d.get('narrative_recall',{}).get('selected_fact_ids',[]),'estimated_prompt_tokens':d['estimated_prompt_tokens'],'compile_median_ms':round(statistics.median(times),4),'memory_size':len(n.state['facts']),'memory_bytes':len(json.dumps(n.state).encode()),'simulated_curator_triggers':24//8 if arm=='C' else 0})
                if live and expected:
                    import httpx
                    provider=OllamaProvider(config.model,base_url='http://127.0.0.1:11435',config=config)
                    start=time.perf_counter()
                    try:
                        text=await collect_reply(provider,LLMRequest(config,tuple(ChatMessage(**m) for m in messages)))
                        live_rows.append({'arm':arm,'model':model,'query':query,'status':'completed','think':False,'exact':expected in text,'synthetic_response':text[:320],'seconds':round(time.perf_counter()-start,3),'metrics':provider.metrics.samples[-1] if provider.metrics.samples else {}})
                    except (httpx.HTTPError,ValueError,TimeoutError) as exc:live_rows.append({'arm':arm,'model':model,'status':'blocked','reason':type(exc).__name__,'think':False})
    return {'baseline':'4b09888','token_method':'Conservative UTF-8/character estimate, native SYSTEM lengths from source','offline_curator':'Synthetic source-validated proposals, NOT live curation or answer accuracy','rows':rows,'curation_inputs':curation_inputs,'live':live_rows}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--output',required=True);a=p.parse_args()
    result=asyncio.run(evaluate(a.live));Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
