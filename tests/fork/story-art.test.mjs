// SPDX-License-Identifier: AGPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import {storyArt,loadStoryRegistry,campaignArt,chapterArt} from '../../src/js/ai/menu-art.js?story-art-tests';

test('story registry is lazy, cached and bounded to local webp references',async()=>{
    const original=globalThis.fetch;
    let calls=0;
    globalThis.fetch=async()=>{
        calls++;
        return {ok:true,json:async()=>({schema_version:1,campaign:'fixture',slots:{
            arrival:{file:'arrival.webp'},escape:{file:'../secret.webp'},remote:{file:'https://other/art.webp'},
        }})};
    };
    try{
        assert.equal(storyArt('fixture','arrival'),null);
        await Promise.all([loadStoryRegistry('fixture'),loadStoryRegistry('fixture')]);
        assert.equal(calls,1);
        assert.equal(storyArt('fixture','arrival'),'/src/assets/story/fixture/arrival.webp');
        for(const slot of ['escape','remote','unknown','toString'])assert.equal(storyArt('fixture',slot),null);
        assert.equal(await loadStoryRegistry('../bad'),null);
        assert.equal(storyArt('../bad','arrival'),null);
        assert.equal(storyArt('fixture','../arrival'),null);
    }finally{globalThis.fetch=original;}
});

test('fetch failure, HTTP error and malformed registry give neutral fallback',async()=>{
    const original=globalThis.fetch;
    try{
        for(const [campaign,result] of [['offline',()=>{throw Error('offline');}],
            ['http_error',()=>({ok:false})],['invalid',()=>({ok:true,json:async()=>({slots:[]})})]]){
            globalThis.fetch=async()=>result();
            assert.equal(await loadStoryRegistry(campaign),null);
            assert.equal(storyArt(campaign,'arrival'),null);
        }
    }finally{globalThis.fetch=original;}
});


test('Helix uses story key/splash slots while Asterion keeps its menu assets',async()=>{
    const original=globalThis.fetch;
    globalThis.fetch=async()=>({ok:true,json:async()=>({schema_version:1,campaign:'rise_of_helix',slots:{
        key_art:{file:'key_art.webp'},chapter_1_splash:{file:'chapter_1_splash.webp'},
    }})});
    try{
        assert.equal(campaignArt('rise_of_helix'),null);
        await loadStoryRegistry('rise_of_helix');
        assert.equal(campaignArt('rise_of_helix'),'/src/assets/story/rise_of_helix/key_art.webp');
        assert.equal(chapterArt('rise_of_helix',1),'/src/assets/story/rise_of_helix/chapter_1_splash.webp');
        assert.equal(chapterArt('rise_of_helix',2),null);
        assert.equal(campaignArt('asterion_initiative'),'/src/assets/menu/campaigns/asterion_initiative/key.webp');
        assert.equal(chapterArt('asterion_initiative',1),'/src/assets/menu/campaigns/asterion_initiative/chapter-1.webp');
        assert.equal(campaignArt('unknown'),null);
    }finally{globalThis.fetch=original;}
});
