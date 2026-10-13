const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
const nodes={},$=id=>nodes[id]||(nodes[id]={value:'',innerHTML:''});
const S={snap:{user:{slug:'alice'},llm:{provider:'gemini'}},ui:{provider:'gemini'}},SX={},ACT={};let calls=[],approve=false;
const c={S,SX,ACT,$,console,esc:x=>String(x||''),sbox:(a,b,c,d)=>d,srow:()=>'',field:(a,b)=>b,inp:(id,ph,val)=>`<input id="${id}" value="${val||''}">`,pad18:x=>x,ask:async()=>approve,api:async(name,...args)=>{calls.push([name,...args]);return {ok:true,msg:'Kaydedildi',models:[{id:'account-model',name:'Model'}]}},loadUi:async()=>{},refresh:async()=>{},drawSettings:()=>{},toast:()=>{}};
vm.createContext(c);
vm.runInContext(src.slice(src.indexOf('function paidProviderBoxes('),src.indexOf('const msgOf=r=>')),c);
(async()=>{
const el={dataset:{provider:'openai',v:'openai'}};
$('#paid-openai-key').value='test-secret';$('#paid-openai-model').value='account-model';
await ACT.paidsave(el);assert.equal(calls.length,1);assert.equal(calls[0][0],'paid_provider_save');assert.equal($('#paid-openai-key').value,'');
calls=[];await ACT.paidmode(el);assert.equal(calls.length,0);
approve=true;await ACT.paidmode(el);assert.deepEqual(calls[0],['llm_set','openai','','']);
calls=[];approve=false;await ACT.paidactivate(el);assert.equal(calls.length,0);
calls=[];approve=true;await ACT.paidactivate(el);assert(calls.some(x=>x[0]==='llm_set'&&x[2]==='account-model'));
const markup=c.paidProviderBoxes({user:{name:'Alice'},llm:{paid:{openai:{key:true,model:'account-model'}}}});assert(markup.includes('data-act="paidactivate"'));assert(!markup.includes('test-secret'));
console.log('Ücretli sağlayıcı UI: kaydetme ayrı, etkinleştirme onaylı, iptal hiçbir sağlayıcı değiştirmiyor, anahtar alanı temizleniyor.');
})().catch(e=>{console.error(e);process.exit(1)});
