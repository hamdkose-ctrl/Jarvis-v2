(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.JarvisActivityStrip=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  const validStatus=s=>['working','done','error'].includes(s)?s:'working';
  const brief=x=>String(x??'').slice(0,80);

  function activityItems(steps,rid,limit=4){
    const card=steps&&steps[rid];
    const values=card&&card.items instanceof Map?[...card.items.values()]:[];
    const raw=Number(limit),count=Number.isFinite(raw)?Math.max(0,Math.floor(raw)):4;
    return values.slice(-count).map(item=>({
      text:String(item&&item.t||''),
      status:validStatus(item&&item.s),
      detail:brief(item&&item.d)
    }));
  }

  function stripState(snap,steps){
    const visible=!!(snap&&snap.working===true);
    let label='Çalışıyor…',bestTs=-Infinity,bestSeq=-1,seq=0;
    for(const card of Object.values(steps||{})){
      if(!card||!(card.items instanceof Map))continue;
      const ts=Number(card.ts)||0;
      for(const item of card.items.values()){
        seq++;
        if(item&&item.s==='working'&&(ts>bestTs||(ts===bestTs&&seq>bestSeq))){
          bestTs=ts;bestSeq=seq;label=String(item.t||'').trim()||'Çalışıyor…';
        }
      }
    }
    return {visible,label,stoppable:visible};
  }

  return {activityItems,stripState};
});
