/* Onaylanan çalışma yüzeyi; mevcut API, kullanıcı ve ses yollarını kullanır. */
(function(){'use strict';
const chat=PAGES.chat,study=PAGES.study,oldAtt=drawAtt,oldDock=drawDock;
function nav(pg){const el=document.createElement('nav');el.className='workspace-nav';el.setAttribute('aria-label','Jarvis sayfaları');el.innerHTML=[['home','Ana Sayfa'],['chat','Sohbet'],['study','Çalışma'],['menu','Menü']].map(([k,t])=>`<button data-go="${k}" class="${S.page===k?'on':''}">${t}</button>`).join('');pg.prepend(el)}
function owner(){return S.snap?.user?.slug||S.snap?.user?.name||''}
function drawer(){return document.querySelector('.unified-files')}
async function drawFileDrawer(){const box=drawer();if(!box)return;const who=owner();box.innerHTML='<div class="ch"><b>Dosyalarım</b><button data-act="filesclose" aria-label="Dosyalar panelini kapat">×</button></div><p class="mut">Dosyalar yükleniyor…</p>';const result=await tryApi('files_list',false);if(who!==owner()||box!==drawer())return;S.files=result||{files:[],counts:{}};
const fs=(S.files?.files||[]).filter(f=>!S.fq||f.name.toLocaleLowerCase('tr').includes(S.fq.toLocaleLowerCase('tr'))).slice(0,100);
box.innerHTML=`<div class="ch"><b>Dosyalarım</b><button data-act="filesclose" aria-label="Dosyalar panelini kapat">×</button></div><input class="unified-search" placeholder="Dosyalarda ara…" value="${esc(S.fq||'')}" aria-label="Dosyalarda ara"><div class="unified-file-items">${fs.map(f=>`<div class="unified-file"><span class="fi ${esc(f.cat)}">${esc(f.ext.toUpperCase().slice(0,3))}</span><div><b>${esc(f.name)}</b><small>${fmtSize(f.size)}</small></div><button data-act="fileattach" data-p="${esc(f.path)}" data-n="${esc(f.name)}" title="Sohbete ekle">${ic('plus')}</button><button data-act="fmenu" data-p="${esc(f.path)}" aria-label="Dosya işlemleri">•••</button></div>`).join('')||'<p class="mut">Dosya bulunamadı.</p>'}</div><button class="btn" data-act="attach">${ic('plus')} Dosya ekle</button><button class="btn" data-act="fupdir">Klasör ekle</button><button class="btn" data-act="fdir">Klasörde aç</button>`;
box.querySelector('input').oninput=e=>{S.fq=e.target.value;const v=S.fq;clearTimeout(S.fileSearchTimer);S.fileSearchTimer=setTimeout(()=>{if(S.fq===v&&drawer()===box)drawFileDrawer()},250)};
}
function showDrawer(){let box=drawer();if(!box){box=document.createElement('aside');box.className='unified-files';box.setAttribute('aria-label','Dosyalarım');document.querySelector('.chatc')?.append(box)}drawFileDrawer()}
ACT.filesopen=()=>{S.fileDrawer=true;showDrawer()};ACT.filesclose=()=>{S.fileDrawer=false;drawer()?.remove()};
ACT.fileattach=el=>{if(atts().length+(S.attPending||0)>=MAX_ATT)return toast(`En fazla ${MAX_ATT} dosya ekleyebilirsin.`);if(!atts().some(a=>a.path===el.dataset.p))S.att=[...atts(),{path:el.dataset.p,name:el.dataset.n}];drawAtt();$('.ask input')?.focus()};
PAGES.chat=pg=>{chat(pg);nav(pg);pg.classList.add('unified-chat');const h=document.createElement('div');h.className='unified-chat-tools';h.innerHTML='<span>Sohbet ve dosyalar</span><button class="btn sm" data-act="filesopen">'+ic('folder')+' Dosyalarım</button>';pg.querySelector('.chatc')?.prepend(h);if(S.fileDrawer)showDrawer()};
PAGES.files=pg=>{S.page='chat';S.fileDrawer=true;PAGES.chat(pg)};
function attachedActions(){const host=document.querySelector('.attachment-actions');if(!host)return;const a=atts();if(!a.length){host.innerHTML='';return}const ext=a[0].name.split('.').pop().toLowerCase(),cat=/png|jpg|jpeg|webp|gif/.test(ext)?'image':/xls|xlsx|csv/.test(ext)?'excel':/pdf/.test(ext)?'pdf':/doc|docx|txt/.test(ext)?'word':'other';const acts=a.length>1?[['ozet','Birlikte özetle'],['analiz','Karşılaştır']]: (FACTS[cat]||FACTS.other).slice(0,3);
host.innerHTML='<span>Ekli dosya için</span>'+acts.map(([k,t])=>`<button class="btn sm" data-act="attachmentaction" data-k="${esc(k)}">${esc(t)}</button>`).join('')};
ACT.attachmentaction=el=>{const prompts={ozet:'Özetle',analiz:atts().length>1?'Dosyaları karşılaştır':'İçeriği analiz et',excel:'Tabloları Excel dosyasına dönüştür',cevir_tr:'Türkçeye çevir',metin:'Görseldeki metni çıkar',gorsel:'Görseli analiz et'};const input=$('.ask input');if(input){input.value=prompts[el.dataset.k]||'İçeriği analiz et';input.focus()}};
drawAtt=function(){oldAtt();attachedActions()};
drawDock=function(){oldDock();const d=$('#dock');if(['chat','home'].includes(S.page)&&d&&!d.querySelector('.attachment-actions')){const h=document.createElement('div');h.className='attachment-actions';d.prepend(h);attachedActions()}if(S.page==='home')d?.querySelector('input')?.setAttribute('placeholder','Yaz veya konuş…')};
PAGES.study=pg=>{study(pg);nav(pg);pg.classList.add('study-desk');const tabs=pg.querySelector('.study-tabs');if(tabs){const shell=document.createElement('details');shell.className='desk-sections';shell.innerHTML='<summary>Çalışmalarım</summary>';tabs.before(shell);shell.append(tabs)}const modes=pg.querySelector('.study-toolbar');if(modes){const shell=document.createElement('details');shell.className='desk-modes';shell.innerHTML='<summary>Çalışma türü</summary>';modes.before(shell);shell.append(modes)}
const rail=document.createElement('div');rail.className='desk-rail';rail.innerHTML=`<button class="btn" data-act="deskresources">${ic('folder')} Kaynaklar</button><button class="btn" data-act="desknotes">${ic('file')} Notlar</button><button class="btn" data-act="deskhistory">${ic('clock')} Geçmiş</button><button class="btn" data-act="deskanswer">${ic('spark')} Anlatım</button>`;pg.prepend(rail);
const grid=pg.querySelector('.study-split');if(grid){grid.classList.add('desk-canvas');const lesson=grid.querySelector('.study-lesson');lesson?.classList.add('desk-explanation');const head=lesson?.querySelector('.ch');if(head)head.insertAdjacentHTML('beforeend','<button data-act="deskanswer" aria-label="Anlatımı katla">−</button>');grid.classList.toggle('answer-collapsed',!!S.deskAnswerClosed);const preview=grid.querySelector('#study-preview');if(preview)preview.addEventListener('pointerup',e=>{if(innerWidth<951||!lesson)return;const r=grid.getBoundingClientRect();lesson.style.top=Math.max(100,Math.min(r.height-lesson.offsetHeight-20,e.clientY-r.top+20))+'px';S.deskAnswerClosed=false;grid.classList.remove('answer-collapsed')});const selector=pg.querySelector('#study-selection-button');if(selector)selector.addEventListener('click',()=>{S.deskAnswerClosed=false;grid.classList.remove('answer-collapsed')});}
};
ACT.deskanswer=()=>{S.deskAnswerClosed=!S.deskAnswerClosed;document.querySelector('.desk-canvas')?.classList.toggle('answer-collapsed',S.deskAnswerClosed)};
ACT.deskresources=()=>{S.stab='resources';render()};
function deskDrawer(title,body){const pg=document.querySelector('.p-study');if(!pg)return;pg.querySelector('.desk-drawer')?.remove();const el=document.createElement('aside');el.className='desk-drawer';el.innerHTML=`<div class="ch"><b>${title}</b><button data-act="deskclose" aria-label="Paneli kapat">×</button></div>${body}`;pg.append(el)}
ACT.deskclose=()=>document.querySelector('.desk-drawer')?.remove();
ACT.deskhistory=()=>{const rows=S.snap?.study?.progress||[];deskDrawer('Geçmiş',rows.slice().reverse().slice(0,30).map(x=>`<div class="srow"><div><b>${esc(x.q||'Çalışma')}</b><small>${esc(x.ts||'')}</small></div></div>`).join('')||'<p class="mut">Henüz çalışma kaydı yok.</p>')};
// Notlar mevcut not hizmeti üzerinden açılır; yeni kişisel veri deposu oluşturulmaz.
ACT.desknotes=()=>{const notes=S.snap?.notes||[];deskDrawer('Notlar',`<input id="desk-note-title" placeholder="Not başlığı" maxlength="120"><textarea id="desk-note-text" placeholder="Çalışma notunu yaz…"></textarea><button class="btn pri" data-act="desknoteadd">Kaydet</button>${notes.map(n=>`<details class="desk-note"><summary>${esc(n.title||'Not')}</summary><p>${esc(n.text||'')}</p></details>`).join('')}`)};
ACT.desknoteadd=async()=>{const who=owner(),text=document.querySelector('#desk-note-text')?.value.trim(),title=document.querySelector('#desk-note-title')?.value.trim();if(!text)return toast('Önce notunu yaz.');await api('note_add',text,'',title);if(owner()!==who)return;await refresh();if(owner()===who&&S.page==='study')ACT.desknotes()};
document.addEventListener('keydown',e=>{if(e.key==='Escape'){ACT.filesclose();ACT.deskclose()}});

const baseAiPage=aiPage;
const localModelView={key:'',at:0,data:null,busy:false};
function localModelKey(sn){const l=sn?.llm||{};return [sn?.user?.slug||sn?.user?.name||'',l.local_backend||'ollama',l.local_model||''].join('|')}
function requestLocalModelStatus(sn){
  const l=sn?.llm||{};if((l.local_backend||'ollama')!=='ollama')return;
  const key=localModelKey(sn),now=Date.now();
  if(localModelView.key!==key){localModelView.key=key;localModelView.data=null;localModelView.at=0}
  if(localModelView.busy||(localModelView.data&&now-localModelView.at<8000))return;
  localModelView.busy=true;
  api('llm_status').then(st=>{if(localModelView.key===key){localModelView.data=st||{};localModelView.at=Date.now()}}).catch(()=>{}).finally(()=>{localModelView.busy=false;if(S.snap&&localModelKey(S.snap)===key)render()});
}
function localModelPanel(panel,sn){
  const l=sn?.llm||{};if((l.local_backend||'ollama')!=='ollama')return panel;
  requestLocalModelStatus(sn);
  const key=localModelKey(sn),st=localModelView.key===key?localModelView.data:null;if(!st)return panel;
  const pref=String(st.local_model_preference||l.local_model||''),effective=String(st.local_effective_model||'');
  const stale=st.local_model_stale===true,noActive=st.local_models_checked===true&&!effective;
  if(!stale&&!noActive)return panel;
  const savedLabel=pref||'Kayıtlı tercih yok',activeLabel=effective||'Kurulu model yok';
  const warning=stale?(st.local_model_warning||`Kayıtlı model kurulu değil; otomatik olarak ${effective} kullanılıyor.`):'Kurulu ve etkin bir Ollama modeli bulunamadı.';
  const renamed=panel.replace('Yerel model · ','Kayıtlı tercih · ');
  return renamed+sbox('cpu','Model kullanımı','Kayıtlı tercih ile gerçekten kullanılan runtime modeli birbirinden ayrıdır.',
    srow('file','Kayıtlı tercih',esc(savedLabel),'')+srow('spark','Aktif model',esc(activeLabel),'')+pad18(`<span class="mut">${esc(warning)}</span>`));
}
aiPage=function(sn,panels,extra=''){const next={...panels};if(next.ollama)next.ollama=localModelPanel(next.ollama,sn);return baseAiPage(sn,next,extra)};
})();
