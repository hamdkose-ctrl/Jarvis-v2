// Local hand-landmark -> normalized gesture classifier.
// Input is 21 normalized landmarks. Output is evidence/input only; never authority.
'use strict';
(function(root){
  const D=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
  const vec=(a,b)=>({x:b.x-a.x,y:b.y-a.y});
  const cos=(a,b)=>{const n=Math.hypot(a.x,a.y)*Math.hypot(b.x,b.y);return n?((a.x*b.x+a.y*b.y)/n):-1};

  function valid(points){
    if(!Array.isArray(points)||points.length!==21)throw new Error('Gesture classifier 21 landmark bekliyor.');
    return points.map((p,i)=>{
      const x=Number(p&&p.x),y=Number(p&&p.y),z=Number(p&&p.z||0);
      if(!Number.isFinite(x)||!Number.isFinite(y)||!Number.isFinite(z)||x<0||x>1||y<0||y>1)throw new Error('Gesture landmark geçersiz: '+i);
      return {x,y,z};
    });
  }

  function extended(p,mcp,pip,dip,tip){
    const a=vec(p[mcp],p[pip]),b=vec(p[pip],p[dip]),c=vec(p[dip],p[tip]);
    const reach=D(p[mcp],p[tip]),base=Math.max(D(p[mcp],p[pip]),1e-6);
    return reach>base*2.15&&cos(a,b)>.45&&cos(b,c)>.45;
  }
  function thumbExtended(p){
    const a=vec(p[2],p[3]),b=vec(p[3],p[4]);
    return D(p[2],p[4])>Math.max(D(p[2],p[3]),1e-6)*1.55&&cos(a,b)>.45;
  }

  function classify(raw){
    const p=valid(raw);
    const index=extended(p,5,6,7,8),middle=extended(p,9,10,11,12),ring=extended(p,13,14,15,16),pinky=extended(p,17,18,19,20),thumb=thumbExtended(p);
    const openCount=[index,middle,ring,pinky].filter(Boolean).length;
    if(openCount===4)return 'open_palm';
    if(index&&middle&&!ring&&!pinky)return 'victory';
    if(index&&!middle&&!ring&&!pinky){
      const d=vec(p[5],p[8]);
      if(Math.abs(d.x)>Math.abs(d.y)*1.15)return d.x>0?'point_right':'point_left';
      if(d.y<0)return 'point_up';
      return 'none';
    }
    if(!index&&!middle&&!ring&&!pinky&&thumb){
      const d=vec(p[2],p[4]);
      if(d.y<0&&Math.abs(d.y)>Math.abs(d.x)*.8)return 'thumbs_up';
    }
    if(!index&&!middle&&!ring&&!pinky&&!thumb)return 'fist';
    return 'none';
  }

  root.JarvisGestureClassifier=Object.freeze({classify});
})(globalThis);
