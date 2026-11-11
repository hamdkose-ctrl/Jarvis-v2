"""BRAIN-07: evidence-only certificate for a fully projected canonical DAG.

This is not a global Goal completion decision, lifecycle transition or an
approval. An all-green DAG can still fail the user's semantic acceptance gate.
Never start/retry a worker or synthesize missing post-CAS output bytes here.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from modules import (
    canonical_output_projection, dependency_evidence, execution_record,
    goal_job_control, goal_plan_gate, goal_state, goal_state_store,
)


class PlanEvidenceError(ValueError):
    """The current durable plan is not wholly proven or has become stale."""


@dataclass(frozen=True)
class ProjectedPlanProof:
    owner: str
    job_id: str
    plan_version: int
    goal_version: int
    record_digest: str
    output_digests: tuple[tuple[str, str], ...]


def certify_projected_plan(owner: str, job_id: str) -> ProjectedPlanProof:
    """Verify that EVERY current read-only DAG node was accepted and projected.

    Exact Core audit/WorkerResult, manifest, plan input/digest and immutable
    clean journal bytes are required for every planned node. Re-run the
    existing domain verifiers outside the short per-job file lock and finally
    recheck both durable snapshots. The result is *evidence*, never authority
    to move canonical GoalState to 'done'.
    """
    from modules import goal_executor, goal_tools

    root = goal_executor._owner_root(owner)
    if not root.is_dir():
        raise PlanEvidenceError('Canonical owner store is unavailable.')
    path = execution_record.path_for(root, job_id)
    state_path = root / (job_id + '.goalstate.json')
    if (path.is_symlink() or not path.is_file()
            or state_path.is_symlink() or not state_path.is_file()):
        raise PlanEvidenceError('Both durable canonical journals are required.')

    with goal_job_control.locked(root, job_id):
        state = goal_state_store.load(state_path)
        record = execution_record.load(root, owner, job_id)
        if ((state['owner'], state['job_id']) != (owner, job_id)
                or goal_state.authority(state) != 'canonical'
                or state['state'] not in ('pending', 'running')
                or record.get('state') != 'running'):
            raise PlanEvidenceError('Only a current running canonical job is eligible.')
        plan = state.get('goal_plan')
        if not isinstance(plan, dict):
            raise PlanEvidenceError('Current canonical GoalPlan required.')

        # This existing gate checks current-plan audit parity, exact owner /
        # manifest / digest and that no subsequent user intent mutation
        # invalidated the plan. An untrusted output alone cannot satisfy it.
        try:
            ready = goal_plan_gate.ready_read_only_candidates(
                state, owner=owner, job_id=job_id,
            )
        except goal_plan_gate.PlanFenceError as exc:
            raise PlanEvidenceError('Canonical plan evidence fence invalid.') from exc
        if ready:
            raise PlanEvidenceError('Not every planned node has accepted evidence.')

        steps = record.get('steps')
        outputs = record.get('outputs')
        if (not isinstance(steps, list) or not isinstance(outputs, dict)
                or len(steps) != len(plan['nodes'])
                or set(outputs) != {node['id'] for node in plan['nodes']}):
            raise PlanEvidenceError('Every planned node needs one projected output.')

        snapshots = []
        for node in plan['nodes']:
            ident = node['id']
            matches = [
                step for step in steps
                if isinstance(step, dict) and step.get('id') == ident
            ]
            if len(matches) != 1:
                raise PlanEvidenceError('ExecutionRecord node is not unique.')
            step = matches[0]
            output = outputs[ident]
            if (step.get('state') != 'done'
                    or step.get('tool') != node['capability_id'].removeprefix('task.')
                    or step.get('input') != node['input']
                    or step.get('depends') != node['depends_on']
                    or not isinstance(output, dict)
                    or '_worker_result' in output):
                raise PlanEvidenceError('Projected node differs from canonical plan.')
            try:
                canonical_output_projection._accepted_row(
                    state, owner, job_id, node, output,
                )
                digest = dependency_evidence.output_sha256(output)
            except (ValueError, TypeError, OverflowError) as exc:
                raise PlanEvidenceError(
                    'Projected output has no exact accepted Core commitment.'
                ) from exc
            snapshots.append((ident, copy.deepcopy(output), digest))

        goal_version = state['version']
        record_digest = goal_job_control.fingerprint(record)
        plan_version = plan['plan_version']

    # A domain check may read external receipts/files. Do not hold a Core
    # job lock across that potentially blocking validation.
    for _step, output, _digest in snapshots:
        try:
            verified = goal_tools.verify(output, owner)
        except (ValueError, PermissionError, OSError, TypeError, KeyError) as exc:
            raise PlanEvidenceError('Projected domain proof is no longer valid.') from exc
        if verified is not True:
            raise PlanEvidenceError('Projected domain proof was not confirmed.')

    # No unowned race or stale handoff after slow verification. Even a
    # legitimate user correction or a new accepted worker invalidates proof.
    with goal_job_control.locked(root, job_id):
        fresh = goal_state_store.load(state_path)
        current = execution_record.load(root, owner, job_id)
        if (fresh['version'] != goal_version
                or fresh['state'] != state['state']
                or goal_job_control.fingerprint(current) != record_digest):
            raise PlanEvidenceError('Canonical plan changed during verification.')

    return ProjectedPlanProof(
        owner=owner, job_id=job_id, plan_version=plan_version,
        goal_version=goal_version, record_digest=record_digest,
        output_digests=tuple((ident, digest) for ident, _, digest in snapshots),
    )
