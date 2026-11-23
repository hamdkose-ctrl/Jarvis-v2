'use strict';
(() => {
  const markup = () => `  <header class="topbar">
    <strong class="brand"><span class="brand-mark" aria-hidden="true"></span>Jarvis</strong>
    <button class="btn" data-home-action="theme" aria-haspopup="dialog"><span class="theme-current-swatch" aria-hidden="true"></span>Tema</button>
  </header>

  <div class="layout">
    <aside class="feed" aria-label="Uydu akışı ve gündem">
      <h2 class="feed-heading">● Uydu Bağlantısı</h2>
      <section class="map-module">
        <header class="map-head"><h3>● Uydu Akışı</h3><button class="btn square" id="map-reset" type="button" aria-label="Haritayı sıfırla">⟳</button><button class="btn alert" id="map-expand" type="button">⤢ Büyüt</button></header>
        <div class="map-window">
          <div class="map-page"><span>Ana</span></div>
          <div class="map-toolbar">
            <button class="btn" id="map-hide" type="button" aria-expanded="true">Haritayı Gizle</button>
            <button class="btn" type="button" data-map-mode="2d" aria-pressed="true">2B</button>
            <button class="btn" type="button" data-map-mode="3d" aria-pressed="false">3B</button>
          </div>
          <div class="map-content" id="map-content">
            <div class="map-filters" role="group" aria-label="Harita filtresi"><button type="button" class="btn" data-filter="all" aria-pressed="true">Tümü</button><button type="button" class="btn" data-filter="economy" aria-pressed="false">Ekonomi</button><button type="button" class="btn" data-filter="technology" aria-pressed="false">Teknoloji</button></div>
            <div class="map-canvas"><canvas id="event-map" width="420" height="500" aria-label="Dünya haritası"></canvas><div class="map-zoom"><button class="btn" id="map-in" type="button" aria-label="Yakınlaştır">+</button><button class="btn" id="map-out" type="button" aria-label="Uzaklaştır">−</button></div></div>
          </div>
          <nav class="map-nav" aria-label="Uydu akışı seçenekleri">
            <button type="button" data-feed="today"><b>◉</b>Bugün</button>
            <button type="button" data-feed="map"><b>◇</b>Harita</button>
            <button type="button" data-feed="search"><b>⌕</b>Ara</button>
            <button type="button" data-feed="alerts"><b>△</b>Uyarılar</button>
            <button type="button" data-feed="more"><b>•••</b>Diğer</button>
          </nav>
        </div>
      </section>
      <section class="news"><header><h2>● Bugünün Gündemi</h2><button class="btn square" type="button" id="news-reset" aria-label="Bugünün haberlerini sor">⟳</button></header><ol id="news-list"></ol><p id="news-empty" class="muted" hidden>Bugün için takvim kaydı yok.</p></section>
    </aside>

    <section class="center" aria-label="Çekirdek ve ekip">
      <div class="core-area">
        <canvas id="core-links" aria-hidden="true"></canvas>
        <nav class="core-buttons" aria-label="Çekirdek araçları">
          <button class="core-option" type="button" data-home-tool="memory" style="--trace:#00bad9"><span aria-hidden="true">♧</span> Hafıza</button>
          <button class="core-option" type="button" data-home-tool="skills" style="--trace:#1fd36b"><span aria-hidden="true">▣</span> Yetenekler</button>
          <button class="core-option" type="button" data-home-tool="character" style="--trace:#ff503d"><span aria-hidden="true">◇</span> Karakter</button>
          <button class="core-option" type="button" data-home-tool="settings" style="--trace:#a4b5c9"><span aria-hidden="true">⚙</span> Ayarlar</button>
        </nav>
        <section class="reactor" aria-label="Jarvis çekirdeği">
          <div class="reactor-state"><span aria-hidden="true">◉</span><span id="core-state">Hazır</span><i aria-hidden="true"></i></div>
          <canvas id="reactor-canvas" width="420" height="320" aria-hidden="true"></canvas>
          <img id="home-media" hidden alt="Canlı önizleme">
          <div class="reactor-actions"><button class="btn alert halt" id="halt" type="button">Durdur</button><button class="btn alert round" id="mic-toggle" data-act="mic" type="button" aria-label="Konuş">${ic("mic")}</button></div>
        </section>
      </div>

      <section class="team-area" id="team-area" aria-label="Hareketli ekip ofisi">
        <header class="team-head"><h2>● Ekip Ofisi</h2><span class="tag">Hazır</span><nav role="group" aria-label="Ofis görünümleri"><button class="tab" type="button" data-team-tab="agents" aria-pressed="true">Uzmanlar</button><button class="tab" type="button" data-team-tab="visual" aria-pressed="false">Görsel Alan</button><button class="tab" type="button" data-team-tab="motion" aria-pressed="false">Hareket</button></nav><button class="btn square" type="button" id="team-pause" aria-label="Ofisi duraklat">⏸</button></header>
        <div id="team-agents" class="team-content">
          <div class="agent-list" id="agent-list" role="group" aria-label="Uzmanı seç"></div>
          <div class="office-wrap"><canvas id="office-map" aria-label="Karakterlerin odalar arasında yürüdüğü piksel ofis"></canvas></div>
        </div>
        <div id="team-visual" class="team-content option-pane" hidden>
          <p>Kamera veya ekranı çekirdek alanında görüntüle.</p><div><button class="btn" type="button" id="camera" data-act="vis" data-a="act:share:camera">Kamerayı aç</button><button class="btn" type="button" id="screen" data-act="vis" data-a="act:share:screen">Ekranı paylaş</button></div>
          <p id="media-notice" role="status"></p>
        </div>
        <div id="team-motion" class="team-content option-pane" hidden>
          <p id="movement-state"></p><div><button class="btn" type="button" id="motion-toggle">Hareketi duraklat</button></div>
        </div>
        <footer class="team-foot"><span class="tag"><i></i>Yerel</span><button class="btn" type="button" id="home-connection" data-act="keysetup" hidden>Model bağlantıları</button><span id="team-status" class="muted" aria-live="polite"></span><div class="room-buttons" role="group" aria-label="Uzmanı odaya gönder"><button class="btn" type="button" data-room="arastirma">Araştırma</button><button class="btn" type="button" data-room="belge">Belge</button><button class="btn" type="button" data-room="kontrol">Kontrol</button></div></footer>
      </section>
    </section>

    <section class="chat" id="chat" aria-label="İletişim">
      <header class="chat-head">
        <nav role="group" aria-label="İletişim görünümleri"><button class="tab" type="button" data-chat="voice" aria-pressed="true">Ses</button><button class="tab" type="button" data-chat="agent" aria-pressed="false">Uzman</button><button class="tab" type="button" data-chat="notes" aria-pressed="false">Notlar</button></nav>
        <div class="chat-tools"><button class="btn square" type="button" id="new-thread" data-act="newchat" aria-label="Yeni konuşma">＋</button><button class="btn square" type="button" id="history" data-home-action="history" aria-label="Sohbet geçmişini aç">↶</button><button class="btn square" type="button" data-home-action="commands" aria-label="Komutlar">›_</button><button class="btn square" type="button" id="chat-expand" aria-label="Konuşmayı büyüt" aria-expanded="false">⛶</button></div>
      </header>
      <div id="home-messages" class="chat-main" role="log" tabindex="0" aria-label="Jarvis konuşması"></div>
      <div id="chat-agent" class="chat-main option-pane" hidden><h3>Ekip Merkezi</h3><div id="home-jobs" aria-live="polite"></div><button class="btn" type="button" data-go="team">Ekip Merkezi’ni aç</button></div>
      <div id="chat-notes" class="chat-main notes-panel" hidden><label for="note">Notun</label><textarea id="note" rows="7" placeholder="Notunu yaz…"></textarea><button class="btn" type="button" id="note-save">Kaydet</button><p id="note-state" role="status"></p><ul id="home-notes"></ul></div>
      <form class="chat-compose" id="compose"><label class="visually-hidden" for="message">Jarvis’e yaz</label><textarea id="message" rows="1" placeholder="Asistana yaz…"></textarea><button class="btn square" type="button" id="attach" data-act="attach" aria-label="Dosya ekle">${ic("clip")}</button><button class="btn square send" type="submit" aria-label="Gönder">↑</button><span class="attc"></span></form>
    </section>
  </div>
<dialog id="info" aria-labelledby="info-title"><header><h2 id="info-title"></h2><button class="btn" id="info-close" type="button">Kapat</button></header><div id="info-body"></div></dialog>`;

  const themes = [
    ['red', 'Kırmızı', '#ff5154'], ['cyan', 'Turkuaz', '#44ddef'],
    ['emerald', 'Yeşil', '#4cdc92'], ['violet', 'Mor', '#b894ff'], ['amber', 'Kehribar', '#ffc15c'],
  ];
  const panels = {
    memory: ['Hafıza', '<button class="btn" data-act="goset" data-k="hafiza">Hafızayı aç</button>'],
    skills: ['Yetenekler', '<button class="btn" data-go="map">Yetenek haritası</button> <button class="btn" data-go="files">Dosyalar</button> <button class="btn" data-go="study">Çalışma</button> <button class="btn" data-go="vision">Ekran ve PC</button>'],
    character: ['Karakter', '<button class="btn" data-act="goset" data-k="ses">Ses ve asistan adı</button>'],
    settings: ['Ayarlar', '<button class="btn" data-act="goset" data-k="ai">Ayarları aç</button> <button class="btn" data-act="user">Kullanıcı değiştir</button> <button class="btn" data-act="notif">Bildirimler</button>'],
    commands: ['Komutlar', '<button class="btn" data-home-prompt="Bugünkü haberleri özetle">Haberleri sor</button> <button class="btn" data-home-prompt="Takvimim">Takvimim</button> <button class="btn" data-home-prompt="Dosyalarımı göster">Dosyalarım</button>'],
  };
  let current = null;

  function mount(page) {
    destroy();
    const root = document.createElement('div');
    root.className = 'jarvis-console';
    const saved = store.get('homeTheme', 'red');
    root.dataset.theme = themes.some(([id]) => id === saved) ? saved : 'red';
    root.innerHTML = markup();
    page.appendChild(root);

    const find = selector => root.querySelector(selector);
    const abort = new AbortController();
    const { signal } = abort;
    const on = (selector, event, handler) => find(selector).addEventListener(event, handler, { signal });
    const dialog = find('#info');
    const input = find('#message');
    let owner = S.snap?.user?.slug;
    let visuals, officePaused = false, reactorPaused = false, chat = 'voice', notePending = null, historyDay = '';
    let previewMode = null, previewTimer = null, previewPending = null;

    function openDialog(title, content) {
      find('#info-title').textContent = title;
      const body = find('#info-body');
      body.innerHTML = content;
      if (!dialog.open) dialog.showModal();
      return body;
    }

    function openTheme() {
      const options = themes.map(([id, label, color]) =>
        `<label class="theme-choice"><input type="radio" name="jarvis-theme" value="${id}" ${root.dataset.theme === id ? 'checked' : ''}><span class="theme-swatch" aria-hidden="true" style="--swatch:${color}"></span><span>${label}</span></label>`
      ).join('');
      const body = openDialog('Tema', `<fieldset class="theme-picker"><legend>Arayüz rengi</legend>${options}</fieldset>`);
      body.querySelector(':checked')?.focus();
    }

    function openHistory() {
      const dates = [...new Set([ymd(new Date()), ...days().map(([day]) => day)])].slice(0,30);
      openDialog('Sohbet geçmişi', '<ul class="console-history">' + dates.map(day =>
        `<li><button class="btn" type="button" data-home-day="${esc(day)}">${day === ymd(new Date()) ? 'Bugün' : esc(day.split('-').reverse().join('.'))}</button></li>`
      ).join('') + '</ul>');
    }

    function setChat(next) {
      chat = next;
      for (const [key, selector] of [['voice','#home-messages'], ['agent','#chat-agent'], ['notes','#chat-notes']]) {
        find(selector).hidden = next !== key;
      }
      find('#compose').hidden = next !== 'voice';
      for (const button of root.querySelectorAll('[data-chat]')) {
        button.setAttribute('aria-pressed', String(button.dataset.chat === next));
      }
      updatePanels();
    }

    function prefill(text) {
      if (dialog.open) dialog.close();
      setChat('voice');
      input.value = text;
      input.focus();
    }

    function setTeam(next) {
      for (const key of ['agents','visual','motion']) find('#team-' + key).hidden = key !== next;
      for (const button of root.querySelectorAll('[data-team-tab]')) {
        button.setAttribute('aria-pressed', String(button.dataset.teamTab === next));
      }
    }

    function renderOffice(state) {
      const host = find('#agent-list');
      const active = state.people[state.selected];
      if (!host.children.length) {
        host.innerHTML = state.people.map((person, index) =>
          `<button class="agent" type="button" data-office-person="${index}" title="${esc(person.role)}"><span class="agent-face" aria-hidden="true" style="--avatar-tone:${esc(person.color)}"></span><span>${esc(person.role)}</span><i aria-hidden="true"></i></button>`
        ).join('');
      }
      Array.from(host.children).forEach((button, index) => button.setAttribute('aria-pressed', String(index === state.selected)));
      find('#team-status').textContent = active.destination ? active.role + ' · ' + active.destination + ' odasına gidiyor' : active.role + ' · ' + active.room;
      officePaused = state.paused;
      const pause = find('#team-pause');
      pause.textContent = officePaused ? '▶' : '⏸';
      pause.setAttribute('aria-label', officePaused ? 'Ofis hareketini başlat' : 'Ofis hareketini duraklat');
      find('#movement-state').textContent = officePaused ? 'Ofis canlandırması duraklatıldı.' : 'Sanal ofiste karakterler odalar arasında hareket ediyor.';
      find('#motion-toggle').textContent = officePaused ? 'Hareketi başlat' : 'Hareketi duraklat';
    }

    function drawAgenda() {
      const today = ymd(new Date());
      const snapshot = S.snap || {};
      const events = (snapshot.all_events || snapshot.events || [])
        .filter(entry => String(entry.when || '').startsWith(today))
        .sort((a,b) => String(a.when).localeCompare(String(b.when))).slice(0,4);
      find('#news-list').innerHTML = events.map(event =>
        `<li><button type="button" data-act="tool" data-k="takvim">${event.when.length > 10 ? `<time>${esc(event.when.slice(11,16))}</time> ` : ''}<b>${esc(event.title || 'Etkinlik')}</b></button></li>`
      ).join('');
      find('#news-empty').hidden = events.length > 0;
    }

    function updatePanels() {
      if (chat === 'agent') window.JarvisTeam?.refreshHome(find('#home-jobs'));
      if (chat === 'notes') {
        const notes = (S.snap?.notes || []).slice(-12).reverse();
        const markup = notes.map(note =>
          `<li><details><summary>${esc(note.title || String(note.text || 'Görsel not').split('\n')[0].slice(0, 70))}</summary><p>${esc(note.text || '')}</p></details></li>`
        ).join('');
        const host = find('#home-notes');
        if (host._markup !== markup) { host._markup = markup; host.innerHTML = markup; }
      }
    }

    function previewImage(data) {
      const img = find('#home-media');
      const valid = typeof data === 'string' && (/^data:image\/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/u.test(data) || /^[A-Za-z0-9+/=]+$/u.test(data));
      if (valid) img.src = data.startsWith('data:') ? data : 'data:image/png;base64,' + data;
      else img.removeAttribute('src');
      img.hidden = !valid;
      find('#reactor-canvas').hidden = valid;
    }

    async function pollPreview() {
      previewTimer = null;
      if (signal.aborted || document.hidden || !previewMode || previewPending) return;
      const request = { mode: previewMode, owner };
      previewPending = request;
      try {
        const data = await api('preview');
        if (previewPending === request && request.mode === S.snap?.mode && request.owner === S.snap?.user?.slug) {
          previewImage(data);
          find('#media-notice').textContent = data ? '' : 'Görüntü bekleniyor…';
        }
      } catch {
        if (previewPending === request) find('#media-notice').textContent = 'Önizleme görüntüsü alınamadı.';
      } finally {
        if (previewPending === request) previewPending = null;
        schedulePreview();
      }
    }

    function schedulePreview() {
      if (!signal.aborted && !document.hidden && previewMode && !previewPending && previewTimer === null) {
        previewTimer = setTimeout(pollPreview, 1250);
      }
    }

    function updateStatus() {
      const mode = S.snap?.mode;
      if (mode !== previewMode) {
        previewMode = mode;
        previewPending = null;
        clearTimeout(previewTimer);
        previewTimer = null;
        previewImage(null);
      }
      for (const [kind, selector, onText, offText] of [
        ['camera','#camera','Kamerayı aç','Kamerayı kapat'], ['screen','#screen','Ekranı paylaş','Paylaşımı kapat'],
      ]) {
        const button = find(selector);
        button.textContent = mode === kind ? offText : onText;
        button.setAttribute('aria-pressed', String(mode === kind));
      }
      const state = S.orb === 'idle' && S.waiting ? 'thinking' : S.orb;
      const active = state !== 'idle';
      const label = mode === 'camera' ? 'Kamera açık' : mode === 'screen' ? 'Ekran paylaşılıyor' :
        !S.snap ? 'Bağlanıyor…' : reactorPaused && !active ? 'Duraklatıldı' : active ? DOCK_ST[state] || 'Hazır' : heyTxt();
      find('#core-state').textContent = label;
      find('#halt').textContent = mode ? 'Paylaşımı kapat' : reactorPaused && !active ? 'Başlat' : 'Durdur';
      const mic = find('#mic-toggle');
      mic.setAttribute('aria-pressed', String(state === 'listening'));
      mic.title = S.snap?.flags?.mic === false ? 'Mikrofon kapalı' : 'Konuş';
      visuals?.setState(mode || (reactorPaused && !active) ? 'stopped' : state);
      schedulePreview();
    }

    function update() {
      const activeOwner = S.snap?.user?.slug;
      if (owner !== activeOwner) {
        owner = activeOwner;
        historyDay = '';
        previewMode = null;
        previewPending = null;
        notePending = null;
        find('#note-save').disabled = false;
        find('#note').value = '';
        input.value = '';
        find('#home-jobs').replaceChildren();
        find('#home-notes').replaceChildren();
        find('#home-notes')._markup = null;
        find('#note-state').textContent = '';
        previewImage(null);
      }
      const sn = S.snap, warning = find('#home-connection');
      warning.hidden = !sn?.llm || !!sn.llm.key || sn.llm.provider === 'ollama';
      updateStatus();
      drawAgenda();
      updatePanels();
    }

    visuals = window.JarvisHomeVisuals?.mount(root, {onOfficeChange: renderOffice});
    const worldMap = window.JarvisHomeMap?.mount(root, {
      onOpenMap(route) {
        if (route === 'today') find('.news').scrollIntoView({block:'nearest'});
        if (route === 'alerts') ACT.notif(find('[data-feed="alerts"]'));
        if (route === 'more') openDialog('Uydu akışı', '<p>Harita dünya konumlarını gösterir.</p><button class="btn" data-go="map">Yetenek haritası</button>');
      },
      async onSearch() {
        const query = await askText('Haber konusu');
        if (!signal.aborted && query?.trim()) prefill('Güncel haberleri ara: ' + query.trim());
      },
      onNotice(text) { toast(text); },
    });
    root.addEventListener('change', event => {
      if (!event.target.matches('input[name="jarvis-theme"]')) return;
      const theme = event.target.value;
      if (!themes.some(([id]) => id === theme)) return;
      root.dataset.theme = theme;
      store.set('homeTheme', theme);
    }, { signal });
    root.addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button) return;
      const { homeAction, homeTool, homePrompt, homeDay, chat: chatTab, teamTab, officePerson, room, act } = button.dataset;
      if (homeAction === 'theme') openTheme();
      if (homeAction === 'history') openHistory();
      if (homeDay) {
        historyDay = homeDay;
        dialog.close();
        setChat('voice');
        drawHomeMessages();
      }
      if (act === 'newchat') { historyDay = ''; setChat('voice'); }
      if (dialog.open && ['user','notif'].includes(act)) dialog.close();
      if (homeAction === 'commands') openDialog(...panels.commands);
      if (homeTool) {
        root.querySelector('.core-option[aria-current]')?.removeAttribute('aria-current');
        button.setAttribute('aria-current','true');
        visuals?.setTask(homeTool);
        const [title, content] = panels[homeTool];
        const audio = homeTool === 'settings' ? '<p>' + micToggleBtn('btn') + muteBtn('btn') + pcMuteBtn('btn') + '</p>' : '';
        openDialog(title, content + audio);
      }
      if (homePrompt) prefill(homePrompt);
      if (chatTab) setChat(chatTab);
      if (teamTab) setTeam(teamTab);
      if (officePerson !== undefined) visuals?.office?.select(Number(officePerson));
      if (room) {
        setTeam('agents');
        visuals?.office?.move(room);
      }
    }, { signal });
    on('#info-close','click',()=>dialog.close());
    on('#news-reset','click',()=>prefill('Bugünkü haberleri özetle'));
    on('#chat-expand','click',event=>{
      const expanded = find('#chat').classList.toggle('is-expanded');
      event.currentTarget.setAttribute('aria-expanded',String(expanded));
    });
    root.addEventListener('keydown',event=>{
      if (event.key !== 'Escape' || dialog.open || !find('#chat').classList.contains('is-expanded')) return;
      find('#chat-expand').click();
      find('#chat-expand').focus();
    }, {signal});
    on('#team-pause','click',()=>visuals?.office?.setPaused(!officePaused));
    on('#motion-toggle','click',()=>visuals?.office?.setPaused(!officePaused));
    on('#halt','click',()=>{
      if (previewMode) return void ACT.vis({dataset:{a:'act:share:'+previewMode}});
      if (S.orb === 'speaking' || S.sspeaking) return void ACT.dstop();
      if (S.waiting || S.orb === 'working' || S.orb === 'thinking') return void ACT.stoptask();
      reactorPaused = !reactorPaused;
      updateStatus();
    });
    on('#message','keydown',event=>{
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        find('#compose').requestSubmit();
      }
    });
    on('#compose','submit',event=>{
      event.preventDefault();
      if (S.attPending) return toast('Dosyanın yüklenmesini bekle.');
      const text = input.value.trim();
      if (!text && !atts().length) return;
      input.value = '';
      historyDay = '';
      void say(text);
    });
    on('#note-save','click',async event=>{
      const text = find('#note').value.trim();
      if (!text || !owner || notePending) return;
      const requestOwner = owner;
      const button = event.currentTarget;
      const request = {owner};
      notePending = request;
      button.disabled = true;
      try {
        const saved = await api('note_add',text);
        if (signal.aborted || requestOwner !== S.snap?.user?.slug || notePending !== request) return;
        if (!saved) throw new Error('Not kaydedilemedi.');
        find('#note').value = '';
        find('#note-state').textContent = 'Not kaydedildi.';
        await refresh();
      } catch (error) {
        if (!signal.aborted && requestOwner === S.snap?.user?.slug && notePending === request) {
          find('#note-state').textContent = error.message;
        }
      } finally {
        if (notePending === request) {
          notePending = null;
          button.disabled = false;
        }
      }
    });
    document.addEventListener('visibilitychange',schedulePreview,{signal});

    current = {
      update, updateStatus, day: () => historyDay,
      destroy() {
        abort.abort();
        clearTimeout(previewTimer);
        previewPending = null;
        visuals?.destroy();
        worldMap?.destroy();
        root.remove();
      },
    };
    setTeam('agents');
    update();
  }

  function destroy() {
    current?.destroy();
    current = null;
  }

  window.JarvisHome = {mount, destroy, day:()=>current?.day(), refresh:()=>current?.update(), updateStatus:()=>current?.updateStatus()};
})();
