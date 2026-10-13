'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../webui/nx.js'),'utf8').replace(/\r\n/g,'\n');
let requests=[],historyCalls=[],storage=new Map();
const location={pathname:'/',hash:'#key=private-key',search:''};
const context={URLSearchParams,encodeURIComponent,toast(){},location,history:{replaceState(...args){historyCalls.push(args);location.hash=''}},sessionStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)},fetch:async(url,options)=>{requests.push({url,options});return{ok:true,json:async()=>({ok:true,data:'passed'})}},Error};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('let TOKEN='),source.indexOf('const store=')),context);
vm.runInContext(source.slice(source.indexOf('async function api('),source.indexOf('async function tryApi(')),context);
(async()=>{
 assert.equal(await context.api('snapshot'),'passed');
 assert.equal(historyCalls[0][2],'/');
 assert.equal(storage.get('jt'),'private-key');
 assert.deepEqual(requests.map(x=>x.url),['/session','/api/snapshot']);
 for(const req of requests){assert(!req.url.includes('private-key'));assert.equal(req.options.headers['X-Jarvis-Token'],'private-key')}
 assert(source.includes("new EventSource('/events')"));
 assert(!source.includes('?t='));
 assert(!source.includes('&t='));
 vm.runInContext(source.slice(source.indexOf('async function upload(file,'),source.indexOf('async function doFile(')),context);
 assert.equal(await context.upload({name:'test.txt'},true),'passed');
 const request=requests.at(-1);
 assert.equal(request.url,'/upload?to=files&name=test.txt');
 assert.equal(request.options.headers['X-Jarvis-Token'],'private-key');
 console.log('Masaüstü erişimi: fragment temizliği, oturum kurulumu ve URL dışında anahtar taşıma geçti.');
})().catch(error=>{console.error(error);process.exit(1)});
