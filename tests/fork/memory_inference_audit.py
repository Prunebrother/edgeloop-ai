# SPDX-License-Identifier: AGPL-3.0-only
"""Test-only inference deadline and metadata stream; never logs prompts or credentials."""
import asyncio,json,time
import httpx

class InferenceAudit:
    def __init__(self,record,timeout_ms,emit=print):
        self.record=record;self.timeout_ms=timeout_ms;self.emit=emit
        self.started=time.monotonic();self.expires=asyncio.get_running_loop().time()+timeout_ms/1000
        self.finished=False;self.pending=b'';self.saw_done=False
        record.update(status='started',timeout_ms=timeout_ms)
        self.log('inference_started')

    def log(self,event):
        self.emit(json.dumps({'type':'memory_inference','event':event,**self.record}),flush=True)

    def finish(self,status,error=None):
        if self.finished:return
        self.finished=True;self.record.update(status=status,elapsed_ms=round((time.monotonic()-self.started)*1000,2))
        if error:self.record['error_type']=type(error).__name__
        self.log('inference_'+status)

    def observe(self,chunk):
        self.pending+=chunk
        while b'\n' in self.pending:
            line,self.pending=self.pending.split(b'\n',1)
            try:data=json.loads(line)
            except (ValueError,UnicodeError):continue
            if data.get('done'):
                self.saw_done=True
                for key in ('prompt_eval_count','eval_count','done_reason'):
                    if key in data:self.record[key]=data[key]
        # Metadata parsing is bounded and does not affect the forwarded stream.
        if len(self.pending)>65536:self.pending=b''

    async def forward(self,transport,request):
        try:
            async with asyncio.timeout_at(self.expires):response=await transport.handle_async_request(request)
            return httpx.Response(response.status_code,headers=response.headers,extensions=response.extensions,stream=AuditedStream(response,self))
        except TimeoutError as error:self.finish('timeout',error);raise
        except asyncio.CancelledError as error:self.finish('cancelled',error);raise
        except Exception as error:self.finish('failed',error);raise

class AuditedStream(httpx.AsyncByteStream):
    def __init__(self,response,audit):self.response=response;self.audit=audit
    async def __aiter__(self):
        try:
            async with asyncio.timeout_at(self.audit.expires):
                async for chunk in self.response.stream:
                    self.audit.observe(chunk);yield chunk
            self.audit.finish('completed' if self.response.status_code<400 else 'http_error')
        except TimeoutError as error:self.audit.finish('timeout',error);raise
        except asyncio.CancelledError as error:self.audit.finish('cancelled',error);raise
        except Exception as error:self.audit.finish('failed',error);raise
        finally:await self.response.aclose()
    async def aclose(self):
        try:await self.response.aclose()
        finally:
            # The provider may stop at the final NDJSON frame before asking for EOF.
            if not self.audit.finished:self.audit.finish('http_error' if self.response.status_code>=400 else 'completed' if self.audit.saw_done else 'cancelled')
