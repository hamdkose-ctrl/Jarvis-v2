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
    # A canonical dependent must never trust in-memory ExecutionRecord outputs
    # solely because they are present or say "done". Validate the exact
    # accepted predecessor-output hashes and domain readback *before* any
    # DecisionAuthority, checkpoint, worker, model or provider invocation.
    # Legacy/unplanned dependencies retain their original execution path.
    # Always inspect canonical authority; a caller could strip both the
    # dependency list and durable version from a dependent step.
    from modules import dependency_evidence, goal_plan_gate
    deps=None
    job_id=job.get('id')
    identity_job_id=identity.get('job_id') if isinstance(identity,dict) else None
    # A planned job cannot lose its ExecutionRecord ID before the predecessor
    # proof is checked. Reject this early: domain re-verification must never
    # obscure a missing canonical execution identity. Some historical direct
    # specialist calls legitimately have no job['id'] and no canonical plan.
    if not isinstance(job_id,str) and isinstance(identity_job_id,str):
        from modules import runtime_worker_result
        try:
            canonical=runtime_worker_result.canonical_snapshot(identity)
        except FileNotFoundError:
            if job.get('_canonical_version') is not None:
                raise goal_plan_gate.PlanFenceError(
                    'Canonical specialist requires exact ExecutionRecord job ID.'
                ) from None
        else:
            if canonical.get('goal_plan') is not None:
                raise goal_plan_gate.PlanFenceError(
                    'Canonical specialist requires exact ExecutionRecord job ID.'
                )
    # Legacy direct specialist calls can lack a durable job ID entirely.
    # But a canonical job may have its runtime dependency list or version
    # marker stripped, so file-backed authority is checked whenever the
    # execution identity gives us an addressable owner/job pair.
    if isinstance(job_id,str) or isinstance(identity_job_id,str):
        deps=dependency_evidence.preflight_durable_step(
            identity, step, job.get('outputs'),
            owner=job['owner'], job_id=job_id if isinstance(job_id,str) else identity_job_id,
            canonical_required=job.get('_canonical_version') is not None,
        )
        if deps is not None and job_id != identity_job_id:
            raise goal_plan_gate.PlanFenceError(
                'Canonical specialist requires exact ExecutionRecord job ID.'
            )
    elif isinstance(identity,dict) and 'version' in identity:
        raise goal_plan_gate.PlanFenceError(
            'Versioned specialist execution has no durable job ID.'
        )
    if deps is None:
        deps={key:job['outputs'][key] for key in step['depends']}
    # ``desktop`` is an existing goal adapter, not a new worker.  It joins the
    # same Core gate before native UIA/CUA/C# adapters can be introduced.
    # State setters enter the durable effect/receipt path only when they have
    # exact OS readback. Media keys remain outside until they do.
    durable_system=(step['tool']=='system' and step['input'].get('operation') in {'volume','mute','brightness'})
    gated={'media','file','finance','computer','publish','account','research','writer','browser','coder','verify','desktop'}
    if durable_system:
        gated.add('system')
    prepare_bound={'coder','desktop','system','writer'}
    if (step['tool'] in ('publish','browser') and isinstance(identity,dict)
            and identity.get('_canonical_scheduler_offer') is not None):
        prepare_bound.add(step['tool'])
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
            if step['tool'] == 'writer':
                if step.get('runtime_approved') is not True:
                    raise PermissionError('Writer dosya yazmadan önce açık onay gerektirir.')
                # The existing GoalApproval and exact prepare artifact were
                # checked before this single invocation; never persist the flag.
                identity = {**identity, '_writer_approved': True}
            from modules import runtime_worker_result
            if runtime_worker_result.durable_identity(identity):
                identity,expected=runtime_worker_result.prepare(identity,step['tool'],step['input'])
                from modules import effect_recovery_runtime
                if (effect_recovery_runtime.required(step['tool'])
                        or (step['tool'] in ('writer', 'media', 'browser') and 'plan_version' in expected)):
                    # Planned writer reports also need write-ahead identity:
                    # a crash after atomic file creation cannot authorize
                    # another automatically generated report.
                    # A bound desktop resume continues the SAME exact command
                    # fence whose intent is already durable; re-recording would
                    # be a replay, not a new effect.
                    if not (step['tool'] == 'desktop'
                            and isinstance(identity, dict)
                            and identity.get('_canonical_desktop_resume')
                            and effect_recovery_runtime.status(expected) != 'not_started'):
                        effect_recovery_runtime.record_intent(expected)

    if step['tool']=='research':
        from modules import research_evidence
        if research_evidence.news_requested(job['request']):
            from contextlib import nullcontext
            from modules import model_free_news
            news_scope = nullcontext(None)
            if (expected is not None and 'plan_version' in expected
                    and expected['capability_id'] == 'task.research'):
                from modules import goal_executor, scheduler_resource_gate
                guard = (scheduler_resource_gate.dependent_research_worker
                         if deps else scheduler_resource_gate.root_research_worker)
                news_scope = guard(
                    goal_executor._RESOURCE_LEASES, identity, expected,
                )
            with news_scope as dependent_commit:
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
                    if isinstance(output,dict) and output.get('state')=='done':
                        goal_tools.verify(output,job['owner'])
                    output=worker_result_hook.wrap_output(output,identity)
                    output=(dependent_commit(output) if dependent_commit is not None
                            else runtime_worker_result.accept_and_commit(output,expected))
                return output

    if (expected is not None and 'plan_version' in expected
            and expected['capability_id'] == 'task.research'):
        # Root and dependent read-only research now reserve the same
        # exact-command namespace through the real worker and Core CAS.
        # This is never a global provider mutex; other roots may overlap.
        from modules import goal_executor, scheduler_resource_gate, worker_result_hook
        guard = (scheduler_resource_gate.dependent_research_worker
                 if deps else scheduler_resource_gate.root_research_worker)
        with guard(
            goal_executor._RESOURCE_LEASES, identity, expected,
        ) as commit_checked:
            research_output=worker_result_hook.execute(
                runtime,step['tool'],step['input'],deps,identity,
                approval=worker_approval,
            )
            if isinstance(research_output,dict) and research_output.get('state')=='approval':
                return research_output
            return commit_checked(research_output)

    if (expected is not None and 'plan_version' in expected
            and step['tool'] == 'verify'):
        from modules import goal_executor, scheduler_resource_gate, worker_result_hook
        with scheduler_resource_gate.dependent_verify_worker(
            goal_executor._RESOURCE_LEASES, identity, expected,
        ) as commit_checked:
            verified = worker_result_hook.execute(
                runtime, step['tool'], step['input'], deps, identity,
                approval=worker_approval,
            )
            return commit_checked(verified)

    if (expected is not None and 'plan_version' in expected
            and step['tool'] == 'account'):
        # The existing durable goal executor owns one in-process lease table.
        # Only this explicitly supported, read-only canonical capability is
        # live-wired. Permission/DecisionAuthority already ran above, and
        # neither account read nor ResourceLease authorizes a write/effect.
        from modules import goal_executor,scheduler_resource_gate,worker_result_hook
        with scheduler_resource_gate.account_read_worker(
            goal_executor._RESOURCE_LEASES, identity, expected,
        ) as commit_checked:
            account_output=worker_result_hook.execute(
                runtime,step['tool'],step['input'],deps,identity,approval=worker_approval,
            )
            if isinstance(account_output,dict) and account_output.get('state')=='approval':
                return account_output
            return commit_checked(account_output)

    if (expected is not None and 'plan_version' in expected
            and step['tool'] in ('file', 'finance', 'computer')):
        # The same canonical read-only lease covers extraction, domain proof
        # and Core WorkerResult CAS; it is never an unleased direct file read.
        from modules import goal_executor, scheduler_resource_gate, worker_result_hook
        with scheduler_resource_gate.read_only_worker(
            goal_executor._RESOURCE_LEASES, identity, expected,
        ) as commit_checked:
            output = worker_result_hook.execute(
                runtime, step['tool'], step['input'], deps, identity,
                approval=worker_approval,
            )
            return commit_checked(output)

    if expected is not None:
        from modules import runtime_worker_result,worker_result_hook
        if (step['tool']=='publish' and 'plan_version' in expected
                and step.get('runtime_approved') is True):
            # The Core approval is for the exact node/input. The Outbox
            # separately owns the immutable resolved payload and its
            # cross-process atomic send-once state. Do not skip either gate.
            from modules import outbox, publish_services, task_workers
            payload=task_workers.resolve_publish_payload(job['owner'],step['input'],deps)
            payload=publish_services.validate(payload)
            if (not isinstance(step.get('_canonical_payload_digest'),str)
                    or outbox._digest(payload)!=step['_canonical_payload_digest']):
                raise PermissionError('Approved publish payload changed; nothing sent.')
            if (not isinstance(step.get('_canonical_connection_digest'),str)
                    or publish_services.connection_digest(job['owner'],payload)
                       != step['_canonical_connection_digest']):
                raise PermissionError('Approved publish account connection changed; nothing sent.')
            outbox_id=outbox.prepare(
                job['owner'],payload,job['id']+':'+step['id'],
            )
            worker_approval={'id':outbox_id}
        output=worker_result_hook.execute(runtime,step['tool'],step['input'],deps,identity,approval=worker_approval)
    else:
        output=goal_tools.execute(runtime,step['tool'],step['input'],deps,identity,approval=approval)
    if (expected is not None and 'plan_version' in expected
            and step['tool'] == 'browser' and isinstance(output, dict)
            and output.get('state') == 'done' and output.get('readonly') is not True):
        raise PermissionError('Canonical browser readonly result required; effect-capable output rejected.')
    if plan and plan['phase']=='prepare':
        from modules import runtime_execution_gate
        if step['tool']=='browser' and isinstance(output,dict) and output.get('state')=='done':
            from modules import runtime_worker_result,worker_result_hook
            if runtime_worker_result.durable_identity(identity):
                # Browser's prepare path bypasses worker_result_hook.execute.
                # It must meet the same domain verification before Core CAS.
                goal_tools.verify(output,job['owner'])
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
        if isinstance(output,dict) and output.get('state')=='done':
            from modules import effect_journal,effect_recovery_runtime
            if step['tool']=='media' and 'plan_version' in expected:
                # Local readback is real: source/video digest and ffprobe have
                # already passed task_results.verify in worker_result_hook.
                # Persist the exact artifact digest as the once-only receipt.
                from modules import task_results
                task_results.verify(output, job['owner'], expected_kind='media')
                effect_recovery_runtime.record_receipt(expected, {
                    'receipt': {'service':'local_media', 'remote_id':output['sha256']},
                })
            if effect_recovery_runtime.required(step['tool']):
                if output.get('receipt') is None:
                    raise effect_journal.ContractViolation(
                        'Receipt-required effect doğrulanmış receipt taşımıyor.')
                effect_recovery_runtime.record_receipt(expected,output)
        from modules import runtime_worker_result
        output=runtime_worker_result.accept_and_commit(output,expected)
    return output
