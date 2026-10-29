// SPDX-License-Identifier: AGPL-3.0-only
// One configurable identity/asset contract, shared with the local static server.
import manifest from '../../assets/characters/manifest.json' with {type:'json'};
export const CHARACTER_MANIFEST=manifest;
export const EXPRESSIONS=Object.freeze([...manifest.expressions]);
export const ACTIVITIES=Object.freeze([...manifest.activities]);
export const MODEL_ARTWORK=manifest.models;
export const CHARACTERS=manifest.characters;
export const DEFAULT_CHARACTER=Object.freeze({name:'Your companion',expressions:{}});
export function resolveArtwork(model,expression='neutral',catalog=CHARACTER_MANIFEST) {
    const id=Object.hasOwn(catalog.models,model||'')?catalog.models[model]:null;
    const character=id&&Object.hasOwn(catalog.characters,id)?catalog.characters[id]:DEFAULT_CHARACTER;
    const requested=EXPRESSIONS.includes(expression)?expression:'neutral';
    const candidates=[{src:character.expressions?.[requested],expression:requested},{src:character.expressions?.neutral,expression:'neutral'}];
    const sources=candidates.filter((x,i,a)=>x.src&&a.findIndex(y=>y.src===x.src)===i);
    return {id:id||'generic',name:character.name,expression:requested,fit:character.fit==='cover'?'cover':'contain',position:character.position||'50% 50%',
        src:sources[0]?.src||null,sources:sources.map(x=>x.src),candidates:sources};
}
