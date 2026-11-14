"""Core-owned steering of the existing canonical goal and Scheduler journals.

Pause is a checkpoint request: no new node is admitted, while the already
admitted read completes with its resource claims intact. A proposed edit waits
for that checkpoint. No model call runs while holding a Core control lock.
"""
from __future__ import annotations

import copy
import time

import release_guard
from modules import execution_record, goal_job_control, goal_state, goal_state_compat, goal_state_store


def owned(state, record):
    return (goal_state.authority(state) == 'canonical'
            and ('goal_plan' in state or '_planner_rid' in record))


def _pair(owner, job_id):
    from modules import goal_executor
    root = goal_executor._owner_root(owner)
    state = goal_state_store.load(root / (job_id + '.goalstate.json'))
    record = execution_record.load(root, owner, job_id)
    if (state['owner'], state['job_id']) != (owner, job_id):
        raise PermissionError('Hedef kontrol sahibi eşleşmiyor.')
    if record.get('request', '').strip() != state['goal']:
        raise ValueError('Hedef yürütme isteği Core kaydıyla eşleşmiyor.')
    return root, state, record


def _write(root, record):
    record['updated'] = time.time()
    release_guard.atomic(execution_record.path_for(root, record['id']), execution_record.encode(record))


def _busy(record):
    return record.get('state') in ('planning_running', 'revision_running') or any(
        step.get('state') == 'running' for step in record.get('steps', []))


def _apply(root, state, operation, **values):
    return goal_state_compat.apply_canonical_control(
        root / (state['job_id'] + '.goalstate.json'), owner=state['owner'], job_id=state['job_id'],
        expected_version=state['version'], operation=operation, **values)


def reconcile_control_projection(root, state, record):
    """Project an already committed Core control after a journal-write failure.

    No lifecycle mutation, model call, external attempt or uncertain retry is
    authorized here. Claimed/review planner states are deliberately excluded.
    """
    if not owned(state, record) or state['state'] in ('done', 'cancelled', 'failed'):
        return record
    record = copy.deepcopy(record)
    last = state['audit'][-1]
    plan_index = max((i for i, row in enumerate(state['audit']) if row['op'] == 'set_goal_plan'), default=-1)
    edited = any(row['op'] == 'mutate_goal_intent' and row['reason_code'] != 'USER_GOAL_PRIORITY'
                 for row in state['audit'][plan_index + 1:])
    if (state['state'] == 'paused' and (state.get('blocker') or {}).get('code') == 'PAUSED_BY_USER'
            and record.get('state') in ('running', 'planning_queued', 'revision_queued')):
        record['_resume_state'] = 'revision_queued' if 'goal_plan' in state and edited else record['state']
        record['state'] = 'paused'
    elif (state['state'] == 'paused' and 'goal_plan' in state and edited
            and (state.get('blocker') or {}).get('code') != 'PAUSED_BY_USER'
            and record.get('state') in ('running', 'paused')):
        record['state'] = 'revision_queued'
        record['goal_intent'] = copy.deepcopy(state['goal_intent'])
        record['goal_intent_history'] = goal_state.intent_history(state)
        record['_plan_requested_version'] = state['version']
        record.pop('_pending_goal_edit', None)
        record.pop('_pause_requested', None)
    elif (state['state'] == 'paused' and last['reason_code'] == 'USER_GOAL_PAUSED'
          and record.get('state') in ('running', 'planning_queued')):
        record['_resume_state'] = record['state']
        record['state'] = 'paused'
    elif (state['state'] in ('pending', 'running') and last['reason_code'] == 'USER_GOAL_RESUMED'
          and record.get('state') == 'paused'):
        record['state'] = record.pop('_resume_state', 'running' if 'goal_plan' in state else 'planning_queued')
    else:
        return record
    _write(root, record)
    return record


def _queue_edit(root, state, record, operation, text):
    state = _apply(root, state, operation, text=text)
    if 'goal_plan' not in state:
        state = _apply(root, state, 'resume')
        from modules import canonical_planning_queue, requests_state
        generation = state['version']
        _ident, rid = canonical_planning_queue._identity(state['owner'], record['request_id'], generation)
        if not requests_state.register_background(state['owner'], rid, seconds=1800):
            raise ValueError('Bu açık planlama düzeltmesi zaten kaydedildi.')
        record['_planner_generation'] = generation
        record['_planner_rid'] = rid
    # One canonical goal remains one semantic outcome, including additions.
    record['goal_intent'] = copy.deepcopy(state['goal_intent'])
    record['goal_intent_history'] = goal_state.intent_history(state)
    record['state'] = 'revision_queued' if 'goal_plan' in state else 'planning_queued'
    record['_plan_requested_version'] = state['version']
    record.pop('_pending_goal_edit', None)
    record.pop('_pause_requested', None)
    _write(root, record)
    return state


def settle_pause(owner, job_id):
    """Called by the SAME Scheduler at discovery and after a worker checkpoint."""
    from modules import goal_executor
    root = goal_executor._owner_root(owner)
    with goal_job_control.locked(root, job_id):
        root, state, record = _pair(owner, job_id)
        if (not owned(state, record) or state['state'] in ('done', 'cancelled', 'failed')
                or (state.get('blocker') or {}).get('code') != 'PAUSE_REQUESTED'):
            return False
        if _busy(record):
            return True
        edit = record.get('_pending_goal_edit')
        if edit is not None:
            if (not isinstance(edit, dict) or set(edit) != {'operation', 'text'}
                    or edit['operation'] not in ('revise', 'add_task')):
                raise ValueError('Bekleyen hedef düzenleme önerisi geçersiz.')
            _queue_edit(root, state, record, edit['operation'], edit['text'])
        else:
            state = _apply(root, state, 'pause')
            record['_resume_state'] = record.get('state', 'running')
            record['state'] = 'paused'
            record.pop('_pause_requested', None)
            _write(root, record)
        return True


def control(owner, job_id, operation, *, text='', expected_snapshot=None, answer=False):
    """Apply one already model-selected goal operation; None means legacy owner."""
    from modules import goal_executor
    root = goal_executor._owner_root(owner)
    # Do not acquire other job locks while holding this job's lock. Two
    # concurrent priority requests must never lock A->B and B->A.
    priority = (max([job.get('priority', 0) for job in goal_executor.open_jobs(owner)] + [0]) + 1
                if operation == 'prioritize' else None)
    with goal_job_control.locked(root, job_id):
        try:
            root, state, record = _pair(owner, job_id)
        except FileNotFoundError:
            return None
        if not owned(state, record):
            return None
        observed = goal_executor.read_job(owner, job_id)
        goal_executor._check_offered(observed, expected_snapshot)
        record = reconcile_control_projection(root, state, record)
        if state['state'] in ('done', 'cancelled', 'failed'):
            raise ValueError('Hedef artık bu işlem için açık değil.')
        if operation == 'prioritize':
            priority = max(priority, state.get('goal_intent', {}).get('priority', 0) + 1)
            state = _apply(root, state, operation, priority=priority)
            record['priority'] = priority
            _write(root, record)
            from modules import canonical_scheduler_dispatch
            canonical_scheduler_dispatch.prefer(owner, job_id)
            return 'Bu hedef Scheduler seçiminde öncelikli olarak kaydedildi.'
        if operation in ('pause', 'revise', 'add_task'):
            if operation == 'pause' and record.get('state') == 'review':
                return 'Hedef zaten inceleme bekliyor; yeni işlem başlatılmayacak.'
            if operation != 'pause' and record.get('state') == 'revision_running':
                raise ValueError('Plan revizyonu sürüyor; ikinci bir planlama başlatılmadı.')
            if operation != 'pause' and (not isinstance(text, str) or not text.strip() or len(text.strip()) > 2000):
                raise ValueError('Somut hedef düzeltmesi gerekli.')
            if record.get('_pending_goal_edit'):
                raise ValueError('Bu hedefin önceki düzenlemesi güvenli adım sonunu bekliyor.')
            if _busy(record):
                if operation != 'pause':
                    record['_pending_goal_edit'] = {'operation': operation, 'text': text.strip()}
                _apply(root, state, 'pause_requested')
                record['_pause_requested'] = True
                _write(root, record)
                return ('Yeni adımlar durduruldu. Çalışan adım bitince hedef '
                        + ('duraklatılacak.' if operation == 'pause' else 'yeni talimatına göre yeniden planlanacak.'))
            if operation != 'pause':
                _queue_edit(root, state, record, operation, text.strip())
                return 'Hedef düzeltmesi kaydedildi; yeni plan aynı Scheduler kuyruğuna alındı.'
            if state['state'] != 'paused' or record.get('state') != 'paused':
                _apply(root, state, 'pause')
                record['_resume_state'] = record.get('state', 'running')
                record['state'] = 'paused'
                _write(root, record)
            return 'Hedef duraklatıldı; plan ve doğrulanmış sonuçlar korundu.'
        if operation in ('continue', 'resume'):
            if answer and isinstance(record.get('_canonical_dialog'), dict):
                from modules import canonical_goal_flow
                return canonical_goal_flow.submit_clarification(owner, job_id, text)
            if record.get('_pending_goal_edit'):
                return 'Hedef, çalışan adımın güvenli sonunu ve istenen yeni planı bekliyor.'
            if record.get('state') == 'review':
                raise ValueError('Belirsiz planlama sonucu yeniden çalıştırılmadı; hedef inceleme bekliyor.')
            if record.get('state') in ('revision_queued', 'revision_running'):
                if (state.get('blocker') or {}).get('code') == 'PAUSE_REQUESTED':
                    _apply(root, state, 'resume_revision')
                    record.pop('_pause_requested', None)
                    _write(root, record)
                return 'Yeni plan aynı Scheduler üzerinde hazırlanıyor; ikinci planlama başlatılmadı.'
            if state['state'] == 'paused':
                revision = record.get('_resume_state') == 'revision_queued'
                if not revision and any(step.get('state') in ('failed', 'running') for step in record.get('steps', [])):
                    raise ValueError('Başlamış veya başarısız adımın sonucu uzlaştırılmadan tekrar çalıştırılmadı.')
                state = _apply(root, state, 'resume_revision' if revision else 'resume')
                record['state'] = record.pop('_resume_state', 'running' if 'goal_plan' in state else 'planning_queued')
                _write(root, record)
                return 'Hedef aynı Scheduler üzerinde sürdürülüyor; tamamlanan adımlar tekrarlanmadı.'
            if (state.get('blocker') or {}).get('code') == 'PAUSE_REQUESTED':
                _apply(root, state, 'resume')
                record.pop('_pause_requested', None)
                _write(root, record)
            return 'Hedef aynı Scheduler üzerinde çalışıyor; ikinci yürütme başlatılmadı.'
        raise ValueError('Desteklenmeyen canonical hedef kontrolü.')
