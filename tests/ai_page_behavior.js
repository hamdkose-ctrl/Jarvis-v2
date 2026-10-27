// Yapay zekâ sayfası: her sağlayıcı bir kart, karta basınca yalnız onun bağlantısı açılır, durum renkle gösterilir.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
const src=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');
let draws=0;
const S={snap:{llm:{provider:'groq',key:true,groq:{key:true},paid:{openai:{key:false},anthropic:{key:true}},ollama_up:false},google:{cred:true},youtube:{key:true,ok:true}}};
const SX={router:{key:true}};const ACT={};
const c={S,SX,ACT,$:()=>null,drawSettings:()=>draws++,esc:x=>String(x).replace(/[&<>\"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[m]))};
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
assert(/apv st-ok [^\"]*act\"[^>]*data-k=\"groq\"/.test(html),'aktif kart işaretli');
assert(/apv st-bad [^\"]*\"[^>]*data-k=\"ollama\"/.test(html)&&/apv st-warn [^\"]*\"[^>]*data-k=\"google\"/.test(html),'durum kart renginde');
assert(html.includes('Şu an kullanılıyor')&&!html.includes('Bunu kullan'),'aktif sağlayıcıda kullan düğmesi yok');
assert(!/Bağlantılar<\/button>|Durum özeti/.test(html),'Bağlantılar sekmesi ve durum özeti yok');
// karta basınca o sağlayıcının bağlantısı açılır
ACT.aipick({dataset:{k:'gemini'}});assert.equal(SX.aiSel,'gemini');assert.equal(draws,1);
html=c.aiPage(S.snap,panels);assert(html.includes('P-gemini')&&!html.includes('P-groq'));assert(html.includes('data-act="sval" data-k="ai_mode" data-v="gemini"'),'seçili ama kullanılmayan sağlayıcı için "Bunu kullan"');
ACT.aipick({dataset:{k:'openai'}});html=c.aiPage(S.snap,panels);assert(html.includes('P-openai')&&!html.includes('Bunu kullan'),'ücretli sağlayıcı kendi panelindeki onaylı etkinleştirmeyi kullanır');
ACT.aipick({dataset:{k:'zzz'}});html=c.aiPage(S.snap,panels);assert(html.includes('P-groq'),'bilinmeyen seçim aktif sağlayıcıya döner');
console.log('Yapay zekâ sayfası: sağlayıcı kartları, tek bağlantı paneli, renkli durum ve onaylı ücretli sağlayıcı akışı geçti.');

// Canlı hata regresyonu: ui-refresh, gerçek aiPage render yolunda legacy panel HTML'sinin
// metnine/DOM biçimine güvenmeden canonical backend status'tan yerel model panelini üretmelidir.
(async()=>{
  const uiSrc=fs.readFileSync(path.join(__dirname,'../webui/ui-refresh.js'),'utf8');
  const modelSlice=uiSrc.slice(uiSrc.indexOf('const baseAiPage=aiPage;'),uiSrc.lastIndexOf('})();'));
  const defaultStatus={
    local_backend:'ollama',
    local_model_preference:'llama3.2',
    local_effective_model:'qwen2.5-coder:7b',
    local_model_stale:true,
    local_model_warning:'Kayıtlı tercih kurulu olmadığı için aktif model otomatik seçildi.',
    local_models_checked:true,
    local_installed_models:['qwen2.5-coder:7b'],
    local_model_choice_provider:'ollama',
    local_model_select_enabled:true,
  };
  const status=process.env.JARVIS_LOCAL_MODEL_STATUS_JSON?JSON.parse(process.env.JARVIS_LOCAL_MODEL_STATUS_JSON):defaultStatus;
  const c2={
    S:{snap:{user:{slug:'hamdi',name:'Hamdi'},llm:{provider:'ollama',local_backend:'ollama',local_model:'llama3.2',ollama_up:true,ollama_url:'http://127.0.0.1:11434'},google:{},youtube:{}}},
    SX:{aiSel:'ollama'},ACT:{},$:()=>null,
    esc:x=>String(x).replace(/[&<>\"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[m])),
    srow:(i,t,s,ctl)=>`<div class="srow2"><b>${t}</b><small>${s}</small>${ctl||''}</div>`,
    sbox:(i,t,s,body)=>`<section class="sbox"><h3>${t}</h3><p>${s}</p>${body}</section>`,
    field:(label,input,hint)=>`<div class="field"><b>${label}</b>${input}<small>${hint||''}</small></div>`,
    pad18:h=>`<div class="pad">${h}</div>`,
    inp:(id,ph,val)=>`<input id="${id}" placeholder="${ph||''}" value="${val||''}">`,
    api:async name=>{assert.equal(name,'llm_status');return status},
    render:()=>{},sAfter:()=>{},msgOf:r=>String(r?.msg||''),refresh:async()=>{},
  };
  vm.createContext(c2);
  vm.runInContext(src.slice(src.indexOf('const AI_CARDS='),src.indexOf('\n',src.indexOf('ACT.aipick='))),c2);
  vm.runInContext(modelSlice,c2);
  const legacy={...panels,ollama:'<section><label>Yerel Model - Hamdi</label><input id="om" value="llama3.2"><button data-act="omsave">Modeli kaydet</button></section>'};
  const loading=c2.aiPage(c2.S.snap,legacy);
  assert(!loading.includes('id="om"'),'status yüklenirken bile legacy serbest metin input görünmemeli');
  assert(loading.includes('Kurulu Modeller'),'status yüklenirken canonical model paneli görünmeli');
  await new Promise(resolve=>setImmediate(resolve));
  const rendered=c2.aiPage(c2.S.snap,legacy);
  const effective=String(status.local_effective_model||'');
  const installed=Array.isArray(status.local_installed_models)?status.local_installed_models.map(String):[];
  const stale=String(status.local_model_preference||'');
  assert(rendered.includes('Aktif Model'),'gerçek render çıktısı aktif modeli göstermeli');
  assert(effective&&rendered.includes(effective),'backend effective model render edilmeli');
  assert(rendered.includes('Kurulu Modeller')&&rendered.includes('<select'),'kurulu model dropdown render edilmeli');
  for(const model of installed)assert(rendered.includes(`<option value="${model}"`),`kurulu model dropdown'da olmalı: ${model}`);
  if(stale&&!installed.includes(stale))assert(!rendered.includes(`<option value="${stale}"`),'stale tercih dropdown seçeneği olmamalı');
  assert(!rendered.includes('id="om"'),'legacy serbest metin model inputu render edilmemeli');
  assert(!rendered.includes('data-act="omsave"'),'legacy save yolu render edilmemeli');
  console.log('Yerel model paneli: production aiPage render yolunda canonical status ile deterministik render geçti.');
})().catch(err=>{console.error(err);process.exitCode=1});
