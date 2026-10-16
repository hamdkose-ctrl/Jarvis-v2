"""Opt-in, model-free live public-data acceptance. No goals or accounts changed."""
from modules import service_store, domain_tools, task_agents, task_results, requests_state
from modules.diagnostics import record_failure as _record_failure
import re
from modules.publisher_news import SOURCES

PUBLISHER_INDEXES=tuple(s['url'] for s in SOURCES)


def run(owner):
    service_store.identity(owner)
    checks=[]
    def add(name,state,detail):checks.append({'check':name,'state':state,'detail':detail})
    def attempt(name,fn):
        service_store.identity(owner);requests_state.check()
        try:return fn()
        except requests_state.Cancelled:raise
        except PermissionError:raise
        except Exception as exc:
            _record_failure('modules/public_data_acceptance.py:attempt')
            # Public requests contain no credentials; do not persist raw errors/bodies.
            add(name,'pending','Live operation unavailable: '+type(exc).__name__)
            return None
    rate=attempt('public_exchange',lambda:domain_tools.exchange(owner,'USD','TRY'))
    if rate:add('public_exchange','passed','Daily USD/TRY source date: '+rate['data']['date'])
    add('public_news_search','informational','Direct official HTML/RSS publishers selected; no search service required')
    sources={}
    request='Son 7 gün yapay zekâ haberlerini araştır ve Türkçe rapor dosyası oluştur; daha eski haberlerle doldurma'
    def worker(kind,ident,data,deps):
        task={'id':ident,'agent':kind,'input':data,'execution':{'owner':owner,'job_id':'public-data-acceptance',
              'task_id':ident,'request':request,'source_only':True}}
        output=task_agents.worker(owner,task,deps)
        task_results.verify(output,owner=owner)
        return output
    seen=set()
    attempted=0
    def articles(rows):
        nonlocal attempted
        for i,row in enumerate(rows[:2]):
            if row['url'] in seen:continue
            if attempted>=6 or len(sources)>=2:break
            seen.add(row['url']);attempted+=1;ident='article'+str(attempted)
            result=attempt('public_news_'+ident,lambda:worker('research',ident,{'url':row['url'],'question':'Tarihli haberden yapay zekâ hakkında birebir alıntılar'},{}))
            if result:
                sources[ident]=result
                add('public_news_'+ident,'passed','Published date and literal article quotes verified')
    for i,url in enumerate(PUBLISHER_INDEXES):
        if attempted>=6 or len(sources)>=2:break
        name='public_publisher_'+str(i+1)
        result=attempt(name,lambda:domain_tools.headlines(owner,url,query='yapay zeka dijital'))
        if result is None:continue
        add(name,'passed','Publisher links read; article evidence still required')
        candidates=[r for r in result['items'] if re.search(r'yapay\s+zek|artificial\s+intelligence|dijital|inovasyon',r['title'],re.I)]
        articles(candidates or result['items'][:1])
    if not sources:
        add('public_news_report','pending','No last-7-day AI article verified in bounded sources; no report created or older news substituted')
        return checks
    filename='veri-kabul-haftalik-rapor.md'
    report=attempt('public_news_report',lambda:worker('writer','report',{'instruction':'Kısmi kaynak alıntıları raporu; kapsam tamamlandı deme.','filename':filename},sources))
    if report:
        checked=attempt('public_news_verify',lambda:worker('verify','verify',{}, {'report':report}))
        if checked:add('public_news_report','passed','Partial report file and evidence verified: '+report['file'])
        else:add('public_news_report','pending','File created; final verification unavailable')
    return checks
