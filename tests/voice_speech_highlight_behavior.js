// §8: Görünür sesli sunum izi. Gerçek oynatma olayı dışında (kuyruk/sentez/WAV) hiçbir
// şey "konuşuyor" gibi işaretlenmez; geç kalan bir stage daha yeni konuşmayı söndürmez;
// vurgu yalnız DOM sınıfıdır, pencere öne alınmaz.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),src=fs.readFileSync(path.join(root,'webui/nx.js'),'utf8');
const begin=src.indexOf('// SPEECH HIGHLIGHT START'),end=src.indexOf('// SPEECH HIGHLIGHT END');
assert(begin>=0&&end>begin,'sesli sunum izi yardımcıları bulunamadı');
const block=src.slice(begin,end);

// Küçük sahte DOM: sağ sohbet yanıtları gerçekten işaretlenir.
function node(rid){const set=new Set(),dataset={rid};
  return {dataset,set,classList:{toggle(c,on){on?set.add(c):set.delete(c)},contains:c=>set.has(c)}}}
let rows=[];
const c={S:{speech:null},$$:sel=>sel==='.jarvis-console .turn[data-speaker="jarvis"]'?rows:[]};
vm.createContext(c);
vm.runInContext(block,c);
const id=(extra={})=>JSON.stringify({speech_id:'sp1',turn_id:'',goal_id:'',kind:'reply',...extra});
const say=(stage,extra)=>c.speechEvent({k:'speech',t:stage,x:id(extra)});
const marked=()=>rows.filter(r=>r.set.has('saying')).map(r=>r.dataset.rid).join(',');

// Kuyruk, sentez ve WAV hazırlığı konuşma değildir: playback_started öncesi hiçbir iz yok.
rows=[node('r1'),node('r2')];for(const stage of ['accepted','synthesizing','audio_ready'])say(stage,{turn_id:'r1'});
assert.equal(c.S.speech,null,'kuyruk/sentez/WAV hazırlığı sesli sunum değildir');
assert.equal(marked(),'','oynatma başlamadan satır işaretlenmez');

// Bozuk/eksiz yük yok sayılır, vurgu koymaz.
c.speechEvent({k:'speech',t:'playback_started',x:'{bozuk'});
assert.equal(c.S.speech,null,'bozuk olay yükü işaret üretmez');

// Gerçek oynatma başlangıcı: yalnız bu yanıt satırı işaretlenir.
say('playback_started',{turn_id:'r1'});
assert.equal(marked(),'r1','yalnız seslendirilen isteğin yanıtı vurgulanır');
assert.equal(c.speechClassFor({rid:'r1'}),' saying');
assert.equal(c.speechClassFor({rid:'r2'}),'','başka isteğin yanıtı sesli sunum değildir');
assert.equal(c.speechClassFor({}), '','kimlik taşımayan satır vurgulanmaz');
say('playback_started',{turn_id:'r2',goal_id:'g-7'});
assert.equal(marked(),'r2','yeni oynatma eski işaretin yerini alır');

// Geç kalan stage daha yeni konuşmayı söndüremez.
say('audio_ready',{speech_id:'sp0',turn_id:'r1'});
assert.equal(c.S.speech.turn_id,'r2','geç kalan hazır-evresi seslendirilen sonucu ezmez');
assert.equal(marked(),'r2','geç kalan hazır-evresi yeni seslendirmeyi boştaya düşürmez');

// Konuşma durumu yalnız oynatma sürdüğünde işaretli kalır; bitişte kalkar.
c.speechStateEvent('speaking');
assert.equal(marked(),'r2','speaking durumu işareti korur');
c.speechStateEvent('idle');
assert.equal(c.S.speech,null,'oynatma bitince sesli sunum izi kalkar');
assert.equal(marked(),'','işaretlenen satır boşta bırakılmaz');
c.speechStateEvent('thinking');
assert.equal(c.S.speech,null,'beklenmedik durum olayı izi geri getirmez');

// Bağlantı kontrolleri: kod gerçekten bu yardımcıları kullanıyor, data attribute ile yetinmiyor.
assert(src.includes("class=\"turn${speechClassFor(m)}\" data-speaker=\"jarvis\" data-rid=\"${esc(m.rid||'')}\""),'yanıt satırı istek kimliğiyle çizilmeli');
assert(/else if\(k==='speech'\)\{speechEvent\(m\);return\}/.test(src),'speech olayı yardımcıya bağlanmalı');
assert(src.includes('speechStateEvent(S.orb)'),'durum olayı izi kapatmaya bağlanmalı');
assert(!src.includes('dataset.speechGoal'),'data attribute tek başına sesli sunum kanıtı değildir');
const css=fs.readFileSync(path.join(root,'webui/home-console.css'),'utf8');
assert(css.includes('.turn.saying .message-body'),'görünür vurgu stili bulunmalı');
for(const line of block.split('\n'))
  assert(!/\bfocus\(\)|window\.open|SetForegroundWindow/.test(line),'sesli sunum izi kullanıcı penceresini öne almaz');
console.log('OK voice speech highlight behavior');
