const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
const S={snap:{user:{slug:'alice'},llm:{provider:'auto'}},sset:'baglanti'},SX={},ACT={},nodes={};let calls=[],draws=0;
const c={S,SX,ACT,$:id=>nodes[id]||(nodes[id]={value:'',checked:false}),api:async(name,...args)=>{calls.push([name,...args]);return name==='smart_router_status'?{model:'openrouter/free',key:true}:{msg:'saved',status:{model:'openrouter/free'}}},sbox:(a,b,c,d)=>d,field:(a,b)=>b,inp:(id,p,v)=>`<input id="${id}" value="${v||''}">`,pad18:x=>x,drawSettings:()=>draws++,toast:()=>{},refresh:async()=>{},say:()=>{},esc:x=>String(x||'')};
vm.createContext(c);vm.runInContext(src.slice(src.indexOf('function routerBox('),src.indexOf('async function setUi(')),c);
S.ui={ai_mode:'auto'};S.snap.llm.provider='gemini';const modes=c.modes();assert(modes.includes('mode on\" data-act=\"sval\" data-k=\"ai_mode\" data-v=\"gemini\"'));assert(!modes.includes('mode on\" data-act=\"sval\" data-k=\"ai_mode\" data-v=\"auto\"'));S.snap.llm.provider='auto';
(async()=>{
 c.routerBox();await new Promise(r=>setImmediate(r));assert.equal(SX.router.model,'openrouter/free');assert.equal(draws,1);
 nodes['#rk']={value:'private'};nodes['#rm']={value:'openrouter/free'};nodes['#rfree']={checked:true};calls=[];
 await ACT.routersave();assert.deepEqual(calls[0],['smart_router_save','private','openrouter/free',null]);assert.equal(nodes['#rk'].value,'');
 S.sset='ai';const automatic=c.routerBox();assert(!automatic.includes('id="rk"'));assert(automatic.includes('id="rfree"'));calls=[];await ACT.routerpolicy();assert.deepEqual(calls[0],['smart_router_save','',null,true]);S.sset='baglanti';assert(!c.routerBox().includes('id="rfree"'));
 S.snap.user.slug='bob';c.routerBox();assert.equal(SX.routerOwner,'bob');assert.equal(SX.router,null);await new Promise(r=>setImmediate(r));
 assert(!c.routerBox().includes('private'));
 console.log('Smart Router UI: ücretsiz hesap seçimi, anahtar temizleme, kullanıcı değişiminde durum yenileme geçti.');
})().catch(e=>{console.error(e);process.exit(1)});
