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


def _decision_context(job: dict, step: dict) -> dict:
    """Derive the durable gate inputs from the active job, never gate defaults."""
    if not isinstance(job, dict) or not isinstance(step, dict):
        raise ValueError('Durable DecisionContext geçersiz.')
    owner = job.get('owner'); request = job.get('request')
    active_job = job.get('state') in {None, 'running'}
    active_step = step.get('state') in {None, 'running'}
    identity_ok = all(isinstance(value, str) and value for value in (owner, request))
    allowed = identity_ok and active_job and active_step
    return {
        'domain_invariant': 'pass' if allowed else 'block',
        'domain_authority': 'execute' if identity_ok else 'forbidden',
        'user_authority': 'execute' if isinstance(request, str) and request.strip() else 'forbidden',
        'job_authority': 'execute' if active_job and active_step else 'forbidden',
        # Recovery never re-enters execute_step(); it has its own effect-journal
        # route in goal_executor, so a fresh worker call is only ready here.
        'effect_state': 'ready',
    }


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
    # This legacy convenience path has no durable identity, DecisionContext,
    # WorkerResult fence or effect journal.  It must never become a second
    # executor for effects whose replay/recovery policy is conditional.
    if any(not goal_tools.replay_safe(task['tool'], task['input']) for task in tasks):
        raise PermissionError('Koşullu veya yan etkili uzman adımı durable yürütme hattından çalıştırılmalı.')
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
    from modules import hooks
    specialist=step.get('specialist')
    payload={'job_id':str(job.get('id','')),'step_id':str(step.get('id','')),'tool':str(step.get('tool','')),
             'specialist':str(specialist.get('id','') if isinstance(specialist,dict) else specialist or '')}
    hooks.observe('sub_agent',{**payload,'phase':'start'},owner=job.get('owner'))
    state='failed'
    try:
        output=_execute_step(runtime,job,step,identity,approval=approval)
        state=output.get('state','failed') if isinstance(output,dict) else 'failed'
        return output
    finally:
        hooks.observe('sub_agent',{**payload,'phase':'end','state':state},owner=job.get('owner'))


def _execute_step(runtime,job,step,identity,*,approval=None):
    if runtime.profile.slug!=job['owner']:raise PermissionError('Uzman görevinin sahibi değişti.')
    deps={key:job['outputs'][key] for key in step['depends']}
    # ``desktop`` is an existing goal adapter, not a new worker.  It joins the
    # same Core gate before native UIA/CUA/C# adapters can be introduced.
    # State setters enter the durable effect/receipt path only when they have
    # exact OS readback. Media keys remain outside until they do.
    durable_system=(step['tool']=='system' and step['input'].get('operation') in {'volume','mute','brightness'})
    gated={'media','publish','account','research','writer','browser','coder','verify','desktop'}
    if durable_system:
        gated.add('system')
    prepare_bound={'coder','desktop','system'}
    plan=None;expected=None
    worker_approval=approval
    if step['tool'] in gated:
        from modules import runtime_execution_gate
        if step['tool'] in prepare_bound and approval is not None and not step.get('runtime_approved'):
            from modules import runtime_prepare_approval
            runtime_prepare_approval.accept(approval,identity,step['tool'],step['input'])
            step['runtime_approved']=True
            # A Core approval proves this execution identity, not a particular
            # native UIA click.  Native adapters retain their own exact-action
            # approval artifact when they need one.
            worker_approval=None
        # Browser keeps its existing native approval contract.  Desktop/coder
        # use the bound Core prepare artifact tracked on the durable step.
        approval_verified=(step.get('runtime_approved') is True
                           if step['tool'] in prepare_bound else approval is not None)
        plan=runtime_execution_gate.plan_task(
            step['tool'],step['input'],approval_verified=approval_verified,
            **_decision_context(job, step),
        )
        if plan['phase']=='blocked':
            raise PermissionError('Capability runtime decision gate tarafından engellendi: '+plan['reason_code'])
        if plan['phase']=='prepare' and step['tool'] in prepare_bound:
            if step['tool']=='coder':
                from modules import developer
                state=developer.status(runtime.profile.slug)
                if not state.get('enabled') or not state.get('unlocked'):
                    raise goal_tools.NotStarted('Kod geliştirme alanı kilitli; hiçbir kod işlemi başlatılmadı. Rapor için writer, sahne/video için media kullan. Yalnız gerçekten kod geliştirmek gerekiyorsa kullanıcıdan geliştirme alanını açmasını iste.')
            from modules import runtime_prepare_approval
            return runtime_execution_gate.accept_prepare_result(
                plan,runtime_prepare_approval.prepare(identity,step['tool'],step['input']))
        if plan['phase']=='execute':
            from modules import runtime_worker_result
            if runtime_worker_result.durable_identity(identity):
                identity,expected=runtime_worker_result.prepare(identity,step['tool'],step['input'])
                from modules import effect_recovery_runtime
                if effect_recovery_runtime.required(step['tool']):
                    effect_recovery_runtime.record_intent(expected)

    if step['tool']=='research':
        from modules import research_evidence
        if research_evidence.news_requested(job['request']):
            from modules import model_free_news
            snapshot=step.get('pipeline_receipt')
            if snapshot is not None:
                from modules import task_results
                task_results.verify(snapshot,owner=job['owner'])
                if snapshot.get('source')!=step['input'].get('url'):
                    raise ValueError('Pipeline kanıtı araştırma adresiyle eşleşmiyor.')
                output=model_free_news.receipt(snapshot['news_article'],job['request'])
            else:
                output=model_free_news.run(job['owner'],step['input'],job['request'],source_only=identity.get('source_only') is True)
            if expected is not None:
                from modules import runtime_worker_result,worker_result_hook
                output=worker_result_hook.wrap_output(output,identity)
                output=runtime_worker_result.accept_and_commit(output,expected)
            return output

    if expected is not None:
        from modules import runtime_worker_result,worker_result_hook
        output=worker_result_hook.execute(runtime,step['tool'],step['input'],deps,identity,approval=worker_approval)
    else:
        output=goal_tools.execute(runtime,step['tool'],step['input'],deps,identity,approval=approval)
    if plan and plan['phase']=='prepare':
        from modules import runtime_execution_gate
        if step['tool']=='browser' and isinstance(output,dict) and output.get('state')=='done':
            from modules import runtime_worker_result,worker_result_hook
            if runtime_worker_result.durable_identity(identity):
                fenced_identity,browser_expected=runtime_worker_result.prepare(identity,step['tool'],step['input'])
                fenced=worker_result_hook.wrap_output(output,fenced_identity)
                return runtime_worker_result.accept_and_commit(fenced,browser_expected)
            return output
        return runtime_execution_gate.accept_prepare_result(plan,output)
    if expected is not None:
        # Native desktop adapters may ask a second, action-specific question.
        # That is neither a WorkerResult nor global completion.
        if isinstance(output,dict) and output.get('state')=='approval':
            return output
        if isinstance(output,dict) and output.get('state')=='done' and output.get('receipt') is not None:
            from modules import effect_recovery_runtime
            if effect_recovery_runtime.required(step['tool']):
                effect_recovery_runtime.record_receipt(expected,output)
        from modules import runtime_worker_result
        output=runtime_worker_result.accept_and_commit(output,expected)
    return output

