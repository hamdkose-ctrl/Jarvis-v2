(() => {
  const button = document.getElementById('install');
  let promptEvent;
  const standalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone;
  if (standalone()) button.hidden = true;
  addEventListener('beforeinstallprompt', e => { e.preventDefault(); promptEvent = e; });
  addEventListener('appinstalled', () => { button.hidden = true; promptEvent = null; });
  button.onclick = async () => {
    if (!isSecureContext) return toast('Uygulama kurulumu için bilgisayarda Telefon → HTTPS’i aç; HTTPS QR’ını okut.');
    if (!localStorage.jk) return toast('Önce bilgisayardaki Telefon sayfasından HTTPS QR koduyla bağlan.');
    try {
      const saved = await fetch('/api/web-session', {method: 'POST', headers: {'X-Token': localStorage.jk}, credentials: 'same-origin'});
      if (!saved.ok) throw Error('oturum');
      const check = await fetch('/api/web-session', {headers: {'X-Jarvis-Web-Session': '1'}, credentials: 'same-origin'});
      if (!check.ok || (await check.json()).token !== localStorage.jk) throw Error('çerez');
    } catch (_) { return toast('Bağlantı kurulum için saklanamadı. HTTPS bağlantısını ve tarayıcı çerez iznini kontrol et; sonra tekrar dene.'); }
    if (promptEvent) {
      await promptEvent.prompt();
      await promptEvent.userChoice;
      promptEvent = null;
    } else {
      const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
      toast(ios ? 'Paylaş menüsünden “Ana Ekrana Ekle”yi seç. Bağlantın ilk açılış için saklandı.' : 'Tarayıcı menüsünden “Uygulamayı yükle” veya “Ana ekrana ekle”yi seç.');
    }
  };
  if (isSecureContext && 'serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
})();
