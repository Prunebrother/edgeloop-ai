// SPDX-License-Identifier: AGPL-3.0-only
import {CHARACTER_MANIFEST,ACTIVITIES,resolveArtwork} from './artwork-manifest.js';
const title=s=>s[0].toUpperCase()+s.slice(1);
// Presentation only: one pending asset, two layers, at most two video decoders
// during a handoff. No Player, observation, AI or card imports/callbacks.
export class CharacterPresentation {
    constructor(host,manifest=CHARACTER_MANIFEST) {
        Object.assign(this,{host,manifest,revision:0,model:null,expression:'neutral',activity:'disconnected',identity:null,key:null,timer:null,pending:null,destroyed:false,failures:new Set()});
        host.innerHTML=`<header class="companion-heading"><div><p class="eyebrow">Character</p><h2 data-character-name>Your companion</h2><span class="character-header-status" data-character-activity>Disconnected</span></div><span class="expression" data-expression>Neutral</span></header>
          <div class="portrait-stage"><div class="portrait-placeholder"><div class="portrait-orbit" aria-hidden="true">✧</div><p>A space for your companion.</p><span>Choose a character model in Chat</span></div><div data-art-layers></div></div>
          <footer class="character-caption"><div class="character-presence"><span data-character-model>No model selected</span></div><p data-art-status></p></footer>`;
        this.stage=host.querySelector('.portrait-stage');
        this.layers=host.querySelector('[data-art-layers]');
        this.motion=matchMedia('(prefers-reduced-motion: reduce)');
        this.policyChanged=()=>{if(!this.destroyed)this.update();};
        this.hide=()=>{this.suspended=true;this.policyChanged();};
        this.show=()=>{this.suspended=false;this.policyChanged();};
        document.addEventListener('visibilitychange',this.policyChanged);
        document.addEventListener('fullscreenchange',this.policyChanged);
        window.addEventListener('pagehide',this.hide);
        window.addEventListener('pageshow',this.show);
        this.motion.addEventListener('change',this.policyChanged);
        this.intersection=new IntersectionObserver(entries=>{
            this.intersecting=entries.at(-1).isIntersecting;this.policyChanged();
        });this.intersection.observe(this.stage);
        this.resize=new ResizeObserver(this.policyChanged);this.resize.observe(this.stage);
        this.attributes=new MutationObserver(this.policyChanged);
        this.attributes.observe(host,{attributes:true,attributeFilter:['style','class','hidden','data-presentation-occluded']});
        this.update();
    }
    visible(){
        const rect=this.stage.getBoundingClientRect();
        return !this.suspended&&this.host.dataset.presentationOccluded!=='true'&&!document.hidden&&!this.motion.matches&&this.intersecting!==false&&
            (!document.fullscreenElement||document.fullscreenElement.contains(this.stage))&&
            this.stage.getClientRects().length>0&&getComputedStyle(this.stage).visibility!=='hidden'&&
            rect.width>0&&rect.height>0&&rect.bottom>0&&rect.right>0&&rect.top<innerHeight&&rect.left<innerWidth;
    }
    setModel(model){this.setState({model});}
    setState(state={}) {
        if(Object.hasOwn(state,'model'))this.model=state.model;
        if(state.expression)this.expression=state.expression;
        if(ACTIVITIES.includes(state.activity))this.activity=state.activity;
        this.update();
    }
    dispose(node){
        if(!node)return;
        clearTimeout(node.readyTimer);node.onload=node.onerror=null;
        if(node.tagName==='VIDEO'){
            node.onloadeddata=node.onplaying=null;
            if(node.frameId!=null)node.cancelVideoFrameCallback?.(node.frameId);
            if(node.frameFallback!=null)cancelAnimationFrame(node.frameFallback);
            node.pause();node.removeAttribute('src');node.removeAttribute('poster');node.load();
        }else node.removeAttribute('src');
        node.remove();
    }
    prune(keep=null){for(const node of [...this.layers.children])if(node!==keep)this.dispose(node);}
    failKey(candidate){return candidate.expression+':'+candidate.src;}
    update(){
        if(this.destroyed)return;
        const view=resolveArtwork(this.model,this.expression,this.manifest),host=this.host;
        host.querySelector('[data-character-name]').textContent=view.name;
        host.querySelector('[data-expression]').textContent=title(view.expression);
        host.querySelector('[data-character-model]').textContent=this.model||'No model selected';
        host.querySelector('[data-character-activity]').textContent=title(this.activity);
        host.dataset.character=view.id;host.dataset.expression=view.expression;host.dataset.activity=this.activity;
        const animate=this.manifest.presentation?.animated_characters_enabled===true&&this.visible();
        host.dataset.animated=String(animate);
        const candidates=[...(animate?view.animations:[]),...view.candidates.map(c=>({...c,type:'image'}))];
        const key=JSON.stringify([view.id,candidates.map(c=>[c.src,c.type]),view.fit,view.position]);
        if(this.key===key){
            if(!this.pending){
                if(this.displayed)this.loadedExpression=candidates.find(c=>c.src===this.displayed.getAttribute('src'))?.expression||this.loadedExpression;
                this.status(view);
            }
            return;
        }
        this.key=key;const revision=++this.revision;clearTimeout(this.timer);
        this.dispose(this.pending);this.pending=null;
        // Retain the same identity during loading, but never another character.
        if(this.identity!==view.id){
            this.prune();this.displayed=null;this.loadedExpression=null;
            host.dataset.artworkType='';host.dataset.artworkSource='';
        }
        else this.prune(this.displayed);
        // Hidden/reduced-motion portraits must stop immediately, before PNG decode.
        if(!animate&&this.displayed?.tagName==='VIDEO')this.displayed.pause();
        this.identity=view.id;
        host.querySelector('.portrait-placeholder').hidden=!!this.displayed;
        host.dataset.renderedExpression=this.displayed?this.loadedExpression||'':'';
        host.dataset.artworkStatus='loading';host.querySelector('[data-art-status]').textContent='Loading portrait…';
        this.load(view,candidates,0,revision,animate);
    }
    status(view){
        if(!this.displayed)return;
        const fallback=this.loadedExpression!==view.expression;
        this.host.dataset.artworkStatus=fallback?'fallback':'intended';
        this.host.querySelector('[data-art-status]').textContent=fallback?'Neutral portrait · expression artwork unavailable':'';
        this.host.dataset.renderedExpression=this.loadedExpression;
        this.host.dataset.artworkType=this.displayed.tagName==='VIDEO'?'video':'image';
        this.host.dataset.artworkSource=this.displayed.getAttribute('src')||'';
        const label=view.name+' · '+title(this.loadedExpression);
        if(this.displayed.tagName==='VIDEO')this.displayed.setAttribute('aria-label',label);
        else this.displayed.alt=label;
    }
    load(view,candidates,index,revision,animate){
        if(this.destroyed||revision!==this.revision)return;
        const candidate=candidates[index];
        if(!candidate){
            this.pending=null;this.prune();this.displayed=null;this.loadedExpression=null;
            this.host.querySelector('.portrait-placeholder').hidden=false;
            this.host.querySelector('[data-art-status]').textContent='Portrait unavailable';
            Object.assign(this.host.dataset,{artworkStatus:'unavailable',renderedExpression:'',artworkType:'',artworkSource:''});return;
        }
        if(candidate.type==='video'&&this.failures.has(this.failKey(candidate)))return this.load(view,candidates,index+1,revision,animate);
        const node=candidate.type==='video'?document.createElement('video'):new Image();
        node.className='character-art';node.style.objectFit=view.fit;node.style.objectPosition=view.position;
        const current=()=>!this.destroyed&&revision===this.revision;
        let committed=false,settled=false,frameScheduled=false;
        const fail=()=>{
            if(!current()||settled)return;
            settled=true;
            if(candidate.type==='video'){
                this.failures.add(this.failKey(candidate));
                if(this.failures.size>64)this.failures.delete(this.failures.values().next().value);
            }
            if(this.pending===node)this.pending=null;
            // A displayed video can fail later too. Keep its last frame until the
            // replacement is ready. Drop any older fading layer before preparing
            // another video, preserving the two-decoder limit even mid-transition.
            if(committed&&node.tagName==='VIDEO'){
                clearTimeout(this.timer);this.prune(node);node.pause();node.onerror=null;
            }else this.dispose(node);
            this.load(view,candidates,index+1,revision,animate);
        };
        const ready=()=>{
            if(!current()||settled||committed)return;
            committed=true;clearTimeout(node.readyTimer);
            if(node.frameId!=null)node.cancelVideoFrameCallback?.(node.frameId);
            if(node.frameFallback!=null)cancelAnimationFrame(node.frameFallback);
            if(!animate&&this.displayed?.tagName==='VIDEO'){
                node.style.transition='none';node.classList.add('visible');
                this.dispose(this.displayed);this.displayed=null;
            }
            this.pending=null;this.prune(this.displayed);
            this.displayed=node;this.loadedExpression=candidate.expression;
            this.layers.append(node);this.host.querySelector('.portrait-placeholder').hidden=true;
            this.status(view);
            requestAnimationFrame(()=>{if(current())node.classList.add('visible');});
            this.timer=setTimeout(()=>{if(current())this.prune(node);},animate&&!this.motion.matches?380:280);
        };
        node.onerror=fail;this.pending=node;
        if(candidate.type==='image'){
            node.decoding='async';node.alt=view.name+' · '+title(candidate.expression);
            node.onload=async()=>{try{await node.decode();}catch{}ready();};
        }else{
            node.muted=true;node.defaultMuted=true;node.loop=true;node.playsInline=true;node.preload='auto';
            node.setAttribute('aria-label',view.name+' · '+title(candidate.expression));
            if(view.src)node.poster=view.src;
            if(!node.canPlayType(candidate.mime)){this.dispose(node);this.pending=null;return this.load(view,candidates,index+1,revision,animate);}
            const firstFrame=()=>{
                if(!current()||settled||frameScheduled)return;
                frameScheduled=true;
                if(node.requestVideoFrameCallback)node.frameId=node.requestVideoFrameCallback(ready);
                // Detached video can decode without submitting frames to the
                // compositor, so its video-frame callback need not fire yet.
                // loadeddata + successful play + HAVE_CURRENT_DATA guarantees
                // a decoded first frame; admit it on the next paint if needed.
                node.frameFallback=requestAnimationFrame(()=>{
                    if(!current()||settled)return;
                    if(node.readyState>=2)ready();
                    else{frameScheduled=false;node.onloadeddata=firstFrame;}
                });
            };
            node.readyTimer=setTimeout(fail,6000);
            node.onloadeddata=()=>{if(current()&&!settled)node.play().then(firstFrame,fail);};
        }
        node.src=candidate.src;
    }
    destroy(){
        if(this.destroyed)return;
        this.destroyed=true;++this.revision;clearTimeout(this.timer);
        this.dispose(this.pending);this.pending=null;this.prune();this.displayed=null;
        this.intersection.disconnect();this.resize.disconnect();this.attributes.disconnect();
        this.motion.removeEventListener('change',this.policyChanged);
        document.removeEventListener('visibilitychange',this.policyChanged);
        document.removeEventListener('fullscreenchange',this.policyChanged);
        window.removeEventListener('pagehide',this.hide);
        window.removeEventListener('pageshow',this.show);
        this.host.replaceChildren();
    }
}
export function mountExpressionPreview(host,controller){
    if(!['127.0.0.1','localhost'].includes(location.hostname)||new URLSearchParams(location.search).get('characterPreview')!=='1')return;
    const controls=document.createElement('details');controls.className='character-preview';
    controls.innerHTML='<summary>Artwork preview · development</summary><p>Visual only; does not select an AI model.</p><label>Character<select data-preview-character></select></label><label>Expression<select data-preview-expression></select></label><label>Activity<select data-preview-activity></select></label><output data-preview-result role="status" aria-live="polite"></output><button type="button" data-preview-reset>Return to conversation</button>';
    host.append(controls);
    const result=controls.querySelector('[data-preview-result]');
    const updateResult=()=>{const labels={loading:'Loading portrait',intended:'Intended portrait',fallback:'Fallback portrait',unavailable:'Generic placeholder'};result.textContent=title(host.dataset.expression||'neutral')+' · '+(labels[host.dataset.artworkStatus]||'Loading portrait')+(host.dataset.renderedExpression?' ('+title(host.dataset.renderedExpression)+')':'');};
    const observer=new MutationObserver(updateResult);observer.observe(host,{attributes:true,attributeFilter:['data-artwork-status','data-rendered-expression','data-expression']});updateResult();
    const fill=(key,values)=>{const select=controls.querySelector('[data-preview-'+key+']');for(const [value,label]of values){const option=document.createElement('option');option.value=value;option.textContent=label;select.append(option);}return select;};
    const characters=fill('character',Object.entries(CHARACTER_MANIFEST.characters).map(([id,c])=>[id,c.name]));
    const expressions=fill('expression',CHARACTER_MANIFEST.expressions.map(e=>[e,title(e)]));
    const activities=fill('activity',ACTIVITIES.map(a=>[a,title(a)]));
    const change=()=>controller.preview({model:Object.keys(CHARACTER_MANIFEST.models).find(m=>CHARACTER_MANIFEST.models[m]===characters.value),expression:expressions.value,activity:activities.value});
    for(const select of [characters,expressions,activities])select.onchange=change;
    controls.querySelector('[data-preview-reset]').onclick=()=>{controller.preview();controls.open=false;};
    controls.ontoggle=()=>{if(controls.open)change();else controller.preview();};
    return ()=>observer.disconnect();
}
