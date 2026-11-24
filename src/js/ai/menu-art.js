// SPDX-License-Identifier: AGPL-3.0-only
// Menu art and host greetings. Curated local files only (src/assets/menu, see MODELS_AND_ASSETS.md);
// the static servers admit nothing else from that folder.
const BASE='/src/assets/menu/';

export const MENU_ART=Object.freeze({
    backdrop:BASE+'backdrop.webp',
    mark:BASE+'mark.svg',
    wordmark:BASE+'wordmark.svg',
});

// Companion cut-outs of the app's own portraits: the full figure for the host and the mission board,
// a face crop for the host chips.
export const COMPANION_ORDER=Object.freeze(['nova','evelyn','daisy','celeste','mira','vex9','iris','seraphine']);
export const figure=id=>COMPANION_ORDER.includes(id)?`${BASE}companions/${id}.webp`:null;
export const face=id=>COMPANION_ORDER.includes(id)?`${BASE}companions/${id}-face.webp`:null;

// Key art per campaign and per chapter number. A campaign without art falls back to the plain backdrop.
const CAMPAIGN_ART={
    asterion_initiative:{key:'key.webp',chapters:{1:'chapter-1.webp',2:'chapter-2.webp',3:'chapter-3.webp',4:'chapter-4.webp'}},
    rise_of_helix:{story:true},
};
export function campaignArt(campaign){
    const art=Object.hasOwn(CAMPAIGN_ART,campaign)?CAMPAIGN_ART[campaign]:null;
    return art?.story?storyArt(campaign,'key_art'):art?`${BASE}campaigns/${campaign}/${art.key}`:null;
}
export function chapterArt(campaign,number){
    const art=Object.hasOwn(CAMPAIGN_ART,campaign)?CAMPAIGN_ART[campaign]:null;
    if(art?.story)return storyArt(campaign,`chapter_${number}_splash`);
    const file=art&&Object.hasOwn(art.chapters,number)?art.chapters[number]:null;
    return file?`${BASE}campaigns/${campaign}/${file}`:null;
}

// The main menu host greets the player with one of her scripted lines (never model output).
// Approved by the author 2026-11-19.
export const GREETINGS=Object.freeze({
    nova:['Hey, partner! Systems are warm and so am I. What are we doing tonight?',
        'Welcome back. I kept the lights low and the coffee hypothetical.',
        'Story, freeplay or just a chat? I’m in for all three.'],
    evelyn:['You’re right on time. I appreciate that more than you know.',
        'My notes are ready. Are you?',
        'Sit down. Let’s see what your numbers have to say tonight.'],
    daisy:['Well, hey there, sugar! Pull up a chair, the night’s young.',
        'There you are! I was startin’ to think you’d forgotten about me.',
        'Boots off, feet up. What’ll it be tonight?'],
    celeste:['You are expected. Choose, and do not keep me waiting.',
        'Good evening. I trust you are ready to perform.',
        'The Initiative does not rest. Neither, I suspect, do you.'],
    mira:['Back already, darling? I was just getting comfortable.',
        'Don’t mind me. I’m only here for the view.',
        'Pick something fun. I get bored so easily.'],
    vex9:['RPU-001. You are four minutes later than projected. Noted.',
        'Select a procedure. Hesitation is an inefficiency.',
        'Stand straight, Specimen. The protocol is ready. Are you?'],
    // Iris: approved by the author 2026-11-20.
    iris:['Oh! You’re here. Hello. I had a whole greeting prepared, and it’s gone.',
        'I read your file again. Twice. What would you like to do tonight?',
        'Story, freeplay, or we could just talk? Any of them. Sorry, I mean, all of them sound good.'],
    // Seraphine: approved by the author 2026-11-23.
    seraphine:['There you are, darling. I was beginning to think you’d found somewhere better to be. You haven’t.',
        'Sit with me a moment, sweetheart. Then tell me how you’d like to spend my evening.',
        'Story, freeplay or simply my company? Choose, darling. I’ll make it worth your while.'],
});


// Story registries are loaded on demand; absent/invalid art uses the caller's neutral fallback.
const STORY_BASE='/src/assets/story/';
const STORY_ID=/^[a-z0-9][a-z0-9_-]*$(?![\s\S])/;
const storyRegistries=new Map();
export async function loadStoryRegistry(campaign){
    if(typeof campaign!=='string'||!STORY_ID.test(campaign))return null;
    if(!storyRegistries.has(campaign)){
        storyRegistries.set(campaign,(async()=>{
            try{
                const response=await fetch(`${STORY_BASE}${campaign}/ASSETS.json`,{cache:'no-cache'});
                if(!response.ok)return null;
                const registry=await response.json();
                if(!registry||registry.schema_version!==1||registry.campaign!==campaign||
                    !registry.slots||typeof registry.slots!=='object'||Array.isArray(registry.slots))return null;
                const slots=Object.create(null);
                for(const [slot,item] of Object.entries(registry.slots)){
                    if(STORY_ID.test(slot)&&item&&typeof item.file==='string'&&/^[a-z0-9][a-z0-9_-]*\.webp$(?![\s\S])/.test(item.file)){
                        slots[slot]=Object.freeze({file:item.file});
                    }
                }
                return Object.freeze({schema_version:1,campaign,slots:Object.freeze(slots)});
            }catch{return null;}
        })().then(registry=>{
            storyRegistries.set(campaign,registry);
            return registry;
        }));
    }
    return await storyRegistries.get(campaign);
}
export function storyArt(campaign,slot){
    if(typeof campaign!=='string'||!STORY_ID.test(campaign)||typeof slot!=='string'||!STORY_ID.test(slot))return null;
    const registry=storyRegistries.get(campaign);
    const item=registry?.slots&&Object.hasOwn(registry.slots,slot)?registry.slots[slot]:null;
    return item?`${STORY_BASE}${campaign}/${item.file}`:null;
}
