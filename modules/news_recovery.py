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
    from modules import goal_executor as goals, goal_tools, news_pipeline

    if job['state'] in {'approval', 'review', 'cancelled'} or not job['goals']:
        return
    goal = next((index for index, item in enumerate(job['goals']) if item['state'] != 'done'), None)
    if goal is None:
        return

    if existing_only:
        verified = news_pipeline.verified_from_outputs(job.get('outputs') or {})
    else:
        result = news_pipeline.deliver_job(job, model_status='unavailable')
        verified = result['verified']

    # A plural/general request is complete only when the pipeline itself supplied
    # two dated articles from distinct publishers. No catalog-attempt counter can
    # substitute for this evidence.
    if not news_pipeline.enough_evidence(verified):
        return

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
        job['steps'].append(step)
        goals._record(runtime, job, step)
        remaining -= 1
        output = job['outputs'].get(ident, {})
        if output.get('state') == 'done' and output.get('news_article'):
            goal_tools.verify(output, job['owner'])
            evidence.append(ident)

    # The durable receipts must still independently meet the canonical threshold;
    # a failed re-read never becomes completion merely because the pipeline had it.
    durable = [job['outputs'][ident] for ident in evidence
               if job['outputs'].get(ident, {}).get('news_article')]
    durable_rows = [{'news_article': output['news_article']} for output in durable]
    if news_pipeline.enough_evidence(durable_rows):
        job['goals'][goal].update(state='done', evidence=evidence)
        goals._save(job)

def deliver(runtime, job, *, max_new_steps=0, existing_only=False):
    """Run the one news authority, then persist its receipts or an evidence-backed report.

    File and chat delivery share the same source decision. The writer may format
    receipts, but it never discovers sources or decides that a news task is complete.
    """
    from modules import goal_executor as goals, goal_tools, news_pipeline, research_evidence

    request = job.get('request', '')
    if (job.get('state') in {'approval', 'review', 'cancelled'} or not job.get('goals')
            or not research_evidence.news_requested(request)):
        return

    _chat_deliver(runtime, job, max_new_steps=max_new_steps, existing_only=existing_only)
    news_pipeline.attach_job(job, model_status='unavailable')

    if not research_evidence.file_requested(request):
        return
    goal = next((index for index, item in enumerate(job['goals']) if item.get('evidence')), None)
    if goal is None or job.get('partial_report') or max_new_steps <= 0:
        return
    evidence = list(job['goals'][goal]['evidence'])
    if len(job.get('steps', [])) >= 96:
        return

    ident = 's' + str(len(job['steps']) + 1)
    while any(step['id'] == ident for step in job['steps']):
        ident += 'x'
    step = {
        'id': ident, 'goal': goal, 'tool': 'writer',
        'input': {
            'instruction': ('Doğrulanmış haber kanıtlarından kaynak, tarih, bağlantı ve '
                            'alıntılarıyla rapor oluştur; kanıtsız çıkarım ekleme.'),
            'filename': 'haber-kaynak-raporu.md',
        },
        'depends': evidence, 'state': 'queued', 'recovery': True,
        'recovery_version': 'pipeline_receipts_v1', 'source_only': False,
    }
    job['steps'].append(step)
    goals._record(runtime, job, step)
    output = job['outputs'].get(ident, {})
    if output.get('state') == 'done':
        goal_tools.verify(output, job['owner'])
        job['partial_report'] = ident
        goals._save(job)
