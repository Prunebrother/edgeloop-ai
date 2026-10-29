// SPDX-License-Identifier: AGPL-3.0-only
// Pair only through the opt-in desktop server. Credentials stay in memory.
export async function pairDesktop(connection, enabled=()=>true, fetchImpl=globalThis.fetch) {
    try {
        const response=await fetchImpl('/ai/pair', {method:'POST', headers:{'X-EdgeLoop-Pair':'1'}, cache:'no-store', credentials:'same-origin'});
        if(!response.ok)return false;
        const pair=await response.json();
        if(!enabled()||connection.epoch||connection.socket)return false;
        if(!/^[0-9a-f-]{36}$/i.test(pair.browser_id)||typeof pair.token!=='string')return false;
        connection.browserId=pair.browser_id;
        connection.connect(pair.url,pair.token);
        return true;
    } catch {return false; /* Static/manual deployments remain independent. */}
}
