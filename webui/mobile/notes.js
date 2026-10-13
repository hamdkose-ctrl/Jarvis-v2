// Public shell; note content lives only in this phone's per-user outbox, never in SW caches.
(()=>{
 const $=id=>document.getElementById(id),slug=name=>String(name||'').toLocaleLowerCase('tr').replace(/[çğıöşü]/g,c=>({'ç':'c','ğ':'g','ı':'i','ö':'o','ş':'s','ü':'u'}[c])).replace(/[^a-z0-9]/g,''),owner=()=>slug(localStorage.ju);
 let syncing=false;
 const key=u=>'jarvis_fieldnotes_'+u;
 function load(u){try{return JSON.parse(localStorage.getItem(key(u))||'[]')}catch(e){return []}}
 function put(u,rows){localStorage.setItem(key(u),JSON.stringify(rows))}
 function message(t){$('status').textContent=t}
 function render(){const u=owner();$('pending').textContent='';for(const note of load(u)){const el=document.createElement('div');el.className='note';el.textContent=note.text;const b=document.createElement('button');b.textContent='Aktarımı İptal Et';b.disabled=syncing;b.onclick=()=>{put(u,load(u).filter(r=>r.uid!==note.uid));render()};el.appendChild(b);$('pending').appendChild(el)}$('save').disabled=!u}
 async function call(url,options={},token=localStorage.jk){const r=await fetch(url,{...options,headers:{...options.headers,'X-Token':token||''}});if(!r.ok){const e=Error(r.status===401||r.status===403?'Yeni bağlantı QR’ını okut.':'PC bağlantısı yok.');e.status=r.status;throw e}return r.json()}
 async function sync(){if(syncing)return;const u=owner(),token=localStorage.jk;if(!u||!token){message('Önce PC’deki Telefon sayfasından kendi bağlantı QR’ını okut.');return}
  syncing=true;render();try{const mine=await call('/api/users',{},token);if(slug(mine.active)!==u)throw Error('Telefon profili ile bağlantı kullanıcısı farklı. Kendi QR’ını yeniden okut.');
   const rows=load(u).slice(0,10);const result=rows.length?await call('/api/notes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({notes:rows})},token):await call('/api/notes',{},token);
   if(owner()!==u||localStorage.jk!==token)return;
   if(result.user!==u)throw Error('Not profili doğrulanamadı.');
   const ack=new Set(result.ack||[]);put(u,load(u).filter(r=>!ack.has(r.uid)));
   $('saved').textContent='';for(const note of (result.notes||[]).slice().reverse()){const el=document.createElement('div');el.className='note';el.textContent=note.text;$('saved').appendChild(el)}
   message(mine.active+' · PC ile eşitlendi. '+load(u).length+' not bekliyor.');
  }catch(e){message(e.message+' Notların telefonda kayıtlı; bağlantı gelince aktarılacak.')}finally{syncing=false;render()}}
 $('save').onclick=()=>{const u=owner(),text=$('draft').value.trim();if(!u||!text)return;const uid=globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'_'+Math.random().toString(36).slice(2);try{put(u,[...load(u),{uid,text}]);$('draft').value='';message('Not telefona kaydedildi.');render();sync()}catch(e){message('Not kaydedilemedi; telefon depolamasını kontrol et.')}};
 $('sync').onclick=sync;addEventListener('online',sync);addEventListener('storage',render);render();sync();setInterval(sync,15000);
 if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
})();
