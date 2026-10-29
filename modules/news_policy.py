"""Haber araştırması tamamlanma ve kayıtlı kurtarma politikası (goal_executor'dan taşındı, davranış aynı).

Yürütücü genel kalır; haber kuralları (tekil makale kanıtı, canonical yayıncı eşiği, modelsiz kurtarma)
burada durur. goal_executor aynı adlı ince sarmalayıcılarla çağırır.
"""
import re
from modules import privacy, requests_state
from modules.diagnostics import record_failure as _record_failure


def deliver_chat(job,goal,evidence):
    """Deliver existing news receipts after a file-only writer was misselected."""
    from modules import goal_tools,research_evidence
    if (job['state'] in {'approval','review','cancelled'} or
            not research_evidence.news_requested(job['request']) or research_evidence.file_requested(job['request'])):
        raise ValueError('Bu hedef sohbet haber teslimine çevrilemez.')
    steps={step['id']:step for step in job['steps']}
    pending=list(evidence);seen=set();sources=[]
    while pending:
        ident=pending.pop(0)
        if ident in seen:continue
        seen.add(ident)
        output=job['outputs'][ident]
        goal_tools.verify(output,job['owner'])
        if output.get('news_article'):sources.append(ident)
        pending.extend(steps.get(ident,{}).get('depends',[]))
    target=job['goals'][goal]
    target['chat_evidence']=sources
    try:
        if not sources:raise ValueError('Henüz doğrulanmış tekil haber gövdesi yok.')
        check_completion(job,target,sources,final=True)
    except ValueError as exc:
        job['state']='paused'
        job['blocker']=('Haberler sohbette kısmi teslim edildi; dosya oluşturulmadı. ' if sources else
                        'Sohbet teslimi tamamlanmadı; dosya oluşturulmadı. ')+str(exc)
        return
    target.update(state='done',evidence=sources)
    target.pop('chat_evidence',None)
    job.setdefault('feedback',[]).append('Dosya adımı çalıştırılmadan mevcut haber kanıtları sohbetten teslim edildi.')


def check_completion(job,goal,evidence,*,final=False):
    from modules import research_evidence
    if not isinstance(job,dict):
        raise ValueError('Geçersiz haber işi kaydı.')
    request=job.get('request');raw_steps=job.get('steps');outputs=job.get('outputs');state=job.get('state')
    if (not isinstance(request,str) or not request.strip() or not isinstance(raw_steps,list)
            or not isinstance(outputs,dict)):
        raise ValueError('Geçersiz haber işi kaydı.')
    if not research_evidence.news_requested(request):return
    steps={}
    for step in raw_steps:
        if not isinstance(step,dict) or not step.get('id'):
            raise ValueError('Geçersiz haber işi kaydı.')
        steps[step['id']]=step
    from modules import news_temporal
    from datetime import datetime,timezone
    event_check=news_temporal.request_scope(request)['intent']=='event_verification'
    event_verified=False
    pending=list(evidence or []);seen=set()
    discovery=False;article=False;verified=[]
    while pending:
        ident=pending.pop()
        if ident in seen:continue
        seen.add(ident);step=steps.get(ident,{})
        output=outputs.get(ident,{})
        if not isinstance(output,dict) or output.get('state')!='done':continue
        if event_check and output.get('event_evidence'):
            created=job.get('created')
            if type(created) not in (int,float):raise ValueError('Özgün istek zamanı eksik.')
            news_temporal.event_receipt(output,request=request,reference=datetime.fromtimestamp(created,timezone.utc))
            event_verified=True
        if output.get('news_article'):
            source=research_evidence.news_receipt(output)
            research_evidence.news_date(source,request);article=True
            verified.append({'news_article':source})
        if step.get('tool')=='data' and isinstance(step.get('input'),dict) and step['input'].get('operation') in {'sources','headlines','news_search'}:discovery=True
        depends=step.get('depends',[])
        if isinstance(depends,list):pending.extend(depends)
    if event_check:
        if not event_verified:raise ValueError('İstenen olay tarihi ve kapsam için kaynak kanıtı gerekli.')
        return
    goal_text=goal.get('text') if isinstance(goal,dict) else None
    text=(goal_text if isinstance(goal_text,str) and goal_text.strip() else request).casefold()
    discovery_goal=(re.search(r'kaynak|bağlantı|baglanti|başlık|baslik|dizin|katalog',text) and
                    re.search(r'bul|listele|keşfet|kesfet|seç|sec|belirle',text) and
                    not re.search(r'araştır|arastir|incele|analiz|doğrula|dogrula|rapor|özet|ozet|değerlendir|degerlendir',text))
    research_goal=re.search(r'araştır|arastir|haber|gelişme|rapor|incele|analiz|özet|ozet',text)
    if not article and not discovery_goal and research_goal and research_evidence.news_requested(text):
        raise ValueError('Haber araştırması yalnız bağlantı/başlık keşfiyle tamamlanamaz; tekil haber gövdesi ve yayın tarihi kanıtı gerekli.')
    # Catalog traversal is discovery telemetry, never completion authority.
    # The canonical pipeline already owns relevance, freshness and publisher evidence.
    from modules import news_pipeline
    if (not discovery_goal and research_goal and research_evidence.news_requested(text)
            and not news_pipeline.enough_evidence(verified,request)):
        raise ValueError('Araştırma kısmi: İstenen kapsam için en az iki bağımsız yayıncıdan tarihli haber kanıtı gerekli; açık tek haber/kaynak isteği kendi kapsamıyla değerlendirilir.')


def resume_recovery(runtime,job,started_steps,save):
    from modules import research_evidence,news_recovery
    if not isinstance(job,dict):return False
    request=job.get('request');steps=job.get('steps');outputs=job.get('outputs')
    if (not isinstance(request,str) or not request.strip() or not isinstance(steps,list) or not steps
            or not isinstance(outputs,dict)):
        return False
    if any(not isinstance(step,dict) or not step.get('id') for step in steps):return False
    if not research_evidence.news_requested(request):return False
    has_article=any(isinstance(o,dict) and o.get('state')=='done' and o.get('news_article') for o in outputs.values())
    if not has_article and not job.get('partial_report'):return False
    before=job.get('partial_report');old_ids={s['id'] for s in steps}
    try:
        news_recovery.deliver(runtime,job,existing_only=not bool(before),
            max_new_steps=max(0,24-(len(steps)-started_steps)))
    except (requests_state.Cancelled,PermissionError):raise
    except Exception as exc:
        _record_failure('modules/goal_executor.py:resume_news_delivery')
        job.setdefault('feedback',[]).append('Kayıtlı haber kurtarması tamamlanamadı: '+privacy.redact(str(exc),force=True)[:600])
        save(job);return False
    after=job.get('partial_report')
    reads=[]
    for step in job.get('steps',[]):
        if not isinstance(step,dict) or not step.get('id') or step['id'] in old_ids or step.get('started') is not True or step.get('state') not in {'done','failed'}:
            continue
        inp=step.get('input') if isinstance(step.get('input'),dict) else {}
        if step.get('tool')=='research' or step.get('tool')=='data' and inp.get('operation')=='headlines':
            reads.append(step)
    if after and (after!=before or reads):
        job['state']='paused'
        job['blocker']=('Kayıtlı hedef modelsiz sürdürüldü; yeni doğrulanmış kaynaklarla kısmi raporun yeni sürümü oluşturuldu. Eksik kapsam açık tutuldu.' if before and after!=before else
                        'Kayıtlı haberlerden kısmi rapor oluşturuldu ve dosyası doğrulandı; eksik kapsam hedefleri açık tutuldu.' if after!=before else
                        'Yeni kaynak denemeleri kaydedildi; mevcut kısmi rapor korundu. Eksik hedefler açık tutuldu.')
        save(job);return True
    # No progress: return control to the durable planner rather than trapping every resume.
    if after:
        job['blocker']='Mevcut kısmi rapor korundu; bu turda yeni kaynak okunmadı. Kalan hedefler için başka yöntem gerekiyor.'
        feedback=job.setdefault('feedback',[])
        if not feedback or feedback[-1]!=job['blocker']:feedback.append(job['blocker'])
        save(job)
    return False

