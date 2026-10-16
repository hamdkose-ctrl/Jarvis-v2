"""Bounded, source-only AI news delivery when the planner is unavailable.

Uses the existing journal and adapters. Does not complete goals or grant approvals.
"""
import hashlib
import json
import re
from urllib.parse import urlsplit
from modules import research_evidence, goal_tools


def deliver(runtime,job,*,max_new_steps=0):
    from modules import goal_executor as goals
    request=job['request']
    if (job['state'] in {'approval','review','cancelled'} or not job['goals'] or
        not research_evidence.news_requested(request) or not re.search(r'yapay\s+zek[aâ]',request,re.I) or
        not re.search(r'rapor',request,re.I) or not re.search(r'dosya|kaydet|markdown',request,re.I)):return
    if job.get('partial_report'):
        if job['outputs'].get(job['partial_report'],{}).get('state')=='done':
            goal_tools.verify(job['outputs'][job['partial_report']],job['owner']);return
        job.pop('partial_report',None)
    seeds=[]
    for step in job['steps']:
        if step.get('recovery'):continue
        if step['tool']=='research' or step['tool']=='data' and step['input'].get('operation')=='headlines':
            url=step['input'].get('url')
            if url and url not in seeds:seeds.append(url)
    seeds=seeds[-2:]
    if not seeds:return
    goal=next((i for i,g in enumerate(job['goals']) if g['state']!='done'),None)
    if goal is None:return
    count=sum(bool(s.get('recovery')) for s in job['steps']);new_steps=0
    def tool(kind,data,depends=()):
        nonlocal count,new_steps
        goals._ensure(runtime,job)
        signature=hashlib.sha256(json.dumps([kind,data],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        previous=next((s for s in reversed(job['steps']) if s.get('recovery') and s['signature']==signature),None)
        if previous:
            output=job['outputs'].get(previous['id'],{})
            if output.get('state')=='done':goal_tools.verify(output,job['owner'])
            return previous['id'],output
        if count>=10 or new_steps>=max_new_steps or len(job['steps'])>=96:return None,{}
        ident='s'+str(len(job['steps'])+1)
        while any(s['id']==ident for s in job['steps']):ident+='x'
        step={'id':ident,'goal':goal,'tool':kind,'input':data,'depends':list(depends),'signature':signature,
              'state':'queued','recovery':True,'source_only':True}
        job['steps'].append(step);count+=1;new_steps+=1
        goals._record(runtime,job,step)
        return ident,job['outputs'][ident]
    sources={}
    for step in job['steps']:
        output=job['outputs'].get(step['id'],{})
        if output.get('state')=='done' and output.get('news_article') and any(re.search(r'yapay\s+zek[aâ]',q,re.I) for q in output.get('source_quotes',[])):
            goal_tools.verify(output,job['owner']);sources[step['id']]=output
    candidates=[]
    for seed in seeds:
        ident,out=tool('data',{'operation':'headlines','url':seed,'query':'yapay zeka'})
        for row in out.get('structured',{}).get('items',[])[:3]:
            if row['url'] not in candidates:candidates.append(row['url'])
    # A failed publisher index can still have indexed articles. Keep the same
    # attempted domains; do not turn an official-source request into general news.
    if not candidates:
        from modules.public_data import _domains
        domains=_domains(list(dict.fromkeys(urlsplit(url).hostname for url in seeds)))
        ranges=[int(n) for n in re.findall(r'(?:son\s+)?(\d{1,4})\s*gün',request,re.I)]
        days=min(90,max(ranges)) if ranges else 7
        ident,out=tool('data',{'operation':'news_search','query':'artificial intelligence',
                              'days':max(1,days),'domains':domains,'limit':4})
        for row in out.get('structured',{}).get('items',[]):
            if row['url'] not in candidates:candidates.append(row['url'])
    # Also retry an already attempted article through the strict, model-free reader.
    for seed in seeds:
        if seed not in candidates:candidates.append(seed)
    for url in candidates[:4]:
        ident,out=tool('research',{'url':url,'question':'Yapay zekâ hakkında tarihli tekil haberden birebir alıntılar'})
        if out.get('state')=='done':sources[ident]=out
        if len(sources)>=3:break
    if not sources:return
    ident,out=tool('writer',{'instruction':'Kısmi kaynak alıntıları raporu; kapsam tamamlandı deme.','filename':'kismi-yapay-zeka-kaynaklari.md'},sources)
    if out.get('state')!='done':return
    checked,verification=tool('verify',{},[ident])
    if verification.get('state')=='done':
        job['partial_report']=ident;goals._save(job)
