"""Compatibility projection from legacy goal_executor jobs to canonical GoalState."""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

from modules import core_state_reducer, execution_record, goal_job_control, goal_state, goal_state_store

# RFC Karar 1 (kabul edildi): legacy goal_executor şemasında fast/durable ayrımı
# hiç yok; canonical projection bu yüzden kalıcı olarak 'agent' üretir ve
# job['execution_mode'] alanını okumaz.
PROJECTION_EXECUTION_MODE = 'agent'


def _execution_journal_lock(path, job_id):
    """Share the control lock only when this ID can own an ExecutionRecord.

    GoalState also permits older short IDs (e.g. 'abc') that can never be
    persisted as execution_record.v1. Those canonical-only records have no
    executor journal to coordinate and retain their original CAS contract.
    """
    parent = Path(path).parent
    try:
        execution_record.path_for(parent, job_id)
    except ValueError:
        return nullcontext()
    return goal_job_control.locked(parent, job_id)


def create_canonical_queued_goal(path, *, owner, job_id, goal):
    """Create one born-canonical, as-yet-unplanned goal for the ONE Scheduler.

    This compat adapter stays the exclusive initial GoalState writer. The
    caller publishes its matching planning_queued ExecutionRecord under the
    same per-job control lock; half-publications fail closed on discovery.
    """
    with _execution_journal_lock(path, job_id):
        initial = goal_state.new(
            owner=owner, job_id=job_id, goal=goal,
            execution_mode=PROJECTION_EXECUTION_MODE, authority='canonical',
        )
        return goal_state_store.create(path, initial)


def park_unplanned_canonical_goal(path, *, owner, job_id, reason):
    """Use the existing reducer/CAS rather than inventing a new goal writer."""
    with _execution_journal_lock(path, job_id):
        current = goal_state_store.load(path)
        if ((current['owner'], current['job_id']) != (owner, job_id)
                or goal_state.authority(current) != 'canonical'
                or current['state'] != 'pending' or 'goal_plan' in current):
            raise ReconcilePolicyError('Only a pending, unplanned canonical goal may be parked.')
        next_state = core_state_reducer.apply(current, {
            'expected_version': current['version'], 'op': 'set_state',
            'state': 'paused', 'reason_code': reason,
        })
        return goal_state_store.compare_and_swap(
            path, expected_version=current['version'], next_state=next_state)


def create_canonical_planned_goal(path, *, owner, job_id, goal, plan):
    """Publish a born-canonical GoalState with its Core-accepted plan in one file.

    The caller owns the matching queued ExecutionRecord publication under the
    same job control lock; a missing record must never be schedulable.
    """
    with _execution_journal_lock(path, job_id):
        initial = goal_state.new(
            owner=owner, job_id=job_id, goal=goal,
            execution_mode=PROJECTION_EXECUTION_MODE, authority='canonical',
        )
        planned = core_state_reducer.apply(initial, {
            'expected_version': initial['version'], 'op': 'set_goal_plan',
            'plan': plan, 'reason_code': 'CORE_GOAL_PLAN_ACCEPTED',
        })
        return goal_state_store.create(path, planned)


def commit_verified_goal_completion(path, *, owner, job_id, proof):
    """CAS global completion only against one current, fully evidenced plan.

    Semantic acceptance and domain verification happen upstream. This adapter
    checks the immutable evidence certificate against BOTH durable snapshots
    under the same per-job lock and never authorizes a worker or model.
    """
    from modules import canonical_plan_evidence, dependency_evidence, goal_plan_gate

    if not isinstance(proof, canonical_plan_evidence.ProjectedPlanProof):
        raise ReconcilePolicyError('Verified projected-plan certificate required.')
    if (proof.owner, proof.job_id) != (owner, job_id):
        raise IdentityMismatchError('Completion certificate owner/job mismatch.')
    with _execution_journal_lock(path, job_id):
        current = goal_state_store.load(path)
        if (current['owner'], current['job_id']) != (owner, job_id):
            raise IdentityMismatchError('GoalState completion identity mismatch.')
        if (goal_state.authority(current) != 'canonical'
                or not isinstance(current.get('goal_plan'), dict)
                or current['state'] not in ('pending', 'running')):
            raise ReconcilePolicyError('Only active planned canonical goals may complete.')
        if (current['version'] != proof.goal_version
                or current['goal_plan']['plan_version'] != proof.plan_version):
            raise goal_state_store.PersistedStateConflict(
                'Canonical completion certificate is stale.',
            )
        node_ids = tuple(node['id'] for node in current['goal_plan']['nodes'])
        if tuple(node_id for node_id, _ in proof.output_digests) != node_ids:
            raise ReconcilePolicyError('Completion certificate does not cover the exact plan.')
        record = execution_record.load(Path(path).parent, owner, job_id)
        outputs = record.get('outputs')
        if (record.get('state') != 'running'
                or goal_job_control.fingerprint(record) != proof.record_digest
                or not isinstance(outputs, dict)
                or set(outputs) != set(node_ids)):
            raise ReconcilePolicyError('Completion journal/evidence is missing or stale.')
        for node_id, digest in proof.output_digests:
            if dependency_evidence.output_sha256(outputs[node_id]) != digest:
                raise ReconcilePolicyError('Projected output changed since certification.')
        try:
            ready = goal_plan_gate.ready_read_only_candidates(
                current, owner=owner, job_id=job_id,
            )
        except goal_plan_gate.PlanFenceError as exc:
            raise ReconcilePolicyError('Canonical plan evidence fence failed.') from exc
        if ready:
            raise ReconcilePolicyError('Some planned workers still lack Core evidence.')
        updated = core_state_reducer.apply(current, {
            'op': 'set_state', 'state': 'done',
            'expected_version': current['version'],
            'reason_code': 'CANONICAL_SEMANTIC_COMPLETION_VERIFIED',
        })
        return goal_state_store.compare_and_swap(
            path, expected_version=current['version'], next_state=updated,
        )


def commit_plan_revision(path, *, owner, job_id, plan, proof):
    """Accept a certified read-only revision/reuse, then project the SAME journal.

    Reuse is a new Core acceptance of an old verified result, never another
    external attempt. The old receipt identity is retained explicitly.
    """
    import copy
    from modules import canonical_output_projection, canonical_plan_revision, dependency_evidence, goal_plan_gate
    import release_guard
    if not isinstance(proof, canonical_plan_revision.RevisionProof) or (proof.owner, proof.job_id) != (owner, job_id):
        raise ReconcilePolicyError('Core revizyon kanıtı gerekli.')
    plan = goal_state.validate_goal_plan(plan)
    with _execution_journal_lock(path, job_id):
        current = goal_state_store.load(path)
        root = Path(path).parent
        record = execution_record.load(root, owner, job_id)
        if ((current['owner'], current['job_id']) != (owner, job_id)
                or goal_state.authority(current) != 'canonical' or current['state'] != 'paused'
                or record.get('state') != 'revision_running'
                or current['version'] != proof.goal_version
                or goal_job_control.fingerprint(record) != proof.record_digest
                or goal_job_control.fingerprint(plan) != proof.plan_digest):
            raise ReconcilePolicyError('Plan revizyonu veya doğrulanan kayıt değişti.')
        if any(node['capability_id'] not in {'task.research', 'task.account', 'task.verify'} for node in plan['nodes']):
            raise ReconcilePolicyError('Revizyon mevcut salt-okunur Scheduler kapsamını aşamaz.')
        canonical_plan_revision._unknown_replay(current, record, plan)
        candidates = set(goal_plan_gate.revision_reuse_candidates(current, plan))
        source = canonical_plan_revision.source_before_edit(current)
        old_nodes = {node['id']: node for node in current['goal_plan']['nodes']}
        reused = dict(proof.reused)
        if len(reused) != len(proof.reused) or not set(reused) <= candidates:
            raise ReconcilePolicyError('Yeniden kullanım adayları geçersiz.')
        accepted = {}
        for node in plan['nodes']:
            ident = node['id']
            if ident not in reused:
                continue
            if any(dep not in accepted for dep in node['depends_on']):
                raise ReconcilePolicyError('Yeniden kullanımın önkoşul kanıtı eksik.')
            output = record['outputs'].get(ident)
            if dependency_evidence.output_sha256(output) != reused[ident]:
                raise ReconcilePolicyError('Doğrulanmış eski çıktı değişti.')
            accepted[ident] = canonical_output_projection._accepted_row(source, owner, job_id, old_nodes[ident], output)
        updated = core_state_reducer.apply(current, dict(
            op='set_goal_plan', expected_version=current['version'], plan=plan, reason_code='CORE_GOAL_PLAN_ACCEPTED'))
        updated = core_state_reducer.apply(updated, dict(
            op='set_state', state='running', expected_version=updated['version'], reason_code='CORE_GOAL_PLAN_REVISED'))
        pause_requested = (current.get('blocker') or {}).get('code') == 'PAUSE_REQUESTED'
        if pause_requested:
            updated = core_state_reducer.apply(updated, dict(
                op='set_blocker', blocker={'code': 'PAUSE_REQUESTED'}, expected_version=updated['version'],
                reason_code='USER_GOAL_PAUSE_REQUESTED'))
        projected = copy.deepcopy(record)
        projected.setdefault('_plan_history', []).append({
            'plan': copy.deepcopy(current['goal_plan']), 'steps': copy.deepcopy(record['steps']),
            'outputs': copy.deepcopy(record['outputs']),
        })
        for key in ('_canonical_dialog', '_pending_goal_edit', '_pause_requested', '_resume_state', '_pending_plan_projection'):
            projected.pop(key, None)
        projected['state'] = 'running'
        if pause_requested:
            projected['_pause_requested'] = True
        projected['goals'] = [{'text': current['goal'], 'state': 'pending', 'evidence': []}]
        projected['goal_intent'] = copy.deepcopy(current.get('goal_intent'))
        projected['steps'] = []
        projected['outputs'] = {}
        for node in plan['nodes']:
            ident = node['id']
            step = dict(id=ident, goal=0, tool=node['capability_id'].removeprefix('task.'),
                        input=copy.deepcopy(node['input']), depends=list(node['depends_on']),
                        state='queued', started=False, attempts=0)
            if ident in accepted:
                old = accepted[ident]
                evidence = copy.deepcopy(old)
                evidence.update(plan_version=plan['plan_version'], node_digest=goal_plan_gate.fingerprints(plan)[ident],
                                command_id=f"{ident}:1:p{plan['plan_version']}", attempt=1,
                                expected_job_version=updated['version'],
                                reused_from={'plan_version': old['plan_version'], 'command_id': old['command_id'],
                                             'output_sha256': reused[ident]})
                updated = core_state_reducer.apply(updated, dict(
                    op='append_evidence', expected_version=updated['version'], evidence=evidence,
                    reason_code='WORKER_RESULT_ACCEPTED'))
                step.update(state='done', started=True, attempts=1, reused_from=evidence['reused_from'])
                projected['outputs'][ident] = copy.deepcopy(record['outputs'][ident])
            projected['steps'].append(step)
        # Prepare recoverable journal bytes BEFORE the new Core CAS. A crash
        # after CAS can only replay projection, never planning/provider work.
        record['_pending_plan_projection'] = {'plan': plan, 'record': projected}
        encoded = execution_record.encode(record)
        if len(encoded) > execution_record.MAX_BYTES:
            raise ReconcilePolicyError('Revizyon günlüğü güvenli kayıt sınırını aşıyor.')
        release_guard.atomic(execution_record.path_for(root, job_id), encoded)
        saved = goal_state_store.compare_and_swap(path, expected_version=current['version'], next_state=updated)
        release_guard.atomic(execution_record.path_for(root, job_id), execution_record.encode(projected))
        return saved


def apply_canonical_control(path, *, owner, job_id, expected_version, operation, text=None, priority=None):
    """Core-only lifecycle/intent transition for one addressed Scheduler goal."""
    with _execution_journal_lock(path, job_id):
        current = goal_state_store.load(path)
        if ((current['owner'], current['job_id']) != (owner, job_id)
                or goal_state.authority(current) != 'canonical'
                or current['state'] in ('done', 'cancelled', 'failed')):
            raise ReconcilePolicyError('Canonical hedef bu kontrol için açık değil.')
        if current['version'] != expected_version:
            raise goal_state_store.PersistedStateConflict('Hedef kontrol sürümü değişti.')
        if operation == 'pause_requested':
            proposal = dict(op='set_blocker', blocker={'code': 'PAUSE_REQUESTED'},
                            reason_code='USER_GOAL_PAUSE_REQUESTED')
        elif operation == 'resume_revision':
            if current['state'] != 'paused' or 'goal_plan' not in current:
                raise ReconcilePolicyError('Revizyon kuyruğu güvenli beklemede değil.')
            proposal = dict(op='clear_blocker', reason_code='USER_GOAL_REPLAN_RELEASED')
        elif operation in ('pause', 'resume'):
            target = 'paused' if operation == 'pause' else ('running' if 'goal_plan' in current else 'pending')
            if (operation == 'resume' and current['state'] in ('pending', 'running')
                    and (current.get('blocker') or {}).get('code') == 'PAUSE_REQUESTED'):
                proposal = dict(op='clear_blocker', reason_code='USER_GOAL_PAUSE_WITHDRAWN')
            elif current['state'] == target:
                if operation == 'pause':
                    proposal = dict(op='set_blocker', blocker={'code': 'PAUSED_BY_USER'}, reason_code='USER_GOAL_PAUSED')
                elif (current.get('blocker') or {}).get('code') != 'PAUSE_REQUESTED':
                    return current
                else:
                    proposal = dict(op='clear_blocker', reason_code='USER_GOAL_PAUSE_WITHDRAWN')
            else:
                proposal = dict(op='set_state', state=target,
                                reason_code='USER_GOAL_PAUSED' if operation == 'pause' else 'USER_GOAL_RESUMED')
        elif operation in ('revise', 'add_task', 'prioritize'):
            proposal = dict(op='mutate_goal_intent', operation=operation, text=text, priority=priority,
                            reason_code='USER_GOAL_PRIORITY' if operation == 'prioritize' else 'USER_GOAL_INTENT')
        else:
            raise ReconcilePolicyError('Bilinmeyen canonical kontrol.')
        updated = core_state_reducer.apply(current, dict(proposal, expected_version=current['version']))
        if operation in ('revise', 'add_task') and updated['state'] != 'paused':
            updated = core_state_reducer.apply(updated, dict(
                op='set_state', state='paused', expected_version=updated['version'],
                reason_code='USER_GOAL_REPLAN_REQUESTED'))
        if operation in ('revise', 'add_task') and updated.get('blocker'):
            updated = core_state_reducer.apply(updated, dict(
                op='clear_blocker', expected_version=updated['version'],
                reason_code='CORE_GOAL_REPLAN_QUEUED'))
        return goal_state_store.compare_and_swap(path, expected_version=expected_version, next_state=updated)


def apply_goal_intent(path, *, owner, job_id, expected_version, operation, text=None, priority=None):
    """Commit an explicitly requested intent mutation to an existing canonical job."""
    # Reuse the executor's existing short per-job, cross-process control lock.
    # Worker/provider execution remains outside this persistence critical section.
    # Nested goal_executor._intent_mutation uses the same reentrant lock.
    with _execution_journal_lock(path, job_id):
        current = goal_state_store.load(path)
        if current['owner'] != owner or current['job_id'] != job_id:
            raise IdentityMismatchError('GoalState kimliği eşleşmiyor.')
        if goal_state.authority(current) != 'canonical':
            raise ReconcilePolicyError('Goal intent için canonical authority gerekli.')
        updated = core_state_reducer.apply(current, {
            'expected_version': expected_version, 'op': 'mutate_goal_intent',
            'operation': operation, 'text': text, 'priority': priority,
            'reason_code': 'USER_GOAL_INTENT',
        })
        return goal_state_store.compare_and_swap(path, expected_version=expected_version, next_state=updated)


def apply_goal_plan(path, *, owner, job_id, expected_version, plan):
    """Commit one Core-validated canonical plan proposal through the existing CAS."""
    # Reuse the executor's existing short per-job, cross-process control lock.
    # Worker/provider execution remains outside this persistence critical section.
    # Nested goal_executor._intent_mutation uses the same reentrant lock.
    with _execution_journal_lock(path, job_id):
        current = goal_state_store.load(path)
        if current['owner'] != owner or current['job_id'] != job_id:
            raise IdentityMismatchError('GoalState plan kimliği eşleşmiyor.')
        if goal_state.authority(current) != 'canonical':
            raise ReconcilePolicyError('Goal plan için canonical authority gerekli.')
        updated = core_state_reducer.apply(current, {
            'expected_version': expected_version, 'op': 'set_goal_plan',
            'plan': plan, 'reason_code': 'CORE_GOAL_PLAN_ACCEPTED',
        })
        return goal_state_store.compare_and_swap(
            path, expected_version=expected_version, next_state=updated,
        )


_STATE_MAP = {
    'running': 'running',
    'approval': 'waiting',
    'question': 'waiting',
    'review': 'paused',
    'paused': 'paused',
    'interrupted': 'paused',
    'blocked': 'paused',
    'failed': 'failed',
    'done': 'done',
    'cancelled': 'cancelled',
}


class ReconcilePolicyError(ValueError):
    reason_code = 'RECONCILE_POLICY_ERROR'

    def __init__(self, message: str):
        super().__init__(message)
        self.reason_code = type(self).reason_code


class IdentityMismatchError(ReconcilePolicyError):
    reason_code = 'IDENTITY_MISMATCH'


class OperatorApprovalRequired(ReconcilePolicyError):
    reason_code = 'OPERATOR_APPROVAL_REQUIRED'


class BackfillAlreadyExists(ReconcilePolicyError):
    reason_code = 'CANONICAL_ALREADY_EXISTS'


def _target(job: dict) -> str:
    value = _STATE_MAP.get(job.get('state'))
    if value is None:
        raise ValueError('Legacy job state GoalState ile eşlenemiyor.')
    return value


def _blocker(job: dict):
    state = job.get('state')
    text = job.get('blocker') or job.get('question')
    if not text:
        return None
    code = 'LEGACY_APPROVAL' if state == 'approval' else 'LEGACY_QUESTION' if state == 'question' else 'LEGACY_BLOCKED'
    return {'code': code, 'text': str(text)[:1200]}


def _assert_identity(current: dict, job: dict) -> None:
    expected = (
        current['owner'],
        current['job_id'],
        current['goal'],
    )
    actual = (
        job.get('owner'),
        job.get('id'),
        str(job.get('request', '')).strip(),
    )
    if actual != expected:
        raise IdentityMismatchError('Legacy/canonical GoalState identity mismatch.')


def project(job: dict) -> dict:
    # RFC Karar 2 flip point: a canonical record created now (no prior canonical
    # file for this job) is a newly-created job and is canonical-authority from
    # birth. A job that already had a canonical record before this field
    # existed keeps no 'authority' key and stays legacy-authority via
    # goal_state.authority()'s default; this function never touches it.
    return _project(job, authority='canonical')


def _project(job: dict, *, authority: str) -> dict:
    state = goal_state.new(
        owner=job['owner'], job_id=job['id'], goal=job['request'],
        execution_mode=PROJECTION_EXECUTION_MODE,
        authority=authority,
    )
    target = _target(job)
    if target != 'pending':
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'set_state',
            'state': target, 'reason_code': 'LEGACY_PROJECTED',
        })
    blocker = _blocker(job)
    if blocker and state['state'] not in {'done', 'cancelled'}:
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'set_blocker',
            'blocker': blocker, 'reason_code': 'LEGACY_BLOCKER_SYNCED',
        })
    return state


def reconcile(current: dict, job: dict) -> dict:
    """Compare one canonical snapshot with one legacy snapshot without choosing cutover timing.

    This function codifies RFC decisions 3 and 4 only.  It does not decide which
    side is write authority or when authority changes.
    """
    current = goal_state.validate(current)
    _assert_identity(current, job)
    target = _target(job)

    if goal_state.terminal(current):
        if current['state'] != target:
            return {
                'state': current,
                'changed': False,
                'decision': 'CANONICAL_TERMINAL_WINS',
                'reason_code': 'TERMINAL_DIVERGENCE',
            }
        return {
            'state': current,
            'changed': False,
            'decision': 'ALIGNED',
            'reason_code': 'ALIGNED',
        }

    state = current
    if state['state'] != target:
        proposal = {
            'expected_version': state['version'], 'op': 'set_state',
            'state': target, 'reason_code': 'LEGACY_STATE_SYNCED',
        }
        try:
            state = core_state_reducer.apply(state, proposal)
        except core_state_reducer.InvalidTransitionError:
            if state['state'] == 'running' or target == 'running':
                raise
            state = core_state_reducer.apply(state, {
                'expected_version': state['version'], 'op': 'set_state',
                'state': 'running', 'reason_code': 'LEGACY_RESUMED',
            })
            state = core_state_reducer.apply(state, {
                'expected_version': state['version'], 'op': 'set_state',
                'state': target, 'reason_code': 'LEGACY_STATE_SYNCED',
            })
    blocker = _blocker(job)
    if blocker is not None and state['blocker'] != blocker and not goal_state.terminal(state):
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'set_blocker',
            'blocker': blocker, 'reason_code': 'LEGACY_BLOCKER_SYNCED',
        })
    elif blocker is None and state['blocker'] is not None and not goal_state.terminal(state):
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'clear_blocker',
            'reason_code': 'LEGACY_BLOCKER_CLEARED',
        })

    changed = state['version'] != current['version']
    return {
        'state': state,
        'changed': changed,
        'decision': 'LEGACY_COMPAT_APPLIED' if changed else 'ALIGNED',
        'reason_code': state['audit'][-1]['reason_code'] if changed else 'ALIGNED',
    }


def advance(current: dict, job: dict) -> dict:
    current = goal_state.validate(current)
    target = _target(job)

    if goal_state.terminal(current):
        return current

    state = current
    if state['state'] != target:
        proposal = {
            'expected_version': state['version'], 'op': 'set_state',
            'state': target, 'reason_code': 'LEGACY_STATE_SYNCED',
        }
        try:
            state = core_state_reducer.apply(state, proposal)
        except core_state_reducer.InvalidTransitionError:
            if state['state'] == 'running' or target == 'running':
                raise
            state = core_state_reducer.apply(state, {
                'expected_version': state['version'], 'op': 'set_state',
                'state': 'running', 'reason_code': 'LEGACY_RESUMED',
            })
            state = core_state_reducer.apply(state, {
                'expected_version': state['version'], 'op': 'set_state',
                'state': target, 'reason_code': 'LEGACY_STATE_SYNCED',
            })
    blocker = _blocker(job)
    if blocker is not None and state['blocker'] != blocker and not goal_state.terminal(state):
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'set_blocker',
            'blocker': blocker, 'reason_code': 'LEGACY_BLOCKER_SYNCED',
        })
    elif blocker is None and state['blocker'] is not None and not goal_state.terminal(state):
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'clear_blocker',
            'reason_code': 'LEGACY_BLOCKER_CLEARED',
        })
    return state


def legacy_terminal_signal(job: dict, state: dict) -> dict | None:
    """Return the legacy job rewritten to canonical's terminal state, or None.

    RFC Karar 4a: canonical terminal always wins, and the legacy side must
    learn it.  When canonical is already done/cancelled but the legacy journal
    still shows another state, the legacy record is written with the canonical
    terminal state so goal_executor.latest()/is_open() treat the job as closed.

    A terminal state that canonical only copied from legacy (LEGACY_* reason)
    is not a canonical decision; legacy keeps owning that record, including
    its own "hedef devam" reopen path.
    """
    state = goal_state.validate(state)
    if not goal_state.terminal(state) or job.get('state') == state['state']:
        return None
    if state['audit'][-1]['reason_code'].startswith('LEGACY_'):
        return None
    signalled = dict(job)
    signalled['state'] = state['state']
    signalled.pop('blocker', None)
    signalled.pop('question', None)
    return signalled


def operator_backfill_missing_canonical_once(
    job: dict,
    path,
    *,
    operator_approved: bool = False,
) -> dict:
    """Explicit, one-shot operator API for RFC decision 3a.

    Compatibility sync never calls this function automatically.  The caller must
    explicitly approve the action and the canonical path must still be absent.

    A legacy job without a canonical record predates canonical sync, so it is an
    in-flight job from before the RFC Karar 2 flip point (job creation).  The
    backfilled record is therefore marked legacy-authority; backfill never flips
    authority at runtime.
    """
    if not operator_approved:
        raise OperatorApprovalRequired('Canonical GoalState backfill requires operator approval.')
    path = Path(path)
    if path.exists():
        raise BackfillAlreadyExists('Canonical GoalState already exists; backfill refused.')
    return goal_state_store.create(path, _project(job, authority='legacy'))


def operator_promote_legacy_authority_once(path) -> dict:
    """Promote one aligned legacy-authority GoalState after explicit operator approval."""
    path = Path(path)
    current = goal_state_store.load(path)
    if goal_state.authority(current) != 'legacy':
        raise BackfillAlreadyExists('GoalState zaten canonical authority ile kayıtlı.')
    next_state = core_state_reducer.apply(current, {
        'expected_version': current['version'], 'op': 'set_authority',
        'authority': 'canonical', 'reason_code': 'OPERATOR_CUTOVER_PROMOTED',
    })
    return goal_state_store.compare_and_swap(
        path, expected_version=current['version'], next_state=next_state,
    )


def rollback_operator_promotion(path, *, expected_state: dict, previous_bytes: bytes) -> None:
    """Undo a just-promoted authority transition only while its CAS state is current."""
    expected_state = goal_state.validate(expected_state)
    if goal_state.authority(expected_state) != 'canonical':
        raise ReconcilePolicyError('Promotion rollback yalnız canonical authority kaydını geri alabilir.')
    goal_state_store.compensate(
        Path(path), expected_state=expected_state, previous_bytes=previous_bytes,
    )


def sync(job: dict, path, *, expected_version=None) -> dict:
    path = Path(path)
    if not path.exists():
        if expected_version is not None:
            raise goal_state_store.PersistedStateConflict('Beklenen canonical hedef kaydı bulunamadı.')
        state = project(job)
        return goal_state_store.create(path, state)
    current = goal_state_store.load(path)
    if expected_version is not None and current['version'] != expected_version:
        raise goal_state_store.PersistedStateConflict('Hedef sürümü değişti; eski kayıt yazılmadı.')
    # After operator promotion, legacy journal saves may still arrive from an
    # already-running executor. They may refresh the separate ExecutionRecord,
    # but must never drive canonical lifecycle state back through compat sync.
    # Canonical-at-birth jobs keep the established sync contract; only the
    # explicit operator promotion audit marks this one-way cutover boundary.
    if (
        goal_state.authority(current) == 'canonical'
        and any(row['reason_code'] == 'OPERATOR_CUTOVER_PROMOTED' for row in current['audit'])
    ):
        return current
    # A born-canonical GoalPlan belongs to Core and its verified semantic
    # completion adapter, not to a legacy execution-journal state string.
    # The ordinary legacy save hook may still propagate an explicit user
    # cancellation and maintain compatible nonterminal projections, but it
    # cannot synthesize global done without projected, accepted WorkerResults.
    if (goal_state.authority(current) == 'canonical'
            and current.get('goal_plan') is not None
            and current['state'] not in {'done', 'cancelled'}
            and job.get('state') == 'done'):
        raise ReconcilePolicyError(
            'Planned canonical goal completion requires verified Core evidence.'
        )
    next_state = advance(current, job)
    if next_state['version'] == current['version']:
        return current
    return goal_state_store.compare_and_swap(
        path, expected_version=current['version'], next_state=next_state
    )


def open_subscription_state(path, *, owner: str, job_id: str, goal: str) -> dict:
    """Canonical GoalState for a long-lived event subscription (e.g. a source watch).

    Born canonical and parked in ``waiting`` so RuntimeEvent evidence can keep
    arriving. An existing record is reused only when its identity matches.
    """
    path = Path(path)
    if path.exists():
        current = goal_state_store.load(path)
        if current['owner'] != owner or current['job_id'] != job_id:
            raise IdentityMismatchError('Abonelik GoalState kimliği eşleşmiyor.')
        return current
    state = goal_state.new(owner=owner, job_id=job_id, goal=goal,
                           execution_mode=PROJECTION_EXECUTION_MODE, authority='canonical')
    state = core_state_reducer.apply(state, {
        'expected_version': state['version'], 'op': 'set_state',
        'state': 'waiting', 'reason_code': 'SUBSCRIPTION_OPENED',
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    return goal_state_store.create(path, state)


def close_subscription_state(path) -> dict | None:
    """Cancel a subscription GoalState when its source is removed; idempotent."""
    path = Path(path)
    if not path.exists():
        return None
    current = goal_state_store.load(path)
    if current['state'] in {'done', 'cancelled'}:
        return current
    next_state = core_state_reducer.apply(current, {
        'expected_version': current['version'], 'op': 'set_state',
        'state': 'cancelled', 'reason_code': 'SUBSCRIPTION_CLOSED',
    })
    return goal_state_store.compare_and_swap(
        path, expected_version=current['version'], next_state=next_state
    )
