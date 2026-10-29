# SPDX-License-Identifier: AGPL-3.0-only
"""Opt-in live validation; existing models only; no hardware or model changes."""
import asyncio,json,os,time,statistics,sys
from pathlib import Path
import httpx
from companion_ai.conversation import ModelManager
from companion_ai.models import AIConfig
from companion_ai.context import compose_messages
from companion_ai.fidelity import violations, GroundingError
from tests.fork.grounding_cases import cases

async def main():
    if os.environ.get('EDGELOOP_LIVE_ACCEPTANCE')!='1':raise RuntimeError('Explicit live opt-in required')
    output=Path(os.environ.get('F25_MATRIX_REPORT','/tmp/f25-matrix.json'))
    report={'endpoint':'http://127.0.0.1:11435','thinking':False,'hardware':'none; canonical synthetic observations only','models':[],'passed':False,'quality_note':'Passing checks cover transport, metadata and existing factual guard, not complete semantic accuracy; manual review required.'}
    wire=[]
    # Audited streaming pool with lifecycle owned by the fixture, not providers.
    class LiveAudit(httpx.AsyncBaseTransport):
        def __init__(self):self.inner=httpx.AsyncHTTPTransport()
        async def handle_async_request(self,request):
            if request.url.path in {'/api/chat','/api/generate'}:
                body=json.loads(request.content);assert body.get('think') is False
                wire.append({'model':body['model'],'think':body['think'],'path':request.url.path})
            return await self.inner.handle_async_request(request)
        async def aclose(self):pass
    transport=LiveAudit()
    manager=ModelManager('http://127.0.0.1:11435',transport=transport)
    canonical={c.name:c for c in cases()}
    idle=canonical['idle_no_sensor'].summary()
    ordinary=[('greeting','Good morning! Say hello in your own style in one or two sentences.'),
              ('joking','My coffee has filed a complaint about being overworked. Give me a quick playful reply.'),
              ('serious','I need to plan a difficult conversation with a friend. Give me one thoughtful first step.'),
              ('reassuring','I had a disappointing day and could use a little reassurance. Keep it brief.'),
              ('surprising','I just learned that octopuses have three hearts. That surprised me!')]
    scenarios=[(name,idle,prompt,[]) for name,prompt in ordinary]
    for name in ['idle_no_sensor','active_simulated','paused','hardware_disconnected_active','stale_connection','edge_increment']:
        c=canonical[name];scenarios.append((name,c.summary(),c.prompt+' Answer in at most two sentences.',c.history))
    # Same validated event context goes to every character; no emotional mapping.
    c=canonical['edge_increment'];summary=c.summary()|{'conversation_source':'event'}
    scenarios.append(('validated_event_reaction',summary,'Observed application event (not a user request): edge. A brief natural acknowledgement is optional; [SILENCE] is allowed.',[]))
    discovered=await manager.provider().discover()
    models=['evelyn-lite-v1:latest','evelyn-qwen35-stable:latest','daisy-qwen35:latest']
    extra=next((m['name'] for m in discovered if m['name']=='qwen3:8b'),None)
    if extra:models.append(extra)
    try:
        for model in models:
            await manager.select(AIConfig(model=model,max_tokens=384,idle_unload_seconds=60),context_policy='adapt')
            row={'model':model,'scenarios':[]};report['models'].append(row)
            for name,summary,prompt,history in scenarios if model in models[:3] else scenarios[:2]:
                seen=[];chunks=[];start=time.monotonic();first=None
                def chunk(text):
                    nonlocal first
                    if text.strip() and first is None:first=time.monotonic()-start
                    chunks.append(text)
                result={'scenario':name,'passed':False}
                try:
                    text=await manager.reply(summary,prompt,history,on_chunk=chunk,on_reset=lambda:chunks.clear(),on_expression=seen.append)
                    metrics=dict(manager.metrics.samples[-1]);metadata=manager.adapter.last_expression_metadata
                    result.update(text=text,expression=metadata.get('expression'),metadata_valid=metadata.get('valid'),expression_updates=seen,
                        first_visible_seconds=round(first,3) if first else None,total_seconds=round(time.monotonic()-start,3),metrics=metrics,
                        grounding_violations=violations(text,summary.get('canonical_session'),history+[{'role':'user','content':prompt}]),
                        grounding_attempts=manager.grounding_attempts,metadata_leak='[[' in text,reasoning_leak='<think' in text.lower(),
                        personality_system_preserved=bool(manager.model_metadata.get('system')) or model==extra)
                    result['passed']=not result['metadata_leak'] and not result['reasoning_leak'] and not result['grounding_violations'] and metrics['thinking_enabled'] is False
                except GroundingError as exc:result.update(passed=True,safe_fallback=True,error_codes=list(exc.codes),error=str(exc),total_seconds=round(time.monotonic()-start,3))
                except Exception as exc:result.update(error=type(exc).__name__+': '+str(exc)[:220],total_seconds=round(time.monotonic()-start,3))
                row['scenarios'].append(result)
                output.write_text(json.dumps(report,indent=2)+'\n')
                print(model,name,result.get('metadata_valid'),result['passed'],flush=True)
            # One controlled no-envelope baseline per primary model, same native personality and think:false.
            if model in models[:3]:
                active=manager.config
                manager.config=active.model_copy(update={'explicit_expressions':False});manager.adapter.config=manager.config
                prompt=ordinary[0][1]
                try:
                    start=time.monotonic();text=await manager.reply(idle,prompt,[])
                    row['f24_style_baseline']={'text':text,'metrics':dict(manager.metrics.samples[-1]),'total_seconds':round(time.monotonic()-start,3)}
                    enabled_messages,_=compose_messages(idle,prompt,[],active,reserve_characters=len(manager.model_metadata.get('system','')))
                    disabled_messages,_=compose_messages(idle,prompt,[],manager.config,reserve_characters=len(manager.model_metadata.get('system','')))
                    row['format_instruction_characters']=len(enabled_messages[0]['content'])-len(disabled_messages[0]['content'])
                except Exception as exc:row['baseline_error']=type(exc).__name__
                manager.config=active;manager.adapter.config=active
            loaded=await manager.adapter.loaded();row['resident_models']=[m['name'] for m in loaded];row['vram_bytes']=sum(m.get('size_vram',0) for m in loaded)
            output.write_text(json.dumps(report,indent=2)+'\n')
        samples=[s for m in report['models'] for s in m['scenarios']]
        report.update(wire=wire,passed=all(s['passed'] for s in samples),valid_expression_responses=sum(s.get('metadata_valid') is True for s in samples),responses=len(samples),completed_responses=sum('text' in s for s in samples),safe_fallbacks=sum(s.get('safe_fallback',False) for s in samples))
    finally:
        output.write_text(json.dumps(report,indent=2)+'\n');await transport.inner.aclose()
    print(json.dumps({k:v for k,v in report.items() if k not in {'models','wire'}}))
if __name__=='__main__':asyncio.run(main())
