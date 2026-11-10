// SPDX-License-Identifier: AGPL-3.0-only
import test from 'node:test';import assert from 'node:assert/strict';
import {createPlayerInteractions,mediaTitle} from './interactions.js';
test('only explicit closed-to-open workspace transitions count',()=>{
 const p=createPlayerInteractions();p.workspace(true);assert.equal(p.snapshot().opened,0);
 p.workspace(false);p.workspace(true,true);p.workspace(true,true);assert.equal(p.snapshot().opened,1);
 p.workspace(false);p.workspace(true,true);assert.equal(p.snapshot().opened,2);
});
test('title labels lose directories, URLs, extensions and invisible controls',()=>{
 for(const name of ['/private/users/a/Aladdin.mp4','C:\\private\\Aladdin.MP4','https://example.test/private/Aladdin.mp4?token=SECRET','/a/hidden%2fAladdin.mp4'])assert.deepEqual(mediaTitle(name),{title:'Aladdin',title_source:'filename'});
 assert.deepEqual(mediaTitle('movie.webm','Verified Title'),{title:'Verified Title',title_source:'metadata'});
 assert.equal(mediaTitle('My_Movie\u0000.webm').title,'My Movie');assert.equal(mediaTitle('').title,null);
 assert.equal(mediaTitle('a'.repeat(200)).title.length,160);
});
test('same media reload, buffering, seeking and resume do not start another viewing',()=>{
 const p=createPlayerInteractions();p.select('file-a','Aladdin.mp4');p.playing();p.paused();p.playing();p.select('file-a','Aladdin.mp4');p.playing();
 assert.equal(p.snapshot().selected,1);assert.equal(p.snapshot().started,1);
 p.ended();p.playing();assert.equal(p.snapshot().started,2);
 p.select('file-b','Other.webm');p.playing();assert.equal(p.snapshot().selected,2);assert.equal(p.snapshot().started,3);
});
test('observer failures and mutated snapshots cannot affect the owner',()=>{
 const p=createPlayerInteractions({notify(){throw Error('offline');}});p.select('a','A.webm');const s=p.snapshot();s.started=99;assert.equal(p.snapshot().started,0);
});
test('title truncation preserves complete Unicode characters',()=>{
 assert.equal(mediaTitle('🎬'.repeat(200)).title,'🎬'.repeat(160));
});
