// Menü yan sayfası "Ekran ve kamera": önizleme, anahtarlar, PC işlemleri, görsel analiz, son görseller ve renkli durum satırı.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
const calls=[];
const S={snap:{mode:null},files:{files:[
 {name:'eski.docx',ext:'docx',cat:'word',size:2048,mtime:100,path:'C:/f/eski.docx',mine:false},
 {name:'foto-eski.png',ext:'png',cat:'image',size:2000,mtime:150,path:'C:/f/foto-eski.png',mine:true},
 {name:'foto-yeni.jpg',ext:'jpg',cat:'image',size:3000,mtime:400,path:'C:/f/foto-yeni.jpg',mine:true}]}};
const ACT={};
const c={S,ACT,esc:x=>String(x).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m])),ic:n=>`<svg data-i="${n}"></svg>`,fmtSize:b=>b+' B',fmtDate:t=>'d'+t,
 sbox:(i,t,s,b)=>`<blk t="${t}">${b}</blk>`,pad18:x=>x,srow:(i,t,s,r)=>`<row>${t}|${r}</row>`,sw2:(m,on)=>`<sw m="${m}" on="${on}"></sw>`,loadFiles:async f=>{calls.push(['loadFiles',f])},settingsOpen:()=>true,drawSettings:()=>{},
 api:async(...a)=>{calls.push(['api',...a])},$:()=>null,setTimeout,clearTimeout,Math,String};
vm.createContext(c);
vm.runInContext(src.slice(src.indexOf('function pcOperationsBox('),src.indexOf('// Ayarlarda arama')),c);
const blocks=h=>[...h.matchAll(/<blk t="([^"]+)">/g)].map(m=>m[1]);
const part=(h,title)=>{const a=h.indexOf('<blk t="'+title+'">');return h.slice(a,h.indexOf('</blk>',a))};
let html=c.screenFilesPanel();
assert.deepEqual(blocks(html),['Ekran Paylaşımı','Kamera','Ekranı İncele','Ekran Görüntüsü Al','PC İşlemleri','Görsel Analiz','Son Görseller'],'her işlev ayrı blok: yan sayfada her biri kendi orbunu alır (dosya işlemleri Dosyalar sayfasındadır)');
assert(part(html,'Ekran Paylaşımı').includes('sfp-state off')&&part(html,'Ekran Paylaşımı').includes('Ekran paylaşımı kapalı'),'kapalıyken kırmızı durum');
assert(!html.includes('id="sfp-img"')&&html.includes('Önizleme için paylaşımı aç'),'paylaşım kapalıyken canlı önizleme yok');
assert(part(html,'PC İşlemleri').includes('pcguide')&&part(html,'PC İşlemleri').includes('pctask')&&part(html,'PC İşlemleri').includes('açık pencereleri listele'),'PC işlemleri');
assert(part(html,'Görsel Analiz').includes('act:image')&&part(html,'Görsel Analiz').includes('act:ocr'),'görsel analiz işlevleri');
assert(part(html,'Ekranı İncele').includes('Ekranı incele')&&part(html,'Ekran Görüntüsü Al').includes('Görüntü al'),'eylemler');
const sg=part(html,'Son Görseller');assert(sg.indexOf('foto-yeni.jpg')<sg.indexOf('foto-eski.png')&&!sg.includes('eski.docx'),'yalnız görseller, yenisi üstte');
assert(/data-a="gorsel"/.test(sg)&&/data-a="metin"/.test(sg),'görsel için Analiz Et ve Metin işlemleri');
S.snap.mode='screen';html=c.screenFilesPanel();assert(part(html,'Ekran Paylaşımı').includes('sfp-state on')&&part(html,'Ekran Paylaşımı').includes('id="sfp-img"')&&!part(html,'Kamera').includes('sfp-img'),'ekran açıkken önizleme ekran bloğunda');
S.snap.mode='camera';html=c.screenFilesPanel();assert(part(html,'Kamera').includes('Kamera açık')&&part(html,'Kamera').includes('id="sfp-img"')&&!part(html,'Ekran Paylaşımı').includes('sfp-img'),'kamera açıkken önizleme kamera bloğunda');
console.log('Ekran ve kamera paneli: önizleme, anahtarlar, PC işlemleri, görsel analiz, son görseller ve renkli durum geçti.');
