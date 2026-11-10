// SPDX-License-Identifier: AGPL-3.0-only
// Fixture isolation for the browser suites. A suite must own the servers it tests:
// it never attaches to a running EdgeLoop desktop stack (page 8770, observer 8768,
// dedicated Ollama 11435), and it fails closed when its own servers cannot start.
import net from 'node:net';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';

export const LIVE_PORTS=Object.freeze([8768,8770,11435]);
const LOOPBACK=new Set(['127.0.0.1','localhost','[::1]','::1','0.0.0.0']);

// Refuse live ports outright and any port that already accepts connections.
export async function claimPorts(...ports){
    for(const raw of ports){
        const port=Number(raw);
        if(!Number.isInteger(port)||port<1||port>65535)throw new Error('Invalid fixture port: '+raw);
        if(LIVE_PORTS.includes(port))throw new Error(`Fixture port ${port} belongs to the live EdgeLoop desktop stack; choose another port.`);
        if(await listening(port))throw new Error(`Fixture port ${port} is already in use (live EdgeLoop stack or another test?). Nothing was attached; choose another port.`);
    }
}
function listening(port){
    return new Promise(resolve=>{
        const socket=net.connect({host:'127.0.0.1',port});
        const done=value=>{socket.destroy();resolve(value);};
        socket.setTimeout(500,()=>done(true));
        socket.once('connect',()=>done(true));
        socket.once('error',error=>done(error.code!=='ECONNREFUSED'));
    });
}

// Ready only while every spawned fixture process is still alive: a server that
// failed to bind exits, so whatever answers on its port is not the fixture.
export async function ownedReady(url,children,{attempts=100,interval=100}={}){
    for(let i=0;i<attempts;i++){
        const dead=children.find(child=>child.exitCode!==null||child.signalCode!==null);
        if(dead)throw new Error(`Fixture process exited before ${url} was ready (exit ${dead.exitCode??dead.signalCode}); refusing to use whatever else answers there.`);
        try{if((await fetch(url,{signal:AbortSignal.timeout(1000)})).ok){
            if(children.some(child=>child.exitCode!==null||child.signalCode!==null))continue;
            return;
        }}catch{}
        await new Promise(r=>setTimeout(r,interval));
    }
    throw new Error('Fixture server unavailable: '+url);
}

// Child environment without live pairing or data locations. Explicit overrides
// (for example a suite's own temporary pairing file) are applied last.
export function isolatedEnv(overrides={}){
    const env={...process.env};
    delete env.EDGELOOP_PAIRING_FILE;delete env.OLLAMA_HOST;
    const scratch=mkdtempSync(path.join(tmpdir(),'edgeloop-fixture-'));
    env.EDGELOOP_FORK_AI_DATA=path.join(scratch,'ai-data');
    env.XDG_RUNTIME_DIR=scratch;
    return {...env,...overrides};
}

// True when a page request would leave the fixture: any loopback port the suite
// does not own, and the live desktop ports in every case.
export function blockedUrl(raw,allowed){
    let url;try{url=new URL(raw);}catch{return false;}
    if(!/^(https?|wss?):$/.test(url.protocol)||!LOOPBACK.has(url.hostname))return false;
    const port=Number(url.port||({'http:':80,'ws:':80,'https:':443,'wss:':443})[url.protocol]);
    return LIVE_PORTS.includes(port)||!allowed.has(port);
}

// Every context created from this browser aborts requests and closes websockets
// that would reach a port outside the fixture. Contexts stay non-persistent.
export function guardBrowser(browser,ports,violations=[]){
    const allowed=new Set(ports.map(Number));
    const newContext=browser.newContext.bind(browser);
    browser.newContext=async(...args)=>{
        const context=await newContext(...args);
        await context.route(url=>blockedUrl(url.href,allowed),route=>{violations.push(route.request().url());return route.abort('blockedbyclient');});
        await context.routeWebSocket(url=>blockedUrl(url.href,allowed),ws=>{violations.push(ws.url());ws.close({code:1008,reason:'Outside test fixture'});});
        return context;
    };
    browser.isolationViolations=violations;
    return browser;
}
