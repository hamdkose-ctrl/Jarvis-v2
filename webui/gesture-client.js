// Gesture client boundary: local tracker/classifier -> existing WebChat bridge.
// This module never grants authority or executes effects; it only forwards a
// normalized gesture label to /api/gesture_sample through nx.js' existing api().
'use strict';
(function(root){
  const LABELS=new Set(['fist','open_palm','point_up','point_right','point_left','thumbs_up','victory','none']);

  async function sample(deviceId,gesture){
    const device=String(deviceId??'').trim();
    const label=String(gesture??'').trim().toLowerCase();
    if(!device||device.length>200)throw new Error('Gesture için geçerli cihaz kimliği gerekli.');
    if(!LABELS.has(label))throw new Error('Gesture etiketi desteklenmiyor.');
    if(typeof root.api!=='function')throw new Error('Jarvis gesture bridge hazır değil.');
    return root.api('gesture_sample',device,label);
  }

  root.JarvisGestureInput=Object.freeze({sample});
})(globalThis);
