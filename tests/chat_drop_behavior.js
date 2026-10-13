const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const src=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');
function load(c,a,b){vm.runInContext(src.slice(src.indexOf(a),src.indexOf(b,src.indexOf(a))),c)}
const esc=x=>String(x??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const file=(name,size=10)=>({name,size,type:'application/pdf'});
const fileItem=(f,dir=false)=>({kind:'file',getAsFile:()=>f,webkitGetAsEntry:()=>({isDirectory:dir})});
function dropEvent(items,{types=['Files'],text='',prevented=false,target={}}={}){
 const e={defaultPrevented:prevented,target,prevented:0,preventDefault(){this.prevented++;this.defaultPrevented=true},
  dataTransfer:{types,items,files:items.map(i=>i.getAsFile?.()).filter(Boolean),getData:t=>t==='text/plain'?text:'',dropEffect:''}};
 return e;
}
(async()=>{
 // Drag and drop: files join the chat attachments instead of opening in a new browser tab.
 const handlers={},notices=[],uploads=[],input={value:'',focus(){}};
 const c={S:{page:'study',att:[],attPending:0,snap:{user:{name:'Hamdi'}}},ACT:{},esc,ic:()=>'',ymd:()=>'2026-10-10',
  document:{addEventListener:(n,f)=>{handlers[n]=f},body:{appendChild(){}},createElement:()=>({})},
  $:s=>s==='.ask input'?input:null,$$:()=>[],drawAtt(){},go(p){c.S.page=p},toast:(m)=>notices.push(m),
  upload:async f=>{uploads.push(f.name);return {path:'C:/Users/H/Documents/Jarvis Dosyaları/'+f.name}}};
 vm.createContext(c);
 load(c,'async function attachChatFile(','function pickAttach(');
 const over=dropEvent([fileItem(file('a.pdf'))]);handlers.dragover(over);assert.equal(over.prevented,1);
 assert.equal(over.dataTransfer.dropEffect,'copy');
 const drop=dropEvent([fileItem(file('a.pdf')),fileItem(file('b.xlsx')),fileItem(file('klasor'),true)]);
 handlers.drop(drop);assert.equal(drop.prevented,1);
 await new Promise(r=>setTimeout(r,0));await new Promise(r=>setTimeout(r,0));
 assert.deepEqual(uploads,['a.pdf','b.xlsx']);assert.equal(c.S.att.length,2);assert.equal(c.S.page,'chat');
 assert(notices.some(m=>m.includes('Klasör eklenemez')));
 // A drop zone that already handled the files (e.g. Math) is not uploaded twice.
 handlers.drop(dropEvent([fileItem(file('math.png'))],{prevented:true}));await new Promise(r=>setTimeout(r,0));
 assert.equal(uploads.length,2);
 // Empty, oversized and over-limit files are refused with a message.
 await c.attachChatFile(file('bos.pdf',0));await c.attachChatFile(file('dev.pdf',250_000_000));
 assert.equal(uploads.length,2);assert(notices.some(m=>m.includes('boş')));assert(notices.some(m=>m.includes('200 MB')));
 for(let i=0;i<12;i++)await c.attachChatFile(file('f'+i+'.pdf'));
 assert.equal(c.S.att.length,10);assert(notices.some(m=>m.includes('En fazla 10')));
 // Dropped link or text lands in the message box instead of navigating the window away.
 const textDrop=dropEvent([],{types:['text/plain'],text:'https://ornek.com/rapor'});handlers.drop(textDrop);
 await new Promise(r=>setTimeout(r,0));assert.equal(textDrop.prevented,1);assert.equal(input.value,'https://ornek.com/rapor');
 // Text dragged onto an input keeps the native behavior.
 const editOver=dropEvent([],{types:['text/plain'],target:{closest:()=>({})}});handlers.dragover(editOver);assert.equal(editOver.prevented,0);

 // Several attachments: one request carrying every path, the bubble text matches the server echo.
 const sent=[];const s={S:{page:'chat',att:[{path:'C:/x/a.pdf',name:'a.pdf'},{path:'C:/x/b.pdf',name:'b.pdf'}],attPending:0,live:[]},
  atts:()=>s.S.att,drawAtt(){},drawMsgs(){},go(){},ymd:()=>'',toast(){},api:async(n,t)=>{sent.push([n,t]);return true}};
 vm.createContext(s);load(s,'async function say(text){','ACT.send=');
 await s.say('özetle');
 assert.deepEqual(sent.map(x=>x[1]),['"C:/x/a.pdf" "C:/x/b.pdf" özetle']);assert.equal(s.S.att.length,0);
 assert.deepEqual(s.S.live.map(m=>m.text),['"C:/x/a.pdf" "C:/x/b.pdf" özetle']);
 s.S.att=[{path:'C:/x/c.pdf',name:'c.pdf'}];await s.say('');
 assert.equal(sent.at(-1)[1],'"C:/x/c.pdf" dosyasını kapsamlı analiz et');

 // Visible steps: one card per request, updated in place from working to done/error.
 const p={S:{page:'chat',steps:{},live:[]},esc,drawMsgs(){},loadPcMute(){p.muteLoads=(p.muteLoads||0)+1},Map};
 vm.createContext(p);load(p,'function stepsHtml(','const extOf=');
 p.onStep({k:'step',t:'Ses yüzde 30 yapılıyor',x:'working|s1|',rid:'r1',ts:5});
 p.onStep({k:'step',t:'Ses yüzde 30 yapılıyor',x:'done|s1|',rid:'r1',ts:5.1});
 p.onStep({k:'step',t:'“Paint” açılıyor',x:'error|s2|Uygulama bulunamadı',rid:'r1',ts:5.2});
 assert.equal(p.S.live.length,1);assert.equal(p.S.steps.r1.items.size,2);
 const card=p.stepsHtml(p.S.steps.r1);assert(card.includes('✓'));assert(card.includes('✗'));assert(card.includes('Uygulama bulunamadı'));
 p.onStep({k:'step',t:'Bilgisayarın sesi kapatılıyor',x:'done|s3|',rid:'r2'});assert.equal(p.muteLoads,1);

 // Voice requests are labelled with what Jarvis understood.
 const m={S:{snap:{user:{name:'Hamdi'}},steps:{}},esc,ic:()=>'',md:x=>esc(x),hm:()=>'10:00',Map};
 vm.createContext(m);load(m,'function msgHtml(m){','const extOf=');
 m.extOf=x=>x.split('.').pop();m.catOf=()=>'pdf';
 assert(m.msgHtml({role:'user',text:'sesi yüzde 30 yap',src:'ses',ts:1}).includes('Anladığım'));
 assert(!m.msgHtml({role:'user',text:'merhaba',src:'yazı',ts:1}).includes('Anladığım'));
 // Several files in one message: a chip per file and only the instruction as text.
 const multi=m.msgHtml({role:'user',text:'"C:/x/a.pdf" "C:/x/b.xlsx" önemli yerleri tablo yap',ts:1});
 assert.equal((multi.match(/class="fchip"/g)||[]).length,2);assert(multi.includes('Önemli yerleri tablo yap'));assert(!multi.includes('C:/x/b.xlsx'));

 // PC mute is separate from "Jarvis'i sustur" and reaches the bridge.
 const calls=[];const b={S:{page:'chat',snap:{flags:{mic:true,speak:true}},pcMuted:false},ACT:{},ic:n=>n,$$:()=>[],toast(){},
  tryApi:async(n,...a)=>{calls.push([n,...a]);return {muted:true}},api:async()=>({muted:false})};
 vm.createContext(b);load(b,"const micToggleBtn=","const DOCK_PH=");
 const btn=()=>vm.runInContext('pcMuteBtn()',b);assert(btn().includes('Bilgisayarın tüm sesini kapat'));
 await b.ACT.pcmute();assert.deepEqual(calls[0],['pc_mute',true]);assert.equal(b.S.pcMuted,true);
 assert(btn().includes('speakerx'));assert(vm.runInContext('muteBtn()',b).includes('data-act="mute"'));
 console.log('Sohbet: sürükle-bırak, çoklu ek, klasör/boyut sınırı, bağlantı bırakma, adım kartı, sesli komut etiketi ve bilgisayar sesi geçti.');
})().catch(e=>{console.error(e);process.exit(1)});
