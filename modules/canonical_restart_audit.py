"""BRAIN-07: read-only restart triage for canonical planned worker attempts.

An OS lock released after a crash cannot tell us whether a provider acted,
or whether Core accepted evidence before a crash. Classify exact *durable*
records without mutating state, replaying tools or trusting a worker's "done".
This is an operator/recovery input, never an automatic admission authority.
"""
from __future__ import annotations

from dataclasses import dataclass

from modules import (
    canonical_output_projection, execution_record, goal_job_control,
    goal_plan_gate, goal_state, goal_state_store,
)


class RestartAuditError(ValueError):
    """Current canonical evidence and ExecutionRecord cannot be trusted."""


@dataclass(frozen=True)
class NodeRecovery:
    node_id: str
    status: str


@dataclass(frozen=True)
class RestartSnapshot:
    owner: str
    job_id: str
    goal_version: int
    plan_version: int
    record_digest: str
    nodes: tuple[NodeRecovery, ...]


def inspect(owner: str, job_id: str) -> RestartSnapshot:
    """Read and classify an active canonical DAG under its existing job lock.

    Statuses:
    - queued_unstarted: no recorded worker launch (still needs Scheduler gates)
    - started_unknown: a started attempt lacks accepted/projection evidence
    - accepted_unprojected: Core has success but clean output bytes are absent
    - accepted_projected: clean output is exactly bound to Core acceptance
    - failed_unaccepted: journal failed but there is no Core successful result
    - failed_accepted: Core has a failed attempt; no blind retry

    Never deduce that a remote operation did not run merely because the OS lock
    is free. No status automatically restarts or closes a goal.
    """
    from modules import goal_executor

    root = goal_executor._owner_root(owner)
    if not root.is_dir() or root.is_symlink():
        raise RestartAuditError('Owner root is not a durable directory.')
    record_path = execution_record.path_for(root, job_id)
    state_path = root / (job_id + '.goalstate.json')
    if (record_path.is_symlink() or not record_path.is_file()
            or state_path.is_symlink() or not state_path.is_file()):
        raise RestartAuditError('Both canonical and execution records required.')

    with goal_job_control.locked(root, job_id):
        state = goal_state_store.load(state_path)
        journal = execution_record.load(root, owner, job_id)
        if ((state['owner'], state['job_id']) != (owner, job_id)
                or goal_state.authority(state) != 'canonical'
                or state['state'] not in ('pending', 'running')
                or journal.get('state') != 'running'
                or not isinstance(journal.get('request'), str)
                # Do not certify evidence for a journal whose prompt no
                # longer belongs to the Core goal that authorized its plan.
                or journal['request'].strip() != state['goal']):
            raise RestartAuditError('Only active canonical goals are inspected.')
        plan = state.get('goal_plan')
        if not isinstance(plan, dict):
            raise RestartAuditError('Canonical GoalPlan absent.')
        try:
            # This checks audit/evidence parity, accepted command identity,
            # plan digests, capability version and stale user intent.
            goal_plan_gate.ready_read_only_candidates(
                state, owner=owner, job_id=job_id,
            )
        except goal_plan_gate.PlanFenceError as exc:
            raise RestartAuditError('Current-plan Core evidence is invalid.') from exc

        steps = journal.get('steps')
        outputs = journal.get('outputs')
        if not isinstance(steps, list) or not isinstance(outputs, dict):
            raise RestartAuditError('ExecutionRecord node payload invalid.')
        identities = [step.get('id') if isinstance(step, dict) else None
                      for step in steps]
        expected = {node['id'] for node in plan['nodes']}
        if (len(steps) != len(plan['nodes']) or len(set(identities)) != len(steps)
                or set(identities) != expected or set(outputs) - expected):
            raise RestartAuditError('ExecutionRecord and current plan nodes differ.')

        statuses = []
        for node in plan['nodes']:
            ident = node['id']
            step = next(item for item in steps if item['id'] == ident)
            if (step.get('tool') != node['capability_id'].removeprefix('task.')
                    or step.get('input') != node['input']
                    or step.get('depends') != node['depends_on']):
                raise RestartAuditError('Published step differs from active GoalPlan.')

            accepted = [
                row for row in state['evidence']
                if isinstance(row, dict)
                and row.get('kind') == 'worker_result'
                and row.get('owner') == owner and row.get('job_id') == job_id
                and row.get('step_id') == ident
                and row.get('plan_version') == plan['plan_version']
            ]
            successes = [row for row in accepted if row.get('status') == 'succeeded']
            output = outputs.get(ident)
            has_output = ident in outputs
            step_state = step.get('state')
            attempts = step.get('attempts', 0)
            started = step.get('started', False)

            if successes:
                if len(successes) != 1:
                    raise RestartAuditError('Repeated successful Core evidence.')
                if has_output:
                    if (step_state != 'done' or attempts != 1 or started is not True
                            or not isinstance(output, dict)):
                        raise RestartAuditError('Accepted output is not a completed step.')
                    try:
                        canonical_output_projection._accepted_row(
                            state, owner, job_id, node, output,
                        )
                    except (ValueError, TypeError, OverflowError) as exc:
                        raise RestartAuditError('Projected output fails Core proof.') from exc
                    code = 'accepted_projected'
                elif step_state == 'running' and attempts == 1 and started is True:
                    code = 'accepted_unprojected'
                else:
                    raise RestartAuditError('Accepted success has an invalid journal state.')
            elif accepted:
                # Failed attempts may not automatically be retried, even if
                # the journal lacks an exact output at the time of a crash.
                if step_state not in ('running', 'failed') or attempts != 1 or started is not True:
                    raise RestartAuditError('Failed Core attempt has no durable launch.')
                if has_output and (
                        step_state != 'failed' or not isinstance(output, dict)
                        or output.get('state') != 'failed'):
                    raise RestartAuditError('Failed Core attempt has invalid journal output.')
                code = 'failed_accepted'
            elif (step_state == 'approval' and attempts == 0
                  and started in (None, False) and not has_output
                  and ident == journal.get('waiting')
                  and node['capability_id'] in ('task.coder','task.publish','task.browser','task.writer')):
                from modules import goal_approval
                try:
                    goal_approval.verify_canonical(journal, step, pending=True)
                except (ValueError, PermissionError, TypeError, KeyError) as exc:
                    raise RestartAuditError('Pending approval evidence invalid.') from exc
                code = 'approval_pending'
            elif (step_state == 'approval' and attempts == 1
                  and started is True and not has_output
                  and ident == journal.get('waiting')
                  and node['capability_id'] == 'task.desktop'
                  and isinstance(step.get('_canonical_desktop_id'), str)
                  and step['_canonical_desktop_id']):
                # A paused desktop engine round keeps its bound Core approval
                # card; the native job itself is re-verified before any resume.
                from modules import goal_approval
                try:
                    goal_approval.verify_canonical(journal, step, pending=True)
                except (ValueError, PermissionError, TypeError, KeyError) as exc:
                    raise RestartAuditError('Pending approval evidence invalid.') from exc
                code = 'approval_pending'
            elif (step_state == 'queued' and attempts == 0
                  and started in (None, False) and not has_output):
                code = 'queued_unstarted'
            elif (step_state == 'running' and attempts == 1
                  and started is True and not has_output):
                code = 'started_unknown'
            elif (step_state == 'failed' and attempts == 1
                  and started is True and has_output
                  and isinstance(output, dict) and output.get('state') == 'failed'):
                code = 'failed_unaccepted'
            else:
                raise RestartAuditError('Unproven or contradictory canonical step.')
            statuses.append(NodeRecovery(ident, code))

        return RestartSnapshot(
            owner=owner, job_id=job_id, goal_version=state['version'],
            plan_version=plan['plan_version'],
            record_digest=goal_job_control.fingerprint(journal),
            nodes=tuple(statuses),
        )
