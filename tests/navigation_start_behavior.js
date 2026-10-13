const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
const S={ui:{},sset:'ai',snap:{study:{mode:'teacher'}},sov:{today:{target:{topic:'Hücre',mk:'bio',course:'Biyoloji'}}}},ACT={},PAGES={},input={value:''};
const calls=[];
const c={S,ACT,PAGES,ic:()=>'',drawSettings:()=>{},loadUi:async()=>{},go:page=>calls.push(['page',page]),$:()=>input};
vm.createContext(c);
vm.runInContext(src.slice(src.indexOf('const SECS='),src.indexOf('\n',src.indexOf('const sectionOf='))),c);
vm.runInContext(src.slice(src.indexOf('PAGES.settings='),src.indexOf('async function loadUi(')),c);
// eski Ayarlar sayfası kalktı: adres menüye yönlenir
for(const oldTab of ['ai','baglanti']){
 S.sset=oldTab;const page={innerHTML:''};calls.length=0;PAGES.settings(page);
 assert.equal(S.sset,oldTab);assert.equal(page.innerHTML,'','sayfa artık çizilmez');assert.deepEqual(calls.pop(),['page','settings'],'go(settings) çağrılır, menüde yan sayfa açılır');
}
S.sset='ses';PAGES.settings({});assert.equal(S.sset,'ses');calls.length=0;
vm.runInContext(src.slice(src.indexOf('function openAiHub('),src.indexOf('\n',src.indexOf('ACT.keysetup='))),c);
ACT.keysetup();assert.equal(S.sset,'baglanti');assert.equal(S.tool,'aihub');assert.deepEqual(calls.pop(),['page','tools']);
ACT.slearn=async e=>calls.push(['lesson',e.dataset.t,e.dataset.k]);ACT.studyask=async()=>calls.push(['source',input.value]);
ACT.sqnext=async()=>calls.push(['quiz',S.sqf]);c.render=()=>{};c.toast=(m)=>calls.push(['notice',m]);
vm.runInContext(src.slice(src.indexOf('ACT.studystart='),src.indexOf('ACT.studyask=',src.indexOf('ACT.studystart='))),c);
(async()=>{
 await ACT.studystart();assert.deepEqual(calls.pop(),['lesson','Hücre','bio']);
 input.value='Çalışmaya başla';await ACT.studystart();assert.deepEqual(calls.pop(),['lesson','Hücre','bio']);
 input.value='Hücre konusunu anlat';await ACT.studystart();assert.deepEqual(calls.pop(),['lesson','Hücre','bio']);
 S.snap.study.mode='source';await ACT.studystart();assert.deepEqual(calls.pop(),['source','']);
 input.value='Bu paragrafı açıkla';await ACT.studystart();assert.deepEqual(calls.pop(),['source','Bu paragrafı açıkla']);
 S.snap.study.mode='exam';await ACT.studystart();assert.deepEqual(calls.pop(),['quiz','bio§Hücre']);assert.equal(S.stab,'quiz');
 S.snap.study.mode='math';input.value='2x + 4 = 10';await ACT.studystart();assert.deepEqual(calls.pop(),['source','2x + 4 = 10']);
 input.value='';await ACT.studystart();assert.equal(calls.pop()[0],'notice');
 S.studyBusy=true;await ACT.studystart();assert.equal(calls.length,0);
 console.log('Ayarlar yönlendirmesi, bağlantı kısayolu ve konu/kaynak çalışma başlangıcı geçti.');
})().catch(e=>{console.error(e);process.exitCode=1});
