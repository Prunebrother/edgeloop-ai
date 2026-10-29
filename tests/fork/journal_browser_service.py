# SPDX-License-Identifier: AGPL-3.0-only
"""Synthetic journal browser fixture, existing mocked Ollama and temporary store only."""
import time
from uuid import uuid4
import uvicorn
from tests.fork.narrative_browser_service import f
from tests.fork.grounding_cases import snapshot,frame
from ai_observer.protocol import Observation

@f.app.post('/fixture/journal-session')
async def journal_session():
    o=f.app.state.observation
    # Browser fixture data travels through exactly the production observer capture path.
    class Clock:
        def wall(self):return time.time()
    s=snapshot(Clock());s['session_id']=str(uuid4());s['seconds']=0;s['details']['warmup_active']=False
    s['status']='IDLE';o.last_capture=None
    for status,seconds,outcome in [('IDLE',0,None),('RUNNING',0,None),('RUNNING',120,None),('IDLE',120,'manual_stop')]:
        s.update(status=status,seconds=seconds);s['details'].update(captured_at_ms=int(time.time()*1000),terminal_outcome=outcome)
        s['details']['hr_recorded_at_ms']=s['details']['captured_at_ms']
        assert o.accept(Observation.model_validate(frame(s,o.sequence+1)))
    return {'recorded':f.app.state.journal.snapshot()['total']}

if __name__=='__main__':uvicorn.run(f.app,host='127.0.0.1',port=f.PORT,access_log=False)
