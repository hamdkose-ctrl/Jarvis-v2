const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const ROOT=path.join(__dirname,'..');
const strip=require(path.join(ROOT,'webui','activity_strip.js'));

const items=new Map();
for(let i=1;i<=7;i++)items.set('s'+i,{t:'İşlem '+i,s:i===7?'working':i===6?'error':'done',d:i===6?'x'.repeat(120):'ayrıntı '+i});
const steps={r1:{ts:10,items}};
const last=strip.activityItems(steps,'r1');
assert.deepStrictEqual(last.map(x=>x.text),['İşlem 4','İşlem 5','İşlem 6','İşlem 7']);
assert.deepStrictEqual(last.map(x=>x.status),['done','done','error','working']);
assert.strictEqual(last[2].detail.length,80);
assert.strictEqual(last[0].detail,'ayrıntı 4');

const hidden=strip.stripState({working:false},steps);
assert.strictEqual(hidden.visible,false);
assert.strictEqual(hidden.stoppable,false);
assert.deepStrictEqual(strip.stripState({working:true},steps),{visible:true,label:'İşlem 7',stoppable:true});
const more={a:{ts:1,items:new Map([['a',{t:'Eski çalışan',s:'working',d:''}]])},b:{ts:2,items:new Map([['b',{t:'Yeni çalışan',s:'working',d:''}]])}};
assert.strictEqual(strip.stripState({working:true},more).label,'Yeni çalışan');

const nx=fs.readFileSync(path.join(ROOT,'webui','nx.js'),'utf8');
const hit=nx.match(/ACT\.stoptask=async\(\)=>\{[\s\S]*?\n?\};/);
assert(hit,'ACT.stoptask bulunamadı');
async function runStop(result){
  const notices=[];
  const ctx={ACT:{},tryApi:async name=>{assert.strictEqual(name,'stop_task');return result},toast:m=>notices.push(m)};
  vm.runInNewContext(hit[0],ctx);
  await ctx.ACT.stoptask();
  return notices;
}
(async()=>{
  assert((await runStop(null)).includes('Durdurma bu sürümde yok.'));
  assert((await runStop(undefined)).includes('Durdurma bu sürümde yok.'));
  assert((await runStop({stopped:true,msg:'Görev durduruldu.'})).includes('Görev durduruldu.'));
  console.log('OK activity strip behavior');
})().catch(e=>{console.error(e);process.exit(1)});
