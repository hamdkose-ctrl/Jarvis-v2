"""Opt-in, model-free live public-data acceptance. No goals or accounts changed."""
from modules import service_store, public_data, domain_tools, task_agents, task_results, requests_state
from modules.diagnostics import record_failure as _record_failure
import re
from datetime import datetime,timezone,timedelta,date

PUBLISHER_INDEXES=('https://tubitak.gov.tr/tr/haberler','https://haberler.bogazici.edu.tr/')


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
    found=attempt('public_news_search',lambda:public_data.news_search(owner,'artificial intelligence',30,['gov.tr','edu.tr'],5))
    if found is not None:add('public_news_search','passed','Search response validated; eligible links: '+str(len(found['items'])))
    sources={};older={}
    request='Son 30 gün yapay zekâ haberlerini araştır; yeterli sonuç yoksa son 90 güne genişlet ve Türkçe rapor dosyası oluştur'
    def worker(kind,ident,data,deps):
        task={'id':ident,'agent':kind,'input':data,'execution':{'owner':owner,'job_id':'public-data-acceptance',
              'task_id':ident,'request':request,'source_only':True}}
        output=task_agents.worker(owner,task,deps)
        task_results.verify(output,owner=owner)
        return output
    seen=set()
    def articles(rows,prefix):
        for i,row in enumerate(rows[:2]):
            if row['url'] in seen:continue
            seen.add(row['url']);ident=prefix+str(i+1)
            result=attempt('public_news_'+ident,lambda:worker('research',ident,{'url':row['url'],'question':'Tarihli haberden yapay zekâ hakkında birebir alıntılar'},{}))
            if result:
                age=(datetime.now(timezone(timedelta(hours=3))).date()-date.fromisoformat(result['news_article']['published'])).days
                (sources if age<=30 else older)[ident]=result
                add('public_news_'+ident,'passed','Published date and literal article quotes verified')
    articles(found['items'] if found is not None else [],'article')
    if not sources:
        # Independent publisher reads; no repeated call to the slow search service.
        candidates=[]
        for i,url in enumerate(PUBLISHER_INDEXES):
            name='public_publisher_'+str(i+1)
            result=attempt(name,lambda:domain_tools.headlines(owner,url,query='yapay zeka'))
            if result is None:continue
            add(name,'passed','Publisher links read; article evidence still required')
            for row in result['items']:
                if re.search(r'yapay\s+zek|artificial\s+intelligence',row['title'],re.I) and row['url'] not in seen and not any(r['url']==row['url'] for r in candidates):
                    candidates.append(row);break
        articles(candidates,'publisher_article')
    if not sources and older:
        sources=older
        add('public_news_window','informational','No verified last-30-day article in bounded candidates; partial report expanded to last 90 days')
    if not sources:
        add('public_news_report','pending','No dated AI article verified; no report created')
        return checks
    filename='veri-kabul-90-gun-raporu.md' if sources is older else 'veri-kabul-raporu.md'
    report=attempt('public_news_report',lambda:worker('writer','report',{'instruction':'Kısmi kaynak alıntıları raporu; kapsam tamamlandı deme.','filename':filename},sources))
    if report:
        checked=attempt('public_news_verify',lambda:worker('verify','verify',{}, {'report':report}))
        if checked:add('public_news_report','passed','Partial report file and evidence verified: '+report['file'])
        else:add('public_news_report','pending','File created; final verification unavailable')
    return checks
