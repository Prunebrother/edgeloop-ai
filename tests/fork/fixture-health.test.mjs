// SPDX-License-Identifier: AGPL-3.0-only
// Exercise direct-script and module entry points with the suites' isolated environment.
// No browser, model inference, hardware, or caller PYTHONPATH is required.
import test from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {rm} from 'node:fs/promises';
import path from 'node:path';
import {claimPorts,ownedReady,isolatedEnv} from './fixture-isolation.mjs';
const root=path.resolve(new URL('../..',import.meta.url).pathname);
async function freePort(){
    const server=net.createServer();
    const listening=once(server,'listening');server.listen(0,'127.0.0.1');await listening;
    const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port;
}
for(const service of ['browser_service','helix_browser_service'])for(const module of [false,true]){
    test(`${service} /health via ${module?'module':'plain script'} without PYTHONPATH`,{timeout:20000},async()=>{
        const port=await freePort();await claimPorts(port);
        const env=isolatedEnv({EDGELOOP_FIXTURE_UI_PORT:'8990',EDGELOOP_FIXTURE_OBSERVER_PORT:String(port)});
        delete env.PYTHONPATH;
        env.EDGELOOP_CAMPAIGN_FIXTURE_DATA=path.join(env.XDG_RUNTIME_DIR,'campaign');
        let child,logs='';
        try{
            const args=module?['-m',`tests.fork.${service}`]:[`tests/fork/${service}.py`];
            child=spawn(path.join(root,'.venv/bin/python'),args,{cwd:root,env,stdio:['ignore','pipe','pipe']});
            child.stdout.on('data',data=>{logs+=data;});child.stderr.on('data',data=>{logs+=data;});
            child.on('error',error=>{logs+=error;});
            const url=`http://127.0.0.1:${port}/health`;
            await ownedReady(url,[child]);
            const response=await fetch(url);
            assert.equal(response.status,200);const health=await response.json();
            assert.equal(health.ok,true);assert.equal(health.read_only,true);assert.equal(health.engine,'original_browser');
        }catch(error){throw new Error(`${error.message}\n${logs}`,{cause:error});}
        finally{
            if(child&&child.exitCode===null&&child.signalCode===null){const exit=once(child,'exit');child.kill();await exit;}
            await rm(env.XDG_RUNTIME_DIR,{recursive:true,force:true});
        }
    });
}
