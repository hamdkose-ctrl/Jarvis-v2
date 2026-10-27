// Existing Jarvis camera preview -> local hand landmarks -> gesture client.
// Raw camera frames stay on this PC; only the normalized gesture label crosses
// the existing gesture_sample bridge. This module opens no second camera.
'use strict';
(function(root){
  const TASKS_JS='https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.1.1/+esm';
  const WASM_ROOT='https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.1.1/wasm';
  const MODEL='https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';
  const FRAME_MS=180;
  const SYNC_MS=500;
  const DEVICE_KEY='nx.gesture_device_id';

  let handLandmarker=null,loading=null,timer=0,syncTimer=0,running=false,busy=false,hadHand=false,closed=false;

  function deviceId(){
    try{
      let value=root.localStorage&&root.localStorage.getItem(DEVICE_KEY);
      if(value)return value;
      const id=root.crypto&&typeof root.crypto.randomUUID==='function'?root.crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
      value='web:'+id;
      root.localStorage&&root.localStorage.setItem(DEVICE_KEY,value);
      return value;
    }catch(_){return 'web:session-'+Date.now().toString(36)}
  }

  function cameraLive(){
    const doc=root.document;
    return !!(doc&&doc.querySelector('[data-act="vis"][data-a="act:share:camera"].live'));
  }

  async function loadTracker(){
    if(handLandmarker)return handLandmarker;
    if(loading)return loading;
    loading=(async()=>{
      const vision=await import(TASKS_JS);
      const files=await vision.FilesetResolver.forVisionTasks(WASM_ROOT);
      const opts={baseOptions:{modelAssetPath:MODEL,delegate:'GPU'},runningMode:'VIDEO',numHands:1,minHandDetectionConfidence:.72,minHandPresenceConfidence:.72,minTrackingConfidence:.72};
      try{return await vision.HandLandmarker.createFromOptions(files,opts)}
      catch(_){return vision.HandLandmarker.createFromOptions(files,{...opts,baseOptions:{modelAssetPath:MODEL}})}
    })();
    try{handLandmarker=await loading;return handLandmarker}finally{loading=null}
  }

  async function imageFromPreview(b64){
    if(!b64)return null;
    const img=new Image();
    img.decoding='async';
    img.src='data:image/png;base64,'+b64;
    if(typeof img.decode==='function')await img.decode();
    else await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=reject});
    return img;
  }

  async function release(){
    if(!hadHand)return;
    hadHand=false;
    if(root.JarvisGestureInput&&typeof root.JarvisGestureInput.sample==='function'){
      try{await root.JarvisGestureInput.sample(deviceId(),'none')}catch(_){}
    }
  }

  async function tick(){
    if(!running||closed)return;
    if(busy){timer=root.setTimeout(tick,FRAME_MS);return}
    busy=true;
    try{
      if(!cameraLive()){await stop();return}
      if(typeof root.api!=='function'||!root.JarvisGestureInput||!root.JarvisGestureClassifier)throw new Error('Jarvis gesture tracker sınırı hazır değil.');
      const b64=await root.api('preview');
      if(!b64){await release();return}
      const img=await imageFromPreview(b64);
      const tracker=await loadTracker();
      const result=tracker.detectForVideo(img,root.performance?root.performance.now():Date.now());
      const points=result&&Array.isArray(result.landmarks)&&result.landmarks[0];
      if(!points){await release();return}
      hadHand=true;
      await root.JarvisGestureInput.landmarks(deviceId(),points);
    }catch(err){
      await release();
      if(root.console&&root.console.warn)root.console.warn('Gesture tracker:',err&&err.message?err.message:err);
    }finally{
      busy=false;
      if(running&&!closed)timer=root.setTimeout(tick,FRAME_MS);
    }
  }

  async function start(){
    if(running||closed||!cameraLive())return false;
    running=true;
    timer=root.setTimeout(tick,0);
    return true;
  }

  async function stop(){
    if(!running&&!hadHand)return false;
    running=false;
    if(timer){root.clearTimeout(timer);timer=0}
    await release();
    return true;
  }

  function sync(){
    if(closed)return;
    if(cameraLive())start();else stop();
  }

  async function close(){
    closed=true;
    await stop();
    if(syncTimer){root.clearInterval(syncTimer);syncTimer=0}
    if(handLandmarker&&typeof handLandmarker.close==='function'){try{handLandmarker.close()}catch(_){}}
    handLandmarker=null;
  }

  root.JarvisGestureTracker=Object.freeze({start,stop,sync,close});
  if(root.document){
    if(typeof MutationObserver!=='undefined')new MutationObserver(sync).observe(root.document.documentElement,{subtree:true,attributes:true,attributeFilter:['class']});
    syncTimer=root.setInterval(sync,SYNC_MS);
    root.addEventListener&&root.addEventListener('pagehide',close,{once:true});
    sync();
  }
})(globalThis);
