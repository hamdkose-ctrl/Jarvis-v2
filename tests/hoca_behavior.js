const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
const S={sov:{}},ACT={},said=[],calls=[],toasts=[];
const nodes={};
const ctx={S,ACT,$:id=>nodes[id]||null,ic:n=>`[${n}]`,esc:x=>String(x==null?'':x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'),
  say:t=>said.push(t),toast:t=>toasts.push(t),render:()=>{},loadStudy:async()=>{ctx.loaded=(ctx.loaded||0)+1},
  tryApi:async(...a)=>{calls.push(a);return 'ok'}};
vm.createContext(ctx);
vm.runInContext(src.slice(src.indexOf('function hocaHtml('),src.indexOf('function wrongHtml(')),ctx);
for(const n of ['hocasay','hocastart','hocaans','hocatoggle']){const i=src.indexOf('ACT.'+n+'=');assert(i>=0,n);vm.runInContext(src.slice(i,src.indexOf('\n',i)),ctx)}
assert(src.includes("['hoca','Hoca','spark']"));assert(src.includes("S.stab==='hoca')body=hocaHtml(ov)"));

// Ders yokken: başlatma formu, zayıf konu boş durumu
let html=ctx.hocaHtml({});
assert(html.includes('id="hocatopic"')&&html.includes('data-act="hocastart"'));assert(html.includes('Zayıf konu yok'));
assert(html.includes('Sohbet komutları açık'));
html=ctx.hocaHtml({hoca:{enabled:false,lesson:null,weak:[]}});assert(html.includes('Sohbet komutları kapalı'));

// Aktif ders: adım, soru, XSS kaçışı, zayıf konu
html=ctx.hocaHtml({hoca:{enabled:true,lesson:{topic:'Hücre',step:2,total:3,title:'Organeller',steps:['Hücre nedir','Organeller','Zar'],text:'<b>x</b>',question:'Çekirdek ne yapar?'},
  weak:[{id:'a',title:'Hücre nedir',topic:'Hücre',due_now:true},{id:'b',title:'Zar',topic:'Hücre',due_now:false}]}});
assert(html.includes('Adım 2/3'));assert(html.includes('Çekirdek ne yapar?'));assert(html.includes('&lt;b&gt;x&lt;/b&gt;'));assert(!html.includes('<b>x</b>'));
assert(!html.includes('id="hocatopic"'),'ders varken başlatma formu yok');
assert(html.includes('tekrar zamanı')&&html.includes('bekliyor'));assert(html.includes('data-q="sonraki adım"'));

// Düğmeler sohbet komutuna döner
ACT.hocasay({dataset:{q:'sonraki adım'}});assert.deepEqual(said,['sonraki adım']);
nodes['#hocatopic']={value:'  hücre '};ACT.hocastart();assert.equal(said.at(-1),'hoca modu: hücre');
nodes['#hocatopic']={value:'  '};ACT.hocastart();assert.equal(said.length,2);assert(toasts.length===1);
nodes['#hocaans']={value:'canlının yapı birimi'};ACT.hocaans();assert.equal(said.at(-1),'cevap: canlının yapı birimi');
nodes['#hocaans']={value:''};ACT.hocaans();assert.equal(said.length,3);

// Aç/kapat ayarı yazar ve özeti yeniler
(async()=>{
  S.sov={hoca:{enabled:true}};await ACT.hocatoggle();assert.equal(JSON.stringify(calls.at(-1)),JSON.stringify(['settings_save',{hoca_enabled:false}]));assert.equal(ctx.loaded,1);
  S.sov={hoca:{enabled:false}};await ACT.hocatoggle();assert.equal(JSON.stringify(calls.at(-1)),JSON.stringify(['settings_save',{hoca_enabled:true}]));
  S.sov={};await ACT.hocatoggle();assert.equal(JSON.stringify(calls.at(-1)),JSON.stringify(['settings_save',{hoca_enabled:false}]),'varsayılan açık');
  console.log('hoca_behavior ok');
})();
