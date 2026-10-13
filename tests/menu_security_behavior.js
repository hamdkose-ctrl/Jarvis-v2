// Menü ekranı (APEX-UI portu) güvenlik denetimi: dışarıya bağlanmaz, veri göndermez, depolama/kod çalıştırma kullanmaz.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const src=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');
const a=src.indexOf('// ---- İkinci ana ekran'),b=src.indexOf('PAGES.home=pg=>{');
assert(a>0&&b>a,'menü bölümü bulunmalı');
const m=src.slice(a,b);
for(const [re,ad] of [[/\bfetch\(/,'fetch'],[/XMLHttpRequest/,'XMLHttpRequest'],[/sendBeacon/,'sendBeacon'],[/WebSocket/,'WebSocket'],[/EventSource/,'EventSource'],[/\bapi\(|tryApi\(/,'sunucu API çağrısı'],
  [/localStorage|sessionStorage|indexedDB|document\.cookie/,'tarayıcı depolama'],[/\beval\(|new Function/,'dinamik kod'],[/window\.open|postMessage|importScripts/,'dış pencere/mesaj'],[/<script|<iframe|<img|\ssrc=|\shref=/,'dış kaynak etiketi']])
  assert(!re.test(m),'menü bölümünde '+ad+' olmamalı');
const urls=[...m.matchAll(/https?:\/\/[^\s'"`)]*/g)].map(x=>x[0]);
assert.deepEqual(urls,['http://www.w3.org/2000/svg'],'tek URL SVG ad alanı olmalı (istek değil)');
// dışarıdan gelen metin (hava durumu) HTML'e kaçışsız girmemeli
assert(/esc\(String\(w\.city/.test(m)&&/esc\(String\(w\.desc/.test(m),'hava durumu metni esc ile kaçırılmalı');
// sunucu tarafı: dışa bağlantıyı CSP engellemeli
const web=fs.readFileSync(path.join(__dirname,'../web.py'),'utf8');
assert(web.includes("connect-src 'self'")&&web.includes("frame-ancestors 'none'"),'CSP connect-src self ve frame-ancestors none olmalı');
console.log('Menü ekranı güvenlik: ağ, depolama, kod çalıştırma ve dış URL yok; CSP dışa bağlantıyı engelliyor geçti.');
