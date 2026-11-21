const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
const S={snap:{user:{slug:'alice'},llm:{provider:'auto'}}}, ACT={};
const SX={routerOwner:'alice',router:{
  gemini_scopes:['conversation'],
  ready_connections:{gemini:{state:'unchecked',configured:true},groq:{state:'ok',configured:true},cloudflare:{state:'quota',configured:true}},
  last_reply:{provider:'groq',model:'exact-model'}
}};
const nodes={'#ready-key':{value:'new-key'},'#rgchat':{checked:true},'#rgselected':{checked:false}};
const calls=[];
const c={
  S,SX,ACT,$:id=>nodes[id],api:async(name,...args)=>{calls.push([name,...args]);return {ok:true,msg:'saved'}},
  sbox:(icon,title,hint,body)=>title+hint+body,srow:(icon,title,description)=>title+description,
  field:(label,input)=>label+input,inp:(id,placeholder)=>`<input id="${id}" placeholder="${placeholder}">`,
  pad18:html=>html,drawSettings:()=>{},toast:()=>{},refresh:async()=>{},settingsOpen:()=>true,esc:value=>String(value||'')
};
vm.createContext(c);
vm.runInContext(src.slice(src.indexOf('const READY_LABELS='),src.indexOf('const AI_CARDS=')),c);
vm.runInContext(src.slice(src.indexOf('function routerBox('),src.indexOf('async function setUi(')),c);

(async()=>{
  assert.equal(c.readyBadge(S.snap,'gemini')[1],'Anahtar kayıtlı');
  assert.equal(c.readyBadge(S.snap,'groq')[1],'Yanıt verdi');
  assert.equal(c.readyBadge(S.snap,'cloudflare')[1],'Kota sınırı');
  const automatic=c.routerBox();
  assert(automatic.includes('Groq · exact-model'));
  assert(!/router-daily|router-parallel|rfree|kota grubu/.test(automatic));
  const gemini=c.readyProviderBox(S.snap,'gemini');
  assert(gemini.includes('Bağlantıyı dene')&&gemini.includes('id="rgchat"')&&gemini.includes('id="rgselected"'));
  assert(!c.readyProviderBox(S.snap,'groq').includes('rgchat'));
  assert(c.readyProviderBox(S.snap,'cloudflare').includes('cf-account'));
  await ACT.readySave({dataset:{provider:'gemini'}});
  assert.equal(JSON.stringify(calls[0]),JSON.stringify(['smart_router_save',['conversation'],'alice']));
  assert.deepEqual(calls[1],['router_ready_key_save','gemini','new-key','alice']);
  await ACT.readyCheck({dataset:{provider:'groq'}});
  assert.deepEqual(calls[2],['router_ready_check','groq','alice']);
  S.snap.user.slug='bob';
  assert(!c.routerBox().includes('exact-model'));
  assert.equal(c.readyBadge(S.snap,'groq')[1],'Durum alınamadı');
  assert(!c.readyProviderBox(S.snap,'gemini').includes('checked'));
  console.log('Router ayarları bağlantı durumunu, gerçek yanıtı, veri iznini ve kullanıcı ayrımını gösteriyor.');
})().catch(error=>{console.error(error);process.exit(1)});
