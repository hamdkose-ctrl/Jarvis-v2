(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.JarvisActivityStrip=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const clip=(value,limit)=>String(value==null?'':value).replace(/\s+/g,' ').trim().slice(0,limit);
  const rows=steps=>{
    const out=[];
    if(!steps||typeof steps!=='object')return out;
    Object.keys(steps).forEach((rid,order)=>{
      const card=steps[rid],items=card&&card.items;
      if(!(items instanceof Map))return;
      let index=0;
      items.forEach(item=>{out.push({item:item||{},ts:Number(card.ts)||0,order,index:index++})});
    });
    return out;
  };
  function activityItems(steps,rid,limit=4){
    const card=steps&&steps[rid],items=card&&card.items;
    if(!(items instanceof Map))return [];
    const n=Math.max(0,Number.isFinite(+limit)?Math.floor(+limit):4);
    return [...items.values()].slice(-n).map(item=>({
      text:clip(item&&item.t,160),
      status:['working','done','error'].includes(item&&item.s)?item.s:'working',
      detail:clip(item&&item.d,80)
    }));
  }
  function stripState(snap,steps){
    const visible=!!(snap&&snap.working===true);
    let latest=null;
    rows(steps).forEach(row=>{
      if(row.item.s!=='working')return;
      if(!latest||row.ts>latest.ts||row.ts===latest.ts&&(row.order>latest.order||row.order===latest.order&&row.index>latest.index))latest=row;
    });
    return {visible,label:clip(latest&&latest.item.t,160)||'Çalışıyor…',stoppable:visible};
  }
  return {activityItems,stripState};
});
