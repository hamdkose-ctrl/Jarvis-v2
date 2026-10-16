"""Bounded, source-only AI news delivery when the planner is unavailable.

Uses the existing journal and adapters. Does not complete goals or grant approvals.
"""
import hashlib
import json
import re
import time
from modules import research_evidence, goal_tools


def deliver(runtime,job,*,max_new_steps=0,existing_only=False):
    from modules import goal_executor as goals
    request=job['request'];state_at_start=job['state']
    if (job['state'] in {'approval','review','cancelled'} or not job['goals'] or
        not research_evidence.news_requested(request) or not re.search(r'yapay\s+zek[aâ]',request,re.I) or
        not re.search(r'rapor',request,re.I) or not re.search(r'dosya|kaydet|markdown',request,re.I)):return
    previous_report=None
    previous_id=job.get('partial_report') or job.get('resume_partial_report')
    if previous_id:
        if job['outputs'].get(previous_id,{}).get('state')=='done':
            previous_report=job['outputs'][previous_id]
            goal_tools.verify(previous_report,job['owner'])
        else:
            job.pop('partial_report',None);job.pop('resume_partial_report',None)
    # A question-state resume may deliver the already verified partial once without a model.
    # On the next bare resume, release that one-shot gate so the durable planner can continue.
    if job.get('partial_report') and job.get('resume_partial_report')==job.get('partial_report'):
        job.pop('partial_report',None);goals._save(job);return
    seeds=[]
    for step in job['steps']:
        if step.get('recovery'):continue
        if step['tool']=='research' or step['tool']=='data' and step['input'].get('operation')=='headlines':
            url=step['input'].get('url')
            if url and url not in seeds:seeds.append(url)
    from modules import publisher_news
    seeds=publisher_news.recovery_indexes(request,seeds[-2:])
    if not seeds and not existing_only:return
    goal=next((i for i,g in enumerate(job['goals']) if g['state']!='done'),None)
    if goal is None:return
    count=sum(bool(s.get('recovery')) for s in job['steps']);new_steps=0;deadline=time.monotonic()+45
    def tool(kind,data,depends=()):
        nonlocal count,new_steps
        goals._ensure(runtime,job)
        signature=hashlib.sha256(json.dumps([kind,data],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        previous=next((s for s in reversed(job['steps']) if s.get('recovery') and s['signature']==signature),None)
        if previous:
            output=job['outputs'].get(previous['id'],{})
            if output.get('state')=='done':goal_tools.verify(output,job['owner'])
            return previous['id'],output
        if kind in {'data','research'} and time.monotonic()>=deadline:return None,{}
        if count>=10 or new_steps>=max_new_steps or len(job['steps'])>=96:return None,{}
        if count>=8 and kind not in {'writer','verify'}:return None,{}
        ident='s'+str(len(job['steps'])+1)
        while any(s['id']==ident for s in job['steps']):ident+='x'
        step={'id':ident,'goal':goal,'tool':kind,'input':data,'depends':list(depends),'signature':signature,
              'state':'queued','recovery':True,'recovery_version':'publishers_v1','source_only':True}
        job['steps'].append(step);count+=1;new_steps+=1
        goals._record(runtime,job,step)
        return ident,job['outputs'][ident]
    sources={}
    for step in job['steps']:
        output=job['outputs'].get(step['id'],{})
        if output.get('state')=='done' and output.get('news_article') and any(re.search(r'yapay\s+zek[aâ]',q,re.I) for q in output.get('source_quotes',[])):
            goal_tools.verify(output,job['owner']);sources[step['id']]=output
    previous_urls={o['news_article']['url'] for o in (previous_report or {}).get('news_report_evidence',{}).get('sources',{}).values() if o.get('news_article')}
    def source_urls():return {o['news_article']['url'] for o in sources.values()}
    # Kullanıcı hedefinde açık bir haber URL'si verdiyse, doğrulanmış kısmi dosya o
    # kaynak kapsamını temsil eder. Sırf "devam" dendi diye başka yayıncılara genişletme.
    explicit_urls={u.rstrip('.,!?)\"\'”') for u in re.findall(r'https?://[^\s<>|]+',request)}
    if previous_report and explicit_urls and source_urls() and source_urls().issubset(explicit_urls):return
    if previous_report and existing_only and source_urls()==previous_urls:return
    broad=publisher_news.broad_research(request)
    def publisher_keys():return {publisher_news.publisher_key(url) for url in source_urls()}
    def sufficient():return len(publisher_keys())>=2 if broad else len(sources)>=2
    candidates=[];attempted=set()
    for seed in ([] if existing_only else seeds):
        # Two publishers are enough to write a verified partial report, but they are
        # not proof that a broad Turkey scan is complete. Keep scanning the registered
        # catalog within the bounded recovery budget. Narrow requests retain the old
        # early-stop behavior.
        if not broad and sufficient():break
        ident,out=tool('data',{'operation':'headlines','url':seed,'query':'yapay zeka dijital'})
        rows=out.get('structured',{}).get('items',[])
        related=[r for r in rows if re.search(r'yapay\s+zek|artificial\s+intelligence|dijital|inovasyon',r['title'],re.I)]
        limit=1 if broad else 2
        for row in (related or rows)[:limit]:
            if row['url'] in attempted:continue
            attempted.add(row['url'])
            ident,result=tool('research',{'url':row['url'],'question':'Yapay zekâ hakkında tarihli tekil haberden birebir alıntılar'})
            if result.get('state')=='done':sources[ident]=result
            if result.get('state')=='done' or not broad and sufficient():break
        if not broad and sufficient():break
    for seed in seeds:
        if seed not in candidates:candidates.append(seed)
    for url in candidates[:2] if not sources and not existing_only else []:
        if url in attempted:continue
        ident,out=tool('research',{'url':url,'question':'Yapay zekâ hakkında tarihli tekil haberden birebir alıntılar'})
        if out.get('state')=='done':sources[ident]=out
        if len(sources)>=3:break
    if not sources:return
    if previous_report and source_urls()==previous_urls:return
    version=hashlib.sha256(json.dumps(sorted(source_urls())).encode()).hexdigest()[:12]
    ident,out=tool('writer',{'instruction':'Kısmi kaynak alıntıları raporu; kapsam tamamlandı deme. Kaynak sürümü: '+version,'filename':'kismi-yapay-zeka-kaynaklari.md'},sources)
    if out.get('state')!='done':return
    checked,verification=tool('verify',{},[ident])
    if verification.get('state')=='done':
        job['partial_report']=ident
        if state_at_start=='question':job['resume_partial_report']=ident
        else:job.pop('resume_partial_report',None)
        goals._save(job)
