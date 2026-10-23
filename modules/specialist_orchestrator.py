"""Execute specialist-owned work across the common goal adapters.

This module does not grant permissions and does not invent capabilities. Jarvis supplies a
bounded plan; each step must belong to a registered specialist and still executes through
goal_tools, so account, publish, browser, desktop and other existing gates remain authoritative.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
from modules import goal_tools, requests_state, team_center
from modules.diagnostics import record_failure as _record_failure


def validate(owner, request, tasks):
    if not isinstance(request,str) or not request.strip() or len(request)>20000:
        raise ValueError('Uzman hedefi gerekli.')
    if not isinstance(tasks,list) or not 1<=len(tasks)<=16:
        raise ValueError('1-16 uzman adımı gerekli.')
    members={m['id']:m for m in team_center.members(owner) if m.get('enabled',True)}
    seen=set();result=[]
    for raw in tasks:
        if not isinstance(raw,dict) or set(raw)-{'id','specialist','tool','input','depends'}:
            raise ValueError('Uzman adımı alanları geçersiz.')
        ident=raw.get('id');specialist=raw.get('specialist');tool=raw.get('tool');deps=raw.get('depends',[])
        if not isinstance(ident,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,30}',ident) or ident in seen:
            raise ValueError('Uzman adım kimliği geçersiz.')
        member=members.get(specialist)
        if member is None:raise ValueError('Uzman kayıtlı veya etkin değil.')
        if tool not in member['tools']:raise ValueError('Seçilen uzman bu aracı kullanamaz.')
        if not isinstance(deps,list) or any(d not in seen for d in deps) or len(set(deps))!=len(deps):
            raise ValueError('Uzman bağımlılığı önceki tamamlanabilir adım olmalı.')
        data=goal_tools.validate(tool,copy.deepcopy(raw.get('input',{})))
        result.append({'id':ident,'specialist':specialist,'tool':tool,'input':data,'depends':list(deps)})
        seen.add(ident)
    return result


def run(runtime, request, tasks):
    owner=runtime.profile.slug;tasks=validate(owner,request,tasks);outputs={};journal=[]
    for task in tasks:
        requests_state.check()
        deps={key:outputs[key] for key in task['depends']}
        for value in deps.values():goal_tools.verify(value,owner)
        identity={'owner':owner,'job_id':'team-'+hashlib.sha256(request.encode()).hexdigest()[:12],
                  'task_id':task['id'],'request':request,'desktop_ids':[],
                  'specialist':task['specialist']}
        checkpoint=goal_tools.checkpoint(runtime,task['tool'],task['input'])
        try:
            output=goal_tools.execute(runtime,task['tool'],task['input'],deps,identity)
        except requests_state.Cancelled:raise
        except Exception:
            _record_failure('modules/specialist_orchestrator.py:execute')
            recovered=goal_tools.reconcile(runtime,task['tool'],task['input'],identity,checkpoint)
            if recovered is None:raise
            output=recovered
        if not isinstance(output,dict) or output.get('state')!='done':
            return {'state':output.get('state','failed') if isinstance(output,dict) else 'failed',
                    'request':request,'tasks':journal+[dict(task,state=output.get('state','failed') if isinstance(output,dict) else 'failed')],
                    'outputs':{**outputs,task['id']:output}}
        goal_tools.verify(output,owner);outputs[task['id']]=output
        journal.append({**task,'state':'done'})
    return {'state':'done','request':request,'tasks':journal,'outputs':outputs,
            'summary':json.dumps([{'id':t['id'],'specialist':t['specialist'],'tool':t['tool']} for t in journal],ensure_ascii=False)}


def execute_step(runtime,job,step,identity,*,approval=None):
    """A specialist executes inside the durable journal and runtime safety gates."""
    if runtime.profile.slug!=job['owner']:raise PermissionError('Uzman görevinin sahibi değişti.')
    deps={key:job['outputs'][key] for key in step['depends']}
    gated={'media','publish','account','research','writer','verify'}
    plan=None;expected=None
    if step['tool'] in gated:
        from modules import runtime_execution_gate
        plan=runtime_execution_gate.plan_task(
            step['tool'],step['input'],approval_verified=approval is not None,
        )
        if plan['phase']=='blocked':
            raise PermissionError('Capability runtime decision gate tarafından engellendi: '+plan['reason_code'])
        if plan['phase']=='execute':
            from modules import runtime_worker_result
            if runtime_worker_result.durable_identity(identity):
                identity,expected=runtime_worker_result.prepare(identity,step['tool'],step['input'])

    if step['tool']=='research':
        from modules import research_evidence
        if research_evidence.news_requested(job['request']):
            from modules import model_free_news
            output=model_free_news.run(job['owner'],step['input'],job['request'],source_only=identity.get('source_only') is True)
            if expected is not None:
                from modules import runtime_worker_result,worker_result_hook
                output=worker_result_hook.wrap_output(output,identity)
                output=runtime_worker_result.accept_and_commit(output,expected)
            return output

    if expected is not None:
        from modules import runtime_worker_result,worker_result_hook
        output=worker_result_hook.execute(runtime,step['tool'],step['input'],deps,identity,approval=approval)
    else:
        output=goal_tools.execute(runtime,step['tool'],step['input'],deps,identity,approval=approval)
    if plan and plan['phase']=='prepare':
        from modules import runtime_execution_gate
        return runtime_execution_gate.accept_prepare_result(plan,output)
    if expected is not None:
        from modules import runtime_worker_result
        output=runtime_worker_result.accept_and_commit(output,expected)
    return output
