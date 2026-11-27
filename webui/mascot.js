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
    speaking: 'mutlu',
  });
  const GREETING = 'selamlama';
  const GREETING_MS = 5000;
  const STILL = 'bosta_still.png';

  let shown = null;
  let state = 'idle';
  let greeted = false;
  let broken = false;
  let timer = null;

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
    for (const name of new Set([...Object.values(CLIPS), GREETING])) new Image().src = BASE + name + '.webp';
  }

  function greet() {
    greeted = true;
    place(GREETING);
    warm();
    timer = setTimeout(() => { timer = null; place(CLIPS[state] || CLIPS.idle); }, GREETING_MS);
  }

  function set(next) {
    state = String(next || 'idle');
    if (broken) return;
    if (reduce()) { place(STILL, true); return; }
    if (timer && state !== 'idle') { clearTimeout(timer); timer = null; }
    if (timer) return;
    if (!greeted) { greet(); return; }
    place(CLIPS[state] || CLIPS.idle);
  }

  globalThis.Mascot = Object.freeze({ set });
})();
