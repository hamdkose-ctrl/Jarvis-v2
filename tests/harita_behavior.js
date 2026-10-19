'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const src=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');
const start=src.indexOf('// HARITA START'),end=src.indexOf('// HARITA END');
assert(start>=0&&end>start,'HARITA bloğu henüz yok');
const calls=[],notices=[];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const context={PAGES:{},ACT:{stoptask(){calls.push(['stop'])}},esc,ic:n=>`<i>${esc(n)}</i>`,toast:(m,k)=>notices.push([m,k]),
  tryApi:async(...args)=>{calls.push(args);return context.apiResult},apiResult:{ok:true},console};
vm.createContext(context);
vm.runInContext(src.slice(start,end+'// HARITA END'.length)+'\nglobalThis.__harita={harita_render,harita_set_policy,PAGES};',context);
const H=context.__harita;
const fake={tools:[
 {id:'printer<1>',name:'3D <Yazıcı>',area:'cihaz',icon:'gear',state:'running',detail:'Baskı <sürüyor>',actions:[
   {id:'send&go',name:'Gönder <şimdi>',desc:'Dosyayı > cihaza',class:'local_destructive',policy:'ask',until:null},
   {id:'pay',name:'Ödeme',desc:'Para alanı',class:'money_credential',policy:'locked',until:null}],
  last:[{ts:1,decision:'ask',action:'send'}]},
 {id:'mail',name:'Posta',area:'iletisim',icon:'msg',state:'ready',detail:'Hazır',actions:[
   {id:'read',name:'Oku',desc:'Mesajları oku',class:'read',policy:'allow',until:123}],last:[]}],
 placeholders:[{area:'cihaz',name:'Akıllı ev <yakında>'}]};

// veri -> güvenli HTML; çalışan kartta mevcut stop action görünür
const html=H.harita_render(fake);
assert(html.includes('3D &lt;Yazıcı&gt;'));
assert(html.includes('Baskı &lt;sürüyor&gt;'));
assert(!html.includes('3D <Yazıcı>'));
assert(html.includes('data-act="stoptask"'));
assert(html.includes('Yakında'));
assert(html.includes('Akıllı ev &lt;yakında&gt;'));
assert(html.includes('harita-class-local_destructive'));

// locked politika tıklanamaz ve kilitlidir
const locked=html.match(/<button[^>]*data-map-policy="locked"[^>]*>/)?.[0]||'';
assert(locked.includes('disabled'));
assert(locked.includes('aria-disabled="true"'));
assert(html.includes('🔒'));

// bozuk veri çökmez; boş veri sahte karta dönüşmez
for(const bad of [null,undefined,{},[],{tools:'bad',placeholders:3},{tools:[null,{id:3}],placeholders:[null]}]){
  assert.doesNotThrow(()=>H.harita_render(bad));
}
assert(H.harita_render(null).includes('Harita bu sürümde yok'));

// politika değişimi backend'e gider; başarıda yeni değer kalır
const control={value:'allow'};
context.apiResult={ok:true};calls.length=0;notices.length=0;
H.harita_set_policy('printer<1>','send&go','ask','allow',control);
setImmediate(async()=>{
  await new Promise(r=>setImmediate(r));
  assert.deepEqual(calls[0],['map_set_policy','printer<1>','send&go','allow']);
  assert.equal(control.value,'allow');

  // boş/null sonuçta eski değere dön ve sürüm uyarısını göster
  calls.length=0;notices.length=0;context.apiResult=null;control.value='deny';
  await H.harita_set_policy('printer<1>','send&go','ask','deny',control);
  assert.deepEqual(calls[0],['map_set_policy','printer<1>','send&go','deny']);
  assert.equal(control.value,'ask');
  assert(notices.some(([m])=>m==='Harita politika değişimi bu sürümde yok.'));

  // PAGES.map gerçek API boşsa sahte veri göstermemeli
  const pg={innerHTML:'',addEventListener(){}};calls.length=0;notices.length=0;context.apiResult=null;
  await H.PAGES.map(pg);
  assert.deepEqual(calls[0],['map']);
  assert(pg.innerHTML.includes('Harita bu sürümde yok'));
  assert(!pg.innerHTML.includes('3D &lt;Yazıcı&gt;'));
  console.log('harita behavior ok');
}).catch(e=>{console.error(e);process.exitCode=1});
