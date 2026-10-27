/* Yerel model ayarı: UI yalnız canonical backend status'unu gösterir ve kullanıcı seçimini iletir. */
(function(){'use strict';
const baseAiPage=aiPage;
const view={key:'',at:0,data:null,busy:false};
const BACKEND_URL={ollama:'http://127.0.0.1:11434',lmstudio:'http://127.0.0.1:1234/v1',llamacpp:'http://127.0.0.1:8080/v1'};
function keyOf(sn){const l=sn?.llm||{};return [sn?.user?.slug||sn?.user?.name||'',l.local_backend||'ollama',l.local_model||''].join('|')}
function requestStatus(sn){
  const key=keyOf(sn),now=Date.now();
  if(view.key!==key){view.key=key;view.data=null;view.at=0}
  if(view.busy||now-view.at<8000)return;
  view.busy=true;view.at=now;let changed=false;
  api('llm_status').then(st=>{if(view.key===key){view.data=st||{};view.at=Date.now();changed=true}})
    .catch(()=>{}).finally(()=>{view.busy=false;if(changed&&S.snap&&keyOf(S.snap)===key&&settingsOpen())drawSettings()});
}
function modelEditor(st){
  const models=Array.isArray(st?.local_installed_models)?st.local_installed_models.map(String):[];
  const active=String(st?.local_effective_model||''),pref=String(st?.local_model_preference||'');
  const selected=models.includes(pref)?pref:(models.includes(active)?active:(models[0]||''));
  const checked=st?.local_models_checked===true,disabled=st?.local_model_select_enabled===false||!models.length;
  const options=models.length
    ?models.map(m=>`<option value="${esc(m)}" ${m===selected?'selected':''}>${esc(m)}</option>`).join('')
    :`<option value="">${checked?'Kurulu model yok':'Model listesi yükleniyor…'}</option>`;
  const info=st?.local_model_stale
    ?`<div class="mut" style="font-size:12.5px;margin-top:5px">${esc(st.local_model_warning||'Kayıtlı tercih kurulu olmadığı için aktif model otomatik seçildi.')}</div>`:'';
  return srow('spark','Aktif Model',esc(active||(checked?'Kurulu model yok':'Yükleniyor…')),'')+
    field('Kurulu Modeller',`<select class="sel" style="width:100%" id="local-model-select" ${disabled?'disabled':''}>${options}</select>`,models.length?'Yalnız backend tarafından bildirilen kurulu modeller seçilebilir.':checked?'Kurulu model bulunamadı; seçim kapalı.':'Backend model durumu okunuyor.')+
    pad18(`<button class="btn sm pri" data-act="localmodelsave" data-provider="${esc(st?.local_model_choice_provider||'')}" ${disabled?'disabled':''}>Modeli Kaydet</button> <button class="btn sm" data-act="connecthelp" data-provider="ollama">Ollama Kurulumu</button> <span class="mut">${esc(SX.om||'')}</span>${info}`);
}
function localPanel(sn){
  requestStatus(sn);
  const l=sn?.llm||{},st=view.key===keyOf(sn)?view.data:null;
  const backend=SX.lb||l.local_backend||'ollama',same=backend===(l.local_backend||'ollama');
  const url=BACKEND_URL[backend]||BACKEND_URL.ollama;
  return sbox('bolt',esc(l.local_label||'Ollama')+' · Yerel model','Bilgisayarında çalışan yerel model; internet ve anahtar gerekmez. Ollama, LM Studio veya llama.cpp (llama-server) seçilebilir; hepsi isteğe bağlıdır.',
    srow('spark','Durum',l.ollama_up?'Çalışıyor':'Kurulu değil veya çalışmıyor','')+
    srow('cpu','Yerel sunucu','LM Studio ve llama.cpp OpenAI uyumlu /v1 uç noktasıyla bağlanır',`<div class="seg">${[['ollama','Ollama'],['lmstudio','LM Studio'],['llamacpp','llama.cpp']].map(([v,t])=>`<button class="${backend===v?'on':''}" data-act="lbpick" data-v="${v}">${t}</button>`).join('')}</div>`)+
    field('Uç nokta',inp('lburl',url,same?l.ollama_url:''))+
    pad18(`<button class="btn sm pri" data-act="lbsave">Sunucuyu kaydet ve dene</button> <span class="mut">${esc(SX.lbm||'')}</span>`)+
    modelEditor(st));
}
ACT.localmodelsave=async el=>{
  const select=$('#local-model-select'),model=select?.value||'',provider=el.dataset.provider||'';
  if(!model||!provider){SX.om='Kurulu model seçilemedi.';return sAfter(0)}
  el.disabled=true;
  try{
    const r=await api('model_choice_save',provider,model);SX.om=(r&&r.ok===false?'✗ ':'')+msgOf(r);
    if(r&&r.ok!==false){view.data=null;view.at=0;await refresh()}
  }catch(e){SX.om='✗ '+e.message}
  sAfter(0);
};
aiPage=function(sn,panels,extra=''){return baseAiPage(sn,{...panels,ollama:localPanel(sn)},extra)};
})();
