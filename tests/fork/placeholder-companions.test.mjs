// SPDX-License-Identifier: AGPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import {CHARACTERS,EXPRESSIONS,resolveArtwork} from '../../src/js/ai/artwork-manifest.js';
import {COMPANION_ORDER} from '../../src/js/ai/menu-art.js';
test('seraphine is a real companion and menu host: her model resolves her approved art and idle clip per expression',()=>{
    assert.equal(CHARACTERS.seraphine.status,undefined);assert.equal(CHARACTERS.seraphine.name,'Seraphine Vale');
    assert.equal(COMPANION_ORDER.includes('seraphine'),true);
    for(const expression of EXPRESSIONS){
        const art=resolveArtwork('seraphine-narrative-f29-v019:latest',expression);
        assert.equal(art.id,'seraphine');assert.equal(art.src,`/Character_Art/Seraphine/expressions/seraphine_${expression}.png`);
        assert.equal(art.animations[0]?.src,`/Character_Art/Seraphine/animations/seraphine_${expression}.webm`);
    }
});
test('iris is a real companion: her model resolves her approved art and idle clip per expression',()=>{
    assert.equal(CHARACTERS.iris.status,undefined);assert.equal(CHARACTERS.iris.name,'Iris Vale');
    for(const expression of EXPRESSIONS){
        const art=resolveArtwork('iris-narrative-f29-v018:latest',expression);
        assert.equal(art.id,'iris');assert.equal(art.src,`/Character_Art/Iris/expressions/iris_${expression}.png`);
        assert.equal(art.animations[0]?.src,`/Character_Art/Iris/animations/iris_${expression}.webm`);
    }
});
