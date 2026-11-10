// SPDX-License-Identifier: AGPL-3.0-only
// In-memory notifications only. No media, engine or hardware commands.
export function mediaTitle(name='',metadataTitle=''){
    const metadata=typeof metadataTitle==='string'&&metadataTitle.trim();
    let value=metadata||String(name);
    if(!metadata){
        try{if(/^https?:\/\//i.test(value))value=new URL(value).pathname;}catch{value='';}
        value=value.replaceAll('\\','/').split('/').at(-1)||'';
        try{value=decodeURIComponent(value);}catch{}
        // Decoding may reveal separators too. Never send a path, URL query or fragment.
        value=value.replaceAll('\\','/').split('/').at(-1).split(/[?#]/)[0];
        value=value.replace(/\.(mp4|m4v|webm|mkv|mov|avi|ogv|ogg|wmv|mpeg|mpg|ts)$/i,'').replace(/[_]+/g,' ');
    }
    value=value.replace(/[\p{Cc}\p{Cf}]/gu,'').replace(/[\\/]/g,' ').replace(/\s+/g,' ').trim();
    value=[...value].slice(0,160).join('');
    return {title:value||null,title_source:value?(metadata?'metadata':'filename'):'unknown'};
}
export function createPlayerInteractions({uuid=()=>crypto.randomUUID(),notify=()=>{}}={}){
    const state={instance_id:uuid(),opened:0,selected:0,started:0,workspace_open:false,has_video:false,playing:false,title:null,title_source:'unknown'};
    let key=null,viewStarted=false;
    const emit=()=>{try{notify({...state});}catch{/* Optional observer never blocks the player. */}};
    return {
        snapshot:()=>({...state}),
        workspace(open,byUser=false){if(open&&!state.workspace_open&&byUser)state.opened++;state.workspace_open=open;emit();},
        select(nextKey,name,metadataTitle){
            if(nextKey===key)return;
            key=nextKey;viewStarted=false;state.has_video=nextKey!==null;state.playing=false;
            Object.assign(state,mediaTitle(name,metadataTitle));
            if(state.has_video)state.selected++;
            emit();
        },
        playing(){if(!state.has_video)return;state.playing=true;if(!viewStarted){state.started++;viewStarted=true;}emit();},
        paused(){state.playing=false;emit();},
        ended(){state.playing=false;viewStarted=false;emit();}
    };
}
