"""BRAIN-07: fail-closed ready-node offers for the ONE engine Scheduler.

Offers are read-only snapshots, NOT execution authority. Existing Core,
DecisionAuthority, ResourceLease, specialist and permission gates still own
dispatch. In particular this module never calls a worker, issues an approval,
updates GoalState/ExecutionRecord, or installs a capability.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from modules import (
    dependency_evidence, execution_record, goal_job_control, goal_plan_gate,
    goal_state, goal_state_store,
)


class DispatchFenceError(ValueError):
    """A scheduled candidate cannot be offered without exact durable proof."""


@dataclass(frozen=True)
class ReadyOffer:
    selection: goal_plan_gate.NodeCandidate
    record_digest: str
    attempt: int = 1


_SUPPORTED = frozenset({'task.research', 'task.account', 'task.verify'})
_MAX_CANDIDATES = 8


def _load(owner: str, job_id: str) -> tuple[dict, dict]:
    from modules import goal_executor

    # Names and filesystem identity are the canonical executor's existing
    # validated owner/job namespace, not arbitrary model-supplied paths.
    root = goal_executor._owner_root(owner)
    if not root.is_dir():
        raise DispatchFenceError('Owner execution directory is unavailable.')
    path = execution_record.path_for(root, job_id)
    state_path = root / (job_id + '.goalstate.json')
    if (path.is_symlink() or not path.is_file()
            or state_path.is_symlink() or not state_path.is_file()):
        raise DispatchFenceError('Exact canonical and ExecutionRecord files required.')
    # Scheduler discovery must not open the ExecutionRecord while another
    # worker atomically replaces it. On Windows, a concurrent reader can
    # reject os.replace with PermissionError *after* Core accepted the
    # WorkerResult, leaving an accepted-but-unprojected attempt. The existing
    # short OS job lock already protects writers; share it for BOTH snapshots.
    # This is reentrant for the already-locked pre-dispatch revalidation path.
    with goal_job_control.locked(root, job_id):
        state = goal_state_store.load(state_path)
        if ((state['owner'], state['job_id']) != (owner, job_id)
                or goal_state.authority(state) != 'canonical'
                or state['state'] not in ('pending', 'running')):
            raise DispatchFenceError('The canonical goal is not schedulable.')
        record = execution_record.load(root, owner, job_id)
        if (record.get('state') != 'running'
                or not isinstance(record.get('request'), str)
                or not record['request'].strip()
                # GoalState.new trims only outer whitespace; internal request
                # bytes must remain bound to the Core-accepted goal. The model
                # or an altered journal cannot substitute a different task.
                or record['request'].strip() != state['goal']
                or not isinstance(record.get('steps'), list)
                or not isinstance(record.get('outputs'), dict)):
            raise DispatchFenceError('ExecutionRecord is not a running goal journal.')
        return state, record


def ready_offers(owner: str, job_id: str, *, limit: int = 3) -> tuple[ReadyOffer, ...]:
    """Offer bounded, first-attempt read-only canonical steps.

    A missing or changed projected predecessor output blocks only its child;
    it never makes that child runnable. No retry is silently authorized and
    no effectful tool or unknown manifest is considered.
    """
    if type(limit) is not int or not 1 <= limit <= _MAX_CANDIDATES:
        raise DispatchFenceError('Candidate limit must be between 1 and 8.')
    state, record = _load(owner, job_id)
    available = goal_plan_gate.ready_read_only_candidates(
        state, owner=owner, job_id=job_id,
    )
    published = record['steps']
    digest = goal_job_control.fingerprint(record)
    offers = []

    for candidate in available:
        if candidate.capability_id not in _SUPPORTED:
            continue
        node = goal_plan_gate.revalidate(state, candidate)
        # At most one published step may represent this canonical node.
        matches = [
            step for step in published
            if isinstance(step, dict) and step.get('id') == candidate.node_id
        ]
        if len(matches) != 1:
            raise DispatchFenceError('Canonical node has no unique published step.')
        step = matches[0]
        if (step.get('tool') != candidate.capability_id.removeprefix('task.')
                or step.get('input') != node['input']
                or step.get('depends') != node['depends_on']):
            raise DispatchFenceError('Published step differs from canonical GoalPlan.')

        if (step.get('state') != 'queued'
                or step.get('attempts', 0) != 0
                or step.get('started') not in (None, False)
                or candidate.node_id in record['outputs']):
            # Never revive a previous attempt or an already projected output.
            continue
        if node['depends_on']:
            if candidate.capability_id not in ('task.research', 'task.account', 'task.verify'):
                continue
            identity = {
                'version': 1, 'owner': owner, 'job_id': job_id,
                'task_id': candidate.node_id, 'attempt': 1,
                'request': record['request'],
            }
            try:
                verified = dependency_evidence.preflight_durable_step(
                    identity, step, record['outputs'],
                    owner=owner, job_id=job_id, canonical_required=True,
                )
            except (ValueError, PermissionError, OSError, TypeError):
                # E.g. accepted parent but missing immutable output projection,
                # unavailable domain proof, or replaced predecessor journal.
                continue
            if not isinstance(verified, dict) or set(verified) != set(node['depends_on']):
                continue
        else:
            goal_plan_gate.validate_root_attempt(state, candidate, attempt=1)
        offers.append(ReadyOffer(candidate, digest))
        if len(offers) >= limit:
            break
    return tuple(offers)


def revalidate_offer(offer: ReadyOffer) -> ReadyOffer:
    """Recheck both snapshots immediately before the future worker admission.

    Success is still only a *candidate*. The actual executor MUST check the
    live owner-bound runtime, DecisionAuthority, approval, resource lease and
    Core fences; it must not treat this method as authorization.
    """
    if not isinstance(offer, ReadyOffer) or offer.attempt != 1:
        raise DispatchFenceError('Unrecognized dispatch offer.')
    selection = offer.selection
    if not isinstance(selection, goal_plan_gate.NodeCandidate):
        raise DispatchFenceError('Unrecognized canonical candidate.')
    try:
        current = ready_offers(selection.owner, selection.job_id, limit=8)
    except (ValueError, PermissionError, OSError, TypeError) as exc:
        raise DispatchFenceError('Dispatch snapshot is no longer valid.') from exc
    if offer not in current:
        raise DispatchFenceError('GoalPlan, worker readiness or journal changed.')
    return offer
