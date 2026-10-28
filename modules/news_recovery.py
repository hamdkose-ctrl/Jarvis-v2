"""Bounded, source-only news delivery when the planner is unavailable.

Uses the existing journal and adapters. Does not grant approvals. File-backed AI report
recovery keeps its established contract; ordinary current-news chat can also recover from
configured publisher indexes or real URLs already attempted by the durable planner.
"""
import hashlib
import json
import re
import time
from modules import research_evidence, goal_tools, requests_state
from modules.diagnostics import record_failure as _record_failure


def _chat_deliver(runtime, job, *, max_new_steps=0, existing_only=False):
    """Seal only canonical pipeline evidence into the durable job.

    Recovery has no source ranking, headline traversal or completion policy. It can
    only persist articles already verified by the canonical pipeline.
    """
    from modules import goal_executor as goals, goal_tools, news_pipeline, model_free_news

    if job['state'] in {'approval', 'review', 'cancelled'} or not job['goals']:
        return
    goal = next((index for index, item in enumerate(job['goals']) if item['state'] != 'done'), None)
    if goal is None:
        return

    if existing_only:
        verified = news_pipeline.verified_from_outputs(job.get('outputs') or {})
    else:
        result = news_pipeline.deliver_job(job, model_status='unavailable',
                                           max_sources=news_pipeline.BROAD_MAX_SOURCES)
        verified = result['verified']

    # A plural/general request is complete only when the pipeline itself supplied
    # two dated articles from distinct publishers. No catalog-attempt counter can
    # substitute for this evidence.

    existing = {
        output.get('news_article', {}).get('url'): ident
        for ident, output in (job.get('outputs') or {}).items()
        if isinstance(output, dict) and output.get('state') == 'done' and output.get('news_article')
    }
    remaining = max(0, int(max_new_steps))
    evidence = []
    for row in verified:
        url = row['news_article']['url']
        ident = existing.get(url)
        if ident:
            goal_tools.verify(job['outputs'][ident], job['owner'])
            model_free_news.receipt(job['outputs'][ident]['news_article'],job['request'])
            evidence.append(ident)
            continue
        if remaining <= 0:
            break
        signature = hashlib.sha256(json.dumps(
            ['research', {'url': url, 'question': job['request']}],
            sort_keys=True, ensure_ascii=False,
        ).encode()).hexdigest()
        previous = next((step for step in reversed(job['steps'])
                         if step.get('recovery') and step.get('signature') == signature), None)
        if previous:
            output = job['outputs'].get(previous['id'], {})
            if output.get('state') == 'done' and output.get('news_article'):
                goal_tools.verify(output, job['owner'])
                evidence.append(previous['id'])
            continue
        if len(job['steps']) >= 96:
            break
        ident = 's' + str(len(job['steps']) + 1)
        while any(step['id'] == ident for step in job['steps']):
            ident += 'x'
        step = {
            'id': ident, 'goal': goal, 'tool': 'research',
            'input': {'url': url, 'question': job['request']}, 'depends': [],
            'signature': signature, 'state': 'queued', 'recovery': True,
            'recovery_version': 'pipeline_receipts_v1', 'source_only': True,
        }
        step['pipeline_receipt']=model_free_news.receipt(row['news_article'],job['request'])
        job['steps'].append(step)
        goals._record(runtime, job, step)
        step.pop('pipeline_receipt',None)
        remaining -= 1
        output = job['outputs'].get(ident, {})
        if output.get('state') == 'done' and output.get('news_article'):
            goal_tools.verify(output, job['owner'])
            evidence.append(ident)

    if evidence:
        job['goals'][goal]['chat_evidence']=evidence
        goals._save(job)

    # The durable receipts must still independently meet the canonical threshold;
    # a failed re-read never becomes completion merely because the pipeline had it.
    durable = [job['outputs'][ident] for ident in evidence
               if job['outputs'].get(ident, {}).get('news_article')]
    durable_rows = [{'news_article': output['news_article']} for output in durable]
    if news_pipeline.enough_evidence(durable_rows,job['request']) and not research_evidence.file_requested(job['request']):
        job['goals'][goal].update(state='done', evidence=evidence)
        goals._save(job)

def deliver(runtime,job,*,max_new_steps=0,existing_only=False):
    """Chat and file delivery consume the same canonical pipeline receipts."""
    from modules import goal_executor as goals, news_pipeline
    if (job.get('state') in {'approval','review','cancelled'} or not job.get('goals')
            or not research_evidence.news_requested(job.get('request',''))):
        return
    before=len(job['steps'])
    _chat_deliver(runtime,job,max_new_steps=max_new_steps,existing_only=existing_only)
    if not research_evidence.file_requested(job['request']):
        return
    evidence=[]
    for goal in job['goals']:
        for ident in goal.get('chat_evidence',[]) + goal.get('evidence',[]):
            if ident not in evidence and job['outputs'].get(ident,{}).get('news_article'):
                evidence.append(ident)
    if not evidence:
        return
    sources={ident:job['outputs'][ident] for ident in evidence}
    for output in sources.values():
        goal_tools.verify(output,job['owner'])
    previous_id=job.get('partial_report') or job.get('resume_partial_report')
    previous=job['outputs'].get(previous_id,{})
    if previous.get('state')=='done':
        goal_tools.verify(previous,job['owner'])
        old={o['news_article']['url'] for o in previous.get('news_report_evidence',{}).get('sources',{}).values()
             if o.get('news_article')}
        if old=={o['news_article']['url'] for o in sources.values()}:
            return
    # Reserve the complete writer + verify pair before any file is created.
    if max_new_steps-(len(job['steps'])-before)<2 or len(job['steps'])>94:
        return
    goal=next((i for i,g in enumerate(job['goals']) if g['state']!='done'),0)
    def record(kind,data,depends):
        goals._ensure(runtime,job)
        ident='s'+str(len(job['steps'])+1)
        while any(s['id']==ident for s in job['steps']):
            ident+='x'
        signature=hashlib.sha256(json.dumps([kind,data,depends],sort_keys=True).encode()).hexdigest()
        step={'id':ident,'goal':goal,'tool':kind,'input':data,'depends':depends,
              'signature':signature,'state':'queued','recovery':True,
              'recovery_version':'pipeline_receipts_v1','source_only':True}
        job['steps'].append(step)
        goals._record(runtime,job,step)
        return ident,job['outputs'].get(ident,{})
    report,output=record('writer',{'instruction':'Kaynak, tarih, bağlantı ve birebir alıntılı haber raporu. Eksik kapsamı tamamlandı gösterme.',
                                  'filename':'haber-kaynak-raporu.md'},evidence)
    if output.get('state')!='done':
        return
    checked_id,checked=record('verify',{},[report])
    if checked.get('state')=='done':
        job['partial_report']=report
        if len(job['goals'])==1 and news_pipeline.enough_evidence(
                [{'news_article':o['news_article']} for o in sources.values()],job['request']):
            job['goals'][0].update(state='done',evidence=[report,checked_id])
            job['goals'][0].pop('chat_evidence',None)
        goals._save(job)
