// SPDX-License-Identifier: AGPL-3.0-only
import {CHARACTER_MANIFEST,ACTIVITIES,resolveArtwork} from './artwork-manifest.js';
const title=s=>s[0].toUpperCase()+s.slice(1);
// Renderer only: at most two visible layers and one in-flight image, no preload loop.
export class CharacterPresentation {
    constructor(host,manifest=CHARACTER_MANIFEST) {
        Object.assign(this,{host,manifest,revision:0,model:null,expression:'neutral',activity:'disconnected',identity:null,key:null,timer:null,pending:null});
        host.innerHTML=`<header class="companion-heading"><div><p class="eyebrow">Character</p><h2 data-character-name>Your companion</h2><span class="character-header-status" data-character-activity>Disconnected</span></div><span class="expression" data-expression>Neutral</span></header>
          <div class="portrait-stage"><div class="portrait-placeholder"><div class="portrait-orbit" aria-hidden="true">✧</div><p>A space for your companion.</p><span>Choose a character model in Chat</span></div><div data-art-layers></div></div>
          <footer class="character-caption"><div class="character-presence"><span data-character-model>No model selected</span></div><p data-art-status></p></footer>`;
        this.update();
    }
    setModel(model){this.setState({model});}
    setState(state={}) {
        if(Object.hasOwn(state,'model'))this.model=state.model;
        if(state.expression)this.expression=state.expression;
        if(ACTIVITIES.includes(state.activity))this.activity=state.activity;
        this.update();
    }
    update(){
        const view=resolveArtwork(this.model,this.expression,this.manifest),host=this.host;
        host.querySelector('[data-character-name]').textContent=view.name;
        host.querySelector('[data-expression]').textContent=title(view.expression);
        host.querySelector('[data-character-model]').textContent=this.model||'No model selected';
        host.querySelector('[data-character-activity]').textContent=title(this.activity);
        host.dataset.character=view.id;host.dataset.expression=view.expression;host.dataset.activity=this.activity;
        const layers=host.querySelector('[data-art-layers]'),placeholder=host.querySelector('.portrait-placeholder'),status=host.querySelector('[data-art-status]');
        const key=JSON.stringify([view.id,view.sources,view.fit,view.position]);
        if(this.key===key){if(this.loadedExpression){status.textContent=this.loadedExpression!==view.expression?'Neutral portrait · expression artwork unavailable':'';host.dataset.artworkStatus=this.loadedExpression===view.expression?'intended':'fallback';}return;}
        this.key=key;const revision=++this.revision;clearTimeout(this.timer);
        if(this.pending){this.pending.onload=this.pending.onerror=null;this.pending.src='';this.pending=null;}
        // Never retain another character's image while its replacement loads.
        if(this.identity!==view.id){layers.replaceChildren();placeholder.hidden=false;this.displayed=null;this.displayedExpression=null;}
        else if(this.displayed)layers.replaceChildren(this.displayed);
        this.identity=view.id;this.loadedExpression=null;host.dataset.renderedExpression=this.displayed?this.displayedExpression||'':'';
        if(!view.src){layers.replaceChildren();placeholder.hidden=false;status.textContent='Portrait unavailable';host.dataset.artworkStatus='unavailable';return;}
        status.textContent='Loading portrait…';host.dataset.artworkStatus='loading';let index=0;
        const img=new Image();this.pending=img;img.className='character-art';img.decoding='async';
        img.style.objectFit=view.fit;img.style.objectPosition=view.position;
        img.onload=async()=>{
            try{await img.decode();}catch{} // Decode asynchronously; never await it from chat.
            if(revision!==this.revision)return;
            this.pending=null;this.displayed=img;this.loadedExpression=view.candidates[index].expression;this.displayedExpression=this.loadedExpression;
            host.dataset.artworkStatus=this.loadedExpression===view.expression?'intended':'fallback';host.dataset.renderedExpression=this.loadedExpression;
            img.alt=view.name+' · '+title(this.loadedExpression);placeholder.hidden=true;
            // Drop an earlier outgoing layer before starting another transition.
            while(layers.children.length>1)layers.firstElementChild.remove();
            layers.append(img);status.textContent=this.loadedExpression!==view.expression?'Neutral portrait · expression artwork unavailable':'';
            requestAnimationFrame(()=>{if(revision===this.revision)img.classList.add('visible');});
            this.timer=setTimeout(()=>{if(revision===this.revision)layers.replaceChildren(img);},280);
        };
        img.onerror=()=>{if(revision!==this.revision)return;
            const fallback=view.candidates[++index];if(fallback)img.src=fallback.src;
            else{this.pending=null;this.displayed=null;this.displayedExpression=null;layers.replaceChildren();placeholder.hidden=false;status.textContent='Portrait unavailable';host.dataset.artworkStatus='unavailable';host.dataset.renderedExpression='';}
        };
        img.src=view.src;
    }
    destroy(){++this.revision;clearTimeout(this.timer);if(this.pending){this.pending.onload=this.pending.onerror=null;this.pending.src='';}this.host.replaceChildren();}
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
