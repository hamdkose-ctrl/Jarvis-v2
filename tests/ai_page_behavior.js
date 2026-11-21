// Yapay zekâ sayfası: her sağlayıcı bir kart, karta basınca yalnız onun bağlantısı açılır, durum renkle gösterilir.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
const src=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');
let draws=0;
const S={snap:{user:{slug:'alice'},llm:{provider:'groq',key:true,groq:{key:true},custom_connections:[{enabled:true}],ollama_up:false},google:{cred:true},youtube:{key:true,ok:true}}};
const SX={routerOwner:'alice',router:{ready_connections:{groq:{state:'ok'}}}};const ACT={};
const c={S,SX,ACT,$:()=>null,drawSettings:()=>draws++,esc:x=>String(x).replace(/[&<>\"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[m]))};
vm.createContext(c);
vm.runInContext(src.slice(src.indexOf('const READY_LABELS='),src.indexOf('\n',src.indexOf('ACT.aipick='))),c);
const panels={auto:'<i>P-auto</i>',gemini:'<i>P-gemini</i>',groq:'<i>P-groq</i>',ollama:'<i>P-ollama</i>',custom:'<i>P-custom</i>',cloudflare:'<i>P-cf</i>',google:'<i>P-google</i>',youtube:'<i>P-yt</i>'};
const st=c.aiStates(S.snap);
assert.deepEqual(Object.keys(st).sort(),Object.keys(panels).sort(),'her kartın durumu var');
assert.equal(st.groq[0],'ok');assert.equal(st.ollama[0],'bad');assert.equal(st.custom[0],'ok');assert.equal(st.openai,undefined);assert.equal(st.anthropic,undefined);assert.equal(st.google[0],'warn');assert.equal(st.auto[0],'ok');assert.equal(st.openrouter,undefined);assert.equal(st.youtube[0],'ok');
let html=c.aiPage(S.snap,panels,'<b>EXTRA</b>');
assert(html.includes('P-groq')&&!html.includes('P-gemini')&&!html.includes('P-auto'),'yalnız seçili sağlayıcının bağlantısı açık');
assert(html.includes('EXTRA'),'ek kutu korunur');
assert.equal((html.match(/data-act="aipick"/g)||[]).length,8,'sekiz kart');
assert(/apv st-ok [^\"]*act\"[^>]*data-k=\"groq\"/.test(html),'aktif kart işaretli');
assert(/apv st-bad [^\"]*\"[^>]*data-k=\"ollama\"/.test(html)&&/apv st-warn [^\"]*\"[^>]*data-k=\"google\"/.test(html),'durum kart renginde');
assert(!html.includes('Bunu kullan'),'hazır sağlayıcı rol sırası değiştirilmez');
assert(!/Bağlantılar<\/button>|Durum özeti/.test(html),'Bağlantılar sekmesi ve durum özeti yok');
ACT.aipick({dataset:{k:'gemini'}});assert.equal(SX.aiSel,'gemini');assert.equal(draws,1);
html=c.aiPage(S.snap,panels);assert(html.includes('P-gemini')&&!html.includes('P-groq'));assert(!html.includes('data-v="gemini"'),'Gemini sabit profil adayıdır, global elle ücretli seçim yok');
ACT.aipick({dataset:{k:'custom'}});html=c.aiPage(S.snap,panels);assert(html.includes('P-custom')&&!html.includes('Bunu kullan'),'ücretli sağlayıcı kendi panelindeki onaylı etkinleştirmeyi kullanır');
ACT.aipick({dataset:{k:'zzz'}});html=c.aiPage(S.snap,panels);assert(html.includes('P-groq'),'bilinmeyen seçim aktif sağlayıcıya döner');
console.log('Yapay zekâ sayfası: sağlayıcı kartları, tek bağlantı paneli, renkli durum ve onaylı ücretli sağlayıcı akışı geçti.');

(async()=>{
  const htmlSrc=fs.readFileSync(path.join(__dirname,'../webui/nx.html'),'utf8');
  assert(htmlSrc.indexOf('src="/nx.js"')>=0&&htmlSrc.indexOf('src="/local-model-panel.js"')>htmlSrc.indexOf('src="/nx.js"'),'canlı HTML local model panelini nx.js sonrasında yüklemeli');
  assert(!htmlSrc.includes('/ui-refresh.js'),'ölü ui-refresh canlı model paneli yolu olmamalı');
  const modelSrc=fs.readFileSync(path.join(__dirname,'../webui/local-model-panel.js'),'utf8');
  assert(!modelSrc.includes('replaceLegacyModelEditor'),'HTML string replacement geri gelmemeli');
  assert(!modelSrc.includes('.indexOf('),'panel HTML yapısına string arama bağımlılığı olmamalı');
  assert(modelSrc.includes('class="model-id"'),'canonical model kimliği genel başlık dönüşümünden ayrılmalı');
  assert(modelSrc.includes('data-local-model-warning'),'stale preference uyarısı metin biçiminden bağımsız semantik işaret taşımalı');
  const defaultStatus={local_backend:'ollama',local_model_preference:'llama3.2',local_effective_model:'qwen2.5-coder:7b',local_model_stale:true,local_model_warning:'Kayıtlı tercih kurulu olmadığı için aktif model otomatik seçildi.',local_models_checked:true,local_installed_models:['qwen2.5-coder:7b'],local_model_choice_provider:'ollama',local_model_select_enabled:true};
  const status=process.env.JARVIS_LOCAL_MODEL_STATUS_JSON?JSON.parse(process.env.JARVIS_LOCAL_MODEL_STATUS_JSON):defaultStatus;
  let fullRenders=0,settingsRedraws=0;
  const c2={
    S:{snap:{user:{slug:'hamdi',name:'Hamdi'},llm:{provider:'ollama',local_backend:'ollama',local_model:'llama3.2',local_label:'Ollama',ollama_up:true,ollama_url:'http://127.0.0.1:11434'},google:{},youtube:{}}},
    SX:{aiSel:'ollama'},ACT:{},$:()=>null,
    esc:x=>String(x).replace(/[&<>\"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[m])),
    srow:(i,t,s,ctl)=>`<div class="srow2"><b>${t}</b><small>${s}</small>${ctl||''}</div>`,
    sbox:(i,t,s,body)=>`<section class="sbox"><h3>${t}</h3><p>${s}</p>${body}</section>`,
    field:(label,input,hint)=>`<div class="field"><b>${label}</b>${input}<small>${hint||''}</small></div>`,
    pad18:h=>`<div class="pad">${h}</div>`,inp:(id,ph,val)=>`<input id="${id}" placeholder="${ph||''}" value="${val||''}">`,
    api:async name=>{assert.equal(name,'llm_status');return status},settingsOpen:()=>true,drawSettings:()=>{settingsRedraws++},render:()=>{fullRenders++},sAfter:()=>{},msgOf:r=>String(r?.msg||''),refresh:async()=>{},
  };
  vm.createContext(c2);
  vm.runInContext(src.slice(src.indexOf('const READY_LABELS='),src.indexOf('\n',src.indexOf('ACT.aipick='))),c2);
  vm.runInContext(modelSrc,c2);
  const legacy={...panels,ollama:'<section><label>Yerel Model - Hamdi</label><input id="om" value="llama3.2"><button data-act="omsave">Modeli kaydet</button></section>'};
  const loading=c2.aiPage(c2.S.snap,legacy);
  assert(!loading.includes('id="om"'),'status yüklenirken legacy serbest metin input görünmemeli');
  assert(loading.includes('Kurulu Modeller'),'status yüklenirken canonical model paneli görünmeli');
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(fullRenders,0,'llm_status tamamlanınca tam render açık menü panelini sökmemeli');
  assert.equal(settingsRedraws,1,'llm_status tamamlanınca mevcut settings paneli yerinde yeniden çizilmeli');
  const rendered=c2.aiPage(c2.S.snap,legacy),effective=String(status.local_effective_model||''),installed=Array.isArray(status.local_installed_models)?status.local_installed_models.map(String):[],stale=String(status.local_model_preference||'');
  assert(rendered.includes('Aktif Model'),'gerçek production render aktif modeli göstermeli');
  assert(effective&&rendered.includes(effective),'backend effective model render edilmeli');
  assert(rendered.includes('Kurulu Modeller')&&rendered.includes('<select'),'kurulu model dropdown render edilmeli');
  for(const model of installed)assert(rendered.includes(`<option value="${model}"`),`kurulu model dropdown'da olmalı: ${model}`);
  if(stale&&!installed.includes(stale))assert(!rendered.includes(`<option value="${stale}"`),'stale tercih dropdown seçeneği olmamalı');
  assert(!rendered.includes('id="om"'),'legacy serbest metin model inputu render edilmemeli');
  assert(!rendered.includes('data-act="omsave"'),'legacy save yolu render edilmemeli');
  console.log('Yerel model paneli: canlı nx.html script zincirinde canonical status ile production render geçti.');
})().catch(err=>{console.error(err);process.exitCode=1});
