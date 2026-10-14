// Menü çekirdeğinin dokunma diski (.mn-tap, görünmez mikrofon düğmesi) hiçbir ekran boyutunda düğümlerin tıklama alanının üstüne binmemeli.
// Regresyon: disk 36vw (850 px altında 60vw) idi; 1280x650 gibi kısa pencerelerde Sohbet düğümünü, dar pencerelerde düğümlerin çoğunu örtüyordu.
// Düğüme basan kullanıcı mikrofonu açıp kapatıyordu ("sekmeye basınca bir şey açılıp kapanıyor").
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const css=fs.readFileSync(path.join(__dirname,'../webui/nx.css'),'utf8'),js=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');
const rule=css.match(/\.mn-tap\{[^}]*\}/);assert(rule,'.mn-tap kuralı var');
const size=prop=>{const m=rule[0].match(new RegExp('(?:^|[;{])'+prop+':min\\(([^)]*)\\)'));assert(m,prop+' min(...) ile sınırlı');return m[1].split(',').map(x=>x.trim())};
const w=size('width'),h=size('height');assert.deepEqual(w,h,'disk yuvarlak kalır');
// .mn-tap boyutunu başka bir kural (ör. eski 850 px medya sorgusu) ezmemeli
const over=[...css.matchAll(/\.mn-tap[^{,]*\{([^}]*)\}/g)].filter(m=>m.index!==rule.index&&/(^|;)\s*(width|height)\s*:/.test(m[1]));
assert.equal(over.length,0,'disk boyutunu ezen başka kural yok');
const px=(parts,W,H)=>Math.min(...parts.map(p=>{const n=parseFloat(p);if(p.endsWith('px'))return n;if(p.endsWith('vw'))return n*W/100;if(p.endsWith('vh'))return n*H/100;throw new Error('bilinmeyen birim '+p)}));
// Düğümler merkezden en az MINR birimdedir; tıklama alanı yarıçapı max(r+13,17)
const MINR=+js.match(/const MINR=(\d+)/)[1];
const roster=js.slice(js.indexOf('const MENU_ROSTER=['),js.indexOf('const MENU_ACT='));
const maxR=Math.max(...[...roster.matchAll(/\['\w+','[^']*','\w+',\d+,\d+,(?:true|false),-?\d+,([\d.]+)\]/g)].map(m=>+m[1]));
assert(maxR>0&&MINR>0);const edge=MINR-Math.max(maxR+13,17);
for(const [W,H] of [[1920,1080],[1594,850],[1536,730],[1366,657],[1280,650],[1280,600],[1100,700],[1024,600],[820,700],[600,800],[400,800]]){
  const s=Math.min(W/680,H/480),r=px(w,W,H)/2/s;   // disk yarıçapı SVG biriminde (yan sayfa açıkken disk ve ağ aynı oranda küçülür)
  assert(r<edge-4,`${W}x${H}: disk yarıçapı ${r.toFixed(1)} birim, en yakın düğüm alanı ${edge} birimde`);
  assert(px(w,W,H)>=60,`${W}x${H}: çekirdeğe dokunulabilir kalır`)}
console.log('menu tap ok');
