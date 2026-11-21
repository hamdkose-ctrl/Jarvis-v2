// JARVIS — yeni arayüz (nx). Gerçek motora bağlı: /api/<ad> (web.Bridge) ve /events (anlık olaylar).
'use strict';
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let TOKEN=new URLSearchParams(location.hash.slice(1)).get('key')||'';
if(TOKEN)history.replaceState(null,'',location.pathname);
try{if(TOKEN)sessionStorage.setItem('jt',TOKEN);else TOKEN=sessionStorage.getItem('jt')||''}catch(e){}
const AUTH_READY=fetch('/session',{method:'POST',headers:{'X-Jarvis-Token':TOKEN}}).then(r=>{if(!r.ok)throw new Error('Jarvis erişim oturumu kurulamadı.');});
const store={get(k,d){try{const v=localStorage.getItem('nx.'+k);return v==null?d:JSON.parse(v)}catch(e){return d}},set(k,v){try{localStorage.setItem('nx.'+k,JSON.stringify(v))}catch(e){}}};
async function api(name,...args){
  await AUTH_READY;
  let r;
  for(let i=0;;i++){
    try{r=await fetch('/api/'+name,{method:'POST',headers:{'Content-Type':'application/json','X-Jarvis-Token':TOKEN},body:JSON.stringify(args)});break}
    catch(e){if(i<3&&performance.now()<20000){await new Promise(z=>setTimeout(z,400+i*400));continue}throw new Error('Jarvis’e ulaşılamadı; yeniden başlıyor olabilir.')}
  }
  const j=await r.json();if(!j.ok)throw new Error(j.error||'Hata');return j.data;
}
async function tryApi(name,...a){try{return await api(name,...a)}catch(e){toast(e.message,'bad')}}
function toast(msg,kind){if(kind!=='bad'&&S.ui&&S.ui.nx_notify===false)return;const d=document.createElement('div');if(kind)d.className=kind;d.textContent=msg;$('#toast').appendChild(d);setTimeout(()=>d.remove(),kind==='bad'?6500:4000)}
const S={snap:null,ui:null,page:store.get('page','home'),orb:'idle',speech:null,chat:[],live:[],hist:null,day:null,since:0,files:null,fsel:null,fcat:'all',fq:'',acat:'Tümü',aq:'',sset:'ai',waiting:false,sc:null,ftab:'genel',att:[],attPending:0,steps:{},pcMuted:null};
const DAYS=['Pazar','Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi'],MONTHS=['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'];
const pad=n=>String(n).padStart(2,'0');
const hm=ts=>{const d=new Date(ts*1000);return pad(d.getHours())+':'+pad(d.getMinutes())};
const fmtSize=b=>b>=1048576?(b/1048576).toFixed(1)+' MB':b>=1024?Math.round(b/1024)+' KB':b+' B';
const fmtDate=ts=>{const d=new Date(ts*1000);return pad(d.getDate())+'.'+pad(d.getMonth()+1)+'.'+d.getFullYear()};
const ymd=d=>d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());

// ======================================================================= küre (dünya ağı + yörüngeler + kaide)
const GLOBES=new Set();
// Gerçek dünya küresi. Kara şekilleri Natural Earth 110m (kamu malı, earth.js). Doku bir kez çizilir; küre her karede
// piksel piksel izdüşümle boyanır (eğiklik sabit olduğundan her pikselin enlem/boylamı önceden hesaplanır, dönüş
// yalnızca boylama kayma ekler). Üstüne: ağ yayları, şehir düğümleri, atmosfer, neon yörüngeler, katmanlı kaide.
const D2R=Math.PI/180,TW=1024,TH=512;
const HOME_C=[41.01,28.98];
const CITIES=[[41.0,29.0],[39.9,32.9],[51.5,-0.1],[48.9,2.35],[52.5,13.4],[55.8,37.6],[40.4,-3.7],[41.9,12.5],[30.0,31.2],[6.5,3.4],[-1.3,36.8],[-26.2,28.0],[25.2,55.3],[35.7,51.4],[19.1,72.9],[28.6,77.2],[39.9,116.4],[31.2,121.5],[35.7,139.7],[37.6,127.0],[1.35,103.8],[-6.2,106.8],[-33.9,151.2],[40.7,-74.0],[41.9,-87.6],[34.1,-118.2],[19.4,-99.1],[-23.6,-46.6],[-34.6,-58.4],[-12.0,-77.0],[4.7,-74.1],[43.7,-79.4],[24.7,46.7],[24.9,67.0],[13.8,100.5],[14.6,121.0],[-4.3,15.3],[36.8,3.1],[59.3,18.1],[50.45,30.5],[64.1,-21.9],[-37.8,144.9],[60.2,24.9],[33.6,-7.6],[9.0,38.7],[23.1,113.3],[43.2,76.9],[-15.8,-47.9]];
const TEX=(()=>{let T=null;return()=>{if(T)return T;
  const c=document.createElement('canvas');c.width=TW;c.height=TH;const g=c.getContext('2d');
  g.fillStyle='#000';g.fillRect(0,0,TW,TH);g.fillStyle='#fff';
  (typeof EARTH_LAND!=='undefined'?EARTH_LAND:[]).forEach(p=>{g.beginPath();for(let i=0;i<p.length;i+=2){const x=(p[i]/10+180)/360*TW,y=(90-p[i+1]/10)/180*TH;i?g.lineTo(x,y):g.moveTo(x,y)}g.closePath();g.fill()});
  const m=g.getImageData(0,0,TW,TH).data,land=new Uint8Array(TW*TH);for(let i=0;i<TW*TH;i++)land[i]=m[i*4]>127?1:0;
  const hash=(x,y)=>{let h=(x*374761393+y*668265263)|0;h=(h^(h>>>13))*1274126177|0;return((h^(h>>>16))>>>0)/4294967295};
  const vn=(x,y,s)=>{const X=Math.floor(x/s),Y=Math.floor(y/s),fx=x/s-X,fy=y/s-Y,a=hash(X,Y),b=hash(X+1,Y),c2=hash(X,Y+1),d=hash(X+1,Y+1);
    const sx=fx*fx*(3-2*fx),sy=fy*fy*(3-2*fy);return a+(b-a)*sx+(c2-a)*sy+(a-b-c2+d)*sx*sy};
  const day=new Uint8Array(TW*TH*3),night=new Uint8Array(TW*TH);
  const L=(x,y)=>land[((y+TH)%TH)*TW+((x+TW)%TW)];
  for(let y=0;y<TH;y++){const lat=90-(y+.5)/TH*180,al=Math.abs(lat);for(let x=0;x<TW;x++){const i=y*TW+x,o=i*3,n=vn(x,y,24)*.6+vn(x,y,7)*.4;
    if(land[i]){const coast=!(L(x+2,y)&&L(x-2,y)&&L(x,y+2)&&L(x,y-2));
      let r,gg,b;if(al>66){r=200+40*n;gg=215+30*n;b=235}else{const dry=Math.max(0,1-Math.abs(al-23)/16);r=150+90*n+50*dry;gg=95+60*n+35*dry;b=40+30*n}
      if(coast){r=Math.min(255,r+70);gg=Math.min(255,gg+50);b+=20}day[o]=Math.min(255,r);day[o+1]=Math.min(255,gg);day[o+2]=Math.min(255,b)}
    else{const near=L(x+4,y)||L(x-4,y)||L(x,y+4)||L(x,y-4);day[o]=6+14*n+(near?20:0);day[o+1]=40+40*n+(near?45:0);day[o+2]=105+55*n+(near?40:0)}}}
  // gece ışıkları: gerçek büyük şehirlerin çevresinde yoğun, karada seyrek
  const put=(x,y,v)=>{x=((x%TW)+TW)%TW;if(y<0||y>=TH)return;const i=y*TW+x;if(land[i])night[i]=Math.min(255,night[i]+v)};
  let s=7;const R=()=>(s=(s*16807)%2147483647)/2147483647;
  CITIES.forEach(([la,lo])=>{const cx=(lo+180)/360*TW,cy=(90-la)/180*TH;for(let k=0;k<140;k++){const rr=Math.pow(R(),2)*14,a=R()*6.28;put(Math.round(cx+Math.cos(a)*rr),Math.round(cy+Math.sin(a)*rr*.8),90+R()*120)}});
  for(let k=0;k<9000;k++){const x=R()*TW|0,y=TH*(.15+R()*.55)|0;put(x,y,60+R()*100)}
  return T={day,night}}})();
function mountGlobe(cv,o={}){const st={cv,o,t:0,alive:true};GLOBES.add(st);return st}
function prepSphere(st,D){
  const tilt=.38,ct=Math.cos(tilt),stt=Math.sin(tilt),Lx=-.55,Ly=.42,Lz=.72,Ln=Math.hypot(Lx,Ly,Lz);
  const n=D*D,row=new Int32Array(n),u0=new Float32Array(n),dk=new Float32Array(n),rim=new Float32Array(n),inside=new Uint8Array(n);const r=D/2;
  for(let py=0;py<D;py++)for(let px=0;px<D;px++){const i=py*D+px,x=(px+.5-r)/r,y=(r-py-.5)/r,q=x*x+y*y;if(q>1)continue;inside[i]=1;const z=Math.sqrt(1-q);
    const yw=y*ct+z*stt,zw=-y*stt+z*ct,lat=Math.asin(Math.max(-1,Math.min(1,yw))),lo=Math.atan2(x,zw);
    row[i]=Math.min(TH-1,Math.max(0,Math.floor((Math.PI/2-lat)/Math.PI*TH)))*TW;u0[i]=(lo+Math.PI)/(2*Math.PI)*TW;
    dk[i]=Math.max(0,(x*Lx+y*Ly+z*Lz)/Ln);rim[i]=Math.pow(1-z,2.2)}
  const c=document.createElement('canvas');c.width=c.height=D;st.sph={D,row,u0,dk,rim,inside,c,g:c.getContext('2d'),img:c.getContext('2d').createImageData(D,D)};
}
function paintSphere(st,rot,boost){
  const s=st.sph,T=TEX(),d=s.img.data,off=-rot/(2*Math.PI)*TW,n=s.D*s.D;
  for(let i=0;i<n;i++){const o=i*4;if(!s.inside[i]){d[o+3]=0;continue}
    let u=(s.u0[i]+off)%TW;if(u<0)u+=TW;const ti=s.row[i]+(u|0),t3=ti*3,k=s.dk[i],lit=.18+1.05*k,nl=k<.25?(1-k*4)*T.night[ti]:0,rm=s.rim[i];
    d[o]=Math.min(255,T.day[t3]*lit+nl*1.0+rm*60*boost);d[o+1]=Math.min(255,T.day[t3+1]*lit+nl*.8+rm*190*boost);d[o+2]=Math.min(255,T.day[t3+2]*lit+nl*.45+rm*255*boost);d[o+3]=255}
  s.g.putImageData(s.img,0,0);
}
const NET=(()=>{const e=[];const v=([la,lo])=>[Math.cos(la*D2R)*Math.cos(lo*D2R),Math.cos(la*D2R)*Math.sin(lo*D2R),Math.sin(la*D2R)];
  CITIES.forEach((a,i)=>{const va=v(a);const ds=CITIES.map((b,j)=>{const vb=v(b);return[j,Math.acos(Math.max(-1,Math.min(1,va[0]*vb[0]+va[1]*vb[1]+va[2]*vb[2])))]}).filter(x=>x[0]!==i).sort((p,q)=>p[1]-q[1]);
    ds.slice(0,2).forEach(([j])=>{if(!e.some(x=>(x[0]===j&&x[1]===i)))e.push([i,j])})});
  for(let j=2;j<CITIES.length;j+=3)e.push([0,j]);return e})();
function drawGlobe(st,dt){
  const cv=st.cv;if(!cv.isConnected){GLOBES.delete(st);return}
  const r=cv.getBoundingClientRect();if(r.width<10)return;
  const dpr=Math.min(2,devicePixelRatio||1);if(cv.width!==Math.round(r.width*dpr)||cv.height!==Math.round(r.height*dpr)){cv.width=r.width*dpr;cv.height=r.height*dpr}
  const g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);const W=r.width,H=r.height;g.clearRect(0,0,W,H);
  st.t+=dt;const t=st.t,o=st.o,busy=['listening','speaking','thinking'].includes(S.orb);st.sp=(st.sp||.12)+((busy?.4:.12)-(st.sp||.12))*.05;st.rot=(st.rot??-HOME_C[1]*D2R)-dt*st.sp;
  const R=Math.min(W*.34,H*(o.pedestal?.33:.4)),cx=W/2,cy=o.pedestal?H*.41:H/2,rot=st.rot,tilt=.38,ct=Math.cos(tilt),stt=Math.sin(tilt);
  const D=Math.max(64,Math.min(420,Math.round(R*2*Math.min(1.5,dpr))));if(!st.sph||st.sph.D!==D)prepSphere(st,D);
  const P=(lat,lon,h=1)=>{const lo=lon+rot,x=Math.cos(lat)*Math.sin(lo),y=Math.sin(lat),z=Math.cos(lat)*Math.cos(lo);return[cx+x*R*h,cy-(y*ct-z*stt)*R*h,y*stt+z*ct]};
  // ---- kaide
  if(o.pedestal){const py=cy+R*1.28,bw=R*1.15,th=R*.13;
    let q=g.createRadialGradient(cx,py+th,0,cx,py+th,bw*1.7);q.addColorStop(0,'rgba(50,140,255,.35)');q.addColorStop(1,'rgba(50,140,255,0)');g.fillStyle=q;g.beginPath();g.ellipse(cx,py+th,bw*1.7,bw*.45,0,0,7);g.fill();
    g.save();g.globalCompositeOperation='lighter';
    [[1.55,'rgba(255,160,60,.5)',1.2],[1.38,'rgba(80,170,255,.6)',1.4],[1.24,'rgba(170,110,255,.55)',1.2]].forEach(([k,c,w],i)=>{g.strokeStyle=c;g.lineWidth=w;g.shadowColor=c;g.shadowBlur=12;g.beginPath();g.ellipse(cx,py+th*1.6+i*2,bw*k,bw*k*.22,0,0,7);g.stroke()});g.restore();
    // yan bant
    let sg=g.createLinearGradient(0,py,0,py+th);sg.addColorStop(0,'#0d2350');sg.addColorStop(1,'#050c1e');g.fillStyle=sg;
    g.beginPath();g.ellipse(cx,py,bw,bw*.24,0,0,Math.PI);g.ellipse(cx,py+th,bw,bw*.24,0,Math.PI,0,true);g.closePath();g.fill();
    g.save();g.globalCompositeOperation='lighter';const segC=['#22d3ee','#a07bff','#2ee6a6','#ff5fb3','#3fb7ff','#ffd166'];
    for(let k=0;k<14;k++){let a=((t*(busy?1.2:.45)+k*Math.PI/7)%(2*Math.PI));if(a>Math.PI)continue;const c=segC[k%6];g.strokeStyle=c;g.shadowColor=c;g.shadowBlur=14;g.lineWidth=3;
      g.beginPath();g.ellipse(cx,py+th*.55,bw,bw*.24,0,a,Math.min(Math.PI,a+.22));g.stroke()}
    g.restore();
    // üst cam yüzey
    q=g.createRadialGradient(cx,py,0,cx,py,bw);q.addColorStop(0,'rgba(90,180,255,.55)');q.addColorStop(.6,'rgba(20,60,140,.85)');q.addColorStop(1,'rgba(10,30,80,.95)');g.fillStyle=q;g.beginPath();g.ellipse(cx,py,bw,bw*.24,0,0,7);g.fill();
    g.save();g.globalCompositeOperation='lighter';g.strokeStyle='rgba(120,210,255,.95)';g.lineWidth=2.2;g.shadowColor='#3fb7ff';g.shadowBlur=18;g.beginPath();g.ellipse(cx,py,bw,bw*.24,0,0,7);g.stroke();
    g.strokeStyle='rgba(150,120,255,.8)';g.lineWidth=1.5;g.beginPath();g.ellipse(cx,py,bw*.72,bw*.17,0,0,7);g.stroke();
    g.strokeStyle='rgba(46,230,166,.7)';g.beginPath();g.ellipse(cx,py,bw*.48,bw*.11,0,0,7);g.stroke();
    // ışık huzmesi
    const lg=g.createLinearGradient(0,cy,0,py);lg.addColorStop(0,'rgba(80,170,255,0)');lg.addColorStop(1,'rgba(80,170,255,.4)');g.shadowBlur=0;g.fillStyle=lg;
    g.beginPath();g.moveTo(cx-bw*.5,py);g.lineTo(cx+bw*.5,py);g.lineTo(cx+R*.35,cy+R*.5);g.lineTo(cx-R*.35,cy+R*.5);g.fill();g.restore()}
  // ---- dış parıltı ve arka yörünge yarıları
  let q=g.createRadialGradient(cx,cy,R*.92,cx,cy,R*1.45);q.addColorStop(0,'rgba(60,170,255,.55)');q.addColorStop(.35,'rgba(60,140,255,.18)');q.addColorStop(1,'rgba(40,120,255,0)');g.fillStyle=q;g.beginPath();g.arc(cx,cy,R*1.45,0,7);g.fill();
  const ORB=[['#3fb7ff',.18,1.42,.36,1],['#2ee6a6',-.42,1.3,.42,1.3],['#a07bff',.75,1.52,.3,.8],['#ff5fb3',-1.05,1.36,.26,1.1]];
  const orbit=(back)=>{g.save();g.globalCompositeOperation='lighter';ORB.forEach(([c,ang,rx,ry,sp],i)=>{const a=ang+Math.sin(t*.25+i)*.06;g.save();g.translate(cx,cy);g.rotate(a);
      g.strokeStyle=c;g.shadowColor=c;g.shadowBlur=16;g.lineWidth=back?1.6:2.6;g.globalAlpha=back?.45:.95;g.beginPath();g.ellipse(0,0,R*rx,R*ry,0,back?Math.PI:0,back?2*Math.PI:Math.PI);g.stroke();
      const pa=((t*sp*.6+i*1.7)%(2*Math.PI));if((pa>Math.PI)===back){g.globalAlpha=1;g.fillStyle='#fff';g.shadowBlur=14;g.beginPath();g.arc(Math.cos(pa)*R*rx,Math.sin(pa)*R*ry,2.8,0,7);g.fill()}g.restore()});g.restore()};
  orbit(true);
  // ---- küre
  paintSphere(st,rot,busy?1.25:1);g.imageSmoothingEnabled=true;g.drawImage(st.sph.c,cx-R,cy-R,R*2,R*2);
  // enlem/boylam ağı (silik)
  g.save();g.globalCompositeOperation='lighter';g.lineWidth=.6;g.strokeStyle='rgba(120,190,255,.13)';
  const line=pts=>{g.beginPath();let pen=false;for(const[a,b]of pts){const[x,y,z]=P(a,b);if(z<0){pen=false;continue}pen?g.lineTo(x,y):g.moveTo(x,y);pen=true}g.stroke()};
  for(let la=-60;la<=60;la+=30){const pts=[];for(let lo=-180;lo<=180;lo+=5)pts.push([la*D2R,lo*D2R]);line(pts)}
  for(let lo=-180;lo<180;lo+=30){const pts=[];for(let la=-85;la<=85;la+=5)pts.push([la*D2R,lo*D2R]);line(pts)}
  // ağ yayları ve hareketli ışık
  const V=([la,lo])=>[Math.cos(la*D2R)*Math.cos(lo*D2R),Math.cos(la*D2R)*Math.sin(lo*D2R),Math.sin(la*D2R)];
  NET.forEach(([i,j],k)=>{const a=V(CITIES[i]),b=V(CITIES[j]),om=Math.acos(Math.max(-1,Math.min(1,a[0]*b[0]+a[1]*b[1]+a[2]*b[2])));if(om<1e-3)return;
    const pts=[];for(let s=0;s<=24;s++){const u=s/24,f1=Math.sin((1-u)*om)/Math.sin(om),f2=Math.sin(u*om)/Math.sin(om),v=[f1*a[0]+f2*b[0],f1*a[1]+f2*b[1],f1*a[2]+f2*b[2]];
      pts.push(P(Math.asin(v[2]),Math.atan2(v[1],v[0]),1+.16*Math.sin(u*Math.PI)*Math.min(1,om*1.2)))}
    const hub=i===0;g.strokeStyle=hub?'rgba(255,215,140,.55)':'rgba(150,225,255,.42)';g.lineWidth=hub?1.3:1;g.beginPath();let pen=false;
    pts.forEach(([x,y,z])=>{if(z<-.05){pen=false;return}pen?g.lineTo(x,y):g.moveTo(x,y);pen=true});g.stroke();
    const u=((t*.35+k*.173)%1),p=pts[Math.round(u*24)];if(p&&p[2]>0){g.fillStyle=hub?'rgba(255,230,170,.95)':'rgba(200,240,255,.95)';g.shadowColor=g.fillStyle;g.shadowBlur=10;g.beginPath();g.arc(p[0],p[1],1.8,0,7);g.fill();g.shadowBlur=0}});
  CITIES.forEach(([la,lo],i)=>{const[x,y,z]=P(la*D2R,lo*D2R);if(z<=0)return;const tw=.6+.4*Math.sin(t*2.4+i);
    g.fillStyle=i===0?'#ff5a5a':`rgba(190,235,255,${.55+.45*tw})`;g.shadowColor=g.fillStyle;g.shadowBlur=i===0?16:8;g.beginPath();g.arc(x,y,i===0?3.4:1.7,0,7);g.fill()});
  {const[x,y,z]=P(HOME_C[0]*D2R,HOME_C[1]*D2R);if(z>0){const pr=(t%2)/2;g.shadowBlur=0;g.strokeStyle=`rgba(255,90,90,${1-pr})`;g.lineWidth=1.6;g.beginPath();g.arc(x,y,4+pr*14,0,7);g.stroke()}}
  g.restore();
  // parlama ve kenar
  q=g.createRadialGradient(cx-R*.45,cy-R*.45,0,cx-R*.45,cy-R*.45,R*.8);q.addColorStop(0,'rgba(200,230,255,.2)');q.addColorStop(1,'rgba(200,230,255,0)');g.fillStyle=q;g.beginPath();g.arc(cx,cy,R,0,7);g.fill();
  g.save();g.globalCompositeOperation='lighter';g.strokeStyle='rgba(110,200,255,.9)';g.lineWidth=2.2;g.shadowColor='#3fb7ff';g.shadowBlur=24;g.beginPath();g.arc(cx,cy,R,0,7);g.stroke();
  // parıltı zerreleri
  for(let k=0;k<34;k++){const a=k*2.399+t*(.12+(k%5)*.03),rr=R*(1.1+((k*37)%40)/100),x=cx+Math.cos(a)*rr,y=cy+Math.sin(a)*rr*.82,tw=.5+.5*Math.sin(t*2+k);
    g.shadowBlur=6;g.fillStyle=`rgba(${k%3?'150,215,255':'255,205,130'},${.3+.6*tw})`;g.beginPath();g.arc(x,y,.8+1.5*tw,0,7);g.fill()}
  g.restore();
  orbit(false);
}
let lastT=performance.now();
let bgT=0;
let orbPaint=0,shPaint=0;function idleGate(now,budget){if(UI_CALM())return true;if(now-(budget>60?orbPaint:shPaint)<budget)return false;if(budget>60)orbPaint=now;else shPaint=now;return true}
let lastPaint=0;function frame(now){const budget=UI_CALM()?50:125;if(now-lastPaint<budget)return requestAnimationFrame(frame);const dt=Math.min(.1,(now-lastT)/1000);lastT=now;lastPaint=now;if(!document.hidden){window.JarvisBackdropController?.sync();bgT+=dt;GLOBES.forEach(st=>drawGlobe(st,dt))}requestAnimationFrame(frame)}

// ======================================================================= üst çubuk ve sağ sütun
const NAV=[['home','Ana Sayfa','home'],['chat','Sohbet','msg'],['study','Çalışma','book'],['files','Dosyalar','folder'],['vision','Ekran','monitor'],['tools','Araçlar','gear'],['settings','Ayarlar','gear'],['menu','Menü','grid'],['team','Ekip merkezi','grid'],['map','Harita','grid']];
function ic2(n){return ic(n)}
function renderTop(){
  const sn=S.snap||{},n=needCount(),w=sn.weather,win=sn.winctl!==false;
  $('#top').innerHTML=`<button class="card hprofile top-profile" data-act="user" title="Kullanıcı değiştir"><span class="hav">${ic('user')}</span><span class="top-profile-text"><b>${esc((sn.user||{}).name||'Kullanıcı')}</b><small><span class="dot ${(sn.flags||{}).sleep?'warn':''}"></span>${(sn.flags||{}).sleep?'JARVIS Uykuda':'JARVIS Aktif'}</small></span><span class="hchev">⌄</span></button>
   <nav class="nav">${NAV.filter(n=>!['files','vision','tools','menu','settings'].includes(n[0])).map(([k,t,i])=>`<button data-go="${k}" class="${S.page===k?'on':''}">${k==='tools'?toolIcon():ic(i)}<span>${t}</span></button>`).join('')}</nav>
   <div class="tbar" title="${esc(wxText())}">
    <div class="tw"><span class="tic">${wxEmoji()}</span><div><b>${w?esc(w.temp+'°C'):'--°C'}</b><span class="c">${w?esc(w.city||''):'Hava durumu'}</span><span class="d">${w?esc(tcFirst(w.desc||'')):'bekleniyor'}</span></div></div>
    <span class="tsp"></span>
    <div class="tt"><b id="clock"></b><small id="date"></small></div>
    <span class="tsp"></span>
    <button class="tbell" data-act="notif" title="Bildirimler">${ic('bell')}${n?`<i>${n}</i>`:''}</button>
    ${win?`<span class="tsp"></span><div class="twbs"><button class="twb" data-act="wmin" title="Küçült"><svg viewBox="0 0 16 16"><path d="M3.5 8h9"/></svg></button><button class="twb" data-act="wfull" title="Tam ekran / pencere"><svg viewBox="0 0 16 16">${(S.snap||{}).fullscreen?'<path d="M5.5 3.5h7v7"/><rect x="3.5" y="5.5" width="7" height="7" rx="1.2"/>':'<rect x="3.5" y="3.5" width="9" height="9" rx="1.6"/>'}</svg></button><button class="twb x" data-act="wclose" title="Jarvis’i kapat"><svg viewBox="0 0 16 16"><path d="M4 4l8 8M12 4l-8 8"/></svg></button></div>`:''}
   </div>`;
  tick();fitTop();
}
function tcFirst(t){t=String(t||'');return t?t[0].toLocaleUpperCase('tr')+t.slice(1):t}
function wxEmoji(){const w=(S.snap||{}).weather;const c=w?+w.code:2;
  const sun=(x,y,r)=>`<g class="wsun"><circle cx="${x}" cy="${y}" r="${r}" fill="url(#wxg)"/>${[0,45,90,135,180,225,270,315].map(a=>{const t=a*Math.PI/180;return `<line x1="${x+Math.cos(t)*(r+3)}" y1="${y+Math.sin(t)*(r+3)}" x2="${x+Math.cos(t)*(r+6.5)}" y2="${y+Math.sin(t)*(r+6.5)}" stroke="#ffc94a" stroke-width="2.2" stroke-linecap="round"/>`}).join('')}</g>`;
  const cloud=(dx=0,dy=0,op=1)=>`<path transform="translate(${dx} ${dy})" opacity="${op}" d="M13 33h19a7 7 0 0 0 .8-13.95A10 10 0 0 0 13.6 21.2 6 6 0 0 0 13 33z" fill="rgba(170,215,255,.22)" stroke="#9fd4ff" stroke-width="1.8" stroke-linejoin="round"/>`;
  const drops=(col,n=3)=>[0,1,2].slice(0,n).map(k=>`<line x1="${17+k*7}" y1="37" x2="${15+k*7}" y2="42" stroke="${col}" stroke-width="2" stroke-linecap="round"/>`).join('');
  let b;
  if(c===0)b=sun(22,22,9);
  else if(c<=2)b=sun(16,15,6.5)+cloud(4,3);
  else if(c===3)b=cloud(2,-1)+cloud(-5,4,.75);
  else if(c===45||c===48)b=cloud(2,-4)+`<g stroke="#9fd4ff" stroke-width="2" stroke-linecap="round" opacity=".8"><line x1="9" y1="35" x2="35" y2="35"/><line x1="13" y1="40" x2="31" y2="40"/></g>`;
  else if(c>=95)b=cloud(2,-4)+`<path d="M22 31l-4 7h5l-3 6" fill="none" stroke="#ffc94a" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>`;
  else if((c>=71&&c<=77)||c===85||c===86)b=cloud(2,-4)+[0,1,2].map(k=>`<circle cx="${16+k*7}" cy="${38+(k%2)*3}" r="1.7" fill="#e6f4ff"/>`).join('');
  else if(c>=51)b=cloud(2,-4)+drops('#5cc2ff');
  else b=sun(16,15,6.5)+cloud(4,3);
  return `<svg class="wxi" viewBox="0 0 44 44" width="40" height="40" aria-hidden="true"><defs><radialGradient id="wxg" cx="40%" cy="38%" r="70%"><stop offset="0" stop-color="#fff3c4"/><stop offset=".55" stop-color="#ffc94a"/><stop offset="1" stop-color="#f08a1c"/></radialGradient></defs>${b}</svg>`}
function toolIcon(){return `<svg class="i" viewBox="0 0 24 24"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/><path d="m16 16 4 4M18 14l3 3-1 1"/></svg>`}
function fitTop(){const t=$('#top'),n=t&&t.querySelector('.nav');if(!n)return;t.classList.remove('fit1','fit2','fit3','fit4');
  for(let k=1;k<=4&&(n.scrollWidth>n.clientWidth+1||t.scrollWidth>t.clientWidth+1);k++){for(let j=1;j<=k;j++)t.classList.add('fit'+j)}t.classList.add('fitted')}
addEventListener('resize',()=>{clearTimeout(window._ft);window._ft=setTimeout(fitTop,60)});
// ilk açılışta yazı tipi ve kullanıcı adı sonradan gelince menü taşmasın: üst çubuğun boyu her değiştiğinde yeniden sığdır
try{new ResizeObserver(()=>requestAnimationFrame(fitTop)).observe(document.getElementById('top'))}catch(e){}
[100,400,1200,2500].forEach(ms=>setTimeout(fitTop,ms));
function tick(){const d=new Date();const de=$('#date'),ce=$('#clock');if(de)de.innerHTML=`${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}<br>${DAYS[d.getDay()]}`;if(ce)ce.textContent=pad(d.getHours())+':'+pad(d.getMinutes())}
function wxIcon(){const w=(S.snap||{}).weather;if(!w)return'sun';const s=(w.desc||'').toLowerCase();return /yağmur|bulut|kapalı|sis/.test(s)?'cloud':'sun'}
function wxText(){const w=(S.snap||{}).weather;return w?`${w.city||''} ${w.temp}°C ${w.desc||''}`:'Hava durumu yok'}
function needCount(){const sn=S.snap;if(!sn)return 0;return (sn.pending_facts||[]).length+(sn.llm&&!sn.llm.key?1:0)+(sn.google&&!sn.google.token?1:0)}
function checks(){const sn=S.snap||{},f=sn.flags||{},l=sn.llm||{},sy=sn.sys||{};
  return [['spark','Yapay Zekâ',l.key?['Anahtar tanımlı','good']:['Anahtar yok','bad']],['wifi','İnternet Bağlantısı',sy.online===true?['Bağlı','good']:sy.online===false?['Yok','bad']:['Kontrol bekliyor','warn']],
    ['mic','Mikrofon',f.sleep?['Uykuda','warn']:f.mic?['Hazır','good']:['Kapalı','warn']],['image','Görsel Analiz',l.key?['Hazır','good']:['Kapalı','warn']],['grid','Komut Motoru',sn.engine_running===false||sn.degraded?['Kontrol gerekli','bad']:sn.engine_running?['Çalışıyor','good']:['Kontrol bekliyor','warn']]]}
function health(){const c=checks();const pts=c.reduce((a,x)=>a+(x[2][1]==='good'?2:x[2][1]==='warn'?1:0),0);return Math.round(pts/(c.length*2)*100)}
function renderHomeRail(){
  const sn=S.snap||{},acts=activities(),ev=(sn.events||[]).slice(0,3),gh=sn.github||{};
  const when=w=>{try{return whenTxt(w)}catch(e){return String(w||'').slice(0,16)}};
  const dotc=['y','c','g','g','y'];
  const [ghTxt,ghKind]=ghState(gh);
  $('#rail').innerHTML=`<section class="card hcard"><div class="ch"><span class="ct">Canlı Aktivite</span><span class="hs good"><span class="dot"></span>JARVIS ${esc((STATE_TXT[(sn.flags||{}).sleep?'sleep':S.orb]||STATE_TXT.idle)[0])}</span></div>
    ${acts.length?acts.slice(0,5).map((a,i)=>`<div class="htl"><span class="dot ${dotc[i%5]}"></span><time>${a.tm}</time><span>${esc(a.t)}</span></div>`).join(''):'<div class="empty">Henüz bir aktivite yok.</div>'}</section>
   <section class="card hcard"><div class="ch"><span class="ct">Yaklaşan Hatırlatmalar</span><button class="link" data-act="tool" data-k="takvim">Tümü</button></div>
    ${ev.length?ev.map(e=>`<div class="hrem"><span>${ic('calendar')}</span><b>${esc(e.title||'Hatırlatma')}</b><em>${esc(when(e.when))}</em></div>`).join(''):'<div class="empty">Yaklaşan hatırlatma yok.</div>'}</section>
   <section class="card hcard"><div class="ch"><span class="ct">Notlarım</span><button class="link" data-act="tool" data-k="takvim">Tümü</button></div><div style="max-height:190px;overflow:auto">${(sn.notes||[]).slice().reverse().map(n=>`<button class="homenotetitle" data-act="homenoteopen" data-id="${n.id}" title="${esc(n.title||String(n.text||'Görsel not').split('\n')[0].slice(0,120))}">${ic(n.photo?'image':'edit')}<span>${esc(n.title||String(n.text||'Görsel not').split('\n')[0].slice(0,60))}</span></button>`).join('')||'<div class="empty">Henüz not yok.</div>'}</div><button class="btn sm" data-act="homenote">${ic('plus')} Not ekle</button></section>
   <section class="card hhey ${S.orb==='listening'?'live':''}"><div class="hwave"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div><div><b>Hey ${esc(sn.aname||'Jarvis')}</b><small>${esc(heyTxt())}</small></div></section>`;
}
// GitHub durumu ve yükle/al düğmeleri (ana ekrandan Ayarlar › Gelişmiş'e taşındı; yalnız kullanıcı basınca çalışır)
// Araçlar (eski ayrı sayfa) Ayarlar › Gelişmiş içinde: kartlar aynı araç görünümlerini açar.
function toolsBox(){
  return sbox('gear','Araçlar','Takvim, görevler, telefon ve bakım.',`<div class="agrid" style="padding:12px 18px">${TOOLS.filter(x=>x[0]!=='aihub').map(([k,c,i,t,s])=>`<button class="acard ${c}" data-act="tool" data-k="${k}"><span class="ib ${c}">${ic(i)}</span><b>${t}</b><small>${s}</small><span class="go">${ic('chev')}</span></button>`).join('')}</div>`);
}
function githubBox(){
  const gh=(S.snap||{}).github||{},[ghTxt,ghKind]=ghState(gh),st=gh.sync_state;
  const info=st==='synced'?'Yüklenecek değişiklik yok':st==='remote_ahead'?'GitHub’da bu bilgisayardan daha yeni sürüm var':gh.local_count?`${gh.local_count} dosya GitHub’a yüklenmeyi bekliyor`:'GitHub durumu doğrulanmayı bekliyor';
  const btn=st==='remote_ahead'?`<button class="btn sm pri" data-act="ghpull">${ic('down')} GitHub’dan Al</button>`:st==='diverged'?`<button class="btn sm pri" data-act="ghresolve">${ic('down')} Yedekle ve GitHub’dan Al</button>`:`<button class="btn sm pri" data-act="ghpublish">${ic('up')} GitHub’a Yükle</button>`;
  return sbox('branch','GitHub','Kaynak sürümü ve yedek; yalnız sen basınca çalışır.',srow('branch','main',esc(info),`<span class="hs ${ghKind}"><span class="dot ${ghKind==='good'?'':'warn'}"></span>${esc(ghTxt)}</span>`)+pad18(btn));
}
function ghState(gh){gh=gh||{};if(!gh.token)return['Anahtar yok','warn'];const st=gh.sync_state;
  return st==='synced'?['Senkron','good']:st==='local_changes'?[(gh.local_count||'')+' dosya bekliyor','warn']:st==='remote_ahead'?['GitHub’da yeni sürüm','warn']:st==='diverged'?['Çakışma','bad']:st==='offline'?['Ulaşılamadı','warn']:['Kontrol bekliyor','warn']}
function heyTxt(){const f=(S.snap||{}).flags||{};return f.sleep?'Uykuda…':!f.mic?'Mikrofon kapalı':S.orb==='listening'?'Dinliyor…':S.orb==='speaking'?'Konuşuyor…':S.orb==='thinking'?'Düşünüyor…':'Seni bekliyor'}
function renderRail(){
  if(S.page==='home')return renderHomeRail();
  if(S.page==='settings'&&false)return;
  const h=health(),dash=2*Math.PI*42,hc=h>=80?'#22d3ee':h>=50?'#ffb020':'#ff4d6a';
  $('#rail').innerHTML=`<section class="card"><div class="ch"><span class="ct">Sistem Durumu</span><button class="link" data-act="tool" data-k="tarama">Tara</button></div>
    <div class="health"><div class="ring"><svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="42" fill="none" stroke="rgba(60,140,220,.18)" stroke-width="7"/><circle cx="50" cy="50" r="42" fill="none" stroke="${hc}" stroke-width="7" stroke-linecap="round" stroke-dasharray="${dash*h/100} ${dash}" style="filter:drop-shadow(0 0 6px ${hc})"/></svg><b>${h}%</b></div>
     <div class="t"><small>Yapılandırma durumu</small><b style="color:${hc}">${h>=80?'Hazır':h>=50?'Kısmen hazır':'Dikkat'}</b></div></div>
    ${checks().map(([i,t,[s,k]])=>`<div class="srow"><span class="i">${ic(i)}</span>${t}<span class="st ${k}"><span class="dot ${k==='good'?'':k}"></span>${s}</span></div>`).join('')}</section>`;
}
function activities(){
  const sn=S.snap||{};const out=[];
  (sn.activity||[]).slice().reverse().forEach(a=>{if(a.status==='start'||/^(Komut motoru|Jarvis aracı|Aktivite ekranı)/.test(a.text||''))return;let t=a.text||'';if(/^Yanıt kullanıcıya iletildi/.test(t))t='Sohbet tamamlandı';
    const s=(t+' '+(a.detail||'')).toLowerCase();let i='msg',c='navy';
    if(/excel|xlsx/.test(s)){i='grid';c='green'}else if(/youtube|müzik|video/.test(s)){i='play';c='red'}else if(/görsel|ekran|fotoğraf|resim/.test(s)){i='image';c='purple'}
    else if(/pdf|word|dosya|belge|özet/.test(s)){i='file';c='blue'}else if(/hata|başarısız|yapamadı/.test(s)){i='alert';c='red'}
    if(out.length<8&&!out.some(o=>o.t===t&&Math.abs(o.ts-a.ts)<60))out.push({t,i,c,ts:a.ts,tm:hm(a.ts)})});
  if(!out.length)(sn.feed||[]).slice().reverse().forEach(f=>{if(f.k==='user'&&out.length<6)out.push({t:f.t,i:'msg',c:'navy',ts:f.ts,tm:hm(f.ts)})});
  return out;
}

// ======================================================================= gezinme ve olaylar
// Eski Ayarlar/Araçlar adreslerinin menüdeki karşılığı (düğüm kimliği).
const SET_NODE={ai:'ai',baglanti:'ai',aihub:'ai',ses:'ses',takvim:'takvim',gorev:'gorev',iletisim:'telefon',telefon:'telefon',mesaj:'mesaj',ekran:'ekran',kb:'chat',hesap:'hesap',kullanici:'hesap',guvenlik:'hesap',hafiza:'hafiza',github:'github',sistem:'sistem',genel:'sistem',hakkinda:'sistem',araclar:'sistem',veri:'veri',rapor:'rapor',tarama:'tarama'};
function settingsNode(tool,sset){return SET_NODE[tool]||SET_NODE[sset]||'sistem'}
function go(p){if(!NAV.some(n=>n[0]===p))p='home';
  if(p==='vision'){S.mnOpen='ekran';p='menu'}
  if(p==='settings'||p==='tools'){S.mnOpen=settingsNode(p==='tools'?S.tool:'',S.sset);S.tool='';p='menu'}   // eski Ayarlar sayfası yok: ayarlar menüdeki yan sayfadan açılır
  if(p!=='chat'&&S.snap?.development?.enabled&&S.snap?.development?.unlocked){
    if(S.leavingDevelopment)return;S.leavingDevelopment=true;
    api('development_disable').then(result=>{if(!result.ok)throw new Error(result.message||'Geliştirme ekranından çıkılamadı.');S.snap.development.enabled=false;S.snap.development.unlocked=false;go(p);refreshSoon()}).catch(e=>toast(e.message,'bad')).finally(()=>{S.leavingDevelopment=false});return;
  }
  S.page=p;store.set('page',p);render()}

function render(){
  document.body.classList.toggle('home-full',['home','menu','chat','study','files'].includes(S.page));renderTop();const body=$('#body');body.classList.toggle('full',['home','menu','chat','study','files','vision','tools'].includes(S.page));
  const pg=$('#page'),keepHome=S.page==='home'&&!!HOME_HOLOGRAM&&pg.classList.contains('p-home')&&!!pg.querySelector('.hscene');   // ana ekran yeniden çizilirken hologram baştan kurulmaz (açılışta takılma)
  const keepScene=pg.classList.contains('p-menu')&&!!pg.querySelector('.mnscene')&&(S.page==='menu'||!!PAGE_NODE[S.page]);   // menü sahnesi korunur: orb kayarak yan sayfa açılır/kapanır
  if(!keepHome&&!keepScene){if(HOME_HOLOGRAM){HOME_HOLOGRAM.destroy();HOME_HOLOGRAM=null}pg.className='page p-'+S.page;pg.innerHTML=''}
  if(PAGE_NODE[S.page])renderPageDock(pg,S.page,PAGE_NODE[S.page]);else if(keepScene&&S.page==='menu')menuReopen(pg);else (PAGES[S.page]||PAGES.home)(pg);renderRail();drawDock();drawAtt();drawMiniPreview();
}
document.addEventListener('click',e=>{
  const g=e.target.closest('[data-go]');if(g){e.preventDefault();if(g.closest('.nav'))S.tool='';go(g.dataset.go);return}
  const sy=e.target.closest('[data-say]');if(sy){e.preventDefault();const v=sy.dataset.say;if(v.startsWith('#'))return go(v.slice(1));say(v);return}
  // Önce açık menüyü kapat, sonra düğmenin işini yap: yoksa profil/bildirim menüsü açılır açılmaz kapanıyordu.
  const a=e.target.closest('[data-act]');if(a&&ACT[a.dataset.act]){e.preventDefault();closeMenu();Promise.resolve(ACT[a.dataset.act](a,e)).catch(err=>toast(err.message||String(err),'bad'));return}
  if(!e.target.closest('.menu'))closeMenu();
});
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.matches('.ask input')){e.preventDefault();if(S.attPending)return toast('Dosyanın yüklenmesini bekle.');const v=e.target.value.trim();if(v||atts().length){e.target.value='';say(v)}}if(e.key==='Escape'){closeMenu();if(S.orb==='speaking'||S.sspeaking)ACT.dstop()}});

// ======================================================================= arayüze uygun soru pencereleri (tarayıcının gri kutusu yerine)
function _dlg(title,msg,input,def){return new Promise(res=>{const o=document.createElement('div');o.className='jdlg';
  o.innerHTML=`<div class="jbox"><div class="jt">${ic('spark')}<b>${esc(title)}</b></div><p>${esc(msg)}</p>${input?`<input class="jin" type="${input==='password'?'password':'text'}" autocomplete="${input==='password'?'current-password':'off'}" value="${esc(def||'')}">`:''}<div class="jbtn"><button class="jno">İptal</button><button class="jok">${input?'Tamam':'Evet'}</button></div></div>`;
  document.body.appendChild(o);const inp=o.querySelector('.jin');(inp||o.querySelector('.jok')).focus();
  const done=v=>{if(inp)inp.value='';o.remove();document.removeEventListener('keydown',kd,true);res(v)};
  const kd=e=>{if(e.key==='Escape'){e.stopPropagation();done(input?null:false)}else if(e.key==='Enter'){e.stopPropagation();e.preventDefault();done(input?inp.value:true)}};
  document.addEventListener('keydown',kd,true);
  o.querySelector('.jno').onclick=()=>done(input?null:false);o.querySelector('.jok').onclick=()=>done(input?inp.value:true);
  o.onclick=e=>{if(e.target===o)done(input?null:false)}})}
const ask=msg=>_dlg('JARVIS',msg,false);
const askText=(msg,def)=>_dlg('JARVIS',msg,true,def);
const ACT={};
ACT.devopen=async()=>{
 const owner=((S.snap||{}).user||{}).name,st=await api('development_status');
 if(!st.unlocked){const password=await _dlg('Şifre Korumalı Geliştirme Modu',st.password_set?'Geliştirme şifreni gir.':'İlk giriş: geliştirme için bir şifre oluştur (en az 6 karakter).','password','');if(password===null)return;
 if(owner!==((S.snap||{}).user||{}).name)return;
 const result=await api('development_unlock',password);if(!result.ok)return toast(result.message,'bad');}
 const enabled=await api('development_enable');
 if(!enabled.ok)return toast(enabled.message||'Geliştirme modu açılamadı.','bad');
 await refresh();go('chat');
};
ACT.devclose=async()=>{
 const result=await api('development_disable');
 if(!result.ok)return toast(result.message||'Geliştirme modu kapatılamadı.','bad');
 refreshSoon();
};
ACT.devexport=async()=>{const r=await api('development_export');await api('file_open',r.path);toast('Geliştirme dosyaları dışa aktarıldı.');};
ACT.devpassword=async()=>{
 const owner=((S.snap||{}).user||{}).name;
 const old=await _dlg('Şifre Korumalı Geliştirme Modu','Mevcut geliştirme şifren:','password','');if(old===null)return;
 const next=await _dlg('Şifre Korumalı Geliştirme Modu','Yeni geliştirme şifren:','password','');if(next===null||owner!==((S.snap||{}).user||{}).name)return;
 const r=await api('development_password_change',old,next);toast(r.message,r.ok?'':'bad');
};
ACT.homenoteopen=el=>{S.noteSelected=+el.dataset.id;S.tool='gorev';go('tools')};
ACT.homenote=()=>{S.tool='gorev';go('tools');setTimeout(()=>{const editor=$('#nti')?.closest('details');if(editor)editor.open=true;$('#nti')?.focus()},50)};
ACT.mute=async el=>{const on=((S.snap||{}).flags||{}).speak!==false;if(on)tryApi('stop_speaking');const f=await tryApi('set_flag','speak',!on);if(f===null||f===undefined)return;if(S.snap){S.snap.flags={...(S.snap.flags||{}),...((f&&typeof f==='object')?f:{}),speak:!on}}toast(on?'Jarvis susturuldu. Yazıyla cevap vermeye devam eder.':'Jarvis’in sesi açıldı.');$$('[data-act="mute"]').forEach(b=>{const c=b.classList.contains('hb2')?'hb2':'ab';b.outerHTML=muteBtn(c)})};
ACT.mictoggle=async()=>{if(S.page==='chat'&&S.snap?.development?.enabled&&S.snap?.development?.unlocked)return toast('Geliştirme ekranında ses kapalı; yazıyla devam et.');if(S.micToggling||!S.snap)return;const on=S.snap?.flags?.mic!==false,owner=S.snap?.user?.name;S.micToggling=true;try{const flags=await tryApi('set_flag','mic',!on);if(owner!==S.snap?.user?.name||!flags||typeof flags.mic!=='boolean')return;S.snap.flags={...(S.snap.flags||{}),...flags};$$('[data-act="mictoggle"]').forEach(b=>{b.outerHTML=micToggleBtn(b.classList.contains('hb2')?'hb2':'ab')});toast(flags.mic?'Mikrofon açıldı.':'Mikrofon kapatıldı.')}finally{S.micToggling=false}};
ACT.wmin=()=>tryApi('win','min');ACT.wfull=()=>tryApi('win','full');ACT.wclose=async ()=>{if(await ask('Jarvis kapatılsın mı?'))tryApi('shutdown')};
function openAiHub(tab='ai'){S.sset=tab;S.tool='aihub';go('tools')}
ACT.keysetup=()=>openAiHub('baglanti');
async function say(text){
  if(S.attPending)return toast('Dosyanın yüklenmesini bekle.');
  const _q=String(text||'').trim(),_noAtt=!(Array.isArray(S.att)?S.att.length:(S.att?1:0));  // "dosyalarımı göster" / "takvimim": tarayıcıda cevaplanır, modele gitmez
  if(_noAtt&&/^(dosyalar[ıi]m[ıi]?(\s+(g[öo]ster|listele))?|son\s+y[üu]klediklerim|y[üu]klediğim\s+dosyalar|dosyalar[ıi]\s+(g[öo]ster|listele))\s*[.!?]*$/i.test(_q))return showFileCards(text);
  if(_noAtt&&/^(takvimim|ajandam|hat[ıi]rlatmalar[ıi]m|g[öo]revlerim|yakla[şs]an\s+(hat[ıi]rlatmalar|etkinlikler|g[öo]revler)|takvimi\s+g[öo]ster|g[öo]revleri\s+g[öo]ster)\s*[.!?]*$/i.test(_q))return showAgendaCard(text);
  // Ekli dosyalar tek istekte gider ('"a" "b" talimat'): sunucu karşılaştırma/birleştirme gibi işleri birlikte yapar,
  // diğer işleri dosya dosya yürütür. Sunucunun yankısı aynı metinle geldiği için balon tekrarlanmaz.
  const files=Array.isArray(S.att)?S.att:(S.att?[S.att]:[]);if(files.length){S.att=[];drawAtt()}
  if(S.page!=='chat'){S.day=ymd(new Date());go('chat')}
  const sends=files.length?[files.map(a=>`"${a.path}"`).join(' ')+' '+(text||(files.length>1?'dosyalarını kapsamlı analiz et':'dosyasını kapsamlı analiz et'))]:[text];
  for(const send of sends){
    S.live.push({role:'user',text:send,ts:Date.now()/1000,mine:true});S.waiting=true;drawMsgs();
    try{const rid=globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+Math.random().toString(36).slice(2);const queued=await api('send',send,rid);if(queued===false){S.waiting=false;drawMsgs()}}catch(e){S.waiting=false;drawMsgs();toast(e.message,'bad');break}
  }
}
ACT.send=el=>{if(S.attPending)return toast('Dosyanın yüklenmesini bekle.');const i=el.closest('.ask').querySelector('input');const v=i.value.trim();if(v||atts().length){i.value='';say(v)}};
ACT.mic=async()=>{if(S.page==='chat'&&S.snap?.development?.enabled&&S.snap?.development?.unlocked)return toast('Geliştirme ekranında ses kapalı; yazıyla devam et.');const listening=await tryApi('listen_once');if(listening===false)return toast('Mikrofon kapalı. Önce mikrofonu aç.');if(listening===true)toast('Dinliyorum… konuşabilirsin.')};
ACT.attach=()=>{if(S.page==='chat'||S.page==='home')return pickAttach();pickUpload(null)};
async function attachChatFile(file){
 if(atts().length+(S.attPending||0)>=MAX_ATT)return toast(`En fazla ${MAX_ATT} dosya ekleyebilirsin.`);
 if(file.size===0)return toast(`${file.name} boş; eklenmedi.`,'bad');
 if(file.size>MAX_ATT_BYTES)return toast(`${file.name} 200 MB'tan büyük; eklenmedi.`,'bad');
 const owner=S.snap?.user?.name;S.attPending=(S.attPending||0)+1;drawAtt();
 toast(`${file.name} yükleniyor…`);
 try{
  const r=await upload(file,true);
  if(!r||owner!==S.snap?.user?.name)return;
  S.att=[...atts(),{path:r.path,name:file.name}];S.files=null;
  toast(`${file.name} eklendi. Ne yapmamı istediğini yazıp gönder.`);
  $('.ask input')?.focus();
 }finally{S.attPending=Math.max(0,(S.attPending||0)-1);drawAtt()}
}
const MAX_ATT=10,MAX_ATT_BYTES=200_000_000;
const atts=()=>Array.isArray(S.att)?S.att:(S.att?[S.att]:[]);
function pasteChatImage(e){
 if(!['chat','home'].includes(S.page)||!e.target.matches?.('.ask input'))return;
 const items=Array.from(e.clipboardData?.items||[]);
 const item=items.find(x=>x.kind==='file'&&x.type.startsWith('image/'));
 const image=item?.getAsFile()||Array.from(e.clipboardData?.files||[]).find(x=>x.type.startsWith('image/'));
 if(!image)return;
 e.preventDefault();
 const ext=({'image/png':'png','image/jpeg':'jpg','image/webp':'webp','image/gif':'gif'})[image.type]||'png';
 const file=new File([image],`ekran-${Date.now()}.${ext}`,{type:image.type});
 return attachChatFile(file);
}
document.addEventListener('paste',pasteChatImage);
// Pencerenin her yerine bırakılan dosya tarayıcıda açılmaz, sohbete eklenir. Kendi bırakma alanı olan kutular
// (ör. Matematik) olayı önce işler; o zaman burada tekrar yüklenmez.
let dragDepth=0;
const dragKind=e=>{const t=[...(e.dataTransfer?.types||[])];return t.includes('Files')?'file':t.some(x=>x==='text/uri-list'||x==='text/plain')?'text':''};
const editable=el=>!!el?.closest?.('input,textarea,[contenteditable="true"]');
function dropOverlay(on){let o=$('#dropov');if(on&&!o){o=document.createElement('div');o.id='dropov';o.className='dropov';o.innerHTML=`<div>${ic('clip')}<b>Dosyaları sohbete eklemek için bırak</b><small>En fazla ${MAX_ATT} dosya · her biri en fazla 200 MB</small></div>`;document.body.appendChild(o)}else if(!on&&o)o.remove()}
function droppedFiles(dt){
 const items=[...(dt?.items||[])].filter(it=>it.kind==='file');let folders=0;
 if(!items.length)return {files:[...(dt?.files||[])],folders};
 const files=[];for(const it of items){const entry=it.webkitGetAsEntry?.();if(entry?.isDirectory){folders++;continue}const f=it.getAsFile();if(f)files.push(f)}
 return {files,folders};
}
async function dropToChat(files,folders,text){
 if(folders)toast('Klasör eklenemez; klasörün içindeki dosyaları seçip bırak.','bad');
 if(!files.length){if(text){const i=$('.ask input');if(i){i.value=(i.value?i.value+' ':'')+text.trim();i.focus()}}return}
 if(!['chat','home'].includes(S.page)){S.day=ymd(new Date());go('chat')}
 for(const f of files)await attachChatFile(f);
}
document.addEventListener('dragenter',e=>{const k=dragKind(e);if(!k||(k==='text'&&editable(e.target)))return;e.preventDefault();if(k==='file'){dragDepth++;dropOverlay(true)}});
document.addEventListener('dragover',e=>{const k=dragKind(e);if(!k||(k==='text'&&editable(e.target)))return;e.preventDefault();if(e.dataTransfer)e.dataTransfer.dropEffect='copy'});
document.addEventListener('dragleave',e=>{if(dragKind(e)!=='file')return;dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)dropOverlay(false)});
document.addEventListener('dragend',()=>{dragDepth=0;dropOverlay(false)});
document.addEventListener('drop',e=>{dragDepth=0;dropOverlay(false);const k=dragKind(e);if(!k||e.defaultPrevented||(k==='text'&&editable(e.target)))return;e.preventDefault();
 const {files,folders}=droppedFiles(e.dataTransfer);const text=files.length?'':(e.dataTransfer.getData('text/uri-list')||e.dataTransfer.getData('text/plain')||'');
 dropToChat(files,folders,text).catch(err=>toast(err.message||String(err),'bad'))});
function pickAttach(accept=''){const inp=$('#upl');inp.accept=accept;inp.onchange=async()=>{const fs=[...inp.files];inp.value='';for(const f of fs)await attachChatFile(f)};inp.click()}
function drawAtt(){const list=atts();$$('.attc').forEach(c=>{c.innerHTML=list.map((a,i)=>`<span class="attchip" title="${esc(a.path)}">${ic('clip')}<b>${esc(a.name)}</b><button data-act="attx" data-i="${i}" title="Kaldır">×</button></span>`).join('')+(S.attPending?`<span class="attchip pending">${ic('clock')}<b>Yükleniyor…</b></span>`:'')})}
ACT.attx=el=>{const i=Number(el?.dataset?.i);S.att=atts().filter((_,k)=>k!==i);drawAtt()};
ACT.image=()=>{if(S.page==='chat'||S.page==='home')return pickAttach('image/*');pickUpload('gorsel','image/*')};
function pickUpload(action,accept){const inp=$('#upl');inp.accept=accept||'';inp.onchange=async()=>{const fs=[...inp.files];inp.value='';for(const f of fs){const r=await upload(f);if(r&&action)await doFile(r.path,action)}if(!action&&fs.length){S.files=null;S.fcat='mine';S.fsel=null;toast(`${fs.length} dosya Belgeler › Jarvis Dosyaları klasörüne kaydedildi.`);if(S.page==='files')render()}};inp.click()}
async function upload(file,quiet){
  if(!quiet)toast(`${file.name} yükleniyor…`);
  try{const r=await fetch('/upload?to=files&name='+encodeURIComponent(file.name),{method:'POST',headers:{'X-Jarvis-Token':TOKEN},body:file});const j=await r.json();if(!j.ok)throw new Error(j.error);if(!quiet)toast(`${file.name} yüklendi (Belgeler › Jarvis Dosyaları).`);return j.data}
  catch(e){toast('Yüklenemedi: '+e.message,'bad')}
}
async function doFile(path,action){
  const cmd=await tryApi('file_do',path,action);if(!cmd)return;
  S.day=ymd(new Date());S.live.push({role:'user',text:cmd,ts:Date.now()/1000,mine:true});S.waiting=true;if(S.page!=='chat')go('chat');else drawMsgs();
}
function menu(x,y,items){closeMenu();const m=document.createElement('div');m.className='menu';m.id='menu';
  m.innerHTML=items.map((it,i)=>it==='-'?'<hr>':`<button data-mi="${i}">${it[0]?ic(it[0]):''}${esc(it[1])}</button>`).join('');document.body.appendChild(m);
  const r=m.getBoundingClientRect();m.style.left=Math.min(x,innerWidth-r.width-10)+'px';m.style.top=Math.min(y,innerHeight-r.height-10)+'px';
  m.onclick=e=>{const b=e.target.closest('[data-mi]');if(b){closeMenu();items[+b.dataset.mi][2]()}}}
function closeMenu(){const m=$('#menu');if(m)m.remove()}
ACT.user=(el,e)=>{const sn=S.snap||{};const us=sn.users||[];const me=(sn.user||{}).name;const r=el.getBoundingClientRect();
  menu(r.left,r.bottom+8,[...us.map(u=>['user',u+(u===me?'  ·  aktif':''),()=>{if(u!==me)api('user_switch',u).then(()=>setTimeout(refresh,800))}]),'-',['gear','Ayarlar',()=>go('settings')],['power','Jarvis’i kapat',async ()=>{if(await ask('Jarvis kapatılsın mı?'))api('shutdown')}]]);
  const m=$('#menu');if(m){m.classList.add('umenu');m.style.width=r.width+'px';[...m.querySelectorAll('button')].forEach(b=>{if(/·  aktif$/.test(b.textContent))b.classList.add('on')})}};
ACT.notif=el=>{const sn=S.snap||{},r=el.getBoundingClientRect(),it=[];
  if((sn.pending_facts||[]).length)it.push(['spark',`${sn.pending_facts.length} bilgi onay bekliyor`,()=>{S.sset='hafiza';go('settings')}]);
  if(sn.llm&&!sn.llm.key)it.push(['key','Gemini anahtarı eksik',()=>openAiHub('baglanti')]);
  if(sn.google&&!sn.google.token)it.push(['mail','Gmail ve Takvim bağlı değil',()=>openAiHub('baglanti')]);
  if(!it.length)it.push(['check','Yeni bildirim yok',()=>{}]);menu(r.left-120,r.bottom+6,it)};

// ======================================================================= ortak parçalar
const micToggleBtn=(cls='ab')=>{if(S.page==='chat'&&S.snap?.development?.enabled&&S.snap?.development?.unlocked)return '';const off=S.snap?.flags?.mic===false;return `<button class="${cls} mic-toggle ${off?'off':''}" data-act="mictoggle" title="${off?'Mikrofonu aç':'Mikrofonu kapat'}" aria-label="${off?'Mikrofonu aç':'Mikrofonu kapat'}" aria-pressed="${off}">${ic('mic')}</button>`};
const pcMuteBtn=(cls='ab')=>{const off=S.pcMuted===true;return `<button class="${cls} pcmute ${off?'off':''}" data-act="pcmute" title="${off?'Bilgisayarın sesini aç':'Bilgisayarın tüm sesini kapat'}" aria-label="${off?'Bilgisayarın sesini aç':'Bilgisayarın tüm sesini kapat'}" aria-pressed="${off}">${ic(off?'speakerx':'speaker')}</button>`};
function drawPcMute(){$$('[data-act="pcmute"]').forEach(b=>{b.outerHTML=pcMuteBtn(b.classList.contains('hb2')?'hb2':'ab')})}
function loadPcMute(){api('pc_mute_state').then(r=>{S.pcMuted=r&&typeof r.muted==='boolean'?r.muted:null;drawPcMute()}).catch(()=>{})}
ACT.pcmute=async()=>{if(S.pcMuteBusy)return;S.pcMuteBusy=true;try{const r=await tryApi('pc_mute',S.pcMuted!==true);if(r&&typeof r==='object'){S.pcMuted=r.muted===true;toast(S.pcMuted?'Bilgisayarın tüm sesi kapatıldı.':'Bilgisayarın sesi açıldı.');drawPcMute()}}finally{S.pcMuteBusy=false}};
const muteBtn=(cls='ab')=>{const off=((S.snap||{}).flags||{}).speak===false;return `<button class="${cls} amute ${off?'off':''}" data-act="mute" title="${off?'Jarvis’in sesini aç':'Jarvis’i sustur (yazıyla cevap verir)'}">${ic(off?'volx':'vol')}</button>`};
const DOCK_PH={home:'JARVIS\'e Bir Şey Söyle...',vision:'Ekran Ya Da Görsel Hakkında Bir Şey Sor...',files:'Dosyalar Hakkında Bir Şey Sor...',study:'Çalışma Konusu Hakkında Sor...',settings:'Bir Şey Söyle Veya Yaz...'};
const DOCK_ST={idle:'Hazır',listening:'Dinliyor',thinking:'Düşünüyor',working:'Çalışıyor',speaking:'Konuşuyor'};
function drawDock(){let d=$('#dock');const host=$('#dockhost');if(!d){d=document.createElement('div');d.id='dock';d.className='dock';if(host)host.appendChild(d);else $('#body').insertBefore(d,$('#rail'))}
  else if(host&&d.parentElement!==host)host.appendChild(d);else if(!host&&d.parentElement&&d.parentElement.id!=='body')$('#body').insertBefore(d,$('#rail'));
  const old=d.querySelector('input'),v=old?old.value:'',f=old&&document.activeElement===old;d.innerHTML=askBar(DOCK_PH[S.page]||'Bir Şey Söyle Veya Yaz...');dockState();const i=d.querySelector('input');i.value=v;if(f)i.focus()}
function dockState(){if(S.sspeaking){if(S.orb==='speaking')S._spk2=1;else if(S._spk2&&S.orb==='idle'){S.sspeaking=0;S._spk2=0;const la=$('#slessonact');if(la)la.innerHTML=lessonActs()}}const d=$('#dock');if(!d)return;const s=DOCK_ST[S.orb]?S.orb:'idle';d.dataset.s=s;const b=d.querySelector('.dst');if(b)b.textContent=DOCK_ST[s]}
const askBar=(ph='Bir Şey Söyle Veya Yaz...')=>`<div class="card hask ask"><button class="hb2" data-act="attach" title="Dosya ekle">${ic('plus')}</button>${shareBtns()}${S.page==='chat'&&S.snap?.development?.enabled&&S.snap?.development?.unlocked?'':`<button class="hb2 mic ${S.orb==='listening'?'live':''}" data-act="mic" title="Konuş">${ic('mic')}</button>`}${micToggleBtn('hb2')}${muteBtn('hb2')}${pcMuteBtn('hb2')}<span class="attc"></span><input placeholder="${S.page==='chat'&&S.snap?.development?.enabled&&S.snap?.development?.unlocked?'Geliştirme ekranı: yaz veya görsel ekle':ph}" autocomplete="off"><span class="dst"></span><button class="dstop" data-act="dstop" title="Konuşmayı durdur (Esc)">${ic('volx')}<span>Durdur</span></button><button class="hsend" data-act="send" title="Gönder">${ic('send')}</button></div>`;
// Jarvis'in "gözü": ekran ve kamera paylaşımı sohbet çubuğundan açılır/kapanır (görsel eklemek için + yeterli).
const shareBtns=()=>{const mode=(S.snap||{}).mode;return [['screen','monitor','Ekranı paylaş','Ekran paylaşımını kapat'],['camera','camera','Kamerayı aç','Kamerayı kapat']].map(([m,i,on,off])=>`<button class="hb2 ${mode===m?'live':''}" data-act="vis" data-a="act:share:${m}" title="${mode===m?off:on}">${ic(i)}</button>`).join('')};
const STATE_TXT={idle:['Hazır','Seni bekliyorum...'],listening:['Dinliyor','Seni dinliyorum...'],thinking:['Düşünüyor','Yanıt hazırlanıyor...'],speaking:['Konuşuyor','Yanıt veriliyor...'],sleep:['Uykuda','“Jarvis uyan” de']};

// ======================================================================= ANA SAYFA
const PAGES={};

// ---- Ana ekran büstü: sağdaki enerji küresinden çıkan parçacıklar kavisle silüetin sol omzuna gelir ve büstü soldan sağa kurar (yalnız yerel canvas; model/ağ yok).
// Her ana ekran açılışında kurulur (ilk ~6 sn, sonrakiler ~3,5 sn), sonra büst sürekli hareket eder. Ayar: nx_bust (varsayılan açık).
const BUST={vecOn:store.get('bustvec',false),img:null,pts:null,done:false,loading:false,asm:null,yaw:0,pit:0,mm:null,tiles:null};
const BUST_COL=(()=>{const c=[];for(let i=0;i<4;i++)c.push([255,140+i*28,40+i*30]);for(let i=0;i<8;i++)c.push([40+i*14,150+i*12,255]);return c})();   // 0-3 turuncu, 4-11 mavi-camgöbeği
// Renk tonu: Apex Humanoid'in ölçülen tonuna göre (kontur camgöbeği ~(36,142,170), parlak kenar ~(70,216,237); çekirdek sönük kehribar ~(149,79,15), parlak ~(213,129,33)). Mavi aile camgöbeğine, turuncu/kırmızı/sarı aile kehribara çekilir; parlaklık (en büyük kanal) korunur.
const BUST_TONE_OFF=true;   // bust.jpg artık Apex Humanoid videosunun karesi (12 Ekim 2026): renkler zaten doğru, ton dönüşümü kapalı (açıkken turuncu çekirdek sarı/bulanık oluyordu)
function bustTone(r,g,b,yf){if(BUST_TONE_OFF){const m0=Math.max(r,g,b),hd=yf==null?0:Math.max(0,Math.min(1,(.62-yf)/.12));return[r,g,b,b>=r?(m0>150?1:m0>110?.65-.15*hd:.36-.18*hd):1]}const m=Math.max(r,g,b);if(m<=0)return[0,0,0,1];   // ton kapalıyken mavi pikseller %20 sönük (Hamdi: mavi kenar çok parlak)
  if(b>=r&&b>=g){const u=Math.min(1,(r+g)/(2*b)*1.5);return[m*(.17+.12*u),m*(.80+.12*u),m,1]}
  if(r>=b&&r>=g){const q=Math.min(1,g/r),gr=.46+.34*q;return[m,m*gr,m*(.10+.18*q*q),.82]}   // kehribar, biraz daha sönük
  return[r,g,b,1]}
function bustLoad(cb){
  if(BUST.pts)return cb();(BUST.q=BUST.q||[]).push(cb);if(BUST.loading)return;BUST.loading=true;   // ana ekran açılışta iki kez çizilebilir: her çizimin geri çağrısı sıraya girer
  const fail=()=>{BUST.loading=false;BUST.q=[];document.querySelectorAll('.hs-greet').forEach(g=>g.classList.add('show'))};   // her hatada en azından selam görünür
  if(!BUST.bd){BUST.bd={img:null,hl:[]};const bi=new Image();bi.onload=()=>{try{
    // Parlak yerler yalnız burada, bir kez saptanır (160x90 ızgara, yerel en parlak noktalar); renkleri resimden örneklenir. Resmin kendisi değişmez, kare başına çözümleme yok.
    const w=160,h=Math.round(w*bi.height/bi.width),c=document.createElement('canvas');c.width=w;c.height=h;const x=c.getContext('2d',{willReadFrequently:true});x.drawImage(bi,0,0,w,h);const d=x.getImageData(0,0,w,h).data,L=(i,j)=>{const o=(j*w+i)*4;return Math.max(d[o],d[o+1],d[o+2])},hl=[];
    for(let j=1;j<h-1;j++)for(let i=1;i<w-1;i++){const l=L(i,j);if(l<150)continue;let top=true;for(let a=-2;a<=2&&top;a++)for(let b=-2;b<=2;b++){if((a||b)&&i+a>=0&&j+b>=0&&i+a<w&&j+b<h&&L(i+a,j+b)>l){top=false;break}}
      if(top){const o=(j*w+i)*4;hl.push([(i+.5)/w,(j+.5)/h,d[o],d[o+1],d[o+2],Math.random()*6.28,.5+Math.random()])}}
    hl.sort((p,q)=>Math.max(q[2],q[3],q[4])-Math.max(p[2],p[3],p[4]));BUST.bd.hl=hl.slice(0,90);BUST.bd.img=bi}catch(e){}};bi.src='/backdrop.webp'}
  const im=new Image();im.onload=()=>{try{
    // Siyah zemini saydamlığa çevir: alfa = en parlak kanal, renk = alfaya göre açılmış (zemin ne olursa olsun kutu görünmez)
    {const pc=document.createElement('canvas');pc.width=im.width;pc.height=im.height;const pg=pc.getContext('2d',{willReadFrequently:true});pg.drawImage(im,0,0);const id=pg.getImageData(0,0,pc.width,pc.height),q=id.data;
      const tw=[1],mm=new Uint8Array(q.length/4);for(let i=0;i<q.length;i+=4){const m=Math.max(q[i],q[i+1],q[i+2]);mm[i>>2]=m;const aa=Math.max(0,Math.min(1,(m-18)/46));if(aa<=0){q[i+3]=0;continue}const tn=bustTone(q[i],q[i+1],q[i+2],((i>>2)/pc.width|0)/pc.height);q[i]=tn[0];q[i+1]=tn[1];q[i+2]=tn[2];tw[0]=tn[3];   // ton: Apex Humanoid renkleri
      const k=255/m;q[i]=Math.min(255,q[i]*k);q[i+1]=Math.min(255,q[i+1]*k);q[i+2]=Math.min(255,q[i+2]*k);q[i+3]=Math.min(255,255*Math.pow(Math.min(1,m*1.1/255),1.5))*aa*tw[0]}   // alfa eğrisi: yumuşak halka incelir (site gibi ince çizgiler), parlak çizgiler korunur   // koyu gri jpeg lekeleri tamamen saydamlaşır
      pg.putImageData(id,0,0);BUST.img=pc;
      {const cc=document.createElement('canvas');cc.width=pc.width;cc.height=pc.height;const cg=cc.getContext('2d'),cd=cg.createImageData(pc.width,pc.height),dd=cd.data,y0=Math.floor(.5*pc.height)*pc.width*4;
        // göğüs katmanı: iç çizgiler eskisi gibi güçlenir (Hamdi: alt kısım boş), dış kenara %3,5 genişlikten yakın pikseller hariç (omuz kenarı bulanıklaşmasın)
        const PW=pc.width,eL=new Int32Array(pc.height).fill(-1),eR=new Int32Array(pc.height).fill(-1);for(let y=0;y<pc.height;y++){for(let x=0;x<PW;x++){if(mm[y*PW+x]>110){if(eL[y]<0)eL[y]=x;eR[y]=x}}}
        const mg=Math.round(PW*.035);for(let i=y0;i<dd.length;i+=4){const mv=mm[i>>2];if(mv<14)continue;const px=(i>>2)%PW,py=((i>>2)/PW)|0;if(eL[py]<0||px<eL[py]+mg||px>eR[py]-mg)continue;dd[i]=q[i];dd[i+1]=q[i+1];dd[i+2]=q[i+2];dd[i+3]=Math.min(190,(mv-12)*2.2)*Math.max(0,Math.min(1,(175-mv)/60))}   // yalnız silik çizgiler güçlenir (parlak omuz/boyun kalınlaşmaz)
        cg.putImageData(cd,0,0);cg.globalCompositeOperation='destination-in';const lg=cg.createLinearGradient(0,.60*pc.height,0,.75*pc.height);lg.addColorStop(0,'rgba(0,0,0,0)');lg.addColorStop(1,'rgba(0,0,0,1)');cg.fillStyle=lg;cg.fillRect(0,0,pc.width,pc.height);BUST.chest=cc}
      {const s3=3,w3=Math.ceil(pc.width/s3),h3=Math.ceil(pc.height/s3),sc=document.createElement('canvas');sc.width=w3;sc.height=h3;const sg=sc.getContext('2d'),sd=sg.createImageData(w3,h3),D=sd.data;   // figürün dolu silüeti: arkadaki dağlar gövdenin içinden görünmesin (Hamdi: iç içe geçme)
        for(let y=0;y<h3;y++){let L=-1,R=-1;const yy=Math.min(pc.height-1,y*s3)*pc.width;for(let x=0;x<w3;x++){if(mm[yy+Math.min(pc.width-1,x*s3)]>110){if(L<0)L=x;R=x}}if(L>=0&&R-L>4)for(let x=L;x<=R;x++)D[(y*w3+x)*4+3]=255}
        sg.putImageData(sd,0,0);const bc=document.createElement('canvas');bc.width=w3;bc.height=h3;const bg=bc.getContext('2d');bg.filter='blur(4px)';bg.drawImage(sc,0,0);BUST.sil=bc}   // göğüs vurgusu: silik gövde çizgileri güçlendirilir (site gibi dolu göğüs), yalnız alt kısım, üstte yumuşak geçişle; bir kez hazırlanır
    }
    const W=340,H=Math.round(W*im.height/im.width),c=document.createElement('canvas');c.width=W;c.height=H;const g=c.getContext('2d',{willReadFrequently:true});g.drawImage(im,0,0,W,H);
    const d=g.getImageData(0,0,W,H).data,pts=[];
    for(let y=0;y<H;y++)for(let x=0;x<W;x++){const i=(y*W+x)*4,r=d[i],gg=d[i+1],b=d[i+2],l=Math.max(r,gg,b);if(l>64){const u=(x+Math.random())/W,v=(y+Math.random())/H;
      const k=r>gg*1.1&&r>b?Math.min(3,Math.floor((l-64)/48)):4+Math.min(7,Math.floor((l-64)/24));
      // gecikme: sol omuzdan (0.17, 0.70) uzaklığa göre; büst soldan sağa kurulur
      const dl=Math.min(1,Math.hypot(u-.17,(v-.70)*.9)/1.05)*.58+Math.random()*.05;
      pts.push([u,v,k,dl,(Math.random()-.5),.85+Math.random()*.3])}}
    {const sum=BUST_COL.map(()=>[0,0,0,0]);for(let y=0;y<H;y++)for(let x=0;x<W;x++){const i=(y*W+x)*4,r=d[i],gg=d[i+1],b=d[i+2],l=Math.max(r,gg,b);if(l>64){const k=r>gg*1.1&&r>b?Math.min(3,Math.floor((l-64)/48)):4+Math.min(7,Math.floor((l-64)/24)),q=sum[k];q[0]+=r;q[1]+=gg;q[2]+=b;q[3]++}}
      sum.forEach((q,k)=>{if(q[3]>20){{const tn=bustTone(q[0],q[1],q[2]);q[0]=tn[0];q[1]=tn[1];q[2]=tn[2]}const m=Math.max(q[0],q[1],q[2])/q[3],f=Math.min(1,190/Math.max(60,m));BUST_COL[k]=[Math.min(255,q[0]/q[3]*f),Math.min(255,q[1]/q[3]*f),Math.min(255,q[2]/q[3]*f)]}})}
    while(pts.length>9000)pts.splice((Math.random()*pts.length)|0,1);
    // Kafa parçacıkları: kafa bir elipsoit gibi alınır (merkez .492/.34, yarıçap .178/.26 resim ölçüsünde); kafa bölgesindeki parçacıklar derinlik (z) ve yüzey normali taşır. Dönerken bunlar (ve soluk bir taban resim) çizilir; bir kez hazırlanır.
    {const iw=BUST.img.width,ih=BUST.img.height,hx=.492*iw,hy=.34*ih,Rx=.178*iw,Ry=.26*ih,Rz=Rx*1.05,H=[];
      for(const p of pts){const cx=p[0]*iw,cy=p[1]*ih;if(p[1]>.575||p[0]<.24||p[0]>.76)continue;const nx=(cx-hx)/Rx,ny=(cy-hy)/Ry,d=nx*nx+ny*ny,inside=d<.985,z=inside?Rz*Math.sqrt(1-d):0;
        let gx=0,gy=0,gz=1;if(inside){gx=nx/Rx;gy=ny/Ry;gz=Math.sqrt(Math.max(0,1-d))/Rz;const l=Math.hypot(gx,gy,gz)||1;gx/=l;gy/=l;gz/=l}
        const wk=Math.max(0,Math.min(1,(cy-.5*ih)/(.12*ih))),wgt=1-wk*wk*(3-2*wk);   // boyuna doğru dönüş azalır
        H.push([cx,cy,z,gx,gz,inside?1:0,wgt,p[2],gy])}
      BUST.tiles={H,hx,hy,ih,iw,cut:.62*ih};
      // bükme için çalışma kopyası: kafa bölgesi (üst %62), satır başına silüet merkezi/yarı genişliği ve boyuna doğru azalan dönüş ağırlığı; bir kez hazırlanır
      {const k=Math.min(1,1400/iw),cutI=Math.round(.62*ih),ww=Math.round(iw*k),wh=Math.round(cutI*k),wc=document.createElement('canvas');wc.width=ww;wc.height=wh;const wg2=wc.getContext('2d',{willReadFrequently:true});wg2.drawImage(BUST.img,0,0,iw,cutI,0,0,ww,wh);
        const src=wg2.getImageData(0,0,ww,wh).data,hxw=hx*k,rxw=Rx*k,rc=new Float32Array(wh),rr=new Float32Array(wh),wg=new Float32Array(wh),lim=rxw*1.3;
        for(let y=0;y<wh;y++){let L=-1,Rt=-1;for(let x=Math.max(0,Math.floor(hxw-lim));x<=Math.min(ww-1,Math.ceil(hxw+lim));x++){if(src[(y*ww+x)*4+3]>110){if(L<0)L=x;Rt=x}}
          if(L>=0&&Rt-L>3){rc[y]=(L+Rt)/2;rr[y]=(Rt-L)/2+1.5}
          const wk=Math.max(0,Math.min(1,(y/k-.43*ih)/(.12*ih)));wg[y]=1-wk*wk*(3-2*wk)}   // dönüş çenede (.55) sıfır: boyun hiç kıpırdamaz
        {const sm=new Float32Array(wh);for(let y=0;y<wh;y++){let t=0,c=0;for(let j=-6;j<=6;j++){const v=rr[Math.max(0,Math.min(wh-1,y+j))];if(v>0){t+=v;c++}}sm[y]=rr[y]>0&&c?t/c:0}
          for(let y=0;y<wh;y++){rr[y]=sm[y];if(sm[y]>0)rc[y]=hxw}}   // satır ölçüsü 13 satırda yumuşatılır, eksen sabit: dönüşte satır satır zıplama (yatay şerit/dalgalanma) olmaz
        Object.assign(BUST.tiles,{cutI,ww,wh,wc,src,rc,rr,wg,hxw,hyw:hy*k,rxw,ryw:Ry*k,out:new ImageData(ww,wh)});{const T=BUST.tiles;T.src32=new Uint32Array(src.buffer);T.tmp32=new Uint32Array(src.length/4);T.out32=new Uint32Array(T.out.data.buffer)}}}
    // Dış iskelet noktaları: figürün dış hattındaki parlak pikseller (komşularında boşluk olanlar) ve dışa bakan normali; çizimde bu hat boyunca nefes alır, fareden kaçar, tıklama dalgasında dışa fırlar. Bir kez hesaplanır.
    {const L=(x,y)=>x<0||y<0||x>=W||y>=H?0:Math.max(d[(y*W+x)*4],d[(y*W+x)*4+1],d[(y*W+x)*4+2]),E=[];
      // yalnız dış kenar (Hamdi: noktalar dış kenarlarda): satırın en dış parlak sınırlarına 5 px yakın noktalar
      const rL=new Int16Array(H).fill(-1),rR=new Int16Array(H).fill(-1);for(let y=0;y<H;y++)for(let x=0;x<W;x++)if(L(x,y)>110){if(rL[y]<0)rL[y]=x;rR[y]=x}   // satırın dış sınırları
      for(let y=2;y<H-2;y++)for(let x=2;x<W-2;x++){if(L(x,y)<=70||rL[y]<0||(x>rL[y]+5&&x<rR[y]-5))continue;let sx=0,sy=0,n=0;for(let a=-3;a<=3;a++)for(let b=-3;b<=3;b++){if(L(x+a,y+b)<=40){sx+=a;sy+=b;n++}}
        if(n<5)continue;const l=Math.hypot(sx,sy);if(l<1.5)continue;E.push([(x+.5)/W,(y+.5)/H,sx/l,sy/l,Math.random()*6.28,Math.random()])}
      while(E.length>450)E.splice((Math.random()*E.length)|0,1);BUST.edge=E}
    BUST.pts=pts;BUST.loading=false;const q=BUST.q||[];BUST.q=[];q.forEach(f=>f())}catch(e){fail()}};
  im.onerror=fail;im.src='/bust.jpg';
}
// Kaynak noktası: videodaki gibi yumuşak mavi parlama ve beyaz çekirdek; parçacıklar buradan çıkar, kurulum bitince göğüste yavaşça söner.
function bustDot(g,x,y,r,t,al){
  if(al<=0)return;g.save();g.globalCompositeOperation='lighter';g.globalAlpha=al;
  const pu=1+.06*Math.sin(t*5),rr=r*1.7*pu;let gr=g.createRadialGradient(x,y,0,x,y,rr);   // site gibi küçük, beyazımsı-turkuaz parıltı (eski büyük mavi top değil)
  gr.addColorStop(0,'rgba(255,255,255,.9)');gr.addColorStop(.15,'rgba(175,238,255,.7)');gr.addColorStop(.38,'rgba(70,195,235,.3)');gr.addColorStop(.7,'rgba(30,140,200,.08)');gr.addColorStop(1,'rgba(20,110,180,0)');
  g.fillStyle=gr;g.beginPath();g.arc(x,y,rr,0,7);g.fill();g.restore();
}
// Kafa dönüşü (Apex Humanoid gibi): gerçek resim bükülür. Her satır kendi genişliğinde bir silindir sayılır, yatay dönüşte ön yüzde görünen noktanın kaynağı bulunur (kulak, çene, yüz çizgileri ve turuncu çekirdek korunur, dış hat kafa biçiminde kalır).
// Yukarı/aşağı eğilme sütun başına aynı şekilde çalışır. Boyuna doğru dönüş azalır, .62'de sıfırdır: gövde olduğu gibi çizilir, birleşimde dikiş yoktur. Arkaya dönen kenarda seyrek parlak noktalar kalır.
// Bükme küçük bir çalışma kopyasında (tam çözünürlük, en yakın piksel, 32 bit kopya; Hamdi: fare yüze gelince bulanıklaşıyordu) kare başına yapılır; dönüş yokken bu işlev çağrılmaz, resim olduğu gibi çizilir.
function bustWarp(yaw,pitch){
  // Dış hat sabit, iç kayar (Hamdi: dönerken sol yüz dağılıyordu): satırın iki kenarı (u=±1) yerinde kalır, içerik dönüş yönüne kayar: kaynak u' = u - s(1-u^2).
  // Resimde olmayan yan yüz hiç açılmaz; kenar çizgisi ve kulaklar iki yanda da korunur. En çok gerilme 1+2|s| (|s|<=.22; Hamdi: daha güçlüsü kafa biçimini bozuyordu).
  const B=BUST.tiles,w=B.ww,h=B.wh,s=B.src32,t=B.tmp32,d=B.out32;
  for(let y=0;y<h;y++){const R=B.rr[y],row=y*w,sh=Math.max(-.22,Math.min(.22,Math.sin(yaw*B.wg[y])*.6));
    if(R<2||Math.abs(sh)<1e-4){t.set(s.subarray(row,row+w),row);continue}
    const c=B.rc[y],xa=Math.max(0,Math.floor(c-R)),xb=Math.min(w-1,Math.ceil(c+R));
    t.set(s.subarray(row,row+xa),row);t.set(s.subarray(row+xb+1,row+w),row+xb+1);
    for(let x=xa;x<=xb;x++){const u=(x-c)/R;let v=s[row+x];if(u>-1&&u<1){const sx=(c+(u-sh*(1-u*u))*R+.5)|0;v=sx>=0&&sx<w?s[row+sx]:0}t[row+x]=v}}
  d.set(t);if(Math.abs(pitch)<1e-3)return B.out;
  const cx=B.hxw,cy=B.hyw,Rx=B.rxw,Ry=B.ryw;
  for(let x=Math.max(0,Math.ceil(cx-Rx));x<=Math.min(w-1,Math.floor(cx+Rx));x++){const dx=(x-cx)/Rx,Rv=Ry*Math.sqrt(Math.max(0,1-dx*dx));if(Rv<2)continue;
    for(let y=Math.max(0,Math.ceil(cy-Rv));y<=Math.min(h-1,Math.floor(cy+Rv));y++){const v=(y-cy)/Rv;if(v<=-1||v>=1)continue;const sp=Math.max(-.05,Math.min(.14,Math.sin(pitch*B.wg[y])*.85));
      const sy=(cy+(v+sp*(1-v*v))*Rv+.5)|0;d[y*w+x]=sy>=0&&sy<h?t[sy*w+x]:0}}
  return B.out}
function bustHead(g,X,Y,W,H,yaw,alpha,pitch,tw){
  const B=BUST.tiles,img=BUST.img;if(!B||!B.src)return false;const dp=Math.min(2,devicePixelRatio||1),sc=W*dp/B.iw,{H:P,hx,hy}=B,sin=Math.sin,cos=Math.cos;   // ara tuval ekran çözünürlüğünde (dpr): dönerken bulanıklaşmaz
  const hc=BUST.hc||(BUST.hc=document.createElement('canvas')),cw=Math.ceil(W*dp),ch=Math.ceil(H*dp);if(hc.width!==cw||hc.height!==ch){hc.width=cw;hc.height=ch}
  const o=hc.getContext('2d');o.setTransform(1,0,0,1,0,0);o.clearRect(0,0,cw,ch);o.globalCompositeOperation='source-over';
  // gövde eğilmez (eskiden hafif eğiliyordu; eğilmeyen göğüs katmanıyla boyunda çift çizgi yapıyordu, Hamdi)
  o.setTransform(1,0,0,1,0,0);
  // kafa çenenin üstünden (bükülmüş kopya), gövde çenenin altından (asıl resim) TEK seferde çizilir: dönüş .55'te sıfır, üst üste binen şerit yok (eskiden boyunda yarı saydam ışıma iki kez çizilip parlak hat yapıyordu, Hamdi)
  const r0=Math.round(.555*B.ih),kw=B.wh/B.cutI;o.imageSmoothingQuality='high';o.drawImage(img,0,r0,B.iw,B.ih-r0,0,r0*sc,cw,(B.ih-r0)*sc);
  const wc=B.wc.getContext('2d');wc.putImageData(bustWarp(yaw,pitch),0,0);o.drawImage(B.wc,0,0,B.ww,r0*kw,0,0,cw,r0*sc);

  
  g.globalAlpha=alpha;g.drawImage(hc,X,Y,W,H);
  return true;
}
// Çizgi kafa (Apex Humanoid gibi, deneme 12 Ekim 2026): kafa resimden değil, her karede yatay kontur çizgilerinden çizilir; her çözünürlükte keskindir.
// Biçim resimden ölçülen yarı genişlik tablosudur (HEAD_PROF: kafa tepeden çeneye, NECK_PROF: boyun). Her çizgi o yükseklikteki yatay kesittir (elips); dönerken 3B döner, arkaya düşen kısım çizilmez.
// Çizgiler nokta zincirleridir (ince soluk çizgi + parlak noktalar), kenara yaklaştıkça parlar; yüzün ortasında turuncu çekirdek çizgileri boyar. Başın çevresinde süzülen toz noktaları vardır.
// Açılışta parçacıklar figürü kurarken çizgiler boyundan tepeye doğru belirir (fin). Gövde de çizgilerdendir: omuz hattı, ona paralel akış çizgileri ve turuncu damarlar. Model/ağ yok, yalnız yerel çizim.
const HEAD_PROF=[[.072,0],[.075,.018],[.08,.034],[.09,.058],[.10,.077],[.12,.105],[.15,.13],[.18,.145],[.22,.155],[.26,.157],[.285,.155],[.30,.166],[.33,.172],[.37,.172],[.40,.166],[.415,.151],[.43,.148],[.46,.138],[.50,.12],[.53,.099],[.555,.075],[.575,.045],[.588,0]],   // .285 kulak üstü çentik, .30-.40 kulak, .415 kulak altı
  NECK_PROF=[[.50,.112],[.56,.114],[.60,.12],[.62,.132]];
const BODY_PROF=[[.60,.128],[.62,.135],[.64,.149],[.66,.168],[.68,.201],[.70,.240],[.72,.285],[.74,.328],[.76,.363],[.78,.385],[.80,.403],[.84,.426],[.90,.443],[1.0,.456]];   // omuz/gövde dış hattı (resimden ölçüldü; Hamdi: önce "geniş", sonra "bi tık büyült" → ölçülenden ~%9 dar)
function bustProf(P,y){if(y<=P[0][0])return P[0][1];for(let i=1;i<P.length;i++)if(y<=P[i][0]){const a=P[i-1],b=P[i],u=(y-a[0])/(b[0]-a[0]);return a[1]+(b[1]-a[1])*u}return P[P.length-1][1]}
function bustVecPrep(){
  const B=BUST.tiles;if(!B||B.vec)return;const lines=[],N=50;
  for(let i=0;i<N;i++){const v=.074+(.584-.074)*i/(N-1),r=bustProf(HEAD_PROF,v);if(r>.004)lines.push([v*B.ih,r*B.iw*.96,0])}
  for(let i=0;i<9;i++){const v=.515+(.62-.515)*i/8;lines.push([v*B.ih,bustProf(NECK_PROF,v)*B.iw*.96,1])}   // boyun çizgileri (yüzün arkasında kalan kısım çizilmez)
  const dust=[];for(let i=0;i<950;i++){const u=(Math.random()+Math.random()+Math.random())/3,a=Math.PI*(.5+(u-.5)*1.5),rr=1+Math.pow(Math.random(),2.6)*.55;dust.push([a,rr,Math.random()*6.28,Math.random()<.12?1:0])}   // saç bulutu: tepede yoğun, kafaya yakın sık, dışa doğru seyrek; %12'si iri/parlak
  // gövde akış çizgileri: omuz hattına paralel, boyundan dışa ve aşağı inen eğriler (her biri yan başına bir nokta dizisi, resim birimi)
  const flows=[];for(let k=0;k<12;k++){const sc=1-k*.072,dy=k*.016,pts=[];for(let v=.60;v<=1.0;v+=.006){const y=v+dy;if(y>1)break;pts.push([bustProf(BODY_PROF,v)*sc*B.iw,y*B.ih])}if(pts.length>3)flows.push([pts,k])}
  // turuncu damarlar: boyundan göğüs ortasına inen kırık çizgiler (bir kez rastgele üretilir), ve dalları
  const rnd=(()=>{let x=7;return()=>(x=(x*16807)%2147483647)/2147483647})(),vein=(x0,y0,x1,y1,n,amp)=>{const p=[];for(let i=0;i<=n;i++){const u=i/n,j=i&&i<n?(rnd()-.5)*amp:0;p.push([(x0+(x1-x0)*u+j)*B.iw,(y0+(y1-y0)*u+(rnd()-.5)*amp*.4)*B.ih])}return p},veins=[];
  veins.push(vein(-.055,.60,-.012,.86,16,.011),vein(.05,.60,.008,.86,16,.011),vein(-.004,.84,0,.99,8,.007));
  for(const[x0,y0,x1,y1]of[[-.04,.66,-.10,.73],[.035,.67,.10,.72],[-.03,.72,-.06,.80],[.03,.73,.07,.79],[-.02,.62,-.035,.67]])veins.push(vein(x0,y0,x1,y1,6,.008));
  B.vec={lines,dust,flows,veins,y0:.075*B.ih,R0:.17*B.iw}}
function bustVec(g,X,Y,W,H,yaw,pitch,alpha,t,busy,fin){
  const B=BUST.tiles;if(!B)return false;bustVecPrep();const V=B.vec;if(!V)return false;
  const s=W/B.iw,hx=B.hx,hy=B.hy,cy=.40*B.ih,cr=.115*B.ih,sin=Math.sin,cos=Math.cos,PX=x=>X+x*s,PY=y=>Y+y*s,M=40,el=-.07;
  g.save();g.globalAlpha=alpha;g.imageSmoothingQuality='high';
  g.globalCompositeOperation='lighter';
  // gövde: omuz dış hattı (kalın ışıma) ve ona paralel akış çizgileri; açılışta alttan yukarı belirir
  {const fb=Math.min(1,fin*1.5),fl=[new Path2D(),new Path2D(),new Path2D()],fd=[new Path2D(),new Path2D(),new Path2D()];
    for(const[pts,k]of V.flows)for(const sd of[-1,1]){const q=k===0?2:k<4?1:0;let first=true;pts.forEach((p,i)=>{const x=PX(hx+sd*p[0]),y=PY(p[1]+(.0018*B.ih)*Math.sin(i*.7+k+t*.5)*(k?1:0));if(first){fl[q].moveTo(x,y);first=false}else fl[q].lineTo(x,y);if(k&&(i+k)%2===0)fd[q].rect(x-.65,y-.65,1.3,1.3)})}
    const bc=[[30,110,190,.32],[50,160,240,.52],[60,180,255,.95]];
    for(let q=0;q<3;q++){const c=bc[q];g.strokeStyle=`rgb(${c[0]},${c[1]},${c[2]})`;g.fillStyle=g.strokeStyle;g.lineJoin='round';
      if(q===2){for(const[w,al,c]of[[26,.05,'45,150,255'],[14,.1,'45,165,255'],[7,.2,'55,180,255'],[3.5,.38,'80,200,255'],[1.4,.55,'150,230,255']]){g.strokeStyle=`rgb(${c})`;g.lineWidth=w;g.globalAlpha=alpha*fb*al;g.stroke(fl[2])}}
      else{g.lineWidth=2.4;g.globalAlpha=alpha*fb*c[3]*.2;g.stroke(fl[q]);g.lineWidth=.8;g.globalAlpha=alpha*fb*c[3]*.75;g.stroke(fl[q]);g.globalAlpha=alpha*fb*Math.min(1,c[3]*1.3);g.fill(fd[q])}}
    // damarlar: turuncu, hafif nabız gibi parlar (konuşurken daha canlı)
    const vp=new Path2D();for(const v of V.veins){const q=v.map(p=>[PX(hx+p[0]),PY(p[1])]);vp.moveTo(q[0][0],q[0][1]);for(let i=1;i<q.length-1;i++)vp.quadraticCurveTo(q[i][0],q[i][1],(q[i][0]+q[i+1][0])/2,(q[i][1]+q[i+1][1])/2);vp.lineTo(q[q.length-1][0],q[q.length-1][1])}   // yumuşak eğri (kırık şimşek değil)
    const pu=.8+.2*Math.sin(t*(busy?3.2:1.4));g.strokeStyle='rgb(255,140,30)';g.lineCap='round';for(const[w,al]of[[9,.07],[4,.2],[1.6,.5],[.9,.9]]){g.lineWidth=w;g.globalAlpha=alpha*fb*al*pu;g.stroke(vp)}}
  const cols=[[35,120,200,.45],[55,170,245,.7],[100,215,255,1],[190,70,10,.55],[245,120,25,.85],[255,175,60,1]],ln=cols.map(()=>new Path2D()),dt=cols.map(()=>new Path2D()),rimL=[],rimR=[],nL=[],nR=[],N=V.lines.length;   // renkler Apex Humanoid'den: doygun mavi çizgiler, kızıl→turuncu→sarı çekirdek
  for(let i=0;i<N;i++){const[y,r,neck]=V.lines[i],rv=Math.max(0,Math.min(1,fin*1.7-(1-i/N)*.7));if(rv<=0)continue;   // açılış: boyundan tepeye doğru belirir
    const wk=Math.max(0,Math.min(1,(y-.5*B.ih)/(.12*B.ih))),wg=1-wk*wk*(3-2*wk),a=yaw*wg,p=pitch*wg,ca=cos(a),sa=sin(a),cp=cos(p),sp=sin(p),hr=neck?bustProf(HEAD_PROF,y/B.ih)*B.iw:0;
    let prev=null,lo=null,hi=null;
    for(let j=0;j<=M;j++){const th=-Math.PI/2+Math.PI*j/M,ux=sin(th),uz=cos(th),x0=r*ux;
      if(neck&&Math.abs(x0)<hr*.97){prev=null;continue}   // boyunun yüz arkasında kalan kısmı
      const ov=neck?0:Math.exp(-(((y-cy)/cr)**2)-((ux/.55)**2)),lf=.55+.9*((Math.sin(i*91.7)*43758.5)%1+1)%1,wv=B.ih*((.0024+.0045*ov)*lf*sin(th*(6+i%3)+i*.9+t*.7)+.0012*sin(th*13+i*2.3-t*.45)),z0=r*uz*.95,x1=x0*ca+z0*sa,z1=-x0*sa+z0*ca,yy=(y+wv-hy)*cp-z1*sp+hy+el*z1,z2=(y-hy)*sp+z1*cp;
      const f=(-ux*sa+uz*ca)*cp;if(f<-.02){prev=null;continue}const sx=PX(hx+x1),sy=PY(yy);   // yön: yüzey normali (konum değil); eğilmede çene çizgileri tümden 'kenar' sayılmaz
      if((!neck||x0<0)&&(!lo||sx<lo[0]))lo=[sx,sy];if((!neck||x0>0)&&(!hi||sx>hi[0]))hi=[sx,sy];   // boyunda iki yan ayrı izlenir (tek yanı görünen çizgi karşı kenara atlamaz)
      const q=ov>.45?5:ov>.2?4:ov>.08?3:f<.3?2:f<.7?1:0;
      if(prev){ln[q].moveTo(prev[0],prev[1]);ln[q].lineTo(sx,sy)}prev=[sx,sy];
      if((j+i)%2===0){const d=q===2||q===5?1.7:1.3;dt[q].rect(sx-d/2,sy-d/2,d,d)}}
    if(neck){if(lo)nL.push(lo);if(hi)nR.push(hi)}else if(lo){rimL.push(lo);rimR.push(hi)}}
  for(let q=0;q<cols.length;q++){const c=cols[q],st=`rgb(${c[0]},${c[1]},${c[2]})`;g.strokeStyle=st;g.lineWidth=2.6;g.globalAlpha=alpha*c[3]*.16;g.stroke(ln[q]);g.lineWidth=.8;g.globalAlpha=alpha*c[3]*.7;g.stroke(ln[q]);g.fillStyle=st;g.globalAlpha=alpha*Math.min(1,c[3]*1.2);g.fill(dt[q])}
  // çekirdek: yüzün ortasında turuncu parıltı (dönerken yüzle birlikte kayar)
  {const x=PX(hx+sin(yaw)*.16*B.iw),y=PY(cy-sin(pitch)*.1*B.ih),rad=.135*B.iw*s,gr=g.createRadialGradient(x,y,0,x,y,rad);
    gr.addColorStop(0,`rgba(255,140,30,${busy?.7:.55})`);gr.addColorStop(.45,'rgba(225,90,15,.24)');gr.addColorStop(1,'rgba(160,50,5,0)');g.globalAlpha=alpha*Math.min(1,fin*1.5);g.fillStyle=gr;g.beginPath();g.ellipse(x,y,rad*.85,rad*1.1,0,0,7);g.fill()}
  // dış hat: kafa (iki kenar tepede ve çenede birleşir) ve boyun kenarları; parlak camgöbeği ve yumuşak ışıma
  const rims=[];if(rimL.length>2){const p=new Path2D();p.moveTo(rimL[rimL.length-1][0],rimL[rimL.length-1][1]);for(let i=rimL.length-2;i>=0;i--)p.lineTo(rimL[i][0],rimL[i][1]);for(const q of rimR)p.lineTo(q[0],q[1]);p.closePath();rims.push(p)}
  for(const side of [nL,nR])if(side.length>1){const p=new Path2D();p.moveTo(side[0][0],side[0][1]);for(const q of side)p.lineTo(q[0],q[1]);rims.push(p)}
  g.lineJoin='round';g.lineCap='round';for(const[w,al,c]of[[26,.05,'45,150,255'],[14,.1,'45,165,255'],[7,.2,'55,180,255'],[3.5,.38,'80,200,255'],[1.4,.55,'150,230,255']]){g.strokeStyle=`rgb(${c})`;g.lineWidth=w;g.globalAlpha=alpha*al*Math.min(1,fin*1.4);for(const p of rims)g.stroke(p)}   // site gibi mavi, geniş ve yumuşak ışıma   // yumuşak, kalın ışıma; ince parlak çekirdek
  {const sp=new Path2D(),sd=(i,k)=>{const v=Math.sin(i*127.1+k*311.7)*43758.5;return v-Math.floor(v)};   // kenardan dışa dağılan parlak noktalar (site gibi tozlu kenar)
    [[rimL,-1],[rimR,1],[nL,-1],[nR,1]].forEach(([A,dir],m)=>A.forEach((q,i)=>{for(let k=0;k<4;k++){const r=sd(i+m*97,k),o=r*r*14,jy=(sd(i,k+5)-.5)*6+Math.sin(t*.9+i+k)*1.2;sp.rect(q[0]+dir*o-.7,q[1]+jy-.7,1.4,1.4)}}));
    g.fillStyle='rgb(150,232,255)';g.globalAlpha=alpha*.6*Math.min(1,fin*1.4);g.fill(sp)}
  // toz noktaları: başın üstünde ve çevresinde yavaşça süzülür
  {const top=V.y0,R0=V.R0,dp=new Path2D();
    const db=new Path2D();for(const d of V.dust){const an=Math.PI+d[0],rr=R0*d[1]*(1+.04*sin(t*.8+d[2])),x=PX(hx+cos(an)*rr*1.02+sin(yaw)*R0*.3*d[1]),y=PY(top+R0*1.42+sin(an)*rr*1.42+sin(t*.6+d[2])*.004*B.ih);if(d[3])db.rect(x-1,y-1,2,2);else dp.rect(x-.55,y-.55,1.1,1.1)}
    g.fillStyle='rgb(110,205,255)';g.globalAlpha=alpha*.5*Math.min(1,fin*1.3);g.fill(dp);g.fillStyle='rgb(170,235,255)';g.globalAlpha=alpha*.8*Math.min(1,fin*1.3);g.fill(db)}
  g.restore();return true}
let HOME_HOLOGRAM=null,HOLOGRAM_TONE=store.get('hologram-tone','blue'),HOLOGRAM_BACKGROUND=store.get('hologram-background','mountains');
function hologramTone(){return ['blue','turquoise','yellow'].includes(HOLOGRAM_TONE)?HOLOGRAM_TONE:'blue'}
function hologramBackground(){return ['mountains','lava'].includes(HOLOGRAM_BACKGROUND)?HOLOGRAM_BACKGROUND:'mountains'}
function mountBust(stage){
  if(!stage)return;if(HOME_HOLOGRAM)HOME_HOLOGRAM.destroy();
  HOME_HOLOGRAM=window.JarvisHologram.mount(stage,{
    getState:()=>((S.snap||{}).flags||{}).sleep?'sleep':S.orb,
    getTone:hologramTone,getBackground:hologramBackground,
    getElapsed:()=>BUST.holoElapsed||0,saveElapsed:t=>{BUST.holoElapsed=t},
    isStill:()=>S.ui?.nx_bust===false||matchMedia('(prefers-reduced-motion: reduce)').matches,
    isCalm:UI_CALM,onMic:()=>ACT.mic(),onRestore:mountBust
  });
}
ACT.hologramtone=el=>{const name=el.dataset.v;if(!['blue','turquoise','yellow'].includes(name))return;HOLOGRAM_TONE=name;store.set('hologram-tone',name);if(settingsOpen())drawSettings();updateHologramChoices()};
ACT.hologrambg=el=>{const name=el.dataset.v;if(!['mountains','lava'].includes(name))return;HOLOGRAM_BACKGROUND=name;store.set('hologram-background',name);if(settingsOpen())drawSettings();updateHologramChoices()};
function updateHologramChoices(){document.querySelectorAll('[data-act="hologramtone"]').forEach(b=>b.classList.toggle('on',b.dataset.v===hologramTone()));document.querySelectorAll('[data-act="hologrambg"]').forEach(b=>b.classList.toggle('on',b.dataset.v===hologramBackground()))}
function hologramChoices(){return `<div class="seg">${[['blue','Mavi'],['turquoise','Turkuaz'],['yellow','Sarı']].map(([v,t])=>`<button class="${hologramTone()===v?'on':''}" data-act="hologramtone" data-v="${v}">${t}</button>`).join('')}</div><div class="seg">${[['mountains','Mavi dağlar'],['lava','Lav dağları']].map(([v,t])=>`<button class="${hologramBackground()===v?'on':''}" data-act="hologrambg" data-v="${v}">${t}</button>`).join('')}</div>`}
// ---- İkinci ana ekran: "Menü". RubenM1990/APEX-UI (MIT) yapısının birebir vanilla JS portu; "Apex" adı/markası alınmadı.
// Katmanlar (APEX ApexWorld sırası): arka plan → camgöbeği ışık → akıl yürütme ağı (SVG 680x480, aynı koordinatlar) → altın halka + parçacık çekirdeği
// → dokunma diski → durum çubuğu → sol üst OVERVIEW lambası. Düğümler Jarvis menü öğeleridir; yalnız yerel çizim (model/ağ yok).
const MN_AX=340,MN_AY=240,MN_COL={consultant:'#00e5ff',doer:'#f5a623',tool:'#7f9bb3'};
const MENU_ROSTER=[   // id, etiket, tür, x, y, canlı, bend, r  (APEX ROSTER ile aynı koordinatlar ve boyutlar)
  ['chat','Sohbet ve dosyalar','consultant',250,212,true,18,9],['hafiza','Hafıza','consultant',452,250,true,-18,8],['ai','Yapay zekâ','consultant',296,118,true,-22,6.5],
  ['study','Çalışma','consultant',182,150,true,24,6.5],['ses','Ses ve konuşma','consultant',584,208,true,-26,6.5],
  ['takvim','Takvim','doer',158,266,true,22,6.5],['telefon','Telefon','doer',195,298,true,22,6.5],['mesaj','Mesajlar','doer',232,330,true,20,6.5],
  ['ekran','Ekran ve kamera','doer',426,350,true,-18,6.5],['hesap','Hesap ve gizlilik','doer',502,312,true,-22,6.5],
  ['gorev','Görevler','doer',118,356,true,26,6.5],['rapor','Gelişim raporu','tool',256,388,false,20,5.5],['github','GitHub ve güncelleme','tool',414,392,true,-18,5.5],
  ['sistem','Sistem','tool',560,356,true,-24,5.5],['veri','Veri klasörü','tool',608,286,false,-26,5.5],['tarama','Sistem taraması','tool',582,132,false,24,5.5]];
const MENU_ACT={chat:['go','chat'],study:['go','study'],hafiza:['set','hesap'],ai:['set','ai'],ses:['set','ses'],takvim:['set','takvim'],telefon:['set','iletisim'],mesaj:['set','iletisim'],
  ekran:['set','ekran'],hesap:['set','hesap'],gorev:['set','takvim'],rapor:['set','sistem'],github:['set','github'],sistem:['set','sistem'],veri:['set','sistem'],tarama:['set','sistem']};
const MENU_ICON={hafiza:'db',ai:'spark',ses:'vol',takvim:'calendar',gorev:'target',telefon:'phone',mesaj:'mail',chat:'msg',study:'book',ekran:'monitor',hesap:'shield',github:'branch',sistem:'gear',veri:'folder',rapor:'file',tarama:'eye'};
const MENU_VIEW={hafiza:/hedefler|ogrenme durumu|onay bekleyen|bildiklerim|ogrettigin/,hesap:/kullanicilar|gizlilik modu|^koruma$/,
  ekran:/ekran paylasimi|^kamera$|ekrani incele|ekran goruntusu|gorsel analiz|pc islemleri|son gorseller/,takvim:/^takvim$|secili gun|yaklasan etkinlik/,gorev:/yapilacaklar|notlar/,
  telefon:/^(?!kisiler|mesaj gonder)/,mesaj:/^(kisiler|mesaj gonder)/,sistem:/genel ayarlar|hakkinda/,veri:/yerel kayit|veri klasor/,rapor:/gelisim rapor/,tarama:/sistem tarama/};
const MENU_INFO={   // rol, ne yapar, durum (online/standby/integration)
  chat:['Konuşma ve dosyalar',['Yazarak ya da sesle her şeyi sorarsın','Dosya ekleyip özetletir, tabloya döktürürsün','Sohbet geçmişin kullanıcıya özel saklanır'],'online'],
  hafiza:['Uzun süreli hafıza',['Senin hakkında öğrendiklerini tutar','Öğrettiğin kurallara her konuşmada uyar','Önce onayına sunar, sonra kaydeder'],'online'],
  ai:['Model ve bağlantılar',['Gemini, Groq ve Ollama arasında seçim','Her kullanıcı kendi anahtarını kullanır','Google ve GitHub bağlantıları'],'online'],
  study:['Çalışma alanı',['Konu çalışma, soru çözme, kaynak ekleme','Matematik çalışma masası','Derse özel notlar'],'online'],
  ses:['Mikrofon, uyanma ve konuşma',['Mikrofon, sesli yanıt, konuşma sesi','Yerel ses tanıma ve düzeltmeler','Uyanma sesi ve hassasiyet'],'online'],
  takvim:['Aylık görünüm ve etkinlikler',['Aylık görünüm ve günün etkinlikleri','Yaklaşan etkinlikler'],'online'],
  telefon:['Telefondan erişim',['QR ile telefondan bağlanma','Bildirimler'],'online'],
  mesaj:['WhatsApp ile mesaj ve kişiler',['WhatsApp kişileri ve mesaj gönderme','Göndermeden önce onay ister'],'online'],
  dosya:['Yükleme, son dosyalar ve klasörler',['Son yüklediklerini kartlarla gösterir','Özetle, çevir, tabloya dönüştür'],'online'],
  ekran:['Paylaşım, görüntü alma ve PC işlemleri',['Ekranı ya da kamerayı yalnız sen açınca görür','Önizleme yerelde kalır'],'online'],
  hesap:['Kullanıcılar ve gizlilik',['Kullanıcılar ve gizlilik modu','Hassas bilgiyi maskeler, onay ister'],'online'],
  gorev:['Yapılacaklar ve notlar',['Yapılacaklar listesi','Notlar ve görseller'],'online'],
  rapor:['Neyi yanlış duydum, ne yapamadım',['Neyi yanlış duydum, neyi yapamadım'],'integration'],
  github:['Anahtar, yükle/al ve güncelleme',['Anahtar, durum, yükle/al/yedekle'],'integration'],
  sistem:['Genel ayarlar ve hakkında',['Genel ayarlar, başlangıç, bildirimler','Sürüm ve güncelleme'],'integration'],
  veri:['Yerel kayıtların yeri',['Ayarlar, hafıza ve kayıtlar yerelde durur'],'integration'],
  tarama:['Parçaları dener, sorunları gösterir',['Her parçayı dener, sorunları gösterir'],'integration']};
const MENU_ASKS={chat:['Bugün ne var?','Dosyalarımı göster','Bana bir fikir öner'],study:['Konu çalışmak istiyorum','Bir soru çöz'],hafiza:['Beni ne kadar tanıyorsun?'],takvim:['Takvimim','Yarın 15\'te toplantı ekle']};
const MN_STATUS={online:['#34d399','Çevrimiçi · Jarvis işi buraya yönlendirir'],standby:['#c9a84c','Beklemede · yalnız sen isteyince'],integration:['#7f9bb3','Entegrasyon · çekirdeğe bağlı']};
const MN_LEVEL={standby:.32,listening:.6,processing:.85,reasoning:.95,speaking:.78};
ACT.bustskip=()=>{if(BUST.asm!=null&&BUST.asm<11000+2500)BUST.asm=11000+9000};
ACT.bustreplay=()=>{window.JarvisBackdropController?.replay();BUST.holoElapsed=0;if(HOME_HOLOGRAM)HOME_HOLOGRAM.replay()};
function menuGo(id){const a=MENU_ACT[id];if(!a)return;if(a[0]==='go')return go(a[1]);S.sset=a[1];go('settings')}
ACT.mnopen=el=>menuCard(MENU_ROSTER.find(r=>r[0]===el.dataset.k));
// Yan sayfa düzeni: Ayarlar bölümü olan düğmeye basınca orb ve ağ sola kayar, içerik sağ tarafta tam boy açılır; düğümden panele bağlantı çizgisi çizilir.
// Sohbet, Çalışma ve Dosyalar: eski tam sayfalar kalktı; içerikleri menü sahnesinin yan sayfasında çizilir (S.page aynı kalır, eski koşullar çalışır).
const PAGE_NODE={chat:'chat',study:'study',files:'chat'};
function renderPageDock(pg,pageId,nodeId){
  if(HOME_HOLOGRAM){HOME_HOLOGRAM.destroy();HOME_HOLOGRAM=null}
  if(!pg.classList.contains('p-menu')||!pg.querySelector('.mnscene')){pg.className='page p-menu';pg.innerHTML='';PAGES.menu(pg)}
  const sc=pg.querySelector('.mnscene'),c=pg.querySelector('#mn-card'),r=MENU_ROSTER.find(x=>x[0]===nodeId);if(!sc||!c||!r)return;
  c.innerHTML=`<div class="mn-ov mn-win mn-pagedock" role="dialog" aria-label="${esc(r[1])}" style="--c:${MN_COL[r[2]]}"><div class="mn-ovh"><span class="mn-ovi">${ic(MENU_ICON[nodeId]||'spark')}</span><div><b>${esc(r[1]).toUpperCase()}</b><small>${esc((MENU_INFO[nodeId]||[''])[0])}</small></div><button data-act="mnclose" aria-label="Kapat">×</button></div><div class="mn-wb pagebox page p-${pageId}" id="pagebox"></div><div class="mn-wf mn-askhost" id="dockhost"></div></div>`;
  sc.classList.add('dock-wide');window.__mnNode=nodeId;menuDock(c,r);PAGES[pageId](c.querySelector('#pagebox'));
  if(nodeId==='chat'&&sc._web&&sc._web.showSubs){const sel=pageId==='files'?1:0;   // tek orb, iki alt orb: Sohbet ve Dosyalar
    sc._web.showSubs([{title:'Sohbet'},{title:'Dosyalar'}],i=>go(i?'files':'chat'),sel);window.__mnSub=sel;window.__mnSubOn=true;menuLink(sc)}}
function menuOpenPending(){if(S.mnOpen){const id=S.mnOpen;S.mnOpen=null;setTimeout(()=>{const r=MENU_ROSTER.find(x=>x[0]===id);if(r&&$('#mn-card'))menuCard(r)},400)}}
function menuReopen(pg){const c=pg.querySelector('#mn-card');if(c)c.innerHTML='';menuUndock();menuOpenPending()}
function menuUndock(){menuSubsStop();const sc=$('.mnscene');if(sc){sc.classList.remove('docked','dock-wide');sc.style.removeProperty('--mnk');const l=sc.querySelector('#mn-link');if(l)l.remove();if(sc._web&&sc._web.focus)sc._web.focus([])}window.__mnLink=null}
// Boş yere basınca yan sayfa kapanır ve ana menü geri gelir (düğüm, orb, panel, düğme ve yazı alanları hariç).
function menuOutsideClick(sc,e){if(!sc||!sc.classList.contains('docked'))return false;const t=e&&e.target;if(t&&t.closest&&t.closest('.mn-dock, circle, .mn-tap, .mn-hud, button, a, input, select, textarea, [data-act], [data-go], [data-say]'))return false;ACT.mnclose();return true}
// Orb, ağ ölçeğiyle birlikte küçülür: yan sayfa açıkken ağ solda kalan alana sığar, orb ağdan büyük kalmaz.
function menuFit(sc){const w=sc.clientWidth,h=sc.clientHeight,pw=(sc.querySelector('.mn-dock')||{}).offsetWidth||0;if(!w||!h)return;const full=Math.min(w/680,h/480),dock=Math.min(Math.max(w-pw-44,120)/680,h/480);sc.style.setProperty('--mnk',Math.min(1,dock/full).toFixed(3))}
// Açılan düğümün dalı parlar.
function menuSameSection(id){return [id]}   // her ana başlığın kendi içeriği vardır (MENU_VIEW); yalnız seçilen düğümün dalı parlar
// Alt başlıklar: açılan sayfanın bölümleri (kutular/kartlar) orbun çevresinde küçük orb olur; birine basınca sağda yalnız o bölüm görünür.
// Yapay zekâ sayfasında alt başlıklar sağlayıcılardır ve orbların rengi bağlantı durumunu gösterir. İçerik sonradan yüklenirse (telefon, mesajlar) yeniden taranır.
let mnObs=null,mnSig='';
function menuSubsStop(){if(mnObs){mnObs.disconnect();mnObs=null}mnSig='';window.__mnSub=null;window.__mnSubOn=false;const sc=$('.mnscene');if(sc&&sc._web&&sc._web.hideSubs)sc._web.hideSubs()}
function menuSubsWatch(sc){menuSubsStop();const pane=sc.querySelector('#spane');if(!pane||typeof MutationObserver==='undefined')return;let t=0;
  mnObs=new MutationObserver(()=>{clearTimeout(t);t=setTimeout(()=>menuSubsScan(sc),120)});mnObs.observe(pane,{childList:true,subtree:true});setTimeout(()=>menuSubsScan(sc),150)}
function menuBlocks(pane){const SEL='.sbox, section.card, [data-tv][data-lazy]';let g=-1;
  return [...pane.querySelectorAll(SEL)].filter(b=>!(b.parentElement&&b.parentElement.closest&&b.parentElement.closest(SEL))&&!b.classList.contains('aihub')).map(b=>{
    const h=b.querySelector('.sh b, .ch .ct, h2, .ct, h3, .ch b');let title=(b.dataset&&b.dataset.mtitle)||(h?h.textContent:'');
    if(!title&&b.dataset&&b.dataset.lazy&&b.previousElementSibling&&b.previousElementSibling.classList.contains('sback'))title=b.previousElementSibling.textContent;
    title=String(title||'').replace(/\s+/g,' ').trim();if(title)g++;return {b,title,group:Math.max(g,0)}})}
// Başlıksız bloklar önceki başlıklı bloğa bağlıdır (ör. seçilen notun ayrıntı kartı); MENU_VIEW düğümün hangi başlıkları göstereceğini belirler.
function menuGroups(pane){const groups=[];menuBlocks(pane).forEach(x=>{if(x.title||!groups.length)groups.push({title:x.title,items:[x]});else groups[groups.length-1].items.push(x)});return groups}
function menuSubsScan(sc){const web=sc&&sc._web,pane=sc&&sc.querySelector('#spane');if(!web||!web.showSubs||!pane||!sc.classList.contains('docked'))return;
  pane.querySelectorAll('.sback, .connection-helpbar').forEach(e=>e.classList.add('sub-hide'));
  if(S.sset==='ai'||S.sset==='baglanti'){   // sağlayıcılar: renkli orblar
    const st=aiStates(S.snap||{}),raw=String(((S.snap||{}).llm||{}).provider||'gemini').toLowerCase(),active=raw==='smart_router'?'auto':raw;
    let sel=AI_CARDS.findIndex(x=>x[0]===(SX.aiSel||active));if(sel<0)sel=0;
    if(mnSig!=='ai'||!web.hasSubs()){mnSig='ai';web.showSubs(AI_CARDS.map(([id,t])=>({title:t,state:st[id][0]})),i=>{window.__mnSub=i;ACT.aipick({dataset:{k:AI_CARDS[i][0]}})},sel)}
    else web.selectSub(sel);
    window.__mnSub=sel;window.__mnSubOn=true;menuLink(sc);return}
  const view=MENU_VIEW[window.__mnNode],groups=menuGroups(pane),shown=groups.filter(g=>g.title&&(!view||view.test(fold(g.title))));
  const apply=()=>{const gs=menuGroups(pane),keep=gs.filter(g=>g.title&&(!view||view.test(fold(g.title))));
    gs.forEach(g=>{const show=!keep.length||(keep.length===1?g.title===keep[0].title:!!keep[window.__mnSub]&&g.title===keep[window.__mnSub].title);g.items.forEach(x=>x.b.classList.toggle('sub-hide',!show))})};
  if(shown.length<2){if(web.hasSubs())web.hideSubs();mnSig='';window.__mnSubOn=false;window.__mnSub=null;apply();menuLink(sc);return}
  const sig='g|'+S.sset+'|'+window.__mnNode+'|'+shown.map(g=>g.title).join('|');
  if(sig!==mnSig||!web.hasSubs()){mnSig=sig;window.__mnSub=0;web.showSubs(shown.map(g=>({title:g.title})),i=>{window.__mnSub=i;apply();menuLink(sc)},0)}
  window.__mnSubOn=true;apply();menuLink(sc)}
function menuDock(c,r){const sc=c.closest('.mnscene');if(!sc)return;sc.classList.add('docked');const p=c.querySelector('.mn-ov');if(p)p.classList.add('mn-dock');window.__mnLink=r[0];
  menuFit(sc);if(sc._web&&sc._web.focus)sc._web.focus(menuSameSection(r[0]),r[0]);menuSubsWatch(sc);drawMiniPreview();setTimeout(()=>{menuFit(sc);menuLink(sc)},520)}
function menuLink(sc){sc=sc||$('.mnscene');if(!sc)return;const svg=sc.querySelector('#mn-svg'),old=svg&&svg.querySelector('#mn-link');if(old)old.remove();
  const id=window.__mnLink,web=sc._web,panel=sc.querySelector('.mn-dock');if(!svg||!web||!id||!panel||!sc.classList.contains('docked'))return;
  const p=window.__mnSubOn&&web.subPos?web.subPos(window.__mnSub):web.pos(id),m=svg.getScreenCTM();if(!p||!m)return;const b=panel.getBoundingClientRect(),pt=svg.createSVGPoint();pt.x=b.left;pt.y=b.top+Math.min(b.height*.45,300);const q=pt.matrixTransform(m.inverse());
  const NS=svg.namespaceURI,g=document.createElementNS(NS,'g');g.id='mn-link';g.setAttribute('filter','url(#rw-glow)');
  const path=document.createElementNS(NS,'path');path.setAttribute('d',`M${p.x} ${p.y} C${p.x+(q.x-p.x)*.45} ${p.y} ${p.x+(q.x-p.x)*.55} ${q.y} ${q.x} ${q.y}`);path.setAttribute('fill','none');path.setAttribute('stroke','#4edcff');path.setAttribute('stroke-width','1.7');path.setAttribute('opacity','.9');
  const dot=document.createElementNS(NS,'circle');dot.setAttribute('cx',q.x);dot.setAttribute('cy',q.y);dot.setAttribute('r','3.6');dot.setAttribute('fill','#4edcff');g.append(path,dot);svg.append(g)}
window.addEventListener('resize',()=>{const sc=$('.mnscene.docked');if(sc){menuFit(sc);menuLink(sc)}});
ACT.mnclose=()=>{if(PAGE_NODE[S.page]){go('menu');return}const c=$('#mn-card');if(c)c.innerHTML='';menuUndock();drawMiniPreview();const o=window.__mnOpener;window.__mnOpener=null;if(o&&document.contains(o))o.focus()};
ACT.mngo=el=>{ACT.mnclose();menuGo(el.dataset.k)};
ACT.mnlamp=()=>{const s=$('.mnscene');if(s)s.classList.toggle('lamp-open')};
function menuWin(r){const c=$('#mn-card');if(!c||!r)return;const a=MENU_ACT[r[0]],sec=sectionOf(a[1])||SECS[0],col=MN_COL[r[2]];S.sset=a[1];S.sq='';window.__mnNode=r[0];
  window.__mnOpener=document.activeElement&&document.activeElement!==document.body?document.activeElement:window.__mnOpener;
  c.innerHTML=`<div class="mn-ov mn-win" id="mn-win" role="dialog" aria-label="${esc(r[1])}" style="--c:${col}"><div class="mn-ovh"><span class="mn-ovi">${ic(MENU_ICON[r[0]]||sec.i)}</span><div><b>${esc(r[1]).toUpperCase()}</b><small>${esc((MENU_INFO[r[0]]||[''])[0])}</small></div><button data-act="mnclose" aria-label="Kapat">×</button></div><div class="mn-wb" id="spane"><div class="empty">Yükleniyor…</div></div><div class="mn-ovs mn-wf"><span style="background:${MN_STATUS[(MENU_INFO[r[0]]||[0,0,'online'])[2]][0]};box-shadow:0 0 8px ${MN_STATUS[(MENU_INFO[r[0]]||[0,0,'online'])[2]][0]}"></span>${esc(MN_STATUS[(MENU_INFO[r[0]]||[0,0,'online'])[2]][1])}</div></div>`;
  menuDock(c,r);   // yan sayfa: orb sola kayar, içerik sağda; başlıktan sürükleme yok
  (S.ui?Promise.resolve():loadUi()).then(drawSettings);const x=c.querySelector('.mn-ovh button');if(x)x.focus()}
function mnDrag(card,hd,c){   // başlıktan sürükle (APEX AgentOverview gibi)
  hd.addEventListener('mousedown',e=>{if(e.target.closest('button'))return;const b=card.getBoundingClientRect(),pr=c.getBoundingClientRect(),dx=e.clientX-b.left,dy=e.clientY-b.top;card.style.transform='none';card.style.left=(b.left-pr.left)+'px';card.style.top=(b.top-pr.top)+'px';
    const mv=ev=>{card.style.left=Math.max(0,Math.min(pr.width-120,ev.clientX-pr.left-dx))+'px';card.style.top=Math.max(0,Math.min(pr.height-60,ev.clientY-pr.top-dy))+'px'};
    const up=()=>{document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up)};document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);e.preventDefault()})}
function menuCard(r){const c=$('#mn-card');if(!c||!r)return;const a=MENU_ACT[r[0]];if(a&&a[0]==='set'){if(PAGE_NODE[S.page]){S.page='menu';store.set('page','menu')}return menuWin(r)}if(a&&a[0]==='go')return go(a[1])}   // Sohbet, Çalışma, Dosyalar: doğrudan kendi yan sayfası
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('#mn-card')&&$('#mn-card').innerHTML)ACT.mnclose()});
function bindStatus(scene){   // ana ekran: BEKLİYOR/DİNLİYOR/DÜŞÜNÜYOR/KONUŞUYOR yazısı ve üç nokta
  const lab=scene.querySelector('.hs-status .lb'),dots=scene.querySelectorAll('.hs-status i'),LB={idle:'BEKLİYOR',listening:'DİNLİYOR',thinking:'DÜŞÜNÜYOR',speaking:'KONUŞUYOR',sleep:'UYKUDA'};
  const tick=now=>{if(!scene.isConnected)return;const t=now/1000,m=(S.snap||{}).flags&&S.snap.flags.sleep?'sleep':S.orb||'idle';
    if(lab){lab.textContent=LB[m]||LB.idle;dots.forEach((d,i)=>d.classList.toggle('on',m==='idle'?i===1:((t*3|0)%3)===i))}
    requestAnimationFrame(tick)};requestAnimationFrame(tick);
}
// ---- ReasoningWeb (APEX'ten birebir; yalnız koyu palet, çekirdeksiz "full" kipi)
function menuWeb(svg,getState,onSelect){
  const NS='http://www.w3.org/2000/svg',AX=MN_AX,AY=MN_AY,P={ring:'#1b5f78',pcb:'#1c5f7a',pcbDot:'#37d6ef',fieldMesh:'#143f4f',fieldDot:'#2bd0e6',mesh:'#1a5468',spoke:'#22566b',spokeHot:'#33eaff',link:'#5eead4',label:'#dfeaf3',labelMinor:'#93a8ba',labelDorm:'#546a7d',mote:'#5fe0f2',moteHot:'#bff6ff'};
  const mk=(t,a={})=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e};
  const defs=mk('defs');defs.innerHTML='<filter id="rw-glow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter><filter id="rw-soft" x="-150%" y="-150%" width="400%" height="400%"><feGaussianBlur stdDeviation="9"/></filter><filter id="rw-line" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="1.9" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>';
  const ringsG=mk('g'),pcbG=mk('g'),fillG=mk('g'),meshG=mk('g'),spokesG=mk('g'),pulsesG=mk('g'),nodesG=mk('g');
  svg.append(defs,pcbG,ringsG,fillG,meshG,spokesG,pulsesG,nodesG);[pcbG,meshG,spokesG].forEach(g=>g.setAttribute('filter','url(#rw-line)'));
  let seed=11;const rnd=()=>(seed=(seed*9301+49297)%233280)/233280;
  const pathD=(bx,by,bend)=>{const mx=(AX+bx)/2,my=(AY+by)/2,dx=bx-AX,dy=by-AY,l=Math.hypot(dx,dy)||1;return `M${AX} ${AY} Q${mx+(-dy/l)*bend} ${my+(dx/l)*bend} ${bx} ${by}`};
  const live=[];let allNodes=[];
  const spawn=(spoke,faint)=>{const el=mk('circle',{r:faint?.9:1.4,fill:faint?P.mote:P.moteHot,filter:'url(#rw-glow)'});pulsesG.append(el);live.push({el,born:performance.now(),spoke,L:spoke.getTotalLength(),faint})};
  [72,128,186].forEach(r=>ringsG.append(mk('circle',{cx:AX,cy:AY,r,fill:'none',stroke:P.ring,opacity:.32,'stroke-width':1,'stroke-dasharray':'1 7'})));
  [-1,1].forEach(side=>{for(let i=0;i<6;i++){
    const y=AY+(i-2.5)*52+(rnd()*16-8),startX=AX+side*(126+rnd()*34),midX=side<0?(40+rnd()*56):(584+rnd()*56),y2=y+(rnd()*30-15),jogX=side<0?(10+rnd()*18):(652+rnd()*18);
    pcbG.append(mk('path',{d:`M${startX} ${y} H${midX} V${y2} H${jogX}`,fill:'none',stroke:P.pcb,opacity:.5,'stroke-width':1}));
    pcbG.append(mk('circle',{cx:jogX,cy:y2,r:2.4,fill:P.pcbDot,opacity:.85}));pcbG.append(mk('circle',{cx:startX,cy:y,r:1.3,fill:P.fieldDot,opacity:.45}))}});
  const fill=[];for(let i=0;i<15;i++){const x=36+rnd()*608,y=34+rnd()*412;if(Math.hypot(x-AX,y-AY)>175)fill.push({x,y})}
  fill.forEach(f=>{let near=null,nd=1e9;fill.forEach(g=>{if(g!==f){const d=Math.hypot(g.x-f.x,g.y-f.y);if(d<nd){nd=d;near=g}}});
    if(near&&nd<110)meshG.append(mk('line',{x1:f.x,y1:f.y,x2:near.x,y2:near.y,stroke:P.fieldMesh,'stroke-width':1,opacity:.45}));
    const c=mk('circle',{cx:f.x,cy:f.y,r:1.1,fill:P.fieldDot});c.style.animation=`rwTwinkle 4s ease-in-out ${(rnd()*4).toFixed(2)}s infinite`;fillG.append(c)});
  const map={},pts=[];MENU_ROSTER.forEach(r=>{const n={id:r[0],label:r[1],layer:r[2],x:r[3],y:r[4],live:r[5],bend:r[6],r:r[7],col:MN_COL[r[2]]};map[r[0]]=n;pts.push(n)});
  const MINR=128;pts.forEach(n=>{const dx=n.x-AX,dy=n.y-AY,d=Math.hypot(dx,dy)||1;if(d<MINR){n.x=AX+dx/d*MINR;n.y=AY+dy/d*MINR}});
  pts.forEach(n=>{const o=pts.filter(m=>m!==n).map(m=>({m,d:Math.hypot(m.x-n.x,m.y-n.y)})).sort((a,b)=>a.d-b.d)[0];
    if(o&&n.id<o.m.id&&o.d<150)meshG.append(mk('line',{x1:n.x,y1:n.y,x2:o.m.x,y2:o.m.y,stroke:P.mesh,'stroke-width':1,opacity:.5}))});
  pts.forEach(n=>{
    n.spoke=mk('path',{d:pathD(n.x,n.y,n.bend),fill:'none',stroke:P.spoke,'stroke-width':1,opacity:n.live?.78:.4});spokesG.append(n.spoke);
    const rr=n.live?n.r:5.5;n.haloR=rr+1.5;n.phase=rnd()*6.283;
    n.halo=mk('circle',{cx:n.x,cy:n.y,r:n.haloR,fill:n.col,filter:'url(#rw-glow)',opacity:n.live?.34:.2});nodesG.append(n.halo);
    n.circ=mk('circle',{cx:n.x,cy:n.y,r:rr,fill:'none',stroke:n.col,'stroke-width':n.live?2:1.3,opacity:n.live?1:.6});if(!n.live)n.circ.setAttribute('stroke-dasharray','2 2');nodesG.append(n.circ);
    const dx=n.x-AX,dy=n.y-AY,d=Math.hypot(dx,dy)||1,ux=dx/d,uy=dy/d,off=rr+11,above=uy>.82,minor=!n.live||n.layer==='tool';
    const t=mk('text',{x:above?n.x:n.x+ux*off,y:above?n.y-(rr+9):n.y+uy*off+(Math.abs(uy)<.3?4:0),'text-anchor':above?'middle':(ux>.3?'start':(ux<-.3?'end':'middle')),'font-size':minor?9.5:12,'font-family':'inherit',fill:!n.live?P.labelDorm:(minor?P.labelMinor:P.label),opacity:!n.live?.75:1});
    t.textContent=n.label;n.txt=t;nodesG.append(t);
    const hit=mk('circle',{cx:n.x,cy:n.y,r:Math.max(rr+13,17),fill:'transparent'});hit.style.pointerEvents='all';hit.style.cursor='pointer';hit.addEventListener('click',()=>onSelect(n.id));nodesG.append(hit)});
  const fire=ids=>{ids.forEach((id,k)=>{const n=map[id];if(!n)return;
    setTimeout(()=>{n.spoke.setAttribute('stroke',P.spokeHot);n.spoke.setAttribute('stroke-width',1.6);n.spoke.setAttribute('opacity',.7);n._until=performance.now()+1150;
      const stream=()=>{if(performance.now()<n._until){spawn(n.spoke,false);setTimeout(stream,105)}};stream();
      setTimeout(()=>{n.circ.setAttribute('filter','url(#rw-glow)');n.circ.setAttribute('r',(n.live?n.r:5.5)+3);n.circ.setAttribute('stroke-width',n.live?3:2);n.circ.setAttribute('opacity',1)},560);
      setTimeout(()=>{n.spoke.setAttribute('stroke',P.spoke);n.spoke.setAttribute('stroke-width',1);n.spoke.setAttribute('opacity',n.live?.78:.4);n.circ.removeAttribute('filter');n.circ.setAttribute('r',n.live?n.r:5.5);n.circ.setAttribute('stroke-width',n.live?2:1.3);n.circ.setAttribute('opacity',n.live?1:.6)},2050)},k*210)});
    const co=ids.map(id=>map[id]).filter(Boolean);for(let i=0;i<co.length-1;i++){const a=co[i],b=co[i+1],ln=mk('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:P.link,'stroke-width':1.3,opacity:0});pulsesG.append(ln);setTimeout(()=>ln.setAttribute('opacity',.6),560);setTimeout(()=>ln.remove(),2400)}};
  allNodes=pts;const allSpokes=pts.map(p=>p.spoke);
  let last=performance.now(),phase=0,nextAmbient=last+1200,raf=0;
  const loop=t=>{if(!svg.isConnected)return;const dt=Math.max(0,Math.min(.05,(t-last)/1000));last=t;const st=getState(),lvl=MN_LEVEL[st]??.4,awake=st!=='standby';
    phase+=dt*(.85+1.9*lvl);
    for(const n of allNodes){const kk=(Math.sin(phase*.85+n.phase)+1)/2;n.halo.setAttribute('opacity',(n.live?.16:.09)+(n.live?.30:.18)*kk);n.halo.setAttribute('r',n.haloR+2*kk)}
    if(t>nextAmbient&&live.length<(awake?18:8)){spawn(allSpokes[(Math.random()*allSpokes.length)|0],true);if(awake&&Math.random()<.6)spawn(allSpokes[(Math.random()*allSpokes.length)|0],true);nextAmbient=t+(470-330*lvl)*(.5+Math.random()*.7)}
    for(let i=live.length-1;i>=0;i--){const p=live[i],pr=(t-p.born)/620;if(pr>=1){p.el.remove();live.splice(i,1);continue}const q=p.spoke.getPointAtLength(pr*p.L);p.el.setAttribute('cx',q.x);p.el.setAttribute('cy',q.y);p.el.setAttribute('opacity',(p.faint?.4:.9)*Math.sin(pr*Math.PI))}
    raf=requestAnimationFrame(loop)};
  // Açılan menünün içeriğine göre dallar: ilgili düğümlerin dalı parlar ve veri akıtır, diğerleri sönükleşir. focus([]) eski hâle döner.
  let focusTimer=0;
  const focus=(ids,main)=>{clearInterval(focusTimer);focusTimer=0;const on=new Set(ids||[]);
    for(const n of allNodes){const hot=on.has(n.id),idle=!on.size;
      n.spoke.setAttribute('stroke',hot?P.spokeHot:P.spoke);n.spoke.setAttribute('stroke-width',hot?(n.id===main?2.2:1.5):1);n.spoke.setAttribute('opacity',idle?(n.live?.78:.4):hot?1:.14);
      n.circ.setAttribute('stroke',hot?P.spokeHot:n.col);n.circ.setAttribute('opacity',idle?(n.live?1:.6):hot?1:.4);n.halo.setAttribute('opacity',idle?(n.live?.34:.2):hot?.55:.08);if(n.txt)n.txt.setAttribute('opacity',idle?(!n.live?.75:1):hot?1:.35)}
    if(on.size)focusTimer=setInterval(()=>{if(!svg.isConnected){clearInterval(focusTimer);return}for(const id of on){const n=map[id];if(n&&live.length<60)spawn(n.spoke,false)}},240)};
  // Alt başlıklar: açılan sayfanın bölümleri orbun çevresinde küçük orblar olarak belirir; ana düğümler geri çekilir. hideSubs() eski hâle döner.
  const subsG=mk('g');svg.append(subsG);const hideG=[nodesG,spokesG,pulsesG,meshG];let subs=[],subTimer=0;
  const wrapLabel=(s,max=17)=>{const out=[];let cur='';for(const w of String(s).split(/\s+/)){if(cur&&(cur+' '+w).length>max){out.push(cur);cur=w}else cur=(cur?cur+' ':'')+w}if(cur)out.push(cur);return out.slice(0,3)};
  const subColor=st=>st==='ok'?'#34d399':st==='warn'?'#ffb020':st==='bad'?'#ff4d6a':MN_COL.doer;
  const hideSubs=()=>{clearInterval(subTimer);subTimer=0;subs=[];subsG.replaceChildren();hideG.forEach(g=>g.removeAttribute('display'))};
  const selectSub=i=>{subs.forEach((s,k)=>{const on=k===i;s.spoke.setAttribute('stroke',on?P.spokeHot:P.spoke);s.spoke.setAttribute('stroke-width',on?2.2:1);s.spoke.setAttribute('opacity',on?1:.45);s.circ.setAttribute('r',on?s.r+2:s.r);s.circ.setAttribute('stroke',on?P.spokeHot:s.col);s.txt.setAttribute('fill',on?'#bff6ff':P.label);s.txt.setAttribute('font-weight',on?'700':'400')});
    clearInterval(subTimer);subTimer=setInterval(()=>{if(!svg.isConnected){clearInterval(subTimer);return}const s=subs[i];if(s&&live.length<60)spawn(s.spoke,false)},220)};
  const showSubs=(items,onPick,sel=0)=>{hideSubs();hideG.forEach(g=>g.setAttribute('display','none'));const n=items.length,R=165;
    items.forEach((it,i)=>{const a=(-90+i*360/n)*Math.PI/180,x=AX+R*Math.cos(a),y=AY+R*Math.sin(a),col=subColor(it.state);
      const spoke=mk('path',{d:pathD(x,y,i%2?-12:12),fill:'none',stroke:P.spoke,'stroke-width':1,opacity:.45});subsG.append(spoke);
      subsG.append(mk('circle',{cx:x,cy:y,r:12,fill:col,filter:'url(#rw-glow)',opacity:.35}));
      const circ=mk('circle',{cx:x,cy:y,r:9,fill:'none',stroke:col,'stroke-width':2.2});subsG.append(circ);
      const ux=Math.cos(a),uy=Math.sin(a),lines=wrapLabel(it.title),anchor=ux>.3?'start':ux<-.3?'end':'middle',tx=x+(anchor==='start'?16:anchor==='end'?-16:0);
      const txt=mk('text',{x:tx,'text-anchor':anchor,'font-size':13.5,'font-family':'inherit',fill:P.label});
      const baseY=Math.abs(uy)>.8?(uy>0?y+26:y-14-(lines.length-1)*16):y+4-(lines.length-1)*8;
      lines.forEach((ln,k)=>{const ts=mk('tspan',{x:tx,y:baseY+k*16});ts.textContent=ln;txt.append(ts)});subsG.append(txt);
      const hit=mk('circle',{cx:x,cy:y,r:22,fill:'transparent',tabindex:0,role:'button','aria-label':it.title});hit.style.pointerEvents='all';hit.style.cursor='pointer';
      const pick=()=>{selectSub(i);onPick(i)};hit.addEventListener('click',pick);hit.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pick()}});subsG.append(hit);
      subs.push({x,y,spoke,circ,txt,col,r:9})});
    selectSub(Math.max(0,Math.min(n-1,sel)))};
  raf=requestAnimationFrame(loop);return {fire,focus,showSubs,hideSubs,selectSub,hasSubs:()=>subs.length>0,subPos:i=>subs[i]?{x:subs[i].x,y:subs[i].y}:null,pos:id=>{const n=map[id];return n?{x:n.x,y:n.y}:null}};
}
// ---- ApexOrb "frame" varyantı: altın halka (SVG, CSS animasyonlarıyla) — APEX ile aynı ölçüler
function menuOrbSvg(){const W=900,H=520,cx=450,cy=260,R=155,G='#f5a623',GB='#ffd080',OUT=[178,194,212,230,250];
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" fill="none"><defs>
   <radialGradient id="mo-fill" cx="50%" cy="50%" r="50%"><stop offset="0%" stop-color="${G}" stop-opacity="0"/><stop offset="70%" stop-color="${G}" stop-opacity=".04"/><stop offset="88%" stop-color="${G}" stop-opacity=".18"/><stop offset="100%" stop-color="${GB}" stop-opacity=".5"/></radialGradient>
   <radialGradient id="mo-amb" cx="50%" cy="50%" r="50%"><stop offset="0%" stop-color="${G}" stop-opacity=".08"/><stop offset="100%" stop-color="${G}" stop-opacity="0"/></radialGradient>
   <filter id="mo-blur" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="7" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
   <ellipse cx="${cx}" cy="${cy}" rx="${R+130}" ry="${R+90}" fill="url(#mo-amb)" class="orb-ambient"/>
   ${OUT.map((r,i)=>`<circle cx="${cx}" cy="${cy}" r="${r}" stroke="${G}" stroke-width="${i===0?.8:.4}" stroke-opacity="${.15-i*.02}" fill="none" ${i%2?'stroke-dasharray="3 7"':''}/>`).join('')}
   <line x1="${cx}" y1="${cy-OUT[4]-10}" x2="${cx}" y2="${cy-OUT[4]+10}" stroke="${G}" stroke-width="1" opacity=".3"/><line x1="${cx}" y1="${cy+OUT[4]-10}" x2="${cx}" y2="${cy+OUT[4]+10}" stroke="${G}" stroke-width="1" opacity=".3"/>
   <g>${[0,1,2,3].map(i=>`<circle cx="${cx}" cy="${cy}" r="${R}" stroke="${G}" stroke-width=".8" fill="none" opacity=".18" class="sound-wave wave-${i}" style="transform-origin:${cx}px ${cy}px"/>`).join('')}</g>
   <circle class="mo-think orb-orbit-cw" cx="${cx}" cy="${cy}" r="${R+22}" stroke="${G}" stroke-width="1" stroke-opacity=".45" stroke-dasharray="8 14" fill="none" style="transform-origin:${cx}px ${cy}px"/>
   <circle cx="${cx}" cy="${cy}" r="${R}" fill="url(#mo-fill)" class="orb-ring-breathe"/>
   <circle cx="${cx}" cy="${cy}" r="${R}" stroke="${G}" stroke-width="18" stroke-opacity=".08" fill="none" filter="url(#mo-blur)" class="orb-ring-glow"/>
   <circle cx="${cx}" cy="${cy}" r="${R}" stroke="${G}" stroke-width="6" stroke-opacity=".4" fill="none" filter="url(#mo-blur)"/>
   <circle cx="${cx}" cy="${cy}" r="${R}" stroke="${GB}" stroke-width="2.5" stroke-opacity=".95" fill="none" class="orb-ring-bright"/>
   <circle cx="${cx}" cy="${cy}" r="${R*.58}" stroke="${G}" stroke-width="1.5" stroke-opacity=".15" fill="none" stroke-dasharray="55 25" class="orb-orbit-cw mo-sw1" style="transform-origin:${cx}px ${cy}px"/>
   <circle cx="${cx}" cy="${cy}" r="${R*.35}" stroke="${G}" stroke-width="1" stroke-opacity=".1" fill="none" stroke-dasharray="28 18" class="orb-orbit-ccw mo-sw2" style="transform-origin:${cx}px ${cy}px"/></svg>`}
// ---- OrbStatusBar: ekolayzır + çekirdek topu + durum yazısı + üç nokta (APEX ile aynı ölçüler)
function menuStatusSvg(state){const W=420,H=130,cx=210,cy=48,G='#f5a623',GB='#ffd080',act=state!=='idle',n=28,bw=3,wd=170,gap=(wd-n*bw)/(n-1);
  const LB={listening:'DİNLİYOR',speaking:'KONUŞUYOR',thinking:'İŞLENİYOR'}[state]||'BEKLİYOR';
  let bars='';for(let i=0;i<n;i++){const x=cx-wd/2+i*(bw+gap),h=act?8+Math.abs(Math.sin(i*.8))*26:3+Math.abs(Math.sin(i*.6))*5;
    bars+=`<rect x="${x}" y="${cy-h/2}" width="${bw}" height="${h}" rx="1.5" fill="${G}" opacity="${act?.85:.3}" style="transform-origin:${x+bw/2}px ${cy}px;${act?`animation:sbBar ${(.55+(i%5)*.16).toFixed(2)}s ease-in-out ${((i%7)*.07).toFixed(2)}s infinite alternate`:''}"/>`}
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" fill="none"><defs><filter id="sbBlur" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
   <line x1="${cx-150}" y1="${cy}" x2="${cx-28}" y2="${cy}" stroke="${G}" stroke-width="1" opacity="${act?.5:.18}" stroke-dasharray="4 3"/><line x1="${cx+28}" y1="${cy}" x2="${cx+150}" y2="${cy}" stroke="${G}" stroke-width="1" opacity="${act?.5:.18}" stroke-dasharray="4 3"/>
   ${bars}<circle cx="${cx}" cy="${cy}" r="20" stroke="${G}" stroke-width="1.5" stroke-opacity=".7" fill="#030200" filter="url(#sbBlur)" class="orb-center-ring"/>
   <circle cx="${cx}" cy="${cy}" r="6" fill="${GB}" opacity=".95" class="orb-center" style="filter:drop-shadow(0 0 10px ${G})"/>
   <text x="${cx}" y="${cy+44}" text-anchor="middle" fill="${G}" font-size="13" font-family="Consolas,monospace" letter-spacing="0.4em" opacity=".75">${LB}</text>
   ${[0,1,2].map(i=>`<circle cx="${cx+(i-1)*12}" cy="${cy+62}" r="2.5" fill="${G}" class="orb-dot-blink blink-${i}"/>`).join('')}
   ${act?'':`<text x="${cx}" y="${cy+80}" text-anchor="middle" fill="${G}" font-size="9" font-family="Consolas,monospace" letter-spacing="0.14em" opacity=".32">ÇEKİRDEĞE DOKUN · BİR DÜĞÜM SEÇ</text>`}</svg>`}
// Arka plan dalgaları: APEX-UI'nin ShaderBackground'ı (21st.dev topluluk bileşeninden uyarlanmış, MIT; kredi CREDITS'te). WebGL 'plasma waves', camgöbeği, konuşurken hızlanıp parlar.
// Sakin mod: Jarvis dinlerken/konuşurken ağır çizimler (büst, menü, dalgalar) her ikinci kareyi atlar; böylece ses işleyen süreç işlemciyi rahat kullanır.
// Atlanan karenin süresi sonrakine eklenir, hareket hızı aynı kalır (orb donmuş görünmez). Ses koduna dokunulmaz.
const UI_CALM=()=>S.orb==='listening'||S.orb==='speaking';
const MN_VS='attribute vec4 aVertexPosition;void main(){gl_Position=aVertexPosition;}';
const MN_FS=`
  precision highp float;
  uniform vec2 iResolution;
  uniform float iFlow;
  uniform float iVoiceIntensity;
  uniform float iGold;            // 0 = cyan (command center), 1 = gold (original)

  const float overallSpeed    = 0.11;
  const float gridSmoothWidth = 0.015;
  const float axisWidth       = 0.05;
  const float majorLineWidth  = 0.025;
  const float minorLineWidth  = 0.0125;
  const float majorLineFreq   = 5.0;
  const float minorLineFreq   = 1.0;
  const float scale           = 5.0;
  const float minLineWidth    = 0.025;
  const float maxLineWidth    = 0.32;
  const float lineSpeed       = 1.0 * overallSpeed;
  const float baseAmplitude   = 0.65;
  const float lineFrequency   = 0.14;
  const float warpSpeed       = 0.3 * overallSpeed;
  const float warpFrequency   = 0.4;
  const float warpAmplitude   = 1.6;
  const float offsetFrequency = 0.45;
  const float offsetSpeed     = 1.1 * overallSpeed;
  const float minOffsetSpread = 0.7;
  const float maxOffsetSpread = 2.4;
  const int   linesPerGroup   = 10;

  // line colors are mixed per-frame from iGold (see main): cyan ↔ gold

  #define drawCircle(pos, radius, coord) smoothstep(radius + gridSmoothWidth, radius, length(coord - (pos)))
  #define drawSmoothLine(pos, halfWidth, t) smoothstep(halfWidth, 0.0, abs(pos - (t)))
  #define drawCrispLine(pos, halfWidth, t) smoothstep(halfWidth + gridSmoothWidth, halfWidth, abs(pos - (t)))
  #define drawPeriodicLine(freq, width, t) drawCrispLine(freq / 2.0, width, abs(mod(t, freq) - (freq) / 2.0))

  float random(float t) {
    return (cos(t) + cos(t * 1.3 + 1.3) + cos(t * 1.4 + 1.4)) / 3.0;
  }

  float getPlasmaY(float x, float horizontalFade, float offset, float amp) {
    return random(x * lineFrequency + iFlow * lineSpeed) * horizontalFade * amp + offset;
  }

  void main() {
    vec2 fragCoord = gl_FragCoord.xy;
    vec2 uv = fragCoord.xy / iResolution.xy;

    // Voice intensity — clearly reactive when Apex speaks (amplitude + brightness + flow)
    float voiceBoost = iVoiceIntensity;
    vec4 lineColorBase = mix(vec4(0.06, 0.45, 0.55, 1.0), vec4(0.62, 0.40, 0.06, 1.0), iGold);
    vec4 lineColorCool = mix(vec4(0.03, 0.28, 0.38, 1.0), vec4(0.42, 0.27, 0.04, 1.0), iGold);
    float lineAmplitude = baseAmplitude * (1.0 + voiceBoost * 2.8);
    float brightnessBoost = 1.0 + voiceBoost * 2.2;

    vec2 space = (fragCoord - iResolution.xy / 2.0) / iResolution.x * 2.0 * scale;

    float horizontalFade = 1.0 - (cos(uv.x * 6.28) * 0.5 + 0.5);
    float verticalFade   = 1.0 - (cos(uv.y * 6.28) * 0.5 + 0.5);

    // Warp
    space.y += random(space.x * warpFrequency + iFlow * warpSpeed) * warpAmplitude * (0.5 + horizontalFade);
    space.x += random(space.y * warpFrequency + iFlow * warpSpeed + 2.0) * warpAmplitude * horizontalFade;

    // -- Depth: radial darkening at center (orb area), gold edge glow --
    // UV-space distance from center
    vec2 centerUv = uv - vec2(0.5, 0.48);
    float centerDist = length(centerUv * vec2(1.0, iResolution.x / iResolution.y));
    // Center stays very dark; edges pick up warm gold
    float edgeGlow  = smoothstep(0.15, 0.55, centerDist);
    // Bottom vertical glow — ground-level warmth
    float bottomGlow = smoothstep(0.65, 0.0, uv.y) * 0.35;
    // Upper-corner vignette — slightly cooler/darker
    float cornerDark = smoothstep(0.4, 0.8, length((uv - vec2(0.5, 0.5)) * 1.6));

    // Background: near-pure black, barely warm at edges
    vec4 bgCenter = vec4(0.001, 0.002, 0.003, 1.0);
    vec4 bgEdge   = mix(vec4(0.001, 0.006, 0.010, 1.0), vec4(0.009, 0.005, 0.001, 1.0), iGold);
    vec4 fragColor = mix(bgCenter, bgEdge, edgeGlow * 0.45 + bottomGlow * 0.6);
    fragColor *= verticalFade * 0.92 + 0.08;
    fragColor.a = 1.0;

    // -- Lines --
    vec4 lines = vec4(0.0);
    for (int l = 0; l < linesPerGroup; l++) {
      float normalizedIdx = float(l) / float(linesPerGroup);
      float offsetTime     = iFlow * offsetSpeed;
      float offsetPos      = float(l) + space.x * offsetFrequency;
      float rand = random(offsetPos + offsetTime) * 0.5 + 0.5;
      float halfWidth = mix(minLineWidth, maxLineWidth, rand * horizontalFade) / 2.0;
      float offset    = random(offsetPos + offsetTime * (1.0 + normalizedIdx)) * mix(minOffsetSpread, maxOffsetSpread, horizontalFade);
      float linePos   = getPlasmaY(space.x, horizontalFade, offset, lineAmplitude);
      float line = drawSmoothLine(linePos, halfWidth, space.y) / 2.0
                 + drawCrispLine(linePos, halfWidth * 0.15, space.y);

      float circleX = mod(float(l) + iFlow * lineSpeed, 25.0) - 12.0;
      vec2  circlePos = vec2(circleX, getPlasmaY(circleX, horizontalFade, offset, lineAmplitude));
      float circle = drawCircle(circlePos, 0.01, space) * 4.0;
      line += circle;

      // Depth-tinted color: warmer near bottom, cooler near top-center
      float depthTint = uv.y * 0.4 + normalizedIdx * 0.3;
      vec4  lineColor = mix(lineColorCool, lineColorBase, depthTint);
      lines += line * lineColor * rand;
    }

    // Very subtle glossy ring — barely visible
    float glossRing = smoothstep(0.38, 0.42, centerDist) * smoothstep(0.58, 0.42, centerDist);
    fragColor += mix(vec4(0.06, 0.42, 0.55, 0.0), vec4(0.62, 0.40, 0.06, 0.0), iGold) * glossRing * 0.03;

    fragColor += lines * brightnessBoost;
    gl_FragColor = fragColor;
  }
`;
function mnShader(cv,speaking){
  const gl=cv.getContext('webgl');if(!gl)return;
  let pr=null,buf=null,aPos,uRes,uT,uV,uG,lost=false;
  const init=()=>{const sh=(t,src)=>{const o=gl.createShader(t);gl.shaderSource(o,src);gl.compileShader(o);return gl.getShaderParameter(o,gl.COMPILE_STATUS)?o:null};
    const vs=sh(gl.VERTEX_SHADER,MN_VS),fs=sh(gl.FRAGMENT_SHADER,MN_FS);if(!vs||!fs)return false;
    pr=gl.createProgram();gl.attachShader(pr,vs);gl.attachShader(pr,fs);gl.linkProgram(pr);if(!gl.getProgramParameter(pr,gl.LINK_STATUS))return false;
    buf=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buf);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
    aPos=gl.getAttribLocation(pr,'aVertexPosition');uRes=gl.getUniformLocation(pr,'iResolution');uT=gl.getUniformLocation(pr,'iFlow');uV=gl.getUniformLocation(pr,'iVoiceIntensity');uG=gl.getUniformLocation(pr,'iGold');return true};
  if(!init())return;
  // ekran kartı bağlamı kaybolursa (güç tasarrufu, sürücü sıfırlama) çizim durur, geri gelince yeniden kurulur; aksi hâlde dalgalar sonsuza dek donabilirdi
  cv.addEventListener('webglcontextlost',e=>{e.preventDefault();lost=true},false);
  cv.addEventListener('webglcontextrestored',()=>{if(init())lost=false},false);
  let voice=0,flow=0,last=performance.now(),carry=0,skip=false;
  const frame=now=>{if(!cv.isConnected)return;const dt0=Math.max(0,Math.min((now-last)/1000,.05));last=now;
    if(lost){requestAnimationFrame(frame);return}
    if(UI_CALM()){skip=!skip;if(skip){carry+=dt0;requestAnimationFrame(frame);return}}
    else if(!idleGate(now,50)){carry+=dt0;requestAnimationFrame(frame);return}
    const dt=Math.min(dt0+carry,.1);carry=0;
    const w=cv.clientWidth||innerWidth,h=cv.clientHeight||innerHeight;if(cv.width!==w||cv.height!==h){cv.width=w;cv.height=h;gl.viewport(0,0,w,h)}
    const tg=speaking()?1:0,rate=tg>voice?dt*2:dt*.67;voice+=(tg-voice)*Math.min(rate*4,1);flow+=dt*(1+voice*2.4);
    gl.clearColor(0,0,0,1);gl.clear(gl.COLOR_BUFFER_BIT);gl.useProgram(pr);gl.uniform2f(uRes,w,h);gl.uniform1f(uT,flow);gl.uniform1f(uV,voice);gl.uniform1f(uG,0);
    gl.bindBuffer(gl.ARRAY_BUFFER,buf);gl.vertexAttribPointer(aPos,2,gl.FLOAT,false,0,0);gl.enableVertexAttribArray(aPos);gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
    requestAnimationFrame(frame)};
  requestAnimationFrame(frame);
}
function mountMenu(scene){
  const svg=scene.querySelector('#mn-svg'),stage=scene.querySelector('.mn-stage'),box=scene.querySelector('.mn-orbbox'),cv=scene.querySelector('.mn-core'),bar=scene.querySelector('.mn-status'),wrap=scene.querySelector('.apex-orb-wrap'),clock=scene.querySelector('.mn-time'),wx=scene.querySelector('.mn-wx'),cast=scene.querySelector('.mn-cast');
  const ost=()=>{const o=S.orb||'idle';return ['listening','thinking','speaking'].includes(o)?o:'idle'},wst=()=>({thinking:'processing',speaking:'speaking',listening:'listening'}[ost()]||'standby');
  const sc0=scene.querySelector('.mn-shader');if(sc0&&!document.body.classList.contains('seljuk-theme')&&!matchMedia('(prefers-reduced-motion: reduce)').matches)mnShader(sc0,()=>ost()==='speaking');
  const web=menuWeb(svg,wst,id=>menuCard(MENU_ROSTER.find(r=>r[0]===id)));scene._web=web;
  // ApexCore3D yerine 2B parçacık topu: 1200 camgöbeği parçacık, durumla büyür ve kaynar, bloom parlaması
  const N=1200,dir=[],ph=[],sp=[],br=[];for(let i=0;i<N;i++){const u=Math.random()*2-1,a=Math.random()*6.283,r=Math.sqrt(1-u*u);dir.push([Math.cos(a)*r,u,Math.sin(a)*r]);ph.push(Math.random()*6.283);sp.push(.7+Math.random()*1.7);br.push(.35+Math.pow(Math.random(),.45)*.65)}
  const spr=document.createElement('canvas');spr.width=spr.height=32;{const g=spr.getContext('2d'),gr=g.createRadialGradient(16,16,0,16,16,16);gr.addColorStop(0,'rgba(200,247,255,1)');gr.addColorStop(.35,'rgba(0,229,255,.6)');gr.addColorStop(1,'rgba(0,229,255,0)');g.fillStyle=gr;g.fillRect(0,0,32,32)}
  let last=performance.now(),Rt=46,spin=0,prev='idle',tm=0,sbState=null,lastScale=0;
  let cr=0,sk=false;
  const frame=now=>{if(!cv.isConnected)return;const dt0=Math.max(0,Math.min(.05,(now-last)/1000));last=now;
    if(UI_CALM()){sk=!sk;if(sk){cr+=dt0;requestAnimationFrame(frame);return}}
    else if(!idleGate(now,50)){cr+=dt0;requestAnimationFrame(frame);return}
    const dt=Math.min(dt0+cr,.1);cr=0;const t=now/1000,st=ost();
    if(st!==prev){if(st==='thinking')web.fire(['ai']);else if(st==='speaking'||st==='listening')web.fire(['ses']);prev=st}
    wrap.dataset.state=st;cast.style.background=`radial-gradient(circle at 50% 50%, rgba(13,210,255,${st==='speaking'?.30:.18}) 0%, rgba(13,170,228,.08) 30%, rgba(8,17,31,0) 62%)`;
    if(sbState!==st){sbState=st;bar.innerHTML=menuStatusSvg(st)}
    const sc=Math.min(1.6,box.clientWidth/560,box.clientHeight/540)||.6;if(Math.abs(sc-lastScale)>.001){lastScale=sc;stage.style.transform=`translate(-50%,-50%) scale(${sc})`}
    const tgt=st==='idle'?32:st==='speaking'?66:83;Rt+=(tgt-Rt)*.05*Math.min(3,dt*60);spin+=dt*.07;   // APEX: bekleme .58, konuşma 1.2, uyanık 1.5 birim (1 birim ≈ 55 px); yavaş dönüş
    const g=cv.getContext('2d');g.setTransform(1,0,0,1,0,0);g.clearRect(0,0,cv.width,cv.height);g.globalCompositeOperation='lighter';
    const cx=cv.width/2,cy=cv.height/2,k=cv.width/900,ca=Math.cos(spin),sa=Math.sin(spin),bub=st==='idle'?9:12,wav=st==='speaking'?27:(st==='idle'?0:6);   // kaynama genliği; konuşurken büyük dalga, uyanıkken yavaş nefes dalgası
    let gr=g.createRadialGradient(cx,cy,0,cx,cy,Rt*k*1.9);gr.addColorStop(0,'rgba(0,229,255,.28)');gr.addColorStop(1,'rgba(0,229,255,0)');g.fillStyle=gr;g.fillRect(cx-Rt*k*2,cy-Rt*k*2,Rt*k*4,Rt*k*4);
    const s0=(st==='idle'?3.0:3.6)*k;
    for(let i=0;i<N;i++){const d=dir[i],ri=br[i]*Rt+Math.sin(t*sp[i]+ph[i])*bub+(st==='speaking'?Math.sin(br[i]*5.5-t*5)*wav:Math.sin(br[i]*3-t*1.7)*wav),r=Math.max(0,ri)*k,x=d[0]*ca+d[2]*sa,z=-d[0]*sa+d[2]*ca,dd=(z+1)/2;g.globalAlpha=.25+.6*dd;const s=s0*(.6+.8*dd);g.drawImage(spr,cx+x*r-s/2,cy+d[1]*r-s/2,s,s)}
    g.globalAlpha=1;g.globalCompositeOperation='source-over';
    tm+=dt;if(tm>.5){tm=0;const d=new Date();if(clock)clock.textContent=d.toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit'})}
    requestAnimationFrame(frame)};
  cv.width=cv.height=Math.round(900*Math.min(1.5,devicePixelRatio||1));
  if(matchMedia('(prefers-reduced-motion: reduce)').matches)cv.style.display='none';
  requestAnimationFrame(frame);
}
PAGES.menu=pg=>{
  const d=new Date(),date=d.toLocaleDateString('tr-TR',{weekday:'short',month:'short',day:'numeric'}).toUpperCase(),w=(S.snap||{}).weather;
  pg.innerHTML=`<div class="hscene mnscene">
   <div class="mn-bg"></div><canvas class="mn-shader" aria-hidden="true"></canvas><div class="mn-cast"></div>
   <div class="mn-websvg" aria-hidden="true"><svg id="mn-svg" width="100%" height="100%" viewBox="0 0 680 480" preserveAspectRatio="xMidYMid meet" style="overflow:visible;font-family:inherit;pointer-events:none"></svg></div>
   <nav class="visually-hidden" aria-label="Jarvis menüsü"><ul>${MENU_ROSTER.map(r=>`<li><button type="button" data-act="mnopen" data-k="${r[0]}">${esc(r[1])} - ${esc((MENU_INFO[r[0]]||[''])[0])}</button></li>`).join('')}</ul></nav>
   <div class="mn-orbbox"><div class="mn-stage"><div class="apex-orb-wrap" data-state="idle" style="position:absolute;left:0;top:190px">${menuOrbSvg()}</div><canvas class="mn-core" style="position:absolute;left:0;top:0;width:900px;height:900px"></canvas></div></div>
   <button class="mn-tap" data-act="mic" aria-label="Jarvis çekirdeği: konuşmak için dokun"></button>
   <div class="mn-status"></div>
   <div class="mn-hud"><div class="mn-glow"></div><small class="mn-lbl" data-act="mnlamp" role="button" tabindex="0" aria-label="Menü panelini aç/kapat">MENÜ</small>
    <div class="mn-clock"><div><b class="mn-time">${d.toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit'})}</b><small>${esc(date)}</small></div>${w?`<div><span class="mn-t">${Math.round(w.temp)}°C</span><small class="mn-wx">${esc(String(w.city||'').toUpperCase())}${w.desc?' · '+esc(String(w.desc).toUpperCase()):''}</small></div>`:''}</div>
    <button class="mn-bell" data-act="notif" aria-label="Bildirimler">${ic('bell')}${needCount()?`<i>${needCount()}</i>`:''}</button>
    <div class="mn-tiles"><button class="mn-tile" data-go="home">Ana ekrana dön</button><button class="mn-tile" data-go="team">Ekip merkezi</button></div></div>
   <div id="mn-card"></div></div>`;
  {const sc=pg.querySelector('.hscene');sc.addEventListener('click',e=>menuOutsideClick(sc,e))}
  mountMenu(pg.querySelector('.hscene'));
  menuOpenPending();
};
PAGES.home=pg=>{
  const sn=S.snap||{},u=((sn.user||{}).name)||'Kullanıcı',l=sn.llm||{},q=l.groq||{},sy=sn.sys||{},f=sn.flags||{},gh=sn.github||{};
  const provider=(l.provider||'gemini').toLowerCase(),phone=(sn.phone||{}).running;
  const hr=new Date().getHours(),greet=hr<5?'İyi geceler':hr<11?'Günaydın':hr<17?'İyi günler':hr<22?'İyi akşamlar':'İyi geceler';
  const gauge=(name,val,col)=>{const v=Math.max(0,Math.min(100,Math.round(Number(val)||0)));return `<div class="hg" style="--v:${v};--c:${col}"><div class="hgr"><b>${v}%</b></div><small>${name}</small></div>`};
  const sec=k=>{const v=(l.sec||{})[k];return v!=null?v+'s':'—'};
  const row=(icon,name,stTxt,kind,badge)=>`<div class="hrow"><span class="hi">${icon}</span><b>${name}</b><span class="hs ${kind}"><span class="dot ${kind==='good'?'':kind}"></span>${esc(stTxt)}</span>${badge!==undefined?`<span class="hb">${esc(badge)}</span>`:''}</div>`;
  const boot=!S.snap?'':checks().map(([i,t,[st,kind]])=>`<p class="${kind}" style="animation-delay:${300+checks().findIndex(x=>x[1]===t)*260}ms"><span></span>${esc(t.toUpperCase())} · ${esc(st.toUpperCase())}</p>`).join('');
  const keyWarn=(S.snap&&!l.key)?`<button class="home-key-warning" data-act="keysetup">${ic('key')}<span><b>${esc(u)} için Gemini anahtarı yok</b><small>Yanıt alabilmek için bu profile anahtar ekle.</small></span><strong>Ekle →</strong></button>`:'';
  const live=pg.querySelector('.hscene');
  if(live&&HOME_HOLOGRAM){   // hologram kurulu: yeniden kurma, yalnız değişen parçaları güncelle
    const cs=live.querySelector('.center-stage'),w=cs&&cs.querySelector('.home-key-warning');
    if(cs&&!l.key&&!w)cs.insertAdjacentHTML('afterbegin',keyWarn);else if(l.key&&w)w.remove();
    const on=live.querySelector('.hs-online');
    if(on){const lab=on.querySelector('span'),num=on.querySelector('b'),bar=on.querySelector(':scope > i'),lt=!S.snap?'BAĞLANIYOR':(sn.flags||{}).sleep?'UYKUDA':'ÇEVRİMİÇİ',hv=health();
      if(on.dataset.real)on.dataset.real=JSON.stringify([lt,hv+'%',hv+'%']);   // açılış animasyonu sürerken gerçek değer bitişte geri gelir
      else if(lab&&num&&bar){lab.textContent=lt;num.textContent=hv+'%';bar.style.setProperty('--v',hv+'%')}}
    const bt=live.querySelector('.hs-boot');if(bt&&bt.innerHTML!==boot)bt.innerHTML=boot;
    return}
  pg.innerHTML=`<div class="hscene">
   <div class="center-stage">${keyWarn}</div>
   <div class="hs-online"><span>${!S.snap?'BAĞLANIYOR':(sn.flags||{}).sleep?'UYKUDA':'ÇEVRİMİÇİ'}</span><b>${S.snap?health()+'%':'…'}</b><i style="--v:${S.snap?health():0}%"></i><button class="hs-go" data-go="menu">MENÜ ${ic('arrow')}</button><button class="hs-go" data-act="bustreplay" aria-label="Açılış animasyonunu tekrar oynat">TEKRAR OYNAT ↻</button></div>
   <details class="hs-appearance"><summary>GÖRÜNÜM</summary>${hologramChoices()}</details>
   <div class="hs-boot">${boot}</div>
  </div>`;
  mountBust(pg.querySelector('.center-stage'));bindStatus(pg.querySelector('.hscene'));
};
ACT.goset=el=>{if(['ai','baglanti'].includes(el.dataset.k)){S.tool='aihub';S.sset=el.dataset.k;go('tools');return}S.sset=el.dataset.k;go('settings')};
ACT.research=()=>{const i=$('.hask input');if(i){i.value='İnternette araştır: ';i.focus()}};

// ======================================================================= ÇALIŞMA MODU
PAGES.study=pg=>{
  const st=((S.snap||{}).study)||{mode:'teacher',modes:{},docs:[],progress:[],books:[],exams:[],recent_exam_years:[],exam_priority:70};
  if(st.mode==='math'){S.mathAttachment=st.math_attachment||S.mathAttachment||'';if(!S.sans&&!S.studyBusy&&(st.math_turns||[]).length)S.sans=mathAnswer(st.math_turns)}
  const ov=S.sov||{};S.stab=S.stab||'learn';
  const docs=st.docs||[];if(!docs.some(d=>+d.id===+S.sdoc))S.sdoc=docs.length?docs[docs.length-1].id:0;
  const selected=docs.find(d=>+d.id===+S.sdoc);
  const sourcePicker=docs.length?`<label class="mut">Çalışılacak kaynak<select id="study-source" style="width:100%;margin:8px 0">${docs.map(d=>`<option value="${d.id}" ${+d.id===+S.sdoc?'selected':''}>${esc(d.title)}</option>`).join('')}</select></label><details class="study-source-suggestions"><summary>Çalışma Önerileri</summary><div id="source-questions" class="qrow" style="flex-wrap:wrap"></div></details>`:'<p class="mut">Bir konu yazabilir veya kaynak yükleyebilirsin.</p>';

  const modes=st.modes||{},books=st.books||[],exams=st.exams||[],yrs=st.recent_exam_years||[],an=st.exam_analysis||{},astale=!!st.exam_analysis_stale;
  const srcrow=(x,exam=false)=>{const xl=[x.year,x.period,x.session].filter(Boolean).join(' · ');return `<div class="srow"><span class="i">${ic(exam?'check':'book')}</span><div style="flex:1"><b>${esc(x.title)}</b>${exam?`<small>${esc(xl||'')} çıkmış soru</small>`:''}</div><span class="mut">${(x.chars||0).toLocaleString('tr')} karakter</span><button class="ab" data-act="studydel" data-id="${x.id}">${ic('trash')}</button></div>`};
  const abar=(x,val,tag='',col='')=>`<div style="margin:7px 0"><div style="display:flex;justify-content:space-between;gap:8px;font-size:12px"><b>${esc(x)}</b><span class="mut">${esc(tag)}</span></div><div style="height:5px;border-radius:5px;background:rgba(255,255,255,.08);margin-top:4px;overflow:hidden"><i style="display:block;height:100%;width:${Math.max(4,Math.min(100,+val||0))}%;background:${col||'linear-gradient(90deg,#f2ad32,#55c8ff)'};border-radius:5px"></i></div></div>`;
  const per=an.per_course||[];
  const analysisHtml=yrs.length?`<div class="exam-analysis" style="margin-top:12px;padding:12px;border:1px solid rgba(255,190,70,.24);border-radius:13px;background:rgba(7,25,45,.46)"><div class="ch" style="margin-bottom:8px"><span class="ct">Son 3 Yıl Sınav Analizi</span><button class="btn sm" data-act="studyanalyze">${ic('spark')} ${an.status==='ready'&&!astale?'Güncelle':'Analiz Et'}</button></div>${an.status==='ready'&&!astale?`<div class="mut" style="font-size:11px;margin-bottom:8px">${(an.years||yrs).join(' · ')} · ${an.question_count||0} soru${an.coverage?' · anahtarlı '+an.coverage.with_key+'/'+an.coverage.questions+' · etiketli '+an.coverage.tagged+'/'+an.coverage.questions:an.source==='kitapçık'?' · kitapçık':''} · güven: ${esc(an.confidence||'orta')}</div>${(per.length?per:[{label:'',top_topics:an.top_topics||[],rising_topics:an.rising_topics||[]}]).map(c=>`${c.label?`<b style="font-size:12.5px;color:var(--gold)">${esc(c.label)}</b>`:''}${(c.top_topics||[]).slice(0,6).map(x=>abar(x.name,x.pct,`${x.count} soru · %${x.pct}`)).join('')||'<div class="mut">Konu bulunamadı.</div>'}${(c.rising_topics||[]).length?`<div class="qrow" style="margin:4px 0 8px;flex-wrap:wrap">${c.rising_topics.map(x=>`<span class="pill warn">↑ ${esc(x.name)} +${x.delta_pct}</span>`).join('')}</div>`:''}`).join('')}`:`<div class="mut">${astale?'Ders seçimi ya da çıkmış sorular değişti. Analizi başlat; ilk seferde biraz sürer.':'Derslerini seçip analizi başlat: hangi konudan kaç soru çıktığı burada görünür.'}</div>`}</div>`:'';
  const courses=ov.courses||[],sel=courses.filter(c=>c.selected);
  const coursesHtml=yrs.length?`<div class="ch" style="margin-top:4px"><span class="ct">Derslerim</span><span class="mut" style="font-size:11.5px">Kitapçıkta ${courses.length} ders var; yalnız seçtiklerin analiz edilir</span></div>
    <div class="qrow" style="flex-wrap:wrap;margin:6px 0">${sel.map(c=>`<span class="qchip on">${ic('book')} ${esc(c.label)} <button class="ab" style="padding:0 0 0 4px" data-act="scdel" data-k="${esc(c.key)}">×</button></span>`).join('')||'<span class="mut">Henüz ders seçilmedi.</span>'}</div>
    <div style="display:flex;gap:8px"><select id="scadd" class="inp" style="flex:1">${courses.filter(c=>!c.selected).map(c=>`<option value="${esc(c.key)}">${esc(c.label)} · ${c.count} soru</option>`).join('')}</select><button class="btn sm" data-act="scadd">${ic('plus')} Ekle</button></div>`:'';
  const fall=(ov.focus_all||ov.focus||[]);
  const focusHtml=fall.length?`<div class="sfocus"><b>${ic('target')} Bugün öncelik · ${fall.length} konu <small class="mut" style="font-weight:400">sınavda sık çıkan ve zayıf olduğun önce · tıkla, önce anlatsın</small></b><div class="sflist">${fall.map((f,i)=>`<button class="qchip ${i<3?'top':''}" data-act="slearn" data-t="${esc(f.topic)}" data-k="${esc(f.mk)}" data-c="${esc(f.course)}"><span class="no">${i+1}</span> ${esc(f.topic)} <small class="mut">%${f.weight} sınavda · ${esc(f.why)}</small></button>`).join('')}</div></div>`:'';
  const tabs=[['learn','Çalış','spark'],['quiz','Soru Çöz','check'],['wrong','Yanlışlarım','refresh'],['mock','Deneme','target'],['plan','Programım','calendar'],['resources','Kaynaklar','folder'],['progress','İlerleme','target'],['hoca','Hoca','spark']];
  const td=ov.today||{},tg=td.target||null,cov=ov.coverage||{},prep=td.readiness||0;
  const summary=`<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:12px"><div class="card"><small class="mut">Sınava kalan</small><b style="display:block;font-size:20px;margin-top:4px">${td.days_left==null?'—':td.days_left+' gün'}</b></div><div class="card"><small class="mut">Hazırlık seviyesi</small><b style="display:block;font-size:20px;margin-top:4px">%${prep}</b></div><div class="card"><small class="mut">Bugünkü hedef</small><b style="display:block;margin-top:4px">${tg?esc(tg.topic):'Henüz belirlenmedi'}</b><small class="mut">${tg?esc(tg.course.split(' (')[0]):esc(td.note||'')}</small></div><div class="card"><small class="mut">Son 3 yıl kapsaması</small><b style="display:block;font-size:20px;margin-top:4px">${cov.year_count||0}/3 yıl</b><small class="mut">${(cov.years||[]).join(' · ')||'Soru eklenmedi'}</small></div></div>${tg?`<button class="btn pri" style="width:100%;margin-bottom:12px" data-act="stoday" data-t="${esc(tg.topic)}" data-k="${esc(tg.mk)}" data-c="${esc(tg.course)}">${ic('spark')} Bugünkü Çalışmayı Başlat · ${esc(td.note||'')}</button>`:''}`;
  const libraryHtml=`${coursesHtml}${analysisHtml}
    <div class="ch" style="margin-top:16px"><span class="ct">Çalışma Kaynakları</span><span style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn sm pri" data-act="studyadd">${ic('plus')} Kitap / Kaynak</button><button class="btn sm" data-act="studyexamadd">${ic('plus')} Çıkmış Soru</button>${(st.docs||[]).length?`<button class="btn sm" data-act="studyclear">Hepsini sil</button>`:''}</span></div>
    ${(st.pending||[]).map(x=>`<div class="srow"><span class="i">${ic(x.state==='error'?'x':'clock')}</span><div style="flex:1"><b>${esc(x.title)}</b><small style="${x.state==='error'?'color:#ff8a8a':''}">${x.state==='error'?'Eklenemedi: '+esc(x.error||''):'Okunuyor… büyük kitaplarda 1-2 dakika sürebilir'}</small></div></div>`).join('')}
    <div class="ch" style="margin-top:10px"><span class="ct">Kitaplar / Kaynaklar</span></div>
    ${books.map(x=>srcrow(x,false)).join('')||'<div class="empty">Henüz kitap/kaynak yok.</div>'}
    <div class="ch" style="margin-top:18px"><span class="ct">Çıkmış Sorular · Son 3 Yıl</span><span class="mut">Yıl · dönem · oturum etiketiyle eklenir</span></div>
    ${exams.slice().sort((a,b)=>(b.year||0)-(a.year||0)).map(x=>srcrow(x,true)).join('')||'<div class="empty">Son 3 yılın çıkmış soru PDF’lerini buraya ekle.</div>'}
    <div class="ch" style="margin-top:18px"><span class="ct">Son çalışmalar</span></div>
    ${(st.progress||[]).slice().reverse().slice(0,6).map(x=>`<div class="srow"><span class="i">${ic('check')}</span><div style="flex:1"><b>${esc((modes[x.mode]||x.mode||'Çalışma'))}</b><small>${esc(x.q||'')}</small></div><span class="mut">${esc(x.ts||'')}</span></div>`).join('')||'<div class="empty">Henüz çalışma kaydı yok.</div>'}`;
  let body='';
  if(S.stab==='learn')body=`
    ${['source','math'].includes(st.mode)?'':focusHtml}
    <div class="study-question-row"><textarea class="big" id="studyq" rows="2" placeholder="${st.mode==='math'?'Matematik sorunu yaz (örn. 2x + 4 = 10) veya çözüm adımı hakkında soru sor…':st.mode==='source'?'Seçili bölümle ilgili sorunu veya alıştırma cevabını yaz…':'Konuyu, soruyu veya ne çalışmak istediğini yaz… (örn. Hücre zarını anlat)'}">${st.mode==='math'?esc(S.mathDraft||''):''}</textarea>
    <button class="btn pri" data-act="studystart">${ic('spark')} ${st.mode==='math'?'Anlat':'Çalışmaya Başla'}</button>${st.mode==='math'?'<button class="btn" data-act="mathsolve">Çöz</button>':''}</div>
    ${st.mode==='source'?`<div class="qrow" style="margin-top:10px"><button class="btn sm" data-act="sourcesend" data-q="devam et">Sonraki bölüm</button><button class="btn sm" data-act="sourcesend" data-q="Bu bölümden bir alıştırma sorusu sor; cevabımı bekle.">Bu bölümden soru sor</button></div>`:''}<div id="slessonact" class="slactwrap">${['source','math'].includes(st.mode)?'':lessonActs()}</div>
    ${st.mode==='math'?'<div class="qrow study-answer-actions"><button class="btn sm" data-act="studyplain">Daha basit anlat</button><button class="btn sm" data-act="slspeak">Sesli anlat</button><button class="btn sm" data-act="slstop">Okumayı durdur</button></div>':''}<div id="studya" class="studyanswer" style="margin-top:12px">${S.sans?(st.mode==='math'?mathHtml(S.sans):mdMath(S.sans)):''}</div>`;
  else if(S.stab==='quiz')body=quizHtml(ov,abar);
  else if(S.stab==='wrong')body=wrongHtml(ov);
  else if(S.stab==='hoca')body=hocaHtml(ov);
  else if(S.stab==='mock')body=mockHtml(ov);
  else if(S.stab==='resources')body=libraryHtml;
  else if(S.stab==='progress')body=summary;
  else body=planHtml(ov);
  pg.innerHTML=`<div class="pagehead study-heading"><div><h1>Kaynak ve anlatım</h1><p>Soruyu solda gör, takıldığın kısmı sağda öğren.</p></div></div>
   <div class="study-tabs stabs">${tabs.map(([k,t,i])=>`<button class="${S.stab===k?'on':''}" data-act="stab" data-k="${k}">${ic(i)} ${t}</button>`).join('')}</div>
   <div class="study-toolbar"><span class="study-mode-label" id="study-mode-label">Çalışma Türü</span><div class="study-mode-buttons" role="group" aria-labelledby="study-mode-label">${Object.entries(modes).map(([k,v])=>`<button class="btn sm ${st.mode===k?'on':''}" data-act="studymode" data-k="${esc(k)}" aria-pressed="${st.mode===k}">${esc(v)}</button>`).join('')}</div></div>
   <div class="grid2 sgrid ${S.stab==='learn'?'study-split':''}">${S.stab==='learn'?`<section class="card study-source"><div class="ch study-source-head"><span class="ct">Soru / Kaynak</span><div class="study-selection-actions"><button class="btn sm" data-act="studyselection" id="study-selection-button" disabled>Seçili alanı anlat</button><button class="btn sm" data-act="studyselectionclear">Seçimi kaldır</button></div><small class="mut" id="study-selection-note">Görselde sürükleyerek alan seç; metinde açıklanacak kısmı işaretle.</small></div>${st.mode==='math'?'':sourcePicker}<div id="study-preview" class="study-preview"><p class="mut">${st.mode==='math'?'Dosya veya görsel yükleyebilirsin.':'Seçili kaynağın metni burada görünür.'}</p></div>${st.mode==='math'?mathUploadHtml():''}</section>`:''}<section class="card glow study-lesson"><div class="ch"><span class="ct">${S.stab==='learn'?'Anlatım':esc(tabs.find(t=>t[0]===S.stab)?.[1]||'Çalışma')}</span></div>${body}</section>
   ${S.swin&&S.stab==='learn'?`<section class="card swin" id="swin">${winHtml()}</section>`:''}</div>`;
  const picker=$('#study-source');if(picker){picker.onchange=()=>{S.sdoc=+picker.value;S.sans='';S.slesson=null;render()};loadSourceQuestions(S.sdoc)}
  const drop=$('#math-drop');if(drop){drop.ondragover=e=>{e.preventDefault();drop.style.borderColor='var(--gold)'};drop.ondragleave=()=>{drop.style.borderColor=''};drop.ondrop=e=>{e.preventDefault();drop.style.borderColor='';const files=[...e.dataTransfer.files];if(files.length>1)return toast('Soruları sırayla ele almak için tek dosya bırak.');if(files[0])uploadMathFile(files[0])}};
  const q=$('#studyq');if(q&&st.mode==='math')q.oninput=()=>{S.mathDraft=q.value};if(q)q.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ACT.studystart()}};
  if(typeof initStudyWorkspace==='function')initStudyWorkspace(pg);
  if(!S.sov&&!S._sovLoading){S._sovLoading=1;loadStudy().then(()=>{S._sovLoading=0;if(S.page==='study')render()})}
};
async function loadStudy(){const owner=((S.snap||{}).user||{}).name,ticket=Symbol();S.studyOverviewRequest=ticket;const result=await tryApi('study_overview');if(owner!==((S.snap||{}).user||{}).name||S.studyOverviewRequest!==ticket)return;S.sov=result||{}}
function lessonActs(){const L=S.slesson;if(!L||!S.sans)return '';return `<div class="slact"><button class="btn pri" data-act="slquiz">${ic('check')} Anladım, “${esc(L.topic)}” sorularını çöz</button>${S.sspeaking?`<button class="btn" data-act="slstop">${ic('volx')} Okumayı durdur</button>`:`<button class="btn" data-act="slspeak">${ic('vol')} Sesli anlat</button>`}<button class="btn" data-act="slmore">${ic('spark')} Daha basit anlat</button>${S.swin?'':`<button class="btn" data-act="swinopen">${ic('image')} Görsel ve videolar</button>`}</div>`}
function winHtml(){const m=S.smedia;const tab=S.swtab||'wiki';
  const head=`<div class="ch"><span class="ct">${ic('image')} ${esc((m&&m.topic)||'Kaynak penceresi')}</span><button class="ab" data-act="swinclose" title="Kapat">×</button></div>
   <div class="stabs" style="margin-bottom:10px"><button class="${tab==='wiki'?'on':''}" data-act="swtab" data-k="wiki">${ic('book')} Vikipedi</button><button class="${tab==='yt'?'on':''}" data-act="swtab" data-k="yt">${ic('play')} YouTube</button></div>`;
  if(!m||m.loading)return head+`<div class="mut">${m?`“${esc(m.topic)}” aranıyor…`:'Bir konu anlatıldığında burada açılır.'}</div>`;
  if(m.blocked)return head+`<div class="mut">${esc(m.blocked)}</div>`;
  if(tab==='wiki'){const w=m.wiki||{};
    return head+(w.title?`<div class="swwiki">${w.thumb?`<img src="${esc(w.thumb)}" alt="">`:''}<b>${esc(w.title)}</b><p>${esc(w.extract||'')}</p><button class="btn sm" data-act="slink" data-u="${esc(w.url)}">${ic('link')} Vikipedi’de aç</button></div>`:'<div class="mut">Vikipedi’de uygun makale bulunamadı.</div>')
      +((m.images||[]).length?`<div class="ct" style="font-size:13px;margin:12px 0 6px">Görseller</div><div class="swimgs">${m.images.map(x=>`<a class="smimg" data-act="swimg" data-src="${esc(x.src)}" data-u="${esc(x.url)}" title="${esc(x.title)}"><img src="${esc(x.src)}" alt="" loading="lazy"><span>${esc(x.title)}</span></a>`).join('')}</div>`:'')
      +(S.swbig?`<div class="swbig" data-act="swbigclose"><img src="${esc(S.swbig)}" alt=""></div>`:'');}
  const vids=m.videos||[];
  return head+(S.swvid?`<div class="swplayer"><iframe src="https://www.youtube-nocookie.com/embed/${esc(S.swvid)}?autoplay=1&rel=0" allow="autoplay; encrypted-media; picture-in-picture" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe></div>`:'')
    +(vids.length?vids.map(v=>`<a class="smvid ${S.swvid===v.id?'on':''}" data-act="swplay" data-id="${esc(v.id)}"><img src="${esc(v.thumb)}" alt="" loading="lazy"><span><b>${esc(v.title)}</b><small>${esc(v.channel)}</small></span></a>`).join(''):`<div class="mut" style="margin-bottom:8px">${m.youtube_key?'Bu konu için video bulunamadı.':'Videoların burada listelenip oynatılması için YouTube anahtarı gerekiyor.'}</div>${m.youtube_key?'':`<button class="btn sm" data-act="sytkey">YouTube anahtarı ekle</button>`}`)
    +`<button class="btn sm" style="width:100%;margin-top:8px" data-act="slink" data-u="${esc(m.search)}">${ic('play')} YouTube’da ara</button>`}
function redrawWin(){const w=$('#swin');if(w)w.innerHTML=winHtml();else if(S.page==='study')render()}
ACT.slearn=async el=>{const t=el.dataset.t,k=el.dataset.k,c=el.dataset.c||'';S.stab='learn';S.slesson={topic:t,mk:k,course:c};S.sans='';render();
  const q=$('#studyq');if(q)q.value=`${t} konusunu anlat`;
  const a=$('#studya');if(a)a.innerHTML=`<div class="slwait">${ic('book')} “${esc(t)}” dersi hazırlanıyor… <small>(ayrıntılı anlatım 15-30 sn sürebilir)</small></div>`;
  S.swin=1;showMedia(t,c);
  const lesson=S.slesson,owner=((S.snap||{}).user||{}).name,ticket=Symbol();S.studyLessonRequest=ticket;
  const r=await tryApi('study_lesson',t,c,k,false);if(!r||owner!==((S.snap||{}).user||{}).name||S.slesson!==lesson||S.studyLessonRequest!==ticket)return;
  S.sans=r.text||'';S.slesson.no_book=r.no_book;const a2=$('#studya');if(a2)a2.innerHTML=(r.no_book?`<div class="pill warn" style="margin-bottom:8px;display:inline-block">Kitap eklenmediği için genel bilgiyle anlatıldı</div>`:'')+mdMath(S.sans);
  const la=$('#slessonact');if(la)la.innerHTML=lessonActs();if(a2)a2.scrollIntoView({behavior:'smooth',block:'start'});
  if(((S.ui||{}).study_voice)!==false)ACT.slspeak();await refresh()};
ACT.slquiz=()=>{const L=S.slesson;if(!L)return;tryApi('stop_speaking');S.sspeaking=0;S.stab='quiz';S.sqf=L.mk?L.mk+'§'+L.topic:'';S.squiz=null;S.sres=null;render();ACT.sqnext()};
ACT.slmore=async()=>{const L=S.slesson;if(!L)return;const owner=((S.snap||{}).user||{}).name,ticket=Symbol();S.studyLessonRequest=ticket;tryApi('stop_speaking');const a=$('#studya');if(a)a.innerHTML='<div class="slwait">Daha basit anlatılıyor…</div>';const r=await tryApi('study_lesson',L.topic,L.course||'',L.mk||'',true);if(owner!==((S.snap||{}).user||{}).name||S.slesson!==L||S.studyLessonRequest!==ticket)return;S.sans=(r&&r.text)||S.sans;const a2=$('#studya');if(a2)a2.innerHTML=mdMath(S.sans);if(((S.ui||{}).study_voice)!==false)ACT.slspeak()};
ACT.slspeak=async()=>{if(!S.sans)return;S.sspeaking=1;const la=$('#slessonact');if(la)la.innerHTML=lessonActs();await tryApi('study_speak',S.sans)};
ACT.dstop=async()=>{S.sspeaking=0;S._spk2=0;await tryApi('stop_speaking');const la=$('#slessonact');if(la)la.innerHTML=lessonActs()};
ACT.slstop=async()=>{S.sspeaking=0;await tryApi('stop_speaking');const la=$('#slessonact');if(la)la.innerHTML=lessonActs()};
ACT.swinopen=()=>{S.swin=1;render();if(!S.smedia&&S.slesson)showMedia(S.slesson.topic,S.slesson.course||'')};
ACT.swinclose=()=>{S.swin=0;S.swvid='';render()};
ACT.swtab=el=>{S.swtab=el.dataset.k;redrawWin()};
ACT.swplay=el=>{S.swvid=el.dataset.id;redrawWin()};
ACT.swimg=el=>{S.swbig=el.dataset.src;redrawWin()};
ACT.swbigclose=()=>{S.swbig='';redrawWin()};
function mediaHtml(m){
  if(!m)return `<div class="mut" style="font-size:12px">Bir konu çalıştığında ilgili görseller ve videolar burada çıkar.</div>${(S.snap||{}).youtube_key?'':`<button class="link" style="font-size:11.5px;margin-top:8px" data-act="sytkey">YouTube anahtarı ekle</button>`}`;
  if(m.loading)return `<div class="mut">“${esc(m.topic)}” için görseller aranıyor…</div>`;
  if(m.blocked)return `<div class="mut">${esc(m.blocked)}</div>`;
  const imgs=(m.images||[]).map(x=>`<a class="smimg" data-act="slink" data-u="${esc(x.url)}" title="${esc(x.title)} · ${esc(x.from)}"><img src="${esc(x.src)}" alt="" loading="lazy"><span>${esc(x.title)}</span></a>`).join('');
  const vids=(m.videos||[]).map(v=>`<a class="smvid" data-act="slink" data-u="${esc(v.url)}"><img src="${esc(v.thumb)}" alt="" loading="lazy"><span><b>${esc(v.title)}</b><small>${esc(v.channel)}</small></span></a>`).join('');
  return `<div class="ct" style="font-size:13px;margin-bottom:6px">${ic('image')} ${esc(m.topic)}</div>${imgs||'<div class="mut" style="font-size:12px">Uygun görsel bulunamadı.</div>'}
   <div class="ct" style="font-size:13px;margin:12px 0 6px">${ic('play')} Videolar</div>${vids}
   <button class="btn sm" style="width:100%;margin-top:6px" data-act="slink" data-u="${esc(m.search)}">${ic('play')} YouTube’da “${esc(m.topic)}” ara</button>
   ${m.youtube_key?'':`<button class="link" style="font-size:11.5px;margin-top:6px" data-act="sytkey">Videoların burada listelenmesi için YouTube anahtarı ekle</button>`}`;
}
function quizHtml(ov,abar){
  const q=S.squiz,r=S.sres;const stats=ov.stats||{};const keys=Object.keys(stats);
  if(!keys.length)return `<div class="empty" style="margin-top:12px">Soru çözmek için sağdaki <b>Derslerim</b>’den dersini seç ve çıkmış soru PDF’lerini ekle.</div>`;
  const filt=`<div style="display:flex;gap:8px;margin-bottom:12px"><select id="sqtopic" class="inp" style="flex:1"><option value="">Karışık · öncelikli konulardan</option>${keys.map(k=>stats[k].topics.filter(t=>t.name!=='Diğer').map(t=>`<option value="${esc(k)}§${esc(t.name)}" ${S.sqf===k+'§'+t.name?'selected':''}>${esc(t.name)} · ${esc(stats[k].label.split(' (')[0])}</option>`).join('')).join('')}</select><button class="btn sm pri" data-act="sqnext">${ic('spark')} ${q?'Yeni Soru':'Başla'}</button></div>`;
  const card=q?`<div class="sqcard"><div class="mut" style="font-size:11.5px;margin-bottom:6px">${esc(q.course)} · ${[q.year,q.period,q.session].filter(Boolean).join(' · ')} · ${q.n}. soru · ${esc(q.topic)}</div><div class="sqtext">${esc(q.text)}</div>
    <div class="sqopts">${Object.entries(q.options).map(([k,v])=>{const cls=r?(k===r.answer?'ok':(k===r.choice?'bad':'')):'';return `<button class="sqopt ${cls}" data-act="sqans" data-c="${k}" ${r?'disabled':''}><b>${k}</b><span>${esc(v)}</span></button>`}).join('')}</div>
    ${r?`<div class="sqres ${r.ok?'ok':'bad'}">${r.ok?'Doğru! 🎉':`Yanlış. Doğru cevap: <b>${r.answer}</b>`}</div><div style="display:flex;gap:8px;margin-top:8px"><button class="btn sm" data-act="sqwhy">${ic('spark')} Neden?</button><button class="btn sm pri" data-act="sqnext">Sonraki Soru ${ic('chev')}</button></div><div id="sqexp" class="studyanswer" style="margin-top:10px">${S.sexp?mdMath(S.sexp):''}</div>`:''}</div>`:'<div class="mut">Soru, sınavda sık çıkan ve senin zayıf olduğun konulardan seçilir. Her cevabın kaydedilir.</div>';
  const table=keys.map(k=>{const c=stats[k];return `<div class="ch" style="margin-top:16px"><span class="ct">${esc(c.label)}</span><span class="mut">${c.asked} soru çözüldü · ${c.asked?Math.round(c.correct*100/c.asked):0}% doğru</span></div>${c.topics.filter(t=>t.name!=='Diğer').map(t=>abar(t.name,t.pct==null?0:t.pct,t.asked?`${t.correct}/${t.asked} doğru · sınavda %${t.weight}`:`henüz çözülmedi · sınavda %${t.weight}`,t.pct==null?'rgba(255,255,255,.15)':t.pct<50?'linear-gradient(90deg,#ff6b6b,#ff9f43)':t.pct<75?'linear-gradient(90deg,#f2ad32,#ffd36b)':'linear-gradient(90deg,#28d38c,#55c8ff)')).join('')}`}).join('');
  return filt+card+table;
}
function hocaHtml(ov){
  const h=(ov&&ov.hoca)||{enabled:true,lesson:null,weak:[]},L=h.lesson,weak=h.weak||[];
  const on=h.enabled!==false;
  const head=`<div class="ch" style="margin-top:10px"><span class="ct">Hoca</span><span class="pill ${on?'good':'warn'}">${on?'Sohbet komutları açık':'Sohbet komutları kapalı'}</span><button class="btn sm" data-act="hocatoggle">${on?'Kapat':'Aç'}</button></div>`;
  const start=`<div class="study-question-row" style="margin-top:8px"><input class="inp" id="hocatopic" placeholder="Hangi konuyu çalışalım? (örn. hücre)" style="flex:1"><button class="btn pri" data-act="hocastart">${ic('spark')} Başla</button></div><p class="mut" style="font-size:12px;margin-top:6px">Ders sohbet ekranında ilerler. Sohbette de “hoca modu: konu” veya “konu konusunu öğret” diyebilirsin.</p>`;
  let lesson='';
  if(L){
    const steps=(L.steps||[]).map((t,i)=>`<div class="srow"><span class="i">${ic(i+1<L.step?'check':(i+1===L.step?'spark':'clock'))}</span><div style="flex:1"><b>${esc(t)}</b></div></div>`).join('');
    lesson=`<div class="card" style="margin-top:12px"><div class="ch"><span class="ct">${esc(L.topic)}</span><span class="mut">Adım ${L.step}/${L.total}</span></div>${steps}
      ${L.text?`<div style="white-space:pre-wrap;margin-top:10px">${esc(L.text)}</div>`:''}
      ${L.question?`<div style="margin-top:10px"><b>Kontrol sorusu:</b> ${esc(L.question)}</div><div class="study-question-row" style="margin-top:8px"><input class="inp" id="hocaans" placeholder="Cevabın" style="flex:1"><button class="btn pri" data-act="hocaans">Cevapla</button></div>`:''}
      <div class="qrow" style="margin-top:10px"><button class="btn sm" data-act="hocasay" data-q="sonraki adım">Sonraki adım</button><button class="btn sm" data-act="hocasay" data-q="bilmiyorum">Bilmiyorum</button><button class="btn sm" data-act="hocasay" data-q="konuyu değiştir">Dersi bırak</button></div></div>`;
  }
  const weakHtml=weak.length?weak.map(w=>`<div class="srow"><span class="i">${ic(w.due_now?'refresh':'clock')}</span><div style="flex:1"><b>${esc(w.title)}</b><small>${esc(w.topic||'')}</small></div><span class="pill ${w.due_now?'warn':'good'}">${w.due_now?'tekrar zamanı':'bekliyor'}</span></div>`).join(''):'<div class="empty">Zayıf konu yok. Kontrol sorusunu yanlış yaptığın adımlar burada aralıklı tekrara (1, 3, 7 gün arayla) girer; iki doğru tekrardan sonra öğrenildi sayılır.</div>';
  return `${head}${L?'':start}${lesson}<div class="ch" style="margin-top:16px"><span class="ct">Zayıf konularım</span></div>${weakHtml}`;
}
function wrongHtml(ov){
  const w=ov.wrong||{},rows=w.active||[],due=w.due||[];
  if(!rows.length)return `<div class="empty" style="margin-top:12px">Yanlış defterin temiz. Yanlış yaptığın çıkmış sorular burada 1 ve 3 günlük tekrar döngüsüne girer; iki doğru tekrardan sonra öğrenildi sayılır.</div>`;
  return `<div class="ch" style="margin-top:10px"><span class="ct">Yanlış Defteri</span><span class="pill ${due.length?'warn':'good'}">${due.length} tekrar zamanı geldi · ${w.learned||0} öğrenildi</span></div>
   <div class="mut" style="font-size:12px;margin:8px 0">Yanlış soru ertesi gün tekrar gelir. Doğru yaparsan 3 gün sonra yeniden sorulur; iki doğru tekrardan sonra öğrenildi kabul edilir.</div>
   ${rows.slice(0,30).map(x=>`<div class="srow"><span class="i">${ic(x.due_now?'bell':'clock')}</span><div style="flex:1"><b>${esc(x.topic)}</b><small>${esc(x.course.split(' (')[0])} · ${[x.year,x.period,x.session].filter(Boolean).join(' · ')} · ${x.n}. soru · tekrar ${esc(x.due)}</small></div><span class="pill ${x.due_now?'warn':''}">${x.correct_after?x.correct_after+' doğru':'bekliyor'}</span></div>`).join('')}
   <button class="btn pri" style="margin-top:10px" data-act="swrongnext">${ic('refresh')} ${due.length?'Şimdi Tekrar Et':'Sıradaki Yanlışı Tekrar Et'}</button>`;
}
function mockHtml(ov){
  const m=ov.mock||{};
  if(!m.active)return `<div class="ch" style="margin-top:10px"><span class="ct">Gerçek Deneme Modu</span></div><div class="mut" style="margin:8px 0 12px">Sorular son 3 yılın gerçek soru havuzundan seçilir; konu dağılımı geçmiş sınav ağırlığını doğal olarak korur.</div><div class="qrow"><button class="btn pri" data-act="smockstart" data-n="10">10 Soru</button><button class="btn" data-act="smockstart" data-n="20">20 Soru</button><button class="btn" data-act="smockstart" data-n="0">Tam Deneme</button></div>`;
  if(m.finished)return `<div class="sqres ok" style="margin-top:12px">Deneme tamamlandı · <b>${m.correct}/${m.total}</b> · %${m.total?Math.round(m.correct*100/m.total):0}</div><div class="ch" style="margin-top:14px"><span class="ct">Konu Sonuçları</span></div>${(m.breakdown||[]).map(x=>`<div class="srow"><div style="flex:1"><b>${esc(x.topic)}</b><small>${x.correct}/${x.asked} doğru</small></div><span class="pill ${x.pct<50?'warn':'good'}">%${x.pct}</span></div>`).join('')}<button class="btn pri" style="margin-top:12px" data-act="smockstart" data-n="10">Yeni Deneme</button>`;
  const q=m.current;if(!q)return '<div class="empty">Deneme sorusu hazırlanıyor…</div>';
  return `<div class="mut" style="margin:10px 0">${m.answered+1}/${m.total} · ${esc(q.course)} · ${[q.year,q.period,q.session].filter(Boolean).join(' · ')}</div><div class="sqcard"><div class="sqtext">${esc(q.text)}</div><div class="sqopts">${Object.entries(q.options).map(([k,v])=>`<button class="sqopt" data-act="smockans" data-q="${esc(q.id)}" data-c="${k}"><b>${k}</b><span>${esc(v)}</span></button>`).join('')}</div></div>`;
}
function planHtml(ov){
  const p=ov.plan||{},c=p.cfg||{minutes:60,days:[0,1,2,3,4,5],time:'20:00',exam_date:''};const D=['Pzt','Sal','Çar','Per','Cum','Cmt','Paz'];
  const form=`<div class="spform"><label>Sınav tarihi<input type="date" id="spdate" class="inp" value="${esc(c.exam_date||'')}"></label><label>Günde kaç dakika<input type="number" id="spmin" class="inp" min="15" max="480" step="15" value="${c.minutes}"></label><label>Saat<input type="time" id="sptime" class="inp" value="${esc(c.time)}"></label></div>
   <div class="qrow" style="margin:8px 0;flex-wrap:wrap">${D.map((d,i)=>`<button class="qchip ${(c.days||[]).includes(i)?'on':''}" data-act="spday" data-i="${i}">${d}</button>`).join('')}</div>
   <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn pri sm" data-act="spsave">${ic('calendar')} Programı Oluştur</button><button class="btn sm" data-act="sprem">${ic('bell')} Hatırlatıcıları Kur</button></div>`;
  const left=p.days_left!=null?`<div class="pill ${p.days_left<14?'warn':'good'}" style="margin:10px 0;display:inline-block">Sınava ${p.days_left} gün kaldı</div>`:'';
  const days=(p.days||[]).map(d=>`<div class="spday"><div class="spd"><b>${esc(d.day)}</b><small>${d.date.split('-').reverse().slice(0,2).join('.')} · ${esc(d.time)}</small></div><div style="flex:1">${d.blocks.map(b=>`<div class="spb ${b.kind}"><span>${b.kind==='konu'?ic('book'):b.kind==='soru'?ic('check'):ic('target')}</span><div><b>${esc(b.topic||b.text)}</b><small>${b.kind==='konu'?'Konu çalış':b.kind==='soru'?`${b.questions} çıkmış soru çöz`:'Deneme'} · ${b.minutes} dk${b.course?' · '+esc(b.course.split(' (')[0]):''}</small></div></div>`).join('')}</div></div>`).join('');
  return form+left+(days?`<div class="mut" style="font-size:12px;margin:8px 0">Sınavda sık çıkan ve senin zayıf olduğun konulara daha çok zaman ayrıldı. Soru çözdükçe program kendini günceller.</div>${days}`:`<div class="empty" style="margin-top:12px">${esc(p.note||'Programı oluşturmak için tarihi ve süreyi seçip “Programı Oluştur”a bas.')}</div>`);
}
ACT.stoday=el=>(((S.snap||{}).study||{}).mode==='teacher'?ACT.slearn(el):ACT.studystart());
ACT.swrongnext=async()=>{const q=await tryApi('study_wrong_next');if(!q)return toast('Tekrar edilecek yanlış soru yok.');S.stab='quiz';S.squiz=q;S.sres=null;S.sexp='';S.sqf=q.mk+'§'+q.topic;render()};
ACT.smockstart=async el=>{const r=await tryApi('study_mock_start',+el.dataset.n);if(!r)return;await loadStudy();render()};
ACT.smockans=async el=>{if(S.mockBusy)return;const owner=((S.snap||{}).user||{}).name,session=((S.sov||{}).mock||{}).id,ticket=Symbol();S.mockBusy=ticket;try{const r=await tryApi('study_mock_answer',el.dataset.q,el.dataset.c,session||'');if(!r||owner!==((S.snap||{}).user||{}).name)return;await loadStudy();if(owner===((S.snap||{}).user||{}).name)render()}finally{if(S.mockBusy===ticket)S.mockBusy=false}};
ACT.scadd=async()=>{const v=$('#scadd')&&$('#scadd').value;if(!v)return;const cur=((S.sov||{}).courses||[]).filter(c=>c.selected).map(c=>c.key);await tryApi('study_set_courses',[...cur,v]);await loadStudy();await refresh();render();toast('Ders eklendi. Sınav analizini başlatabilirsin.')};
ACT.scdel=async el=>{const cur=((S.sov||{}).courses||[]).filter(c=>c.selected).map(c=>c.key).filter(k=>k!==el.dataset.k);await tryApi('study_set_courses',cur);await loadStudy();await refresh();render()};
ACT.sfocus=el=>ACT.slearn(el);
ACT.hocasay=el=>say(el.dataset.q);
ACT.hocastart=()=>{const t=(($('#hocatopic')||{}).value||'').trim();if(!t)return toast('Konuyu yaz.');say('hoca modu: '+t)};
ACT.hocaans=()=>{const t=(($('#hocaans')||{}).value||'').trim();if(!t)return toast('Cevabını yaz.');say('cevap: '+t)};
ACT.hocatoggle=async()=>{const on=((S.sov||{}).hoca||{}).enabled!==false;const r=await tryApi('settings_save',{hoca_enabled:!on});if(r===undefined||r===null)return;await loadStudy();if(S.page==='study')render()};
ACT.sqnext=async()=>{const f=($('#sqtopic')&&$('#sqtopic').value)||S.sqf||'';S.sqf=f;const [k,t]=f?f.split('§'):['',''];const owner=((S.snap||{}).user||{}).name,ticket=Symbol();S.studyQuizRequest=ticket;S.sres=null;S.sexp='';const q=await tryApi('study_quiz_next',k||'',t||'');if(owner!==((S.snap||{}).user||{}).name||S.studyQuizRequest!==ticket)return;if(!q){S.squiz=null;render();toast('Bu seçimde cevap anahtarı olan soru bulunamadı.','bad');return}S.squiz=q;render()};
ACT.sqans=async el=>{if(!S.squiz||S.sres||S.quizBusy)return;const question=S.squiz,c=el.dataset.c,owner=((S.snap||{}).user||{}).name,ticket=Symbol();S.quizBusy=ticket;try{const r=await tryApi('study_quiz_answer',question.id,c,question.attempt_id||'');if(!r||owner!==((S.snap||{}).user||{}).name||S.squiz!==question)return;S.sres={...r,choice:c};await loadStudy();if(owner===((S.snap||{}).user||{}).name)render()}finally{if(S.quizBusy===ticket)S.quizBusy=false}};
ACT.sqwhy=async()=>{const e=$('#sqexp');if(e)e.innerHTML='<span class="mut">Açıklanıyor…</span>';const t=await tryApi('study_explain',S.squiz.id,(S.sres||{}).choice||'');S.sexp=t||'';if(e)e.innerHTML=mdMath(S.sexp)};
ACT.spday=el=>{el.classList.toggle('on')};
ACT.spsave=async()=>{const days=$$('[data-act="spday"]').map((b,i)=>b.classList.contains('on')?+b.dataset.i:-1).filter(i=>i>=0);const p=await tryApi('study_plan_set',{exam_date:$('#spdate').value,minutes:+$('#spmin').value,time:$('#sptime').value,days});if(p){S.sov=S.sov||{};S.sov.plan=p;render();toast('Program hazır.')}};
ACT.sprem=async()=>{const n=await tryApi('study_plan_reminders');if(n!=null)toast(`${n} günlük çalışma hatırlatması kuruldu. Saati gelince Jarvis haber verir.`)};
ACT.slink=el=>{if(el.dataset.u)tryApi('open_link',el.dataset.u)};
ACT.ytsave=async()=>{const k=($('#ytk')||{}).value||'';if(!k.trim())return toast('Anahtarı yapıştır.','bad');toast('Anahtar deneniyor…');const r=await tryApi('study_set_youtube_key',k.trim());if(r){toast(r.test&&r.test.ok?'YouTube anahtarı çalışıyor ve kaydedildi.':'Anahtar kaydedildi; '+((r.test||{}).msg||'deneme sonucu bekleniyor')+'.');await refresh();render()}};
ACT.ytdel=async()=>{if(!await ask('YouTube anahtarı silinsin mi?'))return;await tryApi('study_set_youtube_key','');await refresh();render()};
ACT.sytkey=async()=>{const k=await askText('YouTube Data API anahtarını yapıştır (Google Cloud Console › YouTube Data API v3 › Kimlik bilgileri). Ücretsizdir.','');if(k==null)return;const r=await tryApi('study_set_youtube_key',k);if(r){toast(r.set?(r.test&&r.test.ok?'YouTube anahtarı çalışıyor ve kaydedildi.':'YouTube anahtarı kaydedildi.'):'YouTube anahtarı silindi.');await refresh();if(S.smedia&&S.smedia.topic)showMedia(S.smedia.topic)}};
async function showMedia(topic,course=''){if(!topic)return;const owner=((S.snap||{}).user||{}).name,ticket=Symbol();S.studyMediaRequest=ticket;S.smedia={topic,loading:1};S.swvid='';S.swbig='';S.swin=1;redrawWin();const m=await tryApi('study_media',topic,course);if(owner!==((S.snap||{}).user||{}).name||S.studyMediaRequest!==ticket)return;S.smedia=m||{topic,images:[],videos:[]};redrawWin()}
ACT.studymode=async el=>{if(S.studyBusy)return toast('Yanıt tamamlandıktan sonra modu değiştirebilirsin.');const r=await tryApi('study_mode',el.dataset.k);if(!r)return;S.sans='';await refresh();if(S.page==='study'){S.stab='learn';render();if(el.dataset.k==='exam')return ACT.studystart()}};
async function loadSourceQuestions(id){const user=((S.snap||{}).user||{}).name;const r=await tryApi('study_source_info',+id,(S.slesson||{}).topic||'');if(+id!==+S.sdoc||user!==((S.snap||{}).user||{}).name)return;const box=$('#source-questions');if(box&&r)box.innerHTML='<span class="mut">Kaynakla çalış:</span>'+r.questions.map(q=>`<button class="qchip" data-act="sourcequestion" data-q="${esc(q)}">${esc(q)}</button>`).join('')}
ACT.sourcequestion=el=>{const q=$('#studyq');if(q){q.value=el.dataset.q;q.focus();toast('İsteği düzenleyebilir, ardından Çalışmaya Başla’ya basabilirsin.')}};
ACT.sourcesend=el=>{if(S.studyBusy)return;const q=$('#studyq');if(q){q.value=el.dataset.q;return ACT.studyask()}};
ACT.studystart=async()=>{
  if(S.studyBusy)return;
  const q=(($('#studyq')||{}).value||'').trim(),st=(S.snap||{}).study||{};
  const ov=S.sov||{},target=S.slesson||(ov.today||{}).target||(ov.focus||[])[0];
  if(st.mode==='math'){
    if(!q&&!st.math_attachment&&!S.mathAttachment)return toast('Bir soru yaz veya dosya/görsel ekle.','bad');
    return ACT.studyask();
  }
  if(st.mode==='exam'){
    S.stab='quiz';S.squiz=null;S.sres=null;S.sexp='';
    S.sqf=target&&target.mk?target.mk+'§'+target.topic:'';
    render();return ACT.sqnext();
  }
  const selectedPrompt=target&&q===`${target.topic} konusunu anlat`;
  if(q&&!selectedPrompt&&!/^(?:ders )?çalışmaya başla[.! ]*$/i.test(q))return ACT.studyask();
  if(st.mode!=='source'){
    if(target&&target.topic)return ACT.slearn({dataset:{t:target.topic,k:target.mk||'',c:target.course||''}});
  }
  const input=$('#studyq');if(input)input.value='';
  return ACT.studyask();
};
ACT.studyask=async()=>{if(S.studyBusy||S.mathUploadBusy)return;if(S.snap?.study?.mode==='math')return runMath((($('#studyq')||{}).value||'').trim());let q=(($('#studyq')||{}).value||'').trim();if(/^(?:ders )?çalışmaya başla[.! ]*$/i.test(q))q='';if(!q&&!S.sdoc)return toast('Önce bir kaynak yükle veya çalışmak istediğin konuyu yaz.','bad');const ticket=Symbol(),doc=+S.sdoc||0;S.studyBusy=ticket;const user=((S.snap||{}).user||{}).name;const a=$('#studya');if(a)a.innerHTML='<span class="mut">Seçili kaynakla çalışılıyor…</span>';S.slesson=null;
try{const st=((S.snap||{}).study)||{};const pdf=S.studyPdfPage,chosen=S.studySelection;const selection=chosen?.owner===user&&chosen.data?.page?chosen.data:pdf?.owner===user&&pdf.mode===st.mode&&pdf.doc===doc?{image_id:pdf.image_id,page:pdf.page,full_page:true}:null;const r=selection?await api('study_answer_with_context',q.trim(),st.mode||'teacher',doc,selection):await api('study_answer_with_context',q.trim(),st.mode||'teacher',doc);if(user!==((S.snap||{}).user||{}).name||doc!==( +S.sdoc||0)||S.studyBusy!==ticket)return;S.sans=r&&Array.isArray(r.turns)?r.turns.map(t=>`**${t.role}**\n\n${t.text}`).join('\n\n---\n\n'):(r&&r.text)||'';const box=$('#studya');if(box)box.innerHTML=mdMath(S.sans);await refresh()}catch(e){if(user!==((S.snap||{}).user||{}).name||S.studyBusy!==ticket)return;const box=$('#studya');if(box)box.textContent='Çalışma başlatılamadı: '+e.message;toast(e.message,'bad')}finally{if(S.studyBusy===ticket)S.studyBusy=false}};

function mathAnswer(turns){return [...(turns||[])].reverse().find(t=>t.role==='Jarvis')?.text||''}
function mathUploadHtml(){return `<div id="math-drop" class="study-upload"><span>${ic('clip')} Dosya veya görsel sürükleyip bırak<br><small>PDF’nin Sayfa Düzeni Korunur · En Fazla 20 MB</small></span><button class="btn sm" data-act="mathpick">Dosya seç</button><button class="btn sm" data-act="mathclear">Yeni soru</button></div>`}
async function runMath(question,path='',expectedOwner=S.snap?.user?.name,wholeQuestion=false){
 if(S.studyBusy||expectedOwner!==S.snap?.user?.name||S.snap?.study?.mode!=='math')return;
 const ticket=Symbol();S.studyBusy=ticket;const owner=expectedOwner;
 const current=()=>owner===S.snap?.user?.name&&S.snap?.study?.mode==='math'&&S.studyBusy===ticket;
 const box=$('#studya');if(box)box.textContent='Soru okunuyor, açıklama hazırlanıyor…';
 try{
  const pdf=S.studyPdfPage;
  const selection=!wholeQuestion&&!path&&S.studySelection?.owner===owner?S.studySelection.data:!path&&pdf?.owner===owner&&pdf.mode==='math'?{image_id:pdf.image_id,page:pdf.page,full_page:true}:null;
  const result=selection?await api('study_math',question,path,selection):await api('study_math',question,path);if(!current())return;
  S.sans=mathAnswer(result.turns)||result.text||'';S.mathResponse={...result,owner,text:S.sans};S.mathAttachment=result.attachment||'';if(path||wholeQuestion)S.studySelection=null;if(path)S.studyPdfPage=null;
  const output=$('#studya');if(output){output.innerHTML=mathHtml(S.sans);output.scrollTop=0;}
  await refresh();if(S.page==='study'&&typeof initStudyWorkspace==='function')initStudyWorkspace($('#page'));
 }catch(error){if(current()){const output=$('#studya');if(output)output.textContent='Çözüm tamamlanamadı: '+error.message;toast(error.message,'bad')}}
 finally{if(S.studyBusy===ticket)S.studyBusy=false}
}
async function uploadMathFile(file){
 if(S.studyBusy||S.mathUploadBusy)return toast('Devam eden çözümün bitmesini bekle.');
 if(!/\.(pdf|docx|txt|md|png|jpe?g|webp|gif|bmp)$/i.test(file.name))return toast('PDF, Word, metin veya görsel yükleyebilirsin.','bad');
 if(file.size>20000000)return toast('Dosya 20 MB sınırını aşıyor.','bad');
 const owner=S.snap?.user?.name,question=(($('#studyq')||{}).value||'').trim(),ticket=Symbol();S.mathUploadBusy=ticket;
 toast(`${file.name} yükleniyor…`);
 try{const result=await upload(file,true);if(!result||owner!==S.snap?.user?.name||S.snap?.study?.mode!=='math'||S.mathUploadBusy!==ticket)return;await runMath(question,result.path,owner)}
 finally{if(S.mathUploadBusy===ticket)S.mathUploadBusy=false}
}
ACT.mathsolve=()=>{if(S.mathUploadBusy)return;const question=(($('#studyq')||{}).value||'').trim();return runMath(question?question+'\nBu sorunun tamamını adım adım çöz.':'Ekteki veya konuşmadaki güncel sorunun tamamını adım adım çöz; önceki alan seçimi yalnız bir ara işlemdi.','',S.snap?.user?.name,true)};
ACT.mathpick=()=>{const input=$('#upl');input.accept='.pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp,.gif,.bmp';input.onchange=()=>{const file=input.files[0];input.value='';if(file)return uploadMathFile(file)};input.click()};
ACT.mathclear=async()=>{const owner=S.snap?.user?.name;await api('study_math_clear');if(owner!==S.snap?.user?.name)return;S.studyBusy=false;S.mathUploadBusy=false;S.mathDraft='';S.mathAttachment='';S.mathResponse=null;S.studyPdfPage=null;S.studySelection=null;S.sans='';await refresh();if(owner===S.snap?.user?.name)render()};

ACT.studyanalyze=async()=>{toast('Seçili derslerin çıkmış soruları konulara ayrılıyor… (ilk seferde 20-40 sn)');const r=await tryApi('study_exam_analysis',true);if(r&&r.status==='ready')toast('Sınav analizi hazır.');await loadStudy();await refresh();if(S.page==='study')render()};
const studyUpload=async(kind,meta={})=>{const inp=$('#upl');inp.accept='.pdf,.docx,.xlsx,.txt,.md';inp.onchange=async()=>{const f=inp.files[0];inp.value='';if(!f)return;toast((kind==='exam'?'Çıkmış soru':'Kaynak')+' ekleniyor: '+f.name);try{const r=await fetch('/upload?to=files&name='+encodeURIComponent(f.name),{method:'POST',headers:{'X-Jarvis-Token':TOKEN},body:f});const j=await r.json();if(!j.ok)throw new Error(j.error);const a=kind==='exam'?await api('study_add_exam_path',j.data.path,+meta.year,meta.period||'',meta.session||''):await api('study_add_path',j.data.path);const lab=[meta.year,meta.period,meta.session].filter(Boolean).join(' · ');toast(a&&a.exists?'Bu kaynak zaten ekli.':a&&a.already?'Bu kaynak zaten ekleniyor, bekle.':(kind==='exam'?lab+' çıkmış soruları':'Kaynak')+' okunuyor; bitince listede görünecek (büyük kitaplarda 1-2 dakika).');after(0)}catch(e){toast(e.message,'bad')}};inp.click()};
ACT.studyadd=()=>studyUpload('book');
ACT.studyexamadd=async()=>{const y=await askText('Çıkmış sorular hangi sınav yılına ait?',String(new Date().getFullYear()-1));if(y==null)return;const n=Number(String(y).trim());if(!Number.isInteger(n)||n<2000||n>new Date().getFullYear()+1){toast('Geçerli bir sınav yılı gir.','bad');return}const p=await askText('Dönem bilgisi (isteğe bağlı, örn. 1. Dönem):','');if(p==null)return;const o=await askText('Oturum bilgisi (isteğe bağlı, örn. 2. Oturum):','');if(o==null)return;studyUpload('exam',{year:n,period:p.trim(),session:o.trim()})};
ACT.studydel=el=>{S.sov=null;after(api('study_remove_document',+el.dataset.id)).then(()=>{if(S.page==='study')render()})};
ACT.studyclear=async ()=>{if(await ask('Bu kullanıcıya ait tüm kitaplar ve çıkmış sorular silinsin mi?')){S.sov=null;after(api('study_clear_documents')).then(()=>{if(S.page==='study')render()})}};

// ======================================================================= SOHBET
// Ortadaki hologram dünya (webui/merkez.webp). Jarvis'in durumuna göre (dinliyor/konuşuyor/düşünüyor) parlaması değişir.
function convIcon(t){t=(t||'').toLowerCase();return /pdf|dosya|belge|özet/.test(t)?['file','blue']:/excel|tablo/.test(t)?['grid','green']:/görsel|resim|ekran|fotoğraf/.test(t)?['image','purple']:/kod|python|javascript/.test(t)?['term','orange']:/web|araştır|haber/.test(t)?['globe','blue']:/plan|proje|görev/.test(t)?['list','navy']:/seyahat|rota|gezi/.test(t)?['target','red']:['msg','navy']}
function convTitle(t){t=(t||'').replace(/^(?:"[^"]+"\s*)+/,'').trim();return t.length>34?t.slice(0,32)+'…':t||'Sohbet'}
async function loadHist(){S.hist=await tryApi('history','',1500)||[]}
function days(){const by={};(S.hist||[]).forEach(r=>{const d=(r.ts||'').slice(0,10);if(d)(by[d]=by[d]||[]).push(r)});return Object.entries(by).sort((a,b)=>a[0]<b[0]?1:-1)}
function dayLabel(d,lastTs){const t=ymd(new Date()),y=ymd(new Date(Date.now()-864e5));return d===t?(lastTs||'').slice(11,16):d===y?'Dün':d.slice(8,10)+'.'+d.slice(5,7)}
PAGES.chat=pg=>{
  if(!S.day)S.day=ymd(new Date());
  const Q=chatShortcuts();
  pg.innerHTML=`<div class="chatp"><section class="card convs"><div class="convh"><span class="ct">Sohbetler</span><button class="newc" data-act="newchat">${ic('plus')} Yeni</button></div>
    <div class="search csr">${ic('search')}<input id="cq" placeholder="Sohbetlerde ara..." value="${esc(S.cq||'')}"></div>
    <div class="clist" id="clist"><div class="empty" style="padding:10px">Yükleniyor…</div></div>
    <button class="frow" style="padding:10px 8px;border-top:1px solid var(--line)" data-act="allconv">${ic('list')}<span>${S.allConv?'Son Sohbetler':'Tüm Sohbetleri Gör'}</span>${ic('chev')}</button></section>
   <section class="card chatc"><div class="chead" id="chead"></div><div class="msgs" id="msgs"></div>
    <div class="chatask"><div id="dev-status" class="devstatus"></div><div class="qrow" id="qrow">${qrowHtml(Q)}</div></div></section></div>`;
  mountMiniOrb(pg.querySelector('.chatc'));
  $('#cq').oninput=e=>{S.cq=e.target.value;drawConvs()};
  (S.hist?Promise.resolve():loadHist()).then(()=>{drawConvs();drawMsgs();drawSide();drawDevelopment()});
};
// Sohbet altındaki kısayollar: günlük 4 iş. Geliştirme düğmeleri yalnız geliştirme modu açıkken görünür; kalanlar "•••" menüsündedir.
function chatShortcuts(){const dev=((S.snap||{}).development)||{};
  const base=[['folder','Dosyalarım','dosyalarımı göster'],['eye','Özetle','bu konuşmayı kısaca özetle'],['grid','Tabloya Dönüştür','son cevabını tablo olarak ver'],['file','Dosya Olarak Al','çıktı al'],['lang','Türkçeye Çevir','önceki metni Türkçeye çevir']];
  return dev.enabled?base.concat([['eye','Taslak','taslağı göster'],['check','Uygula','değişiklikleri uygula'],['refresh','Geri Al','son geliştirmeyi geri al'],['msg','Normal Sohbet','normal sohbete dön']]):base}
function chatRun(c){return c==='geliştirme modunu aç'?ACT.devopen():c==='normal sohbete dön'?ACT.devclose():say(c)}
function qrowHtml(Q){return Q.map(([i,t,s])=>`<button class="qchip" ${s==='normal sohbete dön'?'data-act="devclose"':`data-say="${esc(s)}"`}>${ic(i)}${t}</button>`).join('')}
function drawQrow(){const el=$('#qrow');if(!el)return;const h=qrowHtml(chatShortcuts());if(el._h!==h){el._h=h;el.innerHTML=h}}
function drawDevelopment(){drawQrow();const el=$('#dev-status');if(!el)return;const st=(S.snap||{}).development||{};el.innerHTML=st.enabled?`<b>Şifre Korumalı Geliştirme Modu · ${st.unlocked?'Açık':'Kilitli'}</b><span>${(st.draft_files||[]).length} dosya taslağı · ${st.visual_count||0} görsel · ${st.reference_count||0} referans</span><button class="btn sm" data-act="attach">${ic('clip')} Görsel / Dosya</button><button class="btn sm" data-say="son görseli göster">Son Görsel</button><span>Her değişiklik için son onayın gerekir.</span><button class="btn sm" data-act="devexport">Dosyaları Al</button><button class="btn sm" data-act="devpassword">Şifre</button>`:'';}
function drawConvs(){const el=$('#clist');if(!el)return;const ds=days(),q=(S.cq||'').toLowerCase();
  const items=ds.filter(([d,rs])=>!q||rs.some(r=>(r.text||'').toLowerCase().includes(q))).slice(0,S.allConv?400:40);
  if(!items.some(([d])=>d===ymd(new Date())))items.unshift([ymd(new Date()),[]]);
  el.innerHTML=items.map(([d,rs])=>{const first=rs.find(r=>r.role==='user'),last=rs.slice().reverse().find(r=>r.role==='assistant');const t=d===ymd(new Date())&&!rs.length?'Bugün':convTitle(first&&first.text);const [i,c]=convIcon(first&&first.text);
    return `<div class="convwrap"><button class="conv ${S.day===d?'on':''}" data-act="day" data-d="${d}"><span class="ib sm ${c}" style="width:40px;height:40px;font-size:19px">${ic(i)}</span><span style="min-width:0"><b>${esc(t)}</b><small>${esc(last?last.text.replace(/[*#`|_>]+/g,'').replace(/^\s*[-•]\s*/gm,'').replace(/\s+/g,' ').trim().slice(0,60):rs.length?rs.length+' mesaj':'Yeni konuşma')}</small></span><time>${dayLabel(d,(rs[rs.length-1]||{}).ts)}</time></button>${rs.length?`<button class="convdelete" data-act="convdelete" data-d="${d}" title="Bu sohbeti sil" aria-label="${esc(t)} sohbetini sil">${ic('trash')}</button>`:''}</div>`}).join('')||'<div class="empty">Konuşma yok.</div>'}
ACT.convdelete=async el=>{
  const day=el.dataset.d,user=((S.snap||{}).user||{}).name;
  if(!await ask(`${day.split('-').reverse().join('.')} tarihindeki sohbet silinsin mi? Bu güne ait tüm mesajlar kaldırılacak.`))return;
  if(user!==((S.snap||{}).user||{}).name)return;
  try{await api('history_delete_conversation',day);if(user!==((S.snap||{}).user||{}).name)return;
    if(day===ymd(new Date())){S.live=[];S.chat=[];S.waiting=false;S.since=0}
    await loadHist();if(S.day===day){S.day=ymd(new Date());S.since=0}
    drawConvs();drawMsgs();drawSide();toast('Seçilen sohbet silindi.');
  }catch(e){toast('Sohbet silinemedi: '+e.message,'bad')}
};
ACT.day=el=>{S.day=el.dataset.d;S.since=0;drawConvs();drawMsgs();drawSide()};
ACT.newchat=async()=>{await tryApi('chat_reset');S.day=ymd(new Date());S.since=Date.now()/1000;S.live=[];drawConvs();drawMsgs();drawSide();toast('Yeni sohbet başladı.')};
ACT.csearch=async ()=>{const q=await askText('Sohbetlerde ara:',S.cq||'');if(q!==null){S.cq=q;drawConvs()}};
ACT.allconv=()=>{S.allConv=!S.allConv;render()};
function curMsgs(){
  const today=ymd(new Date());let rows=(S.hist||[]).filter(r=>(r.ts||'').slice(0,10)===S.day).map(r=>({role:r.role,text:r.text,ts:Date.parse(r.ts.replace(' ','T'))/1000,src:r.source}));
  if(S.day===today){const seen=new Set(rows.map(r=>r.role+'|'+r.text));S.live.forEach(m=>{const k=m.role+'|'+m.text;if(!seen.has(k)){rows.push(m);seen.add(k)}})}
  if(S.since)rows=rows.filter(r=>r.ts>=S.since);
  return rows.sort((a,b)=>a.ts-b.ts);
}
function chatImageHtml(label,url){
  if(!/^https:\/\//i.test(url)&&!/^data:image\/(?:png|jpeg|webp|gif|svg\+xml);base64,[A-Za-z0-9+/=]+$/.test(url))return esc(label);
  return `<figure class="chatimage"><img src="${esc(url)}" alt="${esc(label)}" loading="lazy"><figcaption>${esc(label)}</figcaption></figure>`;
}
function md(t){
  let s=esc(t||'');const blocks=[];s=s.replace(/```(\w*)\n?([\s\S]*?)```/g,(m,l,c)=>{blocks.push(`<pre><code>${c}</code></pre>`);return `\u0000${blocks.length-1}\u0000`});
  s=s.replace(/!\[([^\]\n]*)\]\(([^\s)]+)\)/g,(m,label,url)=>{blocks.push(chatImageHtml(label.replace(/&amp;/g,'&'),url.replace(/&amp;/g,'&')));return `\u0000${blocks.length-1}\u0000`});
  const lines=s.split('\n'),out=[];let list=null;
  const flush=()=>{if(list){out.push(`<${list.t}>${list.i.map(x=>`<li>${x}</li>`).join('')}</${list.t}>`);list=null}};
  for(let index=0;index<lines.length;index++){let ln=lines[index];const ul=ln.match(/^\s*[-•*]\s+(.*)/),ol=ln.match(/^\s*\d+[.)]\s+(.*)/);
    if(ul||ol){const t=ul?'ul':'ol';if(!list||list.t!==t){flush();list={t,i:[]}}list.i.push(inl(ul?ul[1]:ol[1]));continue}
    flush();if(/^\s*\|.*\|\s*$/.test(ln)){if(/^\s*\|[\s:|-]+\|\s*$/.test(ln))continue;const tag=/^\s*\|[\s:|-]+\|\s*$/.test(lines[index+1]||'')?'th':'td';out.push('<tr>'+ln.trim().slice(1,-1).split('|').map(c=>`<${tag}${tag==='th'?' scope="col"':''}>${inl(c.trim())}</${tag}>`).join('')+'</tr>');continue}
    const h=ln.match(/^#{1,4}\s+(.*)/);out.push(h?`<p><b>${inl(h[1])}</b></p>`:ln.trim()?`<p>${inl(ln)}</p>`:'')}
  flush();let html=out.join('').replace(/(<tr>.*?<\/tr>)+/g,m=>{const header=m.startsWith('<tr><th')?m.slice(0,m.indexOf('</tr>')+5):'';return `<div class="chat-table" tabindex="0" role="region" aria-label="Tablo; yatay kaydırılabilir"><table>${header?'<thead>'+header+'</thead>':''}<tbody>${m.slice(header.length)}</tbody></table></div>`});
  return html.replace(/\u0000(\d+)\u0000/g,(m,i)=>blocks[+i]);
}
function inl(s){return s.replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/`([^`]+)`/g,'<code>$1</code>')}
function mathGroup(s,start){if(s[start]!=='{')return null;let depth=0;for(let i=start;i<s.length;i++){if(s[i]==='{')depth++;if(s[i]==='}'&&--depth===0)return {text:s.slice(start+1,i),end:i+1};if(depth>20)return null}return null}
function mathBasic(x,depth=0){
 let s=String(x);if(depth>12)return s;
 s=s.replace(/\\(?:left|right)\b/g,'').replace(/\\(?:,|;|!|quad\b|qquad\b)/g,' ');
 const command=/\\(d?frac|tfrac|sqrt)\s*/g;let out='',last=0,match;
 while((match=command.exec(s))){const first=mathGroup(s,command.lastIndex),second=first&&match[1]!=='sqrt'?mathGroup(s,first.end):null;if(!first||(match[1]!=='sqrt'&&!second))continue;
  out+=s.slice(last,match.index)+(match[1]==='sqrt'?`√<span class="root">${mathBasic(first.text,depth+1)}</span>`:`<span class="frac"><span>${mathBasic(first.text,depth+1)}</span><span>${mathBasic(second.text,depth+1)}</span></span>`);last=second?second.end:first.end;command.lastIndex=last;
 }
 s=out+s.slice(last);
 s=s.replace(/\\(?:text|mathrm)\{([^{}]+)\}/g,'$1').replace(/\^\{([^{}]+)\}/g,'<sup>$1</sup>').replace(/_\{([^{}]+)\}/g,'<sub>$1</sub>').replace(/\^([0-9A-Za-z]+)/g,'<sup>$1</sup>').replace(/_([0-9A-Za-z]+)/g,'<sub>$1</sub>');
 return s.replace(/\\times\b/g,'×').replace(/\\div\b/g,'÷').replace(/\\neq\b/g,'≠').replace(/\\leq?\b/g,'≤').replace(/\\geq?\b/g,'≥').replace(/\\pi\b/g,'π').replace(/\\sum\b/g,'∑').replace(/\\int\b/g,'∫').replace(/\\cdot\b/g,'·').replace(/\\pm\b/g,'±');
}
function mdMath(t){let h=md(t||'');return h.replace(/\\\((.*?)\\\)/g,(m,x)=>`<span class="math">${mathBasic(x)}</span>`).replace(/\$\$([^$]+)\$\$/g,(m,x)=>`<div class="math block">${mathBasic(x)}</div>`).replace(/\$([^$\n]+)\$/g,(m,x)=>`<span class="math">${mathBasic(x)}</span>`)}
// SPEECH HIGHLIGHT START
// §8: Görünür "şimdi sesli anlatılan sonuç" izi. Vurguyu yalnız üreticinin gerçek
// oynatma olayı (playback_started) koyar; kuyruk, sentez veya WAV hazırlığı konuşma
// değildir. Geç kalan bir stage daha yeni konuşmayı söndüremez, çünkü konuşma durumu
// olayın akış sırasından değil oynatmanın kendisinden gelir. Pencere öne alınmaz.
function speechEvent(m){
  let id=null;try{id=JSON.parse(m.x||'{}')}catch(e){}
  if(!id||typeof id!=='object'||String(m.t||'')!=='playback_started')return;
  S.speech=id;applySpeechHighlight();
}
function speechStateEvent(state){if(state==='speaking'||!S.speech)return;S.speech=null;applySpeechHighlight()}
function speechClassFor(m){return S.speech&&m&&m.rid&&S.speech.turn_id===m.rid?' saying':''}
function taskGoalId(item){const area=String((item||{}).area||'');const match=/^Görev (\S+)/.exec(area);return match?match[1]:''}
function speechTaskClass(goal){const id=S.speech||{};return goal&&(id.goal_id===goal||id.event_id===goal)?' saying':''}
function applySpeechHighlight(){
  const id=S.speech||{};
  $$('.m.a').forEach(el=>el.classList.toggle('saying',!!id.turn_id&&el.dataset.rid===id.turn_id));
  // Görev kartı yalnız kendi işi seslendirildiğinde işaretlenir: kartın kimliği
  // çizimdeki aktivite kaydından gelir, seslendirmenin sonuç kimliğiyle (iş/hedef)
  // karşılaştırılır. Kimliksiz seslendirme hiçbir kartı boyamaz.
  const task=$('#cside .task');if(task)task.classList.toggle('saying',!!task.dataset.goal&&(task.dataset.goal===id.goal_id||task.dataset.goal===id.event_id));
}
// SPEECH HIGHLIGHT END
function msgHtml(m){
  if(m.role==='files')return filesHtml();
  if(m.role==='agenda')return agendaHtml();
  if(m.role==='user'){const fm=msgFiles(m.text);
    const body=fm.paths.length?`${esc(fm.rest.replace(/^dosyalarını |^dosyasını |^görselini |^görselindeki /,'').replace(/^./,c=>c.toUpperCase()))}${fm.paths.map(f=>`<div class="fchip"><span class="fi ${catOf(f)}">${extOf(f).toUpperCase().slice(0,4)}</span><span><b>${esc(f.split(/[\\/]/).pop())}</b><small>${esc(extOf(f).toUpperCase())}</small></span></div>`).join('')}`:md(m.text);
    const heard=m.src==='ses'?`<div class="heard">${ic('mic')}Anladığım</div>`:'';
    return `<div class="m u"><div class="bb">${heard}${body}<time class="t">${hm(m.ts)}</time></div><span class="av">${esc(((S.snap||{}).user||{}).name?.[0]||'S')}</span></div>`}
  if(m.role==='system')return `<div class="m s">${esc(m.text)}</div>`;
  if(m.role==='step')return stepsHtml(S.steps[m.rid]);
  return `<div class="m a${speechClassFor(m)}" data-rid="${esc(m.rid||'')}"><span class="orb">${ic('mic')}</span><div><div class="nm">${esc(((S.snap||{}).aname||'JARVIS').toUpperCase())}<time>${hm(m.ts)}</time></div><div class="bb">${md(m.text)}</div></div></div>`;
}
function stepsHtml(card){
  const items=card?[...card.items.values()]:[];if(!items.length)return '';
  const mark={working:'…',done:'✓',error:'✗'};
  return `<div class="m stepcard"><div class="steps">${items.map(i=>`<div class="step ${esc(i.s)}"><span class="sm">${mark[i.s]||'•'}</span><span>${esc(i.t)}${i.s==='error'&&i.d?`<small>${esc(i.d)}</small>`:''}</span></div>`).join('')}</div></div>`+taskSummaryCardHtml(card);
}
// ---- Sohbet köşe orb'u (APEX "mini" kipi): başlıkta küçük orb Jarvis'in durumunu gösterir; cevap gelirken hangi modelin yanıtladığı yanında bir an çiçek gibi açılıp kaybolur.
// Yalnız yerel çizim (model/ağ yok); veri mevcut 'step' olaylarındaki model satırlarından (m1, m2…) gelir. Sakin modda kare atlar.
const MO_CHIP={gemini:'#00e5ff',groq:'#f5a623',ollama:'#34d399',claude:'#ff7ac6',gpt:'#7f9bb3'};
function miniBloom(text,status){const c=document.querySelector('.mo-chip');if(!c)return;const t=String(text||'').replace(/^(Cevabı veren|Yanıtlayan|Model)\s*[:·-]\s*/i,'').trim()||'Model';
  const key=Object.keys(MO_CHIP).find(k=>t.toLowerCase().includes(k)),col=status==='error'?'#ff8a6a':(MO_CHIP[key]||'#00e5ff');
  c.textContent=t.length>34?t.slice(0,33)+'…':t;c.style.setProperty('--c',col);c.classList.add('on');clearTimeout(c._t);c._t=setTimeout(()=>c.classList.remove('on'),4200);
  const o=document.querySelector('.mo-orb2');if(o){o.classList.add('bloom');setTimeout(()=>o.classList.remove('bloom'),900)}}
function mountMiniOrb(card){
  if(!card||card.querySelector('.mo-mini'))return;
  const box=document.createElement('div');box.className='mo-mini';box.setAttribute('aria-hidden','true');
  box.innerHTML='<span class="mo-chip"></span><div class="mo-orb2"><div class="apex-orb-wrap" data-state="idle">'+menuOrbSvg().replace('width="900" height="520" viewBox="0 0 900 520"','width="54" height="54" viewBox="260 70 380 380"')+'</div><canvas width="108" height="108"></canvas></div>';
  card.appendChild(box);
  const cv=box.querySelector('canvas'),wrap=box.querySelector('.apex-orb-wrap'),N=170,dir=[],ph=[],sp=[],br=[];
  for(let i=0;i<N;i++){const u=Math.random()*2-1,a=Math.random()*6.283,r=Math.sqrt(1-u*u);dir.push([Math.cos(a)*r,u,Math.sin(a)*r]);ph.push(Math.random()*6.283);sp.push(.7+Math.random()*1.7);br.push(.35+Math.pow(Math.random(),.45)*.65)}
  const spr=document.createElement('canvas');spr.width=spr.height=16;{const g=spr.getContext('2d'),gr=g.createRadialGradient(8,8,0,8,8,8);gr.addColorStop(0,'rgba(200,247,255,1)');gr.addColorStop(.4,'rgba(0,229,255,.6)');gr.addColorStop(1,'rgba(0,229,255,0)');g.fillStyle=gr;g.fillRect(0,0,16,16)}
  let last=performance.now(),Rt=5,spin=0,cr=0,sk=false;
  const frame=now=>{if(!cv.isConnected)return;const dt0=Math.max(0,Math.min(.05,(now-last)/1000));last=now;
    if(UI_CALM()){sk=!sk;if(sk){cr+=dt0;requestAnimationFrame(frame);return}}
    const dt=Math.min(dt0+cr,.1);cr=0;const t=now/1000,o=S.orb,st=['listening','thinking','speaking'].includes(o)?o:'idle';wrap.dataset.state=st;
    const tgt=st==='idle'?4.6:st==='speaking'?9.4:11.8;Rt+=(tgt-Rt)*.05*Math.min(3,dt*60);spin+=dt*.5;
    const g=cv.getContext('2d');g.clearRect(0,0,108,108);g.globalCompositeOperation='lighter';const ca=Math.cos(spin),sa=Math.sin(spin),bub=st==='idle'?1.3:1.7,wav=st==='speaking'?3.8:(st==='idle'?0:.9);
    for(let i=0;i<N;i++){const d=dir[i],r=Math.max(0,br[i]*Rt*2+Math.sin(t*sp[i]+ph[i])*bub*2+(st==='speaking'?Math.sin(br[i]*5.5-t*5)*wav*2:Math.sin(br[i]*3-t*1.7)*wav*2)),x=d[0]*ca+d[2]*sa,z=-d[0]*sa+d[2]*ca,dd=(z+1)/2;g.globalAlpha=.25+.6*dd;const sz=(2.2+2*dd);g.drawImage(spr,54+x*r-sz/2,54+d[1]*r-sz/2,sz,sz)}
    g.globalAlpha=1;g.globalCompositeOperation='source-over';requestAnimationFrame(frame)};
  requestAnimationFrame(frame);
}
// TASK SUMMARY START
function taskSummaryText(text){
  if(typeof text!=='string')return '';
  text=text.replace(/\b(Bearer|Basic)\s+\S+/gi,'$1 [gizlendi]')
    .replace(/(^|[^\p{L}\p{N}_])([\p{L}\p{N}_-]*(?:token|secret|password|passwd|parola|belirte[çc]|[şŞsS][iİıI]fre|api[_ -]?key|anahtar)[\p{L}\p{N}_-]*)\s*[:=]\s*\S+/giu,'$1$2=[gizlendi]')
    .replace(/\b(?:AIza|sk-|gsk_|ghp_|github_pat_|xox[baprs]-|AKIA|ASIA)[\w-]+/g,'[gizlendi]')
    .replace(/[\w.+-]+@[\w.-]+\.[a-z]{2,}/gi,'[e-posta gizlendi]')
    .replace(/\bTR(?:\s*\d){24}\b/gi,'[IBAN gizlendi]')
    .replace(/\+?\d[\d ()-]{8,}\d/g,'[numara gizlendi]');
  return Array.from(text.replace(/\s+/g,' ').trim()).slice(0,200).join('');
}
function taskSummaryData(job){
  const empty=()=>({title:'',done:[],left:[],stopped:false,verified:false});
  if(!job||Array.isArray(job)||typeof job!=='object')return empty();
  const title=job.title===undefined?job.request:job.title,steps=job.steps;
  if(typeof title!=='string'||!title.trim()||typeof job.state!=='string'||!Array.isArray(steps))return empty();
  const done=[],left=[];
  for(const step of steps){
    if(!step||typeof step!=='object')return empty();
    const text=step.text===undefined?step.title:step.text;
    if(typeof text!=='string'||!text.trim()||typeof step.state!=='string')return empty();
    (['done','completed'].includes(step.state)?done:left).push(taskSummaryText(text));
  }
  const stopped=['cancelled','stopped'].includes(job.state)||job.stopped===true;
  const verified=steps.length>0&&!left.length&&!stopped&&['done','completed'].includes(job.state)&&(job.verified===true||steps.every(x=>x.verified===true));
  return {title:taskSummaryText(title),done,left,stopped,verified};
}
function taskSummaryHtml(job){
  const data=taskSummaryData(job);if(!data.title)return '';
  const list=(label,items)=>items.length?'<div><b>'+label+'</b><ul>'+items.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul></div>':'';
  return '<section class="task-summary" aria-label="Görev sonucu"><strong>'+esc(data.title)+'</strong>'+list('Yapılan',data.done)+list('Yarım kalan',data.left)+'<small>'+(data.verified?'Doğrulandı':'Doğrulama bilgisi yok')+'</small></section>';
}
function taskSummaryOwner(){return (((S.snap||{}).user||{}).slug)||''}
function taskSummaryTrack(card,rid){
  if(card._summaryOwner===undefined)card._summaryOwner=taskSummaryOwner();
  card._summaryRid=rid;
  if(card._summaryReady===undefined)card._summaryReady=false;
}
function taskSummaryActiveRid(){
  const owner=taskSummaryOwner();if(!owner)return null;
  const ids=Object.keys(S.steps).filter(rid=>rid!=='serbest'&&S.steps[rid]._summaryOwner===owner&&!S.steps[rid]._summaryReady);
  const last=[...(S.live||[])].reverse().find(x=>x.role==='user'&&x.rid);
  return last?(ids.includes(last.rid)?last.rid:null):(ids.length===1?ids[0]:null);
}
function taskSummaryFinish(rid,stopped){
  const card=rid&&S.steps[rid],owner=taskSummaryOwner();
  if(!card||!owner||card._summaryOwner!==owner||(card._summaryReady&&stopped!==true))return;
  card._summaryReady=true;card._summaryStopped=stopped===true;
  if(S.page==='chat'&&typeof drawMsgs==='function')drawMsgs();
}
function taskSummaryEvent(m){
  const owner=taskSummaryOwner();
  if(!m||!owner||(m.user&&m.user!==owner))return;
  if(m.rid&&((m.k==='state'&&m.t==='idle')||m.k==='assistant'))taskSummaryFinish(m.rid,false);
}
function taskSummaryCardHtml(card){
  if(!card||!card._summaryReady||!taskSummaryOwner()||card._summaryOwner!==taskSummaryOwner()||!(card.items instanceof Map))return '';
  return taskSummaryHtml({title:card._summaryStopped?'Durdurulan görev':'Görev sonucu',state:card._summaryStopped?'stopped':'done',
    steps:[...card.items.values()].map(x=>({text:x.t,state:x.s==='error'?'failed':x.s})),verified:false});
}
// TASK SUMMARY END
function onStep(m){
  const [status,id,detail]=String(m.x||'').split('|');const rid=m.rid||'serbest';const ts=m.ts||Date.now()/1000;
  let card=S.steps[rid];if(!card){card=S.steps[rid]={ts,items:new Map()};S.live.push({role:'step',rid,text:'adım:'+rid,ts});S.live=S.live.slice(-300)}
  card.items.set(id||String(card.items.size),{t:String(m.t||''),s:status||'working',d:detail||''});
  taskSummaryTrack(card,rid);
  const keys=Object.keys(S.steps);if(keys.length>60)keys.slice(0,keys.length-60).forEach(k=>delete S.steps[k]);
  if(/ses(i)? (kapatıl|açıl)/i.test(String(m.t||''))&&status!=='working')loadPcMute();
  if(/^m\d+$/.test(id||''))miniBloom(m.t,status);
  if(S.page==='chat')drawMsgs();
}
// Mesaj başındaki tırnaklı dosya yolları ('"a.pdf" "b.xlsx" talimat') ve kalan talimat
function msgFiles(t){const paths=[];let rest=t||'',x;while((x=rest.match(/^"([^"]*[\\/][^"]*\.\w{2,5})"\s+/))){paths.push(x[1]);rest=rest.slice(x[0].length)}return {paths,rest}}
const extOf=p=>(p.split('.').pop()||'').toLowerCase();
const catOf=p=>{const e=extOf(p);return e==='pdf'?'pdf':/^docx?|odt|rtf$/.test(e)?'word':/^xlsx?|csv|ods$/.test(e)?'excel':/^(png|jpe?g|webp|bmp|gif|heic)$/.test(e)?'image':'other'};
function stripHtml(){const A=window.JarvisActivityStrip;if(!A)return'';const st=A.stripState(S.snap,S.steps);if(!st.visible)return'';const rid=Object.keys(S.steps).pop();const it=A.activityItems(S.steps,rid).map(x=>`<small class="as-${x.status}">${esc(x.text)}${x.detail?' · '+esc(x.detail):''}</small>`).join('');return `<div class="actstrip"><b>${esc(st.label)}</b>${it}${st.stoppable?'<button data-act="stoptask" title="Durdur">Durdur</button>':''}</div>`}
ACT.stoptask=async()=>{const rid=typeof taskSummaryActiveRid==='function'?taskSummaryActiveRid():null;const r=await tryApi('stop_task');if(!r)return toast('Durdurma bu sürümde yok.','bad');if(r.stopped===true&&typeof taskSummaryFinish==='function')taskSummaryFinish(rid,true);toast(r.msg||'Görev durduruldu.')};
function drawMsgs(){
  const el=$('#msgs');if(!el)return;const ms=curMsgs(),first=ms.find(m=>m.role==='user');
  const ch=$('#chead');if(ch){const [i,c]=convIcon(first&&first.text);const files=new Set(ms.flatMap(m=>m.role==='user'?msgFiles(m.text).paths:[]));
    ch.innerHTML=`<span class="ib ${c}" style="width:52px;height:52px;font-size:26px">${ic(i)}</span><div><b>${esc(first?convTitle(first.text):'Yeni Sohbet')}</b><small>${files.size?files.size+' dosya • ':''}${ms.length} mesaj • ${S.day===ymd(new Date())?'Bugün':S.day.split('-').reverse().join('.')}</small></div>
     <div class="acts"><button data-act="ccopy" title="Kopyala">${ic('up')}</button><button data-act="cmore" title="Diğer">•••</button></div>`}
  el.innerHTML=(ms.length?ms.map(msgHtml).join(''):`<div class="m s" style="margin:auto">Konuşmaya başla: yaz ya da mikrofona dokun.</div>`)+(S.waiting&&S.day===ymd(new Date())?`<div class="m a"><span class="orb">${ic('mic')}</span><div class="bb"><span class="typing"><i></i><i></i><i></i></span></div></div>`:'')+stripHtml();
  el.scrollTop=el.scrollHeight;
}
ACT.ccopy=async()=>{const t=curMsgs().filter(m=>m.role!=='step'&&m.role!=='files'&&m.role!=='agenda').map(m=>`${m.role==='user'?'Sen':'Jarvis'}: ${m.text}`).join('\n\n');try{await navigator.clipboard.writeText(t);toast('Konuşma panoya kopyalandı.')}catch(e){toast('Kopyalanamadı.','bad')}};
ACT.cmore=el=>{const r=el.getBoundingClientRect(),x=r.left-150,y=r.bottom+6;
  const sub=(icon,label,list)=>[icon,label+'  ›',()=>menu(x,y,[['arrow','‹  Geri',()=>ACT.cmore(el)],'-',...list])];
  menu(x,y,[['copy','Konuşmayı kopyala',ACT.ccopy],['refresh','Yenile',async()=>{await loadHist();drawConvs();drawMsgs()}],'-',
    sub('monitor','Ekran ve görsel',[['monitor','Ekranı analiz et',()=>say('ekranı analiz et')],['eye','Ekran görüntüsü al',()=>ACT.capture()],['image','Görselden metin çıkar',()=>pickUpload('metin','image/*')],['image','Görsel yükle ve analiz et',()=>pickUpload('gorsel','image/*')]]),
    sub('bolt','Diğer komutlar',[['lang','İngilizceye çevir',()=>say('önceki metni İngilizceye çevir')],['bolt','Model yetenekleri',()=>say('router durumu')],['grid','Görev durumu',()=>say('görev durumu')],['check','PC / Ses kontrolü',()=>say('pc ses kontrolü')],['term','Şifre korumalı geliştirme modu',()=>chatRun('geliştirme modunu aç')]]),
    '-',['trash','Bu sohbeti sil',()=>ACT.convdelete({dataset:{d:S.day}})],['trash','Tüm geçmişi sil',async ()=>{if(await ask('Tüm konuşma geçmişi silinsin mi?')){await api('history_clear');S.hist=[];S.live=[];drawConvs();drawMsgs()}}]])};
function drawSide(){
  const el=$('#cside');if(!el)return;const sn=S.snap||{};
  const run=(sn.activity||[]).slice().reverse().find(a=>a.status==='start'),last=(sn.activity||[]).slice().reverse().find(a=>a.status!=='start'&&!/Aktivite ekranı/.test(a.text));
  const ms=curMsgs();const fl=[...new Set(ms.flatMap(m=>m.role==='user'?msgFiles(m.text).paths:[]))].map(p=>({path:p,name:p.split(/[\\/]/).pop(),cat:catOf(p)}));
  const files=fl.length?fl:(S.files&&S.files.files||[]).slice(0,3);
  const goal=taskGoalId(run||last);   // kartın kendi iş kimliği; aktivite kaydından gelir
  el.innerHTML=`<section class="card"><div class="ch"><span class="ct" style="display:flex;gap:8px;align-items:center"><span class="ib sm purple">${ic('file')}</span>Mevcut Görev</span></div>
     <div class="task${speechTaskClass(goal)}" data-goal="${esc(goal)}"><span class="ib ${run?'orange':'navy'}" style="width:50px;height:50px">${ic(run?'activity':'check')}</span><div style="min-width:0"><b>${esc(run?run.text.replace(/^Komut alındı:\s*/,'').slice(0,40):last?(last.area||'Son işlem'):'Görev yok')}</b><small>${files.length} dosya</small>
      <div class="okk" style="${run?'color:var(--orange)':''}">${ic(run?'clock':'check')} ${run?'Çalışıyor…':last?(last.status==='error'?'Başarısız':'Tamamlandı'):'Hazır'}</div></div></div></section>
   <section class="card"><div class="ch"><span class="ct">Dosyalar</span><button class="link" data-go="files">Tümünü Gör</button></div>
     ${files.length?files.map(f=>`<div class="frow" data-act="fpick" data-p="${esc(f.path)}"><span class="fi ${f.cat}">${(extOf(f.path)||'?').toUpperCase().slice(0,3)}</span><span>${esc(f.name)}</span><small>${f.size?fmtSize(f.size):''}</small></div>`).join(''):'<div class="empty">Dosya yok.</div>'}</section>
   <section class="card"><div class="ch"><span class="ct">Hızlı İşlemler</span></div><div class="qgrid">
     ${[['eye','Özeti Çıkar','bu konuşmayı kısaca özetle'],['file','Rapor Oluştur','çıktı al'],['layers','Karşılaştır','#prefill:Karşılaştır: '],['grid','Tabloya Dönüştür','son cevabını tablo olarak ver']].map(([i,t,c])=>c.startsWith('#prefill:')?`<button class="qbtn" data-act="prefill" data-t="${esc(c.slice(9))}">${ic(i)}${t}</button>`:`<button class="qbtn" data-say="${esc(c)}">${ic(i)}${t}</button>`).join('')}</div></section>`;
}
ACT.prefill=el=>{const i=$('.chatask input')||$('.ask input');if(i){i.value=el.dataset.t+(el.dataset.t.endsWith(' ')?'':' ');i.focus()}};
ACT.fpick=el=>{S.fsel=el.dataset.p;go('files')};

// ======================================================================= DOSYALAR
// "Dosyalarım" isteği tarayıcıda cevaplanır (model/Gemini çağrısı yok): son yüklenen dosyalar kartlarla sohbete düşer.
async function showFileCards(text){
  if(S.page!=='chat'){S.day=ymd(new Date());go('chat')}
  const now=Date.now()/1000;S.day=ymd(new Date());
  S.live.push({role:'user',text,ts:now,mine:true});drawMsgs();
  await loadFiles(true);
  S.live.push({role:'files',text:'dosya kartları '+now,ts:now+.001});S.live=S.live.slice(-300);drawMsgs();
}
async function showAgendaCard(text){
  if(S.page!=='chat'){S.day=ymd(new Date());go('chat')}
  try{await refresh()}catch(e){}
  const now=Date.now()/1000;S.day=ymd(new Date());
  S.live.push({role:'user',text,ts:now,mine:true});S.live.push({role:'agenda',text:'takvim kartı '+now,ts:now+.001});S.live=S.live.slice(-300);drawMsgs();
}
function agendaHtml(){
  const sn=S.snap||{},t0=ymd(new Date()),ev=(sn.all_events||[]).filter(e=>(e.when||'').slice(0,10)>=t0).sort((a,b)=>a.when.localeCompare(b.when)).slice(0,5),tk=(sn.tasks||[]).filter(t=>!t.done).slice(0,4);
  const row=(b,sm)=>`<div class="fcard"><span class="fcn"><b>${esc(b)}</b>${sm?`<small>${esc(sm)}</small>`:''}</span></div>`;
  const body=ev.length||tk.length?`<p>Yaklaşan işlerin bunlar.</p><div class="fcards">${ev.map(e=>row(e.title,whenTxt(e.when))).join('')}${tk.map(t=>row(t.text,t.when?whenTxt(t.when):'Görev')).join('')}</div>`:'<p>Yaklaşan etkinlik ya da açık görev yok.</p>';
  return `<div class="m a"><span class="orb">${ic('mic')}</span><div><div class="nm">${esc(((sn.aname)||'JARVIS').toUpperCase())}</div><div class="bb">${body}<div class="acts" style="margin-top:10px;display:flex;gap:8px"><button class="ac b" data-act="tool" data-k="takvim">Takvimi aç</button><button class="ac o" data-act="homenote">Not ekle</button></div></div></div></div>`;
}
function filesHtml(){
  const all=((S.files&&S.files.files)||[]).slice().sort((a,b)=>b.mtime-a.mtime),mine=all.filter(f=>f.mine),list=(mine.length?mine:all).slice(0,5);
  const body=list.length?`<p>Son dosyaların bunlar. Hangisiyle ne yapalım?</p><div class="fcards">${list.map(f=>`<div class="fcard"><span class="fi ${f.cat}">${esc(f.ext.toUpperCase().slice(0,3))}</span><span class="fcn"><b>${esc(f.name)}</b><small>${fmtSize(f.size)} · ${fmtDate(f.mtime)}</small></span><span class="acts">${(FACTS[f.cat]||FACTS.other).slice(0,3).map(([a,t,cl])=>`<button class="ac ${cl}" data-act="fdo" data-p="${esc(f.path)}" data-a="${a}">${esc(t)}</button>`).join('')}</span></div>`).join('')}</div>`
    :'<p>Henüz yüklenmiş dosya yok. Soldaki + ile dosya ekleyebilirsin.</p>';
  return `<div class="m a"><span class="orb">${ic('mic')}</span><div><div class="nm">${esc(((S.snap||{}).aname||'JARVIS').toUpperCase())}</div><div class="bb">${body}</div></div></div>`;
}
async function loadFiles(force=false){S.files=await tryApi('files_list',force)||{files:[],counts:{}}}
const FCATS=[['mine','Yüklediklerim',''],['all','Tümü',''],['pdf','PDF','pdf'],['word','Word','word'],['excel','Excel','excel'],['image','Görsel','image'],['other','Diğer','other']];
const FACTS={pdf:[['analiz','Analiz Et','b'],['excel','PDF → Excel','g'],['cevir_tr','Türkçeye Çevir','b'],['ozet','Özetle','o'],['gorsellestir','Görselleştir','p']],word:[['cevir_tr','Türkçeye Çevir','b'],['cevir','İngilizceye Çevir','b'],['ozet','Özetle','o'],['pdf','Rapor','p'],['gorsellestir','Görselleştir','p']],
  excel:[['analiz','Analiz Et','b'],['cevir_tr','Türkçeye Çevir','b'],['ozet','Rapor Oluştur','p'],['gorsellestir','Görselleştir','p']],image:[['metin','Metne Çevir','p'],['gorsel','Analiz Et','b']],other:[['analiz','Analiz Et','b'],['cevir_tr','Türkçeye Çevir','b'],['ozet','Özetle','o'],['gorsellestir','Görselleştir','p']]};
PAGES.files=pg=>{
  pg.innerHTML=`<section class="card glow"><div class="ftool"><button class="btn pri" data-act="attach">${ic('up')} Dosya Yükle</button><button class="btn" data-act="fupdir" title="Bir klasördeki bütün dosyaları Jarvis'e yükler">${ic('up')} Klasör Yükle</button><button class="btn" data-act="fdir" title="Yüklediğin dosyaların durduğu klasörü (Belgeler › Jarvis Dosyaları) açar">${ic('folder')} Jarvis Klasörü</button>
     <div class="search">${ic('search')}<input id="fq" placeholder="Dosya adında ve belge içinde ara…" value="${esc(S.fq)}"></div><button class="btn" data-act="frefresh" title="Yenile">${ic('refresh')}</button><button class="btn" data-act="fhelp" title="Bu bölüm ne işe yarar, nasıl çalışır">${ic('help')} Nasıl çalışır?</button></div>
    <div class="chips" id="fchips"></div>
    <div class="fgrid"><section class="card" style="padding:14px"><div class="ct" style="margin-bottom:12px">Yapay Zekâ Araçları</div>
      ${[['green','scan','Kapsamlı Dosya Analizi','İçeriği analiz et, özetle, içgörü çıkar','analiz'],['red','file','PDF → Excel','Tablo verilerini Excel’e dönüştür','excel'],['blue','file','PDF → Word','PDF’i düzenlenebilir Word’e çevir','word'],['purple','chart','Rapor Oluştur','Dosyadan profesyonel rapor hazırla','pdf'],['orange','folder','Klasör Analizi','Klasördeki dosyaları özetle','#folder'],['cyan','chart','Klasör Envanteri','Çift/eski/boş dosyaları Excel raporuna yazar','envanter'],['purple','image','Görselden Metin','Resim ve taramaları metne çevir','metin']]
        .map(([c,i,t,s,a])=>`<button class="tool" data-act="ftool" data-a="${a}"><span class="ib ${c}">${ic(i)}</span><span><b>${t}</b><small>${s}</small></span><span class="chev">${ic('chev')}</span></button>`).join('')}</section>
     <section class="card filelist"><div class="fpager" id="fpg"></div><div class="filelist-scroll"><table class="ft"><thead><tr><th>Ad</th><th>Tür</th><th>Boyut</th><th>Tarih</th><th>Yapay Zekâ İşlemleri</th><th></th></tr></thead><tbody id="ftb"><tr><td colspan="6" class="empty">Dosyalar taranıyor…</td></tr></tbody></table></div></section>
     <section class="card detail" id="fdet"></section></div></section>`;
  $('#fq').oninput=e=>{S.fq=e.target.value;S.fpg=0;drawFiles();fContent()};
  (S.files?Promise.resolve():loadFiles()).then(drawFiles);
};
// Arama: dosya adı + belge içeriği (içerik isabetleri S.fhits'te, Jarvis'e yüklenen belgeler dizinlenir); eşleşme cümlesi satırın altında görünür.
function fFiltered(){const fs=(S.files&&S.files.files)||[],q=S.fq.toLowerCase(),hits=S.fq.trim().length>=3&&S.fhits?S.fhits:{},ok=f=>S.fcat==='all'||(S.fcat==='mine'?f.mine:f.cat===S.fcat);
  const base=fs.filter(f=>ok(f)&&(!q||f.name.toLowerCase().includes(q)||hits[f.path])),have=new Set(base.map(f=>f.path));return base.concat(Object.values(hits).filter(h=>!have.has(h.path)&&ok(h)))}
function fSnip(f){const h=S.fhits&&S.fhits[f.path];return h&&S.fq.trim().length>=3?`<small class="fsnip">${esc(h.snippet)}</small>`:''}
function fContent(){const q=S.fq.trim();clearTimeout(S.fcTimer);if(q.length<3){S.fhits=null;return}const who=((S.snap||{}).user||{}).slug||((S.snap||{}).user||{}).name;
  S.fcTimer=setTimeout(async()=>{const r=await tryApi('files_search',q);if(S.fq.trim()!==q||who!==(((S.snap||{}).user||{}).slug||((S.snap||{}).user||{}).name))return;S.fhits=Object.fromEntries((r||[]).map(h=>[h.path,h]));S.fpg=0;if($('#fq'))drawFiles()},350)}
function drawFiles(){
  const c=(S.files&&S.files.counts)||{};const ch=$('#fchips');if(!ch)return;
  ch.innerHTML=FCATS.map(([k,t,f])=>`<button class="chip ${S.fcat===k?'on':''}" data-act="fcat" data-k="${k}">${f?`<span class="fi ${f}" style="width:20px;height:20px">${t[0]}</span>`:''}${t} (${k==='mine'?((S.files&&S.files.files)||[]).filter(x=>x.mine).length:(c[k]||0)})</button>`).join('');
  const all=fFiltered().slice(0,200);let fs=all;const paint=()=>{
  $('#ftb').innerHTML=fs.length?fs.map(f=>`<tr class="${S.fsel===f.path?'on':''}" data-act="fsel" data-p="${esc(f.path)}"><td><div class="nm"><span class="fi ${f.cat}">${f.ext.toUpperCase().slice(0,3)}</span><span style="min-width:0"><span title="${esc(f.path)}">${esc(f.name)}</span><small class="floc${f.mine?' mine':''}">${esc(f.where||f.folder)}</small>${fSnip(f)}</span></div></td>
     <td>${esc({pdf:'PDF',word:'Word',excel:'Excel',image:'Görsel',other:f.ext.toUpperCase()}[f.cat])}</td><td>${fmtSize(f.size)}</td><td>${fmtDate(f.mtime)}</td>
     <td>${(FACTS[f.cat]||FACTS.other).map(([a,t,cl])=>`<button class="ac ${cl}" data-act="fdo" data-p="${esc(f.path)}" data-a="${a}">${t}</button>`).join('')}</td><td><button class="tool" style="all:unset;cursor:pointer;color:var(--mut)" data-act="fmenu" data-p="${esc(f.path)}">•••</button></td></tr>`).join('')
    :`<tr><td colspan="6" class="empty">${S.files?'Bu filtrede dosya yok.':'Dosyalar taranıyor…'}</td></tr>`;
  };paint();fPager(all,paint,x=>{fs=x});drawDetail();
}
function fPager(all,paint,setFs){const pg=$('#fpg');if(!pg)return;const box=$('.filelist-scroll'),r=box&&box.querySelector('#ftb tr[data-p]');
  if(!box||!r||!box.closest('.mn-pagedock')){pg.innerHTML='';return}
  const th=box.querySelector('thead'),n=Math.max(3,Math.floor((box.clientHeight-(th?th.offsetHeight:0))/Math.max(30,r.offsetHeight))),pages=Math.max(1,Math.ceil(all.length/n));
  S.fpg=Math.min(S.fpg||0,pages-1);setFs(all.slice(S.fpg*n,S.fpg*n+n));paint();
  pg.innerHTML=pages>1?`<button data-act="fpg" data-d="-1" ${S.fpg?'':'disabled'}>‹ Önceki</button><span>${S.fpg+1} / ${pages} · ${all.length} dosya</span><button data-act="fpg" data-d="1" ${S.fpg<pages-1?'':'disabled'}>Sonraki ›</button>`:`<span>${all.length} dosya</span>`}
ACT.fpg=el=>{S.fpg=Math.max(0,(S.fpg||0)+ +el.dataset.d);drawFiles()};
function drawDetail(){
  const el=$('#fdet');if(!el)return;const f=((S.files&&S.files.files)||[]).find(x=>x.path===S.fsel)||fFiltered()[0];
  if(!f){el.innerHTML='<div class="empty">Bir dosya seç.</div>';return}S.fsel=f.path;
  el.innerHTML=`<div class="fbig"><span class="doc"><span class="fi ${f.cat}">${f.ext.toUpperCase().slice(0,3)}</span></span><div style="min-width:0"><b style="word-break:break-all">${esc(f.name)}</b><div class="mut" style="font-size:12.5px">${f.ext.toUpperCase()} • ${fmtSize(f.size)}</div></div></div>
   <div class="tabs"><button class="${S.ftab==='genel'?'on':''}" data-act="ftab" data-t="genel">Genel Bakış</button><button class="${S.ftab==='ai'?'on':''}" data-act="ftab" data-t="ai">Yapay Zekâ Analizi</button></div>
   ${S.ftab==='genel'?`<div class="ct" style="font-size:15px;margin-bottom:10px">Dosya Bilgileri</div><div class="kv"><span>${ic('file')}Tür</span><b>${f.ext.toUpperCase()}</b><span>${ic('folder')}Boyut</span><b>${fmtSize(f.size)}</b>
     <span>${ic('clock')}Son Güncelleme</span><b>${fmtDate(f.mtime)} ${hm(f.mtime)}</b><span>${ic('folder')}Konum</span><b>${esc(f.where||f.folder)}</b></div>
     <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap"><button class="btn sm" data-act="fopen" data-p="${esc(f.path)}">${ic('eye')} Aç</button><button class="btn sm" data-act="freveal" data-p="${esc(f.path)}">${ic('folder')} Klasörde göster</button><button class="btn sm" data-act="fdo" data-a="telefon" data-p="${esc(f.path)}">${ic('phone')} Telefona</button></div>`
   :`<div style="display:flex;flex-direction:column;gap:8px">${Object.entries({analiz:'Kapsamlı analiz et',ozet:'Özetle',cevir:'İngilizceye çevir',excel:'Excel’e dönüştür',word:'Word’e dönüştür',pdf:'PDF’e dönüştür',...(f.cat==='image'?{gorsel:'Görseli analiz et',metin:'Metni çıkar'}:{gorsellestir:'Görselleştir'})})
       .map(([a,t])=>`<button class="tool" style="margin:0" data-act="fdo" data-a="${a}" data-p="${esc(f.path)}"><span class="ib sm blue">${ic('spark')}</span><b>${t}</b><span class="chev">${ic('chev')}</span></button>`).join('')}</div>`}
   <button class="aibig" data-act="fdo" data-a="${f.cat==='image'?'gorsel':'analiz'}" data-p="${esc(f.path)}"><span class="ib blue" style="width:44px;height:44px">${ic('spark')}</span><span><b>Yapay Zekâ ile Analiz Et</b><small>Bu dosyanın içeriğini detaylı analiz et, özet çıkar ve önemli noktaları belirle.</small></span><span class="chev" style="margin-left:auto">${ic('chev')}</span></button>`;
}
ACT.fcat=el=>{S.fcat=el.dataset.k;S.fpg=0;drawFiles()};
ACT.fsel=(el,e)=>{if(e.target.closest('[data-act="fdo"],[data-act="fmenu"]'))return;S.fsel=el.dataset.p;$$('#ftb tr').forEach(r=>r.classList.toggle('on',r.dataset.p===S.fsel));drawDetail()};
ACT.ftab=el=>{S.ftab=el.dataset.t;drawDetail()};
ACT.fdo=(el,e)=>{e.stopPropagation();doFile(el.dataset.p,el.dataset.a)};
ACT.fopen=el=>api('file_open',el.dataset.p,false);
ACT.freveal=el=>api('file_open',el.dataset.p,true);
ACT.fdir=()=>api('files_dir_open');
ACT.fupdir=async()=>{const owner=((S.snap||{}).user||{}).slug||((S.snap||{}).user||{}).name;toast('Klasör seçme penceresi açılıyor…');let r=await tryApi('folder_pick');if(r&&r.job){while(r&&r.job){await new Promise(resolve=>setTimeout(resolve,350));const status=await tryApi('ui_job_status',r.job);if(!status)return;if(owner!==(((S.snap||{}).user||{}).slug||((S.snap||{}).user||{}).name))return;if(status.state==='error')return toast(status.error,'bad');if(status.state==='done'){r=status.data;break}}}if(!r||!r.path)return;
  if(!r.count)return toast('Klasörde yüklenecek dosya bulunamadı.','bad');
  if(!await ask(`“${r.name}” klasöründeki ${r.count} dosya Jarvis'e yüklensin mi?`))return;
  toast(`${r.count} dosya yükleniyor…`);const x=await tryApi('folder_import',r.path);if(x)toast(`${x.ok}/${x.total} dosya yüklendi → Jarvis Dosyaları › ${r.name}`);S.files=null;S.fcat='mine';S.fq='';if(S.page==='files')render()};
ACT.frefresh=async()=>{S.files=null;drawFiles();await loadFiles(true);drawFiles();toast('Dosya listesi yenilendi.')};
const FHELP=[
  ['up','Dosya Yükle / Klasör Yükle','Bilgisayarından tek bir dosya ya da bir klasördeki bütün dosyaları Jarvis’e yükler. Yüklenenler kendi klasörüne kopyalanır, aslına dokunulmaz.'],
  ['folder','Jarvis Klasörü','Yüklediğin dosyaların gerçekte durduğu klasörü açar (Belgeler › Jarvis Dosyaları). Oraya elle dosya da atabilirsin, liste kendiliğinden görür.'],
  ['search','Arama','Yazdığın kelimeyi hem dosya adında hem belge İÇERİĞİNDE arar (en az 3 harf). Eşleşen cümle, satırın altında küçük bir alıntı olarak görünür.'],
  ['spark','Yapay Zekâ Araçları','Soldaki panel: seçili dosya üzerinde toplu işlem yapar — Kapsamlı Analiz, PDF → Excel, PDF → Word, Rapor Oluştur, Klasör Analizi, Görselden Metin.'],
  ['list','Dosya Listesi','Her satırda o dosya türüne uygun hızlı düğmeler (Analiz Et, Özetle, Çevir…) ve sağdaki ••• menüsünde Aç / Klasörde göster / Telefona gönder seçenekleri var.'],
  ['eye','Detay Paneli','Bir dosyaya tıklayınca sağda açılır: Genel Bakış (boyut, tarih, konum) ve Yapay Zekâ Analizi sekmeleri arasında geçiş yapabilirsin.'],
  ['grid','Üstteki Kategoriler','Yüklediklerim / Tümü / PDF / Word / Excel / Görsel / Diğer — listeyi türe göre süzer, yanındaki sayı o kategorideki dosya adedidir.'],
  ['image','Görselleştir','Bir dosyanın "Görselleştir" düğmesine basınca, içeriğinden zihin haritası/akış şeması/infografik gibi bir görsel üretir ve bu sayfaya kaydeder. Sohbette de "zihin haritası çiz" gibi doğal bir şey söylersen Jarvis sohbetten mi dosyadan mı alacağını sorar.'],
];
ACT.fhelp=()=>{
  const overlay=document.createElement('div');overlay.className='jdlg';
  overlay.innerHTML=`<div class="jbox" style="width:min(640px,94vw);max-height:80vh;overflow:auto"><div class="jt"><b>Dosyalar sayfası nasıl çalışır?</b></div>
    <p class="mut" style="margin:0 0 12px">Bu sayfa yüklediğin dosyaları, Jarvis’in onlarla yapabileceği yapay zekâ işlemlerini ve dosya aramasını tek yerde toplar.</p>
    <div style="display:flex;flex-direction:column;gap:10px">${FHELP.map(([i,t,s])=>`<div style="display:flex;gap:10px;align-items:flex-start"><span class="ib blue sm" style="flex:none">${ic(i)}</span><div><b>${esc(t)}</b><div class="mut" style="font-size:13px">${esc(s)}</div></div></div>`).join('')}</div>
    <div class="jbtn"><button class="jok">Anladım</button></div></div>`;
  document.body.appendChild(overlay);
  const close=()=>overlay.remove();
  overlay.querySelector('.jok').onclick=close;
  overlay.onclick=e=>{if(e.target===overlay)close()};
  const key=e=>{if(e.key==='Escape'){document.removeEventListener('keydown',key,true);close()}};
  document.addEventListener('keydown',key,true);
};
ACT.fmenu=(el,e)=>{e.stopPropagation();const p=el.dataset.p,r=el.getBoundingClientRect();menu(r.left-170,r.bottom+4,[['eye','Aç',()=>api('file_open',p,false)],['folder','Klasörde göster',()=>api('file_open',p,true)],['phone','Telefona gönder',()=>doFile(p,'telefon')],'-',['spark','Özetle',()=>doFile(p,'ozet')],['lang','İngilizceye çevir',()=>doFile(p,'cevir')]])};
ACT.ftool=el=>{const a=el.dataset.a;if(a==='#folder'){say('İndirilenler klasöründeki dosyaları listele ve kısaca özetle');return}
  if(a==='envanter')return ACT.finv();
  const f=((S.files&&S.files.files)||[]).find(x=>x.path===S.fsel);if(!f){toast('Önce listeden bir dosya seç.');return}doFile(f.path,a)};
// SADE: Klasör Envanteri — köklü arayüz yenilemesinde bu düğme/akış taşınabilir;
// kalıcı sözleşme API adlarıdır: folder_pick + file_inventory_excel (web_files.py).
ACT.finv=async()=>{const owner=((S.snap||{}).user||{}).slug||((S.snap||{}).user||{}).name;toast('Klasör seçme penceresi açılıyor…');let r=await tryApi('folder_pick');if(r&&r.job){while(r&&r.job){await new Promise(resolve=>setTimeout(resolve,350));const status=await tryApi('ui_job_status',r.job);if(!status)return;if(owner!==(((S.snap||{}).user||{}).slug||((S.snap||{}).user||{}).name))return;if(status.state==='error')return toast(status.error,'bad');if(status.state==='done'){r=status.data;break}}}if(!r||!r.path)return;
  try{const inv=await tryApi('file_inventory_excel',r.path);if(!inv||!inv.path)return;toast(`Envanter raporu yazıldı: ${inv.path} (çift ${inv.duplicates}, benzer ${inv.similar}, boş ${inv.empty}, eski ${inv.old})`);}catch(e){toast(e.message,'bad')}};

// ======================================================================= GÖRSEL ANALİZ
PAGES.vision=pg=>{
  const imgs=((S.files&&S.files.files)||[]).filter(f=>f.cat==='image').slice(0,8);const mode=(S.snap||{}).mode;
  pg.innerHTML=`<div class="pagehead"><div><h1>Ekran</h1><p>Ekranı, kamerayı ve görselleri yapay zekâyla incele.</p></div></div>
   <div class="grid3" style="margin-bottom:14px">
    ${[['green','monitor','Ekranı Analiz Et','Ekrandaki içeriği gör, açıkla, öner','say:ekranı analiz et'],['purple','image','Görsel Yükle ve Analiz Et','Bilgisayarından bir resim seç','act:image'],['orange','file','Görselden Metin','Resim ve taramalardaki yazıyı çıkar','act:ocr'],
       ['blue','monitor',mode==='screen'?'Ekran Paylaşımını Kapat':'Ekranı Paylaş','Sorular ekran görüntüsüyle yanıtlanır','act:share:screen'],['cyan','camera',mode==='camera'?'Kamerayı Kapat':'Kamerayı Aç','Sorular kamera görüntüsüyle yanıtlanır','act:share:camera'],['red','eye','Ekran Görüntüsü Al','Jarvis gizlensin, görüntüden alan seç','act:capture']]
     .map(([c,i,t,s,a])=>`<button class="acard ${c}" data-act="vis" data-a="${a}"><span class="ib ${c}">${ic(i)}</span><b>${t}</b><small>${s}</small><span class="go">${ic('chev')}</span></button>`).join('')}</div>
   ${mode?`<section class="card" style="margin-bottom:14px"><div class="ch"><span class="ct">${mode==='camera'?'Canlı Kamera':'Ekran Paylaşımı'}</span><button class="btn sm" data-act="vis" data-a="act:share:${mode}">Kapat</button></div><img id="vision-preview" alt="Canlı önizleme" style="display:none;width:100%;max-height:430px;object-fit:contain"><p id="vision-status" class="mut">Görüntü bekleniyor…</p></section>`:''}
   <section class="card"><div class="ch"><span class="ct">Son görseller</span><button class="link" data-go="files">Dosyalar</button></div>
    ${imgs.length?`<div class="grid2">${imgs.map(f=>`<div class="frow vrow"><span class="fi image">IMG</span><span class="vn" title="${esc(f.path)}">${esc(f.name)}</span><button class="ac b" data-act="fdo" data-a="gorsel" data-p="${esc(f.path)}">Analiz Et</button><button class="ac p" data-act="fdo" data-a="metin" data-p="${esc(f.path)}">Metin</button></div>`).join('')}</div>`:'<div class="empty">Henüz görsel yok. Yukarıdan bir görsel yükleyebilirsin.</div>'}</section>`;
  if(mode)pollVisionPreview();
  if(!S.files)loadFiles().then(()=>{if(S.page==='vision')render()});
};
ACT.vis=async el=>{const a=el.dataset.a;if(a.startsWith('say:'))return say(a.slice(4));if(a==='act:capture')return ACT.capture();if(a==='act:image')return pickUpload('gorsel','image/*');if(a==='act:ocr')return pickUpload('metin','image/*');
  if(a.startsWith('act:share:')){const r=await tryApi('share',a.slice(10));if(r)toast(r);await refresh();drawMiniPreview();if(S.page==='vision')render()}};

function showCapturePreview(capture){return new Promise(resolve=>{
 const overlay=document.createElement('div');overlay.className='jdlg';
 overlay.innerHTML=`<div class="jbox" style="width:min(760px,94vw)"><div class="jt"><b>Ekran görüntüsü</b></div><img src="${esc(capture.preview)}" alt="Seçtiğin ekran alanı" style="width:100%;max-height:60vh;object-fit:contain"><div class="jbtn"><button class="jno">Kapat</button><button class="jok">Sohbete ekle</button></div></div>`;
 document.body.appendChild(overlay);
 const done=accepted=>{document.removeEventListener('keydown',key,true);overlay.remove();resolve(accepted)};
 const key=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();done(false)}};
 document.addEventListener('keydown',key,true);
 overlay.querySelector('.jno').onclick=()=>done(false);
 overlay.querySelector('.jok').onclick=()=>done(true);
 overlay.onclick=e=>{if(e.target===overlay)done(false)};
 overlay.querySelector('.jok').focus();
})}
ACT.capture=async()=>{
 if(S.captureBusy)return;
 if(S.attPending)return toast('Dosyanın yüklenmesini bekle.');
 const owner=S.snap?.user?.name;S.captureBusy=true;
 try{
  const result=await api('screen_capture');
  if(owner!==S.snap?.user?.name||!result||result.cancelled)return;
  S.files=null;
  if(!await showCapturePreview(result)||owner!==S.snap?.user?.name)return;
  if(S.attPending)return toast('Dosyanın yüklenmesini bekle.');
  if(atts().length>=MAX_ATT)return toast(`En fazla ${MAX_ATT} dosya ekleyebilirsin.`);
  S.att=[...atts(),{path:result.path,name:result.name}];go('chat');drawAtt();
  $('.ask input')?.focus();toast('Ekran görüntüsü eklendi. Talimatını yazıp gönder.');
 }catch(error){toast(error.message||'Ekran görüntüsü alınamadı.','bad')}
 finally{S.captureBusy=false}
};

// Paylaşım açıkken sohbetin köşesinde küçük canlı önizleme (Ekran sayfasında gizlenir). Görüntü yalnız yerelde alınır; model çağrısı yoktur.
let miniTimer=null,miniBusy=false;
function miniHidden(){return S.page==='vision'||(S.page==='menu'&&window.__mnNode==='ekran'&&!!$('.mnscene.docked'))}   // Ekran paneli açıkken panelin kendi önizlemesi var; ikinci pencere açılmaz
function drawMiniPreview(){
  const mode=(S.snap||{}).mode;let box=$('#vprev');
  $$('.hb2[data-a^="act:share:"]').forEach(b=>{const m=b.dataset.a.slice(10),on=mode===m;b.classList.toggle('live',on);b.title=on?(m==='camera'?'Kamerayı kapat':'Ekran paylaşımını kapat'):(m==='camera'?'Kamerayı aç':'Ekranı paylaş')});
  if(!mode||miniHidden()){if(box)box.remove();clearTimeout(miniTimer);miniTimer=null;return}
  if(!box){box=document.createElement('div');box.id='vprev';box.className='vprev'+(S.vmini?' mini':'');box.innerHTML=`<div class="vph"><span></span><div class="vbtns"><button data-act="vmin" title="Küçült / büyüt">${ic('chevd')}</button><button data-act="vis" title="Kapat">${ic('x')}</button></div></div><img alt="Canlı önizleme"><p class="mut">Görüntü bekleniyor…</p>`;document.body.appendChild(box)}
  box.querySelector('span').textContent=mode==='camera'?'Canlı kamera':'Ekran paylaşımı';box.querySelector('[data-act="vis"]').dataset.a='act:share:'+mode;
  if(!miniTimer&&!miniBusy)miniTimer=setTimeout(pollMini,200);
}
ACT.vmin=()=>{S.vmini=!S.vmini;const b=$('#vprev');if(b)b.classList.toggle('mini',!!S.vmini)};
async function pollMini(){
  miniTimer=null;const box=$('#vprev');if(!box||miniBusy)return;if(!(S.snap||{}).mode)return drawMiniPreview();miniBusy=true;
  try{const d=await api('preview'),img=box.querySelector('img'),p=box.querySelector('p');if(d){img.src=d.startsWith('data:')?d:'data:image/png;base64,'+d;img.style.display='block';p.textContent=''}else p.textContent='Görüntü alınamadı. Kamera seçimini ve başka uygulamaların kamerayı kullanıp kullanmadığını kontrol et.'}
  catch(e){const p=box.querySelector('p');if(p)p.textContent=e.message}
  finally{miniBusy=false;if($('#vprev')&&!miniHidden())miniTimer=setTimeout(pollMini,1500)}
}
let previewTimer=null,previewBusy=false;
async function pollVisionPreview(){clearTimeout(previewTimer);if(previewBusy)return;const img=$('#vision-preview');if(!img||S.page!=='vision'||!(S.snap||{}).mode)return;previewBusy=true;try{const data=await api('preview');if(img.isConnected){if(data){img.src=data.startsWith('data:')?data:'data:image/png;base64,'+data;img.style.display='block';$('#vision-status').textContent='Canlı önizleme'}else $('#vision-status').textContent='Kameradan görüntü alınamadı. Kamera seçimini ve başka uygulamaların kamerayı kullanıp kullanmadığını kontrol et.'}}catch(e){if($('#vision-status'))$('#vision-status').textContent=e.message}finally{previewBusy=false;if(S.page==='vision'&&(S.snap||{}).mode)previewTimer=setTimeout(pollVisionPreview,700)}}
// ======================================================================= UYGULAMALAR
const APPS=[
 ['Üretkenlik','blue','msg','Sohbet Et','Sor, konuş, üret. Her konuda yanıt al.','#chat'],
 ['Analiz','purple','file','Dosya Analiz Et','PDF, Word, Excel ve diğer dosyaları analiz et.','#files'],
 ['Analiz','green','monitor','Ekranı Analiz Et','Ekran görüntülerini anlamlandır, analiz et.','ekranı analiz et'],
 ['Araçlar','blue','grid','Uygulama Aç','İstediğin uygulamayı hemen başlat.','#prefill:Aç: '],
 ['Üretkenlik','red','file','PDF Dönüştür','PDF’i Word, Excel ve diğer formatlara çevir.','#files'],
 ['Üretkenlik','green','grid','Excel Oluştur','Tablo oluştur, düzenle ve analiz et.','#prefill:Şu verilerle bir Excel tablosu oluştur: '],
 ['Üretkenlik','blue','file','Word Oluştur','Rapor, metin ve doküman otomatik hazırla.','#prefill:Şu konuda bir Word raporu hazırla: '],
 ['Medya','purple','image','Görsel Analiz','Görselleri analiz et, içeriğini açıkla.','#vision'],
 ['Analiz','orange','folder','Klasör Analizi','Klasör içindeki dosyaları özetle, analiz et.','İndirilenler klasöründeki dosyaları listele ve kısaca özetle'],
 ['Araçlar','blue','globe','Web Araştır','Güncel bilgi topla, kaynaklarla araştır.','#prefill:İnternette araştır: '],
 ['Üretkenlik','purple','chart','Rapor Oluştur','Verilerden kapsamlı raporlar hazırla.','#prefill:Şu konuda kapsamlı bir rapor hazırla: '],
 ['Medya','red','play','YouTube','YouTube’u aç ya da bir şey çal.','YouTube aç'],
 ['Medya','purple','music','Müzik Çal','Ruh haline uygun müzik aç.','müzik aç'],
 ['Araçlar','cyan','phone','Telefona Gönder','Bir dosyayı telefonuna gönder.','#files'],
 ['Araçlar','green','calendar','Bugün Neler Var','Takvim, mail ve görevlerin özeti.','günlük özet'],
];
const ACATS=['Tümü','Üretkenlik','Analiz','Geliştirme','Medya','Araçlar'];
// HARITA START
const HARITA_CLASS={read:['okuma','ok'],local_reversible:['geri alınabilir','ok'],local_destructive:['yıkıcı','warn'],message_out:['gönderim','warn'],publish:['yayın','warn'],money_credential:['para','bad'],system_config:['sistem','warn'],physical:['fiziksel','warn']};
const HARITA_POLICY=[['ask','Sor'],['allow','İzin ver'],['deny','Engelle']];
const HARITA_AREA={cihaz:'Cihazlar',iletisim:'İletişim'};
function harita_action(t,a){
  const cls=HARITA_CLASS[a.class]||[String(a.class||'bilinmiyor'),'warn'];
  const ctl=a.policy==='locked'
    ?`<button class="harita-lock" data-map-policy="locked" disabled aria-disabled="true" title="Bu işlem kilitli">🔒 Kilitli</button>`
    :`<select class="harita-pol" data-map-tool="${esc(t.id)}" data-map-action="${esc(a.id)}" data-map-old="${esc(a.policy)}">${HARITA_POLICY.map(([v,l])=>`<option value="${v}"${v===a.policy?' selected':''}>${l}</option>`).join('')}</select>`;
  return `<div class="harita-act"><div class="harita-actx"><b>${esc(a.name)}</b><small>${esc(a.desc)}</small></div><span class="harita-badge ${cls[1]}">${esc(cls[0])}</span>${ctl}</div>`;
}
function harita_tool(t){
  const acts=Array.isArray(t.actions)?t.actions.filter(a=>a&&typeof a==='object'):[];
  return `<section class="card harita-tool"><div class="harita-th"><span class="harita-ic">${ic(t.icon||'gear')}</span><div><b>${esc(t.name)}</b><small>${esc(t.detail)}</small></div><span class="harita-state ${esc(t.state)}">${esc(t.state)}</span></div>${acts.map(a=>harita_action(t,a)).join('')}</section>`;
}
function harita_render(data){
  if(!data||typeof data!=='object'||!Array.isArray(data.tools))return `<div class="harita-wrap"><div class="empty">Harita bu sürümde yok.</div></div>`;
  const tools=data.tools.filter(t=>t&&typeof t==='object'&&t.id!==undefined&&t.name!==undefined);
  const ph=(Array.isArray(data.placeholders)?data.placeholders:[]).filter(p=>p&&typeof p==='object');
  const areas=[...new Set(tools.map(t=>t.area).concat(ph.map(p=>p.area)))];
  return `<div class="harita-wrap"><div class="harita-hub"><div class="harita-orb">${menuOrbSvg()}</div><button class="btn sm bad" data-act="stoptask">Durdur</button></div>`
    +harita_wizard_html()+areas.map(ar=>`<div class="harita-area"><h3>${esc(HARITA_AREA[ar]||ar||'Diğer')}</h3>${tools.filter(t=>t.area===ar).map(harita_tool).join('')}${ph.filter(p=>p.area===ar).map(p=>`<div class="card harita-soon"><b>${esc(p.name)}</b><span class="harita-badge">Yakında</span></div>`).join('')}</div>`).join('')+`</div>`;
}
async function harita_set_policy(tool,action,old,next,control){
  const r=await tryApi('map_set_policy',tool,action,next);
  if(r===null||r===undefined||r===false||(typeof r==='object'&&r.ok===false)){if(control)control.value=old;toast('Harita politika değişimi bu sürümde yok.','bad');return}
  if(control&&control.dataset)control.dataset.mapOld=next;
}
PAGES.map=async pg=>{
  pg.innerHTML=`<div class="harita-wrap"><div class="empty">Harita yükleniyor…</div></div>`;
  const d=await tryApi('map');
  pg.innerHTML=harita_render(d);
};
if(typeof document!=='undefined')document.addEventListener('change',e=>{
  const s=e.target&&e.target.closest&&e.target.closest('select[data-map-tool]');if(!s)return;
  harita_set_policy(s.dataset.mapTool,s.dataset.mapAction,s.dataset.mapOld,s.value,s);
});
const HARITA_PENDING=new WeakMap(),HARITA_BUSY=new WeakSet();
const HARITA_PROGRAM_CLASSES=['local_destructive','local_reversible','read','message_out','publish','physical'];
function harita_wizard_html(){
  return `<details class="harita-wizard"><summary>Araç ekle</summary><form class="harita-form">
    <label>Araç türü<select name="kind"><option value="api">Açık API</option><option value="program">Yerel program</option><option value="device">HTTP cihaz</option></select></label>
    <fieldset class="harita-api"><legend>Açık API</legend><label>Keşfet<input name="query" maxlength="200" placeholder="Örneğin hava durumu"></label><button type="button" class="btn sm" data-harita-search>Servis ara</button>
      <label>Servis adayı<select name="candidate"><option value="">Önce servis arayın</option></select></label><label>Kesin HTTPS GET adresi<input name="endpoint" maxlength="2048"></label>
      <label>Parametre şeması<textarea name="parameters" rows="2">{}</textarea></label><p>Belgeden doğruladığınız kesin okuma adresini girin. Şema örneği: {"city":"string"}. Bu araç yalnız okuma yapar; ücret/kota doğrulanmadı.</p></fieldset>
    <fieldset class="harita-program" hidden><legend>Yerel program</legend><label>Araç adı<input name="program_name" maxlength="120"></label><label>Programın tam yolu<input name="program" maxlength="2000"></label>
      <label>Argüman listesi<textarea name="arguments" rows="3">[]</textarea></label><label>Eylem sınıfı<select name="action_class">${HARITA_PROGRAM_CLASSES.map(c=>`<option value="${c}">${esc(HARITA_CLASS[c][0])}</option>`).join('')}</select></label>
      <p>Argüman örneği: ["--dosya", "{dosya}"]. Sınıfı siz seçersiniz; varsayılan yıkıcı yerel işlem onay ister. Para ve sistem sınıfları kapalıdır. Program otomatik indirilmez.</p></fieldset>
    <fieldset class="harita-device" hidden><legend>HTTP cihaz</legend><label>Araç adı<input name="device_name" maxlength="120"></label><label>IP veya localhost adresi<input name="address" maxlength="1000"></label>
      <label>Anahtar<input name="key" type="password" autocomplete="off" maxlength="1024"></label><label class="harita-check"><input name="allow_private" type="checkbox">Bu cihaz için özel IP/localhost erişimini onaylıyorum.</label>
      <p>Yalnız açık IP veya localhost kabul edilir; genel IP HTTPS ister. GET okuma, POST fiziksel komuttur ve her seferinde onay ister. Bu genel cihazın durdurma protokolü tanımlı değildir.</p></fieldset>
    <div class="harita-buttons"><button type="button" class="btn sm" data-harita-preview>Önizle</button><button type="button" class="btn sm pri harita-confirm" data-harita-confirm disabled>Onayla ve ekle</button></div>
    <pre class="harita-review" role="status" aria-live="polite"></pre></form></details>`;
}
function harita_wizard_payload(form){
  const value=name=>form.querySelector(`[name="${name}"]`)?.value||'';
  const kind=value('kind');let payload;
  if(kind==='api')payload={candidate:value('candidate'),endpoint:value('endpoint'),parameters:JSON.parse(value('parameters')||'{}')};
  else if(kind==='program'){
    if(!HARITA_PROGRAM_CLASSES.includes(value('action_class')))throw Error('Sınıf kapalı.');
    payload={name:value('program_name'),program:value('program'),arguments:JSON.parse(value('arguments')||'[]'),action_class:value('action_class')};
    if(!Array.isArray(payload.arguments))throw Error('Argüman listesi gerekli.');
  }else if(kind==='device')payload={name:value('device_name'),address:value('address'),key:value('key'),allow_private:!!form.querySelector('[name="allow_private"]')?.checked};
  else throw Error('Araç türü geçersiz.');
  return {kind,payload};
}
function harita_wizard_reset(form){
  HARITA_PENDING.delete(form);
  const button=form.querySelector('.harita-confirm');if(button)button.disabled=true;
  const review=form.querySelector('.harita-review');if(review)review.textContent='';
}
function harita_wizard_kind(form){
  const kind=form.querySelector('[name="kind"]')?.value;
  for(const name of ['api','program','device']){const section=form.querySelector('.harita-'+name);if(section)section.hidden=name!==kind}
}
async function harita_wizard_save(form,confirmed){
  if(HARITA_BUSY.has(form))return;
  const review=form.querySelector('.harita-review');
  try{
    const data=harita_wizard_payload(form),signature=JSON.stringify(data),pending=HARITA_PENDING.get(form);
    if(confirmed&&(!pending||pending.signature!==signature)){harita_wizard_reset(form);review.textContent='Bilgiler değişti veya önizleme yok; yeniden önizleyin.';return}
    const owner=confirmed?pending.owner:null;
    harita_wizard_reset(form);HARITA_BUSY.add(form);
    review.textContent=confirmed?'Kayıt onaylanıyor…':'Önizleme hazırlanıyor…';
    const result=await tryApi('tool_wizard_add',data.kind,data.payload,!!confirmed,owner);
    if(form.isConnected===false)return;
    if(!result||result.state==='error'||result.state==='blocked'){review.textContent=result?.detail||'Araç eklenemedi. Alanları kontrol edip yeniden önizleyin.';return}
    if(!confirmed){
      if(result.state!=='approval'||typeof result.owner!=='string'||!result.owner){review.textContent='Önizleme kullanıcı bağlamı doğrulanamadı.';return}
      if(JSON.stringify(harita_wizard_payload(form))!==signature){review.textContent='Bilgiler değişti; yeniden önizleyin.';return}
      review.textContent=String(result.text||'Bu aracı eklemeyi onaylayın.');
      HARITA_PENDING.set(form,{signature,owner:result.owner});form.querySelector('.harita-confirm').disabled=false;return;
    }
    if(result.state!=='done'){review.textContent='Kayıt doğrulanamadı; yeniden önizleyin.';return}
    const key=form.querySelector('[name="key"]');if(key)key.value='';
    review.textContent='Araç kaydedildi. Gerçek PC, canlı hesap ve gerçek cihaz denenmedi.';toast('Araç Harita’ya eklendi.','ok');
    const map=await tryApi('map'),wrap=form.closest('.harita-wrap');
    if(form.isConnected!==false&&wrap&&Array.isArray(map?.tools))wrap.outerHTML=harita_render(map);
  }catch(_){harita_wizard_reset(form);review.textContent='Alanları kontrol edin: argüman listesi ve parametre şeması geçerli JSON olmalı.'}
  finally{HARITA_BUSY.delete(form)}
}
async function harita_wizard_search(form){
  if(HARITA_BUSY.has(form))return;
  harita_wizard_reset(form);HARITA_BUSY.add(form);
  const review=form.querySelector('.harita-review'),query=form.querySelector('[name="query"]').value;
  try{
    review.textContent='Servisler aranıyor…';const result=await tryApi('tool_wizard_discover',query);
    if(form.isConnected===false)return;
    if(form.querySelector('[name="query"]').value!==query){review.textContent='Arama değişti; yeniden arayın.';return}
    if(!Array.isArray(result?.candidates)){review.textContent='Servis araması tamamlanamadı.';return}
    form.querySelector('[name="candidate"]').innerHTML='<option value="">Bir aday seçin</option>'+result.candidates.filter(c=>c&&typeof c.id==='string').map(c=>`<option value="${esc(c.id)}">${esc(c.name)} — ${esc(c.url)}</option>`).join('');
    review.textContent=result.candidates.length?'Adayı seçin; resmî belgeden kesin okuma adresini ve şemayı girip önizleyin.':'Aday bulunamadı.';
  }catch(_){review.textContent='Servis araması tamamlanamadı.'}finally{HARITA_BUSY.delete(form)}
}
if(typeof document!=='undefined'){
  document.addEventListener('input',event=>{const form=event.target?.closest?.('form.harita-form');if(form)harita_wizard_reset(form)});
  document.addEventListener('change',event=>{const form=event.target?.closest?.('form.harita-form');if(form){harita_wizard_reset(form);harita_wizard_kind(form)}});
  document.addEventListener('click',event=>{const button=event.target?.closest?.('[data-harita-preview],[data-harita-confirm],[data-harita-search]'),form=button?.closest('form.harita-form');if(!form)return;event.preventDefault();if(button.hasAttribute('data-harita-search'))harita_wizard_search(form);else harita_wizard_save(form,button.hasAttribute('data-harita-confirm'))});
  document.addEventListener('submit',event=>{const form=event.target?.closest?.('form.harita-form');if(form){event.preventDefault();harita_wizard_save(form,false)}});
}
// HARITA END
PAGES.apps=pg=>{
  pg.innerHTML=`<div class="apph"><div><div class="kick">• YAPAY ZEKÂ ARAÇLARI •</div><h1>Uygula<span>malar</span></h1><p>Daha fazlasını keşfet, üretkenliğini artır</p></div><div style="height:250px;position:relative"><canvas id="g-apps" style="position:absolute;inset:0;width:100%;height:100%"></canvas></div></div>
   <section class="card glow"><div class="ftool"><div class="chips" style="margin:0">${ACATS.map(c=>`<button class="chip ${S.acat===c?'on':''}" data-act="acat" data-c="${c}">${c}</button>`).join('')}</div>
    <div class="search" style="margin-left:auto;max-width:330px">${ic('search')}<input id="aq" placeholder="Uygulama ara..." value="${esc(S.aq)}"></div></div><div class="agrid" id="agrid"></div></section>`;
  mountGlobe($('#g-apps'),{color:'blue',pedestal:true});$('#aq').oninput=e=>{S.aq=e.target.value;drawApps()};drawApps();
};
function drawApps(){const q=S.aq.toLowerCase();$('#agrid').innerHTML=APPS.map((a,i)=>[a,i]).filter(([a])=>(S.acat==='Tümü'||a[0]===S.acat)&&(!q||(a[3]+' '+a[4]).toLowerCase().includes(q)))
  .map(([[cat,c,i,t,s],k])=>`<button class="acard ${c}" data-act="app" data-k="${k}"><span class="ib ${c}">${ic(i)}</span><b>${t}</b><small>${s}</small><span class="go">${ic('chev')}</span></button>`).join('')||'<div class="empty">Sonuç yok.</div>'}
function artSvg(c){const col={blue:'#3b9bff',purple:'#b58cff',green:'#34d399',red:'#ff5a5a',orange:'#ffbf47',cyan:'#45e1ff'}[c]||'#3b9bff';
  return `<g fill="none" stroke="${col}" stroke-width="1.2" opacity=".9"><rect x="18" y="10" width="80" height="52" rx="5" fill="${col}" fill-opacity=".08"/><path d="M26 22h40M26 30h56M26 38h30"/><rect x="62" y="34" width="44" height="34" rx="4" fill="${col}" fill-opacity=".12"/><path d="M68 58l8-10 8 6 10-14"/></g>`}
ACT.acat=el=>{S.acat=el.dataset.c;render()};
ACT.app=el=>{const a=APPS[+el.dataset.k][5];if(a.startsWith('#prefill:')){go('chat');setTimeout(()=>{const i=$('.chatask input');if(i){i.value=a.slice(9);i.focus()}},50);return}if(a.startsWith('#'))return go(a.slice(1));say(a)};

const TOOLS=[['takvim','orange','calendar','Takvim ve Görevler','Günler, etkinlikler, görevler ve notlar'],['veri','cyan','folder','Veri Klasörü','Ayarlar, hafıza ve kayıtları aç'],['telefon','green','phone','Telefon','Telefondan erişim ve bildirim'],
  ['mesaj','green','whats','Mesajlar','WhatsApp kişileri ve mesaj'],['rapor','purple','chart','Gelişim Raporu','Neyi yanlış duydum, neyi yapamadım'],['tarama','blue','scan','Sistem Taraması','Her parçayı dene, sorunları göster']];
PAGES.tools=pg=>{go('tools')};   // eski adres: Ayarlar içindeki ilgili bölüme yönlenir
ACT.tool=el=>{S.tool=el.dataset.k==='gorev'?'takvim':el.dataset.k;go('tools')};
const settingsOpen=()=>S.page==='settings'||!!document.getElementById('mn-win');
const TV={},redrawTool=()=>{if(settingsOpen())$$('#spane [data-tv]:not([data-lazy])').forEach(d=>TV[d.dataset.tv](d))};
ACT.tvload=el=>{const d=el.closest('[data-tv]');d.removeAttribute('data-lazy');TV[d.dataset.tv](d)};
TOOLS.unshift(['aihub','purple','spark','Yapay Zekâ ve Bağlantılar','Otomatik model seçimi ve sağlayıcı bağlantılarını yönet']);
TOOLS.push(['rehber','cyan','book','Kullanım Rehberi','Jarvis neler yapar? Nasıl kullanılır?']);
TV.rehber=el=>{el.innerHTML=JarvisGuide.general()};
ACT.aihubtab=el=>{S.sset=el.dataset.k;drawSettings()};
TV.veri=el=>{el.innerHTML=`<section class="card data-folder"><span class="ib cyan">${ic('folder')}</span><div class="data-folder-copy"><h2>Yerel Kayıtlar</h2><p>Jarvis’in Ayarları, Hafızası Ve İşlem Kayıtları Bu Klasörde Tutulur.</p><button class="btn pri" data-act="odata">${ic('folder')} Klasörü Aç</button></div></section>`};
const after=async p=>{await p;await refresh();redrawTool()};
const today=()=>ymd(new Date());
const whenTxt=w=>{const d=w.slice(0,10),t=w.length>10?' '+w.slice(11,16):'';const td=today(),tm=ymd(new Date(Date.now()+864e5));return (d===td?'Bugün':d===tm?'Yarın':d.split('-').reverse().join('.'))+t};

TV.takvim=el=>{const sn=S.snap||{};S.calDay=S.calDay||today();S.calMonth=S.calMonth||S.calDay.slice(0,7);const [year,month]=S.calMonth.split('-').map(Number),first=new Date(year,month-1,1),days=new Date(year,month,0).getDate(),offset=(first.getDay()+6)%7;
const ev=(sn.all_events||[]).slice().sort((a,b)=>a.when.localeCompare(b.when)),tasks=sn.tasks||[];
const cells=Array(offset).fill('<span></span>');for(let d=1;d<=days;d++){const date=ymd(new Date(year,month-1,d));const count=ev.filter(e=>e.when.slice(0,10)===date).length+tasks.filter(t=>!t.done&&(t.when||'').slice(0,10)===date).length;cells.push(`<button class="calday ${date===S.calDay?'on':''} ${date===today()?'today':''}" data-act="calday" data-day="${date}">${d}${count?`<small>${count}</small>`:''}</button>`)}
const row=e=>`<div class="srow"><b style="flex:1">${esc(e.title)}</b><span class="mut">${esc(whenTxt(e.when))}</span><button class="ab" data-act="evdel" data-id="${e.id}">${ic('trash')}</button></div>`;
const dayEvents=ev.filter(e=>e.when.slice(0,10)===S.calDay),dayTasks=tasks.filter(t=>(t.when||'').slice(0,10)===S.calDay);
el.innerHTML=`<div class="planner-top"><section data-mtitle="Takvim" class="card"><div class="ch"><button class="btn sm" data-act="calmonth" data-n="-1">‹</button><b>${first.toLocaleDateString('tr-TR',{month:'long',year:'numeric'})}</b><button class="btn sm" data-act="calmonth" data-n="1">›</button><button class="btn sm" data-act="caltoday">Bugün</button></div><div class="calendar-grid">${['Pzt','Sal','Çar','Per','Cum','Cmt','Paz'].map(x=>`<b>${x}</b>`).join('')}${cells.join('')}</div><div class="calsel"><h3>${esc(whenTxt(S.calDay))}</h3>${dayEvents.slice(0,4).map(row).join('')}${dayEvents.length>4?`<p class="mut">+${dayEvents.length-4} etkinlik daha</p>`:''}${dayTasks.slice(0,3).map(t=>`<div class="srow"><button class="ab" data-act="tktog" data-id="${t.id}">${ic(t.done?'check':'target')}</button><span>${esc(t.text)} ${t.done?'· Tamamlandı':''}</span></div>`).join('')}${!dayEvents.length&&!dayTasks.length?'<p class="mut">Bu gün için kayıt yok.</p>':''}
<div class="ftool"><input id="evtitle" placeholder="Etkinlik başlığı"><input id="evdate" type="date" value="${S.calDay}" aria-label="Etkinlik tarihi"><input id="evtime" type="time" aria-label="Saat (isteğe bağlı)"><button class="btn pri" data-act="evsave">Ekle</button></div>
<p class="mut">Veya gün ve saati yazarak ekle:</p><div class="ftool"><input id="evt" placeholder="Yarın 15'te toplantı"><button class="btn" data-act="evadd">Ekle</button></div></div></section><div id="planner-tasklist"></div></div><div id="planner-tasks" style="margin-top:14px"></div><section class="card" style="margin-top:14px"><h3>Yaklaşan Etkinlikler</h3>${ev.filter(e=>e.when.slice(0,10)>=today()).map(row).join('')||'<p class="mut">Yaklaşan etkinlik yok.</p>'}</section>`;
$('#evt').onkeydown=e=>{if(e.key==='Enter')ACT.evadd()};drawTaskNotes($('#planner-tasks'))};
ACT.calday=el=>{S.calDay=el.dataset.day;redrawTool()};
ACT.calmonth=el=>{const [y,m]=S.calMonth.split('-').map(Number);S.calMonth=ymd(new Date(y,m-1+(+el.dataset.n),1)).slice(0,7);redrawTool()};
ACT.caltoday=()=>{S.calDay=today();S.calMonth=S.calDay.slice(0,7);redrawTool()};
ACT.evsave=async()=>{const title=$('#evtitle').value.trim(),date=$('#evdate').value,time=$('#evtime').value;if(!title||!date)return toast('Başlık ve gün seç.','bad');const r=await tryApi('event_add',title,date+(time?'T'+time:''));if(r){S.calDay=date;S.calMonth=date.slice(0,7);await after(0)}};
ACT.evadd=async()=>{const v=$('#evt').value.trim();if(!v)return;const r=await tryApi('event_add_text',v,true);if(r){S.calDay=r.when.slice(0,10);S.calMonth=S.calDay.slice(0,7);toast('Eklendi: '+r.label);await after(0)}};
ACT.evdel=el=>after(api('event_delete',+el.dataset.id));

function drawTaskNotes(el){const sn=S.snap||{},ts=sn.tasks||[],open=ts.filter(t=>!t.done),done=ts.filter(t=>t.done),notes=sn.notes||[];
  const tr=(t,d)=>`<div class="srow"><button class="ab" data-act="tktog" data-id="${t.id}" style="color:${d?'var(--green)':'var(--mut)'}">${ic(d?'check':'target')}</button><span style="flex:1;${d?'text-decoration:line-through;color:var(--mut)':''}">${esc(t.text)}${t.when?`<small>${esc(whenTxt(t.when))}</small>`:''}</span><button class="ab" data-act="tkdel" data-id="${t.id}">${ic('trash')}</button></div>`;
  const taskMarkup=`<section class="card glow"><div class="ch"><span class="ct">Yapılacaklar</span><span class="pill">${open.length}</span></div>
     <div class="ftool"><div class="search">${ic('plus')}<input id="tki" placeholder="Yeni görev yaz, Enter’a bas"></div><input id="tkdate" type="date" value="${esc(S.calDay||today())}" aria-label="Görev tarihi"><button class="btn sm" data-act="taskadd">Ekle</button></div>${open.map(t=>tr(t,0)).join('')||'<div class="empty">Açık görev yok.</div>'}
     ${done.length?`<div class="ch" style="margin-top:14px"><span class="ct" style="font-size:15px">Tamamlanan</span><button class="link" data-act="tkclear">Temizle</button></div>${done.map(t=>tr(t,1)).join('')}`:''}</section>`;
  $('#planner-tasklist').innerHTML=taskMarkup;
  el.innerHTML=`<div class="notesworkspace"><section class="card"><div class="ch"><span class="ct">Notlar</span><span class="pill">${notes.length}</span></div><details class="noteeditor"><summary>+ Yeni Not / Görsel Ekle</summary><input id="nttitle" placeholder="Not başlığı" value="${esc(S.noteTitle||'')}" maxlength="120"><textarea id="nti" placeholder="Notunu buraya yaz; görsele ait açıklamayı da ekleyebilirsin.">${esc(S.noteText||'')}</textarea><div class="ftool"><button class="btn sm" data-act="ntimage">${ic('image')} Görsel Ekle</button><button class="btn sm pri" data-act="ntsave">Kaydet</button></div><div id="ntpreview"></div></details>
     ${notes.map(n=>`<div class="noterow"><button class="noteselect ${S.noteSelected===n.id?'on':''}" data-act="ntopen" data-id="${n.id}">${n.photo?ic('image'):ic('edit')} ${esc(n.title||String(n.text||'Görsel not').split('\n')[0].slice(0,60))}</button><button class="ab" data-act="ntdel" data-id="${n.id}" aria-label="Notu sil">${ic('trash')}</button></div>`).join('')||'<div class="empty">Not yok.</div>'}</section><section class="card notedetail" id="note-detail" aria-live="polite"><div class="empty">Soldan bir not seç.</div></section></div>`;
  $('#tki').onkeydown=e=>{if(e.key==='Enter')ACT.taskadd()};
  $('#nti').oninput=e=>{S.noteText=e.target.value};
  $('#nttitle').oninput=e=>{S.noteTitle=e.target.value};drawNotePreview();if(notes.some(n=>n.id===S.noteSelected))ACT.ntopen({dataset:{id:S.noteSelected}})};
function drawNotePreview(){const el=$('#ntpreview');if(el)el.innerHTML=S.notePreview?`<div class="notepreview"><img src="${esc(S.notePreview)}" alt="Seçilen not görseli"><button class="btn sm" data-act="ntimageclear">Görseli Kaldır</button></div>`:''}
ACT.ntimage=()=>{if(S.noteSaving)return;const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp,image/gif,image/bmp';const owner=((S.snap||{}).user||{}).name;
 input.onchange=()=>{const file=input.files[0];if(!file||owner!==((S.snap||{}).user||{}).name)return;if(file.size>20*1024*1024)return toast('Görsel en fazla 20 MB olabilir.','bad');if(S.notePreview)URL.revokeObjectURL(S.notePreview);S.noteFile=file;S.notePreview=URL.createObjectURL(file);drawNotePreview()};input.click()};
ACT.ntimageclear=()=>{if(S.notePreview)URL.revokeObjectURL(S.notePreview);S.notePreview=null;S.noteFile=null;drawNotePreview()};
ACT.ntsave=async()=>{if(S.noteSaving)return;const text=($('#nti')?.value||S.noteText||'').trim(),file=S.noteFile,owner=((S.snap||{}).user||{}).name;if(!text&&!file)return toast('Not metni veya görsel ekle.','bad');S.noteSaving=true;
 try{let path='';if(file){const result=await upload(file,true);if(!result)return;path=result.path}if(owner!==((S.snap||{}).user||{}).name)return;
 await api('note_add',text,path,($('#nttitle')?.value||S.noteTitle||'').trim());if(owner!==((S.snap||{}).user||{}).name)return;S.noteText='';S.noteTitle='';if($('#nttitle'))$('#nttitle').value='';ACT.ntimageclear();if($('#nti'))$('#nti').value='';await after(0);toast('Not kaydedildi.');
 }catch(e){toast('Not kaydedilemedi: '+e.message,'bad')}finally{S.noteSaving=false}};
ACT.ntopen=async el=>{const id=+el.dataset.id,note=((S.snap||{}).notes||[]).find(n=>n.id===id);if(!note)return;S.noteSelected=id;const owner=((S.snap||{}).user||{}).name,panel=$('#note-detail');if(!panel)return;
 panel.innerHTML=`<h3>${esc(note.title||String(note.text||'Görsel not').split('\n')[0].slice(0,60))}</h3><small class="mut">${esc(note.ts||'')}</small><div id="note-detail-image"></div><div class="notebody">${esc(note.text||'')}</div>`;
 document.querySelectorAll('.noteselect').forEach(b=>b.classList.toggle('on',+b.dataset.id===id));if(!note.photo)return;
 try{const data=await api('note_image',id);if(owner!==((S.snap||{}).user||{}).name||S.noteSelected!==id||!panel.isConnected)return;const image=$('#note-detail-image');if(image)image.innerHTML=`<img src="${esc(data)}" alt="Not görseli">`}catch(e){if(S.noteSelected===id&&owner===((S.snap||{}).user||{}).name)toast('Görsel açılamadı: '+e.message,'bad')}};
ACT.taskadd=async()=>{const t=$('#tki').value.trim();if(t)await after(api('task_add',t,$('#tkdate').value))};
TV.gorev=el=>TV.takvim(el);
ACT.tktog=el=>after(api('task_toggle',+el.dataset.id));ACT.tkdel=el=>after(api('task_delete',+el.dataset.id));
ACT.tkclear=()=>after(api('task_clear_done'));ACT.ntdel=el=>after(api('note_delete',+el.dataset.id));

function drawQR(c,m,size){const n=m.length,q=4,cell=Math.max(1,Math.floor(size/(n+q*2)));const px=cell*(n+q*2);c.width=c.height=px;c.style.width=c.style.height=px+'px';const g=c.getContext('2d');g.fillStyle='#fff';g.fillRect(0,0,px,px);g.fillStyle='#000';m.forEach((r,y)=>r.forEach((v,x)=>{if(v)g.fillRect((x+q)*cell,(y+q)*cell,cell,cell)}))}
const PH={sel:0,msg:'',nmsg:''};
TV.telefon=async el=>{const i=PH.info=await tryApi('phone_info',PH.user||'')||{};PH.user=i.user||'';const urls=i.urls||[];if(PH.sel>=urls.length)PH.sel=0;const cur=urls[PH.sel];const sn=S.snap||{},ts=i.tailscale||{},https=i.https||{};
  const scope=i.scope||'secure', legacy=!!i.token_legacy;
  el.innerHTML=`<div class="grid2"><section class="card glow"><div class="ch"><span class="ct">Android / iPhone · PC bağlantısı</span><span class="pill ${i.connected?'good':''}">${i.connected?'Telefon bağlı':i.running?'Bağlantıya hazır':'Kapalı'}</span></div>
     ${(i.users||[]).length>1?`<p class="mut" style="margin:0 0 6px;font-size:12.5px">Kimin telefonu? Her kişinin adresi kendi anahtarını taşır; başkası adına konuşamaz.</p><div class="chips" style="margin:0 0 10px">${i.users.map(u=>`<button class="chip ${u===i.user?'on':''}" data-act="phuser" data-u="${esc(u)}">${ic('user')} ${esc(u)}</button>`).join('')}</div>`:''}
     ${i.running?`<div class="chips" style="margin:0 0 12px">${urls.map((u,k)=>`<button class="chip ${k===PH.sel?'on':''}" data-act="phsel" data-i="${k}">${u.label.includes('HTTPS')?'HTTPS · mikrofon':u.label.startsWith('Her')?'Tailscale':'Aynı Wi-Fi'}</button>`).join('')}</div>
       <div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap"><canvas id="phqr" style="border-radius:8px"></canvas><div><p class="mut">Telefonun kamerasıyla QR’ı okut. Kod 90 saniye içinde bir kez kullanılır; kişisel API anahtarı içermez.</p><p class="mut">Android ve iPhone’da açılan sayfadaki ＋ düğmesiyle ana ekrana ekleyebilirsin. PC’de Jarvis açık kalmalı; mikrofon ve kurulum için HTTPS sekmesini seç.</p><p style="font-size:12px;word-break:break-all;margin:8px 0" class="mut">${esc(cur?cur.url:'')}</p>
       ${cur&&!cur.qr?'<p class="mut">QR oluşturulamadı. kurulum.bat ile segno paketini onar veya adresi kopyala.</p>':''}<button class="btn sm" data-act="phrenew">${ic('refresh')} QR’ı yenile</button> <button class="btn sm" data-act="phcopy">${ic('copy')} Adresi kopyala</button> <button class="btn sm" data-act="phoff">Kapat</button></div></div>`
     :`<p class="mut" style="margin-bottom:12px">Telefonla Jarvis’e yazmak ve komut vermek için erişim sayfası açılır. Adres gizli bir anahtar içerir.</p><button class="btn pri" data-act="phon">${ic('phone')} Telefon erişimini aç</button>`}
     ${srow('power','Jarvis açılınca erişimi aç','Her seferinde açmak zorunda kalma',`<button class="sw ${i.auto?'on':''}" data-act="phauto"></button>`)}
     <p class="mut" style="margin-top:8px">${esc(PH.msg||i.error||'')}</p></section>
   <section class="card"><div class="ch"><span class="ct">Telefon güvenliği</span><span class="pill ${legacy?'bad':'good'}">${legacy?'Eski anahtar':'Güçlü anahtar'}</span></div>
     ${srow('key','Bağlantı anahtarı',legacy?`${i.token_len||0} karakter · yenilenmeli`:`${i.token_len||0} karakter · güçlü`,`<button class="btn sm ${legacy?'pri':''}" data-act="phtoken">${ic('refresh')} Anahtarı yenile</button>`)}
     ${srow('shield','Bağlantı',scope==='secure'?'Güvenli HTTPS · önerilen':scope==='tailscale'?'Yalnız şifreli Tailscale ağı':'Wi-Fi · bağlantı şifrelenmez',`<div class="seg"><button class="${scope==='secure'?'on':''}" data-act="phscope" data-v="secure">HTTPS</button><button class="${scope==='tailscale'?'on':''}" data-act="phscope" data-v="tailscale">Yalnız Tailscale</button><button class="${scope==='both'?'on':''}" data-act="phscope" data-v="both">Wi-Fi erişimini aç</button></div>`)}
     ${srow('wifi','Tailscale',ts.state==='running'?`Bağlı${ts.name?' · '+esc(ts.name):''}`:ts.installed?'Kurulu ama bağlı değil':'Kurulu değil',`<span class="pill ${ts.state==='running'?'good':'warn'}">${ts.state==='running'?'Hazır':'Gerekli'}</span>`)}
     ${srow('lock','HTTPS',https.active?'Açık · telefon mikrofonu güvenli bağlantıda':'Kapalı',`<button class="btn sm ${https.active?'':'pri'}" data-act="tshttps" data-v="${https.active?'0':'1'}">${https.active?'HTTPS’i kapat':'HTTPS’i aç'}</button>`)}
     <div style="display:flex;gap:8px;flex-wrap:wrap;padding:10px 2px 0"><button class="btn sm" data-act="tsopen">Tailscale’i aç</button>${ts.installed?'':`<button class="btn sm" data-act="tsdownload">Tailscale indir</button>`}</div>
     <p class="mut" style="margin-top:10px">Varsayılan bağlantı <b>HTTPS</b> kullanır. Wi-Fi erişimini seçersen bağlantı şifrelenmez. Anahtarı yenilersen eski QR/Siri kestirmesi geçersiz olur ve bir kez yeniden kurman gerekir.</p></section></div>
   <div class="grid2" style="margin-top:14px"><section class="card"><div class="ch"><span class="ct">Telefona bildirim (ntfy)</span><span class="pill ${sn.ntfy?'good':''}">${sn.ntfy?'Açık':'Kapalı'}</span></div>
     <p class="mut" style="margin-bottom:12px">Hatırlatmalar telefonuna bildirim olarak gelir. Telefona ücretsiz ntfy uygulamasını kurup konuya abone olursun.</p>
     <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn sm pri" data-act="ntfy" data-a="on">Aç / konu oluştur</button><button class="btn sm" data-act="ntfy" data-a="show">Konuyu göster</button><button class="btn sm" data-act="ntfy" data-a="test">Deneme gönder</button><button class="btn sm" data-act="ntfy" data-a="off">Kapat</button></div>
     <p class="mut" style="margin-top:10px;word-break:break-all">${esc(PH.nmsg)}</p></section>
   <section class="card"><div class="ch"><span class="ct">Android · bilgisayardan bağımsız uygulama</span></div><p class="mut" style="margin-bottom:12px">Android Jarvis 3.0.8 ve sonrasında “QR ile kur” ile okut. QR anahtar içermez; 90 saniyelik ve tek kullanımlık kurulum kodudur. Kurulum sırasında telefon ve PC Tailscale üzerinden bağlı olmalı, PC’de HTTPS açık olmalı. Kurulumdan sonra uygulama PC kapalıyken de çalışır.</p>
     ${PH.app?`<canvas id="appqr"></canvas>`:`<button class="btn sm pri" data-act="phapp">${ic('phone')} Kurulum QR’ını göster</button>`}<p class="mut">${esc(PH.appmsg||'')}</p></section></div>`;
  const c=$('#phqr');if(c&&cur&&cur.qr)drawQR(c,cur.qr,190);const a=$('#appqr');if(a&&PH.app)drawQR(a,PH.app,220)};
ACT.phsel=el=>{PH.sel=+el.dataset.i;redrawTool()};
ACT.phuser=el=>{PH.user=el.dataset.u;PH.sel=0;PH.app=null;PH.appmsg='';redrawTool()};
ACT.phrenew=async()=>{await tryApi('phone_info',PH.user||'',true);PH.msg='Yeni QR hazır; 90 saniye içinde okut.';redrawTool()};
ACT.phon=async()=>{const r=await tryApi('phone_toggle',true);PH.msg=(r&&r.error)||'';after(0)};
ACT.phoff=()=>after(api('phone_toggle',false));
ACT.phauto=async()=>{await tryApi('phone_set',{auto:!PH.info.auto});redrawTool()};
ACT.phtoken=async ()=>{if(!await ask('Telefon anahtarı yenilensin mi? Eski QR adresleri ve Siri kestirmesi çalışmayacak; telefonda bir kez yeniden kurman gerekecek.'))return;const r=await tryApi('phone_token_reset');PH.info=r||PH.info;PH.msg='Anahtar yenilendi. Telefonda yeni QR/adresi kullan.';redrawTool()};
ACT.phscope=async el=>{const r=await tryApi('phone_set',{scope:el.dataset.v});PH.info=r||PH.info;redrawTool()};
ACT.tshttps=async el=>{const r=await tryApi('tailscale_https',el.dataset.v==='1');PH.info=r||PH.info;PH.msg=(r&&r.error)||((r&&r.https&&r.https.active)?'HTTPS hazır.':'');redrawTool()};
ACT.tsopen=async()=>{await tryApi('tailscale_action','open');setTimeout(redrawTool,1200)};
ACT.tsdownload=async()=>{await tryApi('tailscale_action','download')};
ACT.phcopy=async()=>{const u=((PH.info.urls||[])[PH.sel]||{}).url||'';try{await navigator.clipboard.writeText(u);toast('Adres kopyalandı.')}catch(e){toast(u)}};
ACT.ntfy=async el=>{const r=await tryApi('ntfy',el.dataset.a)||{};PH.nmsg=r.topic&&['on','show'].includes(el.dataset.a)?`${r.msg||'Konu:'} ${r.topic}`:(r.msg||(r.on?'Açık.':'Kapalı.'));after(0)};
ACT.phapp=async()=>{const r=await tryApi('phone_app_qr',PH.user||((S.snap||{}).user||{}).name||'');if(r&&r.ok){PH.app=r.qr;PH.appmsg=r.name+' için hazır.';clearTimeout(PH.appTimer);PH.appTimer=setTimeout(()=>{PH.app=null;redrawTool()},90000)}else PH.appmsg=(r&&r.msg)||'QR üretilemedi.';redrawTool()};

TV.mesaj=el=>{const c=(S.snap||{}).contacts||{},names=Object.keys(c);
  el.innerHTML=`<div class="grid2"><section class="card glow"><div class="ch"><span class="ct">Mesaj gönder</span></div><p class="mut" style="margin-bottom:10px">Jarvis WhatsApp Masaüstü’nü açıp mesajı yazar ve gönderir.</p>${names.length?'':'<p class="mut" style="margin-bottom:10px">Göndermek için önce Kişiler bölümünden bir kişi ekle.</p>'}
     <select class="sel" id="mto" style="width:100%;margin-bottom:10px">${names.map(n=>`<option>${esc(n)}</option>`).join('')}</select><textarea class="big" id="mtx" placeholder="Mesajını yaz…"></textarea>
     <button class="btn pri" style="margin-top:10px" data-act="wsend" ${names.length?'':'disabled'}>${ic('send')} Gönder</button></section>
<section class="card"><div class="ch"><span class="ct">Kişiler</span><span class="pill">${names.length}</span></div>
     ${names.map(n=>`<div class="srow"><span class="i">${ic('user')}</span><b style="flex:1">${esc(n)}</b><span class="mut">+${esc(c[n])}</span><button class="ab" data-act="cdel" data-n="${esc(n)}">${ic('trash')}</button></div>`).join('')||'<div class="empty">Kişi yok. “kişi ekle Ahmet 0532…” de ya da aşağıdan ekle.</div>'}
     <div class="ftool" style="margin-top:12px"><div class="search"><input id="cn" placeholder="Ad"></div><div class="search"><input id="cp" placeholder="0532 123 45 67"></div><button class="btn pri" data-act="cadd">${ic('plus')}</button></div></section></div>`};
ACT.cadd=async()=>{const r=await tryApi('contact_add',$('#cn').value,$('#cp').value);if(r){toast(r+' kaydedildi.');after(0)}};
ACT.cdel=async el=>{if(await ask(el.dataset.n+' silinsin mi?'))after(api('contact_delete',el.dataset.n))};
ACT.wsend=async()=>{const t=$('#mtx').value.trim();if(!t)return;await tryApi('whatsapp_send',$('#mto').value,t);toast('Mesaj gönderiliyor…');$('#mtx').value=''};


TV.rapor=async el=>{const r=await tryApi('learning_report',true)||{};
  el.innerHTML=`<section class="card glow"><div style="white-space:pre-wrap;line-height:1.6">${esc(r.text||r.summary||'Henüz rapor için yeterli kullanım yok.')}</div></section>`};
TV.tarama=async el=>{el.innerHTML='<section class="card"><div class="empty">Taranıyor…</div></section>';const r=await tryApi('scan')||[];
  el.innerHTML=`<section class="card">${r.map(x=>`<div class="srow"><span class="dot ${x.ok?(x.warn?'warn':''):'bad'}"></span><b style="min-width:200px">${esc(x.name)}</b><span class="mut">${esc(x.detail||'')}${x.fix?' — '+esc(x.fix):''}</span></div>`).join('')}</section>`};

// ======================================================================= AYARLAR
// Ayarlar: tek adres, 7 bölüm. keys = Ayarlar kutuları (drawSettings), tools = eski araç görünümleri (TV.*); alias/keys/tools eski adresleri bölüme çevirir.
const SECS=[
  {id:'ai',kw:'yapay zeka gemini groq model anahtar api ollama claude openai google gmail baglanti',t:'Yapay zekâ',i:'spark',c:'purple',alias:['baglanti']},
  {id:'ses',kw:'ses mikrofon konusma sesli yanit hey jarvis uyanma kulaklik',t:'Ses ve konuşma',i:'vol',c:'cyan',keys:['ses']},
  {id:'takvim',kw:'takvim gorev hatirlatma ajanda not',t:'Takvim ve görevler',i:'calendar',c:'orange',tools:['takvim'],alias:['gorev','araclar']},
  {id:'iletisim',kw:'telefon mesaj whatsapp qr kisi',t:'Telefon ve mesajlar',i:'phone',c:'green',tools:['telefon','mesaj']},
  {id:'ekran',kw:'ekran kamera dosya dosyalar belge paylasim goruntu',t:'Ekran ve dosyalar',i:'monitor',c:'blue',extra:'screenBox'},
  {id:'hesap',kw:'hesap kullanici gizlilik guvenlik hafiza hedef sifre',t:'Hesap ve gizlilik',i:'shield',c:'pink',keys:['kullanici','hafiza','guvenlik']},
  {id:'github',kw:'github git yukle guncelleme anahtar yedek surum',t:'GitHub',i:'branch',c:'blue',keys:['github']},
  {id:'sistem',kw:'sistem genel baslangic bildirim tarama rapor veri klasoru hakkinda guncelleme',t:'Sistem',i:'gear',c:'navy',keys:['genel','hakkinda'],tools:['veri','rapor','tarama'],lazy:{rapor:'Gelişim raporunu göster',tarama:'Sistem taramasını çalıştır'}}];
const TOOL_TITLE={telefon:'Telefon',mesaj:'Mesajlar',kb:'Bilgi tabanı',veri:'Veri klasörü',rapor:'Gelişim raporu',tarama:'Sistem taraması'};
const fold=x=>String(x||'').toLocaleLowerCase('tr').replace(/ç/g,'c').replace(/ğ/g,'g').replace(/ı/g,'i').replace(/ö/g,'o').replace(/ş/g,'s').replace(/ü/g,'u');
const sectionOf=x=>SECS.find(s=>s.id===x||(s.alias||[]).includes(x)||(s.keys||[]).includes(x)||(s.tools||[]).includes(x));
const sw=(k,on)=>`<button class="sw ${on?'on':''}" data-act="sset" data-k="${k}" data-v="${on?0:1}"></button>`;
const srow=(i,t,s,ctl)=>`<div class="srow2"><span class="i">${ic(i)}</span><div class="l"><b>${t}</b><small>${s}</small></div>${ctl}</div>`;
const sbox=(i,t,s,body)=>`<div class="sbox"><div class="sh"><span class="i">${ic(i)}</span><div><b>${t}</b><small>${s}</small></div></div>${body}</div>`;
const pad18=h=>`<div style="padding:12px 18px">${h}</div>`;
const field=(label,input,hint)=>`<div style="padding:10px 18px"><div class="fl" style="font-weight:600;margin-bottom:6px">${label}</div>${input}${hint?`<div class="mut" style="font-size:12.5px;margin-top:5px">${hint}</div>`:''}</div>`;
const inp=(id,ph,val,type)=>`<input class="sel" style="width:100%" id="${id}" ${type?`type="${type}"`:''} placeholder="${esc(ph||'')}" value="${esc(val||'')}" autocomplete="off">`;
PAGES.settings=pg=>{go('settings')};   // eski Ayarlar sayfası kaldırıldı: menüde ilgili yan sayfa açılır
async function loadUi(){S.ui=await tryApi('nx_settings')||{};applyTheme()}
const SX={};          // sayfa içi geçici durum (mesajlar)
// Yapay zekâ sayfası: her sağlayıcı bir kart; karta basınca yalnız onun bağlantısı açılır, durum kart renginde görünür.
const AI_CARDS=[['auto','Otomatik Model Seçimi','Jarvis seçer · anahtar gerekmez','<span class="lg" style="color:#7fd0ff">✦</span>'],
  ['gemini','Gemini','Google’ın güçlü modeli','<span class="lg" style="background:linear-gradient(135deg,#4285f4,#ea4335,#fbbc05,#34a853);-webkit-background-clip:text;color:transparent">G</span>'],
  ['groq','Groq','Ultra hızlı yanıtlar','<span class="lg" style="color:#ff4d6a">g</span>'],
  ['cloudflare','Cloudflare','İlave ücretsiz metin yedeği','<span class="lg">☁</span>'],
  ['ollama','Ollama','Yerel ve gizli çalışma','<span class="lg">🦙</span>'],
  ['custom','Özel API','İlave bağlantı ve kullanım rolü','<span class="lg">＋</span>'],
  ['google','Gmail ve Takvim','Google hesabın · salt okuma','<span class="lg">✉</span>'],
  ['youtube','YouTube','Çalışma videoları · isteğe bağlı','<span class="lg">▶</span>']];
function aiStates(sn){
  const l=sn.llm||{},q=l.groq||{},g=sn.google||{},y=sn.youtube||{},r=SX.router||{};
  const on=(v,t='Bağlı')=>v?['ok',t]:['bad','Bağlı değil'];
  return {auto:['ok','Hazır'],gemini:on(l.key),groq:on(q.key),cloudflare:on((SX.routerOwner===(sn.user||{}).slug?r.connection_states?.cloudflare:false)),ollama:on(l.ollama_up,'Çalışıyor'),
    custom:(r.custom_connections||l.custom_connections||[]).some(c=>c.enabled)?['ok','Etkin']:['warn','İsteğe bağlı'],google:g.token?['ok','Bağlı']:g.cred?['warn','İzin bekliyor']:['bad','Bağlı değil'],
    youtube:!y.key?['bad','Bağlı değil']:y.ok===false?['bad','Hata']:y.ok===true?['ok','Bağlı']:['warn','Deneniyor']};
}
function aiPage(sn,panels,extra=''){
  const l=sn.llm||{},raw=String(l.provider||'gemini').toLowerCase(),active=raw==='smart_router'?'auto':raw,st=aiStates(sn),sel=panels[SX.aiSel]?SX.aiSel:(panels[active]?active:'auto');
  const cards=AI_CARDS.map(([id,t,s,lg])=>`<button class="apv st-${st[id][0]} ${sel===id?'sel':''} ${active===id?'act':''}" data-act="aipick" data-k="${id}" title="${esc(st[id][1])}" aria-label="${esc(t+': '+st[id][1]+(active===id?' · şu an kullanılıyor':''))}" aria-pressed="${sel===id}">${lg}<span><b>${t}</b><small>${s}</small></span><i class="sd"></i></button>`).join('');
  const usable=['auto','ollama'].includes(sel);
  const use=usable?`<div class="apuse">${active===sel?'<span class="pill good">Şu an kullanılıyor</span>':`<button class="btn sm pri" data-act="sval" data-k="ai_mode" data-v="${sel}">Bunu kullan</button>`}</div>`:'';
  return `<div class="apgrid">${cards}</div>${use}<div class="appanel">${panels[sel]}</div>${$('#mn-win')?'':extra}`;
}
ACT.aipick=el=>{SX.aiSel=el.dataset.k;drawSettings()};
function screenBox(){const mode=(S.snap||{}).mode,on=m=>mode===m;
  return sbox('monitor','Ekran ve kamera','Sohbetin gözü. Yalnız sen açınca çalışır; önizleme yerelde kalır.',
    srow('monitor','Ekran paylaşımı','Sorular ekran görüntüsüyle yanıtlanır',sw2('screen',on('screen')))+
    srow('camera','Kamera','Sorular kamera görüntüsüyle yanıtlanır',sw2('camera',on('camera')))+
    srow('eye','Ekran sayfası','Analiz, görüntü alma, görselden metin çıkarma','<button class="btn sm" data-go="vision">Aç</button>'))+
  sbox('folder','Dosyalar','Son yüklediklerin sohbette kartlarla görünür.',
    srow('folder','Dosyalarım','Son 5 dosyanı sohbete getir','<button class="btn sm" data-say="dosyalarımı göster">Göster</button>')+
    srow('file','Dosyalar sayfası','Tüm dosyalar ve işlemler','<button class="btn sm" data-go="files">Aç</button>'));
}
const sw2=(m,on)=>`<button class="sw ${on?'on':''}" data-act="sharebtn" data-m="${m}"></button>`;
ACT.sharebtn=async el=>{const r=await tryApi('share',el.dataset.m);if(r)toast(r);await refresh();drawMiniPreview();if(settingsOpen())drawSettings()};
// Ses sayfası yan sayfada sekiz ayrı bölüm olur (her biri orbun çevresinde kendi orbunu alır). Alanlar ve Kaydet düğmesi aynıdır; tümü DOM'da kalır, ACT.vsave hepsini okur.
function sesBoxes({st,vo,devs,ls,sel,f,u,sn}){
  const save=pad18(`<button class="btn pri" data-act="vsave">${ic('check')} Kaydet</button> <span class="mut">${esc(SX.v||'')}</span>`);
  const sw1=(k,on)=>`<button class="sw ${on?'on':''}" data-act="sflag" data-k="${k}" data-v="${on?0:1}"></button>`;
  return sbox('mic','Mikrofon','Jarvis’in seni dinleyeceği cihaz ve dinleme anahtarı.',
      srow('mic','Mikrofon','“Hey Jarvis” dinlemesi',sw1('mic',f.mic))+
      field('Mikrofon cihazı',sel('micdev',[['','Windows varsayılanı'],...devs.map(d=>[d.name,d.name])],st.input_device||''),'Değişiklik için Jarvis’i yeniden başlat.')+
      field('Uzun iş beklerken dinleme',sel('mmic',[[1,'Açık · model beklerken dinle (varsayılan)'],[0,'Kapalı · yanıt bitene dek dinleme']],st.voice_mic_during_model_wait===false?0:1),'Model beklemesi mikrofonu kapatmaz; konuşma sırası, “sus” ve “dur” değişmez. Kapatırsan yanıt bitene dek dinlemez.')+save)
   +sbox('bell','Uyanma','“Hey Jarvis” ile uyanma.',
      srow('bell','Uyanma sesi','Dinlemeye geçince yumuşak bir ses',sw('wake_beep',u.wake_beep))+
      field('Uyanma hassasiyeti',sel('wsens',[[1,'1 · Zor uyanır'],[2,'2'],[3,'3 · Dengeli'],[4,'4'],[5,'5 · Çok kolay uyanır']],st.wake_sensitivity||3),'“Hey Jarvis”i kaçırıyorsa artır; kendi kendine uyanıyorsa azalt.')+save)
   +sbox('vol','Sesli Yanıt','Cevapları sesli okuma ve konuşma sesi.',
      srow('vol','Sesli yanıt','Cevapları sesli oku',sw1('speak',f.speak))+
      (vo.voices.length?field('Konuşma sesi',sel('vsel',vo.voices.map(v=>[v.key,v.name]),vo.voice)):'')+
      vresField(st,sel)+save)
   +sbox('user','Asistanın Adı','Uyanma ve konuşmada kullanılan ad.',
      field('Asistanın adı',inp('aname','Jarvis',st.assistant_name))+save)
   +sbox('check','Yerel Ses Tanıma','Konuş düğmesinde internetsiz ses tanıma.',
      field('Ses tanıma',sel('lstt',[[0,'Gemini / Google · mevcut akış'],[1,'Yerel · yalnız Konuş düğmesi']],st.local_stt_enabled?1:0),'Yerel seçimi yeniden başlatınca etkinleşir; yerel denemede “Hey Jarvis” ile arka plan uyanması kapalıdır. Cevap modeli ayrıca seçilir.')+
      field('Yerel ses modeli',sel('lsttmodel',[['small','small · başlangıç'],['base','base · daha hafif']],st.local_stt_model||'small'))+
      field('Yerel ses hızı',sel('lsttbeam',[[5,'En doğru · yavaş (varsayılan)'],[2,'Dengeli'],[1,'En hızlı · daha az doğru']],st.local_stt_beam||5),'İşlemcide yavaş kalırsa Dengeli ya da En hızlı dene.')+
      pad18(`<span class="mut">${esc(localSttText(ls))}</span> <button class="btn sm" data-act="lsttprepare">Modeli indir</button> <button class="btn sm" data-act="lsttrefresh">Durumu yenile</button>`)+save)
   +sbox('list','Düzeltmeler','Yanlış duyulan sözcükler ve özel kelimeler.',
      field('Yanlış duyulanlar',inp('sfix','city mall=steam',st.stt_fixes),'“yanlış=doğru”, virgülle ayır.')+
      field('Özel kelimeler',inp('swords','Nevzat Bey, EAE',st.stt_words),'Sık söylediğin adlar/terimler, virgülle.')+save)
   +sbox('target','Konuşma Tarzı','Yanıtların uzunluğu.',
      field('Yanıt uzunluğu',`<div class="seg">${[['kısa','Kısa'],['orta','Dengeli'],['uzun','Detaylı']].map(([v,t])=>`<button class="${(((sn||{}).prefs||{}).verbosity||'orta')===v?'on':''}" data-act="verb" data-v="${v}">${t}</button>`).join('')}</div>`))}
// Sonuç bildiriminin sesli okunması tek satırdan yönetilir: yan sayfa bölümleri ile Ayarlar
// sayfası aynı alanı, aynı kimlikle ve aynı açıklamayla gösterir.
function vresField(st,sel){return field('Sonuç bildirimi sesli okunsun',sel('vres',[[0,'Kapalı · yazılı kalsın (varsayılan)'],[1,'Açık · biten görev ve araştırma sonucu da seslendirilsin']],st.voice_announce_results?1:0),'Uzun işin sonucu ekranda yazılı kalır; bu açıkken ses kuyruğunda yanıtının arkasına sıraya girer, beş dakikadan eski sonuç yüksek sesle okunmaz.');}
// GitHub bölümü yan sayfada üç bölüm olur: bağlantı, yükle/al, güncelleme ve paketler (Ayarlar sayfası eski tek kutuyu korur).
function githubBoxes(up,dep){const msg=`<div class="mut" style="margin-top:8px;white-space:pre-wrap">${esc(SX.gh||up.sync_msg||'')}</div>`;
  return sbox('key','GitHub Bağlantısı','GitHub tek ana geliştirme kaynağıdır; Ev ve İş PC eşittir.',
      srow('refresh','Durum',up.token?('Bağlı'+(up.sha?' · sürüm '+esc(up.sha):'')):'Anahtar yok',`<span class="pill ${up.token?'good':'warn'}">${up.token?'Bağlı':'Yok'}</span>`)+
      field('GitHub anahtarı',inp('ghk','github_pat_…','','password'))+
      pad18(`<button class="btn sm pri" data-act="ghsave">${ic('check')} Kaydet ve dene</button> <button class="btn sm" data-act="ghverify">${ic('refresh')} Gerçek durumu doğrula</button>${msg}`))
   +sbox('up','Yükle ve Al','Kaynak değişiklikleri bu düğmeyle ayrı dala yüklenip PR açılır, main’e PR birleşince girer; açılışta yalnız kontrol yapılır.',
      pad18(`<button class="btn sm pri" data-act="ghpublish">${ic('up')} GitHub’a Yükle ↑</button> <button class="btn sm pri" data-act="ghpull">${ic('down')} GitHub’dan Al ↓</button>${up.sync_state==='diverged'?` <button class="btn sm pri" data-act="ghresolve">${ic('down')} Yedekle ve GitHub’dan Al</button>`:''}${msg}`))
   +sbox('refresh','Güncelleme ve Paketler','Yeni sürüm kontrolü ve paket sürümlerinin sabitlenmesi.',
      pad18(`<button class="btn sm" data-act="upd">Güncelleme var mı?</button>`)+
      srow('db','Paket sürümleri',dep.exists?`${dep.count||0} paket requirements.lock.txt ile sabit`:'Henüz sabitlenmedi · GitHub’a yüklerken otomatik sabitlenir',`<button class="btn sm" data-act="deplock">Şimdi sabitle</button>`))}
// Ekran ve Dosyalar yan sayfası (taslağa göre): önizleme + eylemler, paylaşım anahtarları, dosya bırakma alanı, son dosyalar, renkli durum satırı.
// Yalnız menü yan sayfasında (#mn-win) çizilir; Ayarlar sayfası eski kutuları (screenBox) kullanır.
function screenFilesPanel(){
  const mode=(S.snap||{}).mode,on=m=>mode===m;
  if(!S.files)loadFiles().then(()=>{if(settingsOpen())drawSettings()});
  const imgs=((S.files&&S.files.files)||[]).filter(f=>f.cat==='image').sort((a,b)=>b.mtime-a.mtime).slice(0,6);
  const imgRows=imgs.length?imgs.map(f=>`<div class="sfp-file"><span class="fi image">IMG</span><span class="fcn"><b>${esc(f.name)}</b><small>${fmtSize(f.size)} · ${fmtDate(f.mtime)}</small></span><button class="btn sm" data-act="fdo" data-p="${esc(f.path)}" data-a="gorsel">Analiz Et</button><button class="btn sm" data-act="fdo" data-p="${esc(f.path)}" data-a="metin">Metin</button></div>`).join(''):'<div class="empty">Henüz görsel yok. “Görsel yükle ve analiz et” ile ekleyebilirsin.</div>';
  const thumb=live=>`<div class="sfp-thumb ${live?'live':''}"><i class="c1"></i><i class="c2"></i><i class="c3"></i><i class="c4"></i>${live?'<img id="sfp-img" alt="Canlı önizleme" style="display:none">':''}<span class="sfp-ph">${live?'Görüntü bekleniyor…':'Önizleme için paylaşımı aç'}</span></div>`;
  const state=(live,name)=>`<div class="sfp-state ${live?'on':'off'}"><i></i><div><b>${name} ${live?'açık':'kapalı'}</b><small>${live?'Önizleme yalnız bu bilgisayarda kalır.':'Erişim şu anda devre dışı.'}</small></div></div>`;
  // Her işlev ayrı blok: yan sayfada her biri orbun çevresinde kendi küçük orbunu alır (menuSubsScan başlıkları bu bloklardan alır).
  return sbox('monitor','Ekran Paylaşımı','Sohbetin çözüm üretirken ekranına erişmesine izin ver.',srow('monitor','Ekran paylaşımı','Sorular ekran görüntüsüyle yanıtlanır',sw2('screen',on('screen')))+pad18(thumb(on('screen'))+state(on('screen'),'Ekran paylaşımı')))
   +sbox('camera','Kamera','Sorulara kamera görüntüsüyle yanıt alınmasını sağlar.',srow('camera','Kamera','Sorular kamera görüntüsüyle yanıtlanır',sw2('camera',on('camera')))+pad18(thumb(on('camera'))+state(on('camera'),'Kamera')))
   +sbox('eye','Ekranı İncele','Ekrandaki içeriği gör, açıkla, öner.',pad18(`<button class="btn pri" data-act="vis" data-a="say:ekranı analiz et">${ic('monitor')} Ekranı incele</button>`))
   +sbox('image','Ekran Görüntüsü Al','Jarvis gizlenir, görüntüden alan seçersin.',pad18(`<button class="btn pri" data-act="vis" data-a="act:capture">${ic('camera')} Görüntü al</button>`))
   +sbox('monitor','PC İşlemleri','Bilgisayarında adım adım yardım, görev ve pencere işlemleri.',pad18(`<button class="btn pri" data-act="pcguide">${ic('monitor')} PC yardımı iste</button> <button class="btn" data-act="pctask">PC görevi başlat</button> <button class="btn" data-say="açık pencereleri listele">Açık pencereler</button> <button class="btn" data-say="PC izinleri">PC izinleri</button>`))
   +sbox('image','Görsel Analiz','Bir resmi analiz ettir ya da içindeki yazıyı çıkar.',pad18(`<button class="btn pri" data-act="vis" data-a="act:image">${ic('image')} Görsel yükle ve analiz et</button> <button class="btn" data-act="vis" data-a="act:ocr">${ic('file')} Görselden metin çıkar</button>`))
   +sbox('image','Son Görseller','Yüklediğin son resimler ve yapılabilecek işlemler.',pad18(`<div class="sfp-files">${imgRows}</div>`))}
ACT.pctask=async()=>{const g=await askText('Jarvis hangi PC görevini yapsın? Örneğin: hesap makinesi 12 ile 7’yi topla','');if(g&&g.trim())return say('PC görevi: '+g.trim().slice(0,600))};
let sfpTimer=0;
async function sfpPoll(){clearTimeout(sfpTimer);const img=$('#sfp-img');if(!img)return;try{const d=await api('preview');if(d){img.src=d.startsWith('data:')?d:'data:image/png;base64,'+d;img.style.display='block';const ph=img.parentElement&&img.parentElement.querySelector('.sfp-ph');if(ph)ph.style.display='none'}}catch(e){}sfpTimer=setTimeout(sfpPoll,1500)}
function sfpBind(el){if(el.querySelector('#sfp-img'))sfpPoll()}
// Ayarlarda arama: eşleşmeyen satırlar ve kutular gizlenir (yazı varken tüm bölümler çizilir).
function applySettingsFilter(el){
  const q=(S.sq||'').trim().toLocaleLowerCase('tr');if(!q)return;let hits=0;
  el.querySelectorAll('.sbox').forEach(b=>{const head=((b.querySelector('.sh')||{}).textContent||'').toLocaleLowerCase('tr');
    if(head.includes(q)){hits++;return}
    let any=false;[...b.children].forEach(c=>{if(c.classList.contains('sh'))return;const hit=c.textContent.toLocaleLowerCase('tr').includes(q);c.style.display=hit?'':'none';if(hit){any=true;if(c.tagName==='DETAILS')c.open=true}});
    b.style.display=any?'':'none';if(any)hits++});
  if(!hits)el.insertAdjacentHTML('afterbegin','<div class="empty">Bu aramayla eşleşen ayar yok.</div>');
}
document.addEventListener('input',e=>{if(e.target&&e.target.id==='sq'){S.sq=e.target.value;clearTimeout(S._sqt);S._sqt=setTimeout(()=>{if(settingsOpen())drawSettings()},250)}});
function personaPreferencesBox(data){
  if(!data)return sbox('spark','Yanıt tercihleri','Şu an okunamadı. Lütfen yeniden dene.','');
  if(data.owner!==((S.snap||{}).user||{}).slug)return '';
  return sbox('spark','Yanıt tercihlerin','Bu seçimler anlatım tarzını değiştirir. Açık tercihin öğrenilmiş öneriden üstündür.',
    (data.controls||[]).map(row=>field(esc(row.label),`<select data-persona-key="${esc(row.key)}" data-owner="${esc(data.owner)}"><option value="">Açık tercih yok</option>${row.options.map(v=>`<option value="${esc(v)}" ${row.selected===v?'selected':''}>${esc(v.replaceAll('_',' '))}</option>`).join('')}</select>`,
      esc('Etkin: '+row.effective+' · '+row.source_label)+(row.has_learned?` <button class="btn sm" data-act="personaforget" data-k="${esc(row.key)}" data-owner="${esc(data.owner)}">Öğrenilmiş öneriyi unut</button>`:''))).join(''));
}
function bindPersonaPreferences(el){
  el.querySelectorAll('[data-persona-key]').forEach(control=>{control.onchange=()=>{
    if(control.dataset.owner!==((S.snap||{}).user||{}).slug)return;
    return sAfter(api('pref_set',control.dataset.personaKey,control.value||null).then(()=>toast('Tercihin kaydedildi.')));
  }});
}
ACT.personaforget=el=>{
  if(el.dataset.owner!==((S.snap||{}).user||{}).slug)return;
  return sAfter(api('presentation_reset',el.dataset.k,'learned'));
};
// Persona controls end.
async function drawSettings(){
  const el=$('#spane');if(!el)return;const u=S.ui||{},sn=S.snap||{},f=sn.flags||{},k=S.sset,l=sn.llm||{};let h='';
  const sec=sectionOf(k)||SECS[0],keys=S.sq?SECS.flatMap(x=>x.keys||[]):(sec.id==='ai'?[k==='baglanti'?'baglanti':'ai']:(sec.keys||[]));
  const theme=`<div class="seg">${[['dark','Koyu'],['light','Açık'],['system','Sistem']].map(([v,t])=>`<button class="${u.nx_theme===v?'on':''}" data-act="sval" data-k="nx_theme" data-v="${v}">${t}</button>`).join('')}</div>`;
  for(const k of keys){
  if(k==='genel'){h+=sbox('gear','Genel Ayarlar','Uygulamanın temel davranışları.',
    
    srow('power','Başlangıçta aç','Bilgisayar açıldığında JARVIS’i başlat',sw('autostart',u.autostart))+
    srow('gear','Arka planda çalış','Pencere kapansa bile sistem tepsisinde çalışmaya devam et',sw('tray',u.tray))+
    srow('bell','Bildirimler','Ekranda kısa bilgi mesajları',sw('nx_notify',u.nx_notify!==false))+
    srow('spark','Proaktif öneriler','İlgili bir risk ya da fırsat görünce “Burada dikkat et” / “Bunu da düşünebilirsin” der',sw('proactive_suggestions',u.proactive_suggestions!==false))+
    srow('spark','Ana ekran animasyonu','Hologram büst açılışta parçacıklardan kurulur; kapalıyken durağan görünür',sw('nx_bust',u.nx_bust!==false))+
    srow('spark','Hologram görünümü','Renk ve dağ seçimi bu tarayıcıda saklanır; turuncu yüz ve boğaz korunur',hologramChoices())+
    srow('grid','Küçük Jarvis','Pencereyi simge durumuna küçültünce köşede görünür',`<button class="sw ${u.widget_on!==false?'on':''}" data-act="wset" data-v="${u.widget_on!==false?0:1}"></button>`)+
    srow('globe','Şehir','Hava durumu için (boş = konumundan bulur)',`<input class="sel" id="city" style="max-width:200px" value="${esc((sn.prefs||{}).city||'')}" placeholder="İstanbul">`))}
  else if(k==='kullanici'){let keys=[];try{keys=await api('user_keys')}catch(e){}const me=(sn.user||{}).name;
    h+=sbox('user','Kullanıcılar','Her kullanıcı kendi hafızası, sohbeti ve kendi API anahtarıyla çalışır; anahtarlar paylaşılmaz.',
      (sn.users||[]).map(n=>srow('user',esc(n),(n===me?'Şu an aktif':'')+(keys.includes(n)?' · kendi Gemini anahtarı var':''),`<div style="display:flex;gap:6px">${n===me?'<span class="pill good">Aktif</span>':`<button class="btn sm" data-act="uswitch" data-n="${esc(n)}">Geç</button>`}<button class="btn sm" data-act="uren" data-n="${esc(n)}">${ic('edit')}</button><button class="btn sm" data-act="ukey" data-n="${esc(n)}" title="Kendi Gemini anahtarı">${ic('key')}</button>${n===me?'':`<button class="btn sm" data-act="udel" data-n="${esc(n)}">${ic('trash')}</button>`}</div>`)).join('')+
      pad18(`<button class="btn sm" data-act="unew">${ic('plus')} Yeni kullanıcı</button> <span class="mut">${esc(SX.umsg||'')}</span>`))+
    sbox('target',$('#mn-win')?'Hedefler':'Hedefler ve konuşma tarzı',`${esc(me||'')} için`,
      ($('#mn-win')?'':field('Yanıt uzunluğu',`<div class="seg">${[['kısa','Kısa'],['orta','Dengeli'],['uzun','Detaylı']].map(([v,t])=>`<button class="${((sn.prefs||{}).verbosity||'orta')===v?'on':''}" data-act="verb" data-v="${v}">${t}</button>`).join('')}</div>`))+
      (sn.goals||[]).map((g,i)=>srow('target',esc(g),'',`<button class="btn sm" data-act="gdel" data-i="${i}">${ic('trash')}</button>`)).join('')+
      field('Yeni hedef',inp('goal','örn. İngilizce öğreniyorum'),'Hedefin varsa Jarvis ona göre yardımcı olur. Enter’a bas.'))}
  else if(k==='github'){let up={},dep={};try{[up,dep]=await Promise.all([api('update_status'),api('dependency_lock_status')])}catch(e){}
    if($('#mn-win')){h+=githubBoxes(up,dep)}else h+=
      sbox('branch','GitHub ana sürüm / senkronizasyon','GitHub tek ana geliştirme kaynağıdır. Ev/İş PC eşittir. Yerel kaynak değişiklikleri “git yükle” komutuyla ayrı dala yüklenip PR açılır; main’e PR birleşince girer. Açılışta yalnız kontrol yapılır.',
        srow('refresh','Durum',up.token?('Bağlı'+(up.sha?' · sürüm '+esc(up.sha):'')):'Anahtar yok',`<span class="pill ${up.token?'good':'warn'}">${up.token?'Bağlı':'Yok'}</span>`)+
        field('GitHub anahtarı',inp('ghk','github_pat_…','','password'))+pad18(`<button class="btn sm pri" data-act="ghsave">${ic('check')} Kaydet ve dene</button> <button class="btn sm" data-act="ghverify">${ic('refresh')} Gerçek durumu doğrula</button> <button class="btn sm pri" data-act="ghpublish">${ic('up')} GitHub’a Yükle ↑</button> <button class="btn sm pri" data-act="ghpull">${ic('down')} GitHub’dan Al ↓</button>${up.sync_state==='diverged'?` <button class="btn sm pri" data-act="ghresolve">${ic('down')} Yedekle ve GitHub’dan Al</button>`:''} <button class="btn sm" data-act="upd">Güncelleme var mı?</button> <div class="mut" style="margin-top:8px;white-space:pre-wrap">${esc(SX.gh||up.sync_msg||'')}</div>`)+
        srow('db','Paket sürümleri',dep.exists?`${dep.count||0} paket requirements.lock.txt ile sabit`:'Henüz sabitlenmedi · GitHub’a yüklerken otomatik sabitlenir',`<button class="btn sm" data-act="deplock">Şimdi sabitle</button>`));}
  else if(k==='baglanti'||k==='ai'){let up={},ho={},goa={},dep={},gsu={},rq={};try{[up,ho,goa,dep,gsu,rq]=await Promise.all([api('update_status'),api('handoff_status'),api('google_oauth_status'),api('dependency_lock_status'),api('google_setup_status').catch(()=>({})),api('role_qualification_status').catch(()=>({}))])}catch(e){}const g=sn.google||{},q=l.groq||{};
    const learnBox=sbox('db','Öğrenme','Jarvis seninle konuşurken.',
      srow('db','Konuşmalardan öğren','Öğrendiklerini önce onayına sunar',sw('learn_from_chat',sn.learn_on)));
    const pGem=sbox('key','Gemini · '+esc((sn.user||{}).name||'Kullanıcı'),'Bu anahtar yalnız aktif kullanıcıya aittir. Anahtar: aistudio.google.com/apikey',
        srow('key','Durum',l.key?'Kayıtlı'+(l.key_tail?' …'+esc(l.key_tail):''):'Anahtar yok',`<span class="pill ${l.key?'good':'bad'}">${l.key?'Aktif':'Yok'}</span>`)+
        srow('spark','Model kontrolü',esc((sn.model_validation||{}).message||'Henüz doğrulanmadı'),'<button class="btn sm" data-act="modelcheck">Kontrol et</button>')+
        srow('spark','Bu sürümü doğrula',esc(roleQualText(rq)),`<button class="btn sm" data-act="rolequal"${rq.running?' disabled':''}>Doğrula</button> <button class="btn sm" data-act="rolequalrefresh">Durumu yenile</button>`)+
        field('Yeni anahtar',inp('gk','AIza…','','password'),'Boş bırakırsan mevcut anahtar korunur.')+pad18(`<button class="btn sm pri" data-act="gksave">${ic('check')} Kaydet ve dene</button> <span class="mut">${esc(SX.gk||'')}</span>`));
    const gsDone=(id)=>({json:gsu.cred==='hazir',baglan:!!gsu.token}[id]);
    const gsBox=(gsu.steps&&!g.token)?sbox('list','Google kurulum sihirbazı','Her kullanıcı kendi Google Cloud projesini açar (yaklaşık 10 dakika). Adımları sırayla yap; “Aç” ilgili Google sayfasını açar.',
        gsu.steps.map((st,i)=>{const d=gsDone(st.id);const cur=gsu.next===st.id;return srow(d?'check':'file',(i+1)+'. '+esc(st.title),esc(st.text)+(st.id==='json'&&gsu.cred_msg?' · '+esc(gsu.cred_msg):''),
          st.url?`<button class="btn sm${cur?' pri':''}" data-act="gsopen" data-v="${esc(st.id)}">Aç</button>`:(d!==undefined?`<span class="pill ${d?'good':'warn'}">${d?'Tamam':'Bekliyor'}</span>`:''))}).join('')+
        (gsu.packages===false?pad18('<span class="mut">Google paketleri kurulu değil: kurulum.bat çalıştırılmış olmalı.</span>'):'')):'';
    const pGoogle=sbox('mail','Gmail ve Google Takvim','Salt okuma. Google Cloud’dan indirdiğin client_secret…json dosyasını seç, sonra Bağlan.',
        srow('mail','Durum',g.token?'Bağlı':g.cred?'İzin bekliyor':'Kurulmadı',`<span class="pill ${g.token?'good':'warn'}">${g.token?'Bağlı':'Değil'}</span>`)+
        srow('shield','OAuth yayın durumu',goa.production?'In production · Testing izin uyarısı kapalı':'Testing / doğrulanmadı · Google izni bir süre sonra düşürebilir',`<div style="display:flex;gap:6px"><button class="btn sm" data-act="gprodopen">Google Cloud’u aç</button>${goa.production?'<span class="pill good">Production</span>':'<button class="btn sm pri" data-act="gprodok">Production yaptım</button>'}</div>`)+
        pad18(`<button class="btn sm" data-act="gpick">${ic('file')} JSON seç</button> <button class="btn sm pri" data-act="gconn">${ic('link')} Bağlan</button> <button class="btn sm" data-act="greset">Sıfırla</button><div class="mut" style="margin-top:8px;white-space:pre-wrap">${esc(SX.g||'')}</div>`)+
        srow('home','Bu bilgisayar','Ev/iş devir listesi (Google Görevler) için',`<div class="seg">${[['is','İş'],['ev','Ev']].map(([v,t])=>`<button class="${ho.place===v?'on':''}" data-act="hoplace" data-v="${v}">${t}</button>`).join('')}</div>`)+
        pad18(`<button class="btn sm" data-act="hoconn">${ic('link')} Görevler iznini ver</button> <span class="mut">${esc(SX.ho||(ho.ready?'Görevler izni kayıtlı; düşerse buradan yenile.':''))}</span>`));
    const lb=SX.lb||l.local_backend||'ollama',lbSame=lb===(l.local_backend||'ollama');
    const LB_URL={ollama:'http://127.0.0.1:11434',lmstudio:'http://127.0.0.1:1234/v1',llamacpp:'http://127.0.0.1:8080/v1'};
    const pOll=sbox('bolt',esc(l.local_label||'Ollama')+' · Yerel model','Bilgisayarında çalışan yerel model; internet ve anahtar gerekmez. Ollama, LM Studio veya llama.cpp (llama-server) seçilebilir; hepsi isteğe bağlıdır.',
      srow('spark','Durum',l.ollama_up?'Çalışıyor':'Kurulu değil veya çalışmıyor','')+
      srow('cpu','Yerel sunucu','LM Studio ve llama.cpp OpenAI uyumlu /v1 uç noktasıyla bağlanır',`<div class="seg">${[['ollama','Ollama'],['lmstudio','LM Studio'],['llamacpp','llama.cpp']].map(([v,t])=>`<button class="${lb===v?'on':''}" data-act="lbpick" data-v="${v}">${t}</button>`).join('')}</div>`)+
      field('Uç nokta',inp('lburl',LB_URL[lb],lbSame?l.ollama_url:''))+
      pad18(`<button class="btn sm pri" data-act="lbsave">Sunucuyu kaydet ve dene</button> <span class="mut">${esc(SX.lbm||'')}</span>`)+
      field('Yerel model · '+esc((sn.user||{}).name||'Kullanıcı'),inp('om','llama3.2',l.local_model),'Yalnız bu kullanıcı için. Ollama’da indirdiğin model adını yaz (ör. llama3.2, qwen2.5:7b); LM Studio/llama.cpp’de boş bırakırsan sunucudaki ilk model kullanılır.')+
      pad18(`<button class="btn sm pri" data-act="omsave">Modeli kaydet</button> <button class="btn sm" data-act="connecthelp" data-provider="ollama">Ollama Kurulumu</button> <span class="mut">${esc(SX.om||'')}</span>`));
    const pGroq=sbox('bolt','Groq · '+esc((sn.user||{}).name||'Kullanıcı')+' (isteğe bağlı)','Bu anahtar yalnız aktif kullanıcıya aittir. Anahtar: console.groq.com/keys',
        srow('bolt','Groq',q.key?'Kayıtlı …'+esc(q.tail||''):'Yok','')+field('Groq anahtarı',inp('qk','gsk_…','','password'))+field('Groq modeli',inp('qm','openai/gpt-oss-120b',q.model))+pad18(`<button class="btn sm pri" data-act="qsave">Kaydet ve dene</button> <span class="mut">${esc(SX.q||'')}</span>`));
    const pYt=sbox('play','YouTube · Çalışma videoları (isteğe bağlı)','Çalışma ekranında anlatılan konunun videoları yanda listelensin. Anahtar: console.cloud.google.com › YouTube Data API v3 › Kimlik Bilgileri › API anahtarı',
        srow('play','YouTube',(()=>{const y=sn.youtube||{};return !y.key?'Yok — yalnız “YouTube’da ara” bağlantısı':y.ok===true?'Kayıtlı · çalışıyor':y.ok===false?'Kayıtlı · HATA: '+esc(y.msg||''):'Kayıtlı · deneniyor…'})(),'')+field('YouTube API anahtarı',inp('ytk','AIza…','','password'))+pad18(`<button class="btn sm pri" data-act="ytsave">Kaydet</button>${sn.youtube_key?' <button class="btn sm" data-act="ytdel">Sil</button>':''}`));
    h=aiPage(sn,{auto:routerBox('policy'),gemini:pGem,groq:pGroq,ollama:pOll,custom:routerConnectionsBox(sn),cloudflare:cloudflareBox(sn),google:gsBox+pGoogle,youtube:pYt},learnBox)}
  else if(k==='ses'){let st={},vo={voices:[]},devs=[],ls={};try{[st,vo,devs,ls]=await Promise.all([api('settings'),api('voice_options'),api('input_devices'),api('local_stt_status')])}catch(e){}
    const sel=(id,opts,cur)=>`<select class="sel" id="${id}" style="width:100%">${opts.map(([v,t])=>`<option value="${esc(v)}" ${String(cur)===String(v)?'selected':''}>${esc(t)}</option>`).join('')}</select>`;
    h+=$('#mn-win')?sesBoxes({st,vo,devs,ls,sel,f,u,sn}):sbox('vol','Ses','Konuşma ve dinleme.',
      srow('mic','Mikrofon','“Hey Jarvis” dinlemesi',`<button class="sw ${f.mic?'on':''}" data-act="sflag" data-k="mic" data-v="${f.mic?0:1}"></button>`)+
      srow('vol','Sesli yanıt','Cevapları sesli oku',`<button class="sw ${f.speak?'on':''}" data-act="sflag" data-k="speak" data-v="${f.speak?0:1}"></button>`)+
      (vo.voices.length?field('Konuşma sesi',sel('vsel',vo.voices.map(v=>[v.key,v.name]),vo.voice)):'')+
      vresField(st,sel)+
      field('Asistanın adı',inp('aname','Jarvis',st.assistant_name))+
      '<details class="sdet"><summary>Gelişmiş ses ayarları</summary>'+
      srow('bell','Uyanma sesi','Dinlemeye geçince yumuşak bir ses',sw('wake_beep',u.wake_beep))+
      field('Ses tanıma',sel('lstt',[[0,'Gemini / Google · mevcut akış'],[1,'Yerel · yalnız Konuş düğmesi']],st.local_stt_enabled?1:0),'Yerel seçimi yeniden başlatınca etkinleşir; yerel denemede “Hey Jarvis” ile arka plan uyanması kapalıdır. Cevap modeli ayrıca seçilir.')+
      field('Yerel ses modeli',sel('lsttmodel',[['small','small · başlangıç'],['base','base · daha hafif']],st.local_stt_model||'small'))+
      field('Yerel ses hızı',sel('lsttbeam',[[5,'En doğru · yavaş (varsayılan)'],[2,'Dengeli'],[1,'En hızlı · daha az doğru']],st.local_stt_beam||5),'İşlemcide yavaş kalırsa Dengeli ya da En hızlı dene. Hemen geçerli olur, yeniden başlatma gerekmez.')+
      pad18(`<span class="mut">${esc(localSttText(ls))}</span> <button class="btn sm" data-act="lsttprepare">Modeli indir</button> <button class="btn sm" data-act="lsttrefresh">Durumu yenile</button>`)+
      field('Uyanma hassasiyeti',sel('wsens',[[1,'1 · Zor uyanır'],[2,'2'],[3,'3 · Dengeli'],[4,'4'],[5,'5 · Çok kolay uyanır']],st.wake_sensitivity||3),'“Hey Jarvis”i kaçırıyorsa artır; kendi kendine uyanıyorsa azalt.')+
      field('Yanlış duyulanlar',inp('sfix','city mall=steam',st.stt_fixes),'“yanlış=doğru”, virgülle ayır.')+
      field('Özel kelimeler',inp('swords','Nevzat Bey, EAE',st.stt_words),'Sık söylediğin adlar/terimler, virgülle.')+
      field('Mikrofon cihazı',sel('micdev',[['','Windows varsayılanı'],...devs.map(d=>[d.name,d.name])],st.input_device||''),'Değişiklik için Jarvis’i yeniden başlat.')+
      field('Uzun iş beklerken dinleme',sel('mmic',[[1,'Açık · model beklerken dinle (varsayılan)'],[0,'Kapalı · yanıt bitene dek dinleme']],st.voice_mic_during_model_wait===false?0:1),'Model beklemesi mikrofonu kapatmaz; konuşma sırası, “sus” ve “dur” değişmez. Kapatırsan yanıt bitene dek dinlemez.')+
      '</details>'+
      pad18(`<button class="btn pri" data-act="vsave">${ic('check')} Kaydet</button> <span class="mut">${esc(SX.v||'')}</span>`))}
  else if(k==='hafiza'){const pf=sn.pending_facts||[];
    let pv=null;try{pv=await api('presentation_preferences')}catch(e){}h+=personaPreferencesBox(pv);
    h+=(sn.learning_status?.state==='error'?sbox('spark','Öğrenme durumu',esc(sn.learning_status.error||'Bilgi çıkarılamadı.'),''):'')+(pf.length?sbox('spark','Onay bekleyenler','Konuşmalarından öğrendim. Onaylarsan hafızaya geçer.',pf.map((x,i)=>srow('spark',esc(x),'',`<div style="display:flex;gap:6px"><button class="btn sm pri" data-act="pfok" data-i="${i}">${ic('check')}</button><button class="btn sm" data-act="pfno" data-i="${i}">${ic('x')}</button></div>`)).join('')+pad18(`<button class="btn sm pri" data-act="pfok" data-i="-1">Hepsini kaydet</button> <button class="btn sm" data-act="pfno" data-i="-1">Hiçbirini kaydetme</button>`)):'')+
      sbox('db','Bildiklerim','Jarvis’in senin hakkında bildikleri.',(sn.facts||[]).map((x,i)=>srow('check',esc(x),'',`<button class="btn sm" data-act="fdel" data-i="${i}">${ic('trash')}</button>`)).join('')+field('Yeni bilgi',inp('fact','örn. Kedimin adı Pamuk'),'Enter’a bas.'))+
      sbox('list','Öğrettiğin kurallar','Jarvis bunlara her konuşmada uyar.',(sn.rules||[]).map((x,i)=>srow('list',esc(x),'',`<button class="btn sm" data-act="rdel" data-i="${i}">${ic('trash')}</button>`)).join('')+field('Yeni kural',inp('rule','örn. Cevapların kısa olsun'),'Enter’a bas.')+
        srow('db','Konuşmalardan öğren','Öğrendiklerini önce onayına sunar',sw('learn_from_chat',sn.learn_on))+
        srow('trash','Konuşma geçmişi','Tüm sohbet kayıtları','<button class="btn sm" data-act="hclear">Temizle</button>'))}
  else if(k==='guvenlik'){let d=null;try{d=await api('privacy_get')}catch(e){}
    h+=d?sbox('shield','Gizlilik modu','Verilerinin nereye gittiğini sen belirlersin.',Object.entries(d.modes||{}).map(([m,t])=>srow(m===d.mode?'shieldok':'shield',esc(t.split(' — ')[0]),esc(t.split(' — ')[1]||''),m===d.mode?'<span class="pill good">Seçili</span>':`<button class="btn sm" data-act="pmode" data-k="${m}">Seç</button>`)).join(''))+
      sbox('lock','Koruma','',srow('eye','Hassas bilgiyi gizle','Anahtar, e-posta, kart, IBAN, telefon buluta gitmeden maskelenir',`<button class="sw ${d.redact?'on':''}" data-act="ptog" data-k="redact" data-v="${d.redact?0:1}"></button>`)+
        srow('check','Hassas işlemlerde onay iste','Mesaj gönderme, bilgisayarı kapatma, dosya taşıma',`<button class="sw ${d.approve?'on':''}" data-act="ptog" data-k="approve" data-v="${d.approve?0:1}"></button>`)+
        srow('key','API anahtarı',d.key_protected?'Windows hesabınla şifreli saklanıyor':'Korumalı değil; Bağlantılar’da yeniden kaydet',`<span class="pill ${d.key_protected?'good':'warn'}">${d.key_protected?'Korumalı':'Düz'}</span>`)+
        srow('lock','Yerel veriler','Anahtarlar ve ayarlar kullanıcı hesabında tutulur','<span class="pill good">Açık</span>')):'<div class="empty">Gizlilik bilgisi alınamadı.</div>'}
  else if(k==='araclar'){h+=toolsBox()}
  else{h+=sbox('info','Hakkında','JARVIS — Senin Yapay Zekâ Asistanın',`<div id="about" style="padding:14px 18px" class="mut">Yükleniyor…</div>`+
      pad18(`<button class="btn sm" data-act="upd">${ic('refresh')} Güncelleme var mı?</button> <button class="btn sm" data-act="restart">${ic('power')} Yeniden Başlat</button> <button class="btn sm" data-act="olog">${ic('file')} Kayıt dosyası</button>`));
    tryApi('update_status').then(r=>{const a=$('#about');if(a&&r)a.innerHTML=`Sürüm: <b>${esc(r.sha||'—')}</b><br>Son güncelleme: ${esc(r.msg||'—')} ${esc(r.applied||'')}`})}
  
  }
  if(S.sq)h+=screenBox();
  if(!S.sq){
    if(sec.id==='ai'){const sn2=S.snap||{};h=`<section class="card glow aihub"><div class="aihub-head"><span class="ib purple">${ic('spark')}</span><div><h2>Yapay Zekâ</h2><p>Bir yapay zekâya dokun, bağlantısı altta açılsın. Renk durumu gösterir: <span class="lgd ok"></span>bağlı <span class="lgd warn"></span>bekliyor <span class="lgd bad"></span>bağlı değil.</p></div><span class="pill">${ic('user')} ${esc((sn2.user||{}).name||'Kullanıcı')}</span></div></section>`+h}
    if(sec.extra==='screenBox')h+=$('#mn-win')?screenFilesPanel():screenBox();
    for(const t of sec.tools||[]){const lz=(sec.lazy||{})[t],ttl=(sec.tools.length>1||sec.keys)&&TOOL_TITLE[t]?`<div class="sback"><b>${TOOL_TITLE[t]}</b></div>`:'';
      h+=ttl+(lz?`<div data-tv="${t}" data-lazy="1"><button class="btn" data-act="tvload">${lz}</button></div>`:`<div data-tv="${t}"></div>`)}
  }
  if(S.sset!==k||$('#spane')!==el||((S.snap||{}).user||{}).name!==(sn.user||{}).name)return;el.innerHTML=h;{const sqi=$('#sq');if(sqi&&sqi.value!==(S.sq||''))sqi.value=S.sq||''}applySettingsFilter(el);if(S.sq){const q=fold(S.sq.trim()),hit=SECS.filter(x=>fold(x.t+' '+(x.kw||'')).includes(q));if(hit.length){el.querySelector('.empty')?.remove();el.insertAdjacentHTML('afterbegin','<div class="sbox"><div class="sh"><div><b>Bölümler</b><small>Eşleşen bölümü aç</small></div></div>'+hit.map(x=>`<button class="srow2" data-act="smenu" data-k="${x.id}" style="width:100%;text-align:left"><span class="ib sm ${x.c}">${ic(x.i)}</span><div class="l"><b>${x.t}</b></div><span class="chev">${ic('chev')}</span></button>`).join('')+'</div>')}}el.querySelectorAll('[data-tv]:not([data-lazy])').forEach(d=>TV[d.dataset.tv](d));
  if(k==='baglanti'||k==='ai'||k==='github')installConnectionHelp(el);
  if(k==='ekran'&&$('#mn-win'))sfpBind(el);
  const enter=(id,fn)=>{const i=$('#'+id);if(i)i.onkeydown=e=>{if(e.key==='Enter'&&i.value.trim())fn(i.value.trim())}};
  enter('goal',v=>sAfter(api('goal_add',v)));enter('fact',v=>sAfter(api('fact_add',v)));enter('rule',v=>sAfter(api('rule_add',v).then(toast)));
  const city=$('#city');if(city)city.onchange=()=>sAfter(api('pref_set','city',city.value.trim()).then(()=>toast('Kaydedildi.')));
  bindPersonaPreferences(el);
  const vs=$('#vsel');if(vs)vs.onchange=()=>tryApi('voice_set',vs.value);
}
function connectionHelpProvider(title){
  return [['gemini',/^Gemini/],['github',/^GitHub/],['google',/^Gmail/],['groq',/^Groq/],['custom',/^Özel API/],['youtube',/^YouTube/],['ollama',/^Ollama/]].find(([,re])=>re.test(title))?.[0]||'';
}
function installConnectionHelp(el){
  if(!el.querySelectorAll)return;
  el.querySelectorAll('.sbox .sh').forEach(head=>{
    const key=connectionHelpProvider(head.querySelector('b')?.textContent||'');
    if(!key||head.querySelector('[data-act="connecthelp"]'))return;
    const button=document.createElement('button');button.className='btn sm connection-help';button.dataset.act='connecthelp';button.dataset.provider=key;button.textContent='Nasıl Bağlanırım?';head.appendChild(button);
  });
}
let closeConnectionGuide=null;
ACT.connecthelp=el=>{
  const key=el.dataset.provider;if(!JarvisGuide.hasProvider(key))return;
  if(closeConnectionGuide)closeConnectionGuide();
  const previous=document.activeElement,overlay=document.createElement('div');
  overlay.className='jdlg connection-guide-dialog';
  overlay.innerHTML='<div class="jbox connection-guide-box" role="dialog" aria-modal="true" aria-label="Bağlantı Kurulum Rehberi"><div class="connection-guide-head"><div><small>JARVIS • BAĞLANTI MERKEZİ</small><b>Adım Adım Kurulum</b></div><button class="btn sm guide-close">Kapat</button></div><div class="connection-guide-body"></div></div>';
  const body=overlay.querySelector('.connection-guide-body');
  JarvisGuide.connections(body,key);
  const close=()=>{overlay.remove();document.removeEventListener('keydown',keydown,true);closeConnectionGuide=null;if(previous?.isConnected)previous.focus()};
  const keydown=e=>{if(e.key==='Escape'){e.stopPropagation();close()}else if(e.key==='Tab'){const items=[...overlay.querySelectorAll('button,input,a')].filter(x=>!x.disabled);const first=items[0],last=items[items.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}}};
  closeConnectionGuide=close;overlay.querySelector('.guide-close').onclick=close;
  overlay.addEventListener('click',e=>{if(e.target===overlay)close()});
  document.body.appendChild(overlay);document.addEventListener('keydown',keydown,true);overlay.querySelector('.guide-close').focus();
};const sAfter=async p=>{try{await p}catch(e){toast(e.message,'bad')}await refresh();drawSettings()};
function routerBox(mode){   // Otomatik Model Seçimi kartı
  const owner=((S.snap||{}).user||{}).slug;if(SX.routerOwner!==owner){SX.router=null;SX.routerOwner=owner}const r=SX.router||{};
  if(!SX.routerLoading&&!SX.router){SX.routerLoading=true;api('smart_router_status').then(v=>{if(SX.routerOwner!==owner){SX.routerLoading=false;return}SX.router=v;SX.routerLoading=false;if(S.sset==='baglanti'||S.sset==='ai')drawSettings()}).catch(()=>{SX.routerLoading=false})}
  const limits=r.application_limits||{daily_requests:200,max_parallel:2,interactive_reserved:1,interactive_daily_reserve:20};
  const maintenance=['gemini','groq','cloudflare'].map(provider=>field(provider+' proje/kota grubu',inp('router-project-'+provider,'Aynı projeyi paylaşan hesaplarda aynı ad',(r.account_scopes||{})[provider]||''))+pad18(`<button class="btn sm" data-act="routerfree" data-provider="${provider}">${provider} ücretsiz plan beyanını güncelle</button>`)).join('');
  const traces=(r.traces||[]).map(t=>`<details><summary>${esc(t.request_id)} · ${esc(t.profile)} · ${esc(t.state)}</summary><p>${esc(t.policy_version)} · ${esc(t.provider||'—')} / ${esc(t.model||'—')} · ${t.duration_ms??'—'} ms</p><p>Ana / yedek: ${(t.planned||[]).map(x=>esc(x.provider+' / '+x.model)).join(' → ')||'Uygun aday yok'}</p><p>Rezervasyon üst sınırı: ${t.reservation?.token_upper_bound??'bilinmiyor'} token; parasal sınır ${t.reservation?.cost_upper_bound_microusd??'bilinmiyor'} µUSD. Gerçek kullanım: giriş ${t.usage?.input_tokens??'bilinmiyor'}, çıkış ${t.usage?.output_tokens??'bilinmiyor'}, reasoning ${t.usage?.reasoning_tokens??'bilinmiyor'}, cache ${t.usage?.cached_tokens??'bilinmiyor'}. İlk token: ${t.first_token_ms??'ölçülmedi'}. ${esc(t.finish_reason||'')}</p><p>${(t.attempts||[]).map(x=>esc(x.model+' · '+(x.kind||x.state))).join('; ')}</p><p>${(t.skipped||[]).map(x=>esc(x.provider+': '+x.reason)).join('; ')}</p></details>`).join('');
  if(mode==='policy'||(!mode&&S.sset==='ai'))return sbox('bolt','Otomatik Model Seçimi','Jarvis işe göre bağlı sağlayıcılar arasından seçim yapar. Bu özellik için ayrı API anahtarı gerekmez.',
    pad18(`<label class="router-confirm"><input type="checkbox" id="rfree" ${r.cloud_free_confirmed?'checked':''}><span>Hazır bulut hesaplarım ücretsiz planda; ücretli faturalama kapalı.</span></label><label class="router-confirm"><input type="checkbox" id="rgchat" ${(r.gemini_scopes||[]).includes('conversation')?'checked':''}><span>Gemini konuşma ve anlamlandırma için gerekli bağlamı kullanabilir.</span></label><label class="router-confirm"><input type="checkbox" id="rgselected" ${(r.gemini_scopes||[]).includes('selected_content')?'checked':''}><span>Gemini iş için seçtiğim dosya ve görüntüleri analiz edebilir.</span></label><p class="mut">Google ücretsiz hizmete gönderilen içeriği ürün geliştirme/eğitim için kullanabilir. Bu kapsam yalnız senin hesabına aittir ve geri alınabilir; yerel/gizli mod daha dar kalır.</p><div class="connection-actions"><button class="btn sm pri" data-act="routerpolicy">Tercihi Kaydet</button><button class="btn sm" data-act="routerstatus">Model Yetenekleri</button></div><p class="mut">Hazır havuz Gemini, uygun Groq/Cloudflare ve isteğe bağlı yerel modellerdir. Diğer sağlayıcıları Özel API alanından rol seçerek ekle. Ücretsiz kota ve model uygunluğu ayrıca doğrulanır. Kalan kota bilinmiyorsa bilinmiyor kalır; uygulama tavanları sağlayıcının gerçek limiti değildir.</p>`)+
    field('Günlük uygulama çağrı tavanı',inp('router-daily','200',limits.daily_requests))+field('En fazla eşzamanlı bulut çağrısı',inp('router-parallel','2',limits.max_parallel))+field('Sohbet için ayrılan eşzamanlı pay',inp('router-reserved','1',limits.interactive_reserved))+field('Sohbete ayrılan günlük çağrı payı',inp('router-daily-reserve','20',limits.interactive_daily_reserve??20))+maintenance+pad18(`<button class="btn sm" data-act="routerlocalcaps">Yerel modelin görüntü yeteneğini kontrol et</button> <span class="mut">${esc(SX.localCapsMsg||'Model indirilmez veya inference yapılmaz. Ollama runtime bilgisi 5 dakika geçerlidir; diğer backend desteği doğrulanmadan açılmaz.')}</span>`)+pad18(traces||'Bu kullanıcı için kayıtlı model çağrısı yok.'));
  return '';
}
ACT.routerpolicy=async()=>{const owner=((S.snap||{}).user||{}).slug;try{const r=await api('smart_router_save',$('#rfree').checked,[['conversation','rgchat'],['selected_content','rgselected']].filter(([,id])=>$('#'+id).checked).map(([scope])=>scope),owner,{daily_requests:Number($('#router-daily').value),max_parallel:Number($('#router-parallel').value),interactive_reserved:Number($('#router-reserved').value),interactive_daily_reserve:Number($('#router-daily-reserve').value)},Object.fromEntries(['gemini','groq','cloudflare'].map(p=>[p,$('#router-project-'+p).value.trim()]).filter(([,v])=>v)));if(owner!==((S.snap||{}).user||{}).slug)return;SX.router=r.status;toast(r.msg);await refresh();drawSettings()}catch(e){toast(e.message,'bad')}};
ACT.routerstatus=()=>say('router durumu');
ACT.routerfree=async el=>{const owner=((S.snap||{}).user||{}).slug;if(!$('#rfree').checked)return toast('Önce ücretsiz plan ve ücretli faturalamanın kapalı olduğu beyanını seç.','bad');try{const r=await api('router_free_account_confirm',el.dataset.provider,true,true,owner);if(owner!==((S.snap||{}).user||{}).slug)return;SX.router=null;toast(r.msg);drawSettings()}catch(e){toast(e.message,'bad')}};
ACT.routerlocalcaps=async()=>{const owner=((S.snap||{}).user||{}).slug;try{const r=await api('router_local_capabilities',owner);if(owner!==((S.snap||{}).user||{}).slug)return;SX.localCapsMsg=r.ok?(r.vision?'Görüntü destekli runtime doğrulandı: ':'Runtime görüntü desteği bildirmiyor: ')+r.model:r.reason;drawSettings()}catch(e){toast(e.message,'bad')}};
function modes(){
  const m=(((S.snap||{}).llm||{}).provider||'auto')==='ollama'?'ollama':'auto';
  return `<div class="modes">${[['auto','Otomatik Model Seçimi','Hazır ücretsiz havuz ve seçilmiş özel roller'],['ollama','Yalnız yerel','Ollama, LM Studio veya llama.cpp']].map(([v,t,s])=>`<button class="mode ${m===v?'on':''}" data-act="sval" data-k="ai_mode" data-v="${v}"><span><b>${t}</b><small>${s}</small></span><span class="rd"></span></button>`).join('')}</div>`}

async function setUi(k,v){const r=await tryApi('nx_set',k,v);if(r){S.ui=r;await refresh();applyTheme();drawSettings();toast('Kaydedildi.')}}
ACT.smenu=el=>{S.sset=el.dataset.k;S.sq='';render()};
ACT.aiconnections=()=>openAiHub('baglanti');
ACT.sset=el=>setUi(el.dataset.k,el.dataset.v==='1');
ACT.sval=el=>setUi(el.dataset.k,isNaN(+el.dataset.v)?el.dataset.v:+el.dataset.v);
ACT.sflag=async el=>{await tryApi('set_flag',el.dataset.k,el.dataset.v==='1');await refresh();drawSettings()};
ACT.uswitch=el=>api('user_switch',el.dataset.n).then(()=>setTimeout(()=>sAfter(0),900));
ACT.unew=async ()=>{const n=await askText('Yeni kullanıcının adı:');if(n&&n.trim())api('user_new',n.trim()).then(()=>setTimeout(()=>sAfter(0),900))};
ACT.uren=async el=>{const n=await askText('Yeni ad:',el.dataset.n);if(n&&n.trim()&&n.trim()!==el.dataset.n)api('user_rename',el.dataset.n,n.trim()).then(()=>setTimeout(()=>sAfter(0),700))};
ACT.udel=async el=>{if(await ask('“'+el.dataset.n+'” silinsin mi? Verileri “silinenler” klasörüne taşınır.'))api('user_delete',el.dataset.n).then(()=>setTimeout(()=>sAfter(0),700))};
ACT.ukey=async el=>{const k=await askText(el.dataset.n+' için Gemini anahtarı (boş bırakırsan yalnız bu kullanıcının anahtarı silinir):','');if(k===null)return;const r=await tryApi('user_key_set',el.dataset.n,k.trim());if(r){SX.umsg=(r.ok?'✓ ':'✗ ')+r.msg;drawSettings()}};
ACT.verb=el=>sAfter(api('pref_set','verbosity',el.dataset.v));
ACT.gdel=el=>sAfter(api('goal_delete',+el.dataset.i));
ACT.fdel=el=>sAfter(api('fact_delete',+el.dataset.i));
ACT.rdel=el=>sAfter(api('rule_delete',+el.dataset.i));
ACT.pfok=el=>sAfter(api('pending_approve',+el.dataset.i));
ACT.pfno=el=>sAfter(api('pending_reject',+el.dataset.i));
function cloudflareBox(sn){
  const owner=(sn.user||{}).slug,ready=SX.routerOwner===owner&&SX.router?.connection_states?.cloudflare;
  return sbox('cloud','Cloudflare · '+esc((sn.user||{}).name||'Kullanıcı'),'Workers AI için bu kullanıcıya ait Account ID ve API token. Kaydetmek model çağırmaz.',
    field('Account ID',inp('cf-account','32 karakter; kayıtlı değeri korumak için boş bırak',''))+
    field('API token',inp('cf-token','Kayıtlı anahtarı korumak için boş bırak','','password'))+
    pad18(`<button class="btn sm pri" data-act="routercfsave">Kaydet</button> ${ready?'<button class="btn sm" data-act="routercfdelete">Kaldır</button>':''}<p class="mut">${esc(ready?'Bu kullanıcı için bağlantı kayıtlı; ücretsiz plan ve rol uygunluğu ayrı doğrulanır.':'Bu kullanıcı için bağlantı eksik.')} Workers Free planı ve ücretli faturalamanın kapalı olması ayrıca Otomatik Model Seçimi alanından beyan edilir.</p>`));
}
ACT.routercfsave=async()=>{const owner=((S.snap||{}).user||{}).slug;try{const r=await api('router_cloudflare_save',$('#cf-account').value,$('#cf-token').value,false,owner);if(owner!==((S.snap||{}).user||{}).slug)return;$('#cf-token').value='';SX.router=null;toast(r.msg);drawSettings()}catch(e){toast(e.message,'bad')}};
ACT.routercfdelete=async()=>{const owner=((S.snap||{}).user||{}).slug;if(!await ask('Bu kullanıcının Cloudflare bağlantısı kaldırılsın mı?'))return;if(owner!==((S.snap||{}).user||{}).slug)return;try{const r=await api('router_cloudflare_save','','',true,owner);if(owner!==((S.snap||{}).user||{}).slug)return;SX.router=null;toast(r.msg);drawSettings()}catch(e){toast(e.message,'bad')}};
const ROUTER_ROLES=[['brain_understanding','Ana model / Brain'],['conversation','Sohbet'],['public_research','Araştırma'],['long_worker','Uzun işler'],['vision','Görüntü analizi']];
function routerConnectionsBox(sn){
  const owner=(sn.user||{}).slug;
  if(SX.customOwner!==owner){SX.customOwner=owner;SX.customId='';SX.customModels=[];SX.customMsg='';SX.localCapsMsg=''}
  const rows=(SX.routerOwner===owner?SX.router?.custom_connections:null)||sn.llm?.custom_connections||[];
  const r=rows.find(x=>x.id===SX.customId)||{protocol:'openai_compatible',role:'conversation',billing:'unknown',daily_requests:25,max_output_tokens:4096,data_scopes:[]};
  const select=(id,values,current)=>`<select class="sel" id="${id}">${values.map(([value,label])=>`<option value="${value}" ${value===current?'selected':''}>${esc(label)}</option>`).join('')}</select>`;
  const checked=(id,label,value)=>`<label class="router-confirm"><input type="checkbox" id="${id}" ${value?'checked':''}><span>${label}</span></label>`;
  const saved=rows.map(c=>`<div class="connection-actions"><span>${esc(c.name)} · ${esc(c.model||'Model seçilmedi')} · ${esc(ROUTER_ROLES.find(x=>x[0]===c.role)?.[1]||c.role)} · ${c.enabled?'Etkin':c.migration_pending?'Eski bağlantı · etkinleştirme bekliyor':'Kapalı'}</span><button class="btn sm" data-act="customedit" data-id="${esc(c.id)}">Düzenle</button><button class="btn sm" data-act="customdelete" data-id="${esc(c.id)}">Kaldır</button></div>`).join('');
  return sbox('spark','Özel API','Hazır görev düzeni sabittir. Eklediğin bağlantının kullanım rolünü seçebilirsin. Kaydetmek API denemesi yapmaz.',
    pad18(saved+`<button class="btn sm" data-act="customnew">İlave API ekle</button>`)+
    field('Bağlantı adı',inp('custom-name','Bağlantım',r.name||''))+
    field('API temel adresi',inp('custom-url','https://…/v1',r.base_url||''),'Uzak adres HTTPS; yerel sunucu loopback adresi kullanır.')+
    field('API biçimi',select('custom-protocol',[['openai_compatible','OpenAI uyumlu Chat Completions'],['responses','Responses'],['anthropic_messages','Anthropic Messages']],r.protocol))+
    field('API anahtarı',inp('custom-key','Kayıtlı anahtarı korumak için boş bırak','','password'))+
    field('Exact model kimliği',`<input class="sel" id="custom-model" list="custom-models" value="${esc(r.model||'')}" autocomplete="off"><datalist id="custom-models">${(SX.customModels||[]).map(m=>`<option value="${esc(m.id)}">${esc(m.name)}</option>`).join('')}</datalist>`)+
    field('Kullanım rolü',select('custom-role',ROUTER_ROLES,r.role),'Bu rol için etkinleştirdiğin özel bağlantı kullanılır; ücretsiz havuz ücretliye kendiliğinden geçmez.')+
    field('Hesabın ücret sınıfı',select('custom-billing',[['unknown','Bilinmiyor'],['free','Ücretsiz plan beyanı'],['trial','Deneme'],['paid','Ücretli']],r.billing),'Sınıf seçimi tek başına ücretsiz hesap veya kalan kota kanıtı değildir. Ücretsiz havuza katılım ayrıca incelenmiş hesap/model/veri kanıtı ister; bilinmeyen uygunlukta aday gönderilmez.')+
    field('Günlük Jarvis çağrı tavanı',inp('custom-daily','25',r.daily_requests),'Sağlayıcının gerçek kotası veya parasal harcama garantisi değildir.')+
    field('Çağrı başına çıktı sınırı',inp('custom-output','4096',r.max_output_tokens))+
    field('Günlük yerel parasal tavan (USD, isteğe bağlı)',inp('custom-money','Boş: parasal tavan yok',r.daily_cost_microusd==null?'':r.daily_cost_microusd/1000000),'Bu tavan provider billing limiti değildir. Doluysa doğrulanmış maliyet üst sınırı olmadan çağrı gönderilmez; bilinmeyen fiyat sıfır sayılmaz.')+
    field('Çalışma alanı (gerekiyorsa)',inp('custom-workspace','',r.workspace||''))+
    field('Ortak hesap/proje kota grubu (varsa)',inp('custom-quota','Aynı hesapta aynı ad',r.quota_group||''),'Boşsa endpoint ve anahtar parmak izine göre paylaşılır; anahtar görüntülenmez.')+
    pad18(checked('custom-conversation','Bu bağlantıya konuşma bağlamı gönderilebilir.',r.data_scopes.includes('conversation'))+
      checked('custom-selected','Bu bağlantıya iş için seçtiğim içerik gönderilebilir.',r.data_scopes.includes('selected_content'))+
      checked('custom-public','Herkese açık araştırma kaynakları gönderilebilir.',r.data_scopes.includes('public'))+
      checked('custom-paid','Bu bağlantıda ücretli kullanım ihtimalini kabul ediyor ve etkinleştiriyorum.',r.paid_enabled)+
      checked('custom-enabled','Seçtiğim rol için bu bağlantıyı kullan.',r.enabled)+
      checked('custom-freepool','Yalnız doğrulanmış ücretsiz hesap/model ise sabit hazır havuza ilave aday olarak kat.',r.free_pool)+
      `<div class="connection-actions"><button class="btn sm pri" data-act="customsave">Kaydet</button>${r.id?'<button class="btn sm" data-act="custommodels">Modelleri getir</button><button class="btn sm" data-act="customtest">Tek bağlantı denemesi</button><button class="btn sm" data-act="customvisiontest">Görüntü desteğini dene</button>':''}</div><p class="mut">${esc(SX.customMsg||'Model yeterliliği, vision desteği ve ücretsiz uygunluk ayrıca doğrulanır.')}</p>`));
}
ACT.customnew=()=>{SX.customId='';SX.customModels=[];SX.customMsg='';drawSettings()};
ACT.customedit=el=>{SX.customId=el.dataset.id;SX.customModels=[];SX.customMsg='';drawSettings()};
ACT.customsave=async el=>{
  const owner=((S.snap||{}).user||{}).slug;
  const record={name:$('#custom-name').value.trim(),protocol:$('#custom-protocol').value,base_url:$('#custom-url').value.trim(),model:$('#custom-model').value.trim(),role:$('#custom-role').value,billing:$('#custom-billing').value,enabled:$('#custom-enabled').checked,paid_enabled:$('#custom-paid').checked,free_pool:$('#custom-freepool').checked,daily_cost_microusd:$('#custom-money').value.trim()?Math.round(Number($('#custom-money').value)*1000000):null,data_scopes:[['conversation','custom-conversation'],['selected_content','custom-selected'],['public','custom-public']].filter(([,id])=>$('#'+id).checked).map(([value])=>value),daily_requests:Number($('#custom-daily').value),max_output_tokens:Number($('#custom-output').value),workspace:$('#custom-workspace').value.trim(),quota_group:$('#custom-quota').value.trim()};
  if(SX.customId)record.id=SX.customId;
  el.disabled=true;
  try{const r=await api('router_connection_save',record,$('#custom-key').value,owner);if(owner!==((S.snap||{}).user||{}).slug)return;$('#custom-key').value='';SX.customId=r.connection.id;SX.customMsg=r.msg;SX.router=null;await refresh();drawSettings()}catch(e){toast(e.message,'bad')}finally{el.disabled=false}
};
ACT.custommodels=async()=>{const owner=((S.snap||{}).user||{}).slug,r=await api('router_connection_models',SX.customId,owner);if(owner!==((S.snap||{}).user||{}).slug)return;SX.customModels=r.models||[];SX.customMsg='Model listesi alındı; rol yeterliliği veya ücretsiz kullanım kanıtı değildir.';drawSettings()};
ACT.customtest=async()=>{const owner=((S.snap||{}).user||{}).slug,id=SX.customId;if(!await ask('Kaydedilmiş bağlantıda tek küçük gerçek model çağrısı yapılacak. Sağlayıcı ücretlendirebilir. Denensin mi?'))return;if(owner!==((S.snap||{}).user||{}).slug)return;const r=await api('router_connection_test',id,true,owner);if(owner!==((S.snap||{}).user||{}).slug)return;SX.customMsg=r.msg;drawSettings()};
ACT.customvisiontest=async()=>{const owner=((S.snap||{}).user||{}).slug,id=SX.customId;if(!await ask('Bu bağlantıya yalnız sentetik bir test görüntüsüyle tek küçük çağrı yapılacak. Sağlayıcı ücretlendirebilir. Denensin mi?'))return;if(owner!==((S.snap||{}).user||{}).slug)return;try{const r=await api('router_connection_vision_test',id,true,owner);if(owner!==((S.snap||{}).user||{}).slug)return;SX.customMsg=r.msg;drawSettings()}catch(e){toast(e.message,'bad')}};
ACT.customdelete=async el=>{const owner=((S.snap||{}).user||{}).slug,id=el.dataset.id;if(!await ask('Bu özel bağlantı kaldırılsın mı?'))return;if(owner!==((S.snap||{}).user||{}).slug)return;await api('router_connection_delete',id,owner);if(owner!==((S.snap||{}).user||{}).slug)return;SX.customId='';SX.router=null;await refresh();drawSettings()};

const msgOf=r=>(r&&r.ok?'✓ ':'✗ ')+((r&&r.msg)||'');
ACT.gksave=async el=>{const v=$('#gk').value.trim();if(!v){SX.gk='Anahtarı yaz.';return drawSettings()}SX.gk='Deneniyor…';el.disabled=true;
  try{const r=await api('api_key_save',v,'','');const bad=Object.values(r||{}).filter(x=>!x.ok);SX.gk=bad.length?'✗ '+bad.map(x=>x.error).join(' | '):'✓ Kaydedildi. Model denemesi yapılmadı.'}catch(e){SX.gk='✗ '+e.message}sAfter(0)};
ACT.ghsave=async el=>{const v=$('#ghk').value.trim();if(!v)return;el.disabled=true;SX.gh='Deneniyor…';try{SX.gh=msgOf(await api('update_token_save',v))}catch(e){SX.gh='✗ '+e.message}sAfter(0)};
ACT.ghverify=async()=>{SX.gh='GitHub main ile gerçek dosya karşılaştırması yapılıyor…';drawSettings();const r=await tryApi('github_verify');SX.gh=msgOf(r)+ghFiles(r);await refresh();drawSettings()};
const ghFiles=r=>{const f=(r&&r.local_changes)||[];if(String((r&&r.msg)||'').includes('Engelleyen dosyalar'))return '';return f.length?'\nGitHub’dan farklı dosyalar: '+f.join(', ')+(r.local_change_count>f.length?' …':''):''};
ACT.ghresolve=async el=>{const v=await tryApi('github_verify');if(!v||v.sync_state!=='diverged'){SX.gh=msgOf(v);await refresh();if(settingsOpen())drawSettings();else toast(SX.gh);return}
  if(!await ask('Bu bilgisayarda GitHub’dan farklı '+(v.local_change_count||0)+' dosya var. Önce hepsini ~/.jarvis/yerel_yedek klasörüne yedekleyip sonra GitHub main sürümünü kurayım mı?'+ghFiles(v)))return;
  if(el)el.disabled=true;SX.gh='Farklı dosyalar yedekleniyor ve GitHub main testlerden geçirilerek kuruluyor…';if(settingsOpen())drawSettings();else toast(SX.gh);
  try{const r=await api('github_backup_pull');SX.gh=msgOf(r);toast(r.msg,r.ok?'':'bad')}catch(e){SX.gh='✗ '+e.message;toast(e.message,'bad')}finally{if(el)el.disabled=false}
  await refresh();if(settingsOpen())drawSettings()};
ACT.deplock=async()=>{const r=await tryApi('dependency_lock_create');SX.gh=msgOf(r);drawSettings()};
ACT.ghpublish=async el=>{if(!await ask('Bu bilgisayardaki kaynak değişiklikleri test edip ayrı bir dala yükleyeyim ve main için PR açayım mı? (main’e PR birleşince girer)'))return;el.disabled=true;SX.gh='Testler çalışıyor ve GitHub yayını hazırlanıyor…';if(settingsOpen())drawSettings();else toast(SX.gh);try{const r=await api('github_publish');SX.gh=msgOf(r);toast(r.msg,r.ok?'':'bad')}catch(e){SX.gh='✗ '+e.message;toast(e.message,'bad')}finally{await refresh();if(S.sset==='baglanti'||S.sset==='github')drawSettings()}};
ACT.ghpull=async el=>{if(!await ask('GitHub main sürümünü bu bilgisayara alayım mı? Yerel değişiklik varsa işlem güvenlik için duracak.'))return;el.disabled=true;SX.gh='GitHub main doğrulanıyor ve güvenli güncelleme hazırlanıyor…';if(settingsOpen())drawSettings();else toast(SX.gh);try{const r=await api('github_pull');SX.gh=msgOf(r);toast(r.msg,r.ok?'':'bad')}catch(e){SX.gh='✗ '+e.message;toast(e.message,'bad')}finally{await refresh();if(S.sset==='baglanti'||S.sset==='github')drawSettings()}};
ACT.upd=async()=>{const r=await tryApi('update_now');if(r){SX.gh=msgOf(r);toast(r.msg);if(S.sset==='baglanti'||S.sset==='github')drawSettings()}};
ACT.lbpick=el=>{SX.lb=el.dataset.v;SX.lbm='';drawSettings()};
ACT.lbsave=async el=>{el.disabled=true;SX.lbm='Deneniyor…';try{SX.lbm=msgOf(await api('local_backend_set',SX.lb||((S.snap||{}).llm||{}).local_backend||'ollama',$('#lburl').value,''));SX.lb=''}catch(e){SX.lbm='✗ '+e.message}sAfter(0)};
ACT.omsave=async el=>{el.disabled=true;try{SX.om=msgOf(await api('model_choice_save','ollama',$('#om').value))}catch(e){SX.om='✗ '+e.message}sAfter(0)};
ACT.qsave=async el=>{el.disabled=true;SX.q='Deneniyor…';try{SX.q=msgOf(await api('groq_key_save',$('#qk').value,$('#qm').value,false))}catch(e){SX.q='✗ '+e.message}sAfter(0)};
ACT.gsopen=async el=>{const r=await tryApi('google_setup_open',el.dataset.v);SX.g=msgOf(r);drawSettings()};
ACT.gpick=()=>{const i=$('#upl');i.accept='.json,application/json';i.onchange=async()=>{const f=i.files[0];i.value='';if(!f)return;try{SX.g=await api('google_upload',await f.text())}catch(e){SX.g='✗ '+e.message}sAfter(0)};i.click()};
ACT.gconn=async()=>{SX.g='Bağlanılıyor… Tarayıcıda Google izin ekranı açılabilir.';drawSettings();const r=await tryApi('google_connect');SX.g=msgOf(r);sAfter(0)};
ACT.greset=async()=>{await tryApi('google_reset');SX.g='Bağlantı sıfırlandı.';sAfter(0)};
ACT.gprodopen=async()=>{const r=await tryApi('google_oauth_console');SX.g=msgOf(r);drawSettings()};
ACT.gprodok=async ()=>{if(!await ask('Google Cloud’da OAuth yayın durumunu gerçekten “In production” yaptın mı?'))return;const r=await tryApi('google_oauth_production',true);SX.g=msgOf(r);drawSettings()};
ACT.hoplace=el=>sAfter(api('handoff_place',el.dataset.v));
ACT.hoconn=async()=>{SX.ho='Tarayıcıda Google izin ekranı açılıyor…';drawSettings();SX.ho=msgOf(await tryApi('handoff_connect'));sAfter(0)};
ACT.vsave=async()=>{SX.v='Kaydediliyor…';try{await api('settings_save',{local_stt_enabled:$('#lstt').value==='1',local_stt_model:$('#lsttmodel').value,local_stt_beam:+$('#lsttbeam').value||5,assistant_name:$('#aname').value,wake_sensitivity:+$('#wsens').value,stt_fixes:$('#sfix').value,stt_words:$('#swords').value,input_device:$('#micdev').value,voice_mic_during_model_wait:$('#mmic').value==='1',voice_announce_results:$('#vres').value==='1'});SX.v='✓ Kaydedildi. Ses tanıma seçimini değiştirdiysen Jarvis’i yeniden başlat.'}catch(e){SX.v='✗ '+e.message}S.ui=null;await loadUi();drawSettings()};
ACT.pmode=el=>sAfter(api('privacy_set',{mode:el.dataset.k}));
ACT.ptog=el=>sAfter(api('privacy_set',{[el.dataset.k]:el.dataset.v==='1'}));
ACT.odata=()=>api('open_folder','data');
ACT.olog=()=>api('open_folder','log');
ACT.restart=async ()=>{if(await ask('Jarvis yeniden başlatılsın mı?'))api('restart')};
ACT.wset=async el=>{await tryApi('widget_set',el.dataset.v==='1');S.ui=null;await loadUi();drawSettings();toast('Kaydedildi.')};
ACT.hclear=async ()=>{if(await ask('Tüm konuşma geçmişi silinsin mi?')){await api('history_clear');S.hist=[];toast('Geçmiş temizlendi.')}};
function applyTheme(){const t=(S.ui||{}).nx_theme||'dark';const dark=t==='dark'||(t==='system'&&matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.dataset.theme=dark?'dark':'light'}

// ======================================================================= veri ve olaylar
async function refresh(){const oldUser=((S.snap||{}).user||{}).name;try{S.snap=await api('snapshot')}catch(e){return}
  if(oldUser&&oldUser!==((S.snap||{}).user||{}).name){S.noteSelected=null;S.noteText='';S.noteTitle='';ACT.ntimageclear();document.querySelectorAll('.noteviewer').forEach(el=>el.click());S.hist=null;S.live=[];S.chat=[];S.day=null;S.since=0;S.waiting=false;S.sdoc=0;S.sans='';S.mathDraft='';S.mathAttachment='';S.mathResponse=null;S.studyPdfPage=null;S.studySelection=null;S.mathUploadBusy=false;S.slesson=null;S.sov=null;S.squiz=null;S.sres=null;S.smedia=null;S.quizBusy=false;S.mockBusy=false;S.studyLessonRequest=null;S.studyQuizRequest=null;S.studyMediaRequest=null;S.studyOverviewRequest=null;S.studyBusy=false;S._sovLoading=0;await loadHist();render()}
  if(!S.snap)return;S.orb=S.snap.orb||'idle';dockState();
  {const pk=JSON.stringify(((S.snap.study||{}).pending)||[]);if(S.page==='study'&&S._spk!==undefined&&pk!==S._spk){const was=S._spk;S._spk=pk;S.sov=null;render();const pd=S.snap.study.pending||[];if(pd.some(x=>x.state==='error'))toast('Bir kaynak eklenemedi; ayrıntı listede.','bad');else if(pd.length<JSON.parse(was).length)toast('Çalışma kaynağı eklendi.')}S._spk=pk;
   clearTimeout(S._spt);if(pk!=='[]'&&pk.includes('running'))S._spt=setTimeout(refresh,3000)}renderTop();renderRail();if(S.page==='chat'){drawSide();drawDevelopment()}if(S.page==='home'&&!$('.hscene'))render()}
let rt=null;const refreshSoon=()=>{clearTimeout(rt);rt=setTimeout(refresh,150)};
// Sesle gelen görünüm komutları (selfctl._ui): yalnız beyaz listedeki işlem ve değerler uygulanır.
const UI_VOICE={hologramtone:v=>{if(['blue','turquoise','yellow'].includes(v))ACT.hologramtone({dataset:{v}})},
  hologrambg:v=>{if(['mountains','lava'].includes(v))ACT.hologrambg({dataset:{v}})},
  bustreplay:()=>{if(S.page!=='home'){go('home');setTimeout(()=>ACT.bustreplay(),600)}else ACT.bustreplay()},
  nxbust:v=>setUi('nx_bust',v==='1')};
function uiVoice(t){const[n,v]=String(t||'').split('|');const f=UI_VOICE[n];if(f)f(v)}
function onEvent(m){
  const k=m.k;
  const owner=((S.snap||{}).user||{}).slug;
  if(m.user&&owner&&m.user!==owner){refreshSoon();return}
  if(m.mid&&((S.hist||[]).some(r=>r.id===m.mid)||S.live.some(r=>r.id===m.mid)))return;
  if(typeof taskSummaryEvent==='function')taskSummaryEvent(m);
  if(k==='action'){Promise.all([refresh(),loadUi()]).then(()=>{S.files=null;S.sc=null;S.sov=null;if(S.page!=='chat')render()});return}
  if(k==='reconcile'){loadHist().then(()=>{S.live=[];if(S.page==='chat'){drawMsgs();drawConvs()}});return}
  if(k==='user'||k==='assistant'){const ts=m.ts||Date.now()/1000;
    if(k==='user'){const i=S.live.findIndex(x=>x.mine&&x.role==='user'&&x.text===m.t);if(i>=0)S.live.splice(i,1)}
    S.live.push({id:m.mid,role:k,text:m.t,ts,src:m.x,rid:m.rid});S.live=S.live.slice(-300);if(k==='assistant')S.waiting=false;
    if(S.hist){const d=new Date(ts*1000),z=n=>String(n).padStart(2,'0');S.hist.push({id:m.mid,role:k,text:m.t,ts:`${ymd(d)} ${z(d.getHours())}:${z(d.getMinutes())}:${z(d.getSeconds())}`,source:m.x})}
    if(S.page==='chat'){drawMsgs();drawConvs()}}
  else if(k==='step'){onStep(m);return}
  else if(k==='system'){toast(String(m.t).slice(0,180));S.live.push({role:'system',text:m.t,ts:Date.now()/1000});S.waiting=false;if(S.page==='chat')drawMsgs()}
  else if(k==='state'){S.orb=m.t||'idle';dockState();speechStateEvent(S.orb);{const hh=$('.hhey');if(hh){hh.classList.toggle('live',S.orb==='listening');const sm=hh.querySelector('small');if(sm)sm.textContent=heyTxt()}const hc=$('.hcore');if(hc)hc.dataset.s=S.orb}$$('.mic').forEach(b=>b.classList.toggle('live',S.orb==='listening'));if(S.page==='home'){const r=$('.ready');if(r){const[a,b]=STATE_TXT[S.orb]||STATE_TXT.idle;r.querySelector('b').textContent=a;r.querySelector('small').textContent=b}}}
  else if(k==='speech'){speechEvent(m);return}
  else if(k==='share'){S.snap=S.snap||{};S.snap.mode=m.t||null;drawMiniPreview();if(S.page==='vision')render()}
  else if(k==='nav'){navTo(m.t);return}
  else if(k==='ui'){uiVoice(m.t);return}
  else if(k==='study_start'){const owner=((S.snap||{}).user||{}).name;S.stab='learn';go('study');loadStudy().then(()=>{if(S.page==='study'&&owner===((S.snap||{}).user||{}).name){render();ACT.studystart()}});return}
  else if(k==='study_media'){if(S.page!=='study'){S.stab='learn';go('study')}S.swin=1;S.swtab='wiki';setTimeout(()=>showMedia(m.t),S.page==='study'?0:400);return}
  else if(k==='quit'){document.body.innerHTML='<div style="display:grid;place-items:center;height:100vh;color:#7396ae;font-family:sans-serif">Jarvis kapandı. Bu pencereyi kapatabilirsin.</div>';return}
  refreshSoon();
}
function navTo(h){const[t,s]=String(h||'home').replace(/^#/,'').split(/[|/]/);if(t==='settings'&&['ai','baglanti'].includes(s)){S.sset=s;S.tool='aihub';go('tools');return}if(t==='settings'&&s)S.sset=s;if(t==='tools')S.tool=s||'';go(NAV.some(n=>n[0]===t)?t:'home')}
function connect(){
  const es=new EventSource('/events');let loading=true,closed=false,buffer=[];
  es.onopen=async()=>{
    loading=true;await refresh();if(closed)return;const user=((S.snap||{}).user||{}).name;
    const rows=await tryApi('history','',1500);if(closed)return;
    if(rows&&user===((S.snap||{}).user||{}).name){S.hist=rows;S.live=S.live.filter(r=>r.mine);S.waiting=S.orb==='thinking'}
    loading=false;const pending=buffer;buffer=[];pending.forEach(onEvent);
    if(S.page==='chat'){drawMsgs();drawConvs()}
  };
  es.onmessage=ev=>{try{const m=JSON.parse(ev.data);if(loading)buffer.push(m);else onEvent(m)}catch(e){console.error(e)}};
  es.onerror=()=>{closed=true;es.close();setTimeout(connect,2500)};
}

// ======================================================================= Baş Harfler Büyük
// Hamdi: başlık ve etiketlerde her kelimenin baş harfi büyük ("Hamdi Köse Bugün Ne Yaptın"). Türkçe kurala göre
// (i -> İ). Mesajlar, dosya adları, adresler ve uzun açıklamalar olduğu gibi kalır.
const TC_SEL='.sbox b,.empty,.sbox small,.srow2 small,.mut,.pagehead p,.sethead small,.hginfo small,.jbox p,.toast div,#spane span,#spane div,.nav button span,.hcard .ct,.hrow b,.hs,.hsub,.htl span,.hrem b,.hrem em,.hgl span,.hginfo div,.hhey b,.hhey small,.hgreet h1,.hgreet p,.home-actions span,.tw .c,.tw .d,.tt small,.hprofile small,.hgbtn,.acard b,.ch .ct,.link,.ct,.qc b,.qc small,.hello p,.sum .row b,.sum .row small,.acard b,.acard small,.tool b,.tool small,.btn,.chip,.smenu button,'+
 '.srow2 .l b,.srow2 .l small,.sbox .sh b,.sbox .sh small,.pagehead h1,.pagehead p,.hero p,.ready b,.ready small,.doing .ok,.sug,.qbtn,.chead b,.task b,'+
 '.task small,.kv span,.tabs button,.ac,.pill,.srow,.act .tx,.health .t,.newc,.sethead small,.apph p,.logo small,.conv b,.seg button,.mode b,.mode small,.st,.menu button,.link,.okk,.frow span:not(.fi),.fl';
const tcWord=s=>s.replace(/(^|[\s(“"\/-])(\p{Ll})/gu,(m,a,b)=>a+b.toLocaleUpperCase('tr'));
function tcEl(el){const w=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);let n;while((n=w.nextNode())){const p=n.parentElement;if(!p||p.closest('input,textarea,.bb,.msgs,.fchip,.nm,time,code,#ftb,.fdet .kv b'))continue;
  if(/\\|^[a-z]:|https?:|\w\.\w+\/|\/\w+\/|\.\w{2,4}$|^\s*$/i.test(n.nodeValue))continue;const v=tcWord(n.nodeValue);if(v!==n.nodeValue)n.nodeValue=v}}
function tcPh(root){(root.matches&&root.matches('input[placeholder],textarea[placeholder]')?[root]:[]).concat([...root.querySelectorAll('input[placeholder],textarea[placeholder]')]).forEach(i=>{const v=i.getAttribute('placeholder');if(v&&/\s/.test(v)){const t=tcWord(v);if(t!==v)i.setAttribute('placeholder',t)}})}
function tcScan(root){if(!(root instanceof Element))return;tcPh(root);if(root.matches(TC_SEL))tcEl(root);root.querySelectorAll(TC_SEL).forEach(tcEl);const c=root.closest&&root.closest(TC_SEL);if(c&&c!==root)tcEl(c)}
new MutationObserver(ms=>{let topHit=false;for(const m of ms){if(!topHit){const te=m.target.nodeType===1?m.target:m.target.parentElement;if(te&&te.closest('#top'))topHit=true}if(m.type==='characterData'){const c=m.target.parentElement&&m.target.parentElement.closest(TC_SEL);if(c)tcEl(c)}else{m.addedNodes.forEach(x=>{if(x.nodeType===1)tcScan(x);else if(x.nodeType===3&&x.parentElement)tcScan(x.parentElement)})}}if(topHit)requestAnimationFrame(fitTop)})
  .observe(document.body,{childList:true,subtree:true,characterData:true});

// ======================================================================= açılış

// Tüm sayfaların arkasında APEX dalgaları (WebGL; yerel, ağ yok). Hareketi azalt açıksa çizilmez.
function mountAppBg(){window.JarvisBackdropController=window.JarvisBackdrop.mount({isStill:()=>S.ui?.nx_bust===false,isWorkspace:()=>S.page!=='home'&&(S.page!=='menu'||!!document.querySelector('.mnscene.docked'))})}
(async function boot(){
  if(['vision','tools','settings'].includes(S.page))S.page='menu';
  mountAppBg();requestAnimationFrame(frame);try{document.fonts.ready.then(fitTop);document.fonts.addEventListener('loadingdone',fitTop)}catch(e){}setInterval(tick,5000);
  if(location.hash.length<=1)try{render()}catch(e){}   // anlık görüntü yavaşsa ekran boş kalmasın: ana ekran hemen çizilir, veri gelince yeniden çizilir
  await Promise.all([refresh(),loadUi()]);if(location.hash.length>1){navTo(location.hash);history.replaceState(null,'',location.pathname+location.search)}else render();connect();setInterval(refresh,15000);loadPcMute();addEventListener('focus',loadPcMute);
  loadFiles().then(()=>{if(['files','vision','home'].includes(S.page)&&S.page!=='home')render();renderRail()});
})();

ACT.modelcheck=async()=>{try{const r=await api('llm_validate',true);SX.gk=r.message||r.state}catch(e){SX.gk='Model kontrolü tamamlanamadı: '+e.message}sAfter(0)};

function localSttText(s){return !s.installed?'Önce faster-whisper paketini kur (docs/YEREL_SES.md).':s.preparing?'Model indiriliyor; biraz sonra durumu yenile.':s.error|| (s.ready?'Model hazır. Gizli/Yerel modda ses buluta gitmez.':'Model henüz indirilmedi. İndirme internet kullanır; ses kaydı göndermez.')}
function roleQualText(s){return s.running?`Doğrulama sürüyor: ${s.done||0}/${s.total||20} vaka bitti; Jarvis'yi kapatman sürmeyi durdurmaz.`:s.qualified?'Bu sürüm doğrulanmış; serbest cümleler model üzerinden çalışıyor.':(s.error||'Doğrulama 20 sınırlı ücretsiz Gemini çağrısı kullanır, ~12 dakika sürer, işlem yapmaz.')}
ACT.rolequal=async()=>{if(!await ask('Bu sürüm doğrulansın mı? 20 sınırlı ücretsiz Gemini çağrısı kullanılır, yaklaşık 12 dakika sürer; hiçbir işlem yapılmaz.'))return;try{const r=await api('role_qualification_prepare');toast(r&&r.started?'Doğrulama başladı; birkaç dakika sonra “Durumu yenile”e bas.':'Doğrulama zaten sürüyor.')}catch(e){toast(e.message,'bad')}drawSettings()};
ACT.rolequalrefresh=()=>drawSettings();
ACT.lsttprepare=async()=>{const name=$('#lsttmodel').value;if(!await ask(name+' yerel ses modeli indirilsin mi? İnternet ve disk alanı kullanır.'))return;try{await api('settings_save',{local_stt_model:name});await api('local_stt_prepare',name);toast('Model hazırlanıyor; biraz sonra durumu yenile.');drawSettings()}catch(e){toast(e.message,'bad')}};
ACT.lsttrefresh=()=>drawSettings();
