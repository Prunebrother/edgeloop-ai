# SPDX-License-Identifier: AGPL-3.0-only
"""Opt-in matched live telemetry evaluation. Real Ollama; synthetic input only."""
import argparse,asyncio,hashlib,json,re,subprocess,threading,time,types
from pathlib import Path
import httpx
import psutil
from ai_observer.diagnostics import local_model_directories
from companion_ai.context import compose_messages
from companion_ai.llm import OllamaProvider,LLMRequest,ChatMessage,collect_reply
from companion_ai.models import AIConfig,MemoryConfig
from companion_ai.conversation import ModelManager
from tests.fork.grounding_cases import cases

ROOT=Path(__file__).resolve().parents[2]
MODELS=['evelyn-lite-v1:latest','evelyn-qwen35-stable:latest','daisy-qwen35:latest']
BASELINE='standalone source fixture'
WORDS={0:'zero',1:'one',3:'three',42:'forty two',70:'seventy',98:'ninety eight',99:'ninety nine',100:'one hundred',120:'one hundred twenty',125:'one hundred twenty five',140:'one hundred forty',150:'one hundred fifty'}

def has_number(text,n):
    if re.search(r'(?<!\d)'+str(n)+r'(?!\d)',text):return True
    normalized=re.sub(r'\band\b',' ',text.lower().replace('-',' '));normalized=' '.join(normalized.split())
    return bool(re.search(r'\b'+WORDS.get(n,'<unrepresented>')+r'\b',normalized))

def affirmative(text,pattern):
    for m in re.finditer(pattern,text,re.I):
        prefix=text[max(0,m.start()-65):m.start()].lower().split('.')[-1]
        if re.search(r"\b(not|no|never|cannot|can't|isn't|aren't|without|insufficient|unknown|whether|if)\b",prefix):continue
        return True
    return False

def assess(reply,expected,canonical):
    text=reply.lower();checks={}
    for n in expected.get('numbers',[]):checks['number_'+str(n)]=has_number(text,n)
    uncertainty=bool(re.search(r"unavailable|unknown|unrecorded|mystery|no (?:current|valid|live|fresh)|not (?:available|known|established)|cannot|can't|don't (?:have|know)|not sure|no .*reading",text))
    if expected.get('unknown_hr'):checks['unknown_hr']=uncertainty and not bool(re.search(r'\b\d+\s*(?:bpm|beats per minute)',text))
    if expected.get('unknown_resting'):checks['unknown_resting']=uncertainty
    if expected.get('unknown_connection'):checks['unknown_connection']=uncertainty
    if 'state' in expected:
        value=expected['state'];patterns={'IDLE':r'\b(idle|stopped|inactive)\b|not running','RUNNING':r'\b(running|active)\b','PAUSED':r'\bpaused\b'}
        checks['session_state']=bool(re.search(patterns[value],text))
    if 'simulated' in expected:
        checks['hr_source']=bool(re.search(r'simulat',text)) if expected['simulated'] else bool(re.search(r'\bble\b|sensor|physical|real reading',text))
    if expected.get('device_disconnected'):checks['device_disconnected']=bool(re.search(r'disconnected|not connected|isn.t connected|no .*handy|handy.*not .*connect',text))
    if expected.get('no_motion'):checks['motion_uncertainty']=bool(re.search(r'cannot|can.t|unknown|unavailable|not .*prov|no .*evidence|doesn.t .*prov|not .*mov|not .*feedback|no .*feedback|not .*confirm|doesn.t mean',text))
    if expected.get('experience'):checks['selected_experience']='head' in text
    if expected.get('goal'):checks['selected_goal']=expected['goal'] in text
    if expected.get('trend'):checks['trend']=affirmative(text,r'\b(rising|increasing|climbing|upward)\b')
    if expected.get('no_trend'):checks['trend_uncertainty']=bool(re.search(r'unknown|not .*establish|no .*trend|cannot|can.t|insufficient|not enough|doesn.t .*trend|not .*mean|no .*evidence|not .*pulse|not .*reading',text))
    if expected.get('stop_observed'):checks['stop_observed']='stop' in text
    if expected.get('edge_increment'):checks['edge_increment']=bool(re.search(r'increas|increment|went up|up from|risen|rose|from.*to',text))
    # Candidate flags require manual review; grammar/polarity is not an oracle.
    trend=canonical['facts']['trend']['value']
    flags=[]
    if trend is None and affirmative(text,r'\b(climbing|rising|steadily|falling|dropping|steady|stable)\b'):flags.append('unsupported_trend_candidate')
    if not canonical['events'] and affirmative(text,r"\byou(?:'ve| have)? (?:just )?(?:edged|orgasmed|restarted|paused)\b"):flags.append('unsupported_event_candidate')
    if not canonical['facts']['handy']['value'] and affirmative(text,r'\bhandy (?:is |has been )?(?:moving|running|speeding|stimulating)\b'):flags.append('unsupported_device_activity_candidate')
    if re.search(r'\b(healthy|safe baseline|resting comfortably|for a man in your condition)\b',text):flags.append('unsupported_physiological_interpretation_candidate')
    return {'checks':checks,'passed_checks':sum(checks.values()),'total_checks':len(checks),'flags':flags,'bpm_mentions':re.findall(r'\b(\d+)\s*(?:bpm|beats per minute)',text)}

class Monitor:
    def __init__(self,pid):self.pid=pid;self.samples=[];self.errors=[];self.stop=threading.Event();self.thread=threading.Thread(target=self.run,daemon=True)
    def run(self):
        with httpx.Client(base_url='http://127.0.0.1:11435',timeout=3,trust_env=False) as api:
            while not self.stop.is_set():
                try:
                    out=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,memory.total','--format=csv,noheader,nounits'],text=True,timeout=5)
                    used,total=map(int,out.splitlines()[0].split(','));loaded=api.get('/api/ps');loaded.raise_for_status()
                    compute=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid,used_gpu_memory','--format=csv,noheader,nounits'],text=True,timeout=5)
                    runner=0
                    for line in compute.splitlines():
                        pid,mib=line.split(',')
                        try:
                            if int(pid)==self.pid or any(p.pid==self.pid for p in psutil.Process(int(pid)).parents()):runner+=int(mib)
                        except (psutil.Error,ValueError):pass
                    self.samples.append({'at':time.time(),'used_mib':used,'total_mib':total,'runner_mib':runner,'resident_models':[m['name'] for m in loaded.json()['models']]})
                except Exception as exc:self.errors.append(type(exc).__name__+': '+str(exc)[:160])
                self.stop.wait(1)
    def start(self):self.thread.start()
    def close(self):self.stop.set();self.thread.join(8)

def baseline_compose():
    source=(ROOT/'tests/fixtures/historical/grounding/context.py').read_text()
    module=types.ModuleType('companion_ai.f23_pinned_baseline');module.__package__='companion_ai'
    exec(compile(source,'git:'+BASELINE+':companion_ai/context.py','exec'),module.__dict__)
    return module.compose_messages,hashlib.sha256(source.encode()).hexdigest()

async def evaluate(args):
    if args.output.exists():raise ValueError('Output already exists; choose a new directory')
    args.output.mkdir(parents=True)
    origins=local_model_directories('http://127.0.0.1:11435')
    if len(origins)!=1:raise ValueError('Expected one already-running 11435 server; none will be started')
    pid=origins[0]['pid'];env=dict(x.split('=',1) for x in Path(f'/proc/{pid}/environ').read_text().split('\0') if '=' in x)
    if env.get('OLLAMA_MAX_LOADED_MODELS')!='1' or env.get('OLLAMA_NUM_PARALLEL')!='1':raise ValueError('Existing server must already limit loaded models and parallel requests to one; no restart attempted')
    baseline,baseline_sha=baseline_compose();selected=[c for c in cases() if not args.scenarios or c.name in args.scenarios]
    report={'baseline_ref':BASELINE,'baseline_context_sha256':baseline_sha,'matched_inputs':'Same validated snapshots/settings, history, question and native model instructions; F2.2 raw JSON versus F2.3 canonical runtime block','models':args.models,'temperature':0,'thinking':False,'max_tokens':512,'context_length':8192,'hardware':'Synthetic authoritative snapshots only; no physical APIs','results':[],'completed':False}
    report['runtime_source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for name in ['companion_ai/context.py','companion_ai/grounding.py','companion_ai/fidelity.py','companion_ai/conversation.py','ai_observer/observation.py','ai_observer/protocol.py','tests/fork/grounding_cases.py','tests/fork/evaluate_grounding.py'] for p in [ROOT/name]}
    monitor=Monitor(pid);monitor.start()
    try:
        with httpx.Client(base_url='http://127.0.0.1:11435',timeout=5,trust_env=False) as api:
            tags=api.get('/api/tags');tags.raise_for_status();report['installed_models']=[m['name'] for m in tags.json()['models']]
        for model in args.models:
            if model not in report['installed_models']:raise ValueError('Requested model not installed: '+model)
            config=AIConfig(model=model,thinking=False,temperature=0,max_tokens=512,idle_unload_seconds=60,timeout_seconds=120)
            manager=ModelManager('http://127.0.0.1:11435');await manager.start(config);manager.memory=MemoryConfig(max_messages=64)
            provider=manager.adapter
            metadata=await provider.capabilities(model);embedded=metadata.get('system','');manager.model_metadata=metadata
            for case in selected:
                for variant in ['baseline','grounded']:
                    summary=case.summary()
                    if variant=='baseline':
                        summary.pop('canonical_session',None)
                        if summary['state'] is not None:summary['state']['trend']=case.observation.trend
                        summary['recent_events']=[e for e in case.observation.canonical()['events']]
                    composer=baseline if variant=='baseline' else compose_messages
                    messages,warnings=composer(summary,case.prompt,case.history,config,MemoryConfig(max_messages=64),reserve_characters=len(embedded))
                    row={'model':model,'scenario':case.name,'variant':variant,'expected':case.expected,'runtime_context_characters':len(messages[0]['content'])+len(messages[-1]['content'])-len(case.prompt),
                         'history_messages_supplied':len(case.history),'history_messages_retained':len(messages)-2,'context_warnings':warnings,
                         'embedded_system_sha256':hashlib.sha256(embedded.encode()).hexdigest(),'embedded_system_characters':len(embedded)}
                    started=time.monotonic();chunks=[];metrics_start=len(provider.metrics.samples)
                    try:
                        if variant=='grounded':
                            manager.current_summary=case.observation.summary
                            reply=await manager.reply(case.summary(),case.prompt,case.history,chunks.append,on_reset=chunks.clear)
                            row['grounding_attempts']=manager.grounding_attempts;row['grounding_corrections']=manager.grounding_corrections
                        else:
                            reply=await collect_reply(provider,LLMRequest(config,tuple(ChatMessage(**m) for m in messages)),chunks.append)
                        row.update(reply=reply,seconds=round(time.monotonic()-started,3),streamed_chunks=len(chunks),metrics=dict(provider.metrics.samples[-1]),
                                   assessment=assess(reply,case.expected,case.observation.canonical()))
                        assert chunks and provider.metrics.samples[-1]['thinking_characters']==0
                    except (ValueError,httpx.HTTPError,TimeoutError) as exc:row.update(error=type(exc).__name__+': '+str(exc),provisional_text=''.join(chunks),seconds=round(time.monotonic()-started,3))
                    new_metrics=list(provider.metrics.samples)[metrics_start:]
                    row['inference_count']=len(new_metrics);row['total_prompt_tokens']=sum(m.get('prompt_tokens',0) or 0 for m in new_metrics)
                    report['results'].append(row)
                    with (args.output/'responses.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')
                print(model+' '+case.name+' baseline / grounded complete',flush=True)
        report['completed']=True
    finally:
        monitor.close();report['gpu_samples']=monitor.samples;report['monitor_errors']=monitor.errors
        report['gpu_summary']={'peak_used_mib':max((s['used_mib'] for s in monitor.samples),default=0),'peak_runner_mib':max((s['runner_mib'] for s in monitor.samples),default=0),'max_resident_models':max((len(s['resident_models']) for s in monitor.samples),default=0)}
        report['request_errors']=sum('error' in r for r in report['results'])
        (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['monitor_errors'] or report['gpu_summary']['max_resident_models']>1 or report['request_errors']:raise ValueError('Evaluation completed with errors; inspect saved report')
    print(json.dumps({'completed':report['completed'],'responses':len(report['results']),'gpu':report['gpu_summary'],'output':str(args.output)}))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true',required=True)
    parser.add_argument('--models',nargs='+',default=MODELS);parser.add_argument('--scenarios',nargs='*');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();asyncio.run(evaluate(args))
if __name__=='__main__':main()
