"""Haber araştırması tamamlanma ve kayıtlı kurtarma politikası (goal_executor'dan taşındı, davranış aynı).

Yürütücü genel kalır; haber kuralları (tekil makale kanıtı, iki yayıncı, katalog denemesi, modelsiz kurtarma)
burada durur. goal_executor aynı adlı ince sarmalayıcılarla çağırır.
"""
import re
from modules import privacy, requests_state
from modules.diagnostics import record_failure as _record_failure


def check_completion(job,goal,evidence,*,final=False):
    from modules import research_evidence
    if not research_evidence.news_requested(job['request']):return
    steps={s['id']:s for s in job['steps']};pending=list(evidence);seen=set()
    discovery=False;article=False;publishers=set()
    while pending:
        ident=pending.pop()
        if ident in seen:continue
        seen.add(ident);step=steps.get(ident,{})
        output=job['outputs'].get(ident,{})
        if output.get('state')!='done':continue
        if output.get('news_article'):
            source=research_evidence.news_receipt(output)
            research_evidence.news_date(source['published'],job['request']);article=True
            from modules import publisher_news
            publishers.add(publisher_news.publisher_key(source['url']))
        if step.get('tool')=='data' and step.get('input',{}).get('operation') in {'sources','headlines','news_search'}:discovery=True
        pending.extend(step.get('depends',[]))
    if final or job.get('state')=='done':
        from modules import publisher_news
        publisher_news.require_catalog(job)
    text=goal['text'].casefold()
    discovery_goal=(re.search(r'kaynak|bağlantı|baglanti|başlık|baslik|dizin|katalog',text) and
                    re.search(r'bul|listele|keşfet|kesfet|seç|sec|belirle',text) and
                    not re.search(r'araştır|arastir|incele|analiz|doğrula|dogrula|rapor|özet|ozet|değerlendir|degerlendir',text))
    if discovery and not article and not discovery_goal:
        raise ValueError('Haber araştırması yalnız bağlantı/başlık keşfiyle tamamlanamaz; tekil haber gövdesi ve yayın tarihi kanıtı gerekli.')
    from modules import publisher_news
    if (not discovery_goal and re.search(r'araştır|arastir|haber|gelişme|rapor|incele|analiz|özet|ozet',text)
            and publisher_news.broad_research(job['request']) and len(publishers)<2):
        raise ValueError(f'Araştırma kısmi: {len(publishers)} bağımsız yayıncı doğrulandı. Genel Türkiye araştırmasını tamamlamak için en az iki yayıncıdan tarihli haber kanıtı gerekli; tek haber bütün kapsam sayılmaz.')


def resume_recovery(runtime,job,started_steps,save):
    from modules import research_evidence,news_recovery
    if not job['steps'] or not research_evidence.news_requested(job['request']):return False
    has_article=any(o.get('state')=='done' and o.get('news_article') for o in job['outputs'].values())
    if not has_article and not job.get('partial_report'):return False
    before=job.get('partial_report');old_ids={s['id'] for s in job['steps']}
    try:
        news_recovery.deliver(runtime,job,existing_only=not bool(before),
            max_new_steps=max(0,24-(len(job['steps'])-started_steps)))
    except (requests_state.Cancelled,PermissionError):raise
    except Exception as exc:
        _record_failure('modules/goal_executor.py:resume_news_delivery')
        job.setdefault('feedback',[]).append('Kayıtlı haber kurtarması tamamlanamadı: '+privacy.redact(str(exc),force=True)[:600])
        save(job);return False
    after=job.get('partial_report')
    reads=[s for s in job['steps'] if s['id'] not in old_ids and s.get('started') is True and
           s.get('state') in {'done','failed'} and (s['tool']=='research' or s['tool']=='data' and s['input'].get('operation')=='headlines')]
    if after and reads:
        from modules import publisher_news
        if publisher_news.broad_research(job['request']) and publisher_news.catalog_keys().issubset(publisher_news.catalog_attempted(job)):
            job['blocker']='Kayıtlı katalog denemeleri tamamlandı; doğrulanmış rapor korundu. Kalan hedefler gerçek kanıtlarıyla denetleniyor.'
            save(job);return False
    if after and (after!=before or reads):
        job['state']='paused'
        job['blocker']=('Kayıtlı hedef modelsiz sürdürüldü; yeni doğrulanmış kaynaklarla kısmi raporun yeni sürümü oluşturuldu. Eksik kapsam açık tutuldu.' if before and after!=before else
                        'Kayıtlı haberlerden kısmi rapor oluşturuldu ve dosyası doğrulandı; eksik kapsam hedefleri açık tutuldu.' if after!=before else
                        'Yeni kaynak denemeleri kaydedildi; mevcut kısmi rapor korundu. Eksik hedefler açık tutuldu.')
        save(job);return True
    # No progress: return control to the durable planner rather than trapping every resume.
    if after:
        job['blocker']='Mevcut kısmi rapor korundu; bu turda yeni kaynak okunmadı. Kalan hedefler için başka yöntem gerekiyor.'
        job.setdefault('feedback',[]).append(job['blocker']);save(job)
    return False
