// §8: Görünür sesli sunum izi. Gerçek oynatma olayı dışında (kuyruk/sentez/WAV) hiçbir
// şey "konuşuyor" gibi işaretlenmez; geç kalan bir stage daha yeni konuşmayı söndürmez;
// vurgu yalnız DOM sınıfıdır, pencere öne alınmaz.
// F6: görev kartı "ilk kart" değildir — kart yalnız kendi iş kimliği seslendirildiğinde
// işaretlenir; kimlik aktivite kaydından çizime taşınır, seslendirme kimliğiyle karşılaştırılır.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),src=fs.readFileSync(path.join(root,'webui/nx.js'),'utf8');
const begin=src.indexOf('// SPEECH HIGHLIGHT START'),end=src.indexOf('// SPEECH HIGHLIGHT END');
assert(begin>=0&&end>begin,'sesli sunum izi yardımcıları bulunamadı');
const block=src.slice(begin,end);

// Küçük sahte DOM: satırlar ve görev kartı sınıfı gerçekten değiştirir.
function node(rid,goal){const set=new Set(),dataset={};if(rid)dataset.rid=rid;if(goal)dataset.goal=goal;
  return {dataset,set,classList:{toggle(c,on){on?set.add(c):set.delete(c)},contains:c=>set.has(c)}}}
let rows=[],task=null;
const fake$=sel=>sel==='#cside .task'?task:null;
const fake$$=sel=>sel==='.m.a'?rows:[];
const c={S:{speech:null},$:fake$,$$:fake$$};
vm.createContext(c);
vm.runInContext(block,c);
const id=(extra={})=>JSON.stringify({speech_id:'sp1',turn_id:'',goal_id:'',kind:'reply',...extra});
const say=(stage,extra)=>c.speechEvent({k:'speech',t:stage,x:id(extra)});
const marked=()=>rows.filter(r=>r.set.has('saying')).map(r=>r.dataset.rid).join(',');

// Kuyruk, sentez ve WAV hazırlığı konuşma değildir: playback_started öncesi hiçbir iz yok.
rows=[node('r1'),node('r2')];task=node();for(const stage of ['accepted','synthesizing','audio_ready'])say(stage,{turn_id:'r1'});
assert.equal(c.S.speech,null,'kuyruk/sentez/WAV hazırlığı sesli sunum değildir');
assert.equal(marked(),'','oynatma başlamadan satır işaretlenmez');
assert(!task.set.has('saying'),'oynatma başlamadan görev kartı işaretlenmez');

// Bozuk/eksiz yük yok sayılır, vurgu koymaz.
c.speechEvent({k:'speech',t:'playback_started',x:'{bozuk'});
assert.equal(c.S.speech,null,'bozuk olay yükü işaret üretmez');

// Gerçek oynatma başlangıcı: yalnız bu yanıt satırı işaretlenir.
say('playback_started',{turn_id:'r1'});
assert.equal(marked(),'r1','yalnız seslendirilen isteğin yanıtı vurgulanır');
assert.equal(c.speechClassFor({rid:'r1'}),' saying');
assert.equal(c.speechClassFor({rid:'r2'}),'','başka isteğin yanıtı sesli sunum değildir');
assert.equal(c.speechClassFor({}), '','kimlik taşımayan satır vurgulanmaz');
assert.equal(c.speechTaskClass(''),'','hedef kimliği olmayan seslendirme görev kartını işaretlemez');
assert.equal(c.speechTaskClass('g-7'),'','seslendirme hedef kimliği taşımıyorsa kart işaretlenmez');

// Hedef kimliği taşındığında kart VAKİT kendi işi söyleniyorken vurgulanır.
say('playback_started',{turn_id:'r2',goal_id:'g-7'});
assert.equal(marked(),'r2','yeni oynatma eski işaretin yerini alır');
assert(!task.set.has('saying'),'kimliksiz görev kartı rastgele bir hedef için işaretlenmez');
task=node(undefined,'g-7');
assert(!task.set.has('saying'),'çizimdeki kart sessizken işaret kendiliğinden doğmaz');
c.applySpeechHighlight();
assert(task.set.has('saying'),'kartın kendi işi seslendirildiğinde vurgu kartta görünür');
task=node(undefined,'g-8');c.applySpeechHighlight();
assert(!task.set.has('saying'),'başka işin kartı seslendirilen hedef için vurgulanmaz');
task=node(undefined,'g-7');

// Kayıt/çizim kimliği: kart "Görev <iş>" kaydından kendi iş numarasını taşır ve
// seslendirme o numarayı adlandırıyorsa (bitmiş görev bildirimi) kart vurgulanır.
assert.equal(c.taskGoalId({area:'Görev job-9 · tamamlandı'}),'job-9','kart iş kimliğini aktivite kaydından alır');
assert.equal(c.taskGoalId({area:'Son işlem'}),'','iş kimliği taşımayan kayıt kimlik uydurmaz');
assert.equal(c.taskGoalId(),'','kayıtsız çizim kimlik uydurmaz');
say('playback_started',{turn_id:'r2',event_id:'job-9'});
assert(c.speechTaskClass('job-9').includes('saying'),'kendi görev işi seslendirilen kart işaretlenir');
assert.equal(c.speechTaskClass('job-8'),'','başka işin kartı seslendirilen iş için vurgulanmaz');
assert.equal(c.speechTaskClass(''),'','kimlik taşımayan çizim hiçbir seslendirmeye boyanmaz');
task=node(undefined,'job-9');c.applySpeechHighlight();
assert(task.set.has('saying'),'bitmiş görevinin bildirimi kendi kartını işaretler');
task=node(undefined,'g-7');c.applySpeechHighlight();
assert(!task.set.has('saying'),'hedef kimliği olmayan kart iş bildirimiyle işaretlenmez');

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
assert(!task.set.has('saying'));
c.speechStateEvent('thinking');
assert.equal(c.S.speech,null,'beklenmedik durum olayı izi geri getirmez');

// Bağlantı kontrolleri: kod gerçekten bu yardımcıları kullanıyor, data attribute ile yetinmiyor.
assert(src.includes("class=\"m a${speechClassFor(m)}\" data-rid=\"${esc(m.rid||'')}\""),'yanıt satırı istek kimliğiyle çizilmeli');
assert(src.includes('class="task${speechTaskClass(goal)}" data-goal="${esc(goal)}"'),'görev kartı kendi iş kimliğiyle ve ona göre vurguyla çizilmeli');
assert(src.includes('const goal=taskGoalId(run||last)'),'kartın iş kimliği çizimdeki aktivite kaydından gelir');
assert(/else if\(k==='speech'\)\{speechEvent\(m\);return\}/.test(src),'speech olayı yardımcıya bağlanmalı');
assert(src.includes('speechStateEvent(S.orb)'),'durum olayı izi kapatmaya bağlanmalı');
assert(!src.includes('dataset.speechGoal'),'data attribute tek başına sesli sunum kanıtı değildir');
const css=fs.readFileSync(path.join(root,'webui/nx.css'),'utf8');
assert(css.includes('.m.a.saying .bb')&&css.includes('.task.saying'),'görünür vurgu stili bulunmalı');
for(const line of block.split('\n'))
  assert(!/\bfocus\(\)|window\.open|SetForegroundWindow/.test(line),'sesli sunum izi kullanıcı penceresini öne almaz');
console.log('OK voice speech highlight behavior');
