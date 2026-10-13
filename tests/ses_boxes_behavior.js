// Ses sayfası yan sayfada üç bölüm olur; tüm alanlar DOM'da bir kez bulunur ve her bölümde Kaydet vardır (ACT.vsave hepsini okur).
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
const c={SX:{},esc:x=>String(x),ic:n=>'',pad18:x=>x,sbox:(i,t,s,b)=>`<blk t="${t}">${b}</blk>`,srow:(i,t,s,r)=>`<row>${t}|${r}</row>`,sw:(k,on)=>`<sw k="${k}"></sw>`,
 field:(l,ctl)=>`<field l="${l}">${ctl}</field>`,inp:(id)=>`<input id="${id}">`,localSttText:()=>'durum'};
vm.createContext(c);vm.runInContext(src.slice(src.indexOf('function sesBoxes('),src.indexOf('// Ekran ve Dosyalar yan sayfası')),c);
const sel=(id)=>`<select id="${id}"></select>`;
const html=c.sesBoxes({st:{},vo:{voices:[{key:'a',name:'A'}],voice:'a'},devs:[{name:'Mik'}],ls:{},sel,f:{mic:true,speak:false},u:{},sn:{prefs:{verbosity:'kısa'}}});
const titles=[...html.matchAll(/<blk t="([^"]+)">/g)].map(m=>m[1]);
assert.equal(titles.join('|'),'Mikrofon|Uyanma|Sesli Yanıt|Canlı Konuşma|Asistanın Adı|Yerel Ses Tanıma|Düzeltmeler|Konuşma Tarzı','sekiz bölüm: her biri orbun çevresinde kendi orbunu alır');
for(const id of ['wsens','lidle','micdev','vsel','aname','lsil','lstt','lsttmodel','lsttbeam','sfix','swords'])assert.equal((html.match(new RegExp('id=\"'+id+'\"','g'))||[]).length,1,id+' bir kez');
assert.equal((html.match(/data-act="vsave"/g)||[]).length,7,'alan içeren her bölümde Kaydet');
assert(html.includes('data-act="verb"'),'konuşma tarzı Ses içinde');
// özgün Ayarlar düzeni korunur: gelişmiş ses ayarları ayrı <details> altında
assert(src.includes('<details class="sdet"><summary>Gelişmiş ses ayarları</summary>'),'Ayarlar sayfasındaki düzen aynı');
console.log('Ses bölümleri: sekiz ayrı orb başlığı, tüm alanlar bir kez, her bölümde Kaydet geçti.');
