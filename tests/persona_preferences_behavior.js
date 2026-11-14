const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
const calls=[];const controls=[];
const c={S:{snap:{user:{slug:'alice'}}},ACT:{},esc:s=>String(s).replaceAll('<','&lt;').replaceAll('"','&quot;'),
  sbox:(i,t,d,b)=>t+d+b,field:(label,select,description)=>label+select+description,
  api:async(...args)=>calls.push(args),sAfter:x=>x,toast:()=>{}};
vm.createContext(c);vm.runInContext(src.slice(src.indexOf('function personaPreferencesBox('),src.indexOf('// Persona controls end.')),c);
const data={owner:'alice',controls:[{key:'verbosity',label:'Yanıt uzunluğu',options:['kısa','orta','uzun'],selected:'uzun',effective:'uzun',source_label:'Açık tercihin',has_learned:true}]};
const html=c.personaPreferencesBox(data);
assert(c.personaPreferencesBox(null).includes('yeniden dene'),'read failure is visible');
assert(html.includes('value="uzun" selected'));assert(html.includes('Açık tercihin'));assert(html.includes('Öğrenilmiş öneriyi unut'));
assert.equal(c.personaPreferencesBox({...data,owner:'bob'}),'','late response cannot expose another owner');
assert(c.personaPreferencesBox({...data,controls:[{...data.controls[0],label:'<script>'}]}).includes('&lt;script>'));
controls.push({dataset:{owner:'alice',personaKey:'verbosity'},value:'kısa'});
c.bindPersonaPreferences({querySelectorAll:()=>controls});
(async()=>{
  await controls[0].onchange();assert.deepEqual(calls.pop(),['pref_set','verbosity','kısa']);
  controls[0].value='';await controls[0].onchange();assert.deepEqual(calls.pop(),['pref_set','verbosity',null]);
  await c.ACT.personaforget({dataset:{owner:'alice',k:'verbosity'}});assert.deepEqual(calls.pop(),['presentation_reset','verbosity','learned']);
  c.S.snap.user.slug='bob';await controls[0].onchange();await c.ACT.personaforget({dataset:{owner:'alice',k:'verbosity'}});
  assert.equal(calls.length,0,'stale controls must not change the new owner');
  assert(src.includes("pv=await api('presentation_preferences')"));assert(src.includes('bindPersonaPreferences(el);'));
  console.log('Persona: tercih seçimi/silme, öğrenilmiş öneri temizliği, kaynak gösterimi ve geç kullanıcı cevabı sınırları geçti.');
})().catch(error=>{console.error(error);process.exitCode=1});
