const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');

function hand(kind){
  const p=Array.from({length:21},()=>({x:.5,y:.75,z:0}));
  p[0]={x:.5,y:.92,z:0};
  // MCP anchors
  p[2]={x:.38,y:.70,z:0}; p[5]={x:.42,y:.68,z:0}; p[9]={x:.50,y:.64,z:0}; p[13]={x:.58,y:.68,z:0}; p[17]={x:.66,y:.72,z:0};
  const setFinger=(mcp,pip,dip,tip,x,extended)=>{
    p[mcp]={x,y:.68,z:0};
    if(extended){p[pip]={x,y:.50,z:0};p[dip]={x,y:.34,z:0};p[tip]={x,y:.18,z:0};}
    else{p[pip]={x,y:.58,z:0};p[dip]={x:x+.03,y:.68,z:0};p[tip]={x:x+.02,y:.76,z:0};}
  };
  const fingers={index:false,middle:false,ring:false,pinky:false};
  let thumb=false;
  if(kind==='open_palm')Object.assign(fingers,{index:true,middle:true,ring:true,pinky:true}),thumb=true;
  if(kind==='victory')Object.assign(fingers,{index:true,middle:true});
  if(kind.startsWith('point_'))fingers.index=true;
  if(kind==='thumbs_up')thumb=true;
  setFinger(5,6,7,8,.42,fingers.index);
  setFinger(9,10,11,12,.50,fingers.middle);
  setFinger(13,14,15,16,.58,fingers.ring);
  setFinger(17,18,19,20,.66,fingers.pinky);
  if(thumb){p[2]={x:.40,y:.70,z:0};p[3]={x:.34,y:.53,z:0};p[4]={x:.28,y:.35,z:0};}
  else{p[3]={x:.42,y:.70,z:0};p[4]={x:.46,y:.74,z:0};}
  if(kind==='thumbs_up'){p[2]={x:.46,y:.69,z:0};p[3]={x:.46,y:.45,z:0};p[4]={x:.46,y:.18,z:0};}
  if(kind==='point_right'){p[5]={x:.42,y:.68,z:0};p[6]={x:.56,y:.66,z:0};p[7]={x:.70,y:.64,z:0};p[8]={x:.86,y:.62,z:0};}
  if(kind==='point_left'){p[5]={x:.58,y:.68,z:0};p[6]={x:.44,y:.66,z:0};p[7]={x:.30,y:.64,z:0};p[8]={x:.14,y:.62,z:0};}
  return p;
}

const classifierSrc=fs.readFileSync(path.join(__dirname,'../webui/gesture-classifier.js'),'utf8');
const clientSrc=fs.readFileSync(path.join(__dirname,'../webui/gesture-client.js'),'utf8');
const calls=[];
const ctx={console,api:async(...args)=>{calls.push(args);return {ok:true}},globalThis:null};ctx.globalThis=ctx;
vm.createContext(ctx);vm.runInContext(classifierSrc,ctx);vm.runInContext(clientSrc,ctx);

for(const label of ['fist','open_palm','point_up','point_right','point_left','thumbs_up','victory']){
  assert.equal(ctx.JarvisGestureClassifier.classify(hand(label)),label,label+' sınıflandırılmalı');
}
const ambiguous=hand('fist');ambiguous[8]={x:.42,y:.42,z:0};
assert.equal(ctx.JarvisGestureClassifier.classify(ambiguous),'none','kararsız şekil none olmalı');
assert.throws(()=>ctx.JarvisGestureClassifier.classify([{x:.1,y:.1}]),/21/);
const bad=hand('fist');bad[4]={x:NaN,y:.2,z:0};assert.throws(()=>ctx.JarvisGestureClassifier.classify(bad),/geçersiz/);

(async()=>{
  calls.length=0;
  await ctx.JarvisGestureInput.landmarks('phone-1',hand('victory'));
  assert.deepEqual(calls,[['gesture_sample','phone-1','victory']]);
  console.log('gesture classifier behavior OK');
})().catch(e=>{console.error(e);process.exit(1)});
