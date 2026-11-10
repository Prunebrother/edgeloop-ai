// SPDX-License-Identifier: AGPL-3.0-only
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {resolveArtwork,setCustomCharacter,EXPRESSIONS} from '../../src/js/ai/artwork-manifest.js';
const base='huihui_ai/qwen3.5-abliterated:9b',sha='a'.repeat(64);
const wren={identity:'custom.wren-calloway',name:'Wren Calloway',portrait:{file:sha+'.png',fit:'cover',position:'40% 20%'}};
test('a custom character owns its model only while active and serves one portrait for every expression',()=>{
    try{
        assert.equal(resolveArtwork(base).id,'generic');
        setCustomCharacter(base,wren,'http://127.0.0.1:8768');
        for(const e of EXPRESSIONS){const v=resolveArtwork(base,e);assert.equal(v.id,'custom.wren-calloway');assert.equal(v.name,'Wren Calloway');assert.equal(v.src,'http://127.0.0.1:8768/character-art/'+sha+'.png');assert.equal(v.expression,e);}
        assert.equal(resolveArtwork(base).fit,'cover');assert.equal(resolveArtwork(base).position,'40% 20%');
        // Other models and explicit catalogs are untouched.
        assert.equal(resolveArtwork('daisy-qwen35:latest').id,'daisy');
        assert.equal(resolveArtwork(base,'neutral',{models:{},characters:{}}).id,'generic');
        setCustomCharacter(base,null);assert.equal(resolveArtwork(base).id,'generic');
    }finally{setCustomCharacter(null,null);}
});
test('a custom portrait name that is not a content hash is never turned into a URL',()=>{
    try{
        for(const file of ['../selection.json','x.png',sha+'.svg','https://example.com/'+sha+'.png']){
            setCustomCharacter(base,{...wren,portrait:{file}},'http://127.0.0.1:8768');assert.equal(resolveArtwork(base).src,null,file);
        }
        setCustomCharacter(base,{...wren,portrait:null},'http://127.0.0.1:8768');assert.equal(resolveArtwork(base).src,null);
        assert.equal(resolveArtwork(base).name,'Wren Calloway');
    }finally{setCustomCharacter(null,null);}
});
import {preservedConditions,MAX_CARDS,SIZE_HELP} from '../../src/js/ai/character-builder.js';
import {messageBytes,MESSAGE_LIMIT_BYTES} from '../../src/js/ai/connection.js';
test('conditions the editor cannot edit are named so the player knows they are kept',()=>{
    assert.deepEqual(preservedConditions({}),[]);
    assert.deepEqual(preservedConditions({statuses:['RUNNING','RAMPDOWN'],requires_hr:false,hr_trends:null,requires_story_welcome:false}),[]);
    assert.deepEqual(preservedConditions({requires_hr:true,hr_trends:['rising'],requires_story_welcome:true,statuses:['RAMPDOWN']}),
        ['needs a live heart rate (rising)','only when story is welcome','only while rampdown']);
});
test('limits are the observer limits, counted in UTF-8 bytes',()=>{
    assert.equal(MAX_CARDS,16);assert.equal(MESSAGE_LIMIT_BYTES,16384);
    assert.equal(messageBytes('abc'),3);assert.equal(messageBytes('ž'),2);assert.equal(messageBytes('🌊'),4);
    assert.match(SIZE_HELP,/before the deck has 16 cards/);
});
