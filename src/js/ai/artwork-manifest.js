// SPDX-License-Identifier: AGPL-3.0-only
// One configurable identity/asset contract, shared with the local static server.
import manifest from '../../assets/characters/manifest.json?v=f29-candidates-1' with {type:'json'};
export const CHARACTER_MANIFEST=manifest;
export const EXPRESSIONS=Object.freeze([...manifest.expressions]);
export const ACTIVITIES=Object.freeze([...manifest.activities]);
export const MODEL_ARTWORK=manifest.models;
export const CHARACTERS=manifest.characters;
export const DEFAULT_CHARACTER=Object.freeze({name:'Your companion',expressions:{}});
// Character Builder: the active custom character on its model, set from model_selected.
let custom=null;
export function setCustomCharacter(model,character,origin){
    if(!model||!character){custom=null;return;}
    const src=character.portrait?.file&&/^[0-9a-f]{64}\.(png|jpg|webp)$/.test(character.portrait.file)&&origin?origin+'/character-art/'+character.portrait.file:null;
    custom={model,id:character.identity,character:{name:character.name,fit:character.portrait?.fit||'contain',position:character.portrait?.position||'50% 50%',
        // One portrait serves every expression until the builder supports expression sets.
        expressions:src?Object.fromEntries(manifest.expressions.map(e=>[e,src])):{}}};
}
export function customCharacter(){return custom;}
// Curated local files only. Never turn a catalog entry into a remote URL, query,
// decoded traversal or user-selected Player asset. Keep this contract in both hosts.
export function animationPath(value,format){
    return typeof value==='string'&&['webm','mp4'].includes(format)&&
        new RegExp('^/Character_Art/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\\.'+format+'$').test(value)?value:null;
}
export function resolveArtwork(model,expression='neutral',catalog=CHARACTER_MANIFEST) {
    const own=catalog===CHARACTER_MANIFEST&&custom&&model===custom.model;
    const id=own?custom.id:Object.hasOwn(catalog.models,model||'')?catalog.models[model]:null;
    const character=own?custom.character:id&&Object.hasOwn(catalog.characters,id)?catalog.characters[id]:DEFAULT_CHARACTER;
    const requested=EXPRESSIONS.includes(expression)?expression:'neutral';
    const candidates=[{src:character.expressions?.[requested],expression:requested},{src:character.expressions?.neutral,expression:'neutral'}];
    const sources=candidates.filter((x,i,a)=>x.src&&a.findIndex(y=>y.src===x.src)===i);
    // Custom overrides intentionally have no animation capability. Their existing
    // image/package contract is unchanged, even on a model with built-in clips.
    const clips=own?null:character.animations?.[requested];
    const animations=['webm','mp4'].flatMap(format=>{
        const src=animationPath(clips?.[format],format);
        return src?[{src,expression:requested,type:'video',format,
            mime:format==='webm'?'video/webm; codecs="vp9"':'video/mp4; codecs="avc1.42E01E"'}]:[];
    });
    return {id:id||'generic',name:character.name,expression:requested,fit:character.fit==='cover'?'cover':'contain',position:character.position||'50% 50%',
        src:sources[0]?.src||null,sources:sources.map(x=>x.src),candidates:sources,
        animations:catalog.presentation?.animated_characters_enabled===true?animations:[]};
}
