"""Runtime bridge from durable execution identity to WorkerResult v1 fencing."""
from __future__ import annotations

import copy
import hashlib
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar

from modules import capability_manifest, goal_state_store, worker_result


class CanonicalWorkerDeadlineExceeded(RuntimeError):
    """A canonical read-only worker outlived its cooperative time budget."""


class CanonicalWorkerRevoked(RuntimeError):
    """A canonical goal was cancelled or revised while its worker was running."""


class CanonicalSchedulerStopped(RuntimeError):
    """The owner Scheduler stopped while a read-only attempt was in flight."""


class CanonicalWorkerDeadline:
    """One bounded worker attempt, not a provider kill or retry authority.

    The same token represents engine stop and elapsed deadline. It is bound
    through the existing Scheduler stop ContextVar, so Core rejects results
    that return after either boundary. It does NOT cancel a blocking provider
    or release a resource lock while an external call is still in flight.
    """

    def __init__(self, stop_event, seconds: float, *, clock=time.monotonic):
        if not callable(getattr(stop_event, 'is_set', None)):
            raise ValueError('Canonical Scheduler stop event invalid.')
        if (type(seconds) not in (int, float) or not 1 <= seconds <= 3600
                or not callable(clock)):
            raise ValueError('Canonical worker deadline must be 1–3600 seconds.')
        self._stop_event = stop_event
        self._clock = clock
        self._deadline = clock() + seconds

    def stop_reason(self):
        if self._stop_event.is_set():
            return 'scheduler_stopped'
        if self._clock() >= self._deadline:
            return 'worker_deadline'
        return None

    def is_set(self):
        return self.stop_reason() is not None


# Only the canonical worker launched by the existing Scheduler binds this
# cooperative stop check. It must never be mistaken for a durable cancellation
# decision or an authority to launch/retry an effectful command.
_SCHEDULER_STOP = ContextVar('jarvis_canonical_scheduler_stop', default=None)
# Immutable NodeCandidate from the real Scheduler, never a model-supplied ID.
_CANONICAL_SELECTION = ContextVar('jarvis_canonical_scheduler_selection', default=None)


@contextmanager
def scheduler_stop_scope(stop_event, *, selection=None):
    """Bind Scheduler stop and its exact canonical goal to one worker thread.

    The Core fence checks terminal cancellation/replan before each next model or
    provider step, not just when the result eventually reaches WorkerResult CAS.
    A blocked remote request cannot be forcibly cancelled or deemed unissued.
    """
    if stop_event is not None and not callable(getattr(stop_event, 'is_set', None)):
        raise ValueError('Canonical Scheduler stop token invalid.')
    if selection is not None:
        from modules import goal_plan_gate
        if not isinstance(selection, goal_plan_gate.NodeCandidate):
            raise ValueError('Canonical worker selection must come from Core.')
    from modules import requests_state
    token = _SCHEDULER_STOP.set(stop_event)
    selected_token = _CANONICAL_SELECTION.set(selection)
    try:
        # The Scheduler's own stop/deadline token remains authoritative.
        # Existing requests_state.check() sites in Gmail, research readers
        # and model waits now stop before their NEXT provider/read step.
        # A currently blocked provider still cannot be forcibly interrupted.
        with requests_state.worker_probe(require_scheduler_active):
            require_scheduler_active()
            yield
    finally:
        _CANONICAL_SELECTION.reset(selected_token)
        _SCHEDULER_STOP.reset(token)


def _require_canonical_goal_active(selection):
    """Read current Core authority; admit only independent accepted worker CAS.

    A user correction, changed plan or terminal cancellation must stop the
    NEXT provider/read operation even if the old worker was already running.
    The per-job lock is short and never held over provider execution.
    """
    from modules import goal_executor, goal_job_control, goal_plan_gate, goal_state
    root = goal_executor._owner_root(selection.owner)
    if not root.is_dir() or root.is_symlink():
        raise CanonicalWorkerRevoked('Canonical owner root unavailable.')
    with goal_job_control.locked(root, selection.job_id):
        current = goal_state_store.load(root / (selection.job_id + '.goalstate.json'))
        plan = current.get('goal_plan')
        if ((current['owner'], current['job_id']) !=
                (selection.owner, selection.job_id)
                or goal_state.authority(current) != 'canonical'
                or current['state'] not in ('pending', 'running')
                or not isinstance(plan, dict)
                or plan.get('plan_version') != selection.plan_version
                or current['version'] < selection.expected_goal_version):
            raise CanonicalWorkerRevoked('Canonical goal cancelled, closed or revised.')
        try:
            digests = goal_plan_gate.fingerprints(plan)
            if digests.get(selection.node_id) != selection.node_digest:
                raise CanonicalWorkerRevoked('Canonical node or prerequisites changed.')
            advances = current['audit'][selection.expected_goal_version + 1:]
            if any(not goal_plan_gate.worker_compatible_audit(row) for row in advances):
                raise CanonicalWorkerRevoked('Non-worker canonical intent mutation.')
            # Verify accepted worker evidence/audit parity, not just a newer version.
            goal_plan_gate.ready_read_only_candidates(
                current, owner=selection.owner, job_id=selection.job_id,
            )
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise CanonicalWorkerRevoked('Canonical plan evidence changed.') from exc


def require_scheduler_active():
    """Cooperative fence directly before Core accepts this worker's result."""
    stop_event = _SCHEDULER_STOP.get()
    if stop_event is not None and stop_event.is_set():
        if (isinstance(stop_event, CanonicalWorkerDeadline)
                and stop_event.stop_reason() == 'worker_deadline'):
            raise CanonicalWorkerDeadlineExceeded(
                'Canonical worker deadline elapsed; stale result not accepted.'
            )
        raise CanonicalSchedulerStopped(
            'Canonical Scheduler stopped; stale worker result not accepted.'
        )
    selection = _CANONICAL_SELECTION.get()
    if selection is not None:
        _require_canonical_goal_active(selection)


def durable_identity(identity: dict) -> bool:
    """True only for the versioned execution identity emitted by goal_executor.

    Older/direct specialist calls do not carry this runtime policy metadata and
    remain outside this migration slice.  A versioned identity is fail-closed:
    prepare() still validates every required field before a worker is called.
    """
    return isinstance(identity, dict) and isinstance(identity.get('version'), int)


def canonical_snapshot(identity: dict) -> dict:
    owner = identity.get('owner') if isinstance(identity, dict) else None
    job_id = identity.get('job_id') if isinstance(identity, dict) else None
    if not isinstance(owner, str) or not owner or not isinstance(job_id, str) or not job_id:
        raise ValueError('Worker execution kimliği eksik.')
    # Use the executor's active STORE/root rather than config.DATA_DIR. Tests and
    # isolated runtimes intentionally relocate STORE; the canonical sidecar is
    # created beside the legacy job by goal_state_save_hook.
    from modules import goal_executor
    path = goal_executor._root(owner) / (job_id + '.goalstate.json')
    state = goal_state_store.load(path)
    if state['owner'] != owner or state['job_id'] != job_id:
        raise ValueError('Canonical GoalState worker kimliğiyle eşleşmiyor.')
    return state


def canonical_version(identity: dict) -> int:
    return canonical_snapshot(identity)['version']


def prepare(identity: dict, kind: str, data: dict, *, expected_job_version: int | None = None,
            reconcile_existing: bool = False):
    if not isinstance(identity, dict):
        raise ValueError('Worker kimliği geçersiz.')
    # Default durable execution reads the single canonical GoalState snapshot.
    # Explicit-version legacy/testing callers remain v1, but commit rejects a
    # v1 result if a canonical goal_plan is present (no version-fence bypass).
    snapshot = canonical_snapshot(identity) if expected_job_version is None else None
    if snapshot is not None:
        expected_job_version = snapshot['version']
    if not isinstance(expected_job_version, int) or isinstance(expected_job_version, bool) or expected_job_version < 0:
        raise ValueError('Beklenen GoalState sürümü geçersiz.')
    row = _capability(kind)
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    attempt = identity.get('attempt', 1)
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 0:
        raise ValueError('Worker attempt geçersiz.')
    owner = identity.get('owner'); job_id = identity.get('job_id'); step_id = identity.get('task_id')
    if not all(isinstance(value, str) and value for value in (owner, job_id, step_id)):
        raise ValueError('Worker execution kimliği eksik.')
    expected = {
        'owner': owner,
        'job_id': job_id,
        'step_id': step_id,
        'command_id': f'{step_id}:{attempt}',
        'attempt': attempt,
        'expected_job_version': expected_job_version,
        'capability_id': row['id'],
        'capability_version': str(row['version']),
        'input_digest': hashlib.sha256(payload.encode('utf-8')).hexdigest(),
    }
    if snapshot is not None and snapshot.get('goal_plan') is not None:
        from modules import goal_plan_gate
        effect = row['id'] in ('task.writer', 'task.coder', 'task.publish', 'task.media', 'task.browser')
        if row['effect_policy'] != 'read_only' and not effect:
            raise ValueError('Unsupported planned effect capability.')
        selection = goal_plan_gate.candidate(
            snapshot, owner=owner, job_id=job_id, node_id=step_id,
        )
        node = goal_plan_gate.revalidate(snapshot, selection)
        # A scheduler offer is a revision-pinned observation. It must not
        # silently execute against a newer plan that happened to reuse its
        # node ID/input; this check runs inside specialist preparation BEFORE
        # the real provider/worker starts, and the resource guard checks again.
        dispatch = identity.get('_canonical_scheduler_offer')
        if effect and dispatch is None:
            raise goal_plan_gate.PlanFenceError(
                'Effect must be dispatched by the exact canonical Scheduler offer.')
        if dispatch is not None and (
                not isinstance(dispatch, dict)
                or set(dispatch) != {'owner', 'job_id', 'node_id', 'plan_version', 'node_digest'}
                or dispatch != {
                    'owner': owner, 'job_id': job_id, 'node_id': step_id,
                    'plan_version': selection.plan_version,
                    'node_digest': selection.node_digest,
                }):
            raise goal_plan_gate.PlanFenceError(
                'Canonical scheduler offer plan changed before worker prepare.'
            )
        if node['depends_on']:
            # Only two developer-approved dependent read-only forms; both
            # re-bind exact, accepted and projected predecessor outputs.
            from modules import dependency_evidence
            if node['capability_id'] == 'task.research':
                goal_plan_gate.validate_dependent_research_attempt(
                    snapshot, selection, attempt=attempt,
                )
                dependency_evidence.require_persisted_research_dependencies(identity, node)
            elif node['capability_id'] == 'task.account':
                goal_plan_gate.validate_dependent_account_attempt(
                    snapshot, selection, attempt=attempt,
                )
                dependency_evidence.require_persisted_account_dependencies(identity, node)
            elif node['capability_id'] == 'task.verify':
                goal_plan_gate.validate_dependent_verify_attempt(
                    snapshot, selection, attempt=attempt,
                )
                dependency_evidence.require_persisted_verify_dependencies(identity, node)
            elif node['capability_id'] in ('task.writer', 'task.publish'):
                goal_plan_gate.validate_dependent_effect_attempt(
                    snapshot, selection, attempt=attempt,
                )
                dependency_evidence.require_persisted_effect_dependencies(identity, node)
            else:
                raise goal_plan_gate.PlanFenceError('Dependent worker not supported.')
        if node['capability_id'] != row['id'] or node['input'] != data:
            raise ValueError('Worker capability/input canonical plan node ile eşleşmiyor.')
        # Read canonical acceptance evidence BEFORE invoking the real worker.
        # The same old plan root may be retried only with a later failed
        # attempt; success, stale user intent and malformed proof fail closed.
        if reconcile_existing is not True and not node['depends_on']:
            goal_plan_gate.validate_root_attempt(
                snapshot, selection, attempt=attempt,
            )
        # Reconciliation never launches a worker. Its caller MUST still find
        # an already accepted exact execution fence before committing any
        # planned observation; worker_result_commit enforces idempotency.
        expected.update({
            'command_id': f"{step_id}:{attempt}:p{selection.plan_version}",
            'plan_version': selection.plan_version,
            'node_digest': selection.node_digest,
        })
        if effect:
            from modules import scheduler_resource_gate
            scheduler_resource_gate.require_effect_result_lease(expected)
    enriched = copy.deepcopy(identity)
    enriched.update(expected)
    return enriched, expected


def _accepted_and_clean(output: dict, expected: dict):
    if not isinstance(output, dict):
        raise ValueError('Worker çıktısı sözlük olmalı.')
    envelope = output.get('_worker_result')
    if not isinstance(envelope, dict):
        raise ValueError('WorkerResult fence kaydı eksik.')
    accepted = worker_result.accept(envelope, expected)
    clean = copy.deepcopy(output)
    clean.pop('_worker_result', None)
    return accepted, clean


def accept_output(output: dict, expected: dict) -> dict:
    """Validate one WorkerResult fence without mutating GoalState."""
    _accepted, clean = _accepted_and_clean(output, expected)
    return clean


def accept_and_commit(output: dict, expected: dict) -> dict:
    """Validate the exact fence, persist reducer evidence, then return clean output."""
    accepted, clean = _accepted_and_clean(output, expected)
    from modules import worker_result_commit
    worker_result_commit.commit(accepted)
    return clean


def _capability(kind: str) -> dict:
    """Use the read-only manifest projection; never introduce a runtime catalog."""
    try:
        return capability_manifest.from_task_tool(kind)
    except ValueError:
        return capability_manifest.from_goal_tool(kind)
