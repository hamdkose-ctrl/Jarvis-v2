const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const src=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8');
const c={esc:s=>String(s??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]))};
vm.createContext(c);
vm.runInContext(src.slice(src.indexOf('function chatImageHtml('),src.indexOf('function mathBasic(')),c);
const data='data:image/svg+xml;base64,PHN2Zy8+';
let saved=`Tasarım\n\n![Jarvis](${data})`;
// The actual markdown renderer receives the same durable history text after refresh.
assert(c.md(saved).includes(`<img src="${data}"`));
assert(c.md(JSON.parse(JSON.stringify({text:saved})).text).includes('chatimage'));
assert(c.md('![x](javascript:alert)').includes('x'));assert(!c.md('![x](javascript:alert)').includes('<img'));
assert(!c.md('![x](file:///secret.png)').includes('<img'));
assert(c.md('```python\n![example](https://example.com/a.png)\n```').includes('<code>![example]'));
assert(!c.md('```python\n![example](https://example.com/a.png)\n```').includes('<img'));
assert(c.md('![Kaynak](https://example.com/a.png)').includes('https://example.com/a.png'));
assert(!c.md('![<script>](https://example.com/a.png)').includes('<script>'));
assert(c.md('**Kalın**\n```python\nprint(1)\n```').includes('<b>Kalın</b>'));
assert(src.includes("'geliştirme modunu aç'"));assert(src.includes("'değişiklikleri uygula'"));
console.log('Geliştirme: kalıcı görsel Markdown, yenileme sonrası önizleme, güvenli kaynak ve sohbet komutları geçti.');

(async()=>{
 const input={value:'Bu hatayı düzelt',focus(){}};
 const notices=[];
 const p={S:{page:'chat',snap:{user:{name:'alice'}}},ACT:{},
  File:class{constructor(parts,name,options){this.name=name;this.type=options.type;this.parts=parts}},
  document:{addEventListener(){}},$:()=>input,drawAtt(){},toast:x=>notices.push(x),
  upload:async()=>({path:'C:/Jarvis/ekran.png'})};
 vm.createContext(p);
 vm.runInContext(src.slice(src.indexOf('async function attachChatFile('),src.indexOf('function pickAttach(')),p);
 let prevented=0;
 const image={type:'image/png'};
 const event={target:{matches:()=>true},preventDefault(){prevented++},
  clipboardData:{items:[{kind:'file',type:'image/png',getAsFile:()=>image}]}};
 await p.pasteChatImage(event);
 assert.equal(prevented,1);assert.equal(p.S.att[0].path,'C:/Jarvis/ekran.png');
 assert.equal(input.value,'Bu hatayı düzelt');assert.match(p.S.att[0].name,/^ekran-\d+\.png$/);
 await p.pasteChatImage({...event,clipboardData:{items:[{kind:'string',type:'text/plain'}]}});
 assert.equal(prevented,1); // ordinary text keeps native paste behavior
 await p.pasteChatImage(event);assert.equal(p.S.att.length,2); // several attachments are kept together
 p.S.att=[];p.upload=async()=>undefined;
 await p.pasteChatImage(event);assert.deepEqual(p.S.att,[]);assert.equal(p.S.attPending,0);
 let finish;p.upload=()=>new Promise(resolve=>{finish=resolve});
 const pending=p.pasteChatImage(event);assert.equal(p.S.attPending,1);
 p.say=()=>{throw new Error('Must not send during upload')};
 vm.runInContext(src.slice(src.indexOf('ACT.send='),src.indexOf('ACT.mic=',src.indexOf('ACT.send='))),p);
 p.ACT.send({closest:()=>({querySelector:()=>input})});assert.equal(input.value,'Bu hatayı düzelt');
 const handlers={};p.document.addEventListener=(name,fn)=>{handlers[name]=fn};
 vm.runInContext(src.slice(src.indexOf("document.addEventListener('keydown',e=>"),src.indexOf('// ======================================================================= arayüze uygun')),p);
 handlers.keydown({key:'Enter',target:{value:input.value,matches:()=>true},preventDefault(){}});
 p.S.snap.user.name='bob';finish({path:'C:/Jarvis/alice.png'});await pending;
 assert.deepEqual(p.S.att,[]);assert.equal(p.S.attPending,0);
 p.S.page='files';await p.pasteChatImage(event);assert.equal(p.S.attPending,0);
 console.log('Geliştirme: pano görseli, metin koruma, yükleme hatası, gönderme bekletme ve kullanıcı değişimi geçti.');
})().catch(error=>{console.error(error);process.exitCode=1});
