'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');
const start=source.indexOf('// HARITA START'),end=source.indexOf('// HARITA END');
const calls=[],notices=[];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const context={PAGES:{},ACT:{},esc,ic:()=>'',menuOrbSvg:()=>'',toast:(...args)=>notices.push(args),console,
  tryApi:async(...args)=>{calls.push(JSON.parse(JSON.stringify(args)));return context.reply}};
vm.createContext(context);
vm.runInContext(source.slice(start,end)+'\nglobalThis.H={harita_render,harita_wizard_payload,harita_wizard_save,harita_wizard_reset,harita_wizard_search};',context);
const H=context.H;
const html=H.harita_render({tools:[],placeholders:[]});
assert(html.includes('Araç ekle'));
assert(html.includes('type="password"'));
assert(html.includes('local_destructive'));
assert(!html.includes('<option value="money_credential"'));
assert(!html.includes('<option value="system_config"'));

function form(kind='program'){
 const values={kind,query:'weather',candidate:'abcdef0123456789',endpoint:'https://example.com/data',parameters:'{}',
  program_name:'Test <tool>',program:'/usr/bin/example',arguments:'["--text","{text}"]',action_class:'local_destructive',
  device_name:'Device',address:'http://127.0.0.1/device',key:'fake-key',allow_private:false};
 const fields=Object.fromEntries(Object.entries(values).map(([name,value])=>[name,{value,checked:value===true}]));
 const review={textContent:'',innerHTML:''},confirm={disabled:true},candidate={innerHTML:''};
 return {fields,review,confirm,isConnected:true,
  querySelector(selector){if(selector==='.harita-review')return review;if(selector==='.harita-confirm')return confirm;
   if(selector==='[name="candidate"]')return Object.assign(fields.candidate,{set innerHTML(v){candidate.innerHTML=v},get innerHTML(){return candidate.innerHTML}});
   return fields[selector.match(/name="([^"]+)"/)?.[1]]||null},
  closest(){return null}};
}

(async()=>{
 const f=form();calls.length=0;
 await H.harita_wizard_save(f,true);
 assert.equal(calls.length,0,'Önizlemesiz kayıt yapılamaz');
 context.reply={state:'approval',text:'<img src=x onerror=alert(1)>',owner:'alice'};
 await H.harita_wizard_save(f,false);
 assert.deepEqual(calls[0],['tool_wizard_add','program',{name:'Test <tool>',program:'/usr/bin/example',arguments:['--text','{text}'],action_class:'local_destructive'},false,null]);
 assert.equal(f.review.textContent,context.reply.text);
 assert.equal(f.review.innerHTML,'');
 assert.equal(f.confirm.disabled,false);
 f.fields.program.value='/changed';
 calls.length=0;await H.harita_wizard_save(f,true);assert.equal(calls.length,0,'Değişen veri eski onayı kullanamaz');
 f.fields.program.value='/usr/bin/example';
 await H.harita_wizard_save(f,false);
 context.reply={state:'done',id:'custom_test'};calls.length=0;
 await H.harita_wizard_save(f,true);
 assert.equal(calls[0][3],true);assert.equal(calls[0][4],'alice');
 assert.equal(f.confirm.disabled,true);

 for(const kind of ['api','device']){
  const g=form(kind);context.reply={state:'approval',text:'Önizleme',owner:'alice'};calls.length=0;
  await H.harita_wizard_save(g,false);
  assert.equal(calls[0][1],kind);
  assert.equal(calls[0][3],false);
  if(kind==='api')assert.deepEqual(calls[0][2],{candidate:'abcdef0123456789',endpoint:'https://example.com/data',parameters:{}});
  else {assert.equal(calls[0][2].allow_private,false);assert.equal(calls[0][2].key,'fake-key')}
  context.reply={state:'done',id:'custom_other'};calls.length=0;
  await H.harita_wizard_save(g,true);
  assert.equal(calls[0][3],true);assert.equal(g.fields.key.value,'');
 }

 const bad=form();bad.fields.arguments.value='not JSON';calls.length=0;
 await H.harita_wizard_save(bad,false);assert.equal(calls.length,0);
 bad.fields.arguments.value='[]';bad.fields.action_class.value='money_credential';
 await H.harita_wizard_save(bad,false);assert.equal(calls.length,0);
 const old=form();context.reply={state:'approval',text:'No owner'};
 await H.harita_wizard_save(old,false);assert.equal(old.confirm.disabled,true);
 const rejected=form();context.reply=null;await H.harita_wizard_save(rejected,false);assert.equal(rejected.confirm.disabled,true);
 context.reply={state:'error',detail:'User changed'};await H.harita_wizard_save(rejected,false);assert.equal(rejected.confirm.disabled,true);
 const search=form('api');context.reply={candidates:[{id:'id"x',name:'<script>evil</script>',url:'https://example.com'}]};
 await H.harita_wizard_search(search);
 assert(search.fields.candidate.innerHTML.includes('&lt;script&gt;'));
 assert(!search.fields.candidate.innerHTML.includes('<script>'));
 console.log('harita wizard behavior ok');
})().catch(error=>{console.error(error);process.exitCode=1});
