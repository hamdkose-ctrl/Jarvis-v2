const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8').replace(/\r\n/g,'\n');
const S={snap:{user:{name:'A',slug:'a'}},page:'chat',hist:[{id:'old',role:'assistant',text:'lost response'}],live:[],waiting:true,orb:'idle'};
let streams=[],draws=0;
class EventSource{constructor(){streams.push(this)}close(){this.closed=true}}
const c={S,EventSource,TOKEN:'token',encodeURIComponent,console,refresh:async()=>{},tryApi:async()=>[{id:'old',role:'assistant',text:'lost response'}],onEvent:m=>{if(!S.hist.some(r=>r.id===m.mid))S.live.push(m)},drawMsgs:()=>draws++,drawConvs:()=>draws++,setTimeout:()=>{},Date};vm.createContext(c);
vm.runInContext(source.slice(source.indexOf('function connect(){'),source.indexOf('\n\n// ',source.indexOf('function connect(){'))),c);
(async()=>{
 c.connect();const a=streams[0];const ready=a.onopen();a.onmessage({data:JSON.stringify({mid:'old',k:'assistant',t:'lost response'})});await ready;
 assert.equal(S.hist[0].text,'lost response');assert.equal(S.live.length,0);assert.equal(S.waiting,false);
 a.onerror();assert(a.closed);c.connect();await streams[1].onopen();assert.equal(streams.length,2);assert.equal(draws,2);
 // Real user-switch refresh must erase A's caches before B appears.
 let clearedNoteImage=false;const rc={ACT:{ntimageclear(){clearedNoteImage=true}},document:{querySelectorAll:()=>[]},S:{snap:{user:{name:'A'}},hist:[{text:'SECRET-A'}],live:[{text:'SECRET-A'}],chat:[{}],page:'chat'},api:async()=>({user:{name:'B'},study:{}}),loadHist:async function(){rc.S.hist=[]},render:()=>{},dockState(){},renderTop(){},updateHome(){},renderRail(){},drawSide(){},drawDevelopment(){},$:()=>null,toast(){},clearTimeout(){},setTimeout(){}};
 vm.createContext(rc);vm.runInContext(source.slice(source.indexOf('async function refresh(){'),source.indexOf('\nlet rt=',source.indexOf('async function refresh(){'))),rc);await rc.refresh();assert.equal(rc.S.live.length,0);assert.equal(rc.S.hist.length,0);assert.equal(rc.S.chat.length,0);assert.equal(rc.S.noteText,'');assert(clearedNoteImage);
 // A synchronous stop has no assistant event; release the chat's waiting indicator.
 const sendState={page:'chat',live:[],waiting:false};let sendError='';
 const sc={S:sendState,Date,drawMsgs(){},toast:m=>{sendError=m},api:async()=>false};vm.createContext(sc);
 vm.runInContext(source.slice(source.indexOf('async function say(text, keepWorkspace=false){'),source.indexOf('\nACT.send=',source.indexOf('async function say(text, keepWorkspace=false){'))),sc);
 await sc.say('dur');assert.equal(sendState.waiting,false);
 sc.api=async()=>true;await sc.say('merhaba');assert.equal(sendState.waiting,true);
 sc.api=async()=>{throw Error('queue rejected')};await sc.say('tekrar');assert.equal(sendState.waiting,false);assert.equal(sendError,'queue rejected');
 console.log('Bağlantı: kalıcı yanıt uzlaştırması, profil önbelleği, doğrudan durdurma ve kuyruk reddi kontrolleri geçti.');
})().catch(e=>{console.error(e);process.exit(1)});
