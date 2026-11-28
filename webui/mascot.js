'use strict';
/* Çekirdek maskotu: Jarvis'in durumunu (S.orb) karakter klibine bağlar.
   Klipler webui/mascot/*.webp; hareket azaltma tercihinde tek kare gösterilir.
   Görsel yüklenemezse sessizce susar, çekirdek çizimi (canvas) görünür kalır. */
(() => {
  const BASE = '/mascot/';
  const CLIPS = Object.freeze({
    idle: 'bosta',
    listening: 'dinleme',
    thinking: 'dusunme',
    working: 'calisma',
    speaking: 'konusma',
  });
  const ALT_SPEECH = 'konusma2';
  const GREETING = 'selamlama';
  const GREETING_MS = 2400;
  const STILL = 'bosta_still.png';

  let shown = null;
  let state = 'idle';
  let greeted = false;
  let broken = false;
  let timer = null;
  let speech = ALT_SPEECH;

  const currentClip = () => state === 'speaking' ? speech : (CLIPS[state] || CLIPS.idle);

  const reduce = () => globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true;
  const node = () => document.querySelector('.reactor .mascot');

  function place(name, still = false) {
    const img = node();
    if (!img || (shown === name && img.getAttribute('src'))) return;
    shown = name;
    img.onload = () => { img.hidden = false; };
    img.onerror = () => { img.hidden = true; img.removeAttribute('src'); shown = null; broken = true; };
    img.src = BASE + name + (still ? '.png' : '.webp');
  }

  function warm() {
    for (const name of new Set([...Object.values(CLIPS), ALT_SPEECH, GREETING])) new Image().src = BASE + name + '.webp';
  }

  function set(next) {
    const wanted = String(next || 'idle');
    if (state !== wanted && wanted === 'speaking') {
      speech = speech === ALT_SPEECH ? CLIPS.speaking : ALT_SPEECH;
    }
    state = wanted;
    if (broken) return;
    if (reduce()) { place(STILL, true); return; }
    if (timer && state !== 'idle') { clearTimeout(timer); timer = null; }
    if (timer) return;
    if (!greeted) {
      greeted = true;
      warm();
      if (state === 'idle') {
        place(GREETING);
        timer = setTimeout(() => { timer = null; place(currentClip()); }, GREETING_MS);
        return;
      }
    }
    place(currentClip());
  }

  globalThis.Mascot = Object.freeze({ set });
})();
