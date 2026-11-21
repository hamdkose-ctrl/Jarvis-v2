const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../webui/nx.js'),'utf8');
const nodes={};const $=id=>nodes[id]||(nodes[id]={value:'',innerHTML:'',textContent:'',style:{},isConnected:true});
const S={page:'study',sdoc:4,snap:{user:{name:'Hamdi'},study:{mode:'source'}}},ACT={},TV={};let calls=[],timers=0;
const c={S,ACT,TV,$,Date,console,ic:()=>'',esc:x=>String(x??'').replace(/</g,'&lt;'),ymd:d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`,mdMath:x=>x,toast(){},refresh:async()=>{},after:async()=>{},redrawTool:()=>{},clearTimeout(){},setTimeout(){timers++},api:async(name,...args)=>{calls.push([name,...args]);return name==='preview'?'PNGDATA':{text:'Yanıt'}}};vm.createContext(c);
function load(a,b){vm.runInContext(src.slice(src.indexOf(a),src.indexOf(b,src.indexOf(a))),c)}
(async()=>{
load('ACT.studyask=async()=>','\nACT.studyanalyze=');await ACT.studyask();assert.deepEqual(calls[0],['study_answer_with_context','','source',4]);assert.equal($('#studya').innerHTML,'Yanıt');
load('ACT.convdelete=async el=>','\nACT.day=');
c.ask=async()=>false;const beforeDelete=calls.length;await ACT.convdelete({dataset:{d:'2026-10-07'}});assert.equal(calls.length,beforeDelete);
c.ask=async()=>true;c.loadHist=async()=>{};c.drawConvs=()=>{};c.drawMsgs=()=>{};c.drawSide=()=>{};S.day='2026-10-06';
await ACT.convdelete({dataset:{d:'2026-10-06'}});assert.deepEqual(calls[calls.length-1],['history_delete_conversation','2026-10-06']);
load('const today=()=>','\nTV.takvim=');load('TV.takvim=el=>','\nfunction drawTaskNotes');load('function drawTaskNotes','\nACT.tktog=');
S.calDay='2026-10-12';S.calMonth='2026-10';S.snap.all_events=[{id:1,title:'Bakım',when:'2026-10-12T15:00'}];S.snap.tasks=[{id:2,text:'Motor kontrolü',when:'2026-10-12',done:false}];S.snap.notes=[{id:3,text:'Not örneği'}];const el={};TV.takvim(el);assert(el.innerHTML.includes('Bakım'));assert(el.innerHTML.includes('Motor kontrolü'));assert($('#planner-tasks').innerHTML.includes('Not örneği'));
ACT.calmonth({dataset:{n:'1'}});assert.equal(S.calMonth,'2026-11');ACT.calday({dataset:{day:'2026-11-03'}});assert.equal(S.calDay,'2026-11-03');
assert(el.innerHTML.includes('planner-top'));assert(el.innerHTML.indexOf('calendar-grid')<el.innerHTML.indexOf('planner-tasklist'));assert(el.innerHTML.indexOf('evtitle')<el.innerHTML.indexOf('planner-tasklist'));assert($('#planner-tasklist').innerHTML.includes('Yapılacaklar'));assert($('#planner-tasks').innerHTML.includes('notesworkspace'));assert($('#planner-tasks').innerHTML.includes('note-detail'));
c.document={querySelectorAll:()=>[]};await ACT.ntopen({dataset:{id:'3'}});assert($('#note-detail').innerHTML.includes('Not örneği'));assert.equal(S.noteSelected,3);
c.URL={revokeObjectURL(){}};c.upload=async()=>({path:'photo.png'});$('#nti').value='Görselli not';S.noteFile={name:'photo.png'};S.notePreview='blob:preview';await ACT.ntsave();assert.deepEqual(calls[calls.length-1],['note_add','Görselli not','photo.png','']);assert.equal(S.noteFile,null);assert.equal($('#nti').value,'');
$('#nti').value='Saklanacak taslak';S.noteFile={name:'photo.png'};c.upload=async()=>null;const beforeFailedSave=calls.length;await ACT.ntsave();assert.equal(calls.length,beforeFailedSave);assert.equal($('#nti').value,'Saklanacak taslak');assert(S.noteFile);ACT.ntimageclear();
// Microphone mute reaches the real server flag and sits immediately left of the speaker.
load("const micToggleBtn=","const DOCK_PH=");load("const askBar=","// ======================================================================= ANA SAYFA");
load('ACT.mictoggle=','ACT.wmin=');load('ACT.mic=','ACT.attach=');
c.$$=()=>[];c.tryApi=async(name,...args)=>{calls.push([name,...args]);return name==='set_flag'?{mic:args[1],speak:true}:false};S.snap.flags={mic:true,speak:true};
let dock=vm.runInContext('askBar()',c);assert(dock.indexOf('data-act="mic"')<dock.indexOf('data-act="mictoggle"'));assert(dock.indexOf('data-act="mictoggle"')<dock.indexOf('data-act="mute"'));assert(dock.indexOf('data-act="mute"')<dock.indexOf('data-act="pcmute"'));
await ACT.mictoggle();assert.deepEqual(calls[calls.length-1],['set_flag','mic',false]);assert.equal(S.snap.flags.mic,false);assert.equal(S.snap.flags.speak,true);assert(vm.runInContext('micToggleBtn()',c).includes('Mikrofonu aç'));
await ACT.mictoggle();assert.deepEqual(calls[calls.length-1],['set_flag','mic',true]);assert.equal(S.snap.flags.mic,true);
c.tryApi=async()=>undefined;await ACT.mictoggle();assert.equal(S.snap.flags.mic,true);
let toasts=[];c.toast=x=>toasts.push(x);c.tryApi=async()=>false;await ACT.mic();assert.equal(toasts[0],'Mikrofon kapalı. Önce mikrofonu aç.');
load('let previewTimer=null','// HARITA START');S.page='vision';S.snap.mode='camera';await c.pollVisionPreview();assert.equal($('#vision-preview').src,'data:image/png;base64,PNGDATA');assert.equal($('#vision-preview').style.display,'block');let n=calls.length;S.page='home';await c.pollVisionPreview();assert.equal(calls.length,n);
// Screenshot button captures via the bridge and attaches only after preview approval.
load('const MAX_ATT=','function pasteChatImage(');load('ACT.capture=async()=>','let previewTimer=null');
S.page='vision';S.att=null;S.attPending=false;S.snap.user.name='Hamdi';
const capture={path:'C:/Jarvis/screen.png',name:'screen.png',preview:'data:image/png;base64,AA=='};
c.api=async name=>{calls.push([name]);return capture};let previews=0;
c.showCapturePreview=async()=>{previews++;return true};c.go=page=>{S.page=page};c.drawAtt=()=>{};
await ACT.capture();assert.equal(previews,1);assert.equal(S.att[0].path,capture.path);assert.equal(S.page,'chat');assert.equal(S.captureBusy,false);
S.att=null;c.api=async()=>({cancelled:true});await ACT.capture();assert.equal(previews,1);assert.equal(S.att,null);
c.api=async()=>capture;c.showCapturePreview=async()=>false;await ACT.capture();assert.equal(S.att,null);
c.api=async()=>{throw Error('Capture failed')};await ACT.capture();assert.equal(S.captureBusy,false);assert.equal(S.att,null);
c.api=async()=>{S.snap.user.name='Other';return capture};c.showCapturePreview=async()=>{throw Error('Must not preview another user capture')};await ACT.capture();assert.equal(S.att,null);
assert(src.includes("'act:capture'"));assert(!src.includes("'say:ekran görüntüsü al'"));
// A single PC help route still passes the user's goal through the existing coaching command.
const helpSent=[];
const help={ACT:{},askText:async()=> 'Fotoğrafları telefona gönder',say:q=>helpSent.push(q)};
vm.createContext(help);
vm.runInContext(src.slice(src.indexOf('ACT.pcguide='),src.indexOf('function pcOperationsBox(')),help);
await help.ACT.pcguide();assert.deepEqual(helpSent,['PC yardımı: Fotoğrafları telefona gönder']);
console.log('Masaüstü: boş konuyla seçili kaynak, takvim/görev/not birleşimi, ay/gün seçimi ve kamera önizlemesi geçti (taklit DOM).');
})().catch(e=>{console.error(e);process.exit(1)});
