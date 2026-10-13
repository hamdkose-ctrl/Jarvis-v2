// Ekran/kamera paylaşımı: Ekran paneli açıkken ikinci (yüzen) önizleme penceresi açılmaz; Takvim'de seçili gün takvimle aynı blokta.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');
const a=src.indexOf('function miniHidden('),b=src.indexOf('function drawMiniPreview(');
assert(a>0&&b>a,'miniHidden bulunmalı');
let docked=true;
const ctx={S:{page:'menu'},$:s=>s==='.mnscene.docked'&&docked?{}:null,window:{__mnNode:'ekran'}};
vm.createContext(ctx);vm.runInContext(src.slice(a,b),ctx);
const hidden=()=>vm.runInContext('miniHidden()',ctx);
assert.equal(hidden(),true,'Ekran paneli açıkken yüzen önizleme gizli olmalı');
ctx.window.__mnNode='takvim';assert.equal(hidden(),false,'başka panelde paylaşım önizlemesi görünmeli');
ctx.window.__mnNode='ekran';docked=false;assert.equal(hidden(),false,'panel kapanınca yüzen önizleme geri gelmeli');
docked=true;ctx.S.page='home';assert.equal(hidden(),false);
ctx.S.page='vision';assert.equal(hidden(),true,'eski Ekran sayfası da gizler');
// panel açılıp kapanınca önizleme yeniden çizilir; döngü gizliyken sürmez
assert(/menuSubsWatch\(sc\);drawMiniPreview\(\)/.test(src),'panel açılınca önizleme yeniden değerlendirilmeli');
assert(/menuUndock\(\);drawMiniPreview\(\)/.test(src),'panel kapanınca önizleme yeniden değerlendirilmeli');
assert(/if\(\$\('#vprev'\)&&!miniHidden\(\)\)miniTimer/.test(src),'yoklama döngüsü gizliyken sürmemeli');
// Takvim: seçili gün ayrı alt başlık değil, takvimin altında
const t=src.slice(src.indexOf('TV.takvim=el=>'),src.indexOf('ACT.calday='));
assert(!/data-mtitle="Seçili gün"/.test(t)&&/class="calsel"/.test(t),'seçili gün takvim bloğunun içinde olmalı');
assert(t.indexOf('calendar-grid')<t.indexOf('class="calsel"'),'seçili gün takvimin altında olmalı');
console.log('Paylaşım önizlemesi panel açıkken tek, Takvim seçili günü aynı blokta gösteriyor geçti.');
