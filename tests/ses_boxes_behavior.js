// Ses sayfası yan sayfada yedi bölüm olur; tüm alanlar DOM'da bir kez bulunur ve her bölümde Kaydet vardır (ACT.vsave hepsini okur).
// Eski "Canlı Konuşma" bölümü ve `live_*` anahtarları emekli edildi: sürgüler gerçek bir tüketicisi olan
// anahtara (`wake_beep`) bağlanır, tüketicisi olmayan ayar arayüzde kalmaz.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
const c={SX:{},esc:x=>String(x),ic:n=>'',pad18:x=>x,sbox:(i,t,s,b)=>`<blk t="${t}">${b}</blk>`,srow:(i,t,s,r)=>`<row>${t}|${r}</row>`,sw:(k,on)=>`<sw k="${k}"></sw>`,
 field:(l,ctl)=>`<field l="${l}">${ctl}</field>`,inp:(id)=>`<input id="${id}">`,localSttText:()=>'durum'};
vm.createContext(c);vm.runInContext(src.slice(src.indexOf('function sesBoxes('),src.indexOf('// Ekran ve Dosyalar yan sayfası')),c);
const sel=(id)=>`<select id="${id}"></select>`;
const html=c.sesBoxes({st:{},vo:{voices:[{key:'a',name:'A'}],voice:'a'},devs:[{name:'Mik'}],ls:{},sel,f:{mic:true,speak:false},u:{},sn:{prefs:{verbosity:'kısa'}}});
const titles=[...html.matchAll(/<blk t="([^"]+)">/g)].map(m=>m[1]);
assert.equal(titles.join('|'),'Mikrofon|Uyanma|Sesli Yanıt|Asistanın Adı|Yerel Ses Tanıma|Düzeltmeler|Konuşma Tarzı','yedi bölüm: her biri orbun çevresinde kendi orbunu alır');
for(const id of ['wsens','micdev','mmic','vsel','aname','lstt','lsttmodel','lsttbeam','sfix','swords'])assert.equal((html.match(new RegExp('id=\"'+id+'\"','g'))||[]).length,1,id+' bir kez');
const realSel=(id,opts,cur)=>`<select id="${id}">${opts.map(([v,t])=>`<option value="${v}" ${String(cur)===String(v)?'selected':''}>${t}</option>`).join('')}</select>`;
const mmicSelected=(st)=>{const h=c.sesBoxes({st,vo:{voices:[]},devs:[],ls:{},sel:realSel,f:{mic:true,speak:false},u:{},sn:{prefs:{}}});const seg=h.slice(h.indexOf('id="mmic"'));const on=seg.indexOf('value="1" selected'),off=seg.indexOf('value="0" selected');return on>=0&&(off<0||on<off);};
assert(mmicSelected({}),'model beklerken dinleme varsayılan olarak açık görünür');
assert(!mmicSelected({voice_mic_during_model_wait:false}),'kapalı seçim arayüzde görünür');
assert.equal((html.match(/data-act="vsave"/g)||[]).length,6,'alan içeren her bölümde Kaydet');
assert.equal((html.match(/id="lsil"|id="lidle"/g)||[]).length,0,'cevap hızı ve açık kalma süresi alanları kalktı');
assert(!html.includes('Canlı Konuşma'),'Gemini Live bölümü arayüzde kalmadı');
assert(!src.includes('live_mode')&&!src.includes('live_beep')&&!src.includes('live_silence_ms')&&!src.includes('live_idle_seconds')&&!src.includes('live_headphones'),'canlı konuşma ayar anahtarları arayüzden silindi');
assert(src.includes('sw(\'wake_beep\',u.wake_beep)'),'uyanima sesi sürgüsü gerçek tüketicisine bağlandı');
assert(!src.includes('data-act="phones"'),'kulaklık sürgüsü (tüketicisi Live mikrofona aitti) kaldırıldı');
assert(html.includes('data-act="verb"'),'konuşma tarzı Ses içinde');
// özgün Ayarlar düzeni korunur: gelişmiş ses ayarları ayrı <details> altında
assert(src.includes('<details class="sdet"><summary>Gelişmiş ses ayarları</summary>'),'Ayarlar sayfasındaki düzen aynı');
console.log('Ses bölümleri: yedi ayrı orb başlığı, tüm alanlar bir kez, her bölümde Kaydet geçti.');
