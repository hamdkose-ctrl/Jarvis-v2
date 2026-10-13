// Ana menü yan sayfa düzeni: düğmeye basınca orb sola kayar (docked), içerik sağda açılır, düğümden panele çizgi çizilir; kapanınca her şey geri gelir.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
const mkEl=()=>{const e={attrs:{},children:[],removed:false,setAttribute(k,v){e.attrs[k]=v},append(...x){e.children.push(...x)},remove(){e.removed=true}};return e};
const cls=()=>{const s=new Set();return {add:x=>s.add(x),remove:x=>s.delete(x),contains:x=>s.has(x),has:x=>s.has(x)}};
const panel={classList:cls()};let linkEl=null;
const svg={querySelector:s=>s==='#mn-link'?linkEl:null,getScreenCTM:()=>({inverse:()=>({})}),createSVGPoint:()=>({matrixTransform:()=>({x:700,y:200})}),append:g=>{linkEl=g}};
const focusCalls=[];const styleCalls=[];const scene={classList:cls(),clientWidth:1594,clientHeight:850,style:{removeProperty:k=>styleCalls.push(['remove',k]),setProperty:(k,v)=>styleCalls.push(['set',k,v])},_web:{pos:id=>id==='dosya'?{x:330,y:374}:null,focus:(ids,main)=>focusCalls.push([ids,main])},querySelector:s=>s==='#mn-svg'?svg:s==='#mn-link'?linkEl:s==='.mn-dock'?(scene.classList.contains('docked')&&panel.classList.contains('mn-dock')?panel:null):null,getBoundingClientRect:()=>({})};
panel.getBoundingClientRect=()=>({left:900,top:20,height:700});panel.offsetWidth=700;
const win={__mnLink:null,addEventListener(){}};
let closed=0;const c={drawMiniPreview(){},ACT:{mnclose(){closed++}},MENU_ROSTER:[['bilgi'],['dosya'],['ekran'],['chat'],['sistem']],MENU_ACT:{bilgi:['set','ekran'],dosya:['set','ekran'],ekran:['set','ekran'],chat:['go','chat'],sistem:['set','sistem']},window:win,document:{createElementNS:()=>mkEl()},$:s=>s==='.mnscene'?scene:null,setTimeout:f=>f(),Math,String};
vm.createContext(c);
vm.runInContext(src.slice(src.indexOf('function menuUndock('),src.indexOf('ACT.mnclose=')),c);
const card={closest:()=>scene,querySelector:()=>panel};
c.menuDock(card,['dosya','Dosyalar','doer']);
assert(scene.classList.contains('docked'),'orb ve ağ sola kayar');assert(panel.classList.contains('mn-dock'),'panel yan sayfa olur');assert.equal(win.__mnLink,'dosya');
assert(linkEl&&linkEl.children[0].attrs.d.startsWith('M330 374'),'çizgi seçilen düğümden başlar');assert.equal(linkEl.children[1].attrs.cx,700,'çizgi panelin kenarında biter');
assert.equal(JSON.stringify(focusCalls.at(-1)),JSON.stringify([['dosya'],'dosya']),'yalnız seçilen düğümün dalı parlar');
const k=styleCalls.filter(x=>x[0]==='set'&&x[1]==='--mnk').at(-1);assert(k&&+k[2]>0&&+k[2]<1,'orb ağın ölçeğiyle küçülür (yan sayfa açıkken)');
// başka düğüm: eski çizgi silinir, yenisi çizilir
const first=linkEl;win.__mnLink='dosya';c.menuLink(scene);assert(first.removed,'eski çizgi temizlenir');
// bilinmeyen düğüm için çizgi çizilmez, hata vermez
const before=linkEl;win.__mnLink='yok';c.menuLink(scene);assert(before.removed);
// kapanınca eski düzen
win.__mnLink='dosya';c.menuUndock();assert(!scene.classList.contains('docked'),'orb ortaya döner');assert.equal(JSON.stringify(focusCalls.at(-1)),'[[],null]','dallar eski hâline döner');assert(styleCalls.some(x=>x[0]==='remove'&&x[1]==='--mnk'),'ölçek sıfırlanır');assert.equal(win.__mnLink,null);
// boş yere basınca kapanır; düğme, panel, düğüm ve orb tıklamaları kapatmaz
c.menuDock(card,['dosya','Dosyalar','doer']);closed=0;
const tgt=sel=>({target:{closest:s=>s.split(',').map(x=>x.trim()).includes(sel)?{}:null}});
for(const sel of ['.mn-dock','circle','.mn-tap','.mn-hud','button','[data-act]'])assert.equal(c.menuOutsideClick(scene,tgt(sel)),false,sel+' kapatmaz');
assert.equal(closed,0);assert.equal(c.menuOutsideClick(scene,tgt('.yok')),true,'boş alan kapatır');assert.equal(closed,1);
scene.classList.remove('docked');assert.equal(c.menuOutsideClick(scene,tgt('.yok')),false,'yan sayfa kapalıyken bir şey olmaz');assert.equal(closed,1);
// eski Ayarlar/Araçlar adresleri menüde doğru düğümün yan sayfasını açar
const nc={};vm.createContext(nc);vm.runInContext(src.slice(src.indexOf('const SET_NODE='),src.indexOf('function go(')),nc);
for(const [tool,sset,want] of [['','ai','ai'],['aihub','baglanti','ai'],['','ses','ses'],['takvim','','takvim'],['gorev','','gorev'],['telefon','iletisim','telefon'],['mesaj','','mesaj'],['kb','','chat'],['veri','sistem','veri'],['rapor','','rapor'],['tarama','','tarama'],['','hafiza','hafiza'],['','guvenlik','hesap'],['','github','github'],['','genel','sistem'],['','bilinmeyen','sistem']])
  assert.equal(nc.settingsNode(tool,sset),want,tool+'|'+sset+' → '+want);
console.log('Menü yan sayfa: orb sola kayma, sağ panel, düğümden panele çizgi, yeniden çizim ve kapanış geçti.');
