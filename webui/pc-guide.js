// A scoped extension to the screen page; the existing UI and PC actions stay intact.
'use strict';
(()=>{
 const draw=PAGES.vision;
 PAGES.vision=pg=>{
  draw(pg);
  const grid=pg.querySelector('.grid3');if(!grid)return;
  const button=document.createElement('button');button.className='acard cyan';
  button.dataset.act='pcguide';
  button.innerHTML=`<span class="ib cyan">${ic('monitor')}</span><b>PC Yardımı</b><small>Ne yapmak istediğini söyle; adım adım ilerleyelim.</small><span class="go">${ic('chev')}</span>`;
  grid.appendChild(button);
 };
 ACT.pcguide=async()=>{
  const goal=await askText('Bilgisayarda ne yapmak istiyorsun? Örneğin: Fotoğrafları telefona göndermek.','');
  if(goal&&goal.trim())return say('PC yardımı: '+goal.trim().slice(0,1200));
 };
})();
