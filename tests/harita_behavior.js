'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const src=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');
const start=src.indexOf('// HARITA START'),end=src.indexOf('// HARITA END');
assert(start>=0&&end>start,'HARITA bloğu henüz yok');
const calls=[],notices=[];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const context={S:{page:'map'},PAGES:{},ACT:{stoptask(){calls.push(['stop'])}},esc,ic:n=>`<i>${esc(n)}</i>`,menuOrbSvg:()=>'<svg class="fake-orb"></svg>',toast:(m,k)=>notices.push([m,k]),
  tryApi:async(...args)=>{calls.push(args);return context.apiResult},apiResult:{ok:true},console};
vm.createContext(context);
vm.runInContext(src.slice(start,end+'// HARITA END'.length)+'\nglobalThis.__harita={harita_render,harita_set_policy,PAGES};',context);
const H=context.__harita;
const fake={tools:[
 {id:'printer<1>',name:'3D <Yazıcı>',area:'cihaz',icon:'gear',state:'running',detail:'Baskı <sürüyor>',actions:[
   {id:'send&go',name:'Gönder <şimdi>',desc:'Dosyayı > cihaza',class:'local_destructive',policy:'ask',until:null},
   {id:'pay',name:'Ödeme',desc:'Para alanı',class:'money_credential',policy:'locked',until:null}],last:[{ts:1,decision:'ask',action:'send'}]},
 {id:'mail',name:'Posta',area:'iletisim',icon:'msg',state:'ready',detail:'Hazır',actions:[
   {id:'read',name:'Oku',desc:'Mesajları oku',class:'read',policy:'allow',until:123},
   {id:'undo',name:'Geri al',desc:'Yerel değişiklik',class:'local_reversible',policy:'ask',until:null},
   {id:'send',name:'Gönder',desc:'Mesaj gönder',class:'message_out',policy:'deny',until:null},
   {id:'publish',name:'Yayınla',desc:'Dışarı yayınla',class:'publish',policy:'ask',until:null},
   {id:'system',name:'Sistem',desc:'Sistem ayarı',class:'system_config',policy:'ask',until:null},
   {id:'print',name:'Yazdır',desc:'Fiziksel işlem',class:'physical',policy:'ask',until:null}],last:[]}],
 placeholders:[{area:'cihaz',name:'Akıllı ev <yakında>'}]};

const html=H.harita_render(fake);
assert(html.includes('3D &lt;Yazıcı&gt;'));
assert(html.includes('Baskı &lt;sürüyor&gt;'));
assert(!html.includes('3D <Yazıcı>'));
assert(html.includes('fake-orb'));
assert(html.includes('data-act="stoptask"'));
assert(html.includes('Yakında'));
assert(html.includes('Akıllı ev &lt;yakında&gt;'));
for(const label of ['okuma','geri alınabilir','yıkıcı','gönderim','yayın','para','sistem','fiziksel'])assert(html.includes(label),label+' rozeti eksik');

const locked=html.match(/<button[^>]*data-map-policy="locked"[^>]*>/)?.[0]||'';
assert(locked.includes('disabled'));
assert(locked.includes('aria-disabled="true"'));
assert(html.includes('🔒'));

for(const bad of [null,undefined,{},[],{tools:'bad',placeholders:3},{tools:[null,{id:3}],placeholders:[null]}])assert.doesNotThrow(()=>H.harita_render(bad));
assert(H.harita_render(null).includes('Harita bu sürümde yok'));

(async()=>{
  const control={value:'allow'};
  context.apiResult={ok:true};calls.length=0;notices.length=0;
  await H.harita_set_policy('printer<1>','send&go','ask','allow',control);
  assert.deepEqual(calls[0],['map_set_policy','printer<1>','send&go','allow']);
  assert.equal(control.value,'allow');

  calls.length=0;notices.length=0;context.apiResult=null;control.value='deny';
  await H.harita_set_policy('printer<1>','send&go','ask','deny',control);
  assert.deepEqual(calls[0],['map_set_policy','printer<1>','send&go','deny']);
  assert.equal(control.value,'ask');
  assert(notices.some(([m])=>m==='Harita politika değişimi bu sürümde yok.'));

  const pg={innerHTML:''};calls.length=0;notices.length=0;context.apiResult=null;
  await H.PAGES.map(pg);
  assert.deepEqual(calls[0],['map']);
  assert(pg.innerHTML.includes('Harita bu sürümde yok'));
  assert(!pg.innerHTML.includes('3D &lt;Yazıcı&gt;'));
  const pending=H.PAGES.map(pg);
  context.S.page='home';
  pg.innerHTML='Yeni konsol';
  await pending;
  assert.equal(pg.innerHTML,'Yeni konsol');
  console.log('harita behavior ok');
})().catch(e=>{console.error(e);process.exitCode=1});
