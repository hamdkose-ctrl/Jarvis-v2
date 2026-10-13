// Menü yan sayfası alt başlık orbları: bölümler orbun çevresinde küçük orblara dönüşür, seçilmeyenler gizlenir; Yapay zekâda orblar sağlayıcılardır.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
const set=()=>{const s=new Set();return {add:x=>s.add(x),remove:x=>s.delete(x),contains:x=>s.has(x),toggle:(x,on)=>{if(on)s.add(x);else s.delete(x)},has:x=>s.has(x)}};
const block=(title,extra={})=>({title,classList:set(),dataset:extra.dataset||{},parentElement:{closest:()=>null},previousElementSibling:extra.prev||null,querySelector:()=>title&&!extra.noTitleNode?{textContent:title}:null});
let blocks=[];const webCalls=[];let linked=0;
const pane={querySelectorAll:sel=>sel.includes('sbox')?blocks:sel==='.sub-hide'?blocks.filter(b=>b.classList.has('sub-hide')):[],};
let hasSubs=false,picker=null;
const web={showSubs:(items,pick,sel)=>{hasSubs=true;picker=pick;webCalls.push(['show',JSON.stringify(items),sel])},hideSubs:()=>{hasSubs=false;webCalls.push(['hide'])},selectSub:i=>webCalls.push(['select',i]),hasSubs:()=>hasSubs};
const sc={_web:web,classList:{contains:c=>c==='docked'},querySelector:s=>s==='#spane'?pane:null};
const win={};const aipicks=[];
const S={sset:'telefon',snap:{llm:{provider:'groq',key:true,groq:{key:true},paid:{},ollama_up:false},google:{},youtube:{}}},SX={},ACT={aipick:e=>aipicks.push(e.dataset.k)};
const AI_CARDS=[['auto','Otomatik'],['gemini','Gemini'],['groq','Groq']];
const MENU_VIEW_SRC=src.slice(src.indexOf('const MENU_VIEW='),src.indexOf('const MENU_INFO='));
const FOLD_SRC=src.slice(src.indexOf('const fold='),src.indexOf('\n',src.indexOf('const fold=')));
const c={S,SX,ACT,AI_CARDS,aiStates:()=>({auto:['ok'],gemini:['ok'],groq:['bad']}),window:win,$:()=>sc,menuLink:()=>linked++,setTimeout,clearTimeout,String,MutationObserver:undefined};
vm.createContext(c);
vm.runInContext(FOLD_SRC,c);vm.runInContext(MENU_VIEW_SRC,c);vm.runInContext(src.slice(src.indexOf('let mnObs=null'),src.indexOf('function menuDock(')),c);
// 1) üç bölüm: orbların başlıkları bölümlerin başlıkları, ilki açık, diğerleri gizli
blocks=[block('Android / iPhone · PC bağlantısı'),block('Telefon güvenliği'),block('Android · Bilgisayardan Bağımsız Uygulama'),block('')];
c.menuSubsScan(sc);
assert.equal(webCalls[0][0],'show');assert.equal(JSON.parse(webCalls[0][1]).map(x=>x.title).join('|'),'Android / iPhone · PC bağlantısı|Telefon güvenliği|Android · Bilgisayardan Bağımsız Uygulama','başlıksız blok orb olmaz');
assert(!blocks[0].classList.has('sub-hide')&&blocks[1].classList.has('sub-hide')&&blocks[2].classList.has('sub-hide'),'ilk başlık açık, diğerleri gizli');
assert.equal(win.__mnSubOn,true);assert(linked>0,'bağlantı çizgisi yenilenir');
// 2) bir orba basınca yalnız o bölüm görünür
picker(1);assert(blocks[0].classList.has('sub-hide')&&!blocks[1].classList.has('sub-hide')&&blocks[2].classList.has('sub-hide'));assert.equal(win.__mnSub,1);
// 3) içerik yeniden yüklenince (aynı başlıklar) orblar yeniden kurulmaz, seçim korunur
const shows=webCalls.filter(x=>x[0]==='show').length;blocks=[block('Android / iPhone · PC bağlantısı'),block('Telefon güvenliği'),block('Android · Bilgisayardan Bağımsız Uygulama')];c.menuSubsScan(sc);
assert.equal(webCalls.filter(x=>x[0]==='show').length,shows,'aynı bölümler: yeniden kurulmaz');assert(!blocks[1].classList.has('sub-hide')&&blocks[0].classList.has('sub-hide'),'yeni çizilen bloklara seçim yeniden uygulanır');
// 4) tek bölüm: orb yok, her şey görünür
blocks=[block('GitHub ana sürüm')];c.menuSubsScan(sc);assert.equal(webCalls.at(-1)[0],'hide');assert.equal(win.__mnSubOn,false);assert(!blocks[0].classList.has('sub-hide'));
// 5) yapay zekâ: orblar sağlayıcılar, renk durumdan, seçili sağlayıcı kullanılan
S.sset='ai';webCalls.length=0;hasSubs=false;
c.menuSubsStop();c.menuSubsScan(sc);
const showAi=webCalls.find(x=>x[0]==='show');const ai=JSON.parse(showAi[1]);assert.deepEqual(ai.map(x=>x.title),['Otomatik','Gemini','Groq']);assert.deepEqual(ai.map(x=>x.state),['ok','ok','bad'],'orb rengi bağlantı durumu');assert.equal(showAi[2],2,'kullanılan sağlayıcı seçili');
picker(1);assert.deepEqual(aipicks,['gemini'],'orba basınca o sağlayıcının bağlantısı açılır');
// 6) her şey tek yerde: aynı bölüm içeriğini paylaşan düğümlerin görünüm listeleri ayrık olmalı ve her başlık tam bir düğümde bulunmalı
const MV=vm.runInContext('MENU_VIEW',c),FOLD=vm.runInContext('fold',c);
const owners=(nodes,title)=>nodes.filter(n=>MV[n].test(FOLD(title)));
const SEC={ekran:[['ekran'],['Ekran Paylaşımı','Kamera','Ekranı İncele','Ekran Görüntüsü Al','Görsel Analiz','PC İşlemleri','Son Görseller']],
 sistem:[['sistem','veri','rapor','tarama'],['Genel Ayarlar','Hakkında','Yerel Kayıtlar','Gelişim raporu','Sistem taraması']],
 hesap:[['hesap','hafiza'],['Kullanıcılar','Gizlilik modu','Koruma','Hedefler','Öğrenme durumu','Onay bekleyenler','Bildiklerim','Öğrettiğin kurallar']],
 takvim:[['takvim','gorev'],['Takvim','Yaklaşan Etkinlikler','Yapılacaklar','Notlar']],
 iletisim:[['telefon','mesaj'],['Android / iPhone · PC bağlantısı','Telefon güvenliği','Telefona bildirim (Ntfy)','Android · Bilgisayardan bağımsız uygulama','Kişiler','Mesaj gönder']]};
for(const [sec,[nodes,titles]] of Object.entries(SEC))for(const ti of titles)assert.equal(owners(nodes,ti).length,1,sec+' / '+ti+' tam bir ana başlıkta olmalı: '+owners(nodes,ti));
assert.equal(owners(['telefon','mesaj'],'Kişiler')[0],'mesaj');assert.equal(owners(['telefon','mesaj'],'Telefon güvenliği')[0],'telefon');
// 7) düğüm görünümü: Mesajlar yalnız kendi iki bölümünü orb yapar
win.__mnNode='mesaj';win.__mnSub=null;c.menuSubsStop();webCalls.length=0;S.sset='iletisim';
blocks=[block('Android / iPhone · PC bağlantısı'),block('Telefon güvenliği'),block('Kişiler'),block('Mesaj gönder')];c.menuSubsScan(sc);
const mshow=webCalls.find(x=>x[0]==='show');assert.deepEqual(JSON.parse(mshow[1]).map(x=>x.title),['Kişiler','Mesaj gönder'],'Mesajlar düğümü yalnız kendi bölümlerini gösterir');
assert(blocks[0].classList.has('sub-hide')&&blocks[1].classList.has('sub-hide')&&!blocks[2].classList.has('sub-hide')&&blocks[3].classList.has('sub-hide'),'telefon kartları gizli, ilk mesaj bölümü açık');
// 8) tek bölümlü düğüm (Veri klasörü): orb yok, yalnız o blok görünür
win.__mnNode='veri';c.menuSubsStop();webCalls.length=0;S.sset='sistem';blocks=[block('Genel Ayarlar'),block('Yerel Kayıtlar'),block('Hakkında')];c.menuSubsScan(sc);
assert(!webCalls.some(x=>x[0]==='show'),'tek bölüm: orb yok');assert(blocks[0].classList.has('sub-hide')&&!blocks[1].classList.has('sub-hide')&&blocks[2].classList.has('sub-hide'));
console.log('Menü alt başlık orbları: bölümler orba dönüşür, seçilmeyen gizlenir, yeniden yüklemede seçim korunur, Yapay zekâda renkli sağlayıcı orbları geçti.');
