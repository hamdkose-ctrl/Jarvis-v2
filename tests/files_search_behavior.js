// Dosyalar arama kutusu: dosya adı + belge içeriği; içerik isabeti listede görünür, eşleşme cümlesi satırın altında çıkar.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');
const a=src.indexOf('function fFiltered('),b=src.indexOf('function drawFiles(');
assert(a>0&&b>a,'arama işlevleri bulunmalı');
const calls=[];let redraws=0;
const ctx={S:{files:{files:[
  {path:'C:/J/Sozlesme.pdf',name:'Sozlesme.pdf',cat:'pdf',mine:true},
  {path:'C:/J/Fiyat.xlsx',name:'Fiyat.xlsx',cat:'excel',mine:true},
  {path:'C:/D/Notlar.docx',name:'Notlar.docx',cat:'word',mine:false}]},fq:'',fcat:'all',fhits:null,snap:{user:{slug:'hamdi'}}},
  esc:x=>String(x).replace(/</g,'&lt;'),$:()=>({}),drawFiles:()=>{redraws++},
  tryApi:async(name,q)=>{calls.push([name,q]);return [{path:'C:/J/Sozlesme.pdf',name:'Sozlesme.pdf',cat:'pdf',mine:true,snippet:'KİRA BEDELİ 15.000 TL'},{path:'C:/Eski/Kira.pdf',name:'Kira.pdf',cat:'pdf',mine:false,snippet:'depozito'}]},
  setTimeout:(fn)=>{ctx.__timer=fn;return 1},clearTimeout(){}};
vm.createContext(ctx);vm.runInContext(src.slice(a,b),ctx);
const names=()=>JSON.parse(JSON.stringify(vm.runInContext('fFiltered().map(f=>f.name)',ctx)));
// 1) arama yokken hepsi, ad araması yalnız adda
assert.deepEqual(names(),['Sozlesme.pdf','Fiyat.xlsx','Notlar.docx']);
ctx.S.fq='fiyat';assert.deepEqual(names(),['Fiyat.xlsx']);
// 2) içerik isabeti: adında geçmeyen belge de listelenir, listede olmayan eski belge sona eklenir
ctx.S.fq='kira bedeli';ctx.S.fhits={'C:/J/Sozlesme.pdf':{path:'C:/J/Sozlesme.pdf',name:'Sozlesme.pdf',cat:'pdf',mine:true,snippet:'KİRA BEDELİ 15.000 TL'},'C:/Eski/Kira.pdf':{path:'C:/Eski/Kira.pdf',name:'Kira.pdf',cat:'pdf',mine:false,snippet:'depozito'}};
assert.deepEqual(names(),['Sozlesme.pdf','Kira.pdf']);
// 3) kategori süzgeci içerik isabetine de uygulanır
ctx.S.fcat='excel';assert.deepEqual(names(),[]);ctx.S.fcat='mine';assert.deepEqual(names(),['Sozlesme.pdf']);ctx.S.fcat='all';
// 4) eşleşme cümlesi yalnız yeterince uzun aramada ve isabetli satırda görünür, HTML kaçırılır
assert(vm.runInContext("fSnip({path:'C:/J/Sozlesme.pdf'})",ctx).includes('KİRA BEDELİ'));
assert.equal(vm.runInContext("fSnip({path:'C:/J/Fiyat.xlsx'})",ctx),'');
ctx.S.fq='ki';assert.equal(vm.runInContext("fSnip({path:'C:/J/Sozlesme.pdf'})",ctx),'');
// 5) içerik araması: 3 harften kısa aramada istek yok; uzunda gecikmeli tek istek ve sonuç listeye işlenir
(async()=>{
  ctx.S.fq='ki';vm.runInContext('fContent()',ctx);assert.equal(ctx.S.fhits,null);assert.equal(calls.length,0);
  ctx.S.fq='kira';ctx.S.fhits=null;vm.runInContext('fContent()',ctx);assert.equal(calls.length,0,'istek gecikmeli gitmeli');
  await ctx.__timer();
  assert.deepEqual(calls,[['files_search','kira']]);assert.equal(Object.keys(ctx.S.fhits).length,2);assert.equal(redraws,1);
  // arama kutusu değiştiyse eski cevap yok sayılır
  calls.length=0;ctx.S.fq='fatura';ctx.S.fhits=null;vm.runInContext('fContent()',ctx);ctx.S.fq='baska';await ctx.__timer();assert.equal(ctx.S.fhits,null);
  console.log('Dosyalar arama: ad + belge içeriği, kategori süzgeci, eşleşme cümlesi, gecikmeli tek istek ve eski cevabı yok sayma geçti.');
})().catch(e=>{console.error(e);process.exit(1)});
