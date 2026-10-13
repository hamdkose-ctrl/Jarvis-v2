// Yapay zekâ sayfası: her sağlayıcı bir kart, karta basınca yalnız onun bağlantısı açılır, durum renkle gösterilir.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
let draws=0;
const S={snap:{llm:{provider:'groq',key:true,groq:{key:true},paid:{openai:{key:false},anthropic:{key:true}},ollama_up:false},google:{cred:true},youtube:{key:true,ok:true}}};
const SX={router:{key:true}};const ACT={};
const c={S,SX,ACT,$:()=>null,drawSettings:()=>draws++,esc:x=>String(x).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]))};
vm.createContext(c);
vm.runInContext(src.slice(src.indexOf('const AI_CARDS='),src.indexOf('\n',src.indexOf('ACT.aipick='))),c);
const panels={auto:'<i>P-auto</i>',gemini:'<i>P-gemini</i>',groq:'<i>P-groq</i>',openrouter:'<i>P-or</i>',ollama:'<i>P-ollama</i>',openai:'<i>P-openai</i>',anthropic:'<i>P-claude</i>',google:'<i>P-google</i>',youtube:'<i>P-yt</i>'};
const st=c.aiStates(S.snap);
assert.deepEqual(Object.keys(st).sort(),Object.keys(panels).sort(),'her kartın durumu var');
assert.equal(st.groq[0],'ok');assert.equal(st.ollama[0],'bad');assert.equal(st.openai[0],'bad');assert.equal(st.anthropic[0],'ok');assert.equal(st.google[0],'warn');assert.equal(st.auto[0],'ok');assert.equal(st.openrouter[0],'ok');assert.equal(st.youtube[0],'ok');
// varsayılan: şu an kullanılan sağlayıcının paneli açık, yalnız o panel görünür
let html=c.aiPage(S.snap,panels,'<b>EXTRA</b>');
assert(html.includes('P-groq')&&!html.includes('P-gemini')&&!html.includes('P-auto'),'yalnız seçili sağlayıcının bağlantısı açık');
assert(html.includes('EXTRA'),'ek kutu korunur');
assert.equal((html.match(/data-act="aipick"/g)||[]).length,9,'dokuz kart');
assert(/apv st-ok [^"]*act"[^>]*data-k="groq"/.test(html),'aktif kart işaretli');
assert(/apv st-bad [^"]*"[^>]*data-k="ollama"/.test(html)&&/apv st-warn [^"]*"[^>]*data-k="google"/.test(html),'durum kart renginde');
assert(html.includes('Şu an kullanılıyor')&&!html.includes('Bunu kullan'),'aktif sağlayıcıda kullan düğmesi yok');
assert(!/Bağlantılar<\/button>|Durum özeti/.test(html),'Bağlantılar sekmesi ve durum özeti yok');
// karta basınca o sağlayıcının bağlantısı açılır
ACT.aipick({dataset:{k:'gemini'}});assert.equal(SX.aiSel,'gemini');assert.equal(draws,1);
html=c.aiPage(S.snap,panels);assert(html.includes('P-gemini')&&!html.includes('P-groq'));assert(html.includes('data-act="sval" data-k="ai_mode" data-v="gemini"'),'seçili ama kullanılmayan sağlayıcı için "Bunu kullan"');
ACT.aipick({dataset:{k:'openai'}});html=c.aiPage(S.snap,panels);assert(html.includes('P-openai')&&!html.includes('Bunu kullan'),'ücretli sağlayıcı kendi panelindeki onaylı etkinleştirmeyi kullanır');
ACT.aipick({dataset:{k:'zzz'}});html=c.aiPage(S.snap,panels);assert(html.includes('P-groq'),'bilinmeyen seçim aktif sağlayıcıya döner');
console.log('Yapay zekâ sayfası: sağlayıcı kartları, tek bağlantı paneli, renkli durum ve onaylı ücretli sağlayıcı akışı geçti.');
