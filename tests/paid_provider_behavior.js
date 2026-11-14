const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
const nodes={},$=id=>nodes[id]||(nodes[id]={value:'',checked:false});
const S={snap:{user:{slug:'alice'},llm:{provider:'auto'}},ui:{}},SX={},ACT={};let calls=[],approve=false;
const c={S,SX,ACT,$,console,esc:x=>String(x||''),sbox:(a,b,c,d)=>d,field:(a,b)=>b,inp:(id,p,v)=>`<input id="${id}" value="${v||''}">`,pad18:x=>x,ask:async()=>approve,api:async(name,...args)=>{calls.push([name,...args]);return {ok:true,msg:'Kaydedildi',connection:{id:'a'.repeat(24)},models:[{id:'account-model',name:'Model'}]}},refresh:async()=>{},drawSettings:()=>{},toast:()=>{}};
vm.createContext(c);vm.runInContext(src.slice(src.indexOf('const ROUTER_ROLES='),src.indexOf('const msgOf=r=>')),c);
(async()=>{
const markup=c.routerConnectionsBox(S.snap);assert(markup.includes('custom-protocol'));assert(markup.includes('custom-paid'));assert(!markup.includes('test-secret'));assert.equal(calls.length,0,'opening form sends no generation');
for(const [id,value] of Object.entries({'name':'My API','url':'https://api.example.org/v1','protocol':'responses','model':'account-model','role':'conversation','billing':'paid','daily':'25','output':'4096','workspace':'','money':'','key':'test-secret'}))$('#custom-'+id).value=value;
$('#custom-paid').checked=true;$('#custom-enabled').checked=true;$('#custom-conversation').checked=true;
await ACT.customsave({disabled:false});assert.equal(calls.length,1);assert.equal(calls[0][0],'router_connection_save');assert.equal(calls[0][1].role,'conversation');assert.equal(calls[0][3],'alice');assert.equal($('#custom-key').value,'');assert(!calls.some(x=>x[0]==='llm_set'||x[0]==='router_connection_test'));
calls=[];await ACT.customtest();assert.equal(calls.length,0);approve=true;await ACT.customtest();assert.deepEqual(calls[0],['router_connection_test','a'.repeat(24),true,'alice']);
calls=[];await ACT.custommodels();assert.deepEqual(calls[0],['router_connection_models','a'.repeat(24),'alice']);assert.equal(SX.customModels[0].id,'account-model');
S.snap.user.slug='bob';c.routerConnectionsBox(S.snap);assert.equal(SX.customId,'');assert.equal(SX.customModels.length,0);
assert.equal(ACT.paidmode,undefined);assert.equal(ACT.paidactivate,undefined);
console.log('Özel API UI: ağsız kayıt/açılış, açık tek test, rol ve owner sınırı, anahtar temizleme geçti.');
})().catch(e=>{console.error(e);process.exit(1)});
