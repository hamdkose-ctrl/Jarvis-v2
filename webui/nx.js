// JARVIS — yeni arayüz (nx). Gerçek motora bağlı: /api/<ad> (web.Bridge) ve /events (anlık olaylar).
'use strict';
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let TOKEN=new URLSearchParams(location.hash.slice(1)).get('key')||'';
if(TOKEN)history.replaceState(null,'',location.pathname);
try{if(TOKEN)sessionStorage.setItem('jt',TOKEN);else TOKEN=sessionStorage.getItem('jt')||''}catch(e){}
const AUTH_READY=fetch('/session',{method:'POST',headers:{'X-Jarvis-Token':TOKEN}}).then(r=>{if(!r.ok)throw new Error('Jarvis erişim oturumu kurulamadı.');});
const store={get(k,d){try{const v=localStorage.getItem('nx.'+k);return v==null?d:JSON.parse(v)}catch(e){return d}},set(k,v){try{localStorage.setItem('nx.'+k,JSON.stringify(v))}catch(e){}}};
async function api(name,...args){
  await AUTH_READY;
  let r;
  for(let i=0;;i++){
    try{r=await fetch('/api/'+name,{method:'POST',headers:{'Content-Type':'application/json','X-Jarvis-Token':TOKEN},body:JSON.stringify(args)});break}
    catch(e){if(i<3&&performance.now()<20000){await new Promise(z=>setTimeout(z,400+i*400));continue}throw new Error('Jarvis’e ulaşılamadı; yeniden başlıyor olabilir.')}
  }
  const j=await r.json();if(!j.ok)throw new Error(j.error||'Hata');return j.data;
}
async function tryApi(name,...a){try{return await api(name,...a)}catch(e){toast(e.message,'bad')}}
function toast(msg,kind){if(kind!=='bad'&&S.ui&&S.ui.nx_notify===false)return;const d=document.createElement('div');if(kind)d.className=kind;d.textContent=msg;$('#toast').appendChild(d);setTimeout(()=>d.remove(),kind==='bad'?6500:4000)}
const S={snap:null,ui:null,page:'home',orb:'idle',speech:null,chat:[],live:[],hist:null,day:null,since:0,files:null,fsel:null,fcat:'all',fq:'',sset:'ai',waiting:false,sc:null,ftab:'genel',att:[],attPending:0,steps:{},pcMuted:null};
const DAYS=['Pazar','Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi'],MONTHS=['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'];
const pad=n=>String(n).padStart(2,'0');
const hm=ts=>{const d=new Date(ts*1000);return pad(d.getHours())+':'+pad(d.getMinutes())};
const fmtSize=b=>b>=1048576?(b/1048576).toFixed(1)+' MB':b>=1024?Math.round(b/1024)+' KB':b+' B';
const fmtDate=ts=>{const d=new Date(ts*1000);return pad(d.getDate())+'.'+pad(d.getMonth()+1)+'.'+d.getFullYear()};
const ymd=d=>d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());

// ======================================================================= masaüstü gezintisi
const NAV=[
  ['home','Ana ekran','home'],['chat','Sohbet','msg'],['files','Dosyalar','folder'],
  ['vision','Ekran ve PC','monitor'],['team','Ekip Merkezi','grid'],
  ['study','Çalışma','book'],['tools','Günlük işler','calendar'],['settings','Ayarlar','gear'],
  ['map','Harita','globe']
];
function renderTop(){
  const top=$('#top'),home=S.page==='home';
  top.closest?.('.workspace')?.classList.toggle('workspace-console',home);
  if(home){top.innerHTML='';return}
  const sn=S.snap||{}, n=needCount(), win=sn.winctl!==false;
  const name=(sn.user||{}).name||'Kullanıcı';
  $('#workspace-nav').innerHTML=NAV.filter(([key])=>key!=='map').map(([key,label,glyph])=>
    `<button type="button" data-go="${key}" ${S.page===key?'aria-current="page"':''}>${ic(glyph)}<span>${label}</span></button>`).join('');
  $('#workspace-profile').innerHTML=`<button type="button" data-act="user" aria-label="Kullanıcı değiştir"><span class="profile-mark">${esc(name.charAt(0))}</span><span><b>${esc(name)}</b><small>Profil ve ayarlar</small></span>${ic('chev')}</button>`;
  top.innerHTML=`<strong>${esc(NAV.find(([key])=>key===S.page)?.[1]||'Jarvis')}</strong>
   <div class="top-actions"><span id="clock" aria-hidden="true"></span>
    <button class="ab" data-act="notif" aria-label="Bildirimler">${ic('bell')}${n?`<span class="notice-count">${n}</span>`:''}</button>
    ${win?`<button class="ab" data-act="wmin" aria-label="Pencereyi küçült">−</button><button class="ab" data-act="wfull" aria-label="Tam ekran veya pencere">□</button><button class="ab" data-act="wclose" aria-label="Pencereyi kapat">×</button>`:''}
   </div>`;
  tick();
}
function tick(){const clock=$('#clock');if(clock)clock.textContent=hm(Date.now()/1000)}

function needCount(){const sn=S.snap;if(!sn)return 0;return (sn.pending_facts||[]).length+(sn.llm&&!sn.llm.key?1:0)+(sn.google&&!sn.google.token?1:0)}
// GitHub durumu ve yükle/al düğmeleri (ana ekrandan Ayarlar › Gelişmiş'e taşındı; yalnız kullanıcı basınca çalışır)
// Araçlar (eski ayrı sayfa) Ayarlar › Gelişmiş içinde: kartlar aynı araç görünümlerini açar.
function toolsBox(){
  return sbox('gear','Araçlar','Takvim, görevler, telefon ve bakım.',`<div class="agrid" style="padding:12px 18px">${TOOLS.filter(x=>x[0]!=='aihub').map(([k,c,i,t,s])=>`<button class="acard ${c}" data-act="tool" data-k="${k}"><span class="ib ${c}">${ic(i)}</span><b>${t}</b><small>${s}</small><span class="go">${ic('chev')}</span></button>`).join('')}</div>`);
}
function heyTxt(){const f=(S.snap||{}).flags||{};return f.sleep?'Uykuda':!f.mic?'Mikrofon kapalı':(DOCK_ST[S.orb]||'Hazır')}

// ======================================================================= gezinme ve olaylar
function go(p){
  if(p==='menu')p='home'; // Kayıtlı eski adresler tek masaüstü kabuğuna taşınır.
  if(!NAV.some(n=>n[0]===p))p='home';
  if(p!=='chat'&&S.snap?.development?.enabled&&S.snap?.development?.unlocked){
    if(S.leavingDevelopment)return;S.leavingDevelopment=true;
    api('development_disable').then(result=>{if(!result.ok)throw new Error(result.message||'Geliştirme ekranından çıkılamadı.');S.snap.development.enabled=false;S.snap.development.unlocked=false;go(p);refreshSoon()}).catch(e=>toast(e.message,'bad')).finally(()=>{S.leavingDevelopment=false});return;
  }
  S.sq='';
  S.page=p;render();
}

function render(){
  const pg=$('#page'), dock=$('#dock');
  const focused=dock?.contains(document.activeElement);
  if(dock)dock.remove();
  renderTop();
  pg.className='page p-'+S.page;
  if(S.page==='home'){
    if(!pg.querySelector('.jarvis-console')){pg.innerHTML='';PAGES.home(pg)}
    else{updateHome();drawHomeMessages()}
    drawAtt();drawMiniPreview();
    return;
  }
  window.JarvisHome?.destroy();
  pg.innerHTML='';
  if(S.page==='team'&&!PAGES.team)return;
  PAGES[S.page](pg);
  drawDock(dock);drawAtt();drawMiniPreview();if(focused)$('#dock input')?.focus();
}
document.addEventListener('click',e=>{
  const g=e.target.closest('[data-go]');if(g){e.preventDefault();if(g.closest('#workspace-nav')){S.tool='';if(g.dataset.go==='tools')S.sset='takvim';if(g.dataset.go==='settings')S.sset='ai'}go(g.dataset.go);return}
  const sy=e.target.closest('[data-say]');if(sy){e.preventDefault();const v=sy.dataset.say;if(v.startsWith('#'))return go(v.slice(1));say(v);return}
  // Önce açık menüyü kapat, sonra düğmenin işini yap: yoksa profil/bildirim menüsü açılır açılmaz kapanıyordu.
  const a=e.target.closest('[data-act]');if(a&&ACT[a.dataset.act]){e.preventDefault();closeMenu();Promise.resolve(ACT[a.dataset.act](a,e)).catch(err=>toast(err.message||String(err),'bad'));return}
  if(!e.target.closest('.menu'))closeMenu();
});
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.matches('.ask input')){e.preventDefault();if(S.attPending)return toast('Dosyanın yüklenmesini bekle.');const v=e.target.value.trim();if(v||atts().length){e.target.value='';say(v)}}if(e.key==='Escape'){closeMenu();if(S.orb==='speaking'||S.sspeaking)ACT.dstop()}});

// ======================================================================= arayüze uygun soru pencereleri (tarayıcının gri kutusu yerine)
function _dlg(title,msg,input,def){return new Promise(res=>{const o=document.createElement('div');o.className='jdlg';
  o.innerHTML=`<div class="jbox"><div class="jt">${ic('spark')}<b>${esc(title)}</b></div><p>${esc(msg)}</p>${input?`<input class="jin" type="${input==='password'?'password':'text'}" autocomplete="${input==='password'?'current-password':'off'}" value="${esc(def||'')}">`:''}<div class="jbtn"><button class="jno">İptal</button><button class="jok">${input?'Tamam':'Evet'}</button></div></div>`;
  document.body.appendChild(o);const inp=o.querySelector('.jin');(inp||o.querySelector('.jok')).focus();
  const done=v=>{if(inp)inp.value='';o.remove();document.removeEventListener('keydown',kd,true);res(v)};
  const kd=e=>{if(e.key==='Escape'){e.stopPropagation();done(input?null:false)}else if(e.key==='Enter'){e.stopPropagation();e.preventDefault();done(input?inp.value:true)}};
  document.addEventListener('keydown',kd,true);
  o.querySelector('.jno').onclick=()=>done(input?null:false);o.querySelector('.jok').onclick=()=>done(input?inp.value:true);
  o.onclick=e=>{if(e.target===o)done(input?null:false)}})}
const ask=msg=>_dlg('JARVIS',msg,false);
const askText=(msg,def)=>_dlg('JARVIS',msg,true,def);
const ACT={};
ACT.devopen=async()=>{
 const owner=((S.snap||{}).user||{}).name,st=await api('development_status');
 if(!st.unlocked){const password=await _dlg('Şifre Korumalı Geliştirme Modu',st.password_set?'Geliştirme şifreni gir.':'İlk giriş: geliştirme için bir şifre oluştur (en az 6 karakter).','password','');if(password===null)return;
 if(owner!==((S.snap||{}).user||{}).name)return;
 const result=await api('development_unlock',password);if(!result.ok)return toast(result.message,'bad');}
 const enabled=await api('development_enable');
 if(!enabled.ok)return toast(enabled.message||'Geliştirme modu açılamadı.','bad');
 await refresh();go('chat');
};
ACT.devclose=async()=>{
 const result=await api('development_disable');
 if(!result.ok)return toast(result.message||'Geliştirme modu kapatılamadı.','bad');
 refreshSoon();
};
ACT.devexport=async()=>{const r=await api('development_export');await api('file_open',r.path);toast('Geliştirme dosyaları dışa aktarıldı.');};
ACT.devpassword=async()=>{
 const owner=((S.snap||{}).user||{}).name;
 const old=await _dlg('Şifre Korumalı Geliştirme Modu','Mevcut geliştirme şifren:','password','');if(old===null)return;
 const next=await _dlg('Şifre Korumalı Geliştirme Modu','Yeni geliştirme şifren:','password','');if(next===null||owner!==((S.snap||{}).user||{}).name)return;
 const r=await api('development_password_change',old,next);toast(r.message,r.ok?'':'bad');
};
ACT.homenote=()=>{S.tool='gorev';go('tools');setTimeout(()=>{const editor=$('#nti')?.closest('details');if(editor)editor.open=true;$('#nti')?.focus()},50)};
ACT.mute=async el=>{const on=((S.snap||{}).flags||{}).speak!==false;if(on)tryApi('stop_speaking');const f=await tryApi('set_flag','speak',!on);if(f===null||f===undefined)return;if(S.snap){S.snap.flags={...(S.snap.flags||{}),...((f&&typeof f==='object')?f:{}),speak:!on}}toast(on?'Jarvis susturuldu. Yazıyla cevap vermeye devam eder.':'Jarvis’in sesi açıldı.');$$('[data-act="mute"]').forEach(b=>{const c=b.classList.contains('hb2')?'hb2':'ab';b.outerHTML=muteBtn(c)});if(S.page==='home')updateHomeStatus()};
ACT.mictoggle=async()=>{if(S.page==='chat'&&S.snap?.development?.enabled&&S.snap?.development?.unlocked)return toast('Geliştirme ekranında ses kapalı; yazıyla devam et.');if(S.micToggling||!S.snap)return;const on=S.snap?.flags?.mic!==false,owner=S.snap?.user?.name;S.micToggling=true;try{const flags=await tryApi('set_flag','mic',!on);if(owner!==S.snap?.user?.name||!flags||typeof flags.mic!=='boolean')return;S.snap.flags={...(S.snap.flags||{}),...flags};$$('[data-act="mictoggle"]').forEach(b=>{b.outerHTML=micToggleBtn(b.classList.contains('hb2')?'hb2':'ab')});toast(flags.mic?'Mikrofon açıldı.':'Mikrofon kapatıldı.');if(S.page==='home')updateHomeStatus()}finally{S.micToggling=false}};
ACT.wmin=()=>tryApi('win','min');ACT.wfull=()=>tryApi('win','full');ACT.wclose=async ()=>{if(await ask('Jarvis kapatılsın mı?'))tryApi('shutdown')};
function openAiHub(tab='ai'){S.sset=tab;S.tool='aihub';go('tools')}
ACT.keysetup=()=>openAiHub('baglanti');
async function say(text){
  if(S.attPending)return toast('Dosyanın yüklenmesini bekle.');
  const _q=String(text||'').trim(),_noAtt=!(Array.isArray(S.att)?S.att.length:(S.att?1:0));  // "dosyalarımı göster" / "takvimim": tarayıcıda cevaplanır, modele gitmez
  if(_noAtt&&/^(dosyalar[ıi]m[ıi]?(\s+(g[öo]ster|listele))?|son\s+y[üu]klediklerim|y[üu]klediğim\s+dosyalar|dosyalar[ıi]\s+(g[öo]ster|listele))\s*[.!?]*$/i.test(_q))return showFileCards(text);
  if(_noAtt&&/^(takvimim|ajandam|hat[ıi]rlatmalar[ıi]m|g[öo]revlerim|yakla[şs]an\s+(hat[ıi]rlatmalar|etkinlikler|g[öo]revler)|takvimi\s+g[öo]ster|g[öo]revleri\s+g[öo]ster)\s*[.!?]*$/i.test(_q))return showAgendaCard(text);
  // Ekli dosyalar tek istekte gider ('"a" "b" talimat'): sunucu karşılaştırma/birleştirme gibi işleri birlikte yapar,
  // diğer işleri dosya dosya yürütür. Sunucunun yankısı aynı metinle geldiği için balon tekrarlanmaz.
  const files=Array.isArray(S.att)?S.att:(S.att?[S.att]:[]);if(files.length){S.att=[];drawAtt()}
  if(S.page!=='home'&&S.page!=='chat'){S.day=ymd(new Date());go('chat')}
  const sends=files.length?[files.map(a=>`"${a.path}"`).join(' ')+' '+(text||(files.length>1?'dosyalarını kapsamlı analiz et':'dosyasını kapsamlı analiz et'))]:[text];
  for(const send of sends){
    S.live.push({role:'user',text:send,ts:Date.now()/1000,mine:true});S.waiting=true;drawMsgs();
    try{const rid=globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+Math.random().toString(36).slice(2);const queued=await api('send',send,rid);if(queued===false){S.waiting=false;drawMsgs()}}catch(e){S.waiting=false;drawMsgs();toast(e.message,'bad');break}
  }
}
ACT.send=el=>{if(S.attPending)return toast('Dosyanın yüklenmesini bekle.');const i=el.closest('.ask').querySelector('input');const v=i.value.trim();if(v||atts().length){i.value='';say(v)}};
ACT.mic=async()=>{if(S.page==='chat'&&S.snap?.development?.enabled&&S.snap?.development?.unlocked)return toast('Geliştirme ekranında ses kapalı; yazıyla devam et.');const listening=await tryApi('listen_once');if(listening===false)return toast('Mikrofon kapalı. Önce mikrofonu aç.');if(listening===true)toast('Dinliyorum… konuşabilirsin.')};
ACT.attach=()=>{if(S.page==='chat'||S.page==='home')return pickAttach();pickUpload(null)};
async function attachChatFile(file){
 if(atts().length+(S.attPending||0)>=MAX_ATT)return toast(`En fazla ${MAX_ATT} dosya ekleyebilirsin.`);
 if(file.size===0)return toast(`${file.name} boş; eklenmedi.`,'bad');
 if(file.size>MAX_ATT_BYTES)return toast(`${file.name} 200 MB'tan büyük; eklenmedi.`,'bad');
 const owner=S.snap?.user?.name;S.attPending=(S.attPending||0)+1;drawAtt();
 toast(`${file.name} yükleniyor…`);
 try{
  const r=await upload(file,true);
  if(!r||owner!==S.snap?.user?.name)return;
  S.att=[...atts(),{path:r.path,name:file.name}];S.files=null;
  toast(`${file.name} eklendi. Ne yapmamı istediğini yazıp gönder.`);
  ($('.ask input')||$('.jarvis-console #message'))?.focus();
 }finally{S.attPending=Math.max(0,(S.attPending||0)-1);drawAtt()}
}
const MAX_ATT=10,MAX_ATT_BYTES=200_000_000;
const atts=()=>Array.isArray(S.att)?S.att:(S.att?[S.att]:[]);
function pasteChatImage(e){
 if(!['chat','home'].includes(S.page)||!e.target.matches?.('.ask input, .jarvis-console #message'))return;
 const items=Array.from(e.clipboardData?.items||[]);
 const item=items.find(x=>x.kind==='file'&&x.type.startsWith('image/'));
 const image=item?.getAsFile()||Array.from(e.clipboardData?.files||[]).find(x=>x.type.startsWith('image/'));
 if(!image)return;
 e.preventDefault();
 const ext=({'image/png':'png','image/jpeg':'jpg','image/webp':'webp','image/gif':'gif'})[image.type]||'png';
 const file=new File([image],`ekran-${Date.now()}.${ext}`,{type:image.type});
 return attachChatFile(file);
}
document.addEventListener('paste',pasteChatImage);
// Pencerenin her yerine bırakılan dosya tarayıcıda açılmaz, sohbete eklenir. Kendi bırakma alanı olan kutular
// (ör. Matematik) olayı önce işler; o zaman burada tekrar yüklenmez.
let dragDepth=0;
const dragKind=e=>{const t=[...(e.dataTransfer?.types||[])];return t.includes('Files')?'file':t.some(x=>x==='text/uri-list'||x==='text/plain')?'text':''};
const editable=el=>!!el?.closest?.('input,textarea,[contenteditable="true"]');
function dropOverlay(on){let o=$('#dropov');if(on&&!o){o=document.createElement('div');o.id='dropov';o.className='dropov';o.innerHTML=`<div>${ic('clip')}<b>Dosyaları sohbete eklemek için bırak</b><small>En fazla ${MAX_ATT} dosya · her biri en fazla 200 MB</small></div>`;document.body.appendChild(o)}else if(!on&&o)o.remove()}
function droppedFiles(dt){
 const items=[...(dt?.items||[])].filter(it=>it.kind==='file');let folders=0;
 if(!items.length)return {files:[...(dt?.files||[])],folders};
 const files=[];for(const it of items){const entry=it.webkitGetAsEntry?.();if(entry?.isDirectory){folders++;continue}const f=it.getAsFile();if(f)files.push(f)}
 return {files,folders};
}
async function dropToChat(files,folders,text){
 if(folders)toast('Klasör eklenemez; klasörün içindeki dosyaları seçip bırak.','bad');
 if(!files.length){if(text){const i=$('.ask input')||$('.jarvis-console #message');if(i){i.value=(i.value?i.value+' ':'')+text.trim();i.focus()}}return}
 if(!['chat','home'].includes(S.page)){S.day=ymd(new Date());go('chat')}
 for(const f of files)await attachChatFile(f);
}
document.addEventListener('dragenter',e=>{const k=dragKind(e);if(!k||(k==='text'&&editable(e.target)))return;e.preventDefault();if(k==='file'){dragDepth++;dropOverlay(true)}});
document.addEventListener('dragover',e=>{const k=dragKind(e);if(!k||(k==='text'&&editable(e.target)))return;e.preventDefault();if(e.dataTransfer)e.dataTransfer.dropEffect='copy'});
document.addEventListener('dragleave',e=>{if(dragKind(e)!=='file')return;dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)dropOverlay(false)});
document.addEventListener('dragend',()=>{dragDepth=0;dropOverlay(false)});
document.addEventListener('drop',e=>{dragDepth=0;dropOverlay(false);const k=dragKind(e);if(!k||e.defaultPrevented||(k==='text'&&editable(e.target)))return;e.preventDefault();
 const {files,folders}=droppedFiles(e.dataTransfer);const text=files.length?'':(e.dataTransfer.getData('text/uri-list')||e.dataTransfer.getData('text/plain')||'');
 dropToChat(files,folders,text).catch(err=>toast(err.message||String(err),'bad'))});
function pickAttach(accept=''){const inp=$('#upl');inp.accept=accept;inp.onchange=async()=>{const fs=[...inp.files];inp.value='';for(const f of fs)await attachChatFile(f)};inp.click()}
function drawAtt(){const list=atts();$$('.attc').forEach(c=>{c.innerHTML=list.map((a,i)=>`<span class="attchip" title="${esc(a.path)}">${ic('clip')}<b>${esc(a.name)}</b><button data-act="attx" data-i="${i}" title="Kaldır">×</button></span>`).join('')+(S.attPending?`<span class="attchip pending">${ic('clock')}<b>Yükleniyor…</b></span>`:'')})}
ACT.attx=el=>{const i=Number(el?.dataset?.i);S.att=atts().filter((_,k)=>k!==i);drawAtt()};
ACT.image=()=>{if(S.page==='chat'||S.page==='home')return pickAttach('image/*');pickUpload('gorsel','image/*')};
function pickUpload(action,accept){const inp=$('#upl');inp.accept=accept||'';inp.onchange=async()=>{const fs=[...inp.files];inp.value='';for(const f of fs){const r=await upload(f);if(r&&action)await doFile(r.path,action)}if(!action&&fs.length){S.files=null;S.fcat='mine';S.fsel=null;toast(`${fs.length} dosya Belgeler › Jarvis Dosyaları klasörüne kaydedildi.`);if(S.page==='files')render()}};inp.click()}
async function upload(file,quiet){
  if(!quiet)toast(`${file.name} yükleniyor…`);
  try{const r=await fetch('/upload?to=files&name='+encodeURIComponent(file.name),{method:'POST',headers:{'X-Jarvis-Token':TOKEN},body:file});const j=await r.json();if(!j.ok)throw new Error(j.error);if(!quiet)toast(`${file.name} yüklendi (Belgeler › Jarvis Dosyaları).`);return j.data}
  catch(e){toast('Yüklenemedi: '+e.message,'bad')}
}
async function doFile(path,action){
  const cmd=await tryApi('file_do',path,action);if(!cmd)return;
  S.day=ymd(new Date());S.live.push({role:'user',text:cmd,ts:Date.now()/1000,mine:true});S.waiting=true;if(S.page!=='home'&&S.page!=='chat')go('chat');else drawMsgs();
}
function menu(x,y,items){closeMenu();const m=document.createElement('div');m.className='menu';m.id='menu';
  m.innerHTML=items.map((it,i)=>it==='-'?'<hr>':`<button data-mi="${i}">${it[0]?ic(it[0]):''}${esc(it[1])}</button>`).join('');document.body.appendChild(m);
  const r=m.getBoundingClientRect();m.style.left=Math.max(8,Math.min(x,innerWidth-r.width-10))+'px';m.style.top=Math.max(8,Math.min(y,innerHeight-r.height-10))+'px';
  m.onclick=e=>{const b=e.target.closest('[data-mi]');if(b){closeMenu();items[+b.dataset.mi][2]()}}}
function closeMenu(){const m=$('#menu');if(m)m.remove()}
ACT.user=(el,e)=>{const sn=S.snap||{};const us=sn.users||[];const me=(sn.user||{}).name;const r=el.getBoundingClientRect();
  menu(r.left,r.bottom+8,[...us.map(u=>['user',u+(u===me?'  ·  aktif':''),()=>{if(u!==me)api('user_switch',u).then(()=>setTimeout(refresh,800))}]),'-',['gear','Ayarlar',()=>go('settings')],['power','Jarvis’i kapat',async ()=>{if(await ask('Jarvis kapatılsın mı?'))api('shutdown')}]]);
  const m=$('#menu');if(m){m.classList.add('umenu');m.style.width=r.width+'px';[...m.querySelectorAll('button')].forEach(b=>{if(/·  aktif$/.test(b.textContent))b.classList.add('on')})}};
ACT.notif=el=>{const sn=S.snap||{},r=el.getBoundingClientRect(),it=[];
  if((sn.pending_facts||[]).length)it.push(['spark',`${sn.pending_facts.length} bilgi onay bekliyor`,()=>{S.sset='hafiza';go('settings')}]);
  if(sn.llm&&!sn.llm.key)it.push(['key','Gemini anahtarı eksik',()=>openAiHub('baglanti')]);
  if(sn.google&&!sn.google.token)it.push(['mail','Gmail ve Takvim bağlı değil',()=>openAiHub('baglanti')]);
  if(!it.length)it.push(['check','Yeni bildirim yok',()=>{}]);menu(r.left-120,r.bottom+6,it)};

// ======================================================================= ortak parçalar
const micToggleBtn=(cls='ab')=>{if(S.page==='chat'&&S.snap?.development?.enabled&&S.snap?.development?.unlocked)return '';const off=S.snap?.flags?.mic===false;return `<button class="${cls} mic-toggle ${off?'off':''}" data-act="mictoggle" title="${off?'Mikrofonu aç':'Mikrofonu kapat'}" aria-label="${off?'Mikrofonu aç':'Mikrofonu kapat'}" aria-pressed="${off}">${ic('mic')}</button>`};
const pcMuteBtn=(cls='ab')=>{const off=S.pcMuted===true;return `<button class="${cls} pcmute ${off?'off':''}" data-act="pcmute" title="${off?'Bilgisayarın sesini aç':'Bilgisayarın tüm sesini kapat'}" aria-label="${off?'Bilgisayarın sesini aç':'Bilgisayarın tüm sesini kapat'}" aria-pressed="${off}">${ic(off?'speakerx':'speaker')}</button>`};
function drawPcMute(){$$('[data-act="pcmute"]').forEach(b=>{b.outerHTML=pcMuteBtn(b.classList.contains('hb2')?'hb2':'ab')})}
function loadPcMute(){api('pc_mute_state').then(r=>{S.pcMuted=r&&typeof r.muted==='boolean'?r.muted:null;drawPcMute()}).catch(()=>{})}
ACT.pcmute=async()=>{if(S.pcMuteBusy)return;S.pcMuteBusy=true;try{const r=await tryApi('pc_mute',S.pcMuted!==true);if(r&&typeof r==='object'){S.pcMuted=r.muted===true;toast(S.pcMuted?'Bilgisayarın tüm sesi kapatıldı.':'Bilgisayarın sesi açıldı.');drawPcMute()}}finally{S.pcMuteBusy=false}};
const muteBtn=(cls='ab')=>{const off=((S.snap||{}).flags||{}).speak===false;return `<button class="${cls} amute ${off?'off':''}" data-act="mute" title="${off?'Jarvis’in sesini aç':'Jarvis’i sustur (yazıyla cevap verir)'}">${ic(off?'volx':'vol')}</button>`};
const DOCK_PH={vision:'Ekran Ya Da Görsel Hakkında Bir Şey Sor...',files:'Dosyalar Hakkında Bir Şey Sor...',study:'Çalışma Konusu Hakkında Sor...',settings:'Bir Şey Söyle Veya Yaz...'};
const DOCK_ST={idle:'Hazır',listening:'Dinliyor',thinking:'Düşünüyor',working:'Çalışıyor',speaking:'Konuşuyor'};
function drawDock(previous=null){
  const host=$('#dockhost')||$('#workspace-composer');
  let d=previous||$('#dock');
  if(!d){d=document.createElement('div');d.id='dock';d.className='dock'}
  if(d.parentElement!==host)host.appendChild(d);
  const old=d.querySelector('input'),v=old?old.value:'',f=old&&document.activeElement===old;
  d.innerHTML=askBar(DOCK_PH[S.page]||'Jarvis’e yaz…');dockState();
  const input=d.querySelector('input');input.value=v;if(f)input.focus();
}
function dockState(){if(S.sspeaking){if(S.orb==='speaking')S._spk2=1;else if(S._spk2&&S.orb==='idle'){S.sspeaking=0;S._spk2=0;const la=$('#slessonact');if(la)la.innerHTML=lessonActs()}}const d=$('#dock');if(!d)return;const s=DOCK_ST[S.orb]?S.orb:'idle';d.dataset.s=s;const b=d.querySelector('.dst');if(b)b.textContent=DOCK_ST[s]}
const askBar=(ph='Bir Şey Söyle Veya Yaz...')=>`<div class="card hask ask"><button class="hb2" data-act="attach" title="Dosya ekle" aria-label="Dosya ekle">${ic('clip')}</button>${S.page==='chat'&&S.snap?.development?.enabled&&S.snap?.development?.unlocked?'':`<button class="hb2 mic ${S.orb==='listening'?'live':''}" data-act="mic" title="Konuş" aria-label="Konuş">${ic('mic')}</button>`}<details class="composer-options"><summary aria-label="Ses, kamera ve ekran seçenekleri">•••</summary><div>${micToggleBtn('hb2')}${muteBtn('hb2')}${pcMuteBtn('hb2')}${shareBtns()}</div></details><span class="attc"></span><input placeholder="${S.page==='chat'&&S.snap?.development?.enabled&&S.snap?.development?.unlocked?'Geliştirme ekranı: yaz veya görsel ekle':ph}" autocomplete="off"><span class="dst"></span><button class="dstop" data-act="dstop" title="Konuşmayı durdur (Esc)">${ic('volx')}<span>Durdur</span></button><button class="hsend" data-act="send" title="Gönder" aria-label="Gönder"><span>Gönder</span>${ic('send')}</button></div>`;
// Jarvis'in "gözü": ekran ve kamera paylaşımı sohbet çubuğundan açılır/kapanır (görsel eklemek için + yeterli).
const shareBtns=()=>{const mode=(S.snap||{}).mode;return [['screen','monitor','Ekranı paylaş','Ekran paylaşımını kapat'],['camera','camera','Kamerayı aç','Kamerayı kapat']].map(([m,i,on,off])=>`<button class="hb2 ${mode===m?'live':''}" data-act="vis" data-a="act:share:${m}" title="${mode===m?off:on}">${ic(i)}</button>`).join('')};
// ======================================================================= ANA SAYFA
const PAGES={};

function updateHomeStatus(){window.JarvisHome?.updateStatus()}
function updateHome(){window.JarvisHome?.refresh()}
PAGES.home=pg=>{window.JarvisHome.mount(pg);drawHomeMessages()};
ACT.goset=el=>{S.sset=el.dataset.k;S.tool='';go('settings')};
ACT.research=()=>{go('chat');const input=$('.ask input');if(input){input.value='İnternette araştır: ';input.focus()}};

// ======================================================================= ÇALIŞMA MODU
PAGES.study=pg=>{
  const st=((S.snap||{}).study)||{mode:'teacher',modes:{},docs:[],progress:[],books:[],exams:[],recent_exam_years:[],exam_priority:70};
  if(st.mode==='math'){S.mathAttachment=st.math_attachment||S.mathAttachment||'';if(!S.sans&&!S.studyBusy&&(st.math_turns||[]).length)S.sans=mathAnswer(st.math_turns)}
  const ov=S.sov||{};S.stab=S.stab||'learn';
  const docs=st.docs||[];if(!docs.some(d=>+d.id===+S.sdoc))S.sdoc=docs.length?docs[docs.length-1].id:0;
  const selected=docs.find(d=>+d.id===+S.sdoc);
  const sourcePicker=docs.length?`<label class="mut">Çalışılacak kaynak<select id="study-source" style="width:100%;margin:8px 0">${docs.map(d=>`<option value="${d.id}" ${+d.id===+S.sdoc?'selected':''}>${esc(d.title)}</option>`).join('')}</select></label><details class="study-source-suggestions"><summary>Çalışma Önerileri</summary><div id="source-questions" class="qrow" style="flex-wrap:wrap"></div></details>`:'<p class="mut">Bir konu yazabilir veya kaynak yükleyebilirsin.</p>';

  const modes=st.modes||{},books=st.books||[],exams=st.exams||[],yrs=st.recent_exam_years||[],an=st.exam_analysis||{},astale=!!st.exam_analysis_stale;
  const srcrow=(x,exam=false)=>{const xl=[x.year,x.period,x.session].filter(Boolean).join(' · ');return `<div class="srow"><span class="i">${ic(exam?'check':'book')}</span><div style="flex:1"><b>${esc(x.title)}</b>${exam?`<small>${esc(xl||'')} çıkmış soru</small>`:''}</div><span class="mut">${(x.chars||0).toLocaleString('tr')} karakter</span><button class="ab" data-act="studydel" data-id="${x.id}">${ic('trash')}</button></div>`};
  const abar=(x,val,tag='',col='')=>`<div style="margin:7px 0"><div style="display:flex;justify-content:space-between;gap:8px;font-size:12px"><b>${esc(x)}</b><span class="mut">${esc(tag)}</span></div><div style="height:5px;border-radius:5px;background:rgba(255,255,255,.08);margin-top:4px;overflow:hidden"><i style="display:block;height:100%;width:${Math.max(4,Math.min(100,+val||0))}%;background:${col||'linear-gradient(90deg,#f2ad32,#55c8ff)'};border-radius:5px"></i></div></div>`;
  const per=an.per_course||[];
  const analysisHtml=yrs.length?`<div class="exam-analysis" style="margin-top:12px;padding:12px;border:1px solid rgba(255,190,70,.24);border-radius:13px;background:rgba(7,25,45,.46)"><div class="ch" style="margin-bottom:8px"><span class="ct">Son 3 Yıl Sınav Analizi</span><button class="btn sm" data-act="studyanalyze">${ic('spark')} ${an.status==='ready'&&!astale?'Güncelle':'Analiz Et'}</button></div>${an.status==='ready'&&!astale?`<div class="mut" style="font-size:11px;margin-bottom:8px">${(an.years||yrs).join(' · ')} · ${an.question_count||0} soru${an.coverage?' · anahtarlı '+an.coverage.with_key+'/'+an.coverage.questions+' · etiketli '+an.coverage.tagged+'/'+an.coverage.questions:an.source==='kitapçık'?' · kitapçık':''} · güven: ${esc(an.confidence||'orta')}</div>${(per.length?per:[{label:'',top_topics:an.top_topics||[],rising_topics:an.rising_topics||[]}]).map(c=>`${c.label?`<b style="font-size:12.5px;color:var(--gold)">${esc(c.label)}</b>`:''}${(c.top_topics||[]).slice(0,6).map(x=>abar(x.name,x.pct,`${x.count} soru · %${x.pct}`)).join('')||'<div class="mut">Konu bulunamadı.</div>'}${(c.rising_topics||[]).length?`<div class="qrow" style="margin:4px 0 8px;flex-wrap:wrap">${c.rising_topics.map(x=>`<span class="pill warn">↑ ${esc(x.name)} +${x.delta_pct}</span>`).join('')}</div>`:''}`).join('')}`:`<div class="mut">${astale?'Ders seçimi ya da çıkmış sorular değişti. Analizi başlat; ilk seferde biraz sürer.':'Derslerini seçip analizi başlat: hangi konudan kaç soru çıktığı burada görünür.'}</div>`}</div>`:'';
  const courses=ov.courses||[],sel=courses.filter(c=>c.selected);
  const coursesHtml=yrs.length?`<div class="ch" style="margin-top:4px"><span class="ct">Derslerim</span><span class="mut" style="font-size:11.5px">Kitapçıkta ${courses.length} ders var; yalnız seçtiklerin analiz edilir</span></div>
    <div class="qrow" style="flex-wrap:wrap;margin:6px 0">${sel.map(c=>`<span class="qchip on">${ic('book')} ${esc(c.label)} <button class="ab" style="padding:0 0 0 4px" data-act="scdel" data-k="${esc(c.key)}">×</button></span>`).join('')||'<span class="mut">Henüz ders seçilmedi.</span>'}</div>
    <div style="display:flex;gap:8px"><select id="scadd" class="inp" style="flex:1">${courses.filter(c=>!c.selected).map(c=>`<option value="${esc(c.key)}">${esc(c.label)} · ${c.count} soru</option>`).join('')}</select><button class="btn sm" data-act="scadd">${ic('plus')} Ekle</button></div>`:'';
  const fall=(ov.focus_all||ov.focus||[]);
  const focusHtml=fall.length?`<div class="sfocus"><b>${ic('target')} Bugün öncelik · ${fall.length} konu <small class="mut" style="font-weight:400">sınavda sık çıkan ve zayıf olduğun önce · tıkla, önce anlatsın</small></b><div class="sflist">${fall.map((f,i)=>`<button class="qchip ${i<3?'top':''}" data-act="slearn" data-t="${esc(f.topic)}" data-k="${esc(f.mk)}" data-c="${esc(f.course)}"><span class="no">${i+1}</span> ${esc(f.topic)} <small class="mut">%${f.weight} sınavda · ${esc(f.why)}</small></button>`).join('')}</div></div>`:'';
  const tabs=[['learn','Çalış','spark'],['quiz','Soru Çöz','check'],['wrong','Yanlışlarım','refresh'],['mock','Deneme','target'],['plan','Programım','calendar'],['resources','Kaynaklar','folder'],['progress','İlerleme','target'],['hoca','Hoca','spark']];
  const td=ov.today||{},tg=td.target||null,cov=ov.coverage||{},prep=td.readiness||0;
  const summary=`<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:12px"><div class="card"><small class="mut">Sınava kalan</small><b style="display:block;font-size:20px;margin-top:4px">${td.days_left==null?'—':td.days_left+' gün'}</b></div><div class="card"><small class="mut">Hazırlık seviyesi</small><b style="display:block;font-size:20px;margin-top:4px">%${prep}</b></div><div class="card"><small class="mut">Bugünkü hedef</small><b style="display:block;margin-top:4px">${tg?esc(tg.topic):'Henüz belirlenmedi'}</b><small class="mut">${tg?esc(tg.course.split(' (')[0]):esc(td.note||'')}</small></div><div class="card"><small class="mut">Son 3 yıl kapsaması</small><b style="display:block;font-size:20px;margin-top:4px">${cov.year_count||0}/3 yıl</b><small class="mut">${(cov.years||[]).join(' · ')||'Soru eklenmedi'}</small></div></div>${tg?`<button class="btn pri" style="width:100%;margin-bottom:12px" data-act="stoday" data-t="${esc(tg.topic)}" data-k="${esc(tg.mk)}" data-c="${esc(tg.course)}">${ic('spark')} Bugünkü Çalışmayı Başlat · ${esc(td.note||'')}</button>`:''}`;
  const libraryHtml=`${coursesHtml}${analysisHtml}
    <div class="ch" style="margin-top:16px"><span class="ct">Çalışma Kaynakları</span><span style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn sm pri" data-act="studyadd">${ic('plus')} Kitap / Kaynak</button><button class="btn sm" data-act="studyexamadd">${ic('plus')} Çıkmış Soru</button>${(st.docs||[]).length?`<button class="btn sm" data-act="studyclear">Hepsini sil</button>`:''}</span></div>
    ${(st.pending||[]).map(x=>`<div class="srow"><span class="i">${ic(x.state==='error'?'x':'clock')}</span><div style="flex:1"><b>${esc(x.title)}</b><small style="${x.state==='error'?'color:#ff8a8a':''}">${x.state==='error'?'Eklenemedi: '+esc(x.error||''):'Okunuyor… büyük kitaplarda 1-2 dakika sürebilir'}</small></div></div>`).join('')}
    <div class="ch" style="margin-top:10px"><span class="ct">Kitaplar / Kaynaklar</span></div>
    ${books.map(x=>srcrow(x,false)).join('')||'<div class="empty">Henüz kitap/kaynak yok.</div>'}
    <div class="ch" style="margin-top:18px"><span class="ct">Çıkmış Sorular · Son 3 Yıl</span><span class="mut">Yıl · dönem · oturum etiketiyle eklenir</span></div>
    ${exams.slice().sort((a,b)=>(b.year||0)-(a.year||0)).map(x=>srcrow(x,true)).join('')||'<div class="empty">Son 3 yılın çıkmış soru PDF’lerini buraya ekle.</div>'}
    <div class="ch" style="margin-top:18px"><span class="ct">Son çalışmalar</span></div>
    ${(st.progress||[]).slice().reverse().slice(0,6).map(x=>`<div class="srow"><span class="i">${ic('check')}</span><div style="flex:1"><b>${esc((modes[x.mode]||x.mode||'Çalışma'))}</b><small>${esc(x.q||'')}</small></div><span class="mut">${esc(x.ts||'')}</span></div>`).join('')||'<div class="empty">Henüz çalışma kaydı yok.</div>'}`;
  let body='';
  if(S.stab==='learn')body=`
    ${['source','math'].includes(st.mode)?'':focusHtml}
    <div class="study-question-row"><textarea class="big" id="studyq" rows="2" placeholder="${st.mode==='math'?'Matematik sorunu yaz (örn. 2x + 4 = 10) veya çözüm adımı hakkında soru sor…':st.mode==='source'?'Seçili bölümle ilgili sorunu veya alıştırma cevabını yaz…':'Konuyu, soruyu veya ne çalışmak istediğini yaz… (örn. Hücre zarını anlat)'}">${st.mode==='math'?esc(S.mathDraft||''):''}</textarea>
    <button class="btn pri" data-act="studystart">${ic('spark')} ${st.mode==='math'?'Anlat':'Çalışmaya Başla'}</button>${st.mode==='math'?'<button class="btn" data-act="mathsolve">Çöz</button>':''}</div>
    ${st.mode==='source'?`<div class="qrow" style="margin-top:10px"><button class="btn sm" data-act="sourcesend" data-q="devam et">Sonraki bölüm</button><button class="btn sm" data-act="sourcesend" data-q="Bu bölümden bir alıştırma sorusu sor; cevabımı bekle.">Bu bölümden soru sor</button></div>`:''}<div id="slessonact" class="slactwrap">${['source','math'].includes(st.mode)?'':lessonActs()}</div>
    ${st.mode==='math'?'<div class="qrow study-answer-actions"><button class="btn sm" data-act="studyplain">Daha basit anlat</button><button class="btn sm" data-act="slspeak">Sesli anlat</button><button class="btn sm" data-act="slstop">Okumayı durdur</button></div>':''}<div id="studya" class="studyanswer" style="margin-top:12px">${S.sans?(st.mode==='math'?mathHtml(S.sans):mdMath(S.sans)):''}</div>`;
  else if(S.stab==='quiz')body=quizHtml(ov,abar);
  else if(S.stab==='wrong')body=wrongHtml(ov);
  else if(S.stab==='hoca')body=hocaHtml(ov);
  else if(S.stab==='mock')body=mockHtml(ov);
  else if(S.stab==='resources')body=libraryHtml;
  else if(S.stab==='progress')body=summary;
  else body=planHtml(ov);
  pg.innerHTML=`<div class="pagehead study-heading"><div><h1>Kaynak ve anlatım</h1><p>Soruyu solda gör, takıldığın kısmı sağda öğren.</p></div></div>
   <div class="study-tabs stabs">${tabs.map(([k,t,i])=>`<button class="${S.stab===k?'on':''}" data-act="stab" data-k="${k}">${ic(i)} ${t}</button>`).join('')}</div>
   <div class="study-toolbar"><span class="study-mode-label" id="study-mode-label">Çalışma Türü</span><div class="study-mode-buttons" role="group" aria-labelledby="study-mode-label">${Object.entries(modes).map(([k,v])=>`<button class="btn sm ${st.mode===k?'on':''}" data-act="studymode" data-k="${esc(k)}" aria-pressed="${st.mode===k}">${esc(v)}</button>`).join('')}</div></div>
   <div class="grid2 sgrid ${S.stab==='learn'?'study-split':''}">${S.stab==='learn'?`<section class="card study-source"><div class="ch study-source-head"><span class="ct">Soru / Kaynak</span><div class="study-selection-actions"><button class="btn sm" data-act="studyselection" id="study-selection-button" disabled>Seçili alanı anlat</button><button class="btn sm" data-act="studyselectionclear">Seçimi kaldır</button></div><small class="mut" id="study-selection-note">Görselde sürükleyerek alan seç; metinde açıklanacak kısmı işaretle.</small></div>${st.mode==='math'?'':sourcePicker}<div id="study-preview" class="study-preview"><p class="mut">${st.mode==='math'?'Dosya veya görsel yükleyebilirsin.':'Seçili kaynağın metni burada görünür.'}</p></div>${st.mode==='math'?mathUploadHtml():''}</section>`:''}<section class="card glow study-lesson"><div class="ch"><span class="ct">${S.stab==='learn'?'Anlatım':esc(tabs.find(t=>t[0]===S.stab)?.[1]||'Çalışma')}</span></div>${body}</section>
   ${S.swin&&S.stab==='learn'?`<section class="card swin" id="swin">${winHtml()}</section>`:''}</div>`;
  const picker=$('#study-source');if(picker){picker.onchange=()=>{S.sdoc=+picker.value;S.sans='';S.slesson=null;render()};loadSourceQuestions(S.sdoc)}
  const drop=$('#math-drop');if(drop){drop.ondragover=e=>{e.preventDefault();drop.style.borderColor='var(--gold)'};drop.ondragleave=()=>{drop.style.borderColor=''};drop.ondrop=e=>{e.preventDefault();drop.style.borderColor='';const files=[...e.dataTransfer.files];if(files.length>1)return toast('Soruları sırayla ele almak için tek dosya bırak.');if(files[0])uploadMathFile(files[0])}};
  const q=$('#studyq');if(q&&st.mode==='math')q.oninput=()=>{S.mathDraft=q.value};if(q)q.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ACT.studystart()}};
  if(typeof initStudyWorkspace==='function')initStudyWorkspace(pg);
  if(!S.sov&&!S._sovLoading){S._sovLoading=1;loadStudy().then(()=>{S._sovLoading=0;if(S.page==='study')render()})}
};
async function loadStudy(){const owner=((S.snap||{}).user||{}).name,ticket=Symbol();S.studyOverviewRequest=ticket;const result=await tryApi('study_overview');if(owner!==((S.snap||{}).user||{}).name||S.studyOverviewRequest!==ticket)return;S.sov=result||{}}
function lessonActs(){const L=S.slesson;if(!L||!S.sans)return '';return `<div class="slact"><button class="btn pri" data-act="slquiz">${ic('check')} Anladım, “${esc(L.topic)}” sorularını çöz</button>${S.sspeaking?`<button class="btn" data-act="slstop">${ic('volx')} Okumayı durdur</button>`:`<button class="btn" data-act="slspeak">${ic('vol')} Sesli anlat</button>`}<button class="btn" data-act="slmore">${ic('spark')} Daha basit anlat</button>${S.swin?'':`<button class="btn" data-act="swinopen">${ic('image')} Görsel ve videolar</button>`}</div>`}
function winHtml(){const m=S.smedia;const tab=S.swtab||'wiki';
  const head=`<div class="ch"><span class="ct">${ic('image')} ${esc((m&&m.topic)||'Kaynak penceresi')}</span><button class="ab" data-act="swinclose" title="Kapat">×</button></div>
   <div class="stabs" style="margin-bottom:10px"><button class="${tab==='wiki'?'on':''}" data-act="swtab" data-k="wiki">${ic('book')} Vikipedi</button><button class="${tab==='yt'?'on':''}" data-act="swtab" data-k="yt">${ic('play')} YouTube</button></div>`;
  if(!m||m.loading)return head+`<div class="mut">${m?`“${esc(m.topic)}” aranıyor…`:'Bir konu anlatıldığında burada açılır.'}</div>`;
  if(m.blocked)return head+`<div class="mut">${esc(m.blocked)}</div>`;
  if(tab==='wiki'){const w=m.wiki||{};
    return head+(w.title?`<div class="swwiki">${w.thumb?`<img src="${esc(w.thumb)}" alt="">`:''}<b>${esc(w.title)}</b><p>${esc(w.extract||'')}</p><button class="btn sm" data-act="slink" data-u="${esc(w.url)}">${ic('link')} Vikipedi’de aç</button></div>`:'<div class="mut">Vikipedi’de uygun makale bulunamadı.</div>')
      +((m.images||[]).length?`<div class="ct" style="font-size:13px;margin:12px 0 6px">Görseller</div><div class="swimgs">${m.images.map(x=>`<a class="smimg" data-act="swimg" data-src="${esc(x.src)}" data-u="${esc(x.url)}" title="${esc(x.title)}"><img src="${esc(x.src)}" alt="" loading="lazy"><span>${esc(x.title)}</span></a>`).join('')}</div>`:'')
      +(S.swbig?`<div class="swbig" data-act="swbigclose"><img src="${esc(S.swbig)}" alt=""></div>`:'');}
  const vids=m.videos||[];
  return head+(S.swvid?`<div class="swplayer"><iframe src="https://www.youtube-nocookie.com/embed/${esc(S.swvid)}?autoplay=1&rel=0" allow="autoplay; encrypted-media; picture-in-picture" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe></div>`:'')
    +(vids.length?vids.map(v=>`<a class="smvid ${S.swvid===v.id?'on':''}" data-act="swplay" data-id="${esc(v.id)}"><img src="${esc(v.thumb)}" alt="" loading="lazy"><span><b>${esc(v.title)}</b><small>${esc(v.channel)}</small></span></a>`).join(''):`<div class="mut" style="margin-bottom:8px">${m.youtube_key?'Bu konu için video bulunamadı.':'Videoların burada listelenip oynatılması için YouTube anahtarı gerekiyor.'}</div>${m.youtube_key?'':`<button class="btn sm" data-act="sytkey">YouTube anahtarı ekle</button>`}`)
    +`<button class="btn sm" style="width:100%;margin-top:8px" data-act="slink" data-u="${esc(m.search)}">${ic('play')} YouTube’da ara</button>`}
function redrawWin(){const w=$('#swin');if(w)w.innerHTML=winHtml();else if(S.page==='study')render()}
ACT.slearn=async el=>{const t=el.dataset.t,k=el.dataset.k,c=el.dataset.c||'';S.stab='learn';S.slesson={topic:t,mk:k,course:c};S.sans='';render();
  const q=$('#studyq');if(q)q.value=`${t} konusunu anlat`;
  const a=$('#studya');if(a)a.innerHTML=`<div class="slwait">${ic('book')} “${esc(t)}” dersi hazırlanıyor… <small>(ayrıntılı anlatım 15-30 sn sürebilir)</small></div>`;
  S.swin=1;showMedia(t,c);
  const lesson=S.slesson,owner=((S.snap||{}).user||{}).name,ticket=Symbol();S.studyLessonRequest=ticket;
  const r=await tryApi('study_lesson',t,c,k,false);if(!r||owner!==((S.snap||{}).user||{}).name||S.slesson!==lesson||S.studyLessonRequest!==ticket)return;
  S.sans=r.text||'';S.slesson.no_book=r.no_book;const a2=$('#studya');if(a2)a2.innerHTML=(r.no_book?`<div class="pill warn" style="margin-bottom:8px;display:inline-block">Kitap eklenmediği için genel bilgiyle anlatıldı</div>`:'')+mdMath(S.sans);
  const la=$('#slessonact');if(la)la.innerHTML=lessonActs();if(a2)a2.scrollIntoView({behavior:'smooth',block:'start'});
  if(((S.ui||{}).study_voice)!==false)ACT.slspeak();await refresh()};
ACT.slquiz=()=>{const L=S.slesson;if(!L)return;tryApi('stop_speaking');S.sspeaking=0;S.stab='quiz';S.sqf=L.mk?L.mk+'§'+L.topic:'';S.squiz=null;S.sres=null;render();ACT.sqnext()};
ACT.slmore=async()=>{const L=S.slesson;if(!L)return;const owner=((S.snap||{}).user||{}).name,ticket=Symbol();S.studyLessonRequest=ticket;tryApi('stop_speaking');const a=$('#studya');if(a)a.innerHTML='<div class="slwait">Daha basit anlatılıyor…</div>';const r=await tryApi('study_lesson',L.topic,L.course||'',L.mk||'',true);if(owner!==((S.snap||{}).user||{}).name||S.slesson!==L||S.studyLessonRequest!==ticket)return;S.sans=(r&&r.text)||S.sans;const a2=$('#studya');if(a2)a2.innerHTML=mdMath(S.sans);if(((S.ui||{}).study_voice)!==false)ACT.slspeak()};
ACT.slspeak=async()=>{if(!S.sans)return;S.sspeaking=1;const la=$('#slessonact');if(la)la.innerHTML=lessonActs();await tryApi('study_speak',S.sans)};
ACT.dstop=async()=>{S.sspeaking=0;S._spk2=0;await tryApi('stop_speaking');const la=$('#slessonact');if(la)la.innerHTML=lessonActs()};
ACT.slstop=async()=>{S.sspeaking=0;await tryApi('stop_speaking');const la=$('#slessonact');if(la)la.innerHTML=lessonActs()};
ACT.swinopen=()=>{S.swin=1;render();if(!S.smedia&&S.slesson)showMedia(S.slesson.topic,S.slesson.course||'')};
ACT.swinclose=()=>{S.swin=0;S.swvid='';render()};
ACT.swtab=el=>{S.swtab=el.dataset.k;redrawWin()};
ACT.swplay=el=>{S.swvid=el.dataset.id;redrawWin()};
ACT.swimg=el=>{S.swbig=el.dataset.src;redrawWin()};
ACT.swbigclose=()=>{S.swbig='';redrawWin()};
function mediaHtml(m){
  if(!m)return `<div class="mut" style="font-size:12px">Bir konu çalıştığında ilgili görseller ve videolar burada çıkar.</div>${(S.snap||{}).youtube_key?'':`<button class="link" style="font-size:11.5px;margin-top:8px" data-act="sytkey">YouTube anahtarı ekle</button>`}`;
  if(m.loading)return `<div class="mut">“${esc(m.topic)}” için görseller aranıyor…</div>`;
  if(m.blocked)return `<div class="mut">${esc(m.blocked)}</div>`;
  const imgs=(m.images||[]).map(x=>`<a class="smimg" data-act="slink" data-u="${esc(x.url)}" title="${esc(x.title)} · ${esc(x.from)}"><img src="${esc(x.src)}" alt="" loading="lazy"><span>${esc(x.title)}</span></a>`).join('');
  const vids=(m.videos||[]).map(v=>`<a class="smvid" data-act="slink" data-u="${esc(v.url)}"><img src="${esc(v.thumb)}" alt="" loading="lazy"><span><b>${esc(v.title)}</b><small>${esc(v.channel)}</small></span></a>`).join('');
  return `<div class="ct" style="font-size:13px;margin-bottom:6px">${ic('image')} ${esc(m.topic)}</div>${imgs||'<div class="mut" style="font-size:12px">Uygun görsel bulunamadı.</div>'}
   <div class="ct" style="font-size:13px;margin:12px 0 6px">${ic('play')} Videolar</div>${vids}
   <button class="btn sm" style="width:100%;margin-top:6px" data-act="slink" data-u="${esc(m.search)}">${ic('play')} YouTube’da “${esc(m.topic)}” ara</button>
   ${m.youtube_key?'':`<button class="link" style="font-size:11.5px;margin-top:6px" data-act="sytkey">Videoların burada listelenmesi için YouTube anahtarı ekle</button>`}`;
}
function quizHtml(ov,abar){
  const q=S.squiz,r=S.sres;const stats=ov.stats||{};const keys=Object.keys(stats);
  if(!keys.length)return `<div class="empty" style="margin-top:12px">Soru çözmek için sağdaki <b>Derslerim</b>’den dersini seç ve çıkmış soru PDF’lerini ekle.</div>`;
  const filt=`<div style="display:flex;gap:8px;margin-bottom:12px"><select id="sqtopic" class="inp" style="flex:1"><option value="">Karışık · öncelikli konulardan</option>${keys.map(k=>stats[k].topics.filter(t=>t.name!=='Diğer').map(t=>`<option value="${esc(k)}§${esc(t.name)}" ${S.sqf===k+'§'+t.name?'selected':''}>${esc(t.name)} · ${esc(stats[k].label.split(' (')[0])}</option>`).join('')).join('')}</select><button class="btn sm pri" data-act="sqnext">${ic('spark')} ${q?'Yeni Soru':'Başla'}</button></div>`;
  const card=q?`<div class="sqcard"><div class="mut" style="font-size:11.5px;margin-bottom:6px">${esc(q.course)} · ${[q.year,q.period,q.session].filter(Boolean).join(' · ')} · ${q.n}. soru · ${esc(q.topic)}</div><div class="sqtext">${esc(q.text)}</div>
    <div class="sqopts">${Object.entries(q.options).map(([k,v])=>{const cls=r?(k===r.answer?'ok':(k===r.choice?'bad':'')):'';return `<button class="sqopt ${cls}" data-act="sqans" data-c="${k}" ${r?'disabled':''}><b>${k}</b><span>${esc(v)}</span></button>`}).join('')}</div>
    ${r?`<div class="sqres ${r.ok?'ok':'bad'}">${r.ok?'Doğru! 🎉':`Yanlış. Doğru cevap: <b>${r.answer}</b>`}</div><div style="display:flex;gap:8px;margin-top:8px"><button class="btn sm" data-act="sqwhy">${ic('spark')} Neden?</button><button class="btn sm pri" data-act="sqnext">Sonraki Soru ${ic('chev')}</button></div><div id="sqexp" class="studyanswer" style="margin-top:10px">${S.sexp?mdMath(S.sexp):''}</div>`:''}</div>`:'<div class="mut">Soru, sınavda sık çıkan ve senin zayıf olduğun konulardan seçilir. Her cevabın kaydedilir.</div>';
  const table=keys.map(k=>{const c=stats[k];return `<div class="ch" style="margin-top:16px"><span class="ct">${esc(c.label)}</span><span class="mut">${c.asked} soru çözüldü · ${c.asked?Math.round(c.correct*100/c.asked):0}% doğru</span></div>${c.topics.filter(t=>t.name!=='Diğer').map(t=>abar(t.name,t.pct==null?0:t.pct,t.asked?`${t.correct}/${t.asked} doğru · sınavda %${t.weight}`:`henüz çözülmedi · sınavda %${t.weight}`,t.pct==null?'rgba(255,255,255,.15)':t.pct<50?'linear-gradient(90deg,#ff6b6b,#ff9f43)':t.pct<75?'linear-gradient(90deg,#f2ad32,#ffd36b)':'linear-gradient(90deg,#28d38c,#55c8ff)')).join('')}`}).join('');
  return filt+card+table;
}
function hocaHtml(ov){
  const h=(ov&&ov.hoca)||{enabled:true,lesson:null,weak:[]},L=h.lesson,weak=h.weak||[];
  const on=h.enabled!==false;
  const head=`<div class="ch" style="margin-top:10px"><span class="ct">Hoca</span><span class="pill ${on?'good':'warn'}">${on?'Sohbet komutları açık':'Sohbet komutları kapalı'}</span><button class="btn sm" data-act="hocatoggle">${on?'Kapat':'Aç'}</button></div>`;
  const start=`<div class="study-question-row" style="margin-top:8px"><input class="inp" id="hocatopic" placeholder="Hangi konuyu çalışalım? (örn. hücre)" style="flex:1"><button class="btn pri" data-act="hocastart">${ic('spark')} Başla</button></div><p class="mut" style="font-size:12px;margin-top:6px">Ders sohbet ekranında ilerler. Sohbette de “hoca modu: konu” veya “konu konusunu öğret” diyebilirsin.</p>`;
  let lesson='';
  if(L){
    const steps=(L.steps||[]).map((t,i)=>`<div class="srow"><span class="i">${ic(i+1<L.step?'check':(i+1===L.step?'spark':'clock'))}</span><div style="flex:1"><b>${esc(t)}</b></div></div>`).join('');
    lesson=`<div class="card" style="margin-top:12px"><div class="ch"><span class="ct">${esc(L.topic)}</span><span class="mut">Adım ${L.step}/${L.total}</span></div>${steps}
      ${L.text?`<div style="white-space:pre-wrap;margin-top:10px">${esc(L.text)}</div>`:''}
      ${L.question?`<div style="margin-top:10px"><b>Kontrol sorusu:</b> ${esc(L.question)}</div><div class="study-question-row" style="margin-top:8px"><input class="inp" id="hocaans" placeholder="Cevabın" style="flex:1"><button class="btn pri" data-act="hocaans">Cevapla</button></div>`:''}
      <div class="qrow" style="margin-top:10px"><button class="btn sm" data-act="hocasay" data-q="sonraki adım">Sonraki adım</button><button class="btn sm" data-act="hocasay" data-q="bilmiyorum">Bilmiyorum</button><button class="btn sm" data-act="hocasay" data-q="konuyu değiştir">Dersi bırak</button></div></div>`;
  }
  const weakHtml=weak.length?weak.map(w=>`<div class="srow"><span class="i">${ic(w.due_now?'refresh':'clock')}</span><div style="flex:1"><b>${esc(w.title)}</b><small>${esc(w.topic||'')}</small></div><span class="pill ${w.due_now?'warn':'good'}">${w.due_now?'tekrar zamanı':'bekliyor'}</span></div>`).join(''):'<div class="empty">Zayıf konu yok. Kontrol sorusunu yanlış yaptığın adımlar burada aralıklı tekrara (1, 3, 7 gün arayla) girer; iki doğru tekrardan sonra öğrenildi sayılır.</div>';
  return `${head}${L?'':start}${lesson}<div class="ch" style="margin-top:16px"><span class="ct">Zayıf konularım</span></div>${weakHtml}`;
}
function wrongHtml(ov){
  const w=ov.wrong||{},rows=w.active||[],due=w.due||[];
  if(!rows.length)return `<div class="empty" style="margin-top:12px">Yanlış defterin temiz. Yanlış yaptığın çıkmış sorular burada 1 ve 3 günlük tekrar döngüsüne girer; iki doğru tekrardan sonra öğrenildi sayılır.</div>`;
  return `<div class="ch" style="margin-top:10px"><span class="ct">Yanlış Defteri</span><span class="pill ${due.length?'warn':'good'}">${due.length} tekrar zamanı geldi · ${w.learned||0} öğrenildi</span></div>
   <div class="mut" style="font-size:12px;margin:8px 0">Yanlış soru ertesi gün tekrar gelir. Doğru yaparsan 3 gün sonra yeniden sorulur; iki doğru tekrardan sonra öğrenildi kabul edilir.</div>
   ${rows.slice(0,30).map(x=>`<div class="srow"><span class="i">${ic(x.due_now?'bell':'clock')}</span><div style="flex:1"><b>${esc(x.topic)}</b><small>${esc(x.course.split(' (')[0])} · ${[x.year,x.period,x.session].filter(Boolean).join(' · ')} · ${x.n}. soru · tekrar ${esc(x.due)}</small></div><span class="pill ${x.due_now?'warn':''}">${x.correct_after?x.correct_after+' doğru':'bekliyor'}</span></div>`).join('')}
   <button class="btn pri" style="margin-top:10px" data-act="swrongnext">${ic('refresh')} ${due.length?'Şimdi Tekrar Et':'Sıradaki Yanlışı Tekrar Et'}</button>`;
}
function mockHtml(ov){
  const m=ov.mock||{};
  if(!m.active)return `<div class="ch" style="margin-top:10px"><span class="ct">Gerçek Deneme Modu</span></div><div class="mut" style="margin:8px 0 12px">Sorular son 3 yılın gerçek soru havuzundan seçilir; konu dağılımı geçmiş sınav ağırlığını doğal olarak korur.</div><div class="qrow"><button class="btn pri" data-act="smockstart" data-n="10">10 Soru</button><button class="btn" data-act="smockstart" data-n="20">20 Soru</button><button class="btn" data-act="smockstart" data-n="0">Tam Deneme</button></div>`;
  if(m.finished)return `<div class="sqres ok" style="margin-top:12px">Deneme tamamlandı · <b>${m.correct}/${m.total}</b> · %${m.total?Math.round(m.correct*100/m.total):0}</div><div class="ch" style="margin-top:14px"><span class="ct">Konu Sonuçları</span></div>${(m.breakdown||[]).map(x=>`<div class="srow"><div style="flex:1"><b>${esc(x.topic)}</b><small>${x.correct}/${x.asked} doğru</small></div><span class="pill ${x.pct<50?'warn':'good'}">%${x.pct}</span></div>`).join('')}<button class="btn pri" style="margin-top:12px" data-act="smockstart" data-n="10">Yeni Deneme</button>`;
  const q=m.current;if(!q)return '<div class="empty">Deneme sorusu hazırlanıyor…</div>';
  return `<div class="mut" style="margin:10px 0">${m.answered+1}/${m.total} · ${esc(q.course)} · ${[q.year,q.period,q.session].filter(Boolean).join(' · ')}</div><div class="sqcard"><div class="sqtext">${esc(q.text)}</div><div class="sqopts">${Object.entries(q.options).map(([k,v])=>`<button class="sqopt" data-act="smockans" data-q="${esc(q.id)}" data-c="${k}"><b>${k}</b><span>${esc(v)}</span></button>`).join('')}</div></div>`;
}
function planHtml(ov){
  const p=ov.plan||{},c=p.cfg||{minutes:60,days:[0,1,2,3,4,5],time:'20:00',exam_date:''};const D=['Pzt','Sal','Çar','Per','Cum','Cmt','Paz'];
  const form=`<div class="spform"><label>Sınav tarihi<input type="date" id="spdate" class="inp" value="${esc(c.exam_date||'')}"></label><label>Günde kaç dakika<input type="number" id="spmin" class="inp" min="15" max="480" step="15" value="${c.minutes}"></label><label>Saat<input type="time" id="sptime" class="inp" value="${esc(c.time)}"></label></div>
   <div class="qrow" style="margin:8px 0;flex-wrap:wrap">${D.map((d,i)=>`<button class="qchip ${(c.days||[]).includes(i)?'on':''}" data-act="spday" data-i="${i}">${d}</button>`).join('')}</div>
   <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn pri sm" data-act="spsave">${ic('calendar')} Programı Oluştur</button><button class="btn sm" data-act="sprem">${ic('bell')} Hatırlatıcıları Kur</button></div>`;
  const left=p.days_left!=null?`<div class="pill ${p.days_left<14?'warn':'good'}" style="margin:10px 0;display:inline-block">Sınava ${p.days_left} gün kaldı</div>`:'';
  const days=(p.days||[]).map(d=>`<div class="spday"><div class="spd"><b>${esc(d.day)}</b><small>${d.date.split('-').reverse().slice(0,2).join('.')} · ${esc(d.time)}</small></div><div style="flex:1">${d.blocks.map(b=>`<div class="spb ${b.kind}"><span>${b.kind==='konu'?ic('book'):b.kind==='soru'?ic('check'):ic('target')}</span><div><b>${esc(b.topic||b.text)}</b><small>${b.kind==='konu'?'Konu çalış':b.kind==='soru'?`${b.questions} çıkmış soru çöz`:'Deneme'} · ${b.minutes} dk${b.course?' · '+esc(b.course.split(' (')[0]):''}</small></div></div>`).join('')}</div></div>`).join('');
  return form+left+(days?`<div class="mut" style="font-size:12px;margin:8px 0">Sınavda sık çıkan ve senin zayıf olduğun konulara daha çok zaman ayrıldı. Soru çözdükçe program kendini günceller.</div>${days}`:`<div class="empty" style="margin-top:12px">${esc(p.note||'Programı oluşturmak için tarihi ve süreyi seçip “Programı Oluştur”a bas.')}</div>`);
}
ACT.stoday=el=>(((S.snap||{}).study||{}).mode==='teacher'?ACT.slearn(el):ACT.studystart());
ACT.swrongnext=async()=>{const q=await tryApi('study_wrong_next');if(!q)return toast('Tekrar edilecek yanlış soru yok.');S.stab='quiz';S.squiz=q;S.sres=null;S.sexp='';S.sqf=q.mk+'§'+q.topic;render()};
ACT.smockstart=async el=>{const r=await tryApi('study_mock_start',+el.dataset.n);if(!r)return;await loadStudy();render()};
ACT.smockans=async el=>{if(S.mockBusy)return;const owner=((S.snap||{}).user||{}).name,session=((S.sov||{}).mock||{}).id,ticket=Symbol();S.mockBusy=ticket;try{const r=await tryApi('study_mock_answer',el.dataset.q,el.dataset.c,session||'');if(!r||owner!==((S.snap||{}).user||{}).name)return;await loadStudy();if(owner===((S.snap||{}).user||{}).name)render()}finally{if(S.mockBusy===ticket)S.mockBusy=false}};
ACT.scadd=async()=>{const v=$('#scadd')&&$('#scadd').value;if(!v)return;const cur=((S.sov||{}).courses||[]).filter(c=>c.selected).map(c=>c.key);await tryApi('study_set_courses',[...cur,v]);await loadStudy();await refresh();render();toast('Ders eklendi. Sınav analizini başlatabilirsin.')};
ACT.scdel=async el=>{const cur=((S.sov||{}).courses||[]).filter(c=>c.selected).map(c=>c.key).filter(k=>k!==el.dataset.k);await tryApi('study_set_courses',cur);await loadStudy();await refresh();render()};
ACT.sfocus=el=>ACT.slearn(el);
ACT.hocasay=el=>say(el.dataset.q);
ACT.hocastart=()=>{const t=(($('#hocatopic')||{}).value||'').trim();if(!t)return toast('Konuyu yaz.');say('hoca modu: '+t)};
ACT.hocaans=()=>{const t=(($('#hocaans')||{}).value||'').trim();if(!t)return toast('Cevabını yaz.');say('cevap: '+t)};
ACT.hocatoggle=async()=>{const on=((S.sov||{}).hoca||{}).enabled!==false;const r=await tryApi('settings_save',{hoca_enabled:!on});if(r===undefined||r===null)return;await loadStudy();if(S.page==='study')render()};
ACT.sqnext=async()=>{const f=($('#sqtopic')&&$('#sqtopic').value)||S.sqf||'';S.sqf=f;const [k,t]=f?f.split('§'):['',''];const owner=((S.snap||{}).user||{}).name,ticket=Symbol();S.studyQuizRequest=ticket;S.sres=null;S.sexp='';const q=await tryApi('study_quiz_next',k||'',t||'');if(owner!==((S.snap||{}).user||{}).name||S.studyQuizRequest!==ticket)return;if(!q){S.squiz=null;render();toast('Bu seçimde cevap anahtarı olan soru bulunamadı.','bad');return}S.squiz=q;render()};
ACT.sqans=async el=>{if(!S.squiz||S.sres||S.quizBusy)return;const question=S.squiz,c=el.dataset.c,owner=((S.snap||{}).user||{}).name,ticket=Symbol();S.quizBusy=ticket;try{const r=await tryApi('study_quiz_answer',question.id,c,question.attempt_id||'');if(!r||owner!==((S.snap||{}).user||{}).name||S.squiz!==question)return;S.sres={...r,choice:c};await loadStudy();if(owner===((S.snap||{}).user||{}).name)render()}finally{if(S.quizBusy===ticket)S.quizBusy=false}};
ACT.sqwhy=async()=>{const e=$('#sqexp');if(e)e.innerHTML='<span class="mut">Açıklanıyor…</span>';const t=await tryApi('study_explain',S.squiz.id,(S.sres||{}).choice||'');S.sexp=t||'';if(e)e.innerHTML=mdMath(S.sexp)};
ACT.spday=el=>{el.classList.toggle('on')};
ACT.spsave=async()=>{const days=$$('[data-act="spday"]').map((b,i)=>b.classList.contains('on')?+b.dataset.i:-1).filter(i=>i>=0);const p=await tryApi('study_plan_set',{exam_date:$('#spdate').value,minutes:+$('#spmin').value,time:$('#sptime').value,days});if(p){S.sov=S.sov||{};S.sov.plan=p;render();toast('Program hazır.')}};
ACT.sprem=async()=>{const n=await tryApi('study_plan_reminders');if(n!=null)toast(`${n} günlük çalışma hatırlatması kuruldu. Saati gelince Jarvis haber verir.`)};
ACT.slink=el=>{if(el.dataset.u)tryApi('open_link',el.dataset.u)};
ACT.ytsave=async()=>{const k=($('#ytk')||{}).value||'';if(!k.trim())return toast('Anahtarı yapıştır.','bad');toast('Anahtar deneniyor…');const r=await tryApi('study_set_youtube_key',k.trim());if(r){toast(r.test&&r.test.ok?'YouTube anahtarı çalışıyor ve kaydedildi.':'Anahtar kaydedildi; '+((r.test||{}).msg||'deneme sonucu bekleniyor')+'.');await refresh();render()}};
ACT.ytdel=async()=>{if(!await ask('YouTube anahtarı silinsin mi?'))return;await tryApi('study_set_youtube_key','');await refresh();render()};
ACT.sytkey=async()=>{const k=await askText('YouTube Data API anahtarını yapıştır (Google Cloud Console › YouTube Data API v3 › Kimlik bilgileri). Ücretsizdir.','');if(k==null)return;const r=await tryApi('study_set_youtube_key',k);if(r){toast(r.set?(r.test&&r.test.ok?'YouTube anahtarı çalışıyor ve kaydedildi.':'YouTube anahtarı kaydedildi.'):'YouTube anahtarı silindi.');await refresh();if(S.smedia&&S.smedia.topic)showMedia(S.smedia.topic)}};
async function showMedia(topic,course=''){if(!topic)return;const owner=((S.snap||{}).user||{}).name,ticket=Symbol();S.studyMediaRequest=ticket;S.smedia={topic,loading:1};S.swvid='';S.swbig='';S.swin=1;redrawWin();const m=await tryApi('study_media',topic,course);if(owner!==((S.snap||{}).user||{}).name||S.studyMediaRequest!==ticket)return;S.smedia=m||{topic,images:[],videos:[]};redrawWin()}
ACT.studymode=async el=>{if(S.studyBusy)return toast('Yanıt tamamlandıktan sonra modu değiştirebilirsin.');const r=await tryApi('study_mode',el.dataset.k);if(!r)return;S.sans='';await refresh();if(S.page==='study'){S.stab='learn';render();if(el.dataset.k==='exam')return ACT.studystart()}};
async function loadSourceQuestions(id){const user=((S.snap||{}).user||{}).name;const r=await tryApi('study_source_info',+id,(S.slesson||{}).topic||'');if(+id!==+S.sdoc||user!==((S.snap||{}).user||{}).name)return;const box=$('#source-questions');if(box&&r)box.innerHTML='<span class="mut">Kaynakla çalış:</span>'+r.questions.map(q=>`<button class="qchip" data-act="sourcequestion" data-q="${esc(q)}">${esc(q)}</button>`).join('')}
ACT.sourcequestion=el=>{const q=$('#studyq');if(q){q.value=el.dataset.q;q.focus();toast('İsteği düzenleyebilir, ardından Çalışmaya Başla’ya basabilirsin.')}};
ACT.sourcesend=el=>{if(S.studyBusy)return;const q=$('#studyq');if(q){q.value=el.dataset.q;return ACT.studyask()}};
ACT.studystart=async()=>{
  if(S.studyBusy)return;
  const q=(($('#studyq')||{}).value||'').trim(),st=(S.snap||{}).study||{};
  const ov=S.sov||{},target=S.slesson||(ov.today||{}).target||(ov.focus||[])[0];
  if(st.mode==='math'){
    if(!q&&!st.math_attachment&&!S.mathAttachment)return toast('Bir soru yaz veya dosya/görsel ekle.','bad');
    return ACT.studyask();
  }
  if(st.mode==='exam'){
    S.stab='quiz';S.squiz=null;S.sres=null;S.sexp='';
    S.sqf=target&&target.mk?target.mk+'§'+target.topic:'';
    render();return ACT.sqnext();
  }
  const selectedPrompt=target&&q===`${target.topic} konusunu anlat`;
  if(q&&!selectedPrompt&&!/^(?:ders )?çalışmaya başla[.! ]*$/i.test(q))return ACT.studyask();
  if(st.mode!=='source'){
    if(target&&target.topic)return ACT.slearn({dataset:{t:target.topic,k:target.mk||'',c:target.course||''}});
  }
  const input=$('#studyq');if(input)input.value='';
  return ACT.studyask();
};
ACT.studyask=async()=>{if(S.studyBusy||S.mathUploadBusy)return;if(S.snap?.study?.mode==='math')return runMath((($('#studyq')||{}).value||'').trim());let q=(($('#studyq')||{}).value||'').trim();if(/^(?:ders )?çalışmaya başla[.! ]*$/i.test(q))q='';if(!q&&!S.sdoc)return toast('Önce bir kaynak yükle veya çalışmak istediğin konuyu yaz.','bad');const ticket=Symbol(),doc=+S.sdoc||0;S.studyBusy=ticket;const user=((S.snap||{}).user||{}).name;const a=$('#studya');if(a)a.innerHTML='<span class="mut">Seçili kaynakla çalışılıyor…</span>';S.slesson=null;
try{const st=((S.snap||{}).study)||{};const pdf=S.studyPdfPage,chosen=S.studySelection;const selection=chosen?.owner===user&&chosen.data?.page?chosen.data:pdf?.owner===user&&pdf.mode===st.mode&&pdf.doc===doc?{image_id:pdf.image_id,page:pdf.page,full_page:true}:null;const r=selection?await api('study_answer_with_context',q.trim(),st.mode||'teacher',doc,selection):await api('study_answer_with_context',q.trim(),st.mode||'teacher',doc);if(user!==((S.snap||{}).user||{}).name||doc!==( +S.sdoc||0)||S.studyBusy!==ticket)return;S.sans=r&&Array.isArray(r.turns)?r.turns.map(t=>`**${t.role}**\n\n${t.text}`).join('\n\n---\n\n'):(r&&r.text)||'';const box=$('#studya');if(box)box.innerHTML=mdMath(S.sans);await refresh()}catch(e){if(user!==((S.snap||{}).user||{}).name||S.studyBusy!==ticket)return;const box=$('#studya');if(box)box.textContent='Çalışma başlatılamadı: '+e.message;toast(e.message,'bad')}finally{if(S.studyBusy===ticket)S.studyBusy=false}};

function mathAnswer(turns){return [...(turns||[])].reverse().find(t=>t.role==='Jarvis')?.text||''}
function mathUploadHtml(){return `<div id="math-drop" class="study-upload"><span>${ic('clip')} Dosya veya görsel sürükleyip bırak<br><small>PDF’nin Sayfa Düzeni Korunur · En Fazla 20 MB</small></span><button class="btn sm" data-act="mathpick">Dosya seç</button><button class="btn sm" data-act="mathclear">Yeni soru</button></div>`}
async function runMath(question,path='',expectedOwner=S.snap?.user?.name,wholeQuestion=false){
 if(S.studyBusy||expectedOwner!==S.snap?.user?.name||S.snap?.study?.mode!=='math')return;
 const ticket=Symbol();S.studyBusy=ticket;const owner=expectedOwner;
 const current=()=>owner===S.snap?.user?.name&&S.snap?.study?.mode==='math'&&S.studyBusy===ticket;
 const box=$('#studya');if(box)box.textContent='Soru okunuyor, açıklama hazırlanıyor…';
 try{
  const pdf=S.studyPdfPage;
  const selection=!wholeQuestion&&!path&&S.studySelection?.owner===owner?S.studySelection.data:!path&&pdf?.owner===owner&&pdf.mode==='math'?{image_id:pdf.image_id,page:pdf.page,full_page:true}:null;
  const result=selection?await api('study_math',question,path,selection):await api('study_math',question,path);if(!current())return;
  S.sans=mathAnswer(result.turns)||result.text||'';S.mathResponse={...result,owner,text:S.sans};S.mathAttachment=result.attachment||'';if(path||wholeQuestion)S.studySelection=null;if(path)S.studyPdfPage=null;
  const output=$('#studya');if(output){output.innerHTML=mathHtml(S.sans);output.scrollTop=0;}
  await refresh();if(S.page==='study'&&typeof initStudyWorkspace==='function')initStudyWorkspace($('#page'));
 }catch(error){if(current()){const output=$('#studya');if(output)output.textContent='Çözüm tamamlanamadı: '+error.message;toast(error.message,'bad')}}
 finally{if(S.studyBusy===ticket)S.studyBusy=false}
}
async function uploadMathFile(file){
 if(S.studyBusy||S.mathUploadBusy)return toast('Devam eden çözümün bitmesini bekle.');
 if(!/\.(pdf|docx|txt|md|png|jpe?g|webp|gif|bmp)$/i.test(file.name))return toast('PDF, Word, metin veya görsel yükleyebilirsin.','bad');
 if(file.size>20000000)return toast('Dosya 20 MB sınırını aşıyor.','bad');
 const owner=S.snap?.user?.name,question=(($('#studyq')||{}).value||'').trim(),ticket=Symbol();S.mathUploadBusy=ticket;
 toast(`${file.name} yükleniyor…`);
 try{const result=await upload(file,true);if(!result||owner!==S.snap?.user?.name||S.snap?.study?.mode!=='math'||S.mathUploadBusy!==ticket)return;await runMath(question,result.path,owner)}
 finally{if(S.mathUploadBusy===ticket)S.mathUploadBusy=false}
}
ACT.mathsolve=()=>{if(S.mathUploadBusy)return;const question=(($('#studyq')||{}).value||'').trim();return runMath(question?question+'\nBu sorunun tamamını adım adım çöz.':'Ekteki veya konuşmadaki güncel sorunun tamamını adım adım çöz; önceki alan seçimi yalnız bir ara işlemdi.','',S.snap?.user?.name,true)};
ACT.mathpick=()=>{const input=$('#upl');input.accept='.pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp,.gif,.bmp';input.onchange=()=>{const file=input.files[0];input.value='';if(file)return uploadMathFile(file)};input.click()};
ACT.mathclear=async()=>{const owner=S.snap?.user?.name;await api('study_math_clear');if(owner!==S.snap?.user?.name)return;S.studyBusy=false;S.mathUploadBusy=false;S.mathDraft='';S.mathAttachment='';S.mathResponse=null;S.studyPdfPage=null;S.studySelection=null;S.sans='';await refresh();if(owner===S.snap?.user?.name)render()};

ACT.studyanalyze=async()=>{toast('Seçili derslerin çıkmış soruları konulara ayrılıyor… (ilk seferde 20-40 sn)');const r=await tryApi('study_exam_analysis',true);if(r&&r.status==='ready')toast('Sınav analizi hazır.');await loadStudy();await refresh();if(S.page==='study')render()};
const studyUpload=async(kind,meta={})=>{const inp=$('#upl');inp.accept='.pdf,.docx,.xlsx,.txt,.md';inp.onchange=async()=>{const f=inp.files[0];inp.value='';if(!f)return;toast((kind==='exam'?'Çıkmış soru':'Kaynak')+' ekleniyor: '+f.name);try{const r=await fetch('/upload?to=files&name='+encodeURIComponent(f.name),{method:'POST',headers:{'X-Jarvis-Token':TOKEN},body:f});const j=await r.json();if(!j.ok)throw new Error(j.error);const a=kind==='exam'?await api('study_add_exam_path',j.data.path,+meta.year,meta.period||'',meta.session||''):await api('study_add_path',j.data.path);const lab=[meta.year,meta.period,meta.session].filter(Boolean).join(' · ');toast(a&&a.exists?'Bu kaynak zaten ekli.':a&&a.already?'Bu kaynak zaten ekleniyor, bekle.':(kind==='exam'?lab+' çıkmış soruları':'Kaynak')+' okunuyor; bitince listede görünecek (büyük kitaplarda 1-2 dakika).');after(0)}catch(e){toast(e.message,'bad')}};inp.click()};
ACT.studyadd=()=>studyUpload('book');
ACT.studyexamadd=async()=>{const y=await askText('Çıkmış sorular hangi sınav yılına ait?',String(new Date().getFullYear()-1));if(y==null)return;const n=Number(String(y).trim());if(!Number.isInteger(n)||n<2000||n>new Date().getFullYear()+1){toast('Geçerli bir sınav yılı gir.','bad');return}const p=await askText('Dönem bilgisi (isteğe bağlı, örn. 1. Dönem):','');if(p==null)return;const o=await askText('Oturum bilgisi (isteğe bağlı, örn. 2. Oturum):','');if(o==null)return;studyUpload('exam',{year:n,period:p.trim(),session:o.trim()})};
ACT.studydel=el=>{S.sov=null;after(api('study_remove_document',+el.dataset.id)).then(()=>{if(S.page==='study')render()})};
ACT.studyclear=async ()=>{if(await ask('Bu kullanıcıya ait tüm kitaplar ve çıkmış sorular silinsin mi?')){S.sov=null;after(api('study_clear_documents')).then(()=>{if(S.page==='study')render()})}};

// ======================================================================= SOHBET
function convIcon(t){t=(t||'').toLowerCase();return /pdf|dosya|belge|özet/.test(t)?['file','blue']:/excel|tablo/.test(t)?['grid','green']:/görsel|resim|ekran|fotoğraf/.test(t)?['image','purple']:/kod|python|javascript/.test(t)?['term','orange']:/web|araştır|haber/.test(t)?['globe','blue']:/plan|proje|görev/.test(t)?['list','navy']:/seyahat|rota|gezi/.test(t)?['target','red']:['msg','navy']}
function convTitle(t){t=(t||'').replace(/^(?:"[^"]+"\s*)+/,'').trim();return t.length>34?t.slice(0,32)+'…':t||'Sohbet'}
async function loadHist(){S.hist=await tryApi('history','',1500)||[]}
function days(){const by={};(S.hist||[]).forEach(r=>{const d=(r.ts||'').slice(0,10);if(d)(by[d]=by[d]||[]).push(r)});return Object.entries(by).sort((a,b)=>a[0]<b[0]?1:-1)}
function dayLabel(d,lastTs){const t=ymd(new Date()),y=ymd(new Date(Date.now()-864e5));return d===t?(lastTs||'').slice(11,16):d===y?'Dün':d.slice(8,10)+'.'+d.slice(5,7)}
PAGES.chat=pg=>{
  if(!S.day)S.day=ymd(new Date());
  const Q=chatShortcuts();
  pg.innerHTML=`<div class="chatp"><section class="card convs"><div class="convh"><span class="ct">Sohbetler</span><button class="newc" data-act="newchat">${ic('plus')} Yeni</button></div>
    <div class="search csr">${ic('search')}<input id="cq" placeholder="Sohbetlerde ara..." value="${esc(S.cq||'')}"></div>
    <div class="clist" id="clist"><div class="empty" style="padding:10px">Yükleniyor…</div></div>
    <button class="frow" style="padding:10px 8px;border-top:1px solid var(--line)" data-act="allconv">${ic('list')}<span>${S.allConv?'Son Sohbetler':'Tüm Sohbetleri Gör'}</span>${ic('chev')}</button></section>
   <section class="card chatc"><div class="chead" id="chead"></div><div class="msgs" id="msgs"></div>
    <div class="chatask"><div id="dev-status" class="devstatus"></div><div class="qrow" id="qrow">${qrowHtml(Q)}</div><div id="dockhost"></div></div></section></div>`;
  $('#cq').oninput=e=>{S.cq=e.target.value;drawConvs()};
  (S.hist?Promise.resolve():loadHist()).then(()=>{drawConvs();drawMsgs();drawSide();drawDevelopment()});
};
// Sohbet altındaki kısayollar: günlük 4 iş. Geliştirme düğmeleri yalnız geliştirme modu açıkken görünür; kalanlar "•••" menüsündedir.
function chatShortcuts(){const dev=((S.snap||{}).development)||{};
  const base=[['folder','Dosyalarım','dosyalarımı göster'],['eye','Özetle','bu konuşmayı kısaca özetle'],['grid','Tabloya Dönüştür','son cevabını tablo olarak ver'],['file','Dosya Olarak Al','çıktı al'],['lang','Türkçeye Çevir','önceki metni Türkçeye çevir']];
  return dev.enabled?base.concat([['eye','Taslak','taslağı göster'],['check','Uygula','değişiklikleri uygula'],['refresh','Geri Al','son geliştirmeyi geri al'],['msg','Normal Sohbet','normal sohbete dön']]):base}
function chatRun(c){return c==='geliştirme modunu aç'?ACT.devopen():c==='normal sohbete dön'?ACT.devclose():say(c)}
function qrowHtml(Q){return Q.map(([i,t,s])=>`<button class="qchip" ${s==='normal sohbete dön'?'data-act="devclose"':`data-say="${esc(s)}"`}>${ic(i)}${t}</button>`).join('')}
function drawQrow(){const el=$('#qrow');if(!el)return;const h=qrowHtml(chatShortcuts());if(el._h!==h){el._h=h;el.innerHTML=h}}
function drawDevelopment(){drawQrow();const el=$('#dev-status');if(!el)return;const st=(S.snap||{}).development||{};el.innerHTML=st.enabled?`<b>Şifre Korumalı Geliştirme Modu · ${st.unlocked?'Açık':'Kilitli'}</b><span>${(st.draft_files||[]).length} dosya taslağı · ${st.visual_count||0} görsel · ${st.reference_count||0} referans</span><button class="btn sm" data-act="attach">${ic('clip')} Görsel / Dosya</button><button class="btn sm" data-say="son görseli göster">Son Görsel</button><span>Her değişiklik için son onayın gerekir.</span><button class="btn sm" data-act="devexport">Dosyaları Al</button><button class="btn sm" data-act="devpassword">Şifre</button>`:'';}
function drawConvs(){const el=$('#clist');if(!el)return;const ds=days(),q=(S.cq||'').toLowerCase();
  const items=ds.filter(([d,rs])=>!q||rs.some(r=>(r.text||'').toLowerCase().includes(q))).slice(0,S.allConv?400:40);
  if(!items.some(([d])=>d===ymd(new Date())))items.unshift([ymd(new Date()),[]]);
  el.innerHTML=items.map(([d,rs])=>{const first=rs.find(r=>r.role==='user'),last=rs.slice().reverse().find(r=>r.role==='assistant');const t=d===ymd(new Date())&&!rs.length?'Bugün':convTitle(first&&first.text);const [i,c]=convIcon(first&&first.text);
    return `<div class="convwrap"><button class="conv ${S.day===d?'on':''}" data-act="day" data-d="${d}"><span class="ib sm ${c}" style="width:40px;height:40px;font-size:19px">${ic(i)}</span><span style="min-width:0"><b>${esc(t)}</b><small>${esc(last?last.text.replace(/[*#`|_>]+/g,'').replace(/^\s*[-•]\s*/gm,'').replace(/\s+/g,' ').trim().slice(0,60):rs.length?rs.length+' mesaj':'Yeni konuşma')}</small></span><time>${dayLabel(d,(rs[rs.length-1]||{}).ts)}</time></button>${rs.length?`<button class="convdelete" data-act="convdelete" data-d="${d}" title="Bu sohbeti sil" aria-label="${esc(t)} sohbetini sil">${ic('trash')}</button>`:''}</div>`}).join('')||'<div class="empty">Konuşma yok.</div>'}
ACT.convdelete=async el=>{
  const day=el.dataset.d,user=((S.snap||{}).user||{}).name;
  if(!await ask(`${day.split('-').reverse().join('.')} tarihindeki sohbet silinsin mi? Bu güne ait tüm mesajlar kaldırılacak.`))return;
  if(user!==((S.snap||{}).user||{}).name)return;
  try{await api('history_delete_conversation',day);if(user!==((S.snap||{}).user||{}).name)return;
    if(day===ymd(new Date())){S.live=[];S.chat=[];S.waiting=false;S.since=0}
    await loadHist();if(S.day===day){S.day=ymd(new Date());S.since=0}
    drawConvs();drawMsgs();drawSide();toast('Seçilen sohbet silindi.');
  }catch(e){toast('Sohbet silinemedi: '+e.message,'bad')}
};
ACT.day=el=>{S.day=el.dataset.d;S.since=0;drawConvs();drawMsgs();drawSide()};
ACT.newchat=async()=>{await tryApi('chat_reset');S.day=ymd(new Date());S.since=Date.now()/1000;S.live=[];drawConvs();drawMsgs();drawSide();toast('Yeni sohbet başladı.')};
ACT.csearch=async ()=>{const q=await askText('Sohbetlerde ara:',S.cq||'');if(q!==null){S.cq=q;drawConvs()}};
ACT.allconv=()=>{S.allConv=!S.allConv;render()};
function curMsgs(day=S.day,since=S.since){
  const today=ymd(new Date());let rows=(S.hist||[]).filter(r=>(r.ts||'').slice(0,10)===day).map(r=>({role:r.role,text:r.text,ts:Date.parse(r.ts.replace(' ','T'))/1000,src:r.source,rid:r.rid}));
  if(day===today){const seen=new Set(rows.map(r=>r.role+'|'+r.text));S.live.forEach(m=>{const k=m.role+'|'+m.text;if(!seen.has(k)){rows.push(m);seen.add(k)}})}
  if(since)rows=rows.filter(r=>r.ts>=since);
  return rows.sort((a,b)=>a.ts-b.ts);
}
function chatImageHtml(label,url){
  if(!/^https:\/\//i.test(url)&&!/^data:image\/(?:png|jpeg|webp|gif|svg\+xml);base64,[A-Za-z0-9+/=]+$/.test(url))return esc(label);
  return `<figure class="chatimage"><img src="${esc(url)}" alt="${esc(label)}" loading="lazy"><figcaption>${esc(label)}</figcaption></figure>`;
}
function md(t){
  let s=esc(t||'');const blocks=[];s=s.replace(/```(\w*)\n?([\s\S]*?)```/g,(m,l,c)=>{blocks.push(`<pre><code>${c}</code></pre>`);return `\u0000${blocks.length-1}\u0000`});
  s=s.replace(/!\[([^\]\n]*)\]\(([^\s)]+)\)/g,(m,label,url)=>{blocks.push(chatImageHtml(label.replace(/&amp;/g,'&'),url.replace(/&amp;/g,'&')));return `\u0000${blocks.length-1}\u0000`});
  const lines=s.split('\n'),out=[];let list=null;
  const flush=()=>{if(list){out.push(`<${list.t}>${list.i.map(x=>`<li>${x}</li>`).join('')}</${list.t}>`);list=null}};
  for(let index=0;index<lines.length;index++){let ln=lines[index];const ul=ln.match(/^\s*[-•*]\s+(.*)/),ol=ln.match(/^\s*\d+[.)]\s+(.*)/);
    if(ul||ol){const t=ul?'ul':'ol';if(!list||list.t!==t){flush();list={t,i:[]}}list.i.push(inl(ul?ul[1]:ol[1]));continue}
    flush();if(/^\s*\|.*\|\s*$/.test(ln)){if(/^\s*\|[\s:|-]+\|\s*$/.test(ln))continue;const tag=/^\s*\|[\s:|-]+\|\s*$/.test(lines[index+1]||'')?'th':'td';out.push('<tr>'+ln.trim().slice(1,-1).split('|').map(c=>`<${tag}${tag==='th'?' scope="col"':''}>${inl(c.trim())}</${tag}>`).join('')+'</tr>');continue}
    const h=ln.match(/^#{1,4}\s+(.*)/);out.push(h?`<p><b>${inl(h[1])}</b></p>`:ln.trim()?`<p>${inl(ln)}</p>`:'')}
  flush();let html=out.join('').replace(/(<tr>.*?<\/tr>)+/g,m=>{const header=m.startsWith('<tr><th')?m.slice(0,m.indexOf('</tr>')+5):'';return `<div class="chat-table" tabindex="0" role="region" aria-label="Tablo; yatay kaydırılabilir"><table>${header?'<thead>'+header+'</thead>':''}<tbody>${m.slice(header.length)}</tbody></table></div>`});
  return html.replace(/\u0000(\d+)\u0000/g,(m,i)=>blocks[+i]);
}
function inl(s){
  // Bağlantılar tıklanabilir olsun (kullanıcı: "kaynaklar tıklanacak şekilde olursa tamamdır").
  // Metin zaten esc() ile kaçırıldı; adres yalnız http(s) kabul eder, sondaki noktalama ayrılır.
  s=s.replace(/(https?:\/\/[^\s<"'`]+)/g,(m,url)=>{const t=url.replace(/[.,;:!?]+$/,'');const tail=url.slice(t.length);
    return `<a href="${t}" target="_blank" rel="noopener noreferrer">${t}</a>${tail}`});
  return s.replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/`([^`]+)`/g,'<code>$1</code>')}
function mathGroup(s,start){if(s[start]!=='{')return null;let depth=0;for(let i=start;i<s.length;i++){if(s[i]==='{')depth++;if(s[i]==='}'&&--depth===0)return {text:s.slice(start+1,i),end:i+1};if(depth>20)return null}return null}
function mathBasic(x,depth=0){
 let s=String(x);if(depth>12)return s;
 s=s.replace(/\\(?:left|right)\b/g,'').replace(/\\(?:,|;|!|quad\b|qquad\b)/g,' ');
 const command=/\\(d?frac|tfrac|sqrt)\s*/g;let out='',last=0,match;
 while((match=command.exec(s))){const first=mathGroup(s,command.lastIndex),second=first&&match[1]!=='sqrt'?mathGroup(s,first.end):null;if(!first||(match[1]!=='sqrt'&&!second))continue;
  out+=s.slice(last,match.index)+(match[1]==='sqrt'?`√<span class="root">${mathBasic(first.text,depth+1)}</span>`:`<span class="frac"><span>${mathBasic(first.text,depth+1)}</span><span>${mathBasic(second.text,depth+1)}</span></span>`);last=second?second.end:first.end;command.lastIndex=last;
 }
 s=out+s.slice(last);
 s=s.replace(/\\(?:text|mathrm)\{([^{}]+)\}/g,'$1').replace(/\^\{([^{}]+)\}/g,'<sup>$1</sup>').replace(/_\{([^{}]+)\}/g,'<sub>$1</sub>').replace(/\^([0-9A-Za-z]+)/g,'<sup>$1</sup>').replace(/_([0-9A-Za-z]+)/g,'<sub>$1</sub>');
 return s.replace(/\\times\b/g,'×').replace(/\\div\b/g,'÷').replace(/\\neq\b/g,'≠').replace(/\\leq?\b/g,'≤').replace(/\\geq?\b/g,'≥').replace(/\\pi\b/g,'π').replace(/\\sum\b/g,'∑').replace(/\\int\b/g,'∫').replace(/\\cdot\b/g,'·').replace(/\\pm\b/g,'±');
}
function mdMath(t){let h=md(t||'');return h.replace(/\\\((.*?)\\\)/g,(m,x)=>`<span class="math">${mathBasic(x)}</span>`).replace(/\$\$([^$]+)\$\$/g,(m,x)=>`<div class="math block">${mathBasic(x)}</div>`).replace(/\$([^$\n]+)\$/g,(m,x)=>`<span class="math">${mathBasic(x)}</span>`)}
// SPEECH HIGHLIGHT START
// §8: Görünür "şimdi sesli anlatılan sonuç" izi. Vurguyu yalnız üreticinin gerçek
// oynatma olayı (playback_started) koyar; kuyruk, sentez veya WAV hazırlığı konuşma
// değildir. Geç kalan bir stage daha yeni konuşmayı söndüremez, çünkü konuşma durumu
// olayın akış sırasından değil oynatmanın kendisinden gelir. Pencere öne alınmaz.
function speechEvent(m){
  let id=null;try{id=JSON.parse(m.x||'{}')}catch(e){}
  if(!id||typeof id!=='object'||String(m.t||'')!=='playback_started')return;
  S.speech=id;applySpeechHighlight();
}
function speechStateEvent(state){if(state==='speaking'||!S.speech)return;S.speech=null;applySpeechHighlight()}
function speechClassFor(m){return S.speech&&m&&m.rid&&S.speech.turn_id===m.rid?' saying':''}
function taskGoalId(item){const area=String((item||{}).area||'');const match=/^Görev (\S+)/.exec(area);return match?match[1]:''}
function speechTaskClass(goal){const id=S.speech||{};return goal&&(id.goal_id===goal||id.event_id===goal)?' saying':''}
function applySpeechHighlight(){
  const id=S.speech||{};
  [...$$('.m.a'),...$$('.jarvis-console .turn[data-speaker="jarvis"]')].forEach(el=>el.classList.toggle('saying',!!id.turn_id&&el.dataset.rid===id.turn_id));
  // Görev kartı yalnız kendi işi seslendirildiğinde işaretlenir: kartın kimliği
  // çizimdeki aktivite kaydından gelir, seslendirmenin sonuç kimliğiyle (iş/hedef)
  // karşılaştırılır. Kimliksiz seslendirme hiçbir kartı boyamaz.
  const task=$('#cside .task');if(task)task.classList.toggle('saying',!!task.dataset.goal&&(task.dataset.goal===id.goal_id||task.dataset.goal===id.event_id));
}
// SPEECH HIGHLIGHT END
function msgHtml(m){
  if(m.role==='files')return filesHtml();
  if(m.role==='agenda')return agendaHtml();
  if(m.role==='user'){const fm=msgFiles(m.text);
    const body=fm.paths.length?`${esc(fm.rest.replace(/^dosyalarını |^dosyasını |^görselini |^görselindeki /,'').replace(/^./,c=>c.toUpperCase()))}${fm.paths.map(f=>`<div class="fchip"><span class="fi ${catOf(f)}">${extOf(f).toUpperCase().slice(0,4)}</span><span><b>${esc(f.split(/[\\/]/).pop())}</b><small>${esc(extOf(f).toUpperCase())}</small></span></div>`).join('')}`:md(m.text);
    const heard=m.src==='ses'?`<div class="heard">${ic('mic')}Anladığım</div>`:'';
    if(m.home)return `<article class="turn" data-speaker="you"><div class="turn-role">Sen •</div><div class="message-body">${heard}${body}</div></article>`;
    return `<div class="m u"><div class="bb">${heard}${body}<time class="t">${hm(m.ts)}</time></div><span class="av">${esc(((S.snap||{}).user||{}).name?.[0]||'S')}</span></div>`}
  if(m.role==='system')return `<div class="m s">${esc(m.text)}</div>`;
  if(m.role==='step')return stepsHtml(S.steps[m.rid]);
  if(m.home)return `<article class="turn${speechClassFor(m)}" data-speaker="jarvis" data-rid="${esc(m.rid||'')}"><div class="turn-role">• ${esc(S.snap?.aname||'Jarvis')}</div><div class="message-body">${md(m.text)}</div></article>`;
  return `<div class="m a${speechClassFor(m)}" data-rid="${esc(m.rid||'')}"><span class="orb">${ic('mic')}</span><div><div class="nm">${esc(((S.snap||{}).aname||'JARVIS').toUpperCase())}<time>${hm(m.ts)}</time></div><div class="bb">${md(m.text)}</div></div></div>`;
}
function stepsHtml(card){
  const items=card?[...card.items.values()]:[];if(!items.length)return '';
  const mark={working:'…',done:'✓',error:'✗'};
  return `<div class="m stepcard"><div class="steps">${items.map(i=>`<div class="step ${esc(i.s)}"><span class="sm">${mark[i.s]||'•'}</span><span>${esc(i.t)}${i.s==='error'&&i.d?`<small>${esc(i.d)}</small>`:''}</span></div>`).join('')}</div></div>`+taskSummaryCardHtml(card);
}
// TASK SUMMARY START
function taskSummaryText(text){
  if(typeof text!=='string')return '';
  text=text.replace(/\b(Bearer|Basic)\s+\S+/gi,'$1 [gizlendi]')
    .replace(/(^|[^\p{L}\p{N}_])([\p{L}\p{N}_-]*(?:token|secret|password|passwd|parola|belirte[çc]|[şŞsS][iİıI]fre|api[_ -]?key|anahtar)[\p{L}\p{N}_-]*)\s*[:=]\s*\S+/giu,'$1$2=[gizlendi]')
    .replace(/\b(?:AIza|sk-|gsk_|ghp_|github_pat_|xox[baprs]-|AKIA|ASIA)[\w-]+/g,'[gizlendi]')
    .replace(/[\w.+-]+@[\w.-]+\.[a-z]{2,}/gi,'[e-posta gizlendi]')
    .replace(/\bTR(?:\s*\d){24}\b/gi,'[IBAN gizlendi]')
    .replace(/\+?\d[\d ()-]{8,}\d/g,'[numara gizlendi]');
  return Array.from(text.replace(/\s+/g,' ').trim()).slice(0,200).join('');
}
function taskSummaryData(job){
  const empty=()=>({title:'',done:[],left:[],stopped:false,verified:false});
  if(!job||Array.isArray(job)||typeof job!=='object')return empty();
  const title=job.title===undefined?job.request:job.title,steps=job.steps;
  if(typeof title!=='string'||!title.trim()||typeof job.state!=='string'||!Array.isArray(steps))return empty();
  const done=[],left=[];
  for(const step of steps){
    if(!step||typeof step!=='object')return empty();
    const text=step.text===undefined?step.title:step.text;
    if(typeof text!=='string'||!text.trim()||typeof step.state!=='string')return empty();
    (['done','completed'].includes(step.state)?done:left).push(taskSummaryText(text));
  }
  const stopped=['cancelled','stopped'].includes(job.state)||job.stopped===true;
  const verified=steps.length>0&&!left.length&&!stopped&&['done','completed'].includes(job.state)&&(job.verified===true||steps.every(x=>x.verified===true));
  return {title:taskSummaryText(title),done,left,stopped,verified};
}
function taskSummaryHtml(job){
  const data=taskSummaryData(job);if(!data.title)return '';
  const list=(label,items)=>items.length?'<div><b>'+label+'</b><ul>'+items.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul></div>':'';
  return '<section class="task-summary" aria-label="Görev sonucu"><strong>'+esc(data.title)+'</strong>'+list('Yapılan',data.done)+list('Yarım kalan',data.left)+'<small>'+(data.verified?'Doğrulandı':'Doğrulama bilgisi yok')+'</small></section>';
}
function taskSummaryOwner(){return (((S.snap||{}).user||{}).slug)||''}
function taskSummaryTrack(card,rid){
  if(card._summaryOwner===undefined)card._summaryOwner=taskSummaryOwner();
  card._summaryRid=rid;
  if(card._summaryReady===undefined)card._summaryReady=false;
}
function taskSummaryActiveRid(){
  const owner=taskSummaryOwner();if(!owner)return null;
  const ids=Object.keys(S.steps).filter(rid=>rid!=='serbest'&&S.steps[rid]._summaryOwner===owner&&!S.steps[rid]._summaryReady);
  const last=[...(S.live||[])].reverse().find(x=>x.role==='user'&&x.rid);
  return last?(ids.includes(last.rid)?last.rid:null):(ids.length===1?ids[0]:null);
}
function taskSummaryFinish(rid,stopped){
  const card=rid&&S.steps[rid],owner=taskSummaryOwner();
  if(!card||!owner||card._summaryOwner!==owner||(card._summaryReady&&stopped!==true))return;
  card._summaryReady=true;card._summaryStopped=stopped===true;
  if(S.page==='chat'&&typeof drawMsgs==='function')drawMsgs();
}
function taskSummaryEvent(m){
  const owner=taskSummaryOwner();
  if(!m||!owner||(m.user&&m.user!==owner))return;
  if(m.rid&&((m.k==='state'&&m.t==='idle')||m.k==='assistant'))taskSummaryFinish(m.rid,false);
}
function taskSummaryCardHtml(card){
  if(!card||!card._summaryReady||!taskSummaryOwner()||card._summaryOwner!==taskSummaryOwner()||!(card.items instanceof Map))return '';
  return taskSummaryHtml({title:card._summaryStopped?'Durdurulan görev':'Görev sonucu',state:card._summaryStopped?'stopped':'done',
    steps:[...card.items.values()].map(x=>({text:x.t,state:x.s==='error'?'failed':x.s})),verified:false});
}
// TASK SUMMARY END
function onStep(m){
  const [status,id,detail]=String(m.x||'').split('|');const rid=m.rid||'serbest';const ts=m.ts||Date.now()/1000;
  let card=S.steps[rid];if(!card){card=S.steps[rid]={ts,items:new Map()};S.live.push({role:'step',rid,text:'adım:'+rid,ts});S.live=S.live.slice(-300)}
  card.items.set(id||String(card.items.size),{t:String(m.t||''),s:status||'working',d:detail||''});
  taskSummaryTrack(card,rid);
  const keys=Object.keys(S.steps);if(keys.length>60)keys.slice(0,keys.length-60).forEach(k=>delete S.steps[k]);
  if(/ses(i)? (kapatıl|açıl)/i.test(String(m.t||''))&&status!=='working')loadPcMute();
  if(S.page==='chat'||S.page==='home')drawMsgs();
}
// Mesaj başındaki tırnaklı dosya yolları ('"a.pdf" "b.xlsx" talimat') ve kalan talimat
function msgFiles(t){const paths=[];let rest=t||'',x;while((x=rest.match(/^"([^"]*[\\/][^"]*\.\w{2,5})"\s+/))){paths.push(x[1]);rest=rest.slice(x[0].length)}return {paths,rest}}
const extOf=p=>(p.split('.').pop()||'').toLowerCase();
const catOf=p=>{const e=extOf(p);return e==='pdf'?'pdf':/^docx?|odt|rtf$/.test(e)?'word':/^xlsx?|csv|ods$/.test(e)?'excel':/^(png|jpe?g|webp|bmp|gif|heic)$/.test(e)?'image':'other'};
function stripHtml(){const A=window.JarvisActivityStrip;if(!A)return'';const st=A.stripState(S.snap,S.steps);if(!st.visible)return'';const rid=Object.keys(S.steps).pop();const it=A.activityItems(S.steps,rid).map(x=>`<small class="as-${x.status}">${esc(x.text)}${x.detail?' · '+esc(x.detail):''}</small>`).join('');return `<div class="actstrip"><b>${esc(st.label)}</b>${it}${st.stoppable?'<button data-act="stoptask" title="Durdur">Durdur</button>':''}</div>`}
ACT.stoptask=async()=>{const rid=typeof taskSummaryActiveRid==='function'?taskSummaryActiveRid():null;const r=await tryApi('stop_task');if(!r)return toast('Durdurma bu sürümde yok.','bad');if(r.stopped===true&&typeof taskSummaryFinish==='function')taskSummaryFinish(rid,true);toast(r.msg||'Görev durduruldu.')};
function drawHomeMessages(){
  const host=$('#home-messages');if(!host)return;
  const today=ymd(new Date()),day=window.JarvisHome?.day()||today;
  const messages=curMsgs(day,day===today?S.since:0);
  const markup=messages.length?messages.map(message=>msgHtml({...message,home:true})).join(''):'<p class="mut">Yaz, konuş veya bir dosya ekle.</p>';
  if(host._markup!==markup){
    const atEnd=host.scrollHeight-host.scrollTop-host.clientHeight<48;
    host._markup=markup;host.innerHTML=markup;
    if(atEnd)host.scrollTop=host.scrollHeight;
  }
  updateHomeStatus();
}
function drawMsgs(){
  if(S.page==='home')return drawHomeMessages();
  const el=$('#msgs');if(!el)return;const ms=curMsgs(),first=ms.find(m=>m.role==='user');
  const ch=$('#chead');if(ch){const [i,c]=convIcon(first&&first.text);const files=new Set(ms.flatMap(m=>m.role==='user'?msgFiles(m.text).paths:[]));
    ch.innerHTML=`<span class="ib ${c}" style="width:52px;height:52px;font-size:26px">${ic(i)}</span><div><b>${esc(first?convTitle(first.text):'Yeni Sohbet')}</b><small>${files.size?files.size+' dosya • ':''}${ms.length} mesaj • ${S.day===ymd(new Date())?'Bugün':S.day.split('-').reverse().join('.')}</small></div>
     <div class="acts"><button data-act="ccopy" title="Kopyala">${ic('up')}</button><button data-act="cmore" title="Diğer">•••</button></div>`}
  el.innerHTML=(ms.length?ms.map(msgHtml).join(''):`<div class="m s" style="margin:auto">Konuşmaya başla: yaz ya da mikrofona dokun.</div>`)+(S.waiting&&S.day===ymd(new Date())?`<div class="m a"><span class="orb">${ic('mic')}</span><div class="bb"><span class="typing"><i></i><i></i><i></i></span></div></div>`:'')+stripHtml();
  el.scrollTop=el.scrollHeight;
}
ACT.ccopy=async()=>{const t=curMsgs().filter(m=>m.role!=='step'&&m.role!=='files'&&m.role!=='agenda').map(m=>`${m.role==='user'?'Sen':'Jarvis'}: ${m.text}`).join('\n\n');try{await navigator.clipboard.writeText(t);toast('Konuşma panoya kopyalandı.')}catch(e){toast('Kopyalanamadı.','bad')}};
ACT.cmore=el=>{const r=el.getBoundingClientRect(),x=r.left-150,y=r.bottom+6;
  const sub=(icon,label,list)=>[icon,label+'  ›',()=>menu(x,y,[['arrow','‹  Geri',()=>ACT.cmore(el)],'-',...list])];
  menu(x,y,[['copy','Konuşmayı kopyala',ACT.ccopy],['refresh','Yenile',async()=>{await loadHist();drawConvs();drawMsgs()}],'-',
    sub('monitor','Ekran ve görsel',[['monitor','Ekranı analiz et',()=>say('ekranı analiz et')],['eye','Ekran görüntüsü al',()=>ACT.capture()],['image','Görselden metin çıkar',()=>pickUpload('metin','image/*')],['image','Görsel yükle ve analiz et',()=>pickUpload('gorsel','image/*')]]),
    sub('bolt','Diğer komutlar',[['lang','İngilizceye çevir',()=>say('önceki metni İngilizceye çevir')],['bolt','Model yetenekleri',()=>say('router durumu')],['grid','Görev durumu',()=>say('görev durumu')],['check','PC / Ses kontrolü',()=>say('pc ses kontrolü')],['term','Şifre korumalı geliştirme modu',()=>chatRun('geliştirme modunu aç')]]),
    '-',['trash','Bu sohbeti sil',()=>ACT.convdelete({dataset:{d:S.day}})],['trash','Tüm geçmişi sil',async ()=>{if(await ask('Tüm konuşma geçmişi silinsin mi?')){await api('history_clear');S.hist=[];S.live=[];drawConvs();drawMsgs()}}]])};
function drawSide(){
  const el=$('#cside');if(!el)return;const sn=S.snap||{};
  const run=(sn.activity||[]).slice().reverse().find(a=>a.status==='start'),last=(sn.activity||[]).slice().reverse().find(a=>a.status!=='start'&&!/Aktivite ekranı/.test(a.text));
  const ms=curMsgs();const fl=[...new Set(ms.flatMap(m=>m.role==='user'?msgFiles(m.text).paths:[]))].map(p=>({path:p,name:p.split(/[\\/]/).pop(),cat:catOf(p)}));
  const files=fl.length?fl:(S.files&&S.files.files||[]).slice(0,3);
  const goal=taskGoalId(run||last);   // kartın kendi iş kimliği; aktivite kaydından gelir
  el.innerHTML=`<section class="card"><div class="ch"><span class="ct" style="display:flex;gap:8px;align-items:center"><span class="ib sm purple">${ic('file')}</span>Mevcut Görev</span></div>
     <div class="task${speechTaskClass(goal)}" data-goal="${esc(goal)}"><span class="ib ${run?'orange':'navy'}" style="width:50px;height:50px">${ic(run?'activity':'check')}</span><div style="min-width:0"><b>${esc(run?run.text.replace(/^Komut alındı:\s*/,'').slice(0,40):last?(last.area||'Son işlem'):'Görev yok')}</b><small>${files.length} dosya</small>
      <div class="okk" style="${run?'color:var(--orange)':''}">${ic(run?'clock':'check')} ${run?'Çalışıyor…':last?(last.status==='error'?'Başarısız':'Tamamlandı'):'Hazır'}</div></div></div></section>
   <section class="card"><div class="ch"><span class="ct">Dosyalar</span><button class="link" data-go="files">Tümünü Gör</button></div>
     ${files.length?files.map(f=>`<div class="frow" data-act="fpick" data-p="${esc(f.path)}"><span class="fi ${f.cat}">${(extOf(f.path)||'?').toUpperCase().slice(0,3)}</span><span>${esc(f.name)}</span><small>${f.size?fmtSize(f.size):''}</small></div>`).join(''):'<div class="empty">Dosya yok.</div>'}</section>
   <section class="card"><div class="ch"><span class="ct">Hızlı İşlemler</span></div><div class="qgrid">
     ${[['eye','Özeti Çıkar','bu konuşmayı kısaca özetle'],['file','Rapor Oluştur','çıktı al'],['layers','Karşılaştır','#prefill:Karşılaştır: '],['grid','Tabloya Dönüştür','son cevabını tablo olarak ver']].map(([i,t,c])=>c.startsWith('#prefill:')?`<button class="qbtn" data-act="prefill" data-t="${esc(c.slice(9))}">${ic(i)}${t}</button>`:`<button class="qbtn" data-say="${esc(c)}">${ic(i)}${t}</button>`).join('')}</div></section>`;
}
ACT.prefill=el=>{const i=$('.chatask input')||$('.ask input');if(i){i.value=el.dataset.t+(el.dataset.t.endsWith(' ')?'':' ');i.focus()}};
ACT.fpick=el=>{S.fsel=el.dataset.p;go('files')};

// ======================================================================= DOSYALAR
// "Dosyalarım" isteği tarayıcıda cevaplanır (model/Gemini çağrısı yok): son yüklenen dosyalar kartlarla sohbete düşer.
async function showFileCards(text){
  if(S.page!=='home'&&S.page!=='chat'){S.day=ymd(new Date());go('chat')}
  const now=Date.now()/1000,owner=S.snap?.user?.slug;S.day=ymd(new Date());
  S.live.push({role:'user',text,ts:now,mine:true});drawMsgs();
  await loadFiles(true);
  if(owner!==S.snap?.user?.slug)return;
  S.live.push({role:'files',text:'dosya kartları '+now,ts:now+.001});S.live=S.live.slice(-300);drawMsgs();
}
async function showAgendaCard(text){
  if(S.page!=='home'&&S.page!=='chat'){S.day=ymd(new Date());go('chat')}
  const owner=S.snap?.user?.slug;
  try{await refresh()}catch(e){}
  if(owner!==S.snap?.user?.slug)return;
  const now=Date.now()/1000;S.day=ymd(new Date());
  S.live.push({role:'user',text,ts:now,mine:true});S.live.push({role:'agenda',text:'takvim kartı '+now,ts:now+.001});S.live=S.live.slice(-300);drawMsgs();
}
function agendaHtml(){
  const sn=S.snap||{},t0=ymd(new Date()),ev=(sn.all_events||[]).filter(e=>(e.when||'').slice(0,10)>=t0).sort((a,b)=>a.when.localeCompare(b.when)).slice(0,5),tk=(sn.tasks||[]).filter(t=>!t.done).slice(0,4);
  const row=(b,sm)=>`<div class="fcard"><span class="fcn"><b>${esc(b)}</b>${sm?`<small>${esc(sm)}</small>`:''}</span></div>`;
  const body=ev.length||tk.length?`<p>Yaklaşan işlerin bunlar.</p><div class="fcards">${ev.map(e=>row(e.title,whenTxt(e.when))).join('')}${tk.map(t=>row(t.text,t.when?whenTxt(t.when):'Görev')).join('')}</div>`:'<p>Yaklaşan etkinlik ya da açık görev yok.</p>';
  return `<div class="m a"><span class="orb">${ic('mic')}</span><div><div class="nm">${esc(((sn.aname)||'JARVIS').toUpperCase())}</div><div class="bb">${body}<div class="acts" style="margin-top:10px;display:flex;gap:8px"><button class="ac b" data-act="tool" data-k="takvim">Takvimi aç</button><button class="ac o" data-act="homenote">Not ekle</button></div></div></div></div>`;
}
function filesHtml(){
  const all=((S.files&&S.files.files)||[]).slice().sort((a,b)=>b.mtime-a.mtime),mine=all.filter(f=>f.mine),list=(mine.length?mine:all).slice(0,5);
  const body=list.length?`<p>Son dosyaların bunlar. Hangisiyle ne yapalım?</p><div class="fcards">${list.map(f=>`<div class="fcard"><span class="fi ${f.cat}">${esc(f.ext.toUpperCase().slice(0,3))}</span><span class="fcn"><b>${esc(f.name)}</b><small>${fmtSize(f.size)} · ${fmtDate(f.mtime)}</small></span><span class="acts">${(FACTS[f.cat]||FACTS.other).slice(0,3).map(([a,t,cl])=>`<button class="ac ${cl}" data-act="fdo" data-p="${esc(f.path)}" data-a="${a}">${esc(t)}</button>`).join('')}</span></div>`).join('')}</div>`
    :'<p>Henüz yüklenmiş dosya yok. Soldaki + ile dosya ekleyebilirsin.</p>';
  return `<div class="m a"><span class="orb">${ic('mic')}</span><div><div class="nm">${esc(((S.snap||{}).aname||'JARVIS').toUpperCase())}</div><div class="bb">${body}</div></div></div>`;
}
async function loadFiles(force=false){
  const owner=S.snap?.user?.slug;
  const files=await tryApi('files_list',force);
  if(owner===S.snap?.user?.slug)S.files=files||{files:[],counts:{}};
}
const FCATS=[['mine','Yüklediklerim'],['all','Tümü'],['pdf','PDF'],['word','Word'],['excel','Excel'],['image','Görsel'],['other','Diğer']];
const FACTS={pdf:[['analiz','Analiz Et','b'],['excel','PDF → Excel','g'],['cevir_tr','Türkçeye Çevir','b'],['ozet','Özetle','o'],['gorsellestir','Görselleştir','p']],word:[['cevir_tr','Türkçeye Çevir','b'],['cevir','İngilizceye Çevir','b'],['ozet','Özetle','o'],['pdf','Rapor','p'],['gorsellestir','Görselleştir','p']],
  excel:[['analiz','Analiz Et','b'],['cevir_tr','Türkçeye Çevir','b'],['ozet','Rapor Oluştur','p'],['gorsellestir','Görselleştir','p']],image:[['metin','Metne Çevir','p'],['gorsel','Analiz Et','b']],other:[['analiz','Analiz Et','b'],['cevir_tr','Türkçeye Çevir','b'],['ozet','Özetle','o'],['gorsellestir','Görselleştir','p']]};
PAGES.files=pg=>{
  pg.innerHTML=`<header class="pagehead file-heading">
      <div><h1>Dosyalar</h1><p>Belgelerini bul, incele ve dönüştür.</p></div>
    </header>
    <div class="fgrid">
      <section class="card filelist" aria-label="Dosya listesi">
        <div class="file-searchbar">
          <label class="search">${ic('search')}<input id="fq" aria-label="Dosyalarda ara" placeholder="Dosyalarda ara…" value="${esc(S.fq)}"></label>
          <button class="btn pri" data-act="attach">${ic('plus')} Dosya ekle</button>
          <button class="btn" data-act="frefresh" aria-label="Dosya listesini yenile" title="Yenile">${ic('refresh')}</button>
        </div>
        <div class="chips" id="fchips"></div>
        <div class="filelist-scroll"><table class="ft">
          <thead><tr><th>Dosya adı</th><th>Tür</th><th>Tarih</th><th><span class="visually-hidden">İşlemler</span></th></tr></thead>
          <tbody id="ftb"><tr><td colspan="4" class="empty">Dosyalar taranıyor…</td></tr></tbody>
        </table></div>
        <div class="fpager" id="fpg"></div>
        <details class="file-tools"><summary>Dosya ve klasör araçları</summary>
          <div class="file-tools-bar">
            <button class="btn" data-act="fupdir">${ic('up')} Klasör yükle</button>
            <button class="btn" data-act="fdir">${ic('folder')} Jarvis klasörü</button>
            <button class="btn" data-act="fhelp">${ic('help')} Dosya rehberi</button>
          </div>
          <div class="agrid">${[
            ['green','scan','Kapsamlı dosya analizi','analiz'],['red','file','PDF → Excel','excel'],
            ['blue','file','PDF → Word','word'],['purple','chart','Rapor oluştur','pdf'],
            ['orange','folder','Klasör analizi','#folder'],['cyan','chart','Klasör envanteri','envanter'],
            ['purple','image','Görselden metin','metin']
          ].map(([color,icon,label,action])=>`<button class="tool" data-act="ftool" data-a="${action}"><span class="ib sm ${color}">${ic(icon)}</span><b>${label}</b></button>`).join('')}</div>
        </details>
      </section>
      <section class="card detail" id="fdet" aria-label="Seçili dosya"></section>
    </div>
`;
  $('#fq').oninput=e=>{S.fq=e.target.value;S.fpg=0;drawFiles();fContent()};
  (S.files?Promise.resolve():loadFiles()).then(drawFiles);
};
// Arama: dosya adı + belge içeriği (içerik isabetleri S.fhits'te, Jarvis'e yüklenen belgeler dizinlenir); eşleşme cümlesi satırın altında görünür.
function fFiltered(){const fs=(S.files&&S.files.files)||[],q=S.fq.toLowerCase(),hits=S.fq.trim().length>=3&&S.fhits?S.fhits:{},ok=f=>S.fcat==='all'||(S.fcat==='mine'?f.mine:f.cat===S.fcat);
  const base=fs.filter(f=>ok(f)&&(!q||f.name.toLowerCase().includes(q)||hits[f.path])),have=new Set(base.map(f=>f.path));return base.concat(Object.values(hits).filter(h=>!have.has(h.path)&&ok(h)))}
function fSnip(f){const h=S.fhits&&S.fhits[f.path];return h&&S.fq.trim().length>=3?`<small class="fsnip">${esc(h.snippet)}</small>`:''}
function fContent(){const q=S.fq.trim();clearTimeout(S.fcTimer);if(q.length<3){S.fhits=null;return}const who=((S.snap||{}).user||{}).slug||((S.snap||{}).user||{}).name;
  S.fcTimer=setTimeout(async()=>{const r=await tryApi('files_search',q);if(S.fq.trim()!==q||who!==(((S.snap||{}).user||{}).slug||((S.snap||{}).user||{}).name))return;S.fhits=Object.fromEntries((r||[]).map(h=>[h.path,h]));S.fpg=0;if($('#fq'))drawFiles()},350)}
function drawFiles(){
  const ch=$('#fchips');if(!ch)return;
  const counts=(S.files&&S.files.counts)||{};
  ch.innerHTML=FCATS.map(([key,label])=>`<button class="chip ${S.fcat===key?'on':''}" aria-pressed="${S.fcat===key}" data-act="fcat" data-k="${key}">${label} <small>${key==='mine'?((S.files&&S.files.files)||[]).filter(f=>f.mine).length:counts[key]||0}</small></button>`).join('');
  const all=fFiltered().slice(0,200);
  if(!all.some(f=>f.path===S.fsel))S.fsel=all[0]?.path||null;
  let files=all;
  const paint=()=>{
    $('#ftb').innerHTML=files.length?files.map(f=>`<tr class="${S.fsel===f.path?'on':''}" data-act="fsel" data-p="${esc(f.path)}">
      <td><button class="file-name" data-act="fsel" data-p="${esc(f.path)}" aria-pressed="${S.fsel===f.path}">
        <span class="fi ${esc(f.cat)}">${esc(f.ext.toUpperCase().slice(0,3))}</span>
        <span><b title="${esc(f.path)}">${esc(f.name)}</b><small class="floc">${esc(f.where||f.folder)}</small>${fSnip(f)}</span>
      </button></td>
      <td>${esc({pdf:'PDF',word:'Word',excel:'Excel',image:'Görsel'}[f.cat]||f.ext.toUpperCase())}</td><td>${fmtDate(f.mtime)}</td>
      <td><button class="ab" data-act="fmenu" data-p="${esc(f.path)}" aria-label="${esc(f.name)} için işlemler">•••</button></td>
    </tr>`).join(''):`<tr><td colspan="4" class="empty">${S.files?'Bu filtrede dosya yok.':'Dosyalar taranıyor…'}</td></tr>`;
  };
  paint();fPager(all,paint,rows=>{files=rows});drawDetail();
}
function fPager(all,paint,setFs){const pg=$('#fpg');if(!pg)return;const box=$('.filelist-scroll'),r=box&&box.querySelector('#ftb tr[data-p]');
  if(!box||!r){pg.innerHTML='';return}
  const th=box.querySelector('thead'),n=Math.max(3,Math.floor((box.clientHeight-(th?th.offsetHeight:0))/Math.max(30,r.offsetHeight))),pages=Math.max(1,Math.ceil(all.length/n));
  S.fpg=Math.min(S.fpg||0,pages-1);setFs(all.slice(S.fpg*n,S.fpg*n+n));paint();
  pg.innerHTML=pages>1?`<button data-act="fpg" data-d="-1" ${S.fpg?'':'disabled'}>‹ Önceki</button><span>${S.fpg+1} / ${pages} · ${all.length} dosya</span><button data-act="fpg" data-d="1" ${S.fpg<pages-1?'':'disabled'}>Sonraki ›</button>`:`<span>${all.length} dosya</span>`}
ACT.fpg=el=>{S.fpg=Math.max(0,(S.fpg||0)+ +el.dataset.d);drawFiles()};
function fillFilePreview(host,file){
  const owner=S.snap?.user?.slug;
  if(!host||!owner)return;
  const key=JSON.stringify([owner,file.path,file.mtime,file.size]);
  if(S.filePreview?.key!==key)S.filePreview={key,promise:api('file_preview',file.path,owner)};
  const current=()=>host.isConnected&&S.fsel===file.path&&S.snap?.user?.slug===owner&&S.filePreview?.key===key;
  S.filePreview.promise.then(result=>{
    if(!current()||result?.owner!==owner)return;
    if(!result.image?.startsWith('data:image/webp;base64,'))throw new Error('Önizleme alınamadı.');
    const image=document.createElement('img');
    image.src=result.image;image.alt=file.cat==='pdf'?'PDF’nin ilk sayfası':file.name;
    host.replaceChildren(image);
  }).catch(error=>{if(current())host.textContent=error.message||'Önizleme alınamadı.'});
}
function drawDetail(){
  const el=$('#fdet');if(!el)return;
  const files=fFiltered(),f=files.find(x=>x.path===S.fsel)||files[0];
  if(!f){el.innerHTML='<p class="empty">Bir dosya seç.</p>';S.filePreview=null;return}
  S.fsel=f.path;
  const canPreview=/^(pdf|png|jpe?g|webp|gif|bmp)$/i.test(f.ext);
  const actions=FACTS[f.cat]||FACTS.other;
  const primary=f.cat==='image'?['gorsel','Analiz et']:['ozet','Özetle'];
  const shortcuts=[primary,...(f.cat==='pdf'?[['excel','Excel’e dönüştür']]:[])];
  const actionBtn=([action,label],appearance='')=>`<button class="btn ${appearance}" data-act="fdo" data-a="${action}" data-p="${esc(f.path)}">${esc(label)}</button>`;
  el.innerHTML=`<header class="file-detail-head"><h2>${esc(f.name)}</h2><p class="mut">${esc(f.ext.toUpperCase())} · ${fmtSize(f.size)}</p></header>
    <div class="tabs">
      <button class="${S.ftab==='genel'?'on':''}" data-act="ftab" data-t="genel">Genel bakış</button>
      <button class="${S.ftab==='ai'?'on':''}" data-act="ftab" data-t="ai">Yapay zekâ işlemleri</button>
    </div>
    ${S.ftab==='genel'?`
      <div class="file-preview" ${canPreview?'data-file-preview role="status"':''}>${canPreview?'Önizleme hazırlanıyor…':`${ic('file')}<span>${esc(f.ext.toUpperCase())} dosyası</span>`}</div>
      <div class="file-quick">${shortcuts.map((entry,i)=>actionBtn(entry,i?'':'pri')).join('')}<button class="btn" data-act="fopen" data-p="${esc(f.path)}">${ic('eye')} Aç</button></div>
      <details class="file-info"><summary>Dosya bilgileri</summary>
        <div class="kv"><span>Son güncelleme</span><b>${fmtDate(f.mtime)} ${hm(f.mtime)}</b><span>Konum</span><b>${esc(f.where||f.folder)}</b></div>
        <div class="file-quick"><button class="btn sm" data-act="freveal" data-p="${esc(f.path)}">${ic('folder')} Klasörde göster</button><button class="btn sm" data-act="fdo" data-a="telefon" data-p="${esc(f.path)}">${ic('phone')} Telefona gönder</button></div>
      </details>`:`<div class="file-quick">${Object.entries({
        ...Object.fromEntries(actions),analiz:'Kapsamlı analiz et',ozet:'Özetle',cevir:'İngilizceye çevir',
        excel:'Excel’e dönüştür',word:'Word’e dönüştür',pdf:'PDF’e dönüştür',
        ...(f.cat==='image'?{gorsel:'Görseli analiz et',metin:'Metni çıkar'}:{gorsellestir:'Görselleştir'})
      }).map(entry=>actionBtn(entry)).join('')}</div>`}`;
  if(canPreview&&S.ftab==='genel')fillFilePreview(el.querySelector('[data-file-preview]'),f);
}
ACT.fcat=el=>{S.fcat=el.dataset.k;S.fpg=0;drawFiles()};
ACT.fsel=el=>{
  S.fsel=el.dataset.p;
  $$('#ftb tr[data-p]').forEach(row=>{
    const selected=row.dataset.p===S.fsel;
    row.classList.toggle('on',selected);
    row.querySelector('.file-name').setAttribute('aria-pressed',String(selected));
  });
  drawDetail();
};
ACT.ftab=el=>{S.ftab=el.dataset.t;drawDetail()};
ACT.fdo=(el,e)=>{e.stopPropagation();doFile(el.dataset.p,el.dataset.a)};
ACT.fopen=el=>api('file_open',el.dataset.p,false);
ACT.freveal=el=>api('file_open',el.dataset.p,true);
ACT.fdir=()=>api('files_dir_open');
ACT.fupdir=async()=>{const owner=((S.snap||{}).user||{}).slug||((S.snap||{}).user||{}).name;toast('Klasör seçme penceresi açılıyor…');let r=await tryApi('folder_pick');if(r&&r.job){while(r&&r.job){await new Promise(resolve=>setTimeout(resolve,350));const status=await tryApi('ui_job_status',r.job);if(!status)return;if(owner!==(((S.snap||{}).user||{}).slug||((S.snap||{}).user||{}).name))return;if(status.state==='error')return toast(status.error,'bad');if(status.state==='done'){r=status.data;break}}}if(!r||!r.path)return;
  if(!r.count)return toast('Klasörde yüklenecek dosya bulunamadı.','bad');
  if(!await ask(`“${r.name}” klasöründeki ${r.count} dosya Jarvis'e yüklensin mi?`))return;
  toast(`${r.count} dosya yükleniyor…`);const x=await tryApi('folder_import',r.path);if(x)toast(`${x.ok}/${x.total} dosya yüklendi → Jarvis Dosyaları › ${r.name}`);S.files=null;S.fcat='mine';S.fq='';if(S.page==='files')render()};
ACT.frefresh=async()=>{S.filePreview=null;S.files=null;drawFiles();await loadFiles(true);drawFiles();toast('Dosya listesi yenilendi.')};
const FHELP=[
  ['up','Dosya Yükle / Klasör Yükle','Bilgisayarından tek bir dosya ya da bir klasördeki bütün dosyaları Jarvis’e yükler. Yüklenenler kendi klasörüne kopyalanır, aslına dokunulmaz.'],
  ['folder','Jarvis Klasörü','Yüklediğin dosyaların gerçekte durduğu klasörü açar (Belgeler › Jarvis Dosyaları). Oraya elle dosya da atabilirsin, liste kendiliğinden görür.'],
  ['search','Arama','Yazdığın kelimeyi hem dosya adında hem belge İÇERİĞİNDE arar (en az 3 harf). Eşleşen cümle, satırın altında küçük bir alıntı olarak görünür.'],
  ['spark','Yapay Zekâ Araçları','Dosya ve klasör araçları bölümündeki seçenekler — Kapsamlı Analiz, PDF → Excel, PDF → Word, Rapor Oluştur, Klasör Analizi, Görselden Metin.'],
  ['list','Dosya Listesi','Dosyaya tıklayınca önizleme ve türüne uygun işlemler açılır. ••• menüsünde Aç, Klasörde göster ve Telefona gönder seçenekleri bulunur.'],
  ['eye','Detay Paneli','Bir dosyaya tıklayınca sağda açılır: Genel bakış (yerel önizleme ve dosya bilgileri) ve Yapay zekâ işlemleri sekmeleri arasında geçiş yapabilirsin.'],
  ['grid','Üstteki Kategoriler','Yüklediklerim / Tümü / PDF / Word / Excel / Görsel / Diğer — listeyi türe göre süzer, yanındaki sayı o kategorideki dosya adedidir.'],
  ['image','Görselleştir','Bir dosyanın "Görselleştir" düğmesine basınca, içeriğinden zihin haritası/akış şeması/infografik gibi bir görsel üretir ve bu sayfaya kaydeder. Sohbette de "zihin haritası çiz" gibi doğal bir şey söylersen Jarvis sohbetten mi dosyadan mı alacağını sorar.'],
];
ACT.fhelp=()=>{
  const overlay=document.createElement('div');overlay.className='jdlg';
  overlay.innerHTML=`<div class="jbox" style="width:min(640px,94vw);max-height:80vh;overflow:auto"><div class="jt"><b>Dosyalar sayfası nasıl çalışır?</b></div>
    <p class="mut" style="margin:0 0 12px">Bu sayfa yüklediğin dosyaları, Jarvis’in onlarla yapabileceği yapay zekâ işlemlerini ve dosya aramasını tek yerde toplar.</p>
    <div style="display:flex;flex-direction:column;gap:10px">${FHELP.map(([i,t,s])=>`<div style="display:flex;gap:10px;align-items:flex-start"><span class="ib blue sm" style="flex:none">${ic(i)}</span><div><b>${esc(t)}</b><div class="mut" style="font-size:13px">${esc(s)}</div></div></div>`).join('')}</div>
    <div class="jbtn"><button class="jok">Anladım</button></div></div>`;
  document.body.appendChild(overlay);
  const close=()=>overlay.remove();
  overlay.querySelector('.jok').onclick=close;
  overlay.onclick=e=>{if(e.target===overlay)close()};
  const key=e=>{if(e.key==='Escape'){document.removeEventListener('keydown',key,true);close()}};
  document.addEventListener('keydown',key,true);
};
ACT.fmenu=(el,e)=>{e.stopPropagation();const p=el.dataset.p,r=el.getBoundingClientRect();menu(r.left-170,r.bottom+4,[['eye','Aç',()=>api('file_open',p,false)],['folder','Klasörde göster',()=>api('file_open',p,true)],['phone','Telefona gönder',()=>doFile(p,'telefon')],'-',['spark','Özetle',()=>doFile(p,'ozet')],['lang','İngilizceye çevir',()=>doFile(p,'cevir')]])};
ACT.ftool=el=>{const a=el.dataset.a;if(a==='#folder'){say('İndirilenler klasöründeki dosyaları listele ve kısaca özetle');return}
  if(a==='envanter')return ACT.finv();
  const f=((S.files&&S.files.files)||[]).find(x=>x.path===S.fsel);if(!f){toast('Önce listeden bir dosya seç.');return}doFile(f.path,a)};
// SADE: Klasör Envanteri — köklü arayüz yenilemesinde bu düğme/akış taşınabilir;
// kalıcı sözleşme API adlarıdır: folder_pick + file_inventory_excel (web_files.py).
ACT.finv=async()=>{const owner=((S.snap||{}).user||{}).slug||((S.snap||{}).user||{}).name;toast('Klasör seçme penceresi açılıyor…');let r=await tryApi('folder_pick');if(r&&r.job){while(r&&r.job){await new Promise(resolve=>setTimeout(resolve,350));const status=await tryApi('ui_job_status',r.job);if(!status)return;if(owner!==(((S.snap||{}).user||{}).slug||((S.snap||{}).user||{}).name))return;if(status.state==='error')return toast(status.error,'bad');if(status.state==='done'){r=status.data;break}}}if(!r||!r.path)return;
  try{const inv=await tryApi('file_inventory_excel',r.path);if(!inv||!inv.path)return;toast(`Envanter raporu yazıldı: ${inv.path} (çift ${inv.duplicates}, benzer ${inv.similar}, boş ${inv.empty}, eski ${inv.old})`);}catch(e){toast(e.message,'bad')}};

// ======================================================================= GÖRSEL ANALİZ
PAGES.vision=pg=>{
  const imgs=((S.files&&S.files.files)||[]).filter(f=>f.cat==='image').slice(0,8);const mode=(S.snap||{}).mode;
  pg.innerHTML=`<div class="pagehead"><div><h1>Ekran</h1><p>Ekranı, kamerayı ve görselleri yapay zekâyla incele.</p></div></div>
   <div class="grid3" style="margin-bottom:14px">
    ${[['green','monitor','Ekranı Analiz Et','Ekrandaki içeriği gör, açıkla, öner','say:ekranı analiz et'],['purple','image','Görsel Yükle ve Analiz Et','Bilgisayarından bir resim seç','act:image'],['orange','file','Görselden Metin','Resim ve taramalardaki yazıyı çıkar','act:ocr'],
       ['blue','monitor',mode==='screen'?'Ekran Paylaşımını Kapat':'Ekranı Paylaş','Sorular ekran görüntüsüyle yanıtlanır','act:share:screen'],['cyan','camera',mode==='camera'?'Kamerayı Kapat':'Kamerayı Aç','Sorular kamera görüntüsüyle yanıtlanır','act:share:camera'],['red','eye','Ekran Görüntüsü Al','Jarvis gizlensin, görüntüden alan seç','act:capture']]
     .map(([c,i,t,s,a])=>`<button class="acard ${c}" data-act="vis" data-a="${a}"><span class="ib ${c}">${ic(i)}</span><b>${t}</b><small>${s}</small><span class="go">${ic('chev')}</span></button>`).join('')}</div>
   ${mode?`<section class="card" style="margin-bottom:14px"><div class="ch"><span class="ct">${mode==='camera'?'Canlı Kamera':'Ekran Paylaşımı'}</span><button class="btn sm" data-act="vis" data-a="act:share:${mode}">Kapat</button></div><img id="vision-preview" alt="Canlı önizleme" style="display:none;width:100%;max-height:430px;object-fit:contain"><p id="vision-status" class="mut">Görüntü bekleniyor…</p></section>`:''}
   ${pcOperationsBox()}<section class="card"><div class="ch"><span class="ct">Son görseller</span><button class="link" data-go="files">Dosyalar</button></div>
    ${imgs.length?`<div class="grid2">${imgs.map(f=>`<div class="frow vrow"><span class="fi image">IMG</span><span class="vn" title="${esc(f.path)}">${esc(f.name)}</span><button class="ac b" data-act="fdo" data-a="gorsel" data-p="${esc(f.path)}">Analiz Et</button><button class="ac p" data-act="fdo" data-a="metin" data-p="${esc(f.path)}">Metin</button></div>`).join('')}</div>`:'<div class="empty">Henüz görsel yok. Yukarıdan bir görsel yükleyebilirsin.</div>'}</section>`;
  if(mode)pollVisionPreview();
  if(!S.files)loadFiles().then(()=>{if(S.page==='vision')render()});
};
ACT.vis=async el=>{const a=el.dataset.a;if(a.startsWith('say:'))return say(a.slice(4));if(a==='act:capture')return ACT.capture();if(a==='act:image')return pickUpload('gorsel','image/*');if(a==='act:ocr')return pickUpload('metin','image/*');
  if(a.startsWith('act:share:')){const r=await tryApi('share',a.slice(10));if(r)toast(r);await refresh();drawMiniPreview();if(S.page==='vision')render()}};

function showCapturePreview(capture){return new Promise(resolve=>{
 const overlay=document.createElement('div');overlay.className='jdlg';
 overlay.innerHTML=`<div class="jbox" style="width:min(760px,94vw)"><div class="jt"><b>Ekran görüntüsü</b></div><img src="${esc(capture.preview)}" alt="Seçtiğin ekran alanı" style="width:100%;max-height:60vh;object-fit:contain"><div class="jbtn"><button class="jno">Kapat</button><button class="jok">Sohbete ekle</button></div></div>`;
 document.body.appendChild(overlay);
 const done=accepted=>{document.removeEventListener('keydown',key,true);overlay.remove();resolve(accepted)};
 const key=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();done(false)}};
 document.addEventListener('keydown',key,true);
 overlay.querySelector('.jno').onclick=()=>done(false);
 overlay.querySelector('.jok').onclick=()=>done(true);
 overlay.onclick=e=>{if(e.target===overlay)done(false)};
 overlay.querySelector('.jok').focus();
})}
ACT.capture=async()=>{
 if(S.captureBusy)return;
 if(S.attPending)return toast('Dosyanın yüklenmesini bekle.');
 const owner=S.snap?.user?.name;S.captureBusy=true;
 try{
  const result=await api('screen_capture');
  if(owner!==S.snap?.user?.name||!result||result.cancelled)return;
  S.files=null;
  if(!await showCapturePreview(result)||owner!==S.snap?.user?.name)return;
  if(S.attPending)return toast('Dosyanın yüklenmesini bekle.');
  if(atts().length>=MAX_ATT)return toast(`En fazla ${MAX_ATT} dosya ekleyebilirsin.`);
  S.att=[...atts(),{path:result.path,name:result.name}];go('chat');drawAtt();
  $('.ask input')?.focus();toast('Ekran görüntüsü eklendi. Talimatını yazıp gönder.');
 }catch(error){toast(error.message||'Ekran görüntüsü alınamadı.','bad')}
 finally{S.captureBusy=false}
};

// Paylaşım açıkken sohbetin köşesinde küçük canlı önizleme (Ekran sayfasında gizlenir). Görüntü yalnız yerelde alınır; model çağrısı yoktur.
let miniTimer=null,miniBusy=false;
function miniHidden(){return S.page==='home'||S.page==='vision'||((S.page==='settings'||S.page==='tools')&&S.sset==='ekran')}
function drawMiniPreview(){
  const mode=(S.snap||{}).mode;let box=$('#vprev');
  $$('.hb2[data-a^="act:share:"]').forEach(b=>{const m=b.dataset.a.slice(10),on=mode===m;b.classList.toggle('live',on);b.title=on?(m==='camera'?'Kamerayı kapat':'Ekran paylaşımını kapat'):(m==='camera'?'Kamerayı aç':'Ekranı paylaş')});
  if(S.page==='home')updateHomeStatus();
  if(!mode||miniHidden()){if(box)box.remove();clearTimeout(miniTimer);miniTimer=null;return}
  if(!box){box=document.createElement('div');box.id='vprev';box.className='vprev'+(S.vmini?' mini':'');box.innerHTML=`<div class="vph"><span></span><div class="vbtns"><button data-act="vmin" title="Küçült / büyüt">${ic('chevd')}</button><button data-act="vis" title="Kapat">${ic('x')}</button></div></div><img alt="Canlı önizleme"><p class="mut">Görüntü bekleniyor…</p>`;document.body.appendChild(box)}
  box.querySelector('span').textContent=mode==='camera'?'Canlı kamera':'Ekran paylaşımı';box.querySelector('[data-act="vis"]').dataset.a='act:share:'+mode;
  if(!miniTimer&&!miniBusy)miniTimer=setTimeout(pollMini,200);
}
ACT.vmin=()=>{S.vmini=!S.vmini;const b=$('#vprev');if(b)b.classList.toggle('mini',!!S.vmini)};
async function pollMini(){
  miniTimer=null;const box=$('#vprev');if(!box||miniBusy)return;if(!(S.snap||{}).mode)return drawMiniPreview();miniBusy=true;
  try{const d=await api('preview'),img=box.querySelector('img'),p=box.querySelector('p');if(d){img.src=d.startsWith('data:')?d:'data:image/png;base64,'+d;img.style.display='block';p.textContent=''}else p.textContent='Görüntü alınamadı. Kamera seçimini ve başka uygulamaların kamerayı kullanıp kullanmadığını kontrol et.'}
  catch(e){const p=box.querySelector('p');if(p)p.textContent=e.message}
  finally{miniBusy=false;if($('#vprev')&&!miniHidden())miniTimer=setTimeout(pollMini,1500)}
}
let previewTimer=null,previewBusy=false;
async function pollVisionPreview(){clearTimeout(previewTimer);if(previewBusy)return;const img=$('#vision-preview');if(!img||S.page!=='vision'||!(S.snap||{}).mode)return;previewBusy=true;try{const data=await api('preview');if(img.isConnected){if(data){img.src=data.startsWith('data:')?data:'data:image/png;base64,'+data;img.style.display='block';$('#vision-status').textContent='Canlı önizleme'}else $('#vision-status').textContent='Kameradan görüntü alınamadı. Kamera seçimini ve başka uygulamaların kamerayı kullanıp kullanmadığını kontrol et.'}}catch(e){if($('#vision-status'))$('#vision-status').textContent=e.message}finally{previewBusy=false;if(S.page==='vision'&&(S.snap||{}).mode)previewTimer=setTimeout(pollVisionPreview,700)}}
// HARITA START
const HARITA_CLASS={read:['okuma','ok'],local_reversible:['geri alınabilir','ok'],local_destructive:['yıkıcı','warn'],message_out:['gönderim','warn'],publish:['yayın','warn'],money_credential:['para','bad'],system_config:['sistem','warn'],physical:['fiziksel','warn']};
const HARITA_POLICY=[['ask','Sor'],['allow','İzin ver'],['deny','Engelle']];
const HARITA_AREA={cihaz:'Cihazlar',iletisim:'İletişim'};
function harita_action(t,a){
  const cls=HARITA_CLASS[a.class]||[String(a.class||'bilinmiyor'),'warn'];
  const ctl=a.policy==='locked'
    ?`<button class="harita-lock" data-map-policy="locked" disabled aria-disabled="true" title="Bu işlem kilitli">🔒 Kilitli</button>`
    :`<select class="harita-pol" data-map-tool="${esc(t.id)}" data-map-action="${esc(a.id)}" data-map-old="${esc(a.policy)}">${HARITA_POLICY.map(([v,l])=>`<option value="${v}"${v===a.policy?' selected':''}>${l}</option>`).join('')}</select>`;
  return `<div class="harita-act"><div class="harita-actx"><b>${esc(a.name)}</b><small>${esc(a.desc)}</small></div><span class="harita-badge ${cls[1]}">${esc(cls[0])}</span>${ctl}</div>`;
}
function harita_tool(t){
  const acts=Array.isArray(t.actions)?t.actions.filter(a=>a&&typeof a==='object'):[];
  return `<section class="card harita-tool"><div class="harita-th"><span class="harita-ic">${ic(t.icon||'gear')}</span><div><b>${esc(t.name)}</b><small>${esc(t.detail)}</small></div><span class="harita-state ${esc(t.state)}">${esc(t.state)}</span></div>${acts.map(a=>harita_action(t,a)).join('')}</section>`;
}
function harita_render(data){
  if(!data||typeof data!=='object'||!Array.isArray(data.tools))return `<div class="harita-wrap"><div class="empty">Harita bu sürümde yok.</div></div>`;
  const tools=data.tools.filter(t=>t&&typeof t==='object'&&t.id!==undefined&&t.name!==undefined);
  const ph=(Array.isArray(data.placeholders)?data.placeholders:[]).filter(p=>p&&typeof p==='object');
  const areas=[...new Set(tools.map(t=>t.area).concat(ph.map(p=>p.area)))];
  return `<div class="harita-wrap"><div class="harita-hub"><div class="harita-orb">${menuOrbSvg()}</div><button class="btn sm bad" data-act="stoptask">Durdur</button></div>`
    +harita_wizard_html()+areas.map(ar=>`<div class="harita-area"><h3>${esc(HARITA_AREA[ar]||ar||'Diğer')}</h3>${tools.filter(t=>t.area===ar).map(harita_tool).join('')}${ph.filter(p=>p.area===ar).map(p=>`<div class="card harita-soon"><b>${esc(p.name)}</b><span class="harita-badge">Yakında</span></div>`).join('')}</div>`).join('')+`</div>`;
}
async function harita_set_policy(tool,action,old,next,control){
  const r=await tryApi('map_set_policy',tool,action,next);
  if(r===null||r===undefined||r===false||(typeof r==='object'&&r.ok===false)){if(control)control.value=old;toast('Harita politika değişimi bu sürümde yok.','bad');return}
  if(control&&control.dataset)control.dataset.mapOld=next;
}
PAGES.map=async pg=>{
  pg.innerHTML=`<div class="harita-wrap"><div class="empty">Harita yükleniyor…</div></div>`;
  const d=await tryApi('map');
  if(S.page==='map')pg.innerHTML=harita_render(d);
};
if(typeof document!=='undefined')document.addEventListener('change',e=>{
  const s=e.target&&e.target.closest&&e.target.closest('select[data-map-tool]');if(!s)return;
  harita_set_policy(s.dataset.mapTool,s.dataset.mapAction,s.dataset.mapOld,s.value,s);
});
const HARITA_PENDING=new WeakMap(),HARITA_BUSY=new WeakSet();
const HARITA_PROGRAM_CLASSES=['local_destructive','local_reversible','read','message_out','publish','physical'];
function harita_wizard_html(){
  return `<details class="harita-wizard"><summary>Araç ekle</summary><form class="harita-form">
    <label>Araç türü<select name="kind"><option value="api">Açık API</option><option value="program">Yerel program</option><option value="device">HTTP cihaz</option></select></label>
    <fieldset class="harita-api"><legend>Açık API</legend><label>Keşfet<input name="query" maxlength="200" placeholder="Örneğin hava durumu"></label><button type="button" class="btn sm" data-harita-search>Servis ara</button>
      <label>Servis adayı<select name="candidate"><option value="">Önce servis arayın</option></select></label><label>Kesin HTTPS GET adresi<input name="endpoint" maxlength="2048"></label>
      <label>Parametre şeması<textarea name="parameters" rows="2">{}</textarea></label><p>Belgeden doğruladığınız kesin okuma adresini girin. Şema örneği: {"city":"string"}. Bu araç yalnız okuma yapar; ücret/kota doğrulanmadı.</p></fieldset>
    <fieldset class="harita-program" hidden><legend>Yerel program</legend><label>Araç adı<input name="program_name" maxlength="120"></label><label>Programın tam yolu<input name="program" maxlength="2000"></label>
      <label>Argüman listesi<textarea name="arguments" rows="3">[]</textarea></label><label>Eylem sınıfı<select name="action_class">${HARITA_PROGRAM_CLASSES.map(c=>`<option value="${c}">${esc(HARITA_CLASS[c][0])}</option>`).join('')}</select></label>
      <p>Argüman örneği: ["--dosya", "{dosya}"]. Sınıfı siz seçersiniz; varsayılan yıkıcı yerel işlem onay ister. Para ve sistem sınıfları kapalıdır. Program otomatik indirilmez.</p></fieldset>
    <fieldset class="harita-device" hidden><legend>HTTP cihaz</legend><label>Araç adı<input name="device_name" maxlength="120"></label><label>IP veya localhost adresi<input name="address" maxlength="1000"></label>
      <label>Anahtar<input name="key" type="password" autocomplete="off" maxlength="1024"></label><label class="harita-check"><input name="allow_private" type="checkbox">Bu cihaz için özel IP/localhost erişimini onaylıyorum.</label>
      <p>Yalnız açık IP veya localhost kabul edilir; genel IP HTTPS ister. GET okuma, POST fiziksel komuttur ve her seferinde onay ister. Bu genel cihazın durdurma protokolü tanımlı değildir.</p></fieldset>
    <div class="harita-buttons"><button type="button" class="btn sm" data-harita-preview>Önizle</button><button type="button" class="btn sm pri harita-confirm" data-harita-confirm disabled>Onayla ve ekle</button></div>
    <pre class="harita-review" role="status" aria-live="polite"></pre></form></details>`;
}
function harita_wizard_payload(form){
  const value=name=>form.querySelector(`[name="${name}"]`)?.value||'';
  const kind=value('kind');let payload;
  if(kind==='api')payload={candidate:value('candidate'),endpoint:value('endpoint'),parameters:JSON.parse(value('parameters')||'{}')};
  else if(kind==='program'){
    if(!HARITA_PROGRAM_CLASSES.includes(value('action_class')))throw Error('Sınıf kapalı.');
    payload={name:value('program_name'),program:value('program'),arguments:JSON.parse(value('arguments')||'[]'),action_class:value('action_class')};
    if(!Array.isArray(payload.arguments))throw Error('Argüman listesi gerekli.');
  }else if(kind==='device')payload={name:value('device_name'),address:value('address'),key:value('key'),allow_private:!!form.querySelector('[name="allow_private"]')?.checked};
  else throw Error('Araç türü geçersiz.');
  return {kind,payload};
}
function harita_wizard_reset(form){
  HARITA_PENDING.delete(form);
  const button=form.querySelector('.harita-confirm');if(button)button.disabled=true;
  const review=form.querySelector('.harita-review');if(review)review.textContent='';
}
function harita_wizard_kind(form){
  const kind=form.querySelector('[name="kind"]')?.value;
  for(const name of ['api','program','device']){const section=form.querySelector('.harita-'+name);if(section)section.hidden=name!==kind}
}
async function harita_wizard_save(form,confirmed){
  if(HARITA_BUSY.has(form))return;
  const review=form.querySelector('.harita-review');
  try{
    const data=harita_wizard_payload(form),signature=JSON.stringify(data),pending=HARITA_PENDING.get(form);
    if(confirmed&&(!pending||pending.signature!==signature)){harita_wizard_reset(form);review.textContent='Bilgiler değişti veya önizleme yok; yeniden önizleyin.';return}
    const owner=confirmed?pending.owner:null;
    harita_wizard_reset(form);HARITA_BUSY.add(form);
    review.textContent=confirmed?'Kayıt onaylanıyor…':'Önizleme hazırlanıyor…';
    const result=await tryApi('tool_wizard_add',data.kind,data.payload,!!confirmed,owner);
    if(form.isConnected===false)return;
    if(!result||result.state==='error'||result.state==='blocked'){review.textContent=result?.detail||'Araç eklenemedi. Alanları kontrol edip yeniden önizleyin.';return}
    if(!confirmed){
      if(result.state!=='approval'||typeof result.owner!=='string'||!result.owner){review.textContent='Önizleme kullanıcı bağlamı doğrulanamadı.';return}
      if(JSON.stringify(harita_wizard_payload(form))!==signature){review.textContent='Bilgiler değişti; yeniden önizleyin.';return}
      review.textContent=String(result.text||'Bu aracı eklemeyi onaylayın.');
      HARITA_PENDING.set(form,{signature,owner:result.owner});form.querySelector('.harita-confirm').disabled=false;return;
    }
    if(result.state!=='done'){review.textContent='Kayıt doğrulanamadı; yeniden önizleyin.';return}
    const key=form.querySelector('[name="key"]');if(key)key.value='';
    review.textContent='Araç kaydedildi. Gerçek PC, canlı hesap ve gerçek cihaz denenmedi.';toast('Araç Harita’ya eklendi.','ok');
    const map=await tryApi('map'),wrap=form.closest('.harita-wrap');
    if(form.isConnected!==false&&wrap&&Array.isArray(map?.tools))wrap.outerHTML=harita_render(map);
  }catch(_){harita_wizard_reset(form);review.textContent='Alanları kontrol edin: argüman listesi ve parametre şeması geçerli JSON olmalı.'}
  finally{HARITA_BUSY.delete(form)}
}
async function harita_wizard_search(form){
  if(HARITA_BUSY.has(form))return;
  harita_wizard_reset(form);HARITA_BUSY.add(form);
  const review=form.querySelector('.harita-review'),query=form.querySelector('[name="query"]').value;
  try{
    review.textContent='Servisler aranıyor…';const result=await tryApi('tool_wizard_discover',query);
    if(form.isConnected===false)return;
    if(form.querySelector('[name="query"]').value!==query){review.textContent='Arama değişti; yeniden arayın.';return}
    if(!Array.isArray(result?.candidates)){review.textContent='Servis araması tamamlanamadı.';return}
    form.querySelector('[name="candidate"]').innerHTML='<option value="">Bir aday seçin</option>'+result.candidates.filter(c=>c&&typeof c.id==='string').map(c=>`<option value="${esc(c.id)}">${esc(c.name)} — ${esc(c.url)}</option>`).join('');
    review.textContent=result.candidates.length?'Adayı seçin; resmî belgeden kesin okuma adresini ve şemayı girip önizleyin.':'Aday bulunamadı.';
  }catch(_){review.textContent='Servis araması tamamlanamadı.'}finally{HARITA_BUSY.delete(form)}
}
if(typeof document!=='undefined'){
  document.addEventListener('input',event=>{const form=event.target?.closest?.('form.harita-form');if(form)harita_wizard_reset(form)});
  document.addEventListener('change',event=>{const form=event.target?.closest?.('form.harita-form');if(form){harita_wizard_reset(form);harita_wizard_kind(form)}});
  document.addEventListener('click',event=>{const button=event.target?.closest?.('[data-harita-preview],[data-harita-confirm],[data-harita-search]'),form=button?.closest('form.harita-form');if(!form)return;event.preventDefault();if(button.hasAttribute('data-harita-search'))harita_wizard_search(form);else harita_wizard_save(form,button.hasAttribute('data-harita-confirm'))});
  document.addEventListener('submit',event=>{const form=event.target?.closest?.('form.harita-form');if(form){event.preventDefault();harita_wizard_save(form,false)}});
}
// HARITA END
const TOOLS=[['takvim','orange','calendar','Takvim ve Görevler','Günler, etkinlikler, görevler ve notlar'],['veri','cyan','folder','Veri Klasörü','Ayarlar, hafıza ve kayıtları aç'],['telefon','green','phone','Telefon','Telefondan erişim ve bildirim'],
  ['mesaj','green','whats','Mesajlar','WhatsApp kişileri ve mesaj'],['rapor','purple','chart','Gelişim Raporu','Neyi yanlış duydum, neyi yapamadım'],['tarama','blue','scan','Sistem Taraması','Her parçayı dene, sorunları göster']];
PAGES.tools=pg=>renderSettingsPage(pg,true);
ACT.tool=el=>{S.tool=el.dataset.k==='gorev'?'takvim':el.dataset.k;go('tools')};
const settingsOpen=()=>S.page==='settings'||S.page==='tools';
const TV={},redrawTool=()=>{if(settingsOpen())$$('#spane [data-tv]:not([data-lazy])').forEach(d=>TV[d.dataset.tv](d))};
ACT.tvload=el=>{const d=el.closest('[data-tv]');d.removeAttribute('data-lazy');TV[d.dataset.tv](d)};
TOOLS.unshift(['aihub','purple','spark','Yapay Zekâ ve Bağlantılar','Otomatik model seçimi ve sağlayıcı bağlantılarını yönet']);
TOOLS.push(['rehber','cyan','book','Kullanım Rehberi','Jarvis neler yapar? Nasıl kullanılır?']);
TV.rehber=el=>{el.innerHTML=JarvisGuide.general()};
ACT.aihubtab=el=>{S.sset=el.dataset.k;drawSettings()};
TV.veri=el=>{el.innerHTML=`<section class="card data-folder"><span class="ib cyan">${ic('folder')}</span><div class="data-folder-copy"><h2>Yerel Kayıtlar</h2><p>Jarvis’in Ayarları, Hafızası Ve İşlem Kayıtları Bu Klasörde Tutulur.</p><button class="btn pri" data-act="odata">${ic('folder')} Klasörü Aç</button></div></section>`};
const after=async p=>{await p;await refresh();redrawTool()};
const today=()=>ymd(new Date());
const whenTxt=w=>{const d=w.slice(0,10),t=w.length>10?' '+w.slice(11,16):'';const td=today(),tm=ymd(new Date(Date.now()+864e5));return (d===td?'Bugün':d===tm?'Yarın':d.split('-').reverse().join('.'))+t};

TV.takvim=el=>{const sn=S.snap||{};S.calDay=S.calDay||today();S.calMonth=S.calMonth||S.calDay.slice(0,7);const [year,month]=S.calMonth.split('-').map(Number),first=new Date(year,month-1,1),days=new Date(year,month,0).getDate(),offset=(first.getDay()+6)%7;
const ev=(sn.all_events||[]).slice().sort((a,b)=>a.when.localeCompare(b.when)),tasks=sn.tasks||[];
const cells=Array(offset).fill('<span></span>');for(let d=1;d<=days;d++){const date=ymd(new Date(year,month-1,d));const count=ev.filter(e=>e.when.slice(0,10)===date).length+tasks.filter(t=>!t.done&&(t.when||'').slice(0,10)===date).length;cells.push(`<button class="calday ${date===S.calDay?'on':''} ${date===today()?'today':''}" data-act="calday" data-day="${date}">${d}${count?`<small>${count}</small>`:''}</button>`)}
const row=e=>`<div class="srow"><b style="flex:1">${esc(e.title)}</b><span class="mut">${esc(whenTxt(e.when))}</span><button class="ab" data-act="evdel" data-id="${e.id}">${ic('trash')}</button></div>`;
const dayEvents=ev.filter(e=>e.when.slice(0,10)===S.calDay),dayTasks=tasks.filter(t=>(t.when||'').slice(0,10)===S.calDay);
el.innerHTML=`<div class="planner-top"><section data-mtitle="Takvim" class="card"><div class="ch"><button class="btn sm" data-act="calmonth" data-n="-1">‹</button><b>${first.toLocaleDateString('tr-TR',{month:'long',year:'numeric'})}</b><button class="btn sm" data-act="calmonth" data-n="1">›</button><button class="btn sm" data-act="caltoday">Bugün</button></div><div class="calendar-grid">${['Pzt','Sal','Çar','Per','Cum','Cmt','Paz'].map(x=>`<b>${x}</b>`).join('')}${cells.join('')}</div><div class="calsel"><h3>${esc(whenTxt(S.calDay))}</h3>${dayEvents.slice(0,4).map(row).join('')}${dayEvents.length>4?`<p class="mut">+${dayEvents.length-4} etkinlik daha</p>`:''}${dayTasks.slice(0,3).map(t=>`<div class="srow"><button class="ab" data-act="tktog" data-id="${t.id}">${ic(t.done?'check':'target')}</button><span>${esc(t.text)} ${t.done?'· Tamamlandı':''}</span></div>`).join('')}${!dayEvents.length&&!dayTasks.length?'<p class="mut">Bu gün için kayıt yok.</p>':''}
<div class="ftool"><input id="evtitle" placeholder="Etkinlik başlığı"><input id="evdate" type="date" value="${S.calDay}" aria-label="Etkinlik tarihi"><input id="evtime" type="time" aria-label="Saat (isteğe bağlı)"><button class="btn pri" data-act="evsave">Ekle</button></div>
<p class="mut">Veya gün ve saati yazarak ekle:</p><div class="ftool"><input id="evt" placeholder="Yarın 15'te toplantı"><button class="btn" data-act="evadd">Ekle</button></div></div></section><div id="planner-tasklist"></div></div><div id="planner-tasks" style="margin-top:14px"></div><section class="card" style="margin-top:14px"><h3>Yaklaşan Etkinlikler</h3>${ev.filter(e=>e.when.slice(0,10)>=today()).map(row).join('')||'<p class="mut">Yaklaşan etkinlik yok.</p>'}</section>`;
$('#evt').onkeydown=e=>{if(e.key==='Enter')ACT.evadd()};drawTaskNotes($('#planner-tasks'))};
ACT.calday=el=>{S.calDay=el.dataset.day;redrawTool()};
ACT.calmonth=el=>{const [y,m]=S.calMonth.split('-').map(Number);S.calMonth=ymd(new Date(y,m-1+(+el.dataset.n),1)).slice(0,7);redrawTool()};
ACT.caltoday=()=>{S.calDay=today();S.calMonth=S.calDay.slice(0,7);redrawTool()};
ACT.evsave=async()=>{const title=$('#evtitle').value.trim(),date=$('#evdate').value,time=$('#evtime').value;if(!title||!date)return toast('Başlık ve gün seç.','bad');const r=await tryApi('event_add',title,date+(time?'T'+time:''));if(r){S.calDay=date;S.calMonth=date.slice(0,7);await after(0)}};
ACT.evadd=async()=>{const v=$('#evt').value.trim();if(!v)return;const r=await tryApi('event_add_text',v,true);if(r){S.calDay=r.when.slice(0,10);S.calMonth=S.calDay.slice(0,7);toast('Eklendi: '+r.label);await after(0)}};
ACT.evdel=el=>after(api('event_delete',+el.dataset.id));

function drawTaskNotes(el){const sn=S.snap||{},ts=sn.tasks||[],open=ts.filter(t=>!t.done),done=ts.filter(t=>t.done),notes=sn.notes||[];
  const tr=(t,d)=>`<div class="srow"><button class="ab" data-act="tktog" data-id="${t.id}" style="color:${d?'var(--green)':'var(--mut)'}">${ic(d?'check':'target')}</button><span style="flex:1;${d?'text-decoration:line-through;color:var(--mut)':''}">${esc(t.text)}${t.when?`<small>${esc(whenTxt(t.when))}</small>`:''}</span><button class="ab" data-act="tkdel" data-id="${t.id}">${ic('trash')}</button></div>`;
  const taskMarkup=`<section class="card glow"><div class="ch"><span class="ct">Yapılacaklar</span><span class="pill">${open.length}</span></div>
     <div class="ftool"><div class="search">${ic('plus')}<input id="tki" placeholder="Yeni görev yaz, Enter’a bas"></div><input id="tkdate" type="date" value="${esc(S.calDay||today())}" aria-label="Görev tarihi"><button class="btn sm" data-act="taskadd">Ekle</button></div>${open.map(t=>tr(t,0)).join('')||'<div class="empty">Açık görev yok.</div>'}
     ${done.length?`<div class="ch" style="margin-top:14px"><span class="ct" style="font-size:15px">Tamamlanan</span><button class="link" data-act="tkclear">Temizle</button></div>${done.map(t=>tr(t,1)).join('')}`:''}</section>`;
  $('#planner-tasklist').innerHTML=taskMarkup;
  el.innerHTML=`<div class="notesworkspace"><section class="card"><div class="ch"><span class="ct">Notlar</span><span class="pill">${notes.length}</span></div><details class="noteeditor"><summary>+ Yeni Not / Görsel Ekle</summary><input id="nttitle" placeholder="Not başlığı" value="${esc(S.noteTitle||'')}" maxlength="120"><textarea id="nti" placeholder="Notunu buraya yaz; görsele ait açıklamayı da ekleyebilirsin.">${esc(S.noteText||'')}</textarea><div class="ftool"><button class="btn sm" data-act="ntimage">${ic('image')} Görsel Ekle</button><button class="btn sm pri" data-act="ntsave">Kaydet</button></div><div id="ntpreview"></div></details>
     ${notes.map(n=>`<div class="noterow"><button class="noteselect ${S.noteSelected===n.id?'on':''}" data-act="ntopen" data-id="${n.id}">${n.photo?ic('image'):ic('edit')} ${esc(n.title||String(n.text||'Görsel not').split('\n')[0].slice(0,60))}</button><button class="ab" data-act="ntdel" data-id="${n.id}" aria-label="Notu sil">${ic('trash')}</button></div>`).join('')||'<div class="empty">Not yok.</div>'}</section><section class="card notedetail" id="note-detail" aria-live="polite"><div class="empty">Soldan bir not seç.</div></section></div>`;
  $('#tki').onkeydown=e=>{if(e.key==='Enter')ACT.taskadd()};
  $('#nti').oninput=e=>{S.noteText=e.target.value};
  $('#nttitle').oninput=e=>{S.noteTitle=e.target.value};drawNotePreview();if(notes.some(n=>n.id===S.noteSelected))ACT.ntopen({dataset:{id:S.noteSelected}})};
function drawNotePreview(){const el=$('#ntpreview');if(el)el.innerHTML=S.notePreview?`<div class="notepreview"><img src="${esc(S.notePreview)}" alt="Seçilen not görseli"><button class="btn sm" data-act="ntimageclear">Görseli Kaldır</button></div>`:''}
ACT.ntimage=()=>{if(S.noteSaving)return;const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp,image/gif,image/bmp';const owner=((S.snap||{}).user||{}).name;
 input.onchange=()=>{const file=input.files[0];if(!file||owner!==((S.snap||{}).user||{}).name)return;if(file.size>20*1024*1024)return toast('Görsel en fazla 20 MB olabilir.','bad');if(S.notePreview)URL.revokeObjectURL(S.notePreview);S.noteFile=file;S.notePreview=URL.createObjectURL(file);drawNotePreview()};input.click()};
ACT.ntimageclear=()=>{if(S.notePreview)URL.revokeObjectURL(S.notePreview);S.notePreview=null;S.noteFile=null;drawNotePreview()};
ACT.ntsave=async()=>{if(S.noteSaving)return;const text=($('#nti')?.value||S.noteText||'').trim(),file=S.noteFile,owner=((S.snap||{}).user||{}).name;if(!text&&!file)return toast('Not metni veya görsel ekle.','bad');S.noteSaving=true;
 try{let path='';if(file){const result=await upload(file,true);if(!result)return;path=result.path}if(owner!==((S.snap||{}).user||{}).name)return;
 await api('note_add',text,path,($('#nttitle')?.value||S.noteTitle||'').trim());if(owner!==((S.snap||{}).user||{}).name)return;S.noteText='';S.noteTitle='';if($('#nttitle'))$('#nttitle').value='';ACT.ntimageclear();if($('#nti'))$('#nti').value='';await after(0);toast('Not kaydedildi.');
 }catch(e){toast('Not kaydedilemedi: '+e.message,'bad')}finally{S.noteSaving=false}};
ACT.ntopen=async el=>{const id=+el.dataset.id,note=((S.snap||{}).notes||[]).find(n=>n.id===id);if(!note)return;S.noteSelected=id;const owner=((S.snap||{}).user||{}).name,panel=$('#note-detail');if(!panel)return;
 panel.innerHTML=`<h3>${esc(note.title||String(note.text||'Görsel not').split('\n')[0].slice(0,60))}</h3><small class="mut">${esc(note.ts||'')}</small><div id="note-detail-image"></div><div class="notebody">${esc(note.text||'')}</div>`;
 document.querySelectorAll('.noteselect').forEach(b=>b.classList.toggle('on',+b.dataset.id===id));if(!note.photo)return;
 try{const data=await api('note_image',id);if(owner!==((S.snap||{}).user||{}).name||S.noteSelected!==id||!panel.isConnected)return;const image=$('#note-detail-image');if(image)image.innerHTML=`<img src="${esc(data)}" alt="Not görseli">`}catch(e){if(S.noteSelected===id&&owner===((S.snap||{}).user||{}).name)toast('Görsel açılamadı: '+e.message,'bad')}};
ACT.taskadd=async()=>{const t=$('#tki').value.trim();if(t)await after(api('task_add',t,$('#tkdate').value))};
TV.gorev=el=>TV.takvim(el);
ACT.tktog=el=>after(api('task_toggle',+el.dataset.id));ACT.tkdel=el=>after(api('task_delete',+el.dataset.id));
ACT.tkclear=()=>after(api('task_clear_done'));ACT.ntdel=el=>after(api('note_delete',+el.dataset.id));

function drawQR(c,m,size){const n=m.length,q=4,cell=Math.max(1,Math.floor(size/(n+q*2)));const px=cell*(n+q*2);c.width=c.height=px;c.style.width=c.style.height=px+'px';const g=c.getContext('2d');g.fillStyle='#fff';g.fillRect(0,0,px,px);g.fillStyle='#000';m.forEach((r,y)=>r.forEach((v,x)=>{if(v)g.fillRect((x+q)*cell,(y+q)*cell,cell,cell)}))}
const PH={sel:0,msg:'',nmsg:''};
TV.telefon=async el=>{const i=PH.info=await tryApi('phone_info',PH.user||'')||{};PH.user=i.user||'';const urls=i.urls||[];if(PH.sel>=urls.length)PH.sel=0;const cur=urls[PH.sel];const sn=S.snap||{},ts=i.tailscale||{},https=i.https||{};
  const scope=i.scope||'secure', legacy=!!i.token_legacy;
  el.innerHTML=`<div class="grid2"><section class="card glow"><div class="ch"><span class="ct">Android / iPhone · PC bağlantısı</span><span class="pill ${i.connected?'good':''}">${i.connected?'Telefon bağlı':i.running?'Bağlantıya hazır':'Kapalı'}</span></div>
     ${(i.users||[]).length>1?`<p class="mut" style="margin:0 0 6px;font-size:12.5px">Kimin telefonu? Her kişinin adresi kendi anahtarını taşır; başkası adına konuşamaz.</p><div class="chips" style="margin:0 0 10px">${i.users.map(u=>`<button class="chip ${u===i.user?'on':''}" data-act="phuser" data-u="${esc(u)}">${ic('user')} ${esc(u)}</button>`).join('')}</div>`:''}
     ${i.running?`<div class="chips" style="margin:0 0 12px">${urls.map((u,k)=>`<button class="chip ${k===PH.sel?'on':''}" data-act="phsel" data-i="${k}">${u.label.includes('HTTPS')?'HTTPS · mikrofon':u.label.startsWith('Her')?'Tailscale':'Aynı Wi-Fi'}</button>`).join('')}</div>
       <div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap"><canvas id="phqr" style="border-radius:8px"></canvas><div><p class="mut">Telefonun kamerasıyla QR’ı okut. Kod 90 saniye içinde bir kez kullanılır; kişisel API anahtarı içermez.</p><p class="mut">Android ve iPhone’da açılan sayfadaki ＋ düğmesiyle ana ekrana ekleyebilirsin. PC’de Jarvis açık kalmalı; mikrofon ve kurulum için HTTPS sekmesini seç.</p><p style="font-size:12px;word-break:break-all;margin:8px 0" class="mut">${esc(cur?cur.url:'')}</p>
       ${cur&&!cur.qr?'<p class="mut">QR oluşturulamadı. kurulum.bat ile segno paketini onar veya adresi kopyala.</p>':''}<button class="btn sm" data-act="phrenew">${ic('refresh')} QR’ı yenile</button> <button class="btn sm" data-act="phcopy">${ic('copy')} Adresi kopyala</button> <button class="btn sm" data-act="phoff">Kapat</button></div></div>`
     :`<p class="mut" style="margin-bottom:12px">Telefonla Jarvis’e yazmak ve komut vermek için erişim sayfası açılır. Adres gizli bir anahtar içerir.</p><button class="btn pri" data-act="phon">${ic('phone')} Telefon erişimini aç</button>`}
     ${srow('power','Jarvis açılınca erişimi aç','Her seferinde açmak zorunda kalma',`<button class="sw ${i.auto?'on':''}" data-act="phauto"></button>`)}
     <p class="mut" style="margin-top:8px">${esc(PH.msg||i.error||'')}</p></section>
   <section class="card"><div class="ch"><span class="ct">Telefon güvenliği</span><span class="pill ${legacy?'bad':'good'}">${legacy?'Eski anahtar':'Güçlü anahtar'}</span></div>
     ${srow('key','Bağlantı anahtarı',legacy?`${i.token_len||0} karakter · yenilenmeli`:`${i.token_len||0} karakter · güçlü`,`<button class="btn sm ${legacy?'pri':''}" data-act="phtoken">${ic('refresh')} Anahtarı yenile</button>`)}
     ${srow('shield','Bağlantı',scope==='secure'?'Güvenli HTTPS · önerilen':scope==='tailscale'?'Yalnız şifreli Tailscale ağı':'Wi-Fi · bağlantı şifrelenmez',`<div class="seg"><button class="${scope==='secure'?'on':''}" data-act="phscope" data-v="secure">HTTPS</button><button class="${scope==='tailscale'?'on':''}" data-act="phscope" data-v="tailscale">Yalnız Tailscale</button><button class="${scope==='both'?'on':''}" data-act="phscope" data-v="both">Wi-Fi erişimini aç</button></div>`)}
     ${srow('wifi','Tailscale',ts.state==='running'?`Bağlı${ts.name?' · '+esc(ts.name):''}`:ts.installed?'Kurulu ama bağlı değil':'Kurulu değil',`<span class="pill ${ts.state==='running'?'good':'warn'}">${ts.state==='running'?'Hazır':'Gerekli'}</span>`)}
     ${srow('lock','HTTPS',https.active?'Açık · telefon mikrofonu güvenli bağlantıda':'Kapalı',`<button class="btn sm ${https.active?'':'pri'}" data-act="tshttps" data-v="${https.active?'0':'1'}">${https.active?'HTTPS’i kapat':'HTTPS’i aç'}</button>`)}
     <div style="display:flex;gap:8px;flex-wrap:wrap;padding:10px 2px 0"><button class="btn sm" data-act="tsopen">Tailscale’i aç</button>${ts.installed?'':`<button class="btn sm" data-act="tsdownload">Tailscale indir</button>`}</div>
     <p class="mut" style="margin-top:10px">Varsayılan bağlantı <b>HTTPS</b> kullanır. Wi-Fi erişimini seçersen bağlantı şifrelenmez. Anahtarı yenilersen eski QR/Siri kestirmesi geçersiz olur ve bir kez yeniden kurman gerekir.</p></section></div>
   <div class="grid2" style="margin-top:14px"><section class="card"><div class="ch"><span class="ct">Telefona bildirim (ntfy)</span><span class="pill ${sn.ntfy?'good':''}">${sn.ntfy?'Açık':'Kapalı'}</span></div>
     <p class="mut" style="margin-bottom:12px">Hatırlatmalar telefonuna bildirim olarak gelir. Telefona ücretsiz ntfy uygulamasını kurup konuya abone olursun.</p>
     <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn sm pri" data-act="ntfy" data-a="on">Aç / konu oluştur</button><button class="btn sm" data-act="ntfy" data-a="show">Konuyu göster</button><button class="btn sm" data-act="ntfy" data-a="test">Deneme gönder</button><button class="btn sm" data-act="ntfy" data-a="off">Kapat</button></div>
     <p class="mut" style="margin-top:10px;word-break:break-all">${esc(PH.nmsg)}</p></section>
   <section class="card"><div class="ch"><span class="ct">Android · bilgisayardan bağımsız uygulama</span></div><p class="mut" style="margin-bottom:12px">Android Jarvis 3.0.8 ve sonrasında “QR ile kur” ile okut. QR anahtar içermez; 90 saniyelik ve tek kullanımlık kurulum kodudur. Kurulum sırasında telefon ve PC Tailscale üzerinden bağlı olmalı, PC’de HTTPS açık olmalı. Kurulumdan sonra uygulama PC kapalıyken de çalışır.</p>
     ${PH.app?`<canvas id="appqr"></canvas>`:`<button class="btn sm pri" data-act="phapp">${ic('phone')} Kurulum QR’ını göster</button>`}<p class="mut">${esc(PH.appmsg||'')}</p></section></div>`;
  const c=$('#phqr');if(c&&cur&&cur.qr)drawQR(c,cur.qr,190);const a=$('#appqr');if(a&&PH.app)drawQR(a,PH.app,220)};
ACT.phsel=el=>{PH.sel=+el.dataset.i;redrawTool()};
ACT.phuser=el=>{PH.user=el.dataset.u;PH.sel=0;PH.app=null;PH.appmsg='';redrawTool()};
ACT.phrenew=async()=>{await tryApi('phone_info',PH.user||'',true);PH.msg='Yeni QR hazır; 90 saniye içinde okut.';redrawTool()};
ACT.phon=async()=>{const r=await tryApi('phone_toggle',true);PH.msg=(r&&r.error)||'';after(0)};
ACT.phoff=()=>after(api('phone_toggle',false));
ACT.phauto=async()=>{await tryApi('phone_set',{auto:!PH.info.auto});redrawTool()};
ACT.phtoken=async ()=>{if(!await ask('Telefon anahtarı yenilensin mi? Eski QR adresleri ve Siri kestirmesi çalışmayacak; telefonda bir kez yeniden kurman gerekecek.'))return;const r=await tryApi('phone_token_reset');PH.info=r||PH.info;PH.msg='Anahtar yenilendi. Telefonda yeni QR/adresi kullan.';redrawTool()};
ACT.phscope=async el=>{const r=await tryApi('phone_set',{scope:el.dataset.v});PH.info=r||PH.info;redrawTool()};
ACT.tshttps=async el=>{const r=await tryApi('tailscale_https',el.dataset.v==='1');PH.info=r||PH.info;PH.msg=(r&&r.error)||((r&&r.https&&r.https.active)?'HTTPS hazır.':'');redrawTool()};
ACT.tsopen=async()=>{await tryApi('tailscale_action','open');setTimeout(redrawTool,1200)};
ACT.tsdownload=async()=>{await tryApi('tailscale_action','download')};
ACT.phcopy=async()=>{const u=((PH.info.urls||[])[PH.sel]||{}).url||'';try{await navigator.clipboard.writeText(u);toast('Adres kopyalandı.')}catch(e){toast(u)}};
ACT.ntfy=async el=>{const r=await tryApi('ntfy',el.dataset.a)||{};PH.nmsg=r.topic&&['on','show'].includes(el.dataset.a)?`${r.msg||'Konu:'} ${r.topic}`:(r.msg||(r.on?'Açık.':'Kapalı.'));after(0)};
ACT.phapp=async()=>{const r=await tryApi('phone_app_qr',PH.user||((S.snap||{}).user||{}).name||'');if(r&&r.ok){PH.app=r.qr;PH.appmsg=r.name+' için hazır.';clearTimeout(PH.appTimer);PH.appTimer=setTimeout(()=>{PH.app=null;redrawTool()},90000)}else PH.appmsg=(r&&r.msg)||'QR üretilemedi.';redrawTool()};

TV.mesaj=el=>{const c=(S.snap||{}).contacts||{},names=Object.keys(c);
  el.innerHTML=`<div class="grid2"><section class="card glow"><div class="ch"><span class="ct">Mesaj gönder</span></div><p class="mut" style="margin-bottom:10px">Jarvis WhatsApp Masaüstü’nü açıp mesajı yazar ve gönderir.</p>${names.length?'':'<p class="mut" style="margin-bottom:10px">Göndermek için önce Kişiler bölümünden bir kişi ekle.</p>'}
     <select class="sel" id="mto" style="width:100%;margin-bottom:10px">${names.map(n=>`<option>${esc(n)}</option>`).join('')}</select><textarea class="big" id="mtx" placeholder="Mesajını yaz…"></textarea>
     <button class="btn pri" style="margin-top:10px" data-act="wsend" ${names.length?'':'disabled'}>${ic('send')} Gönder</button></section>
<section class="card"><div class="ch"><span class="ct">Kişiler</span><span class="pill">${names.length}</span></div>
     ${names.map(n=>`<div class="srow"><span class="i">${ic('user')}</span><b style="flex:1">${esc(n)}</b><span class="mut">+${esc(c[n])}</span><button class="ab" data-act="cdel" data-n="${esc(n)}">${ic('trash')}</button></div>`).join('')||'<div class="empty">Kişi yok. “kişi ekle Ahmet 0532…” de ya da aşağıdan ekle.</div>'}
     <div class="ftool" style="margin-top:12px"><div class="search"><input id="cn" placeholder="Ad"></div><div class="search"><input id="cp" placeholder="0532 123 45 67"></div><button class="btn pri" data-act="cadd">${ic('plus')}</button></div></section></div>`};
ACT.cadd=async()=>{const r=await tryApi('contact_add',$('#cn').value,$('#cp').value);if(r){toast(r+' kaydedildi.');after(0)}};
ACT.cdel=async el=>{if(await ask(el.dataset.n+' silinsin mi?'))after(api('contact_delete',el.dataset.n))};
ACT.wsend=async()=>{const t=$('#mtx').value.trim();if(!t)return;await tryApi('whatsapp_send',$('#mto').value,t);toast('Mesaj gönderiliyor…');$('#mtx').value=''};


TV.rapor=async el=>{const r=await tryApi('learning_report',true)||{};
  el.innerHTML=`<section class="card glow"><div style="white-space:pre-wrap;line-height:1.6">${esc(r.text||r.summary||'Henüz rapor için yeterli kullanım yok.')}</div></section>`};
TV.tarama=async el=>{el.innerHTML='<section class="card"><div class="empty">Taranıyor…</div></section>';const r=await tryApi('scan')||[];
  el.innerHTML=`<section class="card">${r.map(x=>`<div class="srow"><span class="dot ${x.ok?(x.warn?'warn':''):'bad'}"></span><b style="min-width:200px">${esc(x.name)}</b><span class="mut">${esc(x.detail||'')}${x.fix?' — '+esc(x.fix):''}</span></div>`).join('')}</section>`};

// ======================================================================= AYARLAR
// Ayarlar: tek adres, 7 bölüm. keys = Ayarlar kutuları (drawSettings), tools = eski araç görünümleri (TV.*); alias/keys/tools eski adresleri bölüme çevirir.
const SECS=[
  {id:'ai',kw:'yapay zeka gemini groq model anahtar api ollama claude openai google gmail baglanti',t:'Yapay zekâ',i:'spark',c:'purple',alias:['baglanti']},
  {id:'ses',kw:'ses mikrofon konusma sesli yanit hey jarvis uyanma kulaklik',t:'Ses ve konuşma',i:'vol',c:'cyan',keys:['ses']},
  {id:'takvim',kw:'takvim gorev hatirlatma ajanda not',t:'Takvim ve görevler',i:'calendar',c:'orange',tools:['takvim'],alias:['gorev','araclar']},
  {id:'iletisim',kw:'telefon mesaj whatsapp qr kisi',t:'Telefon ve mesajlar',i:'phone',c:'green',tools:['telefon','mesaj']},
  {id:'ekran',kw:'ekran kamera dosya dosyalar belge paylasim goruntu',t:'Ekran ve dosyalar',i:'monitor',c:'blue',extra:'screenBox'},
  {id:'hesap',kw:'hesap kullanici gizlilik guvenlik hafiza hedef sifre',t:'Hesap ve gizlilik',i:'shield',c:'pink',keys:['kullanici','hafiza','guvenlik']},
  {id:'github',kw:'github git yukle guncelleme anahtar yedek surum',t:'GitHub',i:'branch',c:'blue',keys:['github']},
  {id:'sistem',kw:'sistem genel gorunum tema baslangic bildirim tarama rapor veri klasoru hakkinda guncelleme',t:'Sistem',i:'gear',c:'navy',keys:['genel','hakkinda'],tools:['veri','rapor','tarama'],lazy:{rapor:'Gelişim raporunu göster',tarama:'Sistem taramasını çalıştır'}}];
const TOOL_TITLE={telefon:'Telefon',mesaj:'Mesajlar',kb:'Bilgi tabanı',veri:'Veri klasörü',rapor:'Gelişim raporu',tarama:'Sistem taraması'};
const fold=x=>String(x||'').toLocaleLowerCase('tr').replace(/ç/g,'c').replace(/ğ/g,'g').replace(/ı/g,'i').replace(/ö/g,'o').replace(/ş/g,'s').replace(/ü/g,'u');
const sectionOf=x=>SECS.find(s=>s.id===x||(s.alias||[]).includes(x)||(s.keys||[]).includes(x)||(s.tools||[]).includes(x));
const sw=(k,on)=>`<button class="sw ${on?'on':''}" data-act="sset" data-k="${k}" data-v="${on?0:1}"></button>`;
const srow=(i,t,s,ctl)=>`<div class="srow2"><span class="i">${ic(i)}</span><div class="l"><b>${t}</b><small>${s}</small></div>${ctl}</div>`;
const sbox=(i,t,s,body)=>`<div class="sbox"><div class="sh"><span class="i">${ic(i)}</span><div><b>${t}</b><small>${s}</small></div></div>${body}</div>`;
const pad18=h=>`<div style="padding:12px 18px">${h}</div>`;
const field=(label,input,hint)=>`<div style="padding:10px 18px"><div class="fl" style="font-weight:600;margin-bottom:6px">${label}</div>${input}${hint?`<div class="mut" style="font-size:12.5px;margin-top:5px">${hint}</div>`:''}</div>`;
const inp=(id,ph,val,type)=>`<input class="sel" style="width:100%" id="${id}" ${type?`type="${type}"`:''} placeholder="${esc(ph||'')}" value="${esc(val||'')}" autocomplete="off">`;
function renderSettingsPage(pg,tools=false){
  const tool=S.tool;
  if(tools&&tool)S.sset=tool==='aihub'?(S.sset==='baglanti'?'baglanti':'ai'):tool;
  if(tools&&!tool&&!sectionOf(S.sset))S.sset='takvim';
  S.tool='';
  const links=tools?[
    ['takvim','Takvim ve görevler'],['telefon','Telefon'],['mesaj','Mesajlar'],
    ['ai','Yapay zekâ ve bağlantılar'],['rehber','Kullanım rehberi'],['tarama','Sistem taraması']
  ]:SECS.map(sec=>[sec.id,sec.t]);
  const active=sectionOf(S.sset)?.id||S.sset;
  pg.innerHTML=`<div class="pagehead"><h1>${tools?'Günlük işler':'Ayarlar'}</h1>${tools?'':'<label class="workspace-settings-search"><span class="visually-hidden">Ayarlarda ara</span><input id="sq" type="search" placeholder="Ayarlarda ara…"></label>'}</div>
  <div class="workspace-settings">
    <aside class="workspace-settings-nav card" aria-label="Ayar bölümleri">
      ${links.map(([id,title])=>`<button type="button" data-act="workspace-section" data-k="${id}" ${id===S.sset||(!tools&&id===active)?'aria-current="true"':''}>${esc(title)}</button>`).join('')}
      ${!tools?'<button data-go="map">Yetenek haritası</button>':''}
    </aside><section id="spane" aria-label="Seçili ayar bölümü"></section>
  </div>`;
  drawSettings();
}
ACT['workspace-section']=el=>{S.sset=el.dataset.k;S.sq='';render()};
PAGES.settings=pg=>renderSettingsPage(pg);

async function loadUi(){S.ui=await tryApi('nx_settings')||{};applyTheme()}
const SX={};          // sayfa içi geçici durum (mesajlar)
// Yapay zekâ sayfası: her sağlayıcı bir kart; karta basınca yalnız onun bağlantısı açılır, durum kart renginde görünür.
const READY_LABELS={gemini:'Gemini',groq:'Groq',cloudflare:'Cloudflare',ollama:'Yerel model',custom:'Özel API'};
function readyConnection(sn,provider){
  return SX.routerOwner===sn.user?.slug?SX.router?.ready_connections?.[provider]:null;
}
function readyBadge(sn,provider){
  const status=readyConnection(sn,provider);
  if(!status)return ['warn','Durum alınamadı'];
  if(status.state==='ok')return ['ok','Yanıt verdi'];
  if(status.state==='quota')return ['warn','Kota sınırı'];
  if(status.state==='unchecked')return ['warn','Anahtar kayıtlı'];
  if(status.state==='disabled')return ['warn','Kullanılamıyor'];
  return ['bad',status.configured?'Bağlantı sorunu':'API bilgisi eksik'];
}
const AI_CARDS=[['auto','Otomatik Model Seçimi','Jarvis seçer · anahtar gerekmez','<span class="lg" style="color:#7fd0ff">✦</span>'],
  ['gemini','Gemini','Google’ın güçlü modeli','<span class="lg" style="background:linear-gradient(135deg,#4285f4,#ea4335,#fbbc05,#34a853);-webkit-background-clip:text;color:transparent">G</span>'],
  ['groq','Groq','Ultra hızlı yanıtlar','<span class="lg" style="color:#ff4d6a">g</span>'],
  ['cloudflare','Cloudflare','Hazır metin yedeği','<span class="lg">☁</span>'],
  ['ollama','Ollama','Yerel ve gizli çalışma','<span class="lg">🦙</span>'],
  ['custom','Özel API','İlave bağlantı ve kullanım rolü','<span class="lg">＋</span>'],
  ['google','Gmail ve Takvim','Google hesabın · salt okuma','<span class="lg">✉</span>'],
  ['youtube','YouTube','Çalışma videoları · isteğe bağlı','<span class="lg">▶</span>']];
function aiStates(sn){
  const l=sn.llm||{},g=sn.google||{},y=sn.youtube||{},r=SX.routerOwner===(sn.user||{}).slug?(SX.router||{}):{};
  const on=(v,t='Bağlı')=>v?['ok',t]:['bad','Bağlı değil'];
  return {auto:['ok','Hazır'],gemini:readyBadge(sn,'gemini'),groq:readyBadge(sn,'groq'),cloudflare:readyBadge(sn,'cloudflare'),ollama:on(l.ollama_up,'Çalışıyor'),
    custom:(r.custom_connections||l.custom_connections||[]).some(c=>c.enabled)?['ok','Etkin']:['warn','İsteğe bağlı'],google:g.token?['ok','Bağlı']:g.cred?['warn','İzin bekliyor']:['bad','Bağlı değil'],
    youtube:!y.key?['bad','Bağlı değil']:y.ok===false?['bad','Hata']:y.ok===true?['ok','Bağlı']:['warn','Deneniyor']};
}
function aiPage(sn,panels,extra=''){
  const l=sn.llm||{},raw=String(l.provider||'gemini').toLowerCase(),active=raw==='smart_router'?'auto':raw,st=aiStates(sn),sel=panels[SX.aiSel]?SX.aiSel:(panels[active]?active:'auto');
  const cards=AI_CARDS.map(([id,t,s,lg])=>`<button class="apv st-${st[id][0]} ${sel===id?'sel':''} ${active===id?'act':''}" data-act="aipick" data-k="${id}" title="${esc(st[id][1])}" aria-label="${esc(t+': '+st[id][1]+(active===id?' · şu an kullanılıyor':''))}" aria-pressed="${sel===id}">${lg}<span><b>${t}</b><small>${s}</small></span><i class="sd"></i></button>`).join('');
  const usable=['auto','ollama'].includes(sel);
  const use=usable?`<div class="apuse">${active===sel?'<span class="pill good">Şu an kullanılıyor</span>':`<button class="btn sm pri" data-act="sval" data-k="ai_mode" data-v="${sel}">Bunu kullan</button>`}</div>`:'';
  return `<div class="apgrid">${cards}</div>${use}<div class="appanel">${panels[sel]}</div>${extra}`;
}
ACT.aipick=el=>{SX.aiSel=el.dataset.k;drawSettings()};
function screenBox(){const mode=(S.snap||{}).mode,on=m=>mode===m;
  return sbox('monitor','Ekran ve kamera','Sohbetin gözü. Yalnız sen açınca çalışır; önizleme yerelde kalır.',
    srow('monitor','Ekran paylaşımı','Sorular ekran görüntüsüyle yanıtlanır',sw2('screen',on('screen')))+
    srow('camera','Kamera','Sorular kamera görüntüsüyle yanıtlanır',sw2('camera',on('camera')))+
    srow('eye','Ekran sayfası','Analiz, görüntü alma, görselden metin çıkarma','<button class="btn sm" data-go="vision">Aç</button>'))+
  sbox('folder','Dosyalar','Son yüklediklerin sohbette kartlarla görünür.',
    srow('folder','Dosyalarım','Son 5 dosyanı sohbete getir','<button class="btn sm" data-say="dosyalarımı göster">Göster</button>')+
    srow('file','Dosyalar sayfası','Tüm dosyalar ve işlemler','<button class="btn sm" data-go="files">Aç</button>'));
}
const sw2=(m,on)=>`<button class="sw ${on?'on':''}" data-act="sharebtn" data-m="${m}"></button>`;
ACT.sharebtn=async el=>{const r=await tryApi('share',el.dataset.m);if(r)toast(r);await refresh();drawMiniPreview();if(settingsOpen())drawSettings()};
// Ses sayfası yan sayfada sekiz ayrı bölüm olur (her biri orbun çevresinde kendi orbunu alır). Alanlar ve Kaydet düğmesi aynıdır; tümü DOM'da kalır, ACT.vsave hepsini okur.
function sesBoxes({st,vo,devs,ls,sel,f,u,sn}){
  const save=pad18(`<button class="btn pri" data-act="vsave">${ic('check')} Kaydet</button> <span class="mut">${esc(SX.v||'')}</span>`);
  const sw1=(k,on)=>`<button class="sw ${on?'on':''}" data-act="sflag" data-k="${k}" data-v="${on?0:1}"></button>`;
  return sbox('mic','Mikrofon','Jarvis’in seni dinleyeceği cihaz ve dinleme anahtarı.',
      srow('mic','Mikrofon','“Hey Jarvis” dinlemesi',sw1('mic',f.mic))+
      field('Mikrofon cihazı',sel('micdev',[['','Windows varsayılanı'],...devs.map(d=>[d.name,d.name])],st.input_device||''),'Değişiklik için Jarvis’i yeniden başlat.')+
      field('Uzun iş beklerken dinleme',sel('mmic',[[1,'Açık · model beklerken dinle (varsayılan)'],[0,'Kapalı · yanıt bitene dek dinleme']],st.voice_mic_during_model_wait===false?0:1),'Model beklemesi mikrofonu kapatmaz; konuşma sırası, “sus” ve “dur” değişmez. Kapatırsan yanıt bitene dek dinlemez.')+save)
   +sbox('bell','Uyanma','“Hey Jarvis” ile uyanma.',
      srow('bell','Uyanma sesi','Dinlemeye geçince yumuşak bir ses',sw('wake_beep',u.wake_beep))+
      field('Uyanma hassasiyeti',sel('wsens',[[1,'1 · Zor uyanır'],[2,'2'],[3,'3 · Dengeli'],[4,'4'],[5,'5 · Çok kolay uyanır']],st.wake_sensitivity||3),'“Hey Jarvis”i kaçırıyorsa artır; kendi kendine uyanıyorsa azalt.')+save)
   +sbox('vol','Sesli Yanıt','Cevapları sesli okuma ve konuşma sesi.',
      srow('vol','Sesli yanıt','Cevapları sesli oku',sw1('speak',f.speak))+
      (vo.voices.length?field('Konuşma sesi',sel('vsel',vo.voices.map(v=>[v.key,v.name]),vo.voice)):'')+
      vresField(st,sel)+save)
   +sbox('user','Asistanın Adı','Uyanma ve konuşmada kullanılan ad.',
      field('Asistanın adı',inp('aname','Jarvis',st.assistant_name))+save)
   +sbox('check','Yerel Ses Tanıma','Konuş düğmesinde internetsiz ses tanıma.',
      field('Ses tanıma',sel('lstt',[[0,'Gemini / Google · mevcut akış'],[1,'Yerel · yalnız Konuş düğmesi']],st.local_stt_enabled?1:0),'Yerel seçimi yeniden başlatınca etkinleşir; yerel denemede “Hey Jarvis” ile arka plan uyanması kapalıdır. Cevap modeli ayrıca seçilir.')+
      field('Yerel ses modeli',sel('lsttmodel',[['small','small · başlangıç'],['base','base · daha hafif']],st.local_stt_model||'small'))+
      field('Yerel ses hızı',sel('lsttbeam',[[5,'En doğru · yavaş (varsayılan)'],[2,'Dengeli'],[1,'En hızlı · daha az doğru']],st.local_stt_beam||5),'İşlemcide yavaş kalırsa Dengeli ya da En hızlı dene.')+
      pad18(`<span class="mut">${esc(localSttText(ls))}</span> <button class="btn sm" data-act="lsttprepare">Modeli indir</button> <button class="btn sm" data-act="lsttrefresh">Durumu yenile</button>`)+save)
   +sbox('list','Düzeltmeler','Yanlış duyulan sözcükler ve özel kelimeler.',
      field('Yanlış duyulanlar',inp('sfix','city mall=steam',st.stt_fixes),'“yanlış=doğru”, virgülle ayır.')+
      field('Özel kelimeler',inp('swords','Nevzat Bey, EAE',st.stt_words),'Sık söylediğin adlar/terimler, virgülle.')+save)
   +sbox('target','Konuşma Tarzı','Yanıtların uzunluğu.',
      field('Yanıt uzunluğu',`<div class="seg">${[['kısa','Kısa'],['orta','Dengeli'],['uzun','Detaylı']].map(([v,t])=>`<button class="${(((sn||{}).prefs||{}).verbosity||'orta')===v?'on':''}" data-act="verb" data-v="${v}">${t}</button>`).join('')}</div>`))}
// Sonuç bildiriminin sesli okunması tek satırdan yönetilir: yan sayfa bölümleri ile Ayarlar
// sayfası aynı alanı, aynı kimlikle ve aynı açıklamayla gösterir.
function vresField(st,sel){return field('Sonuç bildirimi sesli okunsun',sel('vres',[[0,'Kapalı · yazılı kalsın (varsayılan)'],[1,'Açık · biten görev ve araştırma sonucu da seslendirilsin']],st.voice_announce_results?1:0),'Uzun işin sonucu ekranda yazılı kalır; bu açıkken ses kuyruğunda yanıtının arkasına sıraya girer, beş dakikadan eski sonuç yüksek sesle okunmaz.');}
// GitHub bölümü yan sayfada üç bölüm olur: bağlantı, yükle/al, güncelleme ve paketler (Ayarlar sayfası eski tek kutuyu korur).
function githubBoxes(up,dep){const msg=`<div class="mut" style="margin-top:8px;white-space:pre-wrap">${esc(SX.gh||up.sync_msg||'')}</div>`;
  return sbox('key','GitHub Bağlantısı','GitHub tek ana geliştirme kaynağıdır; Ev ve İş PC eşittir.',
      srow('refresh','Durum',up.token?('Bağlı'+(up.sha?' · sürüm '+esc(up.sha):'')):'Anahtar yok',`<span class="pill ${up.token?'good':'warn'}">${up.token?'Bağlı':'Yok'}</span>`)+
      field('GitHub anahtarı',inp('ghk','github_pat_…','','password'))+
      pad18(`<button class="btn sm pri" data-act="ghsave">${ic('check')} Kaydet ve dene</button> <button class="btn sm" data-act="ghverify">${ic('refresh')} Gerçek durumu doğrula</button>${msg}`))
   +sbox('up','Yükle ve Al','Kaynak değişiklikleri bu düğmeyle ayrı dala yüklenip PR açılır, main’e PR birleşince girer; açılışta yalnız kontrol yapılır.',
      pad18(`<button class="btn sm pri" data-act="ghpublish">${ic('up')} GitHub’a Yükle ↑</button> <button class="btn sm pri" data-act="ghpull">${ic('down')} GitHub’dan Al ↓</button>${up.sync_state==='diverged'?` <button class="btn sm pri" data-act="ghresolve">${ic('down')} Yedekle ve GitHub’dan Al</button>`:''}${msg}`))
   +sbox('refresh','Güncelleme ve Paketler','Yeni sürüm kontrolü ve paket sürümlerinin sabitlenmesi.',
      pad18(`<button class="btn sm" data-act="upd">Güncelleme var mı?</button>`)+
      srow('db','Paket sürümleri',dep.exists?`${dep.count||0} paket requirements.lock.txt ile sabit`:'Henüz sabitlenmedi · GitHub’a yüklerken otomatik sabitlenir',`<button class="btn sm" data-act="deplock">Şimdi sabitle</button>`))}
// Ekran ve Dosyalar yan sayfası (taslağa göre): önizleme + eylemler, paylaşım anahtarları, dosya bırakma alanı, son dosyalar, renkli durum satırı.
// Ekran, kamera ve PC ayarları.
ACT.pcguide=async()=>{
  const goal=await askText('Bilgisayarda ne yapmak istiyorsun? Örneğin: Fotoğrafları telefona göndermek.','');
  if(goal&&goal.trim())return say('PC yardımı: '+goal.trim().slice(0,1200));
};
function pcOperationsBox(){return sbox('monitor','PC İşlemleri','Bilgisayarında adım adım yardım, görev ve pencere işlemleri.',pad18(`<button class="btn pri" data-act="pcguide">${ic('monitor')} PC yardımı iste</button> <button class="btn" data-act="pctask">PC görevi başlat</button> <button class="btn" data-say="açık pencereleri listele">Açık pencereler</button> <button class="btn" data-say="PC izinleri">PC izinleri</button>`))}
function screenFilesPanel(){
  const mode=(S.snap||{}).mode,on=m=>mode===m;
  if(!S.files)loadFiles().then(()=>{if(settingsOpen())drawSettings()});
  const imgs=((S.files&&S.files.files)||[]).filter(f=>f.cat==='image').sort((a,b)=>b.mtime-a.mtime).slice(0,6);
  const imgRows=imgs.length?imgs.map(f=>`<div class="sfp-file"><span class="fi image">IMG</span><span class="fcn"><b>${esc(f.name)}</b><small>${fmtSize(f.size)} · ${fmtDate(f.mtime)}</small></span><button class="btn sm" data-act="fdo" data-p="${esc(f.path)}" data-a="gorsel">Analiz Et</button><button class="btn sm" data-act="fdo" data-p="${esc(f.path)}" data-a="metin">Metin</button></div>`).join(''):'<div class="empty">Henüz görsel yok. “Görsel yükle ve analiz et” ile ekleyebilirsin.</div>';
  const thumb=live=>`<div class="sfp-thumb ${live?'live':''}"><i class="c1"></i><i class="c2"></i><i class="c3"></i><i class="c4"></i>${live?'<img id="sfp-img" alt="Canlı önizleme" style="display:none">':''}<span class="sfp-ph">${live?'Görüntü bekleniyor…':'Önizleme için paylaşımı aç'}</span></div>`;
  const state=(live,name)=>`<div class="sfp-state ${live?'on':'off'}"><i></i><div><b>${name} ${live?'açık':'kapalı'}</b><small>${live?'Önizleme yalnız bu bilgisayarda kalır.':'Erişim şu anda devre dışı.'}</small></div></div>`;
  // Her işlev ayrı blok: yan sayfada her biri orbun çevresinde kendi küçük orbunu alır (menuSubsScan başlıkları bu bloklardan alır).
  return sbox('monitor','Ekran Paylaşımı','Sohbetin çözüm üretirken ekranına erişmesine izin ver.',srow('monitor','Ekran paylaşımı','Sorular ekran görüntüsüyle yanıtlanır',sw2('screen',on('screen')))+pad18(thumb(on('screen'))+state(on('screen'),'Ekran paylaşımı')))
   +sbox('camera','Kamera','Sorulara kamera görüntüsüyle yanıt alınmasını sağlar.',srow('camera','Kamera','Sorular kamera görüntüsüyle yanıtlanır',sw2('camera',on('camera')))+pad18(thumb(on('camera'))+state(on('camera'),'Kamera')))
   +sbox('eye','Ekranı İncele','Ekrandaki içeriği gör, açıkla, öner.',pad18(`<button class="btn pri" data-act="vis" data-a="say:ekranı analiz et">${ic('monitor')} Ekranı incele</button>`))
   +sbox('image','Ekran Görüntüsü Al','Jarvis gizlenir, görüntüden alan seçersin.',pad18(`<button class="btn pri" data-act="vis" data-a="act:capture">${ic('camera')} Görüntü al</button>`))
   +pcOperationsBox()
   +sbox('image','Görsel Analiz','Bir resmi analiz ettir ya da içindeki yazıyı çıkar.',pad18(`<button class="btn pri" data-act="vis" data-a="act:image">${ic('image')} Görsel yükle ve analiz et</button> <button class="btn" data-act="vis" data-a="act:ocr">${ic('file')} Görselden metin çıkar</button>`))
   +sbox('image','Son Görseller','Yüklediğin son resimler ve yapılabilecek işlemler.',pad18(`<div class="sfp-files">${imgRows}</div>`))}
ACT.pctask=async()=>{const g=await askText('Jarvis hangi PC görevini yapsın? Örneğin: hesap makinesi 12 ile 7’yi topla','');if(g&&g.trim())return say('PC görevi: '+g.trim().slice(0,600))};
let sfpTimer=0;
async function sfpPoll(){clearTimeout(sfpTimer);const img=$('#sfp-img');if(!img)return;try{const d=await api('preview');if(d){img.src=d.startsWith('data:')?d:'data:image/png;base64,'+d;img.style.display='block';const ph=img.parentElement&&img.parentElement.querySelector('.sfp-ph');if(ph)ph.style.display='none'}}catch(e){}sfpTimer=setTimeout(sfpPoll,1500)}
function sfpBind(el){if(el.querySelector('#sfp-img'))sfpPoll()}
// Ayarlarda arama: eşleşmeyen satırlar ve kutular gizlenir (yazı varken tüm bölümler çizilir).
function applySettingsFilter(el){
  const q=(S.sq||'').trim().toLocaleLowerCase('tr');if(!q)return;let hits=0;
  el.querySelectorAll('.sbox').forEach(b=>{const head=((b.querySelector('.sh')||{}).textContent||'').toLocaleLowerCase('tr');
    if(head.includes(q)){hits++;return}
    let any=false;[...b.children].forEach(c=>{if(c.classList.contains('sh'))return;const hit=c.textContent.toLocaleLowerCase('tr').includes(q);c.style.display=hit?'':'none';if(hit){any=true;if(c.tagName==='DETAILS')c.open=true}});
    b.style.display=any?'':'none';if(any)hits++});
  if(!hits)el.insertAdjacentHTML('afterbegin','<div class="empty">Bu aramayla eşleşen ayar yok.</div>');
}
document.addEventListener('input',e=>{if(e.target&&e.target.id==='sq'){S.sq=e.target.value;clearTimeout(S._sqt);S._sqt=setTimeout(()=>{if(settingsOpen())drawSettings()},250)}});
function personaPreferencesBox(data){
  if(!data)return sbox('spark','Yanıt tercihleri','Şu an okunamadı. Lütfen yeniden dene.','');
  if(data.owner!==((S.snap||{}).user||{}).slug)return '';
  return sbox('spark','Yanıt tercihlerin','Bu seçimler anlatım tarzını değiştirir. Açık tercihin öğrenilmiş öneriden üstündür.',
    (data.controls||[]).map(row=>field(esc(row.label),`<select data-persona-key="${esc(row.key)}" data-owner="${esc(data.owner)}"><option value="">Açık tercih yok</option>${row.options.map(v=>`<option value="${esc(v)}" ${row.selected===v?'selected':''}>${esc(v.replaceAll('_',' '))}</option>`).join('')}</select>`,
      esc('Etkin: '+row.effective+' · '+row.source_label)+(row.has_learned?` <button class="btn sm" data-act="personaforget" data-k="${esc(row.key)}" data-owner="${esc(data.owner)}">Öğrenilmiş öneriyi unut</button>`:''))).join(''));
}
function bindPersonaPreferences(el){
  el.querySelectorAll('[data-persona-key]').forEach(control=>{control.onchange=()=>{
    if(control.dataset.owner!==((S.snap||{}).user||{}).slug)return;
    return sAfter(api('pref_set',control.dataset.personaKey,control.value||null).then(()=>toast('Tercihin kaydedildi.')));
  }});
}
ACT.personaforget=el=>{
  if(el.dataset.owner!==((S.snap||{}).user||{}).slug)return;
  return sAfter(api('presentation_reset',el.dataset.k,'learned'));
};
// Persona controls end.
async function drawSettings(){
  const el=$('#spane');if(!el)return;const u=S.ui||{},sn=S.snap||{},f=sn.flags||{},k=S.sset,l=sn.llm||{};let h='';
  const sec=sectionOf(k)||(k==='rehber'?{id:'rehber'}:SECS[0]),keys=S.sq?SECS.flatMap(x=>x.keys||[]):(sec.id==='ai'?[k==='baglanti'?'baglanti':'ai']:(sec.keys||[]));
  const theme=`<div class="seg">${[['dark','Koyu'],['light','Açık'],['system','Sistem']].map(([v,t])=>`<button class="${u.nx_theme===v?'on':''}" data-act="sval" data-k="nx_theme" data-v="${v}">${t}</button>`).join('')}</div>`;
  for(const k of keys){
  if(k==='genel'){h+=sbox('gear','Genel Ayarlar','Uygulamanın temel davranışları.',
    srow('eye','Görünüm','Jarvis masaüstünün renk temasını seç.',theme)+
    srow('power','Başlangıçta aç','Bilgisayar açıldığında JARVIS’i başlat',sw('autostart',u.autostart))+
    srow('gear','Arka planda çalış','Pencere kapansa bile sistem tepsisinde çalışmaya devam et',sw('tray',u.tray))+
    srow('bell','Bildirimler','Ekranda kısa bilgi mesajları',sw('nx_notify',u.nx_notify!==false))+
    srow('spark','Proaktif öneriler','İlgili bir risk ya da fırsat görünce “Burada dikkat et” / “Bunu da düşünebilirsin” der',sw('proactive_suggestions',u.proactive_suggestions!==false))+
    srow('grid','Küçük Jarvis','Pencereyi simge durumuna küçültünce köşede görünür',`<button class="sw ${u.widget_on!==false?'on':''}" data-act="wset" data-v="${u.widget_on!==false?0:1}"></button>`)+
    srow('globe','Şehir','Hava durumu için (boş = konumundan bulur)',`<input class="sel" id="city" style="max-width:200px" value="${esc((sn.prefs||{}).city||'')}" placeholder="İstanbul">`))}
  else if(k==='kullanici'){let keys=[];try{keys=await api('user_keys')}catch(e){}const me=(sn.user||{}).name;
    h+=sbox('user','Kullanıcılar','Her kullanıcı kendi hafızası, sohbeti ve kendi API anahtarıyla çalışır; anahtarlar paylaşılmaz.',
      (sn.users||[]).map(n=>srow('user',esc(n),(n===me?'Şu an aktif':'')+(keys.includes(n)?' · kendi Gemini anahtarı var':''),`<div style="display:flex;gap:6px">${n===me?'<span class="pill good">Aktif</span>':`<button class="btn sm" data-act="uswitch" data-n="${esc(n)}">Geç</button>`}<button class="btn sm" data-act="uren" data-n="${esc(n)}">${ic('edit')}</button><button class="btn sm" data-act="ukey" data-n="${esc(n)}" title="Kendi Gemini anahtarı">${ic('key')}</button>${n===me?'':`<button class="btn sm" data-act="udel" data-n="${esc(n)}">${ic('trash')}</button>`}</div>`)).join('')+
      pad18(`<button class="btn sm" data-act="unew">${ic('plus')} Yeni kullanıcı</button> <span class="mut">${esc(SX.umsg||'')}</span>`))+
    sbox('target','Hedefler ve konuşma tarzı',`${esc(me||'')} için`,
      (field('Yanıt uzunluğu',`<div class="seg">${[['kısa','Kısa'],['orta','Dengeli'],['uzun','Detaylı']].map(([v,t])=>`<button class="${((sn.prefs||{}).verbosity||'orta')===v?'on':''}" data-act="verb" data-v="${v}">${t}</button>`).join('')}</div>`))+
      (sn.goals||[]).map((g,i)=>srow('target',esc(g),'',`<button class="btn sm" data-act="gdel" data-i="${i}">${ic('trash')}</button>`)).join('')+
      field('Yeni hedef',inp('goal','örn. İngilizce öğreniyorum'),'Hedefin varsa Jarvis ona göre yardımcı olur. Enter’a bas.'))}
  else if(k==='github'){let up={},dep={};try{[up,dep]=await Promise.all([api('update_status'),api('dependency_lock_status')])}catch(e){}
    h+=githubBoxes(up,dep)}
  else if(k==='baglanti'||k==='ai'){
    const owner=sn.user?.slug;
    const [up,ho,goa,dep,gsu,router]=await Promise.all(
      ['update_status','handoff_status','google_oauth_status','dependency_lock_status','google_setup_status','router_ready_status']
        .map(name=>api(name).catch(()=>({}))));
    if(owner!==S.snap?.user?.slug)return;
    SX.routerOwner=owner;SX.router=router?.owner===owner?router:null;
    const g=sn.google||{};
    const learnBox=sbox('db','Öğrenme','Jarvis seninle konuşurken.',
      srow('db','Konuşmalardan öğren','Öğrendiklerini önce onayına sunar',sw('learn_from_chat',sn.learn_on)));
    const pGem=readyProviderBox(sn,'gemini');
    const gsDone=(id)=>({json:gsu.cred==='hazir',baglan:!!gsu.token}[id]);
    const gsBox=(gsu.steps&&!g.token)?sbox('list','Google kurulum sihirbazı','Her kullanıcı kendi Google Cloud projesini açar (yaklaşık 10 dakika). Adımları sırayla yap; “Aç” ilgili Google sayfasını açar.',
        gsu.steps.map((st,i)=>{const d=gsDone(st.id);const cur=gsu.next===st.id;return srow(d?'check':'file',(i+1)+'. '+esc(st.title),esc(st.text)+(st.id==='json'&&gsu.cred_msg?' · '+esc(gsu.cred_msg):''),
          st.url?`<button class="btn sm${cur?' pri':''}" data-act="gsopen" data-v="${esc(st.id)}">Aç</button>`:(d!==undefined?`<span class="pill ${d?'good':'warn'}">${d?'Tamam':'Bekliyor'}</span>`:''))}).join('')+
        (gsu.packages===false?pad18('<span class="mut">Google paketleri kurulu değil: kurulum.bat çalıştırılmış olmalı.</span>'):'')):'';
    const pGoogle=sbox('mail','Gmail ve Google Takvim','Salt okuma. Google Cloud’dan indirdiğin client_secret…json dosyasını seç, sonra Bağlan.',
        srow('mail','Durum',g.token?'Bağlı':g.cred?'İzin bekliyor':'Kurulmadı',`<span class="pill ${g.token?'good':'warn'}">${g.token?'Bağlı':'Değil'}</span>`)+
        srow('shield','OAuth yayın durumu',goa.production?'In production · Testing izin uyarısı kapalı':'Testing / doğrulanmadı · Google izni bir süre sonra düşürebilir',`<div style="display:flex;gap:6px"><button class="btn sm" data-act="gprodopen">Google Cloud’u aç</button>${goa.production?'<span class="pill good">Production</span>':'<button class="btn sm pri" data-act="gprodok">Production yaptım</button>'}</div>`)+
        pad18(`<button class="btn sm" data-act="gpick">${ic('file')} JSON seç</button> <button class="btn sm pri" data-act="gconn">${ic('link')} Bağlan</button> <button class="btn sm" data-act="greset">Sıfırla</button><div class="mut" style="margin-top:8px;white-space:pre-wrap">${esc(SX.g||'')}</div>`)+
        srow('home','Bu bilgisayar','Ev/iş devir listesi (Google Görevler) için',`<div class="seg">${[['is','İş'],['ev','Ev']].map(([v,t])=>`<button class="${ho.place===v?'on':''}" data-act="hoplace" data-v="${v}">${t}</button>`).join('')}</div>`)+
        pad18(`<button class="btn sm" data-act="hoconn">${ic('link')} Görevler iznini ver</button> <span class="mut">${esc(SX.ho||(ho.ready?'Görevler izni kayıtlı; düşerse buradan yenile.':''))}</span>`));
    const lb=SX.lb||l.local_backend||'ollama',lbSame=lb===(l.local_backend||'ollama');
    const LB_URL={ollama:'http://127.0.0.1:11434',lmstudio:'http://127.0.0.1:1234/v1',llamacpp:'http://127.0.0.1:8080/v1'};
    const pOll=sbox('bolt',esc(l.local_label||'Ollama')+' · Yerel model','Bilgisayarında çalışan yerel model; internet ve anahtar gerekmez. Ollama, LM Studio veya llama.cpp (llama-server) seçilebilir; hepsi isteğe bağlıdır.',
      srow('spark','Durum',l.ollama_up?'Çalışıyor':'Kurulu değil veya çalışmıyor','')+
      srow('cpu','Yerel sunucu','LM Studio ve llama.cpp OpenAI uyumlu /v1 uç noktasıyla bağlanır',`<div class="seg">${[['ollama','Ollama'],['lmstudio','LM Studio'],['llamacpp','llama.cpp']].map(([v,t])=>`<button class="${lb===v?'on':''}" data-act="lbpick" data-v="${v}">${t}</button>`).join('')}</div>`)+
      field('Uç nokta',inp('lburl',LB_URL[lb],lbSame?l.ollama_url:''))+
      pad18(`<button class="btn sm pri" data-act="lbsave">Sunucuyu kaydet ve dene</button> <span class="mut">${esc(SX.lbm||'')}</span>`)+
      field('Yerel model · '+esc((sn.user||{}).name||'Kullanıcı'),inp('om','llama3.2',l.local_model),'Yalnız bu kullanıcı için. Ollama’da indirdiğin model adını yaz (ör. llama3.2, qwen2.5:7b); LM Studio/llama.cpp’de boş bırakırsan sunucudaki ilk model kullanılır.')+
      pad18(`<button class="btn sm pri" data-act="omsave">Modeli kaydet</button> <button class="btn sm" data-act="connecthelp" data-provider="ollama">Ollama Kurulumu</button> <span class="mut">${esc(SX.om||'')}</span>`)+
      pad18(`<button class="btn sm" data-act="routerlocalcaps">Görüntü desteğini kontrol et</button> <span class="mut">${esc(SX.localCapsMsg||'')}</span>`));
    const pGroq=readyProviderBox(sn,'groq');
    const pYt=sbox('play','YouTube · Çalışma videoları (isteğe bağlı)','Çalışma ekranında anlatılan konunun videoları yanda listelensin. Anahtar: console.cloud.google.com › YouTube Data API v3 › Kimlik Bilgileri › API anahtarı',
        srow('play','YouTube',(()=>{const y=sn.youtube||{};return !y.key?'Yok — yalnız “YouTube’da ara” bağlantısı':y.ok===true?'Kayıtlı · çalışıyor':y.ok===false?'Kayıtlı · HATA: '+esc(y.msg||''):'Kayıtlı · deneniyor…'})(),'')+field('YouTube API anahtarı',inp('ytk','AIza…','','password'))+pad18(`<button class="btn sm pri" data-act="ytsave">Kaydet</button>${sn.youtube_key?' <button class="btn sm" data-act="ytdel">Sil</button>':''}`));
    h=aiPage(sn,{auto:routerBox(),gemini:pGem,groq:pGroq,ollama:pOll,custom:routerConnectionsBox(sn),cloudflare:readyProviderBox(sn,'cloudflare'),google:gsBox+pGoogle,youtube:pYt},learnBox)}
  else if(k==='ses'){let st={},vo={voices:[]},devs=[],ls={};try{[st,vo,devs,ls]=await Promise.all([api('settings'),api('voice_options'),api('input_devices'),api('local_stt_status')])}catch(e){}
    const sel=(id,opts,cur)=>`<select class="sel" id="${id}" style="width:100%">${opts.map(([v,t])=>`<option value="${esc(v)}" ${String(cur)===String(v)?'selected':''}>${esc(t)}</option>`).join('')}</select>`;
    h+=sesBoxes({st,vo,devs,ls,sel,f,u,sn})}
  else if(k==='hafiza'){const pf=sn.pending_facts||[];
    let pv=null;try{pv=await api('presentation_preferences')}catch(e){}h+=personaPreferencesBox(pv);
    h+=(sn.learning_status?.state==='error'?sbox('spark','Öğrenme durumu',esc(sn.learning_status.error||'Bilgi çıkarılamadı.'),''):'')+(pf.length?sbox('spark','Onay bekleyenler','Konuşmalarından öğrendim. Onaylarsan hafızaya geçer.',pf.map((x,i)=>srow('spark',esc(x),'',`<div style="display:flex;gap:6px"><button class="btn sm pri" data-act="pfok" data-i="${i}">${ic('check')}</button><button class="btn sm" data-act="pfno" data-i="${i}">${ic('x')}</button></div>`)).join('')+pad18(`<button class="btn sm pri" data-act="pfok" data-i="-1">Hepsini kaydet</button> <button class="btn sm" data-act="pfno" data-i="-1">Hiçbirini kaydetme</button>`)):'')+
      sbox('db','Bildiklerim','Jarvis’in senin hakkında bildikleri.',(sn.facts||[]).map((x,i)=>srow('check',esc(x),'',`<button class="btn sm" data-act="fdel" data-i="${i}">${ic('trash')}</button>`)).join('')+field('Yeni bilgi',inp('fact','örn. Kedimin adı Pamuk'),'Enter’a bas.'))+
      sbox('list','Öğrettiğin kurallar','Jarvis bunlara her konuşmada uyar.',(sn.rules||[]).map((x,i)=>srow('list',esc(x),'',`<button class="btn sm" data-act="rdel" data-i="${i}">${ic('trash')}</button>`)).join('')+field('Yeni kural',inp('rule','örn. Cevapların kısa olsun'),'Enter’a bas.')+
        srow('db','Konuşmalardan öğren','Öğrendiklerini önce onayına sunar',sw('learn_from_chat',sn.learn_on))+
        srow('trash','Konuşma geçmişi','Tüm sohbet kayıtları','<button class="btn sm" data-act="hclear">Temizle</button>'))}
  else if(k==='guvenlik'){let d=null;try{d=await api('privacy_get')}catch(e){}
    h+=d?sbox('shield','Gizlilik modu','Verilerinin nereye gittiğini sen belirlersin.',Object.entries(d.modes||{}).map(([m,t])=>srow(m===d.mode?'shieldok':'shield',esc(t.split(' — ')[0]),esc(t.split(' — ')[1]||''),m===d.mode?'<span class="pill good">Seçili</span>':`<button class="btn sm" data-act="pmode" data-k="${m}">Seç</button>`)).join(''))+
      sbox('lock','Koruma','',srow('eye','Hassas bilgiyi gizle','Anahtar, e-posta, kart, IBAN, telefon buluta gitmeden maskelenir',`<button class="sw ${d.redact?'on':''}" data-act="ptog" data-k="redact" data-v="${d.redact?0:1}"></button>`)+
        srow('check','Hassas işlemlerde onay iste','Mesaj gönderme, bilgisayarı kapatma, dosya taşıma',`<button class="sw ${d.approve?'on':''}" data-act="ptog" data-k="approve" data-v="${d.approve?0:1}"></button>`)+
        srow('key','API anahtarı',d.key_protected?'Windows hesabınla şifreli saklanıyor':'Korumalı değil; Bağlantılar’da yeniden kaydet',`<span class="pill ${d.key_protected?'good':'warn'}">${d.key_protected?'Korumalı':'Düz'}</span>`)+
        srow('lock','Yerel veriler','Anahtarlar ve ayarlar kullanıcı hesabında tutulur','<span class="pill good">Açık</span>')):'<div class="empty">Gizlilik bilgisi alınamadı.</div>';
    if(d)h+=sbox('globe','Yerel modda kaynak okuma','Yerel/gizli moddayken yalnız herkese açık kaynakları okur (akademik + haber siteleri). Hiçbir şey buluta gitmez; varsayılan kapalı.',srow('globe',d.public_read?'İzin açık':'Kapalı',d.public_read?'arXiv, CrossRef, DOI ve 19 haber sitesi okunabilir':'Yerel modda araştırma ve haber kapalı',`<button class="sw ${d.public_read?'on':''}" data-act="ptog" data-k="public_read" data-v="${d.public_read?0:1}"></button>`));
  }
  else if(k==='araclar'){h+=toolsBox()}
  else{h+=sbox('info','Hakkında','JARVIS — Senin Yapay Zekâ Asistanın',`<div id="about" style="padding:14px 18px" class="mut">Yükleniyor…</div>`+
      pad18(`<button class="btn sm" data-act="upd">${ic('refresh')} Güncelleme var mı?</button> <button class="btn sm" data-act="restart">${ic('power')} Yeniden Başlat</button> <button class="btn sm" data-act="olog">${ic('file')} Kayıt dosyası</button>`));
    tryApi('update_status').then(r=>{const a=$('#about');if(a&&r)a.innerHTML=`Sürüm: <b>${esc(r.sha||'—')}</b><br>Son güncelleme: ${esc(r.msg||'—')} ${esc(r.applied||'')}`})}
  
  }
  if(S.sq)h+=screenBox();
  if(!S.sq){
    if(sec.id==='ai'){const sn2=S.snap||{};h=`<section class="card glow aihub"><div class="aihub-head"><span class="ib purple">${ic('spark')}</span><div><h2>Yapay Zekâ</h2><p>Bir yapay zekâya dokun, bağlantısı altta açılsın. Renk durumu gösterir: <span class="lgd ok"></span>bağlı <span class="lgd warn"></span>bekliyor <span class="lgd bad"></span>bağlı değil.</p></div><span class="pill">${ic('user')} ${esc((sn2.user||{}).name||'Kullanıcı')}</span></div></section>`+h}
    if(sec.extra==='screenBox')h+=screenFilesPanel();
    if(k==='rehber')h+='<div data-tv="rehber"></div>';
    const scopedTools={telefon:'telefon',mesaj:'mesaj',veri:'veri',rapor:'rapor',tarama:'tarama'};
    for(const t of (scopedTools[k]?[scopedTools[k]]:sec.tools||[])){const lz=(sec.lazy||{})[t],ttl=(sec.tools.length>1||sec.keys)&&TOOL_TITLE[t]?`<div class="sback"><b>${TOOL_TITLE[t]}</b></div>`:'';
      h+=ttl+(lz?`<div data-tv="${t}" data-lazy="1"><button class="btn" data-act="tvload">${lz}</button></div>`:`<div data-tv="${t}"></div>`)}
  }
  if(S.sset!==k||$('#spane')!==el||((S.snap||{}).user||{}).name!==(sn.user||{}).name)return;el.innerHTML=h;{const sqi=$('#sq');if(sqi&&sqi.value!==(S.sq||''))sqi.value=S.sq||''}applySettingsFilter(el);if(S.sq){const q=fold(S.sq.trim()),hit=SECS.filter(x=>fold(x.t+' '+(x.kw||'')).includes(q));if(hit.length){el.querySelector('.empty')?.remove();el.insertAdjacentHTML('afterbegin','<div class="sbox"><div class="sh"><div><b>Bölümler</b><small>Eşleşen bölümü aç</small></div></div>'+hit.map(x=>`<button class="srow2" data-act="smenu" data-k="${x.id}" style="width:100%;text-align:left"><span class="ib sm ${x.c}">${ic(x.i)}</span><div class="l"><b>${x.t}</b></div><span class="chev">${ic('chev')}</span></button>`).join('')+'</div>')}}el.querySelectorAll('[data-tv]:not([data-lazy])').forEach(d=>TV[d.dataset.tv](d));
  if(k==='baglanti'||k==='ai'||k==='github')installConnectionHelp(el);
  if(sec.id==='ekran')sfpBind(el);
  const enter=(id,fn)=>{const i=$('#'+id);if(i)i.onkeydown=e=>{if(e.key==='Enter'&&i.value.trim())fn(i.value.trim())}};
  enter('goal',v=>sAfter(api('goal_add',v)));enter('fact',v=>sAfter(api('fact_add',v)));enter('rule',v=>sAfter(api('rule_add',v).then(toast)));
  const city=$('#city');if(city)city.onchange=()=>sAfter(api('pref_set','city',city.value.trim()).then(()=>toast('Kaydedildi.')));
  bindPersonaPreferences(el);
  const vs=$('#vsel');if(vs)vs.onchange=()=>tryApi('voice_set',vs.value);
}
function connectionHelpProvider(title){
  return [['gemini',/^Gemini/],['github',/^GitHub/],['google',/^Gmail/],['groq',/^Groq/],['custom',/^Özel API/],['youtube',/^YouTube/],['ollama',/^Ollama/]].find(([,re])=>re.test(title))?.[0]||'';
}
function installConnectionHelp(el){
  if(!el.querySelectorAll)return;
  el.querySelectorAll('.sbox .sh').forEach(head=>{
    const key=connectionHelpProvider(head.querySelector('b')?.textContent||'');
    if(!key||head.querySelector('[data-act="connecthelp"]'))return;
    const button=document.createElement('button');button.className='btn sm connection-help';button.dataset.act='connecthelp';button.dataset.provider=key;button.textContent='Nasıl Bağlanırım?';head.appendChild(button);
  });
}
let closeConnectionGuide=null;
ACT.connecthelp=el=>{
  const key=el.dataset.provider;if(!JarvisGuide.hasProvider(key))return;
  if(closeConnectionGuide)closeConnectionGuide();
  const previous=document.activeElement,overlay=document.createElement('div');
  overlay.className='jdlg connection-guide-dialog';
  overlay.innerHTML='<div class="jbox connection-guide-box" role="dialog" aria-modal="true" aria-label="Bağlantı Kurulum Rehberi"><div class="connection-guide-head"><div><small>JARVIS • BAĞLANTI MERKEZİ</small><b>Adım Adım Kurulum</b></div><button class="btn sm guide-close">Kapat</button></div><div class="connection-guide-body"></div></div>';
  const body=overlay.querySelector('.connection-guide-body');
  JarvisGuide.connections(body,key);
  const close=()=>{overlay.remove();document.removeEventListener('keydown',keydown,true);closeConnectionGuide=null;if(previous?.isConnected)previous.focus()};
  const keydown=e=>{if(e.key==='Escape'){e.stopPropagation();close()}else if(e.key==='Tab'){const items=[...overlay.querySelectorAll('button,input,a')].filter(x=>!x.disabled);const first=items[0],last=items[items.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}}};
  closeConnectionGuide=close;overlay.querySelector('.guide-close').onclick=close;
  overlay.addEventListener('click',e=>{if(e.target===overlay)close()});
  document.body.appendChild(overlay);document.addEventListener('keydown',keydown,true);overlay.querySelector('.guide-close').focus();
};const sAfter=async p=>{try{await p}catch(e){toast(e.message,'bad')}await refresh();drawSettings()};
function routerBox(){
  const last=SX.routerOwner===S.snap?.user?.slug?SX.router?.last_reply:null;
  const reply=last?`${esc(READY_LABELS[last.provider]||last.provider)} · ${esc(last.model)}`:'Henüz kayıtlı sohbet yanıtı yok.';
  return sbox('bolt','Otomatik model seçimi','Hazır bağlantılar kullanılabildiğinde Jarvis işe uygun modeli seçer.',
    pad18(`<p><b>Son sohbeti yanıtlayan model</b><br>${reply}</p>`));
}
function readyProviderBox(sn,provider){
  const status=readyConnection(sn,provider),label=READY_LABELS[provider];
  const router=SX.routerOwner===sn.user?.slug?SX.router:null;
  const scopes=router?.gemini_scopes||[];
  const permissions=provider==='gemini'?`<div class="ready-permissions">
    <label class="router-confirm"><input type="checkbox" id="rgchat" ${scopes.includes('conversation')?'checked':''} ${router?'':'disabled'}> Konuşma ve istek bağlamını Gemini’ye gönder</label>
    <label class="router-confirm"><input type="checkbox" id="rgselected" ${scopes.includes('selected_content')?'checked':''} ${router?'':'disabled'}> Seçtiğim dosya ve görüntüleri Gemini’ye gönder</label>
    <p class="mut">Google, ücretsiz kullanımda gönderilen içeriği hizmetlerini geliştirmek için kullanabilir.</p></div>`:'';
  return sbox('key',label,'',
    srow('spark',readyBadge(sn,provider)[1],esc(status?.message||'Bağlantı durumu alınamadı.'),'')+
    (status?.configured&&status.model?pad18(`<p class="mut">Model ${esc(status.model)}</p>`):'')+
    (provider==='cloudflare'?field('Account ID',inp('cf-account','Cloudflare hesap kimliği','')):'')+
    field('API anahtarı',inp('ready-key',status?.configured?'Kayıtlı · değiştirmek için yeni anahtarı gir':'API anahtarını gir','','password'))+
    (permissions?pad18(permissions):'')+
    pad18(`<div class="connection-actions"><button class="btn sm pri" data-act="readySave" data-provider="${provider}">Kaydet</button>
      <button class="btn sm" data-act="readyCheck" data-provider="${provider}" ${status?.configured?'':'disabled'}>Bağlantıyı dene</button>
      ${provider==='cloudflare'&&status?.configured?'<button class="btn sm" data-act="routercfdelete">Kaldır</button>':''}</div>`));
}
ACT.readySave=async el=>{
  const owner=S.snap?.user?.slug,provider=el.dataset.provider,key=$('#ready-key').value.trim();
  const account=$('#cf-account')?.value.trim()||'';
  el.disabled=true;
  try{
    if(provider==='gemini'&&SX.routerOwner===owner&&SX.router){
      const scopes=[['conversation','rgchat'],['selected_content','rgselected']].filter(([,id])=>$('#'+id).checked).map(([name])=>name);
      await api('smart_router_save',scopes,owner);
    }
    if(owner!==S.snap?.user?.slug)return;
    if(provider==='cloudflare')await api('router_cloudflare_save',account,key,false,owner);
    else if(key)await api('router_ready_key_save',provider,key,owner);
    else if(provider!=='gemini')throw new Error('API anahtarını gir.');
    if(owner!==S.snap?.user?.slug)return;
    toast('Kaydedildi.');
    await refresh();
    if(owner===S.snap?.user?.slug&&settingsOpen())drawSettings();
  }catch(error){if(owner===S.snap?.user?.slug)toast(error.message,'bad')}
  finally{el.disabled=false}
};
ACT.readyCheck=async el=>{
  const owner=S.snap?.user?.slug;
  el.disabled=true;
  try{
    const result=await api('router_ready_check',el.dataset.provider,owner);
    if(owner!==S.snap?.user?.slug)return;
    toast(result.msg,result.ok?'good':'bad');
    if(settingsOpen())drawSettings();
  }catch(error){if(owner===S.snap?.user?.slug)toast(error.message,'bad')}
  finally{el.disabled=false}
};
ACT.routerlocalcaps=async()=>{const owner=((S.snap||{}).user||{}).slug;try{const r=await api('router_local_capabilities',owner);if(owner!==((S.snap||{}).user||{}).slug)return;SX.localCapsMsg=r.ok?(r.vision?'Görüntü destekli runtime doğrulandı: ':'Runtime görüntü desteği bildirmiyor: ')+r.model:r.reason;drawSettings()}catch(e){toast(e.message,'bad')}};
function modes(){
  const m=(((S.snap||{}).llm||{}).provider||'auto')==='ollama'?'ollama':'auto';
  return `<div class="modes">${[['auto','Otomatik Model Seçimi','Hazır bağlantılar ve seçilmiş özel roller'],['ollama','Yalnız yerel','Ollama, LM Studio veya llama.cpp']].map(([v,t,s])=>`<button class="mode ${m===v?'on':''}" data-act="sval" data-k="ai_mode" data-v="${v}"><span><b>${t}</b><small>${s}</small></span><span class="rd"></span></button>`).join('')}</div>`}

async function setUi(k,v){const r=await tryApi('nx_set',k,v);if(r){S.ui=r;await refresh();applyTheme();drawSettings();toast('Kaydedildi.')}}
ACT.smenu=el=>{S.sset=el.dataset.k;S.sq='';render()};
ACT.aiconnections=()=>openAiHub('baglanti');
ACT.sset=el=>setUi(el.dataset.k,el.dataset.v==='1');
ACT.sval=el=>setUi(el.dataset.k,isNaN(+el.dataset.v)?el.dataset.v:+el.dataset.v);
ACT.sflag=async el=>{await tryApi('set_flag',el.dataset.k,el.dataset.v==='1');await refresh();drawSettings()};
ACT.uswitch=el=>api('user_switch',el.dataset.n).then(()=>setTimeout(()=>sAfter(0),900));
ACT.unew=async ()=>{const n=await askText('Yeni kullanıcının adı:');if(n&&n.trim())api('user_new',n.trim()).then(()=>setTimeout(()=>sAfter(0),900))};
ACT.uren=async el=>{const n=await askText('Yeni ad:',el.dataset.n);if(n&&n.trim()&&n.trim()!==el.dataset.n)api('user_rename',el.dataset.n,n.trim()).then(()=>setTimeout(()=>sAfter(0),700))};
ACT.udel=async el=>{if(await ask('“'+el.dataset.n+'” silinsin mi? Verileri “silinenler” klasörüne taşınır.'))api('user_delete',el.dataset.n).then(()=>setTimeout(()=>sAfter(0),700))};
ACT.ukey=async el=>{const k=await askText(el.dataset.n+' için Gemini anahtarı (boş bırakırsan yalnız bu kullanıcının anahtarı silinir):','');if(k===null)return;const r=await tryApi('user_key_set',el.dataset.n,k.trim());if(r){SX.umsg=(r.ok?'✓ ':'✗ ')+r.msg;drawSettings()}};
ACT.verb=el=>sAfter(api('pref_set','verbosity',el.dataset.v));
ACT.gdel=el=>sAfter(api('goal_delete',+el.dataset.i));
ACT.fdel=el=>sAfter(api('fact_delete',+el.dataset.i));
ACT.rdel=el=>sAfter(api('rule_delete',+el.dataset.i));
ACT.pfok=el=>sAfter(api('pending_approve',+el.dataset.i));
ACT.pfno=el=>sAfter(api('pending_reject',+el.dataset.i));
ACT.routercfdelete=async()=>{const owner=((S.snap||{}).user||{}).slug;if(!await ask('Bu kullanıcının Cloudflare bağlantısı kaldırılsın mı?'))return;if(owner!==((S.snap||{}).user||{}).slug)return;try{const r=await api('router_cloudflare_save','','',true,owner);if(owner!==((S.snap||{}).user||{}).slug)return;SX.router=null;toast(r.msg);drawSettings()}catch(e){toast(e.message,'bad')}};
const ROUTER_ROLES=[['brain_understanding','Ana model / Brain'],['conversation','Sohbet'],['public_research','Araştırma'],['long_worker','Uzun işler'],['vision','Görüntü analizi']];
function routerConnectionsBox(sn){
  const owner=(sn.user||{}).slug;
  if(SX.customOwner!==owner){SX.customOwner=owner;SX.customId='';SX.customModels=[];SX.customMsg='';SX.localCapsMsg=''}
  const rows=(SX.routerOwner===owner?SX.router?.custom_connections:null)||sn.llm?.custom_connections||[];
  const r=rows.find(x=>x.id===SX.customId)||{protocol:'openai_compatible',role:'conversation',billing:'unknown',daily_requests:25,max_output_tokens:4096,data_scopes:[]};
  const select=(id,values,current)=>`<select class="sel" id="${id}">${values.map(([value,label])=>`<option value="${value}" ${value===current?'selected':''}>${esc(label)}</option>`).join('')}</select>`;
  const checked=(id,label,value)=>`<label class="router-confirm"><input type="checkbox" id="${id}" ${value?'checked':''}><span>${label}</span></label>`;
  const saved=rows.map(c=>`<div class="connection-actions"><span>${esc(c.name)} · ${esc(c.model||'Model seçilmedi')} · ${esc(ROUTER_ROLES.find(x=>x[0]===c.role)?.[1]||c.role)} · ${c.enabled?'Etkin':c.migration_pending?'Eski bağlantı · etkinleştirme bekliyor':'Kapalı'}</span><button class="btn sm" data-act="customedit" data-id="${esc(c.id)}">Düzenle</button><button class="btn sm" data-act="customdelete" data-id="${esc(c.id)}">Kaldır</button></div>`).join('');
  return sbox('spark','Özel API','Hazır görev düzeni sabittir. Eklediğin bağlantının kullanım rolünü seçebilirsin. Kaydetmek API denemesi yapmaz.',
    pad18(saved+`<button class="btn sm" data-act="customnew">İlave API ekle</button>`)+
    field('Bağlantı adı',inp('custom-name','Bağlantım',r.name||''))+
    field('API temel adresi',inp('custom-url','https://…/v1',r.base_url||''),'Uzak adres HTTPS; yerel sunucu loopback adresi kullanır.')+
    field('API biçimi',select('custom-protocol',[['openai_compatible','OpenAI uyumlu Chat Completions'],['responses','Responses'],['anthropic_messages','Anthropic Messages']],r.protocol))+
    field('API anahtarı',inp('custom-key','Kayıtlı anahtarı korumak için boş bırak','','password'))+
    field('Exact model kimliği',`<input class="sel" id="custom-model" list="custom-models" value="${esc(r.model||'')}" autocomplete="off"><datalist id="custom-models">${(SX.customModels||[]).map(m=>`<option value="${esc(m.id)}">${esc(m.name)}</option>`).join('')}</datalist>`)+
    field('Kullanım rolü',select('custom-role',ROUTER_ROLES,r.role),'Bu rol için etkinleştirdiğin özel bağlantı kullanılır; ücretsiz havuz ücretliye kendiliğinden geçmez.')+
    field('Hesabın ücret sınıfı',select('custom-billing',[['unknown','Bilinmiyor'],['free','Ücretsiz plan beyanı'],['trial','Deneme'],['paid','Ücretli']],r.billing),'Sınıf seçimi tek başına ücretsiz hesap veya kalan kota kanıtı değildir. Ücretsiz havuza katılım ayrıca incelenmiş hesap/model/veri kanıtı ister; bilinmeyen uygunlukta aday gönderilmez.')+
    field('Günlük Jarvis çağrı tavanı',inp('custom-daily','25',r.daily_requests),'Sağlayıcının gerçek kotası veya parasal harcama garantisi değildir.')+
    field('Çağrı başına çıktı sınırı',inp('custom-output','4096',r.max_output_tokens))+
    `<details ${r.daily_cost_microusd==null?'':'open'}><summary>İsteğe bağlı harcama sınırı</summary>`+
    field('Günlük sınır (USD)',inp('custom-money','Örn. 5',r.daily_cost_microusd==null?'':r.daily_cost_microusd/1000000))+
    field('Çağrı başına en yüksek ücret (USD)',inp('custom-call-cost','Sağlayıcının kesin üst sınırı',r.max_call_cost_microusd==null?'':r.max_call_cost_microusd/1000000),'Jarvis her çağrı için bu tutarı ayırır. Kesin tutarı bilmiyorsan çağrı sınırını kullan.')+
    '</details>'+
    field('Çalışma alanı (gerekiyorsa)',inp('custom-workspace','',r.workspace||''))+
    field('Ortak hesap/proje kota grubu (varsa)',inp('custom-quota','Aynı hesapta aynı ad',r.quota_group||''),'Boşsa endpoint ve anahtar parmak izine göre paylaşılır; anahtar görüntülenmez.')+
    pad18(checked('custom-conversation','Bu bağlantıya konuşma bağlamı gönderilebilir.',r.data_scopes.includes('conversation'))+
      checked('custom-selected','Bu bağlantıya iş için seçtiğim içerik gönderilebilir.',r.data_scopes.includes('selected_content'))+
      checked('custom-public','Herkese açık araştırma kaynakları gönderilebilir.',r.data_scopes.includes('public'))+
      checked('custom-paid','Bu bağlantıda ücretli kullanım ihtimalini kabul ediyor ve etkinleştiriyorum.',r.paid_enabled)+
      checked('custom-enabled','Seçtiğim rol için bu bağlantıyı kullan.',r.enabled)+
      checked('custom-freepool','Yalnız doğrulanmış ücretsiz hesap/model ise sabit hazır havuza ilave aday olarak kat.',r.free_pool)+
      `<div class="connection-actions"><button class="btn sm pri" data-act="customsave">Kaydet</button>${r.id?'<button class="btn sm" data-act="custommodels">Modelleri getir</button><button class="btn sm" data-act="customtest">Tek bağlantı denemesi</button><button class="btn sm" data-act="customvisiontest">Görüntü desteğini dene</button>':''}</div><p class="mut">${esc(SX.customMsg||'Model yeterliliği, vision desteği ve ücretsiz uygunluk ayrıca doğrulanır.')}</p>`));
}
ACT.customnew=()=>{SX.customId='';SX.customModels=[];SX.customMsg='';drawSettings()};
ACT.customedit=el=>{SX.customId=el.dataset.id;SX.customModels=[];SX.customMsg='';drawSettings()};
ACT.customsave=async el=>{
  const owner=((S.snap||{}).user||{}).slug;
  const money=id=>{
    const value=$('#'+id).value.trim();
    if(!value)return null;
    return /^\d+(?:[.,]\d{1,6})?$/.test(value)?Math.round(Number(value.replace(',','.'))*1000000):NaN;
  };
  const record={name:$('#custom-name').value.trim(),protocol:$('#custom-protocol').value,base_url:$('#custom-url').value.trim(),model:$('#custom-model').value.trim(),role:$('#custom-role').value,billing:$('#custom-billing').value,enabled:$('#custom-enabled').checked,paid_enabled:$('#custom-paid').checked,free_pool:$('#custom-freepool').checked,daily_cost_microusd:money('custom-money'),max_call_cost_microusd:money('custom-call-cost'),data_scopes:[['conversation','custom-conversation'],['selected_content','custom-selected'],['public','custom-public']].filter(([,id])=>$('#'+id).checked).map(([value])=>value),daily_requests:Number($('#custom-daily').value),max_output_tokens:Number($('#custom-output').value),workspace:$('#custom-workspace').value.trim(),quota_group:$('#custom-quota').value.trim()};
  if([record.daily_cost_microusd,record.max_call_cost_microusd].some(v=>v!==null&&!Number.isSafeInteger(v))){toast('Harcama sınırlarını USD tutarı olarak gir.','bad');return;}
  if(SX.customId)record.id=SX.customId;
  el.disabled=true;
  try{const r=await api('router_connection_save',record,$('#custom-key').value,owner);if(owner!==((S.snap||{}).user||{}).slug)return;$('#custom-key').value='';SX.customId=r.connection.id;SX.customMsg=r.msg;SX.router=null;await refresh();drawSettings()}catch(e){toast(e.message,'bad')}finally{el.disabled=false}
};
ACT.custommodels=async()=>{const owner=((S.snap||{}).user||{}).slug,r=await api('router_connection_models',SX.customId,owner);if(owner!==((S.snap||{}).user||{}).slug)return;SX.customModels=r.models||[];SX.customMsg='Model listesi alındı; rol yeterliliği veya ücretsiz kullanım kanıtı değildir.';drawSettings()};
ACT.customtest=async()=>{const owner=((S.snap||{}).user||{}).slug,id=SX.customId;if(!await ask('Kaydedilmiş bağlantıda tek küçük gerçek model çağrısı yapılacak. Sağlayıcı ücretlendirebilir. Denensin mi?'))return;if(owner!==((S.snap||{}).user||{}).slug)return;const r=await api('router_connection_test',id,true,owner);if(owner!==((S.snap||{}).user||{}).slug)return;SX.customMsg=r.msg;drawSettings()};
ACT.customvisiontest=async()=>{const owner=((S.snap||{}).user||{}).slug,id=SX.customId;if(!await ask('Bu bağlantıya yalnız sentetik bir test görüntüsüyle tek küçük çağrı yapılacak. Sağlayıcı ücretlendirebilir. Denensin mi?'))return;if(owner!==((S.snap||{}).user||{}).slug)return;try{const r=await api('router_connection_vision_test',id,true,owner);if(owner!==((S.snap||{}).user||{}).slug)return;SX.customMsg=r.msg;drawSettings()}catch(e){toast(e.message,'bad')}};
ACT.customdelete=async el=>{const owner=((S.snap||{}).user||{}).slug,id=el.dataset.id;if(!await ask('Bu özel bağlantı kaldırılsın mı?'))return;if(owner!==((S.snap||{}).user||{}).slug)return;await api('router_connection_delete',id,owner);if(owner!==((S.snap||{}).user||{}).slug)return;SX.customId='';SX.router=null;await refresh();drawSettings()};

const msgOf=r=>(r&&r.ok?'✓ ':'✗ ')+((r&&r.msg)||'');
ACT.ghsave=async el=>{const v=$('#ghk').value.trim();if(!v)return;el.disabled=true;SX.gh='Deneniyor…';try{SX.gh=msgOf(await api('update_token_save',v))}catch(e){SX.gh='✗ '+e.message}sAfter(0)};
ACT.ghverify=async()=>{SX.gh='GitHub main ile gerçek dosya karşılaştırması yapılıyor…';drawSettings();const r=await tryApi('github_verify');SX.gh=msgOf(r)+ghFiles(r);await refresh();drawSettings()};
const ghFiles=r=>{const f=(r&&r.local_changes)||[];if(String((r&&r.msg)||'').includes('Engelleyen dosyalar'))return '';return f.length?'\nGitHub’dan farklı dosyalar: '+f.join(', ')+(r.local_change_count>f.length?' …':''):''};
ACT.ghresolve=async el=>{const v=await tryApi('github_verify');if(!v||v.sync_state!=='diverged'){SX.gh=msgOf(v);await refresh();if(settingsOpen())drawSettings();else toast(SX.gh);return}
  if(!await ask('Bu bilgisayarda GitHub’dan farklı '+(v.local_change_count||0)+' dosya var. Önce hepsini ~/.jarvis/yerel_yedek klasörüne yedekleyip sonra GitHub main sürümünü kurayım mı?'+ghFiles(v)))return;
  if(el)el.disabled=true;SX.gh='Farklı dosyalar yedekleniyor ve GitHub main testlerden geçirilerek kuruluyor…';if(settingsOpen())drawSettings();else toast(SX.gh);
  try{const r=await api('github_backup_pull');SX.gh=msgOf(r);toast(r.msg,r.ok?'':'bad')}catch(e){SX.gh='✗ '+e.message;toast(e.message,'bad')}finally{if(el)el.disabled=false}
  await refresh();if(settingsOpen())drawSettings()};
ACT.deplock=async()=>{const r=await tryApi('dependency_lock_create');SX.gh=msgOf(r);drawSettings()};
ACT.ghpublish=async el=>{if(!await ask('Bu bilgisayardaki kaynak değişiklikleri test edip ayrı bir dala yükleyeyim ve main için PR açayım mı? (main’e PR birleşince girer)'))return;el.disabled=true;SX.gh='Testler çalışıyor ve GitHub yayını hazırlanıyor…';if(settingsOpen())drawSettings();else toast(SX.gh);try{const r=await api('github_publish');SX.gh=msgOf(r);toast(r.msg,r.ok?'':'bad')}catch(e){SX.gh='✗ '+e.message;toast(e.message,'bad')}finally{await refresh();if(S.sset==='baglanti'||S.sset==='github')drawSettings()}};
ACT.ghpull=async el=>{if(!await ask('GitHub main sürümünü bu bilgisayara alayım mı? Yerel değişiklik varsa işlem güvenlik için duracak.'))return;el.disabled=true;SX.gh='GitHub main doğrulanıyor ve güvenli güncelleme hazırlanıyor…';if(settingsOpen())drawSettings();else toast(SX.gh);try{const r=await api('github_pull');SX.gh=msgOf(r);toast(r.msg,r.ok?'':'bad')}catch(e){SX.gh='✗ '+e.message;toast(e.message,'bad')}finally{await refresh();if(S.sset==='baglanti'||S.sset==='github')drawSettings()}};
ACT.upd=async()=>{const r=await tryApi('update_now');if(r){SX.gh=msgOf(r);toast(r.msg);if(S.sset==='baglanti'||S.sset==='github')drawSettings()}};
ACT.lbpick=el=>{SX.lb=el.dataset.v;SX.lbm='';drawSettings()};
ACT.lbsave=async el=>{el.disabled=true;SX.lbm='Deneniyor…';try{SX.lbm=msgOf(await api('local_backend_set',SX.lb||((S.snap||{}).llm||{}).local_backend||'ollama',$('#lburl').value,''));SX.lb=''}catch(e){SX.lbm='✗ '+e.message}sAfter(0)};
ACT.omsave=async el=>{el.disabled=true;try{SX.om=msgOf(await api('model_choice_save','ollama',$('#om').value))}catch(e){SX.om='✗ '+e.message}sAfter(0)};
ACT.gsopen=async el=>{const r=await tryApi('google_setup_open',el.dataset.v);SX.g=msgOf(r);drawSettings()};
ACT.gpick=()=>{const i=$('#upl');i.accept='.json,application/json';i.onchange=async()=>{const f=i.files[0];i.value='';if(!f)return;try{SX.g=await api('google_upload',await f.text())}catch(e){SX.g='✗ '+e.message}sAfter(0)};i.click()};
ACT.gconn=async()=>{SX.g='Bağlanılıyor… Tarayıcıda Google izin ekranı açılabilir.';drawSettings();const r=await tryApi('google_connect');SX.g=msgOf(r);sAfter(0)};
ACT.greset=async()=>{await tryApi('google_reset');SX.g='Bağlantı sıfırlandı.';sAfter(0)};
ACT.gprodopen=async()=>{const r=await tryApi('google_oauth_console');SX.g=msgOf(r);drawSettings()};
ACT.gprodok=async ()=>{if(!await ask('Google Cloud’da OAuth yayın durumunu gerçekten “In production” yaptın mı?'))return;const r=await tryApi('google_oauth_production',true);SX.g=msgOf(r);drawSettings()};
ACT.hoplace=el=>sAfter(api('handoff_place',el.dataset.v));
ACT.hoconn=async()=>{SX.ho='Tarayıcıda Google izin ekranı açılıyor…';drawSettings();SX.ho=msgOf(await tryApi('handoff_connect'));sAfter(0)};
ACT.vsave=async()=>{SX.v='Kaydediliyor…';try{await api('settings_save',{local_stt_enabled:$('#lstt').value==='1',local_stt_model:$('#lsttmodel').value,local_stt_beam:+$('#lsttbeam').value||5,assistant_name:$('#aname').value,wake_sensitivity:+$('#wsens').value,stt_fixes:$('#sfix').value,stt_words:$('#swords').value,input_device:$('#micdev').value,voice_mic_during_model_wait:$('#mmic').value==='1',voice_announce_results:$('#vres').value==='1'});SX.v='✓ Kaydedildi. Ses tanıma seçimini değiştirdiysen Jarvis’i yeniden başlat.'}catch(e){SX.v='✗ '+e.message}S.ui=null;await loadUi();drawSettings()};
ACT.pmode=el=>sAfter(api('privacy_set',{mode:el.dataset.k}));
ACT.ptog=el=>sAfter(api('privacy_set',{[el.dataset.k]:el.dataset.v==='1'}));
ACT.odata=()=>api('open_folder','data');
ACT.olog=()=>api('open_folder','log');
ACT.restart=async ()=>{if(await ask('Jarvis yeniden başlatılsın mı?'))api('restart')};
ACT.wset=async el=>{await tryApi('widget_set',el.dataset.v==='1');S.ui=null;await loadUi();drawSettings();toast('Kaydedildi.')};
ACT.hclear=async ()=>{if(await ask('Tüm konuşma geçmişi silinsin mi?')){await api('history_clear');S.hist=[];toast('Geçmiş temizlendi.')}};
function applyTheme(){const t=(S.ui||{}).nx_theme||'dark';const dark=t==='dark'||(t==='system'&&matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.dataset.theme=dark?'dark':'light'}

// ======================================================================= veri ve olaylar
async function refresh(){const oldUser=((S.snap||{}).user||{}).name;try{S.snap=await api('snapshot')}catch(e){return}
  if(oldUser&&oldUser!==((S.snap||{}).user||{}).name){S.filePreview=null;S.files=null;S.noteSelected=null;S.noteText='';S.noteTitle='';ACT.ntimageclear();document.querySelectorAll('.noteviewer').forEach(el=>el.click());S.hist=null;S.live=[];S.chat=[];S.day=null;S.since=0;S.waiting=false;S.sdoc=0;S.sans='';S.mathDraft='';S.mathAttachment='';S.mathResponse=null;S.studyPdfPage=null;S.studySelection=null;S.mathUploadBusy=false;S.slesson=null;S.sov=null;S.squiz=null;S.sres=null;S.smedia=null;S.quizBusy=false;S.mockBusy=false;S.studyLessonRequest=null;S.studyQuizRequest=null;S.studyMediaRequest=null;S.studyOverviewRequest=null;S.studyBusy=false;S._sovLoading=0;await loadHist();render()}
  if(!S.snap)return;S.orb=S.snap.orb||'idle';dockState();
  {const pk=JSON.stringify(((S.snap.study||{}).pending)||[]);if(S.page==='study'&&S._spk!==undefined&&pk!==S._spk){const was=S._spk;S._spk=pk;S.sov=null;render();const pd=S.snap.study.pending||[];if(pd.some(x=>x.state==='error'))toast('Bir kaynak eklenemedi; ayrıntı listede.','bad');else if(pd.length<JSON.parse(was).length)toast('Çalışma kaynağı eklendi.')}S._spk=pk;
   clearTimeout(S._spt);if(pk!=='[]'&&pk.includes('running'))S._spt=setTimeout(refresh,3000)}renderTop();if(S.page==='chat'){drawSide();drawDevelopment()}if(S.page==='home')updateHome();
  if(oldUser&&oldUser!==((S.snap||{}).user||{}).name&&S.page==='team')render()}
let rt=null;const refreshSoon=()=>{clearTimeout(rt);rt=setTimeout(refresh,150)};
function onEvent(m){
  const k=m.k;
  const owner=((S.snap||{}).user||{}).slug;
  if(m.user&&owner&&m.user!==owner){refreshSoon();return}
  if(m.mid&&((S.hist||[]).some(r=>r.id===m.mid)||S.live.some(r=>r.id===m.mid)))return;
  if(typeof taskSummaryEvent==='function')taskSummaryEvent(m);
  if(k==='action'){Promise.all([refresh(),loadUi()]).then(()=>{S.files=null;S.sc=null;S.sov=null;if(S.page!=='chat')render()});return}
  if(k==='reconcile'){loadHist().then(()=>{S.live=[];drawMsgs();if(S.page==='chat')drawConvs()});return}
  if(k==='user'||k==='assistant'){const ts=m.ts||Date.now()/1000;
    if(k==='user'){const i=S.live.findIndex(x=>x.mine&&x.role==='user'&&x.text===m.t);if(i>=0)S.live.splice(i,1)}
    S.live.push({id:m.mid,role:k,text:m.t,ts,src:m.x,rid:m.rid});S.live=S.live.slice(-300);if(k==='assistant')S.waiting=false;
    if(S.hist){const d=new Date(ts*1000),z=n=>String(n).padStart(2,'0');S.hist.push({id:m.mid,role:k,text:m.t,ts:`${ymd(d)} ${z(d.getHours())}:${z(d.getMinutes())}:${z(d.getSeconds())}`,source:m.x,rid:m.rid})}
    drawMsgs();if(S.page==='chat')drawConvs()}
  else if(k==='step'){onStep(m);return}
  else if(k==='system'){toast(String(m.t).slice(0,180));S.live.push({role:'system',text:m.t,ts:Date.now()/1000});S.waiting=false;drawMsgs()}
  else if(k==='state'){
    S.orb=m.t||'idle';dockState();speechStateEvent(S.orb);updateHomeStatus();
    $$('.mic').forEach(button=>button.classList.toggle('live',S.orb==='listening'));
  }
  else if(k==='speech'){speechEvent(m);return}
  else if(k==='share'){S.snap=S.snap||{};S.snap.mode=m.t||null;drawMiniPreview();if(S.page==='vision')render()}
  else if(k==='nav'){navTo(m.t);return}
  else if(k==='study_start'){const owner=((S.snap||{}).user||{}).name;S.stab='learn';go('study');loadStudy().then(()=>{if(S.page==='study'&&owner===((S.snap||{}).user||{}).name){render();ACT.studystart()}});return}
  else if(k==='study_media'){if(S.page!=='study'){S.stab='learn';go('study')}S.swin=1;S.swtab='wiki';setTimeout(()=>showMedia(m.t),S.page==='study'?0:400);return}
  else if(k==='quit'){window.JarvisHome?.destroy();document.body.innerHTML='<div style="display:grid;place-items:center;height:100vh;color:#7396ae;font-family:sans-serif">Jarvis kapandı. Bu pencereyi kapatabilirsin.</div>';return}
  refreshSoon();
}
function navTo(h){const[t,s]=String(h||'home').replace(/^#/,'').split(/[|/]/);if(t==='settings'&&['ai','baglanti'].includes(s)){S.sset=s;S.tool='aihub';go('tools');return}if(t==='settings'&&s)S.sset=s;if(t==='tools'){if(s==='kb')return go('files');S.tool=s||'';if(!s)S.sset='takvim'}go(t)}
function connect(){
  const es=new EventSource('/events');let loading=true,closed=false,buffer=[];
  es.onopen=async()=>{
    loading=true;await refresh();if(closed)return;const user=((S.snap||{}).user||{}).name;
    const rows=await tryApi('history','',1500);if(closed)return;
    if(rows&&user===((S.snap||{}).user||{}).name){S.hist=rows;S.live=S.live.filter(r=>r.mine);S.waiting=S.orb==='thinking'}
    loading=false;const pending=buffer;buffer=[];pending.forEach(onEvent);
    drawMsgs();if(S.page==='chat')drawConvs()
  };
  es.onmessage=ev=>{try{const m=JSON.parse(ev.data);if(loading)buffer.push(m);else onEvent(m)}catch(e){console.error(e)}};
  es.onerror=()=>{closed=true;es.close();setTimeout(connect,2500)};
}

// ======================================================================= açılış
(async function boot(){
  if(!NAV.some(([key])=>key===S.page))S.page='home';
  setInterval(tick,5000);
  if(location.hash.length<=1)render();
  await Promise.all([refresh(),loadUi()]);
  if(location.hash.length>1){navTo(location.hash);history.replaceState(null,'',location.pathname+location.search)}else render();
  connect();setInterval(refresh,15000);loadPcMute();addEventListener('focus',loadPcMute);
  loadFiles().then(()=>{if(['files','vision'].includes(S.page))render()});
})();

function localSttText(s){return !s.installed?'Önce faster-whisper paketini kur (docs/YEREL_SES.md).':s.preparing?'Model indiriliyor; biraz sonra durumu yenile.':s.error|| (s.ready?'Model hazır. Gizli/Yerel modda ses buluta gitmez.':'Model henüz indirilmedi. İndirme internet kullanır; ses kaydı göndermez.')}
ACT.lsttprepare=async()=>{const name=$('#lsttmodel').value;if(!await ask(name+' yerel ses modeli indirilsin mi? İnternet ve disk alanı kullanır.'))return;try{await api('settings_save',{local_stt_model:name});await api('local_stt_prepare',name);toast('Model hazırlanıyor; biraz sonra durumu yenile.');drawSettings()}catch(e){toast(e.message,'bad')}};
ACT.lsttrefresh=()=>drawSettings();
