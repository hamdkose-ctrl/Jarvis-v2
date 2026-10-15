(function(global){
  'use strict';
  let active=null;
  function mount(options={}){
    if(active)return active;
    const root=document.createElement('div');
    root.id='seljuk-backdrop';root.setAttribute('aria-hidden','true');
    root.innerHTML=`<div class="sj-land"></div><div class="sj-emblem"><img class="sj-blue" src="/seljuk-emblem.webp" alt=""><img class="sj-energy" src="/seljuk-emblem.webp" alt=""><i class="sj-flow"></i></div><div class="sj-shade"></div>`;
    const media=matchMedia('(prefers-reduced-motion: reduce)');
    function sync(){root.classList.toggle('sj-still',media.matches||!!options.isStill?.());root.classList.toggle('sj-paused',document.hidden)}
    function replay(){sync();root.classList.remove('sj-enter');void root.offsetWidth;root.classList.add('sj-enter')}
    const api={sync,replay,destroy(){document.removeEventListener('visibilitychange',sync);media.removeEventListener('change',sync);root.remove();document.body.classList.remove('seljuk-theme');active=null}};
    document.body.prepend(root);document.body.classList.add('seljuk-theme');
    document.addEventListener('visibilitychange',sync);media.addEventListener('change',sync);
    active=api;replay();return api;
  }
  global.JarvisBackdrop={mount};
})(window);
