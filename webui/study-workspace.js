/* Source stays visible while the student reads the explanation. */
function studyRegion(start,end){
 const [x1,x2]=[start[0],end[0]].sort((a,b)=>a-b),[y1,y2]=[start[1],end[1]].sort((a,b)=>a-b);
 if(x2-x1<.01||y2-y1<.01)return null;
 return [x1,y1,x2,y2].map(v=>Math.max(0,Math.min(1,v)));
}
async function initStudyWorkspace(pg,pageOverride){
 const host=pg&&pg.querySelector('#study-preview');if(!host)return;
 host.studyPreviewObserver?.disconnect();host.studyPreviewObserver=null;
 const owner=S.snap?.user?.name,mode=S.snap?.study?.mode,doc=+S.sdoc||0,ticket=Symbol();S.studyPreviewRequest=ticket;
 const current=()=>S.page==='study'&&S.snap?.user?.name===owner&&S.snap?.study?.mode===mode&&(+S.sdoc||0)===doc&&S.studyPreviewRequest===ticket&&host.isConnected;
 const saved=S.studyPdfPage;
 const page=pageOverride??(saved?.owner===owner&&saved.mode===mode&&saved.doc===doc?saved.page:1);
 const button=pg.querySelector('#study-selection-button'),note=pg.querySelector('#study-selection-note');
 const clear=()=>{S.studySelection=null;button.disabled=true;host.querySelector('.study-region')?.remove();};
 clear();button.textContent='Seçili Alanı Anlat';
 if(mode!=='math'&&!doc)return;
 try{
  const data=await api(mode==='math'?'study_math_preview':'study_source_preview',...(mode==='math'?[page]:[doc,page]));if(!current())return;
  host.innerHTML='';S.studyPdfPage=null;
  let pageControls=null,zoomLabel=null,fitImage=()=>{},setView=()=>{},zoomBy=()=>{};
  if(data.image){
   const bar=document.createElement('div');bar.className='study-page-controls';
   if(data.source_page){
   S.studyPdfPage={owner,mode,doc,page:data.page,image_id:data.image_id};
   const navigation=document.createElement('div');navigation.className='study-page-navigation';
   const previous=document.createElement('button'),next=document.createElement('button'),label=document.createElement('span');
   previous.className=next.className='btn sm';previous.textContent='Önceki Sayfa';next.textContent='Sonraki Sayfa';previous.disabled=data.page<=1;next.disabled=data.page>=data.pages;label.textContent=`Sayfa ${data.page} / ${data.pages}`;
   previous.onclick=()=>{if(!S.studyBusy&&!S.mathUploadBusy)initStudyWorkspace(pg,data.page-1)};next.onclick=()=>{if(!S.studyBusy&&!S.mathUploadBusy)initStudyWorkspace(pg,data.page+1)};
   navigation.append(previous,label,next);bar.appendChild(navigation);
   }
   const zoom=document.createElement('div');zoom.className='study-page-zoom';
   const smaller=document.createElement('button'),larger=document.createElement('button'),width=document.createElement('button'),fit=document.createElement('button');zoomLabel=document.createElement('span');
   for(const control of [smaller,larger,width,fit])control.className='btn sm';
   smaller.textContent='−';smaller.title='Küçült';smaller.ariaLabel='Küçült';larger.textContent='+';larger.title='Büyüt';larger.ariaLabel='Büyüt';width.textContent='Genişliğe Sığdır';fit.textContent='Sayfaya Sığdır';
   smaller.onclick=()=>{if(current())zoomBy(-.25)};larger.onclick=()=>{if(current())zoomBy(.25)};width.onclick=()=>{if(current())setView('width')};fit.onclick=()=>{if(current())setView('page')};
   zoom.append(smaller,zoomLabel,larger,width,fit);bar.appendChild(zoom);pageControls=bar;
  }
  if(data.name||(data.title&&mode==='math')){const title=document.createElement('p');title.className='mut';title.textContent=data.name||data.title;host.appendChild(title)}
  if(data.note){const n=document.createElement('p');n.className='study-preview-note';n.textContent=data.note;host.appendChild(n)}
  if(data.missing_original){
   const restore=document.createElement('button');restore.className='btn sm study-original-button';restore.textContent='Özgün PDF’yi Bağla';
   restore.onclick=()=>{
    const picker=document.createElement('input');picker.type='file';picker.accept='.pdf';
    picker.onchange=async()=>{const file=picker.files[0];if(!file||!current())return;restore.disabled=true;
     try{const result=await upload(file,true);if(!current()||!result)return;await api('study_source_restore_original',data.id,result.path);if(current())await initStudyWorkspace(pg,1)}
     catch(error){if(current())toast(error.message,'bad')}finally{if(current())restore.disabled=false}};
    picker.click();
   };host.appendChild(restore);
  }
  if(data.image){
   const viewport=document.createElement('div');viewport.className='study-page-viewport';viewport.tabIndex=0;viewport.ariaLabel='Kaynak Görünümü';host.appendChild(viewport);
   const wrap=document.createElement('div');wrap.className='study-image-wrap';
   const image=document.createElement('img');image.alt=data.name||'Soru görseli';image.draggable=false;wrap.appendChild(image);viewport.appendChild(wrap);
   const key=data.source_page?data.image_id.replace(/:\d+$/,''):data.image_id;
   const previousView=S.studyPdfView;
   const view=previousView?.owner===owner&&previousView.mode===mode&&previousView.doc===doc&&previousView.key===key?{...previousView}:{owner,mode,doc,key,layout:data.source_page?'width':'page',scale:1};
   const fit=()=>{
    const used=[...host.children].filter(child=>child!==viewport).reduce((total,child)=>total+child.offsetHeight+8,0);
    const availableWidth=Math.max(40,viewport.clientWidth||host.clientWidth-16),availableHeight=Math.max(40,host.clientHeight-used-24);
    const ratio=(image.naturalWidth||1)/(image.naturalHeight||1);
    const width=view.layout==='page'?Math.min(availableWidth,availableHeight*ratio):availableWidth*view.scale;
    wrap.style.width=width+'px';image.style.width=width+'px';image.style.maxWidth='none';image.style.maxHeight='none';
    if(zoomLabel)zoomLabel.textContent=Math.round(width/availableWidth*100)+'%';S.studyPdfView={...view};
   };
   setView=layout=>{view.layout=layout;view.scale=1;fit()};
   zoomBy=amount=>{view.scale=Math.max(.25,Math.min(3,(parseFloat(image.style.width)||viewport.clientWidth)/(viewport.clientWidth||host.clientWidth-16)+amount));view.layout='width';fit()};
   fitImage=fit;image.onload=()=>{if(current())fit()};image.src=data.image;fit();
   if(typeof ResizeObserver!=='undefined'){const observer=new ResizeObserver(()=>{if(!current()){observer.disconnect();return}fit()});host.studyPreviewObserver=observer;observer.observe(host);observer.observe(viewport)}
   let start=null,region=null;
   const point=e=>{const r=image.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];};
   const draw=box=>{if(!region){region=document.createElement('div');region.className='study-region';wrap.appendChild(region)}region.style.cssText=`left:${box[0]*100}%;top:${box[1]*100}%;width:${(box[2]-box[0])*100}%;height:${(box[3]-box[1])*100}%`};
   image.onpointerdown=e=>{if(e.button!==0||S.studyBusy||S.mathUploadBusy)return;e.preventDefault();clear();region=null;start=point(e);image.setPointerCapture(e.pointerId)};
   image.onpointermove=e=>{if(start){const box=studyRegion(start,point(e));if(box)draw(box)}};
   image.onpointerup=e=>{if(!start)return;const box=studyRegion(start,point(e));start=null;if(!box){clear();return}draw(box);S.studySelection={owner,data:{image_id:data.image_id,box,...(data.source_page?{page:data.page}:{})}};button.disabled=false;note.textContent='Seçili alan hazır. “Seçili alanı anlat” ile yalnız bu kısmı açıklat.'};
   image.onpointercancel=()=>{start=null;clear();region=null};
  }else if(data.text){
   const text=document.createElement('textarea');text.readOnly=true;text.className='study-source-text';text.value=data.text;host.appendChild(text);
   button.textContent='Seçili metni anlat';
   const select=()=>{const chosen=text.value.slice(text.selectionStart,text.selectionEnd).trim();S.studySelection=chosen?{owner,text:chosen.slice(0,5000)}:null;button.disabled=!chosen;};
   text.onselect=select;text.onkeyup=select;text.onmouseup=select;
  }else host.textContent='Önizleme için bir dosya veya görsel yükle.';
  if(pageControls)host.appendChild(pageControls);fitImage();
 }catch(error){if(current())host.textContent='Önizleme açılamadı: '+error.message}
}
ACT.studyselection=()=>{
 const selected=S.studySelection;if(!selected||selected.owner!==S.snap?.user?.name)return toast('Önce açıklanacak kısmı seç.');
 if(S.studyBusy||S.mathUploadBusy)return;
 const question=selected.text?'Yalnız aşağıda seçtiğim kısmı açıkla; sorunun tamamını çözme, sonucunu verme:\n'+selected.text:'Yalnız seçili alanda sorduğum kısmı ve yöntemi anlat; tam çözümü veya sonucu verme.';
 if(S.snap?.study?.mode==='math')return runMath(question);
 const input=$('#studyq');if(input)input.value=question;
 return ACT.studyask();
};
ACT.studyselectionclear=()=>{S.studySelection=null;$('#study-preview')?.querySelector('.study-region')?.remove();const button=$('#study-selection-button');if(button)button.disabled=true;};
ACT.studyplain=()=>S.snap?.study?.mode==='math'?runMath('Bu kısmı daha basit, küçük adımlarla anlat; tam çözümü veya sonucu verme.'):ACT.slmore();

ACT.studyresources=()=>{S.stab='resources';if(S.page==='study')render();else go('study')};
