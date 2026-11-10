# SPDX-License-Identifier: AGPL-3.0-only
"""Opt-in F29 Player samples using an OWNED Ollama process, synthetic Replay only.

Never contacts desktop ports 8770/8768/11435. No driver, engine, UI or live data.
Installed model blobs are read in place: no builds, pulls or model mutations.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess

import httpx

from ai_observer.observation import ObserverDirector
from companion_ai.conversation import ModelManager, ConversationService
from companion_ai.director import DirectorConfig
from companion_ai.event_deck import DeckSettings
from companion_ai.models import AIConfig
from tests.ai.test_character_cards import MODELS
from tests.ai.test_player_interactions import player, notify
from tests.fork.event_replay import Replay

PORT=11445
URL=f'http://127.0.0.1:{PORT}'


def store_audit(root):
    result={}
    for p in root.rglob('*'):
        if p.is_file():
            stat=p.stat();relative=p.relative_to(root)
            result[str(relative)]={'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns}
            if relative.parts[0]=='manifests':result[str(relative)]['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    return result


class Audit(httpx.AsyncBaseTransport):
    def __init__(self):self.inner=httpx.AsyncHTTPTransport();self.calls=[]
    async def handle_async_request(self,request):
        assert (request.url.scheme,request.url.host,request.url.port)==('http','127.0.0.1',PORT)
        assert request.url.path in {'/api/show','/api/ps','/api/chat'}
        if request.url.path=='/api/chat':
            body=json.loads(request.content);assert not body.get('tools') and body['think'] is False
            self.calls.append(body)
        return await self.inner.handle_async_request(request)
    async def aclose(self):pass


async def sample(out):
    audit=Audit();rows=[]
    try:
        for identity,model in MODELS.items():
            for scenario in ('clean','answered-history','coalesced'):
                r=Replay();r.state.update(status='RUNNING' if scenario!='clean' else 'IDLE',edges=2,seconds=600)
                r.state['devices'].update(simulated_hr=True,hr_ready=True,toy_ready=False,handy=False)
                r.state['safety'].update(signal='ok',fault='device_unready')
                r.state['details']['player']=player();r.step(90,seconds=0,source='simulator')
                manager=ModelManager(URL,transport=audit)
                await manager.select(AIConfig(model=model,max_tokens=384))
                manager.current_summary=r.observation.summary
                assert manager.tool_executor is None
                frames=[];service=ConversationService(r.observation,frames.append,manager,clock=r.clock.mono,
                    director=ObserverDirector(DirectorConfig(regenerate_once=False),clock=r.clock.mono))
                service.deck_settings=DeckSettings(enabled=True,countdown_seconds=300,simulated_session=True)
                service.arrival=None;service.deck()._start_done=True
                try:
                    if scenario=='answered-history':
                        service.request('For a fictional paper boat, choose Marigold or Tinfoil. Answer briefly.',user=True)
                        await service.task;await asyncio.sleep(0)
                        r.step(90,seconds=45)
                    events=(('player_opened',dict(opened=1,workspace_open=True)),
                            ('video_selected',dict(selected=1,has_video=True,title='Aladdin' if scenario=='clean' else 'Orchid Signal',title_source='filename')),
                            ('video_started',dict(started=1,playing=True)))
                    for kind,updates in events:
                        if kind=='video_started' and r.state['status']=='IDLE':r.step(90,seconds=0,status='RUNNING')
                        first=len(audit.calls);start=len(frames)
                        notify(r,service,kind,**updates)
                        if scenario=='coalesced' and kind!='video_started':continue
                        r.step(90,seconds=8);service.pump()
                        assert service.task is not None and not service.task.done(), (identity,scenario,kind,service.status())
                        await service.task;await asyncio.sleep(0)
                        calls=audit.calls[first:]
                        texts=[f['text'] for f in frames[start:] if f['type']=='speech']
                        row=dict(identity=identity,model=model,scenario=scenario,kind=kind,
                            synthetic_context=dict(status=r.state['status'],edges=2,hr=90,hr_source='simulator',player=deepcopy(r.state['details']['player'])),
                            text='\n'.join(texts),requests=calls,
                            errors=[f for f in frames[start:] if f['type'] in {'conversation_error','response_suppressed'}])
                        rows.append(row);(out/'samples.json').write_text(json.dumps(rows,indent=2)+'\n')
                        print(identity,scenario,kind,repr(row['text']),flush=True)
                        # Finish simulated speech pacing before the next genuine interaction.
                        r.step(90,seconds=30)
                finally:await service.close()
    finally:await audit.inner.aclose()
    assert len(rows)==28
    return rows


async def run(args):
    if os.environ.get('EDGELOOP_LIVE_ACCEPTANCE')!='1':raise RuntimeError('Explicit opt-in required')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    root=Path(args.models).expanduser().resolve()
    before=store_audit(root);assert before
    (out/'model-store-before.json').write_text(json.dumps(before,indent=2)+'\n')
    # Fail closed on an occupied port. Never attach to another daemon.
    with socket.socket() as sock:sock.bind(('127.0.0.1',PORT))
    env={**os.environ,'OLLAMA_HOST':f'127.0.0.1:{PORT}','OLLAMA_MODELS':str(root),
         'OLLAMA_NUM_PARALLEL':'1','OLLAMA_MAX_LOADED_MODELS':'1','OLLAMA_FLASH_ATTENTION':'1',
         'OLLAMA_NOPRUNE':'1','OLLAMA_NO_CLOUD':'1'}
    env.pop('EDGELOOP_PAIRING_FILE',None)
    log=(out/'ollama.log').open('w')
    child=subprocess.Popen(['/usr/bin/ollama','serve'],env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        async with httpx.AsyncClient(base_url=URL,trust_env=False,timeout=2) as client:
            for _ in range(100):
                if child.poll() is not None:raise RuntimeError('Owned Ollama failed; no fallback permitted')
                try:
                    response=await client.get('/api/tags');response.raise_for_status()
                    assert set(MODELS.values())<={x['name'] for x in response.json()['models']}
                    if child.poll() is None:break
                except httpx.HTTPError:await asyncio.sleep(.1)
            else:raise RuntimeError('Owned Ollama not ready')
        await sample(out)
    finally:
        child.terminate()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        log.close();after=store_audit(root)
        (out/'model-store-after.json').write_text(json.dumps(after,indent=2)+'\n')
        (out/'isolation.json').write_text(json.dumps(dict(port=PORT,owned_pid=child.pid,process_stopped=child.poll() is not None,
             desktop_ports_contacted=False,live_data_used=False,physical_hardware=False,model_store_unchanged=before==after),indent=2)+'\n')
        assert before==after,'Model storage changed'


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    p.add_argument('--models',default='~/.ollama/models');asyncio.run(run(p.parse_args()))
