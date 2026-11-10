// SPDX-License-Identifier: AGPL-3.0-only
// Browser fixtures never attach to a running EdgeLoop stack and fail closed when
// their own servers cannot start (2026-11-05 incident: browser.mjs defaulted to the
// desktop ports and its headless page paired with the live observer).
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {spawn,spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {chromium} from 'playwright';
import {LIVE_PORTS,claimPorts,ownedReady,isolatedEnv,blockedUrl,guardBrowser} from './fixture-isolation.mjs';

const root=path.resolve(new URL('../..',import.meta.url).pathname);
const SUITES=['browser','upstream-sync-browser','player-workspace-browser','player-interactions-browser','character-browser','character-menus-browser','narrative-browser',
    'desktop-launcher-browser','context-intelligence-browser','event-intelligence-browser','session-journal-browser','event-reliability'];

// A stand-in for a running stack: answers every request with 200 and counts them.
async function liveStandIn(){
    const requests=[];
    const server=http.createServer((req,res)=>{requests.push(req.url);res.writeHead(200,{'Content-Type':'text/html'});res.end('<p>live</p>');});
    await new Promise(r=>server.listen(0,'127.0.0.1',r));
    return {server,port:server.address().port,requests,close:()=>new Promise(r=>server.close(r))};
}

test('live desktop ports are refused without connecting', async()=>{
    for(const port of LIVE_PORTS)await assert.rejects(claimPorts(port),/live EdgeLoop desktop stack/);
    await assert.rejects(claimPorts('not-a-port'),/Invalid fixture port/);
});

test('an occupied port is refused and receives no HTTP request', async()=>{
    const live=await liveStandIn();
    try{
        await assert.rejects(claimPorts(live.port),/already in use/);
        assert.deepEqual(live.requests,[]);
    }finally{await live.close();}
});

test('a free port is accepted', async()=>{
    const live=await liveStandIn();const port=live.port;await live.close();
    await claimPorts(port);
});

test('a fixture that exits is never replaced by whatever answers on its port', async()=>{
    const live=await liveStandIn();
    try{
        // Same shape as a fixture server that cannot bind: it exits immediately.
        const child=spawn(process.execPath,['-e','process.exit(3)'],{stdio:'ignore'});
        await new Promise(r=>child.once('exit',r));
        await assert.rejects(ownedReady(`http://127.0.0.1:${live.port}/`,[child],{attempts:5,interval:10}),/exited before/);
    }finally{await live.close();}
});

test('a live fixture process is ready once its server answers', async()=>{
    const live=await liveStandIn();
    const child=spawn(process.execPath,['-e','setTimeout(()=>{},60000)'],{stdio:'ignore'});
    try{await ownedReady(`http://127.0.0.1:${live.port}/`,[child],{attempts:20,interval:10});}
    finally{child.kill();await live.close();}
});

test('fixture children get no live pairing, data or runtime locations', ()=>{
    const saved={...process.env};
    Object.assign(process.env,{EDGELOOP_PAIRING_FILE:'/run/user/1000/edgeloop-ai/pairing.json',EDGELOOP_FORK_AI_DATA:'/live/.ai-data',OLLAMA_HOST:'127.0.0.1:11435',XDG_RUNTIME_DIR:'/run/user/1000'});
    try{
        const env=isolatedEnv();
        assert.equal(env.EDGELOOP_PAIRING_FILE,undefined);assert.equal(env.OLLAMA_HOST,undefined);
        assert.notEqual(env.EDGELOOP_FORK_AI_DATA,'/live/.ai-data');assert.notEqual(env.XDG_RUNTIME_DIR,'/run/user/1000');
        assert.ok(env.EDGELOOP_FORK_AI_DATA.startsWith(env.XDG_RUNTIME_DIR));
        assert.equal(isolatedEnv({EDGELOOP_PAIRING_FILE:'/tmp/own.json'}).EDGELOOP_PAIRING_FILE,'/tmp/own.json');
    }finally{for(const key of Object.keys(process.env))if(!(key in saved))delete process.env[key];Object.assign(process.env,saved);}
});

test('page requests outside the fixture ports are classified as blocked', ()=>{
    const allowed=new Set([8783,8793]);
    for(const url of ['http://127.0.0.1:8770/','ws://127.0.0.1:8768/observe','http://localhost:11435/api/tags','http://127.0.0.1:8850/','http://[::1]:8788/'])assert.ok(blockedUrl(url,allowed),url);
    for(const url of ['http://127.0.0.1:8783/index.html','ws://127.0.0.1:8793/observe','https://www.handyfeeling.com/api/handy/v2/connected','data:text/plain,x','blob:http://127.0.0.1:8783/x'])assert.ok(!blockedUrl(url,allowed),url);
    assert.ok(blockedUrl('http://127.0.0.1:8770/',new Set([8770])),'live ports stay blocked even when listed');
});

test('a guarded browser cannot reach a non-fixture port over HTTP or WebSocket', async()=>{
    const fixture=await liveStandIn(),outside=await liveStandIn();
    const browser=guardBrowser(await chromium.launch(),[fixture.port]);
    try{
        const page=await (await browser.newContext()).newPage();
        await page.goto(`http://127.0.0.1:${fixture.port}/`);
        const result=await page.evaluate(async port=>{
            const http=await fetch(`http://127.0.0.1:${port}/`).then(()=>'reached',()=>'blocked');
            const ws=await new Promise(resolve=>{const s=new WebSocket(`ws://127.0.0.1:${port}/observe`);s.onopen=()=>{};s.onclose=e=>resolve('closed:'+e.code);setTimeout(()=>resolve('timeout'),3000);});
            return {http,ws};
        },outside.port);
        assert.equal(result.http,'blocked');assert.match(result.ws,/^closed:/);
        assert.deepEqual(outside.requests,[],'outside server must see no request');
        assert.equal(browser.isolationViolations.length,2);
    }finally{await browser.close();await fixture.close();await outside.close();}
});

test('browser.mjs fails closed on an occupied port and never contacts it', async()=>{
    const live=await liveStandIn();
    try{
        const run=spawnSync(process.execPath,['tests/fork/browser.mjs'],{cwd:root,encoding:'utf8',timeout:60000,
            env:{...process.env,FORK_BROWSER_PORT:String(live.port),FORK_OBSERVER_PORT:'8794',FORK_BROWSER_REPORT:path.join(isolatedEnv().XDG_RUNTIME_DIR,'report')}});
        assert.equal(run.status,1,run.stdout+run.stderr);
        assert.match(run.stdout+run.stderr,/already in use/);
        assert.deepEqual(live.requests,[]);
    }finally{await live.close();}
});

test('browser.mjs refuses the live desktop ports when asked to use them', ()=>{
    const run=spawnSync(process.execPath,['tests/fork/browser.mjs'],{cwd:root,encoding:'utf8',timeout:60000,
        env:{...process.env,FORK_BROWSER_PORT:'8770',FORK_OBSERVER_PORT:'8768',FORK_BROWSER_REPORT:path.join(isolatedEnv().XDG_RUNTIME_DIR,'report')}});
    assert.equal(run.status,1);assert.match(run.stdout+run.stderr,/live EdgeLoop desktop stack/);
});

test('every fixture browser suite claims its ports, waits on its own processes and guards its pages', ()=>{
    for(const name of SUITES){
        const source=readFileSync(path.join(root,'tests/fork',name+'.mjs'),'utf8');
        assert.match(source,/from '\.\/fixture-isolation\.mjs'/,name);
        assert.match(source,/await claimPorts\(/,name);
        assert.match(source,/browser=guardBrowser\(await chromium\.launch\(\)/,name);
        assert.match(source,/return ownedReady\(url,/,name);
        assert.doesNotMatch(source,/await fetch\(url\)\)\.ok\)return/,name+' still polls without checking its children');
        assert.doesNotMatch(source,/\.\.\.process\.env/,name+' passes the live environment to fixtures');
        assert.doesNotMatch(source,/\|\|\s*'?(8770|8768|11435)\b/,name+' defaults to a live port');
        const claim=source.indexOf('await claimPorts('),first=source.search(/spawn\(/);
        assert.ok(claim>=0&&claim<first,name+' must claim ports before spawning');
    }
});
