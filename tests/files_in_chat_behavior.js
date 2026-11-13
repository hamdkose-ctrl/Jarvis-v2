const fs=require('fs'),path=require('path'),assert=require('assert');
const src=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');
const sayBody0=src.slice(src.indexOf('async function say(text){'),src.indexOf('ACT.send='));
const m=sayBody0.match(/&&(\/\^\(dosyalar.*?\/i)\.test\(/);assert(m,'dosya isteği düzenli ifadesi say() içinde bulunamadı');
const re=eval(m[1]);
for(const t of ['Dosyalarımı göster','dosyalarım','son yüklediklerim','dosyalarımı listele','Dosyaları göster.','yüklediğim dosyalar'])assert(re.test(t),t+' yakalanmalı');
for(const t of ['dosyayı sil','dosyalarımı özetle','bugün hava nasıl','dosyalarımı göster ve özetle'])assert(!re.test(t),t+' sunucuya gitmeli');
// say(): kart isteği sunucu çağrısından (api send) önce yakalanır ve ekli dosya varsa yakalanmaz
const sayBody=src.slice(src.indexOf('async function say(text){'),src.indexOf('ACT.send='));
assert(sayBody.indexOf('showFileCards(text)')>-1&&sayBody.indexOf('showFileCards(text)')<sayBody.indexOf("api('send'"),'kart isteği api(send) öncesinde yakalanmalı');
assert(/!\(Array\.isArray\(S\.att\)/.test(sayBody),'ekli dosya varken kart isteği yakalanmamalı');
// geliştirme düğmeleri yalnız geliştirme modu açıkken; geliştirme modunu açma yolu menüde durur
assert(/dev\.enabled\?base\.concat/.test(src),'geliştirme düğmeleri yalnız dev.enabled iken eklenmeli');
assert(src.includes("chatRun('geliştirme modunu aç')")&&src.includes("'değişiklikleri uygula'"),'geliştirme erişimi korunmalı');
// kart mesajı kopyalanan konuşmaya girmez
assert(src.includes("m.role!=='step'&&m.role!=='files'"));
// takvim kartı: yalnız net takvim/görev cümleleri tarayıcıda cevaplanır; "bugün ne var" gibi sorular sunucuya gider
const ma=sayBody.match(/_noAtt&&(\/\^\(takvimim.*?\/i)\.test\(/);assert(ma,'takvim isteği düzenli ifadesi say() içinde bulunamadı');
const rea=eval(ma[1]);
for(const x of ['takvimim','Ajandam','hatırlatmalarım','görevlerim','yaklaşan hatırlatmalar','takvimi göster'])assert(rea.test(x),x+' kart açmalı');
for(const x of ['bugün ne var','yarın toplantı ekle','takvime not ekle','görevlerimi sil'])assert(!rea.test(x),x+' sunucuya gitmeli');
assert(sayBody.indexOf('showAgendaCard(text)')<sayBody.indexOf("api('send'"),'takvim kartı api(send) öncesinde yakalanmalı');
assert(src.includes("m.role!=='files'&&m.role!=='agenda'"),'takvim kartı kopyalanan konuşmaya girmemeli');
// Araçlar ve Ekran menüden kalkar ama sayfaları ve açılış yolları durur; erişim "•••" alt menülerindedir
assert(src.includes("!['files','vision','tools','menu','settings'].includes(n[0])"),'üst menü Dosyalar/Ekran/Araçlar/Menü/Ayarlar düğmelerini gizlemeli (Menü ikinci ana ekrandır, Ayarlar sayfası kalktı)');
assert(/PAGES\.tools=/.test(src)&&/PAGES\.vision=/.test(src)&&/PAGES\.files=/.test(src),'sayfalar silinmemeli');
for(const k of ["tool('takvim')","tool('telefon')","tool('mesaj')","tool('tarama')","openAiHub('ai')"])assert(!/sub\('gear','Araçlar'/.test(src),'Sohbet ••• menüsünde Araçlar alt menüsü olmamalı');
// Ayarlar: 3 grup, eski bölüm kimlikleri gruba katılır, arama ve yapay zekâ girişi durur
assert(src.includes('const SECS=[')&&['ai','ses','takvim','iletisim','ekran','hesap','sistem'].every(id=>src.includes("{id:'"+id+"',")),'Ayarlar 7 bölümlü tek yapı olmalı');
assert(src.includes('for(const k of keys){')&&src.includes('function applySettingsFilter(el)'),'bölümler biriktirilmeli ve arama olmalı');
assert(src.includes("t:'Yapay zekâ'")&&src.includes('data-act="aipick"')&&!src.includes('data-act="aihubtab" data-k="baglanti"'),'yapay zekâ bölümü Ayarlar içinde, sağlayıcı kartlarıyla olmalı; ayrı Bağlantılar sekmesi olmamalı');
// Ana ekran ve Ses sadeleşmesi
assert(!/nx_globe|mountCore|g-home/.test(src),'Ortadaki Dünya kodu ve seçeneği kalkmalı');
assert(src.includes('<details class="sdet"><summary>Gelişmiş ses ayarları</summary>')&&src.includes("'</details>'"),'gelişmiş ses ayarları ayrı bölümde olmalı');
const ses=src.slice(src.indexOf("else if(k==='ses'){"),src.indexOf("else if(k==='hafiza'"));
const dI=ses.indexOf('<details class="sdet">');
for(const id of ["'vsel'","'aname'"])assert(ses.indexOf(id)>-1&&ses.indexOf(id)<dI,id+' görünür bölümde olmalı');
for(const id of ["'lstt'","'lsttmodel'","'lsttbeam'","'wsens'","'sfix'","'swords'","'micdev'"])assert(ses.indexOf(id)>dI,id+' gelişmiş bölümde olmalı');
assert(!src.includes('function quickSettings()'),'Sık Kullanılanlar kartı kalkmalı');
assert(!src.includes('function quickLinks()')&&!src.includes('applySettingsTabs'),'Kısayollar kartı ve otomatik sekmeler kalkmalı');
assert(src.includes("if(p==='settings'||p==='tools'){S.mnOpen=settingsNode("),'go(settings/tools) menüde ilgili düğümün yan sayfasını açmalı (eski Ayarlar sayfası yok)');
const railBody=src.slice(src.indexOf('function renderRail(){'),src.indexOf('function activities()'));
assert(!railBody.includes('Son Aktiviteler')&&!railBody.includes('Öneriler'),'Ayarlar sağ sütununda Son Aktiviteler/Öneriler olmamalı');
const qlSrc='';
for(const x of ["T('kb')","T('rapor')","T('veri')","Ekran görüntüsü al","Ekranı analiz et"])assert(!qlSrc.includes(x),x+' Kısayollar içinde olmamalı');
const menuSrc=src.slice(src.indexOf('ACT.cmore=el=>{'),src.indexOf('ACT.cmore=el=>{')+2600);
for(const x of ["tool('kb')","tool('rapor')","tool('veri')"])assert(!menuSrc.includes(x),x+' ••• menüsünde olmamalı');
// Araçlar giriş sayfası açılmaz: Ayarlar › Gelişmiş içindeki araç kutusuna gider
assert(src.includes("tools:['telefon','mesaj']")&&src.includes("tools:['takvim']")&&src.includes('function screenBox()'),'araçlar Ayarlar bölümlerinde olmalı');
assert(!src.includes('const t=TOOLS.find(x=>x[0]===v)'),'eski Araçlar listesi sayfası kalkmalı');
console.log('Sohbette dosya kartları: istek yakalama, kota harcamama, geliştirme erişimi ve kopyalama geçti.');
// Açılış takılması: ana ekran yeniden çizilirken hologram sökülüp baştan kurulmaz; geçici bağlantı hatası açılışta yeniden denenir
assert(src.includes("keepHome=S.page==='home'&&!!HOME_HOLOGRAM")&&src.includes("if(live&&HOME_HOLOGRAM){"),'ana ekran yeniden çizilirken hologram korunmalı');
assert(src.includes("performance.now()<20000"),'api() açılışta geçici bağlantı hatasını yeniden denemeli');
assert(src.includes("keyWarn=(S.snap&&!l.key)")&&src.includes("const boot=!S.snap?''"),'veri gelmeden "anahtar yok / kontrol gerekli" uyarısı gösterilmemeli (açılışta yanlış hata görünümü)');
