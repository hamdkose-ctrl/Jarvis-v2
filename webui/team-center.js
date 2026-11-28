/* Team view: existing engine journals, not simulated activity. */
'use strict';
(() => {
  let current=null, timer=null, generation=0;
  const labels={running:'Çalışıyor',queued:'Sırada',done:'Tamamlandı',failed:'Başarısız',blocked:'Engellendi',approval:'Onay bekliyor',question:'Yanıt bekliyor',paused:'Durakladı',review:'Kontrol gerekiyor',cancelled:'İptal edildi',incomplete:'Eksik',stopping:'İptal bekleniyor',unavailable:'Kullanılamıyor',interrupted:'Kesildi',pending:'Bekliyor'};
  const status=s=>labels[s]||s||'Bilinmiyor';
  const safeId=s=>String(s).replace(/[^a-zA-Z0-9_-]/g,'');
  function button(label, action, attrs=''){return `<button class="btn sm" type="button" data-team="${action}" ${attrs}>${label}</button>`}
  let selectedPerson=null,selectedJob=null;
  function controls(j,latestGoal){
    const attrs=`data-id="${safeId(j.id)}" data-kind="${safeId(j.kind)}"`,terminal=['done','cancelled'].includes(j.record_state||j.state),latest=j.kind==='task'||j.id===latestGoal?.id;
    let html=button('Kanıtları kontrol et','verify',attrs);
    if(latest)html+=button('Sohbette ayrıntılar','details',attrs);
    if(!terminal&&latest)html+=button('Görevi iptal et','stop',attrs);
    if(!terminal&&latest&&['paused','interrupted','failed','blocked','incomplete'].includes(j.state)&&!(j.kind==='goal'&&['blocked','failed','incomplete'].includes(j.state)))html+=button('Sürdür','continue',attrs);
    if(j.kind==='goal'&&j.state==='question'&&latest)html+=`<form class="team-answer-form" data-id="${safeId(j.id)}" data-control="${safeId(j.control)}"><label>Soruyu yanıtla<textarea name="answer" maxlength="2000" required></textarea></label><button class="btn" type="submit">Yanıtı ilet</button></form>`;
    if(j.state==='approval'&&latest)html+=`<form class="team-approval-form" data-id="${safeId(j.id)}" data-kind="${safeId(j.kind)}" data-control="${safeId(j.control)}" data-approval="${safeId(j.approval_id||'')}"><p class="team-warning">${esc(j.approval||'Somut işlem ayrıntılarını yukarıdaki görev kaydından incele.')}</p><label><input type="checkbox" name="approve" required> Görünen işlemi onaylıyorum</label><button class="btn" type="submit">Bu işlemi onayla</button></form>`;
    return html;
  }
  function renderPerson(host,data){
    const panel=host.querySelector('[data-team-person]'), member=data.members.find(row=>row.id===selectedPerson);
    panel.hidden=!member;
    if(!member)return;
    const entries=data.jobs.flatMap(j=>j.steps.filter(step=>step.specialist?.id===member.id).map(step=>({job:j,step})));
    panel.innerHTML=`<header class="team-head"><h2>${esc(member.name)}</h2>${button('Kapat','person-close')}</header>
      <p>${member.enabled===false?'Yeni atamalara kapalı.':'Yeni atamalara açık.'}</p>
      <p class="mut">Araçlar: ${member.tools.map(esc).join(', ')}</p>
      <ol class="team-steps">${entries.slice(0,16).map(({job,step})=>`<li>
        ${stateBadge(step.state)} <span>${esc(job.request||'Görev')}</span>
        <small>${esc(step.tool)}</small>${step.text?`<p>${esc(step.text)}</p>`:''}
      </li>`).join('')||'<li>Bu uzmana atanmış kayıtlı adım yok.</li>'}</ol>
      ${button('Uzmanı düzenle','edit-person',`data-id="${safeId(member.id)}"`)}`;
  }
  const jobKey=j=>j.kind+':'+j.id;
  const stateBadge=state=>`<span class="team-state" data-state="${safeId(state)}">${esc(status(state))}</span>`;
  function inspector(job,latestGoal){
    if(!job)return '<section class="card"><p class="team-empty">Ayrıntısını görmek için bir iş seç.</p></section>';
    const files=job.steps.flatMap(step=>(step.artifacts||[]).map(file=>{
      const canDownload=step.has_receipt&&(step.downloads||[]).includes(file);
      return `<div class="team-output"><span>${ic('file')} ${esc(file)}</span>${canDownload?button('İndir','artifact',`data-kind="${esc(job.kind)}" data-id="${esc(job.id)}" data-step="${esc(step.id)}" data-file="${esc(file)}"`):''}</div>`;
    }));
    return `<header class="team-hero">${stateBadge(job.state)}<h2>${esc(job.request||'Görev')}</h2></header>
      <section class="card team-jobbody" data-control="${esc(job.control||'')}">
        <h3>İş adımları</h3>
        ${job.question?`<p class="team-warning">${esc(job.question)}</p>`:''}
        <ol class="team-steps">${job.steps.map(step=>`<li>${stateBadge(step.state)}
          <div><b>${esc(step.tool||'İş adımı')}</b><small>${esc(step.specialist?.name||'Jarvis')}</small>
          ${step.text?`<p>${esc(step.text)}</p>`:''}</div></li>`).join('')||'<li>Henüz kayıtlı adım yok.</li>'}</ol>
        ${files.join('')}
        <div class="team-actions">${controls(job,latestGoal)}</div>
      </section>`;
  }
  let homePending=null,homeCache=null;
  const homeJobGroups=[
    {title:'Dikkat gerekiyor',states:['approval','question','blocked','pending','review','failed','incomplete','interrupted','unavailable']},
    {title:'Devam eden işler',states:['running','queued','stopping']},
    {title:'Tamamlanan işler',states:['done']},
    {title:'Diğer işler',states:[]}
  ];
  function owner(){return S.snap?.user?.slug||''}
  function refreshHome(host){
    const active=owner();
    if(!host||!active)return;
    const paint=(data)=>{
      if(!host.isConnected||data.owner!==active||active!==owner())return;
      const groups=homeJobGroups.map(group=>({...group,jobs:[]}));
      for(const job of data.jobs){
        const group=groups.find(group=>group.states.includes(job.state))||groups[groups.length-1];
        group.jobs.push(job);
      }
      let remaining=3;
      host.innerHTML=groups.map(group=>{
        const jobs=group.jobs.slice(0,remaining);
        if(!jobs.length)return '';
        remaining-=jobs.length;
        return `<section class="home-job-group"><h3>${group.title}</h3>${jobs.map(job=>`<button type="button" class="home-job" data-act="teamHome" data-key="${esc(jobKey(job))}">${stateBadge(job.state)}<span>${esc(job.request||'Görev')}</span>${ic('chev')}</button>`).join('')}</section>`;
      }).join('')||'<p class="mut">Henüz kayıtlı iş yok.</p>';
    };
    if(homeCache?.owner===active&&Date.now()-homeCache.at<4000){paint(homeCache.data);return}
    if(homePending?.owner!==active){
      const request={owner:active};
      request.promise=api('team_snapshot').finally(()=>{if(homePending===request)homePending=null});
      homePending=request;
    }
    homePending.promise.then(data=>{
      if(data.owner!==active||owner()!==active)return;
      homeCache={owner:active,data,at:Date.now()};
      paint(data);
    }).catch(()=>{if(host.isConnected&&owner()===active)host.innerHTML='<p class="mut">İş durumu alınamadı.</p>'});
  }
  window.JarvisTeam={refreshHome};
  ACT.teamHome=el=>{selectedJob=el.dataset.key;go('team')};

  function editPerson(host,id){
    const member=current?.members.find(m=>m.id===id),form=host.querySelector('.team-member-form');
    form.dataset.revision=current?.revision||'';form.elements.identity.value=member?.id||'';form.elements.name.value=member?.name||'';form.elements.tags.value=(member?.tags||[]).join(', ');form.elements.enabled.checked=member?.enabled!==false;
    form.querySelectorAll('[name=tools] input').forEach(i=>i.checked=!!member?.tools.includes(i.value));
    form.closest('details').open=true;form.elements.name.focus();
  }
  function capabilityStatus(data){
    const watches=data.source_watches||[],events=data.source_events||[],refs=data.capability_candidates||[];
    const contracts=data.specialist_contracts?.specialists||[];
    return `<details class="team-config"><summary>Kaynak takipleri (${watches.length})</summary><p>İlk tarama mevcut içerikleri baz alır. Sonraki değişiklikler yalnız Jarvis açıkken bildirilir.</p>${watches.map(w=>`<article class="team-tool"><b>${esc(w.label)}</b><p>${esc(w.url)}</p><small>${w.paused?'Duraklatıldı':'Etkin'} · ${esc(w.terms.join(', '))} · ${esc(w.interval)} saniye</small>${w.error?`<p>Son kontrol: ${esc(w.error)}</p>`:''}</article>`).join('')||'<p>Kaynak takibi kaydedilmedi.</p>'}${events.slice(0,10).map(e=>`<article class="team-tool"><b>${esc(e.title||'Kaynak değişikliği')}</b><p>${esc(e.quote||'')}</p><small>${esc(e.url||'')} · Kaynak alıntısı; kapsamı ayrıca değerlendir.</small></article>`).join('')}</details>
      <details class="team-config"><summary>Servis adayları (${refs.length})</summary><p>Keşfedilmesi bağlantı, ücretsiz kullanım veya hesap izni kanıtı değildir.</p>${refs.map(r=>`<article class="team-tool"><b>${esc(r.name)}</b><p>${esc(r.url)}</p><small>${r.binding?'Sabit GET adaptörü kaydedildi; çalışırlık işlemde denetlenir':'Bağlantı kurulmadı'}</small></article>`).join('')||'<p>Servis adayı kaydedilmedi.</p>'}</details>
      <details class="team-config"><summary>Uzmanların gerçek teslim kapsamı</summary>${contracts.map(m=>`<article class="team-tool"><b>${esc(m.name)}</b>${m.tools.map(t=>`<p>${esc(t.tool)}: ${esc(t.deliverable)}</p><small>${esc(t.scope)}</small>`).join('')}</article>`).join('')}</details>`;
  }
  function paintJobs(host,data){
    const jobs=data.jobs||[], latestGoal=jobs.find(row=>row.kind==='goal');
    const selected=jobs.find(row=>jobKey(row)===selectedJob)||jobs[0];
    selectedJob=selected?jobKey(selected):null;
    const jobHost=host.querySelector('[data-team-jobs]');
    const previous=host.querySelector('.team-jobbody');
    const oldKey=jobHost.dataset.selected, oldControl=previous?.dataset.control;
    const same=selected&&oldKey===selectedJob&&oldControl===(selected.control||'');
    const draft=same?previous.querySelector('[name=answer]')?.value||'':'';
    const approval=same&&!!previous.querySelector('[name=approve]')?.checked;
    const focus=same&&previous.contains(document.activeElement)?document.activeElement.name:'';
    const start=focus==='answer'?document.activeElement.selectionStart:null;
    const end=focus==='answer'?document.activeElement.selectionEnd:null;
    const listFocused=jobHost.contains(document.activeElement)?document.activeElement.dataset.key:null;
    jobHost.dataset.selected=selectedJob||'';
    jobHost.innerHTML=jobs.length?jobs.map(job=>`<button type="button" class="team-job-select" data-team="select" data-key="${esc(jobKey(job))}" aria-pressed="${job===selected}">${stateBadge(job.state)}<strong>${esc(job.request||'Görev')}</strong></button>`).join(''):'<p class="team-empty">Henüz kayıtlı iş yok.</p>';
    const panel=host.querySelector('[data-team-inspector]');
    panel.innerHTML=inspector(selected,latestGoal);
    if(same){
      const answer=panel.querySelector('[name=answer]'),checkbox=panel.querySelector('[name=approve]');
      if(answer)answer.value=draft;
      if(checkbox)checkbox.checked=approval;
      if(focus==='answer'&&answer){answer.focus();answer.setSelectionRange(start,end);}
      if(focus==='approve'&&checkbox)checkbox.focus();
    }
    const focusKey=listFocused&&jobs.some(job=>jobKey(job)===listFocused)?listFocused:null;
    if(focusKey)[...jobHost.querySelectorAll('button')].find(button=>button.dataset.key===focusKey)?.focus();
  }
  function renderData(host,data){
    const jobs=data.jobs||[], live=jobs.flatMap(job=>job.steps||[]).filter(step=>step.state==='running');
    host.querySelector('[data-team-status]').textContent=`${live.length} çalışan adım · ${jobs.filter(j=>['approval','question','review','blocked','failed','incomplete'].includes(j.state)).length} ilgilenilmesi gereken iş`;
    host.querySelector('[data-team-members]').innerHTML=data.members.map(m=>{
      const assigned=live.filter(step=>step.specialist?.id===m.id);
      return `<button type="button" data-team="person" data-id="${safeId(m.id)}" class="team-person ${assigned.length?'is-working':''}"><b>${esc(m.name)}</b><p>${assigned.length?assigned.map(step=>esc(step.tool)+' · '+esc(step.id)).join(', '):m.enabled===false?'Kapalı':'Bekliyor'}</p></button>`;
    }).join('');
    paintJobs(host,data);
    host.querySelector('[data-team-queue]').innerHTML=data.queue.length?data.queue.map(q=>`<article class="team-queued"><div><b>${esc(q.instruction||'Zamanlanmış iş')}</b><p>${esc(status(q.state))} · ${q.repeat_seconds?'Her '+q.repeat_seconds+' saniye':'Tek sefer'} · ${new Date(q.due*1000).toLocaleString('tr-TR')}</p>${q.error?`<p>${esc(q.error)}</p>`:''}</div><div class="team-actions">${['queued','paused'].includes(q.state)?button(q.state==='paused'?'Takibi sürdür':'Duraklat','queue-state',`data-id="${safeId(q.id)}" data-operation="${q.state==='paused'?'resume':'pause'}"`):''}${['queued','paused'].includes(q.state)?`<label>Sıklık<select data-team-interval="${safeId(q.id)}">${[0,300,3600,86400,...([0,300,3600,86400].includes(q.repeat_seconds)?[]:[q.repeat_seconds])].map(n=>`<option value="${n}" ${n===q.repeat_seconds?'selected':''}>${n?n+' saniye':'Tek sefer'}</option>`).join('')}</select></label>`:''}${['queued','running','blocked','paused'].includes(q.state)?button('Takibi iptal et','cancel',`data-id="${safeId(q.id)}"`):''}</div></article>`).join(''):'<p class="mut">Düzenli takip tanımlanmadı. Jarvis kapalıyken işler çalışmaz.</p>';
    renderPerson(host,data);
    host.querySelector('[data-team-notice]').textContent=(data.warnings||[]).join(' ');
    host.querySelector('[data-team-tools]').innerHTML=capabilityStatus(data)+data.capabilities.map(t=>`<div class="team-tool"><b>${esc(t.id)}</b><p>${esc(t.description)}</p><small>${esc(t.scope)}</small></div>`).join('');
    const tools=host.querySelector('[name=tools]');if(!tools.querySelector('input'))tools.innerHTML='<legend>Kullanacağı mevcut araçlar</legend>'+data.capabilities.map(t=>`<label><input type="checkbox" value="${safeId(t.id)}"> ${esc(t.id)}</label>`).join('');
    host.querySelector('[data-team-limits]').textContent=data.limits.join(' ');
  }
  async function downloadArtifact(button){
    const before=owner();
    const result=await api('team_artifact',button.dataset.kind,button.dataset.id,button.dataset.step,button.dataset.file);
    if(!before||before!==owner()||result.owner!==before)return;
    const bytes=Uint8Array.from(atob(result.content),letter=>letter.charCodeAt(0));
    const url=URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'}));
    const link=document.createElement('a');
    link.href=url;link.download=result.name;
    document.body.appendChild(link);
    link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function load(host, id){
    if(!host.isConnected||id!==generation||host._teamLoading)return;
    const before=owner();
    host._teamLoading=true;
    try{const data=await api('team_snapshot');if(!host.isConnected||id!==generation||data.owner!==before||before!==owner())return;if(current&&current.owner!==data.owner){selectedPerson=null;selectedJob=null;}current=data;renderData(host,data);host.querySelector('[data-team-notice]').classList.remove('is-error')}
    catch(e){if(host.isConnected&&id===generation){const n=host.querySelector('[data-team-notice]');n.textContent='Ekip durumu alınamadı: '+e.message;n.classList.add('is-error');host.querySelector('[data-team-status]').textContent='Durum güncellenemedi; görünen kayıtlar eski olabilir.'}}
    finally{host._teamLoading=false;if(host.isConnected&&id===generation&&!document.hidden)timer=setTimeout(()=>load(host,id),5000)}
  }
  ACT.teamNavigate=key=>{selectedJob=key.replace('-',':');go('team')};
  PAGES.team=pg=>{
    clearTimeout(timer);generation++;current=null;selectedPerson=null;const id=generation;
    pg.innerHTML=`<section class="team-center">
      <header class="team-head"><div><h1>Ekip Merkezi</h1><p>İş adımlarını, bekleyen onayları ve teslimleri izle.</p></div>${button('Yenile','refresh')}</header>
      <p data-team-status class="mut">İşler yükleniyor…</p><p data-team-notice class="team-notice" role="status"></p>
      <div class="team-columns">
        <section class="card"><div class="ch"><h2>İşler</h2></div><div data-team-jobs></div></section>
        <section class="team-inspector" data-team-inspector aria-label="Seçili iş"></section>
      </div>
      <div class="team-extras">
        <details class="team-config"><summary>Yeni hedef</summary><form class="team-request"><label for="team-request">Jarvis’e hedef ver</label><div><textarea id="team-request" name="request" required maxlength="20000" placeholder="Yapılacak işi ve beklediğin sonucu anlat…"></textarea><button class="btn pri" type="submit">Jarvis’e ver</button></div><p class="mut" data-team-send-status role="status"></p></form></details>
        <details class="team-config"><summary>Uzmanlar</summary><div class="team-members" data-team-members></div><section class="card" data-team-person hidden></section>${button('Yeni uzman','new-person')}</details>
        <details class="team-config"><summary>Uzman ayarları</summary><form class="team-member-form"><input type="hidden" name="identity"><label>Uzman adı<input name="name" required maxlength="80" placeholder="Örneğin lojistik takibi"></label><label>Anahtar sözcükler<input name="tags" maxlength="600" placeholder="lojistik, kargo, teslimat"></label><fieldset name="tools"><legend>Kullanacağı mevcut araçlar</legend></fieldset><label class="team-enabled"><input type="checkbox" name="enabled" checked> Yeni atamalara açık</label><div class="team-actions"><button class="btn" type="submit">Uzmanı kaydet</button>${button('Yeni uzman','new-person')}</div><p>Bu seçim hesap bağlantısı veya yeni işlem izni sağlamaz.</p></form></details>
        <details class="team-config"><summary>Zamanlanan işler</summary><div data-team-queue></div><form class="team-schedule-form"><label>Kaynak web adresi<input type="url" name="url" required placeholder="https://…"></label><label>Takip edilecek konu<input name="instruction" required maxlength="2000" placeholder="Bu kaynaktaki gelişmeleri kaynak göstererek raporla"></label><label>Tekrar sıklığı<select name="interval"><option value="0">Bir kez şimdi</option><option value="300">5 dakika</option><option value="3600">Saatlik</option><option value="86400">Günlük</option></select></label><button class="btn" type="submit">Takibi kaydet</button><p>Her çalışma seçili modelle kaynak araştırması ve rapor üretir; kota tüketebilir. Yalnız Jarvis açıkken çalışır.</p></form></details>
        <details class="team-config"><summary>Araçlar ve kaynak takipleri</summary><div data-team-tools></div><p data-team-limits class="mut"></p></details>
      </div></section>`;
    const host=pg.querySelector('.team-center');
    host.addEventListener('click',async e=>{
      const b=e.target.closest('[data-team]');if(!b)return;b.disabled=true;
      try{const action=b.dataset.team;if(action==='refresh'){clearTimeout(timer);await load(host,id)}
        else if(action==='select'&&current){selectedJob=b.dataset.key;paintJobs(host,current);[...host.querySelectorAll('.team-job-select')].find(el=>el.dataset.key===selectedJob)?.focus()}
        else if(action==='artifact'){await downloadArtifact(b)}
        else if(action==='person'){selectedPerson=b.dataset.id;if(current)renderPerson(host,current)}
        else if(action==='person-close'){selectedPerson=null;if(current)renderPerson(host,current)}
        else if(action==='edit-person'){editPerson(host,b.dataset.id)}
        else if(action==='new-person'){editPerson(host,null)}
        else if(action==='queue-state'){await api('team_queue_edit',b.dataset.id,b.dataset.operation,null);clearTimeout(timer);await load(host,id)}
        else if(action==='stop'||action==='continue'){const j=current?.jobs.find(j=>j.id===b.dataset.id&&j.kind===b.dataset.kind);if(!j)throw new Error('Görev kaydı yüklenmeli.');const message=await api('team_control',j.kind,j.id,action==='stop'?'cancel':'resume',j.control||'');toast(message);clearTimeout(timer);await load(host,id)}
        else if(action==='cancel'){await api('team_queue_cancel',b.dataset.id);clearTimeout(timer);await load(host,id)}
        else if(action==='verify'){const r=await api('team_verify',b.dataset.kind,b.dataset.id);toast((r.ok?'':'Kontrol tamamlanamadı. ')+r.message+(r.failed?.length?' Geçersiz adımlar: '+r.failed.join(', '):''),r.ok?'good':'bad')}
        else if(action==='details'){say(b.dataset.kind==='goal'?'hedef durumu':'görev durumu '+b.dataset.id)}

      }catch(err){toast(err.message,'bad')}finally{b.disabled=false}
    });
    const submit=(selector,fn)=>host.querySelector(selector).addEventListener('submit',async e=>{e.preventDefault();const f=e.currentTarget,b=f.querySelector('[type=submit]');if(b.disabled)return;b.disabled=true;try{await fn(f)}catch(err){toast(err.message,'bad')}finally{b.disabled=false}});
    submit('.team-request',async f=>{const input=f.elements.request,text=input.value.trim();if(!text)return;const accepted=await api('send','Hedef: '+text,globalThis.crypto?.randomUUID?.()||Date.now().toString(36));if(accepted===false)throw new Error('Jarvis isteği kabul etmedi.');input.value='';host.querySelector('[data-team-send-status]').textContent='Hedef Jarvis’e iletildi; motor kaydettiğinde adımlar burada görünecek.';clearTimeout(timer);await load(host,id)});
    host.querySelector('.team-member-form').addEventListener('input',e=>{const f=e.currentTarget;if(!f.dataset.revision)f.dataset.revision=current?.revision||'';});
    submit('.team-member-form',async f=>{if(!current)throw new Error('Önce ekip kaydı yüklenmeli.');const tools=[...f.querySelectorAll('[name=tools] input:checked')].map(x=>x.value);if(!tools.length)throw new Error('En az bir araç seç.');const member={id:f.elements.identity.value||'expert-'+Date.now().toString(36),name:f.elements.name.value.trim(),tags:f.elements.tags.value.split(',').map(x=>x.trim()).filter(Boolean),tools,enabled:f.elements.enabled.checked};const entries=current.members.some(m=>m.id===member.id)?current.members.map(m=>m.id===member.id?member:m):[...current.members,member];await api('team_save',entries,f.dataset.revision||current.revision);f.reset();delete f.dataset.revision;clearTimeout(timer);await load(host,id);toast('Uzman kaydedildi.')});
    host.addEventListener('change',async e=>{const identity=e.target.dataset.teamInterval;if(!identity)return;try{await api('team_queue_edit',identity,'interval',Number(e.target.value));toast('Takip sıklığı kaydedildi.');clearTimeout(timer);await load(host,id)}catch(err){toast(err.message,'bad')}});
    host.addEventListener('submit',async e=>{const f=e.target;if(!f.matches('.team-answer-form,.team-approval-form'))return;e.preventDefault();const b=f.querySelector('[type=submit]');if(b.disabled)return;b.disabled=true;try{const j=current?.jobs.find(j=>j.id===f.dataset.id&&(!f.dataset.kind||j.kind===f.dataset.kind));if(!j)throw new Error('Görev değişmiş.');const message=await api('team_control',j.kind,j.id,f.matches('.team-answer-form')?'answer':'approve',f.dataset.control,f.elements.answer?.value||'',f.dataset.approval||'');toast(message);clearTimeout(timer);await load(host,id)}catch(err){toast(err.message,'bad')}finally{b.disabled=false}});
    submit('.team-schedule-form',async f=>{const instruction=f.elements.instruction.value.trim(),url=f.elements.url.value.trim();const tasks=[{id:'source',agent:'research',input:{url,question:instruction}},{id:'report',agent:'writer',depends:['source'],input:{instruction}},{id:'check',agent:'verify',depends:['source','report'],input:{}}];await api('team_schedule',tasks,instruction,0,Number(f.elements.interval.value));f.reset();clearTimeout(timer);await load(host,id);toast('Takip kuyruğa kaydedildi.')});
    load(host,id);
  };
  if(S.page==='team'&&typeof render==='function'&&!document.querySelector('.team-center'))render();
  if(S.page==='home')refreshHome(document.getElementById('home-jobs'));
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&S.page==='team'){const host=document.querySelector('.team-center');if(host){clearTimeout(timer);load(host,generation)}}});
})();
