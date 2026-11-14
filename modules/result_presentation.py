"""Read-only view of results checked by existing domain/Core owners.

Never writes lifecycle, runs effects, retries a worker, or asks a model.
"""
from copy import deepcopy
from types import SimpleNamespace

VERSION='jarvis-response.v1'
UNVERIFIED='Sonuç kanıtı doğrulanamadı; bu adımı tamamlanmış olarak sunamıyorum.'


def style_snapshot(owner,*,background=False):
    from modules import persona,personalization
    profile=personalization.Profile(owner)
    rows=persona.effective(profile,session=SimpleNamespace() if background else None)
    return {'version':VERSION,'verbosity':rows['verbosity']['value']}


def validate_style(style):
    if (not isinstance(style,dict) or set(style)!={'version','verbosity'}
            or style['version']!=VERSION or style['verbosity'] not in ('kısa','orta','uzun')):
        raise ValueError('Yanıt sunum kaydı geçersiz.')
    return dict(style)


def preview(text,style,*,normal=1200):
    style=validate_style(style)
    limit={'kısa':400,'orta':normal,'uzun':max(6000,normal)}[style['verbosity']]
    if len(text)<=limit:return text
    cut=text[:limit];space=cut.rfind(' ')
    return (cut[:space] if space>limit//2 else cut)+'\nMetnin devamı görev ayrıntılarında.'


def _canonical_state(job):
    from modules import goal_executor,goal_job_control
    root=goal_executor._owner_root(job['owner'])
    ident=job.get('id')
    if not isinstance(ident,str) or not ident or '/' in ident or '\\' in ident:raise ValueError('Hedef kimliği geçersiz.')
    path=root/(ident+'.goalstate.json')
    if not path.exists() and not path.is_symlink():return None
    return goal_job_control.canonical(root,job['owner'],ident)


def _check_canonical(state,job,step,output):
    if state is None or not isinstance(state.get('goal_plan'),dict):return
    from modules import canonical_output_projection
    if (state['owner']!=job['owner'] or state['job_id']!=job['id']
            or state['goal']!=job.get('request')):
        raise ValueError('Core sonuç sahibi/hedefi uyuşmuyor.')
    nodes=[node for node in state['goal_plan']['nodes'] if node['id']==step['id']]
    if (len(nodes)!=1 or step.get('tool')!=nodes[0]['capability_id'].removeprefix('task.')
            or step.get('input')!=nodes[0]['input'] or step.get('depends')!=nodes[0]['depends_on']):
        raise ValueError('Core sonuç planı uyuşmuyor.')
    canonical_output_projection._accepted_row(state,job['owner'],job['id'],nodes[0],output,
                                              allow_completed_read=state['state']=='done')


def inspect_job(job,family):
    """Return a copy suitable for display; the original state is never repaired."""
    from modules import goal_tools,task_results
    view=deepcopy(job);owner=job.get('owner')
    key='steps' if family=='goal' else 'tasks'
    steps=view.get(key,[]);outputs=view.get('outputs',{})
    if not isinstance(steps,list) or not isinstance(outputs,dict):raise ValueError('Sonuç kaydı geçersiz.')
    valid=set();invalid=set();state=None;core_error=False
    if family=='goal' and isinstance(owner,str) and owner:
        try:state=_canonical_state(job)
        except (ValueError,OSError,KeyError):core_error=True
    counts={}
    for step in steps:
        if isinstance(step,dict):counts[step.get('id')]=counts.get(step.get('id'),0)+1
    for step in steps:
        if not isinstance(step,dict):continue
        ident=step.get('id');output=outputs.get(ident)
        if step.get('state')!='done':
            if isinstance(output,dict) and output.get('state')=='done':
                outputs[ident]={'state':'unavailable','text':UNVERIFIED};invalid.add(ident)
            continue
        try:
            if (not isinstance(owner,str) or not owner or counts.get(ident)!=1
                    or not isinstance(output,dict) or output.get('state')!='done' or core_error):
                raise ValueError('Sonuç sahibi veya adım kaydı eksik.')
            kind=step.get('tool') if family=='goal' else step.get('agent')
            if family=='goal':
                metadata=output.get('verification')
                actual=metadata.get('agent') if isinstance(metadata,dict) else output.get('local_evidence')
                if actual!=kind:raise ValueError('Sonuç türü farklı.')
                if goal_tools.verify(output,owner,kind=kind,data=step.get('input',{})) is not True:raise ValueError('Sonuç doğrulanmadı.')
                _check_canonical(state,job,step,output)
            elif task_results.verify(output,owner=owner,expected_kind=kind) is not True:
                raise ValueError('Sonuç doğrulanmadı.')
            valid.add(ident)
        except (ValueError,PermissionError,OSError,KeyError,TypeError):
            invalid.add(ident);step['state']='unavailable'
            outputs[ident]={'state':'unavailable','text':UNVERIFIED}
    # A historical boolean verifier receipt cannot conceal a changed dependency.
    for step in steps:
        kind=step.get('tool') if family=='goal' else step.get('agent')
        if kind=='verify' and step.get('id') in valid and any(dep not in valid for dep in step.get('depends',[])):
            ident=step['id'];valid.remove(ident);invalid.add(ident);step['state']='unavailable'
            outputs[ident]={'state':'unavailable','text':UNVERIFIED}
    if family=='goal':
        for index,goal in enumerate(view.get('goals',[])):
            evidence=goal.get('evidence',[])
            if goal.get('state')=='done' and (not evidence or any(ident not in valid for ident in evidence)):
                invalid.add('goal:'+str(index))
                goal['state']='pending'
                goal['chat_evidence']=[step['id'] for step in steps if step.get('id') in valid and step.get('goal')==index]
            elif goal.get('chat_evidence'):
                goal['chat_evidence']=[ident for ident in goal['chat_evidence'] if ident in valid]
    if view.get('state')=='done' and (not steps or invalid or any(step.get('state')!='done' for step in steps)
            or (family=='goal' and any(goal.get('state')!='done' for goal in view.get('goals',[])))):
        view['state']='incomplete'
    return {'job':view,'verified':frozenset(valid),'unverified':frozenset(invalid),
            'core_completed':bool(state is not None and state.get('state')=='done'
                                  and isinstance(state.get('goal_plan'),dict) and not invalid)}
