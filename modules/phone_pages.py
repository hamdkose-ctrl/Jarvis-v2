"""Phone and Siri pages. No credentials are embedded in their source."""

PAGE = r"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="referrer" content="no-referrer">
<meta name="theme-color" content="#e8f0fb"><meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes"><link rel="manifest" href="/manifest.json"><title>Jarvis</title>
<link rel="apple-touch-icon" href="/icon-180.png"><link rel="icon" href="/icon-192.png">
<style>
:root{--bg:#e8f0fb;--line:#c5d7ec;--cy:#237dd0;--bl:#237dd0;--gr:#15845d;--rd:#c93651;--tx:#183651;--mut:#56718d;color-scheme:light}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}[hidden]{display:none!important}html,body{height:100%;margin:0}body{background:linear-gradient(145deg,#dbeaf9,#f3f7fc 55%,#dceafa);color:var(--tx);font:16px 'Segoe UI',system-ui,sans-serif;display:flex;flex-direction:column;overflow:hidden;height:100dvh}
button,a,input{font:inherit}button,a{-webkit-touch-callout:none}button{cursor:pointer}button:focus-visible,a:focus-visible{outline:3px solid #e4a93c;outline-offset:2px}
header{padding:calc(12px + env(safe-area-inset-top)) 16px 10px;display:flex;align-items:center;gap:10px}.sp{flex:1}.ub{display:flex;align-items:center;gap:9px;border:1px solid var(--line);background:#ffffffb8;color:var(--tx);border-radius:16px;padding:7px 12px 7px 7px;font-weight:650;max-width:70%;min-width:0;min-height:48px}.ub #uav{width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#62b6ef,#237dd0);color:white;display:grid;place-items:center;flex:none}.ub #unm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.st{display:flex;align-items:center;gap:6px;flex:none;white-space:nowrap;font-size:12px;color:var(--mut)}.dot{width:8px;height:8px;border-radius:50%;background:var(--bl)}
.mobile-nav{display:flex;gap:6px;margin:0 16px 12px;padding:5px;border:1px solid var(--line);background:#ffffffb8;border-radius:16px;box-shadow:0 4px 16px #315d8510}.mobile-nav a,.mobile-nav button{flex:1 1 0;min-width:0;width:0;min-height:44px;border:0;background:none;text-align:center;text-decoration:none;color:var(--mut);padding:11px 3px;border-radius:11px;font-size:13px;font-weight:600}.mobile-nav .active{background:#fff5db;color:#96610d;box-shadow:inset 0 0 0 1px #e4b344}
#state{flex:none;max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:var(--cy);font-weight:650;text-transform:capitalize;padding:6px 8px;background:#e3f1ff;border:1px solid var(--line);border-radius:10px}.mobile-nav .ib{flex:0 0 44px;width:44px;padding:0;border:1px solid var(--line);border-radius:11px;background:#f4f8fe;color:var(--cy);font-size:18px}.mobile-nav .ib.on{background:#e3f1ff;border-color:#74b4ed}
#chat{flex:1;min-height:0;overflow-y:auto;margin:0 16px;padding:12px 8px;display:flex;flex-direction:column;gap:9px;scroll-behavior:smooth;background:#ffffff8f;border:1px solid var(--line);border-radius:18px}.row{display:flex;gap:8px;align-items:flex-end}.row.u{flex-direction:row-reverse}.av{width:27px;height:27px;border-radius:50%;flex:none;display:grid;place-items:center;font-size:10px;font-weight:700}.b .av{background:#d9ecfc;color:#2266a4}.u .av{background:#237dd0;color:white}.m{max-width:calc(100% - 42px);padding:8px 10px;border-radius:14px;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.55;font-size:15px;position:relative}.u .m{background:#237dd0;color:white;border-bottom-right-radius:5px}.b .m{background:white;border:1px solid #d3e0ee;border-bottom-left-radius:5px}.m small{display:block;margin-top:4px;font-size:10px;opacity:.65}.m img{display:block;max-width:100%;border-radius:10px;margin-bottom:6px}.sayb{position:absolute;right:-5px;top:-8px;width:28px;height:28px;border-radius:50%;border:1px solid var(--line);background:#edf5ff;color:var(--cy)}
form{display:flex;gap:7px;align-items:flex-end;margin:10px 16px 0;padding:10px 0 calc(12px + env(safe-area-inset-bottom));flex:none}input{flex:1;min-width:0;font:inherit;background:white;color:var(--tx);border:1px solid var(--line);border-radius:14px;padding:13px 12px;outline:none}form>input{width:0;flex:1 1 0}input:focus{border-color:var(--cy)}.send,.cb,#mic{width:44px;height:46px;border-radius:13px;padding:0;flex:none;font-size:19px}.send{border:0;background:var(--bl);color:white}.cb{border:1px solid var(--line);background:#ffffffcc;color:var(--cy)}#mic{border:0;color:white;background:#237dd0}#mic.rec{background:#c93651;animation:pulse 1.2s infinite}@keyframes pulse{70%{box-shadow:0 0 0 8px #c9365130}}
#shade{display:none;position:fixed;inset:0;background:#18365155;z-index:5}#sheet{position:fixed;left:0;right:0;bottom:0;z-index:6;background:#f5f9ff;border:1px solid var(--line);border-radius:22px 22px 0 0;padding:18px 16px calc(18px + env(safe-area-inset-bottom));transform:translateY(105%);transition:transform .25s;max-height:85dvh;overflow:auto}#sheet.on{transform:none}#sheet h3{margin:0 0 12px;font-size:18px;color:var(--tx)}.ur{display:flex;align-items:center;gap:12px;width:100%;text-align:left;padding:12px;margin-bottom:8px;border-radius:14px;border:1px solid var(--line);background:white;color:var(--tx)}.ur.act{border-color:var(--gr);background:#e8f5ef}.ur .a{width:34px;height:34px;border-radius:50%;background:#237dd0;color:white;display:grid;place-items:center}.ur small{margin-left:auto;color:var(--gr);font-size:11px}.nu{display:flex;gap:8px;margin-top:6px}.nu button{border:0;border-radius:14px;background:var(--bl);color:white;padding:0 18px}.logo{display:none}#hint{display:none;margin:6px 16px 0;font-size:12px;color:var(--mut);text-align:center}
#tools{border:0;border-radius:22px;background:#f5f9ff;color:var(--tx);padding:20px;width:min(90vw,440px);box-shadow:0 20px 80px #18365140}#tools::backdrop{background:#18365155}#tools h2{margin:0 0 15px;font-size:20px}#tools .ur{text-decoration:none}#tools-close{float:right;min-height:40px;min-width:40px;border:1px solid var(--line);border-radius:10px;background:white;color:var(--tx)}
@media(max-width:350px){header,.mobile-nav,#chat,form{margin-left:10px;margin-right:10px}header{padding-left:0;padding-right:0}.st{font-size:10px}#state{max-width:80px;font-size:11px}form{gap:4px}.send,.cb,#mic{width:40px}.m{font-size:14px}}@media(max-height:540px){.mobile-nav{margin-bottom:6px}header{padding-top:6px;padding-bottom:6px}#chat{padding-top:10px}}
</style></head><body>
<header><button class="ub" id="usr" aria-label="Kullanıcı Seç"><span id="uav">?</span><span id="unm">Kullanıcı</span></button><div id="state" role="status" aria-live="polite">Hazır</div><div class="sp"></div><div class="st"><div class="dot" id="dot"></div><span id="stt">Bağlanıyor</span></div></header>
<nav class="mobile-nav" aria-label="Sayfalar"><a class="active" href="/" aria-current="page">Sohbet</a><a href="/notes.html">Notlar</a><button id="tools-open" type="button">Araçlar</button><button class="ib" id="spk" title="Sesli Cevap" aria-label="Sesli Cevap">&#128266;</button><button class="ib" id="stop" title="Sustur" aria-label="Sustur">&#9632;</button></nav>

<dialog id="tools"><button id="tools-close" aria-label="Kapat">✕</button><h2>Araçlar</h2><button class="ur" id="tool-photo">Fotoğraf Çek</button><button class="ur" id="tool-user">Kullanıcı Seç</button><button class="ur" id="install">Ana Ekrana Ekle</button><a class="ur" href="/siri">Siri Bağlantısı</a></dialog>
<div id="chat" role="log" aria-label="Sohbet Geçmişi"></div>
<div id="shade"></div><div id="sheet"><h3>Kullanıcılar</h3><div id="ulist"></div><div class="nu"><input id="nun" placeholder="Yeni kullanıcı adı" autocomplete="off"><button id="nub">Ekle</button></div></div>
<div id="hint"></div>
<input type="file" id="cam" accept="image/*" capture="environment" hidden>
<form id="f"><button type="button" id="cbt" class="cb" title="Fotoğraf çek">&#128247;</button><button type="button" id="mic" title="Konuş">&#127908;</button>
<input id="t" placeholder="Yaz ya da mikrofona bas" autocomplete="off" enterkeyhint="send"><button class="send">&#10148;</button></form>
<script>
const fragment=new URLSearchParams(location.hash.slice(1)),pairCode=fragment.get("p");
if(location.hash)history.replaceState(null,"",location.pathname);
const $=i=>document.getElementById(i),chat=$("chat"),dot=$("dot");let me=localStorage.ju||"",last=0,first=true,mode="idle",speakOn=localStorage.sp!=="0",rec=null,recOn=false,lvl=0;
const stTxt={idle:"hazır",listen:"dinliyorum",think:"düşünüyorum",speak:"konuşuyor",off:"bağlantı yok"};
function setMode(m){mode=m;$("state").textContent=stTxt[m]||m}
async function api(p,o={}){o.headers={...(o.headers||{}),"X-Token":localStorage.jk||""};
 const r=await fetch(p,o);if(!r.ok){const e=new Error(r.status===401||r.status===403?"Bilgisayardaki Telefon sayfasından yeni QR okut.":"İstek tamamlanamadı ("+r.status+").");e.status=r.status;throw e}return r.json()}
function hhmm(){const d=new Date();return d.getHours().toString().padStart(2,"0")+":"+d.getMinutes().toString().padStart(2,"0")}
function appendChatBody(target,text){
 const pattern=/!\[([^\]\n]*)\]\(([^\s)]+)\)/g;let offset=0,match;
 while((match=pattern.exec(text))){target.appendChild(document.createTextNode(text.slice(offset,match.index)));
 const url=match[2];if(/^https:\/\//i.test(url)||/^data:image\/(?:png|jpeg|webp|gif|svg\+xml);base64,[A-Za-z0-9+/=]+$/.test(url)){const image=document.createElement("img");image.src=url;image.alt=match[1];target.appendChild(image)}else target.appendChild(document.createTextNode(match[1]));offset=pattern.lastIndex;}
 target.appendChild(document.createTextNode(text.slice(offset)));
}
function add(k,t,img){const u=k=="user",r=document.createElement("div");r.className="row "+(u?"u":"b");
 const a=document.createElement("div");a.className="av";a.textContent=u?"SEN":"J";
 const m=document.createElement("div");m.className="m";if(img){const im=document.createElement("img");im.src=img;m.appendChild(im)}appendChatBody(m,t);const sm=document.createElement("small");sm.textContent=hhmm();m.appendChild(sm);
 if(!u&&"speechSynthesis" in window){const b=document.createElement("button");b.className="sayb";b.innerHTML="&#128266;";b.onclick=()=>say(t,true);m.appendChild(b)}
 r.appendChild(a);r.appendChild(m);chat.appendChild(r);chat.scrollTop=chat.scrollHeight}
let tt=0;function toast(m){let e=$("toast");if(!e){e=document.createElement("div");e.id="toast";e.style.cssText="position:fixed;left:16px;right:16px;bottom:96px;z-index:9;background:#ffffff;color:#183651;border:1px solid #c5d7ec;border-radius:14px;padding:12px 14px;font-size:14px;text-align:center;transition:opacity .3s";document.body.appendChild(e)}e.textContent=m;e.style.opacity=1;clearTimeout(tt);tt=setTimeout(()=>e.style.opacity=0,3500)}
function say(t,force){if(!("speechSynthesis" in window)||(!speakOn&&!force))return;speechSynthesis.cancel();
 const u=new SpeechSynthesisUtterance(t.replace(/!\[[^\]]*\]\([^)]*\)/g,"Görsel sohbet ekranında.").replace(/[*_`#]/g,""));u.lang="tr-TR";const v=speechSynthesis.getVoices().find(x=>x.lang&&x.lang.toLowerCase().startsWith("tr"));if(v)u.voice=v;
 u.onstart=()=>setMode("speak");u.onend=u.onerror=()=>{if(mode=="speak")setMode("idle")};speechSynthesis.speak(u)}
const seenMessages=new Set();
async function restoreChat(){try{const rows=await api("/api/history");chat.innerHTML="";seenMessages.clear();for(const r of rows){add(r.role,r.text);if(r.id)seenMessages.add(r.id)}last=0}catch(e){}}
async function poll(){try{if(first||mode==="off")await restoreChat();const r=await api("/api/log?after="+last+"&u="+encodeURIComponent(me));
 r.forEach(e=>{last=Math.max(last,e.id);if(e.hid&&seenMessages.has(e.hid))return;if(e.hid)seenMessages.add(e.hid);if(e.kind=="user"&&e.text.startsWith("📷")&&pendPh>0){pendPh--;return}add(e.kind,e.text);if(!first&&e.kind!="user"){if(mode=="think")setMode("idle");if(speakOn&&e.source!="ses")say(e.text)}});
 first=false;dot.style.background=dot.style.color="#2ee6a6";$("stt").textContent="Bağlı";if(mode=="off")setMode("idle")}
 catch(e){dot.style.background=dot.style.color="#ff5d73";$("stt").textContent="Bağlı Değil";setMode("off");if(e.status===401||e.status===403){hintSet(e.message);return}}setTimeout(poll,document.hidden?5000:1000)}
let sending=false;
async function send(t){t=t.trim();if(!t||sending)return false;sending=true;setMode("think");try{await api("/api/send",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:t,user:me,rid:Date.now().toString(36)+Math.random().toString(36).slice(2)})});return true}catch(e){add("assistant","Gönderilemedi: "+(e.message||"bağlantı yok"));setMode("idle");return false}finally{sending=false}}
$("f").onsubmit=async e=>{e.preventDefault();const i=$("t"),draft=i.value;if(await send(draft)){if(i.value===draft)i.value="";i.blur()}};
$("stop").onclick=()=>{if("speechSynthesis" in window)speechSynthesis.cancel();setMode("idle");send("dur")};
function syncSpk(){$("spk").classList.toggle("on",speakOn);$("spk").innerHTML=speakOn?"&#128266;":"&#128263;"}
$("spk").onclick=()=>{speakOn=!speakOn;localStorage.sp=speakOn?"1":"0";syncSpk();if(speakOn)say("Sesli cevap açık",true);else speechSynthesis.cancel()};syncSpk();
const SR=window.SpeechRecognition||window.webkitSpeechRecognition,CANREC=!!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia&&window.MediaRecorder);
function hintSet(m){const hn=$("hint");hn.style.display="block";hn.textContent=m}
function wavOf(buf){const sr=16000,ch=buf.getChannelData(0),ratio=buf.sampleRate/sr,n=Math.floor(ch.length/ratio),o=new DataView(new ArrayBuffer(44+n*2));
 const w=(i,t)=>{for(let k=0;k<t.length;k++)o.setUint8(i+k,t.charCodeAt(k))};w(0,"RIFF");o.setUint32(4,36+n*2,true);w(8,"WAVEfmt ");o.setUint32(16,16,true);o.setUint16(20,1,true);o.setUint16(22,1,true);o.setUint32(24,sr,true);o.setUint32(28,sr*2,true);o.setUint16(32,2,true);o.setUint16(34,16,true);w(36,"data");o.setUint32(40,n*2,true);
 for(let i=0;i<n;i++){const v=Math.max(-1,Math.min(1,ch[Math.floor(i*ratio)]||0));o.setInt16(44+i*2,v<0?v*32768:v*32767,true)}return new Blob([o],{type:"audio/wav"})}
let releaseMic=()=>{},micEpoch=0;
function suspendMic(){micEpoch++;releaseMic();if(rec){rec.onend=null;try{rec.abort()}catch(e){}}if("speechSynthesis" in window)speechSynthesis.cancel();recOn=false;$("mic").classList.remove("rec");if(mode==="listen"||mode==="speak")setMode("idle")}
addEventListener("pagehide",suspendMic);document.addEventListener("visibilitychange",()=>{if(document.hidden)suspendMic()});
async function recorderMic(){let mr=null,chunks=[],stream=null,tm=0,starting=false;
 const stopAll=()=>{clearTimeout(tm);if(stream)stream.getTracks().forEach(t=>t.stop());recOn=false;$("mic").classList.remove("rec")};
 $("mic").onclick=async()=>{$("t").blur();if(recOn){mr.stop();return}if(starting)return;starting=true;if("speechSynthesis" in window)speechSynthesis.cancel();
  const epoch=micEpoch;
  try{stream=await navigator.mediaDevices.getUserMedia({audio:true});if(epoch!==micEpoch){stopAll();return}
   chunks=[];mr=new MediaRecorder(stream)}catch(e){stopAll();toast("Mikrofon açılamadı: tarayıcı iznini kontrol et");return}finally{starting=false}
  releaseMic=()=>{try{if(mr&&mr.state!=="inactive"){mr.onstop=null;mr.stop()}}finally{stopAll()}};
  mr.onerror=()=>{releaseMic();setMode("idle");toast("Ses kaydı durdu. Yeniden deneyebilirsin.")};
  mr.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
  mr.onstop=async()=>{const type=mr.mimeType;stopAll();if(!chunks.length){setMode("idle");return}setMode("think");
   let ac;try{ac=new (window.AudioContext||window.webkitAudioContext)();const ab=await new Blob(chunks,{type}).arrayBuffer(),buf=await ac.decodeAudioData(ab);if(epoch!==micEpoch){setMode("idle");return}
    const r=await fetch("/api/audio",{method:"POST",headers:{"X-Token":localStorage.jk||"","X-User":encodeURIComponent(me),"Content-Type":"audio/wav"},body:wavOf(buf)});if(!r.ok)throw 0;pendAu=1}
   catch(e){add("assistant","Ses gönderilemedi.");setMode("idle")}finally{if(ac)ac.close()}};
  mr.start();recOn=true;$("mic").classList.add("rec");setMode("listen");tm=setTimeout(()=>{if(recOn)mr.stop()},30000)}}
let pendAu=0;
if(!window.isSecureContext){hintSet("Mikrofon için güvenli (https) adres gerekir: bilgisayarda Jarvis → Telefon → “HTTPS’i aç”, sonra QR’ı HTTPS sekmesinden okut.");
 $("mic").onclick=()=>{$("t").blur();toast("Mikrofon için https gerekir: bilgisayarda Telefon → “HTTPS’i aç”")}}
else if(SR){rec=new SR();rec.lang="tr-TR";rec.interimResults=true;rec.continuous=false;let fin="";
 rec.onstart=()=>{if(document.hidden){rec.onend=null;rec.abort();return}recOn=true;$("mic").classList.add("rec");setMode("listen")};
 rec.onresult=e=>{let s="";for(const r of e.results){s+=r[0].transcript;if(r.isFinal)fin=s}$("t").value=s};
 const recognitionEnd=async()=>{recOn=false;$("mic").classList.remove("rec");const t=$("t").value.trim();if(t){if(await send(t))$("t").value=""}else if(mode=="listen")setMode("idle")};rec.onend=recognitionEnd;
 rec.onerror=()=>{recOn=false;$("mic").classList.remove("rec");setMode("idle")};
 $("mic").onclick=()=>{$("t").blur();if(recOn){rec.stop();return}if("speechSynthesis" in window)speechSynthesis.cancel();try{$("t").value="";rec.onend=recognitionEnd;rec.start()}catch(e){}}}
else if(CANREC){recorderMic()}
else{hintSet("Bu tarayıcı ses kaydını desteklemiyor; Chrome ya da Safari kullan.");$("mic").onclick=()=>toast("Bu tarayıcı ses kaydını desteklemiyor")}
let pendPh=0;
async function photoImage(f){if(window.createImageBitmap)return createImageBitmap(f);const url=URL.createObjectURL(f);try{return await new Promise((ok,no)=>{const im=new Image();im.onload=()=>ok(im);im.onerror=no;im.src=url})}finally{URL.revokeObjectURL(url)}}
$("cbt").onclick=()=>$("cam").click();
$("cam").onchange=async e=>{const f=e.target.files[0];e.target.value="";$("t").blur();if(!f)return;
 try{const bm=await photoImage(f),sc=Math.min(1,1280/Math.max(bm.width,bm.height)),cn=document.createElement("canvas");
  cn.width=Math.round(bm.width*sc);cn.height=Math.round(bm.height*sc);cn.getContext("2d").drawImage(bm,0,0,cn.width,cn.height);if(bm.close)bm.close();
  const blob=await new Promise(r=>cn.toBlob(r,"image/jpeg",.82)),q=$("t").value.trim();$("t").value="";
  add("user",q||"Bu fotoğrafı analiz et",cn.toDataURL("image/jpeg",.4));pendPh++;setMode("think");
  const r=await fetch("/api/photo",{method:"POST",headers:{"X-Token":localStorage.jk||"","X-User":encodeURIComponent(me),"X-Question":encodeURIComponent(q),"Content-Type":"image/jpeg"},body:blob});
  if(!r.ok)throw 0}catch(x){add("assistant","Fotoğraf gönderilemedi.");pendPh=Math.max(0,pendPh-1);setMode("idle")}};
$("tools-open").onclick=()=>$("tools").showModal();$("tools-close").onclick=()=>$("tools").close();$("tool-photo").onclick=()=>{$("tools").close();$("cbt").click()};$("tool-user").onclick=()=>{$("tools").close();$("usr").click()};
if("speechSynthesis" in window)speechSynthesis.getVoices();
let users={list:[],active:""};
function ini(n){return (n||"?").trim().charAt(0).toLocaleUpperCase("tr")}
function setMe(n){if(n==me)return;me=n;localStorage.ju=n;chat.innerHTML="";last=0;first=true;paintU()}
function paintU(){$("uav").textContent=ini(me);$("unm").textContent=me||"Kullanıcı";const l=$("ulist");l.innerHTML="";
 users.list.forEach(n=>{const b=document.createElement("button");b.className="ur"+(n==me?" act":"");b.innerHTML="<span class=a></span><span></span><small></small>";
  b.children[0].textContent=ini(n);b.children[1].textContent=n;if(n==me)b.children[2].textContent="bu telefon";
  b.onclick=()=>{setMe(n);openS(false)};l.appendChild(b)})}
async function loadU(){try{const r=await api("/api/users");users=r;if(!me||!r.list.includes(me)){me=r.active||"";localStorage.ju=me}paintU()}catch(e){}}
function openS(o){$("sheet").classList.toggle("on",o);$("shade").style.display=o?"block":"none"}
$("usr").onclick=()=>{loadU();openS(true)};$("shade").onclick=()=>openS(false);
$("nub").onclick=()=>{const v=$("nun").value.trim().split(" ")[0];if(!v)return;$("nun").value="";send("yeni kullanıcı ekle "+v);openS(false);setTimeout(async()=>{await loadU();const n=users.list.find(x=>x.toLocaleLowerCase("tr")==v.toLocaleLowerCase("tr"));if(n)setMe(n)},1500)};
async function connect(){try{if(pairCode){const r=await fetch("/api/pair",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code:pairCode})});const d=await r.json();if(!r.ok)throw new Error(d.error||"QR eşleşmesi tamamlanamadı.");localStorage.jk=d.token;localStorage.removeItem("ju");me=""}
 if(!localStorage.jk&&isSecureContext){const r=await fetch("/api/web-session",{headers:{"X-Jarvis-Web-Session":"1"},credentials:"same-origin"});if(r.ok){const d=await r.json();localStorage.jk=d.token}}
 if(!localStorage.jk)throw new Error("Bilgisayarda Telefon erişimini açıp QR kodunu okut.");
 if(isSecureContext)await fetch("/api/web-session",{method:"POST",headers:{"X-Token":localStorage.jk},credentials:"same-origin"}).catch(()=>{});
 await loadU();poll();setInterval(()=>{if(!document.hidden)loadU()},8000)}catch(e){setMode("off");hintSet(e.message);toast(e.message)}}
connect();
</script><script src="/mobile-install.js"></script></body></html>"""


SIRI_PAGE = r"""<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jarvis Siri Kurulumu</title><style>body{max-width:650px;margin:30px auto;padding:20px;font:17px system-ui;background:#e8f0fb;color:#183651}input,button{padding:12px;margin:6px 0;width:100%;box-sizing:border-box}code{word-break:break-all}li{margin:14px 0}</style>
<h1>Siri ile Jarvis</h1><p>Önce bu telefonda bilgisayarın Telefon ekranındaki yeni QR kodunu okut. Sonra buraya dön.</p>
<p id="status"></p><ol>
<li>Kestirmeler uygulamasında yeni bir kestirme oluştur; adını <b>Jarvis</b> yap.</li>
<li><b>Metni Dikte Et</b> eylemini ekle ve Türkçe seç.</li>
<li><b>URL İçeriğini Al</b> eylemine aşağıdaki adresi yaz. Yöntemi <b>POST</b> seç.</li>
<li>Başlıklara <b>X-Token</b> ekle; aşağıdaki bağlantı anahtarını değeri olarak yapıştır. <b>Content-Type</b> değeri <b>application/json</b> olsun.</li>
<li>İstek gövdesini JSON seç: <b>text</b> alanına <b>Dikte Edilen Metin</b> değişkenini koy.</li>
<li>Yanıttan <b>reply</b> sözlük değerini al ve <b>Metni Seslendir</b> eylemine ver.</li></ol>
<label>İstek adresi</label><input id="address" readonly><label>Bağlantı anahtarı — yalnız kestirmendeki X-Token alanına koy</label><input id="key" type="password" readonly><button id="copy">Anahtarı kopyala</button><button id="test">Bağlantıyı dene</button><p id="result"></p>
<script>
if(location.hash)history.replaceState(null,"",location.pathname);
const key=localStorage.jk||"";
document.getElementById("address").value=location.origin+"/api/ask";
document.getElementById("key").value=key;
document.getElementById("status").textContent=key?"Telefon eşleştirmesi hazır.":"Anahtar yok. Bilgisayardaki Telefon sayfasından yeni QR okut.";
document.getElementById("copy").onclick=()=>navigator.clipboard.writeText(key);
document.getElementById("test").onclick=async()=>{const el=document.getElementById("result");try{const r=await fetch('/api/ask',{method:'POST',headers:{'X-Token':key,'Content-Type':'application/json'},body:JSON.stringify({text:'Merhaba, beni duyuyor musun?'})});const data=await r.json();el.textContent=r.ok?data.reply:(data.error||'Bağlantı reddedildi.')}catch(e){el.textContent='Bağlantı kurulamadı.'}};
</script></html>"""


