// Gerçek çizim modülünü DOM/WebGL taklitleriyle çalıştırır; ağ, mikrofon ve model açmaz.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../webui/hologram.js'),'utf8');
function harness(webgl=true){
 let clock=0,id=0,mic=0,tone='blue',back='mountains',state='idle',still=false,calm=false,elapsed=0,deleted=0,restored=0;
 const queue=new Map(),uniforms={},images=[],logs=[];
 const pixels=new Uint8ClampedArray(200*200*4);
 for(let y=13;y<185;y++)for(let x=0;x<200;x++){const v=y/200,half=v<.55?.16:v<.70?.10:.40;if(Math.abs(x/200-.492)<half){const k=(y*200+x)*4;pixels[k]=35;pixels[k+1]=160;pixels[k+2]=220;pixels[k+3]=255}}
 const ctx=new Proxy({getImageData(){return {data:pixels.slice()}},createImageData(w,h){return {data:new Uint8ClampedArray(w*h*4)}},createRadialGradient(){return {addColorStop(){}}}}, {get(t,k){return k in t?t[k]:()=>{}}});
 const gl=new Proxy({getShaderParameter(){return true},getProgramParameter(){return true},getUniformLocation(p,n){return n},uniform1f(n,v){uniforms[n]=v},uniform2f(n,...v){uniforms[n]=v},uniform3f(n,...v){uniforms[n]=v},getExtension(){return {loseContext(){deleted++}}}}, {get(t,k){if(k in t)return t[k];if(k.startsWith('create'))return ()=>({});if(k.startsWith('delete'))return ()=>{deleted++};return /^[A-Z_]+$/.test(k)?1:()=>{}}});
 class El{constructor(tag){this.tag=tag;this.children=[];this.style={};this.dataset={};this.listeners={};this.parentElement=null;this.classList={toggle(){}};this.width=0;this.height=0;this.rect={left:20,top:30,width:1440,height:900};this.textContent=''}
  get isConnected(){return this.connected||!!this.parentElement?.isConnected}
  append(...els){for(const e of els){e.parentElement=this;this.children.push(e)}}prepend(e){e.parentElement=this;this.children.unshift(e)}after(e){this.parentElement.append(e)}remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(c=>c!==this);this.parentElement=null}
  set innerHTML(value){for(const tag of ['landscape','figure-mask','stage','label','error']){const e=new El(tag==='stage'?'canvas':tag==='figure-mask'?'img':'div');e.id=tag;if(tag==='landscape')e.style.backgroundImage='url(/hologram-backdrop.webp)';this.append(e)}}
  querySelector(q){if(q[0]==='#'){for(const e of this.children){if(e.id===q.slice(1))return e;const v=e.querySelector(q);if(v)return v}}return null}querySelectorAll(){return []}
  toDataURL(){return "data:image/webp;base64,AA=="}getBoundingClientRect(){return this.rect}getContext(type){return type==='webgl'?(webgl?gl:null):ctx}
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn)}removeEventListener(type,fn){this.listeners[type]=(this.listeners[type]||[]).filter(f=>f!==fn)}emit(type,ev={}){for(const f of this.listeners[type]||[])f(ev)}
 }
 const host=new El('section');host.connected=true;
 const onlineParts={span:new El('span'),b:new El('b'),i:new El('i')};onlineParts.span.textContent='ÇEVRİMİÇİ';onlineParts.b.textContent='100%';onlineParts.i.style.props={'--v':'100%'};onlineParts.i.style.setProperty=(k,v)=>{onlineParts.i.style.props[k]=v};onlineParts.i.style.getPropertyValue=k=>onlineParts.i.style.props[k];
 const online={dataset:{},querySelector(q){return q==='span'?onlineParts.span:q==='b'?onlineParts.b:q===':scope > i'?onlineParts.i:null}};
 const document={hidden:false,createElement:t=>new El(t),querySelector:q=>q==='.hs-online'?online:null};
 class Image{constructor(){this.width=200;this.height=200}set src(v){images.push(v);this.onload?.()}}
 const context={document,Image,Float32Array,Uint8Array,Math,Number,Object,String,performance:{now:()=>clock},devicePixelRatio:1,requestAnimationFrame(fn){queue.set(++id,fn);return id},cancelAnimationFrame(n){queue.delete(n)},console:{error(...args){logs.push(args)}}};context.window=context;
 vm.runInNewContext(source,context);
 const opts={getState:()=>state,getTone:()=>tone,getBackground:()=>back,getElapsed:()=>elapsed,saveElapsed:t=>elapsed=t,isStill:()=>still,isCalm:()=>calm,onMic:()=>mic++,onRestore(){restored++}};
 const api=context.JarvisHologram.mount(host,opts),root=host.children[0],canvas=root.querySelector('#stage');
 function tick(ms=16){clock+=ms;const pending=[...queue.values()];queue.clear();pending.forEach(fn=>fn(clock))}
 return {api,root,canvas,document,online,onlineParts,queue,uniforms,images,logs,tick,get mic(){return mic},get deleted(){return deleted},get restored(){return restored},get elapsed(){return elapsed},set state(v){state=v},set still(v){still=v},set calm(v){calm=v},set tone(v){tone=v},set back(v){back=v}};
}
const h=harness();h.tick();assert.equal(h.uniforms.mode,0);assert(Math.abs(h.uniforms.offset[1]+.1)<1e-10);
for(const [state,mode] of [['listening',1],['thinking',2],['speaking',3],['sleep',undefined],['idle',0]]){h.state=state;h.tick();assert.equal(h.root.dataset.state,state);if(mode!==undefined)assert.equal(h.uniforms.mode,mode)}
h.state='speaking';h.tick();assert(h.uniforms.energy>0,'konuşma durumunda görsel zarf etkin');
h.tone='yellow';h.back='lava';for(let i=0;i<40;i++)h.tick();assert(h.uniforms.toneWeights[2]>.9,'sarıya yumuşak geçiş');assert(!h.logs.length);
h.canvas.emit('click',{clientX:20,clientY:600});assert.equal(h.mic,0,'dağlara tıklamak mikrofon açmaz');
h.canvas.emit('click',{clientX:740,clientY:410});assert.equal(h.mic,1,'silüete tıklama tek mevcut mikrofon eylemi');h.tick();assert(h.uniforms.pulse<.1,'dalga tıklama anından başlar');
h.canvas.emit('keydown',{key:'Enter',preventDefault(){}});assert.equal(h.mic,2,'klavye erişimi');
h.root.emit('pointermove',{clientX:1100,clientY:280});h.tick();assert(h.uniforms.yaw>0);h.still=true;h.tick();assert.equal(h.uniforms.assembly,1);assert.equal(h.uniforms.time,0);assert.equal(h.uniforms.yaw,0);
const before=h.elapsed;h.document.hidden=true;h.tick(1000);assert.equal(h.elapsed,before,'gizli sayfada oluşum saati durur');h.document.hidden=false;
h.api.replay();h.still=false;h.tick();assert(h.uniforms.assembly<.02,'tekrar oynat oluşumu baştan alır');
h.api.destroy();assert.equal(h.queue.size,0);assert.equal(h.root.isConnected,false);assert(h.deleted>=5,'GPU kaynakları serbest');assert.equal((h.canvas.listeners.click||[]).length,0,'dinleyiciler temizlenir');h.api.destroy();
const calm=harness();calm.tick();calm.calm=true;const elapsedBefore=calm.elapsed;calm.tick();assert.equal(calm.elapsed,elapsedBefore,'sakin modda bir kare atlanır');calm.tick();assert(calm.elapsed>elapsedBefore);calm.api.destroy();
const lost=harness();lost.tick();let prevented=false;lost.canvas.emit('webglcontextlost',{preventDefault(){prevented=true}});assert(prevented);assert.equal(lost.queue.size,0);lost.canvas.emit('webglcontextrestored');assert.equal(lost.restored,1);assert.equal(lost.root.isConnected,false,'geri gelen bağlam yeni çizime bırakılır');
const detached=harness();detached.root.remove();detached.tick();assert.equal(detached.queue.size,0,'ana ekran kaldırılınca döngü durur');
const fallback=harness(false);fallback.tick();assert.match(fallback.root.querySelector('#error').textContent,/durağan/);fallback.canvas.emit('keydown',{key:' ',preventDefault(){}});assert.equal(fallback.mic,1);fallback.api.destroy();assert.equal(fallback.queue.size,0);
assert(h.images.every(p=>p.startsWith('/')||p.startsWith('data:')),'yalnız yerel görseller');
for(const re of [/\bfetch\(/,/new EventSource/,/new WebSocket/,/navigator\.mediaDevices/,/\beval\(/,/new Function/])assert(!re.test(source),'çizim modülü ağ/model/mikrofon/dinamik kod üretmez');
const nx=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');assert(nx.includes("getState:()=>((S.snap||{}).flags||{}).sleep?'sleep':S.orb"));assert(nx.includes('onMic:()=>ACT.mic()'));
// nx.js'nin gerçek state olay işleyicisini ve mount köprüsünü de çalıştır.
const live={snap:{user:{slug:'me'},flags:{}},orb:'idle',page:'home',hist:[],live:[]},ACT={mic(){micCalls++}},calls=[];let micCalls=0;
const bridge={S:live,ACT,store:{get(k,d){return d},set(){}},BUST:{},UI_CALM:()=>false,matchMedia:()=>({matches:false}),window:{JarvisHologram:{mount(stage,options){calls.push(options);return {destroy(){},replay(){}}}}},document:{querySelectorAll(){return []}},settingsOpen:()=>false,$:()=>null,$$:()=>[],dockState(){},refreshSoon(){}};
vm.runInNewContext(nx.slice(nx.indexOf('let HOME_HOLOGRAM='),nx.indexOf('// ---- İkinci ana ekran')),bridge);
bridge.mountBust({});const bound=calls[0];assert.equal(bound.getState(),'idle');
const hlStart=nx.indexOf('// SPEECH HIGHLIGHT START'),hlEnd=nx.indexOf('// SPEECH HIGHLIGHT END',hlStart);assert(hlStart>-1&&hlEnd>hlStart,'ses vurgusu bloğu işaretleri bulunmalı');
vm.runInNewContext(nx.slice(hlStart,hlEnd),bridge);   // onEvent'in çağırdığı GERÇEK yardımcılar, taklit değil
const eventStart=nx.indexOf('function onEvent(m){'),eventEnd=nx.indexOf('function connect',eventStart);assert(eventEnd>eventStart);
vm.runInNewContext(nx.slice(eventStart,eventEnd),bridge);
for(const state of ['listening','thinking','speaking','idle']){bridge.onEvent({k:'state',t:state,user:'me'});assert.equal(bound.getState(),state)}
bridge.onEvent({k:'state',t:'speaking',user:'other'});assert.equal(bound.getState(),'idle','başka kullanıcının olayı görseli değiştirmez');
live.snap.flags.sleep=true;assert.equal(bound.getState(),'sleep');bound.onMic();assert.equal(micCalls,1,'köprü mevcut ACT.mic yolunu tam bir kez çağırır');
console.log('Hologram: gerçek durum köprüsü, renk, tıklama sınırı, klavye, sakin mod, yeniden oynatma, fallback ve kaynak temizliği geçti.');
// ÇEVRİMİÇİ yüzdesi ve çubuğu açılış animasyonuyla dolar, bitince gerçek değer geri gelir.
{const o=harness();o.tick(50);assert.equal(o.onlineParts.span.textContent,'OLUŞUYOR');assert(parseInt(o.onlineParts.b.textContent)<100,'oluşurken yüzde 100 değil');
 const mid=parseFloat(o.onlineParts.i.style.props['--v']);for(let i=0;i<40;i++)o.tick(50);assert(parseFloat(o.onlineParts.i.style.props['--v'])>mid,'çubuk animasyonla dolar');
 for(let i=0;i<120;i++)o.tick(50);assert.equal(o.onlineParts.span.textContent,'ÇEVRİMİÇİ');assert.equal(o.onlineParts.b.textContent,'100%');assert.equal(o.onlineParts.i.style.props['--v'],'100%','bitince gerçek sağlık değeri geri gelir');o.api.destroy()}
