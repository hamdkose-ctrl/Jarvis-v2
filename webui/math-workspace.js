/* Math is text/HTML so fractions and result labels remain readable at any size. */
function mathFormula(value){
 const plain=String(value||'').trim().replace(/^\$\$?|\$\$?$/g,'').replace(/^\\[([]|\\[)\]]$/g,'');
 return `<span class="math">${mathBasic(esc(plain))}</span>`;
}
function mathResponse(text){
 const cached=S.mathResponse;
 if(cached?.owner===S.snap?.user?.name&&cached.text===text)return cached;
 const turn=[...(S.snap?.study?.math_turns||[])].reverse().find(t=>t.role==='Jarvis');
 return turn?.text===text?turn:{};
}
function mathLegacySteps(text){
 let found=null;
 const prose=text.replace(/!\[[^\]]*\]\(data:image\/svg\+xml;base64,([A-Za-z0-9+/=]+)\)/g,(match,encoded)=>{
  if(found||encoded.length>30000)return match;
  try{
   const svg=new TextDecoder().decode(Uint8Array.from(atob(encoded),x=>x.charCodeAt(0)));
   // Only read text from the app's old numbered step drawing. Never embed its XML.
   if(!svg.includes('fill="#244563"')||!svg.includes('viewBox="0 0 640 '))return match;
   const decode=s=>s.replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&apos;/g,"'").replace(/&amp;/g,'&');
   const labels=[...svg.matchAll(/<text\b[^>]*>([^<]*)<\/text>/g)].map(x=>decode(x[1]));
   if(labels.length<2||labels.length>7||!labels.slice(1).every((s,i)=>s.startsWith((i+1)+'. ')))return match;
   found={legacy:true,steps:labels.slice(1).map(s=>({title:labels[0],expression:s.replace(/^\d+\. /,''),kind:'method',why:''}))};
   return '';
  }catch{return match}
 });
 return {prose,work:found};
}
function mathWorkHtml(work){
 const steps=Array.isArray(work.steps)?work.steps:[];
 if(work.legacy)return `<div class="math-legacy-steps"><b>${esc(steps[0]?.title||'İşlem adımları')}</b>${steps.map(s=>`<div class="math-equation" tabindex="0">${mathFormula(s.expression)}</div>`).join('')}</div>`;
 return `<div class="math-work">
  ${(work.given||[]).length?`<div class="math-given"><b>Verilenler</b><div>${work.given.map(x=>mathFormula(x)).join('<span class="math-separator">·</span>')}</div></div>`:''}
  ${work.problem?`<div class="math-problem"><small>İncelenen ifade</small><div>${mathFormula(work.problem)}</div></div>`:''}
  <ol class="math-steps">${steps.map((step,i)=>{
   const final=step.kind==='final'&&work.goal==='solve'&&work.scope!=='selection';
   const label=final?'Sorunun cevabı':step.kind==='method'?'Yöntem':'Ara işlem';
   return `<li class="math-step ${final?'is-final':''}"><span class="math-step-number">${i+1}</span><div class="math-step-body"><div class="math-step-heading"><b>${esc(step.title)}</b><small>${label}</small></div>${step.expression?`<div class="math-equation" tabindex="0">${mathFormula(step.expression)}</div>`:''}${step.why?`<p class="math-reason">${esc(step.why)}</p>`:''}</div></li>`;
  }).join('')}</ol></div>`;
}
function mathHtml(text){
 if(!text)return '';
 const response=mathResponse(text),old=mathLegacySteps(text),work=response.work||old.work;
 const goal=response.goal||work?.goal,scope=response.scope||work?.scope;
 const final=work?.steps?.find(s=>s.kind==='final'&&goal==='solve'&&scope!=='selection');
 const drawings=(old.prose.match(/!\[[^\]]*\]\(data:image\/svg\+xml;base64,[A-Za-z0-9+/=]+\)/g)||[]).join('\n');
 const title=scope==='selection'?'Seçili kısmın anlatımı':goal==='solve'?'Tam çözüm':goal==='explain_only'?'İşlem / konu anlatımı':'Önceki anlatım';
 const note=scope==='selection'?'Buradaki ara sonuç, sorunun tamamının cevabı değildir.':goal==='explain_only'?'Yalnız sorulan kısmı anlatıyoruz. Tam cevap için “Çöz”.':'';
 const verification=response.verification;
 const checked=Number.isInteger(verification?.checked)?verification.checked:0;
 const pending=Number.isInteger(verification?.unverified)?verification.unverified:0;
 const checkNote=verification?.status==='checked'&&checked>0?`${checked} işlem bağımsız aritmetik denetiminden geçti.${pending>0?` ${pending} adım denetimin kapsamında değil.`:''}`:'Bu anlatımın hesapları bağımsız aritmetik denetimiyle doğrulanmadı.';
 return `<div class="math-answer-header ${final?'has-result':''}"><b>${title}</b>${final?`<div class="math-answer-result"><small>Sorunun cevabı</small>${mathFormula(final.expression)}</div>`:''}${note?`<small>${note}</small>`:''}</div>
  ${work&&!work.legacy?mathWorkHtml(work)+(drawings?mdMath(drawings):''):`<div class="math-prose">${mdMath(old.prose)}</div>${work?mathWorkHtml(work):''}`}
  ${work&&!work.legacy?`<p class="math-reason"><b>Hesap kontrolü:</b> ${esc(checkNote)}</p>`:''}
  ${goal==='solve'&&!final&&work&&!work.legacy?'<p class="math-incomplete">Son cevap belirtilmedi; bu anlatım tamamlanmış çözüm olarak gösterilmiyor.</p>':''}`;
}
