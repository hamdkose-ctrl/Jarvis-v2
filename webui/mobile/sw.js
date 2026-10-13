// Yalnız herkese açık çevrimdışı yardım ve simgeler tutulur. Sohbet/API/anahtarlar saklanmaz.
const CACHE = 'jarvis-mobile-v6';
const PUBLIC = ['/offline.html', '/notes.html', '/notes.js', '/icon-180.png', '/icon-192.png', '/icon-512.png'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PUBLIC)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith('jarvis-mobile-') && k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (u.origin !== self.location.origin || e.request.method !== 'GET' || u.pathname.startsWith('/api/')) return;
  if (e.request.mode === 'navigate' && u.pathname === '/') {
    e.respondWith(fetch(e.request).catch(() => caches.match('/offline.html')));
  } else if (PUBLIC.includes(u.pathname) && !u.search) {
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
  }
});
