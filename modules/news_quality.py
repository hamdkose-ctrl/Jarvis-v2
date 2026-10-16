"""Post-check broad AI news goals without bypassing the durable goal executor."""
import re
from modules import goal_executor, goal_tools, news_recovery, publisher_news, research_evidence


def _eligible(job):
    request=str((job or {}).get('request') or '')
    return bool(job and publisher_news.broad_research(request) and research_evidence.news_requested(request)
                and re.search(r'yapay\s+zek[aâ]',request,re.I) and re.search(r'rapor',request,re.I)
                and re.search(r'dosya|kaydet|markdown',request,re.I))


def _catalog():
    return {publisher_news.publisher_key(row['url']):row for row in publisher_news.SOURCES}


def _attempted(job):
    keys=set(job.get('news_catalog_attempted',[]))
    catalog=_catalog()
    for step in job.get('steps',[]):
        data=step.get('input',{})
        if step.get('tool')=='data' and data.get('operation')=='headlines' and data.get('url'):
            key=publisher_news.publisher_key(data['url'])
            if key in catalog:keys.add(key)
    return keys


def _report(job):
    rows=[(ident,out) for ident,out in job.get('outputs',{}).items()
          if out.get('state')=='done' and out.get('news_report_evidence')]
    return rows[-1] if rows else (None,None)


def _sources(job):
    rows=[]
    for ident,out in job.get('outputs',{}).items():
        if out.get('state')!='done' or not out.get('news_article'):continue
        try:
            source=research_evidence.news_receipt(out)
            research_evidence.news_date(source['published'],job['request'])
        except (ValueError,PermissionError,OSError):continue
        if re.search(r'yapay\s+zek[aâ]', ' '.join(out.get('source_quotes',[])),re.I):rows.append((ident,out))
    return rows


def _complete_from_verified_recovery(job):
    report_id,report=_report(job);sources=_sources(job)
    if not report_id or not sources:return False
    source_ids=[ident for ident,_ in sources]
    for goal in job['goals']:
        text=goal['text'].casefold()
        evidence=[report_id] if re.search(r'rapor|dosya|markdown|kaydet',text) else source_ids
        if not evidence:return False
        goal.update(state='done',evidence=evidence)
    job['state']='running';job.pop('blocker',None);goal_executor._save(job)
    return goal_executor._finish_completed(job)


def _present(job,fallback):
    report_id,report=_report(job)
    if not report:return fallback
    evidence=report.get('news_report_evidence',{})
    items=[]
    for out in evidence.get('sources',{}).values():
        source=out.get('news_article')
        if source and source['url'] not in {row['url'] for row in items}:items.append(source)
    publishers={publisher_news.publisher_key(row['url']) for row in items}
    catalog=_catalog();attempted=_attempted(job)
    names=[catalog[key]['name'] for key in catalog if key in attempted]
    missing=[catalog[key]['name'] for key in catalog if key in attempted and key not in publishers]
    state='Araştırma tamamlandı' if job.get('state')=='done' else 'Araştırma kısmi'
    lines=[state,'','Özet',f'- {len(attempted)}/{len(catalog)} kayıtlı kaynak tarandı.',
           f'- {len(items)} doğrulanmış gelişme bulundu.',f'- {len(publishers)} farklı yayıncıdan kanıt alındı.']
    if items:
        lines+=['','Öne çıkan gelişmeler']
        for index,source in enumerate(items[:6],1):
            lines.append(f'{index}. {source["title"]} — {source["published"]}')
            lines.append('   Kaynak: '+source['url'])
    lines+=['','Kapsam']
    if names:lines.append('- Taranan kaynaklar: '+', '.join(names)+'.')
    if missing:lines.append('- Taranıp rapora doğrulanmış AI haberi girmeyen kaynaklar: '+', '.join(missing)+'.')
    if len(attempted)<len(catalog):lines.append(f'- Katalog taraması tamamlanmadı: {len(catalog)-len(attempted)} kaynak daha var.')
    lines+=['','Rapor',report.get('file','')]
    return '\n'.join(lines).strip()


def run(runtime,command):
    """Run the common executor, then enforce broad-news coverage and present one clean summary."""
    result=goal_executor.run(runtime,command)
    job=goal_executor.latest(runtime.profile.slug)
    if not _eligible(job):return result
    if job.get('state')=='done' and len(_attempted(job))<len(_catalog()):
        report_id,_=_report(job)
        if report_id:job['partial_report']=report_id
        for goal in job['goals']:goal.update(state='pending',evidence=[])
        job['state']='paused'
        job.setdefault('feedback',[]).append('Geniş Türkiye araştırması iki yayıncıda erken kapatılmadı; kayıtlı haber kataloğunun tamamı taranmalı.')
        goal_executor._save(job)
        news_recovery.deliver(runtime,job,max_new_steps=24,existing_only=False)
        job=goal_executor.latest(runtime.profile.slug)
        if len(_attempted(job))==len(_catalog()) and len({publisher_news.publisher_key(out['news_article']['url']) for _,out in _sources(job)})>=2:
            _complete_from_verified_recovery(job)
            job=goal_executor.latest(runtime.profile.slug)
        else:
            job['state']='paused'
            job['blocker']='Geniş Türkiye araştırmasının kayıtlı kaynak taraması tamamlanamadı; mevcut doğrulanmış sonuçlar korundu.'
            goal_executor._save(job)
    return _present(goal_executor.latest(runtime.profile.slug),result)
