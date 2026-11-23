// Ekran/kamera paylaşımı: Ana ekran veya Ekran paneli açıkken ikinci (yüzen) önizleme penceresi açılmaz; Takvim'de seçili gün takvimle aynı blokta.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');
const a=src.indexOf('function miniHidden('),b=src.indexOf('function drawMiniPreview(');
assert(a>0&&b>a,'miniHidden bulunmalı');
const ctx={S:{page:'settings',sset:'ekran'},$:()=>null};
vm.createContext(ctx);vm.runInContext(src.slice(a,b),ctx);
const hidden=()=>vm.runInContext('miniHidden()',ctx);
assert.equal(hidden(),true,'Ekran ayarları açıkken yüzen önizleme gizli olmalı');
ctx.S.sset='takvim';assert.equal(hidden(),false,'başka ayar sayfası önizlemeyi gizlemez');
ctx.S.page='home';assert.equal(hidden(),true,'Ana ekran kendi çekirdek alanında önizleme gösterir');
ctx.S.page='files';ctx.$=()=>({});assert.equal(hidden(),true,'Konsoldaki önizleme tüm sekmelerde tek kalır');
ctx.$=()=>null;ctx.S.page='vision';assert.equal(hidden(),true,'Ekran sayfası ikinci önizlemeyi gizler');
assert(/if\(\$\('#vprev'\)&&!miniHidden\(\)\)miniTimer/.test(src),'yoklama döngüsü gizliyken sürmemeli');
// Takvim: seçili gün ayrı alt başlık değil, takvimin altında
const t=src.slice(src.indexOf('TV.takvim=el=>'),src.indexOf('ACT.calday='));
assert(!/data-mtitle="Seçili gün"/.test(t)&&/class="calsel"/.test(t),'seçili gün takvim bloğunun içinde olmalı');
assert(t.indexOf('calendar-grid')<t.indexOf('class="calsel"'),'seçili gün takvimin altında olmalı');
console.log('Paylaşım önizlemesi panel açıkken tek, Takvim seçili günü aynı blokta gösteriyor geçti.');
