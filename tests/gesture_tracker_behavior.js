'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');

const root=path.join(__dirname,'..');
const trackerPath=path.join(root,'webui','gesture-tracker.js');
assert(fs.existsSync(trackerPath),'gesture tracker dosyası önce eklenmeli');
const src=fs.readFileSync(trackerPath,'utf8');
const html=fs.readFileSync(path.join(root,'webui','nx.html'),'utf8');

assert(src.includes('@mediapipe/tasks-vision@1.1.1'),'MediaPipe Tasks Vision sürümü sabitlenmeli');
assert(src.includes('hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task'),'resmi hand landmarker modeli sabitlenmeli');
assert(/api\(['"]preview['"]\)/.test(src),'tracker mevcut yerel preview API akışını kullanmalı');
assert(!/getUserMedia\s*\(/.test(src),'tracker ikinci kamera akışı açmamalı');
assert(/JarvisGestureInput\.landmarks/.test(src),'21 landmark mevcut gesture classifier/producer hattına verilmeli');
assert(/JarvisGestureInput\.sample\([^\n]*['"]none['"]/.test(src),'el kaybı/kapanış mevcut release sinyalini kullanmalı');
assert(/permission_granted|approve|grantPermission|requestPermission/.test(src)===false,'tracker permission/onay üretmemeli');
assert(/data:image\/png;base64/.test(src),'preview yalnız yerel görüntü kaynağı olarak çözülmeli');
assert(/gesture-tracker\.js/.test(html),'tracker ana UI içinde yüklenmeli');
assert(html.indexOf('/gesture-client.js')<html.indexOf('/gesture-tracker.js'),'tracker classifier/client sınırından sonra yüklenmeli');

// Tracker kendini mevcut kamera düğmesinin canlı durumuna bağlamalı; ayrı kamera UI açmamalı.
assert(/act:share:camera/.test(src),'mevcut kamera paylaşım yaşam döngüsü izlenmeli');
assert(!/appendChild\([^)]*video|createElement\(['"]video['"]\)/.test(src),'ayrı kamera/video UI oluşturulmamalı');

console.log('gesture tracker behavior: ok');
